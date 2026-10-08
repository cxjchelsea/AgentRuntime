"""M3-IU1 injectable Understanding vocabulary registries.

These registries reuse the M0 BaseRegistry mechanism. They register vocabulary
metadata only; they do not classify user input or authorize execution.
"""

from __future__ import annotations

from runtime.registries.base import BaseRegistry
from runtime.understanding.definitions import (
    CandidateActionDefinition,
    IntentDefinition,
    NeedDefinition,
)


class IntentCatalog(BaseRegistry[IntentDefinition]):
    """Registry for Core control and Domain-provided intent definitions."""

    _expected_definition_type = IntentDefinition

    def register_definition(self, definition: IntentDefinition) -> None:
        self.register(
            definition.intent_id,
            definition.version,
            definition,
            namespace=definition.namespace,
        )


class NeedCatalog(BaseRegistry[NeedDefinition]):
    """Registry for Domain-provided need definitions."""

    _expected_definition_type = NeedDefinition

    def register_definition(self, definition: NeedDefinition) -> None:
        self.register(
            definition.need_id,
            definition.version,
            definition,
            namespace=definition.namespace,
        )


class CandidateActionCatalog(BaseRegistry[CandidateActionDefinition]):
    """Registry for semantic-affordance actions visible to M3."""

    _expected_definition_type = CandidateActionDefinition

    def register_definition(self, definition: CandidateActionDefinition) -> None:
        self.register(
            definition.action_id,
            definition.version,
            definition,
            namespace=definition.namespace,
        )
