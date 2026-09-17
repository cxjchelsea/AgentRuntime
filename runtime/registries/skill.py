"""SkillRegistry：只登记 Skill 定义与实现引用。"""

from runtime.registries.base import BaseRegistry, RegistryRecord
from runtime.registries.definitions import SkillDefinition


class SkillRegistry(BaseRegistry[SkillDefinition]):
    """按 skill_id + version 注册。不执行 Skill。"""

    _expected_definition_type = SkillDefinition

    def register(  # type: ignore[override]
        self,
        definition: SkillDefinition,
        *,
        namespace: str | None = None,
        implementation_ref: object | None = None,
    ) -> None:
        """注册 SkillDefinition。"""
        self._store(
            definition.skill_id,
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
    ) -> RegistryRecord[SkillDefinition]:
        """按 skill_id + version 查询。"""
        return super().get(item_id, version, namespace=namespace)
