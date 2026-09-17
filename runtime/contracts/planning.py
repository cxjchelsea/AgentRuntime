"""ActionPlanDraft 与 ApprovedActionPlan。禁止定义 ActionPlan。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import field_validator

from runtime.contracts.common import (
    CanonicalModel,
    QualityAssessment,
    VersionedContract,
)
from runtime.contracts.enums import PlanApprovalStatus, PlanningMode


class PlanningGoal(CanonicalModel):
    """规划目标。goal_type 为注册引用，不是领域枚举。"""

    goal_id: str
    goal_type: str | None = None
    primary: bool | None = None
    goal_source: str | None = None
    goal_priority: int | None = None
    parameters: dict[str, Any] | None = None
    completion_condition: str | None = None


class ActionStep(CanonicalModel):
    """计划步骤。action 为 Core Control Action 或 Domain 注册值字符串。"""

    step_id: str
    action: str
    target: str | None = None
    parameters: dict[str, Any] | None = None
    skill_id: str | None = None
    workflow_id: str | None = None
    tool_requirement: str | None = None
    depends_on: list[str] | None = None
    optional: bool | None = None
    completion_condition: str | None = None
    on_failure: str | None = None


class StrategySelection(CanonicalModel):
    """策略选择。strategy_id 为注册引用。"""

    strategy_id: str
    reason_code: str | None = None
    confidence: float | None = None


class ActionPlanDraft(VersionedContract):
    """Planner 内部输出，approval_status 必须为 DRAFT。不得进入 M5。"""

    plan_id: str
    request_id: str
    approval_status: Literal[PlanApprovalStatus.DRAFT] = PlanApprovalStatus.DRAFT
    planning_mode: PlanningMode
    goals: list[PlanningGoal]
    steps: list[ActionStep]
    quality: QualityAssessment
    strategy: StrategySelection | None = None
    memory_usage: dict[str, Any] | None = None
    capability_plan: dict[str, Any] | None = None
    tool_plan: dict[str, Any] | None = None
    confirmation_plan: dict[str, Any] | None = None
    response_strategy: dict[str, Any] | None = None
    state_intent: dict[str, Any] | None = None
    stop_conditions: list[str] | None = None
    fallback_plan: dict[str, Any] | None = None
    trace: dict[str, Any] | None = None

    @field_validator("approval_status")
    @classmethod
    def validate_draft_status(
        cls, approval_status: PlanApprovalStatus
    ) -> PlanApprovalStatus:
        """Draft 不得伪装成已批准计划。"""
        if approval_status is not PlanApprovalStatus.DRAFT:
            raise ValueError("ActionPlanDraft.approval_status 必须为 DRAFT")
        return approval_status


class ApprovedActionPlan(VersionedContract):
    """M5 唯一合法规划输入，approval_status 必须为 APPROVED。"""

    plan_id: str
    request_id: str
    approval_status: Literal[PlanApprovalStatus.APPROVED] = PlanApprovalStatus.APPROVED
    planning_mode: PlanningMode
    goals: list[PlanningGoal]
    steps: list[ActionStep]
    policy_snapshot: dict[str, Any]
    quality: QualityAssessment
    strategy: StrategySelection | None = None
    memory_usage: dict[str, Any] | None = None
    capability_plan: dict[str, Any] | None = None
    tool_plan: dict[str, Any] | None = None
    confirmation_plan: dict[str, Any] | None = None
    response_strategy: dict[str, Any] | None = None
    state_intent: dict[str, Any] | None = None
    stop_conditions: list[str] | None = None
    fallback_plan: dict[str, Any] | None = None
    trace: dict[str, Any] | None = None
    approved_at: datetime | None = None

    @field_validator("approval_status")
    @classmethod
    def validate_approved_status(
        cls, approval_status: PlanApprovalStatus
    ) -> PlanApprovalStatus:
        """Approved 不得回退为 Draft。"""
        if approval_status is not PlanApprovalStatus.APPROVED:
            raise ValueError("ApprovedActionPlan.approval_status 必须为 APPROVED")
        return approval_status
