"""M5-IU6 Formal Implementation behavioral gates."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from runtime.execution.capability_resolution import CapabilityExecutionOwner
from runtime.execution.models import (
    M5ToolResult,
    StepExecutionStatus,
    ToolExecutionStatus,
)
from runtime.execution.reliability import (
    IdempotencyMode,
    ReliabilityCapabilityKind,
    ReplaySafetyDecision,
    ReplaySafetyStatus,
    ResolvedIdempotencyPolicy,
    ResolvedReliabilityPolicy,
    ResolvedRetryPolicy,
    ResolvedTimeoutPolicy,
    RetryDecisionContext,
    RetryDecisionStatus,
    RetryTriggerStatus,
    SideEffectClass,
)
from runtime.execution.reliability_boundary import (
    StepFinalizationDisposition,
    StepReliabilityDecision,
    StepReliabilityDisposition,
    StepReplaySafetyRequest,
)
from runtime.execution.reliability_defaults import (
    BasicRetryDecisionEvaluator,
    BasicStepFinalizationEvaluator,
    BasicStepReplaySafetyEvaluator,
    InMemoryIdempotencyCoordinator,
    InMemoryStepAttemptSequenceAuthority,
)
from runtime.execution.result_collection import (
    StepAttemptObservation,
    StepAttemptStatus,
)
from runtime.execution.stores import IdempotencyRecord, IdempotencyStatus


def _skill_policy(mode: IdempotencyMode) -> ResolvedReliabilityPolicy:
    return ResolvedReliabilityPolicy(
        capability_kind=ReliabilityCapabilityKind.SKILL,
        capability_id="SKILL_A",
        capability_version="1.0.0",
        policy_identity="skill-policy@sha256:abc",
        timeout=ResolvedTimeoutPolicy(timeout_seconds=None),
        retry=ResolvedRetryPolicy(
            enabled=True,
            max_attempts=3,
            retry_on_statuses=(RetryTriggerStatus.FAILED,),
            backoff_seconds=0.0,
        ),
        idempotency=ResolvedIdempotencyPolicy(mode=mode),
        side_effect_class=SideEffectClass.NONE,
    )


def _observation(
    *,
    status: StepAttemptStatus = StepAttemptStatus.FAILED,
) -> StepAttemptObservation:
    return StepAttemptObservation(
        step_id="step-001",
        step_execution_id="step-exec-001",
        attempt_number=1,
        status=status,
        execution_owner=CapabilityExecutionOwner.SKILL,
        reason_codes=("OBSERVED",),
        observed_at=datetime(2026, 9, 22, 10, 0, tzinfo=UTC),
        owner_capability_id="SKILL_A",
        owner_capability_version="1.0.0",
    )


def test_key_based_step_replay_without_tool_evidence_is_unknown() -> None:
    evaluator = BasicStepReplaySafetyEvaluator(
        idempotency_store=InMemoryIdempotencyCoordinator()
    )
    request = StepReplaySafetyRequest(
        observation=_observation(),
        owner_policy=_skill_policy(IdempotencyMode.KEY_BASED),
    )

    decision = asyncio.run(evaluator.evaluate(request))

    assert decision.status is ReplaySafetyStatus.UNKNOWN
    assert decision.reason_codes == ("STEP_KEY_BASED_EVIDENCE_MISSING",)


def test_natural_step_replay_can_be_safe_without_tool_journal() -> None:
    evaluator = BasicStepReplaySafetyEvaluator(
        idempotency_store=InMemoryIdempotencyCoordinator()
    )
    request = StepReplaySafetyRequest(
        observation=_observation(),
        owner_policy=_skill_policy(IdempotencyMode.NATURAL),
    )

    decision = asyncio.run(evaluator.evaluate(request))

    assert decision.status is ReplaySafetyStatus.SAFE


def test_non_idempotent_step_replay_is_unsafe() -> None:
    evaluator = BasicStepReplaySafetyEvaluator(
        idempotency_store=InMemoryIdempotencyCoordinator()
    )
    request = StepReplaySafetyRequest(
        observation=_observation(),
        owner_policy=_skill_policy(IdempotencyMode.NON_IDEMPOTENT),
    )

    decision = asyncio.run(evaluator.evaluate(request))

    assert decision.status is ReplaySafetyStatus.UNSAFE


def test_step_attempt_sequence_is_monotonic_and_conflict_safe() -> None:
    authority = InMemoryStepAttemptSequenceAuthority()

    claimed = asyncio.run(
        authority.claim_next(
            step_execution_id="step-exec-001",
            expected_current_attempt=1,
        )
    )
    conflict = asyncio.run(
        authority.claim_next(
            step_execution_id="step-exec-001",
            expected_current_attempt=1,
        )
    )

    assert claimed.next_attempt == 2
    assert conflict.next_attempt is None


def test_finalization_only_maps_authorized_terminal_statuses() -> None:
    evaluator = BasicStepFinalizationEvaluator()

    success = evaluator.evaluate(
        observation=_observation(status=StepAttemptStatus.SUCCESS),
        reliability_decision=StepReliabilityDecision(
            disposition=StepReliabilityDisposition.FINALIZE,
            reason_codes=("DONE",),
        ),
    )
    partial = evaluator.evaluate(
        observation=_observation(status=StepAttemptStatus.PARTIAL_SUCCESS),
        reliability_decision=StepReliabilityDecision(
            disposition=StepReliabilityDisposition.FINALIZE,
            reason_codes=("NOT_RETRIED",),
        ),
    )

    assert success.disposition is StepFinalizationDisposition.FINALIZE
    assert success.terminal_status is StepExecutionStatus.SUCCESS
    assert partial.disposition is StepFinalizationDisposition.FINALIZE
    assert partial.terminal_status is StepExecutionStatus.SUCCESS
    assert partial.degraded is True


def test_retry_evaluator_requires_safe_replay_and_budget() -> None:
    evaluator = BasicRetryDecisionEvaluator()
    policy = ResolvedRetryPolicy(
        enabled=True,
        max_attempts=2,
        retry_on_statuses=(RetryTriggerStatus.FAILED,),
        backoff_seconds=0.0,
    )

    retry = evaluator.evaluate(
        policy=policy,
        context=RetryDecisionContext(
            current_attempt=1,
            result_status=RetryTriggerStatus.FAILED,
            error_code=None,
            replay_safety=ReplaySafetyDecision(
                status=ReplaySafetyStatus.SAFE,
                reason_codes=("SAFE",),
            ),
            deadline_remaining_seconds=10.0,
        ),
    )
    stop = evaluator.evaluate(
        policy=policy,
        context=RetryDecisionContext(
            current_attempt=2,
            result_status=RetryTriggerStatus.FAILED,
            error_code=None,
            replay_safety=ReplaySafetyDecision(
                status=ReplaySafetyStatus.SAFE,
                reason_codes=("SAFE",),
            ),
            deadline_remaining_seconds=10.0,
        ),
    )

    assert retry.status is RetryDecisionStatus.RETRY
    assert retry.next_attempt == 2
    assert stop.status is RetryDecisionStatus.STOP


def test_inmemory_idempotency_completion_is_atomic_and_recoverable() -> None:
    coordinator = InMemoryIdempotencyCoordinator()
    record = IdempotencyRecord(
        key="idem-001",
        execution_id="exec-001",
        step_id="step-001",
        step_execution_id="step-exec-001",
        tool_id="TOOL_A",
        tool_version="1.0.0",
        operation_key="operation-001",
        operation_fingerprint="sha256:abc",
        status=IdempotencyStatus.RESERVED,
    )
    result = M5ToolResult(
        tool_call_id="tool-call-001",
        tool_id="TOOL_A",
        status=ToolExecutionStatus.SUCCESS,
        attempt=1,
    )

    assert asyncio.run(coordinator.reserve(record)) is True
    completed = asyncio.run(
        coordinator.complete(
            reserved_record=record,
            result=result,
        )
    )
    stored = asyncio.run(coordinator.get(record.key))
    assert stored is not None
    recovered = asyncio.run(coordinator.resolve_completed(stored))

    assert completed.completed_record is not None
    assert completed.completed_record.status is IdempotencyStatus.COMPLETED
    assert stored.status is IdempotencyStatus.COMPLETED
    assert recovered == result
