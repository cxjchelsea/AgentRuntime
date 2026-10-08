"""M3-IU6 integration gates: real M3 Understanding -> existing M2 deep safety/policy.

IU6 intentionally adds no second production integration path. The frozen
M2RuntimeOrchestrator already owns SAFETY_DEEP and POLICY after UNDERSTANDING.
These tests prove the real M3 engine plugs into that authority boundary.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from runtime.constraint_management import RuntimeConstraintEvaluator
from runtime.context_building import DefaultContextBuilder
from runtime.contracts import (
    ActionPlanDraft,
    PolicyDecision,
    RuntimeContext,
    RuntimeControlState,
    RuntimeInput,
    SafetyResult,
    SafetyRiskLevel,
    UnderstandingState,
)
from runtime.input_processing import DefaultInputProcessor
from runtime.interfaces.planning import Planner
from runtime.orchestration import (
    AlternatePathRequiredError,
    M2RuntimeOrchestrator,
    PrioritySubjectResolver,
    ResolvedPrioritySubjects,
    RuntimeControlBlockedError,
)
from runtime.policy_enforcement import DefaultPolicyRechecker
from runtime.policy_management import DefaultPolicyEngine, PolicyFragment, PolicyRule
from runtime.priority_management import PreemptionEngine, PrioritySubject
from runtime.safety import DefaultSafetyGuard, SafetyFinding, SafetyRule
from runtime.state_management import (
    EngineRuntimeStateProvider,
    InMemoryRuntimeStateStore,
    RuntimeStateDefinition,
    RuntimeStateEngine,
)
from runtime.understanding import (
    ConfiguredTextRule,
    DeepUnderstandingRequest,
    DeepUnderstandingRequestBuilder,
    DefaultModelContextSelector,
    DeterministicRuleDefinition,
    DeterministicRuleParser,
    ModelUnderstandingOutputValidator,
    RuntimeUnderstandingEngine,
    UnderstandingPathRouter,
    UnderstandingPostprocessor,
    UnderstandingRoutingPolicy,
    UnderstandingStateAssembler,
)
from tests.orchestration_stubs import (
    CallRecorder,
    StubExecutionEngine,
    StubPlanValidator,
    StubResponseGenerator,
    StubResponsePlanner,
    StubResponseValidator,
    StubResultValidator,
    StubStateMemoryUpdater,
    build_action_plan_draft,
    build_runtime_input,
)


class RequestAwarePlanner(Planner):
    """Minimal planner used only to prove whether M2 allowed M4 to run."""

    def __init__(self, recorder: CallRecorder) -> None:
        self._recorder = recorder

    async def plan(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        policy_decision: PolicyDecision,
    ) -> ActionPlanDraft:
        del runtime_context, policy_decision
        self._recorder.record("PLAN")
        return build_action_plan_draft().model_copy(
            update={"request_id": understanding_state.metadata.request_id}
        )


class StaticPrioritySubjectResolver(PrioritySubjectResolver):
    """Domain-injected priority mapping; Core still invents no business priority."""

    async def resolve(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        safety_result: SafetyResult,
    ) -> ResolvedPrioritySubjects:
        del runtime_input, runtime_context, understanding_state, safety_result
        return ResolvedPrioritySubjects(
            current=None,
            incoming=PrioritySubject(
                subject_id="incoming-m3-iu6",
                kind="TEST_INCOMING",
                priority=50,
                source="TEST",
            ),
        )


class RecordingRiskModel:
    """Synthetic model that emits only Understanding-layer risk evidence."""

    def __init__(self) -> None:
        self.requests: list[DeepUnderstandingRequest] = []

    async def infer(self, request: DeepUnderstandingRequest) -> dict[str, Any]:
        self.requests.append(request)
        return {
            "intents": [
                {
                    "intent_id": "DOMAIN_RISK_RELATED_INTENT",
                    "confidence": 0.8,
                    "evidence_ids": ["model-risk-e1"],
                }
            ],
            "risk_signals": [
                {
                    "signal_id": "DOMAIN_RISK_SIGNAL",
                    "confidence": 0.9,
                    "evidence_ids": ["model-risk-e1"],
                }
            ],
            "evidence": [
                {
                    "evidence_id": "model-risk-e1",
                    "text_or_value": "risk-bearing input",
                    "supports_field": "risk",
                    "strength": 0.9,
                }
            ],
        }


class M3RiskDeepSafetyRule(SafetyRule):
    """Domain Safety rule that interprets an M3 signal and owns the Safety decision."""

    def __init__(self) -> None:
        self.received_understanding: UnderstandingState | None = None

    @property
    def rule_id(self) -> str:
        return "TEST_M3_RISK_DEEP_SAFETY"

    async def evaluate_deep(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        early_safety: SafetyResult,
    ) -> SafetyFinding | None:
        del runtime_input, runtime_context, early_safety
        self.received_understanding = understanding_state
        risk = understanding_state.risk or {}
        signals = risk.get("signals")
        if not isinstance(signals, list) or "DOMAIN_RISK_SIGNAL" not in signals:
            return None
        return SafetyFinding(
            rule_id=self.rule_id,
            risk_level=SafetyRiskLevel.HIGH,
            reason_codes=("TEST_M3_SIGNAL_ESCALATED_BY_M2",),
            interrupt_current_task=True,
            allowed_to_continue_normal_flow=False,
            safety_lock_required=True,
            force_workflow="TEST_M2_SAFETY_WORKFLOW",
            requires_immediate_action=True,
        )


class M3IntentPolicyRule(PolicyRule):
    """Policy rule proves post-M3 Policy can use the Canonical UnderstandingState."""

    @property
    def rule_id(self) -> str:
        return "TEST_M3_INTENT_POLICY"

    async def evaluate(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        safety_result: SafetyResult,
    ) -> PolicyFragment | None:
        del runtime_context, safety_result
        if any(
            intent.intent_id == "DOMAIN_POLICY_BLOCK_INTENT"
            for intent in understanding_state.intents
        ):
            return PolicyFragment(
                source_id=self.rule_id,
                allowed=False,
                blocked=True,
                reason_codes=("TEST_BLOCK_FROM_M3_INTENT",),
            )
        return None


async def _build_state_engine(raw_input: RuntimeInput) -> RuntimeStateEngine:
    engine = RuntimeStateEngine(
        store=InMemoryRuntimeStateStore(),
        definitions=[
            RuntimeStateDefinition(
                state=RuntimeControlState.PROCESSING,
                interruptible=True,
                allowed_transitions=(RuntimeControlState.PROCESSING,),
            )
        ],
    )
    await engine.initialize(
        engine.scope_key(raw_input),
        initial_state=RuntimeControlState.PROCESSING,
        entered_at=raw_input.timestamp,
    )
    return engine


def _m3_engine(
    *,
    rules: tuple[ConfiguredTextRule, ...] = (),
    model: RecordingRiskModel | None = None,
) -> RuntimeUnderstandingEngine:
    return RuntimeUnderstandingEngine(
        rule_parser=DeterministicRuleParser(rules),
        path_router=UnderstandingPathRouter(UnderstandingRoutingPolicy()),
        request_builder=DeepUnderstandingRequestBuilder(DefaultModelContextSelector()),
        output_validator=ModelUnderstandingOutputValidator(),
        postprocessor=UnderstandingPostprocessor(),
        assembler=UnderstandingStateAssembler(),
        model=model,
    )


async def _build_orchestrator(
    raw_input: RuntimeInput,
    *,
    recorder: CallRecorder,
    understanding_engine: RuntimeUnderstandingEngine,
    safety_guard: DefaultSafetyGuard | None = None,
    policy_engine: DefaultPolicyEngine | None = None,
) -> M2RuntimeOrchestrator:
    state_engine = await _build_state_engine(raw_input)
    policy = policy_engine or DefaultPolicyEngine(rules=[])
    return M2RuntimeOrchestrator(
        runtime_constraint_evaluator=RuntimeConstraintEvaluator(
            policy_engine=policy,
            preemption_engine=PreemptionEngine(rules=[]),
        ),
        priority_subject_resolver=StaticPrioritySubjectResolver(),
        input_processor=DefaultInputProcessor(),
        safety_guard=safety_guard or DefaultSafetyGuard(rules=[]),
        context_builder=DefaultContextBuilder(
            runtime_state_provider=EngineRuntimeStateProvider(state_engine)
        ),
        understanding_engine=understanding_engine,
        policy_engine=policy,
        planner=RequestAwarePlanner(recorder),
        plan_validator=StubPlanValidator(recorder),
        policy_rechecker=DefaultPolicyRechecker(),
        execution_engine=StubExecutionEngine(recorder),
        result_validator=StubResultValidator(recorder),
        response_planner=StubResponsePlanner(recorder),
        response_generator=StubResponseGenerator(recorder),
        response_validator=StubResponseValidator(recorder),
        state_memory_updater=StubStateMemoryUpdater(recorder),
    )


def test_real_m3_output_flows_through_deep_safety_then_policy_before_plan() -> None:
    async def scenario() -> None:
        recorder = CallRecorder()
        raw_input = build_runtime_input(
            request_id="request-m3-iu6-normal",
            trace_id="trace-m3-iu6-normal",
            session_id="session-m3-iu6-normal",
            text="NORMAL",
        )
        fast_rule = ConfiguredTextRule(
            DeterministicRuleDefinition(
                rule_id="normal-fast-rule",
                version="1.0.0",
                patterns=("NORMAL",),
                intent_id="DOMAIN_NORMAL_INTENT",
                confidence=1.0,
            )
        )
        orchestrator = await _build_orchestrator(
            raw_input,
            recorder=recorder,
            understanding_engine=_m3_engine(rules=(fast_rule,)),
        )

        outcome = await orchestrator.run(raw_input)

        stages = [event.stage_name for event in outcome.trace.stage_events]
        assert stages.index("UNDERSTANDING") < stages.index("SAFETY_DEEP")
        assert stages.index("SAFETY_DEEP") < stages.index("POLICY")
        assert stages.index("POLICY") < stages.index("PLAN")
        assert "PLAN" in recorder.entries

    asyncio.run(scenario())


def test_m3_risk_signal_alone_does_not_self_authorize_a_safety_block() -> None:
    async def scenario() -> None:
        recorder = CallRecorder()
        model = RecordingRiskModel()
        raw_input = build_runtime_input(
            request_id="request-m3-risk-no-safety-rule",
            trace_id="trace-m3-risk-no-safety-rule",
            session_id="session-m3-risk-no-safety-rule",
            text="risk-bearing input",
        )
        orchestrator = await _build_orchestrator(
            raw_input,
            recorder=recorder,
            understanding_engine=_m3_engine(model=model),
            safety_guard=DefaultSafetyGuard(rules=[]),
        )

        outcome = await orchestrator.run(raw_input)

        assert len(model.requests) == 1
        assert "PLAN" in recorder.entries
        deep_event = next(
            event
            for event in outcome.trace.stage_events
            if event.stage_name == "SAFETY_DEEP"
        )
        assert deep_event.status is not None
        assert deep_event.status.value == "SUCCESS"

    asyncio.run(scenario())


def test_m2_deep_safety_can_escalate_m3_risk_and_preempt_ordinary_planning() -> None:
    async def scenario() -> None:
        recorder = CallRecorder()
        model = RecordingRiskModel()
        deep_rule = M3RiskDeepSafetyRule()
        raw_input = build_runtime_input(
            request_id="request-m3-risk-escalated",
            trace_id="trace-m3-risk-escalated",
            session_id="session-m3-risk-escalated",
            text="risk-bearing input",
        )
        orchestrator = await _build_orchestrator(
            raw_input,
            recorder=recorder,
            understanding_engine=_m3_engine(model=model),
            safety_guard=DefaultSafetyGuard(rules=[deep_rule]),
        )

        with pytest.raises(AlternatePathRequiredError) as captured:
            await orchestrator.run(raw_input)

        assert captured.value.forced_workflow == "TEST_M2_SAFETY_WORKFLOW"
        assert deep_rule.received_understanding is not None
        assert deep_rule.received_understanding.risk is not None
        assert "DOMAIN_RISK_SIGNAL" in deep_rule.received_understanding.risk["signals"]
        assert "PLAN" not in recorder.entries
        assert orchestrator.last_trace is not None
        assert [event.stage_name for event in orchestrator.last_trace.stage_events][
            -3:
        ] == [
            "UNDERSTANDING",
            "SAFETY_DEEP",
            "POLICY",
        ]

    asyncio.run(scenario())


def test_m2_policy_can_block_using_real_m3_intent_after_deep_safety() -> None:
    async def scenario() -> None:
        recorder = CallRecorder()
        raw_input = build_runtime_input(
            request_id="request-m3-policy-block",
            trace_id="trace-m3-policy-block",
            session_id="session-m3-policy-block",
            text="BLOCK",
        )
        rule = ConfiguredTextRule(
            DeterministicRuleDefinition(
                rule_id="policy-block-intent-rule",
                version="1.0.0",
                patterns=("BLOCK",),
                intent_id="DOMAIN_POLICY_BLOCK_INTENT",
                confidence=1.0,
            )
        )
        policy = DefaultPolicyEngine(rules=[M3IntentPolicyRule()])
        orchestrator = await _build_orchestrator(
            raw_input,
            recorder=recorder,
            understanding_engine=_m3_engine(rules=(rule,)),
            policy_engine=policy,
        )

        with pytest.raises(RuntimeControlBlockedError) as captured:
            await orchestrator.run(raw_input)

        assert captured.value.reason_code == "POLICY_BLOCKED"
        assert "PLAN" not in recorder.entries
        assert orchestrator.last_trace is not None
        stages = [event.stage_name for event in orchestrator.last_trace.stage_events]
        assert stages[-2:] == ["SAFETY_DEEP", "POLICY"]

    asyncio.run(scenario())
