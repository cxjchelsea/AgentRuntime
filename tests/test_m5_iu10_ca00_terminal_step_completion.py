"""CA-M5-IU10-00 terminal Step completion boundary gates."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from runtime.execution import (
    ApprovedPlanExecutionValidator,
    BasicStepFinalizationEvaluator,
    CallableExecutionIdentifierFactory,
    ExecutionContextBuilder,
    ExecutionFoundation,
    ExecutionLifecycleManager,
    ExecutionLifecycleService,
    ExecutionRecordFactory,
    InMemoryExecutionStateStore,
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
    StepScheduleDecision,
    StepScheduleStatus,
    TerminalStepCompletionCoordinator,
    TerminalStepCompletionStatus,
)
from runtime.execution.capability_resolution import CapabilityExecutionOwner
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


def _partial_observation() -> StepAttemptObservation:
    return StepAttemptObservation(
        step_id="step-001",
        step_execution_id="step-exec-001",
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
