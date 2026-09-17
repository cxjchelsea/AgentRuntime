"""M2-IU4 Policy Engine tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from runtime.context_building import DefaultContextBuilder, RuntimeStateProvider
from runtime.contracts import (
    RuntimeContext,
    RuntimeControlState,
    RuntimeInput,
    RuntimeStateContext,
    SafetyPhase,
    SafetyResult,
    SafetyRiskLevel,
    UnderstandingState,
    ValidationMode,
)
from runtime.input_processing import DefaultInputProcessor
from runtime.interfaces.understanding import UnderstandingEngine
from runtime.orchestration import RuntimeOrchestrator
from runtime.policy_management import (
    DefaultPolicyEngine,
    DuplicatePolicyRuleError,
    PolicyConflictError,
    PolicyFragment,
    PolicyInvariantError,
    PolicyRule,
    PolicyRuleExecutionError,
)
from runtime.safety import DefaultSafetyGuard
from tests.orchestration_stubs import (
    CallRecorder,
    StubExecutionEngine,
    StubPlanner,
    StubPlanValidator,
    StubPolicyRechecker,
    StubResponseGenerator,
    StubResponsePlanner,
    StubResponseValidator,
    StubResultValidator,
    StubStateMemoryUpdater,
    build_runtime_context,
    build_runtime_input,
    build_safety_result,
    build_understanding_state,
)


def _deep_safety(**updates: object) -> SafetyResult:
    return build_safety_result(SafetyPhase.DEEP).model_copy(update=updates)


class StaticPolicyRule(PolicyRule):
    def __init__(self, rule_id: str, fragment: PolicyFragment | None) -> None:
        self._rule_id = rule_id
        self._fragment = fragment

    @property
    def rule_id(self) -> str:
        return self._rule_id

    async def evaluate(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        safety_result: SafetyResult,
    ) -> PolicyFragment | None:
        del runtime_context, understanding_state, safety_result
        return self._fragment


class ExplodingPolicyRule(PolicyRule):
    @property
    def rule_id(self) -> str:
        return "TEST_EXPLODING_RULE"

    async def evaluate(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        safety_result: SafetyResult,
    ) -> PolicyFragment | None:
        del runtime_context, understanding_state, safety_result
        raise ValueError("sensitive policy payload")


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
    ) -> UnderstandingState:
        del runtime_context
        self._recorder.record("UNDERSTANDING")
        base = build_understanding_state()
        metadata = base.metadata.model_copy(
            update={"request_id": runtime_input.request_id}
        )
        return base.model_copy(update={"metadata": metadata})


def test_no_matching_rules_yields_allowing_canonical_policy() -> None:
    engine = DefaultPolicyEngine(
        rules=[],
        decision_id_factory=lambda: "policy-test",
        clock=lambda: datetime(2026, 9, 17, 14, 0, tzinfo=UTC),
    )

    result = asyncio.run(
        engine.evaluate(
            build_runtime_context(),
            build_understanding_state(),
            _deep_safety(),
        )
    )

    assert result.policy_decision_id == "policy-test"
    assert result.allowed is True
    assert result.blocked is False
    assert result.priority == 0
    assert result.interrupt_current_task is False
    assert result.validation_mode is ValidationMode.STANDARD
    assert result.reason_codes == ["SAFE"]


def test_safety_hard_constraints_are_projected_without_domain_rule() -> None:
    safety = _deep_safety(
        risk_detected=True,
        risk_level=SafetyRiskLevel.HIGH,
        allowed_to_continue_normal_flow=False,
        interrupt_current_task=True,
        safety_lock_required=True,
        requires_immediate_action=True,
        force_workflow="TEST_SAFETY_WORKFLOW",
        restricted_actions=["TEST_BLOCKED_ACTION"],
        reason_codes=["TEST_SAFETY_REASON"],
    )

    result = asyncio.run(
        DefaultPolicyEngine().evaluate(
            build_runtime_context(),
            build_understanding_state(),
            safety,
        )
    )

    assert result.allowed is False
    assert result.blocked is True
    assert result.interrupt_current_task is True
    assert result.forced_workflow == "TEST_SAFETY_WORKFLOW"
    assert result.forbidden_actions == ["TEST_BLOCKED_ACTION"]
    assert result.policy_flags == ["SAFETY_LOCK_REQUIRED", "IMMEDIATE_ACTION_REQUIRED"]


def test_deny_wins_and_validation_mode_uses_strictest_fragment() -> None:
    rules = [
        StaticPolicyRule(
            "TEST_ALLOW",
            PolicyFragment(
                source_id="TEST_ALLOW",
                allowed=True,
                priority=10,
                validation_mode=ValidationMode.FAST,
            ),
        ),
        StaticPolicyRule(
            "TEST_DENY",
            PolicyFragment(
                source_id="TEST_DENY",
                allowed=False,
                blocked=True,
                priority=80,
                validation_mode=ValidationMode.STRICT,
                reason_codes=("TEST_DENY_REASON",),
            ),
        ),
    ]

    result = asyncio.run(
        DefaultPolicyEngine(rules).evaluate(
            build_runtime_context(),
            build_understanding_state(),
            _deep_safety(),
        )
    )

    assert result.allowed is False
    assert result.blocked is True
    assert result.priority == 80
    assert result.validation_mode is ValidationMode.STRICT
    assert "TEST_DENY_REASON" in result.reason_codes


def test_allow_lists_intersect_and_forbidden_lists_take_precedence() -> None:
    rules = [
        StaticPolicyRule(
            "TEST_RULE_A",
            PolicyFragment(
                source_id="TEST_RULE_A",
                allowed_actions=("A", "B", "C"),
                forbidden_tools=("T3",),
            ),
        ),
        StaticPolicyRule(
            "TEST_RULE_B",
            PolicyFragment(
                source_id="TEST_RULE_B",
                allowed_actions=("B", "C", "D"),
                forbidden_actions=("C",),
                forbidden_tools=("T4",),
            ),
        ),
    ]

    result = asyncio.run(
        DefaultPolicyEngine(rules).evaluate(
            build_runtime_context(),
            build_understanding_state(),
            _deep_safety(),
        )
    )

    assert result.allowed_actions == ["B"]
    assert result.forbidden_actions == ["C"]
    assert result.forbidden_tools == ["T3", "T4"]


def test_conflicting_forced_workflows_fail_closed() -> None:
    rules = [
        StaticPolicyRule(
            "TEST_RULE_A",
            PolicyFragment(source_id="TEST_RULE_A", forced_workflow="WF_A"),
        ),
        StaticPolicyRule(
            "TEST_RULE_B",
            PolicyFragment(source_id="TEST_RULE_B", forced_workflow="WF_B"),
        ),
    ]

    with pytest.raises(PolicyConflictError, match="forced_workflow"):
        asyncio.run(
            DefaultPolicyEngine(rules).evaluate(
                build_runtime_context(),
                build_understanding_state(),
                _deep_safety(),
            )
        )


def test_conflicting_response_constraints_fail_closed() -> None:
    rules = [
        StaticPolicyRule(
            "TEST_RULE_A",
            PolicyFragment(
                source_id="TEST_RULE_A",
                response_constraints={"mode": "A"},
            ),
        ),
        StaticPolicyRule(
            "TEST_RULE_B",
            PolicyFragment(
                source_id="TEST_RULE_B",
                response_constraints={"mode": "B"},
            ),
        ),
    ]

    with pytest.raises(PolicyConflictError, match="response constraint"):
        asyncio.run(
            DefaultPolicyEngine(rules).evaluate(
                build_runtime_context(),
                build_understanding_state(),
                _deep_safety(),
            )
        )


def test_duplicate_rule_ids_are_rejected() -> None:
    fragment = PolicyFragment(source_id="TEST_DUPLICATE")
    rule = StaticPolicyRule("TEST_DUPLICATE", fragment)
    with pytest.raises(DuplicatePolicyRuleError):
        DefaultPolicyEngine([rule, rule])


def test_fragment_source_must_match_rule_id() -> None:
    rule = StaticPolicyRule(
        "TEST_RULE",
        PolicyFragment(source_id="OTHER_RULE"),
    )
    with pytest.raises(Exception, match="source_id"):
        asyncio.run(
            DefaultPolicyEngine([rule]).evaluate(
                build_runtime_context(),
                build_understanding_state(),
                _deep_safety(),
            )
        )


def test_policy_rule_exception_is_wrapped_without_leaking_message() -> None:
    with pytest.raises(PolicyRuleExecutionError) as captured:
        asyncio.run(
            DefaultPolicyEngine([ExplodingPolicyRule()]).evaluate(
                build_runtime_context(),
                build_understanding_state(),
                _deep_safety(),
            )
        )

    assert "sensitive policy payload" not in str(captured.value)
    assert isinstance(captured.value.cause, ValueError)


def test_policy_requires_deep_safety_and_matching_request() -> None:
    engine = DefaultPolicyEngine()
    with pytest.raises(PolicyInvariantError, match="DEEP"):
        asyncio.run(
            engine.evaluate(
                build_runtime_context(),
                build_understanding_state(),
                build_safety_result(SafetyPhase.EARLY),
            )
        )

    mismatch = _deep_safety(request_id="other-request")
    with pytest.raises(PolicyInvariantError, match="request_id"):
        asyncio.run(
            engine.evaluate(
                build_runtime_context(),
                build_understanding_state(),
                mismatch,
            )
        )


def test_real_policy_engine_integrates_into_full_runtime_chain() -> None:
    recorder = CallRecorder()
    raw_input = build_runtime_input(
        request_id="request-policy-e2e",
        trace_id="trace-policy-e2e",
        session_id="session-policy-e2e",
        text="hello policy",
    )
    policy_rule = StaticPolicyRule(
        "TEST_RUNTIME_POLICY",
        PolicyFragment(
            source_id="TEST_RUNTIME_POLICY",
            priority=42,
            confirmation_required=True,
            reason_codes=("TEST_RUNTIME_POLICY_MATCH",),
        ),
    )
    orchestrator = RuntimeOrchestrator(
        input_processor=DefaultInputProcessor(),
        safety_guard=DefaultSafetyGuard(rules=[]),
        context_builder=DefaultContextBuilder(
            runtime_state_provider=FixedRuntimeStateProvider()
        ),
        understanding_engine=RequestAwareUnderstandingEngine(recorder),
        policy_engine=DefaultPolicyEngine([policy_rule]),
        planner=StubPlanner(recorder),
        plan_validator=StubPlanValidator(recorder),
        policy_rechecker=StubPolicyRechecker(recorder),
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
