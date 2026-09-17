"""M2-IU1：真实双阶段 Safety Guard 测试。

测试只使用 TEST 规则，不把任何真实 Domain 风险条件写入 Runtime Core。
"""

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
)
from runtime.input_processing import DefaultInputProcessor
from runtime.orchestration import RuntimeOrchestrator, StageExecutionError
from runtime.safety import (
    DefaultSafetyGuard,
    DuplicateSafetyRuleError,
    InvalidSafetyFindingError,
    SafetyFinding,
    SafetyGuardInvariantError,
    SafetyRule,
    SafetyRuleConflictError,
    SafetyRuleExecutionError,
)
from tests.orchestration_stubs import (
    CallRecorder,
    StubExecutionEngine,
    StubPlanner,
    StubPlanValidator,
    StubPolicyEngine,
    StubPolicyRechecker,
    StubResponseGenerator,
    StubResponsePlanner,
    StubResponseValidator,
    StubResultValidator,
    StubStateMemoryUpdater,
    StubUnderstandingEngine,
    build_runtime_context,
    build_runtime_input,
    build_safety_result,
    build_understanding_state,
)

FIXED_TIME = datetime(2026, 9, 17, 4, 30, tzinfo=UTC)


class BaseTestRule(SafetyRule):
    def __init__(self, rule_id: str) -> None:
        self._rule_id = rule_id

    @property
    def rule_id(self) -> str:
        return self._rule_id


class EarlyHighRule(BaseTestRule):
    async def evaluate_early(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext | None,
    ) -> SafetyFinding | None:
        if runtime_input.text != "TEST_RISK":
            return None
        return SafetyFinding(
            rule_id=self.rule_id,
            risk_level=SafetyRiskLevel.HIGH,
            reason_codes=("TEST_EARLY_RISK",),
            risk_types=("TEST_RISK_TYPE",),
            evidence={"source": "TEST_RULE"},
            confidence=0.9,
            interrupt_current_task=True,
            allowed_to_continue_normal_flow=False,
            safety_lock_required=True,
            force_workflow="TEST_SAFETY_WORKFLOW",
            requires_immediate_action=True,
            restricted_actions=("TEST_BLOCKED_ACTION",),
        )


class DeepCriticalRule(BaseTestRule):
    async def evaluate_deep(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        early_safety: SafetyResult,
    ) -> SafetyFinding | None:
        if not understanding_state.risk or not understanding_state.risk.get(
            "test_flag"
        ):
            return None
        return SafetyFinding(
            rule_id=self.rule_id,
            risk_level=SafetyRiskLevel.CRITICAL,
            reason_codes=("TEST_DEEP_RISK",),
            risk_types=("TEST_DEEP_TYPE",),
            confidence=0.95,
            interrupt_current_task=True,
            allowed_to_continue_normal_flow=False,
            safety_lock_required=True,
            force_workflow="TEST_SAFETY_WORKFLOW",
            requires_immediate_action=True,
        )


class EarlyLowAllowRule(BaseTestRule):
    """较低风险且允许继续，用于验证最严格聚合。"""

    async def evaluate_early(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext | None,
    ) -> SafetyFinding | None:
        return SafetyFinding(
            rule_id=self.rule_id,
            risk_level=SafetyRiskLevel.LOW,
            reason_codes=("TEST_LOW",),
            allowed_to_continue_normal_flow=True,
            restricted_actions=("TEST_LOW_RESTRICTED",),
        )


class EarlyHighDenyRule(BaseTestRule):
    """较高风险且禁止继续，用于验证最严格聚合。"""

    async def evaluate_early(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext | None,
    ) -> SafetyFinding | None:
        return SafetyFinding(
            rule_id=self.rule_id,
            risk_level=SafetyRiskLevel.HIGH,
            reason_codes=("TEST_HIGH",),
            interrupt_current_task=True,
            allowed_to_continue_normal_flow=False,
            restricted_actions=("TEST_HIGH_RESTRICTED",),
        )


class ConflictingWorkflowRule(BaseTestRule):
    def __init__(self, rule_id: str, workflow: str) -> None:
        super().__init__(rule_id)
        self._workflow = workflow

    async def evaluate_early(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext | None,
    ) -> SafetyFinding | None:
        return SafetyFinding(
            rule_id=self.rule_id,
            risk_level=SafetyRiskLevel.HIGH,
            reason_codes=(f"{self.rule_id}_MATCH",),
            allowed_to_continue_normal_flow=False,
            force_workflow=self._workflow,
        )


class ExplodingRule(BaseTestRule):
    async def evaluate_early(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext | None,
    ) -> SafetyFinding | None:
        raise ValueError("rule bug with private payload")


class WrongRuleIdFindingRule(BaseTestRule):
    async def evaluate_early(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext | None,
    ) -> SafetyFinding | None:
        return SafetyFinding(
            rule_id="OTHER_RULE",
            risk_level=SafetyRiskLevel.LOW,
            reason_codes=("TEST",),
        )


class GateRuntimeStateProvider(RuntimeStateProvider):
    async def load(self, runtime_input: RuntimeInput) -> RuntimeStateContext:
        return RuntimeStateContext(
            current_state=RuntimeControlState.PROCESSING,
            previous_state=RuntimeControlState.LISTENING,
            interruptible=True,
            entered_at=runtime_input.timestamp,
        )


def _guard(*rules: SafetyRule) -> DefaultSafetyGuard:
    ids = iter(["safety-1", "safety-2", "safety-3", "safety-4"])
    return DefaultSafetyGuard(
        rules,
        clock=lambda: FIXED_TIME,
        result_id_factory=lambda: next(ids),
    )


def test_no_rule_match_is_explicit_without_inventing_domain_risk() -> None:
    result = asyncio.run(_guard().evaluate_early(build_runtime_input(text="hello")))

    assert result.phase is SafetyPhase.EARLY
    assert result.risk_detected is False
    assert result.risk_level is SafetyRiskLevel.NONE
    assert result.allowed_to_continue_normal_flow is True
    assert result.reason_codes == ["NO_SAFETY_RULE_MATCH"]
    assert result.matched_rules is None
    assert result.created_at == FIXED_TIME


def test_early_rule_maps_hard_constraints_to_canonical_safety_result() -> None:
    result = asyncio.run(
        _guard(EarlyHighRule("TEST_EARLY_RULE")).evaluate_early(
            build_runtime_input(text="TEST_RISK")
        )
    )

    assert result.risk_detected is True
    assert result.risk_level is SafetyRiskLevel.HIGH
    assert result.interrupt_current_task is True
    assert result.allowed_to_continue_normal_flow is False
    assert result.safety_lock_required is True
    assert result.reason_codes == ["TEST_EARLY_RISK"]
    assert result.risk_types == ["TEST_RISK_TYPE"]
    assert result.matched_rules == ["TEST_EARLY_RULE"]
    assert result.force_workflow == "TEST_SAFETY_WORKFLOW"
    assert result.requires_immediate_action is True
    assert result.restricted_actions == ["TEST_BLOCKED_ACTION"]
    assert result.evidence == {"TEST_EARLY_RULE": {"source": "TEST_RULE"}}
    assert result.confidence == 0.9


def test_deep_safety_can_escalate_but_cannot_downgrade_early_constraints() -> None:
    guard = _guard(
        EarlyHighRule("TEST_EARLY_RULE"),
        DeepCriticalRule("TEST_DEEP_RULE"),
    )
    runtime_input = build_runtime_input(text="TEST_RISK")
    early = asyncio.run(guard.evaluate_early(runtime_input))
    understanding = build_understanding_state().model_copy(
        update={"risk": {"test_flag": True}}
    )

    deep = asyncio.run(
        guard.evaluate_deep(
            runtime_input,
            build_runtime_context(),
            understanding,
            early,
        )
    )

    assert deep.phase is SafetyPhase.DEEP
    assert deep.risk_level is SafetyRiskLevel.CRITICAL
    assert deep.reason_codes == ["TEST_EARLY_RISK", "TEST_DEEP_RISK"]
    assert deep.matched_rules == ["TEST_EARLY_RULE", "TEST_DEEP_RULE"]
    assert deep.allowed_to_continue_normal_flow is False
    assert deep.interrupt_current_task is True
    assert deep.safety_lock_required is True
    assert deep.force_workflow == "TEST_SAFETY_WORKFLOW"
    assert deep.confidence == 0.95


def test_deep_no_match_still_preserves_early_high_risk() -> None:
    guard = _guard(EarlyHighRule("TEST_EARLY_RULE"))
    runtime_input = build_runtime_input(text="TEST_RISK")
    early = asyncio.run(guard.evaluate_early(runtime_input))

    deep = asyncio.run(
        guard.evaluate_deep(
            runtime_input,
            build_runtime_context(),
            build_understanding_state(),
            early,
        )
    )

    assert deep.risk_level is SafetyRiskLevel.HIGH
    assert deep.reason_codes == ["TEST_EARLY_RISK"]
    assert deep.allowed_to_continue_normal_flow is False
    assert deep.force_workflow == "TEST_SAFETY_WORKFLOW"


def test_multiple_early_rules_use_strictest_constraint_aggregation() -> None:
    result = asyncio.run(
        _guard(
            EarlyLowAllowRule("TEST_LOW_RULE"),
            EarlyHighDenyRule("TEST_HIGH_RULE"),
        ).evaluate_early(build_runtime_input(text="hello"))
    )

    assert result.risk_level is SafetyRiskLevel.HIGH
    assert result.allowed_to_continue_normal_flow is False
    assert result.interrupt_current_task is True
    assert result.reason_codes == ["TEST_LOW", "TEST_HIGH"]
    assert result.restricted_actions == ["TEST_LOW_RESTRICTED", "TEST_HIGH_RESTRICTED"]
    assert result.matched_rules == ["TEST_LOW_RULE", "TEST_HIGH_RULE"]


def test_conflicting_forced_workflows_fail_instead_of_arbitrarily_picking_one() -> None:
    guard = _guard(
        ConflictingWorkflowRule("TEST_RULE_A", "TEST_WORKFLOW_A"),
        ConflictingWorkflowRule("TEST_RULE_B", "TEST_WORKFLOW_B"),
    )

    with pytest.raises(SafetyRuleConflictError, match="different forced workflows"):
        asyncio.run(guard.evaluate_early(build_runtime_input()))


def test_duplicate_rule_id_is_rejected_at_construction() -> None:
    with pytest.raises(DuplicateSafetyRuleError, match="TEST_RULE"):
        _guard(BaseTestRule("TEST_RULE"), BaseTestRule("TEST_RULE"))


def test_rule_failure_is_not_converted_to_safe_result() -> None:
    guard = _guard(ExplodingRule("TEST_EXPLODING_RULE"))

    with pytest.raises(SafetyRuleExecutionError) as exc_info:
        asyncio.run(guard.evaluate_early(build_runtime_input()))

    error = exc_info.value
    assert error.rule_id == "TEST_EXPLODING_RULE"
    assert error.phase is SafetyPhase.EARLY
    assert isinstance(error.cause, ValueError)
    assert "private payload" not in str(error)


def test_finding_rule_id_mismatch_fails_fast() -> None:
    with pytest.raises(InvalidSafetyFindingError, match="mismatch"):
        asyncio.run(
            _guard(WrongRuleIdFindingRule("TEST_RULE")).evaluate_early(
                build_runtime_input()
            )
        )


def test_deep_requires_early_baseline_and_matching_request_ids() -> None:
    guard = _guard()
    runtime_input = build_runtime_input()

    with pytest.raises(SafetyGuardInvariantError, match="phase=EARLY"):
        asyncio.run(
            guard.evaluate_deep(
                runtime_input,
                build_runtime_context(),
                build_understanding_state(),
                build_safety_result(SafetyPhase.DEEP),
            )
        )

    wrong_early = build_safety_result(SafetyPhase.EARLY).model_copy(
        update={"request_id": "other-request"}
    )
    with pytest.raises(SafetyGuardInvariantError, match="Early Safety request_id"):
        asyncio.run(
            guard.evaluate_deep(
                runtime_input,
                build_runtime_context(),
                build_understanding_state(),
                wrong_early,
            )
        )


def test_deep_requires_understanding_for_same_request() -> None:
    guard = _guard()
    runtime_input = build_runtime_input()
    understanding = build_understanding_state().model_copy(
        update={
            "metadata": build_understanding_state().metadata.model_copy(
                update={"request_id": "other-request"}
            )
        }
    )

    with pytest.raises(
        SafetyGuardInvariantError, match="UnderstandingState request_id"
    ):
        asyncio.run(
            guard.evaluate_deep(
                runtime_input,
                build_runtime_context(),
                understanding,
                build_safety_result(SafetyPhase.EARLY),
            )
        )


def test_real_safety_guard_can_replace_m0_safety_stub_in_full_runtime() -> None:
    recorder = CallRecorder()

    class CapturingUnderstandingEngine(StubUnderstandingEngine):
        def __init__(self, call_recorder: CallRecorder) -> None:
            super().__init__(call_recorder)
            self.seen_context: RuntimeContext | None = None

        async def understand(
            self,
            runtime_input: RuntimeInput,
            runtime_context: RuntimeContext,
        ) -> UnderstandingState:
            self.seen_context = runtime_context
            return await super().understand(runtime_input, runtime_context)

    understanding = CapturingUnderstandingEngine(recorder)
    safety_guard = _guard(EarlyHighRule("TEST_EARLY_RULE"))
    orchestrator = RuntimeOrchestrator(
        input_processor=DefaultInputProcessor(),
        safety_guard=safety_guard,
        context_builder=DefaultContextBuilder(
            runtime_state_provider=GateRuntimeStateProvider()
        ),
        understanding_engine=understanding,
        policy_engine=StubPolicyEngine(recorder),
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

    outcome = asyncio.run(orchestrator.run(build_runtime_input(text="  TEST_RISK  ")))

    assert outcome.runtime_response is not None
    assert outcome.update_result is not None
    assert understanding.seen_context is not None
    assert understanding.seen_context.safety_context is not None
    assert understanding.seen_context.safety_context.current_risk_state == "HIGH"
    assert understanding.seen_context.safety_context.safety_lock is True
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


def test_rule_exception_is_wrapped_by_runtime_stage_error() -> None:
    recorder = CallRecorder()
    orchestrator = RuntimeOrchestrator(
        input_processor=DefaultInputProcessor(),
        safety_guard=_guard(ExplodingRule("TEST_EXPLODING_RULE")),
        context_builder=DefaultContextBuilder(
            runtime_state_provider=GateRuntimeStateProvider()
        ),
        understanding_engine=StubUnderstandingEngine(recorder),
        policy_engine=StubPolicyEngine(recorder),
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

    with pytest.raises(StageExecutionError) as exc_info:
        asyncio.run(orchestrator.run(build_runtime_input(text="hello")))

    assert exc_info.value.stage_name == "SAFETY_EARLY"
    assert isinstance(exc_info.value.cause, SafetyRuleExecutionError)
    assert recorder.entries == []
