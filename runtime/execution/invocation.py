"""M5-IU4 controlled invocation contracts.

These contracts define the Core boundary around real capability invocation. They do
not execute Skill / Workflow / Tool implementations by themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from runtime.execution.models import M5ToolResult
from runtime.execution.permission import PermissionDecisionStatus
from runtime.registries.definitions import ToolDefinition


class ToolPayloadValidationStatus(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ToolPayloadValidationDecision:
    status: ToolPayloadValidationStatus
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")


class ToolInputValidator(Protocol):
    def validate(
        self,
        tool_definition: ToolDefinition,
        input_payload: dict[str, Any],
    ) -> ToolPayloadValidationDecision:
        """Validate one exact approved Tool input before invocation."""


class ToolOutputValidator(Protocol):
    def validate(
        self,
        tool_definition: ToolDefinition,
        tool_result: M5ToolResult,
    ) -> ToolPayloadValidationDecision:
        """Validate one Tool result without upgrading a non-success status."""


class CapabilityInvocationIdentifierFactory(Protocol):
    def new_tool_call_id(
        self,
        *,
        step_execution_id: str,
        tool_id: str,
    ) -> str:
        """Create one traceable Tool call id."""

    def new_workflow_instance_id(
        self,
        *,
        step_execution_id: str,
        workflow_id: str,
    ) -> str:
        """Create one traceable fresh Workflow instance id."""


@dataclass(frozen=True, slots=True)
class ToolInvocationJournalEntry:
    tool_call_id: str
    tool_id: str
    tool_version: str
    result: M5ToolResult
    permission_status: PermissionDecisionStatus | None = None
    input_validation_status: ToolPayloadValidationStatus | None = None
    output_validation_status: ToolPayloadValidationStatus | None = None

    def __post_init__(self) -> None:
        values = (self.tool_call_id, self.tool_id, self.tool_version)
        if any(not value.strip() for value in values):
            raise ValueError("Tool journal identifiers must not be blank")
        if self.result.tool_call_id != self.tool_call_id:
            raise ValueError("Tool journal result tool_call_id must match")
        if self.result.tool_id != self.tool_id:
            raise ValueError("Tool journal result tool_id must match")


class ApprovedToolInvoker(Protocol):
    async def invoke(
        self,
        *,
        tool_id: str,
        input_payload: dict[str, Any],
    ) -> M5ToolResult:
        """Invoke only a Tool already approved/resolved for the current step."""


class ToolInvocationJournalReader(Protocol):
    def entries(self) -> tuple[ToolInvocationJournalEntry, ...]:
        """Return the Core-owned authoritative Tool invocation journal."""
