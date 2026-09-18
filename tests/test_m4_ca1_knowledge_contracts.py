"""M4-CA1 Knowledge Planning Contract Amendment gates."""

from __future__ import annotations

import inspect

import runtime.contracts as contracts_module
from runtime.contracts import (
    SCHEMA_VERSION,
    ActionPlanDraft,
    ApprovedActionPlan,
    EvidenceRequirement,
    KnowledgeRequirement,
    RetrievalMode,
    RetrievalPlan,
)
from runtime.contracts.common import QualityAssessment
from runtime.contracts.enums import PlanApprovalStatus, PlanningMode
from runtime.contracts.planning import ActionStep, PlanningGoal
from runtime.interfaces.execution import ExecutionEngine
from runtime.planning import RetrievalQuery


def _draft_payload(*, schema_version: str) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "plan_id": "plan-ca1",
        "request_id": "request-ca1",
        "approval_status": PlanApprovalStatus.DRAFT,
        "planning_mode": PlanningMode.AGENT_PLANNED,
        "goals": [{"goal_id": "goal-ca1"}],
        "steps": [{"step_id": "step-ca1", "action": "DOMAIN_ACTION"}],
        "quality": {},
    }


def _approved_payload(*, schema_version: str) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "plan_id": "plan-ca1",
        "request_id": "request-ca1",
        "approval_status": PlanApprovalStatus.APPROVED,
        "planning_mode": PlanningMode.AGENT_PLANNED,
        "goals": [{"goal_id": "goal-ca1"}],
        "steps": [{"step_id": "step-ca1", "action": "DOMAIN_ACTION"}],
        "policy_snapshot": {"allowed": True},
        "quality": {},
    }


def test_global_schema_version_is_not_bumped_by_m4_ca1() -> None:
    assert SCHEMA_VERSION == "1.0.0"


def test_new_planning_contract_instances_default_to_1_1_0() -> None:
    draft = ActionPlanDraft(
        plan_id="plan-ca1",
        request_id="request-ca1",
        planning_mode=PlanningMode.AGENT_PLANNED,
        goals=[PlanningGoal(goal_id="goal-ca1")],
        steps=[ActionStep(step_id="step-ca1", action="DOMAIN_ACTION")],
        quality=QualityAssessment(),
    )
    approved = ApprovedActionPlan(
        plan_id="plan-ca1",
        request_id="request-ca1",
        planning_mode=PlanningMode.AGENT_PLANNED,
        goals=[PlanningGoal(goal_id="goal-ca1")],
        steps=[ActionStep(step_id="step-ca1", action="DOMAIN_ACTION")],
        policy_snapshot={"allowed": True},
        quality=QualityAssessment(),
    )

    assert draft.schema_version == "1.1.0"
    assert approved.schema_version == "1.1.0"


def test_old_1_0_0_planning_payloads_remain_parseable() -> None:
    draft = ActionPlanDraft.model_validate(_draft_payload(schema_version="1.0.0"))
    approved = ApprovedActionPlan.model_validate(
        _approved_payload(schema_version="1.0.0")
    )

    assert draft.schema_version == "1.0.0"
    assert approved.schema_version == "1.0.0"
    assert draft.knowledge_requirement is None
    assert draft.retrieval_plan is None
    assert draft.evidence_requirement is None
    assert approved.knowledge_requirement is None
    assert approved.retrieval_plan is None
    assert approved.evidence_requirement is None


def test_draft_and_approved_have_the_same_three_knowledge_fields() -> None:
    field_names = {
        "knowledge_requirement",
        "retrieval_plan",
        "evidence_requirement",
    }

    assert field_names <= set(ActionPlanDraft.model_fields)
    assert field_names <= set(ApprovedActionPlan.model_fields)


def test_no_knowledge_requirement_can_exist_without_retrieval_plan() -> None:
    draft = ActionPlanDraft(
        plan_id="plan-no-knowledge",
        request_id="request-ca1",
        planning_mode=PlanningMode.DETERMINISTIC,
        goals=[PlanningGoal(goal_id="goal-ca1")],
        steps=[ActionStep(step_id="step-ca1", action="DOMAIN_ACTION")],
        quality=QualityAssessment(),
        knowledge_requirement=KnowledgeRequirement(required=False),
    )

    assert draft.knowledge_requirement is not None
    assert draft.knowledge_requirement.required is False
    assert draft.retrieval_plan is None
    assert draft.evidence_requirement is None


def test_required_knowledge_plan_is_representable_as_typed_fields() -> None:
    requirement = KnowledgeRequirement(
        required=True,
        reason="DOMAIN_REASON",
        domain="DOMAIN_CUSTOM",
        knowledge_type="DOMAIN_KNOWLEDGE_TYPE",
        query_target="DOMAIN_QUERY_TARGET",
        source_constraints=["DOMAIN_APPROVED_SOURCE"],
        freshness_requirement="DOMAIN_FRESHNESS",
        evidence_level="DOMAIN_EVIDENCE_LEVEL",
        population="DOMAIN_POPULATION",
        scenario="DOMAIN_SCENARIO",
        safety_level="DOMAIN_SAFETY_LEVEL",
    )
    retrieval = RetrievalPlan(
        required=True,
        domain="DOMAIN_CUSTOM",
        query="domain query",
        query_variants=["domain query variant"],
        retrieval_mode=RetrievalMode.HYBRID,
        filters={"status": "DOMAIN_ACTIVE"},
        source_policy="DOMAIN_SOURCE_POLICY",
        vector_top_k=20,
        sparse_top_k=20,
        merge_policy="DOMAIN_MERGE_POLICY",
        rerank_enabled=True,
        rerank_top_n=5,
        freshness_requirement="DOMAIN_FRESHNESS",
        minimum_evidence=2,
        fallback_policy="DOMAIN_FALLBACK",
    )
    evidence = EvidenceRequirement(
        required=True,
        minimum_count=2,
        minimum_trust="DOMAIN_TRUST",
        freshness_required=True,
        source_diversity_required=True,
        conflict_check_required=True,
        citation_required=True,
    )

    draft = ActionPlanDraft(
        plan_id="plan-knowledge",
        request_id="request-ca1",
        planning_mode=PlanningMode.AGENT_PLANNED,
        goals=[PlanningGoal(goal_id="goal-ca1")],
        steps=[ActionStep(step_id="step-ca1", action="DOMAIN_ACTION")],
        quality=QualityAssessment(),
        knowledge_requirement=requirement,
        retrieval_plan=retrieval,
        evidence_requirement=evidence,
    )

    assert draft.knowledge_requirement == requirement
    assert draft.retrieval_plan == retrieval
    assert draft.evidence_requirement == evidence


def test_retrieval_mode_is_structural_and_domain_values_remain_strings() -> None:
    assert {mode.value for mode in RetrievalMode} == {
        "VECTOR",
        "KEYWORD",
        "HYBRID",
        "STRUCTURED_LOOKUP",
        "EXTERNAL_API",
        "NONE",
    }

    requirement = KnowledgeRequirement(
        required=True,
        domain="UNREGISTERED_DOMAIN_EXAMPLE",
        knowledge_type="UNREGISTERED_TYPE_EXAMPLE",
        population="UNREGISTERED_POPULATION_EXAMPLE",
        scenario="UNREGISTERED_SCENARIO_EXAMPLE",
        safety_level="UNREGISTERED_SAFETY_LEVEL_EXAMPLE",
    )
    assert requirement.domain == "UNREGISTERED_DOMAIN_EXAMPLE"


def test_retrieval_query_is_internal_not_a_canonical_action_plan_field() -> None:
    query = RetrievalQuery(
        original_query="raw query",
        normalized_query="normalized query",
        query_variants=["variant"],
        entities=[{"type": "DOMAIN_ENTITY", "value": "x"}],
        topics=["DOMAIN_TOPIC"],
        temporal_constraints={"window": "DOMAIN_WINDOW"},
        population="DOMAIN_POPULATION",
        domain="DOMAIN_CUSTOM",
        scenario="DOMAIN_SCENARIO",
    )

    assert query.original_query == "raw query"
    assert "RetrievalQuery" not in contracts_module.__all__
    assert "retrieval_query" not in ActionPlanDraft.model_fields
    assert "retrieval_query" not in ApprovedActionPlan.model_fields


def test_knowledge_semantics_are_explicit_not_hidden_in_legacy_dict_fields() -> None:
    assert "knowledge_requirement" in ActionPlanDraft.model_fields
    assert "retrieval_plan" in ActionPlanDraft.model_fields
    assert "evidence_requirement" in ActionPlanDraft.model_fields

    for legacy_field in ("capability_plan", "tool_plan", "trace"):
        assert legacy_field in ActionPlanDraft.model_fields


def test_action_plan_name_remains_forbidden() -> None:
    assert "ActionPlan" not in contracts_module.__all__
    assert "ActionPlanDraft" in contracts_module.__all__
    assert "ApprovedActionPlan" in contracts_module.__all__


def test_m5_execution_interface_still_only_accepts_approved_action_plan() -> None:
    signature = inspect.signature(ExecutionEngine.execute)

    assert tuple(signature.parameters) == (
        "self",
        "approved_action_plan",
        "runtime_context",
    )
    assert signature.parameters["approved_action_plan"].annotation in {
        "ApprovedActionPlan",
        ApprovedActionPlan,
    }


def test_evidence_requirement_is_not_an_evidence_result_type() -> None:
    names = set(EvidenceRequirement.model_fields)

    assert "minimum_count" in names
    assert "minimum_trust" in names
    assert "content" not in names
    assert "verified_fact" not in names
    assert "claims" not in names
