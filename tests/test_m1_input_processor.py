"""M1-IU1: real Input Processor tests.

Only node ① is real in these tests.  No Understanding, Policy, Domain, LLM,
Tool, Store, or Context implementation is introduced here.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta, timezone

import pytest

from runtime.contracts import InputSource, InputTriggerType, RuntimeInput
from runtime.input_processing import DefaultInputProcessor, InputNormalizationError
from runtime.orchestration import RuntimeOrchestrator
from tests.orchestration_stubs import (
    CallRecorder,
    StubContextBuilder,
    StubExecutionEngine,
    StubPlanValidator,
    StubPlanner,
    StubPolicyEngine,
    StubPolicyRechecker,
    StubResponseGenerator,
    StubResponsePlanner,
    StubResponseValidator,
    StubResultValidator,
    StubSafetyGuard,
    StubStateMemoryUpdater,
    StubUnderstandingEngine,
)


def _input(**overrides: object) -> RuntimeInput:
    values: dict[str, object] = {
        "request_id": "request-001",
        "trace_id": "trace-001",
        "session_id": "session-001",
        "subject_id": "subject-001",
        "identity_scope": "scope-001",
        "source": InputSource.USER,
        "trigger_type": InputTriggerType.USER_TEXT,
        "timestamp": datetime(2026, 9, 17, 8, 30, tzinfo=UTC),
        "text": "hello",
    }
    values.update(overrides)
    return RuntimeInput.model_validate(values)


def _process(runtime_input: RuntimeInput) -> RuntimeInput:
    return asyncio.run(DefaultInputProcessor().process(runtime_input))


def test_normalizes_visible_text_and_preserves_raw_text() -> None:
    original = "  Ｈｅｌｌｏ\u200b   世界\n "
    processed = _process(_input(text=original))

    assert processed.text == "Hello 世界"
    assert processed.raw_text == original


def test_existing_raw_text_is_not_overwritten() -> None:
    processed = _process(
        _input(text="  normalized   candidate ", raw_text="RAW   ASR   TEXT")
    )

    assert processed.text == "normalized candidate"
    assert processed.raw_text == "RAW   ASR   TEXT"


def test_raw_text_can_be_source_when_text_is_absent() -> None:
    processed = _process(_input(text=None, raw_text="  raw   only  "))

    assert processed.text == "raw only"
    assert processed.raw_text == "  raw   only  "


def test_normalizes_timestamp_to_utc() -> None:
    plus_eight = timezone(timedelta(hours=8))
    processed = _process(
        _input(timestamp=datetime(2026, 9, 17, 16, 30, tzinfo=plus_eight))
    )

    assert processed.timestamp == datetime(2026, 9, 17, 8, 30, tzinfo=UTC)
    assert processed.timestamp.tzinfo is UTC


def test_rejects_naive_timestamp_instead_of_guessing_timezone() -> None:
    with pytest.raises(InputNormalizationError, match="timezone-aware"):
        _process(_input(timestamp=datetime(2026, 9, 17, 8, 30)))


@pytest.mark.parametrize("confidence", [-0.01, 1.01, float("nan"), float("inf")])
def test_rejects_invalid_confidence(confidence: float) -> None:
    with pytest.raises(InputNormalizationError, match="confidence"):
        _process(_input(confidence=confidence))


def test_accepts_confidence_boundaries() -> None:
    assert _process(_input(confidence=0.0)).confidence == 0.0
    assert _process(_input(confidence=1.0)).confidence == 1.0


def test_required_identifiers_are_trimmed_but_never_inferred() -> None:
    processed = _process(
        _input(
            request_id=" request-001 ",
            trace_id=" trace-001 ",
            session_id=" session-001 ",
            subject_id=" subject-001 ",
            identity_scope=" scope-001 ",
        )
    )

    assert processed.request_id == "request-001"
    assert processed.trace_id == "trace-001"
    assert processed.session_id == "session-001"
    assert processed.subject_id == "subject-001"
    assert processed.identity_scope == "scope-001"


def test_blank_required_identifier_is_rejected() -> None:
    with pytest.raises(InputNormalizationError, match="subject_id"):
        _process(_input(subject_id="   "))


def test_optional_blank_identifiers_become_none() -> None:
    processed = _process(
        _input(actor_id=" ", device_id="  ", tenant_id=" tenant-1 ")
    )

    assert processed.actor_id is None
    assert processed.device_id is None
    assert processed.tenant_id == "tenant-1"


def test_empty_user_input_is_rejected() -> None:
    with pytest.raises(InputNormalizationError, match="user-originated input"):
        _process(_input(text="   ", raw_text=None, input_payload=None, segments=None))


def test_user_input_without_text_can_use_payload_or_segments() -> None:
    payload_input = _process(_input(text=None, input_payload={"audio_ref": "a-1"}))
    segment_input = _process(_input(text=None, segments=[{"text": "segment"}]))

    assert payload_input.input_payload == {"audio_ref": "a-1"}
    assert segment_input.segments == [{"text": "segment"}]


@pytest.mark.parametrize(
    ("source", "trigger_type", "payload"),
    [
        (InputSource.USER, InputTriggerType.USER_VOICE, {"audio_ref": "a-1"}),
        (InputSource.SCHEDULER, InputTriggerType.SCHEDULER_EVENT, {"event": "TEST"}),
        (InputSource.SYSTEM, InputTriggerType.SYSTEM_EVENT, {"event": "TEST"}),
        (InputSource.TOOL, InputTriggerType.TOOL_CALLBACK, {"result_ref": "r-1"}),
        (InputSource.SYSTEM, InputTriggerType.TIMEOUT, None),
        (InputSource.EXTERNAL, InputTriggerType.NETWORK_EVENT, {"status": "TEST"}),
    ],
)
def test_major_core_input_sources_remain_valid_runtime_inputs(
    source: InputSource,
    trigger_type: InputTriggerType,
    payload: dict[str, object] | None,
) -> None:
    processed = _process(
        _input(
            source=source,
            trigger_type=trigger_type,
            text=None,
            raw_text=None,
            input_payload=payload,
            segments=None,
        )
    )

    assert processed.source is source
    assert processed.trigger_type is trigger_type
    assert processed.input_payload == payload


def test_timeout_trigger_is_meaningful_without_fabricated_payload() -> None:
    processed = _process(
        _input(
            source=InputSource.SYSTEM,
            trigger_type=InputTriggerType.TIMEOUT,
            text=None,
            raw_text=None,
            input_payload=None,
            segments=None,
        )
    )

    assert processed.trigger_type is InputTriggerType.TIMEOUT
    assert processed.text is None


def test_payload_metadata_and_segments_are_preserved_without_domain_interpretation() -> None:
    payload = {"domain_event": "TEST_EVENT", "value": {"x": 1}}
    metadata = {"opaque_domain_key": "opaque-value"}
    segments = [{"start": 0.0, "end": 0.4, "text": "hello"}]

    processed = _process(
        _input(input_payload=payload, metadata=metadata, segments=segments)
    )

    assert processed.input_payload == payload
    assert processed.metadata == metadata
    assert processed.segments == segments


def test_processing_does_not_mutate_original_model() -> None:
    original = _input(text="  hello   world ", actor_id=" actor-1 ")
    processed = _process(original)

    assert original.text == "  hello   world "
    assert original.raw_text is None
    assert original.actor_id == " actor-1 "
    assert processed.text == "hello world"
    assert processed.raw_text == "  hello   world "
    assert processed.actor_id == "actor-1"


def test_processing_is_idempotent() -> None:
    once = _process(_input(text="  Ｔｅｓｔ   text "))
    twice = _process(once)

    assert twice == once


def test_real_input_processor_can_replace_m0_stub_in_full_runtime() -> None:
    recorder = CallRecorder()
    orchestrator = RuntimeOrchestrator(
        input_processor=DefaultInputProcessor(),
        safety_guard=StubSafetyGuard(recorder),
        context_builder=StubContextBuilder(recorder),
        understanding_engine=StubUnderstandingEngine(recorder),
        policy_engine=StubPolicyEngine(recorder),
        planner=StubPlanner(recorder),
        plan_validator=StubPlanValidator(recorder),
        policy_rechecker=StubPolicyRechecker(recorder),
        execution_engine=StubExecutionEngine(recorder),
        result_validator=StubResultValidator(recorder),
        response_planner=StubResponsePlanner(recorder),
        response_generator=StubResponseGenerator(recorder),
        response_validator=StubResponseValidator(recorder),
        state_memory_updater=StubStateMemoryUpdater(recorder),
    )

    outcome = asyncio.run(orchestrator.run(_input(text="  hello   runtime ")))

    assert outcome.runtime_response is not None
    assert outcome.update_result is not None
    assert [event.stage_name for event in outcome.trace.stage_events][0] == "INPUT"
    assert outcome.trace.stage_events[0].output_contract_type == "RuntimeInput"
