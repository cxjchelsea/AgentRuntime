"""M5-IU6 CA-02 Tool-attempt, idempotency, sequence, and finalization contracts.

These are Core authority boundaries. They do not implement retry loops, workflow
replay, lifecycle mutation, persistence/recovery, aggregation, or M6.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from runtime.execution.invocation import ToolInvocationJournalEntry
from runtime.execution.models import StepExecutionStatus
from runtime.execution.reliability import (
    ReplaySafetyDecision,
    RetryDecision,
)
from runtime.execution.result_collection import StepAttemptObservation
from runtime.execution.stores import IdempotencyRecord, IdempotencyStatus


@dataclass(frozen=True, slots=True)
class ToolOperationCorrelationKey:
    """Stable Core-owned identity for one semantic Tool operation."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("Tool operation correlation key must not be blank")


class ToolOperationCorrelationStatus(str, Enum):
    NEW = "NEW"
    CORRELATED = "CORRELATED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ToolOperationCorrelationDecision:
    status: ToolOperationCorrelationStatus
    reason_codes: tuple[str, ...]
    operation_key: ToolOperationCorrelationKey | None = None
    logical_tool_call_id: str | None = None
    operation_occurrence: int | None = None

    def __post_init__(self) -> None:
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        identified = self.status in (
            ToolOperationCorrelationStatus.NEW,
            ToolOperationCorrelationStatus.CORRELATED,
        )
        if identified:
            if self.operation_key is None:
                raise ValueError("identified Tool operation requires operation_key")
            if self.logical_tool_call_id is None or not self.logical_tool_call_id.strip():
                raise ValueError(
                    "identified Tool operation requires logical_tool_call_id"
                )
            if self.operation_occurrence is None or self.operation_occurrence < 1:
                raise ValueError(
                    "identified Tool operation requires operation_occurrence >= 1"
                )
        elif (
            self.operation_key is not None
            or self.logical_tool_call_id is not None
            or self.operation_occurrence is not None
        ):
            raise ValueError("UNKNOWN Tool correlation must not invent identity")


class ToolOperationOccurrenceStatus(str, Enum):
    CLAIMED = "CLAIMED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ToolOperationOccurrenceDecision:
    status: ToolOperationOccurrenceStatus
    reason_codes: tuple[str, ...]
    occurrence: int | None = None

    def __post_init__(self) -> None:
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        if self.status is ToolOperationOccurrenceStatus.CLAIMED:
            if self.occurrence is None or self.occurrence < 1:
                raise ValueError("CLAIMED Tool occurrence requires occurrence >= 1")
        elif self.occurrence is not None:
            raise ValueError("UNKNOWN Tool occurrence must not invent occurrence")


class ToolOperationOccurrenceAuthority(Protocol):
    async def claim_next(
        self,
        *,
        step_execution_id: str,
        step_attempt_number: int,
        tool_id: str,
        tool_version: str,
        operation_fingerprint: str,
    ) -> ToolOperationOccurrenceDecision:
        """Atomically assign the next Core-owned occurrence for one fingerprint."""


class ToolOperationCorrelator(Protocol):
    def correlate(
        self,
        *,
        step_execution_id: str,
        step_attempt_number: int,
        tool_id: str,
        tool_version: str,
        operation_fingerprint: str,
        operation_occurrence: int,
        prior_attempt_journal: tuple[ToolInvocationJournalEntry, ...],
    ) -> ToolOperationCorrelationDecision:
        """Correlate one Tool operation across Step attempts.

        operation_occurrence is Core-owned and counts occurrences among the same
        tool/version/fingerprint within one Step attempt. This distinguishes two
        intentional identical calls while allowing occurrence N to correlate to
        occurrence N from a prior Step attempt. Any divergent/ambiguous sequence
        must return UNKNOWN rather than inventing a correlation.
        """


class ToolOperationFingerprintFactory(Protocol):
    def fingerprint(
        self,
        *,
        tool_id: str,
        tool_version: str,
        input_payload: dict[str, Any],
    ) -> str:
        """Return a stable normalized operation fingerprint."""


class IdempotencyKeyFactory(Protocol):
    def create(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
        operation_key: ToolOperationCorrelationKey,
        tool_id: str,
        tool_version: str,
        operation_fingerprint: str,
    ) -> str:
        """Create a stable idempotency key for one correlated Tool operation."""


class IdempotencyPreflightStatus(str, Enum):
    RESERVE_NEW = "RESERVE_NEW"
    RECOVER_COMPLETED = "RECOVER_COMPLETED"
    WAIT_IN_FLIGHT = "WAIT_IN_FLIGHT"
    REOPEN_FAILED = "REOPEN_FAILED"
    FAIL_UNKNOWN = "FAIL_UNKNOWN"
    REJECT_PROVENANCE = "REJECT_PROVENANCE"


@dataclass(frozen=True, slots=True)
class IdempotencyPreflightDecision:
    status: IdempotencyPreflightStatus
    reason_codes: tuple[str, ...]
    existing_record: IdempotencyRecord | None = None

    def __post_init__(self) -> None:
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        needs_existing = self.status in (
            IdempotencyPreflightStatus.RECOVER_COMPLETED,
            IdempotencyPreflightStatus.WAIT_IN_FLIGHT,
            IdempotencyPreflightStatus.REOPEN_FAILED,
            IdempotencyPreflightStatus.FAIL_UNKNOWN,
            IdempotencyPreflightStatus.REJECT_PROVENANCE,
        )
        if needs_existing and self.existing_record is None:
            raise ValueError(
                "idempotency preflight status requires existing_record"
            )
        if (
            self.status is IdempotencyPreflightStatus.RESERVE_NEW
            and self.existing_record is not None
        ):
            raise ValueError("RESERVE_NEW must not carry existing_record")

        expected_status = {
            IdempotencyPreflightStatus.RECOVER_COMPLETED: IdempotencyStatus.COMPLETED,
            IdempotencyPreflightStatus.WAIT_IN_FLIGHT: IdempotencyStatus.RESERVED,
            IdempotencyPreflightStatus.REOPEN_FAILED: IdempotencyStatus.FAILED,
            IdempotencyPreflightStatus.FAIL_UNKNOWN: IdempotencyStatus.UNKNOWN,
        }.get(self.status)
        if (
            expected_status is not None
            and self.existing_record is not None
            and self.existing_record.status is not expected_status
        ):
            raise ValueError(
                "idempotency preflight status does not match record status"
            )


class IdempotencyPreflightEvaluator(Protocol):
    def evaluate(
        self,
        *,
        existing_record: IdempotencyRecord | None,
        expected_execution_id: str,
        expected_step_execution_id: str,
        expected_tool_id: str,
        expected_tool_version: str,
        expected_operation_key: str,
        expected_operation_fingerprint: str,
    ) -> IdempotencyPreflightDecision:
        """Classify existing idempotency state after validation/permission/deadline.

        Provenance mismatch must be REJECT_PROVENANCE. UNKNOWN must never be
        converted to RESERVE_NEW/REOPEN_FAILED.
        """


class StepAttemptSequenceStatus(str, Enum):
    CLAIMED = "CLAIMED"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class StepAttemptSequenceDecision:
    status: StepAttemptSequenceStatus
    step_execution_id: str
    expected_current_attempt: int
    reason_codes: tuple[str, ...]
    next_attempt: int | None = None
    claim_token: str | None = None

    def __post_init__(self) -> None:
        if not self.step_execution_id.strip():
            raise ValueError("step_execution_id must not be blank")
        if self.expected_current_attempt < 1:
            raise ValueError("expected_current_attempt must be >= 1")
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        if self.status is StepAttemptSequenceStatus.CLAIMED:
            if self.next_attempt != self.expected_current_attempt + 1:
                raise ValueError("CLAIMED next_attempt must increment by exactly one")
            if self.claim_token is None or not self.claim_token.strip():
                raise ValueError("CLAIMED attempt requires claim_token")
        elif self.next_attempt is not None or self.claim_token is not None:
            raise ValueError("non-CLAIMED sequence decision must not invent claim")


class StepAttemptSequenceAuthority(Protocol):
    async def current_attempt(self, step_execution_id: str) -> int | None:
        """Return the currently committed Step attempt number, if known."""

    async def claim_next(
        self,
        *,
        step_execution_id: str,
        expected_current_attempt: int,
    ) -> StepAttemptSequenceDecision:
        """Atomically claim expected_current_attempt + 1 or report conflict/unknown."""


class StepReliabilityDisposition(str, Enum):
    RETRY = "RETRY"
    KEEP_RUNNING = "KEEP_RUNNING"
    WAIT_RECOVERY = "WAIT_RECOVERY"
    FINALIZE = "FINALIZE"
    ABORT_UNKNOWN = "ABORT_UNKNOWN"


@dataclass(frozen=True, slots=True)
class StepReliabilityDecision:
    disposition: StepReliabilityDisposition
    reason_codes: tuple[str, ...]
    next_attempt: int | None = None

    def __post_init__(self) -> None:
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        if self.disposition is StepReliabilityDisposition.RETRY:
            if self.next_attempt is None or self.next_attempt < 2:
                raise ValueError("RETRY disposition requires next_attempt >= 2")
        elif self.next_attempt is not None:
            raise ValueError("non-RETRY disposition must not carry next_attempt")


class StepReliabilityEvaluator(Protocol):
    def evaluate(
        self,
        *,
        observation: StepAttemptObservation,
        replay_safety: ReplaySafetyDecision | None,
        retry_decision: RetryDecision | None,
    ) -> StepReliabilityDecision:
        """Decide retry/continue/finalization intent without mutating lifecycle."""


class StepFinalizationDisposition(str, Enum):
    FINALIZE = "FINALIZE"
    KEEP_RUNNING = "KEEP_RUNNING"
    WAIT_RECOVERY = "WAIT_RECOVERY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class StepFinalizationDecision:
    disposition: StepFinalizationDisposition
    reason_codes: tuple[str, ...]
    terminal_status: StepExecutionStatus | None = None

    def __post_init__(self) -> None:
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        if self.disposition is StepFinalizationDisposition.FINALIZE:
            allowed = {
                StepExecutionStatus.SUCCESS,
                StepExecutionStatus.FAILED,
                StepExecutionStatus.CANCELLED,
                StepExecutionStatus.TIMEOUT,
                StepExecutionStatus.PREEMPTED,
            }
            if self.terminal_status not in allowed:
                raise ValueError(
                    "FINALIZE requires an allowed terminal StepExecutionStatus"
                )
        elif self.terminal_status is not None:
            raise ValueError(
                "non-FINALIZE decision must not carry terminal_status"
            )


class StepFinalizationEvaluator(Protocol):
    def evaluate(
        self,
        *,
        observation: StepAttemptObservation,
        reliability_decision: StepReliabilityDecision,
    ) -> StepFinalizationDecision:
        """Authorize terminal mapping without interpreting plan fallback/on_failure."""
