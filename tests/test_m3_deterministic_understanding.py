"""M3-IU2 deterministic rules-first Understanding gates."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from runtime.contracts import (
    CoreControlIntent,
    IdentityContext,
    IdentityStatus,
    InputSource,
    InputTriggerType,
    RuntimeContext,
    RuntimeControlState,
    RuntimeInput,
    RuntimeStateContext,
    SessionContext,
)
from runtime.contracts.context import ConversationContext
from runtime.contracts.enums import IntentEvidenceSource, SpeechAct
from runtime.understanding import (
    ConfiguredTextRule,
    DeterministicRuleDefinition,
    DeterministicRuleExecutionError,
    DeterministicRuleFinding,
    DeterministicRuleParser,
    DeterministicUnderstandingConflictError,
    InvalidDeterministicRuleError,
    TextMatchMode,
    UnderstandingEvidenceSource,
)

FORBIDDEN_DOMAIN_VALUES = {
    "PLAY_CONTENT",
    "QUIET_COMPANION",
    "COMPANIONSHIP",
    "DISCOMFORT",
    "REMINDER_RESPONSE",
    "COGNITIVE_INTERACTION",
}


def _runtime_input(text: str | None = "HALT") -> RuntimeInput:
    return RuntimeInput(
        request_id="request-m3-iu2",
        trace_id="trace-m3-iu2",
        session_id="session-m3-iu2",
        subject_id="subject-m3-iu2",
        identity_scope="scope-m3-iu2",
        source=InputSource.USER,
        trigger_type=InputTriggerType.USER_TEXT,
        timestamp=datetime.now(UTC),
        text=text,
        raw_text=text,
    )


def _runtime_context(*, pending_question: str | None = None) -> RuntimeContext:
    return RuntimeContext(
        identity_context=IdentityContext(
            subject_id="subject-m3-iu2",
            identity_scope="scope-m3-iu2",
            identity_status=IdentityStatus.BOUND,
        ),
        session_context=SessionContext(session_id="session-m3-iu2"),
        runtime_state_context=RuntimeStateContext(
            current_state=RuntimeControlState.PROCESSING,
            previous_state=RuntimeControlState.LISTENING,
            interruptible=True,
            entered_at=datetime.now(UTC),
            pending_question_id=(
                "pending-question-id" if pending_question is not None else None
            ),
        ),
        conversation_context=(
            ConversationContext(pending_question=pending_question)
            if pending_question is not None
            else None
        ),
    )


def test_exact_core_control_rule_is_injected_not_hardcoded() -> None:
    rule = ConfiguredTextRule(
        DeterministicRuleDefinition(
            rule_id="test-stop-rule",
            version="1.0.0",
            patterns=("HALT",),
            intent_id=CoreControlIntent.STOP.value,
            speech_act=SpeechAct.COMMAND,
            confidence=1.0,
        )
    )
    parser = DeterministicRuleParser((rule,))

    result = parser.parse(_runtime_input("halt"), _runtime_context())

    assert result.matched is True
    assert result.matched_rule_ids == ("test-stop-rule",)
    assert len(result.intents) == 1
    assert result.intents[0].intent_id == CoreControlIntent.STOP.value
    assert result.intents[0].source is IntentEvidenceSource.RULE
    assert result.speech_acts == (SpeechAct.COMMAND,)
    assert result.confidence == 1.0
    assert result.evidence[0].source_type is UnderstandingEvidenceSource.RULE_MATCH


def test_domain_intent_is_supported_only_through_injected_rule_data() -> None:
    rule = ConfiguredTextRule(
        DeterministicRuleDefinition(
            rule_id="domain-rule",
            version="1.0.0",
            patterns=(r"domain-[0-9]+",),
            match_mode=TextMatchMode.FULLMATCH,
            intent_id="DOMAIN_CUSTOM_INTENT",
            confidence=0.93,
        )
    )

    result = DeterministicRuleParser((rule,)).parse(
        _runtime_input("DOMAIN-42"), _runtime_context()
    )

    assert [intent.intent_id for intent in result.intents] == ["DOMAIN_CUSTOM_INTENT"]
    assert result.evidence[0].text_or_value == "DOMAIN-42"


def test_search_rule_preserves_matched_text_and_semantic_flags() -> None:
    rule = ConfiguredTextRule(
        DeterministicRuleDefinition(
            rule_id="correction-rule",
            version="1.0.0",
            patterns=(r"replace\s+that",),
            match_mode=TextMatchMode.SEARCH,
            correction=True,
            negation=True,
            speech_act=SpeechAct.CORRECTION,
            confidence=0.88,
        )
    )

    result = DeterministicRuleParser((rule,)).parse(
        _runtime_input("Please replace that now"), _runtime_context()
    )

    assert result.correction is True
    assert result.negation is True
    assert result.speech_acts == (SpeechAct.CORRECTION,)
    assert result.evidence[0].text_or_value == "replace that"


def test_pending_question_rule_requires_explicit_pending_context() -> None:
    rule = ConfiguredTextRule(
        DeterministicRuleDefinition(
            rule_id="pending-confirmation",
            version="1.0.0",
            patterns=("AFFIRM",),
            speech_act=SpeechAct.CONFIRMATION,
            confirmation=True,
            pending_question_resolution="CONFIRMED",
            requires_pending_question=True,
        )
    )
    parser = DeterministicRuleParser((rule,))

    no_pending = parser.parse(_runtime_input("AFFIRM"), _runtime_context())
    with_pending = parser.parse(
        _runtime_input("AFFIRM"),
        _runtime_context(pending_question="synthetic pending question"),
    )

    assert no_pending.matched is False
    assert with_pending.matched is True
    assert with_pending.confirmation is True
    assert with_pending.pending_question_resolution == "CONFIRMED"


def test_multiple_rules_merge_intent_evidence_without_planning() -> None:
    rules = (
        ConfiguredTextRule(
            DeterministicRuleDefinition(
                rule_id="rule-a",
                version="1.0.0",
                patterns=("MERGE",),
                intent_id="DOMAIN_CUSTOM_INTENT",
                confidence=0.7,
            )
        ),
        ConfiguredTextRule(
            DeterministicRuleDefinition(
                rule_id="rule-b",
                version="1.0.0",
                patterns=("MERGE",),
                intent_id="DOMAIN_CUSTOM_INTENT",
                confidence=0.9,
                risk_signal_ids=("DOMAIN_RISK_SIGNAL",),
            )
        ),
    )

    result = DeterministicRuleParser(rules).parse(
        _runtime_input("MERGE"), _runtime_context()
    )

    assert len(result.intents) == 1
    assert result.intents[0].confidence == 0.9
    assert result.intents[0].evidence_ids == ["rule:rule-a:1", "rule:rule-b:2"]
    assert result.risk_signal_ids == ("DOMAIN_RISK_SIGNAL",)
    assert not hasattr(result, "action_plan")
    assert not hasattr(result, "tool_call")
    assert not hasattr(result, "approval_status")


def test_conflicting_deterministic_boolean_facts_fail_closed() -> None:
    rules = (
        ConfiguredTextRule(
            DeterministicRuleDefinition(
                rule_id="confirm-yes",
                version="1.0.0",
                patterns=("CONFLICT",),
                confirmation=True,
            )
        ),
        ConfiguredTextRule(
            DeterministicRuleDefinition(
                rule_id="confirm-no",
                version="1.0.0",
                patterns=("CONFLICT",),
                confirmation=False,
            )
        ),
    )

    with pytest.raises(DeterministicUnderstandingConflictError):
        DeterministicRuleParser(rules).parse(
            _runtime_input("CONFLICT"), _runtime_context()
        )


def test_conflicting_pending_question_resolutions_fail_closed() -> None:
    rules = (
        ConfiguredTextRule(
            DeterministicRuleDefinition(
                rule_id="pending-a",
                version="1.0.0",
                patterns=("ANSWER",),
                pending_question_resolution="A",
            )
        ),
        ConfiguredTextRule(
            DeterministicRuleDefinition(
                rule_id="pending-b",
                version="1.0.0",
                patterns=("ANSWER",),
                pending_question_resolution="B",
            )
        ),
    )

    with pytest.raises(DeterministicUnderstandingConflictError):
        DeterministicRuleParser(rules).parse(
            _runtime_input("ANSWER"), _runtime_context()
        )


def test_rule_validation_rejects_bad_regex_confidence_and_duplicate_ids() -> None:
    with pytest.raises(InvalidDeterministicRuleError):
        DeterministicRuleDefinition(
            rule_id="bad-regex",
            version="1.0.0",
            patterns=("[",),
            match_mode=TextMatchMode.SEARCH,
        )

    with pytest.raises(InvalidDeterministicRuleError):
        DeterministicRuleDefinition(
            rule_id="bad-confidence",
            version="1.0.0",
            patterns=("X",),
            confidence=1.01,
        )

    duplicate = ConfiguredTextRule(
        DeterministicRuleDefinition(
            rule_id="duplicate",
            version="1.0.0",
            patterns=("X",),
        )
    )
    with pytest.raises(InvalidDeterministicRuleError):
        DeterministicRuleParser((duplicate, duplicate))


def test_rule_exception_is_wrapped_without_converting_to_a_match() -> None:
    class ExplodingRule:
        @property
        def rule_id(self) -> str:
            return "exploding-rule"

        def evaluate(
            self,
            runtime_input: RuntimeInput,
            runtime_context: RuntimeContext,
        ) -> DeterministicRuleFinding | None:
            del runtime_input, runtime_context
            raise RuntimeError("private domain failure detail")

    with pytest.raises(DeterministicRuleExecutionError) as exc_info:
        DeterministicRuleParser((ExplodingRule(),)).parse(
            _runtime_input("X"), _runtime_context()
        )

    assert "private domain failure detail" not in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_empty_or_none_text_does_not_fabricate_understanding() -> None:
    rule = ConfiguredTextRule(
        DeterministicRuleDefinition(
            rule_id="never-without-text",
            version="1.0.0",
            patterns=("X",),
            intent_id="DOMAIN_CUSTOM_INTENT",
        )
    )

    result = DeterministicRuleParser((rule,)).parse(
        _runtime_input(None), _runtime_context()
    )

    assert result.matched is False
    assert result.intents == ()
    assert result.evidence == ()
    assert result.confidence is None


def test_m3_iu2_runtime_package_keeps_domain_rules_out_of_core() -> None:
    source_text = "\n".join(
        source_file.read_text(encoding="utf-8")
        for source_file in Path("runtime/understanding").glob("*.py")
    )
    for forbidden_value in FORBIDDEN_DOMAIN_VALUES:
        assert forbidden_value not in source_text

    for forbidden_phrase in (
        "暂停",
        "继续播放",
        "提醒我",
        "头疼",
        "lonely",
    ):
        assert forbidden_phrase not in source_text


def test_m3_iu2_does_not_claim_deep_understanding_or_execution() -> None:
    import runtime.understanding as understanding_module

    exported_names = set(dir(understanding_module))
    for forbidden_name in (
        "DefaultUnderstandingEngine",
        "UnderstandingOrchestrator",
        "LLMUnderstandingEngine",
        "PathRouter",
        "ToolExecutor",
        "MemoryWriter",
    ):
        assert forbidden_name not in exported_names

    package_text = "\n".join(
        source_file.read_text(encoding="utf-8")
        for source_file in Path("runtime/understanding").glob("*.py")
    )
    assert "NotImplementedError" not in package_text
