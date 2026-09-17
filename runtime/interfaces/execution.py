"""ExecutionEngine：节点⑦执行接口。"""

from abc import ABC, abstractmethod

from runtime.contracts import ApprovedActionPlan, ExecutionResult, RuntimeContext


class ExecutionEngine(ABC):
    """只接受 ApprovedActionPlan。不得生成用户可见回复。"""

    @abstractmethod
    async def execute(
        self,
        approved_action_plan: ApprovedActionPlan,
        runtime_context: RuntimeContext,
    ) -> ExecutionResult:
        """执行已批准计划并返回 ExecutionResult。"""
        raise NotImplementedError
