"""M5-IU10 Formal Implementation integration runtime.

This module wires already-frozen M5 authorities. It does not execute capabilities,
recompute policy, invent recovery semantics, or enter M6.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from datetime import UTC, datetime
from enum import Enum

from runtime.contracts.enums import ExecutionPlanStatus
from runtime.contracts.planning import ApprovedActionPlan
from runtime.execution.aggregation_authority import (
    ExecutionAggregationAuthority,
    ExecutionAggregationEligibilityStatus,
)
from runtime.execution.aggregation_result import (
    CanonicalExecutionResultProjector,
    DurableControlTerminalToolEvidenceReader,
    ExecutionAggregationProjectionError,
    ExecutionAggregationRunResult,
    ExecutionAggregator,
)
from runtime.execution.capability_execution import StepCapabilityExecutor
from runtime.execution.concurrency_runtime import ToolConcurrencyRuntime
from runtime.execution.control import ExecutionControlWatcher
from runtime.execution.control_applicability import (
    DurableAggregationControlAuthority,
    DurableControlApplicabilityRecorder,
    DurableControlApplicabilityStore,
)
from runtime.execution.control_application import (
    ExecutionControlApplicationEvaluator,
    InFlightInterruptCoordinator,
)
from runtime.execution.control_lifecycle import ExecutionControlLifecycleService
from runtime.execution.control_runtime import ExecutionControlCoordinator
from runtime.execution.foundation import (
    ExecutionLifecycleService,
    ExecutionTerminalObserver,
    PreparedExecution,
)
from runtime.execution.recovery import ExecutionRecoveryClaim
from runtime.execution.recovery_evidence import (
    DurableExecutionControlLatch,
    DurableReliabilityEvidenceStore,
    DurableTerminalControlStore,
    DurableToolJournalEvidence,
)
from runtime.execution.invocation import ToolInvocationJournalPersistence
from runtime.execution.reliability_coordinator import (
    RecoveredStepReliabilityRunResult,
    RecoveredWorkflowReliabilityRunResult,
    StepReliabilityRunResult,
)
from runtime.execution.scheduler import (
    SequentialStepScheduler,
    StepScheduleDecision,
    StepScheduleStatus,
)
from runtime.execution.step_completion import (
    RunningStepCompletionCoordinator,
    RunningStepCompletionDecision,
    RunningStepCompletionStatus,
    TerminalStepCompletionCoordinator,
    TerminalStepCompletionStatus,
)


class LiveExecutionBindingsBuilder(Protocol):
    def build(
        self,
        *,
        recovery_claim: ExecutionRecoveryClaim,
        tool_journal_persistence: ToolInvocationJournalPersistence,
    ) -> StepCapabilityExecutor:
        """Build live execution authorities around the exact durable journal."""


@dataclass(frozen=True, slots=True)
class DurableLiveExecutionBindings:
    """Live execution bindings whose Tool journal is claim-bound and durable."""

    step_executor: StepCapabilityExecutor
    tool_journal_persistence: DurableToolJournalEvidence


class DurableLiveExecutionBindingsFactory:
    """Enforce durable Tool journaling on the normal live execution path."""

    def __init__(
        self,
        *,
        builder: LiveExecutionBindingsBuilder,
        reliability_store: DurableReliabilityEvidenceStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._builder = builder
        self._reliability_store = reliability_store
        self._clock = clock

    def create(
        self,
        recovery_claim: ExecutionRecoveryClaim,
    ) -> DurableLiveExecutionBindings:
        journal = DurableToolJournalEvidence(
            store=self._reliability_store,
            execution_id=recovery_claim.execution_id,
            recovery_claim=recovery_claim,
            clock=self._clock,
        )
        executor = self._builder.build(
            recovery_claim=recovery_claim,
            tool_journal_persistence=journal,
        )
        if not isinstance(executor, StepCapabilityExecutor):
            raise TypeError("live execution bindings builder returned invalid executor")
        if executor.tool_journal_persistence is not journal:
            raise ValueError(
                "live StepCapabilityExecutor must use exact durable Tool journal"
            )
        return DurableLiveExecutionBindings(
            step_executor=executor,
            tool_journal_persistence=journal,
        )


class DurableControlRuntimeFactory:
    """Build a durable IU7 control path with CA-04 truth bound to one claim."""

    def __init__(
        self,
        *,
        watcher: ExecutionControlWatcher,
        control_store: DurableTerminalControlStore,
        control_applicability_store: DurableControlApplicabilityStore,
        interrupt_coordinator: InFlightInterruptCoordinator,
        application_evaluator: ExecutionControlApplicationEvaluator,
        lifecycle_service: ExecutionControlLifecycleService,
        clock: Callable[[], datetime] | None = None,
        tool_concurrency_runtime: ToolConcurrencyRuntime | None = None,
        terminal_observer: ExecutionTerminalObserver | None = None,
    ) -> None:
        self._watcher = watcher
        self._control_store = control_store
        self._control_applicability_store = control_applicability_store
        self._interrupt_coordinator = interrupt_coordinator
        self._application_evaluator = application_evaluator
        self._lifecycle_service = lifecycle_service
        self._clock = clock or (lambda: datetime.now(UTC))
        self._tool_concurrency_runtime = tool_concurrency_runtime
        self._terminal_observer = terminal_observer

    def create(
        self,
        recovery_claim: ExecutionRecoveryClaim,
    ) -> ExecutionControlCoordinator:
        return ExecutionControlCoordinator(
            watcher=self._watcher,
            latch=DurableExecutionControlLatch(
                store=self._control_store,
                recovery_claim=recovery_claim,
            ),
            interrupt_coordinator=self._interrupt_coordinator,
            application_evaluator=self._application_evaluator,
            lifecycle_service=self._lifecycle_service,
            clock=self._clock,
            tool_concurrency_runtime=self._tool_concurrency_runtime,
            terminal_observer=self._terminal_observer,
            control_applicability_recorder=DurableControlApplicabilityRecorder(
                store=self._control_applicability_store,
                recovery_claim=recovery_claim,
            ),
        )


class DurableRecoveryControlRuntimeFactory(DurableControlRuntimeFactory):
    """Recovery-facing structural adapter for M5RecoveryRuntime."""


@dataclass(frozen=True, slots=True)
class DurableM5ExecutionBindings:
    """Claim-coherent live Tool and terminal-control authorities."""

    live_execution: DurableLiveExecutionBindings
    control_runtime: ExecutionControlCoordinator


class DurableM5ExecutionBindingsFactory:
    """Create live Tool journaling and control authority from one exact claim."""

    def __init__(
        self,
        *,
        live_execution_factory: DurableLiveExecutionBindingsFactory,
        control_runtime_factory: DurableControlRuntimeFactory,
    ) -> None:
        self._live_execution_factory = live_execution_factory
        self._control_runtime_factory = control_runtime_factory

    def create(
        self,
        recovery_claim: ExecutionRecoveryClaim,
    ) -> DurableM5ExecutionBindings:
        live_execution = self._live_execution_factory.create(recovery_claim)
        control_runtime = self._control_runtime_factory.create(recovery_claim)
        if not isinstance(control_runtime, ExecutionControlCoordinator):
            raise TypeError("durable control runtime factory returned invalid result")
        return DurableM5ExecutionBindings(
            live_execution=live_execution,
            control_runtime=control_runtime,
        )


class M5ExecutionAggregationRuntimeStatus(str, Enum):
    STEP_READY = "STEP_READY"
    WAITING = "WAITING"
    BLOCKED_UNKNOWN = "BLOCKED_UNKNOWN"
    AGGREGATED = "AGGREGATED"


@dataclass(frozen=True, slots=True)
class M5ExecutionAggregationOutcome:
    status: M5ExecutionAggregationRuntimeStatus
    reason_codes: tuple[str, ...]
    prepared: PreparedExecution
    schedule_decision: StepScheduleDecision | None = None
    running_completion: RunningStepCompletionDecision | None = None
    aggregation_result: ExecutionAggregationRunResult | None = None
    terminalized_step_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, M5ExecutionAggregationRuntimeStatus):
            raise TypeError("status must be M5ExecutionAggregationRuntimeStatus")
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        if len(set(self.terminalized_step_ids)) != len(
            self.terminalized_step_ids
        ) or any(not step_id.strip() for step_id in self.terminalized_step_ids):
            raise ValueError("terminalized_step_ids must be unique non-blank ids")

        if self.status is M5ExecutionAggregationRuntimeStatus.AGGREGATED:
            result = self.aggregation_result
            if result is None:
                raise ValueError("AGGREGATED outcome requires aggregation_result")
            if result.prepared != self.prepared:
                raise ValueError(
                    "AGGREGATED outcome must expose exact aggregation prepared state"
                )
            if (
                result.eligibility.status
                is not ExecutionAggregationEligibilityStatus.READY_EXISTING_TERMINAL
            ):
                raise ValueError(
                    "AGGREGATED outcome requires READY_EXISTING_TERMINAL authority"
                )
        elif self.aggregation_result is not None:
            raise ValueError("only AGGREGATED outcome can carry aggregation_result")

        if self.status is M5ExecutionAggregationRuntimeStatus.STEP_READY:
            if (
                self.schedule_decision is None
                or self.schedule_decision.status is not StepScheduleStatus.READY
            ):
                raise ValueError(
                    "STEP_READY outcome requires exact READY schedule decision"
                )


class M5ExecutionAggregationRuntime:
    """Formal IU10 composition over the frozen Step and aggregation authorities."""

    _TERMINAL_EXECUTION_STATUSES = frozenset(
        status.value for status in ExecutionPlanStatus
    )

    def __init__(
        self,
        *,
        lifecycle_service: ExecutionLifecycleService,
        control_store: DurableTerminalControlStore,
        control_applicability_store: DurableControlApplicabilityStore,
        reliability_store: DurableReliabilityEvidenceStore,
        scheduler: SequentialStepScheduler | None = None,
    ) -> None:
        scheduler = scheduler or SequentialStepScheduler()
        self._terminal_completion = TerminalStepCompletionCoordinator(
            scheduler=scheduler,
            lifecycle_service=lifecycle_service,
        )
        self._running_completion = RunningStepCompletionCoordinator(
            lifecycle_service=lifecycle_service
        )
        self._aggregator = ExecutionAggregator(
            authority=ExecutionAggregationAuthority(),
            lifecycle_service=lifecycle_service,
            projector=CanonicalExecutionResultProjector(
                control_tool_evidence_reader=DurableControlTerminalToolEvidenceReader(
                    store=reliability_store
                )
            ),
            control_authority=DurableAggregationControlAuthority(
                control_store=control_store,
                applicability_store=control_applicability_store,
            ),
        )

    async def advance(
        self,
        *,
        approved_plan: ApprovedActionPlan,
        prepared: PreparedExecution,
        at: datetime,
    ) -> M5ExecutionAggregationOutcome:
        """Advance terminal Step closure and aggregate only when exact truth is ready."""

        if prepared.execution_record.status in self._TERMINAL_EXECUTION_STATUSES:
            return await self._aggregate(
                approved_plan=approved_plan,
                prepared=prepared,
                at=at,
                terminalized_step_ids=(),
            )

        if prepared.execution_record.status != "RUNNING":
            return M5ExecutionAggregationOutcome(
                status=M5ExecutionAggregationRuntimeStatus.BLOCKED_UNKNOWN,
                reason_codes=("IU10_EXECUTION_NOT_RUNNING_OR_TERMINAL",),
                prepared=prepared,
            )

        current = prepared
        terminalized_step_ids: list[str] = []

        while True:
            decision = await self._terminal_completion.advance(
                approved_plan=approved_plan,
                prepared=current,
                at=at,
            )

            if decision.status is TerminalStepCompletionStatus.TERMINALIZED:
                step_id = decision.terminalized_step_id
                if step_id is None or step_id in terminalized_step_ids:
                    return M5ExecutionAggregationOutcome(
                        status=M5ExecutionAggregationRuntimeStatus.BLOCKED_UNKNOWN,
                        reason_codes=("IU10_TERMINAL_STEP_PROGRESS_UNKNOWN",),
                        prepared=decision.prepared,
                        schedule_decision=decision.schedule_decision,
                        terminalized_step_ids=tuple(terminalized_step_ids),
                    )
                terminalized_step_ids.append(step_id)
                current = decision.prepared
                continue

            if decision.status is TerminalStepCompletionStatus.READY:
                return M5ExecutionAggregationOutcome(
                    status=M5ExecutionAggregationRuntimeStatus.STEP_READY,
                    reason_codes=decision.reason_codes,
                    prepared=decision.prepared,
                    schedule_decision=decision.schedule_decision,
                    terminalized_step_ids=tuple(terminalized_step_ids),
                )

            if decision.status is TerminalStepCompletionStatus.WAITING:
                return M5ExecutionAggregationOutcome(
                    status=M5ExecutionAggregationRuntimeStatus.WAITING,
                    reason_codes=decision.reason_codes,
                    prepared=decision.prepared,
                    schedule_decision=decision.schedule_decision,
                    terminalized_step_ids=tuple(terminalized_step_ids),
                )

            if decision.status is TerminalStepCompletionStatus.BLOCKED_UNKNOWN:
                return M5ExecutionAggregationOutcome(
                    status=M5ExecutionAggregationRuntimeStatus.BLOCKED_UNKNOWN,
                    reason_codes=decision.reason_codes,
                    prepared=decision.prepared,
                    schedule_decision=decision.schedule_decision,
                    terminalized_step_ids=tuple(terminalized_step_ids),
                )

            if decision.status is TerminalStepCompletionStatus.COMPLETE:
                return await self._aggregate(
                    approved_plan=approved_plan,
                    prepared=decision.prepared,
                    at=at,
                    terminalized_step_ids=tuple(terminalized_step_ids),
                    schedule_decision=decision.schedule_decision,
                )

            return M5ExecutionAggregationOutcome(
                status=M5ExecutionAggregationRuntimeStatus.BLOCKED_UNKNOWN,
                reason_codes=("IU10_TERMINAL_STEP_DECISION_UNKNOWN",),
                prepared=decision.prepared,
                schedule_decision=decision.schedule_decision,
                terminalized_step_ids=tuple(terminalized_step_ids),
            )

    async def complete_running_step(
        self,
        *,
        approved_plan: ApprovedActionPlan,
        prepared: PreparedExecution,
        reliability_result: (
            StepReliabilityRunResult
            | RecoveredStepReliabilityRunResult
            | RecoveredWorkflowReliabilityRunResult
        ),
        at: datetime,
    ) -> M5ExecutionAggregationOutcome:
        """Commit one IU6-authorized running Step, then re-enter the same IU10 path."""

        completion = await self._running_completion.complete(
            prepared=prepared,
            reliability_result=reliability_result,
            at=at,
        )

        if completion.status is RunningStepCompletionStatus.TERMINALIZED:
            outcome = await self.advance(
                approved_plan=approved_plan,
                prepared=completion.prepared,
                at=at,
            )
            return M5ExecutionAggregationOutcome(
                status=outcome.status,
                reason_codes=outcome.reason_codes,
                prepared=outcome.prepared,
                schedule_decision=outcome.schedule_decision,
                running_completion=completion,
                aggregation_result=outcome.aggregation_result,
                terminalized_step_ids=outcome.terminalized_step_ids,
            )

        if completion.status in {
            RunningStepCompletionStatus.KEEP_RUNNING,
            RunningStepCompletionStatus.WAIT_RECOVERY,
        }:
            return M5ExecutionAggregationOutcome(
                status=M5ExecutionAggregationRuntimeStatus.WAITING,
                reason_codes=completion.reason_codes,
                prepared=completion.prepared,
                running_completion=completion,
            )

        return M5ExecutionAggregationOutcome(
            status=M5ExecutionAggregationRuntimeStatus.BLOCKED_UNKNOWN,
            reason_codes=completion.reason_codes,
            prepared=completion.prepared,
            running_completion=completion,
        )

    async def _aggregate(
        self,
        *,
        approved_plan: ApprovedActionPlan,
        prepared: PreparedExecution,
        at: datetime,
        terminalized_step_ids: tuple[str, ...],
        schedule_decision: StepScheduleDecision | None = None,
    ) -> M5ExecutionAggregationOutcome:
        try:
            result = await self._aggregator.aggregate(
                approved_plan=approved_plan,
                prepared=prepared,
                at=at,
            )
        except ExecutionAggregationProjectionError as exc:
            return M5ExecutionAggregationOutcome(
                status=M5ExecutionAggregationRuntimeStatus.BLOCKED_UNKNOWN,
                reason_codes=(exc.reason_code,),
                prepared=prepared,
                schedule_decision=schedule_decision,
                terminalized_step_ids=terminalized_step_ids,
            )

        return M5ExecutionAggregationOutcome(
            status=M5ExecutionAggregationRuntimeStatus.AGGREGATED,
            reason_codes=("IU10_CANONICAL_EXECUTION_RESULT_PUBLISHED",),
            prepared=result.prepared,
            schedule_decision=schedule_decision,
            aggregation_result=result,
            terminalized_step_ids=terminalized_step_ids,
        )
