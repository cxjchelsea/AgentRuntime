"""M2-IU2 Core Runtime State / Transition Engine。"""

from runtime.state_management.definitions import (
    RuntimeStateDefinition,
    RuntimeStateSnapshot,
    StateTransitionDecision,
    core_runtime_state_definitions,
)
from runtime.state_management.engine import RuntimeStateEngine
from runtime.state_management.errors import (
    DuplicateStateDefinitionError,
    InvalidStateTransitionError,
    MissingStateDefinitionError,
    RuntimeStateError,
    StateRevisionConflictError,
    StateStoreUnavailableError,
)
from runtime.state_management.provider import EngineRuntimeStateProvider
from runtime.state_management.store import InMemoryRuntimeStateStore, RuntimeStateStore

__all__ = [
    "DuplicateStateDefinitionError",
    "EngineRuntimeStateProvider",
    "InMemoryRuntimeStateStore",
    "InvalidStateTransitionError",
    "MissingStateDefinitionError",
    "RuntimeStateDefinition",
    "RuntimeStateEngine",
    "RuntimeStateError",
    "RuntimeStateSnapshot",
    "RuntimeStateStore",
    "StateRevisionConflictError",
    "StateStoreUnavailableError",
    "StateTransitionDecision",
    "core_runtime_state_definitions",
]
