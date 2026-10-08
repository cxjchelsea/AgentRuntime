"""M5 internal execution contracts.

These types are owned by the Execution Framework. They are intentionally not exported
as Canonical main-chain contracts. M5 projects them into the existing ExecutionResult.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class StepExecutionStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    PREEMPTED = "PREEMPTED"


class ToolExecutionStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    UNAVAILABLE = "UNAVAILABLE"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class SkillExecutionStatus(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    PREEMPTED = "PREEMPTED"


class WorkflowExecutionStatus(str, Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    PREEMPTED = "PREEMPTED"


class ActivityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ToolInvocationRequest:
    tool_call_id: str
    tool_id: str
    input_payload: dict[str, Any]
    attempt: int = 1
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not self.tool_call_id.strip() or not self.tool_id.strip():
            raise ValueError("tool_call_id and tool_id must not be blank")
        if self.attempt < 1:
            raise ValueError("attempt must be >= 1")


@dataclass(frozen=True, slots=True)
class M5ToolResult:
    tool_call_id: str
    tool_id: str
    status: ToolExecutionStatus
    data: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    attempt: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tool_call_id.strip() or not self.tool_id.strip():
            raise ValueError("tool_call_id and tool_id must not be blank")
        if self.attempt < 1:
            raise ValueError("attempt must be >= 1")


@dataclass(frozen=True, slots=True)
class SkillExecutionRequest:
    step_execution_id: str
    step_id: str
    action: str
    skill_id: str
    parameters: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        values = (
            self.step_execution_id,
            self.step_id,
            self.action,
            self.skill_id,
        )
        if any(not value.strip() for value in values):
            raise ValueError("skill execution identifiers must not be blank")


@dataclass(frozen=True, slots=True)
class M5SkillResult:
    skill_id: str
    status: SkillExecutionStatus
    business_outputs: tuple[dict[str, Any], ...] = ()
    tool_results: tuple[M5ToolResult, ...] = ()
    events: tuple[dict[str, Any], ...] = ()
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.skill_id.strip():
            raise ValueError("skill_id must not be blank")


@dataclass(frozen=True, slots=True)
class WorkflowExecutionRequest:
    workflow_instance_id: str
    workflow_id: str
    event: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.workflow_instance_id.strip() or not self.workflow_id.strip():
            raise ValueError("workflow identifiers must not be blank")
        if self.event is not None and not self.event.strip():
            raise ValueError("event must not be blank")


@dataclass(frozen=True, slots=True)
class M5WorkflowResult:
    workflow_instance_id: str
    workflow_id: str
    status: WorkflowExecutionStatus
    current_step: str | None = None
    completed_steps: tuple[str, ...] = ()
    pending_step: str | None = None
    important_outputs: dict[str, Any] = field(default_factory=dict)
    tool_results: tuple[M5ToolResult, ...] = ()
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.workflow_instance_id.strip() or not self.workflow_id.strip():
            raise ValueError("workflow identifiers must not be blank")


@dataclass(frozen=True, slots=True)
class ExecutionErrorRecord:
    error_code: str
    stage: str
    recoverable: bool
    retryable: bool
    message: str
    timestamp: datetime
    step_id: str | None = None
    tool_id: str | None = None
    cause: str | None = None

    def __post_init__(self) -> None:
        if not self.error_code.strip() or not self.stage.strip():
            raise ValueError("error_code and stage must not be blank")


@dataclass(frozen=True, slots=True)
class ExecutionEventRecord:
    event_id: str
    execution_id: str
    event_type: str
    timestamp: datetime
    step_id: str | None = None
    tool_call_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        values = (self.event_id, self.execution_id, self.event_type)
        if any(not value.strip() for value in values):
            raise ValueError("execution event identifiers must not be blank")


@dataclass(frozen=True, slots=True)
class WorkflowCheckpoint:
    workflow_instance_id: str
    workflow_id: str
    current_step: str | None
    completed_steps: tuple[str, ...]
    pending_step: str | None
    important_outputs: dict[str, Any]
    updated_at: datetime

    def __post_init__(self) -> None:
        if not self.workflow_instance_id.strip() or not self.workflow_id.strip():
            raise ValueError("workflow checkpoint identifiers must not be blank")


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    execution_id: str
    plan_id: str
    request_id: str
    identity_scope: str
    status: str
    current_step: str | None = None
    step_results: tuple[dict[str, Any], ...] = ()
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        values = (
            self.execution_id,
            self.plan_id,
            self.request_id,
            self.identity_scope,
            self.status,
        )
        if any(not value.strip() for value in values):
            raise ValueError("execution record fields must not be blank")


@dataclass(frozen=True, slots=True)
class ActivityInstance:
    activity_id: str
    activity_type: str
    status: ActivityStatus
    started_at: datetime
    resource_id: str | None = None
    owner_session: str | None = None

    def __post_init__(self) -> None:
        if not self.activity_id.strip() or not self.activity_type.strip():
            raise ValueError("activity identifiers must not be blank")
