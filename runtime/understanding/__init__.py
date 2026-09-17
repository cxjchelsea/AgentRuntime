"""M3 Understanding implementation building blocks.

The package currently exposes structural foundation types plus deterministic rule
parsing. It still does not provide a full UnderstandingEngine or LLM path.
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
    UnderstandingFoundationError,
)

__all__ = [
    "CandidateAction",
    "CandidateActionCatalog",
    "CandidateActionDefinition",
    "ConfiguredTextRule",
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
    "MemoryCandidate",
    "NeedCatalog",
    "NeedDefinition",
    "NeedResult",
    "RiskSignalSet",
    "RuleParseResult",
    "TextMatchMode",
    "UnderstandingEvidence",
    "UnderstandingEvidenceSource",
    "UnderstandingFoundationError",
]
