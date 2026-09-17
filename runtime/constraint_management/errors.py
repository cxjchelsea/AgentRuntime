"""M2-IU5 Runtime Constraint integration errors."""


class RuntimeConstraintError(RuntimeError):
    """Base error for M2 constraint integration."""


class RuntimeConstraintInvariantError(RuntimeConstraintError):
    """Input decisions or turn identity are inconsistent."""
