"""M2-IU2 Runtime State / Transition Engine 测试。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from runtime.context_building import DefaultContextBuilder
from runtime.contracts import RuntimeContext, RuntimeControlState, UnderstandingState
from runtime.input_processing import DefaultInputProcessor
from runtime.orchestration import RuntimeOrchestrator
from runtime.safety import DefaultSafetyGuard
from runtime.state_management import (
    EngineRuntimeStateProvider,
    InMemoryRuntimeStateStore,
    InvalidStateTransitionError,
    MissingStateDefinitionError,
    RuntimeStateDefinition,
    RuntimeStateEngine,
    StateNotInitializedError,
    StateRevisionConflictError,
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
    build_runtime_input,
)


def _now() -> datetime:
    return datetime(2026, 9, 17, 12, 30, tzinfo=UTC)


def _definitions() -> tuple[RuntimeStateDefinition, ...]:
    """测试专用 Core 状态图；不声明为平台默认业务流程。"""
    return (
        RuntimeStateDefinition(
            state=RuntimeControlState.STARTING,
            interruptible=False,
            allowed_transitions=(RuntimeControlState.IDLE,),
        ),
        RuntimeStateDefinition(
            state=RuntimeControlState.IDLE,
            interruptible=True,
            allowed_transitions=(
                RuntimeControlState.PROCESSING,
                RuntimeControlState.ENDED,
            ),
        ),
        RuntimeStateDefinition(
            state=RuntimeControlState.PROCESSING,
            interruptible=True,
            allowed_transitions=(RuntimeControlState.RESPONDING,),
        ),
        RuntimeStateDefinition(
            state=RuntimeControlState.RESPONDING,
            interruptible=True,
            allowed_transitions=(RuntimeControlState.IDLE,),
        ),
        RuntimeStateDefinition(
            state=RuntimeControlState.WAITING_USER,
            interruptible=True,
            allowed_transitions=(),
        ),
        RuntimeStateDefinition(
            state=RuntimeControlState.ENDED,
            interruptible=False,
            allowed_transitions=(),
        ),
    )


def _engine() -> RuntimeStateEngine:
    return RuntimeStateEngine(
        store=InMemoryRuntimeStateStore(),
        definitions=_definitions(),
    )


def test_engine_requires_explicit_state_definitions() -> None:
    with pytest.raises(MissingStateDefinitionError, match="at least one"):
        RuntimeStateEngine(store=InMemoryRuntimeStateStore(), definitions=())


def test_definition_graph_cannot_reference_undefined_core_state() -> None:
    definitions = (
        RuntimeStateDefinition(
            state=RuntimeControlState.IDLE,
            interruptible=True,
            allowed_transitions=(RuntimeControlState.PROCESSING,),
        ),
    )
    with pytest.raises(MissingStateDefinitionError, match="PROCESSING"):
        RuntimeStateEngine(
            store=InMemoryRuntimeStateStore(),
            definitions=definitions,
        )


def test_initialize_requires_explicit_state_and_preserves_snapshot() -> None:
    engine = _engine()
    key = ("scope-1", "session-1")

    first = asyncio.run(
        engine.initialize(
            key,
            initial_state=RuntimeControlState.STARTING,
            entered_at=_now(),
        )
    )
    second = asyncio.run(
        engine.initialize(
            key,
            initial_state=RuntimeControlState.IDLE,
            entered_at=_now() + timedelta(seconds=1),
        )
    )

    assert first == second
    assert first.current_state is RuntimeControlState.STARTING
    assert first.revision == 0
    assert first.interruptible is False


def test_missing_scope_is_not_fabricated() -> None:
    with pytest.raises(StateNotInitializedError, match="not initialized"):
        asyncio.run(_engine().load(("scope-missing", "session-missing")))


def test_valid_transition_commits_previous_state_and_revision() -> None:
    engine = _engine()
    key = ("scope-1", "session-1")
    asyncio.run(
        engine.initialize(
            key,
            initial_state=RuntimeControlState.STARTING,
            entered_at=_now(),
        )
    )

    committed = asyncio.run(
        engine.transition(
            key,
            target_state=RuntimeControlState.IDLE,
            entered_at=_now() + timedelta(seconds=1),
        )
    )

    assert committed.current_state is RuntimeControlState.IDLE
    assert committed.previous_state is RuntimeControlState.STARTING
    assert committed.revision == 1
    assert committed.interruptible is True


def test_invalid_transition_fails_without_modifying_state() -> None:
    engine = _engine()
    key = ("scope-1", "session-1")
    asyncio.run(
        engine.initialize(
            key,
            initial_state=RuntimeControlState.STARTING,
            entered_at=_now(),
        )
    )

    with pytest.raises(InvalidStateTransitionError, match="not allowed"):
        asyncio.run(
            engine.transition(
                key,
                target_state=RuntimeControlState.RESPONDING,
                entered_at=_now() + timedelta(seconds=1),
            )
        )

    snapshot = asyncio.run(engine.load(key))
    assert snapshot.current_state is RuntimeControlState.STARTING
    assert snapshot.revision == 0


def test_same_state_transition_is_noop_without_revision_change() -> None:
    engine = _engine()
    key = ("scope-1", "session-1")
    snapshot = asyncio.run(
        engine.initialize(
            key,
            initial_state=RuntimeControlState.IDLE,
            entered_at=_now(),
        )
    )

    decision = engine.evaluate_transition(snapshot, RuntimeControlState.IDLE)
    committed = asyncio.run(
        engine.transition(
            key,
            target_state=RuntimeControlState.IDLE,
            entered_at=_now() + timedelta(seconds=1),
        )
    )

    assert decision.allowed is True
    assert decision.no_op is True
    assert decision.reason_codes == ("STATE_UNCHANGED",)
    assert committed == snapshot


def test_terminal_state_behavior_comes_from_injected_definition() -> None:
    engine = _engine()
    key = ("scope-1", "session-1")
    snapshot = asyncio.run(
        engine.initialize(
            key,
            initial_state=RuntimeControlState.ENDED,
            entered_at=_now(),
        )
    )

    decision = engine.evaluate_transition(snapshot, RuntimeControlState.IDLE)
    assert decision.allowed is False
    assert decision.reason_codes == ("TRANSITION_NOT_ALLOWED",)


def test_expected_revision_rejects_stale_caller() -> None:
    engine = _engine()
    key = ("scope-1", "session-1")
    asyncio.run(
        engine.initialize(
            key,
            initial_state=RuntimeControlState.IDLE,
            entered_at=_now(),
        )
    )
    asyncio.run(
        engine.transition(
            key,
            target_state=RuntimeControlState.PROCESSING,
            entered_at=_now() + timedelta(seconds=1),
            expected_revision=0,
        )
    )

    with pytest.raises(StateRevisionConflictError):
        asyncio.run(
            engine.transition(
                key,
                target_state=RuntimeControlState.RESPONDING,
                entered_at=_now() + timedelta(seconds=2),
                expected_revision=0,
            )
        )


def test_state_scope_is_isolated_by_identity_and_session() -> None:
    engine = _engine()
    key_a = ("scope-a", "session-a")
    key_b = ("scope-a", "session-b")
    asyncio.run(
        engine.initialize(
            key_a,
            initial_state=RuntimeControlState.IDLE,
            entered_at=_now(),
        )
    )
    asyncio.run(
        engine.initialize(
            key_b,
            initial_state=RuntimeControlState.WAITING_USER,
            entered_at=_now(),
        )
    )

    assert asyncio.run(engine.load(key_a)).current_state is RuntimeControlState.IDLE
    assert (
        asyncio.run(engine.load(key_b)).current_state
        is RuntimeControlState.WAITING_USER
    )


def test_definition_can_narrow_allowed_core_transitions() -> None:
    engine = RuntimeStateEngine(
        store=InMemoryRuntimeStateStore(),
        definitions=[
            RuntimeStateDefinition(
                state=RuntimeControlState.IDLE,
                interruptible=True,
                allowed_transitions=(),
            )
        ],
    )
    key = ("scope-1", "session-1")
    snapshot = asyncio.run(
        engine.initialize(
            key,
            initial_state=RuntimeControlState.IDLE,
            entered_at=_now(),
        )
    )

    assert engine.evaluate_transition(snapshot, RuntimeControlState.IDLE).no_op is True


def test_engine_provider_projects_real_snapshot_to_runtime_context() -> None:
    engine = _engine()
    runtime_input = build_runtime_input(
        request_id="request-state",
        trace_id="trace-state",
        session_id="session-state",
        text="hello",
    ).model_copy(update={"identity_scope": "scope-state"})
    key = engine.scope_key(runtime_input)
    asyncio.run(
        engine.initialize(
            key,
            initial_state=RuntimeControlState.PROCESSING,
            entered_at=_now(),
        )
    )

    provider = EngineRuntimeStateProvider(engine)
    context = asyncio.run(provider.load(runtime_input))

    assert context.current_state is RuntimeControlState.PROCESSING
    assert context.previous_state is None
    assert context.interruptible is True
    assert context.entered_at == _now()


def test_uninitialized_engine_provider_remains_missing_context_not_default_state() -> None:
    builder = DefaultContextBuilder(
        runtime_state_provider=EngineRuntimeStateProvider(_engine())
    )
    runtime_input = build_runtime_input(text="hello")
    safety = asyncio.run(DefaultSafetyGuard().evaluate_early(runtime_input))

    from runtime.context_building import CriticalContextUnavailableError

    with pytest.raises(CriticalContextUnavailableError):
        asyncio.run(builder.build(runtime_input, safety))


def test_real_state_provider_integrates_with_m1_context_and_runtime_chain() -> None:
    recorder = CallRecorder()
    engine = _engine()
    raw_input = build_runtime_input(
        request_id="request-state-e2e",
        trace_id="trace-state-e2e",
        session_id="session-state-e2e",
        text="  hello   state  ",
    ).model_copy(update={"identity_scope": "scope-state-e2e"})
    processed_input = asyncio.run(DefaultInputProcessor().process(raw_input))
    asyncio.run(
        engine.initialize(
            engine.scope_key(processed_input),
            initial_state=RuntimeControlState.PROCESSING,
            entered_at=processed_input.timestamp,
        )
    )
    context_builder = DefaultContextBuilder(
        runtime_state_provider=EngineRuntimeStateProvider(engine)
    )

    class CapturingUnderstandingEngine(StubUnderstandingEngine):
        def __init__(self, call_recorder: CallRecorder) -> None:
            super().__init__(call_recorder)
            self.seen_context: RuntimeContext | None = None

        async def understand(
            self,
            runtime_input,
            runtime_context: RuntimeContext,
        ) -> UnderstandingState:
            self.seen_context = runtime_context
            return await super().understand(runtime_input, runtime_context)

    understanding = CapturingUnderstandingEngine(recorder)
    orchestrator = RuntimeOrchestrator(
        input_processor=DefaultInputProcessor(),
        safety_guard=DefaultSafetyGuard(),
        context_builder=context_builder,
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

    outcome = asyncio.run(orchestrator.run(raw_input))

    assert understanding.seen_context is not None
    assert understanding.seen_context.runtime_state_context.current_state is (
        RuntimeControlState.PROCESSING
    )
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
