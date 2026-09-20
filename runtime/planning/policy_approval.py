"""M4-IU7 M2 Policy Re-check + ApprovedActionPlan integration.

This module does not reimplement M2 approval. It performs M4-side surface auditing,
delegates approval to the frozen PolicyRechecker interface, and verifies that approval
did not mutate planning semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from runtime.contracts import ActionPlanDraft, ApprovedActionPlan, PolicyDecision
from runtime.contracts.enums import PlanApprovalStatus
from runtime.interfaces.planning import PolicyRechecker
from runtime.planning.draft_validation import PlanValidationResult
from runtime.planning.errors import (
    ApprovalIntegrityError,
    PolicyApprovalIntegrationError,
    PolicySurfaceViolationError,
)


class PolicyApprovalRule(Protocol):
    """Injected Domain/config rule for opaque policy fields M4 Core cannot interpret."""

    def validate(
        self,
        draft: ActionPlanDraft,
        policy_decision: PolicyDecision,
    ) -> str | None:
        """Raise PolicySurfaceViolationError to reject, or return an audit code."""


@dataclass(frozen=True, slots=True)
class PolicyApprovalResult:
    """IU7 output: the sole M5-legal plan plus audit codes."""

    approved_plan: ApprovedActionPlan
    audit_codes: tuple[str, ...]


class M4PolicySurfaceAuditor:
    """Audit explicit PolicyDecision bounds across all M4 Draft subplans.

    M2 DefaultPolicyRechecker already checks step action/skill/tool references,
    forced action/workflow, and confirmation presence. IU7 extends visibility to
    M4-owned opaque subplans so those fields cannot bypass the same explicit lists.
    """

    def __init__(self, rules: tuple[PolicyApprovalRule, ...] = ()) -> None:
        self._rules = rules

    def audit(
        self,
        draft: ActionPlanDraft,
        policy_decision: PolicyDecision,
    ) -> tuple[str, ...]:
        self._validate_actions(draft, policy_decision)
        self._validate_skills(draft, policy_decision)
        self._validate_tools(draft, policy_decision)
        self._validate_forced_workflow_surface(draft, policy_decision)
        self._validate_confirmation(draft, policy_decision)

        codes = ["M4_POLICY_SURFACE_VALID"]
        for rule in self._rules:
            try:
                code = rule.validate(draft, policy_decision)
            except Exception as exc:
                if isinstance(exc, PolicyApprovalIntegrationError):
                    raise
                raise PolicySurfaceViolationError(
                    "injected policy approval rule execution failed"
                ) from exc
            if code is not None:
                if not code.strip():
                    raise PolicySurfaceViolationError(
                        "policy approval rule audit code must not be blank"
                    )
                codes.append(code)
        return tuple(dict.fromkeys(codes))

    @classmethod
    def _validate_actions(
        cls,
        draft: ActionPlanDraft,
        policy_decision: PolicyDecision,
    ) -> None:
        action_ids = [step.action for step in draft.steps]
        fallback = draft.fallback_plan or {}
        fallback_actions = fallback.get("allowed_actions", [])
        if not isinstance(fallback_actions, list) or any(
            not isinstance(item, str) for item in fallback_actions
        ):
            raise PolicySurfaceViolationError(
                "fallback allowed_actions must be a string list"
            )
        action_ids.extend(fallback_actions)
        for action_id in action_ids:
            cls._validate_reference(
                value=action_id,
                allowed=policy_decision.allowed_actions,
                forbidden=policy_decision.forbidden_actions,
                label="action",
            )

        if policy_decision.forced_action is not None and not any(
            step.action == policy_decision.forced_action for step in draft.steps
        ):
            raise PolicySurfaceViolationError(
                "validated Draft does not contain M2 forced_action"
            )

    @classmethod
    def _validate_skills(
        cls,
        draft: ActionPlanDraft,
        policy_decision: PolicyDecision,
    ) -> None:
        skill_ids: list[str] = [
            step.skill_id for step in draft.steps if step.skill_id is not None
        ]
        capability = draft.capability_plan or {}
        selected = capability.get("selected_skills", [])
        bindings = capability.get("bindings", [])
        if not isinstance(selected, list) or any(
            not isinstance(item, str) for item in selected
        ):
            raise PolicySurfaceViolationError(
                "capability selected_skills must be a string list"
            )
        if not isinstance(bindings, list):
            raise PolicySurfaceViolationError(
                "capability bindings must be a list"
            )
        skill_ids.extend(selected)
        for binding in bindings:
            if not isinstance(binding, dict):
                raise PolicySurfaceViolationError(
                    "capability binding must be an object"
                )
            skill_id = binding.get("skill_id")
            if skill_id is not None:
                if not isinstance(skill_id, str):
                    raise PolicySurfaceViolationError(
                        "capability binding skill_id must be text"
                    )
                skill_ids.append(skill_id)

        tool_plan = draft.tool_plan or {}
        calls = tool_plan.get("tool_calls", [])
        if not isinstance(calls, list):
            raise PolicySurfaceViolationError("tool_calls must be a list")
        for call in calls:
            if not isinstance(call, dict):
                raise PolicySurfaceViolationError(
                    "tool call plan must be an object"
                )
            required_by = call.get("required_by_skills", [])
            if not isinstance(required_by, list) or any(
                not isinstance(item, str) for item in required_by
            ):
                raise PolicySurfaceViolationError(
                    "required_by_skills must be a string list"
                )
            skill_ids.extend(required_by)

        for skill_id in dict.fromkeys(skill_ids):
            cls._validate_reference(
                value=skill_id,
                allowed=policy_decision.allowed_skills,
                forbidden=policy_decision.forbidden_skills,
                label="skill",
            )

    @classmethod
    def _validate_tools(
        cls,
        draft: ActionPlanDraft,
        policy_decision: PolicyDecision,
    ) -> None:
        tool_ids: list[str] = [
            step.tool_requirement
            for step in draft.steps
            if step.tool_requirement is not None
        ]
        tool_plan = draft.tool_plan or {}
        calls = tool_plan.get("tool_calls", [])
        if not isinstance(calls, list):
            raise PolicySurfaceViolationError("tool_calls must be a list")
        for call in calls:
            if not isinstance(call, dict):
                raise PolicySurfaceViolationError(
                    "tool call plan must be an object"
                )
            tool_id = call.get("tool_id")
            if not isinstance(tool_id, str):
                raise PolicySurfaceViolationError(
                    "tool call tool_id must be text"
                )
            tool_ids.append(tool_id)

        for tool_id in dict.fromkeys(tool_ids):
            cls._validate_reference(
                value=tool_id,
                allowed=policy_decision.allowed_tools,
                forbidden=policy_decision.forbidden_tools,
                label="tool",
            )

    @staticmethod
    def _validate_forced_workflow_surface(
        draft: ActionPlanDraft,
        policy_decision: PolicyDecision,
    ) -> None:
        forced = policy_decision.forced_workflow
        if forced is None:
            return

        workflow_ids = {
            step.workflow_id
            for step in draft.steps
            if step.workflow_id is not None
        }
        capability = draft.capability_plan or {}
        selected = capability.get("selected_workflows", [])
        bindings = capability.get("bindings", [])
        if not isinstance(selected, list) or any(
            not isinstance(item, str) for item in selected
        ):
            raise PolicySurfaceViolationError(
                "capability selected_workflows must be a string list"
            )
        if not isinstance(bindings, list):
            raise PolicySurfaceViolationError(
                "capability bindings must be a list"
            )
        workflow_ids.update(selected)
        for binding in bindings:
            if not isinstance(binding, dict):
                raise PolicySurfaceViolationError(
                    "capability binding must be an object"
                )
            workflow_id = binding.get("workflow_id")
            if workflow_id is not None:
                if not isinstance(workflow_id, str):
                    raise PolicySurfaceViolationError(
                        "capability binding workflow_id must be text"
                    )
                workflow_ids.add(workflow_id)

        if forced not in workflow_ids:
            raise PolicySurfaceViolationError(
                "validated Draft does not contain M2 forced_workflow"
            )
        if workflow_ids - {forced}:
            raise PolicySurfaceViolationError(
                "Draft contains workflow outside M2 forced_workflow"
            )

    @staticmethod
    def _validate_confirmation(
        draft: ActionPlanDraft,
        policy_decision: PolicyDecision,
    ) -> None:
        if policy_decision.confirmation_required is not True:
            return
        confirmation = draft.confirmation_plan
        if not isinstance(confirmation, dict):
            raise PolicySurfaceViolationError(
                "M2 requires confirmation but Draft has no confirmation plan"
            )
        if confirmation.get("required") is not True:
            raise PolicySurfaceViolationError(
                "M2 confirmation_required requires confirmation_plan.required=true"
            )
        action_ids = confirmation.get("action_ids")
        if not isinstance(action_ids, list) or not action_ids:
            raise PolicySurfaceViolationError(
                "M2 confirmation_required requires explicit confirmation action_ids"
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
            raise PolicySurfaceViolationError(
                f"Draft uses forbidden {label}"
            )
        if allowed is not None and value not in allowed:
            raise PolicySurfaceViolationError(
                f"Draft uses {label} outside M2 allowed set"
            )


class PlanApprovalCoordinator:
    """Delegate sole approval authority to M2 PolicyRechecker."""

    _REQUIRED_VALIDATION_CODES = frozenset(
        {
            "DRAFT_STRUCTURE_VALID",
            "REGISTRY_REFERENCES_VALID",
            "KNOWLEDGE_PLAN_VALID",
        }
    )

    def __init__(
        self,
        *,
        policy_rechecker: PolicyRechecker,
        surface_auditor: M4PolicySurfaceAuditor | None = None,
    ) -> None:
        self._policy_rechecker = policy_rechecker
        self._surface_auditor = surface_auditor or M4PolicySurfaceAuditor()

    async def approve(
        self,
        validated: PlanValidationResult,
        policy_decision: PolicyDecision,
    ) -> PolicyApprovalResult:
        draft = validated.draft
        if draft.approval_status is not PlanApprovalStatus.DRAFT:
            raise ApprovalIntegrityError(
                "IU7 accepts only validated ActionPlanDraft"
            )
        if not self._REQUIRED_VALIDATION_CODES <= set(
            validated.validation_codes
        ):
            raise ApprovalIntegrityError(
                "IU7 requires successful IU6 validation codes"
            )

        audit_codes = self._surface_auditor.audit(draft, policy_decision)
        before_draft = draft.model_dump(mode="python")
        before_policy = policy_decision.model_dump(mode="python")

        approved = await self._policy_rechecker.recheck(
            draft,
            policy_decision,
        )

        if draft.model_dump(mode="python") != before_draft:
            raise ApprovalIntegrityError(
                "PolicyRechecker mutated ActionPlanDraft"
            )
        if policy_decision.model_dump(mode="python") != before_policy:
            raise ApprovalIntegrityError(
                "PolicyRechecker mutated PolicyDecision"
            )

        self._validate_approved_integrity(
            draft,
            approved,
            policy_decision,
        )
        return PolicyApprovalResult(
            approved_plan=approved,
            audit_codes=tuple(
                dict.fromkeys(
                    (
                        *validated.validation_codes,
                        *audit_codes,
                        "M2_POLICY_RECHECK_APPROVED",
                    )
                )
            ),
        )

    @staticmethod
    def _validate_approved_integrity(
        draft: ActionPlanDraft,
        approved: ApprovedActionPlan,
        policy_decision: PolicyDecision,
    ) -> None:
        if not isinstance(approved, ApprovedActionPlan):
            raise ApprovalIntegrityError(
                "PolicyRechecker must return ApprovedActionPlan"
            )
        if approved.approval_status is not PlanApprovalStatus.APPROVED:
            raise ApprovalIntegrityError(
                "PolicyRechecker output is not APPROVED"
            )

        draft_semantics = draft.model_dump(
            mode="python",
            exclude={"approval_status"},
        )
        approved_semantics = approved.model_dump(
            mode="python",
            exclude={
                "approval_status",
                "policy_snapshot",
                "approved_at",
            },
        )
        if approved_semantics != draft_semantics:
            raise ApprovalIntegrityError(
                "ApprovedActionPlan changed validated planning semantics"
            )

        expected_snapshot = policy_decision.model_dump(mode="json")
        if approved.policy_snapshot != expected_snapshot:
            raise ApprovalIntegrityError(
                "ApprovedActionPlan policy_snapshot does not match active M2 decision"
            )
