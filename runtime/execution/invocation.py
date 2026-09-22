"""M5-IU4 controlled invocation contracts.

These contracts define the Core boundary around real capability invocation. They do
not execute Skill / Workflow / Tool implementations by themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
class ToolAttemptObservation:
    """One physical attempt inside one logical Tool invocation."""

    logical_tool_call_id: str
    tool_id: str
    tool_version: str
    physical_attempt: int
    result: M5ToolResult
    operation_key: str | None = None
    operation_fingerprint: str | None = None
    idempotency_key: str | None = None
    raw_result: M5ToolResult | None = None
    permission_status: PermissionDecisionStatus | None = None
    input_validation_status: ToolPayloadValidationStatus | None = None
    output_validation_status: ToolPayloadValidationStatus | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def __post_init__(self) -> None:
        values = (self.logical_tool_call_id, self.tool_id, self.tool_version)
        if any(not value.strip() for value in values):
            raise ValueError("Tool attempt identifiers must not be blank")
        if self.physical_attempt < 1:
            raise ValueError("physical_attempt must be >= 1")
        if self.operation_key is not None and not self.operation_key.strip():
            raise ValueError("operation_key must not be blank when present")
        if (
            self.operation_fingerprint is not None
            and not self.operation_fingerprint.strip()
        ):
            raise ValueError(
                "operation_fingerprint must not be blank when present"
            )
        if (
            self.operation_fingerprint is not None
            and not self.operation_fingerprint.strip()
        ):
            raise ValueError(
                "operation_fingerprint must not be blank when present"
            )
        if (self.operation_key is None) != (
            self.operation_fingerprint is None
        ):
            raise ValueError(
                "operation_key and operation_fingerprint must be present together"
            )
        if self.idempotency_key is not None and not self.idempotency_key.strip():
            raise ValueError("idempotency_key must not be blank when present")
        if self.result.tool_call_id != self.logical_tool_call_id:
            raise ValueError("Tool attempt result tool_call_id must match logical call")
        if self.result.tool_id != self.tool_id:
            raise ValueError("Tool attempt result tool_id must match")
        if self.result.attempt != self.physical_attempt:
            raise ValueError("Tool attempt result attempt must match physical_attempt")
        if self.raw_result is not None:
            if self.raw_result.tool_call_id != self.logical_tool_call_id:
                raise ValueError(
                    "Tool attempt raw_result tool_call_id must match logical call"
                )
            if self.raw_result.tool_id != self.tool_id:
                raise ValueError("Tool attempt raw_result tool_id must match")
            if self.raw_result.attempt != self.physical_attempt:
                raise ValueError(
                    "Tool attempt raw_result attempt must match physical_attempt"
                )
        if (
            self.started_at is not None
            and self.finished_at is not None
            and self.finished_at < self.started_at
        ):
            raise ValueError("Tool attempt finished_at cannot precede started_at")


class PhysicalToolAttemptExecutor(Protocol):
    async def execute_physical_attempt(
        self,
        *,
        logical_tool_call_id: str,
        tool_id: str,
        input_payload: dict[str, Any],
        physical_attempt: int,
        idempotency_key: str | None,
        operation_key: str | None,
        operation_fingerprint: str | None,
    ) -> ToolAttemptObservation:
        """Execute exactly one physical attempt; never decide whether to retry."""


@dataclass(frozen=True, slots=True)
class ToolInvocationJournalEntry:
    tool_call_id: str
    tool_id: str
    tool_version: str
    result: M5ToolResult
    raw_result: M5ToolResult | None = None
    permission_status: PermissionDecisionStatus | None = None
    input_validation_status: ToolPayloadValidationStatus | None = None
    output_validation_status: ToolPayloadValidationStatus | None = None
    operation_key: str | None = None
    operation_fingerprint: str | None = None
    idempotency_key: str | None = None
    attempts: tuple[ToolAttemptObservation, ...] = ()

    def __post_init__(self) -> None:
        values = (self.tool_call_id, self.tool_id, self.tool_version)
        if any(not value.strip() for value in values):
            raise ValueError("Tool journal identifiers must not be blank")
        if self.result.tool_call_id != self.tool_call_id:
            raise ValueError("Tool journal result tool_call_id must match")
        if self.result.tool_id != self.tool_id:
            raise ValueError("Tool journal result tool_id must match")
        if self.raw_result is not None:
            if self.raw_result.tool_call_id != self.tool_call_id:
                raise ValueError("Tool journal raw_result tool_call_id must match")
            if self.raw_result.tool_id != self.tool_id:
                raise ValueError("Tool journal raw_result tool_id must match")
        if self.operation_key is not None and not self.operation_key.strip():
            raise ValueError("operation_key must not be blank when present")
        if (self.operation_key is None) != (
            self.operation_fingerprint is None
        ):
            raise ValueError(
                "operation_key and operation_fingerprint must be present together"
            )
        if self.idempotency_key is not None and not self.idempotency_key.strip():
            raise ValueError("idempotency_key must not be blank when present")
        if self.attempts:
            expected_attempts = tuple(range(1, len(self.attempts) + 1))
            observed_attempts = tuple(
                item.physical_attempt for item in self.attempts
            )
            if observed_attempts != expected_attempts:
                raise ValueError(
                    "Tool journal physical attempts must be contiguous from 1"
                )
            for attempt in self.attempts:
                if attempt.logical_tool_call_id != self.tool_call_id:
                    raise ValueError(
                        "Tool journal attempt logical_tool_call_id must match"
                    )
                if attempt.tool_id != self.tool_id:
                    raise ValueError("Tool journal attempt tool_id must match")
                if attempt.tool_version != self.tool_version:
                    raise ValueError("Tool journal attempt tool_version must match")
                if attempt.operation_key != self.operation_key:
                    raise ValueError(
                        "Tool journal attempt operation_key must stay stable"
                    )
                if attempt.operation_fingerprint != self.operation_fingerprint:
                    raise ValueError(
                        "Tool journal attempt operation_fingerprint must stay stable"
                    )
                if attempt.idempotency_key != self.idempotency_key:
                    raise ValueError(
                        "Tool journal attempt idempotency_key must stay stable"
                    )
            if self.result != self.attempts[-1].result:
                raise ValueError(
                    "Tool journal result must equal the final physical attempt result"
                )
            if self.raw_result != self.attempts[-1].raw_result:
                raise ValueError(
                    "Tool journal raw_result must equal final attempt raw_result"
                )


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
