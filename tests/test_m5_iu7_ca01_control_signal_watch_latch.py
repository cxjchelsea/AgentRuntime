"""CA-M5-IU7-01 control-signal identity, watch, and latch contract gates."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from runtime.execution import (
    ExecutionControlLatchDecision,
    ExecutionControlLatchStatus,
    ExecutionControlSignal,
    ExecutionControlSignalType,
    LatchedExecutionControl,
    ObservedExecutionControl,
)

FIXED_TIME = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


def _cancel_signal(
    *,
    reason_code: str | None = "USER_STOP",
    source: str | None = "RUNTIME",
    signal_id: str | None = "signal-cancel-001",
    target_execution_id: str | None = "execution-001",
    issued_at: datetime | None = FIXED_TIME,
) -> ExecutionControlSignal:
    return ExecutionControlSignal(
        signal_type=ExecutionControlSignalType.CANCEL,
        reason_code=reason_code,
        source=source,
        signal_id=signal_id,
        target_execution_id=target_execution_id,
        issued_at=issued_at,
    )


def test_none_signal_carries_no_terminal_authority_identity() -> None:
    signal = ExecutionControlSignal(
        signal_type=ExecutionControlSignalType.NONE,
        source="RUNTIME",
    )

    assert signal.signal_id is None
    assert signal.target_execution_id is None
    assert signal.issued_at is None


def test_terminal_signal_requires_complete_auditable_envelope() -> None:
    missing_cases = (
        {"reason_code": None},
        {"source": None},
        {"signal_id": None},
        {"target_execution_id": None},
        {"issued_at": None},
    )

    for case in missing_cases:
        with pytest.raises(ValueError, match="requires"):
            _cancel_signal(
                reason_code=case.get("reason_code", "USER_STOP"),
                source=case.get("source", "RUNTIME"),
                signal_id=case.get("signal_id", "signal-cancel-001"),
                target_execution_id=case.get(
                    "target_execution_id",
                    "execution-001",
                ),
                issued_at=case.get("issued_at", FIXED_TIME),
            )


def test_terminal_signal_rejects_naive_issued_at() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _cancel_signal(issued_at=datetime(2026, 9, 22, 12, 0))


def test_none_signal_rejects_terminal_authority_fields() -> None:
    with pytest.raises(ValueError, match="NONE signal cannot carry signal_id"):
        ExecutionControlSignal(
            signal_type=ExecutionControlSignalType.NONE,
            signal_id="unexpected",
        )

    with pytest.raises(
        ValueError,
        match="NONE signal cannot carry target_execution_id",
    ):
        ExecutionControlSignal(
            signal_type=ExecutionControlSignalType.NONE,
            target_execution_id="unexpected",
        )

    with pytest.raises(ValueError, match="NONE signal cannot carry issued_at"):
        ExecutionControlSignal(
            signal_type=ExecutionControlSignalType.NONE,
            issued_at=FIXED_TIME,
        )


def test_observed_control_requires_terminal_signal_and_core_aware_time() -> None:
    observed = ObservedExecutionControl(
        signal=_cancel_signal(),
        observed_at=FIXED_TIME + timedelta(seconds=1),
    )

    assert observed.signal.target_execution_id == "execution-001"

    with pytest.raises(ValueError, match="requires CANCEL/PREEMPT"):
        ObservedExecutionControl(
            signal=ExecutionControlSignal(
                signal_type=ExecutionControlSignalType.NONE,
            ),
            observed_at=FIXED_TIME,
        )

    with pytest.raises(ValueError, match="timezone-aware"):
        ObservedExecutionControl(
            signal=_cancel_signal(),
            observed_at=datetime(2026, 9, 22, 12, 0),
        )


def test_latched_control_uses_core_local_monotonic_times() -> None:
    observed_at = FIXED_TIME + timedelta(seconds=1)
    latched = LatchedExecutionControl(
        signal=_cancel_signal(),
        observed_at=observed_at,
        latched_at=observed_at + timedelta(milliseconds=1),
    )

    assert latched.latched_at >= latched.observed_at

    with pytest.raises(ValueError, match="cannot be before"):
        LatchedExecutionControl(
            signal=_cancel_signal(),
            observed_at=observed_at,
            latched_at=FIXED_TIME,
        )


def test_latch_success_decisions_require_latched_control() -> None:
    latched = LatchedExecutionControl(
        signal=_cancel_signal(),
        observed_at=FIXED_TIME,
        latched_at=FIXED_TIME,
    )

    first = ExecutionControlLatchDecision(
        status=ExecutionControlLatchStatus.LATCHED,
        reason_codes=("CONTROL_LATCHED",),
        latched_control=latched,
    )
    replay = ExecutionControlLatchDecision(
        status=ExecutionControlLatchStatus.ALREADY_LATCHED,
        reason_codes=("CONTROL_ALREADY_LATCHED",),
        latched_control=latched,
    )

    assert first.latched_control == replay.latched_control

    with pytest.raises(ValueError, match="requires latched_control"):
        ExecutionControlLatchDecision(
            status=ExecutionControlLatchStatus.LATCHED,
            reason_codes=("CONTROL_LATCHED",),
        )


def test_latch_conflict_preserves_existing_barrier() -> None:
    latched = LatchedExecutionControl(
        signal=_cancel_signal(),
        observed_at=FIXED_TIME,
        latched_at=FIXED_TIME,
    )

    conflict = ExecutionControlLatchDecision(
        status=ExecutionControlLatchStatus.CONFLICT,
        reason_codes=("CONTROL_SIGNAL_CONFLICT",),
        latched_control=latched,
    )

    assert conflict.latched_control == latched

    with pytest.raises(ValueError, match="CONFLICT requires"):
        ExecutionControlLatchDecision(
            status=ExecutionControlLatchStatus.CONFLICT,
            reason_codes=("CONTROL_SIGNAL_CONFLICT",),
        )


def test_latch_unknown_cannot_claim_control_barrier() -> None:
    decision = ExecutionControlLatchDecision(
        status=ExecutionControlLatchStatus.UNKNOWN,
        reason_codes=("CONTROL_LATCH_UNKNOWN",),
    )

    assert decision.latched_control is None

    with pytest.raises(ValueError, match="UNKNOWN must not claim"):
        ExecutionControlLatchDecision(
            status=ExecutionControlLatchStatus.UNKNOWN,
            reason_codes=("CONTROL_LATCH_UNKNOWN",),
            latched_control=LatchedExecutionControl(
                signal=_cancel_signal(),
                observed_at=FIXED_TIME,
                latched_at=FIXED_TIME,
            ),
        )
