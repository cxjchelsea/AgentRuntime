"""UnderstandingEngine：节点④理解接口。"""

from abc import ABC, abstractmethod

from runtime.contracts import RuntimeContext, RuntimeInput, UnderstandingState


class UnderstandingEngine(ABC):
    """只负责理解，不规划、不执行、不改状态。"""

    @abstractmethod
    async def understand(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext,
    ) -> UnderstandingState:
        """输出 UnderstandingState。不得返回计划或调用 Tool。"""
        raise NotImplementedError
