"""PolicyRegistry：只登记规则定义。"""

from runtime.registries.base import BaseRegistry, RegistryRecord
from runtime.registries.definitions import PolicyDefinition


class PolicyRegistry(BaseRegistry[PolicyDefinition]):
    """按 rule_id + version 注册。不在 Registry 内执行 Policy。"""

    _expected_definition_type = PolicyDefinition

    def register(  # type: ignore[override]
        self,
        definition: PolicyDefinition,
        *,
        namespace: str | None = None,
        implementation_ref: object | None = None,
    ) -> None:
        """注册 PolicyDefinition。"""
        self._store(
            definition.rule_id,
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
    ) -> RegistryRecord[PolicyDefinition]:
        """按 rule_id + version 查询。"""
        return super().get(item_id, version, namespace=namespace)
