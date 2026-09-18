"""M4 StrategyRegistry：只登记 StrategyDefinition，不做策略选择。"""

from runtime.registries.base import BaseRegistry, RegistryRecord
from runtime.registries.definitions import StrategyDefinition


class StrategyRegistry(BaseRegistry[StrategyDefinition]):
    """按 strategy_id + version 注册。具体 Strategy 值由 Domain 注入。"""

    _expected_definition_type = StrategyDefinition

    def register(  # type: ignore[override]
        self,
        definition: StrategyDefinition,
        *,
        namespace: str | None = None,
        implementation_ref: object | None = None,
    ) -> None:
        """注册 StrategyDefinition；不重新理解、不选择、不批准计划。"""
        self._store(
            definition.strategy_id,
            definition.version,
            definition,
            namespace=namespace,
            implementation_ref=implementation_ref,
            enabled=definition.enabled,
        )

    def get(
        self,
        item_id: str,
        version: str,
        *,
        namespace: str | None = None,
    ) -> RegistryRecord[StrategyDefinition]:
        """按 strategy_id + version 精确查询。"""
        return super().get(item_id, version, namespace=namespace)
