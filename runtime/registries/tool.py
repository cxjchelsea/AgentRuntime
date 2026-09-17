"""ToolRegistry：只登记 Tool 定义与 adapter 引用。"""

from runtime.registries.base import BaseRegistry, RegistryRecord
from runtime.registries.definitions import ToolDefinition


class ToolRegistry(BaseRegistry[ToolDefinition]):
    """按 tool_id + version 注册。不调用 Tool，不重试，不产生副作用。"""

    _expected_definition_type = ToolDefinition

    def register(  # type: ignore[override]
        self,
        definition: ToolDefinition,
        *,
        namespace: str | None = None,
        implementation_ref: object | None = None,
    ) -> None:
        """注册 ToolDefinition。"""
        self._store(
            definition.tool_id,
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
    ) -> RegistryRecord[ToolDefinition]:
        """按 tool_id + version 查询。"""
        return super().get(item_id, version, namespace=namespace)
