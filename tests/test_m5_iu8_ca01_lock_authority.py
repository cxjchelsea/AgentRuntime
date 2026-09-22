"""CA-M5-IU8-01 lock identity and typed acquire/release authority gates."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from runtime.execution.resource_lock import (
    InMemoryResourceLockAuthority,
    ResourceLockAcquireDecision,
    ResourceLockAcquireRequest,
    ResourceLockAcquireStatus,
    ResourceLockLease,
    ResourceLockOwner,
    ResourceLockReleaseDecision,
    ResourceLockReleaseStatus,
)

NOW = datetime(2026, 9, 22, 16, 30, tzinfo=UTC)


def _owner(
    *,
    owner_id: str = "execution-001:step-exec-001:tool-call-001:attempt-1",
    execution_id: str = "execution-001",
    step_execution_id: str = "step-exec-001",
    tool_call_id: str = "tool-call-001",
    physical_attempt: int = 1,
) -> ResourceLockOwner:
    return ResourceLockOwner(
        owner_id=owner_id,
        execution_id=execution_id,
        step_execution_id=step_execution_id,
        tool_call_id=tool_call_id,
        physical_attempt=physical_attempt,
    )


def _request(
    *,
    lock_key: str = "opaque-lock-001",
    acquisition_id: str = "acq-001",
    owner: ResourceLockOwner | None = None,
) -> ResourceLockAcquireRequest:
    return ResourceLockAcquireRequest(
        lock_key=lock_key,
        owner=owner or _owner(),
        acquisition_id=acquisition_id,
        requested_at=NOW,
    )


def test_exact_acquire_returns_auditable_lease() -> None:
    authority = InMemoryResourceLockAuthority()
    request = _request()

    decision = asyncio.run(authority.acquire(request))

    assert decision.status is ResourceLockAcquireStatus.ACQUIRED
    assert decision.lease is not None
    assert decision.lease.lock_key == request.lock_key
    assert decision.lease.owner == request.owner
    assert decision.lease.acquisition_id == request.acquisition_id
    assert decision.lease.acquired_at == NOW
    assert authority.active_lease(request.lock_key) == decision.lease


def test_exact_acquire_replay_is_idempotent() -> None:
    authority = InMemoryResourceLockAuthority()
    request = _request()
    first = asyncio.run(authority.acquire(request))

    replay = asyncio.run(authority.acquire(request))

    assert first.lease is not None
    assert replay.status is ResourceLockAcquireStatus.ALREADY_ACQUIRED
    assert replay.lease is first.lease


def test_same_owner_different_acquisition_is_busy_not_replay() -> None:
    authority = InMemoryResourceLockAuthority()
    owner = _owner()
    asyncio.run(authority.acquire(_request(owner=owner)))

    second = asyncio.run(
        authority.acquire(
            _request(
                acquisition_id="acq-002",
                owner=owner,
            )
        )
    )

    assert second.status is ResourceLockAcquireStatus.BUSY
    assert second.lease is None
    assert second.reason_codes == ("LOCK_HELD_BY_ANOTHER_ACQUISITION",)


def test_different_owner_cannot_steal_active_lock() -> None:
    authority = InMemoryResourceLockAuthority()
    first = asyncio.run(authority.acquire(_request()))
    other = _owner(
        owner_id="execution-002:step-exec-002:tool-call-002:attempt-1",
        execution_id="execution-002",
        step_execution_id="step-exec-002",
        tool_call_id="tool-call-002",
    )

    decision = asyncio.run(
        authority.acquire(
            _request(
                acquisition_id="acq-002",
                owner=other,
            )
        )
    )

    assert first.lease is not None
    assert decision.status is ResourceLockAcquireStatus.BUSY
    assert authority.active_lease("opaque-lock-001") is first.lease


def test_acquisition_id_cannot_be_rebound_to_other_lock_or_owner() -> None:
    authority = InMemoryResourceLockAuthority()
    asyncio.run(authority.acquire(_request()))

    other_lock = asyncio.run(
        authority.acquire(
            _request(
                lock_key="opaque-lock-002",
                acquisition_id="acq-001",
            )
        )
    )

    assert other_lock.status is ResourceLockAcquireStatus.UNKNOWN
    assert other_lock.lease is None
    assert other_lock.reason_codes == ("LOCK_ACQUISITION_IDENTITY_CONFLICT",)


def test_release_exact_lease_and_replay_release() -> None:
    authority = InMemoryResourceLockAuthority()
    acquired = asyncio.run(authority.acquire(_request()))
    assert acquired.lease is not None

    released = asyncio.run(
        authority.release(
            acquired.lease,
            released_at=NOW + timedelta(seconds=1),
        )
    )
    replay = asyncio.run(
        authority.release(
            acquired.lease,
            released_at=NOW + timedelta(seconds=2),
        )
    )

    assert released.status is ResourceLockReleaseStatus.RELEASED
    assert replay.status is ResourceLockReleaseStatus.ALREADY_RELEASED
    assert authority.active_lease("opaque-lock-001") is None


def test_wrong_acquisition_cannot_release_active_lock() -> None:
    authority = InMemoryResourceLockAuthority()
    acquired = asyncio.run(authority.acquire(_request()))
    assert acquired.lease is not None
    forged = replace(
        acquired.lease,
        acquisition_id="acq-forged",
    )

    decision = asyncio.run(
        authority.release(
            forged,
            released_at=NOW + timedelta(seconds=1),
        )
    )

    assert decision.status is ResourceLockReleaseStatus.NOT_OWNER
    assert authority.active_lease("opaque-lock-001") is acquired.lease


def test_wrong_owner_cannot_release_active_lock() -> None:
    authority = InMemoryResourceLockAuthority()
    acquired = asyncio.run(authority.acquire(_request()))
    assert acquired.lease is not None
    forged_owner = _owner(
        owner_id="forged-owner",
        execution_id="execution-other",
        step_execution_id="step-exec-other",
        tool_call_id="tool-call-other",
    )
    forged = replace(acquired.lease, owner=forged_owner)

    decision = asyncio.run(
        authority.release(
            forged,
            released_at=NOW + timedelta(seconds=1),
        )
    )

    assert decision.status is ResourceLockReleaseStatus.NOT_OWNER
    assert authority.active_lease("opaque-lock-001") is acquired.lease


def test_released_acquisition_cannot_be_reacquired_as_exact_replay() -> None:
    authority = InMemoryResourceLockAuthority()
    request = _request()
    acquired = asyncio.run(authority.acquire(request))
    assert acquired.lease is not None
    asyncio.run(
        authority.release(
            acquired.lease,
            released_at=NOW + timedelta(seconds=1),
        )
    )

    replay = asyncio.run(authority.acquire(request))

    assert replay.status is ResourceLockAcquireStatus.UNKNOWN
    assert replay.reason_codes == ("LOCK_ACQUISITION_REPLAY_NOT_ACTIVE",)
    assert replay.lease is None


def test_new_acquisition_can_acquire_after_exact_release() -> None:
    authority = InMemoryResourceLockAuthority()
    first = asyncio.run(authority.acquire(_request()))
    assert first.lease is not None
    asyncio.run(
        authority.release(
            first.lease,
            released_at=NOW + timedelta(seconds=1),
        )
    )

    second = asyncio.run(authority.acquire(_request(acquisition_id="acq-002")))

    assert second.status is ResourceLockAcquireStatus.ACQUIRED
    assert second.lease is not None
    assert second.lease.acquisition_id == "acq-002"


def test_tool_owner_requires_complete_physical_attempt_identity() -> None:
    with pytest.raises(ValueError, match="present together"):
        ResourceLockOwner(
            owner_id="owner-001",
            execution_id="execution-001",
            step_execution_id="step-exec-001",
            tool_call_id="tool-call-001",
        )

    with pytest.raises(ValueError, match="step_execution_id"):
        ResourceLockOwner(
            owner_id="owner-001",
            execution_id="execution-001",
            tool_call_id="tool-call-001",
            physical_attempt=1,
        )


def test_acquire_request_requires_timezone_aware_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ResourceLockAcquireRequest(
            lock_key="opaque-lock-001",
            owner=_owner(),
            acquisition_id="acq-001",
            requested_at=datetime(2026, 9, 22, 16, 30),  # noqa: DTZ001
        )


def test_release_time_cannot_precede_acquisition() -> None:
    authority = InMemoryResourceLockAuthority()
    acquired = asyncio.run(authority.acquire(_request()))
    assert acquired.lease is not None

    with pytest.raises(ValueError, match="cannot precede"):
        asyncio.run(
            authority.release(
                acquired.lease,
                released_at=NOW - timedelta(seconds=1),
            )
        )


def test_typed_decisions_reject_invalid_status_or_lease_shape() -> None:
    with pytest.raises(TypeError, match="ResourceLockAcquireStatus"):
        ResourceLockAcquireDecision(
            status=cast(ResourceLockAcquireStatus, "ACQUIRED"),
            reason_codes=("LOCK_ACQUIRED",),
            lease=ResourceLockLease(
                lock_key="opaque-lock-001",
                owner=_owner(),
                acquisition_id="acq-001",
                acquired_at=NOW,
            ),
        )

    with pytest.raises(ValueError, match="must not expose lease"):
        ResourceLockAcquireDecision(
            status=ResourceLockAcquireStatus.BUSY,
            reason_codes=("LOCK_BUSY",),
            lease=ResourceLockLease(
                lock_key="opaque-lock-001",
                owner=_owner(),
                acquisition_id="acq-001",
                acquired_at=NOW,
            ),
        )

    with pytest.raises(TypeError, match="ResourceLockReleaseStatus"):
        ResourceLockReleaseDecision(
            status=cast(ResourceLockReleaseStatus, "RELEASED"),
            reason_codes=("LOCK_RELEASED",),
            lease=ResourceLockLease(
                lock_key="opaque-lock-001",
                owner=_owner(),
                acquisition_id="acq-001",
                acquired_at=NOW,
            ),
        )
