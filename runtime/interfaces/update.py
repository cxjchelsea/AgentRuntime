"""StateMemoryUpdater：节点⑩状态与记忆提交接口。"""

from abc import ABC, abstractmethod

from runtime.contracts import (
    ApprovedActionPlan,
    RuntimeContext,
    RuntimeInput,
    RuntimeResponse,
    UnderstandingState,
    UpdateResult,
    ValidatedResult,
)


class StateMemoryUpdater(ABC):
    """正式输出只能是 UpdateResult。不得重新规划或执行业务。"""

    @abstractmethod
    async def update(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        approved_action_plan: ApprovedActionPlan,
        validated_result: ValidatedResult,
        runtime_response: RuntimeResponse,
    ) -> UpdateResult:
        """提交本轮状态与记忆。StateUpdate / MemoryUpdate 仅作为内部结果。"""
        raise NotImplementedError
