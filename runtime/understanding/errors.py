"""M3 Understanding internal errors."""


class UnderstandingFoundationError(RuntimeError):
    """Base error for M3 Understanding foundation types."""


class InvalidUnderstandingDefinitionError(UnderstandingFoundationError):
    """Raised when an injected understanding definition is structurally invalid."""


class InvalidUnderstandingEvidenceError(UnderstandingFoundationError):
    """Raised when internal understanding evidence is structurally invalid."""


class InvalidUnderstandingCandidateError(UnderstandingFoundationError):
    """Raised when an internal M3 candidate object is structurally invalid."""


class DeterministicUnderstandingError(UnderstandingFoundationError):
    """Base error for deterministic M3 rule parsing."""


class InvalidDeterministicRuleError(DeterministicUnderstandingError):
    """Raised when an injected deterministic rule is malformed."""


class DeterministicRuleExecutionError(DeterministicUnderstandingError):
    """Raised when a deterministic rule cannot be evaluated safely."""


class DeterministicUnderstandingConflictError(DeterministicUnderstandingError):
    """Raised when matched deterministic rules produce incompatible facts."""


class UnderstandingRoutingError(UnderstandingFoundationError):
    """Base error for M3 path-routing decisions."""


class InvalidUnderstandingRoutingPolicyError(UnderstandingRoutingError):
    """Raised when a routing policy is structurally invalid."""


class ModelBoundaryError(UnderstandingFoundationError):
    """Base error for the deep-understanding model boundary."""


class ModelInputBoundaryError(ModelBoundaryError):
    """Raised when a model request would expose disallowed runtime data."""


class ModelOutputBoundaryError(ModelBoundaryError):
    """Raised when model output crosses the Understanding-only boundary."""
