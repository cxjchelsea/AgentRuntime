"""B2 Foundation F bounded verification; not dual-Orchestrator wiring evidence."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from runtime.orchestration.m6_terminalization import (
    TerminalizationError,
    TerminalizationErrorCode,
    finish_turn_once,
)
from runtime.orchestration.trace import TraceContext, TraceStatus
from runtime.validation.m6_no_grant_facade import (
    M6FoundationError,
    M6FoundationErrorCode,
    M6NoGrantFacadeFactory,
    TurnOriginSnapshot,
)
from runtime.validation.no_grant_downstream_policy import (
    NoGrantDownstreamDisposition,
    NoGrantDownstreamReason,
)
from tests.orchestration_stubs import (
    build_approved_action_plan,
    build_execution_result,
    build_policy_decision,
    build_runtime_context,
    build_runtime_input,
)


def _trace() -> TraceContext:
    return TraceContext(
        request_id="request-001",
        trace_id="trace-001",
        session_id="session-001",
        turn_id="turn-001",
        started_at=datetime.now(UTC),
    )


def _origin() -> TurnOriginSnapshot:
    return TurnOriginSnapshot.from_runtime_input(build_runtime_input())


@pytest.mark.parametrize("field,value", [
    ("request_id", ""),
    ("session_id", " session "),
    ("identity_scope", 7),
    ("trace_id", " "),
])
def test_f_origin_rejects_invalid_fields(field: str, value: object) -> None:
    baseline = dict(
        request_id="request-001",
        session_id="session-001",
        identity_scope="scope-001",
        trace_id="trace-001",
    )
    baseline[field] = value
    with pytest.raises(M6FoundationError) as err:
        TurnOriginSnapshot(**baseline)  # type: ignore[arg-type]
    assert err.value.code is M6FoundationErrorCode.INVALID_ORIGIN


def test_f_processed_origin_mismatch_fails_closed() -> None:
    processed = build_runtime_input()
    processed.session_id = "different"
    with pytest.raises(M6FoundationError) as err:
        _origin().assert_processed_identity(processed)
    assert err.value.code is M6FoundationErrorCode.ORIGIN_CHANGED


@pytest.mark.asyncio
async def test_f_handle_returns_non_authoritative_no_grant() -> None:
    origin = _origin()
    handle = M6NoGrantFacadeFactory().open_turn(origin)
    execution = build_execution_result()
    approved = build_approved_action_plan()
    approved.policy_snapshot = build_policy_decision().model_dump(mode="json")
    try:
        bundle = await handle.validate(execution, build_runtime_context(), approved)
        assert bundle.validated.request_id == origin.request_id
        assert bundle.decision.disposition is NoGrantDownstreamDisposition.BLOCK_BEFORE_M7_M8
        assert bundle.decision.reason is NoGrantDownstreamReason.NO_AUTHORIZED_VALIDATION_GRANT
        assert bundle.decision.may_call_response_planner is False
        assert bundle.decision.may_call_state_memory_updater is False
        with pytest.raises(M6FoundationError) as err:
            await handle.validate(execution, build_runtime_context(), approved)
        assert err.value.code is M6FoundationErrorCode.ALREADY_VALIDATED
    finally:
        handle.close()
    with pytest.raises(M6FoundationError) as closed:
        await handle.validate(execution, build_runtime_context(), approved)
    assert closed.value.code is M6FoundationErrorCode.CLOSED_TURN


@pytest.mark.asyncio
async def test_f_rejected_admission_burns_one_shot() -> None:
    handle = M6NoGrantFacadeFactory().open_turn(_origin())
    approved = build_approved_action_plan()
    approved.policy_snapshot = build_policy_decision().model_dump(mode="json")
    execution = build_execution_result()
    execution.request_id = "forged"
    with pytest.raises(M6FoundationError) as err:
        await handle.validate(execution, build_runtime_context(), approved)
    assert err.value.code is M6FoundationErrorCode.ADMISSION_REJECTED
    with pytest.raises(M6FoundationError) as repeat:
        await handle.validate(execution, build_runtime_context(), approved)
    assert repeat.value.code is M6FoundationErrorCode.ALREADY_VALIDATED
    handle.close()
    handle.close()


def test_f_terminalization_once_and_original_reason() -> None:
    trace = _trace()
    emitted: list[str] = []
    assert finish_turn_once(
        trace, TraceStatus.ERROR, "TURN_CANCELLED",
        emit_turn_end=lambda t: emitted.append(t.status.value),
    )
    finished_at = trace.finished_at
    assert not finish_turn_once(
        trace, TraceStatus.SUCCESS, emit_turn_end=lambda t: emitted.append("BAD")
    )
    assert emitted == ["ERROR"]
    assert trace.finished_at == finished_at
    assert trace.error == "TURN_CANCELLED"


def test_f_logging_failure_cannot_reopen_terminal_trace() -> None:
    trace = _trace()

    def broken(_trace: TraceContext) -> None:
        raise RuntimeError("log down")

    with pytest.raises(TerminalizationError) as err:
        finish_turn_once(trace, TraceStatus.ERROR, "FAULT", emit_turn_end=broken)
    assert err.value.code is TerminalizationErrorCode.TERMINAL_LOG_FAILURE
    assert trace.status is TraceStatus.ERROR
    assert trace.finished_at is not None
    assert not finish_turn_once(trace, TraceStatus.SUCCESS)


def test_f_logging_failure_does_not_mask_primary_exception() -> None:
    trace = _trace()
    primary = RuntimeError("original")

    def broken(_trace: TraceContext) -> None:
        raise RuntimeError("logging failed")

    assert finish_turn_once(
        trace, TraceStatus.ERROR, "STAGE_FAILED",
        emit_turn_end=broken, primary_exception=primary,
    )
    assert trace.error == "STAGE_FAILED"


def test_f_rejects_half_terminal_and_running_terminalization() -> None:
    trace = _trace()
    trace.status = TraceStatus.ERROR
    with pytest.raises(TerminalizationError) as err:
        finish_turn_once(trace, TraceStatus.ERROR)
    assert err.value.code is TerminalizationErrorCode.INCONSISTENT_TERMINAL_STATE

    with pytest.raises(TerminalizationError) as wrong:
        finish_turn_once(_trace(), TraceStatus.RUNNING)
    assert wrong.value.code is TerminalizationErrorCode.INVALID_STATUS


def test_f_factory_does_not_share_handles() -> None:
    factory = M6NoGrantFacadeFactory()
    origin = _origin()
    a = factory.open_turn(origin)
    b = factory.open_turn(origin)
    assert a is not b
    a.close()
    assert b._closed is False
    b.close()
