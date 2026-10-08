"""M5 execution/readiness errors."""


class ExecutionReadinessError(RuntimeError):
    """Base M5 readiness/runtime wiring error."""


class ExecutionRegistryResolutionError(ExecutionReadinessError):
    """Base error for exact approved capability Registry resolution."""


class ExecutionCapabilityNotFoundError(ExecutionRegistryResolutionError):
    """Raised when the exact approved capability id + version is not registered."""


class ExecutionCapabilityDisabledError(ExecutionRegistryResolutionError):
    """Raised when the exact approved capability version is currently disabled."""


class ExecutionImplementationMissingError(ExecutionReadinessError):
    """Raised when the exact approved Registry record has no implementation_ref."""


class ExecutionImplementationTypeError(ExecutionReadinessError, TypeError):
    """Raised when Registry implementation_ref violates the frozen protocol."""
