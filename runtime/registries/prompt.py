"""PromptRegistry：只登记 Prompt 资产。"""

from runtime.registries.base import BaseRegistry, RegistryRecord
from runtime.registries.definitions import PromptDefinition


class PromptRegistry(BaseRegistry[PromptDefinition]):
    """按 prompt_id + version 注册。不调用 LLM，不拼接业务 Prompt。"""

    _expected_definition_type = PromptDefinition

    def register(  # type: ignore[override]
        self,
        definition: PromptDefinition,
        *,
        namespace: str | None = None,
        implementation_ref: object | None = None,
    ) -> None:
        """注册 PromptDefinition。"""
        self._store(
            definition.prompt_id,
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
    ) -> RegistryRecord[PromptDefinition]:
        """按 prompt_id + version 查询。"""
        return super().get(item_id, version, namespace=namespace)
