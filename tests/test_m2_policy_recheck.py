"""M2-IU6 Plan Policy Re-check tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from runtime.context_building import DefaultContextBuilder, RuntimeStateProvider
from runtime.contracts import (
    ActionPlanDraft,
    ApprovedActionPlan,
    PolicyDecision,
    RuntimeContext,
    RuntimeControlState,
    RuntimeInput,
    RuntimeStateContext,
)
from runtime.input_processing import DefaultInputProcessor
from runtime.interfaces.understanding import UnderstandingEngine
from runtime.orchestration import RuntimeOrchestrator
from runtime.policy_enforcement import (
    DefaultPolicyRechecker,
    PlanPolicyViolationError,
)
from runtime.policy_management import DefaultPolicyEngine
from runtime.safety import DefaultSafetyGuard
from tests.orchestration_stubs import (
    CallRecorder,
    StubExecutionEngine,
    StubPlanValidator,
    StubPlanner,
    StubResponseGenerator,
    StubResponsePlanner,
    StubResponseValidator,
    StubResultValidator,
    StubStateMemoryUpdater,
    build_action_plan_draft,
    build_policy_decision,
    build_runtime_input,
    build_understanding_state,
)


def _policy(**updates: object) -> PolicyDecision:
    return build_policy_decision().model_copy(update=updates)


def _draft(**updates: object) -> ActionPlanDraft:
    return build_action_plan_draft().model_copy(update=updates)


class FixedRuntimeStateProvider(RuntimeStateProvider):
    async def load(self, runtime_input: RuntimeInput) -> RuntimeStateContext:
        return RuntimeStateContext(
            current_state=RuntimeControlState.PROCESSING,
            previous_state=RuntimeControlState.IDLE,
            interruptible=True,
            entered_at=runtime_input.timestamp,
        )


class RequestAwareUnderstandingEngine(UnderstandingEngine):
    def __init__(self, recorder: CallRecorder) -> None:
        self._recorder = recorder

    async def understand(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext,
    ):
        del runtime_context
        self._recorder.record("UNDERSTANDING")
        base = build_understanding_state()
        metadata = base.metadata.model_copy(update={"request_id": runtime_input.request_id})
        return base.model_copy(update={"metadata": metadata})


class CapturingPolicyRechecker(DefaultPolicyRechecker):
    def __init__(self, recorder: CallRecorder) -> None:
        super().__init__()
        self._recorder = recorder
        self.last_output: ApprovedActionPlan | None = None

    async def recheck(
        self,
        action_plan_draft: ActionPlanDraft,
        policy_decision: PolicyDecision,
    ) -> ApprovedActionPlan:
        self._recorder.record("POLICY_RECHECK")
        self.last_output = await super().recheck(action_plan_draft, policy_decision)
        return self.last_output


def test_allowed_draft_becomes_approved_without_replanning() -> None:
    draft = build_action_plan_draft()
    approved_at = datetime(2026, 9, 17, 15, 30, tzinfo=UTC)
    result = asyncio.run(
        DefaultPolicyRechecker(clock=lambda: approved_at).recheck(
            draft,
            _policy(),
        )
    )

    assert isinstance(result, ApprovedActionPlan)
    assert result.plan_id == draft.plan_id
    assert result.request_id == draft.request_id
    assert result.steps == draft.steps
    assert result.goals == draft.goals
    assert result.approved_at == approved_at
    assert result.policy_snapshot["policy_decision_id"] == "policy-001"


def test_blocked_or_not_allowed_policy_cannot_approve() -> None:
    rechecker = DefaultPolicyRechecker()
    for policy in (
        _policy(allowed=False, blocked=True),
        _policy(allowed=False, blocked=False),
        _policy(allowed=True, blocked=True),
    ):
        with pytest.raises(PlanPolicyViolationError):
            asyncio.run(rechecker.recheck(_draft(), policy))


def test_forbidden_action_skill_and_tool_are_rejected() -> None:
    base = build_action_plan_draft()
    step = base.steps[0].model_copy(
        update={
            "action": "TEST_ACTION",
            "skill_id": "TEST_SKILL",
            "tool_requirement": "TEST_TOOL",
        }
    )
    draft = base.model_copy(update={"steps": [step]})

    for policy in (
        _policy(forbidden_actions=["TEST_ACTION"]),
        _policy(forbidden_skills=["TEST_SKILL"]),
        _policy(forbidden_tools=["TEST_TOOL"]),
    ):
        with pytest.raises(PlanPolicyViolationError):
            asyncio.run(DefaultPolicyRechecker().recheck(draft, policy))


def test_allow_lists_are_enforced_for_present_step_references() -> None:
    base = build_action_plan_draft()
    step = base.steps[0].model_copy(
        update={
            "action": "TEST_ACTION",
            "skill_id": "TEST_SKILL",
            "tool_requirement": "TEST_TOOL",
        }
    )
    draft = base.model_copy(update={"steps": [step]})
    policy = _policy(
        allowed_actions=["OTHER_ACTION"],
        allowed_skills=["OTHER_SKILL"],
        allowed_tools=["OTHER_TOOL"],
    )

    with pytest.raises(PlanPolicyViolationError):
        asyncio.run(DefaultPolicyRechecker().recheck(draft, policy))


def test_forced_action_must_be_present() -> None:
    with pytest.raises(PlanPolicyViolationError, match="forced_action"):
        asyncio.run(
            DefaultPolicyRechecker().recheck(
                _draft(),
                _policy(forced_action="TEST_FORCED_ACTION"),
            )
        )


def test_forced_workflow_must_be_present_and_exclusive_among_workflow_refs() -> None:
    base = build_action_plan_draft()
    forced_step = base.steps[0].model_copy(update={"workflow_id": "WF_FORCED"})
    accepted = base.model_copy(update={"steps": [forced_step]})
    result = asyncio.run(
        DefaultPolicyRechecker().recheck(
            accepted,
            _policy(forced_workflow="WF_FORCED"),
        )
    )
    assert result.steps[0].workflow_id == "WF_FORCED"

    extra_step = base.steps[0].model_copy(
        update={"step_id": "step-extra", "workflow_id": "WF_OTHER"}
    )
    violating = base.model_copy(update={"steps": [forced_step, extra_step]})
    with pytest.raises(PlanPolicyViolationError, match="outside forced_workflow"):
        asyncio.run(
            DefaultPolicyRechecker().recheck(
                violating,
                _policy(forced_workflow="WF_FORCED"),
            )
        )


def test_confirmation_required_needs_explicit_confirmation_plan() -> None:
    with pytest.raises(PlanPolicyViolationError, match="confirmation"):
        asyncio.run(
            DefaultPolicyRechecker().recheck(
                _draft(confirmation_plan=None),
                _policy(confirmation_required=True),
            )
        )

    approved = asyncio.run(
        DefaultPolicyRechecker().recheck(
            _draft(confirmation_plan={"required": True}),
            _policy(confirmation_required=True),
        )
    )
    assert approved.confirmation_plan == {"required": True}


def test_rechecker_does_not_mutate_draft_or_policy() -> None:
    draft = _draft()
    policy = _policy()
    before_draft = draft.model_dump()
    before_policy = policy.model_dump()

    asyncio.run(DefaultPolicyRechecker().recheck(draft, policy))

    assert draft.model_dump() == before_draft
    assert policy.model_dump() == before_policy


def test_real_policy_rechecker_integrates_into_full_runtime_chain() -> None:
    recorder = CallRecorder()
    rechecker = CapturingPolicyRechecker(recorder)
    raw_input = build_runtime_input(
        request_id="request-policy-recheck-e2e",
        trace_id="trace-policy-recheck-e2e",
        session_id="session-policy-recheck-e2e",
        text="hello recheck",
    )
    orchestrator = RuntimeOrchestrator(
        input_processor=DefaultInputProcessor(),
        safety_guard=DefaultSafetyGuard(rules=[]),
        context_builder=DefaultContextBuilder(
            runtime_state_provider=FixedRuntimeStateProvider()
        ),
        understanding_engine=RequestAwareUnderstandingEngine(recorder),
        policy_engine=DefaultPolicyEngine(rules=[]),
        planner=StubPlanner(recorder),
        plan_validator=StubPlanValidator(recorder),
        policy_rechecker=rechecker,
        execution_engine=StubExecutionEngine(recorder),
        result_validator=StubResultValidator(recorder),
        response_planner=StubResponsePlanner(recorder),
        response_generator=StubResponseGenerator(recorder),
        response_validator=StubResponseValidator(recorder),
        state_memory_updater=StubStateMemoryUpdater(recorder),
    )

    outcome = asyncio.run(orchestrator.run(raw_input))

    assert outcome.runtime_response is not None
    assert outcome.update_result is not None
    assert isinstance(rechecker.last_output, ApprovedActionPlan)
    assert [event.stage_name for event in outcome.trace.stage_events] == [
        "INPUT",
        "SAFETY_EARLY",
        "CONTEXT",
        "UNDERSTANDING",
        "SAFETY_DEEP",
        "POLICY",
        "PLAN",
        "PLAN_VALIDATE",
        "POLICY_RECHECK",
        "EXECUTE",
        "RESULT_VALIDATE",
        "RESPONSE_PLAN",
        "RESPONSE_GENERATE",
        "RESPONSE_VALIDATE",
        "UPDATE",
    ]
