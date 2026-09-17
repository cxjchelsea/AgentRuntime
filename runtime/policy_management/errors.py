"""M2-IU4 Policy Engine errors."""


class PolicyManagementError(RuntimeError):
    """Base error for policy evaluation and aggregation."""


class InvalidPolicyFragmentError(PolicyManagementError):
    """A PolicyFragment is structurally inconsistent."""


class DuplicatePolicyRuleError(PolicyManagementError):
    """The same policy rule id was registered more than once."""


class PolicyRuleExecutionError(PolicyManagementError):
    """A policy rule raised unexpectedly during evaluation."""

    def __init__(self, rule_id: str, cause: Exception) -> None:
        self.rule_id = rule_id
        self.cause = cause
        super().__init__(f"policy rule execution failed: {rule_id}")


class PolicyConflictError(PolicyManagementError):
    """Policy fragments contain an irreconcilable hard conflict."""


class PolicyInvariantError(PolicyManagementError):
    """Inputs do not satisfy frozen M2 policy-stage invariants."""
