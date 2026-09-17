"""ResultValidator：节点⑧结果验证接口。"""

from abc import ABC, abstractmethod

from runtime.contracts import (
    ApprovedActionPlan,
    ExecutionResult,
    RuntimeContext,
    ValidatedResult,
)


class ResultValidator(ABC):
    """把执行观察提升为已验证事实。不得重试业务 Tool。"""

    @abstractmethod
    async def validate(
        self,
        execution_result: ExecutionResult,
        runtime_context: RuntimeContext,
        approved_action_plan: ApprovedActionPlan,
    ) -> ValidatedResult:
        """输出 ValidatedResult。不得直接进入回复生成。"""
        raise NotImplementedError
