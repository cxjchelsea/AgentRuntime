"""ResponsePlanner / ResponseGenerator / ResponseValidator：M7 边界。"""

from abc import ABC, abstractmethod

from runtime.contracts import (
    ApprovedActionPlan,
    ResponsePlan,
    RuntimeContext,
    RuntimeResponse,
    UnderstandingState,
    ValidatedResult,
)


class ResponsePlanner(ABC):
    """只规划表达，不生成最终用户文本以外的副作用。"""

    @abstractmethod
    async def plan(
        self,
        validated_result: ValidatedResult,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        approved_action_plan: ApprovedActionPlan,
    ) -> ResponsePlan:
        """必须消费 ValidatedResult，不得直接消费 ExecutionResult。"""
        raise NotImplementedError


class ResponseGenerator(ABC):
    """只消费 ResponsePlan，输出 RuntimeResponse。"""

    @abstractmethod
    async def generate(self, response_plan: ResponsePlan) -> RuntimeResponse:
        """生成用户可见输出。不得修改 Runtime State。"""
        raise NotImplementedError


class ResponseValidator(ABC):
    """校验 RuntimeResponse 未越过 forbidden claims。"""

    @abstractmethod
    async def validate(
        self,
        runtime_response: RuntimeResponse,
        validated_result: ValidatedResult,
    ) -> RuntimeResponse:
        """通过则返回已校验的 RuntimeResponse。"""
        raise NotImplementedError
