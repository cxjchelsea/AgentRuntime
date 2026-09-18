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
