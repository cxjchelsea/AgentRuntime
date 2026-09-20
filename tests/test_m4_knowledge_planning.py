"""M4-IU4 Knowledge Planning gates."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from runtime.contracts import (
    EvidenceRequirement,
    KnowledgeRequirement,
    PolicyDecision,
    RetrievalMode,
    RetrievalPlan,
    RuntimeContext,
    UnderstandingState,
)
from runtime.contracts.planning import StrategySelection
from runtime.planning import (
    EvidenceRequirementPlanner,
    GoalResolver,
    KnowledgeCapabilityContext,
    KnowledgeDomainRouter,
    KnowledgeDomainRoutingError,
    KnowledgeNeedResolutionError,
    KnowledgeNeedResolver,
    KnowledgePlanner,
    PlanningActionCandidate,
    QueryRewriteError,
    RetrievalPlanner,
    RetrievalPlanningError,
    RetrievalPolicyDecision,
    RetrievalQueryBuildError,
    RetrievalQueryBuilder,
    StrategySelectionResult,
)
from runtime.planning.goals import GoalResolutionResult
from runtime.planning.knowledge_planning import QueryRewriteRequest
from runtime.planning.knowledge_types import RetrievalQuery
from tests.orchestration_stubs import (
    build_policy_decision,
    build_runtime_context,
    build_understanding_state,
)


def _understanding() -> UnderstandingState:
    base = build_understanding_state()
    return base.model_copy(
        update={
            "topic": "DOMAIN_TOPIC",
            "entities": [
                {
                    "entity_type": "DOMAIN_ENTITY_TYPE",
                    "value": "domain entity",
                    "normalized_value": "normalized domain entity",
                }
            ],
            "goal": {
                "explicit_goal": "DOMAIN_GOAL",
                "confidence": 1.0,
            },
        }
    )


def _goals(
    understanding: UnderstandingState,
    context: RuntimeContext | None = None,
    policy: PolicyDecision | None = None,
) -> GoalResolutionResult:
    return GoalResolver().resolve(
        context or build_runtime_context(),
        understanding,
        policy or build_policy_decision(),
    )


def _strategy() -> StrategySelectionResult:
    return StrategySelectionResult(
        strategy=StrategySelection(
            strategy_id="DOMAIN_STRATEGY",
            reason_code="TEST",
            confidence=1.0,
        ),
        selected_action_ids=("DOMAIN_ACTION",),
        selection_path="RULE",
    )


def _capabilities(
    *,
    available_domains: frozenset[str] = frozenset({"DOMAIN_KNOWLEDGE"}),
    modes: frozenset[RetrievalMode] = frozenset({RetrievalMode.HYBRID}),
    default_mode: RetrievalMode | None = RetrievalMode.HYBRID,
) -> KnowledgeCapabilityContext:
    return KnowledgeCapabilityContext(
        available_domains=available_domains,
        supported_retrieval_modes=modes,
        supported_filters=frozenset(
            {
                "domain",
                "population",
                "scenario",
                "safety_level",
                "source_constraints",
                "status",
            }
        ),
        source_policies=frozenset({"DOMAIN_SOURCE_POLICY"}),
        freshness_capabilities=frozenset({"DOMAIN_FRESHNESS"}),
        default_retrieval_mode=default_mode,
        default_vector_top_k=20,
        default_sparse_top_k=20,
        default_rerank_enabled=True,
        default_rerank_top_n=5,
    )


@dataclass(frozen=True)
class StaticNeedRule:
    requirement: KnowledgeRequirement | None

    def evaluate(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        goals: GoalResolutionResult,
        strategy: StrategySelectionResult,
        candidates: tuple[PlanningActionCandidate, ...],
        policy_decision: PolicyDecision,
    ) -> KnowledgeRequirement | None:
        del (
            runtime_context,
            understanding_state,
            goals,
            strategy,
            candidates,
            policy_decision,
        )
        return self.requirement


@dataclass(frozen=True)
class StaticDomainRule:
    domain: str | None

    def route(
        self,
        requirement: KnowledgeRequirement,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        goals: GoalResolutionResult,
    ) -> str | None:
        del requirement, runtime_context, understanding_state, goals
        return self.domain


@dataclass(frozen=True)
class StaticModeRule:
    decision: RetrievalPolicyDecision | None

    def decide(
        self,
        requirement: KnowledgeRequirement,
        query: RetrievalQuery,
        capability_context: KnowledgeCapabilityContext,
    ) -> RetrievalPolicyDecision | None:
        del requirement, query, capability_context
        return self.decision


@dataclass(frozen=True)
class StaticEvidenceRule:
    requirement: EvidenceRequirement | None

    def plan(
        self,
        requirement: KnowledgeRequirement,
        retrieval_plan: RetrievalPlan,
    ) -> EvidenceRequirement | None:
        del requirement, retrieval_plan
        return self.requirement


@dataclass
class RecordingRewriter:
    payload: dict[str, object]

    def __post_init__(self) -> None:
        self.requests: list[QueryRewriteRequest] = []

    async def rewrite(self, request: QueryRewriteRequest) -> dict[str, object]:
        self.requests.append(request)
        return self.payload


@dataclass(frozen=True)
class StaticRewriteValidator:
    allowed: bool

    def preserves_goal(
        self,
        *,
        original_query: str,
        normalized_query: str,
        query_variants: tuple[str, ...],
    ) -> bool:
        del original_query, normalized_query, query_variants
        return self.allowed


def test_no_knowledge_signal_produces_explicit_no_knowledge_result() -> None:
    understanding = _understanding()
    planner = KnowledgePlanner(
        need_resolver=KnowledgeNeedResolver(),
        domain_router=KnowledgeDomainRouter(),
        query_builder=RetrievalQueryBuilder(),
        retrieval_planner=RetrievalPlanner(),
        evidence_planner=EvidenceRequirementPlanner(),
    )

    result = asyncio.run(
        planner.plan(
            runtime_context=build_runtime_context(),
            understanding_state=understanding,
            goals=_goals(understanding),
            strategy=_strategy(),
            candidates=(),
            policy_decision=build_policy_decision(),
            capability_context=_capabilities(),
        )
    )

    assert result.knowledge_requirement.required is False
    assert result.knowledge_requirement.reason == "NO_KNOWLEDGE_REQUIREMENT_SIGNAL"
    assert result.retrieval_query is None
    assert result.retrieval_plan is None
    assert result.evidence_requirement is None


def test_conflicting_knowledge_need_rules_fail_closed() -> None:
    understanding = _understanding()
    resolver = KnowledgeNeedResolver(
        rules=(
            StaticNeedRule(KnowledgeRequirement(required=False, reason="A")),
            StaticNeedRule(
                KnowledgeRequirement(
                    required=True,
                    reason="B",
                    domain="DOMAIN_KNOWLEDGE",
                    query_target="domain query",
                )
            ),
        )
    )

    with pytest.raises(KnowledgeNeedResolutionError):
        resolver.resolve(
            build_runtime_context(),
            understanding,
            _goals(understanding),
            _strategy(),
            (),
            build_policy_decision(),
        )


def test_required_domain_must_be_available() -> None:
    understanding = _understanding()
    requirement = KnowledgeRequirement(
        required=True,
        domain="DOMAIN_UNAVAILABLE",
        query_target="domain query",
    )

    with pytest.raises(KnowledgeDomainRoutingError):
        KnowledgeDomainRouter().route(
            requirement,
            build_runtime_context(),
            understanding,
            _goals(understanding),
            _capabilities(),
        )


def test_missing_domain_is_resolved_only_by_injected_domain_rule() -> None:
    understanding = _understanding()
    requirement = KnowledgeRequirement(
        required=True,
        query_target="domain query",
    )
    router = KnowledgeDomainRouter(
        rules=(StaticDomainRule("DOMAIN_KNOWLEDGE"),)
    )

    routed = router.route(
        requirement,
        build_runtime_context(),
        understanding,
        _goals(understanding),
        _capabilities(),
    )

    assert routed.domain == "DOMAIN_KNOWLEDGE"


def test_missing_domain_without_exactly_one_rule_result_fails_closed() -> None:
    understanding = _understanding()
    requirement = KnowledgeRequirement(
        required=True,
        query_target="domain query",
    )

    with pytest.raises(KnowledgeDomainRoutingError):
        KnowledgeDomainRouter().route(
            requirement,
            build_runtime_context(),
            understanding,
            _goals(understanding),
            _capabilities(),
        )


def test_query_builder_uses_requirement_target_and_structured_m3_projection() -> None:
    understanding = _understanding()
    requirement = KnowledgeRequirement(
        required=True,
        domain="DOMAIN_KNOWLEDGE",
        query_target="domain query target",
        population="DOMAIN_POPULATION",
        scenario="DOMAIN_SCENARIO",
    )

    query = asyncio.run(
        RetrievalQueryBuilder().build(
            requirement,
            build_runtime_context(),
            understanding,
            _goals(understanding),
        )
    )

    assert query.original_query == "domain query target"
    assert query.normalized_query == "domain query target"
    assert query.domain == "DOMAIN_KNOWLEDGE"
    assert query.population == "DOMAIN_POPULATION"
    assert query.scenario == "DOMAIN_SCENARIO"
    assert query.entities == ["normalized domain entity"]
    assert query.topics == ["DOMAIN_TOPIC", "domain query target"]


def test_required_query_without_target_or_provider_fails_closed() -> None:
    understanding = _understanding()

    with pytest.raises(RetrievalQueryBuildError):
        asyncio.run(
            RetrievalQueryBuilder().build(
                KnowledgeRequirement(
                    required=True,
                    domain="DOMAIN_KNOWLEDGE",
                ),
                build_runtime_context(),
                understanding,
                _goals(understanding),
            )
        )


def test_query_rewriter_requires_explicit_semantic_validator() -> None:
    with pytest.raises(RetrievalQueryBuildError):
        RetrievalQueryBuilder(
            rewriter=RecordingRewriter(
                {"normalized_query": "rewritten query"}
            )
        )


def test_query_rewrite_is_allow_listed_and_goal_preservation_gated() -> None:
    understanding = _understanding()
    requirement = KnowledgeRequirement(
        required=True,
        domain="DOMAIN_KNOWLEDGE",
        query_target="original query",
    )
    rewriter = RecordingRewriter(
        {
            "normalized_query": "rewritten query",
            "query_variants": ["variant one", "variant two"],
        }
    )
    builder = RetrievalQueryBuilder(
        rewriter=rewriter,
        rewrite_validator=StaticRewriteValidator(True),
    )

    query = asyncio.run(
        builder.build(
            requirement,
            build_runtime_context(),
            understanding,
            _goals(understanding),
        )
    )

    assert query.normalized_query == "rewritten query"
    assert query.query_variants == ["variant one", "variant two"]
    assert len(rewriter.requests) == 1
    request = rewriter.requests[0]
    assert not hasattr(request, "runtime_context")
    assert not hasattr(request, "policy_decision")
    assert not hasattr(request, "memory_context")
    assert not hasattr(request, "tool_context")


def test_query_rewrite_fails_when_semantic_validator_rejects_change() -> None:
    understanding = _understanding()
    builder = RetrievalQueryBuilder(
        rewriter=RecordingRewriter(
            {"normalized_query": "changed goal"}
        ),
        rewrite_validator=StaticRewriteValidator(False),
    )

    with pytest.raises(QueryRewriteError):
        asyncio.run(
            builder.build(
                KnowledgeRequirement(
                    required=True,
                    domain="DOMAIN_KNOWLEDGE",
                    query_target="original goal",
                ),
                build_runtime_context(),
                understanding,
                _goals(understanding),
            )
        )


def test_retrieval_planner_uses_supported_default_mode_and_filters() -> None:
    requirement = KnowledgeRequirement(
        required=True,
        domain="DOMAIN_KNOWLEDGE",
        query_target="domain query",
        source_constraints=["DOMAIN_APPROVED_SOURCE"],
        freshness_requirement="DOMAIN_FRESHNESS",
        population="DOMAIN_POPULATION",
        scenario="DOMAIN_SCENARIO",
        safety_level="DOMAIN_SAFETY",
    )
    query = RetrievalQuery(
        original_query="domain query",
        normalized_query="normalized domain query",
        query_variants=["variant"],
        domain="DOMAIN_KNOWLEDGE",
        population="DOMAIN_POPULATION",
        scenario="DOMAIN_SCENARIO",
    )

    plan = RetrievalPlanner().build(
        requirement,
        query,
        _capabilities(),
    )

    assert plan.required is True
    assert plan.retrieval_mode is RetrievalMode.HYBRID
    assert plan.query == "normalized domain query"
    assert plan.query_variants == ["variant"]
    assert plan.vector_top_k == 20
    assert plan.sparse_top_k == 20
    assert plan.rerank_enabled is True
    assert plan.rerank_top_n == 5
    assert plan.filters == {
        "domain": "DOMAIN_KNOWLEDGE",
        "population": "DOMAIN_POPULATION",
        "scenario": "DOMAIN_SCENARIO",
        "safety_level": "DOMAIN_SAFETY",
        "source_constraints": ["DOMAIN_APPROVED_SOURCE"],
    }


def test_retrieval_rule_cannot_request_unsupported_mode_or_source_policy() -> None:
    requirement = KnowledgeRequirement(
        required=True,
        domain="DOMAIN_KNOWLEDGE",
        query_target="domain query",
    )
    query = RetrievalQuery(
        original_query="domain query",
        domain="DOMAIN_KNOWLEDGE",
    )

    with pytest.raises(RetrievalPlanningError):
        RetrievalPlanner(
            rules=(
                StaticModeRule(
                    RetrievalPolicyDecision(
                        retrieval_mode=RetrievalMode.EXTERNAL_API,
                    )
                ),
            )
        ).build(requirement, query, _capabilities())

    with pytest.raises(RetrievalPlanningError):
        RetrievalPlanner(
            rules=(
                StaticModeRule(
                    RetrievalPolicyDecision(
                        retrieval_mode=RetrievalMode.HYBRID,
                        source_policy="UNSUPPORTED_SOURCE_POLICY",
                    )
                ),
            )
        ).build(requirement, query, _capabilities())


def test_external_api_is_only_a_plan_when_explicitly_supported() -> None:
    requirement = KnowledgeRequirement(
        required=True,
        domain="DOMAIN_REALTIME",
        query_target="current domain data",
    )
    query = RetrievalQuery(
        original_query="current domain data",
        domain="DOMAIN_REALTIME",
    )
    context = _capabilities(
        available_domains=frozenset({"DOMAIN_REALTIME"}),
        modes=frozenset({RetrievalMode.EXTERNAL_API}),
        default_mode=None,
    )

    plan = RetrievalPlanner(
        rules=(
            StaticModeRule(
                RetrievalPolicyDecision(
                    retrieval_mode=RetrievalMode.EXTERNAL_API,
                )
            ),
        )
    ).build(requirement, query, context)

    assert plan.retrieval_mode is RetrievalMode.EXTERNAL_API
    assert plan.required is True


def test_evidence_planner_default_only_derives_plan_level_requirements() -> None:
    requirement = KnowledgeRequirement(
        required=True,
        domain="DOMAIN_KNOWLEDGE",
        freshness_requirement="DOMAIN_FRESHNESS",
    )
    retrieval_plan = RetrievalPlanner(
        rules=(
            StaticModeRule(
                RetrievalPolicyDecision(
                    retrieval_mode=RetrievalMode.HYBRID,
                    minimum_evidence=2,
                )
            ),
        )
    ).build(
        requirement,
        RetrievalQuery(
            original_query="domain query",
            domain="DOMAIN_KNOWLEDGE",
        ),
        _capabilities(),
    )

    evidence = EvidenceRequirementPlanner().build(
        requirement,
        retrieval_plan,
    )

    assert evidence.required is True
    assert evidence.minimum_count == 2
    assert evidence.freshness_required is True
    assert evidence.minimum_trust is None
    assert not hasattr(evidence, "verified_fact")


def test_full_knowledge_planner_composes_steps_6_to_10_without_execution() -> None:
    understanding = _understanding()
    requirement = KnowledgeRequirement(
        required=True,
        reason="DOMAIN_NEEDS_KNOWLEDGE",
        domain="DOMAIN_KNOWLEDGE",
        knowledge_type="DOMAIN_KNOWLEDGE_TYPE",
        query_target="domain query",
        freshness_requirement="DOMAIN_FRESHNESS",
    )
    planner = KnowledgePlanner(
        need_resolver=KnowledgeNeedResolver(
            rules=(StaticNeedRule(requirement),)
        ),
        domain_router=KnowledgeDomainRouter(),
        query_builder=RetrievalQueryBuilder(),
        retrieval_planner=RetrievalPlanner(
            rules=(
                StaticModeRule(
                    RetrievalPolicyDecision(
                        retrieval_mode=RetrievalMode.HYBRID,
                        source_policy="DOMAIN_SOURCE_POLICY",
                        minimum_evidence=2,
                    )
                ),
            )
        ),
        evidence_planner=EvidenceRequirementPlanner(
            rules=(
                StaticEvidenceRule(
                    EvidenceRequirement(
                        required=True,
                        minimum_count=2,
                        minimum_trust="DOMAIN_TRUST",
                        freshness_required=True,
                        source_diversity_required=True,
                        conflict_check_required=True,
                        citation_required=True,
                    )
                ),
            )
        ),
    )

    result = asyncio.run(
        planner.plan(
            runtime_context=build_runtime_context(),
            understanding_state=understanding,
            goals=_goals(understanding),
            strategy=_strategy(),
            candidates=(),
            policy_decision=build_policy_decision(),
            capability_context=_capabilities(),
        )
    )

    assert result.knowledge_requirement == requirement
    assert result.retrieval_query is not None
    assert result.retrieval_plan is not None
    assert result.retrieval_plan.retrieval_mode is RetrievalMode.HYBRID
    assert result.evidence_requirement is not None
    assert result.evidence_requirement.minimum_trust == "DOMAIN_TRUST"


def test_knowledge_planning_uses_no_builtin_business_domain_catalog() -> None:
    context = KnowledgeCapabilityContext(
        available_domains=frozenset({"ARBITRARY_DOMAIN"}),
        supported_retrieval_modes=frozenset({RetrievalMode.KEYWORD}),
        default_retrieval_mode=RetrievalMode.KEYWORD,
    )

    assert context.available_domains == frozenset({"ARBITRARY_DOMAIN"})
