"""M5-IU8 CA-02 runtime resource projection and deterministic lock-set coordination.

This module converts static Tool resource references into opaque concrete runtime
lock identities through an injected resolver, then acquires the resulting lock set
in a canonical order with fail-closed rollback.

It does not own session execution locks, physical-operation lifetime release wiring,
stale-lock reclaim, durable persistence, checkpoint/recovery, aggregation, or M6.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from runtime.contracts.execution import ExecutionContext
from runtime.execution.reliability import ExecutionClock
from runtime.execution.resource_lock import (
    ResourceLockAcquireDecision,
    ResourceLockAcquireRequest,
    ResourceLockAcquireStatus,
    ResourceLockAuthority,
    ResourceLockLease,
    ResourceLockOwner,
    ResourceLockReleaseDecision,
    ResourceLockReleaseStatus,
)
from runtime.registries.definitions import ToolDefinition


def _require_non_blank(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


class ResourceLockResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ResourceLockRequirement:
    resource_ref: str
    tool_id: str
    tool_version: str

    def __post_init__(self) -> None:
        _require_non_blank(self.resource_ref, "resource_ref")
        _require_non_blank(self.tool_id, "tool_id")
        _require_non_blank(self.tool_version, "tool_version")


@dataclass(frozen=True, slots=True)
class ResolvedResourceLock:
    resource_ref: str
    lock_key: str
    provenance: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_non_blank(self.resource_ref, "resource_ref")
        _require_non_blank(self.lock_key, "lock_key")
        if not self.provenance or any(
            not isinstance(item, str) or not item.strip() for item in self.provenance
        ):
            raise ValueError("provenance must contain non-blank values")


@dataclass(frozen=True, slots=True)
class ResourceLockResolutionDecision:
    status: ResourceLockResolutionStatus
    reason_codes: tuple[str, ...]
    resolved_lock: ResolvedResourceLock | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ResourceLockResolutionStatus):
            raise TypeError("status must be ResourceLockResolutionStatus")
        if not self.reason_codes or any(
            not isinstance(code, str) or not code.strip() for code in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        if self.status is ResourceLockResolutionStatus.RESOLVED:
            if self.resolved_lock is None:
                raise ValueError("RESOLVED requires resolved_lock")
        elif self.resolved_lock is not None:
            raise ValueError("UNKNOWN resolution must not expose resolved_lock")


class ResourceLockRequirementResolver(Protocol):
    async def resolve(
        self,
        *,
        requirement: ResourceLockRequirement,
        execution_context: ExecutionContext,
        tool_call_id: str,
        physical_attempt: int,
    ) -> ResourceLockResolutionDecision:
        """Resolve one static resource ref into one opaque runtime lock identity."""


class ResourceLockProjectionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ResourceLockProjectionDecision:
    status: ResourceLockProjectionStatus
    reason_codes: tuple[str, ...]
    requirements: tuple[ResourceLockRequirement, ...] = ()
    resolved_locks: tuple[ResolvedResourceLock, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, ResourceLockProjectionStatus):
            raise TypeError("status must be ResourceLockProjectionStatus")
        if not self.reason_codes or any(
            not isinstance(code, str) or not code.strip() for code in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        if self.status is ResourceLockProjectionStatus.RESOLVED:
            if len(self.requirements) != len(self.resolved_locks):
                raise ValueError(
                    "RESOLVED projection requires one resolved lock per requirement"
                )
            for requirement, resolved in zip(
                self.requirements,
                self.resolved_locks,
                strict=True,
            ):
                if requirement.resource_ref != resolved.resource_ref:
                    raise ValueError(
                        "resolved resource_ref must match projected requirement"
                    )
        elif self.resolved_locks:
            raise ValueError("UNKNOWN projection must not expose partial resolved locks")


class ToolResourceLockProjector:
    """Project ToolDefinition.resource_locks through an injected runtime resolver."""

    def __init__(self, resolver: ResourceLockRequirementResolver) -> None:
        self._resolver = resolver

    async def project(
        self,
        *,
        tool_definition: ToolDefinition,
        execution_context: ExecutionContext,
        tool_call_id: str,
        physical_attempt: int,
    ) -> ResourceLockProjectionDecision:
        _require_non_blank(tool_call_id, "tool_call_id")
        if physical_attempt < 1:
            raise ValueError("physical_attempt must be >= 1")

        raw_refs = tuple(tool_definition.resource_locks or ())
        if not raw_refs:
            return ResourceLockProjectionDecision(
                status=ResourceLockProjectionStatus.RESOLVED,
                reason_codes=("TOOL_RESOURCE_LOCKS_NOT_DECLARED",),
            )
        if any(not isinstance(item, str) or not item.strip() for item in raw_refs):
            return ResourceLockProjectionDecision(
                status=ResourceLockProjectionStatus.UNKNOWN,
                reason_codes=("RESOURCE_LOCK_REFERENCE_INVALID",),
            )

        unique_refs = tuple(dict.fromkeys(raw_refs))
        requirements = tuple(
            ResourceLockRequirement(
                resource_ref=resource_ref,
                tool_id=tool_definition.tool_id,
                tool_version=tool_definition.version,
            )
            for resource_ref in unique_refs
        )

        resolved_locks: list[ResolvedResourceLock] = []
        for requirement in requirements:
            try:
                decision = await self._resolver.resolve(
                    requirement=requirement,
                    execution_context=execution_context,
                    tool_call_id=tool_call_id,
                    physical_attempt=physical_attempt,
                )
            except Exception:  # noqa: BLE001
                return ResourceLockProjectionDecision(
                    status=ResourceLockProjectionStatus.UNKNOWN,
                    reason_codes=("RESOURCE_LOCK_RESOLUTION_EXCEPTION",),
                    requirements=requirements,
                )
            if (
                not isinstance(decision, ResourceLockResolutionDecision)
                or not isinstance(decision.status, ResourceLockResolutionStatus)
            ):
                return ResourceLockProjectionDecision(
                    status=ResourceLockProjectionStatus.UNKNOWN,
                    reason_codes=("RESOURCE_LOCK_RESOLUTION_INVALID_DECISION",),
                    requirements=requirements,
                )
            if decision.status is ResourceLockResolutionStatus.UNKNOWN:
                return ResourceLockProjectionDecision(
                    status=ResourceLockProjectionStatus.UNKNOWN,
                    reason_codes=decision.reason_codes,
                    requirements=requirements,
                )
            resolved = decision.resolved_lock
            if (
                resolved is None
                or resolved.resource_ref != requirement.resource_ref
            ):
                return ResourceLockProjectionDecision(
                    status=ResourceLockProjectionStatus.UNKNOWN,
                    reason_codes=("RESOURCE_LOCK_RESOLUTION_IDENTITY_MISMATCH",),
                    requirements=requirements,
                )
            resolved_locks.append(resolved)

        return ResourceLockProjectionDecision(
            status=ResourceLockProjectionStatus.RESOLVED,
            reason_codes=("RESOURCE_LOCKS_RESOLVED",),
            requirements=requirements,
            resolved_locks=tuple(resolved_locks),
        )


class ResourceLockSetStatus(str, Enum):
    ACQUIRED = "ACQUIRED"
    BUSY = "BUSY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ResourceLockSetRequest:
    lock_set_id: str
    owner: ResourceLockOwner
    resolved_locks: tuple[ResolvedResourceLock, ...]
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_non_blank(self.lock_set_id, "lock_set_id")
        _require_aware(self.requested_at, "requested_at")


@dataclass(frozen=True, slots=True)
class ResourceLockSetDecision:
    status: ResourceLockSetStatus
    reason_codes: tuple[str, ...]
    leases: tuple[ResourceLockLease, ...] = ()
    retained_leases: tuple[ResourceLockLease, ...] = ()
    failed_lock_key: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ResourceLockSetStatus):
            raise TypeError("status must be ResourceLockSetStatus")
        if not self.reason_codes or any(
            not isinstance(code, str) or not code.strip() for code in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        if self.status is ResourceLockSetStatus.ACQUIRED:
            if self.retained_leases or self.failed_lock_key is not None:
                raise ValueError(
                    "ACQUIRED lock set cannot carry retained leases or failed key"
                )
        else:
            if self.leases:
                raise ValueError("non-ACQUIRED lock set must not expose active leases")
            if self.failed_lock_key is None or not self.failed_lock_key.strip():
                raise ValueError("BUSY/UNKNOWN lock set requires failed_lock_key")
            if self.status is ResourceLockSetStatus.BUSY and self.retained_leases:
                raise ValueError("BUSY requires rollback to be fully confirmed")


class ResourceLockAcquisitionIdentifierFactory(Protocol):
    def new_acquisition_id(
        self,
        *,
        lock_set_id: str,
        lock_set_fingerprint: str,
        lock_key: str,
    ) -> str:
        """Return a deterministic acquisition id for exact lock-set replay."""


class Sha256ResourceLockAcquisitionIdentifierFactory:
    """Deterministically bind one lock-set identity to one concrete lock key."""

    def new_acquisition_id(
        self,
        *,
        lock_set_id: str,
        lock_set_fingerprint: str,
        lock_key: str,
    ) -> str:
        _require_non_blank(lock_set_id, "lock_set_id")
        _require_non_blank(lock_set_fingerprint, "lock_set_fingerprint")
        _require_non_blank(lock_key, "lock_key")
        payload = (
            f"iu8-lock-acquisition\0{lock_set_id}\0"
            f"{lock_set_fingerprint}\0{lock_key}"
        ).encode()
        return f"sha256:{hashlib.sha256(payload).hexdigest()}"


class ResourceLockSetCoordinator:
    """Acquire a concrete lock set canonically and rollback partial acquisition."""

    def __init__(
        self,
        *,
        authority: ResourceLockAuthority,
        clock: ExecutionClock,
        identifier_factory: ResourceLockAcquisitionIdentifierFactory,
    ) -> None:
        self._authority = authority
        self._clock = clock
        self._identifier_factory = identifier_factory

    async def acquire(
        self,
        request: ResourceLockSetRequest,
    ) -> ResourceLockSetDecision:
        canonical_locks = self._canonical_locks(request.resolved_locks)
        if not canonical_locks:
            return ResourceLockSetDecision(
                status=ResourceLockSetStatus.ACQUIRED,
                reason_codes=("LOCK_SET_EMPTY",),
            )

        lock_set_fingerprint = self._lock_set_fingerprint(canonical_locks)
        leases: list[ResourceLockLease] = []
        newly_acquired: list[ResourceLockLease] = []
        replayed: list[ResourceLockLease] = []
        for resolved in canonical_locks:
            try:
                acquisition_id = self._identifier_factory.new_acquisition_id(
                    lock_set_id=request.lock_set_id,
                    lock_set_fingerprint=lock_set_fingerprint,
                    lock_key=resolved.lock_key,
                )
            except Exception:  # noqa: BLE001
                return await self._failed_with_rollback(
                    newly_acquired=newly_acquired,
                    replayed=replayed,
                    failed_lock_key=resolved.lock_key,
                    failure_status=ResourceLockSetStatus.UNKNOWN,
                    reason_codes=("LOCK_ACQUISITION_ID_UNAVAILABLE",),
                )
            if not isinstance(acquisition_id, str) or not acquisition_id.strip():
                return await self._failed_with_rollback(
                    newly_acquired=newly_acquired,
                    replayed=replayed,
                    failed_lock_key=resolved.lock_key,
                    failure_status=ResourceLockSetStatus.UNKNOWN,
                    reason_codes=("LOCK_ACQUISITION_ID_UNAVAILABLE",),
                )

            acquire_request = ResourceLockAcquireRequest(
                lock_key=resolved.lock_key,
                owner=request.owner,
                acquisition_id=acquisition_id,
                requested_at=request.requested_at,
            )
            try:
                decision = await self._authority.acquire(acquire_request)
            except Exception:  # noqa: BLE001
                return await self._failed_with_rollback(
                    newly_acquired=newly_acquired,
                    replayed=replayed,
                    failed_lock_key=resolved.lock_key,
                    failure_status=ResourceLockSetStatus.UNKNOWN,
                    reason_codes=("LOCK_ACQUIRE_AUTHORITY_EXCEPTION",),
                )

            if not self._valid_acquire_decision(
                decision=decision,
                request=acquire_request,
            ):
                return await self._failed_with_rollback(
                    newly_acquired=newly_acquired,
                    replayed=replayed,
                    failed_lock_key=resolved.lock_key,
                    failure_status=ResourceLockSetStatus.UNKNOWN,
                    reason_codes=("LOCK_ACQUIRE_AUTHORITY_INVALID_DECISION",),
                )

            if decision.status in {
                ResourceLockAcquireStatus.ACQUIRED,
                ResourceLockAcquireStatus.ALREADY_ACQUIRED,
            }:
                assert decision.lease is not None
                leases.append(decision.lease)
                if decision.status is ResourceLockAcquireStatus.ACQUIRED:
                    newly_acquired.append(decision.lease)
                else:
                    replayed.append(decision.lease)
                continue

            failure_status = (
                ResourceLockSetStatus.BUSY
                if decision.status is ResourceLockAcquireStatus.BUSY
                else ResourceLockSetStatus.UNKNOWN
            )
            return await self._failed_with_rollback(
                newly_acquired=newly_acquired,
                replayed=replayed,
                failed_lock_key=resolved.lock_key,
                failure_status=failure_status,
                reason_codes=decision.reason_codes,
            )

        return ResourceLockSetDecision(
            status=ResourceLockSetStatus.ACQUIRED,
            reason_codes=("LOCK_SET_ACQUIRED",),
            leases=tuple(leases),
        )

    @staticmethod
    def _canonical_locks(
        locks: tuple[ResolvedResourceLock, ...],
    ) -> tuple[ResolvedResourceLock, ...]:
        by_key: dict[str, ResolvedResourceLock] = {}
        for lock in locks:
            by_key.setdefault(lock.lock_key, lock)
        return tuple(by_key[key] for key in sorted(by_key))

    @staticmethod
    def _lock_set_fingerprint(
        locks: tuple[ResolvedResourceLock, ...],
    ) -> str:
        payload = "\0".join(lock.lock_key for lock in locks).encode()
        return f"sha256:{hashlib.sha256(payload).hexdigest()}"

    @staticmethod
    def _valid_acquire_decision(
        *,
        decision: object,
        request: ResourceLockAcquireRequest,
    ) -> bool:
        if (
            not isinstance(decision, ResourceLockAcquireDecision)
            or not isinstance(decision.status, ResourceLockAcquireStatus)
        ):
            return False
        if decision.status in {
            ResourceLockAcquireStatus.ACQUIRED,
            ResourceLockAcquireStatus.ALREADY_ACQUIRED,
        }:
            lease = decision.lease
            return (
                lease is not None
                and lease.lock_key == request.lock_key
                and lease.owner == request.owner
                and lease.acquisition_id == request.acquisition_id
            )
        return decision.lease is None

    async def _failed_with_rollback(
        self,
        *,
        newly_acquired: list[ResourceLockLease],
        replayed: list[ResourceLockLease],
        failed_lock_key: str,
        failure_status: ResourceLockSetStatus,
        reason_codes: tuple[str, ...],
    ) -> ResourceLockSetDecision:
        rollback_retained: tuple[ResourceLockLease, ...] = ()
        rollback_reasons: tuple[str, ...] = ()
        if newly_acquired:
            rollback_retained, rollback_reasons = await self._rollback(
                newly_acquired
            )

        retained = tuple(replayed) + rollback_retained
        if retained:
            replay_reason = (
                ("LOCK_SET_REPLAY_PARTIAL_STATE",) if replayed else ()
            )
            rollback_reason = (
                ("LOCK_SET_ROLLBACK_UNCERTAIN",)
                if rollback_retained
                else ()
            )
            return ResourceLockSetDecision(
                status=ResourceLockSetStatus.UNKNOWN,
                reason_codes=reason_codes
                + replay_reason
                + rollback_reason
                + rollback_reasons,
                retained_leases=retained,
                failed_lock_key=failed_lock_key,
            )

        confirmed_reason = (
            ("LOCK_SET_ROLLBACK_CONFIRMED",) if newly_acquired else ()
        )
        return ResourceLockSetDecision(
            status=failure_status,
            reason_codes=reason_codes + confirmed_reason,
            failed_lock_key=failed_lock_key,
        )

    async def _rollback(
        self,
        acquired: list[ResourceLockLease],
    ) -> tuple[tuple[ResourceLockLease, ...], tuple[str, ...]]:
        try:
            released_at = self._clock.now()
            _require_aware(released_at, "rollback released_at")
        except Exception:  # noqa: BLE001
            return tuple(acquired), ("LOCK_ROLLBACK_TIME_UNAVAILABLE",)

        if any(released_at < lease.acquired_at for lease in acquired):
            return tuple(acquired), ("LOCK_ROLLBACK_TIME_PRECEDES_ACQUIRE",)

        retained: list[ResourceLockLease] = []
        reasons: list[str] = []
        for lease in reversed(acquired):
            try:
                decision = await self._authority.release(
                    lease,
                    released_at=released_at,
                )
            except Exception:  # noqa: BLE001
                retained.append(lease)
                reasons.append("LOCK_ROLLBACK_RELEASE_EXCEPTION")
                continue

            if not isinstance(decision, ResourceLockReleaseDecision) or not isinstance(
                decision.status,
                ResourceLockReleaseStatus,
            ):
                retained.append(lease)
                reasons.append("LOCK_ROLLBACK_RELEASE_INVALID_DECISION")
                continue
            if decision.lease != lease:
                retained.append(lease)
                reasons.append("LOCK_ROLLBACK_RELEASE_IDENTITY_MISMATCH")
                continue
            if decision.status in {
                ResourceLockReleaseStatus.RELEASED,
                ResourceLockReleaseStatus.ALREADY_RELEASED,
            }:
                continue

            retained.append(lease)
            reasons.append(
                "LOCK_ROLLBACK_RELEASE_NOT_OWNER"
                if decision.status is ResourceLockReleaseStatus.NOT_OWNER
                else "LOCK_ROLLBACK_RELEASE_UNKNOWN"
            )

        retained.reverse()
        return tuple(retained), tuple(reasons)
