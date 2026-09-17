"""M2-IU2 Runtime State / Transition Engine 测试。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from runtime.context_building import DefaultContextBuilder
from runtime.contracts import (
    RuntimeControlState,
    RuntimeInput,
)
from runtime.input_processing import DefaultInputProcessor
from runtime.orchestration import RuntimeOrchestrator
from runtime.safety import DefaultSafetyGuard
from runtime.state_management import (
    EngineRuntimeStateProvider,
    InMemoryRuntimeStateStore,
    InvalidStateTransitionError,
    RuntimeStateDefinition,
    RuntimeStateEngine,
    StateRevisionConflictError,
    StateStoreUnavailableError,
    core_runtime_state_definitions,
)
from tests.orchestration_stubs import (
    CallRecorder,
    StubExecutionEngine,
    StubPlanValidator,
    StubPlanner,
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


def _engine() -> RuntimeStateEngine:
    return RuntimeStateEngine(store=InMemoryRuntimeStateStore())


def test_default_definitions_cover_every_core_runtime_state() -> None:
    definitions = core_runtime_state_definitions()
    assert {definition.state for definition in definitions} == set(RuntimeControlState)
    assert len(definitions) == len(RuntimeControlState)


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
    with pytest.raises(StateStoreUnavailableError, match="not initialized"):
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


def test_ended_is_terminal_in_default_core_graph() -> None:
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


def test_custom_definition_can_narrow_core_transition_graph() -> None:
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

    orchestrator = RuntimeOrchestrator(
        input_processor=DefaultInputProcessor(),
        safety_guard=DefaultSafetyGuard(rules=[]),
        context_builder=context_builder,
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
