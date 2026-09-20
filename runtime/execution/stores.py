"""M5 persistence, checkpoint, idempotency, and lock protocols."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from runtime.execution.models import ExecutionRecord, WorkflowCheckpoint


class IdempotencyStatus(str, Enum):
    RESERVED = "RESERVED"
    COMPLETED = "COMPLETED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    key: str
    execution_id: str
    step_id: str
    status: IdempotencyStatus
    tool_call_id: str | None = None
    result_reference: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("idempotency key must not be blank")
        if not self.execution_id.strip() or not self.step_id.strip():
            raise ValueError("execution_id and step_id must not be blank")


class ExecutionStateStore(Protocol):
    async def save(self, record: ExecutionRecord) -> None:
        """Persist the latest execution observation."""

    async def load(self, execution_id: str) -> ExecutionRecord | None:
        """Load one execution by id."""


class WorkflowCheckpointStore(Protocol):
    async def save(self, checkpoint: WorkflowCheckpoint) -> None:
        """Persist a workflow checkpoint."""

    async def load(self, workflow_instance_id: str) -> WorkflowCheckpoint | None:
        """Load a workflow checkpoint."""


class IdempotencyStore(Protocol):
    async def get(self, key: str) -> IdempotencyRecord | None:
        """Read an idempotency record."""

    async def reserve(self, record: IdempotencyRecord) -> bool:
        """Atomically reserve a key; return False when it already exists."""

    async def mark_completed(
        self,
        key: str,
        *,
        tool_call_id: str | None,
        result_reference: str | None,
    ) -> None:
        """Mark a reserved side effect as completed without replaying it."""

    async def mark_unknown(self, key: str) -> None:
        """Record that an external side effect may have happened but is unconfirmed."""


class ResourceLockProvider(Protocol):
    async def acquire(
        self,
        resource_id: str,
        *,
        owner_id: str,
    ) -> bool:
        """Acquire a resource lock without silently stealing another owner's lock."""

    async def release(
        self,
        resource_id: str,
        *,
        owner_id: str,
    ) -> None:
        """Release a lock owned by owner_id."""
