"""M5 workflow execution-authority projection.

There is no generic PolicyDecision.allowed_workflows / forbidden_workflows contract.
Workflow execution authority therefore comes from the already-approved plan, plus the
existing M2 forced_workflow constraint captured in policy_snapshot, plus runtime
Registry/eligibility/permission checks performed by later M5 components.
"""

from __future__ import annotations

from dataclasses import dataclass

from runtime.contracts import ApprovedActionPlan


@dataclass(frozen=True, slots=True)
class ApprovedWorkflowAuthority:
    approved_workflow_ids: frozenset[str]
    forced_workflow: str | None

    def __post_init__(self) -> None:
        if any(not workflow_id.strip() for workflow_id in self.approved_workflow_ids):
            raise ValueError("approved_workflow_ids must not contain blank values")
        if self.forced_workflow is not None and not self.forced_workflow.strip():
            raise ValueError("forced_workflow must not be blank")


def project_workflow_authority(
    approved_plan: ApprovedActionPlan,
) -> ApprovedWorkflowAuthority:
    workflow_ids = frozenset(
        step.workflow_id for step in approved_plan.steps if step.workflow_id is not None
    )
    forced_workflow = approved_plan.policy_snapshot.get("forced_workflow")
    if forced_workflow is not None and not isinstance(forced_workflow, str):
        raise TypeError("policy_snapshot.forced_workflow must be text or null")

    if forced_workflow is not None:
        if forced_workflow not in workflow_ids:
            raise ValueError("approved plan lost the M2 forced_workflow reference")
        if workflow_ids - {forced_workflow}:
            raise ValueError("approved plan contains workflow outside forced_workflow")

    return ApprovedWorkflowAuthority(
        approved_workflow_ids=workflow_ids,
        forced_workflow=forced_workflow,
    )
