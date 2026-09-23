"""CA-M5-IU8-02 runtime resource projection and multi-lock set gates."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from runtime.contracts.execution import ExecutionContext
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
from runtime.execution.resource_lock_set import (
    ResolvedResourceLock,
    ResourceLockProjectionStatus,
    ResourceLockRequirement,
    ResourceLockResolutionDecision,
    ResourceLockResolutionStatus,
    ResourceLockSetCoordinator,
    ResourceLockSetRequest,
    ResourceLockSetStatus,
    Sha256ResourceLockAcquisitionIdentifierFactory,
    ToolResourceLockProjector,
)
from runtime.registries.definitions import ToolDefinition

NOW = datetime(2026, 9, 23, 8, 30, tzinfo=UTC)


def _context(*, device_id: str | None = "device-001") -> ExecutionContext:
    return ExecutionContext(
        execution_id="execution-001",
        plan_id="plan-001",
        request_id="request-001",
        session_id="session-001",
        identity_scope="subject-001",
        policy_snapshot={"policy": "snapshot"},
        device_id=device_id,
    )


def _owner() -> ResourceLockOwner:
    return ResourceLockOwner(
        owner_id="execution-001:step-exec-001:tool-call-001:attempt-1",
        execution_id="execution-001",
        step_execution_id="step-exec-001",
        tool_call_id="tool-call-001",
        physical_attempt=1,
    )


def _resolved(
    lock_key: str,
    *,
    resource_ref: str | None = None,
) -> ResolvedResourceLock:
    return ResolvedResourceLock(
        resource_ref=resource_ref or f"ref-{lock_key}",
        lock_key=lock_key,
        provenance=("test-resolver:v1",),
    )


class _Clock:
    def __init__(self, current: datetime = NOW + timedelta(seconds=5)) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current


class _Resolver:
    def __init__(
        self,
        mapping: dict[str, str | None],
        *,
        raise_for: set[str] | None = None,
    ) -> None:
        self.mapping = mapping
        self.raise_for = raise_for or set()
        self.calls: list[tuple[str, str | None, str, int]] = []

    async def resolve(
        self,
        *,
        requirement: ResourceLockRequirement,
        execution_context: ExecutionContext,
        tool_call_id: str,
        physical_attempt: int,
    ) -> ResourceLockResolutionDecision:
        self.calls.append(
            (
                requirement.resource_ref,
                execution_context.device_id,
                tool_call_id,
                physical_attempt,
            )
        )
        if requirement.resource_ref in self.raise_for:
            raise RuntimeError("resolver unavailable")
        lock_key = self.mapping[requirement.resource_ref]
        if lock_key is None:
            return ResourceLockResolutionDecision(
                status=ResourceLockResolutionStatus.UNKNOWN,
                reason_codes=("RESOURCE_CONTEXT_UNAVAILABLE",),
            )
        return ResourceLockResolutionDecision(
            status=ResourceLockResolutionStatus.RESOLVED,
            reason_codes=("RESOURCE_LOCK_RESOLVED",),
            resolved_lock=ResolvedResourceLock(
                resource_ref=requirement.resource_ref,
                lock_key=lock_key,
                provenance=(
                    f"device:{execution_context.device_id or 'none'}",
                    "resolver:test-v1",
                ),
            ),
        )


class _RecordingAuthority(InMemoryResourceLockAuthority):
    def __init__(self) -> None:
        super().__init__()
        self.acquire_order: list[str] = []
        self.release_order: list[str] = []

    async def acquire(
        self,
        request: ResourceLockAcquireRequest,
    ) -> ResourceLockAcquireDecision:
        self.acquire_order.append(request.lock_key)
        return await super().acquire(request)

    async def release(
        self,
        lease: ResourceLockLease,
        *,
        released_at: datetime,
    ) -> ResourceLockReleaseDecision:
        self.release_order.append(lease.lock_key)
        return await super().release(lease, released_at=released_at)


class _ScriptedAuthority:
    def __init__(
        self,
        *,
        acquire_by_key: dict[str, ResourceLockAcquireStatus],
        release_by_key: dict[str, ResourceLockReleaseStatus] | None = None,
    ) -> None:
        self.acquire_by_key = acquire_by_key
        self.release_by_key = release_by_key or {}
        self.acquire_order: list[str] = []
        self.release_order: list[str] = []

    async def acquire(
        self,
        request: ResourceLockAcquireRequest,
    ) -> ResourceLockAcquireDecision:
        self.acquire_order.append(request.lock_key)
        status = self.acquire_by_key[request.lock_key]
        if status in {
            ResourceLockAcquireStatus.ACQUIRED,
            ResourceLockAcquireStatus.ALREADY_ACQUIRED,
        }:
            return ResourceLockAcquireDecision(
                status=status,
                reason_codes=(f"LOCK_{status.value}",),
                lease=ResourceLockLease(
                    lock_key=request.lock_key,
                    owner=request.owner,
                    acquisition_id=request.acquisition_id,
                    acquired_at=request.requested_at,
                ),
            )
        return ResourceLockAcquireDecision(
            status=status,
            reason_codes=(f"LOCK_{status.value}",),
        )

    async def release(
        self,
        lease: ResourceLockLease,
        *,
        released_at: datetime,
    ) -> ResourceLockReleaseDecision:
        del released_at
        self.release_order.append(lease.lock_key)
        status = self.release_by_key.get(
            lease.lock_key,
            ResourceLockReleaseStatus.RELEASED,
        )
        return ResourceLockReleaseDecision(
            status=status,
            reason_codes=(f"LOCK_{status.value}",),
            lease=lease,
        )


def _coordinator(
    authority: object,
    *,
    clock: _Clock | None = None,
) -> ResourceLockSetCoordinator:
    return ResourceLockSetCoordinator(
        authority=authority,  # type: ignore[arg-type]
        clock=clock or _Clock(),
        identifier_factory=Sha256ResourceLockAcquisitionIdentifierFactory(),
    )


def _set_request(
    *locks: ResolvedResourceLock,
    lock_set_id: str = "lock-set-001",
) -> ResourceLockSetRequest:
    return ResourceLockSetRequest(
        lock_set_id=lock_set_id,
        owner=_owner(),
        resolved_locks=tuple(locks),
        requested_at=NOW,
    )


def test_projection_uses_injected_runtime_context_resolver() -> None:
    resolver = _Resolver({"speaker": "device-001:speaker"})
    projector = ToolResourceLockProjector(resolver)
    tool = ToolDefinition(
        tool_id="TOOL_A",
        version="1.0.0",
        resource_locks=["speaker"],
    )

    decision = asyncio.run(
        projector.project(
            tool_definition=tool,
            execution_context=_context(),
            tool_call_id="tool-call-001",
            physical_attempt=1,
        )
    )

    assert decision.status is ResourceLockProjectionStatus.RESOLVED
    assert decision.requirements == (
        ResourceLockRequirement(
            resource_ref="speaker",
            tool_id="TOOL_A",
            tool_version="1.0.0",
        ),
    )
    assert decision.resolved_locks[0].lock_key == "device-001:speaker"
    assert resolver.calls == [("speaker", "device-001", "tool-call-001", 1)]


def test_projection_does_not_call_resolver_when_no_locks_declared() -> None:
    resolver = _Resolver({})
    projector = ToolResourceLockProjector(resolver)

    decision = asyncio.run(
        projector.project(
            tool_definition=ToolDefinition(tool_id="TOOL_A", version="1.0.0"),
            execution_context=_context(),
            tool_call_id="tool-call-001",
            physical_attempt=1,
        )
    )

    assert decision.status is ResourceLockProjectionStatus.RESOLVED
    assert decision.requirements == ()
    assert decision.resolved_locks == ()
    assert resolver.calls == []


def test_projection_deduplicates_static_resource_refs() -> None:
    resolver = _Resolver(
        {
            "speaker": "device-001:speaker",
            "playback": "device-001:playback",
        }
    )
    projector = ToolResourceLockProjector(resolver)
    tool = ToolDefinition(
        tool_id="TOOL_A",
        version="1.0.0",
        resource_locks=["speaker", "speaker", "playback"],
    )

    decision = asyncio.run(
        projector.project(
            tool_definition=tool,
            execution_context=_context(),
            tool_call_id="tool-call-001",
            physical_attempt=1,
        )
    )

    assert tuple(item.resource_ref for item in decision.requirements) == (
        "speaker",
        "playback",
    )
    assert len(resolver.calls) == 2


def test_unresolved_resource_fails_closed_without_partial_projection() -> None:
    resolver = _Resolver(
        {
            "speaker": "device-001:speaker",
            "playback": None,
        }
    )
    projector = ToolResourceLockProjector(resolver)
    tool = ToolDefinition(
        tool_id="TOOL_A",
        version="1.0.0",
        resource_locks=["speaker", "playback"],
    )

    decision = asyncio.run(
        projector.project(
            tool_definition=tool,
            execution_context=_context(),
            tool_call_id="tool-call-001",
            physical_attempt=1,
        )
    )

    assert decision.status is ResourceLockProjectionStatus.UNKNOWN
    assert decision.resolved_locks == ()
    assert decision.reason_codes == ("RESOURCE_CONTEXT_UNAVAILABLE",)


def test_resolver_exception_fails_closed() -> None:
    resolver = _Resolver(
        {"speaker": "device-001:speaker"},
        raise_for={"speaker"},
    )
    decision = asyncio.run(
        ToolResourceLockProjector(resolver).project(
            tool_definition=ToolDefinition(
                tool_id="TOOL_A",
                version="1.0.0",
                resource_locks=["speaker"],
            ),
            execution_context=_context(),
            tool_call_id="tool-call-001",
            physical_attempt=1,
        )
    )

    assert decision.status is ResourceLockProjectionStatus.UNKNOWN
    assert decision.resolved_locks == ()
    assert decision.reason_codes == ("RESOURCE_LOCK_RESOLUTION_EXCEPTION",)


def test_lock_set_acquires_in_canonical_key_order() -> None:
    authority = _RecordingAuthority()
    decision = asyncio.run(
        _coordinator(authority).acquire(
            _set_request(
                _resolved("z-lock"),
                _resolved("a-lock"),
                _resolved("m-lock"),
            )
        )
    )

    assert decision.status is ResourceLockSetStatus.ACQUIRED
    assert authority.acquire_order == ["a-lock", "m-lock", "z-lock"]
    assert tuple(lease.lock_key for lease in decision.leases) == (
        "a-lock",
        "m-lock",
        "z-lock",
    )


def test_duplicate_concrete_lock_keys_are_acquired_once() -> None:
    authority = _RecordingAuthority()
    decision = asyncio.run(
        _coordinator(authority).acquire(
            _set_request(
                _resolved("shared", resource_ref="speaker"),
                _resolved("shared", resource_ref="playback"),
            )
        )
    )

    assert decision.status is ResourceLockSetStatus.ACQUIRED
    assert authority.acquire_order == ["shared"]
    assert len(decision.leases) == 1


def test_partial_busy_rolls_back_in_reverse_order() -> None:
    authority = _ScriptedAuthority(
        acquire_by_key={
            "a-lock": ResourceLockAcquireStatus.ACQUIRED,
            "b-lock": ResourceLockAcquireStatus.ACQUIRED,
            "c-lock": ResourceLockAcquireStatus.BUSY,
        }
    )

    decision = asyncio.run(
        _coordinator(authority).acquire(
            _set_request(
                _resolved("c-lock"),
                _resolved("a-lock"),
                _resolved("b-lock"),
            )
        )
    )

    assert decision.status is ResourceLockSetStatus.BUSY
    assert decision.failed_lock_key == "c-lock"
    assert decision.leases == ()
    assert decision.retained_leases == ()
    assert authority.acquire_order == ["a-lock", "b-lock", "c-lock"]
    assert authority.release_order == ["b-lock", "a-lock"]
    assert "LOCK_SET_ROLLBACK_CONFIRMED" in decision.reason_codes


def test_partial_unknown_rolls_back_confirmed_acquisitions() -> None:
    authority = _ScriptedAuthority(
        acquire_by_key={
            "a-lock": ResourceLockAcquireStatus.ACQUIRED,
            "b-lock": ResourceLockAcquireStatus.UNKNOWN,
        }
    )

    decision = asyncio.run(
        _coordinator(authority).acquire(
            _set_request(_resolved("a-lock"), _resolved("b-lock"))
        )
    )

    assert decision.status is ResourceLockSetStatus.UNKNOWN
    assert decision.retained_leases == ()
    assert authority.release_order == ["a-lock"]
    assert "LOCK_SET_ROLLBACK_CONFIRMED" in decision.reason_codes


def test_rollback_unknown_escalates_whole_lock_set_to_unknown() -> None:
    authority = _ScriptedAuthority(
        acquire_by_key={
            "a-lock": ResourceLockAcquireStatus.ACQUIRED,
            "b-lock": ResourceLockAcquireStatus.BUSY,
        },
        release_by_key={
            "a-lock": ResourceLockReleaseStatus.UNKNOWN,
        },
    )

    decision = asyncio.run(
        _coordinator(authority).acquire(
            _set_request(_resolved("a-lock"), _resolved("b-lock"))
        )
    )

    assert decision.status is ResourceLockSetStatus.UNKNOWN
    assert decision.failed_lock_key == "b-lock"
    assert tuple(item.lock_key for item in decision.retained_leases) == ("a-lock",)
    assert "LOCK_SET_ROLLBACK_UNCERTAIN" in decision.reason_codes
    assert "LOCK_ROLLBACK_RELEASE_UNKNOWN" in decision.reason_codes


def test_rollback_not_owner_is_uncertain_not_busy() -> None:
    authority = _ScriptedAuthority(
        acquire_by_key={
            "a-lock": ResourceLockAcquireStatus.ACQUIRED,
            "b-lock": ResourceLockAcquireStatus.BUSY,
        },
        release_by_key={
            "a-lock": ResourceLockReleaseStatus.NOT_OWNER,
        },
    )

    decision = asyncio.run(
        _coordinator(authority).acquire(
            _set_request(_resolved("a-lock"), _resolved("b-lock"))
        )
    )

    assert decision.status is ResourceLockSetStatus.UNKNOWN
    assert tuple(item.lock_key for item in decision.retained_leases) == ("a-lock",)
    assert "LOCK_ROLLBACK_RELEASE_NOT_OWNER" in decision.reason_codes


def test_invalid_rollback_clock_retains_all_acquired_leases() -> None:
    authority = _ScriptedAuthority(
        acquire_by_key={
            "a-lock": ResourceLockAcquireStatus.ACQUIRED,
            "b-lock": ResourceLockAcquireStatus.BUSY,
        }
    )
    clock = _Clock(NOW - timedelta(seconds=1))

    decision = asyncio.run(
        _coordinator(authority, clock=clock).acquire(
            _set_request(_resolved("a-lock"), _resolved("b-lock"))
        )
    )

    assert decision.status is ResourceLockSetStatus.UNKNOWN
    assert tuple(item.lock_key for item in decision.retained_leases) == ("a-lock",)
    assert authority.release_order == []
    assert "LOCK_ROLLBACK_TIME_PRECEDES_ACQUIRE" in decision.reason_codes


def test_exact_lock_set_replay_reuses_deterministic_acquisition_ids() -> None:
    authority = _RecordingAuthority()
    coordinator = _coordinator(authority)
    request = _set_request(_resolved("a-lock"), _resolved("b-lock"))

    first = asyncio.run(coordinator.acquire(request))
    replay = asyncio.run(coordinator.acquire(request))

    assert first.status is ResourceLockSetStatus.ACQUIRED
    assert replay.status is ResourceLockSetStatus.ACQUIRED
    assert tuple(item.acquisition_id for item in first.leases) == tuple(
        item.acquisition_id for item in replay.leases
    )
    assert tuple(item.lock_key for item in replay.leases) == ("a-lock", "b-lock")


def test_same_lock_set_id_and_key_is_stable_independent_of_input_order() -> None:
    factory = Sha256ResourceLockAcquisitionIdentifierFactory()

    first = factory.new_acquisition_id(
        lock_set_id="set-001",
        lock_key="a-lock",
    )
    second = factory.new_acquisition_id(
        lock_set_id="set-001",
        lock_key="a-lock",
    )

    assert first == second
    assert first.startswith("sha256:")


def test_empty_lock_set_is_safe_noop() -> None:
    authority = _RecordingAuthority()

    decision = asyncio.run(
        _coordinator(authority).acquire(_set_request())
    )

    assert decision.status is ResourceLockSetStatus.ACQUIRED
    assert decision.leases == ()
    assert authority.acquire_order == []


def test_successful_acquire_decision_with_wrong_lease_identity_fails_closed() -> None:
    class WrongLeaseAuthority:
        async def acquire(
            self,
            request: ResourceLockAcquireRequest,
        ) -> ResourceLockAcquireDecision:
            return ResourceLockAcquireDecision(
                status=ResourceLockAcquireStatus.ACQUIRED,
                reason_codes=("LOCK_ACQUIRED",),
                lease=ResourceLockLease(
                    lock_key="wrong-lock",
                    owner=request.owner,
                    acquisition_id=request.acquisition_id,
                    acquired_at=request.requested_at,
                ),
            )

        async def release(
            self,
            lease: ResourceLockLease,
            *,
            released_at: datetime,
        ) -> ResourceLockReleaseDecision:
            del released_at
            return ResourceLockReleaseDecision(
                status=ResourceLockReleaseStatus.RELEASED,
                reason_codes=("LOCK_RELEASED",),
                lease=lease,
            )

    decision = asyncio.run(
        _coordinator(WrongLeaseAuthority()).acquire(
            _set_request(_resolved("a-lock"))
        )
    )

    assert decision.status is ResourceLockSetStatus.UNKNOWN
    assert decision.failed_lock_key == "a-lock"
    assert decision.reason_codes == ("LOCK_ACQUIRE_AUTHORITY_INVALID_DECISION",)


def test_projection_contract_rejects_partial_unknown_payload() -> None:
    resolved = _resolved("a-lock", resource_ref="speaker")

    with pytest.raises(ValueError, match="must not expose partial"):
        from runtime.execution.resource_lock_set import ResourceLockProjectionDecision

        ResourceLockProjectionDecision(
            status=ResourceLockProjectionStatus.UNKNOWN,
            reason_codes=("RESOURCE_UNKNOWN",),
            requirements=(
                ResourceLockRequirement(
                    resource_ref="speaker",
                    tool_id="TOOL_A",
                    tool_version="1.0.0",
                ),
            ),
            resolved_locks=(resolved,),
        )


def test_lock_set_request_requires_timezone_aware_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ResourceLockSetRequest(
            lock_set_id="set-001",
            owner=_owner(),
            resolved_locks=(_resolved("a-lock"),),
            requested_at=datetime(2026, 9, 23, 8, 30),  # noqa: DTZ001
        )
