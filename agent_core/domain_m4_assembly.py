"""GA-07 Slice B: reusable M4 wiring for assembled domain registries.

Reuses the existing M4 planner, validator, policy rechecker; no second
planner or execution authority is created.
"""

from __future__ import annotations

from agent_core.domain_extension import DomainExtension
from agent_core.model_adapter import StructuredStrategyTransportAdapter
from runtime.planning import (
    ActionPlanDraftAssembler,
    CapabilityIdResolver,
    CapabilityPlanner,
    ConfirmationPlanner,
    DefaultM4Planner,
    EvidenceRequirementPlanner,
    ExecutionPreplanner,
    FallbackPlanner,
    GoalResolver,
    HybridStrategySelector,
    KnowledgeCapabilityContext,
    KnowledgeDomainRouter,
    KnowledgeNeedResolver,
    KnowledgePlanner,
    LegalActionCandidateBuilder,
    MemoryUsagePlanner,
    PlanApprovalCoordinator,
    PlanningModeRouter,
    PlanValidationContext,
    PlanValidator,
    ResponseStrategyBuilder,
    RetrievalPlanner,
    RetrievalQueryBuilder,
    RuntimePlanValidatorAdapter,
    RuntimePolicyRecheckerAdapter,
    SelectedActionResolver,
    SequencePlanner,
    ToolPlanner,
    ValidationReceiptLedger,
)
from runtime.policy_enforcement import DefaultPolicyRechecker
from runtime.registries import CapabilityRegistry, ToolRegistry, WorkflowRegistry


def assemble_domain_m4(
    extension: DomainExtension, model: StructuredStrategyTransportAdapter
) -> tuple[
    DefaultM4Planner, RuntimePlanValidatorAdapter, RuntimePolicyRecheckerAdapter
]:
    """Create fresh, isolated M4 components from one domain package and model."""
    if (
        type(extension) is not DomainExtension
        or type(model) is not StructuredStrategyTransportAdapter
    ):
        raise ValueError("invalid M4 application assembly")
    knowledge = KnowledgeCapabilityContext(
        available_domains=frozenset(), supported_retrieval_modes=frozenset()
    )
    workflows = WorkflowRegistry()
    tools = ToolRegistry()
    ledger = ValidationReceiptLedger()
    planner = DefaultM4Planner(
        mode_router=PlanningModeRouter(),
        goal_resolver=GoalResolver(),
        candidate_builder=LegalActionCandidateBuilder(
            action_registry=extension.actions,
            strategy_registry=extension.strategies,
        ),
        strategy_selector=HybridStrategySelector(
            strategy_registry=extension.strategies,
            model=model,
        ),
        selected_action_resolver=SelectedActionResolver(extension.strategies),
        knowledge_planner=KnowledgePlanner(
            need_resolver=KnowledgeNeedResolver(),
            domain_router=KnowledgeDomainRouter(),
            query_builder=RetrievalQueryBuilder(),
            retrieval_planner=RetrievalPlanner(),
            evidence_planner=EvidenceRequirementPlanner(),
        ),
        execution_preplanner=ExecutionPreplanner(
            memory_planner=MemoryUsagePlanner(),
            capability_planner=CapabilityPlanner(
                skill_registry=extension.skills,
                workflow_registry=workflows,
            ),
            tool_planner=ToolPlanner(
                skill_registry=extension.skills,
                tool_registry=tools,
            ),
            confirmation_planner=ConfirmationPlanner(extension.actions),
            sequence_planner=SequencePlanner(),
            fallback_planner=FallbackPlanner(action_registry=extension.actions),
        ),
        response_strategy_builder=ResponseStrategyBuilder(),
        draft_assembler=ActionPlanDraftAssembler(),
        capability_id_resolver=CapabilityIdResolver(CapabilityRegistry()),
        knowledge_capability_context=knowledge,
        plan_id_factory=lambda request_id: f"domain-{request_id}",
    )
    validator = RuntimePlanValidatorAdapter(
        validator=PlanValidator(),
        validation_context=PlanValidationContext(
            action_registry=extension.actions,
            strategy_registry=extension.strategies,
            skill_registry=extension.skills,
            workflow_registry=workflows,
            tool_registry=tools,
            knowledge_capabilities=knowledge,
        ),
        receipt_ledger=ledger,
    )
    rechecker = RuntimePolicyRecheckerAdapter(
        approval_coordinator=PlanApprovalCoordinator(
            policy_rechecker=DefaultPolicyRechecker()
        ),
        receipt_ledger=ledger,
    )
    return planner, validator, rechecker
