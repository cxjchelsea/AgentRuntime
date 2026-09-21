"""M3 Understanding foundation.

Only structural vocabulary/evidence/candidate types are exported here. No real
UnderstandingEngine implementation is introduced by M3-IU1.
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
from runtime.understanding.errors import (
    InvalidUnderstandingCandidateError,
    InvalidUnderstandingDefinitionError,
    InvalidUnderstandingEvidenceError,
    UnderstandingFoundationError,
)

__all__ = [
    "CandidateAction",
    "CandidateActionCatalog",
    "CandidateActionDefinition",
    "IntentCatalog",
    "IntentDefinition",
    "InvalidUnderstandingCandidateError",
    "InvalidUnderstandingDefinitionError",
    "InvalidUnderstandingEvidenceError",
    "MemoryCandidate",
    "NeedCatalog",
    "NeedDefinition",
    "NeedResult",
    "RiskSignalSet",
    "UnderstandingEvidence",
    "UnderstandingEvidenceSource",
    "UnderstandingFoundationError",
]
