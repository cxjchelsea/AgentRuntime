"""B2 Foundation F bounded verification; not dual-Orchestrator wiring evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

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


@pytest.mark.parametrize(
    "field,value",
    [
        ("request_id", ""),
        ("session_id", " session "),
        ("identity_scope", 7),
        ("trace_id", " "),
    ],
)
def test_f_origin_rejects_invalid_fields(field: str, value: object) -> None:
    payload: dict[str, object] = {
        "request_id": "request-001",
        "session_id": "session-001",
        "identity_scope": "scope-001",
        "trace_id": "trace-001",
    }
    payload[field] = value
    with pytest.raises(M6FoundationError) as err:
        TurnOriginSnapshot(**payload)  # type: ignore[arg-type]
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
        assert (
            bundle.decision.disposition
            is NoGrantDownstreamDisposition.BLOCK_BEFORE_M7_M8
        )
        assert (
            bundle.decision.reason
            is NoGrantDownstreamReason.NO_AUTHORIZED_VALIDATION_GRANT
        )
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
        trace,
        TraceStatus.ERROR,
        "TURN_CANCELLED",
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
        trace,
        TraceStatus.ERROR,
        "STAGE_FAILED",
        emit_turn_end=broken,
        primary_exception=primary,
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


# F-B2-F-01: bounded corruption, replay, projection failure and turn isolation.


@pytest.mark.asyncio
async def test_f01_wrong_dto_consumes_handle_without_grant() -> None:
    handle = M6NoGrantFacadeFactory().open_turn(_origin())
    approved = build_approved_action_plan()
    approved.policy_snapshot = build_policy_decision().model_dump(mode="json")
    try:
        with pytest.raises(M6FoundationError) as invalid:
            await handle.validate(None, build_runtime_context(), approved)  # type: ignore[arg-type]
        assert invalid.value.code is M6FoundationErrorCode.INVALID_INPUT
        with pytest.raises(M6FoundationError) as repeat:
            await handle.validate(
                build_execution_result(), build_runtime_context(), approved
            )
        assert repeat.value.code is M6FoundationErrorCode.ALREADY_VALIDATED
    finally:
        handle.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("identity_scope", "different-scope"),
        ("request_id", "different-request"),
    ],
)
async def test_f01_execution_identity_forgery_denied(field: str, value: str) -> None:
    handle = M6NoGrantFacadeFactory().open_turn(_origin())
    approved = build_approved_action_plan()
    approved.policy_snapshot = build_policy_decision().model_dump(mode="json")
    execution = build_execution_result()
    setattr(execution, field, value)
    try:
        with pytest.raises(M6FoundationError) as rejection:
            await handle.validate(execution, build_runtime_context(), approved)
        assert rejection.value.code is M6FoundationErrorCode.ADMISSION_REJECTED
        with pytest.raises(M6FoundationError) as repeat:
            await handle.validate(
                build_execution_result(), build_runtime_context(), approved
            )
        assert repeat.value.code is M6FoundationErrorCode.ALREADY_VALIDATED
    finally:
        handle.close()


@pytest.mark.asyncio
async def test_f01_projection_failure_cannot_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runtime.validation.no_grant_projection import NoGrantProjectionController

    def fail_projection(*_args: object, **_kwargs: object) -> None:
        raise ValueError("injected projection fault")

    monkeypatch.setattr(NoGrantProjectionController, "project", fail_projection)
    handle = M6NoGrantFacadeFactory().open_turn(_origin())
    approved = build_approved_action_plan()
    approved.policy_snapshot = build_policy_decision().model_dump(mode="json")
    try:
        with pytest.raises(ValueError, match="injected projection fault"):
            await handle.validate(
                build_execution_result(), build_runtime_context(), approved
            )
        with pytest.raises(M6FoundationError) as repeated:
            await handle.validate(
                build_execution_result(), build_runtime_context(), approved
            )
        assert repeated.value.code is M6FoundationErrorCode.ALREADY_VALIDATED
    finally:
        handle.close()


@pytest.mark.asyncio
async def test_f01_interleaved_turn_handles_have_distinct_resources() -> None:
    factory = M6NoGrantFacadeFactory()
    first = factory.open_turn(_origin())
    second = factory.open_turn(_origin())
    assert first._slot is not second._slot
    assert first._controller is not second._controller
    approved = build_approved_action_plan()
    approved.policy_snapshot = build_policy_decision().model_dump(mode="json")
    try:
        first_result = await first.validate(
            build_execution_result(), build_runtime_context(), approved
        )
        second_result = await second.validate(
            build_execution_result(), build_runtime_context(), approved
        )
        assert first_result.decision.may_emit_positive_claim is False
        assert second_result.decision.may_commit_business_or_memory is False
        assert (
            first_result.decision.disposition
            is NoGrantDownstreamDisposition.BLOCK_BEFORE_M7_M8
        )
        assert (
            second_result.decision.disposition
            is NoGrantDownstreamDisposition.BLOCK_BEFORE_M7_M8
        )
        first.close()
        assert second._closed is False
    finally:
        first.close()
        second.close()


def test_f01_low_level_corrupted_origin_rejected_on_factory_constructor() -> None:
    origin = _origin()
    object.__setattr__(origin, "request_id", " different ")
    with pytest.raises(M6FoundationError) as rejected:
        M6NoGrantFacadeFactory().open_turn(origin)
    assert rejected.value.code is M6FoundationErrorCode.INVALID_ORIGIN


# F-B2-F-02: direct helper-level fault ordering only; G1/G2 lifecycle deferred.


def test_f02_preserves_same_primary_exception_with_failed_log_and_cleanup() -> None:
    import asyncio

    def run_case(primary: BaseException) -> None:
        trace = _trace()
        attempts: list[str] = []
        cleanup_errors: list[Exception] = []

        def failed_log(_trace: TraceContext) -> None:
            attempts.append("TURN_END")
            raise OSError("log unavailable")

        def caller() -> None:
            try:
                raise primary
            except BaseException as caught:
                try:
                    finish_turn_once(
                        trace,
                        TraceStatus.ERROR,
                        "TURN_CANCELLED"
                        if isinstance(caught, asyncio.CancelledError)
                        else "STAGE_FAILED",
                        emit_turn_end=failed_log,
                        primary_exception=caught,
                    )
                finally:
                    try:
                        raise OSError("cleanup unavailable")
                    except OSError as cleanup_error:
                        cleanup_errors.append(cleanup_error)
                raise

        with pytest.raises(BaseException) as observed:
            caller()
        assert observed.value is primary
        assert trace.status is TraceStatus.ERROR
        assert trace.finished_at is not None
        assert trace.error == (
            "TURN_CANCELLED"
            if isinstance(primary, asyncio.CancelledError)
            else "STAGE_FAILED"
        )
        assert attempts == ["TURN_END"]
        assert len(cleanup_errors) == 1
        assert finish_turn_once(trace, TraceStatus.ERROR) is False

    run_case(RuntimeError("stage"))
    run_case(asyncio.CancelledError())


@pytest.mark.parametrize("reason", ["", 42])
def test_f02_invalid_reason_fails_before_trace_mutation(reason: object) -> None:
    trace = _trace()
    with pytest.raises(TerminalizationError) as error:
        finish_turn_once(trace, TraceStatus.ERROR, reason)  # type: ignore[arg-type]
    assert error.value.code is TerminalizationErrorCode.INVALID_STATUS
    assert trace.status is TraceStatus.RUNNING
    assert trace.finished_at is None


def test_f02_half_terminal_running_with_timestamp_rejected() -> None:
    trace = _trace()
    trace.finished_at = datetime.now(UTC)
    with pytest.raises(TerminalizationError) as error:
        finish_turn_once(trace, TraceStatus.SUCCESS)
    assert error.value.code is TerminalizationErrorCode.INCONSISTENT_TERMINAL_STATE
    assert trace.status is TraceStatus.RUNNING


def test_f02_duplicate_terminal_calls_do_not_reemit() -> None:
    trace = _trace()
    attempts: list[str] = []
    assert finish_turn_once(
        trace,
        TraceStatus.ERROR,
        "FIRST",
        emit_turn_end=lambda _t: attempts.append("end"),
    )
    original_time = trace.finished_at
    for _ in range(5):
        assert not finish_turn_once(
            trace,
            TraceStatus.SUCCESS,
            "SECOND",
            emit_turn_end=lambda _t: attempts.append("duplicate"),
        )
    assert attempts == ["end"]
    assert trace.error == "FIRST"
    assert trace.finished_at == original_time


# G1: concrete RuntimeOrchestrator only. G2 remains deliberately unauthorized.

def _g1_orchestrator() -> tuple[Any, Any]:
    from runtime.orchestration.runtime import M6IntegrationMode, RuntimeOrchestrator
    from runtime.contracts import ActionPlanDraft, PolicyDecision, ApprovedActionPlan
    from tests.orchestration_stubs import StubPolicyRechecker
    from tests.test_runtime_orchestrator import _StubBundle

    class CanonicalPolicyRechecker(StubPolicyRechecker):
        async def recheck(
            self, draft: ActionPlanDraft, policy: PolicyDecision
        ) -> ApprovedActionPlan:
            approved = await super().recheck(draft, policy)
            approved.policy_snapshot = build_policy_decision().model_dump(mode="json")
            return approved

    bundle = _StubBundle()
    bundle.policy_rechecker = CanonicalPolicyRechecker(bundle.call_recorder)
    orchestrator = RuntimeOrchestrator(
        input_processor=bundle.input_processor,
        safety_guard=bundle.safety_guard,
        context_builder=bundle.context_builder,
        understanding_engine=bundle.understanding_engine,
        policy_engine=bundle.policy_engine,
        planner=bundle.planner,
        plan_validator=bundle.plan_validator,
        policy_rechecker=bundle.policy_rechecker,
        execution_engine=bundle.execution_engine,
        result_validator=bundle.result_validator,
        response_planner=bundle.response_planner,
        response_generator=bundle.response_generator,
        response_validator=bundle.response_validator,
        state_memory_updater=bundle.state_memory_updater,
        m6_integration_mode=M6IntegrationMode.DENY_ONLY_GATED,
        m6_no_grant_factory=M6NoGrantFacadeFactory(),
    )
    return orchestrator, bundle


@pytest.mark.asyncio
async def test_g1_denies_before_any_response_or_update() -> None:
    from runtime.orchestration.runtime import M6DownstreamBlocked
    from runtime.orchestration.trace import TraceStatus

    orchestrator, bundle = _g1_orchestrator()
    with pytest.raises(M6DownstreamBlocked) as blocked:
        await orchestrator.run(build_runtime_input())
    assert blocked.value.error_code == "NO_GRANT_DOWNSTREAM_BLOCKED"
    assert "RESPONSE_PLAN" not in bundle.call_recorder.entries
    assert "RESPONSE_GENERATE" not in bundle.call_recorder.entries
    assert "RESPONSE_VALIDATE" not in bundle.call_recorder.entries
    assert "UPDATE" not in bundle.call_recorder.entries
    assert "RESULT_VALIDATE" not in bundle.call_recorder.entries
    assert orchestrator.last_trace.status is TraceStatus.ERROR


@pytest.mark.asyncio
async def test_g1_constructor_rejects_missing_facade() -> None:
    from runtime.orchestration.runtime import M6IntegrationMode, RuntimeOrchestrator
    from tests.test_runtime_orchestrator import _StubBundle

    bundle = _StubBundle()
    with pytest.raises(ValueError, match="factory"):
        RuntimeOrchestrator(
            input_processor=bundle.input_processor, safety_guard=bundle.safety_guard,
            context_builder=bundle.context_builder, understanding_engine=bundle.understanding_engine,
            policy_engine=bundle.policy_engine, planner=bundle.planner,
            plan_validator=bundle.plan_validator, policy_rechecker=bundle.policy_rechecker,
            execution_engine=bundle.execution_engine, result_validator=bundle.result_validator,
            response_planner=bundle.response_planner, response_generator=bundle.response_generator,
            response_validator=bundle.response_validator,
            state_memory_updater=bundle.state_memory_updater,
            m6_integration_mode=M6IntegrationMode.DENY_ONLY_GATED,
        )


class _G1FailingLog:
    def __init__(self, event: str) -> None:
        self.event = event
        self.attempts: list[str] = []

    def emit(self, record: dict[str, object]) -> None:
        event = str(record["event"])
        self.attempts.append(event)
        if event == self.event:
            raise OSError("injected log failure")


@pytest.mark.asyncio
@pytest.mark.parametrize("event", ["TURN_START", "STAGE_START", "STAGE_END", "TURN_END"])
async def test_g1_log_failure_never_returns_success(event: str) -> None:
    from runtime.orchestration.trace import TraceStatus

    orchestrator, bundle = _g1_orchestrator()
    hook = _G1FailingLog(event)
    orchestrator.log_hook = hook
    with pytest.raises(BaseException):
        await orchestrator.run(build_runtime_input())
    assert orchestrator.last_trace is not None
    assert orchestrator.last_trace.status is TraceStatus.ERROR
    assert orchestrator.last_trace.finished_at is not None
    assert "RESPONSE_PLAN" not in bundle.call_recorder.entries
    assert "UPDATE" not in bundle.call_recorder.entries
    assert hook.attempts.count("TURN_END") <= 1


@pytest.mark.asyncio
async def test_g1_input_identity_mutation_prevents_execution() -> None:
    from runtime.orchestration.trace import TraceStatus

    orchestrator, bundle = _g1_orchestrator()
    original = orchestrator.input_processor.process

    async def changed_identity(raw: object) -> object:
        processed = await original(raw)  # type: ignore[arg-type]
        processed.session_id = "forged-session"
        return processed

    orchestrator.input_processor.process = changed_identity  # type: ignore[method-assign]
    with pytest.raises(M6FoundationError) as rejection:
        await orchestrator.run(build_runtime_input())
    assert rejection.value.code is M6FoundationErrorCode.ORIGIN_CHANGED
    assert orchestrator.last_trace is not None
    assert orchestrator.last_trace.status is TraceStatus.ERROR
    assert "EXECUTE" not in bundle.call_recorder.entries
    assert "RESPONSE_PLAN" not in bundle.call_recorder.entries
