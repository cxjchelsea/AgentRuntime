"""M3-IU1 internal Understanding foundation errors."""


class UnderstandingFoundationError(RuntimeError):
    """Base error for M3 Understanding foundation types."""


class InvalidUnderstandingDefinitionError(UnderstandingFoundationError):
    """Raised when an injected understanding definition is structurally invalid."""


class InvalidUnderstandingEvidenceError(UnderstandingFoundationError):
    """Raised when internal understanding evidence is structurally invalid."""


class InvalidUnderstandingCandidateError(UnderstandingFoundationError):
    """Raised when an internal M3 candidate object is structurally invalid."""
