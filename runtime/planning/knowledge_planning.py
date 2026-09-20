"""M4-IU4 Knowledge Planning.

This module plans knowledge use only. It never executes retrieval, calls K0, validates
evidence truth, or generates a user-facing answer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from runtime.contracts import (
    EvidenceRequirement,
    KnowledgeRequirement,
    PolicyDecision,
    RetrievalMode,
    RetrievalPlan,
    RuntimeContext,
    UnderstandingState,
)
from runtime.planning.candidates import PlanningActionCandidate
from runtime.planning.errors import (
    EvidenceRequirementPlanningError,
    EvidenceRequirementRuleExecutionError,
    KnowledgeDomainRoutingError,
    KnowledgeDomainRuleExecutionError,
    KnowledgeNeedResolutionError,
    KnowledgeNeedRuleExecutionError,
    QueryRewriteError,
    RetrievalModeRuleExecutionError,
    RetrievalPlanningError,
    RetrievalQueryBuildError,
)
from runtime.planning.goals import GoalResolutionResult
from runtime.planning.knowledge_types import RetrievalQuery
from runtime.planning.strategy_selection import StrategySelectionResult


@dataclass(frozen=True, slots=True)
class KnowledgeCapabilityContext:
    """What the current knowledge/runtime installation can support."""

    available_domains: frozenset[str]
    supported_retrieval_modes: frozenset[RetrievalMode]
    supported_filters: frozenset[str] = frozenset()
    source_policies: frozenset[str] = frozenset()
    freshness_capabilities: frozenset[str] = frozenset()
    default_retrieval_mode: RetrievalMode | None = None
    default_vector_top_k: int | None = None
    default_sparse_top_k: int | None = None
    default_rerank_enabled: bool | None = None
    default_rerank_top_n: int | None = None

    def __post_init__(self) -> None:
        if self.default_retrieval_mode is not None and (
            self.default_retrieval_mode not in self.supported_retrieval_modes
        ):
            raise RetrievalPlanningError(
                "default_retrieval_mode must be supported by current capabilities"
            )
        for field_name in (
            "default_vector_top_k",
            "default_sparse_top_k",
            "default_rerank_top_n",
        ):
            value = getattr(self, field_name)
            if value is not None and value <= 0:
                raise RetrievalPlanningError(f"{field_name} must be positive")


class KnowledgeNeedRule(Protocol):
    """Injected Domain/config rule that decides whether knowledge is required."""

    def evaluate(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        goals: GoalResolutionResult,
        strategy: StrategySelectionResult,
        candidates: tuple[PlanningActionCandidate, ...],
        policy_decision: PolicyDecision,
    ) -> KnowledgeRequirement | None:
        """Return a typed requirement or None when this rule has no judgment."""


class KnowledgeNeedResolver:
    """Resolve one KnowledgeRequirement without hardcoding Domain semantics."""

    def __init__(self, rules: tuple[KnowledgeNeedRule, ...] = ()) -> None:
        self._rules = rules

    def resolve(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        goals: GoalResolutionResult,
        strategy: StrategySelectionResult,
        candidates: tuple[PlanningActionCandidate, ...],
        policy_decision: PolicyDecision,
    ) -> KnowledgeRequirement:
        decisions: list[KnowledgeRequirement] = []
        for rule in self._rules:
            try:
                decision = rule.evaluate(
                    runtime_context,
                    understanding_state,
                    goals,
                    strategy,
                    candidates,
                    policy_decision,
                )
            except Exception as exc:
                if isinstance(exc, KnowledgeNeedResolutionError):
                    raise
                raise KnowledgeNeedRuleExecutionError(
                    "knowledge need rule execution failed"
                ) from exc
            if decision is not None:
                decisions.append(decision)

        if not decisions:
            return KnowledgeRequirement(
                required=False,
                reason="NO_KNOWLEDGE_REQUIREMENT_SIGNAL",
            )

        first = decisions[0]
        if any(decision != first for decision in decisions[1:]):
            raise KnowledgeNeedResolutionError(
                "knowledge need rules produced conflicting requirements"
            )
        return first


class KnowledgeDomainRule(Protocol):
    """Injected router for Domain-owned knowledge taxonomy."""

    def route(
        self,
        requirement: KnowledgeRequirement,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        goals: GoalResolutionResult,
    ) -> str | None:
        """Return one Domain-registered knowledge domain or None."""


class KnowledgeDomainRouter:
    """Resolve a required knowledge domain against current capability context."""

    def __init__(self, rules: tuple[KnowledgeDomainRule, ...] = ()) -> None:
        self._rules = rules

    def route(
        self,
        requirement: KnowledgeRequirement,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        goals: GoalResolutionResult,
        capability_context: KnowledgeCapabilityContext,
    ) -> KnowledgeRequirement:
        if not requirement.required:
            return requirement

        if requirement.domain is not None:
            self._assert_available(requirement.domain, capability_context)
            return requirement

        candidates: list[str] = []
        for rule in self._rules:
            try:
                domain = rule.route(
                    requirement,
                    runtime_context,
                    understanding_state,
                    goals,
                )
            except Exception as exc:
                if isinstance(exc, KnowledgeDomainRoutingError):
                    raise
                raise KnowledgeDomainRuleExecutionError(
                    "knowledge domain rule execution failed"
                ) from exc
            if domain is not None:
                if not domain.strip():
                    raise KnowledgeDomainRoutingError(
                        "knowledge domain rule returned blank domain"
                    )
                candidates.append(domain)

        unique = tuple(dict.fromkeys(candidates))
        if len(unique) != 1:
            raise KnowledgeDomainRoutingError(
                "required knowledge must resolve to exactly one available domain"
            )
        self._assert_available(unique[0], capability_context)
        return requirement.model_copy(update={"domain": unique[0]})

    @staticmethod
    def _assert_available(
        domain: str,
        capability_context: KnowledgeCapabilityContext,
    ) -> None:
        if domain not in capability_context.available_domains:
            raise KnowledgeDomainRoutingError(
                "knowledge domain is not available in current capability context"
            )


class QuerySeedProvider(Protocol):
    """Optional Domain/config source when KnowledgeRequirement lacks query_target."""

    def get_seed(
        self,
        requirement: KnowledgeRequirement,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        goals: GoalResolutionResult,
    ) -> str | None:
        """Return a non-blank query seed or None."""


@dataclass(frozen=True, slots=True)
class QueryRewriteRequest:
    """Allow-listed query rewrite input."""

    original_query: str
    domain: str
    topics: tuple[str, ...]
    entities: tuple[str, ...]
    population: str | None
    scenario: str | None


class StructuredQueryRewriter(Protocol):
    """Provider-neutral bounded Query Rewrite interface."""

    async def rewrite(self, request: QueryRewriteRequest) -> Mapping[str, object]:
        """Return only normalized_query and optional query_variants."""


class QueryRewriteSemanticValidator(Protocol):
    """Required guard when a model/provider rewrite is enabled."""

    def preserves_goal(
        self,
        *,
        original_query: str,
        normalized_query: str,
        query_variants: tuple[str, ...],
    ) -> bool:
        """Return whether rewrite preserves the original retrieval goal."""


class RetrievalQueryBuilder:
    """Build structured RetrievalQuery; never sends raw RuntimeInput to retrieval."""

    _ALLOWED_REWRITE_FIELDS = frozenset({"normalized_query", "query_variants"})

    def __init__(
        self,
        *,
        seed_providers: tuple[QuerySeedProvider, ...] = (),
        rewriter: StructuredQueryRewriter | None = None,
        rewrite_validator: QueryRewriteSemanticValidator | None = None,
        max_query_variants: int = 3,
    ) -> None:
        if max_query_variants < 1:
            raise RetrievalQueryBuildError("max_query_variants must be >= 1")
        if rewriter is not None and rewrite_validator is None:
            raise RetrievalQueryBuildError(
                "query rewriter requires an explicit semantic preservation validator"
            )
        self._seed_providers = seed_providers
        self._rewriter = rewriter
        self._rewrite_validator = rewrite_validator
        self._max_query_variants = max_query_variants

    async def build(
        self,
        requirement: KnowledgeRequirement,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        goals: GoalResolutionResult,
    ) -> RetrievalQuery:
        if not requirement.required:
            raise RetrievalQueryBuildError(
                "RetrievalQuery must not be built when knowledge is not required"
            )
        if requirement.domain is None:
            raise RetrievalQueryBuildError(
                "required KnowledgeRequirement must have a routed domain"
            )

        original_query = self._resolve_seed(
            requirement,
            runtime_context,
            understanding_state,
            goals,
        )
        topics = tuple(
            dict.fromkeys(
                topic
                for topic in (understanding_state.topic, requirement.query_target)
                if topic is not None and topic.strip()
            )
        )
        entities = tuple(
            entity.normalized_value or entity.value
            for entity in (understanding_state.entities or ())
            if (entity.normalized_value or entity.value).strip()
        )

        normalized_query = original_query
        query_variants: tuple[str, ...] = ()

        if self._rewriter is not None:
            request = QueryRewriteRequest(
                original_query=original_query,
                domain=requirement.domain,
                topics=topics,
                entities=entities,
                population=requirement.population,
                scenario=requirement.scenario,
            )
            try:
                payload = await self._rewriter.rewrite(request)
            except Exception as exc:
                raise QueryRewriteError("query rewrite execution failed") from exc
            normalized_query, query_variants = self._validate_rewrite_payload(
                payload,
                original_query=original_query,
            )

        return RetrievalQuery(
            original_query=original_query,
            normalized_query=normalized_query,
            query_variants=list(query_variants) or None,
            entities=list(entities) or None,
            topics=list(topics) or None,
            population=requirement.population,
            domain=requirement.domain,
            scenario=requirement.scenario,
        )

    def _resolve_seed(
        self,
        requirement: KnowledgeRequirement,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        goals: GoalResolutionResult,
    ) -> str:
        if requirement.query_target is not None and requirement.query_target.strip():
            return requirement.query_target.strip()

        seeds: list[str] = []
        for provider in self._seed_providers:
            try:
                seed = provider.get_seed(
                    requirement,
                    runtime_context,
                    understanding_state,
                    goals,
                )
            except Exception as exc:
                raise RetrievalQueryBuildError(
                    "query seed provider execution failed"
                ) from exc
            if seed is not None:
                if not seed.strip():
                    raise RetrievalQueryBuildError(
                        "query seed provider returned blank seed"
                    )
                seeds.append(seed.strip())

        unique = tuple(dict.fromkeys(seeds))
        if len(unique) != 1:
            raise RetrievalQueryBuildError(
                "required knowledge must resolve to exactly one query seed"
            )
        return unique[0]

    def _validate_rewrite_payload(
        self,
        payload: Mapping[str, object],
        *,
        original_query: str,
    ) -> tuple[str, tuple[str, ...]]:
        if set(payload) - self._ALLOWED_REWRITE_FIELDS:
            raise QueryRewriteError("query rewriter returned unsupported fields")

        normalized = payload.get("normalized_query")
        if not isinstance(normalized, str) or not normalized.strip():
            raise QueryRewriteError(
                "query rewriter must return non-blank normalized_query"
            )
        normalized = normalized.strip()

        raw_variants = payload.get("query_variants", ())
        if not isinstance(raw_variants, (list, tuple)) or any(
            not isinstance(item, str) or not item.strip() for item in raw_variants
        ):
            raise QueryRewriteError(
                "query_variants must be an array of non-blank strings"
            )
        variants = tuple(dict.fromkeys(item.strip() for item in raw_variants))
        if len(variants) > self._max_query_variants:
            raise QueryRewriteError("query_variants exceeds configured maximum")

        validator = self._rewrite_validator
        if validator is None or not validator.preserves_goal(
            original_query=original_query,
            normalized_query=normalized,
            query_variants=variants,
        ):
            raise QueryRewriteError("query rewrite failed semantic preservation gate")

        return normalized, variants


@dataclass(frozen=True, slots=True)
class RetrievalPolicyDecision:
    """Injected/configured planning policy for one retrieval."""

    retrieval_mode: RetrievalMode
    source_policy: str | None = None
    filters: Mapping[str, object] | None = None
    vector_top_k: int | None = None
    sparse_top_k: int | None = None
    merge_policy: str | None = None
    rerank_enabled: bool | None = None
    rerank_top_n: int | None = None
    minimum_evidence: int | None = None
    fallback_policy: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("vector_top_k", "sparse_top_k", "rerank_top_n"):
            value = getattr(self, field_name)
            if value is not None and value <= 0:
                raise RetrievalPlanningError(f"{field_name} must be positive")
        if self.minimum_evidence is not None and self.minimum_evidence < 0:
            raise RetrievalPlanningError("minimum_evidence must be >= 0")


class RetrievalModeRule(Protocol):
    """Injected generic/Domain rule for retrieval mode and policy."""

    def decide(
        self,
        requirement: KnowledgeRequirement,
        query: RetrievalQuery,
        capability_context: KnowledgeCapabilityContext,
    ) -> RetrievalPolicyDecision | None:
        """Return a supported retrieval policy or None."""


class RetrievalPlanner:
    """Produce RetrievalPlan but never execute it."""

    def __init__(self, rules: tuple[RetrievalModeRule, ...] = ()) -> None:
        self._rules = rules

    def build(
        self,
        requirement: KnowledgeRequirement,
        query: RetrievalQuery,
        capability_context: KnowledgeCapabilityContext,
    ) -> RetrievalPlan:
        if not requirement.required:
            raise RetrievalPlanningError(
                "RetrievalPlan must not be built when knowledge is not required"
            )
        if requirement.domain is None or query.domain != requirement.domain:
            raise RetrievalPlanningError(
                "RetrievalQuery domain must match required knowledge domain"
            )

        decisions: list[RetrievalPolicyDecision] = []
        for rule in self._rules:
            try:
                decision = rule.decide(requirement, query, capability_context)
            except Exception as exc:
                if isinstance(exc, RetrievalPlanningError):
                    raise
                raise RetrievalModeRuleExecutionError(
                    "retrieval mode rule execution failed"
                ) from exc
            if decision is not None:
                decisions.append(decision)

        if decisions:
            first = decisions[0]
            if any(decision != first for decision in decisions[1:]):
                raise RetrievalPlanningError(
                    "retrieval mode rules produced conflicting plans"
                )
            policy = first
        else:
            mode = capability_context.default_retrieval_mode
            if mode is None:
                raise RetrievalPlanningError(
                    "required knowledge has no resolved retrieval mode"
                )
            policy = RetrievalPolicyDecision(
                retrieval_mode=mode,
                vector_top_k=capability_context.default_vector_top_k,
                sparse_top_k=capability_context.default_sparse_top_k,
                rerank_enabled=capability_context.default_rerank_enabled,
                rerank_top_n=capability_context.default_rerank_top_n,
            )

        self._validate_policy(policy, capability_context)

        filters = self._base_filters(requirement, capability_context)
        if policy.filters is not None:
            for key, value in policy.filters.items():
                if key not in capability_context.supported_filters:
                    raise RetrievalPlanningError(
                        "retrieval policy requested an unsupported metadata filter"
                    )
                filters[key] = value

        return RetrievalPlan(
            required=True,
            domain=requirement.domain,
            query=query.normalized_query or query.original_query,
            query_variants=query.query_variants,
            retrieval_mode=policy.retrieval_mode,
            filters=filters or None,
            source_policy=policy.source_policy,
            vector_top_k=policy.vector_top_k,
            sparse_top_k=policy.sparse_top_k,
            merge_policy=policy.merge_policy,
            rerank_enabled=policy.rerank_enabled,
            rerank_top_n=policy.rerank_top_n,
            freshness_requirement=requirement.freshness_requirement,
            minimum_evidence=policy.minimum_evidence,
            fallback_policy=policy.fallback_policy,
        )

    @staticmethod
    def _validate_policy(
        policy: RetrievalPolicyDecision,
        capability_context: KnowledgeCapabilityContext,
    ) -> None:
        if policy.retrieval_mode not in capability_context.supported_retrieval_modes:
            raise RetrievalPlanningError(
                "retrieval mode is unsupported by current knowledge capabilities"
            )
        if policy.source_policy is not None and (
            policy.source_policy not in capability_context.source_policies
        ):
            raise RetrievalPlanningError(
                "source policy is unsupported by current knowledge capabilities"
            )

    @staticmethod
    def _base_filters(
        requirement: KnowledgeRequirement,
        capability_context: KnowledgeCapabilityContext,
    ) -> dict[str, object]:
        candidates: dict[str, object | None] = {
            "domain": requirement.domain,
            "population": requirement.population,
            "scenario": requirement.scenario,
            "safety_level": requirement.safety_level,
        }
        output: dict[str, object] = {}
        for key, value in candidates.items():
            if value is not None and key in capability_context.supported_filters:
                output[key] = value
        if (
            requirement.source_constraints
            and "source_constraints" in capability_context.supported_filters
        ):
            output["source_constraints"] = list(requirement.source_constraints)
        return output


class EvidenceRequirementRule(Protocol):
    """Injected/configured rule for evidence strength requirements."""

    def plan(
        self,
        requirement: KnowledgeRequirement,
        retrieval_plan: RetrievalPlan,
    ) -> EvidenceRequirement | None:
        """Return one evidence requirement or None."""


class EvidenceRequirementPlanner:
    """Plan evidence requirements without evaluating any actual evidence."""

    def __init__(self, rules: tuple[EvidenceRequirementRule, ...] = ()) -> None:
        self._rules = rules

    def build(
        self,
        requirement: KnowledgeRequirement,
        retrieval_plan: RetrievalPlan,
    ) -> EvidenceRequirement:
        if not requirement.required or not retrieval_plan.required:
            raise EvidenceRequirementPlanningError(
                "EvidenceRequirement requires an active knowledge/retrieval plan"
            )

        decisions: list[EvidenceRequirement] = []
        for rule in self._rules:
            try:
                decision = rule.plan(requirement, retrieval_plan)
            except Exception as exc:
                if isinstance(exc, EvidenceRequirementPlanningError):
                    raise
                raise EvidenceRequirementRuleExecutionError(
                    "evidence requirement rule execution failed"
                ) from exc
            if decision is not None:
                decisions.append(decision)

        if decisions:
            first = decisions[0]
            if any(decision != first for decision in decisions[1:]):
                raise EvidenceRequirementPlanningError(
                    "evidence requirement rules produced conflicting requirements"
                )
            if not first.required:
                raise EvidenceRequirementPlanningError(
                    "required knowledge cannot produce required=false evidence plan"
                )
            return first

        return EvidenceRequirement(
            required=True,
            minimum_count=retrieval_plan.minimum_evidence,
            freshness_required=bool(requirement.freshness_requirement)
            if requirement.freshness_requirement is not None
            else None,
        )


@dataclass(frozen=True, slots=True)
class KnowledgePlanningResult:
    """Internal M4 result ready for later ActionPlanDraft assembly."""

    knowledge_requirement: KnowledgeRequirement
    retrieval_query: RetrievalQuery | None
    retrieval_plan: RetrievalPlan | None
    evidence_requirement: EvidenceRequirement | None


class KnowledgePlanner:
    """Compose M4 Knowledge Planning steps 6-10."""

    def __init__(
        self,
        *,
        need_resolver: KnowledgeNeedResolver,
        domain_router: KnowledgeDomainRouter,
        query_builder: RetrievalQueryBuilder,
        retrieval_planner: RetrievalPlanner,
        evidence_planner: EvidenceRequirementPlanner,
    ) -> None:
        self._need_resolver = need_resolver
        self._domain_router = domain_router
        self._query_builder = query_builder
        self._retrieval_planner = retrieval_planner
        self._evidence_planner = evidence_planner

    async def plan(
        self,
        *,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        goals: GoalResolutionResult,
        strategy: StrategySelectionResult,
        candidates: tuple[PlanningActionCandidate, ...],
        policy_decision: PolicyDecision,
        capability_context: KnowledgeCapabilityContext,
    ) -> KnowledgePlanningResult:
        requirement = self._need_resolver.resolve(
            runtime_context,
            understanding_state,
            goals,
            strategy,
            candidates,
            policy_decision,
        )
        requirement = self._domain_router.route(
            requirement,
            runtime_context,
            understanding_state,
            goals,
            capability_context,
        )

        if not requirement.required:
            return KnowledgePlanningResult(
                knowledge_requirement=requirement,
                retrieval_query=None,
                retrieval_plan=None,
                evidence_requirement=None,
            )

        query = await self._query_builder.build(
            requirement,
            runtime_context,
            understanding_state,
            goals,
        )
        retrieval_plan = self._retrieval_planner.build(
            requirement,
            query,
            capability_context,
        )
        evidence_requirement = self._evidence_planner.build(
            requirement,
            retrieval_plan,
        )
        return KnowledgePlanningResult(
            knowledge_requirement=requirement,
            retrieval_query=query,
            retrieval_plan=retrieval_plan,
            evidence_requirement=evidence_requirement,
        )
