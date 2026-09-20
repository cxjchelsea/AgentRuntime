"""M5-IU2 Runtime Execution Check + Step Scheduling gates."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

import runtime.execution.runtime_check as runtime_check_module
import runtime.execution.scheduling as scheduling_module
from runtime.contracts import ExecutionPlanStatus
from runtime.execution import (
    CallableExecutionIdentifierFactory,
    ExecutionContextBuilder,
    ExecutionFoundation,
    ExecutionLifecycleManager,
    ExecutionLifecycleService,
    ExecutionRecordFactory,
    ExecutionControlSignal,
    ExecutionControlSignalType,
    FailureDirectiveResolver,
    InMemoryExecutionStateStore,
    PreparedExecution,
    RuntimeExecutionChecker,
    RuntimeExecutionCheckStatus,
    RuntimeExecutionFacts,
    SequentialStepScheduler,
    StepEligibilityDecision,
    StepEligibilityStatus,
    StepExecutionStatus,
    StepFailureDirective,
    StepScheduleAction,
)
from runtime.execution.foundation import ApprovedPlanExecutionValidator
from tests.orchestration_stubs import (
    build_approved_action_plan,
    build_runtime_context,
)

FIXED_TIME = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)


@dataclass
class StaticFactsProvider:
    facts: RuntimeExecutionFacts

    async def build(self, approved_plan, prepared, step):
        del approved_plan, prepared, step
        return self.facts


@dataclass
class StaticControlSignalSource:
    signal: ExecutionControlSignal

    async def get_signal(self, execution_id: str) -> ExecutionControlSignal:
        assert execution_id
        return self.signal


@dataclass
class StaticStepEligibilityEvaluator:
    decision: StepEligibilityDecision

    def evaluate(self, step, prepared: PreparedExecution) -> StepEligibilityDecision:
        del step, prepared
        return self.decision


@dataclass
class StaticContinueIfSafeEvaluator:
    allowed: bool

    def allows_continue(self, step, prepared: PreparedExecution) -> bool:
        del step, prepared
        return self.allowed


def _identifier_factory(
    execution_id: str = "execution-iu2-001",
) -> CallableExecutionIdentifierFactory:
    return CallableExecutionIdentifierFactory(
        execution_id_factory=lambda: execution_id,
        step_execution_id_factory=lambda step_id: f"{execution_id}:{step_id}",
    )


def _foundation(
    *,
    execution_id: str = "execution-iu2-001",
) -> tuple[ExecutionFoundation, InMemoryExecutionStateStore]:
    ids = _identifier_factory(execution_id)
    store = InMemoryExecutionStateStore()
    return (
        ExecutionFoundation(
            plan_validator=ApprovedPlanExecutionValidator(),
            context_builder=ExecutionContextBuilder(identifier_factory=ids),
            record_factory=ExecutionRecordFactory(
                identifier_factory=ids,
                clock=lambda: FIXED_TIME,
            ),
            execution_store=store,
        ),
        store,
    )


def _two_step_plan():
    plan = build_approved_action_plan()
    first = plan.steps[0].model_copy(
        update={
            "step_id": "step-001",
            "depends_on": None,
            "optional": False,
            "on_failure": None,
        }
    )
    second = plan.steps[0].model_copy(
        update={
            "step_id": "step-002",
            "depends_on": ["step-001"],
            "optional": False,
            "on_failure": None,
        }
    )
    return plan.model_copy(update={"steps": [first, second]})


def _running_execution(plan=None):
    approved_plan = plan or build_approved_action_plan()
    foundation, store = _foundation()
    prepared = asyncio.run(
        foundation.initialize(
            approved_plan,
            build_runtime_context(),
        )
    )
    service = ExecutionLifecycleService(
        lifecycle_manager=ExecutionLifecycleManager(),
        execution_store=store,
    )
    running = asyncio.run(service.start_execution(prepared, at=FIXED_TIME))
    return approved_plan, running, service, store


def _allowed_facts() -> RuntimeExecutionFacts:
    return RuntimeExecutionFacts(
        session_active=True,
        state_allows_step=True,
        policy_snapshot_valid=True,
        safety_allows_step=True,
        current_state="PROCESSING",
    )


def test_runtime_execution_checker_allows_only_when_all_live_facts_allow() -> None:
    plan, running, _, _ = _running_execution()
    checker = RuntimeExecutionChecker(
        facts_provider=StaticFactsProvider(_allowed_facts()),
        control_signal_source=StaticControlSignalSource(
            ExecutionControlSignal(
                signal_type=ExecutionControlSignalType.NONE,
            )
        ),
    )

    decision = asyncio.run(checker.check(plan, running, plan.steps[0]))

    assert decision.status is RuntimeExecutionCheckStatus.ALLOWED
    assert decision.reason_codes == ("RUNTIME_EXECUTION_ALLOWED",)


def test_runtime_execution_checker_fails_closed_on_unknown_runtime_fact() -> None:
    plan, running, _, _ = _running_execution()
    checker = RuntimeExecutionChecker(
        facts_provider=StaticFactsProvider(
            RuntimeExecutionFacts(
                session_active=True,
                state_allows_step=None,
                policy_snapshot_valid=True,
                safety_allows_step=True,
            )
        ),
        control_signal_source=StaticControlSignalSource(
            ExecutionControlSignal(
                signal_type=ExecutionControlSignalType.NONE,
            )
        ),
    )

    decision = asyncio.run(checker.check(plan, running, plan.steps[0]))

    assert decision.status is RuntimeExecutionCheckStatus.BLOCKED
    assert "STATE_UNKNOWN" in decision.reason_codes


def test_runtime_execution_checker_preserves_provider_blocking_reasons() -> None:
    plan, running, _, _ = _running_execution()
    checker = RuntimeExecutionChecker(
        facts_provider=StaticFactsProvider(
            RuntimeExecutionFacts(
                session_active=True,
                state_allows_step=True,
                policy_snapshot_valid=True,
                safety_allows_step=True,
                blocking_reason_codes=("DOMAIN_RUNTIME_RULE_BLOCKED",),
            )
        ),
        control_signal_source=StaticControlSignalSource(
            ExecutionControlSignal(
                signal_type=ExecutionControlSignalType.NONE,
            )
        ),
    )

    decision = asyncio.run(checker.check(plan, running, plan.steps[0]))

    assert decision.status is RuntimeExecutionCheckStatus.BLOCKED
    assert decision.reason_codes == ("DOMAIN_RUNTIME_RULE_BLOCKED",)


@pytest.mark.parametrize(
    ("signal_type", "expected_status", "reason"),
    [
        (
            ExecutionControlSignalType.CANCEL,
            RuntimeExecutionCheckStatus.CANCELLED,
            "USER_STOP",
        ),
        (
            ExecutionControlSignalType.PREEMPT,
            RuntimeExecutionCheckStatus.PREEMPTED,
            "HIGH_PRIORITY_PREEMPTION",
        ),
    ],
)
def test_runtime_execution_checker_obeys_runtime_resolved_control_signal(
    signal_type,
    expected_status,
    reason,
) -> None:
    plan, running, _, _ = _running_execution()
    checker = RuntimeExecutionChecker(
        facts_provider=StaticFactsProvider(_allowed_facts()),
        control_signal_source=StaticControlSignalSource(
            ExecutionControlSignal(
                signal_type=signal_type,
                reason_code=reason,
                source="RUNTIME",
            )
        ),
    )

    decision = asyncio.run(checker.check(plan, running, plan.steps[0]))

    assert decision.status is expected_status
    assert decision.reason_codes == (reason,)
    assert decision.control_source == "RUNTIME"


def test_runtime_execution_checker_does_not_accept_non_pending_step() -> None:
    plan, running, service, _ = _running_execution()
    step_running = asyncio.run(
        service.start_step(
            running,
            step_id=plan.steps[0].step_id,
            at=FIXED_TIME + timedelta(seconds=1),
        )
    )
    checker = RuntimeExecutionChecker(
        facts_provider=StaticFactsProvider(_allowed_facts()),
        control_signal_source=StaticControlSignalSource(
            ExecutionControlSignal(
                signal_type=ExecutionControlSignalType.NONE,
            )
        ),
    )

    with pytest.raises(ValueError, match="PENDING"):
        asyncio.run(checker.check(plan, step_running, plan.steps[0]))


def test_sequential_scheduler_returns_first_ready_step_in_approved_order() -> None:
    plan, running, _, _ = _running_execution(_two_step_plan())

    decision = SequentialStepScheduler().next(plan, running)

    assert decision.action is StepScheduleAction.READY
    assert decision.step_id == "step-001"


def test_sequential_scheduler_waits_while_step_is_running() -> None:
    plan, running, service, _ = _running_execution(_two_step_plan())
    first_running = asyncio.run(
        service.start_step(
            running,
            step_id="step-001",
            at=FIXED_TIME + timedelta(seconds=1),
        )
    )

    decision = SequentialStepScheduler().next(plan, first_running)

    assert decision.action is StepScheduleAction.WAIT
    assert decision.reason_codes == ("STEP_ALREADY_RUNNING",)


def test_sequential_scheduler_releases_dependency_after_success() -> None:
    plan, running, service, _ = _running_execution(_two_step_plan())
    first_running = asyncio.run(
        service.start_step(
            running,
            step_id="step-001",
            at=FIXED_TIME + timedelta(seconds=1),
        )
    )
    first_done = asyncio.run(
        service.finish_step(
            first_running,
            step_id="step-001",
            status=StepExecutionStatus.SUCCESS,
            at=FIXED_TIME + timedelta(seconds=2),
        )
    )

    decision = SequentialStepScheduler().next(plan, first_done)

    assert decision.action is StepScheduleAction.READY
    assert decision.step_id == "step-002"


def test_failed_dependency_is_scheduled_as_skip_and_persisted_via_lifecycle_service() -> None:
    plan, running, service, store = _running_execution(_two_step_plan())
    first_running = asyncio.run(
        service.start_step(
            running,
            step_id="step-001",
            at=FIXED_TIME + timedelta(seconds=1),
        )
    )
    first_failed = asyncio.run(
        service.finish_step(
            first_running,
            step_id="step-001",
            status=StepExecutionStatus.FAILED,
            at=FIXED_TIME + timedelta(seconds=2),
            error="TEST_FAILURE",
        )
    )

    decision = SequentialStepScheduler().next(plan, first_failed)
    assert decision.action is StepScheduleAction.SKIP
    assert decision.step_id == "step-002"

    skipped = asyncio.run(
        service.skip_step(
            first_failed,
            step_id="step-002",
            at=FIXED_TIME + timedelta(seconds=3),
            reason=decision.reason_codes[0],
        )
    )
    persisted = asyncio.run(store.load(skipped.execution_record.execution_id))

    assert skipped.steps[1].status is StepExecutionStatus.SKIPPED
    assert persisted is not None
    assert persisted.step_results[1]["status"] == "SKIPPED"


def test_sequential_scheduler_completes_when_no_pending_steps_remain() -> None:
    plan, running, service, _ = _running_execution()
    step_running = asyncio.run(
        service.start_step(
            running,
            step_id=plan.steps[0].step_id,
            at=FIXED_TIME + timedelta(seconds=1),
        )
    )
    step_done = asyncio.run(
        service.finish_step(
            step_running,
            step_id=plan.steps[0].step_id,
            status=StepExecutionStatus.SUCCESS,
            at=FIXED_TIME + timedelta(seconds=2),
        )
    )

    decision = SequentialStepScheduler().next(plan, step_done)

    assert decision.action is StepScheduleAction.COMPLETE


def test_scheduler_applies_injected_simple_eligibility_without_reordering() -> None:
    plan, running, _, _ = _running_execution(_two_step_plan())
    scheduler = SequentialStepScheduler(
        eligibility_evaluator=StaticStepEligibilityEvaluator(
            StepEligibilityDecision(
                status=StepEligibilityStatus.SKIP,
                reason_codes=("SIMPLE_CONDITION_FALSE",),
            )
        )
    )

    decision = scheduler.next(plan, running)

    assert decision.action is StepScheduleAction.SKIP
    assert decision.step_id == "step-001"
    assert decision.reason_codes == ("SIMPLE_CONDITION_FALSE",)


def test_failure_resolver_defaults_optional_failure_to_continue() -> None:
    plan, running, _, _ = _running_execution()
    optional = plan.steps[0].model_copy(
        update={"optional": True, "on_failure": None}
    )

    decision = FailureDirectiveResolver().resolve(
        optional,
        StepExecutionStatus.FAILED,
        running,
    )

    assert decision.directive is StepFailureDirective.CONTINUE


def test_failure_resolver_defaults_required_failure_to_stop() -> None:
    plan, running, _, _ = _running_execution()
    required = plan.steps[0].model_copy(
        update={"optional": False, "on_failure": None}
    )

    decision = FailureDirectiveResolver().resolve(
        required,
        StepExecutionStatus.FAILED,
        running,
    )

    assert decision.directive is StepFailureDirective.STOP_PLAN


def test_failure_resolver_does_not_continue_cancelled_or_preempted_step() -> None:
    plan, running, _, _ = _running_execution()
    optional = plan.steps[0].model_copy(
        update={"optional": True, "on_failure": "CONTINUE_IF_SAFE"}
    )
    evaluator = StaticContinueIfSafeEvaluator(allowed=True)
    resolver = FailureDirectiveResolver(
        continue_if_safe_evaluator=evaluator
    )

    for status in (
        StepExecutionStatus.CANCELLED,
        StepExecutionStatus.PREEMPTED,
    ):
        decision = resolver.resolve(optional, status, running)
        assert decision.directive is StepFailureDirective.STOP_PLAN


def test_continue_if_safe_requires_explicit_evaluator_and_fails_closed() -> None:
    plan, running, _, _ = _running_execution()
    step = plan.steps[0].model_copy(
        update={"optional": True, "on_failure": "CONTINUE_IF_SAFE"}
    )

    unresolved = FailureDirectiveResolver().resolve(
        step,
        StepExecutionStatus.FAILED,
        running,
    )
    denied = FailureDirectiveResolver(
        continue_if_safe_evaluator=StaticContinueIfSafeEvaluator(False)
    ).resolve(step, StepExecutionStatus.FAILED, running)
    allowed = FailureDirectiveResolver(
        continue_if_safe_evaluator=StaticContinueIfSafeEvaluator(True)
    ).resolve(step, StepExecutionStatus.FAILED, running)

    assert unresolved.directive is StepFailureDirective.STOP_PLAN
    assert denied.directive is StepFailureDirective.STOP_PLAN
    assert allowed.directive is StepFailureDirective.CONTINUE


def test_failure_resolver_surfaces_fallback_without_executing_it() -> None:
    plan, running, _, _ = _running_execution()
    step = plan.steps[0].model_copy(
        update={"on_failure": "RUN_FALLBACK"}
    )

    decision = FailureDirectiveResolver().resolve(
        step,
        StepExecutionStatus.FAILED,
        running,
    )

    assert decision.directive is StepFailureDirective.RUN_FALLBACK


def test_iu2_does_not_resolve_or_invoke_capabilities() -> None:
    source = (
        inspect.getsource(runtime_check_module)
        + "\n"
        + inspect.getsource(scheduling_module)
    )

    forbidden = (
        "ExecutionImplementationResolver",
        "SkillRegistry",
        "WorkflowRegistry",
        "ToolRegistry",
        ".invoke(",
        ".execute(",
        ".start(",
        ".resume(",
        "runtime.validation",
        "runtime.knowledge",
        "runtime.response",
        "runtime.update",
        "httpx",
        "requests",
    )
    for token in forbidden:
        assert token not in source


def test_iu2_core_contains_no_domain_action_or_workflow_taxonomy() -> None:
    source = (
        inspect.getsource(runtime_check_module)
        + "\n"
        + inspect.getsource(scheduling_module)
    )

    for token in (
        "WEATHER",
        "NEWS",
        "MEDICAL",
        "PLAY_CONTENT",
        "NOTIFY_FAMILY",
    ):
        assert token not in source
