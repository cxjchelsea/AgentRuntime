"""WorkflowRegistry：只登记 Workflow 定义。"""

from runtime.registries.base import BaseRegistry, RegistryRecord
from runtime.registries.definitions import WorkflowDefinition


class WorkflowRegistry(BaseRegistry[WorkflowDefinition]):
    """按 workflow_id + version 注册。不执行 Workflow，不管实例。"""

    _expected_definition_type = WorkflowDefinition

    def register(  # type: ignore[override]
        self,
        definition: WorkflowDefinition,
        *,
        namespace: str | None = None,
        implementation_ref: object | None = None,
    ) -> None:
        """注册 WorkflowDefinition。"""
        self._store(
            definition.workflow_id,
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
    ) -> RegistryRecord[WorkflowDefinition]:
        """按 workflow_id + version 查询。"""
        return super().get(item_id, version, namespace=namespace)
