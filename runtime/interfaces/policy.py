"""PolicyEngine：节点⑤策略聚合接口。"""

from abc import ABC, abstractmethod

from runtime.contracts import (
    PolicyDecision,
    RuntimeContext,
    SafetyResult,
    UnderstandingState,
)


class PolicyEngine(ABC):
    """根据上下文、理解与安全结果给出 PolicyDecision。"""

    @abstractmethod
    async def evaluate(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        safety_result: SafetyResult,
    ) -> PolicyDecision:
        """输出允许/禁止约束。不得生成 ApprovedActionPlan。"""
        raise NotImplementedError
