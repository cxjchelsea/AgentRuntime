"""M4-IU7 M2 Policy Re-check + ApprovedActionPlan integration gates."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from runtime.contracts import (
    ActionPlanDraft,
    ApprovedActionPlan,
    EvidenceRequirement,
    KnowledgeRequirement,
    PolicyDecision,
    RetrievalMode,
    RetrievalPlan,
)
from runtime.contracts.enums import PlanApprovalStatus
from runtime.interfaces.planning import PolicyRechecker
from runtime.planning import (
    ApprovalIntegrityError,
    M4PolicySurfaceAuditor,
    PlanApprovalCoordinator,
    PlanValidationResult,
    PolicySurfaceViolationError,
)
from runtime.policy_enforcement import (
    DefaultPolicyRechecker,
    PlanPolicyViolationError,
)
from tests.orchestration_stubs import (
    build_action_plan_draft,
    build_policy_decision,
)

_REQUIRED_CODES = (
    "DRAFT_STRUCTURE_VALID",
    "REGISTRY_REFERENCES_VALID",
    "KNOWLEDGE_PLAN_VALID",
)


def _validated(draft: ActionPlanDraft | None = None) -> PlanValidationResult:
    return PlanValidationResult(
        draft=draft or build_action_plan_draft(),
        validation_codes=_REQUIRED_CODES,
    )


def _policy(**updates: object) -> PolicyDecision:
    return build_policy_decision().model_copy(update=updates)


def _rich_draft() -> ActionPlanDraft:
    base = build_action_plan_draft()
    step = base.steps[0].model_copy(
        update={
            "skill_id": "DOMAIN_SKILL",
            "workflow_id": "DOMAIN_WORKFLOW",
            "tool_requirement": "DOMAIN_TOOL",
        }
    )
    return base.model_copy(
        update={
            "steps": [step],
            "knowledge_requirement": KnowledgeRequirement(
                required=True,
                reason="DOMAIN_REASON",
                domain="DOMAIN_KNOWLEDGE",
                query_target="domain query",
            ),
            "retrieval_plan": RetrievalPlan(
                required=True,
                domain="DOMAIN_KNOWLEDGE",
                query="domain query",
                retrieval_mode=RetrievalMode.HYBRID,
                minimum_evidence=2,
            ),
            "evidence_requirement": EvidenceRequirement(
                required=True,
                minimum_count=2,
            ),
            "memory_usage": {
                "use_memory": False,
                "memory_ids": [],
                "usage_mode": None,
                "reason": "NO_MEMORY_USAGE_RULE",
                "risk": None,
            },
            "capability_plan": {
                "bindings": [
                    {
                        "action_id": step.action,
                        "skill_id": "DOMAIN_SKILL",
                        "skill_version": "1.0.0",
                        "workflow_id": "DOMAIN_WORKFLOW",
                        "workflow_version": "1.0.0",
                    }
                ],
                "selected_skills": ["DOMAIN_SKILL"],
                "selected_workflows": ["DOMAIN_WORKFLOW"],
            },
            "tool_plan": {
                "tool_calls": [
                    {
                        "tool_id": "DOMAIN_TOOL",
                        "tool_version": "1.0.0",
                        "required": True,
                        "required_by_skills": ["DOMAIN_SKILL"],
                        "timeout_policy": None,
                        "retry_policy": None,
                        "idempotency_mode": None,
                        "side_effect_level": None,
                    }
                ],
                "parallelizable": False,
                "required_success": True,
            },
            "confirmation_plan": {
                "required": True,
                "action_ids": [step.action],
                "reason_codes": ["POLICY_CONFIRMATION_REQUIRED"],
            },
            "fallback_plan": {
                "mode": "FAIL_CLOSED",
                "allowed_actions": [],
                "reason_codes": ["NO_FALLBACK_RULE"],
            },
        }
    )


def test_real_m2_rechecker_is_the_only_approval_creator_and_preserves_plan() -> None:
    draft = _rich_draft()
    policy = _policy(
        allowed_actions=[draft.steps[0].action],
        allowed_skills=["DOMAIN_SKILL"],
        allowed_tools=["DOMAIN_TOOL"],
        forced_workflow="DOMAIN_WORKFLOW",
        confirmation_required=True,
    )
    approved_at = datetime(2026, 9, 20, 10, 45, tzinfo=UTC)
    coordinator = PlanApprovalCoordinator(
        policy_rechecker=DefaultPolicyRechecker(
            clock=lambda: approved_at,
        )
    )

    result = asyncio.run(coordinator.approve(_validated(draft), policy))

    assert isinstance(result.approved_plan, ApprovedActionPlan)
    assert result.approved_plan.approval_status is PlanApprovalStatus.APPROVED
    assert result.approved_plan.approved_at == approved_at
    assert draft.approval_status is PlanApprovalStatus.DRAFT
    assert result.approved_plan.knowledge_requirement == draft.knowledge_requirement
    assert result.approved_plan.retrieval_plan == draft.retrieval_plan
    assert result.approved_plan.evidence_requirement == draft.evidence_requirement
    assert result.approved_plan.capability_plan == draft.capability_plan
    assert result.approved_plan.tool_plan == draft.tool_plan
    # 审批不得改写 Draft 已冻结的 capability / tool version
    capability_plan = result.approved_plan.capability_plan
    tool_plan = result.approved_plan.tool_plan
    assert capability_plan is not None
    assert tool_plan is not None
    assert capability_plan["bindings"][0]["skill_version"] == "1.0.0"
    assert capability_plan["bindings"][0]["workflow_version"] == "1.0.0"
    assert tool_plan["tool_calls"][0]["tool_version"] == "1.0.0"
    assert result.approved_plan.policy_snapshot == policy.model_dump(mode="json")
    assert "M2_POLICY_RECHECK_APPROVED" in result.audit_codes


def test_iu7_requires_successful_iu6_validation_codes() -> None:
    validated = PlanValidationResult(
        draft=build_action_plan_draft(),
        validation_codes=("DRAFT_STRUCTURE_VALID",),
    )

    with pytest.raises(ApprovalIntegrityError):
        asyncio.run(
            PlanApprovalCoordinator(policy_rechecker=DefaultPolicyRechecker()).approve(
                validated, _policy()
            )
        )


def test_blocked_policy_still_fails_in_m2_rechecker() -> None:
    with pytest.raises(PlanPolicyViolationError):
        asyncio.run(
            PlanApprovalCoordinator(policy_rechecker=DefaultPolicyRechecker()).approve(
                _validated(),
                _policy(allowed=False, blocked=True),
            )
        )


def test_policy_surface_audit_catches_tool_hidden_outside_step_requirement() -> None:
    base = build_action_plan_draft()
    draft = base.model_copy(
        update={
            "capability_plan": {
                "bindings": [
                    {
                        "action_id": base.steps[0].action,
                        "skill_id": "DOMAIN_SKILL",
                        "workflow_id": None,
                    }
                ],
                "selected_skills": ["DOMAIN_SKILL"],
                "selected_workflows": [],
            },
            "tool_plan": {
                "tool_calls": [
                    {
                        "tool_id": "HIDDEN_TOOL",
                        "required": False,
                        "required_by_skills": [],
                    }
                ],
                "parallelizable": False,
                "required_success": False,
            },
            "confirmation_plan": {
                "required": False,
                "action_ids": [],
                "reason_codes": [],
            },
            "fallback_plan": {
                "mode": "FAIL_CLOSED",
                "allowed_actions": [],
                "reason_codes": [],
            },
        }
    )

    with pytest.raises(PolicySurfaceViolationError, match="tool"):
        asyncio.run(
            PlanApprovalCoordinator(policy_rechecker=DefaultPolicyRechecker()).approve(
                _validated(draft),
                _policy(forbidden_tools=["HIDDEN_TOOL"]),
            )
        )


def test_policy_surface_audit_catches_skill_hidden_in_capability_plan() -> None:
    base = build_action_plan_draft()
    draft = base.model_copy(
        update={
            "capability_plan": {
                "bindings": [
                    {
                        "action_id": base.steps[0].action,
                        "skill_id": "HIDDEN_SKILL",
                        "workflow_id": None,
                    }
                ],
                "selected_skills": ["HIDDEN_SKILL"],
                "selected_workflows": [],
            },
            "tool_plan": {
                "tool_calls": [],
                "parallelizable": False,
                "required_success": False,
            },
            "confirmation_plan": {
                "required": False,
                "action_ids": [],
                "reason_codes": [],
            },
            "fallback_plan": {
                "mode": "FAIL_CLOSED",
                "allowed_actions": [],
                "reason_codes": [],
            },
        }
    )

    with pytest.raises(PolicySurfaceViolationError, match="skill"):
        asyncio.run(
            PlanApprovalCoordinator(policy_rechecker=DefaultPolicyRechecker()).approve(
                _validated(draft),
                _policy(forbidden_skills=["HIDDEN_SKILL"]),
            )
        )


def test_policy_surface_audit_catches_forbidden_fallback_action() -> None:
    base = build_action_plan_draft()
    draft = base.model_copy(
        update={
            "capability_plan": {
                "bindings": [
                    {
                        "action_id": base.steps[0].action,
                        "skill_id": None,
                        "workflow_id": None,
                    }
                ],
                "selected_skills": [],
                "selected_workflows": [],
            },
            "tool_plan": {
                "tool_calls": [],
                "parallelizable": False,
                "required_success": False,
            },
            "confirmation_plan": {
                "required": False,
                "action_ids": [],
                "reason_codes": [],
            },
            "fallback_plan": {
                "mode": "DOMAIN_FALLBACK",
                "allowed_actions": ["FORBIDDEN_FALLBACK"],
                "reason_codes": ["DOMAIN_REASON"],
            },
        }
    )

    with pytest.raises(PolicySurfaceViolationError, match="action"):
        asyncio.run(
            PlanApprovalCoordinator(policy_rechecker=DefaultPolicyRechecker()).approve(
                _validated(draft),
                _policy(forbidden_actions=["FORBIDDEN_FALLBACK"]),
            )
        )


def test_policy_confirmation_requires_required_true_not_merely_truthy_dict() -> None:
    base = build_action_plan_draft()
    draft = base.model_copy(
        update={
            "capability_plan": {
                "bindings": [
                    {
                        "action_id": base.steps[0].action,
                        "skill_id": None,
                        "workflow_id": None,
                    }
                ],
                "selected_skills": [],
                "selected_workflows": [],
            },
            "tool_plan": {
                "tool_calls": [],
                "parallelizable": False,
                "required_success": False,
            },
            "confirmation_plan": {
                "required": False,
                "action_ids": [],
                "reason_codes": [],
            },
            "fallback_plan": {
                "mode": "FAIL_CLOSED",
                "allowed_actions": [],
                "reason_codes": [],
            },
        }
    )

    with pytest.raises(PolicySurfaceViolationError, match="required=true"):
        asyncio.run(
            PlanApprovalCoordinator(policy_rechecker=DefaultPolicyRechecker()).approve(
                _validated(draft),
                _policy(confirmation_required=True),
            )
        )


def test_forced_workflow_cannot_be_bypassed_in_capability_subplan() -> None:
    base = build_action_plan_draft()
    forced_step = base.steps[0].model_copy(update={"workflow_id": "WF_FORCED"})
    draft = base.model_copy(
        update={
            "steps": [forced_step],
            "capability_plan": {
                "bindings": [
                    {
                        "action_id": forced_step.action,
                        "skill_id": None,
                        "workflow_id": "WF_OTHER",
                    }
                ],
                "selected_skills": [],
                "selected_workflows": ["WF_OTHER"],
            },
            "tool_plan": {
                "tool_calls": [],
                "parallelizable": False,
                "required_success": False,
            },
            "confirmation_plan": {
                "required": False,
                "action_ids": [],
                "reason_codes": [],
            },
            "fallback_plan": {
                "mode": "FAIL_CLOSED",
                "allowed_actions": [],
                "reason_codes": [],
            },
        }
    )

    with pytest.raises(PolicySurfaceViolationError, match="outside"):
        asyncio.run(
            PlanApprovalCoordinator(policy_rechecker=DefaultPolicyRechecker()).approve(
                _validated(draft),
                _policy(forced_workflow="WF_FORCED"),
            )
        )


@dataclass(frozen=True)
class DomainApprovalRule:
    reject: bool = False

    def validate(
        self,
        draft: ActionPlanDraft,
        policy_decision: PolicyDecision,
    ) -> str | None:
        del draft, policy_decision
        if self.reject:
            raise PolicySurfaceViolationError("DOMAIN_POLICY_REJECT")
        return "DOMAIN_POLICY_SURFACE_VALID"


def test_injected_policy_rule_can_reject_or_add_audit_code_but_not_approve() -> None:
    draft = build_action_plan_draft()
    auditor = M4PolicySurfaceAuditor(rules=(DomainApprovalRule(),))
    result = asyncio.run(
        PlanApprovalCoordinator(
            policy_rechecker=DefaultPolicyRechecker(),
            surface_auditor=auditor,
        ).approve(_validated(draft), _policy())
    )
    assert "DOMAIN_POLICY_SURFACE_VALID" in result.audit_codes
    assert result.approved_plan.approval_status is PlanApprovalStatus.APPROVED

    rejecting = M4PolicySurfaceAuditor(rules=(DomainApprovalRule(reject=True),))
    with pytest.raises(PolicySurfaceViolationError):
        asyncio.run(
            PlanApprovalCoordinator(
                policy_rechecker=DefaultPolicyRechecker(),
                surface_auditor=rejecting,
            ).approve(_validated(draft), _policy())
        )


class MutatingApprovalRechecker(PolicyRechecker):
    async def recheck(
        self,
        action_plan_draft: ActionPlanDraft,
        policy_decision: PolicyDecision,
    ) -> ApprovedActionPlan:
        payload = action_plan_draft.model_dump(
            mode="python",
            exclude={"approval_status"},
        )
        payload["fallback_plan"] = {
            "mode": "CHANGED",
            "allowed_actions": [],
            "reason_codes": [],
        }
        return ApprovedActionPlan(
            **payload,
            policy_snapshot=policy_decision.model_dump(mode="json"),
        )


def test_approved_plan_cannot_drift_from_validated_draft() -> None:
    with pytest.raises(ApprovalIntegrityError, match="changed"):
        asyncio.run(
            PlanApprovalCoordinator(
                policy_rechecker=MutatingApprovalRechecker()
            ).approve(_validated(), _policy())
        )


class WrongSnapshotRechecker(PolicyRechecker):
    async def recheck(
        self,
        action_plan_draft: ActionPlanDraft,
        policy_decision: PolicyDecision,
    ) -> ApprovedActionPlan:
        del policy_decision
        payload = action_plan_draft.model_dump(
            mode="python",
            exclude={"approval_status"},
        )
        return ApprovedActionPlan(
            **payload,
            policy_snapshot={"policy_decision_id": "WRONG"},
        )


def test_approved_plan_must_snapshot_the_active_policy_decision() -> None:
    with pytest.raises(ApprovalIntegrityError, match="policy_snapshot"):
        asyncio.run(
            PlanApprovalCoordinator(policy_rechecker=WrongSnapshotRechecker()).approve(
                _validated(), _policy()
            )
        )
