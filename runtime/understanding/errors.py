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
    """Base error for M3 understanding-path routing."""


class InvalidUnderstandingRoutingPolicyError(UnderstandingRoutingError):
    """Raised when generic routing configuration is malformed."""


class ModelBoundaryError(UnderstandingFoundationError):
    """Base error for deep-understanding model boundary failures."""


class ModelInputBoundaryError(ModelBoundaryError):
    """Raised when data cannot safely cross into the model boundary."""


class ModelOutputBoundaryError(ModelBoundaryError):
    """Raised when model output crosses the Understanding-only boundary."""


class UnderstandingPostprocessingError(UnderstandingFoundationError):
    """Base error for M3 evidence/uncertainty/candidate postprocessing."""


class InvalidModelEvidenceError(UnderstandingPostprocessingError):
    """Raised when model-provided interpretation evidence is malformed."""


class InvalidModelUncertaintyError(UnderstandingPostprocessingError):
    """Raised when model-provided uncertainty data is malformed."""


class CandidateExtractionError(UnderstandingPostprocessingError):
    """Raised when an injected candidate extractor fails or conflicts."""


class MissingDeepUnderstandingResultError(UnderstandingPostprocessingError):
    """Raised when a model-required route reaches postprocessing without a result."""
