"""M1 Context Builder 默认实现与内部扩展点。"""

from runtime.context_building.builder import DefaultContextBuilder
from runtime.context_building.errors import (
    ContextBuildError,
    ContextBuildInvariantError,
    CriticalContextUnavailableError,
    DuplicateContextProviderError,
    InvalidContextProviderResultError,
)
from runtime.context_building.providers import (
    ContextKind,
    ContextProvider,
    ContextProviderUnavailable,
    IdentityStatusResolver,
    RuntimeStateProvider,
)
from runtime.context_building.selector import ContextSelector, CoreContextSelector

__all__ = [
    "ContextBuildError",
    "ContextBuildInvariantError",
    "ContextKind",
    "ContextProvider",
    "ContextProviderUnavailable",
    "ContextSelector",
    "CoreContextSelector",
    "CriticalContextUnavailableError",
    "DefaultContextBuilder",
    "DuplicateContextProviderError",
    "IdentityStatusResolver",
    "InvalidContextProviderResultError",
    "RuntimeStateProvider",
]
