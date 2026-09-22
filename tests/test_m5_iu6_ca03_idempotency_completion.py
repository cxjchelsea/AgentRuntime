"""CA-M5-IU6-03 atomic idempotency completion contract gates."""

from __future__ import annotations

from runtime.execution import (
    IdempotencyCompletionDecision,
    IdempotencyCompletionStatus,
    IdempotencyRecord,
    IdempotencyStatus,
)


def _completed_record() -> IdempotencyRecord:
    return IdempotencyRecord(
        key="idem-001",
        execution_id="exec-001",
        step_id="step-001",
        step_execution_id="step-exec-001",
        tool_id="TOOL_A",
        tool_version="1.0.0",
        operation_key="operation-001",
        operation_fingerprint="sha256:abc",
        status=IdempotencyStatus.COMPLETED,
        tool_call_id="tool-call-001",
        result_reference="result://tool-call-001",
    )


def test_completed_decision_requires_completed_record() -> None:
    record = _completed_record()

    decision = IdempotencyCompletionDecision(
        status=IdempotencyCompletionStatus.COMPLETED,
        reason_codes=("IDEMPOTENCY_COMPLETED_ATOMICALLY",),
        completed_record=record,
    )

    assert decision.completed_record is record


def test_completed_decision_rejects_missing_record() -> None:
    try:
        IdempotencyCompletionDecision(
            status=IdempotencyCompletionStatus.COMPLETED,
            reason_codes=("IDEMPOTENCY_COMPLETED_ATOMICALLY",),
        )
    except ValueError as exc:
        assert "COMPLETED idempotency completion requires COMPLETED record" in str(exc)
    else:
        raise AssertionError("COMPLETED decision must require completed_record")


def test_conflict_cannot_expose_completed_record() -> None:
    try:
        IdempotencyCompletionDecision(
            status=IdempotencyCompletionStatus.CONFLICT,
            reason_codes=("IDEMPOTENCY_COMPLETION_CONFLICT",),
            completed_record=_completed_record(),
        )
    except ValueError as exc:
        assert "must not expose record" in str(exc)
    else:
        raise AssertionError("CONFLICT must not expose completed record")


def test_unknown_cannot_expose_completed_record() -> None:
    try:
        IdempotencyCompletionDecision(
            status=IdempotencyCompletionStatus.UNKNOWN,
            reason_codes=("IDEMPOTENCY_COMPLETION_UNKNOWN",),
            completed_record=_completed_record(),
        )
    except ValueError as exc:
        assert "must not expose record" in str(exc)
    else:
        raise AssertionError("UNKNOWN must not expose completed record")


def test_completion_decision_requires_reason_codes() -> None:
    try:
        IdempotencyCompletionDecision(
            status=IdempotencyCompletionStatus.CONFLICT,
            reason_codes=(),
        )
    except ValueError as exc:
        assert "reason_codes" in str(exc)
    else:
        raise AssertionError("completion decision must require reason_codes")
