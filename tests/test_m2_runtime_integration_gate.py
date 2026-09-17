"""M2-IU7 Runtime Integration + E2E Gate tests."""

from __future__ import annotations

import asyncio

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
from runtime.interfaces.understanding import UnderstandingEngine
from runtime.orchestration import (
    AlternatePathRequiredError,
    M2RuntimeOrchestrator,
    OrchestrationInvariantError,
    PreemptionEffectRequiredError,
    PrioritySubjectResolver,
    ResolvedPrioritySubjects,
    RuntimeControlBlockedError,
)
from runtime.policy_enforcement import DefaultPolicyRechecker
from runtime.policy_management import DefaultPolicyEngine, PolicyFragment, PolicyRule
from runtime.priority_management import (
    IncomingDisposition,
    PreemptionEngine,
    PreemptionRule,
    PriorityRelation,
    PrioritySubject,
)
from runtime.safety import DefaultSafetyGuard, SafetyFinding, SafetyRule
from runtime.state_management import (
    EngineRuntimeStateProvider,
    InMemoryRuntimeStateStore,
    RuntimeStateDefinition,
    RuntimeStateEngine,
)
from tests.orchestration_stubs import (
    CallRecorder,
    StubExecutionEngine,
    StubPlanner,
    StubPlanValidator,
    StubResponseGenerator,
    StubResponsePlanner,
    StubResponseValidator,
    StubResultValidator,
    StubStateMemoryUpdater,
    build_action_plan_draft,
    build_runtime_input,
    build_understanding_state,
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


class RequestAwarePlanner(Planner):
    def __init__(self, recorder: CallRecorder) -> None:
        self._recorder = recorder
        self.last_output: ActionPlanDraft | None = None

    async def plan(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        policy_decision: PolicyDecision,
    ) -> ActionPlanDraft:
        del runtime_context, policy_decision
        self._recorder.record("PLAN")
        self.last_output = build_action_plan_draft().model_copy(
            update={"request_id": understanding_state.metadata.request_id}
        )
        return self.last_output


class StaticPrioritySubjectResolver(PrioritySubjectResolver):
    def __init__(
        self,
        *,
        current: PrioritySubject | None,
        incoming: PrioritySubject,
    ) -> None:
        self._current = current
        self._incoming = incoming

    async def resolve(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        safety_result: SafetyResult,
    ) -> ResolvedPrioritySubjects:
        del runtime_input, runtime_context, understanding_state, safety_result
        return ResolvedPrioritySubjects(current=self._current, incoming=self._incoming)


class HighSafetyRule(SafetyRule):
    @property
    def rule_id(self) -> str:
        return "TEST_HIGH_SAFETY"

    async def evaluate_early(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext | None,
    ) -> SafetyFinding | None:
        del runtime_input, runtime_context
        return SafetyFinding(
            rule_id=self.rule_id,
            risk_level=SafetyRiskLevel.HIGH,
            reason_codes=("TEST_HIGH_RISK",),
            interrupt_current_task=True,
            allowed_to_continue_normal_flow=False,
            safety_lock_required=True,
            force_workflow="TEST_SAFETY_WORKFLOW",
            requires_immediate_action=True,
        )


class DenyPolicyRule(PolicyRule):
    @property
    def rule_id(self) -> str:
        return "TEST_DENY_POLICY"

    async def evaluate(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        safety_result: SafetyResult,
    ) -> PolicyFragment | None:
        del runtime_context, understanding_state, safety_result
        return PolicyFragment(
            source_id=self.rule_id,
            allowed=False,
            blocked=True,
            reason_codes=("TEST_POLICY_BLOCK",),
        )


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


async def _build_orchestrator(
    raw_input: RuntimeInput,
    *,
    recorder: CallRecorder,
    resolver: PrioritySubjectResolver,
    preemption_engine: PreemptionEngine | None = None,
    safety_guard: DefaultSafetyGuard | None = None,
    policy_engine: DefaultPolicyEngine | None = None,
    planner: Planner | None = None,
) -> tuple[M2RuntimeOrchestrator, RuntimeStateEngine]:
    state_engine = await _build_state_engine(raw_input)
    policy = policy_engine or DefaultPolicyEngine(rules=[])
    constraint_evaluator = RuntimeConstraintEvaluator(
        policy_engine=policy,
        preemption_engine=preemption_engine or PreemptionEngine(rules=[]),
    )
    orchestrator = M2RuntimeOrchestrator(
        runtime_constraint_evaluator=constraint_evaluator,
        priority_subject_resolver=resolver,
        input_processor=DefaultInputProcessor(),
        safety_guard=safety_guard or DefaultSafetyGuard(rules=[]),
        context_builder=DefaultContextBuilder(
            runtime_state_provider=EngineRuntimeStateProvider(state_engine)
        ),
        understanding_engine=RequestAwareUnderstandingEngine(recorder),
        policy_engine=policy,
        planner=planner or RequestAwarePlanner(recorder),
        plan_validator=StubPlanValidator(recorder),
        policy_rechecker=DefaultPolicyRechecker(),
        execution_engine=StubExecutionEngine(recorder),
        result_validator=StubResultValidator(recorder),
        response_planner=StubResponsePlanner(recorder),
        response_generator=StubResponseGenerator(recorder),
        response_validator=StubResponseValidator(recorder),
        state_memory_updater=StubStateMemoryUpdater(recorder),
    )
    return orchestrator, state_engine


def _incoming(priority: int = 50, kind: str = "TEST_INCOMING") -> PrioritySubject:
    return PrioritySubject(
        subject_id="incoming-001",
        kind=kind,
        priority=priority,
        source="TEST",
    )


def _current(priority: int = 10, kind: str = "TEST_CURRENT") -> PrioritySubject:
    return PrioritySubject(
        subject_id="current-001",
        kind=kind,
        priority=priority,
        source="TEST",
    )


def test_full_real_m2_control_path_preserves_frozen_15_call_points() -> None:
    async def scenario() -> None:
        recorder = CallRecorder()
        raw_input = build_runtime_input(
            request_id="request-m2-iu7-e2e",
            trace_id="trace-m2-iu7-e2e",
            session_id="session-m2-iu7-e2e",
            text="hello integrated runtime",
        )
        orchestrator, _ = await _build_orchestrator(
            raw_input,
            recorder=recorder,
            resolver=StaticPrioritySubjectResolver(
                current=None,
                incoming=_incoming(),
            ),
        )

        outcome = await orchestrator.run(raw_input)

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

    asyncio.run(scenario())


def test_high_safety_forced_workflow_stops_ordinary_planner_at_policy() -> None:
    async def scenario() -> None:
        recorder = CallRecorder()
        raw_input = build_runtime_input(
            request_id="request-high-safety",
            trace_id="trace-high-safety",
            session_id="session-high-safety",
            text="trigger high safety",
        )
        orchestrator, _ = await _build_orchestrator(
            raw_input,
            recorder=recorder,
            resolver=StaticPrioritySubjectResolver(
                current=None,
                incoming=_incoming(priority=100),
            ),
            safety_guard=DefaultSafetyGuard(rules=[HighSafetyRule()]),
        )

        with pytest.raises(AlternatePathRequiredError) as captured:
            await orchestrator.run(raw_input)

        assert captured.value.forced_workflow == "TEST_SAFETY_WORKFLOW"
        assert "PLAN" not in recorder.entries
        assert orchestrator.last_trace is not None
        last_policy_event = orchestrator.last_trace.stage_events[-1]
        assert last_policy_event.stage_name == "POLICY"
        assert last_policy_event.status is not None
        assert last_policy_event.status.value == "ERROR"

    asyncio.run(scenario())


def test_policy_blocked_wins_over_no_current_process_now_disposition() -> None:
    async def scenario() -> None:
        recorder = CallRecorder()
        raw_input = build_runtime_input(
            request_id="request-policy-block",
            trace_id="trace-policy-block",
            session_id="session-policy-block",
            text="policy block",
        )
        policy = DefaultPolicyEngine(rules=[DenyPolicyRule()])
        orchestrator, _ = await _build_orchestrator(
            raw_input,
            recorder=recorder,
            resolver=StaticPrioritySubjectResolver(
                current=None,
                incoming=_incoming(),
            ),
            policy_engine=policy,
        )

        with pytest.raises(RuntimeControlBlockedError) as captured:
            await orchestrator.run(raw_input)

        assert captured.value.reason_code == "POLICY_BLOCKED"
        assert captured.value.disposition is None
        assert "PLAN" not in recorder.entries

    asyncio.run(scenario())


def test_defer_disposition_stops_ordinary_planner_before_plan() -> None:
    async def scenario() -> None:
        recorder = CallRecorder()
        raw_input = build_runtime_input(
            request_id="request-defer",
            trace_id="trace-defer",
            session_id="session-defer",
            text="defer incoming",
        )
        preemption = PreemptionEngine(
            rules=[
                PreemptionRule(
                    current_kind="TEST_CURRENT",
                    incoming_kind="TEST_INCOMING",
                    relation=PriorityRelation.LOWER,
                    interrupt=False,
                    disposition=IncomingDisposition.DEFER,
                )
            ]
        )
        orchestrator, _ = await _build_orchestrator(
            raw_input,
            recorder=recorder,
            resolver=StaticPrioritySubjectResolver(
                current=_current(priority=100),
                incoming=_incoming(priority=10),
            ),
            preemption_engine=preemption,
        )

        with pytest.raises(RuntimeControlBlockedError) as captured:
            await orchestrator.run(raw_input)

        assert captured.value.disposition is IncomingDisposition.DEFER
        assert "PLAN" not in recorder.entries

    asyncio.run(scenario())


def test_required_preemption_does_not_execute_without_effect_handler() -> None:
    async def scenario() -> None:
        recorder = CallRecorder()
        raw_input = build_runtime_input(
            request_id="request-preempt",
            trace_id="trace-preempt",
            session_id="session-preempt",
            text="preempt current",
        )
        preemption = PreemptionEngine(
            rules=[
                PreemptionRule(
                    current_kind="TEST_CURRENT",
                    incoming_kind="TEST_INCOMING",
                    relation=PriorityRelation.HIGHER,
                    interrupt=True,
                    disposition=IncomingDisposition.PROCESS_NOW,
                    when_not_interruptible=IncomingDisposition.DEFER,
                )
            ]
        )
        orchestrator, state_engine = await _build_orchestrator(
            raw_input,
            recorder=recorder,
            resolver=StaticPrioritySubjectResolver(
                current=_current(priority=10),
                incoming=_incoming(priority=100),
            ),
            preemption_engine=preemption,
        )
        before = await state_engine.load(state_engine.scope_key(raw_input))

        with pytest.raises(PreemptionEffectRequiredError):
            await orchestrator.run(raw_input)

        after = await state_engine.load(state_engine.scope_key(raw_input))
        assert after == before
        assert "PLAN" not in recorder.entries

    asyncio.run(scenario())


def test_cross_turn_draft_request_id_is_rejected_at_plan_boundary() -> None:
    async def scenario() -> None:
        recorder = CallRecorder()
        raw_input = build_runtime_input(
            request_id="request-current-turn",
            trace_id="trace-current-turn",
            session_id="session-current-turn",
            text="request continuity",
        )
        orchestrator, _ = await _build_orchestrator(
            raw_input,
            recorder=recorder,
            resolver=StaticPrioritySubjectResolver(
                current=None,
                incoming=_incoming(),
            ),
            planner=StubPlanner(recorder),
        )

        with pytest.raises(OrchestrationInvariantError) as captured:
            await orchestrator.run(raw_input)

        assert captured.value.stage_name == "PLAN"
        assert "PLAN_VALIDATE" not in recorder.entries
        assert orchestrator.last_trace is not None
        last_plan_event = orchestrator.last_trace.stage_events[-1]
        assert last_plan_event.stage_name == "PLAN"
        assert last_plan_event.status is not None
        assert last_plan_event.status.value == "ERROR"

    asyncio.run(scenario())
