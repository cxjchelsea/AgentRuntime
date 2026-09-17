"""M3-IU3 Fast/Deep routing and model-boundary gates."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from runtime.contracts import (
    IdentityContext,
    IdentityStatus,
    InputSource,
    InputTriggerType,
    IntentEvidenceSource,
    IntentResult,
    RuntimeContext,
    RuntimeControlState,
    RuntimeInput,
    RuntimeStateContext,
    SessionContext,
)
from runtime.contracts.context import ConversationContext, MemoryContext
from runtime.contracts.enums import ProcessingPath
from runtime.understanding import (
    DeepUnderstandingRequestBuilder,
    DefaultModelContextSelector,
    InvalidUnderstandingRoutingPolicyError,
    ModelContextSelectionPolicy,
    ModelInputBoundaryError,
    ModelOutputBoundaryError,
    ModelUnderstandingOutputValidator,
    RuleParseResult,
    UnderstandingPathRouter,
    UnderstandingRoutingPolicy,
)


def _rule_result(
    *,
    matched: bool = True,
    confidence: float | None = 1.0,
    intents: tuple[IntentResult, ...] = (),
    risk_signal_ids: tuple[str, ...] = (),
    pending_question_resolution: str | None = None,
) -> RuleParseResult:
    return RuleParseResult(
        matched_rule_ids=("rule-1",) if matched else (),
        intents=intents,
        speech_acts=(),
        negation=None,
        confirmation=None,
        correction=None,
        pending_question_resolution=pending_question_resolution,
        risk_signal_ids=risk_signal_ids,
        evidence=(),
        confidence=confidence if matched else None,
    )


def _runtime_input(
    *,
    text: str | None = "synthetic input",
    session_id: str = "session-m3-iu3",
    subject_id: str = "subject-m3-iu3",
    identity_scope: str = "scope-m3-iu3",
) -> RuntimeInput:
    return RuntimeInput(
        request_id="request-m3-iu3",
        trace_id="trace-m3-iu3",
        session_id=session_id,
        subject_id=subject_id,
        identity_scope=identity_scope,
        source=InputSource.USER,
        trigger_type=InputTriggerType.USER_TEXT,
        timestamp=datetime.now(UTC),
        text=text,
        raw_text=text,
    )


def _runtime_context() -> RuntimeContext:
    return RuntimeContext(
        identity_context=IdentityContext(
            subject_id="subject-m3-iu3",
            identity_scope="scope-m3-iu3",
            identity_status=IdentityStatus.BOUND,
        ),
        session_context=SessionContext(
            session_id="session-m3-iu3",
            current_topic="synthetic-topic",
        ),
        runtime_state_context=RuntimeStateContext(
            current_state=RuntimeControlState.PROCESSING,
            previous_state=RuntimeControlState.LISTENING,
            interruptible=True,
            entered_at=datetime.now(UTC),
            active_task_id="task-1",
            active_workflow_id="workflow-1",
        ),
        conversation_context=ConversationContext(
            recent_turns=[{"turn": 1}, {"turn": 2}, {"turn": 3}],
            current_topic="conversation-topic",
            pending_question="synthetic pending question",
        ),
        memory_context=MemoryContext(
            retrieved_memories=[{"memory": 1}, {"memory": 2}],
            service_status="AVAILABLE",
        ),
    )


def test_router_uses_deep_path_when_no_deterministic_rule_matches() -> None:
    decision = UnderstandingPathRouter().route(_rule_result(matched=False))

    assert decision.processing_path is ProcessingPath.DEEP_PATH
    assert decision.requires_model is True
    assert decision.reason_codes == ("NO_DETERMINISTIC_MATCH",)


def test_router_uses_fast_path_when_deterministic_result_is_sufficient() -> None:
    intent = IntentResult(
        intent_id="DOMAIN_INTENT",
        confidence=0.98,
        source=IntentEvidenceSource.RULE,
    )

    decision = UnderstandingPathRouter().route(
        _rule_result(confidence=0.98, intents=(intent,))
    )

    assert decision.processing_path is ProcessingPath.FAST_PATH
    assert decision.requires_model is False
    assert decision.reason_codes == ("DETERMINISTIC_RESULT_SUFFICIENT",)


def test_router_uses_hybrid_for_low_confidence_multiple_intents_or_risk() -> None:
    intent_a = IntentResult(
        intent_id="DOMAIN_A",
        confidence=0.8,
        source=IntentEvidenceSource.RULE,
    )
    intent_b = IntentResult(
        intent_id="DOMAIN_B",
        confidence=0.8,
        source=IntentEvidenceSource.RULE,
    )
    decision = UnderstandingPathRouter().route(
        _rule_result(
            confidence=0.8,
            intents=(intent_a, intent_b),
            risk_signal_ids=("DOMAIN_RISK_SIGNAL",),
        )
    )

    assert decision.processing_path is ProcessingPath.HYBRID_PATH
    assert decision.requires_model is True
    assert "DETERMINISTIC_CONFIDENCE_BELOW_FAST_THRESHOLD" in decision.reason_codes
    assert "MULTIPLE_DETERMINISTIC_INTENTS" in decision.reason_codes
    assert "RISK_SIGNAL_REQUIRES_DEEP_REVIEW" in decision.reason_codes


def test_routing_policy_is_generic_and_validated() -> None:
    with pytest.raises(InvalidUnderstandingRoutingPolicyError):
        UnderstandingRoutingPolicy(fast_min_confidence=1.1)
    with pytest.raises(InvalidUnderstandingRoutingPolicyError):
        UnderstandingRoutingPolicy(max_fast_intents=-1)

    policy = UnderstandingRoutingPolicy(
        fast_min_confidence=0.5,
        max_fast_intents=3,
        deep_on_risk_signal=False,
    )
    decision = UnderstandingPathRouter(policy).route(
        _rule_result(confidence=0.8, risk_signal_ids=("DOMAIN_RISK_SIGNAL",))
    )
    assert decision.processing_path is ProcessingPath.FAST_PATH


def test_model_context_selector_exposes_only_allowlisted_generic_context() -> None:
    selector = DefaultModelContextSelector(
        ModelContextSelectionPolicy(max_recent_turns=2, max_memories=1)
    )

    selected = selector.select(_runtime_context())

    assert selected.session_id == "session-m3-iu3"
    assert selected.current_runtime_state == "PROCESSING"
    assert selected.active_task_id == "task-1"
    assert selected.active_workflow_id == "workflow-1"
    assert selected.pending_question == "synthetic pending question"
    assert selected.current_topic == "conversation-topic"
    assert selected.recent_turns == ({"turn": 2}, {"turn": 3})
    assert selected.relevant_memories == ({"memory": 1},)
    assert not hasattr(selected, "domain_extensions")
    assert not hasattr(selected, "tool_context")
    assert not hasattr(selected, "safety_context")


def test_deep_request_builder_rejects_fast_path_and_turn_identity_mismatch() -> None:
    selector = DefaultModelContextSelector()
    builder = DeepUnderstandingRequestBuilder(selector)
    fast_route = UnderstandingPathRouter().route(_rule_result())
    deep_route = UnderstandingPathRouter().route(_rule_result(matched=False))

    with pytest.raises(ModelInputBoundaryError):
        builder.build(_runtime_input(), _runtime_context(), fast_route)
    with pytest.raises(ModelInputBoundaryError):
        builder.build(
            _runtime_input(session_id="other-session"),
            _runtime_context(),
            deep_route,
        )
    with pytest.raises(ModelInputBoundaryError):
        builder.build(_runtime_input(text=" "), _runtime_context(), deep_route)


def test_deep_request_contains_selected_context_and_deterministic_result_only() -> None:
    deep_route = UnderstandingPathRouter().route(_rule_result(matched=False))
    request = DeepUnderstandingRequestBuilder(DefaultModelContextSelector()).build(
        _runtime_input(),
        _runtime_context(),
        deep_route,
    )

    assert request.request_id == "request-m3-iu3"
    assert request.text == "synthetic input"
    assert request.deterministic_result is deep_route.deterministic_result
    assert not hasattr(request, "policy_decision")
    assert not hasattr(request, "approved_action_plan")
    assert not hasattr(request, "runtime_response")


def test_model_output_validator_accepts_only_understanding_fields() -> None:
    validator = ModelUnderstandingOutputValidator()
    result = validator.validate(
        {
            "semantic": {"normalized_meaning": "synthetic"},
            "intents": [{"intent_id": "DOMAIN_INTENT", "confidence": 0.7}],
            "goal": {"explicit_goal": "synthetic-goal"},
            "emotion": {"primary_emotion": "DOMAIN_EMOTION"},
            "needs": [{"need_type": "DOMAIN_NEED"}],
            "interaction": {"engagement": "DOMAIN_VALUE"},
            "references": [],
            "risk_signals": [],
            "uncertainty": {"needs_clarification": False},
            "evidence": [{"source": "MODEL_INFERENCE"}],
        }
    )

    assert result.semantic == {"normalized_meaning": "synthetic"}
    assert result.intents[0]["intent_id"] == "DOMAIN_INTENT"
    assert result.goal == {"explicit_goal": "synthetic-goal"}
    assert not hasattr(result, "candidate_actions")
    assert not hasattr(result, "final_response")


def test_model_output_validator_fails_closed_on_decision_or_execution_fields() -> None:
    validator = ModelUnderstandingOutputValidator()

    with pytest.raises(ModelOutputBoundaryError):
        validator.validate({"response": "not allowed"})
    with pytest.raises(ModelOutputBoundaryError):
        validator.validate(
            {
                "semantic": {
                    "normalized_meaning": "synthetic",
                    "tool_call": {"tool": "forbidden"},
                }
            }
        )
    with pytest.raises(ModelOutputBoundaryError):
        validator.validate({"semantic": "not-an-object"})


def test_iu3_does_not_ship_domain_taxonomy_or_real_model_provider() -> None:
    source_text = "\n".join(
        source_file.read_text(encoding="utf-8")
        for source_file in Path("runtime/understanding").glob("*.py")
    )
    for forbidden_domain_value in (
        "PLAY_CONTENT",
        "QUIET_COMPANION",
        "COMPANIONSHIP",
        "DISCOMFORT",
        "REMINDER_RESPONSE",
        "COGNITIVE_INTERACTION",
    ):
        assert forbidden_domain_value not in source_text

    import runtime.understanding as understanding_module

    exported_names = set(dir(understanding_module))
    assert "DefaultUnderstandingEngine" not in exported_names
    assert "UnderstandingOrchestrator" not in exported_names
    assert "OpenAIUnderstandingModel" not in exported_names
    assert "AnthropicUnderstandingModel" not in exported_names
    assert "NotImplementedError" not in source_text
