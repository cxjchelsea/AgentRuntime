"""M4-IU6 ActionPlanDraft assembly and validation gates."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from runtime.contracts import (
    ActionPlanDraft,
    EvidenceRequirement,
    KnowledgeRequirement,
    QualityAssessment,
    RetrievalMode,
    RetrievalPlan,
)
from runtime.contracts.enums import PlanningMode
from runtime.contracts.planning import ActionStep, PlanningGoal, StrategySelection
from runtime.planning import (
    ActionPlanDraftAssembler,
    CapabilityBinding,
    CapabilitySelection,
    ConfirmationDecision,
    DraftAssemblyError,
    ExecutionPreplanningResult,
    FallbackDecision,
    KnowledgeCapabilityContext,
    KnowledgePlanningResult,
    MemoryUsageDecision,
    PlanValidationContext,
    PlanValidationError,
    PlanValidator,
    ResponseStrategyBuilder,
    ResponseStrategyDecision,
    SequencePlan,
    StrategySelectionResult,
    ToolCallPlan,
    ToolPlanDecision,
)
from runtime.planning.goals import GoalResolutionResult
from runtime.registries import (
    ActionDefinition,
    ActionRegistry,
    IntrusivenessLevel,
    SkillDefinition,
    SkillRegistry,
    StrategyDefinition,
    StrategyRegistry,
    ToolDefinition,
    ToolRegistry,
    WorkflowDefinition,
    WorkflowRegistry,
)


def _action(
    action_id: str,
    *,
    requires_confirmation: bool = False,
) -> ActionDefinition:
    return ActionDefinition(
        action_id=action_id,
        version="1.0.0",
        category="DOMAIN_CATEGORY",
        description="domain action",
        intrusiveness_level=IntrusivenessLevel.LOW,
        requires_confirmation=requires_confirmation,
        required_capability=None,
        allowed_planning_modes=[PlanningMode.AGENT_PLANNED],
    )


def _registries() -> tuple[
    ActionRegistry,
    StrategyRegistry,
    SkillRegistry,
    WorkflowRegistry,
    ToolRegistry,
]:
    actions = ActionRegistry()
    actions.register(_action("DOMAIN_ACTION"))
    actions.register(_action("DOMAIN_FALLBACK"))

    strategies = StrategyRegistry()
    strategies.register(
        StrategyDefinition(
            strategy_id="DOMAIN_STRATEGY",
            version="1.0.0",
            description="domain strategy",
            preferred_goals=[],
            preferred_needs=[],
            compatible_emotions=[],
            required_conditions=[],
            avoid_conditions=[],
            default_actions=["DOMAIN_ACTION"],
            intrusiveness_level=IntrusivenessLevel.LOW,
        )
    )

    skills = SkillRegistry()
    skills.register(
        SkillDefinition(
            skill_id="DOMAIN_SKILL",
            version="1.0.0",
            supported_actions=["DOMAIN_ACTION"],
            required_tools=["DOMAIN_TOOL"],
        )
    )

    workflows = WorkflowRegistry()
    workflows.register(
        WorkflowDefinition(
            workflow_id="DOMAIN_WORKFLOW",
            version="1.0.0",
        )
    )

    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            tool_id="DOMAIN_TOOL",
            version="1.0.0",
        )
    )
    return actions, strategies, skills, workflows, tools


def _goals() -> GoalResolutionResult:
    primary = PlanningGoal(
        goal_id="DOMAIN_GOAL",
        goal_type="DOMAIN_GOAL",
        primary=True,
        goal_source="EXPLICIT_USER_GOAL",
        goal_priority=400,
        completion_condition="DOMAIN_DONE",
    )
    return GoalResolutionResult(
        primary_goal=primary,
        secondary_goals=(),
        candidates=(),
    )


def _strategy(
    *,
    selected_action_ids: tuple[str, ...] = ("DOMAIN_ACTION",),
) -> StrategySelectionResult:
    return StrategySelectionResult(
        strategy=StrategySelection(
            strategy_id="DOMAIN_STRATEGY",
            reason_code="DOMAIN_REASON",
            confidence=1.0,
        ),
        selected_action_ids=selected_action_ids,
        selection_path="RULE",
    )


def _preplanning() -> ExecutionPreplanningResult:
    return ExecutionPreplanningResult(
        memory_usage=MemoryUsageDecision(
            use_memory=False,
            reason="NO_MEMORY_USAGE_RULE",
        ),
        capability_selection=CapabilitySelection(
            bindings=(
                CapabilityBinding(
                    action_id="DOMAIN_ACTION",
                    skill_id="DOMAIN_SKILL",
                    skill_version="1.0.0",
                ),
            ),
            selected_skills=("DOMAIN_SKILL",),
            selected_workflows=(),
        ),
        tool_plan=ToolPlanDecision(
            tool_calls=(
                ToolCallPlan(
                    tool_id="DOMAIN_TOOL",
                    tool_version="1.0.0",
                    required=True,
                    required_by_skills=("DOMAIN_SKILL",),
                    timeout_policy=None,
                    retry_policy=None,
                    idempotency_mode=None,
                    side_effect_level=None,
                ),
            ),
            parallelizable=False,
            required_success=True,
        ),
        confirmation=ConfirmationDecision(
            required=False,
            action_ids=(),
            reason_codes=(),
        ),
        sequence=SequencePlan(
            steps=(
                ActionStep(
                    step_id="step-1",
                    action="DOMAIN_ACTION",
                    skill_id="DOMAIN_SKILL",
                    tool_requirement="DOMAIN_TOOL",
                ),
            )
        ),
        stop_conditions=("DOMAIN_DONE",),
        fallback=FallbackDecision(
            mode="FAIL_CLOSED",
            allowed_actions=(),
            reason_codes=("NO_FALLBACK_RULE",),
        ),
    )


def _no_knowledge() -> KnowledgePlanningResult:
    return KnowledgePlanningResult(
        knowledge_requirement=KnowledgeRequirement(
            required=False,
            reason="NO_KNOWLEDGE_REQUIREMENT_SIGNAL",
        ),
        retrieval_query=None,
        retrieval_plan=None,
        evidence_requirement=None,
    )


def _knowledge() -> KnowledgePlanningResult:
    return KnowledgePlanningResult(
        knowledge_requirement=KnowledgeRequirement(
            required=True,
            reason="DOMAIN_KNOWLEDGE_REQUIRED",
            domain="DOMAIN_KNOWLEDGE",
            query_target="domain query",
        ),
        retrieval_query=None,
        retrieval_plan=RetrievalPlan(
            required=True,
            domain="DOMAIN_KNOWLEDGE",
            query="domain query",
            retrieval_mode=RetrievalMode.HYBRID,
            filters={"domain": "DOMAIN_KNOWLEDGE"},
            minimum_evidence=2,
        ),
        evidence_requirement=EvidenceRequirement(
            required=True,
            minimum_count=2,
        ),
    )


def _validation_context(
    *,
    knowledge_skill_ids: frozenset[str] = frozenset(),
) -> PlanValidationContext:
    actions, strategies, skills, workflows, tools = _registries()
    return PlanValidationContext(
        action_registry=actions,
        strategy_registry=strategies,
        skill_registry=skills,
        workflow_registry=workflows,
        tool_registry=tools,
        knowledge_capabilities=KnowledgeCapabilityContext(
            available_domains=frozenset({"DOMAIN_KNOWLEDGE"}),
            supported_retrieval_modes=frozenset({RetrievalMode.HYBRID}),
            supported_filters=frozenset({"domain"}),
            default_retrieval_mode=RetrievalMode.HYBRID,
        ),
        knowledge_skill_ids=knowledge_skill_ids,
    )


def test_assembler_projects_prior_m4_results_into_canonical_draft() -> None:
    draft = ActionPlanDraftAssembler().build(
        plan_id="plan-iu6",
        request_id="request-iu6",
        planning_mode=PlanningMode.AGENT_PLANNED,
        goals=_goals(),
        strategy=_strategy(),
        knowledge_planning=_no_knowledge(),
        execution_preplanning=_preplanning(),
        response_strategy=ResponseStrategyDecision(
            communicative_goal="DOMAIN_GOAL",
            tone="DOMAIN_TONE",
            content_order=("DOMAIN_CONTENT",),
        ),
        quality=QualityAssessment(),
    )

    assert draft.approval_status.value == "DRAFT"
    assert draft.schema_version == "1.1.0"
    assert [goal.goal_id for goal in draft.goals] == ["DOMAIN_GOAL"]
    assert draft.strategy is not None
    assert draft.strategy.strategy_id == "DOMAIN_STRATEGY"
    assert [step.action for step in draft.steps] == ["DOMAIN_ACTION"]
    assert draft.memory_usage == {
        "use_memory": False,
        "memory_ids": [],
        "usage_mode": None,
        "reason": "NO_MEMORY_USAGE_RULE",
        "risk": None,
    }
    assert draft.capability_plan is not None
    assert draft.capability_plan["bindings"][0]["skill_version"] == "1.0.0"
    assert draft.tool_plan is not None
    assert draft.tool_plan["tool_calls"][0]["tool_version"] == "1.0.0"
    assert draft.confirmation_plan is not None
    assert draft.fallback_plan is not None
    assert draft.stop_conditions == ["DOMAIN_DONE"]
    assert draft.response_strategy is not None
    assert draft.response_strategy["tone"] == "DOMAIN_TONE"


def test_assembler_rejects_strategy_step_action_drift() -> None:
    with pytest.raises(DraftAssemblyError):
        ActionPlanDraftAssembler().build(
            plan_id="plan-iu6",
            request_id="request-iu6",
            planning_mode=PlanningMode.AGENT_PLANNED,
            goals=_goals(),
            strategy=_strategy(selected_action_ids=("OTHER_ACTION",)),
            knowledge_planning=_no_knowledge(),
            execution_preplanning=_preplanning(),
            response_strategy=None,
        )


@dataclass(frozen=True)
class StaticResponseRule:
    decision: ResponseStrategyDecision | None

    def plan(
        self,
        strategy: StrategySelectionResult,
        execution_preplanning: ExecutionPreplanningResult,
        knowledge_planning: KnowledgePlanningResult,
    ) -> ResponseStrategyDecision | None:
        del strategy, execution_preplanning, knowledge_planning
        return self.decision


def test_response_strategy_builder_is_rule_driven_and_generates_no_text() -> None:
    builder = ResponseStrategyBuilder(
        rules=(
            StaticResponseRule(
                ResponseStrategyDecision(
                    communicative_goal="DOMAIN_COMMUNICATIVE_GOAL",
                    tone="DOMAIN_TONE",
                    length="DOMAIN_LENGTH",
                )
            ),
        )
    )

    result = builder.build(_strategy(), _preplanning(), _no_knowledge())

    assert result is not None
    assert result.communicative_goal == "DOMAIN_COMMUNICATIVE_GOAL"
    assert not hasattr(result, "text")
    assert not hasattr(result, "content")


def test_validator_accepts_structurally_valid_nonknowledge_draft() -> None:
    draft = ActionPlanDraftAssembler().build(
        plan_id="plan-iu6",
        request_id="request-iu6",
        planning_mode=PlanningMode.AGENT_PLANNED,
        goals=_goals(),
        strategy=_strategy(),
        knowledge_planning=_no_knowledge(),
        execution_preplanning=_preplanning(),
        response_strategy=None,
    )

    result = PlanValidator().validate(draft, _validation_context())

    assert result.draft is draft
    assert "DRAFT_STRUCTURE_VALID" in result.validation_codes
    assert draft.approval_status.value == "DRAFT"


def test_validator_rejects_unpinned_or_drifted_capability_versions() -> None:
    draft = ActionPlanDraftAssembler().build(
        plan_id="plan-iu6",
        request_id="request-iu6",
        planning_mode=PlanningMode.AGENT_PLANNED,
        goals=_goals(),
        strategy=_strategy(),
        knowledge_planning=_no_knowledge(),
        execution_preplanning=_preplanning(),
        response_strategy=None,
    )

    capability = dict(draft.capability_plan or {})
    bindings = [dict(item) for item in capability["bindings"]]
    bindings[0]["skill_version"] = "2.0.0"
    capability["bindings"] = bindings
    invalid_skill = draft.model_copy(update={"capability_plan": capability})

    with pytest.raises(PlanValidationError, match="Skill pinned id/version"):
        PlanValidator().validate(invalid_skill, _validation_context())

    tool_plan = dict(draft.tool_plan or {})
    calls = [dict(item) for item in tool_plan["tool_calls"]]
    calls[0]["tool_version"] = "2.0.0"
    tool_plan["tool_calls"] = calls
    invalid_tool = draft.model_copy(update={"tool_plan": tool_plan})

    with pytest.raises(PlanValidationError, match="Tool pinned id/version"):
        PlanValidator().validate(invalid_tool, _validation_context())


def test_validator_rejects_workflow_version_drift() -> None:
    draft = ActionPlanDraftAssembler().build(
        plan_id="plan-iu6",
        request_id="request-iu6",
        planning_mode=PlanningMode.AGENT_PLANNED,
        goals=_goals(),
        strategy=_strategy(),
        knowledge_planning=_no_knowledge(),
        execution_preplanning=_preplanning(),
        response_strategy=None,
    )
    step = draft.steps[0].model_copy(update={"workflow_id": "DOMAIN_WORKFLOW"})
    capability = dict(draft.capability_plan or {})
    bindings = [dict(item) for item in capability["bindings"]]
    bindings[0]["workflow_id"] = "DOMAIN_WORKFLOW"
    bindings[0]["workflow_version"] = "2.0.0"
    capability["bindings"] = bindings
    capability["selected_workflows"] = ["DOMAIN_WORKFLOW"]
    invalid = draft.model_copy(
        update={"steps": [step], "capability_plan": capability}
    )

    with pytest.raises(PlanValidationError, match="Workflow pinned id/version"):
        PlanValidator().validate(invalid, _validation_context())


def test_validator_rejects_missing_capability_version_pin() -> None:
    draft = ActionPlanDraftAssembler().build(
        plan_id="plan-iu6",
        request_id="request-iu6",
        planning_mode=PlanningMode.AGENT_PLANNED,
        goals=_goals(),
        strategy=_strategy(),
        knowledge_planning=_no_knowledge(),
        execution_preplanning=_preplanning(),
        response_strategy=None,
    )
    capability = dict(draft.capability_plan or {})
    bindings = [dict(item) for item in capability["bindings"]]
    bindings[0].pop("skill_version")
    capability["bindings"] = bindings
    invalid = draft.model_copy(update={"capability_plan": capability})

    with pytest.raises(PlanValidationError, match="pinned skill_version"):
        PlanValidator().validate(invalid, _validation_context())


def test_validator_requires_exactly_one_primary_goal() -> None:
    draft = ActionPlanDraftAssembler().build(
        plan_id="plan-iu6",
        request_id="request-iu6",
        planning_mode=PlanningMode.AGENT_PLANNED,
        goals=_goals(),
        strategy=_strategy(),
        knowledge_planning=_no_knowledge(),
        execution_preplanning=_preplanning(),
        response_strategy=None,
    )
    invalid = draft.model_copy(
        update={
            "goals": [
                draft.goals[0].model_copy(update={"primary": False}),
            ]
        }
    )

    with pytest.raises(PlanValidationError):
        PlanValidator().validate(invalid, _validation_context())


def test_validator_rejects_step_dependency_on_future_or_missing_step() -> None:
    draft = ActionPlanDraftAssembler().build(
        plan_id="plan-iu6",
        request_id="request-iu6",
        planning_mode=PlanningMode.AGENT_PLANNED,
        goals=_goals(),
        strategy=_strategy(),
        knowledge_planning=_no_knowledge(),
        execution_preplanning=_preplanning(),
        response_strategy=None,
    )
    invalid_step = draft.steps[0].model_copy(update={"depends_on": ["step-2"]})
    invalid = draft.model_copy(update={"steps": [invalid_step]})

    with pytest.raises(PlanValidationError):
        PlanValidator().validate(invalid, _validation_context())


def test_validator_rejects_action_incompatible_with_planning_mode() -> None:
    draft = ActionPlanDraftAssembler().build(
        plan_id="plan-iu6",
        request_id="request-iu6",
        planning_mode=PlanningMode.AGENT_PLANNED,
        goals=_goals(),
        strategy=_strategy(),
        knowledge_planning=_no_knowledge(),
        execution_preplanning=_preplanning(),
        response_strategy=None,
    )
    invalid = draft.model_copy(update={"planning_mode": PlanningMode.DETERMINISTIC})

    with pytest.raises(PlanValidationError):
        PlanValidator().validate(invalid, _validation_context())


def test_required_knowledge_needs_complete_plan_and_configured_knowledge_skill() -> (
    None
):
    draft = ActionPlanDraftAssembler().build(
        plan_id="plan-knowledge",
        request_id="request-iu6",
        planning_mode=PlanningMode.AGENT_PLANNED,
        goals=_goals(),
        strategy=_strategy(),
        knowledge_planning=_knowledge(),
        execution_preplanning=_preplanning(),
        response_strategy=None,
    )

    with pytest.raises(PlanValidationError):
        PlanValidator().validate(draft, _validation_context())

    result = PlanValidator().validate(
        draft,
        _validation_context(knowledge_skill_ids=frozenset({"DOMAIN_SKILL"})),
    )
    assert "KNOWLEDGE_PLAN_VALID" in result.validation_codes


def test_required_false_cannot_carry_retrieval_or_evidence_plan() -> None:
    draft = ActionPlanDraftAssembler().build(
        plan_id="plan-iu6",
        request_id="request-iu6",
        planning_mode=PlanningMode.AGENT_PLANNED,
        goals=_goals(),
        strategy=_strategy(),
        knowledge_planning=_no_knowledge(),
        execution_preplanning=_preplanning(),
        response_strategy=None,
    )
    invalid = draft.model_copy(
        update={
            "retrieval_plan": RetrievalPlan(
                required=True,
                domain="DOMAIN_KNOWLEDGE",
                query="domain query",
                retrieval_mode=RetrievalMode.HYBRID,
            )
        }
    )

    with pytest.raises(PlanValidationError):
        PlanValidator().validate(invalid, _validation_context())


def test_validator_rejects_missing_skill_required_tool() -> None:
    draft = ActionPlanDraftAssembler().build(
        plan_id="plan-iu6",
        request_id="request-iu6",
        planning_mode=PlanningMode.AGENT_PLANNED,
        goals=_goals(),
        strategy=_strategy(),
        knowledge_planning=_no_knowledge(),
        execution_preplanning=_preplanning(),
        response_strategy=None,
    )
    invalid_tool_plan = dict(draft.tool_plan or {})
    invalid_tool_plan["tool_calls"] = []
    invalid = draft.model_copy(update={"tool_plan": invalid_tool_plan})

    with pytest.raises(PlanValidationError):
        PlanValidator().validate(invalid, _validation_context())


def test_validator_rejects_confirmation_that_omits_action_requirement() -> None:
    actions, strategies, skills, workflows, tools = _registries()
    actions = ActionRegistry()
    actions.register(_action("DOMAIN_ACTION", requires_confirmation=True))
    actions.register(_action("DOMAIN_FALLBACK"))

    draft = ActionPlanDraftAssembler().build(
        plan_id="plan-iu6",
        request_id="request-iu6",
        planning_mode=PlanningMode.AGENT_PLANNED,
        goals=_goals(),
        strategy=_strategy(),
        knowledge_planning=_no_knowledge(),
        execution_preplanning=_preplanning(),
        response_strategy=None,
    )
    context = PlanValidationContext(
        action_registry=actions,
        strategy_registry=strategies,
        skill_registry=skills,
        workflow_registry=workflows,
        tool_registry=tools,
        knowledge_capabilities=_validation_context().knowledge_capabilities,
    )

    with pytest.raises(PlanValidationError):
        PlanValidator().validate(draft, context)


@dataclass(frozen=True)
class DomainValidationRule:
    reject: bool = False

    def validate(
        self,
        draft: ActionPlanDraft,
        context: PlanValidationContext,
    ) -> str | None:
        del draft, context
        if self.reject:
            raise PlanValidationError("DOMAIN_RULE_REJECT")
        return "DOMAIN_RULE_VALID"


def test_injected_plan_validation_rule_can_reject_or_add_audit_code() -> None:
    draft = ActionPlanDraftAssembler().build(
        plan_id="plan-iu6",
        request_id="request-iu6",
        planning_mode=PlanningMode.AGENT_PLANNED,
        goals=_goals(),
        strategy=_strategy(),
        knowledge_planning=_no_knowledge(),
        execution_preplanning=_preplanning(),
        response_strategy=None,
    )

    passed = PlanValidator(rules=(DomainValidationRule(),)).validate(
        draft, _validation_context()
    )
    assert "DOMAIN_RULE_VALID" in passed.validation_codes

    with pytest.raises(PlanValidationError):
        PlanValidator(rules=(DomainValidationRule(reject=True),)).validate(
            draft, _validation_context()
        )


def test_iu6_does_not_create_approved_action_plan() -> None:
    draft = ActionPlanDraftAssembler().build(
        plan_id="plan-iu6",
        request_id="request-iu6",
        planning_mode=PlanningMode.AGENT_PLANNED,
        goals=_goals(),
        strategy=_strategy(),
        knowledge_planning=_no_knowledge(),
        execution_preplanning=_preplanning(),
        response_strategy=None,
    )
    validated = PlanValidator().validate(draft, _validation_context())

    assert validated.draft.approval_status.value == "DRAFT"
    assert validated.draft.__class__.__name__ == "ActionPlanDraft"
