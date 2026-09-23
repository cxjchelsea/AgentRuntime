"""M5-IU8 Formal Implementation concurrency runtime.

This module wires the frozen IU8 authorities into live execution admission without
adding priority policy, parallel scheduling, durable recovery, aggregation, or M6.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from runtime.contracts.execution import ExecutionContext
from runtime.execution.control_application import (
    HierarchicalInterruptSummary,
    InFlightOperationHandle,
    InFlightOperationIdentifierFactory,
    InFlightOperationKind,
    InFlightOperationRegistry,
    InterruptOutcomeStatus,
)
from runtime.execution.foundation import PreparedExecution
from runtime.execution.resource_lock import ResourceLockLease, ResourceLockOwner
from runtime.execution.resource_lock_lifecycle import (
    OperationResourceLeaseBinding,
    OperationResourceLeaseRegistry,
    OperationResourceReleaseCoordinator,
    OperationResourceReleaseDecision,
    OperationResourceReleaseStatus,
    SessionExecutionAcquireStatus,
    SessionExecutionLease,
    SessionExecutionLockCoordinator,
    SessionExecutionReleaseDecision,
    SessionExecutionReleaseStatus,
)
from runtime.execution.resource_lock_set import (
    ResourceLockProjectionStatus,
    ResourceLockSetCoordinator,
    ResourceLockSetRequest,
    ResourceLockSetStatus,
    ToolResourceLockProjector,
)
from runtime.registries.definitions import ToolDefinition


class ExecutionConcurrencyAdmissionStatus(str, Enum):
    ADMITTED = "ADMITTED"
    BUSY = "BUSY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ExecutionConcurrencyAdmissionDecision:
    status: ExecutionConcurrencyAdmissionStatus
    reason_codes: tuple[str, ...]
    session_lease: SessionExecutionLease | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ExecutionConcurrencyAdmissionStatus):
            raise TypeError("status must be ExecutionConcurrencyAdmissionStatus")
        if not self.reason_codes or any(
            not isinstance(code, str) or not code.strip() for code in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        if self.status is ExecutionConcurrencyAdmissionStatus.ADMITTED:
            if self.session_lease is None:
                raise ValueError("ADMITTED requires session_lease")
        elif self.session_lease is not None:
            raise ValueError("BUSY/UNKNOWN must not expose session_lease")


class ExecutionConcurrencyRuntime:
    """Live session admission/terminal-release wiring for one Runtime process."""

    def __init__(
        self,
        *,
        session_coordinator: SessionExecutionLockCoordinator,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_coordinator = session_coordinator
        self._clock = clock or (lambda: datetime.now(UTC))
        self._leases: dict[str, SessionExecutionLease] = {}
        self._release_decisions: dict[str, SessionExecutionReleaseDecision] = {}

    async def admit(
        self,
        execution_context: ExecutionContext,
    ) -> ExecutionConcurrencyAdmissionDecision:
        existing = self._leases.get(execution_context.execution_id)
        if existing is not None:
            if existing.session_id != execution_context.session_id:
                return ExecutionConcurrencyAdmissionDecision(
                    status=ExecutionConcurrencyAdmissionStatus.UNKNOWN,
                    reason_codes=("SESSION_EXECUTION_LEASE_CONTEXT_MISMATCH",),
                )
            return ExecutionConcurrencyAdmissionDecision(
                status=ExecutionConcurrencyAdmissionStatus.ADMITTED,
                reason_codes=("SESSION_EXECUTION_LEASE_ALREADY_TRACKED",),
                session_lease=existing,
            )

        requested_at = self._now()
        try:
            decision = await self._session_coordinator.acquire(
                execution_context=execution_context,
                requested_at=requested_at,
            )
        except Exception:  # noqa: BLE001
            return ExecutionConcurrencyAdmissionDecision(
                status=ExecutionConcurrencyAdmissionStatus.UNKNOWN,
                reason_codes=("SESSION_EXECUTION_ADMISSION_EXCEPTION",),
            )

        if decision.status in {
            SessionExecutionAcquireStatus.ACQUIRED,
            SessionExecutionAcquireStatus.ALREADY_ACQUIRED,
        }:
            lease = decision.session_lease
            if lease is None:
                return ExecutionConcurrencyAdmissionDecision(
                    status=ExecutionConcurrencyAdmissionStatus.UNKNOWN,
                    reason_codes=("SESSION_EXECUTION_ADMISSION_INVALID_DECISION",),
                )
            self._leases[execution_context.execution_id] = lease
            return ExecutionConcurrencyAdmissionDecision(
                status=ExecutionConcurrencyAdmissionStatus.ADMITTED,
                reason_codes=decision.reason_codes,
                session_lease=lease,
            )
        if decision.status is SessionExecutionAcquireStatus.BUSY:
            return ExecutionConcurrencyAdmissionDecision(
                status=ExecutionConcurrencyAdmissionStatus.BUSY,
                reason_codes=decision.reason_codes,
            )
        return ExecutionConcurrencyAdmissionDecision(
            status=ExecutionConcurrencyAdmissionStatus.UNKNOWN,
            reason_codes=decision.reason_codes,
        )

    async def on_terminal_execution(
        self,
        prepared: PreparedExecution,
        *,
        observed_at: datetime,
    ) -> None:
        """ExecutionTerminalObserver hook; terminal lifecycle remains authoritative."""

        lease = self._leases.get(prepared.execution_context.execution_id)
        if lease is None:
            return
        try:
            decision = await self._session_coordinator.release_if_terminal(
                prepared=prepared,
                session_lease=lease,
                released_at=observed_at,
            )
        except Exception:  # noqa: BLE001
            return
        self._release_decisions[prepared.execution_context.execution_id] = decision
        if decision.status in {
            SessionExecutionReleaseStatus.RELEASED,
            SessionExecutionReleaseStatus.ALREADY_RELEASED,
        }:
            self._leases.pop(prepared.execution_context.execution_id, None)

    def active_session_lease(
        self,
        execution_id: str,
    ) -> SessionExecutionLease | None:
        return self._leases.get(execution_id)

    def last_release_decision(
        self,
        execution_id: str,
    ) -> SessionExecutionReleaseDecision | None:
        return self._release_decisions.get(execution_id)

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise TypeError("concurrency clock returned invalid time")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("concurrency clock must return timezone-aware time")
        return value


class ToolConcurrencyAdmissionStatus(str, Enum):
    ADMITTED = "ADMITTED"
    BUSY = "BUSY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ToolConcurrencyAdmissionDecision:
    status: ToolConcurrencyAdmissionStatus
    reason_codes: tuple[str, ...]
    handle: InFlightOperationHandle | None = None
    binding: OperationResourceLeaseBinding | None = None
    retained_leases: tuple[ResourceLockLease, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, ToolConcurrencyAdmissionStatus):
            raise TypeError("status must be ToolConcurrencyAdmissionStatus")
        if not self.reason_codes or any(
            not isinstance(code, str) or not code.strip() for code in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        if self.status is ToolConcurrencyAdmissionStatus.ADMITTED:
            if self.handle is None:
                raise ValueError("ADMITTED requires Tool handle")
        elif self.binding is not None:
            raise ValueError("BUSY/UNKNOWN must not expose active binding")


class ToolConcurrencyCompletionStatus(str, Enum):
    COMPLETED = "COMPLETED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ToolConcurrencyCompletionDecision:
    status: ToolConcurrencyCompletionStatus
    reason_codes: tuple[str, ...]
    resource_release: OperationResourceReleaseDecision | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ToolConcurrencyCompletionStatus):
            raise TypeError("status must be ToolConcurrencyCompletionStatus")
        if not self.reason_codes or any(
            not isinstance(code, str) or not code.strip() for code in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")


class ToolConcurrencyRuntime:
    """Unify IU7 Tool in-flight truth with IU8 resource-lock authority."""

    def __init__(
        self,
        *,
        projector: ToolResourceLockProjector,
        lock_set_coordinator: ResourceLockSetCoordinator,
        resource_release_coordinator: OperationResourceReleaseCoordinator,
        operation_resource_registry: OperationResourceLeaseRegistry,
        inflight_registry: InFlightOperationRegistry,
        inflight_identifier_factory: InFlightOperationIdentifierFactory,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._projector = projector
        self._lock_set_coordinator = lock_set_coordinator
        self._resource_release_coordinator = resource_release_coordinator
        self._operation_resource_registry = operation_resource_registry
        self._inflight_registry = inflight_registry
        self._inflight_identifier_factory = inflight_identifier_factory
        self._clock = clock or (lambda: datetime.now(UTC))
        self._interrupt_cleanup: dict[str, ToolConcurrencyCompletionDecision] = {}

    @property
    def inflight_registry(self) -> InFlightOperationRegistry:
        return self._inflight_registry

    @property
    def inflight_identifier_factory(self) -> InFlightOperationIdentifierFactory:
        return self._inflight_identifier_factory

    async def admit(
        self,
        *,
        tool_definition: ToolDefinition,
        tool_id: str,
        tool_version: str,
        execution_context: ExecutionContext,
        step_execution_id: str,
        parent_handle_id: str,
        logical_tool_call_id: str,
        physical_attempt: int,
    ) -> ToolConcurrencyAdmissionDecision:
        if (
            tool_definition.tool_id != tool_id
            or tool_definition.version != tool_version
        ):
            return self._unknown("TOOL_CONCURRENCY_DEFINITION_IDENTITY_MISMATCH")

        try:
            handle_id = self._inflight_identifier_factory.new_tool_handle_id(
                execution_id=execution_context.execution_id,
                step_execution_id=step_execution_id,
                parent_handle_id=parent_handle_id,
                tool_call_id=logical_tool_call_id,
                physical_attempt=physical_attempt,
            )
        except Exception:  # noqa: BLE001
            return self._unknown("TOOL_OPERATION_HANDLE_ID_UNKNOWN")
        if not isinstance(handle_id, str) or not handle_id.strip():
            return self._unknown("TOOL_OPERATION_HANDLE_ID_UNKNOWN")

        owner = ResourceLockOwner(
            owner_id=handle_id,
            execution_id=execution_context.execution_id,
            step_execution_id=step_execution_id,
            tool_call_id=logical_tool_call_id,
            physical_attempt=physical_attempt,
        )

        try:
            projection = await self._projector.project(
                tool_definition=tool_definition,
                execution_context=execution_context,
                tool_call_id=logical_tool_call_id,
                physical_attempt=physical_attempt,
            )
        except Exception:  # noqa: BLE001
            return self._unknown("RESOURCE_LOCK_PROJECTION_EXCEPTION")
        if (
            not hasattr(projection, "status")
            or projection.status is ResourceLockProjectionStatus.UNKNOWN
        ):
            return self._unknown(
                *getattr(
                    projection,
                    "reason_codes",
                    ("RESOURCE_LOCK_PROJECTION_UNKNOWN",),
                )
            )
        if projection.status is not ResourceLockProjectionStatus.RESOLVED:
            return self._unknown("RESOURCE_LOCK_PROJECTION_INVALID_DECISION")

        requested_at = self._now()
        try:
            lock_set = await self._lock_set_coordinator.acquire(
                ResourceLockSetRequest(
                    lock_set_id=f"tool-operation:{handle_id}",
                    owner=owner,
                    resolved_locks=projection.resolved_locks,
                    requested_at=requested_at,
                )
            )
        except Exception:  # noqa: BLE001
            return self._unknown("RESOURCE_LOCK_SET_ACQUIRE_EXCEPTION")

        if lock_set.status is ResourceLockSetStatus.BUSY:
            return ToolConcurrencyAdmissionDecision(
                status=ToolConcurrencyAdmissionStatus.BUSY,
                reason_codes=lock_set.reason_codes,
            )
        if lock_set.status is not ResourceLockSetStatus.ACQUIRED:
            return ToolConcurrencyAdmissionDecision(
                status=ToolConcurrencyAdmissionStatus.UNKNOWN,
                reason_codes=lock_set.reason_codes,
                retained_leases=lock_set.retained_leases,
            )

        leases = lock_set.leases
        try:
            started_at = self._now()
            handle = InFlightOperationHandle(
                operation_handle_id=handle_id,
                execution_id=execution_context.execution_id,
                step_execution_id=step_execution_id,
                parent_handle_id=parent_handle_id,
                kind=InFlightOperationKind.TOOL,
                capability_id=tool_id,
                capability_version=tool_version,
                tool_call_id=logical_tool_call_id,
                started_at=started_at,
            )
            binding = (
                OperationResourceLeaseBinding(
                    handle=handle,
                    owner=owner,
                    leases=leases,
                )
                if leases
                else None
            )
        except Exception:  # noqa: BLE001
            return self._unknown(
                "TOOL_OPERATION_BINDING_CONSTRUCTION_FAILED",
                retained_leases=leases,
            )

        try:
            registered = await self._inflight_registry.register(handle)
        except Exception:  # noqa: BLE001
            registered = False
        if registered is not True:
            return self._unknown(
                "INFLIGHT_TOOL_REGISTRATION_UNKNOWN",
                handle=handle,
                retained_leases=leases,
            )

        if binding is not None:
            try:
                bound = await self._resource_release_coordinator.bind(binding)
            except Exception:  # noqa: BLE001
                bound = False
            if bound is not True:
                return self._unknown(
                    "OPERATION_RESOURCE_BINDING_UNKNOWN",
                    handle=handle,
                    retained_leases=leases,
                )

        return ToolConcurrencyAdmissionDecision(
            status=ToolConcurrencyAdmissionStatus.ADMITTED,
            reason_codes=("TOOL_CONCURRENCY_ADMITTED",),
            handle=handle,
            binding=binding,
        )

    async def complete_after_operation(
        self,
        admission: ToolConcurrencyAdmissionDecision,
        *,
        completed_at: datetime,
    ) -> ToolConcurrencyCompletionDecision:
        if admission.status is not ToolConcurrencyAdmissionStatus.ADMITTED:
            return ToolConcurrencyCompletionDecision(
                status=ToolConcurrencyCompletionStatus.UNKNOWN,
                reason_codes=("TOOL_CONCURRENCY_ADMISSION_NOT_ACTIVE",),
            )
        handle = admission.handle
        if handle is None:
            return ToolConcurrencyCompletionDecision(
                status=ToolConcurrencyCompletionStatus.UNKNOWN,
                reason_codes=("TOOL_CONCURRENCY_HANDLE_MISSING",),
            )

        try:
            completed = await self._inflight_registry.complete(
                handle.operation_handle_id,
                completed_at=completed_at,
            )
        except Exception:  # noqa: BLE001
            completed = False
        if completed is not True:
            return ToolConcurrencyCompletionDecision(
                status=ToolConcurrencyCompletionStatus.UNKNOWN,
                reason_codes=("INFLIGHT_TOOL_COMPLETION_UNKNOWN",),
            )

        if admission.binding is None:
            return ToolConcurrencyCompletionDecision(
                status=ToolConcurrencyCompletionStatus.COMPLETED,
                reason_codes=("TOOL_COMPLETED_WITHOUT_RESOURCE_LOCKS",),
            )

        release = await self._resource_release_coordinator.release_after_completion(
            binding=admission.binding,
            completed_handle=handle,
            completed_at=completed_at,
        )
        if release.status is OperationResourceReleaseStatus.RELEASED:
            return ToolConcurrencyCompletionDecision(
                status=ToolConcurrencyCompletionStatus.COMPLETED,
                reason_codes=release.reason_codes,
                resource_release=release,
            )
        return ToolConcurrencyCompletionDecision(
            status=ToolConcurrencyCompletionStatus.UNKNOWN,
            reason_codes=release.reason_codes,
            resource_release=release,
        )

    async def reconcile_interrupt(
        self,
        summary: HierarchicalInterruptSummary,
        *,
        observed_at: datetime,
    ) -> tuple[ToolConcurrencyCompletionDecision, ...]:
        decisions: list[ToolConcurrencyCompletionDecision] = []
        for handle, outcome in zip(
            summary.handles,
            summary.outcomes,
            strict=True,
        ):
            if handle.kind is not InFlightOperationKind.TOOL:
                continue
            if outcome.status is not InterruptOutcomeStatus.CONFIRMED_STOPPED:
                continue

            try:
                completed = await self._inflight_registry.complete(
                    handle.operation_handle_id,
                    completed_at=observed_at,
                )
            except Exception:  # noqa: BLE001
                completed = False
            if completed is not True:
                decision = ToolConcurrencyCompletionDecision(
                    status=ToolConcurrencyCompletionStatus.UNKNOWN,
                    reason_codes=("INFLIGHT_CONFIRMED_STOPPED_COMPLETION_UNKNOWN",),
                )
                decisions.append(decision)
                self._interrupt_cleanup[handle.operation_handle_id] = decision
                continue

            try:
                binding = await self._operation_resource_registry.get(
                    handle.operation_handle_id
                )
            except Exception:  # noqa: BLE001
                binding = None
            if binding is None:
                decision = ToolConcurrencyCompletionDecision(
                    status=ToolConcurrencyCompletionStatus.COMPLETED,
                    reason_codes=("CONFIRMED_STOPPED_WITHOUT_RESOURCE_BINDING",),
                )
                decisions.append(decision)
                self._interrupt_cleanup[handle.operation_handle_id] = decision
                continue

            release = await self._resource_release_coordinator.release_after_interrupt(
                binding=binding,
                interrupt_summary=summary,
                observed_at=observed_at,
            )
            status = (
                ToolConcurrencyCompletionStatus.COMPLETED
                if release.status is OperationResourceReleaseStatus.RELEASED
                else ToolConcurrencyCompletionStatus.UNKNOWN
            )
            decision = ToolConcurrencyCompletionDecision(
                status=status,
                reason_codes=release.reason_codes,
                resource_release=release,
            )
            decisions.append(decision)
            self._interrupt_cleanup[handle.operation_handle_id] = decision
        return tuple(decisions)

    def last_interrupt_cleanup(
        self,
        operation_handle_id: str,
    ) -> ToolConcurrencyCompletionDecision | None:
        return self._interrupt_cleanup.get(operation_handle_id)

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise TypeError("concurrency clock returned invalid time")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("concurrency clock must return timezone-aware time")
        return value

    @staticmethod
    def _unknown(
        *reason_codes: str,
        handle: InFlightOperationHandle | None = None,
        retained_leases: tuple[ResourceLockLease, ...] = (),
    ) -> ToolConcurrencyAdmissionDecision:
        reasons = reason_codes or ("TOOL_CONCURRENCY_UNKNOWN",)
        return ToolConcurrencyAdmissionDecision(
            status=ToolConcurrencyAdmissionStatus.UNKNOWN,
            reason_codes=tuple(reasons),
            handle=handle,
            retained_leases=retained_leases,
        )
