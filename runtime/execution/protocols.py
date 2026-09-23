"""M5 execution implementation protocols.

Registry implementation_ref values must satisfy the corresponding runtime-checkable
protocol before M5 invokes them. These protocols define invocation shape only; they do
not authorize planning changes or capability substitution.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from runtime.contracts.execution import ExecutionContext
from runtime.execution.invocation import ApprovedToolInvoker
from runtime.execution.models import (
    M5SkillResult,
    M5ToolResult,
    M5WorkflowResult,
    SkillExecutionRequest,
    ToolInvocationRequest,
    WorkflowExecutionRequest,
)


@runtime_checkable
class ToolImplementation(Protocol):
    async def invoke(
        self,
        request: ToolInvocationRequest,
        execution_context: ExecutionContext,
    ) -> M5ToolResult:
        """Invoke exactly the registered Tool represented by request.tool_id."""


@runtime_checkable
class SkillImplementation(Protocol):
    async def execute(
        self,
        request: SkillExecutionRequest,
        execution_context: ExecutionContext,
        tool_invoker: ApprovedToolInvoker,
    ) -> M5SkillResult:
        """Execute exactly the registered Skill represented by request.skill_id."""


@runtime_checkable
class WorkflowImplementation(Protocol):
    async def start(
        self,
        request: WorkflowExecutionRequest,
        execution_context: ExecutionContext,
        tool_invoker: ApprovedToolInvoker,
    ) -> M5WorkflowResult:
        """Start one registered Workflow instance."""

    async def resume(
        self,
        request: WorkflowResumeRequest,
        execution_context: ExecutionContext,
        tool_invoker: ApprovedToolInvoker,
    ) -> M5WorkflowResult:
        """Resume the same exact registered Workflow instance from durable checkpoint authority."""
