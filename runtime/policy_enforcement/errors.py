"""M2-IU6 Plan Policy Re-check errors."""


class PolicyRecheckError(RuntimeError):
    """Base error for plan policy re-check failures."""


class PlanPolicyViolationError(PolicyRecheckError):
    """The validated draft violates the active PolicyDecision."""


class PolicyRecheckInvariantError(PolicyRecheckError):
    """The re-check inputs violate Runtime invariants."""
