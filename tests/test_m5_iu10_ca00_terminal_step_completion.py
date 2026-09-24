"""CA-M5-IU10-00 terminal Step completion boundary gates."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from runtime.execution import (
    ApprovedPlanExecutionValidator,
    CallableExecutionIdentifierFactory,
    ExecutionContextBuilder,
    ExecutionFoundation,
    ExecutionLifecycleError,
    ExecutionLifecycleManager,
    ExecutionLifecycleService,
    ExecutionRecordFactory,
    ExecutionRecoveryClaim,
    ExecutionRecoverySnapshotFactory,
    InMemoryExecutionStateStore,
    PendingStepSkipAuthority,
    PendingStepSkipAuthorityKind,
    RunningStepCompletionCoordinator,
    RunningStepCompletionStatus,
    SequentialStepScheduler,
    StepAttemptObservation,
    StepAttemptStatus,
    StepConditionDecision,
    StepConditionStatus,
    StepExecutionStatus,
    StepFinalizationDecision,
    StepFinalizationDisposition,
    StepReliabilityDecision,
    StepReliabilityDisposition,
    StepReliabilityRunResult,
    StepScheduleDecision,
    StepScheduleStatus,
    TerminalStepCompletionCoordinator,
    TerminalStepCompletionStatus,
)
from runtime.execution.capability_resolution import CapabilityExecutionOwner
from runtime.execution.reliability_defaults import BasicStepFinalizationEvaluator
from tests.orchestration_stubs import (
    build_approved_action_plan,
    build_runtime_context,
)

NOW = datetime(2026, 9, 24, 9, 0, tzinfo=UTC)


def _plan_with_steps(
    *,
    count: int,
    first_optional: bool | None = None,
    second_depends_on_first: bool = False,
):
    base = build_approved_action_plan()
    steps = []
    for index in range(count):
        source = base.steps[0]
        step_id = f"step-{index + 1:03d}"
        updates = {
            "step_id": step_id,
            "action": f"ACTION_{index + 1}",
            "depends_on": None,
            "optional": False,
        }
        if index == 0:
            updates["optional"] = first_optional
        if index == 1 and second_depends_on_first:
            updates["depends_on"] = ["step-001"]
        steps.append(source.model_copy(update=updates))
    return base.model_copy(update={"steps": steps})


async def _running(plan):
    ids = CallableExecutionIdentifierFactory(
        execution_id_factory=lambda: "execution-iu10-ca00",
        step_execution_id_factory=lambda step_id: f"exec:{step_id}",
    )
    store = InMemoryExecutionStateStore()
    foundation = ExecutionFoundation(
        plan_validator=ApprovedPlanExecutionValidator(),
        context_builder=ExecutionContextBuilder(identifier_factory=ids),
        record_factory=ExecutionRecordFactory(
            identifier_factory=ids,
            clock=lambda: NOW,
        ),
        execution_store=store,
    )
    prepared = await foundation.initialize(plan, build_runtime_context())
    service = ExecutionLifecycleService(
        lifecycle_manager=ExecutionLifecycleManager(),
        execution_store=store,
    )
    running = await service.start_execution(prepared, at=NOW)
    return running, service, store


async def _finish_first(
    plan,
    *,
    status: StepExecutionStatus,
):
    prepared, service, store = await _running(plan)
    started = await service.start_step(
        prepared,
        step_id="step-001",
        at=NOW + timedelta(seconds=1),
    )
    finished = await service.finish_step(
        started,
        step_id="step-001",
        status=status,
        at=NOW + timedelta(seconds=2),
        terminal_reason_codes=("FIRST_STEP_TERMINAL",),
    )
    return finished, service, store


class StaticConditionEvaluator:
    def __init__(self, decision: StepConditionDecision) -> None:
        self.decision = decision

    async def evaluate(self, *, step, prepared):
        del step, prepared
        return self.decision


class StaticScheduler:
    def __init__(self, decision: StepScheduleDecision) -> None:
        self.decision = decision
        self.calls = 0

    async def next_step(self, *, approved_plan, prepared):
        del approved_plan, prepared
        self.calls += 1
        return self.decision


def test_scheduler_skip_terminalizes_exact_pending_step_and_preserves_reason() -> None:
    async def scenario() -> None:
        plan = _plan_with_steps(
            count=2,
            first_optional=True,
            second_depends_on_first=True,
        )
        prepared, service, store = await _finish_first(
            plan,
            status=StepExecutionStatus.FAILED,
        )
        coordinator = TerminalStepCompletionCoordinator(
            scheduler=SequentialStepScheduler(),
            lifecycle_service=service,
        )

        decision = await coordinator.advance(
            approved_plan=plan,
            prepared=prepared,
            at=NOW + timedelta(seconds=3),
        )

        assert decision.status is TerminalStepCompletionStatus.TERMINALIZED
        assert decision.terminalized_step_id == "step-002"
        assert decision.reason_codes == ("DEPENDENCY_NOT_SUCCESSFUL",)
        step = decision.prepared.steps[1]
        assert step.status is StepExecutionStatus.SKIPPED
        assert step.started_at is None
        assert step.finished_at == NOW + timedelta(seconds=3)
        assert step.terminal_reason_codes == ("DEPENDENCY_NOT_SUCCESSFUL",)
        stored = await store.load("execution-iu10-ca00")
        assert stored is not None
        assert stored.step_results[1]["terminal_reason_codes"] == [
            "DEPENDENCY_NOT_SUCCESSFUL"
        ]

    asyncio.run(scenario())


def test_condition_skip_terminalizes_without_invoking_a_capability() -> None:
    async def scenario() -> None:
        plan = _plan_with_steps(count=1)
        prepared, service, _ = await _running(plan)
        scheduler = SequentialStepScheduler(
            condition_evaluator=StaticConditionEvaluator(
                StepConditionDecision(
                    status=StepConditionStatus.NOT_SATISFIED,
                    reason_codes=("REGISTERED_CONDITION_FALSE",),
                )
            )
        )
        coordinator = TerminalStepCompletionCoordinator(
            scheduler=scheduler,
            lifecycle_service=service,
        )

        decision = await coordinator.advance(
            approved_plan=plan,
            prepared=prepared,
            at=NOW + timedelta(seconds=1),
        )

        assert decision.status is TerminalStepCompletionStatus.TERMINALIZED
        assert decision.prepared.steps[0].status is StepExecutionStatus.SKIPPED
        assert decision.prepared.steps[0].terminal_reason_codes == (
            "REGISTERED_CONDITION_FALSE",
        )

    asyncio.run(scenario())


def test_required_failure_can_close_remaining_pending_steps_one_exact_step_at_a_time() -> None:
    async def scenario() -> None:
        plan = _plan_with_steps(count=3, first_optional=False)
        prepared, service, _ = await _finish_first(
            plan,
            status=StepExecutionStatus.FAILED,
        )
        coordinator = TerminalStepCompletionCoordinator(
            scheduler=SequentialStepScheduler(),
            lifecycle_service=service,
        )

        second = await coordinator.advance(
            approved_plan=plan,
            prepared=prepared,
            at=NOW + timedelta(seconds=3),
        )
        assert second.status is TerminalStepCompletionStatus.TERMINALIZED
        assert second.terminalized_step_id == "step-002"
        assert second.reason_codes == ("REQUIRED_PREVIOUS_STEP_NOT_SUCCESSFUL",)

        third = await coordinator.advance(
            approved_plan=plan,
            prepared=second.prepared,
            at=NOW + timedelta(seconds=4),
        )
        assert third.status is TerminalStepCompletionStatus.TERMINALIZED
        assert third.terminalized_step_id == "step-003"

        complete = await coordinator.advance(
            approved_plan=plan,
            prepared=third.prepared,
            at=NOW + timedelta(seconds=5),
        )
        assert complete.status is TerminalStepCompletionStatus.COMPLETE
        assert [step.status for step in complete.prepared.steps] == [
            StepExecutionStatus.FAILED,
            StepExecutionStatus.SKIPPED,
            StepExecutionStatus.SKIPPED,
        ]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("schedule_status", "reason_codes"),
    [
        (StepScheduleStatus.WAITING, ("DEPENDENCY_NOT_TERMINAL",)),
        (StepScheduleStatus.UNKNOWN, ("CONDITION_UNKNOWN",)),
        (StepScheduleStatus.BLOCKED, ("SEQUENTIAL_ORDER_VIOLATION",)),
    ],
)
def test_waiting_unknown_or_unrelated_blocked_cannot_terminalize_pending_step(
    schedule_status: StepScheduleStatus,
    reason_codes: tuple[str, ...],
) -> None:
    async def scenario() -> None:
        plan = _plan_with_steps(count=1)
        prepared, service, store = await _running(plan)
        scheduler = StaticScheduler(
            StepScheduleDecision(
                status=schedule_status,
                step_id="step-001",
                reason_codes=reason_codes,
            )
        )
        coordinator = TerminalStepCompletionCoordinator(
            scheduler=scheduler,
            lifecycle_service=service,
        )

        decision = await coordinator.advance(
            approved_plan=plan,
            prepared=prepared,
            at=NOW + timedelta(seconds=1),
        )

        expected = (
            TerminalStepCompletionStatus.WAITING
            if schedule_status is StepScheduleStatus.WAITING
            else TerminalStepCompletionStatus.BLOCKED_UNKNOWN
        )
        assert decision.status is expected
        assert decision.prepared is prepared
        assert decision.terminalized_step_id is None
        assert decision.prepared.steps[0].status is StepExecutionStatus.PENDING
        stored = await store.load("execution-iu10-ca00")
        assert stored is not None
        assert stored.step_results[0]["status"] == "PENDING"

    asyncio.run(scenario())


def _partial_observation(
    *,
    step_execution_id: str = "step-exec-001",
) -> StepAttemptObservation:
    return StepAttemptObservation(
        step_id="step-001",
        step_execution_id=step_execution_id,
        attempt_number=1,
        status=StepAttemptStatus.PARTIAL_SUCCESS,
        execution_owner=CapabilityExecutionOwner.SKILL,
        reason_codes=("SKILL_PARTIAL",),
        observed_at=NOW,
        owner_capability_id="SKILL_A",
        owner_capability_version="1.0.0",
    )


def test_partial_success_has_explicit_degraded_terminal_authority() -> None:
    decision = BasicStepFinalizationEvaluator().evaluate(
        observation=_partial_observation(),
        reliability_decision=StepReliabilityDecision(
            disposition=StepReliabilityDisposition.FINALIZE,
            reason_codes=("STEP_RETRY_NOT_AUTHORIZED",),
        ),
    )

    assert decision.disposition is StepFinalizationDisposition.FINALIZE
    assert decision.terminal_status is StepExecutionStatus.SUCCESS
    assert decision.degraded is True
    assert decision.reason_codes == (
        "STEP_PARTIAL_SUCCESS_FINALIZATION_AUTHORIZED",
    )


def test_degraded_finalization_cannot_claim_failed_or_nonfinal_lifecycle() -> None:
    with pytest.raises(ValueError, match="degraded"):
        StepFinalizationDecision(
            disposition=StepFinalizationDisposition.FINALIZE,
            reason_codes=("INVALID",),
            terminal_status=StepExecutionStatus.FAILED,
            degraded=True,
        )

    with pytest.raises(ValueError, match="degraded"):
        StepFinalizationDecision(
            disposition=StepFinalizationDisposition.UNKNOWN,
            reason_codes=("INVALID",),
            degraded=True,
        )


def test_ca00_does_not_add_partial_success_to_step_lifecycle_enum() -> None:
    assert "PARTIAL_SUCCESS" not in {status.value for status in StepExecutionStatus}



def test_recovery_snapshot_accepts_legacy_step_payload_without_terminal_reasons() -> None:
    async def scenario() -> None:
        plan = _plan_with_steps(count=1)
        prepared, _, _ = await _running(plan)
        legacy_payload = tuple(
            {
                key: value
                for key, value in item.items()
                if key not in {"terminal_reason_codes", "degraded"}
            }
            for item in prepared.execution_record.step_results
        )
        legacy = replace(
            prepared,
            execution_record=replace(
                prepared.execution_record,
                step_results=legacy_payload,
            ),
        )
        claim = ExecutionRecoveryClaim(
            claim_id="claim-ca00",
            execution_id=legacy.execution_record.execution_id,
            recovery_owner_id="worker-ca00",
            recovery_epoch=1,
            source_snapshot_generation=0,
            claimed_at=NOW,
        )

        snapshot = ExecutionRecoverySnapshotFactory().capture(
            legacy,
            checkpoint_id="checkpoint-ca00",
            generation=1,
            captured_at=NOW + timedelta(seconds=1),
            claim=claim,
        )

        restored = snapshot.restore_prepared_execution()
        assert restored.steps[0].terminal_reason_codes == ()
        assert restored.steps[0].degraded is False
        assert "terminal_reason_codes" not in legacy_payload[0]
        assert "degraded" not in legacy_payload[0]

    asyncio.run(scenario())



def test_direct_skip_mutation_rejects_authority_bound_to_other_step_execution() -> None:
    async def scenario() -> None:
        plan = _plan_with_steps(count=1)
        prepared, service, store = await _running(plan)
        forged = PendingStepSkipAuthority(
            execution_id=prepared.execution_record.execution_id,
            plan_id=prepared.execution_record.plan_id,
            step_execution_id="different-step-execution",
            step_id="step-001",
            kind=PendingStepSkipAuthorityKind.SCHEDULER_SKIP,
            reason_codes=("REGISTERED_CONDITION_FALSE",),
        )

        with pytest.raises(ExecutionLifecycleError, match="step_execution_id"):
            await service.skip_pending_step(
                prepared,
                authority=forged,
                at=NOW + timedelta(seconds=1),
            )

        stored = await store.load("execution-iu10-ca00")
        assert stored is not None
        assert stored.step_results[0]["status"] == "PENDING"

    asyncio.run(scenario())



def test_skip_authority_kind_cannot_impersonate_required_failure_provenance() -> None:
    with pytest.raises(ValueError, match="impersonate"):
        PendingStepSkipAuthority(
            execution_id="execution-iu10-ca00",
            plan_id="plan-001",
            step_execution_id="exec:step-001",
            step_id="step-001",
            kind=PendingStepSkipAuthorityKind.SCHEDULER_SKIP,
            reason_codes=("REQUIRED_PREVIOUS_STEP_NOT_SUCCESSFUL",),
        )


def test_partial_success_is_not_terminalized_while_iu6_still_requests_retry() -> None:
    decision = BasicStepFinalizationEvaluator().evaluate(
        observation=_partial_observation(),
        reliability_decision=StepReliabilityDecision(
            disposition=StepReliabilityDisposition.RETRY,
            reason_codes=("STEP_RETRY_AUTHORIZED",),
            next_attempt=2,
        ),
    )

    assert decision.disposition is StepFinalizationDisposition.UNKNOWN
    assert decision.terminal_status is None
    assert decision.degraded is False



def _partial_reliability_result(
    *,
    step_execution_id: str = "step-exec-001",
) -> StepReliabilityRunResult:
    observation = _partial_observation(step_execution_id=step_execution_id)
    return StepReliabilityRunResult(
        attempts=(observation,),
        reliability_decision=StepReliabilityDecision(
            disposition=StepReliabilityDisposition.FINALIZE,
            reason_codes=("STEP_RETRY_NOT_AUTHORIZED",),
        ),
        finalization_decision=StepFinalizationDecision(
            disposition=StepFinalizationDisposition.FINALIZE,
            reason_codes=("STEP_PARTIAL_SUCCESS_FINALIZATION_AUTHORIZED",),
            terminal_status=StepExecutionStatus.SUCCESS,
            degraded=True,
        ),
        owner_policy_identity="skill-policy@partial",
    )


def test_running_partial_success_commits_degraded_terminal_step() -> None:
    async def scenario() -> None:
        plan = _plan_with_steps(count=1)
        prepared, service, store = await _running(plan)
        running_step = await service.start_step(
            prepared,
            step_id="step-001",
            at=NOW + timedelta(seconds=1),
        )
        coordinator = RunningStepCompletionCoordinator(
            lifecycle_service=service
        )

        decision = await coordinator.complete(
            prepared=running_step,
            reliability_result=_partial_reliability_result(
                step_execution_id=running_step.steps[0].step_execution_id
            ),
            at=NOW + timedelta(seconds=2),
        )

        assert decision.status is RunningStepCompletionStatus.TERMINALIZED
        assert decision.degraded is True
        step = decision.prepared.steps[0]
        assert step.status is StepExecutionStatus.SUCCESS
        assert step.degraded is True
        assert step.terminal_reason_codes == (
            "STEP_PARTIAL_SUCCESS_FINALIZATION_AUTHORIZED",
        )
        assert step.retry_count == 0
        persisted = await store.load("execution-iu10-ca00")
        assert persisted is not None
        assert persisted.step_results[0]["status"] == "SUCCESS"
        assert persisted.step_results[0]["degraded"] is True
        assert persisted.step_results[0]["terminal_reason_codes"] == [
            "STEP_PARTIAL_SUCCESS_FINALIZATION_AUTHORIZED"
        ]

    asyncio.run(scenario())


def test_running_completion_does_not_mutate_wait_recovery_step() -> None:
    async def scenario() -> None:
        plan = _plan_with_steps(count=1)
        prepared, service, store = await _running(plan)
        running_step = await service.start_step(
            prepared,
            step_id="step-001",
            at=NOW + timedelta(seconds=1),
        )
        observation = _partial_observation()
        result = StepReliabilityRunResult(
            attempts=(observation,),
            reliability_decision=StepReliabilityDecision(
                disposition=StepReliabilityDisposition.WAIT_RECOVERY,
                reason_codes=("STEP_RETRY_SAFETY_UNKNOWN",),
            ),
            finalization_decision=StepFinalizationDecision(
                disposition=StepFinalizationDisposition.WAIT_RECOVERY,
                reason_codes=("STEP_WAIT_RECOVERY",),
            ),
            owner_policy_identity="skill-policy@partial",
        )
        coordinator = RunningStepCompletionCoordinator(
            lifecycle_service=service
        )

        decision = await coordinator.complete(
            prepared=running_step,
            reliability_result=result,
            at=NOW + timedelta(seconds=2),
        )

        assert decision.status is RunningStepCompletionStatus.WAIT_RECOVERY
        assert decision.prepared is running_step
        assert decision.prepared.steps[0].status is StepExecutionStatus.RUNNING
        persisted = await store.load("execution-iu10-ca00")
        assert persisted is not None
        assert persisted.step_results[0]["status"] == "RUNNING"

    asyncio.run(scenario())


def test_running_completion_rejects_step_execution_identity_drift() -> None:
    async def scenario() -> None:
        plan = _plan_with_steps(count=1)
        prepared, service, store = await _running(plan)
        running_step = await service.start_step(
            prepared,
            step_id="step-001",
            at=NOW + timedelta(seconds=1),
        )
        observation = replace(
            _partial_observation(),
            step_execution_id="different-step-execution",
        )
        result = StepReliabilityRunResult(
            attempts=(observation,),
            reliability_decision=StepReliabilityDecision(
                disposition=StepReliabilityDisposition.FINALIZE,
                reason_codes=("STEP_RETRY_NOT_AUTHORIZED",),
            ),
            finalization_decision=StepFinalizationDecision(
                disposition=StepFinalizationDisposition.FINALIZE,
                reason_codes=("STEP_PARTIAL_SUCCESS_FINALIZATION_AUTHORIZED",),
                terminal_status=StepExecutionStatus.SUCCESS,
                degraded=True,
            ),
        )
        coordinator = RunningStepCompletionCoordinator(
            lifecycle_service=service
        )

        decision = await coordinator.complete(
            prepared=running_step,
            reliability_result=result,
            at=NOW + timedelta(seconds=2),
        )

        assert decision.status is RunningStepCompletionStatus.BLOCKED_UNKNOWN
        assert decision.prepared is running_step
        persisted = await store.load("execution-iu10-ca00")
        assert persisted is not None
        assert persisted.step_results[0]["status"] == "RUNNING"

    asyncio.run(scenario())


def test_degraded_lifecycle_fact_survives_recovery_snapshot_roundtrip() -> None:
    async def scenario() -> None:
        plan = _plan_with_steps(count=1)
        prepared, service, _ = await _running(plan)
        running_step = await service.start_step(
            prepared,
            step_id="step-001",
            at=NOW + timedelta(seconds=1),
        )
        completed = await RunningStepCompletionCoordinator(
            lifecycle_service=service
        ).complete(
            prepared=running_step,
            reliability_result=_partial_reliability_result(
                step_execution_id=running_step.steps[0].step_execution_id
            ),
            at=NOW + timedelta(seconds=2),
        )
        claim = ExecutionRecoveryClaim(
            claim_id="claim-ca00-degraded",
            execution_id=completed.prepared.execution_record.execution_id,
            recovery_owner_id="worker-ca00",
            recovery_epoch=1,
            source_snapshot_generation=0,
            claimed_at=NOW,
        )

        snapshot = ExecutionRecoverySnapshotFactory().capture(
            completed.prepared,
            checkpoint_id="checkpoint-ca00-degraded",
            generation=1,
            captured_at=NOW + timedelta(seconds=3),
            claim=claim,
        )

        restored = snapshot.restore_prepared_execution()
        assert restored.steps[0].status is StepExecutionStatus.SUCCESS
        assert restored.steps[0].degraded is True
        assert restored.execution_record.step_results[0]["degraded"] is True

    asyncio.run(scenario())
