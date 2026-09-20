"""M4-IU8 concrete runtime integration + E2E closure gates."""

from __future__ import annotations

import ast
import asyncio
import inspect
from dataclasses import dataclass

import pytest

import runtime.planning.runtime_integration as runtime_integration_module
from runtime.contracts import (
    ActionPlanDraft,
    ApprovedActionPlan,
    PolicyDecision,
    RuntimeContext,
    RuntimeInput,
    UnderstandingState,
)
from runtime.contracts.enums import PlanningMode, ProcessingPath
from runtime.contracts.understanding import GoalUnderstanding
from runtime.interfaces.understanding import UnderstandingEngine
from runtime.orchestration import RuntimeOrchestrator
from runtime.planning import (
    ActionPlanDraftAssembler,
    CapabilityContextError,
    CapabilityIdResolver,
    CapabilityPlanner,
    ConfirmationPlanner,
    DefaultM4Planner,
    EvidenceRequirementPlanner,
    ExecutionPreplanner,
    FallbackPlanner,
    GoalResolutionResult,
    GoalResolver,
    HybridStrategySelector,
    KnowledgeCapabilityContext,
    KnowledgeDomainRouter,
    KnowledgeNeedResolver,
    KnowledgePlanner,
    LegalActionCandidateBuilder,
    MemoryUsagePlanner,
    PlanningActionCandidate,
    PlanApprovalCoordinator,
    PlanValidationContext,
    PlanValidator,
    PlanningModeRouter,
    ResponseStrategyBuilder,
    RetrievalPlanner,
    RetrievalQueryBuilder,
    RuntimePlanValidatorAdapter,
    RuntimePolicyRecheckerAdapter,
    SequencePlanner,
    StrategyRuleChoice,
    ToolPlanner,
    ValidationReceiptError,
    ValidationReceiptLedger,
)
from runtime.policy_enforcement import DefaultPolicyRechecker
from runtime.registries import (
    ActionDefinition,
    ActionRegistry,
    CapabilityDefinition,
    CapabilityRegistry,
    IntrusivenessLevel,
    SkillDefinition,
    SkillRegistry,
    StrategyDefinition,
    StrategyRegistry,
    ToolRegistry,
    WorkflowRegistry,
)
from tests.orchestration_stubs import (
    CallRecorder,
    StubContextBuilder,
    StubExecutionEngine,
    StubInputProcessor,
    StubPolicyEngine,
    StubResponseGenerator,
    StubResponsePlanner,
    StubResponseValidator,
    StubResultValidator,
    StubSafetyGuard,
    StubStateMemoryUpdater,
    build_policy_decision,
    build_runtime_context,
    build_runtime_input,
    build_understanding_state,
)


DOMAIN_ACTION = "DOMAIN_ACTION"
DOMAIN_STRATEGY = "DOMAIN_STRATEGY"
DOMAIN_SKILL = "DOMAIN_SKILL"
DOMAIN_GOAL = "DOMAIN_GOAL"


@dataclass(frozen=True)
class FixedStrategyRule:
    """Deterministic Domain rule used only by the IU8 integration test."""

    def select(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        goals: GoalResolutionResult,
        candidates: tuple[PlanningActionCandidate, ...],
        policy_decision: PolicyDecision,
        legal_strategy_ids: tuple[str, ...],
    ) -> StrategyRuleChoice | None:
        del (
            runtime_context,
            understanding_state,
            goals,
            candidates,
            policy_decision,
        )
        if DOMAIN_STRATEGY not in legal_strategy_ids:
            return None
        return StrategyRuleChoice(
            strategy_id=DOMAIN_STRATEGY,
            reason_code="DOMAIN_DETERMINISTIC_RULE",
            action_ids=(DOMAIN_ACTION,),
            confidence=1.0,
        )


class GoalUnderstandingEngine(UnderstandingEngine):
    """Produce a request-bound M3 output with one explicit generic Domain goal."""

    def __init__(self, recorder: CallRecorder) -> None:
        self._recorder = recorder

    async def understand(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext,
    ) -> UnderstandingState:
        del runtime_context
        self._recorder.record("UNDERSTANDING")
        base = build_understanding_state()
        metadata = base.metadata.model_copy(
            update={
                "request_id": runtime_input.request_id,
                "processing_path": ProcessingPath.DEGRADED_PATH,
            }
        )
        return base.model_copy(
            update={
                "metadata": metadata,
                "goal": GoalUnderstanding(
                    explicit_goal=DOMAIN_GOAL,
                    confidence=1.0,
                ),
            }
        )


@dataclass(frozen=True)
class M4Fixture:
    planner: DefaultM4Planner
    validator_adapter: RuntimePlanValidatorAdapter
    rechecker_adapter: RuntimePolicyRecheckerAdapter
    receipt_ledger: ValidationReceiptLedger


def _registries() -> tuple[
    ActionRegistry,
    StrategyRegistry,
    SkillRegistry,
    WorkflowRegistry,
    ToolRegistry,
    CapabilityRegistry,
]:
    actions = ActionRegistry()
    actions.register(
        ActionDefinition(
            action_id=DOMAIN_ACTION,
            version="1.0.0",
            category="DOMAIN_CATEGORY",
            description="domain action",
            intrusiveness_level=IntrusivenessLevel.LOW,
            requires_confirmation=False,
            required_capability=None,
            allowed_planning_modes=[PlanningMode.DEGRADED],
        )
    )

    strategies = StrategyRegistry()
    strategies.register(
        StrategyDefinition(
            strategy_id=DOMAIN_STRATEGY,
            version="1.0.0",
            description="domain strategy",
            preferred_goals=[],
            preferred_needs=[],
            compatible_emotions=[],
            required_conditions=[],
            avoid_conditions=[],
            default_actions=[DOMAIN_ACTION],
            intrusiveness_level=IntrusivenessLevel.LOW,
        )
    )

    skills = SkillRegistry()
    skills.register(
        SkillDefinition(
            skill_id=DOMAIN_SKILL,
            version="1.0.0",
            supported_actions=[DOMAIN_ACTION],
        )
    )

    workflows = WorkflowRegistry()
    tools = ToolRegistry()
    capabilities = CapabilityRegistry()
    return actions, strategies, skills, workflows, tools, capabilities


def _build_m4_fixture(
    *,
    plan_id: str = "plan-m4-iu8",
) -> M4Fixture:
    actions, strategies, skills, workflows, tools, capabilities = _registries()

    knowledge_capabilities = KnowledgeCapabilityContext(
        available_domains=frozenset(),
        supported_retrieval_modes=frozenset(),
    )
    candidate_builder = LegalActionCandidateBuilder(
        action_registry=actions,
        strategy_registry=strategies,
    )
    strategy_selector = HybridStrategySelector(
        strategy_registry=strategies,
        rules=(FixedStrategyRule(),),
    )
    knowledge_planner = KnowledgePlanner(
        need_resolver=KnowledgeNeedResolver(),
        domain_router=KnowledgeDomainRouter(),
        query_builder=RetrievalQueryBuilder(),
        retrieval_planner=RetrievalPlanner(),
        evidence_planner=EvidenceRequirementPlanner(),
    )
    execution_preplanner = ExecutionPreplanner(
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
    )
    planner = DefaultM4Planner(
        mode_router=PlanningModeRouter(),
        goal_resolver=GoalResolver(),
        candidate_builder=candidate_builder,
        strategy_selector=strategy_selector,
        knowledge_planner=knowledge_planner,
        execution_preplanner=execution_preplanner,
        response_strategy_builder=ResponseStrategyBuilder(),
        draft_assembler=ActionPlanDraftAssembler(),
        capability_id_resolver=CapabilityIdResolver(capabilities),
        knowledge_capability_context=knowledge_capabilities,
        plan_id_factory=lambda request_id: (
            plan_id if request_id.strip() else ""
        ),
    )

    receipt_ledger = ValidationReceiptLedger()
    validator_adapter = RuntimePlanValidatorAdapter(
        validator=PlanValidator(),
        validation_context=PlanValidationContext(
            action_registry=actions,
            strategy_registry=strategies,
            skill_registry=skills,
            workflow_registry=workflows,
            tool_registry=tools,
            knowledge_capabilities=knowledge_capabilities,
        ),
        receipt_ledger=receipt_ledger,
    )
    rechecker_adapter = RuntimePolicyRecheckerAdapter(
        approval_coordinator=PlanApprovalCoordinator(
            policy_rechecker=DefaultPolicyRechecker()
        ),
        receipt_ledger=receipt_ledger,
    )
    return M4Fixture(
        planner=planner,
        validator_adapter=validator_adapter,
        rechecker_adapter=rechecker_adapter,
        receipt_ledger=receipt_ledger,
    )


def _understanding(request_id: str = "request-001") -> UnderstandingState:
    base = build_understanding_state()
    return base.model_copy(
        update={
            "metadata": base.metadata.model_copy(
                update={
                    "request_id": request_id,
                    "processing_path": ProcessingPath.DEGRADED_PATH,
                }
            ),
            "goal": GoalUnderstanding(
                explicit_goal=DOMAIN_GOAL,
                confidence=1.0,
            ),
        }
    )


def test_concrete_m4_planner_composes_iu2_through_iu6_into_draft() -> None:
    fixture = _build_m4_fixture()

    draft = asyncio.run(
        fixture.planner.plan(
            build_runtime_context(),
            _understanding(),
            build_policy_decision(),
        )
    )

    assert isinstance(draft, ActionPlanDraft)
    assert draft.approval_status.value == "DRAFT"
    assert draft.plan_id == "plan-m4-iu8"
    assert draft.request_id == "request-001"
    assert draft.planning_mode is PlanningMode.DEGRADED
    assert [goal.goal_id for goal in draft.goals] == [DOMAIN_GOAL]
    assert draft.strategy is not None
    assert draft.strategy.strategy_id == DOMAIN_STRATEGY
    assert [step.action for step in draft.steps] == [DOMAIN_ACTION]
    assert draft.steps[0].skill_id == DOMAIN_SKILL
    assert draft.knowledge_requirement is not None
    assert draft.knowledge_requirement.required is False


def test_runtime_validator_and_rechecker_bridge_exact_validated_draft() -> None:
    fixture = _build_m4_fixture()
    draft = asyncio.run(
        fixture.planner.plan(
            build_runtime_context(),
            _understanding(),
            build_policy_decision(),
        )
    )

    validated = asyncio.run(fixture.validator_adapter.validate(draft))
    assert validated is draft
    assert fixture.receipt_ledger.pending_count() == 1

    approved = asyncio.run(
        fixture.rechecker_adapter.recheck(
            validated,
            build_policy_decision(),
        )
    )

    assert isinstance(approved, ApprovedActionPlan)
    assert approved.plan_id == draft.plan_id
    assert approved.steps == draft.steps
    assert approved.capability_plan == draft.capability_plan
    assert approved.tool_plan == draft.tool_plan
    assert fixture.receipt_ledger.pending_count() == 0


def test_policy_recheck_cannot_bypass_plan_validate_receipt() -> None:
    fixture = _build_m4_fixture()
    draft = asyncio.run(
        fixture.planner.plan(
            build_runtime_context(),
            _understanding(),
            build_policy_decision(),
        )
    )

    with pytest.raises(ValidationReceiptError, match="prior PLAN_VALIDATE"):
        asyncio.run(
            fixture.rechecker_adapter.recheck(
                draft,
                build_policy_decision(),
            )
        )


def test_draft_mutation_after_plan_validate_breaks_receipt_continuity() -> None:
    fixture = _build_m4_fixture()
    draft = asyncio.run(
        fixture.planner.plan(
            build_runtime_context(),
            _understanding(),
            build_policy_decision(),
        )
    )
    validated = asyncio.run(fixture.validator_adapter.validate(draft))
    mutated = validated.model_copy(
        update={
            "fallback_plan": {
                "mode": "CHANGED_AFTER_VALIDATE",
                "allowed_actions": [],
                "reason_codes": [],
            }
        }
    )

    with pytest.raises(ValidationReceiptError, match="changed"):
        asyncio.run(
            fixture.rechecker_adapter.recheck(
                mutated,
                build_policy_decision(),
            )
        )
    assert fixture.receipt_ledger.pending_count() == 0


def test_capability_id_resolver_fails_on_enabled_version_ambiguity() -> None:
    capabilities = CapabilityRegistry()
    capabilities.register(
        CapabilityDefinition(
            capability_id="DOMAIN_CAPABILITY",
            version="1.0.0",
        )
    )
    capabilities.register(
        CapabilityDefinition(
            capability_id="DOMAIN_CAPABILITY",
            version="2.0.0",
        )
    )

    with pytest.raises(CapabilityContextError):
        CapabilityIdResolver(capabilities).resolve()


def test_full_runtime_chain_uses_concrete_m4_plan_validate_and_recheck() -> None:
    recorder = CallRecorder()
    fixture = _build_m4_fixture(plan_id="plan-runtime-e2e")
    execution = StubExecutionEngine(recorder)

    orchestrator = RuntimeOrchestrator(
        input_processor=StubInputProcessor(recorder),
        safety_guard=StubSafetyGuard(recorder),
        context_builder=StubContextBuilder(recorder),
        understanding_engine=GoalUnderstandingEngine(recorder),
        policy_engine=StubPolicyEngine(recorder),
        planner=fixture.planner,
        plan_validator=fixture.validator_adapter,
        policy_rechecker=fixture.rechecker_adapter,
        execution_engine=execution,
        result_validator=StubResultValidator(recorder),
        response_planner=StubResponsePlanner(recorder),
        response_generator=StubResponseGenerator(recorder),
        response_validator=StubResponseValidator(recorder),
        state_memory_updater=StubStateMemoryUpdater(recorder),
    )

    outcome = asyncio.run(orchestrator.run(build_runtime_input()))

    assert outcome.runtime_response is not None
    assert outcome.update_result is not None
    assert isinstance(execution.received_plan, ApprovedActionPlan)
    assert execution.received_plan.plan_id == "plan-runtime-e2e"
    assert execution.received_plan.steps[0].action == DOMAIN_ACTION
    assert fixture.receipt_ledger.pending_count() == 0
    assert [event.stage_name for event in outcome.trace.stage_events] == [
        "INPUT",
        "SAFETY_EARLY",
        "CONTEXT",
        "UNDERSTANDING",
        "SAFETY_DEEP",
        "POLICY",
        "PLAN",
        "PLAN_VALIDATE",
        "POLICY_RECHECK",
        "EXECUTE",
        "RESULT_VALIDATE",
        "RESPONSE_PLAN",
        "RESPONSE_GENERATE",
        "RESPONSE_VALIDATE",
        "UPDATE",
    ]


def test_m4_runtime_integration_imports_no_execution_or_knowledge_runtime() -> None:
    source = inspect.getsource(runtime_integration_module)
    tree = ast.parse(source)
    imported_modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module)

    forbidden_prefixes = (
        "runtime.interfaces.execution",
        "runtime.execution",
        "runtime.knowledge",
        "runtime.validation",
        "runtime.response",
        "requests",
        "httpx",
    )
    assert not any(
        module.startswith(prefix)
        for module in imported_modules
        for prefix in forbidden_prefixes
    )
