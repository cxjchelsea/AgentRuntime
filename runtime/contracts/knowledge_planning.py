"""M4 Knowledge Planning subcontracts.

These contracts describe planning requirements only. They do not execute retrieval,
produce evidence, or assert verified truth.
"""

from typing import Any

from runtime.contracts.common import CanonicalModel
from runtime.contracts.enums import RetrievalMode


class KnowledgeRequirement(CanonicalModel):
    """M4 decision about whether and what knowledge support is required."""

    required: bool
    reason: str | None = None
    domain: str | None = None
    knowledge_type: str | None = None
    query_target: str | None = None
    source_constraints: list[str] | None = None
    freshness_requirement: str | None = None
    evidence_level: str | None = None
    population: str | None = None
    scenario: str | None = None
    safety_level: str | None = None


class RetrievalPlan(CanonicalModel):
    """Execution-facing retrieval plan produced by M4 and consumed downstream."""

    required: bool
    domain: str | None = None
    query: str | None = None
    query_variants: list[str] | None = None
    retrieval_mode: RetrievalMode | None = None
    filters: dict[str, Any] | None = None
    source_policy: str | None = None
    vector_top_k: int | None = None
    sparse_top_k: int | None = None
    merge_policy: str | None = None
    rerank_enabled: bool | None = None
    rerank_top_n: int | None = None
    freshness_requirement: str | None = None
    minimum_evidence: int | None = None
    fallback_policy: str | None = None


class EvidenceRequirement(CanonicalModel):
    """M4 requirement for what evidence quality/count the plan needs."""

    required: bool
    minimum_count: int | None = None
    minimum_trust: str | None = None
    freshness_required: bool | None = None
    source_diversity_required: bool | None = None
    conflict_check_required: bool | None = None
    citation_required: bool | None = None
