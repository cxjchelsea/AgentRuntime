"""M4 Planning internal errors."""


class PlanningError(RuntimeError):
    """Base error for M4 planning implementation."""


class PlanningBlockedByPolicyError(PlanningError):
    """Raised when M4 is invoked despite a blocking M2 PolicyDecision."""


class PlanningRouteConflictError(PlanningError):
    """Raised when generic planning-route signals conflict."""


class InvalidPlanningRouteRuleError(PlanningError):
    """Raised when an injected PlanningMode rule is malformed."""


class GoalResolutionError(PlanningError):
    """Base error for M4 goal resolution."""


class InvalidGoalCandidateError(GoalResolutionError):
    """Raised when an injected/internal goal candidate is malformed."""


class GoalProviderExecutionError(GoalResolutionError):
    """Raised when an injected goal provider fails."""


class CandidateGenerationError(PlanningError):
    """Base error for legal M4 action candidate generation."""


class InvalidActionCandidateError(CandidateGenerationError):
    """Raised when a candidate is malformed or references an illegal action."""


class ActionRegistryAmbiguityError(CandidateGenerationError):
    """Raised when one action_id has multiple enabled registry versions."""


class CandidateEligibilityError(CandidateGenerationError):
    """Raised when an injected eligibility rule fails."""


class StrategySelectionError(PlanningError):
    """Base error for M4 strategy selection."""


class StrategyRegistryAmbiguityError(StrategySelectionError):
    """Raised when one strategy_id has multiple enabled registry versions."""


class InvalidStrategySelectionError(StrategySelectionError):
    """Raised when a rule/model chooses outside the legal strategy/action space."""


class StrategyRuleExecutionError(StrategySelectionError):
    """Raised when an injected deterministic strategy rule fails."""


class StrategyModelBoundaryError(StrategySelectionError):
    """Base error for the optional soft-selection model boundary."""


class StrategyModelUnavailableError(StrategyModelBoundaryError):
    """Raised when model selection is requested without a configured model."""


class StrategyModelExecutionError(StrategyModelBoundaryError):
    """Raised when the strategy model fails during inference."""


class StrategyModelOutputError(StrategyModelBoundaryError):
    """Raised when model output violates the frozen legal-choice boundary."""
