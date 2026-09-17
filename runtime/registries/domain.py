"""DomainRegistry：登记 DomainManifest。"""

from runtime.registries.base import BaseRegistry, RegistryRecord
from runtime.registries.definitions import DomainManifest


class DomainRegistry(BaseRegistry[DomainManifest]):
    """按 domain_id + version 注册。不加载、不执行 Domain Package。"""

    _expected_definition_type = DomainManifest

    def register(  # type: ignore[override]
        self,
        definition: DomainManifest,
        *,
        namespace: str | None = None,
        implementation_ref: object | None = None,
    ) -> None:
        """注册 DomainManifest。"""
        self._store(
            definition.domain_id,
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
    ) -> RegistryRecord[DomainManifest]:
        """按 domain_id + version 查询。"""
        return super().get(item_id, version, namespace=namespace)
