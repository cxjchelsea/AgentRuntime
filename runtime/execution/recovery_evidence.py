"""M5-IU9 CA-02 durable reliability, control, and in-flight evidence.

This unit freezes crash-surviving evidence contracts for IU6 and IU7 without
performing recovery orchestration. The in-memory implementation is a reference
mechanism: sharing the store across recreated adapters simulates restart, but it is
not a production durability claim.

Production adapters for mutating methods must validate the supplied recovery claim
in the same durable transaction / CAS boundary as the evidence mutation.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from typing import Callable, Protocol

from runtime.execution.control import (
    ExecutionControlLatch,
    ExecutionControlLatchDecision,
    ExecutionControlLatchStatus,
    LatchedExecutionControl,
    ObservedExecutionControl,
)
from runtime.execution.control_application import (
    InFlightOperationHandle,
    InFlightOperationRegistry,
)
from runtime.execution.invocation import ToolInvocationJournalEntry
from runtime.execution.recovery import (
    ExecutionRecoveryClaim,
    InMemoryRecoveryClaimAuthority,
    RecoveryEpochValidationStatus,
)
from runtime.execution.reliability_boundary import (
    StepAttemptSequenceAuthority,
    StepAttemptSequenceDecision,
    StepAttemptSequenceStatus,
    ToolOperationOccurrenceAuthority,
    ToolOperationOccurrenceDecision,
    ToolOperationOccurrenceStatus,
)


def _require_non_blank(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_claim_execution(
    claim: ExecutionRecoveryClaim,
    execution_id: str,
) -> None:
    if claim.execution_id != execution_id:
        raise ValueError("recovery claim execution_id mismatch")


class DurableEvidenceMutationStatus(str, Enum):
    RECORDED = "RECORDED"
    ALREADY_CURRENT = "ALREADY_CURRENT"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class DurableEvidenceMutationDecision:
    status: DurableEvidenceMutationStatus
    reason_codes: tuple[str, ...]
    revision: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, DurableEvidenceMutationStatus):
            raise TypeError("status must be DurableEvidenceMutationStatus")
        if not self.reason_codes or any(not item.strip() for item in self.reason_codes):
            raise ValueError("reason_codes must contain non-blank values")
        if self.status in {
            DurableEvidenceMutationStatus.RECORDED,
            DurableEvidenceMutationStatus.ALREADY_CURRENT,
        }:
            if self.revision is None or self.revision < 1:
                raise ValueError("successful evidence mutation requires revision >= 1")
        elif self.revision is not None:
            raise ValueError("CONFLICT/UNKNOWN must not invent accepted revision")


@dataclass(frozen=True, slots=True)
class StepAttemptCursorRecord:
    execution_id: str
    step_execution_id: str
    current_attempt: int
    revision: int
    updated_at: datetime
    last_claim_token: str | None = None
    writer_recovery_epoch: int = 1

    def __post_init__(self) -> None:
        _require_non_blank(self.execution_id, "execution_id")
        _require_non_blank(self.step_execution_id, "step_execution_id")
        if self.current_attempt < 1:
            raise ValueError("current_attempt must be >= 1")
        if self.revision < 1:
            raise ValueError("revision must be >= 1")
        if self.writer_recovery_epoch < 1:
            raise ValueError("writer_recovery_epoch must be >= 1")
        _require_aware(self.updated_at, "updated_at")
        if self.last_claim_token is not None:
            _require_non_blank(self.last_claim_token, "last_claim_token")


@dataclass(frozen=True, slots=True)
class ToolOccurrenceCursorRecord:
    execution_id: str
    step_execution_id: str
    step_attempt_number: int
    tool_id: str
    tool_version: str
    operation_fingerprint: str
    current_occurrence: int
    revision: int
    updated_at: datetime
    writer_recovery_epoch: int

    def __post_init__(self) -> None:
        for name, value in (
            ("execution_id", self.execution_id),
            ("step_execution_id", self.step_execution_id),
            ("tool_id", self.tool_id),
            ("tool_version", self.tool_version),
            ("operation_fingerprint", self.operation_fingerprint),
        ):
            _require_non_blank(value, name)
        if self.step_attempt_number < 1:
            raise ValueError("step_attempt_number must be >= 1")
        if self.current_occurrence < 1:
            raise ValueError("current_occurrence must be >= 1")
        if self.revision < 1:
            raise ValueError("revision must be >= 1")
        if self.writer_recovery_epoch < 1:
            raise ValueError("writer_recovery_epoch must be >= 1")
        _require_aware(self.updated_at, "updated_at")


class ToolJournalWriteStatus(str, Enum):
    APPENDED = "APPENDED"
    ALREADY_CURRENT = "ALREADY_CURRENT"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ToolJournalWriteDecision:
    status: ToolJournalWriteStatus
    reason_codes: tuple[str, ...]
    entry_index: int | None = None
    current_length: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ToolJournalWriteStatus):
            raise TypeError("status must be ToolJournalWriteStatus")
        if not self.reason_codes or any(not item.strip() for item in self.reason_codes):
            raise ValueError("reason_codes must contain non-blank values")
        if self.current_length is not None and self.current_length < 0:
            raise ValueError("current_length must be >= 0")
        if self.status in {
            ToolJournalWriteStatus.APPENDED,
            ToolJournalWriteStatus.ALREADY_CURRENT,
        }:
            if self.entry_index is None or self.entry_index < 1:
                raise ValueError("successful journal write requires entry_index >= 1")
            if self.current_length is None or self.current_length < self.entry_index:
                raise ValueError("current_length must include accepted journal entry")
        elif self.entry_index is not None:
            raise ValueError("CONFLICT/UNKNOWN must not invent accepted entry_index")


class DurableReliabilityEvidenceStore(Protocol):
    async def ensure_step_attempt_baseline(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
        recorded_at: datetime,
        required_claim: ExecutionRecoveryClaim,
    ) -> DurableEvidenceMutationDecision:
        """Durably establish attempt 1 before owner execution begins."""

    async def load_step_attempt_cursor(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
    ) -> StepAttemptCursorRecord | None:
        """Load the exact Step attempt cursor."""

    async def claim_next_step_attempt(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
        expected_current_attempt: int,
        claimed_at: datetime,
        required_claim: ExecutionRecoveryClaim,
    ) -> StepAttemptSequenceDecision:
        """Atomically fence + claim expected current attempt + 1."""

    async def load_tool_occurrence_cursor(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
        step_attempt_number: int,
        tool_id: str,
        tool_version: str,
        operation_fingerprint: str,
    ) -> ToolOccurrenceCursorRecord | None:
        """Load one exact Tool occurrence cursor."""

    async def claim_next_tool_occurrence(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
        step_attempt_number: int,
        tool_id: str,
        tool_version: str,
        operation_fingerprint: str,
        claimed_at: datetime,
        required_claim: ExecutionRecoveryClaim,
    ) -> ToolOperationOccurrenceDecision:
        """Atomically fence + advance one exact Tool occurrence cursor."""

    async def append_tool_journal_entry(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
        step_attempt_number: int,
        expected_current_length: int,
        entry: ToolInvocationJournalEntry,
        recorded_at: datetime,
        required_claim: ExecutionRecoveryClaim,
    ) -> ToolJournalWriteDecision:
        """Append journal evidence monotonically with exact-replay support."""

    async def load_tool_journal(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
        step_attempt_number: int,
    ) -> tuple[ToolInvocationJournalEntry, ...]:
        """Load ordered journal evidence for exact Step attempt provenance."""


class DurableStepAttemptSequenceAuthority(StepAttemptSequenceAuthority):
    """IU6 authority backed by crash-surviving cursor evidence."""

    def __init__(
        self,
        *,
        store: DurableReliabilityEvidenceStore,
        execution_id: str,
        recovery_claim: ExecutionRecoveryClaim,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        _require_non_blank(execution_id, "execution_id")
        _require_claim_execution(recovery_claim, execution_id)
        self._store = store
        self._execution_id = execution_id
        self._claim = recovery_claim
        self._clock = clock or (lambda: datetime.now(UTC))

    async def ensure_baseline(
        self,
        *,
        step_execution_id: str,
    ) -> DurableEvidenceMutationDecision:
        return await self._store.ensure_step_attempt_baseline(
            execution_id=self._execution_id,
            step_execution_id=step_execution_id,
            recorded_at=self._clock(),
            required_claim=self._claim,
        )

    async def current_attempt(self, step_execution_id: str) -> int | None:
        record = await self._store.load_step_attempt_cursor(
            execution_id=self._execution_id,
            step_execution_id=step_execution_id,
        )
        return None if record is None else record.current_attempt

    async def claim_next(
        self,
        *,
        step_execution_id: str,
        expected_current_attempt: int,
    ) -> StepAttemptSequenceDecision:
        return await self._store.claim_next_step_attempt(
            execution_id=self._execution_id,
            step_execution_id=step_execution_id,
            expected_current_attempt=expected_current_attempt,
            claimed_at=self._clock(),
            required_claim=self._claim,
        )


class DurableToolOperationOccurrenceAuthority(ToolOperationOccurrenceAuthority):
    """IU6 occurrence authority backed by exact crash-surviving cursors."""

    def __init__(
        self,
        *,
        store: DurableReliabilityEvidenceStore,
        execution_id: str,
        recovery_claim: ExecutionRecoveryClaim,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        _require_non_blank(execution_id, "execution_id")
        _require_claim_execution(recovery_claim, execution_id)
        self._store = store
        self._execution_id = execution_id
        self._claim = recovery_claim
        self._clock = clock or (lambda: datetime.now(UTC))

    async def claim_next(
        self,
        *,
        step_execution_id: str,
        step_attempt_number: int,
        tool_id: str,
        tool_version: str,
        operation_fingerprint: str,
    ) -> ToolOperationOccurrenceDecision:
        return await self._store.claim_next_tool_occurrence(
            execution_id=self._execution_id,
            step_execution_id=step_execution_id,
            step_attempt_number=step_attempt_number,
            tool_id=tool_id,
            tool_version=tool_version,
            operation_fingerprint=operation_fingerprint,
            claimed_at=self._clock(),
            required_claim=self._claim,
        )


class DurableToolJournalEvidence:
    """Recovery-facing journal recorder/reader for CoreApprovedToolInvoker wiring."""

    def __init__(
        self,
        *,
        store: DurableReliabilityEvidenceStore,
        execution_id: str,
        recovery_claim: ExecutionRecoveryClaim,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        _require_non_blank(execution_id, "execution_id")
        _require_claim_execution(recovery_claim, execution_id)
        self._store = store
        self._execution_id = execution_id
        self._claim = recovery_claim
        self._clock = clock or (lambda: datetime.now(UTC))

    async def append(
        self,
        *,
        step_execution_id: str,
        step_attempt_number: int,
        expected_current_length: int,
        entry: ToolInvocationJournalEntry,
    ) -> ToolJournalWriteDecision:
        return await self._store.append_tool_journal_entry(
            execution_id=self._execution_id,
            step_execution_id=step_execution_id,
            step_attempt_number=step_attempt_number,
            expected_current_length=expected_current_length,
            entry=entry,
            recorded_at=self._clock(),
            required_claim=self._claim,
        )

    async def load(
        self,
        *,
        step_execution_id: str,
        step_attempt_number: int,
    ) -> tuple[ToolInvocationJournalEntry, ...]:
        return await self._store.load_tool_journal(
            execution_id=self._execution_id,
            step_execution_id=step_execution_id,
            step_attempt_number=step_attempt_number,
        )


class DurableTerminalControlStore(Protocol):
    async def latch(
        self,
        *,
        observed: ObservedExecutionControl,
        latched_at: datetime,
        required_claim: ExecutionRecoveryClaim,
    ) -> ExecutionControlLatchDecision:
        """Atomically fence + persist first immutable terminal control."""

    async def get_latched(
        self,
        execution_id: str,
    ) -> LatchedExecutionControl | None:
        """Load the durable terminal control barrier, if any."""


class DurableExecutionControlLatch(ExecutionControlLatch):
    """IU7 latch adapter whose accepted terminal barrier survives restart."""

    def __init__(
        self,
        *,
        store: DurableTerminalControlStore,
        recovery_claim: ExecutionRecoveryClaim,
    ) -> None:
        self._store = store
        self._claim = recovery_claim

    async def latch(
        self,
        *,
        observed: ObservedExecutionControl,
        latched_at: datetime,
    ) -> ExecutionControlLatchDecision:
        return await self._store.latch(
            observed=observed,
            latched_at=latched_at,
            required_claim=self._claim,
        )

    async def get_latched(
        self,
        execution_id: str,
    ) -> LatchedExecutionControl | None:
        return await self._store.get_latched(execution_id)


class InFlightEvidenceState(str, Enum):
    ACTIVE_AT_CHECKPOINT = "ACTIVE_AT_CHECKPOINT"
    COMPLETED = "COMPLETED"
    CONFIRMED_STOPPED = "CONFIRMED_STOPPED"
    ORPHANED_UNCONFIRMED = "ORPHANED_UNCONFIRMED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class DurableInFlightOperationObservation:
    handle: InFlightOperationHandle
    state: InFlightEvidenceState
    revision: int
    observed_at: datetime
    writer_recovery_epoch: int
    terminal_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, InFlightEvidenceState):
            raise TypeError("state must be InFlightEvidenceState")
        if self.revision < 1:
            raise ValueError("revision must be >= 1")
        if self.writer_recovery_epoch < 1:
            raise ValueError("writer_recovery_epoch must be >= 1")
        _require_aware(self.observed_at, "observed_at")
        if self.terminal_at is not None:
            _require_aware(self.terminal_at, "terminal_at")
            if self.terminal_at < self.handle.started_at:
                raise ValueError("terminal_at cannot precede operation started_at")
        terminal = self.state in {
            InFlightEvidenceState.COMPLETED,
            InFlightEvidenceState.CONFIRMED_STOPPED,
        }
        if terminal != (self.terminal_at is not None):
            raise ValueError(
                "COMPLETED/CONFIRMED_STOPPED require terminal_at; other states forbid it"
            )


class DurableInFlightEvidenceStore(Protocol):
    async def register_active(
        self,
        *,
        handle: InFlightOperationHandle,
        observed_at: datetime,
        required_claim: ExecutionRecoveryClaim,
    ) -> DurableEvidenceMutationDecision:
        """Persist exact active handle before relying on live registry truth."""

    async def mark_completed(
        self,
        *,
        operation_handle_id: str,
        completed_at: datetime,
        required_claim: ExecutionRecoveryClaim,
    ) -> DurableEvidenceMutationDecision:
        """Persist live completion without deleting crash evidence."""

    async def recover_active_as_orphaned(
        self,
        *,
        execution_id: str,
        recovered_at: datetime,
        required_claim: ExecutionRecoveryClaim,
    ) -> tuple[DurableInFlightOperationObservation, ...]:
        """On restart, ACTIVE evidence becomes ORPHANED_UNCONFIRMED."""

    async def load_inflight(
        self,
        *,
        execution_id: str,
        step_execution_id: str | None = None,
    ) -> tuple[DurableInFlightOperationObservation, ...]:
        """Load durable operation evidence without upgrading uncertainty."""


class DurableInFlightOperationRegistry(InFlightOperationRegistry):
    """IU7 live registry adapter backed by durable operation observations."""

    def __init__(
        self,
        *,
        store: DurableInFlightEvidenceStore,
        recovery_claim: ExecutionRecoveryClaim,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._claim = recovery_claim
        self._clock = clock or (lambda: datetime.now(UTC))

    async def register(self, handle: InFlightOperationHandle) -> bool:
        decision = await self._store.register_active(
            handle=handle,
            observed_at=self._clock(),
            required_claim=self._claim,
        )
        if decision.status is DurableEvidenceMutationStatus.RECORDED:
            return True
        if decision.status is DurableEvidenceMutationStatus.ALREADY_CURRENT:
            return False
        raise RuntimeError(decision.reason_codes[0])

    async def complete(
        self,
        operation_handle_id: str,
        *,
        completed_at: datetime,
    ) -> bool:
        decision = await self._store.mark_completed(
            operation_handle_id=operation_handle_id,
            completed_at=completed_at,
            required_claim=self._claim,
        )
        if decision.status is DurableEvidenceMutationStatus.RECORDED:
            return True
        if decision.status is DurableEvidenceMutationStatus.ALREADY_CURRENT:
            return False
        raise RuntimeError(decision.reason_codes[0])

    async def active_chain(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
    ) -> tuple[InFlightOperationHandle, ...]:
        observations = await self._store.load_inflight(
            execution_id=execution_id,
            step_execution_id=step_execution_id,
        )
        return tuple(
            item.handle
            for item in observations
            if item.state is InFlightEvidenceState.ACTIVE_AT_CHECKPOINT
        )


class InMemoryDurableRecoveryEvidenceStore(
    DurableReliabilityEvidenceStore,
    DurableTerminalControlStore,
    DurableInFlightEvidenceStore,
):
    """Reference durable-evidence mechanism.

    State survives recreation of authority/registry adapters only while this object
    remains shared. Production adapters must persist the same contracts durably.
    """

    def __init__(
        self,
        *,
        claim_authority: InMemoryRecoveryClaimAuthority,
    ) -> None:
        self._claim_authority = claim_authority
        self._lock = asyncio.Lock()
        self._step_cursors: dict[tuple[str, str], StepAttemptCursorRecord] = {}
        self._occurrence_cursors: dict[
            tuple[str, str, int, str, str, str],
            ToolOccurrenceCursorRecord,
        ] = {}
        self._journals: dict[
            tuple[str, str, int],
            list[ToolInvocationJournalEntry],
        ] = {}
        self._journal_updated_at: dict[tuple[str, str, int], datetime] = {}
        self._control_latches: dict[str, LatchedExecutionControl] = {}
        self._inflight: dict[str, DurableInFlightOperationObservation] = {}

    def _fence_status(
        self,
        claim: ExecutionRecoveryClaim,
    ) -> RecoveryEpochValidationStatus:
        return self._claim_authority._validate_current_sync(claim).status

    @staticmethod
    def _mutation_from_fence(
        status: RecoveryEpochValidationStatus,
        *,
        stale_reason: str,
        unknown_reason: str,
    ) -> DurableEvidenceMutationDecision | None:
        if status is RecoveryEpochValidationStatus.CURRENT:
            return None
        if status is RecoveryEpochValidationStatus.STALE:
            return DurableEvidenceMutationDecision(
                status=DurableEvidenceMutationStatus.CONFLICT,
                reason_codes=(stale_reason,),
            )
        return DurableEvidenceMutationDecision(
            status=DurableEvidenceMutationStatus.UNKNOWN,
            reason_codes=(unknown_reason,),
        )

    async def ensure_step_attempt_baseline(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
        recorded_at: datetime,
        required_claim: ExecutionRecoveryClaim,
    ) -> DurableEvidenceMutationDecision:
        _require_non_blank(execution_id, "execution_id")
        _require_non_blank(step_execution_id, "step_execution_id")
        _require_aware(recorded_at, "recorded_at")
        _require_claim_execution(required_claim, execution_id)
        async with self._lock:
            fenced = self._mutation_from_fence(
                self._fence_status(required_claim),
                stale_reason="STEP_ATTEMPT_STALE_RECOVERY_EPOCH",
                unknown_reason="STEP_ATTEMPT_RECOVERY_EPOCH_UNKNOWN",
            )
            if fenced is not None:
                return fenced
            key = (execution_id, step_execution_id)
            current = self._step_cursors.get(key)
            if current is not None:
                return DurableEvidenceMutationDecision(
                    status=DurableEvidenceMutationStatus.ALREADY_CURRENT,
                    reason_codes=("STEP_ATTEMPT_BASELINE_ALREADY_DURABLE",),
                    revision=current.revision,
                )
            self._step_cursors[key] = StepAttemptCursorRecord(
                execution_id=execution_id,
                step_execution_id=step_execution_id,
                current_attempt=1,
                revision=1,
                updated_at=recorded_at,
                writer_recovery_epoch=required_claim.recovery_epoch,
            )
            return DurableEvidenceMutationDecision(
                status=DurableEvidenceMutationStatus.RECORDED,
                reason_codes=("STEP_ATTEMPT_BASELINE_RECORDED",),
                revision=1,
            )

    async def load_step_attempt_cursor(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
    ) -> StepAttemptCursorRecord | None:
        async with self._lock:
            record = self._step_cursors.get((execution_id, step_execution_id))
            return None if record is None else deepcopy(record)

    async def claim_next_step_attempt(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
        expected_current_attempt: int,
        claimed_at: datetime,
        required_claim: ExecutionRecoveryClaim,
    ) -> StepAttemptSequenceDecision:
        _require_non_blank(execution_id, "execution_id")
        _require_non_blank(step_execution_id, "step_execution_id")
        _require_aware(claimed_at, "claimed_at")
        _require_claim_execution(required_claim, execution_id)
        normalized_expected = max(expected_current_attempt, 1)
        if expected_current_attempt < 1:
            return StepAttemptSequenceDecision(
                status=StepAttemptSequenceStatus.UNKNOWN,
                step_execution_id=step_execution_id,
                expected_current_attempt=normalized_expected,
                reason_codes=("STEP_ATTEMPT_EXPECTATION_INVALID",),
            )
        async with self._lock:
            fence = self._fence_status(required_claim)
            if fence is RecoveryEpochValidationStatus.STALE:
                return StepAttemptSequenceDecision(
                    status=StepAttemptSequenceStatus.CONFLICT,
                    step_execution_id=step_execution_id,
                    expected_current_attempt=expected_current_attempt,
                    reason_codes=("STEP_ATTEMPT_STALE_RECOVERY_EPOCH",),
                )
            if fence is not RecoveryEpochValidationStatus.CURRENT:
                return StepAttemptSequenceDecision(
                    status=StepAttemptSequenceStatus.UNKNOWN,
                    step_execution_id=step_execution_id,
                    expected_current_attempt=expected_current_attempt,
                    reason_codes=("STEP_ATTEMPT_RECOVERY_EPOCH_UNKNOWN",),
                )

            key = (execution_id, step_execution_id)
            current = self._step_cursors.get(key)
            current_attempt = 1 if current is None else current.current_attempt
            if current_attempt != expected_current_attempt:
                return StepAttemptSequenceDecision(
                    status=StepAttemptSequenceStatus.CONFLICT,
                    step_execution_id=step_execution_id,
                    expected_current_attempt=expected_current_attempt,
                    reason_codes=("STEP_ATTEMPT_CONFLICT",),
                )
            next_attempt = current_attempt + 1
            token = (
                f"{execution_id}:{step_execution_id}:attempt:{next_attempt}:"
                f"epoch:{required_claim.recovery_epoch}"
            )
            revision = 1 if current is None else current.revision + 1
            self._step_cursors[key] = StepAttemptCursorRecord(
                execution_id=execution_id,
                step_execution_id=step_execution_id,
                current_attempt=next_attempt,
                revision=revision,
                updated_at=claimed_at,
                last_claim_token=token,
                writer_recovery_epoch=required_claim.recovery_epoch,
            )
            return StepAttemptSequenceDecision(
                status=StepAttemptSequenceStatus.CLAIMED,
                step_execution_id=step_execution_id,
                expected_current_attempt=expected_current_attempt,
                reason_codes=("STEP_ATTEMPT_DURABLY_CLAIMED",),
                next_attempt=next_attempt,
                claim_token=token,
            )

    async def load_tool_occurrence_cursor(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
        step_attempt_number: int,
        tool_id: str,
        tool_version: str,
        operation_fingerprint: str,
    ) -> ToolOccurrenceCursorRecord | None:
        key = (
            execution_id,
            step_execution_id,
            step_attempt_number,
            tool_id,
            tool_version,
            operation_fingerprint,
        )
        async with self._lock:
            record = self._occurrence_cursors.get(key)
            return None if record is None else deepcopy(record)

    async def claim_next_tool_occurrence(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
        step_attempt_number: int,
        tool_id: str,
        tool_version: str,
        operation_fingerprint: str,
        claimed_at: datetime,
        required_claim: ExecutionRecoveryClaim,
    ) -> ToolOperationOccurrenceDecision:
        for name, value in (
            ("execution_id", execution_id),
            ("step_execution_id", step_execution_id),
            ("tool_id", tool_id),
            ("tool_version", tool_version),
            ("operation_fingerprint", operation_fingerprint),
        ):
            _require_non_blank(value, name)
        _require_aware(claimed_at, "claimed_at")
        _require_claim_execution(required_claim, execution_id)
        if step_attempt_number < 1:
            return ToolOperationOccurrenceDecision(
                status=ToolOperationOccurrenceStatus.UNKNOWN,
                reason_codes=("STEP_ATTEMPT_INVALID",),
            )

        key = (
            execution_id,
            step_execution_id,
            step_attempt_number,
            tool_id,
            tool_version,
            operation_fingerprint,
        )
        async with self._lock:
            if self._fence_status(required_claim) is not RecoveryEpochValidationStatus.CURRENT:
                return ToolOperationOccurrenceDecision(
                    status=ToolOperationOccurrenceStatus.UNKNOWN,
                    reason_codes=("TOOL_OCCURRENCE_RECOVERY_EPOCH_NOT_CURRENT",),
                )
            current = self._occurrence_cursors.get(key)
            occurrence = 1 if current is None else current.current_occurrence + 1
            revision = 1 if current is None else current.revision + 1
            self._occurrence_cursors[key] = ToolOccurrenceCursorRecord(
                execution_id=execution_id,
                step_execution_id=step_execution_id,
                step_attempt_number=step_attempt_number,
                tool_id=tool_id,
                tool_version=tool_version,
                operation_fingerprint=operation_fingerprint,
                current_occurrence=occurrence,
                revision=revision,
                updated_at=claimed_at,
                writer_recovery_epoch=required_claim.recovery_epoch,
            )
            return ToolOperationOccurrenceDecision(
                status=ToolOperationOccurrenceStatus.CLAIMED,
                reason_codes=("TOOL_OPERATION_OCCURRENCE_DURABLY_CLAIMED",),
                occurrence=occurrence,
            )

    async def append_tool_journal_entry(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
        step_attempt_number: int,
        expected_current_length: int,
        entry: ToolInvocationJournalEntry,
        recorded_at: datetime,
        required_claim: ExecutionRecoveryClaim,
    ) -> ToolJournalWriteDecision:
        _require_non_blank(execution_id, "execution_id")
        _require_non_blank(step_execution_id, "step_execution_id")
        _require_aware(recorded_at, "recorded_at")
        _require_claim_execution(required_claim, execution_id)
        if step_attempt_number < 1 or expected_current_length < 0:
            return ToolJournalWriteDecision(
                status=ToolJournalWriteStatus.UNKNOWN,
                reason_codes=("TOOL_JOURNAL_WRITE_INPUT_INVALID",),
            )

        key = (execution_id, step_execution_id, step_attempt_number)
        async with self._lock:
            fence = self._fence_status(required_claim)
            if fence is RecoveryEpochValidationStatus.STALE:
                return ToolJournalWriteDecision(
                    status=ToolJournalWriteStatus.CONFLICT,
                    reason_codes=("TOOL_JOURNAL_STALE_RECOVERY_EPOCH",),
                    current_length=len(self._journals.get(key, ())),
                )
            if fence is not RecoveryEpochValidationStatus.CURRENT:
                return ToolJournalWriteDecision(
                    status=ToolJournalWriteStatus.UNKNOWN,
                    reason_codes=("TOOL_JOURNAL_RECOVERY_EPOCH_UNKNOWN",),
                    current_length=len(self._journals.get(key, ())),
                )

            journal = self._journals.setdefault(key, [])
            current_length = len(journal)
            if (
                current_length > 0
                and expected_current_length == current_length - 1
                and journal[-1] == entry
            ):
                return ToolJournalWriteDecision(
                    status=ToolJournalWriteStatus.ALREADY_CURRENT,
                    reason_codes=("TOOL_JOURNAL_EXACT_APPEND_REPLAY",),
                    entry_index=current_length,
                    current_length=current_length,
                )
            if expected_current_length != current_length:
                return ToolJournalWriteDecision(
                    status=ToolJournalWriteStatus.CONFLICT,
                    reason_codes=("TOOL_JOURNAL_LENGTH_CONFLICT",),
                    current_length=current_length,
                )
            if any(
                existing.tool_call_id == entry.tool_call_id and existing != entry
                for existing in journal
            ):
                return ToolJournalWriteDecision(
                    status=ToolJournalWriteStatus.CONFLICT,
                    reason_codes=("TOOL_JOURNAL_IDENTITY_REBIND_CONFLICT",),
                    current_length=current_length,
                )
            journal.append(deepcopy(entry))
            self._journal_updated_at[key] = recorded_at
            return ToolJournalWriteDecision(
                status=ToolJournalWriteStatus.APPENDED,
                reason_codes=("TOOL_JOURNAL_ENTRY_DURABLY_APPENDED",),
                entry_index=len(journal),
                current_length=len(journal),
            )

    async def load_tool_journal(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
        step_attempt_number: int,
    ) -> tuple[ToolInvocationJournalEntry, ...]:
        key = (execution_id, step_execution_id, step_attempt_number)
        async with self._lock:
            return deepcopy(tuple(self._journals.get(key, ())))

    async def latch(
        self,
        *,
        observed: ObservedExecutionControl,
        latched_at: datetime,
        required_claim: ExecutionRecoveryClaim,
    ) -> ExecutionControlLatchDecision:
        _require_aware(latched_at, "latched_at")
        target = observed.signal.target_execution_id
        if target is None or not target.strip():
            return ExecutionControlLatchDecision(
                status=ExecutionControlLatchStatus.UNKNOWN,
                reason_codes=("CONTROL_LATCH_TARGET_UNKNOWN",),
            )
        if target != required_claim.execution_id:
            return ExecutionControlLatchDecision(
                status=ExecutionControlLatchStatus.UNKNOWN,
                reason_codes=("CONTROL_LATCH_RECOVERY_CLAIM_MISMATCH",),
            )
        try:
            candidate = LatchedExecutionControl(
                signal=observed.signal,
                observed_at=observed.observed_at,
                latched_at=latched_at,
            )
        except (TypeError, ValueError):
            return ExecutionControlLatchDecision(
                status=ExecutionControlLatchStatus.UNKNOWN,
                reason_codes=("CONTROL_LATCH_INPUT_INVALID",),
            )

        async with self._lock:
            if self._fence_status(required_claim) is not RecoveryEpochValidationStatus.CURRENT:
                return ExecutionControlLatchDecision(
                    status=ExecutionControlLatchStatus.UNKNOWN,
                    reason_codes=("CONTROL_LATCH_RECOVERY_EPOCH_NOT_CURRENT",),
                )
            existing = self._control_latches.get(target)
            if existing is None:
                self._control_latches[target] = candidate
                return ExecutionControlLatchDecision(
                    status=ExecutionControlLatchStatus.LATCHED,
                    reason_codes=("CONTROL_DURABLY_LATCHED",),
                    latched_control=deepcopy(candidate),
                )
            if existing.signal == candidate.signal:
                return ExecutionControlLatchDecision(
                    status=ExecutionControlLatchStatus.ALREADY_LATCHED,
                    reason_codes=("CONTROL_DURABLE_LATCH_EXACT_REPLAY",),
                    latched_control=deepcopy(existing),
                )
            return ExecutionControlLatchDecision(
                status=ExecutionControlLatchStatus.CONFLICT,
                reason_codes=("CONTROL_DURABLE_LATCH_CONFLICT",),
                latched_control=deepcopy(existing),
            )

    async def get_latched(
        self,
        execution_id: str,
    ) -> LatchedExecutionControl | None:
        if not isinstance(execution_id, str) or not execution_id.strip():
            return None
        async with self._lock:
            current = self._control_latches.get(execution_id)
            return None if current is None else deepcopy(current)

    async def register_active(
        self,
        *,
        handle: InFlightOperationHandle,
        observed_at: datetime,
        required_claim: ExecutionRecoveryClaim,
    ) -> DurableEvidenceMutationDecision:
        _require_aware(observed_at, "observed_at")
        _require_claim_execution(required_claim, handle.execution_id)
        if observed_at < handle.started_at:
            return DurableEvidenceMutationDecision(
                status=DurableEvidenceMutationStatus.UNKNOWN,
                reason_codes=("INFLIGHT_OBSERVATION_PRECEDES_START",),
            )
        async with self._lock:
            fenced = self._mutation_from_fence(
                self._fence_status(required_claim),
                stale_reason="INFLIGHT_STALE_RECOVERY_EPOCH",
                unknown_reason="INFLIGHT_RECOVERY_EPOCH_UNKNOWN",
            )
            if fenced is not None:
                return fenced
            existing = self._inflight.get(handle.operation_handle_id)
            if existing is not None:
                if (
                    existing.handle == handle
                    and existing.state is InFlightEvidenceState.ACTIVE_AT_CHECKPOINT
                ):
                    return DurableEvidenceMutationDecision(
                        status=DurableEvidenceMutationStatus.ALREADY_CURRENT,
                        reason_codes=("INFLIGHT_ACTIVE_EXACT_REPLAY",),
                        revision=existing.revision,
                    )
                return DurableEvidenceMutationDecision(
                    status=DurableEvidenceMutationStatus.CONFLICT,
                    reason_codes=("INFLIGHT_HANDLE_REBIND_OR_STATE_CONFLICT",),
                )
            self._inflight[handle.operation_handle_id] = (
                DurableInFlightOperationObservation(
                    handle=deepcopy(handle),
                    state=InFlightEvidenceState.ACTIVE_AT_CHECKPOINT,
                    revision=1,
                    observed_at=observed_at,
                    writer_recovery_epoch=required_claim.recovery_epoch,
                )
            )
            return DurableEvidenceMutationDecision(
                status=DurableEvidenceMutationStatus.RECORDED,
                reason_codes=("INFLIGHT_ACTIVE_DURABLY_RECORDED",),
                revision=1,
            )

    async def mark_completed(
        self,
        *,
        operation_handle_id: str,
        completed_at: datetime,
        required_claim: ExecutionRecoveryClaim,
    ) -> DurableEvidenceMutationDecision:
        _require_non_blank(operation_handle_id, "operation_handle_id")
        _require_aware(completed_at, "completed_at")
        async with self._lock:
            fenced = self._mutation_from_fence(
                self._fence_status(required_claim),
                stale_reason="INFLIGHT_COMPLETION_STALE_RECOVERY_EPOCH",
                unknown_reason="INFLIGHT_COMPLETION_RECOVERY_EPOCH_UNKNOWN",
            )
            if fenced is not None:
                return fenced
            existing = self._inflight.get(operation_handle_id)
            if existing is None:
                return DurableEvidenceMutationDecision(
                    status=DurableEvidenceMutationStatus.UNKNOWN,
                    reason_codes=("INFLIGHT_COMPLETION_HANDLE_UNKNOWN",),
                )
            if existing.handle.execution_id != required_claim.execution_id:
                return DurableEvidenceMutationDecision(
                    status=DurableEvidenceMutationStatus.UNKNOWN,
                    reason_codes=("INFLIGHT_COMPLETION_EXECUTION_MISMATCH",),
                )
            if existing.state is InFlightEvidenceState.COMPLETED:
                if existing.terminal_at == completed_at:
                    return DurableEvidenceMutationDecision(
                        status=DurableEvidenceMutationStatus.ALREADY_CURRENT,
                        reason_codes=("INFLIGHT_COMPLETION_EXACT_REPLAY",),
                        revision=existing.revision,
                    )
                return DurableEvidenceMutationDecision(
                    status=DurableEvidenceMutationStatus.CONFLICT,
                    reason_codes=("INFLIGHT_COMPLETION_TIME_CONFLICT",),
                )
            if existing.state is not InFlightEvidenceState.ACTIVE_AT_CHECKPOINT:
                return DurableEvidenceMutationDecision(
                    status=DurableEvidenceMutationStatus.CONFLICT,
                    reason_codes=("INFLIGHT_COMPLETION_STATE_CONFLICT",),
                )
            if completed_at < existing.handle.started_at:
                return DurableEvidenceMutationDecision(
                    status=DurableEvidenceMutationStatus.UNKNOWN,
                    reason_codes=("INFLIGHT_COMPLETION_PRECEDES_START",),
                )
            updated = replace(
                existing,
                state=InFlightEvidenceState.COMPLETED,
                revision=existing.revision + 1,
                observed_at=completed_at,
                terminal_at=completed_at,
                writer_recovery_epoch=required_claim.recovery_epoch,
            )
            self._inflight[operation_handle_id] = updated
            return DurableEvidenceMutationDecision(
                status=DurableEvidenceMutationStatus.RECORDED,
                reason_codes=("INFLIGHT_COMPLETION_DURABLY_RECORDED",),
                revision=updated.revision,
            )

    async def recover_active_as_orphaned(
        self,
        *,
        execution_id: str,
        recovered_at: datetime,
        required_claim: ExecutionRecoveryClaim,
    ) -> tuple[DurableInFlightOperationObservation, ...]:
        _require_non_blank(execution_id, "execution_id")
        _require_aware(recovered_at, "recovered_at")
        _require_claim_execution(required_claim, execution_id)
        async with self._lock:
            if self._fence_status(required_claim) is not RecoveryEpochValidationStatus.CURRENT:
                return ()
            for handle_id, existing in tuple(self._inflight.items()):
                if (
                    existing.handle.execution_id == execution_id
                    and existing.state is InFlightEvidenceState.ACTIVE_AT_CHECKPOINT
                ):
                    self._inflight[handle_id] = replace(
                        existing,
                        state=InFlightEvidenceState.ORPHANED_UNCONFIRMED,
                        revision=existing.revision + 1,
                        observed_at=recovered_at,
                        writer_recovery_epoch=required_claim.recovery_epoch,
                    )
            return deepcopy(
                tuple(
                    item
                    for item in self._inflight.values()
                    if item.handle.execution_id == execution_id
                )
            )

    async def load_inflight(
        self,
        *,
        execution_id: str,
        step_execution_id: str | None = None,
    ) -> tuple[DurableInFlightOperationObservation, ...]:
        _require_non_blank(execution_id, "execution_id")
        if step_execution_id is not None:
            _require_non_blank(step_execution_id, "step_execution_id")
        async with self._lock:
            return deepcopy(
                tuple(
                    item
                    for item in self._inflight.values()
                    if item.handle.execution_id == execution_id
                    and (
                        step_execution_id is None
                        or item.handle.step_execution_id == step_execution_id
                    )
                )
            )
