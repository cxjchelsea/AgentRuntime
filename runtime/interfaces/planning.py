"""Planner / PlanValidator / PolicyRechecker：M4 规划边界。"""

from abc import ABC, abstractmethod

from runtime.contracts import (
    ActionPlanDraft,
    ApprovedActionPlan,
    PolicyDecision,
    RuntimeContext,
    UnderstandingState,
)


class Planner(ABC):
    """只输出 ActionPlanDraft，不得执行 Tool。"""

    @abstractmethod
    async def plan(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        policy_decision: PolicyDecision,
    ) -> ActionPlanDraft:
        """生成尚未批准的计划。"""
        raise NotImplementedError


class PlanValidator(ABC):
    """校验 Draft 结构与能力引用。不发明新 Contract。"""

    @abstractmethod
    async def validate(self, action_plan_draft: ActionPlanDraft) -> ActionPlanDraft:
        """通过则返回同一 Draft；失败由实现抛出，不新增结果类型。"""
        raise NotImplementedError


class PolicyRechecker(ABC):
    """对已校验 Draft 做 Policy 二次检查，输出 ApprovedActionPlan。"""

    @abstractmethod
    async def recheck(
        self,
        action_plan_draft: ActionPlanDraft,
        policy_decision: PolicyDecision,
    ) -> ApprovedActionPlan:
        """M5 之前的唯一批准出口。"""
        raise NotImplementedError
