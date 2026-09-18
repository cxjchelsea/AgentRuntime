"""M4 ActionRegistry：只登记 ActionDefinition，不执行 Action。"""

from runtime.registries.base import BaseRegistry, RegistryRecord
from runtime.registries.definitions import ActionDefinition


class ActionRegistry(BaseRegistry[ActionDefinition]):
    """按 action_id + version 注册。具体 Action 值由 Domain 注入。"""

    _expected_definition_type = ActionDefinition

    def register(  # type: ignore[override]
        self,
        definition: ActionDefinition,
        *,
        namespace: str | None = None,
        implementation_ref: object | None = None,
    ) -> None:
        """注册 ActionDefinition；不批准、不规划、不执行。"""
        self._store(
            definition.action_id,
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
    ) -> RegistryRecord[ActionDefinition]:
        """按 action_id + version 精确查询。"""
        return super().get(item_id, version, namespace=namespace)
