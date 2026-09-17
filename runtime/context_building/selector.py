"""M1 Context Selector：按 Core trigger 选择最小必要可选上下文。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping

from runtime.context_building.providers import ContextKind
from runtime.contracts import InputTriggerType, RuntimeInput


class ContextSelector(ABC):
    """决定本轮需要加载哪些可选 Context；不做语义理解。"""

    @abstractmethod
    def select(self, runtime_input: RuntimeInput) -> tuple[ContextKind, ...]:
        """返回按优先级排列的可选 ContextKind。"""
        ...


_DEFAULT_ROUTES: dict[InputTriggerType, tuple[ContextKind, ...]] = {
    InputTriggerType.USER_VOICE: (
        ContextKind.CONVERSATION,
        ContextKind.TASK,
        ContextKind.TOOL,
        ContextKind.INTERACTION,
    ),
    InputTriggerType.USER_TEXT: (
        ContextKind.CONVERSATION,
        ContextKind.TASK,
        ContextKind.TOOL,
        ContextKind.INTERACTION,
    ),
    InputTriggerType.USER_OTHER: (
        ContextKind.CONVERSATION,
        ContextKind.TASK,
        ContextKind.TOOL,
        ContextKind.INTERACTION,
    ),
    InputTriggerType.SYSTEM_EVENT: (
        ContextKind.TASK,
        ContextKind.INTERACTION,
    ),
    InputTriggerType.SCHEDULER_EVENT: (ContextKind.TASK,),
    InputTriggerType.TOOL_CALLBACK: (
        ContextKind.TASK,
        ContextKind.TOOL,
    ),
    InputTriggerType.WORKFLOW_CALLBACK: (
        ContextKind.TASK,
        ContextKind.TOOL,
    ),
    InputTriggerType.TIMEOUT: (ContextKind.TASK,),
    InputTriggerType.NETWORK_EVENT: (
        ContextKind.TOOL,
        ContextKind.ENVIRONMENT,
    ),
    InputTriggerType.DEVICE_EVENT: (ContextKind.ENVIRONMENT,),
}


class CoreContextSelector(ContextSelector):
    """只依据 Core trigger 的可配置规则选择 Context。

    默认规则不读取用户文本内容，因此不会提前承担 M3 的语义理解职责。
    Memory 与 DomainExtensions 默认不自动加载，必须由调用方显式配置。
    """

    def __init__(
        self,
        routes: Mapping[InputTriggerType, tuple[ContextKind, ...]] | None = None,
    ) -> None:
        source = _DEFAULT_ROUTES if routes is None else routes
        self._routes = {trigger: tuple(kinds) for trigger, kinds in source.items()}

    def select(self, runtime_input: RuntimeInput) -> tuple[ContextKind, ...]:
        """返回当前 trigger 的最小必要可选上下文集合。"""
        return self._routes.get(runtime_input.trigger_type, ())
