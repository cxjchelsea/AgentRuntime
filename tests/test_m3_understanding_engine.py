"""M3-IU5 final merge and composed UnderstandingEngine gates."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from runtime.contracts import (
    IdentityContext,
    IdentityStatus,
    InputSource,
    InputTriggerType,
    RuntimeContext,
    RuntimeControlState,
    RuntimeInput,
    RuntimeStateContext,
    SessionContext,
    UnderstandingState,
)
from runtime.contracts.enums import IntentEvidenceSource, ProcessingPath, SpeechAct
from runtime.understanding import (
    ConfiguredTextRule,
    DeepUnderstandingRequest,
    DeepUnderstandingRequestBuilder,
    DefaultModelContextSelector,
    DeterministicRuleDefinition,
    DeterministicRuleParser,
    InvalidModelUnderstandingFragmentError,
    MissingUnderstandingModelError,
    ModelUnderstandingOutputValidator,
    RuntimeUnderstandingEngine,
    StructuredUnderstandingModel,
    UnderstandingMergeConflictError,
    UnderstandingModelExecutionError,
    UnderstandingPathRouter,
    UnderstandingPostprocessor,
    UnderstandingRoutingPolicy,
    UnderstandingStateAssembler,
)


def _runtime_input(text: str = "INPUT") -> RuntimeInput:
    return RuntimeInput(
        request_id="request-m3-iu5",
        trace_id="trace-m3-iu5",
        session_id="session-m3-iu5",
        subject_id="subject-m3-iu5",
        identity_scope="scope-m3-iu5",
        source=InputSource.USER,
        trigger_type=InputTriggerType.USER_TEXT,
        timestamp=datetime.now(UTC),
        text=text,
        raw_text=text,
    )


def _runtime_context() -> RuntimeContext:
    return RuntimeContext(
        identity_context=IdentityContext(
            subject_id="subject-m3-iu5",
            identity_scope="scope-m3-iu5",
            identity_status=IdentityStatus.BOUND,
        ),
        session_context=SessionContext(session_id="session-m3-iu5"),
        runtime_state_context=RuntimeStateContext(
            current_state=RuntimeControlState.PROCESSING,
            previous_state=RuntimeControlState.LISTENING,
            interruptible=True,
            entered_at=datetime.now(UTC),
        ),
    )


def _engine(
    *,
    rules: tuple[ConfiguredTextRule, ...] = (),
    model: StructuredUnderstandingModel | None = None,
    routing_policy: UnderstandingRoutingPolicy | None = None,
) -> RuntimeUnderstandingEngine:
    return RuntimeUnderstandingEngine(
        rule_parser=DeterministicRuleParser(rules),
        path_router=UnderstandingPathRouter(routing_policy),
        request_builder=DeepUnderstandingRequestBuilder(
            DefaultModelContextSelector()
        ),
        output_validator=ModelUnderstandingOutputValidator(),
        postprocessor=UnderstandingPostprocessor(),
        assembler=UnderstandingStateAssembler(),
        model=model,
    )


class RecordingModel:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.requests: list[DeepUnderstandingRequest] = []

    async def infer(self, request: DeepUnderstandingRequest) -> dict[str, Any]:
        self.requests.append(request)
        return self.payload


def test_fast_path_builds_final_state_without_calling_model() -> None:
    rule = ConfiguredTextRule(
        DeterministicRuleDefinition(
            rule_id="fast-rule",
            version="1.0.0",
            patterns=("FAST",),
            intent_id="DOMAIN_INTENT",
            speech_act=SpeechAct.COMMAND,
            confirmation=True,
            confidence=1.0,
        )
    )
    model = RecordingModel({"intents": [{"intent_id": "SHOULD_NOT_RUN"}]})
    engine = _engine(rules=(rule,), model=model)

    result = asyncio.run(
        engine.understand(_runtime_input("FAST"), _runtime_context())
    )

    assert isinstance(result, UnderstandingState)
    assert result.metadata.processing_path is ProcessingPath.FAST_PATH
    assert result.metadata.request_id == "request-m3-iu5"
    assert result.metadata.understanding_id == "understanding:request-m3-iu5"
    assert result.intents[0].intent_id == "DOMAIN_INTENT"
    assert result.intents[0].source is IntentEvidenceSource.RULE
    assert result.semantic is not None
    assert result.semantic.speech_act is SpeechAct.COMMAND
    assert result.semantic.confirmation is True
    assert model.requests == []


def test_deep_path_calls_model_once_and_builds_canonical_state() -> None:
    model = RecordingModel(
        {
            "semantic": {
                "speech_act": "QUESTION",
                "normalized_meaning": "normalized",
            },
            "intents": [
                {
                    "intent_id": "DOMAIN_DEEP_INTENT",
                    "confidence": 0.82,
                    "evidence_ids": ["model-e1"],
                }
            ],
            "goal": {"explicit_goal": "DOMAIN_GOAL", "confidence": 0.7},
            "emotion": {"label": "DOMAIN_EMOTION"},
            "needs": [{"need_type": "DOMAIN_NEED", "confidence": 0.6}],
            "references": [{"reference_text": "that", "status": "UNRESOLVED"}],
            "uncertainty": {
                "uncertain_fields": ["references"],
                "needs_clarification": True,
                "safe_to_infer": False,
            },
            "evidence": [
                {
                    "evidence_id": "model-e1",
                    "text_or_value": "INPUT",
                    "supports_field": "intents",
                    "strength": 0.82,
                }
            ],
        }
    )
    engine = _engine(model=model)

    result = asyncio.run(
        engine.understand(_runtime_input("INPUT"), _runtime_context())
    )

    assert result.metadata.processing_path is ProcessingPath.DEEP_PATH
    assert len(model.requests) == 1
    assert result.semantic is not None
    assert result.semantic.speech_act is SpeechAct.QUESTION
    assert result.intents[0].intent_id == "DOMAIN_DEEP_INTENT"
    assert result.intents[0].source is IntentEvidenceSource.INFERRED
    assert result.intents[0].evidence_ids == ["model-e1"]
    assert result.goal is not None
    assert result.goal.explicit_goal == "DOMAIN_GOAL"
    assert result.uncertainty.needs_clarification is True
    assert result.evidence is not None
    assert result.evidence[0]["source_type"] == "MODEL_INFERENCE"


def test_hybrid_deterministic_intent_cannot_be_overwritten_by_model() -> None:
    rule = ConfiguredTextRule(
        DeterministicRuleDefinition(
            rule_id="hybrid-rule",
            version="1.0.0",
            patterns=("HYBRID",),
            intent_id="SAME_INTENT",
            confidence=0.5,
        )
    )
    model = RecordingModel(
        {
            "intents": [
                {
                    "intent_id": "SAME_INTENT",
                    "confidence": 0.99,
                },
                {
                    "intent_id": "MODEL_ADDED_INTENT",
                    "confidence": 0.8,
                },
            ]
        }
    )
    engine = _engine(rules=(rule,), model=model)

    result = asyncio.run(
        engine.understand(_runtime_input("HYBRID"), _runtime_context())
    )

    assert result.metadata.processing_path is ProcessingPath.HYBRID_PATH
    by_id = {intent.intent_id: intent for intent in result.intents}
    assert by_id["SAME_INTENT"].confidence == 0.5
    assert by_id["SAME_INTENT"].source is IntentEvidenceSource.RULE
    assert by_id["MODEL_ADDED_INTENT"].source is IntentEvidenceSource.INFERRED


def test_deterministic_semantic_flags_override_model_values() -> None:
    rule = ConfiguredTextRule(
        DeterministicRuleDefinition(
            rule_id="semantic-rule",
            version="1.0.0",
            patterns=("FLAGS",),
            negation=True,
            correction=True,
            confidence=0.5,
        )
    )
    model = RecordingModel(
        {
            "semantic": {
                "negation": False,
                "correction": False,
                "normalized_meaning": "model meaning",
            }
        }
    )
    engine = _engine(rules=(rule,), model=model)

    result = asyncio.run(
        engine.understand(_runtime_input("FLAGS"), _runtime_context())
    )

    assert result.semantic is not None
    assert result.semantic.negation is True
    assert result.semantic.correction is True
    assert result.semantic.normalized_meaning == "model meaning"


def test_model_cannot_spoof_intent_source() -> None:
    model = RecordingModel(
        {
            "intents": [
                {
                    "intent_id": "DOMAIN_INTENT",
                    "confidence": 0.9,
                    "source": "RULE",
                }
            ]
        }
    )

    with pytest.raises(InvalidModelUnderstandingFragmentError):
        asyncio.run(
            _engine(model=model).understand(
                _runtime_input("INPUT"),
                _runtime_context(),
            )
        )


def test_model_intent_cannot_reference_unknown_evidence() -> None:
    model = RecordingModel(
        {
            "intents": [
                {
                    "intent_id": "DOMAIN_INTENT",
                    "confidence": 0.9,
                    "evidence_ids": ["missing-evidence"],
                }
            ]
        }
    )

    with pytest.raises(InvalidModelUnderstandingFragmentError):
        asyncio.run(
            _engine(model=model).understand(
                _runtime_input("INPUT"),
                _runtime_context(),
            )
        )


def test_deep_route_without_model_fails_closed() -> None:
    with pytest.raises(MissingUnderstandingModelError):
        asyncio.run(
            _engine().understand(_runtime_input("INPUT"), _runtime_context())
        )


def test_model_failure_is_sanitized_and_preserves_cause() -> None:
    class ExplodingModel:
        async def infer(
            self,
            request: DeepUnderstandingRequest,
        ) -> dict[str, Any]:
            del request
            raise RuntimeError("private provider failure")

    with pytest.raises(UnderstandingModelExecutionError) as exc_info:
        asyncio.run(
            _engine(model=ExplodingModel()).understand(
                _runtime_input("INPUT"),
                _runtime_context(),
            )
        )

    assert "private provider failure" not in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_multiple_deterministic_speech_acts_fail_if_fast_cannot_represent_them() -> None:
    rules = (
        ConfiguredTextRule(
            DeterministicRuleDefinition(
                rule_id="act-a",
                version="1.0.0",
                patterns=("MULTI",),
                speech_act=SpeechAct.COMMAND,
            )
        ),
        ConfiguredTextRule(
            DeterministicRuleDefinition(
                rule_id="act-b",
                version="1.0.0",
                patterns=("MULTI",),
                speech_act=SpeechAct.REQUEST,
            )
        ),
    )

    with pytest.raises(UnderstandingMergeConflictError):
        asyncio.run(
            _engine(rules=rules).understand(
                _runtime_input("MULTI"),
                _runtime_context(),
            )
        )


def test_hybrid_model_may_disambiguate_only_among_deterministic_speech_acts() -> None:
    rules = (
        ConfiguredTextRule(
            DeterministicRuleDefinition(
                rule_id="act-a",
                version="1.0.0",
                patterns=("MULTI",),
                speech_act=SpeechAct.COMMAND,
                confidence=0.5,
            )
        ),
        ConfiguredTextRule(
            DeterministicRuleDefinition(
                rule_id="act-b",
                version="1.0.0",
                patterns=("MULTI",),
                speech_act=SpeechAct.REQUEST,
                confidence=0.5,
            )
        ),
    )
    model = RecordingModel({"semantic": {"speech_act": "REQUEST"}})

    result = asyncio.run(
        _engine(rules=rules, model=model).understand(
            _runtime_input("MULTI"),
            _runtime_context(),
        )
    )

    assert result.metadata.processing_path is ProcessingPath.HYBRID_PATH
    assert result.semantic is not None
    assert result.semantic.speech_act is SpeechAct.REQUEST
