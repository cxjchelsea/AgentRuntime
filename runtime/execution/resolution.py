"""Resolve execution implementations from existing registries.

M5 never substitutes a different Skill / Workflow / Tool when the approved reference
cannot resolve. Multiple enabled versions are treated as ambiguous and fail closed.
"""

from __future__ import annotations

from typing import TypeVar

from runtime.execution.errors import (
    ExecutionImplementationTypeError,
    ExecutionRegistryResolutionError,
)
from runtime.execution.protocols import (
    SkillImplementation,
    ToolImplementation,
    WorkflowImplementation,
)
from runtime.registries import SkillRegistry, ToolRegistry, WorkflowRegistry
from runtime.registries.base import RegistryRecord
from runtime.registries.definitions import (
    SkillDefinition,
    ToolDefinition,
    WorkflowDefinition,
)

DefinitionT = TypeVar(
    "DefinitionT",
    SkillDefinition,
    WorkflowDefinition,
    ToolDefinition,
)


class ExecutionImplementationResolver:
    """Fail-closed resolution for approved execution references."""

    def __init__(
        self,
        *,
        skill_registry: SkillRegistry,
        workflow_registry: WorkflowRegistry,
        tool_registry: ToolRegistry,
    ) -> None:
        self._skill_registry = skill_registry
        self._workflow_registry = workflow_registry
        self._tool_registry = tool_registry

    def resolve_skill(self, skill_id: str) -> SkillImplementation:
        record = self._resolve_one_enabled(
            self._skill_registry.list(),
            item_id=skill_id,
            id_attr="skill_id",
            label="skill",
        )
        implementation = record.implementation_ref
        if not isinstance(implementation, SkillImplementation):
            raise ExecutionImplementationTypeError(
                "skill implementation_ref does not satisfy SkillImplementation"
            )
        return implementation

    def resolve_workflow(self, workflow_id: str) -> WorkflowImplementation:
        record = self._resolve_one_enabled(
            self._workflow_registry.list(),
            item_id=workflow_id,
            id_attr="workflow_id",
            label="workflow",
        )
        implementation = record.implementation_ref
        if not isinstance(implementation, WorkflowImplementation):
            raise ExecutionImplementationTypeError(
                "workflow implementation_ref does not satisfy WorkflowImplementation"
            )
        return implementation

    def resolve_tool(self, tool_id: str) -> ToolImplementation:
        record = self._resolve_one_enabled(
            self._tool_registry.list(),
            item_id=tool_id,
            id_attr="tool_id",
            label="tool",
        )
        implementation = record.implementation_ref
        if not isinstance(implementation, ToolImplementation):
            raise ExecutionImplementationTypeError(
                "tool implementation_ref does not satisfy ToolImplementation"
            )
        return implementation

    @staticmethod
    def _resolve_one_enabled(
        records: list[RegistryRecord[DefinitionT]],
        *,
        item_id: str,
        id_attr: str,
        label: str,
    ) -> RegistryRecord[DefinitionT]:
        if not item_id.strip():
            raise ExecutionRegistryResolutionError(
                f"{label} id must not be blank"
            )

        matches = [
            record
            for record in records
            if record.enabled
            and getattr(record.definition, "enabled", False)
            and getattr(record.definition, id_attr) == item_id
        ]
        if len(matches) != 1:
            raise ExecutionRegistryResolutionError(
                f"{label} must resolve to exactly one enabled registered version"
            )
        return matches[0]
