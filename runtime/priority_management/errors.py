"""M2-IU3 Priority / Preemption Engine errors."""


class PriorityPreemptionError(RuntimeError):
    """Base error for priority / preemption evaluation."""


class InvalidPrioritySubjectError(PriorityPreemptionError):
    """A priority subject is structurally invalid."""


class PriorityDecisionMismatchError(PriorityPreemptionError):
    """A PriorityDecision does not belong to the supplied subjects."""


class DuplicatePreemptionRuleError(PriorityPreemptionError):
    """The same preemption rule key was registered more than once."""


class MissingPreemptionRuleError(PriorityPreemptionError):
    """No explicit rule can decide an active-vs-incoming pair."""


class AmbiguousPreemptionRuleError(PriorityPreemptionError):
    """More than one equally-specific preemption rule matches."""
