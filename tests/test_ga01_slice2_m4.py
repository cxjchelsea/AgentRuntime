"""GA-01B Slice 2: model-selected strategies reach the REAL M4 approval chain.

The async model transport remains fake, M4 legality and approval are real.
There is no physical Tool implementation or production M6 grant in this file.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from agent_core.model_adapter import StructuredStrategyTransportAdapter
from runtime.contracts import ActionPlanDraft, ApprovedActionPlan
from runtime.contracts.context import InteractionContext
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
    StrategyEligibilityRule,
    StrategyModelRequestBuilder,
    ToolPlanner,
    ValidationReceiptLedger,
)
from runtime.policy_enforcement import DefaultPolicyRechecker
from runtime.registries import (
    ActionRegistry,
    CapabilityRegistry,
    SkillDefinition,
    SkillRegistry,
    StrategyRegistry,
    ToolRegistry,
    WorkflowRegistry,
)
from tests.orchestration_stubs import build_policy_decision, build_runtime_context
from tests.test_ga01_slice2 import ObservationSensitiveFakeTransport
from tests.test_m4_candidate_strategy_selection import (
    _action,
    _strategy_registry,
    _understanding,
)


@dataclass(frozen=True)
class PlanningFixture:
    planner: DefaultM4Planner
    validator: RuntimePlanValidatorAdapter
    rechecker: RuntimePolicyRecheckerAdapter


def _build_model_planner(
    model: StructuredStrategyTransportAdapter,
    *,
    eligibility_rules: tuple[StrategyEligibilityRule, ...] = (),
    request_builder: StrategyModelRequestBuilder | None = None,
) -> PlanningFixture:
    actions = ActionRegistry()
    actions.register(_action("DOMAIN_ACTION_A"))
    actions.register(_action("DOMAIN_ACTION_B"))
    strategies: StrategyRegistry = _strategy_registry()
    skills = SkillRegistry()
    skills.register(
        SkillDefinition(
            skill_id="SKILL_A",
            version="1.0.0",
            supported_actions=["DOMAIN_ACTION_A"],
        )
    )
    skills.register(
        SkillDefinition(
            skill_id="SKILL_B",
            version="1.0.0",
            supported_actions=["DOMAIN_ACTION_B"],
        )
    )
    workflows = WorkflowRegistry()
    tools = ToolRegistry()
    capabilities = CapabilityRegistry()
    knowledge = KnowledgeCapabilityContext(
        available_domains=frozenset(),
        supported_retrieval_modes=frozenset(),
    )
    planner = DefaultM4Planner(
        mode_router=PlanningModeRouter(),
        goal_resolver=GoalResolver(),
        candidate_builder=LegalActionCandidateBuilder(
            action_registry=actions,
            strategy_registry=strategies,
        ),
        strategy_selector=HybridStrategySelector(
            strategy_registry=strategies,
            model=model,
            eligibility_rules=eligibility_rules,
            request_builder=request_builder,
        ),
        selected_action_resolver=SelectedActionResolver(strategies),
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
                skill_registry=skills,
                workflow_registry=workflows,
            ),
            tool_planner=ToolPlanner(
                skill_registry=skills,
                tool_registry=tools,
            ),
            confirmation_planner=ConfirmationPlanner(actions),
            sequence_planner=SequencePlanner(),
            fallback_planner=FallbackPlanner(action_registry=actions),
        ),
        response_strategy_builder=ResponseStrategyBuilder(),
        draft_assembler=ActionPlanDraftAssembler(),
        capability_id_resolver=CapabilityIdResolver(capabilities),
        knowledge_capability_context=knowledge,
        plan_id_factory=lambda request_id: f"model-{request_id}",
    )
    ledger = ValidationReceiptLedger()
    validator = RuntimePlanValidatorAdapter(
        validator=PlanValidator(),
        validation_context=PlanValidationContext(
            action_registry=actions,
            strategy_registry=strategies,
            skill_registry=skills,
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
    return PlanningFixture(planner, validator, rechecker)


async def _approved_from_observation(
    fixture: PlanningFixture,
    *,
    observed: str | None,
) -> tuple[ActionPlanDraft, ApprovedActionPlan]:
    context = build_runtime_context().model_copy(
        update={"interaction_context": InteractionContext(last_agent_action=observed)}
    )
    understanding = _understanding()
    policy = build_policy_decision()
    draft = await fixture.planner.plan(context, understanding, policy)
    validated = await fixture.validator.validate(draft)
    approved = await fixture.rechecker.recheck(validated, policy)
    return draft, approved


def test_live_m4_planner_changes_approved_steps_when_sandbox_context_changes() -> None:
    async def scenario() -> None:
        transport = ObservationSensitiveFakeTransport()
        fixture = _build_model_planner(StructuredStrategyTransportAdapter(transport))
        first_draft, first_approved = await _approved_from_observation(
            fixture, observed=None
        )
        # Another simulated iteration, new Planner instance to isolate receipt usage.
        second_fixture = _build_model_planner(
            StructuredStrategyTransportAdapter(transport)
        )
        second_draft, second_approved = await _approved_from_observation(
            second_fixture, observed="MOCK_FOUND_NEEDS_VERIFICATION"
        )
        assert first_draft.strategy is not None
        assert second_draft.strategy is not None
        assert first_draft.strategy.strategy_id == "DOMAIN_STRATEGY_A"
        assert second_draft.strategy.strategy_id == "DOMAIN_STRATEGY_B"
        assert [step.action for step in first_approved.steps] == ["DOMAIN_ACTION_A"]
        assert [step.action for step in second_approved.steps] == ["DOMAIN_ACTION_B"]
        assert len(transport.calls) == 2

    asyncio.run(scenario())


def test_illegal_model_selection_never_produces_an_approved_plan() -> None:
    async def illegal(_payload: dict[str, Any]) -> dict[str, object]:
        return {
            "strategy_id": "UNKNOWN",
            "action_ids": ["UNREGISTERED_TOOL"],
        }

    async def scenario() -> None:
        fixture = _build_model_planner(StructuredStrategyTransportAdapter(illegal))
        with pytest.raises(Exception, match="unregistered or ineligible"):
            await _approved_from_observation(fixture, observed=None)

    asyncio.run(scenario())
