"""把 M2 RuntimeStateEngine 适配为 M1 RuntimeStateProvider。"""

from runtime.context_building import ContextProviderUnavailable, RuntimeStateProvider
from runtime.contracts import RuntimeInput
from runtime.contracts.context import RuntimeStateContext
from runtime.state_management.engine import RuntimeStateEngine
from runtime.state_management.errors import (
    StateNotInitializedError,
    StateStoreUnavailableError,
)


class EngineRuntimeStateProvider(RuntimeStateProvider):
    """从真实 State Engine 读取状态快照，不自行猜测或初始化状态。"""

    def __init__(self, engine: RuntimeStateEngine) -> None:
        self._engine = engine

    async def load(self, runtime_input: RuntimeInput) -> RuntimeStateContext:
        try:
            snapshot = await self._engine.load(self._engine.scope_key(runtime_input))
        except (StateNotInitializedError, StateStoreUnavailableError) as error:
            raise ContextProviderUnavailable("runtime state unavailable") from error
        return self._engine.to_context(snapshot)
