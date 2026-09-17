"""ContextBuilder：节点③上下文构建接口。"""

from abc import ABC, abstractmethod

from runtime.contracts import RuntimeContext, RuntimeInput, SafetyResult


class ContextBuilder(ABC):
    """根据标准化输入与早期安全结果构建 RuntimeContext。"""

    @abstractmethod
    async def build(
        self,
        runtime_input: RuntimeInput,
        safety_result: SafetyResult,
    ) -> RuntimeContext:
        """构建已知背景。不得伪造未观察到的事实。"""
        raise NotImplementedError
