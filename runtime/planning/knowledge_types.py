"""Internal M4 typed query representation for Knowledge Planning."""

from typing import Any

from runtime.contracts.common import CanonicalModel


class RetrievalQuery(CanonicalModel):
    """M4 query-construction intermediate; not an ActionPlan top-level field."""

    original_query: str
    normalized_query: str | None = None
    query_variants: list[str] | None = None
    entities: list[Any] | None = None
    topics: list[str] | None = None
    temporal_constraints: dict[str, Any] | None = None
    population: str | None = None
    domain: str | None = None
    scenario: str | None = None
