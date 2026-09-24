"""M5-IU10 Formal Implementation behavioral gates."""

from __future__ import annotations

import asyncio
import inspect
from datetime import timedelta

import pytest

import runtime.execution.aggregation_runtime as aggregation_runtime_module
from runtime.contracts.enums import ExecutionPlanStatus
from runtime.execution.aggregation_runtime import (
    DurableRecoveryControlRuntimeFactory,
    M5ExecutionAggregationRuntime,
    M5ExecutionAggregationRuntimeStatus,
)
from runtime.execution.control import (
    ExecutionControlLatchStatus,
    ExecutionControlSignal,
    ExecutionControlSignalType,
    ObservedExecutionControl,
)
from runtime.execution.control_applicability import (
    ControlApplicabilityEvidenceStatus,
    ControlApplicabilityReadStatus,
    ControlApplicabilityWriteStatus,
    InMemoryDurableControlApplicabilityStore,
)
from runtime.execution.control_application import (
    ExecutionControlApplication,
    ExecutionControlApplicationEvaluator,
    ExecutionControlDisposition,
    InFlightInterruptCoordinator,
    InMemoryInFlightOperationRegistry,
)
from runtime.execution.control_lifecycle import (
    ExecutionControlLifecycleService,
    ExecutionControlLifecycleTransitioner,
)
from runtime.execution.foundation import (
    ExecutionLifecycleManager,
    ExecutionLifecycleService,
    InMemoryExecutionStateStore,
)
from runtime.execution.models import StepExecutionStatus, WorkflowExecutionStatus
from runtime.execution.recovery import (
    InMemoryRecoveryClaimAuthority,
    RecoveryClaimRequest,
    RecoveryClaimStatus,
)
from runtime.execution.recovery_evidence import InMemoryDurableRecoveryEvidenceStore
from runtime.execution.reliability_boundary import (
    StepFinalizationDecision,
    StepFinalizationDisposition,
    StepReliabilityDecision,
    StepReliabilityDisposition,
)
from runtime.execution.reliability_coordinator import StepReliabilityRunResult
from runtime.execution.scheduler import (
    SequentialStepScheduler,
    StepConditionDecision,
    StepConditionStatus,
)
from tests.test_m5_iu10_ca02_aggregation_evidence import (
    NOW,
    _partial_reliability_result,
    _plain_plan,
    _running,
    _skill_observation,
    _skill_plan,
    _workflow_observation,
    _workflow_plan,
)
from tests.test_m5_iu10_ca03_canonical_result_projection import (
    _control_terminal,
    _multi_workflow_terminal,
)
from tests.test_m5_iu7_formal_implementation import (
    StaticInterruptController,
    StaticWatcher,
    _observed as iu7_observed,
    _prepared as iu7_prepared,
)


class RecordingTerminalObserver:
    def __init__(self) -> None:
        self.calls = 0
        self.execution_ids: list[str] = []

    async def on_terminal_execution(self, prepared, *, observed_at) -> None:
        del observed_at
        self.calls += 1
        self.execution_ids.append(prepared.execution_record.execution_id)


class FalseConditionEvaluator:
    async def evaluate(self, *, step, prepared) -> StepConditionDecision:
        del step, prepared
        return StepConditionDecision(
            status=StepConditionStatus.NOT_SATISFIED,
            reason_codes=("FORMAL_CONDITION_FALSE",),
        )


def _stores():
    claims = InMemoryRecoveryClaimAuthority()
    reliability = InMemoryDurableRecoveryEvidenceStore(
        claim_authority=claims
    )
    applicability = InMemoryDurableControlApplicabilityStore(
        claim_authority=claims
    )
    return claims, reliability, applicability


def _runtime(
    *,
    lifecycle_service: ExecutionLifecycleService,
    scheduler: SequentialStepScheduler | None = None,
):
    claims, reliability, applicability = _stores()
    runtime = M5ExecutionAggregationRuntime(
        lifecycle_service=lifecycle_service,
        control_store=reliability,
        control_applicability_store=applicability,
        reliability_store=reliability,
        scheduler=scheduler,
    )
    return runtime, claims, reliability, applicability


async def _claim(
    authority: InMemoryRecoveryClaimAuthority,
    *,
    execution_id: str,
    claim_id: str,
):
    decision = await authority.claim(
        RecoveryClaimRequest(
            claim_id=claim_id,
            execution_id=execution_id,
            recovery_owner_id="formal-worker",
            expected_current_epoch=0,
            source_snapshot_generation=0,
            requested_at=NOW,
        )
    )
    assert decision.status is RecoveryClaimStatus.CLAIMED
    assert decision.claim is not None
    return decision.claim


def test_formal_runtime_completes_partial_success_and_publishes_canonical_result() -> None:
    async def scenario() -> None:
        plan = _skill_plan()
        prepared, service, _ = await _running(plan)
        running = await service.start_step(
            prepared,
            step_id="step-001",
            at=NOW + timedelta(seconds=1),
        )
        runtime, _, _, _ = _runtime(lifecycle_service=service)

        outcome = await runtime.complete_running_step(
            approved_plan=plan,
            prepared=running,
            reliability_result=_partial_reliability_result(
                step_execution_id=running.steps[0].step_execution_id
            ),
            at=NOW + timedelta(seconds=3),
        )

        assert outcome.status is M5ExecutionAggregationRuntimeStatus.AGGREGATED
        assert outcome.running_completion is not None
        assert outcome.running_completion.degraded is True
        assert outcome.aggregation_result is not None
        result = outcome.aggregation_result.execution_result
        assert result.plan_status is ExecutionPlanStatus.PARTIAL_SUCCESS
        assert result.quality is not None
        assert result.quality["degraded"] is True
        assert outcome.prepared.execution_record.status == "PARTIAL_SUCCESS"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("workflow_status", "step_status", "plan_status"),
    [
        (
            WorkflowExecutionStatus.COMPLETED,
            StepExecutionStatus.SUCCESS,
            ExecutionPlanStatus.SUCCESS,
        ),
        (
            WorkflowExecutionStatus.FAILED,
            StepExecutionStatus.FAILED,
            ExecutionPlanStatus.FAILED,
        ),
        (
            WorkflowExecutionStatus.TIMEOUT,
            StepExecutionStatus.TIMEOUT,
            ExecutionPlanStatus.TIMEOUT,
        ),
    ],
)
def test_formal_runtime_aggregates_natural_workflow_terminal_statuses(
    workflow_status: WorkflowExecutionStatus,
    step_status: StepExecutionStatus,
    plan_status: ExecutionPlanStatus,
) -> None:
    async def scenario() -> None:
        plan = _workflow_plan()
        prepared, service, _ = await _running(plan)
        running = await service.start_step(
            prepared,
            step_id="step-001",
            at=NOW + timedelta(seconds=1),
        )
        observation = _workflow_observation(
            step_execution_id=running.steps[0].step_execution_id,
            status=workflow_status,
        )
        reliability = StepReliabilityRunResult(
            attempts=(observation,),
            reliability_decision=StepReliabilityDecision(
                disposition=StepReliabilityDisposition.FINALIZE,
                reason_codes=("FORMAL_FINALIZE",),
            ),
            finalization_decision=StepFinalizationDecision(
                disposition=StepFinalizationDisposition.FINALIZE,
                reason_codes=("FORMAL_TERMINAL_AUTHORIZED",),
                terminal_status=step_status,
            ),
        )
        runtime, _, _, _ = _runtime(lifecycle_service=service)

        outcome = await runtime.complete_running_step(
            approved_plan=plan,
            prepared=running,
            reliability_result=reliability,
            at=NOW + timedelta(seconds=3),
        )

        assert outcome.status is M5ExecutionAggregationRuntimeStatus.AGGREGATED
        assert outcome.aggregation_result is not None
        assert outcome.aggregation_result.execution_result.plan_status is plan_status

    asyncio.run(scenario())


def test_formal_runtime_terminalizes_scheduler_skip_before_aggregation() -> None:
    async def scenario() -> None:
        plan = _plain_plan()
        prepared, service, _ = await _running(plan)
        scheduler = SequentialStepScheduler(
            condition_evaluator=FalseConditionEvaluator()
        )
        runtime, _, _, _ = _runtime(
            lifecycle_service=service,
            scheduler=scheduler,
        )

        outcome = await runtime.advance(
            approved_plan=plan,
            prepared=prepared,
            at=NOW + timedelta(seconds=1),
        )

        assert outcome.status is M5ExecutionAggregationRuntimeStatus.AGGREGATED
        assert outcome.terminalized_step_ids == ("step-001",)
        assert outcome.prepared.steps[0].status is StepExecutionStatus.SKIPPED
        assert outcome.prepared.steps[0].aggregation_evidence is not None
        assert outcome.aggregation_result is not None
        assert (
            outcome.aggregation_result.execution_result.plan_status
            is ExecutionPlanStatus.FAILED
        )

    asyncio.run(scenario())


def test_formal_runtime_waiting_does_not_publish_execution_result() -> None:
    async def scenario() -> None:
        plan = _skill_plan()
        prepared, service, _ = await _running(plan)
        running = await service.start_step(
            prepared,
            step_id="step-001",
            at=NOW + timedelta(seconds=1),
        )
        runtime, _, _, _ = _runtime(lifecycle_service=service)

        outcome = await runtime.advance(
            approved_plan=plan,
            prepared=running,
            at=NOW + timedelta(seconds=2),
        )

        assert outcome.status is M5ExecutionAggregationRuntimeStatus.WAITING
        assert outcome.aggregation_result is None
        assert outcome.prepared.execution_record.status == "RUNNING"

    asyncio.run(scenario())


def test_formal_runtime_existing_terminal_replay_is_identical() -> None:
    async def scenario() -> None:
        plan = _skill_plan()
        prepared, service, _ = await _running(plan)
        running = await service.start_step(
            prepared,
            step_id="step-001",
            at=NOW + timedelta(seconds=1),
        )
        runtime, _, _, _ = _runtime(lifecycle_service=service)

        first = await runtime.complete_running_step(
            approved_plan=plan,
            prepared=running,
            reliability_result=_partial_reliability_result(
                step_execution_id=running.steps[0].step_execution_id
            ),
            at=NOW + timedelta(seconds=3),
        )
        assert first.aggregation_result is not None

        replay = await runtime.advance(
            approved_plan=plan,
            prepared=first.prepared,
            at=NOW + timedelta(seconds=20),
        )

        assert replay.status is M5ExecutionAggregationRuntimeStatus.AGGREGATED
        assert replay.aggregation_result is not None
        assert replay.prepared == first.prepared
        assert (
            replay.aggregation_result.execution_result.model_dump(mode="python")
            == first.aggregation_result.execution_result.model_dump(mode="python")
        )

    asyncio.run(scenario())


def test_formal_runtime_preserves_multiple_workflows_on_existing_terminal_replay() -> None:
    async def scenario() -> None:
        plan, prepared = await _multi_workflow_terminal()
        store = InMemoryExecutionStateStore()
        assert await store.create(prepared.execution_record) is True
        service = ExecutionLifecycleService(
            lifecycle_manager=ExecutionLifecycleManager(),
            execution_store=store,
        )
        runtime, _, _, _ = _runtime(lifecycle_service=service)

        outcome = await runtime.advance(
            approved_plan=plan,
            prepared=prepared,
            at=NOW + timedelta(seconds=20),
        )

        assert outcome.status is M5ExecutionAggregationRuntimeStatus.AGGREGATED
        assert outcome.aggregation_result is not None
        result = outcome.aggregation_result.execution_result
        assert result.workflow_result is None
        assert result.workflow_results is not None
        assert [item["workflow_id"] for item in result.workflow_results] == [
            "workflow-001",
            "workflow-002",
        ]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("signal_type", "plan_status"),
    [
        (ExecutionControlSignalType.CANCEL, ExecutionPlanStatus.CANCELLED),
        (ExecutionControlSignalType.PREEMPT, ExecutionPlanStatus.PREEMPTED),
    ],
)
def test_formal_runtime_uses_durable_control_applicability_for_terminal_result(
    signal_type: ExecutionControlSignalType,
    plan_status: ExecutionPlanStatus,
) -> None:
    async def scenario() -> None:
        plan, prepared, control, _ = await _control_terminal(signal_type)
        assert control.latched_control is not None
        latched = control.latched_control

        store = InMemoryExecutionStateStore()
        assert await store.create(prepared.execution_record) is True
        service = ExecutionLifecycleService(
            lifecycle_manager=ExecutionLifecycleManager(),
            execution_store=store,
        )
        runtime, claims, reliability, applicability = _runtime(
            lifecycle_service=service
        )
        claim = await _claim(
            claims,
            execution_id=prepared.execution_record.execution_id,
            claim_id=f"formal-{signal_type.value.lower()}",
        )
        latch_decision = await reliability.latch(
            observed=ObservedExecutionControl(
                signal=latched.signal,
                observed_at=latched.observed_at,
            ),
            latched_at=latched.latched_at,
            required_claim=claim,
        )
        assert latch_decision.status is ExecutionControlLatchStatus.LATCHED
        assert latch_decision.latched_control is not None

        step_id = prepared.steps[0].step_execution_id
        application = ExecutionControlApplication(
            signal=latched.signal,
            disposition=ExecutionControlDisposition.READY_TO_TERMINALIZE,
            reason_codes=("CONTROL_AFFECTS_PENDING_WORK",),
            nonterminal_step_ids_at_latch=(step_id,),
            affected_step_ids=(step_id,),
            handoff_required=(
                signal_type is ExecutionControlSignalType.PREEMPT
            ),
        )
        write = await applicability.record(
            latched_control=latch_decision.latched_control,
            application=application,
            recorded_at=latched.latched_at,
            required_claim=claim,
        )
        assert write.status is ControlApplicabilityWriteStatus.RECORDED

        outcome = await runtime.advance(
            approved_plan=plan,
            prepared=prepared,
            at=NOW + timedelta(seconds=20),
        )

        assert outcome.status is M5ExecutionAggregationRuntimeStatus.AGGREGATED
        assert outcome.aggregation_result is not None
        result = outcome.aggregation_result.execution_result
        assert result.plan_status is plan_status
        assert result.cancellation is not None
        assert result.cancellation["signal_id"] == latched.signal.signal_id

    asyncio.run(scenario())


def test_formal_runtime_late_control_noop_does_not_override_natural_terminal_truth() -> (
    None
):
    async def scenario() -> None:
        plan = _skill_plan()
        prepared, service, _ = await _running(plan)
        running = await service.start_step(
            prepared,
            step_id="step-001",
            at=NOW + timedelta(seconds=1),
        )
        runtime, claims, reliability, applicability = _runtime(
            lifecycle_service=service
        )

        natural = await runtime.complete_running_step(
            approved_plan=plan,
            prepared=running,
            reliability_result=_partial_reliability_result(
                step_execution_id=running.steps[0].step_execution_id
            ),
            at=NOW + timedelta(seconds=3),
        )
        assert natural.aggregation_result is not None

        execution_id = natural.prepared.execution_record.execution_id
        claim = await _claim(
            claims,
            execution_id=execution_id,
            claim_id="formal-late-control",
        )
        signal = ExecutionControlSignal(
            signal_type=ExecutionControlSignalType.CANCEL,
            reason_code="LATE_CANCEL",
            source="runtime",
            signal_id="formal-late-signal",
            target_execution_id=execution_id,
            issued_at=NOW + timedelta(seconds=4),
        )
        observed = ObservedExecutionControl(
            signal=signal,
            observed_at=NOW + timedelta(seconds=5),
        )
        latch = await reliability.latch(
            observed=observed,
            latched_at=NOW + timedelta(seconds=6),
            required_claim=claim,
        )
        assert latch.status is ExecutionControlLatchStatus.LATCHED
        assert latch.latched_control is not None
        write = await applicability.record(
            latched_control=latch.latched_control,
            application=ExecutionControlApplication(
                signal=signal,
                disposition=ExecutionControlDisposition.ALREADY_TERMINAL,
                reason_codes=("CONTROL_ARRIVED_AFTER_EXECUTION_TERMINAL",),
                handoff_required=False,
            ),
            recorded_at=NOW + timedelta(seconds=7),
            required_claim=claim,
        )
        assert write.status is ControlApplicabilityWriteStatus.RECORDED

        replay = await runtime.advance(
            approved_plan=plan,
            prepared=natural.prepared,
            at=NOW + timedelta(seconds=8),
        )

        assert replay.status is M5ExecutionAggregationRuntimeStatus.AGGREGATED
        assert replay.aggregation_result is not None
        assert (
            replay.aggregation_result.execution_result.plan_status
            is ExecutionPlanStatus.PARTIAL_SUCCESS
        )
        assert replay.aggregation_result.execution_result.cancellation is None

    asyncio.run(scenario())


def test_durable_recovery_control_factory_binds_latch_and_applicability_to_same_claim() -> (
    None
):
    async def scenario() -> None:
        prepared = iu7_prepared(running=False)
        observed = iu7_observed()
        claims, reliability, applicability = _stores()
        claim = await _claim(
            claims,
            execution_id=prepared.execution_record.execution_id,
            claim_id="formal-recovery-control",
        )

        state_store = InMemoryExecutionStateStore()
        assert await state_store.create(prepared.execution_record) is True
        lifecycle = ExecutionControlLifecycleService(
            transitioner=ExecutionControlLifecycleTransitioner(),
            execution_store=state_store,
        )
        inflight = InMemoryInFlightOperationRegistry()
        factory = DurableRecoveryControlRuntimeFactory(
            watcher=StaticWatcher(observed),
            control_store=reliability,
            control_applicability_store=applicability,
            interrupt_coordinator=InFlightInterruptCoordinator(
                registry=inflight,
                interrupt_controller=StaticInterruptController(),
            ),
            application_evaluator=ExecutionControlApplicationEvaluator(),
            lifecycle_service=lifecycle,
            clock=lambda: NOW + timedelta(seconds=10),
        )

        runtime = factory.create(claim)
        result = await runtime.observe_and_apply(
            prepared,
            observed=observed,
        )

        assert result.application.disposition is ExecutionControlDisposition.READY_TO_TERMINALIZE
        assert result.prepared.execution_record.status == "CANCELLED"

        control = await reliability.read_latched(
            prepared.execution_record.execution_id
        )
        evidence = await applicability.read(
            prepared.execution_record.execution_id
        )
        assert control.status.value == "LATCHED"
        assert evidence.status is ControlApplicabilityReadStatus.RECORDED
        assert evidence.record is not None
        assert (
            evidence.record.status
            is ControlApplicabilityEvidenceStatus.APPLIES
        )
        assert evidence.record.writer_recovery_epoch == claim.recovery_epoch

    asyncio.run(scenario())


def test_formal_runtime_natural_terminal_preserves_terminal_observer_boundary() -> None:
    async def scenario() -> None:
        plan = _skill_plan()
        prepared, _, store = await _running(plan)
        observer = RecordingTerminalObserver()
        service = ExecutionLifecycleService(
            lifecycle_manager=ExecutionLifecycleManager(),
            execution_store=store,
            terminal_observer=observer,
        )
        running = await service.start_step(
            prepared,
            step_id="step-001",
            at=NOW + timedelta(seconds=1),
        )
        runtime, _, _, _ = _runtime(lifecycle_service=service)

        outcome = await runtime.complete_running_step(
            approved_plan=plan,
            prepared=running,
            reliability_result=_partial_reliability_result(
                step_execution_id=running.steps[0].step_execution_id
            ),
            at=NOW + timedelta(seconds=3),
        )

        assert outcome.status is M5ExecutionAggregationRuntimeStatus.AGGREGATED
        assert observer.calls == 1
        assert observer.execution_ids == [
            prepared.execution_record.execution_id
        ]

    asyncio.run(scenario())


def test_formal_control_projection_reads_durable_current_attempt_not_retry_count() -> None:
    async def scenario() -> None:
        plan, prepared, control, _ = await _control_terminal(
            ExecutionControlSignalType.CANCEL,
            tool_call_ids=("tool-call-001",),
            retry_count=98,
        )
        assert control.latched_control is not None
        latched = control.latched_control

        state_store = InMemoryExecutionStateStore()
        assert await state_store.create(prepared.execution_record) is True
        service = ExecutionLifecycleService(
            lifecycle_manager=ExecutionLifecycleManager(),
            execution_store=state_store,
        )
        runtime, claims, reliability, applicability = _runtime(
            lifecycle_service=service
        )
        claim = await _claim(
            claims,
            execution_id=prepared.execution_record.execution_id,
            claim_id="formal-control-tool",
        )

        latch = await reliability.latch(
            observed=ObservedExecutionControl(
                signal=latched.signal,
                observed_at=latched.observed_at,
            ),
            latched_at=latched.latched_at,
            required_claim=claim,
        )
        assert latch.status is ExecutionControlLatchStatus.LATCHED
        assert latch.latched_control is not None

        step = prepared.steps[0]
        write = await applicability.record(
            latched_control=latch.latched_control,
            application=ExecutionControlApplication(
                signal=latched.signal,
                disposition=ExecutionControlDisposition.READY_TO_TERMINALIZE,
                reason_codes=("CONTROL_AFFECTS_RUNNING_WORK",),
                nonterminal_step_ids_at_latch=(step.step_execution_id,),
                affected_step_ids=(step.step_execution_id,),
                handoff_required=False,
            ),
            recorded_at=latched.latched_at,
            required_claim=claim,
        )
        assert write.status is ControlApplicabilityWriteStatus.RECORDED

        baseline = await reliability.ensure_step_attempt_baseline(
            execution_id=prepared.execution_record.execution_id,
            step_execution_id=step.step_execution_id,
            recorded_at=NOW + timedelta(seconds=1),
            required_claim=claim,
        )
        assert baseline.status.value in {"RECORDED", "ALREADY_CURRENT"}
        journal = _skill_observation(
            step_execution_id=step.step_execution_id
        ).tool_journal
        assert len(journal) == 1
        appended = await reliability.append_tool_journal_entry(
            execution_id=prepared.execution_record.execution_id,
            step_execution_id=step.step_execution_id,
            step_attempt_number=1,
            expected_current_length=0,
            entry=journal[0],
            recorded_at=NOW + timedelta(seconds=2),
            required_claim=claim,
        )
        assert appended.status.value in {"APPENDED", "ALREADY_CURRENT"}

        outcome = await runtime.advance(
            approved_plan=plan,
            prepared=prepared,
            at=NOW + timedelta(seconds=20),
        )

        assert outcome.status is M5ExecutionAggregationRuntimeStatus.AGGREGATED
        assert outcome.aggregation_result is not None
        result = outcome.aggregation_result.execution_result
        assert result.tool_results is not None
        assert len(result.tool_results) == 1
        assert result.tool_results[0]["tool_call_id"] == "tool-call-001"

    asyncio.run(scenario())


def test_formal_runtime_does_not_use_skeleton_projector_or_hand_built_control() -> None:
    source = inspect.getsource(aggregation_runtime_module)

    assert " ExecutionResultProjector" not in source
    assert "StaticAggregationControlAuthority" not in source
    assert "AggregationControlApplicabilityDecision(" not in source
    assert "DurableAggregationControlAuthority(" in source
    assert "CanonicalExecutionResultProjector(" in source
    assert "DurableControlTerminalToolEvidenceReader(" in source
