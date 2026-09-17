"""SchemaRegistry：登记 Core / Domain Schema 引用。"""

from runtime.registries.base import BaseRegistry, RegistryRecord
from runtime.registries.definitions import SchemaDefinition


class SchemaRegistry(BaseRegistry[SchemaDefinition]):
    """按 schema_id + version 注册。Domain Schema 不得改写 Core Contract。"""

    _expected_definition_type = SchemaDefinition

    def register(  # type: ignore[override]
        self,
        definition: SchemaDefinition,
        *,
        namespace: str | None = None,
        implementation_ref: object | None = None,
    ) -> None:
        """注册 SchemaDefinition。"""
        self._store(
            definition.schema_id,
            definition.version,
            definition,
            namespace=namespace or definition.namespace,
            implementation_ref=implementation_ref,
        )

    def get(
        self,
        item_id: str,
        version: str,
        *,
        namespace: str | None = None,
    ) -> RegistryRecord[SchemaDefinition]:
        """按 schema_id + version 查询。"""
        return super().get(item_id, version, namespace=namespace)
