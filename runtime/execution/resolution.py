"""Exact execution implementation resolution for approved capability versions.

M5 resolves only the capability id + version already frozen in ApprovedActionPlan.
It never selects a newer/current/alternative version and never substitutes another
Skill / Workflow / Tool.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from runtime.execution.errors import (
    ExecutionCapabilityDisabledError,
    ExecutionCapabilityNotFoundError,
    ExecutionImplementationMissingError,
    ExecutionImplementationTypeError,
    ExecutionRegistryResolutionError,
)
from runtime.execution.protocols import (
    SkillImplementation,
    ToolImplementation,
    WorkflowImplementation,
)
from runtime.registries import (
    BaseRegistry,
    RegistryItemNotFoundError,
    SkillDefinition,
    SkillRegistry,
    ToolDefinition,
    ToolRegistry,
    WorkflowDefinition,
    WorkflowRegistry,
)
from runtime.registries.base import RegistryRecord

DefinitionT = TypeVar(
    "DefinitionT",
    SkillDefinition,
    WorkflowDefinition,
    ToolDefinition,
)
ImplementationT = TypeVar(
    "ImplementationT",
    SkillImplementation,
    WorkflowImplementation,
    ToolImplementation,
)


@dataclass(frozen=True, slots=True)
class ResolvedExecutionImplementation(Generic[DefinitionT, ImplementationT]):
    """Exact Registry definition + runtime implementation binding."""

    definition: DefinitionT
    implementation_ref: ImplementationT


class ExecutionImplementationResolver:
    """Resolve one exact approved capability id + version, fail closed."""

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

    def resolve_skill(
        self,
        skill_id: str,
        version: str,
    ) -> ResolvedExecutionImplementation[SkillDefinition, SkillImplementation]:
        record = self._resolve_exact(
            self._skill_registry,
            item_id=skill_id,
            version=version,
            label="skill",
        )
        implementation = record.implementation_ref
        if implementation is None:
            raise ExecutionImplementationMissingError(
                "skill implementation_ref is missing"
            )
        if not isinstance(implementation, SkillImplementation):
            raise ExecutionImplementationTypeError(
                "skill implementation_ref does not satisfy SkillImplementation"
            )
        return ResolvedExecutionImplementation(
            definition=record.definition,
            implementation_ref=implementation,
        )

    def resolve_workflow(
        self,
        workflow_id: str,
        version: str,
    ) -> ResolvedExecutionImplementation[WorkflowDefinition, WorkflowImplementation]:
        record = self._resolve_exact(
            self._workflow_registry,
            item_id=workflow_id,
            version=version,
            label="workflow",
        )
        implementation = record.implementation_ref
        if implementation is None:
            raise ExecutionImplementationMissingError(
                "workflow implementation_ref is missing"
            )
        if not isinstance(implementation, WorkflowImplementation):
            raise ExecutionImplementationTypeError(
                "workflow implementation_ref does not satisfy WorkflowImplementation"
            )
        return ResolvedExecutionImplementation(
            definition=record.definition,
            implementation_ref=implementation,
        )

    def resolve_tool(
        self,
        tool_id: str,
        version: str,
    ) -> ResolvedExecutionImplementation[ToolDefinition, ToolImplementation]:
        record = self._resolve_exact(
            self._tool_registry,
            item_id=tool_id,
            version=version,
            label="tool",
        )
        implementation = record.implementation_ref
        if implementation is None:
            raise ExecutionImplementationMissingError(
                "tool implementation_ref is missing"
            )
        if not isinstance(implementation, ToolImplementation):
            raise ExecutionImplementationTypeError(
                "tool implementation_ref does not satisfy ToolImplementation"
            )
        return ResolvedExecutionImplementation(
            definition=record.definition,
            implementation_ref=implementation,
        )

    @staticmethod
    def _resolve_exact(
        registry: BaseRegistry[DefinitionT],
        *,
        item_id: str,
        version: str,
        label: str,
    ) -> RegistryRecord[DefinitionT]:
        if not item_id.strip():
            raise ExecutionRegistryResolutionError(f"{label} id must not be blank")
        if not version.strip():
            raise ExecutionRegistryResolutionError(
                f"{label} approved version must not be blank"
            )

        try:
            record = registry.get(item_id, version)
        except RegistryItemNotFoundError as exc:
            raise ExecutionCapabilityNotFoundError(
                f"{label} approved version is not registered"
            ) from exc

        if not record.enabled or not getattr(record.definition, "enabled", False):
            raise ExecutionCapabilityDisabledError(
                f"{label} approved version is disabled"
            )
        return record
