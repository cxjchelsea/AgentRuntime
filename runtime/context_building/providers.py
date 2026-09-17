"""M1 Context Builder 的内部 Provider 抽象。

这些类型只负责把外部/持久化事实读成已经冻结的 RuntimeContext 子结构。
它们不是新的 Canonical Contract，也不负责 Understanding、Policy 或 Planning。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum

from runtime.contracts import (
    DomainExtensions,
    EnvironmentContext,
    InteractionContext,
    MemoryContext,
    RuntimeInput,
    RuntimeStateContext,
    SafetyResult,
    TaskContext,
    ToolContext,
)
from runtime.contracts.context import ConversationContext
from runtime.contracts.enums import IdentityStatus


class ContextKind(str, Enum):
    """可选 Context Provider 的 Core 结构类型。"""

    CONVERSATION = "conversation_context"
    TASK = "task_context"
    MEMORY = "memory_context"
    TOOL = "tool_context"
    INTERACTION = "interaction_context"
    ENVIRONMENT = "environment_context"
    DOMAIN_EXTENSIONS = "domain_extensions"


ContextValue = (
    ConversationContext
    | TaskContext
    | MemoryContext
    | ToolContext
    | InteractionContext
    | EnvironmentContext
    | DomainExtensions
)


class ContextProviderUnavailable(RuntimeError):
    """Provider 明确表示当前上下文不可取得，可安全降级为 missing_context。"""


class RuntimeStateProvider(ABC):
    """提供构造 RuntimeContext 所必需的 Core Runtime 状态快照。"""

    @abstractmethod
    async def load(self, runtime_input: RuntimeInput) -> RuntimeStateContext:
        """读取当前 Runtime 状态；不得根据用户文本猜测状态。"""
        raise NotImplementedError


class IdentityStatusResolver(ABC):
    """可选身份状态解析器；缺省时 Builder 使用 UNKNOWN。"""

    @abstractmethod
    async def resolve(self, runtime_input: RuntimeInput) -> IdentityStatus:
        """返回当前主体的绑定状态，不得猜测 Domain 角色。"""
        raise NotImplementedError


class ContextProvider(ABC):
    """一个可选 RuntimeContext 子结构的数据提供者。"""

    @property
    @abstractmethod
    def kind(self) -> ContextKind:
        """声明此 Provider 负责的唯一 ContextKind。"""
        raise NotImplementedError

    @abstractmethod
    async def load(
        self,
        runtime_input: RuntimeInput,
        safety_result: SafetyResult,
    ) -> ContextValue | None:
        """返回已观察到的上下文；无结果返回 None，不得伪造默认事实。"""
        raise NotImplementedError
