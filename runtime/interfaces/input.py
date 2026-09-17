"""InputProcessor：节点①输入标准化接口。"""

from abc import ABC, abstractmethod

from runtime.contracts import RuntimeInput


class InputProcessor(ABC):
    """将本轮入口数据标准化为 RuntimeInput。不理解用户意图。"""

    @abstractmethod
    async def process(self, runtime_input: RuntimeInput) -> RuntimeInput:
        """标准化输入。不得调用 Understanding / Planner / Tool。"""
        raise NotImplementedError
