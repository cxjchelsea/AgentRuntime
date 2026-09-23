"""M5-IU8 CA-03 session lock and operation-bound resource release authority.

This amendment binds Tool resource leases to the exact IU7 in-flight Tool operation
and introduces a Core session-execution lock. It deliberately remains live/in-memory:
durable leases, stale reclaim, fencing, crash recovery, and restart semantics belong
to IU9.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from runtime.contracts.enums import ExecutionPlanStatus
from runtime.contracts.execution import ExecutionContext
from runtime.execution.control_application import (
    HierarchicalInterruptStatus,
    HierarchicalInterruptSummary,
    InFlightOperationHandle,
    InFlightOperationKind,
    InterruptOutcomeStatus,
)
from runtime.execution.foundation import PreparedExecution
from runtime.execution.models import StepExecutionStatus
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


def _require_non_blank(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


class SessionExecutionLockIdentityFactory(Protocol):
    def lock_key(self, *, session_id: str) -> str:
        """Return one deterministic Core lock key for a session."""

    def acquisition_id(
        self,
        *,
        session_id: str,
        execution_id: str,
    ) -> str:
        """Bind one session-lock acquisition to one exact execution."""


class Sha256SessionExecutionLockIdentityFactory:
    """Namespace generic Core session identities without exposing raw session ids."""

    def lock_key(self, *, session_id: str) -> str:
        _require_non_blank(session_id, "session_id")
        digest = hashlib.sha256(f"session-execution\0{session_id}".encode()).hexdigest()
        return f"session-execution:sha256:{digest}"

    def acquisition_id(
        self,
        *,
        session_id: str,
        execution_id: str,
    ) -> str:
        _require_non_blank(session_id, "session_id")
        _require_non_blank(execution_id, "execution_id")
        payload = (
            f"session-execution-acquisition\0{session_id}\0{execution_id}".encode()
        )
        return f"sha256:{hashlib.sha256(payload).hexdigest()}"


@dataclass(frozen=True, slots=True)
class SessionExecutionLease:
    session_id: str
    execution_id: str
    lease: ResourceLockLease

    def __post_init__(self) -> None:
        _require_non_blank(self.session_id, "session_id")
        _require_non_blank(self.execution_id, "execution_id")
        if self.lease.owner.execution_id != self.execution_id:
            raise ValueError("session lease owner execution_id mismatch")
        if self.lease.owner.owner_id != self.execution_id:
            raise ValueError("session lease owner_id must equal execution_id")
        if self.lease.owner.step_execution_id is not None:
            raise ValueError("session lease owner must not carry Step identity")
        if self.lease.owner.tool_call_id is not None:
            raise ValueError("session lease owner must not carry Tool identity")
        if self.lease.owner.physical_attempt is not None:
            raise ValueError("session lease owner must not carry physical attempt")


class SessionExecutionAcquireStatus(str, Enum):
    ACQUIRED = "ACQUIRED"
    ALREADY_ACQUIRED = "ALREADY_ACQUIRED"
    BUSY = "BUSY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class SessionExecutionAcquireDecision:
    status: SessionExecutionAcquireStatus
    reason_codes: tuple[str, ...]
    session_lease: SessionExecutionLease | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, SessionExecutionAcquireStatus):
            raise TypeError("status must be SessionExecutionAcquireStatus")
        if not self.reason_codes or any(
            not isinstance(code, str) or not code.strip() for code in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        if self.status in {
            SessionExecutionAcquireStatus.ACQUIRED,
            SessionExecutionAcquireStatus.ALREADY_ACQUIRED,
        }:
            if self.session_lease is None:
                raise ValueError("successful session acquire requires session_lease")
        elif self.session_lease is not None:
            raise ValueError("BUSY/UNKNOWN session acquire must not expose lease")


class SessionExecutionReleaseStatus(str, Enum):
    RELEASED = "RELEASED"
    ALREADY_RELEASED = "ALREADY_RELEASED"
    RETAINED = "RETAINED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class SessionExecutionReleaseDecision:
    status: SessionExecutionReleaseStatus
    reason_codes: tuple[str, ...]
    session_lease: SessionExecutionLease

    def __post_init__(self) -> None:
        if not isinstance(self.status, SessionExecutionReleaseStatus):
            raise TypeError("status must be SessionExecutionReleaseStatus")
        if not self.reason_codes or any(
            not isinstance(code, str) or not code.strip() for code in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")


class SessionExecutionLockCoordinator:
    """Hold one session lock for the complete authoritative Execution lifetime."""

    _TERMINAL_EXECUTION_STATUSES = frozenset(item.value for item in ExecutionPlanStatus)
    _TERMINAL_STEP_STATUSES = frozenset(
        {
            StepExecutionStatus.SUCCESS,
            StepExecutionStatus.FAILED,
            StepExecutionStatus.SKIPPED,
            StepExecutionStatus.CANCELLED,
            StepExecutionStatus.TIMEOUT,
            StepExecutionStatus.PREEMPTED,
        }
    )

    def __init__(
        self,
        *,
        authority: ResourceLockAuthority,
        identity_factory: SessionExecutionLockIdentityFactory,
    ) -> None:
        self._authority = authority
        self._identity_factory = identity_factory

    async def acquire(
        self,
        *,
        execution_context: ExecutionContext,
        requested_at: datetime,
    ) -> SessionExecutionAcquireDecision:
        _require_aware(requested_at, "requested_at")
        session_id = execution_context.session_id
        execution_id = execution_context.execution_id
        try:
            lock_key = self._identity_factory.lock_key(session_id=session_id)
            acquisition_id = self._identity_factory.acquisition_id(
                session_id=session_id,
                execution_id=execution_id,
            )
        except Exception:  # noqa: BLE001
            return SessionExecutionAcquireDecision(
                status=SessionExecutionAcquireStatus.UNKNOWN,
                reason_codes=("SESSION_LOCK_IDENTITY_UNAVAILABLE",),
            )
        if (
            not isinstance(lock_key, str)
            or not lock_key.strip()
            or not isinstance(acquisition_id, str)
            or not acquisition_id.strip()
        ):
            return SessionExecutionAcquireDecision(
                status=SessionExecutionAcquireStatus.UNKNOWN,
                reason_codes=("SESSION_LOCK_IDENTITY_UNAVAILABLE",),
            )

        owner = ResourceLockOwner(
            owner_id=execution_id,
            execution_id=execution_id,
        )
        request = ResourceLockAcquireRequest(
            lock_key=lock_key,
            owner=owner,
            acquisition_id=acquisition_id,
            requested_at=requested_at,
        )
        try:
            decision = await self._authority.acquire(request)
        except Exception:  # noqa: BLE001
            return SessionExecutionAcquireDecision(
                status=SessionExecutionAcquireStatus.UNKNOWN,
                reason_codes=("SESSION_LOCK_ACQUIRE_EXCEPTION",),
            )
        if not self._valid_acquire_decision(decision=decision, request=request):
            return SessionExecutionAcquireDecision(
                status=SessionExecutionAcquireStatus.UNKNOWN,
                reason_codes=("SESSION_LOCK_ACQUIRE_INVALID_DECISION",),
            )

        if decision.status is ResourceLockAcquireStatus.BUSY:
            return SessionExecutionAcquireDecision(
                status=SessionExecutionAcquireStatus.BUSY,
                reason_codes=decision.reason_codes,
            )
        if decision.status is ResourceLockAcquireStatus.UNKNOWN:
            return SessionExecutionAcquireDecision(
                status=SessionExecutionAcquireStatus.UNKNOWN,
                reason_codes=decision.reason_codes,
            )

        assert decision.lease is not None
        status = (
            SessionExecutionAcquireStatus.ACQUIRED
            if decision.status is ResourceLockAcquireStatus.ACQUIRED
            else SessionExecutionAcquireStatus.ALREADY_ACQUIRED
        )
        return SessionExecutionAcquireDecision(
            status=status,
            reason_codes=decision.reason_codes,
            session_lease=SessionExecutionLease(
                session_id=session_id,
                execution_id=execution_id,
                lease=decision.lease,
            ),
        )

    async def release_if_terminal(
        self,
        *,
        prepared: PreparedExecution,
        session_lease: SessionExecutionLease,
        released_at: datetime,
    ) -> SessionExecutionReleaseDecision:
        _require_aware(released_at, "released_at")
        identity_reason = self._session_identity_error(
            prepared=prepared,
            session_lease=session_lease,
        )
        if identity_reason is not None:
            return SessionExecutionReleaseDecision(
                status=SessionExecutionReleaseStatus.UNKNOWN,
                reason_codes=(identity_reason,),
                session_lease=session_lease,
            )

        if not self._is_authoritatively_terminal(prepared):
            return SessionExecutionReleaseDecision(
                status=SessionExecutionReleaseStatus.RETAINED,
                reason_codes=("EXECUTION_NOT_AUTHORITATIVELY_TERMINAL",),
                session_lease=session_lease,
            )
        if prepared.finished_at is not None and released_at < prepared.finished_at:
            return SessionExecutionReleaseDecision(
                status=SessionExecutionReleaseStatus.UNKNOWN,
                reason_codes=("SESSION_LOCK_RELEASE_PRECEDES_EXECUTION_FINISH",),
                session_lease=session_lease,
            )
        if (
            prepared.execution_record.updated_at is not None
            and released_at < prepared.execution_record.updated_at
        ):
            return SessionExecutionReleaseDecision(
                status=SessionExecutionReleaseStatus.UNKNOWN,
                reason_codes=("SESSION_LOCK_RELEASE_PRECEDES_LATEST_OBSERVATION",),
                session_lease=session_lease,
            )
        if released_at < session_lease.lease.acquired_at:
            return SessionExecutionReleaseDecision(
                status=SessionExecutionReleaseStatus.UNKNOWN,
                reason_codes=("SESSION_LOCK_RELEASE_PRECEDES_ACQUIRE",),
                session_lease=session_lease,
            )

        try:
            decision = await self._authority.release(
                session_lease.lease,
                released_at=released_at,
            )
        except Exception:  # noqa: BLE001
            return SessionExecutionReleaseDecision(
                status=SessionExecutionReleaseStatus.UNKNOWN,
                reason_codes=("SESSION_LOCK_RELEASE_EXCEPTION",),
                session_lease=session_lease,
            )
        if (
            not isinstance(decision, ResourceLockReleaseDecision)
            or not isinstance(decision.status, ResourceLockReleaseStatus)
            or decision.lease != session_lease.lease
        ):
            return SessionExecutionReleaseDecision(
                status=SessionExecutionReleaseStatus.UNKNOWN,
                reason_codes=("SESSION_LOCK_RELEASE_INVALID_DECISION",),
                session_lease=session_lease,
            )
        if decision.status is ResourceLockReleaseStatus.RELEASED:
            status = SessionExecutionReleaseStatus.RELEASED
        elif decision.status is ResourceLockReleaseStatus.ALREADY_RELEASED:
            status = SessionExecutionReleaseStatus.ALREADY_RELEASED
        else:
            status = SessionExecutionReleaseStatus.UNKNOWN
        return SessionExecutionReleaseDecision(
            status=status,
            reason_codes=decision.reason_codes,
            session_lease=session_lease,
        )

    @staticmethod
    def _valid_acquire_decision(
        *,
        decision: object,
        request: ResourceLockAcquireRequest,
    ) -> bool:
        if not isinstance(decision, ResourceLockAcquireDecision) or not isinstance(
            decision.status, ResourceLockAcquireStatus
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

    @classmethod
    def _is_authoritatively_terminal(cls, prepared: PreparedExecution) -> bool:
        return (
            prepared.execution_record.status in cls._TERMINAL_EXECUTION_STATUSES
            and prepared.finished_at is not None
            and bool(prepared.steps)
            and all(
                step.status in cls._TERMINAL_STEP_STATUSES for step in prepared.steps
            )
        )

    def _session_identity_error(
        self,
        *,
        prepared: PreparedExecution,
        session_lease: SessionExecutionLease,
    ) -> str | None:
        context = prepared.execution_context
        record = prepared.execution_record
        if context.execution_id != record.execution_id:
            return "PREPARED_EXECUTION_IDENTITY_INCONSISTENT"
        if context.execution_id != session_lease.execution_id:
            return "SESSION_LEASE_EXECUTION_MISMATCH"
        if context.session_id != session_lease.session_id:
            return "SESSION_LEASE_SESSION_MISMATCH"
        if session_lease.lease.owner.execution_id != context.execution_id:
            return "SESSION_LEASE_OWNER_MISMATCH"
        try:
            expected_lock_key = self._identity_factory.lock_key(
                session_id=context.session_id
            )
            expected_acquisition_id = self._identity_factory.acquisition_id(
                session_id=context.session_id,
                execution_id=context.execution_id,
            )
        except Exception:  # noqa: BLE001
            return "SESSION_LOCK_IDENTITY_UNAVAILABLE"
        if session_lease.lease.lock_key != expected_lock_key:
            return "SESSION_LEASE_LOCK_KEY_MISMATCH"
        if session_lease.lease.acquisition_id != expected_acquisition_id:
            return "SESSION_LEASE_ACQUISITION_MISMATCH"
        return None


@dataclass(frozen=True, slots=True)
class OperationResourceLeaseBinding:
    handle: InFlightOperationHandle
    owner: ResourceLockOwner
    leases: tuple[ResourceLockLease, ...]

    def __post_init__(self) -> None:
        if self.handle.kind is not InFlightOperationKind.TOOL:
            raise ValueError("operation resource binding requires TOOL handle")
        if self.handle.tool_call_id is None:
            raise ValueError("TOOL handle requires tool_call_id")
        if not self.leases:
            raise ValueError("operation resource binding requires at least one lease")
        if self.owner.owner_id != self.handle.operation_handle_id:
            raise ValueError(
                "resource owner_id must equal exact Tool operation_handle_id"
            )
        if self.owner.execution_id != self.handle.execution_id:
            raise ValueError("resource owner execution_id mismatch")
        if self.owner.step_execution_id != self.handle.step_execution_id:
            raise ValueError("resource owner step_execution_id mismatch")
        if self.owner.tool_call_id != self.handle.tool_call_id:
            raise ValueError("resource owner tool_call_id mismatch")
        if self.owner.physical_attempt is None:
            raise ValueError("resource owner requires physical_attempt")
        lock_keys = [lease.lock_key for lease in self.leases]
        acquisition_ids = [lease.acquisition_id for lease in self.leases]
        if len(set(lock_keys)) != len(lock_keys):
            raise ValueError("operation resource leases require unique lock_key")
        if len(set(acquisition_ids)) != len(acquisition_ids):
            raise ValueError("operation resource leases require unique acquisition_id")
        if any(lease.owner != self.owner for lease in self.leases):
            raise ValueError("operation resource lease owner mismatch")
        if any(lease.acquired_at > self.handle.started_at for lease in self.leases):
            raise ValueError(
                "operation resource lease must be acquired before operation start"
            )


class OperationResourceLeaseRegistry(Protocol):
    async def register(self, binding: OperationResourceLeaseBinding) -> bool:
        """Bind exact leases to one live Tool operation without rebinding."""

    async def get(
        self,
        operation_handle_id: str,
    ) -> OperationResourceLeaseBinding | None:
        """Return the live exact binding for one operation."""

    async def remove(self, binding: OperationResourceLeaseBinding) -> bool:
        """Remove only the exact binding after confirmed resource release."""


class InMemoryOperationResourceLeaseRegistry:
    """Live binding registry only; durable recovery belongs to IU9."""

    def __init__(self) -> None:
        self._bindings: dict[str, OperationResourceLeaseBinding] = {}

    async def register(self, binding: OperationResourceLeaseBinding) -> bool:
        key = binding.handle.operation_handle_id
        existing = self._bindings.get(key)
        if existing is not None:
            if existing != binding:
                raise ValueError(
                    "operation_handle_id resource binding cannot be rebound"
                )
            return False
        self._bindings[key] = binding
        return True

    async def get(
        self,
        operation_handle_id: str,
    ) -> OperationResourceLeaseBinding | None:
        _require_non_blank(operation_handle_id, "operation_handle_id")
        return self._bindings.get(operation_handle_id)

    async def remove(self, binding: OperationResourceLeaseBinding) -> bool:
        key = binding.handle.operation_handle_id
        existing = self._bindings.get(key)
        if existing is None:
            return False
        if existing != binding:
            raise ValueError("operation resource binding identity mismatch")
        del self._bindings[key]
        return True


class OperationResourceReleaseStatus(str, Enum):
    RELEASED = "RELEASED"
    RETAINED = "RETAINED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class OperationResourceReleaseDecision:
    status: OperationResourceReleaseStatus
    reason_codes: tuple[str, ...]
    released_leases: tuple[ResourceLockLease, ...] = ()
    retained_leases: tuple[ResourceLockLease, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, OperationResourceReleaseStatus):
            raise TypeError("status must be OperationResourceReleaseStatus")
        if not self.reason_codes or any(
            not isinstance(code, str) or not code.strip() for code in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        released_ids = {lease.acquisition_id for lease in self.released_leases}
        retained_ids = {lease.acquisition_id for lease in self.retained_leases}
        if released_ids & retained_ids:
            raise ValueError("released and retained leases must be disjoint")
        if self.status is OperationResourceReleaseStatus.RELEASED:
            if self.retained_leases:
                raise ValueError("RELEASED cannot carry retained leases")
        elif self.status is OperationResourceReleaseStatus.RETAINED:
            if self.released_leases:
                raise ValueError("RETAINED cannot claim released leases")
            if not self.retained_leases:
                raise ValueError("RETAINED requires retained leases")


class OperationResourceReleaseCoordinator:
    """Release Tool leases only from exact operation terminal evidence."""

    def __init__(
        self,
        *,
        authority: ResourceLockAuthority,
        registry: OperationResourceLeaseRegistry,
    ) -> None:
        self._authority = authority
        self._registry = registry

    async def bind(
        self,
        binding: OperationResourceLeaseBinding,
    ) -> bool:
        return await self._registry.register(binding)

    async def release_after_completion(
        self,
        *,
        binding: OperationResourceLeaseBinding,
        completed_handle: InFlightOperationHandle,
        completed_at: datetime,
    ) -> OperationResourceReleaseDecision:
        _require_aware(completed_at, "completed_at")
        if completed_handle != binding.handle:
            return self._retained_unknown(
                binding,
                "OPERATION_COMPLETION_IDENTITY_MISMATCH",
            )
        if completed_at < completed_handle.started_at:
            return self._retained_unknown(
                binding,
                "OPERATION_COMPLETION_PRECEDES_START",
            )
        if any(completed_at < lease.acquired_at for lease in binding.leases):
            return self._retained_unknown(
                binding,
                "OPERATION_COMPLETION_PRECEDES_LOCK_ACQUIRE",
            )
        if not await self._is_exact_registered(binding):
            return self._retained_unknown(
                binding,
                "OPERATION_RESOURCE_BINDING_NOT_ACTIVE",
            )
        return await self._release_exact(
            binding=binding,
            released_at=completed_at,
            success_reason="OPERATION_COMPLETED_RESOURCE_RELEASED",
        )

    async def release_after_interrupt(
        self,
        *,
        binding: OperationResourceLeaseBinding,
        interrupt_summary: HierarchicalInterruptSummary,
        observed_at: datetime,
    ) -> OperationResourceReleaseDecision:
        _require_aware(observed_at, "observed_at")
        if not await self._is_exact_registered(binding):
            return self._retained_unknown(
                binding,
                "OPERATION_RESOURCE_BINDING_NOT_ACTIVE",
            )
        handle = binding.handle
        if (
            interrupt_summary.execution_id != handle.execution_id
            or interrupt_summary.step_execution_id != handle.step_execution_id
        ):
            return self._retained_unknown(
                binding,
                "INTERRUPT_RESOURCE_IDENTITY_MISMATCH",
            )
        if interrupt_summary.status is not HierarchicalInterruptStatus.ORDERED:
            return self._retained_unknown(
                binding,
                "INTERRUPT_RESOURCE_RELEASE_UNPROVEN",
            )

        matches = [
            (candidate, outcome)
            for candidate, outcome in zip(
                interrupt_summary.handles,
                interrupt_summary.outcomes,
                strict=True,
            )
            if candidate.operation_handle_id == handle.operation_handle_id
        ]
        if len(matches) != 1:
            return self._retained_unknown(
                binding,
                "INTERRUPT_TOOL_OUTCOME_MISSING",
            )
        observed_handle, outcome = matches[0]
        if observed_handle != handle:
            return self._retained_unknown(
                binding,
                "INTERRUPT_TOOL_HANDLE_MISMATCH",
            )
        if observed_at < handle.started_at:
            return self._retained_unknown(
                binding,
                "INTERRUPT_OBSERVATION_PRECEDES_START",
            )

        if outcome.status is InterruptOutcomeStatus.CONFIRMED_STOPPED:
            if any(observed_at < lease.acquired_at for lease in binding.leases):
                return self._retained_unknown(
                    binding,
                    "INTERRUPT_OBSERVATION_PRECEDES_LOCK_ACQUIRE",
                )
            return await self._release_exact(
                binding=binding,
                released_at=observed_at,
                success_reason="INTERRUPT_CONFIRMED_STOPPED_RESOURCE_RELEASED",
            )
        if outcome.status is InterruptOutcomeStatus.ALREADY_COMPLETED:
            return OperationResourceReleaseDecision(
                status=OperationResourceReleaseStatus.RETAINED,
                reason_codes=("ALREADY_COMPLETED_AWAITING_REAL_COMPLETION",),
                retained_leases=binding.leases,
            )
        if outcome.status is InterruptOutcomeStatus.NOT_CANCELLABLE:
            return OperationResourceReleaseDecision(
                status=OperationResourceReleaseStatus.RETAINED,
                reason_codes=("NOT_CANCELLABLE_RESOURCE_RETAINED",),
                retained_leases=binding.leases,
            )
        return OperationResourceReleaseDecision(
            status=OperationResourceReleaseStatus.RETAINED,
            reason_codes=("INTERRUPT_UNKNOWN_RESOURCE_RETAINED",),
            retained_leases=binding.leases,
        )

    async def _is_exact_registered(
        self,
        binding: OperationResourceLeaseBinding,
    ) -> bool:
        try:
            active = await self._registry.get(binding.handle.operation_handle_id)
        except Exception:  # noqa: BLE001
            return False
        return active == binding

    async def _release_exact(
        self,
        *,
        binding: OperationResourceLeaseBinding,
        released_at: datetime,
        success_reason: str,
    ) -> OperationResourceReleaseDecision:
        released: list[ResourceLockLease] = []
        retained: list[ResourceLockLease] = []

        for lease in reversed(binding.leases):
            try:
                decision = await self._authority.release(
                    lease,
                    released_at=released_at,
                )
            except Exception:  # noqa: BLE001
                retained.append(lease)
                continue
            if (
                not isinstance(decision, ResourceLockReleaseDecision)
                or not isinstance(decision.status, ResourceLockReleaseStatus)
                or decision.lease != lease
            ):
                retained.append(lease)
                continue
            if decision.status in {
                ResourceLockReleaseStatus.RELEASED,
                ResourceLockReleaseStatus.ALREADY_RELEASED,
            }:
                released.append(lease)
            else:
                retained.append(lease)

        released.reverse()
        retained.reverse()

        if retained:
            return OperationResourceReleaseDecision(
                status=OperationResourceReleaseStatus.UNKNOWN,
                reason_codes=("OPERATION_RESOURCE_RELEASE_UNCERTAIN",),
                released_leases=tuple(released),
                retained_leases=tuple(retained),
            )

        try:
            removed = await self._registry.remove(binding)
        except Exception:  # noqa: BLE001
            return OperationResourceReleaseDecision(
                status=OperationResourceReleaseStatus.UNKNOWN,
                reason_codes=(
                    success_reason,
                    "OPERATION_RESOURCE_BINDING_REMOVE_UNKNOWN",
                ),
                released_leases=tuple(released),
            )
        if not removed:
            return OperationResourceReleaseDecision(
                status=OperationResourceReleaseStatus.UNKNOWN,
                reason_codes=(
                    success_reason,
                    "OPERATION_RESOURCE_BINDING_REMOVE_MISSING",
                ),
                released_leases=tuple(released),
            )

        return OperationResourceReleaseDecision(
            status=OperationResourceReleaseStatus.RELEASED,
            reason_codes=(success_reason,),
            released_leases=tuple(released),
        )

    @staticmethod
    def _retained_unknown(
        binding: OperationResourceLeaseBinding,
        reason_code: str,
    ) -> OperationResourceReleaseDecision:
        return OperationResourceReleaseDecision(
            status=OperationResourceReleaseStatus.UNKNOWN,
            reason_codes=(reason_code,),
            retained_leases=binding.leases,
        )
