"""M5 persistence, checkpoint, idempotency, and lock protocols."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from runtime.execution.models import ExecutionRecord, M5ToolResult, WorkflowCheckpoint


class IdempotencyStatus(str, Enum):
    RESERVED = "RESERVED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    key: str
    execution_id: str
    step_id: str
    step_execution_id: str
    tool_id: str
    tool_version: str
    operation_key: str
    operation_fingerprint: str
    status: IdempotencyStatus
    tool_call_id: str | None = None
    result_reference: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("idempotency key must not be blank")
        values = (
            self.execution_id,
            self.step_id,
            self.step_execution_id,
            self.tool_id,
            self.tool_version,
            self.operation_key,
            self.operation_fingerprint,
        )
        if any(not value.strip() for value in values):
            raise ValueError("idempotency provenance fields must not be blank")
        if self.status is IdempotencyStatus.COMPLETED and (
            self.tool_call_id is None
            or not self.tool_call_id.strip()
            or self.result_reference is None
            or not self.result_reference.strip()
        ):
            raise ValueError(
                "COMPLETED idempotency record requires tool_call_id/result_reference"
            )
        if self.status is not IdempotencyStatus.COMPLETED and (
            self.result_reference is not None
        ):
            raise ValueError(
                "only COMPLETED idempotency record may carry result_reference"
            )


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
        tool_call_id: str,
        result_reference: str,
    ) -> None:
        """Mark a reserved side effect as completed without replaying it."""

    async def mark_failed(self, key: str) -> None:
        """Mark a reserved operation as definitively failed with no side effect."""

    async def reopen_failed(self, record: IdempotencyRecord) -> bool:
        """Atomically transition matching FAILED provenance back to RESERVED.

        The supplied record describes the exact operation provenance to reopen.
        Return False when the stored record is not FAILED or provenance differs.
        """

    async def mark_unknown(self, key: str) -> None:
        """Record that an external side effect may have happened but is unconfirmed."""


class IdempotencyCompletionStatus(str, Enum):
    COMPLETED = "COMPLETED"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class IdempotencyCompletionDecision:
    status: IdempotencyCompletionStatus
    reason_codes: tuple[str, ...]
    completed_record: IdempotencyRecord | None = None

    def __post_init__(self) -> None:
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        if self.status is IdempotencyCompletionStatus.COMPLETED:
            if (
                self.completed_record is None
                or self.completed_record.status is not IdempotencyStatus.COMPLETED
            ):
                raise ValueError(
                    "COMPLETED idempotency completion requires COMPLETED record"
                )
        elif self.completed_record is not None:
            raise ValueError(
                "non-COMPLETED idempotency completion must not expose record"
            )


class IdempotencyCompletionAuthority(Protocol):
    async def complete(
        self,
        *,
        reserved_record: IdempotencyRecord,
        result: M5ToolResult,
    ) -> IdempotencyCompletionDecision:
        """Atomically persist trusted result and RESERVED -> COMPLETED.

        The returned COMPLETED record must preserve exact operation provenance and
        bind result.tool_call_id plus an opaque recoverable result_reference.
        CONFLICT/UNKNOWN must not claim completion.
        """


class IdempotencyResultResolver(Protocol):
    async def resolve_completed(
        self,
        record: IdempotencyRecord,
    ) -> M5ToolResult | None:
        """Resolve a trusted completed Tool result without re-invoking the Tool."""


class ResourceLockProvider(Protocol):
    """Legacy readiness seed retained for backward compatibility.

    M5-IU8 formal lock authority must use runtime.execution.resource_lock.
    The bool/None surface is intentionally insufficient for audited lock decisions.
    """

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
