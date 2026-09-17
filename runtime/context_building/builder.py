"""M1 节点③ Context Builder 的默认真实实现。"""

from __future__ import annotations

from collections.abc import Iterable

from runtime.contracts import RuntimeContext, RuntimeInput, SafetyPhase, SafetyResult
from runtime.contracts.context import (
    ConversationContext,
    DomainExtensions,
    EnvironmentContext,
    IdentityContext,
    InteractionContext,
    MemoryContext,
    RuntimeStateContext,
    SafetyContext,
    SessionContext,
    TaskContext,
    TimeContext,
    ToolContext,
)
from runtime.contracts.enums import IdentityStatus
from runtime.context_building.errors import (
    ContextBuildInvariantError,
    CriticalContextUnavailableError,
    DuplicateContextProviderError,
    InvalidContextProviderResultError,
)
from runtime.context_building.providers import (
    ContextKind,
    ContextProvider,
    ContextProviderUnavailable,
    ContextValue,
    IdentityStatusResolver,
    RuntimeStateProvider,
)
from runtime.context_building.selector import ContextSelector, CoreContextSelector
from runtime.interfaces.context import ContextBuilder

_EXPECTED_PROVIDER_TYPES: dict[ContextKind, type[ContextValue]] = {
    ContextKind.CONVERSATION: ConversationContext,
    ContextKind.TASK: TaskContext,
    ContextKind.MEMORY: MemoryContext,
    ContextKind.TOOL: ToolContext,
    ContextKind.INTERACTION: InteractionContext,
    ContextKind.ENVIRONMENT: EnvironmentContext,
    ContextKind.DOMAIN_EXTENSIONS: DomainExtensions,
}


class DefaultContextBuilder(ContextBuilder):
    """聚合当前可证实背景，输出 Canonical ``RuntimeContext``。

    设计原则：
    - Identity / Session 由当前 RuntimeInput 确定，不猜测 Domain 身份；
    - RuntimeState 是必需事实，必须由显式 Provider 提供；
    - Safety / Time 只映射当前已知输入，不做新的风险或时间语义推断；
    - 其余上下文按 Selector 按需读取；
    - Provider 明确 unavailable/None 时写入 ``missing_context``，不伪造空事实；
    - 未预期异常不静默吞掉，避免把实现错误伪装成“没有上下文”。
    """

    def __init__(
        self,
        *,
        runtime_state_provider: RuntimeStateProvider,
        providers: Iterable[ContextProvider] = (),
        selector: ContextSelector | None = None,
        identity_status_resolver: IdentityStatusResolver | None = None,
    ) -> None:
        if runtime_state_provider is None:
            raise CriticalContextUnavailableError(
                "runtime_state_context",
                "RuntimeStateProvider is required",
            )

        self._runtime_state_provider = runtime_state_provider
        self._selector = selector if selector is not None else CoreContextSelector()
        self._identity_status_resolver = identity_status_resolver
        self._providers: dict[ContextKind, ContextProvider] = {}

        for provider in providers:
            if provider.kind in self._providers:
                raise DuplicateContextProviderError(
                    f"duplicate ContextProvider for {provider.kind.value}"
                )
            self._providers[provider.kind] = provider

    async def build(
        self,
        runtime_input: RuntimeInput,
        safety_result: SafetyResult,
    ) -> RuntimeContext:
        """按冻结边界构建一轮 RuntimeContext。"""
        self._validate_inputs(runtime_input, safety_result)
        missing_context: list[str] = []

        identity_status = await self._resolve_identity_status(
            runtime_input,
            missing_context,
        )
        identity_context = IdentityContext(
            subject_id=runtime_input.subject_id,
            identity_scope=runtime_input.identity_scope,
            identity_status=identity_status,
            actor_id=runtime_input.actor_id,
            device_id=runtime_input.device_id,
            tenant_id=runtime_input.tenant_id,
        )

        session_context = SessionContext(session_id=runtime_input.session_id)
        runtime_state_context = await self._load_runtime_state(runtime_input)

        # 这里只投影 Early Safety 已经确认的事实，不做新的风险判断。
        safety_context = SafetyContext(
            current_risk_state=safety_result.risk_level.value,
            safety_lock=safety_result.safety_lock_required,
            restricted_actions=safety_result.restricted_actions,
        )

        # RuntimeInput.timestamp 已由 IU1 标准化；不猜测用户本地时区，因而只填
        # current_datetime，其余 date/weekday/time_of_day 交由未来明确时区来源提供。
        time_context = TimeContext(current_datetime=runtime_input.timestamp)

        optional_values = await self._load_optional_contexts(
            runtime_input,
            safety_result,
            missing_context,
        )

        return RuntimeContext(
            identity_context=identity_context,
            session_context=session_context,
            runtime_state_context=runtime_state_context,
            conversation_context=self._value(
                optional_values,
                ContextKind.CONVERSATION,
                ConversationContext,
            ),
            task_context=self._value(
                optional_values,
                ContextKind.TASK,
                TaskContext,
            ),
            time_context=time_context,
            memory_context=self._value(
                optional_values,
                ContextKind.MEMORY,
                MemoryContext,
            ),
            safety_context=safety_context,
            tool_context=self._value(
                optional_values,
                ContextKind.TOOL,
                ToolContext,
            ),
            interaction_context=self._value(
                optional_values,
                ContextKind.INTERACTION,
                InteractionContext,
            ),
            environment_context=self._value(
                optional_values,
                ContextKind.ENVIRONMENT,
                EnvironmentContext,
            ),
            domain_extensions=self._value(
                optional_values,
                ContextKind.DOMAIN_EXTENSIONS,
                DomainExtensions,
            ),
            missing_context=missing_context or None,
        )

    @staticmethod
    def _validate_inputs(
        runtime_input: RuntimeInput,
        safety_result: SafetyResult,
    ) -> None:
        if safety_result.phase is not SafetyPhase.EARLY:
            raise ContextBuildInvariantError(
                "ContextBuilder 只能消费 SafetyResult(phase=EARLY)"
            )
        if safety_result.request_id != runtime_input.request_id:
            raise ContextBuildInvariantError(
                "SafetyResult.request_id 必须与 RuntimeInput.request_id 一致"
            )

    async def _resolve_identity_status(
        self,
        runtime_input: RuntimeInput,
        missing_context: list[str],
    ) -> IdentityStatus:
        resolver = self._identity_status_resolver
        if resolver is None:
            return IdentityStatus.UNKNOWN

        try:
            status = await resolver.resolve(runtime_input)
        except ContextProviderUnavailable:
            missing_context.append("identity_status")
            return IdentityStatus.UNKNOWN

        if not isinstance(status, IdentityStatus):
            raise InvalidContextProviderResultError(
                "identity_status",
                "IdentityStatus",
                type(status).__name__,
            )
        return status

    async def _load_runtime_state(
        self,
        runtime_input: RuntimeInput,
    ) -> RuntimeStateContext:
        try:
            state = await self._runtime_state_provider.load(runtime_input)
        except Exception as error:
            raise CriticalContextUnavailableError(
                "runtime_state_context",
                type(error).__name__,
            ) from error

        if not isinstance(state, RuntimeStateContext):
            raise InvalidContextProviderResultError(
                "runtime_state_context",
                "RuntimeStateContext",
                type(state).__name__,
            )
        return state

    async def _load_optional_contexts(
        self,
        runtime_input: RuntimeInput,
        safety_result: SafetyResult,
        missing_context: list[str],
    ) -> dict[ContextKind, ContextValue]:
        loaded: dict[ContextKind, ContextValue] = {}
        selected = tuple(dict.fromkeys(self._selector.select(runtime_input)))

        for kind in selected:
            provider = self._providers.get(kind)
            if provider is None:
                missing_context.append(kind.value)
                continue

            try:
                value = await provider.load(runtime_input, safety_result)
            except ContextProviderUnavailable:
                missing_context.append(kind.value)
                continue

            if value is None:
                missing_context.append(kind.value)
                continue

            expected_type = _EXPECTED_PROVIDER_TYPES[kind]
            if not isinstance(value, expected_type):
                raise InvalidContextProviderResultError(
                    kind.value,
                    expected_type.__name__,
                    type(value).__name__,
                )
            loaded[kind] = value

        return loaded

    @staticmethod
    def _value(
        values: dict[ContextKind, ContextValue],
        kind: ContextKind,
        expected_type: type[ContextValue],
    ) -> ContextValue | None:
        value = values.get(kind)
        if value is None:
            return None
        if not isinstance(value, expected_type):
            # 正常路径已在 Provider 边界校验；此处只保护内部不变量。
            raise ContextBuildInvariantError(
                f"{kind.value} 内部类型不变量被破坏"
            )
        return value
