"""CA-M5-IU7-02 in-flight interrupt and control-application contracts.

This amendment makes live interrupt authority and its uncertainty representable. It
does not mutate Step/Execution lifecycle; CA-M5-IU7-03 owns control-specific
terminalization. Resource locking, durable recovery, aggregation, and M6 remain out
of scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from runtime.execution.control import (
    ExecutionControlSignal,
    ExecutionControlSignalType,
    LatchedExecutionControl,
)
from runtime.execution.foundation import PreparedExecution, StepLifecycleSnapshot
from runtime.execution.models import StepExecutionStatus


class InFlightOperationKind(str, Enum):
    TOOL = "TOOL"
    SKILL = "SKILL"
    WORKFLOW = "WORKFLOW"


@dataclass(frozen=True, slots=True)
class InFlightOperationHandle:
    operation_handle_id: str
    execution_id: str
    step_execution_id: str
    kind: InFlightOperationKind
    capability_id: str
    capability_version: str
    started_at: datetime
    parent_handle_id: str | None = None
    tool_call_id: str | None = None
    workflow_instance_id: str | None = None

    def __post_init__(self) -> None:
        values = (
            self.operation_handle_id,
            self.execution_id,
            self.step_execution_id,
            self.capability_id,
            self.capability_version,
        )
        if any(not value.strip() for value in values):
            raise ValueError("in-flight operation identifiers must not be blank")
        if not isinstance(self.kind, InFlightOperationKind):
            raise ValueError("kind must be InFlightOperationKind")  # noqa: TRY004
        _require_aware_datetime(self.started_at, "started_at")
        if self.parent_handle_id is not None and not self.parent_handle_id.strip():
            raise ValueError("parent_handle_id must not be blank when present")
        if self.parent_handle_id == self.operation_handle_id:
            raise ValueError("operation cannot be its own parent")
        if self.tool_call_id is not None and not self.tool_call_id.strip():
            raise ValueError("tool_call_id must not be blank when present")
        if (
            self.workflow_instance_id is not None
            and not self.workflow_instance_id.strip()
        ):
            raise ValueError("workflow_instance_id must not be blank when present")

        if self.kind is InFlightOperationKind.TOOL:
            if self.parent_handle_id is None:
                raise ValueError("TOOL in-flight operation requires parent_handle_id")
            if self.tool_call_id is None:
                raise ValueError("TOOL in-flight operation requires tool_call_id")
            if self.workflow_instance_id is not None:
                raise ValueError("TOOL operation cannot carry workflow_instance_id")
        elif self.kind is InFlightOperationKind.SKILL:
            if self.tool_call_id is not None or self.workflow_instance_id is not None:
                raise ValueError("SKILL operation cannot carry Tool/Workflow identity")
        elif self.tool_call_id is not None:
            raise ValueError("WORKFLOW operation cannot carry tool_call_id")


class InFlightOperationRegistry(Protocol):
    async def register(self, handle: InFlightOperationHandle) -> bool:
        """Register one live operation without discovering/substituting capability."""

    async def complete(
        self,
        operation_handle_id: str,
        *,
        completed_at: datetime,
    ) -> bool:
        """Remove one completed live handle; durable recovery belongs to IU9."""

    async def active_chain(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
    ) -> tuple[InFlightOperationHandle, ...]:
        """Return all currently active handles for one Step."""


class InMemoryInFlightOperationRegistry:
    """Live mechanism implementation for IU7; this is not a durable IU9 store."""

    def __init__(self) -> None:
        self._handles: dict[str, InFlightOperationHandle] = {}

    async def register(self, handle: InFlightOperationHandle) -> bool:
        existing = self._handles.get(handle.operation_handle_id)
        if existing is not None:
            if existing != handle:
                raise ValueError("operation_handle_id cannot be rebound")
            return False
        self._handles[handle.operation_handle_id] = handle
        return True

    async def complete(
        self,
        operation_handle_id: str,
        *,
        completed_at: datetime,
    ) -> bool:
        _require_aware_datetime(completed_at, "completed_at")
        existing = self._handles.get(operation_handle_id)
        if existing is None:
            return False
        if completed_at < existing.started_at:
            raise ValueError("completed_at cannot precede operation started_at")
        del self._handles[operation_handle_id]
        return True

    async def active_chain(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
    ) -> tuple[InFlightOperationHandle, ...]:
        return tuple(
            item
            for item in self._handles.values()
            if item.execution_id == execution_id
            and item.step_execution_id == step_execution_id
        )


class InterruptOutcomeStatus(str, Enum):
    CONFIRMED_STOPPED = "CONFIRMED_STOPPED"
    ALREADY_COMPLETED = "ALREADY_COMPLETED"
    NOT_CANCELLABLE = "NOT_CANCELLABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class InterruptOutcome:
    operation_handle_id: str
    status: InterruptOutcomeStatus
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.operation_handle_id.strip():
            raise ValueError("operation_handle_id must not be blank")
        if not isinstance(self.status, InterruptOutcomeStatus):
            raise ValueError("status must be InterruptOutcomeStatus")  # noqa: TRY004
        _require_reason_codes(self.reason_codes)


class ExecutionInterruptController(Protocol):
    async def interrupt(
        self,
        *,
        handle: InFlightOperationHandle,
        signal: ExecutionControlSignal,
    ) -> InterruptOutcome:
        """Request and confirm an operation interrupt.

        Returning CONFIRMED_STOPPED is stronger than merely requesting cancellation.
        Implementations must not equate Python task cancellation with confirmed
        business-operation termination unless the adapter can establish that fact.
        """


class HierarchicalInterruptStatus(str, Enum):
    NO_ACTIVE_OPERATION = "NO_ACTIVE_OPERATION"
    ORDERED = "ORDERED"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class HierarchicalInterruptSummary:
    execution_id: str
    step_execution_id: str
    status: HierarchicalInterruptStatus
    handles: tuple[InFlightOperationHandle, ...]
    outcomes: tuple[InterruptOutcome, ...]
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.execution_id.strip() or not self.step_execution_id.strip():
            raise ValueError("interrupt summary identifiers must not be blank")
        if not isinstance(self.status, HierarchicalInterruptStatus):
            raise ValueError("status must be HierarchicalInterruptStatus")  # noqa: TRY004
        _require_reason_codes(self.reason_codes)

        for handle in self.handles:
            if (
                handle.execution_id != self.execution_id
                or handle.step_execution_id != self.step_execution_id
            ):
                raise ValueError("interrupt summary handle identity mismatch")

        if self.status is HierarchicalInterruptStatus.NO_ACTIVE_OPERATION:
            if self.handles or self.outcomes:
                raise ValueError("NO_ACTIVE_OPERATION cannot carry handles/outcomes")
            return

        if self.status is HierarchicalInterruptStatus.AMBIGUOUS:
            if self.outcomes:
                raise ValueError("AMBIGUOUS must not claim interrupt outcomes")
            return

        if len(self.outcomes) > len(self.handles):
            raise ValueError("interrupt outcomes cannot exceed observed handles")
        for index, outcome in enumerate(self.outcomes):
            if outcome.operation_handle_id != self.handles[index].operation_handle_id:
                raise ValueError(
                    "interrupt outcomes must follow leaf-first handle order"
                )

        if self.status is HierarchicalInterruptStatus.ORDERED and (
            not self.handles or len(self.outcomes) != len(self.handles)
        ):
            raise ValueError("ORDERED requires one outcome for every ordered handle")


class InFlightInterruptCoordinator:
    """Resolve one active chain and invoke leaf-to-root interrupt authority."""

    def __init__(
        self,
        *,
        registry: InFlightOperationRegistry,
        interrupt_controller: ExecutionInterruptController,
    ) -> None:
        self._registry = registry
        self._interrupt_controller = interrupt_controller

    async def interrupt(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
        signal: ExecutionControlSignal,
    ) -> HierarchicalInterruptSummary:
        if signal.signal_type not in {
            ExecutionControlSignalType.CANCEL,
            ExecutionControlSignalType.PREEMPT,
        }:
            return HierarchicalInterruptSummary(
                execution_id=execution_id,
                step_execution_id=step_execution_id,
                status=HierarchicalInterruptStatus.UNKNOWN,
                handles=(),
                outcomes=(),
                reason_codes=("TERMINAL_CONTROL_REQUIRED",),
            )
        if signal.target_execution_id != execution_id:
            return HierarchicalInterruptSummary(
                execution_id=execution_id,
                step_execution_id=step_execution_id,
                status=HierarchicalInterruptStatus.UNKNOWN,
                handles=(),
                outcomes=(),
                reason_codes=("CONTROL_SIGNAL_TARGET_MISMATCH",),
            )

        try:
            observed = await self._registry.active_chain(
                execution_id=execution_id,
                step_execution_id=step_execution_id,
            )
        except Exception:  # noqa: BLE001
            return HierarchicalInterruptSummary(
                execution_id=execution_id,
                step_execution_id=step_execution_id,
                status=HierarchicalInterruptStatus.UNKNOWN,
                handles=(),
                outcomes=(),
                reason_codes=("INFLIGHT_REGISTRY_UNKNOWN",),
            )

        if not observed:
            return HierarchicalInterruptSummary(
                execution_id=execution_id,
                step_execution_id=step_execution_id,
                status=HierarchicalInterruptStatus.NO_ACTIVE_OPERATION,
                handles=(),
                outcomes=(),
                reason_codes=("NO_ACTIVE_OPERATION",),
            )

        ordered, graph_reason = self._leaf_first_order(
            execution_id=execution_id,
            step_execution_id=step_execution_id,
            handles=observed,
        )
        if ordered is None:
            return HierarchicalInterruptSummary(
                execution_id=execution_id,
                step_execution_id=step_execution_id,
                status=HierarchicalInterruptStatus.AMBIGUOUS,
                handles=observed,
                outcomes=(),
                reason_codes=(graph_reason,),
            )

        outcomes: list[InterruptOutcome] = []
        for handle in ordered:
            try:
                outcome = await self._interrupt_controller.interrupt(
                    handle=handle,
                    signal=signal,
                )
            except Exception:  # noqa: BLE001
                return HierarchicalInterruptSummary(
                    execution_id=execution_id,
                    step_execution_id=step_execution_id,
                    status=HierarchicalInterruptStatus.UNKNOWN,
                    handles=ordered,
                    outcomes=tuple(outcomes),
                    reason_codes=("INTERRUPT_CONTROLLER_UNKNOWN",),
                )
            if (
                not isinstance(outcome, InterruptOutcome)
                or outcome.operation_handle_id != handle.operation_handle_id
            ):
                return HierarchicalInterruptSummary(
                    execution_id=execution_id,
                    step_execution_id=step_execution_id,
                    status=HierarchicalInterruptStatus.UNKNOWN,
                    handles=ordered,
                    outcomes=tuple(outcomes),
                    reason_codes=("INTERRUPT_OUTCOME_IDENTITY_MISMATCH",),
                )
            outcomes.append(outcome)

        return HierarchicalInterruptSummary(
            execution_id=execution_id,
            step_execution_id=step_execution_id,
            status=HierarchicalInterruptStatus.ORDERED,
            handles=ordered,
            outcomes=tuple(outcomes),
            reason_codes=("INTERRUPT_CHAIN_OBSERVED",),
        )

    @staticmethod
    def _leaf_first_order(
        *,
        execution_id: str,
        step_execution_id: str,
        handles: tuple[InFlightOperationHandle, ...],
    ) -> tuple[tuple[InFlightOperationHandle, ...] | None, str]:
        by_id: dict[str, InFlightOperationHandle] = {}
        for handle in handles:
            if (
                handle.execution_id != execution_id
                or handle.step_execution_id != step_execution_id
            ):
                return None, "INFLIGHT_IDENTITY_MISMATCH"
            if handle.operation_handle_id in by_id:
                return None, "DUPLICATE_INFLIGHT_HANDLE"
            by_id[handle.operation_handle_id] = handle

        roots = [item for item in handles if item.parent_handle_id is None]
        if len(roots) != 1:
            return None, "AMBIGUOUS_INFLIGHT_GRAPH"
        root = roots[0]
        if root.kind not in {
            InFlightOperationKind.SKILL,
            InFlightOperationKind.WORKFLOW,
        }:
            return None, "INFLIGHT_OWNER_KIND_INVALID"

        children: dict[str, list[InFlightOperationHandle]] = {
            handle_id: [] for handle_id in by_id
        }
        for handle in handles:
            parent_id = handle.parent_handle_id
            if parent_id is None:
                continue
            if parent_id not in by_id:
                return None, "INFLIGHT_PARENT_MISSING"
            if handle.kind is not InFlightOperationKind.TOOL:
                return None, "INFLIGHT_CHILD_KIND_INVALID"
            children[parent_id].append(handle)

        if any(len(items) > 1 for items in children.values()):
            return None, "AMBIGUOUS_INFLIGHT_GRAPH"

        leaves = [item for item in handles if not children[item.operation_handle_id]]
        if len(leaves) != 1:
            return None, "AMBIGUOUS_INFLIGHT_GRAPH"

        ordered: list[InFlightOperationHandle] = []
        seen: set[str] = set()
        current = leaves[0]
        while True:
            if current.operation_handle_id in seen:
                return None, "INFLIGHT_GRAPH_CYCLE"
            seen.add(current.operation_handle_id)
            ordered.append(current)
            parent_id = current.parent_handle_id
            if parent_id is None:
                break
            current = by_id[parent_id]

        if ordered[-1].operation_handle_id != root.operation_handle_id:
            return None, "AMBIGUOUS_INFLIGHT_GRAPH"
        if len(seen) != len(handles):
            return None, "AMBIGUOUS_INFLIGHT_GRAPH"
        return tuple(ordered), "INTERRUPT_ORDER_RESOLVED"


class ExecutionControlDisposition(str, Enum):
    NO_CONTROL = "NO_CONTROL"
    WAITING_IN_FLIGHT = "WAITING_IN_FLIGHT"
    READY_TO_TERMINALIZE = "READY_TO_TERMINALIZE"
    ALREADY_TERMINAL = "ALREADY_TERMINAL"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ExecutionControlApplication:
    signal: ExecutionControlSignal | None
    disposition: ExecutionControlDisposition
    reason_codes: tuple[str, ...]
    running_step_id: str | None = None
    interrupt_summary: HierarchicalInterruptSummary | None = None
    nonterminal_step_ids_at_latch: tuple[str, ...] = ()
    affected_step_ids: tuple[str, ...] = ()
    preserve_running_step_result: bool = False
    handoff_required: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, ExecutionControlDisposition):
            raise ValueError("disposition must be ExecutionControlDisposition")  # noqa: TRY004
        _require_reason_codes(self.reason_codes)
        _require_unique_ids(
            self.nonterminal_step_ids_at_latch,
            "nonterminal_step_ids_at_latch",
        )
        _require_unique_ids(self.affected_step_ids, "affected_step_ids")
        if not set(self.affected_step_ids).issubset(
            set(self.nonterminal_step_ids_at_latch)
        ):
            raise ValueError("affected_step_ids must be nonterminal at latch")

        if self.running_step_id is not None:
            if not self.running_step_id.strip():
                raise ValueError("running_step_id must not be blank")
            if self.running_step_id not in self.nonterminal_step_ids_at_latch:
                raise ValueError("running_step_id must be nonterminal at latch")
        if self.preserve_running_step_result and self.running_step_id is None:
            raise ValueError("preserve_running_step_result requires running_step_id")

        if self.disposition is ExecutionControlDisposition.NO_CONTROL:
            if self.signal is not None:
                raise ValueError("NO_CONTROL cannot carry signal")
            if self.affected_step_ids or self.interrupt_summary is not None:
                raise ValueError("NO_CONTROL cannot claim control effects")
            if self.handoff_required:
                raise ValueError("NO_CONTROL cannot require handoff")
            return

        if self.signal is None or self.signal.signal_type not in {
            ExecutionControlSignalType.CANCEL,
            ExecutionControlSignalType.PREEMPT,
        }:
            raise ValueError("control application requires CANCEL/PREEMPT signal")

        expected_handoff = self.signal.signal_type is ExecutionControlSignalType.PREEMPT
        if self.handoff_required != expected_handoff:
            raise ValueError("handoff_required must reflect PREEMPT signal authority")

        if (
            self.disposition is ExecutionControlDisposition.READY_TO_TERMINALIZE
            and not self.affected_step_ids
        ):
            raise ValueError("READY_TO_TERMINALIZE requires affected_step_ids")
        if (
            self.disposition is ExecutionControlDisposition.ALREADY_TERMINAL
            and self.affected_step_ids
        ):
            raise ValueError("ALREADY_TERMINAL cannot claim affected_step_ids")


class ExecutionControlApplicationEvaluator:
    """Evaluate interrupt evidence without mutating PreparedExecution.

    Existing Step output, Tool journal truth, and terminal lifecycle evidence are
    observations only. This evaluator never rewrites them.
    """

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

    def evaluate(
        self,
        *,
        latched_control: LatchedExecutionControl,
        prepared_at_latch: PreparedExecution,
        interrupt_summary: HierarchicalInterruptSummary | None,
        prepared_after_interrupt: PreparedExecution | None = None,
    ) -> ExecutionControlApplication:
        signal = latched_control.signal
        handoff_required = signal.signal_type is ExecutionControlSignalType.PREEMPT
        execution_id = prepared_at_latch.execution_context.execution_id

        nonterminal = tuple(
            step.step_id
            for step in prepared_at_latch.steps
            if step.status not in self._TERMINAL_STEP_STATUSES
        )
        pending = tuple(
            step.step_id
            for step in prepared_at_latch.steps
            if step.status is StepExecutionStatus.PENDING
        )
        running = tuple(
            step
            for step in prepared_at_latch.steps
            if step.status is StepExecutionStatus.RUNNING
        )

        if signal.target_execution_id != execution_id:
            return self._application(
                signal=signal,
                disposition=ExecutionControlDisposition.UNKNOWN,
                reason_codes=("CONTROL_SIGNAL_TARGET_MISMATCH",),
                nonterminal=nonterminal,
                affected=(),
                running_step=None,
                summary=interrupt_summary,
                preserve=False,
                handoff_required=handoff_required,
            )

        if prepared_after_interrupt is not None and (
            prepared_after_interrupt.execution_context.execution_id != execution_id
        ):
            return self._application(
                signal=signal,
                disposition=ExecutionControlDisposition.UNKNOWN,
                reason_codes=("LIFECYCLE_RECONCILIATION_IDENTITY_MISMATCH",),
                nonterminal=nonterminal,
                affected=pending,
                running_step=running[0] if len(running) == 1 else None,
                summary=interrupt_summary,
                preserve=bool(running),
                handoff_required=handoff_required,
            )

        if not nonterminal:
            return self._application(
                signal=signal,
                disposition=ExecutionControlDisposition.ALREADY_TERMINAL,
                reason_codes=("CONTROL_ARRIVED_AFTER_EXECUTION_TERMINAL",),
                nonterminal=(),
                affected=(),
                running_step=None,
                summary=interrupt_summary,
                preserve=False,
                handoff_required=handoff_required,
            )

        if len(running) > 1:
            return self._application(
                signal=signal,
                disposition=ExecutionControlDisposition.UNKNOWN,
                reason_codes=("MULTIPLE_RUNNING_STEPS_UNSUPPORTED",),
                nonterminal=nonterminal,
                affected=pending,
                running_step=None,
                summary=interrupt_summary,
                preserve=False,
                handoff_required=handoff_required,
            )

        if not running:
            return self._application(
                signal=signal,
                disposition=ExecutionControlDisposition.READY_TO_TERMINALIZE,
                reason_codes=("CONTROL_AFFECTS_PENDING_WORK",),
                nonterminal=nonterminal,
                affected=pending,
                running_step=None,
                summary=interrupt_summary,
                preserve=False,
                handoff_required=handoff_required,
            )

        running_step = running[0]
        reconciled = self._find_step(
            prepared_after_interrupt,
            running_step.step_id,
        )
        if reconciled is not None and reconciled.status in self._TERMINAL_STEP_STATUSES:
            if pending:
                return self._application(
                    signal=signal,
                    disposition=ExecutionControlDisposition.READY_TO_TERMINALIZE,
                    reason_codes=("RUNNING_STEP_COMPLETION_PRESERVED",),
                    nonterminal=nonterminal,
                    affected=pending,
                    running_step=running_step,
                    summary=interrupt_summary,
                    preserve=True,
                    handoff_required=handoff_required,
                )
            return self._application(
                signal=signal,
                disposition=ExecutionControlDisposition.ALREADY_TERMINAL,
                reason_codes=("LATE_CONTROL_NO_UNFINISHED_WORK_AFFECTED",),
                nonterminal=nonterminal,
                affected=(),
                running_step=running_step,
                summary=interrupt_summary,
                preserve=True,
                handoff_required=handoff_required,
            )

        if interrupt_summary is None:
            return self._application(
                signal=signal,
                disposition=ExecutionControlDisposition.UNKNOWN,
                reason_codes=("INTERRUPT_SUMMARY_MISSING",),
                nonterminal=nonterminal,
                affected=pending,
                running_step=running_step,
                summary=None,
                preserve=True,
                handoff_required=handoff_required,
            )

        if (
            interrupt_summary.execution_id != execution_id
            or interrupt_summary.step_execution_id != running_step.step_execution_id
        ):
            return self._application(
                signal=signal,
                disposition=ExecutionControlDisposition.UNKNOWN,
                reason_codes=("INTERRUPT_SUMMARY_IDENTITY_MISMATCH",),
                nonterminal=nonterminal,
                affected=pending,
                running_step=running_step,
                summary=interrupt_summary,
                preserve=True,
                handoff_required=handoff_required,
            )

        if interrupt_summary.status is HierarchicalInterruptStatus.AMBIGUOUS:
            return self._application(
                signal=signal,
                disposition=ExecutionControlDisposition.UNKNOWN,
                reason_codes=("AMBIGUOUS_INFLIGHT_GRAPH",),
                nonterminal=nonterminal,
                affected=pending,
                running_step=running_step,
                summary=interrupt_summary,
                preserve=True,
                handoff_required=handoff_required,
            )
        if interrupt_summary.status is HierarchicalInterruptStatus.UNKNOWN:
            return self._application(
                signal=signal,
                disposition=ExecutionControlDisposition.UNKNOWN,
                reason_codes=("INTERRUPT_APPLICATION_UNKNOWN",),
                nonterminal=nonterminal,
                affected=pending,
                running_step=running_step,
                summary=interrupt_summary,
                preserve=True,
                handoff_required=handoff_required,
            )
        if interrupt_summary.status is HierarchicalInterruptStatus.NO_ACTIVE_OPERATION:
            return self._application(
                signal=signal,
                disposition=ExecutionControlDisposition.WAITING_IN_FLIGHT,
                reason_codes=("RUNNING_STEP_REQUIRES_COMPLETION_RECONCILIATION",),
                nonterminal=nonterminal,
                affected=pending,
                running_step=running_step,
                summary=interrupt_summary,
                preserve=True,
                handoff_required=handoff_required,
            )

        statuses = tuple(item.status for item in interrupt_summary.outcomes)
        if InterruptOutcomeStatus.UNKNOWN in statuses:
            return self._application(
                signal=signal,
                disposition=ExecutionControlDisposition.UNKNOWN,
                reason_codes=("INTERRUPT_OUTCOME_UNKNOWN",),
                nonterminal=nonterminal,
                affected=pending,
                running_step=running_step,
                summary=interrupt_summary,
                preserve=True,
                handoff_required=handoff_required,
            )
        if InterruptOutcomeStatus.NOT_CANCELLABLE in statuses:
            return self._application(
                signal=signal,
                disposition=ExecutionControlDisposition.WAITING_IN_FLIGHT,
                reason_codes=("INFLIGHT_OPERATION_NOT_CANCELLABLE",),
                nonterminal=nonterminal,
                affected=pending,
                running_step=running_step,
                summary=interrupt_summary,
                preserve=True,
                handoff_required=handoff_required,
            )

        owner_outcome = interrupt_summary.outcomes[-1]
        if owner_outcome.status is InterruptOutcomeStatus.ALREADY_COMPLETED:
            return self._application(
                signal=signal,
                disposition=ExecutionControlDisposition.WAITING_IN_FLIGHT,
                reason_codes=("OWNER_COMPLETED_AWAITING_LIFECYCLE_COMMIT",),
                nonterminal=nonterminal,
                affected=pending,
                running_step=running_step,
                summary=interrupt_summary,
                preserve=True,
                handoff_required=handoff_required,
            )

        if owner_outcome.status is InterruptOutcomeStatus.CONFIRMED_STOPPED:
            affected = (running_step.step_id, *pending)
            return self._application(
                signal=signal,
                disposition=ExecutionControlDisposition.READY_TO_TERMINALIZE,
                reason_codes=("CONTROL_SAFE_BOUNDARY_CONFIRMED",),
                nonterminal=nonterminal,
                affected=affected,
                running_step=running_step,
                summary=interrupt_summary,
                preserve=False,
                handoff_required=handoff_required,
            )

        return self._application(
            signal=signal,
            disposition=ExecutionControlDisposition.UNKNOWN,
            reason_codes=("INTERRUPT_OUTCOME_UNSUPPORTED",),
            nonterminal=nonterminal,
            affected=pending,
            running_step=running_step,
            summary=interrupt_summary,
            preserve=True,
            handoff_required=handoff_required,
        )

    @staticmethod
    def _find_step(
        prepared: PreparedExecution | None,
        step_id: str,
    ) -> StepLifecycleSnapshot | None:
        if prepared is None:
            return None
        matches = [step for step in prepared.steps if step.step_id == step_id]
        if len(matches) != 1:
            return None
        return matches[0]

    @staticmethod
    def _application(
        *,
        signal: ExecutionControlSignal,
        disposition: ExecutionControlDisposition,
        reason_codes: tuple[str, ...],
        nonterminal: tuple[str, ...],
        affected: tuple[str, ...],
        running_step: StepLifecycleSnapshot | None,
        summary: HierarchicalInterruptSummary | None,
        preserve: bool,
        handoff_required: bool,
    ) -> ExecutionControlApplication:
        return ExecutionControlApplication(
            signal=signal,
            disposition=disposition,
            reason_codes=reason_codes,
            running_step_id=(None if running_step is None else running_step.step_id),
            interrupt_summary=summary,
            nonterminal_step_ids_at_latch=nonterminal,
            affected_step_ids=affected,
            preserve_running_step_result=preserve,
            handoff_required=handoff_required,
        )


def _require_aware_datetime(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_reason_codes(reason_codes: tuple[str, ...]) -> None:
    if not reason_codes or any(not reason.strip() for reason in reason_codes):
        raise ValueError("reason_codes must contain non-blank values")


def _require_unique_ids(values: tuple[str, ...], field_name: str) -> None:
    if any(not value.strip() for value in values):
        raise ValueError(f"{field_name} must contain non-blank values")
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must not contain duplicates")
