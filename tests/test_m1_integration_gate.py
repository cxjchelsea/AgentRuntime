"""M1-IU3：M1 Input + Context 集成与 E2E Gate。

本文件不新增 Runtime 能力，只验证已经通过的 M1-IU1 与 M1-IU2 在同一条
M0 Runtime 主链中可以稳定组合，并保持 M1 的职责边界。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from runtime.context_building import (
    ContextKind,
    ContextProvider,
    ContextProviderUnavailable,
    CoreContextSelector,
    CriticalContextUnavailableError,
    DefaultContextBuilder,
    RuntimeStateProvider,
)
from runtime.context_building.providers import ContextValue
from runtime.contracts import (
    InputSource,
    InputTriggerType,
    RuntimeContext,
    RuntimeControlState,
    RuntimeInput,
    SafetyPhase,
    SafetyResult,
    SafetyRiskLevel,
    UnderstandingState,
)
from runtime.contracts.context import MemoryContext, RuntimeStateContext
from runtime.input_processing import DefaultInputProcessor
from runtime.orchestration import RuntimeOrchestrator, StageExecutionError
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
    StubSafetyGuard,
    StubStateMemoryUpdater,
    StubUnderstandingEngine,
)

EXPECTED_CALL_ORDER = [
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


def _input(**overrides: object) -> RuntimeInput:
    values: dict[str, object] = {
        "request_id": "request-gate",
        "trace_id": "trace-gate",
        "session_id": "session-gate",
        "subject_id": "subject-gate",
        "identity_scope": "scope-gate",
        "source": InputSource.USER,
        "trigger_type": InputTriggerType.USER_TEXT,
        "timestamp": datetime(2026, 9, 17, 10, 30, tzinfo=UTC),
        "text": "hello",
    }
    values.update(overrides)
    return RuntimeInput.model_validate(values)


def _safety(runtime_input: RuntimeInput, phase: SafetyPhase) -> SafetyResult:
    return SafetyResult(
        safety_result_id=f"safety-{phase.value.lower()}",
        request_id=runtime_input.request_id,
        phase=phase,
        risk_detected=False,
        risk_level=SafetyRiskLevel.NONE,
        interrupt_current_task=False,
        allowed_to_continue_normal_flow=True,
        safety_lock_required=False,
        reason_codes=["SAFE"],
        created_at=runtime_input.timestamp,
    )


class GateRuntimeStateProvider(RuntimeStateProvider):
    """Gate 使用的显式 RuntimeState 快照来源。"""

    async def load(self, runtime_input: RuntimeInput) -> RuntimeStateContext:
        return RuntimeStateContext(
            current_state=RuntimeControlState.PROCESSING,
            previous_state=RuntimeControlState.LISTENING,
            interruptible=True,
            entered_at=runtime_input.timestamp,
        )


class UnavailableRuntimeStateProvider(RuntimeStateProvider):
    async def load(self, runtime_input: RuntimeInput) -> RuntimeStateContext:
        raise ContextProviderUnavailable("runtime state unavailable")


class RequestAwareSafetyGuard(StubSafetyGuard):
    """仅让 M0 Safety Stub 与真实 IU1 request_id 连续。"""

    async def evaluate_early(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext | None = None,
    ) -> SafetyResult:
        self._call_recorder.record("SAFETY_EARLY")
        return _safety(runtime_input, SafetyPhase.EARLY)

    async def evaluate_deep(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        early_safety: SafetyResult,
    ) -> SafetyResult:
        self._call_recorder.record("SAFETY_DEEP")
        return _safety(runtime_input, SafetyPhase.DEEP)


class CapturingUnderstandingEngine(StubUnderstandingEngine):
    """捕获 M3 实际收到的 M1 输出，不增加真实 Understanding。"""

    def __init__(self, call_recorder: CallRecorder) -> None:
        super().__init__(call_recorder)
        self.seen_input: RuntimeInput | None = None
        self.seen_context: RuntimeContext | None = None

    async def understand(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext,
    ) -> UnderstandingState:
        self.seen_input = runtime_input
        self.seen_context = runtime_context
        return await super().understand(runtime_input, runtime_context)


class MemoryProvider(ContextProvider):
    def __init__(
        self,
        value: MemoryContext | None,
        *,
        unavailable: bool = False,
    ) -> None:
        self._value = value
        self._unavailable = unavailable

    @property
    def kind(self) -> ContextKind:
        return ContextKind.MEMORY

    async def load(
        self,
        runtime_input: RuntimeInput,
        safety_result: SafetyResult,
    ) -> ContextValue | None:
        if self._unavailable:
            raise ContextProviderUnavailable("memory unavailable")
        return self._value


def _orchestrator(
    *,
    recorder: CallRecorder,
    context_builder: DefaultContextBuilder,
    understanding_engine: StubUnderstandingEngine | None = None,
) -> RuntimeOrchestrator:
    return RuntimeOrchestrator(
        input_processor=DefaultInputProcessor(),
        safety_guard=RequestAwareSafetyGuard(recorder),
        context_builder=context_builder,
        understanding_engine=understanding_engine or StubUnderstandingEngine(recorder),
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


def test_m1_real_chain_preserves_input_to_context_continuity() -> None:
    recorder = CallRecorder()
    understanding = CapturingUnderstandingEngine(recorder)
    orchestrator = _orchestrator(
        recorder=recorder,
        context_builder=DefaultContextBuilder(
            runtime_state_provider=GateRuntimeStateProvider()
        ),
        understanding_engine=understanding,
    )

    outcome = asyncio.run(
        orchestrator.run(
            _input(
                request_id=" request-gate ",
                trace_id=" trace-gate ",
                session_id=" session-gate ",
                subject_id=" subject-gate ",
                identity_scope=" scope-gate ",
                text="  Ｈｅｌｌｏ\u200b   M1   gate  ",
            )
        )
    )

    assert understanding.seen_input is not None
    assert understanding.seen_context is not None
    assert understanding.seen_input.request_id == "request-gate"
    assert understanding.seen_input.text == "Hello M1 gate"
    assert understanding.seen_input.raw_text == "  Ｈｅｌｌｏ\u200b   M1   gate  "
    assert understanding.seen_context.identity_context.subject_id == "subject-gate"
    assert understanding.seen_context.identity_context.identity_scope == "scope-gate"
    assert understanding.seen_context.session_context.session_id == "session-gate"
    assert understanding.seen_context.runtime_state_context.current_state is (
        RuntimeControlState.PROCESSING
    )
    assert understanding.seen_context.time_context is not None
    assert understanding.seen_context.time_context.current_datetime == (
        understanding.seen_input.timestamp
    )
    assert understanding.seen_context.safety_context is not None
    assert understanding.seen_context.safety_context.current_risk_state == "NONE"
    assert [event.stage_name for event in outcome.trace.stage_events] == EXPECTED_CALL_ORDER


def test_m1_default_context_does_not_infer_memory_or_domain_state() -> None:
    recorder = CallRecorder()
    understanding = CapturingUnderstandingEngine(recorder)
    orchestrator = _orchestrator(
        recorder=recorder,
        context_builder=DefaultContextBuilder(
            runtime_state_provider=GateRuntimeStateProvider()
        ),
        understanding_engine=understanding,
    )

    asyncio.run(
        orchestrator.run(
            _input(text="请记住这句话，并进入一个并不存在的领域状态")
        )
    )

    assert understanding.seen_context is not None
    assert understanding.seen_context.memory_context is None
    assert understanding.seen_context.domain_extensions is None


def test_m1_missing_unavailable_and_empty_memory_remain_distinct() -> None:
    processed = asyncio.run(DefaultInputProcessor().process(_input()))
    early_safety = _safety(processed, SafetyPhase.EARLY)
    selector = CoreContextSelector(
        {InputTriggerType.USER_TEXT: (ContextKind.MEMORY,)}
    )

    missing_builder = DefaultContextBuilder(
        runtime_state_provider=GateRuntimeStateProvider(),
        selector=selector,
    )
    unavailable_builder = DefaultContextBuilder(
        runtime_state_provider=GateRuntimeStateProvider(),
        providers=[MemoryProvider(None, unavailable=True)],
        selector=selector,
    )
    empty_builder = DefaultContextBuilder(
        runtime_state_provider=GateRuntimeStateProvider(),
        providers=[
            MemoryProvider(
                MemoryContext(retrieved_memories=[], service_status="AVAILABLE")
            )
        ],
        selector=selector,
    )

    missing = asyncio.run(missing_builder.build(processed, early_safety))
    unavailable = asyncio.run(unavailable_builder.build(processed, early_safety))
    empty = asyncio.run(empty_builder.build(processed, early_safety))

    assert missing.memory_context is None
    assert missing.missing_context == [ContextKind.MEMORY.value]
    assert unavailable.memory_context is None
    assert unavailable.missing_context == [ContextKind.MEMORY.value]
    assert empty.memory_context is not None
    assert empty.memory_context.retrieved_memories == []
    assert empty.missing_context is None


@pytest.mark.parametrize(
    ("source", "trigger_type", "payload"),
    [
        (InputSource.USER, InputTriggerType.USER_TEXT, None),
        (
            InputSource.SCHEDULER,
            InputTriggerType.SCHEDULER_EVENT,
            {"event": "TEST_EVENT"},
        ),
        (
            InputSource.TOOL,
            InputTriggerType.TOOL_CALLBACK,
            {"result_ref": "result-1"},
        ),
        (
            InputSource.SYSTEM,
            InputTriggerType.DEVICE_EVENT,
            {"device_event": "TEST_EVENT"},
        ),
    ],
)
def test_m1_core_trigger_families_build_runtime_context(
    source: InputSource,
    trigger_type: InputTriggerType,
    payload: dict[str, object] | None,
) -> None:
    text = "hello" if trigger_type is InputTriggerType.USER_TEXT else None
    processed = asyncio.run(
        DefaultInputProcessor().process(
            _input(
                source=source,
                trigger_type=trigger_type,
                text=text,
                raw_text=None,
                input_payload=payload,
            )
        )
    )
    context = asyncio.run(
        DefaultContextBuilder(
            runtime_state_provider=GateRuntimeStateProvider()
        ).build(processed, _safety(processed, SafetyPhase.EARLY))
    )

    assert context.session_context.session_id == processed.session_id
    assert context.identity_context.subject_id == processed.subject_id
    assert context.runtime_state_context.current_state is RuntimeControlState.PROCESSING


def test_m1_critical_context_failure_stops_runtime_at_context_stage() -> None:
    recorder = CallRecorder()
    orchestrator = _orchestrator(
        recorder=recorder,
        context_builder=DefaultContextBuilder(
            runtime_state_provider=UnavailableRuntimeStateProvider()
        ),
    )

    with pytest.raises(StageExecutionError) as exc_info:
        asyncio.run(orchestrator.run(_input()))

    error = exc_info.value
    assert error.stage_name == "CONTEXT"
    assert isinstance(error.cause, CriticalContextUnavailableError)
    assert error.trace_context is not None
    assert [event.stage_name for event in error.trace_context.stage_events] == [
        "INPUT",
        "SAFETY_EARLY",
        "CONTEXT",
    ]
    assert recorder.calls == ["SAFETY_EARLY"]


def test_m1_two_turns_keep_session_identity_without_trace_cross_contamination() -> None:
    recorder = CallRecorder()
    orchestrator = _orchestrator(
        recorder=recorder,
        context_builder=DefaultContextBuilder(
            runtime_state_provider=GateRuntimeStateProvider()
        ),
    )

    first = asyncio.run(
        orchestrator.run(
            _input(request_id="request-1", trace_id="trace-1", session_id="session-1")
        )
    )
    second = asyncio.run(
        orchestrator.run(
            _input(request_id="request-2", trace_id="trace-2", session_id="session-1")
        )
    )

    assert first.trace.session_id == second.trace.session_id == "session-1"
    assert first.trace.trace_id == "trace-1"
    assert second.trace.trace_id == "trace-2"
    assert first.trace.turn_id != second.trace.turn_id
    assert len(first.trace.stage_events) == len(EXPECTED_CALL_ORDER)
    assert len(second.trace.stage_events) == len(EXPECTED_CALL_ORDER)
