"""M5-IU8 CA-01 typed resource-lock authority.

This module freezes auditable lock identity, exact acquisition replay,
typed acquire/release outcomes, and no-silent-steal semantics.

It does not resolve domain resource refs, coordinate multi-lock sets,
bind session execution locks, reclaim stale locks, or perform crash recovery.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol


def _require_non_blank(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


class ResourceLockAcquireStatus(str, Enum):
    ACQUIRED = "ACQUIRED"
    ALREADY_ACQUIRED = "ALREADY_ACQUIRED"
    BUSY = "BUSY"
    UNKNOWN = "UNKNOWN"


class ResourceLockReleaseStatus(str, Enum):
    RELEASED = "RELEASED"
    ALREADY_RELEASED = "ALREADY_RELEASED"
    NOT_OWNER = "NOT_OWNER"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ResourceLockOwner:
    owner_id: str
    execution_id: str
    step_execution_id: str | None = None
    tool_call_id: str | None = None
    physical_attempt: int | None = None

    def __post_init__(self) -> None:
        _require_non_blank(self.owner_id, "owner_id")
        _require_non_blank(self.execution_id, "execution_id")
        if self.step_execution_id is not None:
            _require_non_blank(self.step_execution_id, "step_execution_id")
        if self.tool_call_id is not None:
            _require_non_blank(self.tool_call_id, "tool_call_id")
        if self.physical_attempt is not None and self.physical_attempt < 1:
            raise ValueError("physical_attempt must be >= 1")

        has_tool = self.tool_call_id is not None
        has_attempt = self.physical_attempt is not None
        if has_tool != has_attempt:
            raise ValueError(
                "tool_call_id and physical_attempt must be present together"
            )
        if has_tool and self.step_execution_id is None:
            raise ValueError("Tool lock owner requires step_execution_id")


@dataclass(frozen=True, slots=True)
class ResourceLockAcquireRequest:
    lock_key: str
    owner: ResourceLockOwner
    acquisition_id: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_non_blank(self.lock_key, "lock_key")
        _require_non_blank(self.acquisition_id, "acquisition_id")
        _require_aware(self.requested_at, "requested_at")


@dataclass(frozen=True, slots=True)
class ResourceLockLease:
    lock_key: str
    owner: ResourceLockOwner
    acquisition_id: str
    acquired_at: datetime

    def __post_init__(self) -> None:
        _require_non_blank(self.lock_key, "lock_key")
        _require_non_blank(self.acquisition_id, "acquisition_id")
        _require_aware(self.acquired_at, "acquired_at")


@dataclass(frozen=True, slots=True)
class ResourceLockAcquireDecision:
    status: ResourceLockAcquireStatus
    reason_codes: tuple[str, ...]
    lease: ResourceLockLease | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ResourceLockAcquireStatus):
            raise TypeError("status must be ResourceLockAcquireStatus")
        if not self.reason_codes or any(
            not isinstance(code, str) or not code.strip() for code in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        if self.status in {
            ResourceLockAcquireStatus.ACQUIRED,
            ResourceLockAcquireStatus.ALREADY_ACQUIRED,
        }:
            if self.lease is None:
                raise ValueError("successful acquire decision requires lease")
        elif self.lease is not None:
            raise ValueError("BUSY/UNKNOWN acquire decision must not expose lease")


@dataclass(frozen=True, slots=True)
class ResourceLockReleaseDecision:
    status: ResourceLockReleaseStatus
    reason_codes: tuple[str, ...]
    lease: ResourceLockLease

    def __post_init__(self) -> None:
        if not isinstance(self.status, ResourceLockReleaseStatus):
            raise TypeError("status must be ResourceLockReleaseStatus")
        if not self.reason_codes or any(
            not isinstance(code, str) or not code.strip() for code in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")


class ResourceLockAuthority(Protocol):
    async def acquire(
        self,
        request: ResourceLockAcquireRequest,
    ) -> ResourceLockAcquireDecision:
        """Acquire an exact lock acquisition without stealing another lease."""

    async def release(
        self,
        lease: ResourceLockLease,
        *,
        released_at: datetime,
    ) -> ResourceLockReleaseDecision:
        """Release only the exact lease represented by acquisition identity."""


class InMemoryResourceLockAuthority:
    """Live in-memory typed lock authority for IU8.

    This implementation intentionally has no lease expiry, stale-owner reclaim,
    cross-process fencing, or crash recovery. Those belong to IU9.
    """

    def __init__(self) -> None:
        self._active_by_key: dict[str, ResourceLockLease] = {}
        self._released_by_acquisition: dict[str, ResourceLockLease] = {}
        self._acquisition_index: dict[str, ResourceLockLease] = {}

    async def acquire(
        self,
        request: ResourceLockAcquireRequest,
    ) -> ResourceLockAcquireDecision:
        existing_by_acquisition = self._acquisition_index.get(request.acquisition_id)
        if existing_by_acquisition is not None:
            if (
                existing_by_acquisition.lock_key == request.lock_key
                and existing_by_acquisition.owner == request.owner
            ):
                active = self._active_by_key.get(request.lock_key)
                if active == existing_by_acquisition:
                    return ResourceLockAcquireDecision(
                        status=ResourceLockAcquireStatus.ALREADY_ACQUIRED,
                        reason_codes=("LOCK_EXACT_ACQUIRE_REPLAY",),
                        lease=existing_by_acquisition,
                    )
                return ResourceLockAcquireDecision(
                    status=ResourceLockAcquireStatus.UNKNOWN,
                    reason_codes=("LOCK_ACQUISITION_REPLAY_NOT_ACTIVE",),
                )
            return ResourceLockAcquireDecision(
                status=ResourceLockAcquireStatus.UNKNOWN,
                reason_codes=("LOCK_ACQUISITION_IDENTITY_CONFLICT",),
            )

        active = self._active_by_key.get(request.lock_key)
        if active is not None:
            return ResourceLockAcquireDecision(
                status=ResourceLockAcquireStatus.BUSY,
                reason_codes=("LOCK_HELD_BY_ANOTHER_ACQUISITION",),
            )

        lease = ResourceLockLease(
            lock_key=request.lock_key,
            owner=request.owner,
            acquisition_id=request.acquisition_id,
            acquired_at=request.requested_at,
        )
        self._active_by_key[request.lock_key] = lease
        self._acquisition_index[request.acquisition_id] = lease
        return ResourceLockAcquireDecision(
            status=ResourceLockAcquireStatus.ACQUIRED,
            reason_codes=("LOCK_ACQUIRED",),
            lease=lease,
        )

    async def release(
        self,
        lease: ResourceLockLease,
        *,
        released_at: datetime,
    ) -> ResourceLockReleaseDecision:
        _require_aware(released_at, "released_at")
        if released_at < lease.acquired_at:
            raise ValueError("released_at cannot precede acquired_at")

        released = self._released_by_acquisition.get(lease.acquisition_id)
        if released is not None:
            if released == lease:
                return ResourceLockReleaseDecision(
                    status=ResourceLockReleaseStatus.ALREADY_RELEASED,
                    reason_codes=("LOCK_EXACT_RELEASE_REPLAY",),
                    lease=lease,
                )
            return ResourceLockReleaseDecision(
                status=ResourceLockReleaseStatus.NOT_OWNER,
                reason_codes=("LOCK_RELEASE_IDENTITY_CONFLICT",),
                lease=lease,
            )

        indexed = self._acquisition_index.get(lease.acquisition_id)
        if indexed is None or indexed != lease:
            return ResourceLockReleaseDecision(
                status=ResourceLockReleaseStatus.NOT_OWNER,
                reason_codes=("LOCK_RELEASE_ACQUISITION_NOT_OWNED",),
                lease=lease,
            )

        active = self._active_by_key.get(lease.lock_key)
        if active != lease:
            return ResourceLockReleaseDecision(
                status=ResourceLockReleaseStatus.NOT_OWNER,
                reason_codes=("LOCK_RELEASE_ACTIVE_LEASE_MISMATCH",),
                lease=lease,
            )

        del self._active_by_key[lease.lock_key]
        self._released_by_acquisition[lease.acquisition_id] = lease
        return ResourceLockReleaseDecision(
            status=ResourceLockReleaseStatus.RELEASED,
            reason_codes=("LOCK_RELEASED",),
            lease=lease,
        )

    def active_lease(self, lock_key: str) -> ResourceLockLease | None:
        _require_non_blank(lock_key, "lock_key")
        return self._active_by_key.get(lock_key)
