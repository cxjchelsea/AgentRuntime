"""M5-IU2 Runtime Execution Check + Step Scheduler gates."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

import runtime.execution.runtime_check as runtime_check_module
import runtime.execution.scheduler as scheduler_module
from runtime.contracts.enums import RuntimeControlState
from runtime.execution import (
    ApprovedPlanExecutionValidator,
    CallableExecutionIdentifierFactory,
    ExecutionContextBuilder,
    ExecutionControlSignal,
    ExecutionControlSignalType,
    ExecutionFoundation,
    ExecutionLifecycleManager,
    ExecutionRecordFactory,
    InMemoryExecutionStateStore,
    PolicySnapshotValidityDecision,
    PolicySnapshotValidityStatus,
    RuntimeExecutionChecker,
    RuntimeExecutionCheckStatus,
    RuntimeExecutionSnapshot,
    SequentialStepScheduler,
    StateEligibilityDecision,
    StateEligibilityStatus,
    StepConditionDecision,
    StepConditionStatus,
    StepExecutionStatus,
    StepScheduleStatus,
)
from tests.orchestration_stubs import (
    build_approved_action_plan,
    build_runtime_context,
)

FIXED_TIME = datetime(2026, 9, 20, 8, 30, tzinfo=UTC)


def _terminal_signal(
    signal_type: ExecutionControlSignalType,
    *,
    reason_code: str,
    source: str,
    target_execution_id: str = "execution-iu2-001",
    signal_id: str | None = None,
) -> ExecutionControlSignal:
    return ExecutionControlSignal(
        signal_type=signal_type,
        reason_code=reason_code,
        source=source,
        signal_id=signal_id or f"signal-{signal_type.value.lower()}-001",
        target_execution_id=target_execution_id,
        issued_at=FIXED_TIME,
    )


class StaticSnapshotProvider:
    def __init__(self, snapshot: RuntimeExecutionSnapshot) -> None:
        self.snapshot = snapshot
        self.calls = 0

    async def get_snapshot(self, execution_context):
        del execution_context
        self.calls += 1
        return self.snapshot


class StaticControlSignalSource:
    def __init__(self, signal: ExecutionControlSignal) -> None:
        self.signal = signal

    async def get_signal(self, execution_id: str) -> ExecutionControlSignal:
        assert execution_id
        return self.signal


class StaticPolicyValidityEvaluator:
    def __init__(self, decision: PolicySnapshotValidityDecision) -> None:
        self.decision = decision

    async def evaluate(self, *, execution_context, snapshot):
        del execution_context, snapshot
        return self.decision


class StaticStateEligibilityEvaluator:
    def __init__(self, decision: StateEligibilityDecision) -> None:
        self.decision = decision

    async def evaluate(self, *, step, execution_context, snapshot):
        del step, execution_context, snapshot
        return self.decision


class StaticConditionEvaluator:
    def __init__(self, decision: StepConditionDecision) -> None:
        self.decision = decision

    async def evaluate(self, *, step, prepared):
        del step, prepared
        return self.decision


def _foundation(execution_id: str = "execution-iu2-001"):
    ids = CallableExecutionIdentifierFactory(
        execution_id_factory=lambda: execution_id,
        step_execution_id_factory=lambda step_id: f"{execution_id}:{step_id}",
    )
    store = InMemoryExecutionStateStore()
    foundation = ExecutionFoundation(
        plan_validator=ApprovedPlanExecutionValidator(),
        context_builder=ExecutionContextBuilder(identifier_factory=ids),
        record_factory=ExecutionRecordFactory(
            identifier_factory=ids,
            clock=lambda: FIXED_TIME,
        ),
        execution_store=store,
    )
    return foundation, store


def _prepared(plan=None):
    approved_plan = plan or build_approved_action_plan()
    foundation, _ = _foundation()
    prepared = asyncio.run(
        foundation.initialize(
            approved_plan,
            build_runtime_context(),
        )
    )
    return approved_plan, prepared


def _running_prepared(plan=None):
    approved_plan, prepared = _prepared(plan)
    running = ExecutionLifecycleManager().start_execution(
        prepared,
        at=FIXED_TIME,
    )
    return approved_plan, running


def _runtime_checker(
    *,
    snapshot: RuntimeExecutionSnapshot | None = None,
    signal: ExecutionControlSignal | None = None,
    policy: PolicySnapshotValidityDecision | None = None,
    state: StateEligibilityDecision | None = None,
):
    snapshot_provider = StaticSnapshotProvider(
        snapshot
        or RuntimeExecutionSnapshot(
            session_id="session-001",
            identity_scope="scope-001",
            current_state=RuntimeControlState.IDLE,
            session_active=True,
            safety_lock=False,
        )
    )
    checker = RuntimeExecutionChecker(
        snapshot_provider=snapshot_provider,
        control_signal_source=StaticControlSignalSource(
            signal
            or ExecutionControlSignal(
                signal_type=ExecutionControlSignalType.NONE,
            )
        ),
        policy_validity_evaluator=StaticPolicyValidityEvaluator(
            policy
            or PolicySnapshotValidityDecision(
                status=PolicySnapshotValidityStatus.VALID,
                reason_codes=("POLICY_SNAPSHOT_VALID",),
            )
        ),
        state_eligibility_evaluator=StaticStateEligibilityEvaluator(
            state
            or StateEligibilityDecision(
                status=StateEligibilityStatus.ELIGIBLE,
                reason_codes=("STATE_ELIGIBLE",),
            )
        ),
    )
    return checker, snapshot_provider


def test_runtime_execution_check_allows_only_after_all_runtime_facts_pass() -> None:
    plan, prepared = _prepared()
    checker, _ = _runtime_checker()

    decision = asyncio.run(
        checker.check(
            step=plan.steps[0],
            execution_context=prepared.execution_context,
        )
    )

    assert decision.status is RuntimeExecutionCheckStatus.ALLOWED
    assert decision.reason_codes == ("RUNTIME_EXECUTION_ALLOWED",)


def test_cancel_signal_preempts_other_runtime_checks_without_redeciding_priority() -> (
    None
):
    plan, prepared = _prepared()
    checker, snapshot_provider = _runtime_checker(
        signal=_terminal_signal(
            ExecutionControlSignalType.CANCEL,
            reason_code="USER_STOP",
            source="RUNTIME",
        )
    )

    decision = asyncio.run(
        checker.check(
            step=plan.steps[0],
            execution_context=prepared.execution_context,
        )
    )

    assert decision.status is RuntimeExecutionCheckStatus.CANCEL_REQUIRED
    assert decision.reason_codes == ("USER_STOP",)
    assert snapshot_provider.calls == 0


def test_preempt_signal_is_consumed_not_recomputed() -> None:
    plan, prepared = _prepared()
    checker, snapshot_provider = _runtime_checker(
        signal=_terminal_signal(
            ExecutionControlSignalType.PREEMPT,
            reason_code="HIGH_PRIORITY_PREEMPTION",
            source="M2",
        )
    )

    decision = asyncio.run(
        checker.check(
            step=plan.steps[0],
            execution_context=prepared.execution_context,
        )
    )

    assert decision.status is RuntimeExecutionCheckStatus.PREEMPT_REQUIRED
    assert decision.reason_codes == ("HIGH_PRIORITY_PREEMPTION",)
    assert snapshot_provider.calls == 0


def test_control_signal_target_mismatch_fails_closed_before_other_checks() -> None:
    plan, prepared = _prepared()
    checker, snapshot_provider = _runtime_checker(
        signal=_terminal_signal(
            ExecutionControlSignalType.CANCEL,
            reason_code="USER_STOP",
            source="RUNTIME",
            target_execution_id="different-execution",
        )
    )

    decision = asyncio.run(
        checker.check(
            step=plan.steps[0],
            execution_context=prepared.execution_context,
        )
    )

    assert decision.status is RuntimeExecutionCheckStatus.UNKNOWN
    assert decision.reason_codes == ("CONTROL_SIGNAL_TARGET_MISMATCH",)
    assert snapshot_provider.calls == 0


def test_runtime_execution_check_fails_closed_on_identity_or_session_drift() -> None:
    plan, prepared = _prepared()
    checker, _ = _runtime_checker(
        snapshot=RuntimeExecutionSnapshot(
            session_id="session-001",
            identity_scope="other-scope",
            current_state=RuntimeControlState.IDLE,
            session_active=True,
        )
    )

    decision = asyncio.run(
        checker.check(
            step=plan.steps[0],
            execution_context=prepared.execution_context,
        )
    )

    assert decision.status is RuntimeExecutionCheckStatus.BLOCKED
    assert decision.reason_codes == ("IDENTITY_SCOPE_MISMATCH",)


def test_runtime_execution_check_preserves_unknown_session_validity() -> None:
    plan, prepared = _prepared()
    checker, _ = _runtime_checker(
        snapshot=RuntimeExecutionSnapshot(
            session_id="session-001",
            identity_scope="scope-001",
            current_state=RuntimeControlState.IDLE,
            session_active=None,
        )
    )

    decision = asyncio.run(
        checker.check(
            step=plan.steps[0],
            execution_context=prepared.execution_context,
        )
    )

    assert decision.status is RuntimeExecutionCheckStatus.UNKNOWN
    assert decision.reason_codes == ("SESSION_VALIDITY_UNKNOWN",)


def test_unknown_safety_lock_state_is_preserved_and_never_allowed() -> None:
    plan, prepared = _prepared()
    checker, _ = _runtime_checker(
        snapshot=RuntimeExecutionSnapshot(
            session_id="session-001",
            identity_scope="scope-001",
            current_state=RuntimeControlState.IDLE,
            session_active=True,
            safety_lock=None,
        )
    )

    decision = asyncio.run(
        checker.check(
            step=plan.steps[0],
            execution_context=prepared.execution_context,
        )
    )

    assert decision.status is RuntimeExecutionCheckStatus.UNKNOWN
    assert decision.reason_codes == ("SAFETY_LOCK_STATE_UNKNOWN",)


def test_safety_lock_blocks_only_explicitly_restricted_action() -> None:
    plan, prepared = _prepared()
    checker, _ = _runtime_checker(
        snapshot=RuntimeExecutionSnapshot(
            session_id="session-001",
            identity_scope="scope-001",
            current_state=RuntimeControlState.IDLE,
            session_active=True,
            safety_lock=True,
            restricted_actions=(plan.steps[0].action,),
        )
    )

    decision = asyncio.run(
        checker.check(
            step=plan.steps[0],
            execution_context=prepared.execution_context,
        )
    )

    assert decision.status is RuntimeExecutionCheckStatus.BLOCKED
    assert decision.reason_codes == ("ACTION_RESTRICTED_BY_SAFETY_LOCK",)


def test_safety_lock_without_restriction_facts_is_unknown_not_allow() -> None:
    plan, prepared = _prepared()
    checker, _ = _runtime_checker(
        snapshot=RuntimeExecutionSnapshot(
            session_id="session-001",
            identity_scope="scope-001",
            current_state=RuntimeControlState.IDLE,
            session_active=True,
            safety_lock=True,
            restricted_actions=None,
        )
    )

    decision = asyncio.run(
        checker.check(
            step=plan.steps[0],
            execution_context=prepared.execution_context,
        )
    )

    assert decision.status is RuntimeExecutionCheckStatus.UNKNOWN
    assert decision.reason_codes == ("SAFETY_RESTRICTIONS_UNKNOWN",)


def test_invalid_policy_snapshot_blocks_without_recomputing_policy() -> None:
    plan, prepared = _prepared()
    checker, _ = _runtime_checker(
        policy=PolicySnapshotValidityDecision(
            status=PolicySnapshotValidityStatus.INVALID,
            reason_codes=("POLICY_SNAPSHOT_EXPIRED",),
        )
    )

    decision = asyncio.run(
        checker.check(
            step=plan.steps[0],
            execution_context=prepared.execution_context,
        )
    )

    assert decision.status is RuntimeExecutionCheckStatus.BLOCKED
    assert decision.reason_codes == ("POLICY_SNAPSHOT_EXPIRED",)


def test_unknown_runtime_state_eligibility_is_preserved() -> None:
    plan, prepared = _prepared()
    checker, _ = _runtime_checker(
        state=StateEligibilityDecision(
            status=StateEligibilityStatus.UNKNOWN,
            reason_codes=("STATE_ELIGIBILITY_UNKNOWN",),
        )
    )

    decision = asyncio.run(
        checker.check(
            step=plan.steps[0],
            execution_context=prepared.execution_context,
        )
    )

    assert decision.status is RuntimeExecutionCheckStatus.UNKNOWN


def _two_step_plan(*, first_optional: bool | None = None, dependency: bool = True):
    plan = build_approved_action_plan()
    first = plan.steps[0].model_copy(update={"optional": first_optional})
    second = plan.steps[0].model_copy(
        update={
            "step_id": "step-002",
            "action": "SECOND_ACTION",
            "depends_on": ["step-001"] if dependency else None,
            "optional": False,
        }
    )
    return plan.model_copy(update={"steps": [first, second]})


def _finish_first_step(plan, prepared, *, status: StepExecutionStatus):
    lifecycle = ExecutionLifecycleManager()
    running = lifecycle.start_execution(prepared, at=FIXED_TIME)
    first_running = lifecycle.start_step(
        running,
        step_id="step-001",
        at=FIXED_TIME + timedelta(seconds=1),
    )
    return lifecycle.finish_step(
        first_running,
        step_id="step-001",
        status=status,
        at=FIXED_TIME + timedelta(seconds=2),
    )


def test_scheduler_blocks_before_execution_enters_running_state() -> None:
    plan, prepared = _prepared()

    decision = asyncio.run(
        SequentialStepScheduler().next_step(
            approved_plan=plan,
            prepared=prepared,
        )
    )

    assert decision.status is StepScheduleStatus.BLOCKED
    assert decision.reason_codes == ("EXECUTION_NOT_RUNNING",)


def test_scheduler_returns_first_approved_pending_step() -> None:
    plan, prepared = _running_prepared()
    decision = asyncio.run(
        SequentialStepScheduler().next_step(
            approved_plan=plan,
            prepared=prepared,
        )
    )

    assert decision.status is StepScheduleStatus.READY
    assert decision.step_id == "step-001"


def test_scheduler_waits_when_a_step_is_already_running() -> None:
    plan, prepared = _prepared()
    running = ExecutionLifecycleManager().start_execution(
        prepared,
        at=FIXED_TIME,
    )
    step_running = ExecutionLifecycleManager().start_step(
        running,
        step_id="step-001",
        at=FIXED_TIME + timedelta(seconds=1),
    )

    decision = asyncio.run(
        SequentialStepScheduler().next_step(
            approved_plan=plan,
            prepared=step_running,
        )
    )

    assert decision.status is StepScheduleStatus.WAITING
    assert decision.step_id == "step-001"


def test_scheduler_advances_after_successful_dependency() -> None:
    plan = _two_step_plan()
    _, prepared = _prepared(plan)
    first_done = _finish_first_step(
        plan,
        prepared,
        status=StepExecutionStatus.SUCCESS,
    )

    decision = asyncio.run(
        SequentialStepScheduler().next_step(
            approved_plan=plan,
            prepared=first_done,
        )
    )

    assert decision.status is StepScheduleStatus.READY
    assert decision.step_id == "step-002"


def test_scheduler_skips_dependency_child_after_optional_dependency_failure() -> None:
    plan = _two_step_plan(first_optional=True)
    _, prepared = _prepared(plan)
    first_done = _finish_first_step(
        plan,
        prepared,
        status=StepExecutionStatus.FAILED,
    )

    decision = asyncio.run(
        SequentialStepScheduler().next_step(
            approved_plan=plan,
            prepared=first_done,
        )
    )

    assert decision.status is StepScheduleStatus.SKIP
    assert decision.step_id == "step-002"
    assert decision.reason_codes == ("DEPENDENCY_NOT_SUCCESSFUL",)


def test_scheduler_blocks_after_required_previous_step_failure() -> None:
    plan = _two_step_plan(first_optional=False, dependency=False)
    _, prepared = _prepared(plan)
    first_done = _finish_first_step(
        plan,
        prepared,
        status=StepExecutionStatus.FAILED,
    )

    decision = asyncio.run(
        SequentialStepScheduler().next_step(
            approved_plan=plan,
            prepared=first_done,
        )
    )

    assert decision.status is StepScheduleStatus.BLOCKED
    assert decision.reason_codes == ("REQUIRED_PREVIOUS_STEP_NOT_SUCCESSFUL",)


def test_optional_previous_step_failure_may_continue_when_no_dependency_requires_it() -> (
    None
):
    plan = _two_step_plan(first_optional=True, dependency=False)
    _, prepared = _prepared(plan)
    first_done = _finish_first_step(
        plan,
        prepared,
        status=StepExecutionStatus.FAILED,
    )

    decision = asyncio.run(
        SequentialStepScheduler().next_step(
            approved_plan=plan,
            prepared=first_done,
        )
    )

    assert decision.status is StepScheduleStatus.READY
    assert decision.step_id == "step-002"


def test_scheduler_uses_injected_simple_condition_without_parsing_business_rules() -> (
    None
):
    plan, prepared = _running_prepared()
    scheduler = SequentialStepScheduler(
        condition_evaluator=StaticConditionEvaluator(
            StepConditionDecision(
                status=StepConditionStatus.NOT_SATISFIED,
                reason_codes=("REGISTERED_CONDITION_FALSE",),
            )
        )
    )

    decision = asyncio.run(
        scheduler.next_step(
            approved_plan=plan,
            prepared=prepared,
        )
    )

    assert decision.status is StepScheduleStatus.SKIP
    assert decision.reason_codes == ("REGISTERED_CONDITION_FALSE",)


def test_scheduler_preserves_unknown_condition_fail_closed() -> None:
    plan, prepared = _running_prepared()
    scheduler = SequentialStepScheduler(
        condition_evaluator=StaticConditionEvaluator(
            StepConditionDecision(
                status=StepConditionStatus.UNKNOWN,
                reason_codes=("CONDITION_UNKNOWN",),
            )
        )
    )

    decision = asyncio.run(
        scheduler.next_step(
            approved_plan=plan,
            prepared=prepared,
        )
    )

    assert decision.status is StepScheduleStatus.UNKNOWN


def test_scheduler_reports_complete_when_no_pending_steps_remain() -> None:
    plan, prepared = _prepared()
    first_done = _finish_first_step(
        plan,
        prepared,
        status=StepExecutionStatus.SUCCESS,
    )

    decision = asyncio.run(
        SequentialStepScheduler().next_step(
            approved_plan=plan,
            prepared=first_done,
        )
    )

    assert decision.status is StepScheduleStatus.COMPLETE
    assert decision.step_id is None


def test_scheduler_rejects_plan_execution_alignment_drift() -> None:
    plan, prepared = _running_prepared()
    drifted = replace(
        prepared,
        execution_record=replace(
            prepared.execution_record,
            plan_id="other-plan",
        ),
    )

    with pytest.raises(ValueError, match="plan_id"):
        asyncio.run(
            SequentialStepScheduler().next_step(
                approved_plan=plan,
                prepared=drifted,
            )
        )


def test_iu2_does_not_execute_capability_or_import_later_execution_layers() -> None:
    source = "\n".join(
        (
            inspect.getsource(runtime_check_module),
            inspect.getsource(scheduler_module),
        )
    )

    forbidden = (
        "runtime.validation",
        "runtime.knowledge",
        "runtime.response",
        "runtime.update",
        "ToolImplementation",
        "SkillImplementation",
        "WorkflowImplementation",
        "ExecutionImplementationResolver",
        "ExecutionPermissionEvaluator",
        "httpx",
        "requests",
    )
    for token in forbidden:
        assert token not in source
