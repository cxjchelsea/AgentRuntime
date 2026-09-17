"""M2-IU6 deterministic Plan Policy Re-check implementation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from runtime.contracts import (
    ActionPlanDraft,
    ApprovedActionPlan,
    PolicyDecision,
)
from runtime.interfaces.planning import PolicyRechecker
from runtime.policy_enforcement.errors import (
    PlanPolicyViolationError,
    PolicyRecheckInvariantError,
)


class DefaultPolicyRechecker(PolicyRechecker):
    """Approve a validated draft only when it remains inside PolicyDecision bounds.

    The re-check is deterministic and side-effect free. It never repairs, rewrites, or
    replans a violating draft. A violation fails closed before M5.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))

    async def recheck(
        self,
        action_plan_draft: ActionPlanDraft,
        policy_decision: PolicyDecision,
    ) -> ApprovedActionPlan:
        """Validate policy constraints and produce the sole M5-approved plan type."""
        self._validate_policy(policy_decision)
        self._validate_steps(action_plan_draft, policy_decision)
        self._validate_forced_requirements(action_plan_draft, policy_decision)
        self._validate_confirmation(action_plan_draft, policy_decision)

        draft_payload = action_plan_draft.model_dump(
            mode="python",
            exclude={"approval_status"},
        )
        return ApprovedActionPlan(
            **draft_payload,
            policy_snapshot=policy_decision.model_dump(mode="json"),
            approved_at=self._clock(),
        )

    @staticmethod
    def _validate_policy(policy_decision: PolicyDecision) -> None:
        if policy_decision.allowed and policy_decision.blocked:
            raise PolicyRecheckInvariantError(
                "PolicyDecision cannot be both allowed and blocked"
            )
        if policy_decision.blocked or not policy_decision.allowed:
            raise PlanPolicyViolationError(
                "active PolicyDecision does not allow plan approval"
            )

    @classmethod
    def _validate_steps(
        cls,
        action_plan_draft: ActionPlanDraft,
        policy_decision: PolicyDecision,
    ) -> None:
        for step in action_plan_draft.steps:
            cls._validate_reference(
                value=step.action,
                allowed=policy_decision.allowed_actions,
                forbidden=policy_decision.forbidden_actions,
                label="action",
            )
            if step.skill_id is not None:
                cls._validate_reference(
                    value=step.skill_id,
                    allowed=policy_decision.allowed_skills,
                    forbidden=policy_decision.forbidden_skills,
                    label="skill",
                )
            if step.tool_requirement is not None:
                cls._validate_reference(
                    value=step.tool_requirement,
                    allowed=policy_decision.allowed_tools,
                    forbidden=policy_decision.forbidden_tools,
                    label="tool",
                )

    @staticmethod
    def _validate_reference(
        *,
        value: str,
        allowed: list[str] | None,
        forbidden: list[str] | None,
        label: str,
    ) -> None:
        if forbidden is not None and value in forbidden:
            raise PlanPolicyViolationError(f"plan uses forbidden {label}")
        if allowed is not None and value not in allowed:
            raise PlanPolicyViolationError(f"plan uses {label} outside allowed set")

    @staticmethod
    def _validate_forced_requirements(
        action_plan_draft: ActionPlanDraft,
        policy_decision: PolicyDecision,
    ) -> None:
        if policy_decision.forced_action is not None and not any(
            step.action == policy_decision.forced_action
            for step in action_plan_draft.steps
        ):
            raise PlanPolicyViolationError("plan does not contain forced_action")

        if policy_decision.forced_workflow is not None:
            workflow_ids = {
                step.workflow_id
                for step in action_plan_draft.steps
                if step.workflow_id is not None
            }
            if policy_decision.forced_workflow not in workflow_ids:
                raise PlanPolicyViolationError("plan does not contain forced_workflow")
            unexpected = workflow_ids - {policy_decision.forced_workflow}
            if unexpected:
                raise PlanPolicyViolationError(
                    "plan contains workflow outside forced_workflow"
                )

    @staticmethod
    def _validate_confirmation(
        action_plan_draft: ActionPlanDraft,
        policy_decision: PolicyDecision,
    ) -> None:
        if (
            policy_decision.confirmation_required is True
            and not action_plan_draft.confirmation_plan
        ):
            raise PlanPolicyViolationError(
                "policy requires confirmation but plan has no confirmation_plan"
            )
