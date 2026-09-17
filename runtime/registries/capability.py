"""CapabilityRegistry：M9 业务能力目录。"""

from runtime.registries.base import BaseRegistry, RegistryRecord
from runtime.registries.definitions import CapabilityDefinition

__all__ = ["CapabilityDefinition", "CapabilityRegistry"]


class CapabilityRegistry(BaseRegistry[CapabilityDefinition]):
    """按 capability_id + version 注册。不执行能力实现。"""

    _expected_definition_type = CapabilityDefinition

    def register(  # type: ignore[override]
        self,
        definition: CapabilityDefinition,
        *,
        namespace: str | None = None,
        implementation_ref: object | None = None,
    ) -> None:
        """注册 CapabilityDefinition。"""
        self._store(
            definition.capability_id,
            definition.version,
            definition,
            namespace=namespace,
            implementation_ref=implementation_ref,
        )

    def get(
        self,
        item_id: str,
        version: str,
        *,
        namespace: str | None = None,
    ) -> RegistryRecord[CapabilityDefinition]:
        """按 capability_id + version 查询。"""
        return super().get(item_id, version, namespace=namespace)
