"""Reference/default implementations for M5-IU6 reliability authorities.

These implementations are Core-generic. In-memory stores/sequence authorities are
mechanism/reference implementations only; they are not crash-durable production
persistence.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from collections.abc import Awaitable, Callable
from typing import Any

from runtime.execution.invocation import ToolInvocationJournalEntry
from runtime.execution.models import M5ToolResult, StepExecutionStatus, ToolExecutionStatus
from runtime.execution.reliability import (
    ExecutionClock,
    IdempotencyMode,
    ReplaySafetyContext,
    ReplaySafetyDecision,
    ReplaySafetyStatus,
    ResolvedRetryPolicy,
    RetryDecision,
    RetryDecisionContext,
    RetryDecisionStatus,
    TimeoutRunResult,
    TimeoutRunStatus,
)
from runtime.execution.reliability_boundary import (
    IdempotencyPreflightDecision,
    IdempotencyPreflightStatus,
    StepAttemptSequenceDecision,
    StepAttemptSequenceStatus,
    StepFinalizationDecision,
    StepFinalizationDisposition,
    StepReliabilityDecision,
    StepReliabilityDisposition,
    StepReplaySafetyRequest,
    ToolOperationCorrelationDecision,
    ToolOperationCorrelationKey,
    ToolOperationCorrelationStatus,
    ToolOperationOccurrenceDecision,
    ToolOperationOccurrenceStatus,
)
from runtime.execution.result_collection import StepAttemptObservation, StepAttemptStatus
from runtime.execution.stores import (
    IdempotencyCompletionDecision,
    IdempotencyCompletionStatus,
    IdempotencyRecord,
    IdempotencyStatus,
    IdempotencyStore,
)


class UtcExecutionClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class AsyncioOperationTimeoutRunner:
    async def run(
        self,
        *,
        timeout_seconds: float,
        operation: Callable[[], Awaitable[Any]],
    ) -> TimeoutRunResult[Any]:
        if timeout_seconds <= 0:
            return TimeoutRunResult(
                status=TimeoutRunStatus.TIMED_OUT,
                reason_codes=("TIMEOUT_BUDGET_EXHAUSTED",),
            )
        try:
            value = await asyncio.wait_for(operation(), timeout=timeout_seconds)
        except TimeoutError:
            return TimeoutRunResult(
                status=TimeoutRunStatus.TIMED_OUT,
                reason_codes=("ASYNC_OPERATION_TIMED_OUT",),
            )
        return TimeoutRunResult(
            status=TimeoutRunStatus.COMPLETED,
            value=value,
            reason_codes=("ASYNC_OPERATION_COMPLETED",),
        )


class AsyncioRetrySleeper:
    async def sleep(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("retry sleep seconds must be >= 0")
        await asyncio.sleep(seconds)


class ExponentialBackoffCalculator:
    def calculate(
        self,
        *,
        policy: ResolvedRetryPolicy,
        next_attempt: int,
    ) -> float:
        if next_attempt < 2:
            raise ValueError("next_attempt must be >= 2")
        exponent = next_attempt - 2
        value = policy.backoff_seconds * (policy.backoff_multiplier**exponent)
        if policy.max_backoff_seconds is not None:
            value = min(value, policy.max_backoff_seconds)
        return value


class BasicRetryDecisionEvaluator:
    def __init__(
        self,
        *,
        backoff_calculator: ExponentialBackoffCalculator | None = None,
    ) -> None:
        self._backoff = backoff_calculator or ExponentialBackoffCalculator()

    def evaluate(
        self,
        *,
        policy: ResolvedRetryPolicy,
        context: RetryDecisionContext,
    ) -> RetryDecision:
        if context.replay_safety.status is ReplaySafetyStatus.UNKNOWN:
            return RetryDecision(
                status=RetryDecisionStatus.UNKNOWN,
                reason_codes=("REPLAY_SAFETY_UNKNOWN",),
            )
        if context.replay_safety.status is ReplaySafetyStatus.UNSAFE:
            return RetryDecision(
                status=RetryDecisionStatus.STOP,
                reason_codes=("REPLAY_UNSAFE",),
            )
        if not policy.enabled:
            return RetryDecision(
                status=RetryDecisionStatus.STOP,
                reason_codes=("RETRY_DISABLED",),
            )
        if context.current_attempt >= policy.max_attempts:
            return RetryDecision(
                status=RetryDecisionStatus.STOP,
                reason_codes=("MAX_ATTEMPTS_REACHED",),
            )
        if (
            context.deadline_remaining_seconds is not None
            and context.deadline_remaining_seconds <= 0
        ):
            return RetryDecision(
                status=RetryDecisionStatus.STOP,
                reason_codes=("DEADLINE_EXHAUSTED",),
            )
        matches_status = context.result_status in policy.retry_on_statuses
        matches_error = (
            context.error_code is not None
            and context.error_code in policy.retry_on_error_codes
        )
        if not matches_status and not matches_error:
            return RetryDecision(
                status=RetryDecisionStatus.STOP,
                reason_codes=("RETRY_POLICY_NOT_MATCHED",),
            )
        next_attempt = context.current_attempt + 1
        return RetryDecision(
            status=RetryDecisionStatus.RETRY,
            reason_codes=("RETRY_POLICY_MATCHED",),
            next_attempt=next_attempt,
            backoff_seconds=self._backoff.calculate(
                policy=policy,
                next_attempt=next_attempt,
            ),
        )


class BasicToolReplaySafetyEvaluator:
    def evaluate(self, context: ReplaySafetyContext) -> ReplaySafetyDecision:
        if context.idempotency_mode is IdempotencyMode.NATURAL:
            return ReplaySafetyDecision(
                status=ReplaySafetyStatus.SAFE,
                reason_codes=("NATURAL_IDEMPOTENCY",),
            )
        if context.idempotency_mode is IdempotencyMode.NON_IDEMPOTENT:
            if context.invocation_started:
                return ReplaySafetyDecision(
                    status=ReplaySafetyStatus.UNSAFE,
                    reason_codes=("NON_IDEMPOTENT_INVOCATION_STARTED",),
                )
            return ReplaySafetyDecision(
                status=ReplaySafetyStatus.SAFE,
                reason_codes=("NON_IDEMPOTENT_NOT_STARTED",),
            )
        if (
            context.idempotency_state_unknown
            or context.has_unknown_side_effect
            or context.has_untrusted_success
            or context.current_status
            in {ToolExecutionStatus.TIMEOUT, ToolExecutionStatus.UNKNOWN}
        ):
            return ReplaySafetyDecision(
                status=ReplaySafetyStatus.UNKNOWN,
                reason_codes=("KEY_BASED_RECONCILIATION_REQUIRED",),
            )
        return ReplaySafetyDecision(
            status=ReplaySafetyStatus.SAFE,
            reason_codes=("KEY_BASED_RESERVATION_STABLE",),
        )


class DeterministicToolOperationFingerprintFactory:
    def fingerprint(
        self,
        *,
        tool_id: str,
        tool_version: str,
        input_payload: dict[str, Any],
    ) -> str:
        payload = json.dumps(
            {
                "tool_id": tool_id,
                "tool_version": tool_version,
                "input": input_payload,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(payload).hexdigest()}"


class DeterministicIdempotencyKeyFactory:
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
        raw = "|".join(
            (
                execution_id,
                step_execution_id,
                operation_key.value,
                tool_id,
                tool_version,
                operation_fingerprint,
            )
        ).encode("utf-8")
        return f"idem:{hashlib.sha256(raw).hexdigest()}"


class InMemoryToolOperationOccurrenceAuthority:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._counts: dict[tuple[str, int, str, str, str], int] = {}

    async def claim_next(
        self,
        *,
        step_execution_id: str,
        step_attempt_number: int,
        tool_id: str,
        tool_version: str,
        operation_fingerprint: str,
    ) -> ToolOperationOccurrenceDecision:
        if step_attempt_number < 1:
            return ToolOperationOccurrenceDecision(
                status=ToolOperationOccurrenceStatus.UNKNOWN,
                reason_codes=("STEP_ATTEMPT_INVALID",),
            )
        key = (
            step_execution_id,
            step_attempt_number,
            tool_id,
            tool_version,
            operation_fingerprint,
        )
        async with self._lock:
            occurrence = self._counts.get(key, 0) + 1
            self._counts[key] = occurrence
        return ToolOperationOccurrenceDecision(
            status=ToolOperationOccurrenceStatus.CLAIMED,
            reason_codes=("TOOL_OPERATION_OCCURRENCE_CLAIMED",),
            occurrence=occurrence,
        )


class DeterministicToolOperationCorrelator:
    @staticmethod
    def _new_identity(
        *,
        step_execution_id: str,
        tool_id: str,
        tool_version: str,
        operation_fingerprint: str,
        operation_occurrence: int,
    ) -> tuple[ToolOperationCorrelationKey, str]:
        raw = "|".join(
            (
                step_execution_id,
                tool_id,
                tool_version,
                operation_fingerprint,
                str(operation_occurrence),
            )
        ).encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        return ToolOperationCorrelationKey(f"op:{digest}"), f"tool-call:{digest}"

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
        if step_attempt_number < 1 or operation_occurrence < 1:
            return ToolOperationCorrelationDecision(
                status=ToolOperationCorrelationStatus.UNKNOWN,
                reason_codes=("TOOL_OPERATION_CORRELATION_INPUT_INVALID",),
            )
        if step_attempt_number == 1:
            if prior_attempt_journal:
                return ToolOperationCorrelationDecision(
                    status=ToolOperationCorrelationStatus.UNKNOWN,
                    reason_codes=("UNEXPECTED_PRIOR_ATTEMPT_JOURNAL",),
                )
            operation_key, logical_id = self._new_identity(
                step_execution_id=step_execution_id,
                tool_id=tool_id,
                tool_version=tool_version,
                operation_fingerprint=operation_fingerprint,
                operation_occurrence=operation_occurrence,
            )
            return ToolOperationCorrelationDecision(
                status=ToolOperationCorrelationStatus.NEW,
                reason_codes=("NEW_TOOL_OPERATION",),
                operation_key=operation_key,
                logical_tool_call_id=logical_id,
                operation_occurrence=operation_occurrence,
            )

        matching = tuple(
            entry
            for entry in prior_attempt_journal
            if entry.tool_id == tool_id
            and entry.tool_version == tool_version
            and entry.operation_fingerprint == operation_fingerprint
        )
        if len(matching) < operation_occurrence:
            return ToolOperationCorrelationDecision(
                status=ToolOperationCorrelationStatus.UNKNOWN,
                reason_codes=("PRIOR_TOOL_OPERATION_NOT_FOUND",),
            )
        prior = matching[operation_occurrence - 1]
        if prior.operation_key is None:
            return ToolOperationCorrelationDecision(
                status=ToolOperationCorrelationStatus.UNKNOWN,
                reason_codes=("PRIOR_TOOL_OPERATION_IDENTITY_MISSING",),
            )
        return ToolOperationCorrelationDecision(
            status=ToolOperationCorrelationStatus.CORRELATED,
            reason_codes=("PRIOR_TOOL_OPERATION_CORRELATED",),
            operation_key=ToolOperationCorrelationKey(prior.operation_key),
            logical_tool_call_id=prior.tool_call_id,
            operation_occurrence=operation_occurrence,
        )


class BasicIdempotencyPreflightEvaluator:
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
        if existing_record is None:
            return IdempotencyPreflightDecision(
                status=IdempotencyPreflightStatus.RESERVE_NEW,
                reason_codes=("IDEMPOTENCY_KEY_AVAILABLE",),
            )
        provenance_matches = (
            existing_record.execution_id == expected_execution_id
            and existing_record.step_execution_id == expected_step_execution_id
            and existing_record.tool_id == expected_tool_id
            and existing_record.tool_version == expected_tool_version
            and existing_record.operation_key == expected_operation_key
            and existing_record.operation_fingerprint
            == expected_operation_fingerprint
        )
        if not provenance_matches:
            return IdempotencyPreflightDecision(
                status=IdempotencyPreflightStatus.REJECT_PROVENANCE,
                reason_codes=("IDEMPOTENCY_PROVENANCE_MISMATCH",),
                existing_record=existing_record,
            )
        mapping = {
            IdempotencyStatus.COMPLETED: IdempotencyPreflightStatus.RECOVER_COMPLETED,
            IdempotencyStatus.RESERVED: IdempotencyPreflightStatus.WAIT_IN_FLIGHT,
            IdempotencyStatus.FAILED: IdempotencyPreflightStatus.REOPEN_FAILED,
            IdempotencyStatus.UNKNOWN: IdempotencyPreflightStatus.FAIL_UNKNOWN,
        }
        return IdempotencyPreflightDecision(
            status=mapping[existing_record.status],
            reason_codes=(f"IDEMPOTENCY_{existing_record.status.value}",),
            existing_record=existing_record,
        )


class InMemoryIdempotencyCoordinator:
    """One-lock reference store + completion authority + result resolver."""

    def __init__(self, *, clock: ExecutionClock | None = None) -> None:
        self._clock = clock or UtcExecutionClock()
        self._lock = asyncio.Lock()
        self._records: dict[str, IdempotencyRecord] = {}
        self._results: dict[str, M5ToolResult] = {}

    async def get(self, key: str) -> IdempotencyRecord | None:
        async with self._lock:
            return self._records.get(key)

    async def reserve(self, record: IdempotencyRecord) -> bool:
        if record.status is not IdempotencyStatus.RESERVED:
            raise ValueError("reserve requires RESERVED record")
        async with self._lock:
            if record.key in self._records:
                return False
            self._records[record.key] = record
            return True

    async def mark_completed(
        self,
        key: str,
        *,
        tool_call_id: str,
        result_reference: str,
    ) -> None:
        async with self._lock:
            current = self._records.get(key)
            if current is None or current.status is not IdempotencyStatus.RESERVED:
                raise RuntimeError("idempotency completion requires RESERVED record")
            self._records[key] = replace(
                current,
                status=IdempotencyStatus.COMPLETED,
                tool_call_id=tool_call_id,
                result_reference=result_reference,
                updated_at=self._clock.now(),
            )

    async def mark_failed(self, key: str) -> None:
        async with self._lock:
            current = self._records.get(key)
            if current is None or current.status is not IdempotencyStatus.RESERVED:
                raise RuntimeError("mark_failed requires RESERVED record")
            self._records[key] = replace(
                current,
                status=IdempotencyStatus.FAILED,
                updated_at=self._clock.now(),
            )

    async def reopen_failed(self, record: IdempotencyRecord) -> bool:
        async with self._lock:
            current = self._records.get(record.key)
            if (
                current is None
                or current.status is not IdempotencyStatus.FAILED
                or not self._same_provenance(current, record)
            ):
                return False
            self._records[record.key] = replace(
                current,
                status=IdempotencyStatus.RESERVED,
                result_reference=None,
                updated_at=self._clock.now(),
            )
            return True

    async def mark_unknown(self, key: str) -> None:
        async with self._lock:
            current = self._records.get(key)
            if current is None or current.status is not IdempotencyStatus.RESERVED:
                raise RuntimeError("mark_unknown requires RESERVED record")
            self._records[key] = replace(
                current,
                status=IdempotencyStatus.UNKNOWN,
                result_reference=None,
                updated_at=self._clock.now(),
            )

    async def complete(
        self,
        *,
        reserved_record: IdempotencyRecord,
        result: M5ToolResult,
    ) -> IdempotencyCompletionDecision:
        async with self._lock:
            current = self._records.get(reserved_record.key)
            if (
                current is None
                or current.status is not IdempotencyStatus.RESERVED
                or not self._same_provenance(current, reserved_record)
            ):
                return IdempotencyCompletionDecision(
                    status=IdempotencyCompletionStatus.CONFLICT,
                    reason_codes=("IDEMPOTENCY_COMPLETION_CONFLICT",),
                )
            if result.tool_id != current.tool_id:
                return IdempotencyCompletionDecision(
                    status=IdempotencyCompletionStatus.CONFLICT,
                    reason_codes=("IDEMPOTENCY_RESULT_TOOL_MISMATCH",),
                )
            reference = f"memory://idempotency/{current.key}"
            completed = replace(
                current,
                status=IdempotencyStatus.COMPLETED,
                tool_call_id=result.tool_call_id,
                result_reference=reference,
                updated_at=self._clock.now(),
            )
            self._results[reference] = result
            self._records[current.key] = completed
            return IdempotencyCompletionDecision(
                status=IdempotencyCompletionStatus.COMPLETED,
                reason_codes=("IDEMPOTENCY_COMPLETED_ATOMICALLY",),
                completed_record=completed,
            )

    async def resolve_completed(
        self,
        record: IdempotencyRecord,
    ) -> M5ToolResult | None:
        if (
            record.status is not IdempotencyStatus.COMPLETED
            or record.result_reference is None
        ):
            return None
        async with self._lock:
            current = self._records.get(record.key)
            if current != record:
                return None
            return self._results.get(record.result_reference)

    @staticmethod
    def _same_provenance(
        left: IdempotencyRecord,
        right: IdempotencyRecord,
    ) -> bool:
        return (
            left.key == right.key
            and left.execution_id == right.execution_id
            and left.step_id == right.step_id
            and left.step_execution_id == right.step_execution_id
            and left.tool_id == right.tool_id
            and left.tool_version == right.tool_version
            and left.operation_key == right.operation_key
            and left.operation_fingerprint == right.operation_fingerprint
        )


class InMemoryStepAttemptSequenceAuthority:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._current: dict[str, int] = {}

    async def current_attempt(self, step_execution_id: str) -> int | None:
        async with self._lock:
            return self._current.get(step_execution_id)

    async def claim_next(
        self,
        *,
        step_execution_id: str,
        expected_current_attempt: int,
    ) -> StepAttemptSequenceDecision:
        if expected_current_attempt < 1:
            return StepAttemptSequenceDecision(
                status=StepAttemptSequenceStatus.UNKNOWN,
                step_execution_id=step_execution_id,
                expected_current_attempt=max(expected_current_attempt, 1),
                reason_codes=("STEP_ATTEMPT_EXPECTATION_INVALID",),
            )
        async with self._lock:
            current = self._current.get(step_execution_id)
            if current is None:
                if expected_current_attempt != 1:
                    return StepAttemptSequenceDecision(
                        status=StepAttemptSequenceStatus.CONFLICT,
                        step_execution_id=step_execution_id,
                        expected_current_attempt=expected_current_attempt,
                        reason_codes=("STEP_ATTEMPT_BASELINE_UNKNOWN",),
                    )
                current = 1
            if current != expected_current_attempt:
                return StepAttemptSequenceDecision(
                    status=StepAttemptSequenceStatus.CONFLICT,
                    step_execution_id=step_execution_id,
                    expected_current_attempt=expected_current_attempt,
                    reason_codes=("STEP_ATTEMPT_CONFLICT",),
                )
            next_attempt = current + 1
            self._current[step_execution_id] = next_attempt
            return StepAttemptSequenceDecision(
                status=StepAttemptSequenceStatus.CLAIMED,
                step_execution_id=step_execution_id,
                expected_current_attempt=expected_current_attempt,
                reason_codes=("STEP_ATTEMPT_CLAIMED",),
                next_attempt=next_attempt,
                claim_token=f"{step_execution_id}:attempt:{next_attempt}",
            )


class BasicStepReplaySafetyEvaluator:
    def __init__(self, *, idempotency_store: IdempotencyStore) -> None:
        self._idempotency_store = idempotency_store

    async def evaluate(self, request: StepReplaySafetyRequest) -> ReplaySafetyDecision:
        observation = request.observation
        policy = request.owner_policy
        if observation.has_unknown_tool_observation or (
            observation.has_untrusted_success_observation
        ):
            return ReplaySafetyDecision(
                status=ReplaySafetyStatus.UNKNOWN,
                reason_codes=("STEP_TOOL_EVIDENCE_UNKNOWN",),
            )
        if policy.idempotency.mode is IdempotencyMode.NON_IDEMPOTENT:
            return ReplaySafetyDecision(
                status=ReplaySafetyStatus.UNSAFE,
                reason_codes=("NON_IDEMPOTENT_SKILL_ATTEMPT_STARTED",),
            )
        if policy.idempotency.mode is IdempotencyMode.NATURAL:
            return ReplaySafetyDecision(
                status=ReplaySafetyStatus.SAFE,
                reason_codes=("NATURAL_SKILL_IDEMPOTENCY",),
            )
        if not observation.tool_journal:
            return ReplaySafetyDecision(
                status=ReplaySafetyStatus.UNKNOWN,
                reason_codes=("STEP_KEY_BASED_EVIDENCE_MISSING",),
            )
        for entry in observation.tool_journal:
            if entry.idempotency_key is None:
                return ReplaySafetyDecision(
                    status=ReplaySafetyStatus.UNKNOWN,
                    reason_codes=("STEP_TOOL_IDEMPOTENCY_KEY_MISSING",),
                )
            try:
                record = await self._idempotency_store.get(entry.idempotency_key)
            except Exception:  # noqa: BLE001
                record = None
            if record is None or record.status in {
                IdempotencyStatus.RESERVED,
                IdempotencyStatus.UNKNOWN,
            }:
                return ReplaySafetyDecision(
                    status=ReplaySafetyStatus.UNKNOWN,
                    reason_codes=("STEP_TOOL_IDEMPOTENCY_UNRESOLVED",),
                )
            if record.status not in {
                IdempotencyStatus.COMPLETED,
                IdempotencyStatus.FAILED,
            }:
                return ReplaySafetyDecision(
                    status=ReplaySafetyStatus.UNKNOWN,
                    reason_codes=("STEP_TOOL_IDEMPOTENCY_INVALID",),
                )
        return ReplaySafetyDecision(
            status=ReplaySafetyStatus.SAFE,
            reason_codes=("KEY_BASED_STEP_REPLAY_SAFE",),
        )


class BasicStepReliabilityEvaluator:
    def evaluate(
        self,
        *,
        observation: StepAttemptObservation,
        replay_safety: ReplaySafetyDecision | None,
        retry_decision: RetryDecision | None,
    ) -> StepReliabilityDecision:
        if observation.status is StepAttemptStatus.SUCCESS:
            return StepReliabilityDecision(
                disposition=StepReliabilityDisposition.FINALIZE,
                reason_codes=("STEP_ATTEMPT_SUCCESS",),
            )
        if observation.status in {
            StepAttemptStatus.WAITING,
            StepAttemptStatus.IN_PROGRESS,
        }:
            return StepReliabilityDecision(
                disposition=StepReliabilityDisposition.KEEP_RUNNING,
                reason_codes=("STEP_ATTEMPT_STILL_RUNNING",),
            )
        if observation.status in {
            StepAttemptStatus.CANCELLED,
            StepAttemptStatus.PREEMPTED,
        }:
            return StepReliabilityDecision(
                disposition=StepReliabilityDisposition.WAIT_RECOVERY,
                reason_codes=("STEP_CONTROL_FINALIZATION_DEFERRED",),
            )
        if observation.status in {
            StepAttemptStatus.FAILED,
            StepAttemptStatus.TIMEOUT,
            StepAttemptStatus.PARTIAL_SUCCESS,
        }:
            if (
                replay_safety is not None
                and replay_safety.status is ReplaySafetyStatus.SAFE
                and retry_decision is not None
                and retry_decision.status is RetryDecisionStatus.RETRY
                and retry_decision.next_attempt is not None
            ):
                return StepReliabilityDecision(
                    disposition=StepReliabilityDisposition.RETRY,
                    reason_codes=("STEP_RETRY_AUTHORIZED",),
                    next_attempt=retry_decision.next_attempt,
                )
            if (
                replay_safety is not None
                and replay_safety.status is ReplaySafetyStatus.UNKNOWN
            ) or (
                retry_decision is not None
                and retry_decision.status is RetryDecisionStatus.UNKNOWN
            ):
                return StepReliabilityDecision(
                    disposition=StepReliabilityDisposition.WAIT_RECOVERY,
                    reason_codes=("STEP_RETRY_SAFETY_UNKNOWN",),
                )
            return StepReliabilityDecision(
                disposition=StepReliabilityDisposition.FINALIZE,
                reason_codes=("STEP_RETRY_NOT_AUTHORIZED",),
            )
        return StepReliabilityDecision(
            disposition=StepReliabilityDisposition.ABORT_UNKNOWN,
            reason_codes=("STEP_ATTEMPT_NOT_FINALIZABLE",),
        )


class BasicStepFinalizationEvaluator:
    def evaluate(
        self,
        *,
        observation: StepAttemptObservation,
        reliability_decision: StepReliabilityDecision,
    ) -> StepFinalizationDecision:
        if reliability_decision.disposition is StepReliabilityDisposition.KEEP_RUNNING:
            return StepFinalizationDecision(
                disposition=StepFinalizationDisposition.KEEP_RUNNING,
                reason_codes=("STEP_KEEP_RUNNING",),
            )
        if reliability_decision.disposition is StepReliabilityDisposition.WAIT_RECOVERY:
            return StepFinalizationDecision(
                disposition=StepFinalizationDisposition.WAIT_RECOVERY,
                reason_codes=("STEP_WAIT_RECOVERY",),
            )
        if reliability_decision.disposition is StepReliabilityDisposition.ABORT_UNKNOWN:
            return StepFinalizationDecision(
                disposition=StepFinalizationDisposition.UNKNOWN,
                reason_codes=("STEP_FINALIZATION_UNKNOWN",),
            )
        if reliability_decision.disposition is StepReliabilityDisposition.RETRY:
            return StepFinalizationDecision(
                disposition=StepFinalizationDisposition.UNKNOWN,
                reason_codes=("STEP_RETRY_NOT_FINALIZATION",),
            )
        mapping = {
            StepAttemptStatus.SUCCESS: "SUCCESS",
            StepAttemptStatus.FAILED: "FAILED",
            StepAttemptStatus.TIMEOUT: "TIMEOUT",
        }
        value = mapping.get(observation.status)
        if value is None:
            return StepFinalizationDecision(
                disposition=StepFinalizationDisposition.UNKNOWN,
                reason_codes=("STEP_STATUS_REQUIRES_LATER_AUTHORITY",),
            )
        return StepFinalizationDecision(
            disposition=StepFinalizationDisposition.FINALIZE,
            reason_codes=("STEP_FINALIZATION_AUTHORIZED",),
            terminal_status=StepExecutionStatus(value),
        )
