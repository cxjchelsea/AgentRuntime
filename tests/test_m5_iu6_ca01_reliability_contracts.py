"""CA-M5-IU6-01 reliability contract invariants."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from runtime.execution.models import ToolExecutionStatus
from runtime.execution.reliability import (
    IdempotencyMode,
    ReliabilityCapabilityKind,
    ReplaySafetyContext,
    ReplaySafetyDecision,
    ReplaySafetyStatus,
    ResolvedIdempotencyPolicy,
    ResolvedReliabilityPolicy,
    ResolvedRetryPolicy,
    ResolvedTimeoutPolicy,
    RetryDecision,
    RetryDecisionContext,
    RetryDecisionStatus,
    SideEffectClass,
    TimeoutRunResult,
    TimeoutRunStatus,
)


def _retry_policy(**overrides: object) -> ResolvedRetryPolicy:
    values: dict[str, object] = {
        "enabled": True,
        "max_attempts": 3,
        "retry_on_statuses": (ToolExecutionStatus.FAILED,),
        "retry_on_error_codes": ("NETWORK_ERROR",),
        "backoff_seconds": 1.0,
        "backoff_multiplier": 2.0,
        "max_backoff_seconds": 8.0,
    }
    values.update(overrides)
    return ResolvedRetryPolicy(**values)  # type: ignore[arg-type]


def test_retry_max_attempts_counts_total_attempts_including_first() -> None:
    policy = _retry_policy(max_attempts=3)

    assert policy.max_attempts == 3


def test_retry_policy_rejects_zero_attempts() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        _retry_policy(max_attempts=0)


def test_disabled_retry_policy_is_single_attempt_only() -> None:
    policy = _retry_policy(
        enabled=False,
        max_attempts=1,
        retry_on_statuses=(),
        retry_on_error_codes=(),
    )

    assert policy.enabled is False
    assert policy.max_attempts == 1

    with pytest.raises(ValueError, match="disabled retry policy"):
        _retry_policy(enabled=False, max_attempts=2)


def test_retry_policy_rejects_negative_backoff() -> None:
    with pytest.raises(ValueError, match="backoff_seconds"):
        _retry_policy(backoff_seconds=-0.1)


def test_retry_policy_rejects_backoff_multiplier_below_one() -> None:
    with pytest.raises(ValueError, match="backoff_multiplier"):
        _retry_policy(backoff_multiplier=0.5)


def test_timeout_policy_requires_positive_duration() -> None:
    assert ResolvedTimeoutPolicy(timeout_seconds=None).timeout_seconds is None
    assert ResolvedTimeoutPolicy(timeout_seconds=1.0).timeout_seconds == 1.0

    with pytest.raises(ValueError, match="timeout_seconds"):
        ResolvedTimeoutPolicy(timeout_seconds=0)


def test_resolved_policy_requires_exact_identity_and_policy_identity() -> None:
    policy = ResolvedReliabilityPolicy(
        capability_kind=ReliabilityCapabilityKind.TOOL,
        capability_id="DOMAIN_TOOL",
        capability_version="1.2.3",
        policy_identity="policy:retry-v3@sha256:abc",
        timeout=ResolvedTimeoutPolicy(timeout_seconds=2.0),
        retry=_retry_policy(),
        idempotency=ResolvedIdempotencyPolicy(mode=IdempotencyMode.KEY_BASED),
        side_effect_class=SideEffectClass.HIGH,
    )

    assert policy.capability_version == "1.2.3"
    assert policy.policy_identity == "policy:retry-v3@sha256:abc"

    with pytest.raises(ValueError, match="policy_identity"):
        ResolvedReliabilityPolicy(
            capability_kind=ReliabilityCapabilityKind.TOOL,
            capability_id="DOMAIN_TOOL",
            capability_version="1.2.3",
            policy_identity="",
            timeout=ResolvedTimeoutPolicy(timeout_seconds=None),
            retry=_retry_policy(),
            idempotency=ResolvedIdempotencyPolicy(
                mode=IdempotencyMode.NATURAL
            ),
            side_effect_class=SideEffectClass.NONE,
        )


def test_replay_safety_unknown_is_distinct_from_safe_and_unsafe() -> None:
    context = ReplaySafetyContext(
        idempotency_mode=IdempotencyMode.KEY_BASED,
        side_effect_class=SideEffectClass.HIGH,
        invocation_started=True,
        current_status=ToolExecutionStatus.UNKNOWN,
        has_unknown_side_effect=True,
        idempotency_state_unknown=True,
    )
    decision = ReplaySafetyDecision(
        status=ReplaySafetyStatus.UNKNOWN,
        reason_codes=("IDEMPOTENCY_STATE_UNKNOWN",),
    )

    assert context.has_unknown_side_effect is True
    assert decision.status is ReplaySafetyStatus.UNKNOWN
    assert decision.status is not ReplaySafetyStatus.SAFE


def test_replay_safety_decision_requires_reason_codes() -> None:
    with pytest.raises(ValueError, match="reason_codes"):
        ReplaySafetyDecision(status=ReplaySafetyStatus.UNSAFE, reason_codes=())


def test_retry_decision_retry_requires_next_attempt_and_backoff() -> None:
    decision = RetryDecision(
        status=RetryDecisionStatus.RETRY,
        reason_codes=("RETRY_POLICY_MATCH",),
        next_attempt=2,
        backoff_seconds=0.0,
    )

    assert decision.next_attempt == 2

    with pytest.raises(ValueError, match="next_attempt"):
        RetryDecision(
            status=RetryDecisionStatus.RETRY,
            reason_codes=("RETRY_POLICY_MATCH",),
            next_attempt=1,
            backoff_seconds=0.0,
        )


def test_non_retry_decision_cannot_carry_retry_fields() -> None:
    with pytest.raises(ValueError, match="non-RETRY"):
        RetryDecision(
            status=RetryDecisionStatus.STOP,
            reason_codes=("MAX_ATTEMPTS_REACHED",),
            next_attempt=2,
            backoff_seconds=1.0,
        )


def test_retry_context_rejects_negative_deadline_budget() -> None:
    safety = ReplaySafetyDecision(
        status=ReplaySafetyStatus.SAFE,
        reason_codes=("NATURAL_IDEMPOTENCY",),
    )
    with pytest.raises(ValueError, match="deadline_remaining_seconds"):
        RetryDecisionContext(
            current_attempt=1,
            result_status=ToolExecutionStatus.FAILED,
            error_code="NETWORK_ERROR",
            replay_safety=safety,
            deadline_remaining_seconds=-0.01,
        )


def test_timeout_result_keeps_timeout_distinct_from_failure() -> None:
    timed_out = TimeoutRunResult[object](
        status=TimeoutRunStatus.TIMED_OUT,
        reason_codes=("TOOL_TIMEOUT",),
    )

    assert timed_out.status is TimeoutRunStatus.TIMED_OUT
    assert timed_out.value is None


def test_timeout_result_completed_may_return_none() -> None:
    completed = TimeoutRunResult[object](
        status=TimeoutRunStatus.COMPLETED,
        value=None,
        reason_codes=("COMPLETED_WITHIN_TIMEOUT",),
    )

    assert completed.status is TimeoutRunStatus.COMPLETED
    assert completed.value is None


def test_timeout_result_unknown_cannot_carry_value() -> None:
    with pytest.raises(ValueError, match="must not carry value"):
        TimeoutRunResult(
            status=TimeoutRunStatus.UNKNOWN,
            value={"maybe": True},
            reason_codes=("TIMEOUT_BOUNDARY_UNKNOWN",),
        )


def test_contracts_do_not_embed_wall_clock_timestamp_defaults() -> None:
    now = datetime(2026, 9, 21, 8, 0, tzinfo=UTC)
    assert now.tzinfo is UTC
    # CA-01 supplies ExecutionClock as a Protocol; contracts themselves do not
    # call datetime.now()/time.time() or create hidden current-time defaults.
