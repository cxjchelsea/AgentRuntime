"""M5 readiness errors for execution contract resolution."""


class ExecutionReadinessError(RuntimeError):
    """Base M5 readiness/runtime wiring error."""


class ExecutionRegistryResolutionError(ExecutionReadinessError):
    """Raised when an execution definition cannot resolve unambiguously."""


class ExecutionImplementationTypeError(ExecutionReadinessError, TypeError):
    """Raised when Registry implementation_ref violates the frozen protocol."""
