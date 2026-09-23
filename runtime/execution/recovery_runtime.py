"""M5-IU9 Formal Implementation recovery runtime.

This module wires the frozen CA-01..CA-06 recovery authorities back into the
existing M5 execution boundaries. It does not replan, aggregate IU10 results,
invoke M6, or substitute capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from runtime.contracts import ApprovedActionPlan
from runtime.contracts.planning import ActionStep
from runtime.execution.capability_execution import (
    CapabilityExecutionStatus,
    StepCapabilityExecutionOutcome,
    StepCapabilityExecutor,
)
from runtime.execution.capability_resolution import (
    ApprovedStepCapabilityProjector,
    CapabilityResolutionStatus,
    StepCapabilityResolver,
)
from runtime.execution.control import ObservedExecutionControl
from runtime.execution.control_application import InFlightOperationKind
from runtime.execution.control_runtime import (
    ExecutionControlCoordinator,
    ExecutionControlDisposition,
    ExecutionControlRuntimeResult,
)
from runtime.execution.foundation import PreparedExecution, StepLifecycleSnapshot
from runtime.execution.recovery import (
    CurrentRecoveryEpochSideEffectAdmissionGuard,
    ExecutionRecoveryClaim,
    ExecutionRecoverySnapshot,
    ExecutionRecoverySnapshotStore,
    RecoveryClaimAuthority,
)
from runtime.execution.recovery_evidence import (
    DurableControlReadStatus,
    DurableInFlightEvidenceStore,
    DurableReliabilityEvidenceStore,
    DurableStepAttemptSequenceAuthority,
    DurableTerminalControlStore,
    InFlightEvidenceState,
)
from runtime.execution.recovery_resource_lock import (
    DurableOperationResourceBindingStore,
    ResourceRecoveryStatus,
    ToolResourceRecoveryCoordinator,
)
from runtime.execution.recovery_workflow import (
    RecoveryCoordinator,
    RecoveryDecision,
    RecoveryDisposition,
    StepRecoveryReplayEvaluator,
    WorkflowRecoveryCheckpointStore,
    WorkflowVersionAuthority,
)
from runtime.execution.scheduler import (
    SequentialStepScheduler,
    StepScheduleDecision,
)


class M5RecoveryRuntimeStatus(str, Enum):
    TERMINAL_NO_ACTION = "TERMINAL_NO_ACTION"
    CONTROL_APPLIED = "CONTROL_APPLIED"
    CONTROL_WAITING = "CONTROL_WAITING"
    WAIT_RECONCILIATION = "WAIT_RECONCILIATION"
    WORKFLOW_RESUMED = "WORKFLOW_RESUMED"
    SKILL_RETRIED = "SKILL_RETRIED"
    SCHEDULER_REENTERED = "SCHEDULER_REENTERED"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class M5RecoveryRuntimeOutcome:
    status: M5RecoveryRuntimeStatus
    reason_codes: tuple[str, ...]
    recovery_decision: RecoveryDecision
    prepared: PreparedExecution | None = None
    capability_outcome: StepCapabilityExecutionOutcome | None = None
    schedule_decision: StepScheduleDecision | None = None
    control_result: ExecutionControlRuntimeResult | None = None

    def __post_init__(self) -> None:
        if not self.reason_codes or any(not item.strip() for item in self.reason_codes):
            raise ValueError("reason_codes must contain non-blank values")


class ApprovedPlanWorkflowVersionAuthority(WorkflowVersionAuthority):
    """Return the exact approved Workflow version for the recovered Step."""

    def __init__(
        self,
        *,
        approved_plan: ApprovedActionPlan,
        snapshot: ExecutionRecoverySnapshot,
        projector: ApprovedStepCapabilityProjector | None = None,
    ) -> None:
        if approved_plan.plan_id != snapshot.execution_record.plan_id:
            raise ValueError("approved plan does not match recovery snapshot plan_id")
        if approved_plan.request_id != snapshot.execution_record.request_id:
            raise ValueError("approved plan does not match recovery snapshot request_id")
        self._approved_plan = approved_plan
        self._snapshot = snapshot
        self._projector = projector or ApprovedStepCapabilityProjector()

    async def expected_version(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
        workflow_id: str,
    ) -> str | None:
        if execution_id != self._snapshot.execution_id:
            return None
        lifecycle = self._step_snapshot(step_execution_id)
        if lifecycle is None or lifecycle.workflow_id != workflow_id:
            return None
        step = self._plan_step(lifecycle.step_id)
        if step is None:
            return None
        try:
            references = self._projector.project(
                approved_plan=self._approved_plan,
                step=step,
            )
        except Exception:  # noqa: BLE001
            return None
        if references.workflow is None:
            return None
        if references.workflow.capability_id != workflow_id:
            return None
        return references.workflow.version

    def _step_snapshot(
        self,
        step_execution_id: str,
    ) -> StepLifecycleSnapshot | None:
        matches = tuple(
            item
            for item in self._snapshot.steps
            if item.step_execution_id == step_execution_id
        )
        return matches[0] if len(matches) == 1 else None

    def _plan_step(self, step_id: str) -> ActionStep | None:
        matches = tuple(
            item for item in self._approved_plan.steps if item.step_id == step_id
        )
        return matches[0] if len(matches) == 1 else None


class M5RecoveryRuntime:
    """Formal IU9 recovery integration using only frozen M5 authorities."""

    def __init__(
        self,
        *,
        claim_authority: RecoveryClaimAuthority,
        snapshot_store: ExecutionRecoverySnapshotStore,
        control_store: DurableTerminalControlStore,
        inflight_store: DurableInFlightEvidenceStore,
        resource_binding_store: DurableOperationResourceBindingStore,
        workflow_checkpoint_store: WorkflowRecoveryCheckpointStore,
        step_replay_evaluator: StepRecoveryReplayEvaluator,
        step_resolver: StepCapabilityResolver,
        step_executor: StepCapabilityExecutor,
        scheduler: SequentialStepScheduler,
        reliability_store: DurableReliabilityEvidenceStore,
        tool_resource_recovery: ToolResourceRecoveryCoordinator | None = None,
        control_runtime: ExecutionControlCoordinator | None = None,
    ) -> None:
        self._claim_authority = claim_authority
        self._snapshot_store = snapshot_store
        self._control_store = control_store
        self._inflight_store = inflight_store
        self._resource_binding_store = resource_binding_store
        self._workflow_checkpoint_store = workflow_checkpoint_store
        self._step_replay_evaluator = step_replay_evaluator
        self._step_resolver = step_resolver
        self._step_executor = step_executor
        self._scheduler = scheduler
        self._reliability_store = reliability_store
        self._tool_resource_recovery = tool_resource_recovery
        self._control_runtime = control_runtime

    async def recover(
        self,
        *,
        approved_plan: ApprovedActionPlan,
        recovery_claim: ExecutionRecoveryClaim,
        recovered_at: datetime,
    ) -> M5RecoveryRuntimeOutcome:
        snapshot = await self._load_snapshot(recovery_claim)
        if snapshot is None:
            return self._unknown_decision(
                recovery_claim,
                "RECOVERY_RUNTIME_SNAPSHOT_UNAVAILABLE",
            )
        if not self._plan_matches_snapshot(approved_plan, snapshot):
            return self._unknown_from_snapshot(
                snapshot,
                "RECOVERY_RUNTIME_APPROVED_PLAN_MISMATCH",
            )

        coordinator = RecoveryCoordinator(
            claim_authority=self._claim_authority,
            snapshot_store=self._snapshot_store,
            control_store=self._control_store,
            inflight_store=self._inflight_store,
            resource_binding_store=self._resource_binding_store,
            workflow_checkpoint_store=self._workflow_checkpoint_store,
            workflow_version_authority=ApprovedPlanWorkflowVersionAuthority(
                approved_plan=approved_plan,
                snapshot=snapshot,
            ),
            step_replay_evaluator=self._step_replay_evaluator,
        )

        decision = await coordinator.decide(
            recovery_claim=recovery_claim,
            recovered_at=recovered_at,
        )

        if (
            decision.disposition is RecoveryDisposition.WAIT_RECONCILIATION
            and self._tool_resource_recovery is not None
        ):
            await self._reconcile_tools_once(
                execution_id=recovery_claim.execution_id,
                recovery_claim=recovery_claim,
                recovered_at=recovered_at,
            )
            decision = await coordinator.decide(
                recovery_claim=recovery_claim,
                recovered_at=recovered_at,
            )

        prepared = snapshot.restore_prepared_execution()

        if decision.disposition is RecoveryDisposition.TERMINAL_NO_ACTION:
            return M5RecoveryRuntimeOutcome(
                status=M5RecoveryRuntimeStatus.TERMINAL_NO_ACTION,
                reason_codes=decision.reason_codes,
                recovery_decision=decision,
                prepared=prepared,
            )

        if decision.disposition is RecoveryDisposition.APPLY_LATCHED_CONTROL:
            return await self._apply_control(
                prepared=prepared,
                decision=decision,
            )

        if decision.disposition is RecoveryDisposition.WAIT_RECONCILIATION:
            return M5RecoveryRuntimeOutcome(
                status=M5RecoveryRuntimeStatus.WAIT_RECONCILIATION,
                reason_codes=decision.reason_codes,
                recovery_decision=decision,
                prepared=prepared,
            )

        if decision.disposition is RecoveryDisposition.UNKNOWN_BLOCKED:
            return M5RecoveryRuntimeOutcome(
                status=M5RecoveryRuntimeStatus.UNKNOWN,
                reason_codes=decision.reason_codes,
                recovery_decision=decision,
                prepared=prepared,
            )

        if decision.disposition is RecoveryDisposition.RESUME_SCHEDULING:
            schedule = await self._scheduler.next_step(
                approved_plan=approved_plan,
                prepared=prepared,
            )
            return M5RecoveryRuntimeOutcome(
                status=M5RecoveryRuntimeStatus.SCHEDULER_REENTERED,
                reason_codes=("RECOVERY_REENTERED_EXISTING_SCHEDULER",),
                recovery_decision=decision,
                prepared=prepared,
                schedule_decision=schedule,
            )

        step_snapshot = self._running_step(prepared, decision)
        if step_snapshot is None:
            return M5RecoveryRuntimeOutcome(
                status=M5RecoveryRuntimeStatus.UNKNOWN,
                reason_codes=("RECOVERY_RUNTIME_RUNNING_STEP_MISSING",),
                recovery_decision=decision,
                prepared=prepared,
            )
        step = self._plan_step(approved_plan, step_snapshot.step_id)
        if step is None:
            return M5RecoveryRuntimeOutcome(
                status=M5RecoveryRuntimeStatus.UNKNOWN,
                reason_codes=("RECOVERY_RUNTIME_APPROVED_STEP_MISSING",),
                recovery_decision=decision,
                prepared=prepared,
            )

        resolution = await self._step_resolver.resolve(
            approved_plan=approved_plan,
            step=step,
            execution_context=prepared.execution_context,
            current_state=prepared.execution_context.current_state,
        )
        if (
            resolution.status is not CapabilityResolutionStatus.RESOLVED
            or resolution.resolved is None
        ):
            status = (
                M5RecoveryRuntimeStatus.BLOCKED
                if resolution.status is CapabilityResolutionStatus.BLOCKED
                else M5RecoveryRuntimeStatus.UNKNOWN
            )
            return M5RecoveryRuntimeOutcome(
                status=status,
                reason_codes=resolution.reason_codes,
                recovery_decision=decision,
                prepared=prepared,
            )

        guard = CurrentRecoveryEpochSideEffectAdmissionGuard(
            claim_authority=self._claim_authority,
            recovery_claim=recovery_claim,
        )
        attempt_authority = DurableStepAttemptSequenceAuthority(
            store=self._reliability_store,
            execution_id=recovery_claim.execution_id,
            recovery_claim=recovery_claim,
        )
        current_attempt = await attempt_authority.current_attempt(
            step_snapshot.step_execution_id
        )
        if current_attempt is None:
            return M5RecoveryRuntimeOutcome(
                status=M5RecoveryRuntimeStatus.UNKNOWN,
                reason_codes=("RECOVERY_STEP_ATTEMPT_CURSOR_MISSING",),
                recovery_decision=decision,
                prepared=prepared,
            )
        prior_journal = await self._reliability_store.load_tool_journal(
            execution_id=recovery_claim.execution_id,
            step_execution_id=step_snapshot.step_execution_id,
            step_attempt_number=current_attempt,
        )

        if decision.disposition is RecoveryDisposition.RESUME_WORKFLOW:
            request = decision.workflow_resume_request
            if request is None:
                return M5RecoveryRuntimeOutcome(
                    status=M5RecoveryRuntimeStatus.UNKNOWN,
                    reason_codes=("RECOVERY_WORKFLOW_RESUME_REQUEST_MISSING",),
                    recovery_decision=decision,
                    prepared=prepared,
                )
            outcome = await self._step_executor.resume_workflow_from_checkpoint(
                approved_plan=approved_plan,
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolution.resolved,
                execution_context=prepared.execution_context,
                resume_request=request,
                attempt_number=current_attempt,
                prior_attempt_journal=prior_journal,
                side_effect_admission_guard=guard,
            )
            return self._capability_runtime_outcome(
                success_status=M5RecoveryRuntimeStatus.WORKFLOW_RESUMED,
                outcome=outcome,
                decision=decision,
                prepared=prepared,
            )

        if decision.disposition is RecoveryDisposition.RETRY_STEP:
            claim = await attempt_authority.claim_next(
                step_execution_id=step_snapshot.step_execution_id,
                expected_current_attempt=current_attempt,
            )
            if claim.next_attempt is None:
                return M5RecoveryRuntimeOutcome(
                    status=M5RecoveryRuntimeStatus.UNKNOWN,
                    reason_codes=claim.reason_codes,
                    recovery_decision=decision,
                    prepared=prepared,
                )
            outcome = await self._step_executor.execute(
                approved_plan=approved_plan,
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolution.resolved,
                execution_context=prepared.execution_context,
                attempt_number=claim.next_attempt,
                prior_attempt_journal=prior_journal,
                side_effect_admission_guard=guard,
            )
            return self._capability_runtime_outcome(
                success_status=M5RecoveryRuntimeStatus.SKILL_RETRIED,
                outcome=outcome,
                decision=decision,
                prepared=prepared,
            )

        return M5RecoveryRuntimeOutcome(
            status=M5RecoveryRuntimeStatus.UNKNOWN,
            reason_codes=("RECOVERY_RUNTIME_DISPOSITION_UNHANDLED",),
            recovery_decision=decision,
            prepared=prepared,
        )

    async def _load_snapshot(
        self,
        recovery_claim: ExecutionRecoveryClaim,
    ) -> ExecutionRecoverySnapshot | None:
        try:
            snapshot = await self._snapshot_store.load(recovery_claim.execution_id)
        except Exception:  # noqa: BLE001
            return None
        if snapshot is None:
            return None
        if snapshot.generation != recovery_claim.source_snapshot_generation:
            return None
        return snapshot

    async def _reconcile_tools_once(
        self,
        *,
        execution_id: str,
        recovery_claim: ExecutionRecoveryClaim,
        recovered_at: datetime,
    ) -> None:
        coordinator = self._tool_resource_recovery
        if coordinator is None:
            return
        try:
            observations = await self._inflight_store.load_inflight(
                execution_id=execution_id,
            )
            bindings = await self._resource_binding_store.active_for_execution(
                execution_id
            )
        except Exception:  # noqa: BLE001
            return

        operation_ids = {
            item.handle.operation_handle_id
            for item in observations
            if item.handle.kind is InFlightOperationKind.TOOL
            and item.state
            in {
                InFlightEvidenceState.ORPHANED_UNCONFIRMED,
                InFlightEvidenceState.COMPLETED,
                InFlightEvidenceState.CONFIRMED_STOPPED,
                InFlightEvidenceState.PROVEN_ABSENT,
                InFlightEvidenceState.FENCED_OUT,
            }
        }
        operation_ids.update(
            item.binding.handle.operation_handle_id
            for item in bindings
            if item.binding.handle.kind is InFlightOperationKind.TOOL
        )
        for operation_handle_id in sorted(operation_ids):
            try:
                result = await coordinator.recover(
                    operation_handle_id=operation_handle_id,
                    recovery_claim=recovery_claim,
                    recovered_at=recovered_at,
                )
            except Exception:  # noqa: BLE001
                return
            if result.status in {
                ResourceRecoveryStatus.RETAINED,
                ResourceRecoveryStatus.UNKNOWN,
            }:
                return

    async def _apply_control(
        self,
        *,
        prepared: PreparedExecution,
        decision: RecoveryDecision,
    ) -> M5RecoveryRuntimeOutcome:
        runtime = self._control_runtime
        if runtime is None:
            return M5RecoveryRuntimeOutcome(
                status=M5RecoveryRuntimeStatus.UNKNOWN,
                reason_codes=("RECOVERY_CONTROL_RUNTIME_MISSING",),
                recovery_decision=decision,
                prepared=prepared,
            )
        read = await self._control_store.read_latched(
            prepared.execution_context.execution_id
        )
        if (
            read.status is not DurableControlReadStatus.LATCHED
            or read.latched_control is None
        ):
            return M5RecoveryRuntimeOutcome(
                status=M5RecoveryRuntimeStatus.UNKNOWN,
                reason_codes=("RECOVERY_CONTROL_LATCH_NOT_AUTHORITATIVE",),
                recovery_decision=decision,
                prepared=prepared,
            )
        observed = ObservedExecutionControl(
            signal=read.latched_control.signal,
            observed_at=read.latched_control.observed_at,
        )
        try:
            result = await runtime.observe_and_apply(
                prepared,
                observed=observed,
            )
        except Exception:  # noqa: BLE001
            return M5RecoveryRuntimeOutcome(
                status=M5RecoveryRuntimeStatus.UNKNOWN,
                reason_codes=("RECOVERY_CONTROL_APPLICATION_UNKNOWN",),
                recovery_decision=decision,
                prepared=prepared,
            )
        status = (
            M5RecoveryRuntimeStatus.CONTROL_WAITING
            if result.application.disposition
            is ExecutionControlDisposition.WAITING_IN_FLIGHT
            else M5RecoveryRuntimeStatus.CONTROL_APPLIED
        )
        return M5RecoveryRuntimeOutcome(
            status=status,
            reason_codes=result.application.reason_codes,
            recovery_decision=decision,
            prepared=result.prepared,
            control_result=result,
        )

    @staticmethod
    def _plan_matches_snapshot(
        approved_plan: ApprovedActionPlan,
        snapshot: ExecutionRecoverySnapshot,
    ) -> bool:
        if (
            approved_plan.plan_id != snapshot.execution_record.plan_id
            or approved_plan.request_id != snapshot.execution_record.request_id
        ):
            return False
        plan_ids = tuple(item.step_id for item in approved_plan.steps)
        snapshot_ids = tuple(item.step_id for item in snapshot.steps)
        return plan_ids == snapshot_ids

    @staticmethod
    def _plan_step(
        approved_plan: ApprovedActionPlan,
        step_id: str,
    ) -> ActionStep | None:
        matches = tuple(item for item in approved_plan.steps if item.step_id == step_id)
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _running_step(
        prepared: PreparedExecution,
        decision: RecoveryDecision,
    ) -> StepLifecycleSnapshot | None:
        if decision.disposition is RecoveryDisposition.RETRY_STEP:
            matches = tuple(
                item
                for item in prepared.steps
                if item.step_execution_id == decision.retry_step_execution_id
            )
            return matches[0] if len(matches) == 1 else None
        if decision.disposition is RecoveryDisposition.RESUME_WORKFLOW:
            request = decision.workflow_resume_request
            if request is None:
                return None
            matches = tuple(
                item
                for item in prepared.steps
                if item.step_execution_id == request.step_execution_id
            )
            return matches[0] if len(matches) == 1 else None
        return None

    @staticmethod
    def _capability_runtime_outcome(
        *,
        success_status: M5RecoveryRuntimeStatus,
        outcome: StepCapabilityExecutionOutcome,
        decision: RecoveryDecision,
        prepared: PreparedExecution,
    ) -> M5RecoveryRuntimeOutcome:
        if outcome.status in {
            CapabilityExecutionStatus.EXECUTED,
            CapabilityExecutionStatus.WAITING,
        }:
            status = success_status
        elif outcome.status is CapabilityExecutionStatus.BLOCKED:
            status = M5RecoveryRuntimeStatus.BLOCKED
        else:
            status = M5RecoveryRuntimeStatus.UNKNOWN
        return M5RecoveryRuntimeOutcome(
            status=status,
            reason_codes=outcome.reason_codes,
            recovery_decision=decision,
            prepared=prepared,
            capability_outcome=outcome,
        )

    @staticmethod
    def _unknown_from_snapshot(
        snapshot: ExecutionRecoverySnapshot,
        reason: str,
    ) -> M5RecoveryRuntimeOutcome:
        decision = RecoveryDecision(
            disposition=RecoveryDisposition.UNKNOWN_BLOCKED,
            reason_codes=(reason,),
            snapshot_generation=snapshot.generation,
        )
        return M5RecoveryRuntimeOutcome(
            status=M5RecoveryRuntimeStatus.UNKNOWN,
            reason_codes=(reason,),
            recovery_decision=decision,
            prepared=snapshot.restore_prepared_execution(),
        )

    @staticmethod
    def _unknown_decision(
        recovery_claim: ExecutionRecoveryClaim,
        reason: str,
    ) -> M5RecoveryRuntimeOutcome:
        generation = max(recovery_claim.source_snapshot_generation, 1)
        decision = RecoveryDecision(
            disposition=RecoveryDisposition.UNKNOWN_BLOCKED,
            reason_codes=(reason,),
            snapshot_generation=generation,
        )
        return M5RecoveryRuntimeOutcome(
            status=M5RecoveryRuntimeStatus.UNKNOWN,
            reason_codes=(reason,),
            recovery_decision=decision,
        )
