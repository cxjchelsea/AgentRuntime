"""M0-IU5：Trace / Logging / Error Boundary 硬化校验。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from runtime.contracts import RuntimeResponse, UpdateResult
from runtime.orchestration.logging import NullLogHook, RecordingLogHook
from tests.orchestration_stubs import (
    ExplodingPlanner,
    WrongPhaseSafetyGuard,
    WrongTypePlanner,
    build_runtime_input,
)
from tests.test_runtime_orchestrator import (
    EXPECTED_CALL_ORDER,
    _build_orchestrator,
    _StubBundle,
)

SENSITIVE_TEXT = "USER_SECRET_TEXT"
SENSITIVE_TOKEN = "SECRET_TOKEN_VALUE"


def test_successful_turn_has_stable_unique_trace() -> None:
    """成功 turn 复用 RuntimeInput.trace_id，且 turn 内稳定。"""

    async def scenario() -> None:
        stub_bundle = _StubBundle()
        log_hook = RecordingLogHook()
        orchestrator = _build_orchestrator(stub_bundle, log_hook=log_hook)
        runtime_input = build_runtime_input()
        turn_outcome = await orchestrator.run(runtime_input)
        runtime_response, update_result = turn_outcome
        assert isinstance(runtime_response, RuntimeResponse)
        assert isinstance(update_result, UpdateResult)
        assert turn_outcome.trace.trace_id == runtime_input.trace_id
        assert turn_outcome.trace.request_id == runtime_input.request_id
        assert turn_outcome.trace.session_id == runtime_input.session_id
        assert turn_outcome.trace.turn_id
        assert turn_outcome.trace.status == "SUCCESS"
        event_trace_ids = {event.trace_id for event in turn_outcome.trace.stage_events}
        assert event_trace_ids == {runtime_input.trace_id}

    asyncio.run(scenario())


def test_all_fifteen_stages_have_timed_events_in_order() -> None:
    """15 个调用点都有 event，顺序与主链一致，成功 stage 有 duration。"""

    async def scenario() -> None:
        stub_bundle = _StubBundle()
        orchestrator = _build_orchestrator(stub_bundle)
        turn_outcome = await orchestrator.run(build_runtime_input())
        stage_names = [event.stage_name for event in turn_outcome.trace.stage_events]
        assert stage_names == EXPECTED_CALL_ORDER
        assert stub_bundle.call_recorder.entries == EXPECTED_CALL_ORDER
        for stage_event in turn_outcome.trace.stage_events:
            assert stage_event.started_at is not None
            assert stage_event.finished_at is not None
            assert stage_event.duration_ms is not None
            assert stage_event.duration_ms >= 0
            assert stage_event.status == "SUCCESS"
            assert stage_event.output_contract_type

    asyncio.run(scenario())


def test_stage_exception_is_wrapped_and_traced() -> None:
    """stage 异常包装为 StageExecutionError，trace 记录 stage_name，后续不再执行。"""
    from runtime.orchestration.errors import StageExecutionError

    async def scenario() -> None:
        stub_bundle = _StubBundle()
        stub_bundle.planner = ExplodingPlanner(stub_bundle.call_recorder)
        orchestrator = _build_orchestrator(stub_bundle)
        with pytest.raises(StageExecutionError) as captured:
            await orchestrator.run(build_runtime_input())
        assert captured.value.stage_name == "PLAN"
        assert captured.value.cause is not None
        assert "planner exploded" in str(captured.value.cause)
        assert not isinstance(captured.value, RuntimeResponse)
        assert captured.value.trace_context is not None
        error_event = captured.value.trace_context.stage_events[-1]
        assert error_event.stage_name == "PLAN"
        assert error_event.status == "ERROR"
        assert error_event.error_type == "StageExecutionError"
        recorded_stages = [
            event.stage_name for event in captured.value.trace_context.stage_events
        ]
        assert "UPDATE" not in recorded_stages
        assert "EXECUTE" not in recorded_stages
        assert "PLAN" in stub_bundle.call_recorder.entries
        assert "PLAN_VALIDATE" not in stub_bundle.call_recorder.entries

    asyncio.run(scenario())


def test_contract_type_error_fails_fast() -> None:
    """返回类型错误触发 ContractValidationError，不伪造下游结果。"""
    from runtime.orchestration.errors import ContractValidationError

    async def scenario() -> None:
        stub_bundle = _StubBundle()
        stub_bundle.planner = WrongTypePlanner(stub_bundle.call_recorder)
        orchestrator = _build_orchestrator(stub_bundle)
        with pytest.raises(ContractValidationError) as captured:
            await orchestrator.run(build_runtime_input())
        assert captured.value.stage_name == "PLAN"
        assert captured.value.trace_context is not None
        assert captured.value.trace_context.stage_events[-1].status == "ERROR"
        assert "POLICY_RECHECK" not in stub_bundle.call_recorder.entries

    asyncio.run(scenario())


def test_invariant_violation_fails_fast() -> None:
    """Safety phase 不变量违反触发 OrchestrationInvariantError。"""
    from runtime.orchestration.errors import OrchestrationInvariantError

    async def scenario() -> None:
        stub_bundle = _StubBundle()
        stub_bundle.safety_guard = WrongPhaseSafetyGuard(stub_bundle.call_recorder)
        orchestrator = _build_orchestrator(stub_bundle)
        with pytest.raises(OrchestrationInvariantError) as captured:
            await orchestrator.run(build_runtime_input())
        assert captured.value.stage_name == "SAFETY_EARLY"
        assert captured.value.trace_context is not None
        assert captured.value.trace_context.status == "ERROR"
        assert "CONTEXT" not in stub_bundle.call_recorder.entries

    asyncio.run(scenario())


def test_dependency_missing_still_explicit() -> None:
    """缺失依赖仍为 DependencyMissingError，不进入主链。"""
    from runtime.orchestration import RuntimeOrchestrator
    from runtime.orchestration.errors import DependencyMissingError

    stub_bundle = _StubBundle()
    with pytest.raises(DependencyMissingError):
        RuntimeOrchestrator(
            input_processor=stub_bundle.input_processor,
            safety_guard=stub_bundle.safety_guard,
            context_builder=stub_bundle.context_builder,
            understanding_engine=stub_bundle.understanding_engine,
            policy_engine=stub_bundle.policy_engine,
            planner=None,  # type: ignore[arg-type]
            plan_validator=stub_bundle.plan_validator,
            policy_rechecker=stub_bundle.policy_rechecker,
            execution_engine=stub_bundle.execution_engine,
            result_validator=stub_bundle.result_validator,
            response_planner=stub_bundle.response_planner,
            response_generator=stub_bundle.response_generator,
            response_validator=stub_bundle.response_validator,
            state_memory_updater=stub_bundle.state_memory_updater,
        )


def test_two_turns_share_session_but_not_trace() -> None:
    """session_id 可保持一致；两个 turn 的 trace_id / turn_id 不同。"""

    async def scenario() -> None:
        first_bundle = _StubBundle()
        second_bundle = _StubBundle()
        first_orchestrator = _build_orchestrator(first_bundle)
        second_orchestrator = _build_orchestrator(second_bundle)
        first_input = build_runtime_input(
            request_id="request-001",
            trace_id="trace-001",
            session_id="session-shared",
        )
        second_input = build_runtime_input(
            request_id="request-002",
            trace_id="trace-002",
            session_id="session-shared",
        )
        first_outcome = await first_orchestrator.run(first_input)
        second_outcome = await second_orchestrator.run(second_input)
        assert first_outcome.trace.session_id == "session-shared"
        assert second_outcome.trace.session_id == "session-shared"
        assert first_outcome.trace.trace_id != second_outcome.trace.trace_id
        assert first_outcome.trace.turn_id != second_outcome.trace.turn_id

    asyncio.run(scenario())


def test_logging_hook_can_be_replaced_or_disabled() -> None:
    """logging hook 可替换或禁用；默认不记录敏感 payload。"""

    async def scenario() -> None:
        sensitive_input = build_runtime_input(
            text=SENSITIVE_TEXT,
            input_payload={"token": SENSITIVE_TOKEN},
        )
        recording_bundle = _StubBundle()
        recording_hook = RecordingLogHook()
        recording_orchestrator = _build_orchestrator(
            recording_bundle, log_hook=recording_hook
        )
        await recording_orchestrator.run(sensitive_input)
        assert recording_hook.records
        start_events = [
            record
            for record in recording_hook.records
            if record.get("event") == "STAGE_START"
        ]
        end_events = [
            record
            for record in recording_hook.records
            if record.get("event") == "STAGE_END"
        ]
        assert {record["stage_name"] for record in start_events} == set(
            EXPECTED_CALL_ORDER
        )
        assert {record["stage_name"] for record in end_events} == set(
            EXPECTED_CALL_ORDER
        )
        serialized_logs = json.dumps(recording_hook.records, default=str)
        assert SENSITIVE_TEXT not in serialized_logs
        assert SENSITIVE_TOKEN not in serialized_logs
        for record in recording_hook.records:
            assert "text" not in record
            assert "input_payload" not in record
            assert "payload" not in record
            assert record.get("trace_id") == sensitive_input.trace_id

        disabled_bundle = _StubBundle()
        disabled_orchestrator = _build_orchestrator(
            disabled_bundle, log_hook=NullLogHook()
        )
        disabled_outcome = await disabled_orchestrator.run(sensitive_input)
        assert len(disabled_outcome.trace.stage_events) == 15

    asyncio.run(scenario())


def test_trace_does_not_change_chain_or_use_registry_or_domain() -> None:
    """Trace 不改变主链顺序，不调用 Registry 业务，不引入 Domain 值。"""

    async def scenario() -> None:
        stub_bundle = _StubBundle()
        from runtime.registries import SkillRegistry

        skill_registry = SkillRegistry()
        orchestrator = _build_orchestrator(stub_bundle, skill_registry=skill_registry)
        await orchestrator.run(build_runtime_input())
        assert stub_bundle.call_recorder.entries == EXPECTED_CALL_ORDER
        assert skill_registry.list() == []

    asyncio.run(scenario())
    forbidden_values = {"PLAY_CONTENT", "DISCOMFORT", "CLINICAL_DIAGNOSIS"}
    for source_path in Path("runtime/orchestration").glob("*.py"):
        source_tokens = set(source_path.read_text(encoding="utf-8").split())
        assert forbidden_values.isdisjoint(source_tokens)
