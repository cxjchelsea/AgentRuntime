"""M1-IU2：真实 Context Builder 测试。

本文件验证节点③只聚合当前可证实背景，不做 Understanding / Policy / Planning。
完整 Runtime 集成仍让 M2-M8 使用 M0 Stub。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import cast

import pytest

from runtime.context_building import (
    ContextBuildInvariantError,
    ContextKind,
    ContextProvider,
    ContextProviderUnavailable,
    CoreContextSelector,
    CriticalContextUnavailableError,
    DefaultContextBuilder,
    DuplicateContextProviderError,
    IdentityStatusResolver,
    InvalidContextProviderResultError,
    RuntimeStateProvider,
)
from runtime.context_building.providers import ContextValue
from runtime.contracts import (
    DomainExtensions,
    IdentityStatus,
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
from runtime.contracts.context import (
    ConversationContext,
    MemoryContext,
    RuntimeStateContext,
    TaskContext,
    ToolContext,
)
from runtime.input_processing import DefaultInputProcessor
from runtime.orchestration import RuntimeOrchestrator
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
    StubSafetyGuard,
    StubStateMemoryUpdater,
    StubUnderstandingEngine,
)


def _input(**overrides: object) -> RuntimeInput:
    values: dict[str, object] = {
        "request_id": "request-001",
        "trace_id": "trace-001",
        "session_id": "session-001",
        "subject_id": "subject-001",
        "identity_scope": "scope-001",
        "actor_id": "actor-001",
        "device_id": "device-001",
        "tenant_id": "tenant-001",
        "source": InputSource.USER,
        "trigger_type": InputTriggerType.USER_TEXT,
        "timestamp": datetime(2026, 9, 17, 8, 30, tzinfo=UTC),
        "text": "hello",
    }
    values.update(overrides)
    return RuntimeInput.model_validate(values)


def _safety(**overrides: object) -> SafetyResult:
    values: dict[str, object] = {
        "safety_result_id": "safety-early",
        "request_id": "request-001",
        "phase": SafetyPhase.EARLY,
        "risk_detected": False,
        "risk_level": SafetyRiskLevel.NONE,
        "interrupt_current_task": False,
        "allowed_to_continue_normal_flow": True,
        "safety_lock_required": False,
        "reason_codes": ["SAFE"],
        "created_at": datetime(2026, 9, 17, 8, 30, tzinfo=UTC),
    }
    values.update(overrides)
    return SafetyResult.model_validate(values)


class TestRuntimeStateProvider(RuntimeStateProvider):
    """测试用真实状态快照来源。"""

    __test__ = False

    def __init__(self) -> None:
        self.calls = 0

    async def load(self, runtime_input: RuntimeInput) -> RuntimeStateContext:
        self.calls += 1
        return RuntimeStateContext(
            current_state=RuntimeControlState.PROCESSING,
            previous_state=RuntimeControlState.LISTENING,
            interruptible=True,
            entered_at=runtime_input.timestamp,
        )


class FailingRuntimeStateProvider(RuntimeStateProvider):
    async def load(self, runtime_input: RuntimeInput) -> RuntimeStateContext:
        raise ContextProviderUnavailable("state store unavailable")


class ExplodingRuntimeStateProvider(RuntimeStateProvider):
    async def load(self, runtime_input: RuntimeInput) -> RuntimeStateContext:
        raise ValueError("provider bug")


class BoundIdentityResolver(IdentityStatusResolver):
    async def resolve(self, runtime_input: RuntimeInput) -> IdentityStatus:
        return IdentityStatus.BOUND


class UnboundIdentityResolver(IdentityStatusResolver):
    async def resolve(self, runtime_input: RuntimeInput) -> IdentityStatus:
        return IdentityStatus.UNBOUND


class UnavailableIdentityResolver(IdentityStatusResolver):
    async def resolve(self, runtime_input: RuntimeInput) -> IdentityStatus:
        raise ContextProviderUnavailable("identity service unavailable")


class FixedContextProvider(ContextProvider):
    """返回固定 ContextValue，并记录是否真正被 Selector 选中。"""

    def __init__(
        self,
        kind: ContextKind,
        value: ContextValue | None,
        *,
        unavailable: bool = False,
    ) -> None:
        self._kind = kind
        self._value = value
        self._unavailable = unavailable
        self.calls = 0

    @property
    def kind(self) -> ContextKind:
        return self._kind

    async def load(
        self,
        runtime_input: RuntimeInput,
        safety_result: SafetyResult,
    ) -> ContextValue | None:
        self.calls += 1
        if self._unavailable:
            raise ContextProviderUnavailable(self.kind.value)
        return self._value


class InvalidConversationProvider(ContextProvider):
    @property
    def kind(self) -> ContextKind:
        return ContextKind.CONVERSATION

    async def load(
        self,
        runtime_input: RuntimeInput,
        safety_result: SafetyResult,
    ) -> ContextValue | None:
        return cast(ContextValue, "not-a-context")


def _build(
    builder: DefaultContextBuilder,
    runtime_input: RuntimeInput | None = None,
    safety_result: SafetyResult | None = None,
) -> RuntimeContext:
    return asyncio.run(
        builder.build(
            runtime_input or _input(),
            safety_result or _safety(),
        )
    )


def test_builds_required_context_from_observed_core_facts() -> None:
    state_provider = TestRuntimeStateProvider()
    builder = DefaultContextBuilder(runtime_state_provider=state_provider)

    context = _build(builder)

    assert context.identity_context.subject_id == "subject-001"
    assert context.identity_context.identity_scope == "scope-001"
    assert context.identity_context.actor_id == "actor-001"
    assert context.identity_context.device_id == "device-001"
    assert context.identity_context.tenant_id == "tenant-001"
    assert context.identity_context.identity_status is IdentityStatus.UNKNOWN
    assert context.session_context.session_id == "session-001"
    assert context.runtime_state_context.current_state is RuntimeControlState.PROCESSING
    assert context.time_context is not None
    assert context.time_context.current_datetime == _input().timestamp
    assert context.safety_context is not None
    assert context.safety_context.current_risk_state == SafetyRiskLevel.NONE.value
    assert state_provider.calls == 1


def test_identity_status_is_never_inferred_from_subject_id() -> None:
    unknown_context = _build(
        DefaultContextBuilder(runtime_state_provider=TestRuntimeStateProvider())
    )
    bound_context = _build(
        DefaultContextBuilder(
            runtime_state_provider=TestRuntimeStateProvider(),
            identity_status_resolver=BoundIdentityResolver(),
        )
    )
    unbound_context = _build(
        DefaultContextBuilder(
            runtime_state_provider=TestRuntimeStateProvider(),
            identity_status_resolver=UnboundIdentityResolver(),
        )
    )

    assert unknown_context.identity_context.identity_status is IdentityStatus.UNKNOWN
    assert bound_context.identity_context.identity_status is IdentityStatus.BOUND
    assert unbound_context.identity_context.identity_status is IdentityStatus.UNBOUND


def test_unavailable_identity_resolver_is_explicitly_missing() -> None:
    context = _build(
        DefaultContextBuilder(
            runtime_state_provider=TestRuntimeStateProvider(),
            identity_status_resolver=UnavailableIdentityResolver(),
        )
    )

    assert context.identity_context.identity_status is IdentityStatus.UNKNOWN
    assert context.missing_context is not None
    assert "identity_status" in context.missing_context


def test_early_safety_is_projected_without_new_risk_inference() -> None:
    safety = _safety(
        risk_detected=True,
        risk_level=SafetyRiskLevel.HIGH,
        safety_lock_required=True,
        restricted_actions=["TEST_RESTRICTED_ACTION"],
    )
    context = _build(
        DefaultContextBuilder(runtime_state_provider=TestRuntimeStateProvider()),
        safety_result=safety,
    )

    assert context.safety_context is not None
    assert context.safety_context.current_risk_state == "HIGH"
    assert context.safety_context.safety_lock is True
    assert context.safety_context.restricted_actions == ["TEST_RESTRICTED_ACTION"]


def test_deep_safety_cannot_enter_context_builder() -> None:
    with pytest.raises(ContextBuildInvariantError, match="EARLY"):
        _build(
            DefaultContextBuilder(runtime_state_provider=TestRuntimeStateProvider()),
            safety_result=_safety(phase=SafetyPhase.DEEP),
        )


def test_mismatched_request_id_is_rejected() -> None:
    with pytest.raises(ContextBuildInvariantError, match="request_id"):
        _build(
            DefaultContextBuilder(runtime_state_provider=TestRuntimeStateProvider()),
            safety_result=_safety(request_id="another-request"),
        )


def test_runtime_state_is_critical_and_failure_is_not_fabricated() -> None:
    with pytest.raises(CriticalContextUnavailableError, match="runtime_state_context"):
        _build(
            DefaultContextBuilder(runtime_state_provider=FailingRuntimeStateProvider())
        )


def test_unexpected_runtime_state_provider_error_is_not_hidden_as_unavailable() -> None:
    with pytest.raises(ValueError, match="provider bug"):
        _build(
            DefaultContextBuilder(
                runtime_state_provider=ExplodingRuntimeStateProvider()
            )
        )


def test_default_selector_loads_only_core_relevant_optional_contexts() -> None:
    conversation = FixedContextProvider(
        ContextKind.CONVERSATION,
        ConversationContext(last_user_message="previous"),
    )
    memory = FixedContextProvider(
        ContextKind.MEMORY,
        MemoryContext(retrieved_memories=[]),
    )
    builder = DefaultContextBuilder(
        runtime_state_provider=TestRuntimeStateProvider(),
        providers=[conversation, memory],
    )

    context = _build(builder)

    assert conversation.calls == 1
    assert context.conversation_context is not None
    assert memory.calls == 0
    assert context.memory_context is None


def test_unregistered_selected_context_is_explicitly_missing() -> None:
    context = _build(
        DefaultContextBuilder(runtime_state_provider=TestRuntimeStateProvider())
    )

    assert context.missing_context == [
        ContextKind.CONVERSATION.value,
        ContextKind.TASK.value,
        ContextKind.TOOL.value,
        ContextKind.INTERACTION.value,
    ]


def test_provider_unavailable_is_distinct_from_empty_context() -> None:
    selector = CoreContextSelector({InputTriggerType.USER_TEXT: (ContextKind.MEMORY,)})
    unavailable = FixedContextProvider(
        ContextKind.MEMORY,
        None,
        unavailable=True,
    )
    unavailable_context = _build(
        DefaultContextBuilder(
            runtime_state_provider=TestRuntimeStateProvider(),
            providers=[unavailable],
            selector=selector,
        )
    )

    empty = FixedContextProvider(
        ContextKind.MEMORY,
        MemoryContext(retrieved_memories=[], service_status="AVAILABLE"),
    )
    empty_context = _build(
        DefaultContextBuilder(
            runtime_state_provider=TestRuntimeStateProvider(),
            providers=[empty],
            selector=selector,
        )
    )

    assert unavailable_context.memory_context is None
    assert unavailable_context.missing_context == [ContextKind.MEMORY.value]
    assert empty_context.memory_context is not None
    assert empty_context.memory_context.retrieved_memories == []
    assert empty_context.missing_context is None


def test_domain_extension_only_enters_canonical_mount_point() -> None:
    selector = CoreContextSelector(
        {InputTriggerType.USER_TEXT: (ContextKind.DOMAIN_EXTENSIONS,)}
    )
    provider = FixedContextProvider(
        ContextKind.DOMAIN_EXTENSIONS,
        DomainExtensions(
            domain_id="TEST_DOMAIN",
            domain_state={"test_state": "ACTIVE"},
        ),
    )
    context = _build(
        DefaultContextBuilder(
            runtime_state_provider=TestRuntimeStateProvider(),
            providers=[provider],
            selector=selector,
        )
    )

    assert context.domain_extensions is not None
    assert context.domain_extensions.domain_id == "TEST_DOMAIN"
    assert "current_business" not in context.runtime_state_context.model_fields


def test_wrong_provider_result_type_fails_fast() -> None:
    selector = CoreContextSelector(
        {InputTriggerType.USER_TEXT: (ContextKind.CONVERSATION,)}
    )
    builder = DefaultContextBuilder(
        runtime_state_provider=TestRuntimeStateProvider(),
        providers=[InvalidConversationProvider()],
        selector=selector,
    )

    with pytest.raises(InvalidContextProviderResultError, match="ConversationContext"):
        _build(builder)


def test_duplicate_provider_kind_is_rejected() -> None:
    provider_a = FixedContextProvider(
        ContextKind.TASK,
        TaskContext(task_id="task-a"),
    )
    provider_b = FixedContextProvider(
        ContextKind.TASK,
        TaskContext(task_id="task-b"),
    )

    with pytest.raises(DuplicateContextProviderError, match="task_context"):
        DefaultContextBuilder(
            runtime_state_provider=TestRuntimeStateProvider(),
            providers=[provider_a, provider_b],
        )


def test_tool_callback_selector_does_not_load_unrelated_context() -> None:
    task = FixedContextProvider(ContextKind.TASK, TaskContext(task_id="task-1"))
    tool = FixedContextProvider(
        ContextKind.TOOL,
        ToolContext(active_tool_calls=[{"tool_id": "TEST_TOOL"}]),
    )
    conversation = FixedContextProvider(
        ContextKind.CONVERSATION,
        ConversationContext(current_topic="TEST_TOPIC"),
    )
    context = _build(
        DefaultContextBuilder(
            runtime_state_provider=TestRuntimeStateProvider(),
            providers=[task, tool, conversation],
        ),
        runtime_input=_input(
            source=InputSource.TOOL,
            trigger_type=InputTriggerType.TOOL_CALLBACK,
            text=None,
            input_payload={"result_ref": "test-result"},
        ),
    )

    assert task.calls == 1
    assert tool.calls == 1
    assert conversation.calls == 0
    assert context.task_context is not None
    assert context.tool_context is not None
    assert context.conversation_context is None


def test_real_input_and_context_can_replace_first_two_m0_stubs() -> None:
    recorder = CallRecorder()

    class RequestAwareSafetyGuard(StubSafetyGuard):
        async def evaluate_early(
            self,
            runtime_input: RuntimeInput,
            runtime_context: RuntimeContext | None = None,
        ) -> SafetyResult:
            self._call_recorder.record("SAFETY_EARLY")
            return _safety(request_id=runtime_input.request_id)

        async def evaluate_deep(
            self,
            runtime_input: RuntimeInput,
            runtime_context: RuntimeContext,
            understanding_state: UnderstandingState,
            early_safety: SafetyResult,
        ) -> SafetyResult:
            self._call_recorder.record("SAFETY_DEEP")
            return _safety(
                request_id=runtime_input.request_id,
                phase=SafetyPhase.DEEP,
            )

    class CapturingUnderstandingEngine(StubUnderstandingEngine):
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

    safety_guard = RequestAwareSafetyGuard(recorder)
    understanding_engine = CapturingUnderstandingEngine(recorder)
    context_builder = DefaultContextBuilder(
        runtime_state_provider=TestRuntimeStateProvider()
    )
    orchestrator = RuntimeOrchestrator(
        input_processor=DefaultInputProcessor(),
        safety_guard=safety_guard,
        context_builder=context_builder,
        understanding_engine=understanding_engine,
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

    outcome = asyncio.run(
        orchestrator.run(
            _input(
                request_id="request-integration",
                session_id="session-integration",
                text="  hello   context ",
            )
        )
    )

    assert outcome.runtime_response is not None
    assert outcome.update_result is not None
    assert understanding_engine.seen_input is not None
    assert understanding_engine.seen_input.request_id == "request-integration"
    assert understanding_engine.seen_input.text == "hello context"
    assert understanding_engine.seen_input.raw_text == "  hello   context "
    assert understanding_engine.seen_context is not None
    assert understanding_engine.seen_context.session_context.session_id == (
        "session-integration"
    )
    assert (
        understanding_engine.seen_context.identity_context.subject_id == "subject-001"
    )
    assert understanding_engine.seen_context.safety_context is not None
    assert (
        understanding_engine.seen_context.safety_context.current_risk_state
        == SafetyRiskLevel.NONE.value
    )
    assert understanding_engine.seen_context.time_context is not None
    assert (
        understanding_engine.seen_context.time_context.current_datetime
        == _input().timestamp
    )
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
