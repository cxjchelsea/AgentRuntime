"""M3 Understanding implementation building blocks.

The package exposes structural foundation types, deterministic rule parsing, path
routing, and a provider-neutral model boundary. It still does not provide a full
UnderstandingEngine or Understanding Orchestrator.
"""

from runtime.understanding.catalog import (
    CandidateActionCatalog,
    IntentCatalog,
    NeedCatalog,
)
from runtime.understanding.definitions import (
    CandidateAction,
    CandidateActionDefinition,
    IntentDefinition,
    MemoryCandidate,
    NeedDefinition,
    NeedResult,
    RiskSignalSet,
    UnderstandingEvidence,
    UnderstandingEvidenceSource,
)
from runtime.understanding.deterministic import (
    ConfiguredTextRule,
    DeterministicRuleDefinition,
    DeterministicRuleFinding,
    DeterministicRuleParser,
    DeterministicUnderstandingRule,
    RuleParseResult,
    TextMatchMode,
)
from runtime.understanding.errors import (
    DeterministicRuleExecutionError,
    DeterministicUnderstandingConflictError,
    DeterministicUnderstandingError,
    InvalidDeterministicRuleError,
    InvalidUnderstandingCandidateError,
    InvalidUnderstandingDefinitionError,
    InvalidUnderstandingEvidenceError,
    InvalidUnderstandingRoutingPolicyError,
    ModelBoundaryError,
    ModelInputBoundaryError,
    ModelOutputBoundaryError,
    UnderstandingFoundationError,
    UnderstandingRoutingError,
)
from runtime.understanding.model_boundary import (
    DeepUnderstandingRequest,
    DeepUnderstandingRequestBuilder,
    DefaultModelContextSelector,
    ModelContextSelectionPolicy,
    ModelUnderstandingOutputValidator,
    ModelUnderstandingResult,
    SelectedModelContext,
    StructuredUnderstandingModel,
)
from runtime.understanding.routing import (
    UnderstandingPathRouter,
    UnderstandingRouteDecision,
    UnderstandingRoutingPolicy,
)

__all__ = [
    "CandidateAction",
    "CandidateActionCatalog",
    "CandidateActionDefinition",
    "ConfiguredTextRule",
    "DeepUnderstandingRequest",
    "DeepUnderstandingRequestBuilder",
    "DefaultModelContextSelector",
    "DeterministicRuleDefinition",
    "DeterministicRuleExecutionError",
    "DeterministicRuleFinding",
    "DeterministicRuleParser",
    "DeterministicUnderstandingConflictError",
    "DeterministicUnderstandingError",
    "DeterministicUnderstandingRule",
    "IntentCatalog",
    "IntentDefinition",
    "InvalidDeterministicRuleError",
    "InvalidUnderstandingCandidateError",
    "InvalidUnderstandingDefinitionError",
    "InvalidUnderstandingEvidenceError",
    "InvalidUnderstandingRoutingPolicyError",
    "MemoryCandidate",
    "ModelBoundaryError",
    "ModelContextSelectionPolicy",
    "ModelInputBoundaryError",
    "ModelOutputBoundaryError",
    "ModelUnderstandingOutputValidator",
    "ModelUnderstandingResult",
    "NeedCatalog",
    "NeedDefinition",
    "NeedResult",
    "RiskSignalSet",
    "RuleParseResult",
    "SelectedModelContext",
    "StructuredUnderstandingModel",
    "TextMatchMode",
    "UnderstandingEvidence",
    "UnderstandingEvidenceSource",
    "UnderstandingFoundationError",
    "UnderstandingPathRouter",
    "UnderstandingRouteDecision",
    "UnderstandingRoutingError",
    "UnderstandingRoutingPolicy",
]
