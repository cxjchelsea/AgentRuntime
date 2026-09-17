"""M3-IU2 deterministic Understanding parser.

This module implements only rules-first, deterministic interpretation. It does not
call an LLM, decide policy, plan actions, execute tools, persist memory, or make a
SafetyDecision. Concrete lexical/domain rules are injected by configuration.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, TypeVar

from runtime.contracts import IntentResult, RuntimeContext, RuntimeInput
from runtime.contracts.enums import IntentEvidenceSource, SpeechAct
from runtime.understanding.definitions import (
    UnderstandingEvidence,
    UnderstandingEvidenceSource,
)
from runtime.understanding.errors import (
    DeterministicRuleExecutionError,
    DeterministicUnderstandingConflictError,
    InvalidDeterministicRuleError,
)

UniqueType = TypeVar("UniqueType")


class TextMatchMode(str, Enum):
    """Supported deterministic text matching semantics."""

    EXACT = "EXACT"
    FULLMATCH = "FULLMATCH"
    SEARCH = "SEARCH"


@dataclass(frozen=True, slots=True)
class DeterministicRuleDefinition:
    """Configuration for one deterministic interpretation rule.

    Patterns are injected data. The Runtime Core does not ship business-language
    phrases, domain taxonomy values, medical rules, or reminder/content vocabulary.
    """

    rule_id: str
    version: str
    patterns: tuple[str, ...]
    match_mode: TextMatchMode = TextMatchMode.EXACT
    confidence: float = 1.0
    intent_id: str | None = None
    speech_act: SpeechAct | None = None
    negation: bool | None = None
    confirmation: bool | None = None
    correction: bool | None = None
    pending_question_resolution: str | None = None
    risk_signal_ids: tuple[str, ...] = ()
    requires_pending_question: bool = False
    case_sensitive: bool = False

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise InvalidDeterministicRuleError("rule_id must not be blank")
        if not self.version.strip():
            raise InvalidDeterministicRuleError("version must not be blank")
        if not self.patterns:
            raise InvalidDeterministicRuleError("patterns must not be empty")
        if any(not pattern.strip() for pattern in self.patterns):
            raise InvalidDeterministicRuleError(
                "patterns must not contain blank values"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise InvalidDeterministicRuleError("confidence must be within [0, 1]")
        if self.intent_id is not None and not self.intent_id.strip():
            raise InvalidDeterministicRuleError("intent_id must not be blank")
        if (
            self.pending_question_resolution is not None
            and not self.pending_question_resolution.strip()
        ):
            raise InvalidDeterministicRuleError(
                "pending_question_resolution must not be blank"
            )
        if any(not signal_id.strip() for signal_id in self.risk_signal_ids):
            raise InvalidDeterministicRuleError(
                "risk_signal_ids must not contain blank values"
            )

        if self.match_mode in {TextMatchMode.FULLMATCH, TextMatchMode.SEARCH}:
            flags = 0 if self.case_sensitive else re.IGNORECASE
            for pattern in self.patterns:
                try:
                    re.compile(pattern, flags)
                except re.error as exc:
                    raise InvalidDeterministicRuleError(
                        f"invalid regular expression in rule {self.rule_id}"
                    ) from exc


@dataclass(frozen=True, slots=True)
class DeterministicRuleFinding:
    """One matched rule's partial interpretation output."""

    rule_id: str
    matched_text: str
    confidence: float
    intent_id: str | None = None
    speech_act: SpeechAct | None = None
    negation: bool | None = None
    confirmation: bool | None = None
    correction: bool | None = None
    pending_question_resolution: str | None = None
    risk_signal_ids: tuple[str, ...] = ()


class DeterministicUnderstandingRule(Protocol):
    """Pluggable deterministic rule boundary."""

    @property
    def rule_id(self) -> str:
        """Stable rule identifier."""
        ...

    def evaluate(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext,
    ) -> DeterministicRuleFinding | None:
        """Return one deterministic finding or no match."""
        ...


class ConfiguredTextRule:
    """Generic text rule backed only by injected configuration."""

    def __init__(self, definition: DeterministicRuleDefinition) -> None:
        self._definition = definition
        self._compiled_patterns = self._compile_patterns(definition)

    @property
    def rule_id(self) -> str:
        return self._definition.rule_id

    def evaluate(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext,
    ) -> DeterministicRuleFinding | None:
        text = runtime_input.text
        if text is None:
            return None
        if self._definition.requires_pending_question and not _has_pending_question(
            runtime_context
        ):
            return None

        matched_text = self._match(text)
        if matched_text is None:
            return None

        return DeterministicRuleFinding(
            rule_id=self._definition.rule_id,
            matched_text=matched_text,
            confidence=self._definition.confidence,
            intent_id=self._definition.intent_id,
            speech_act=self._definition.speech_act,
            negation=self._definition.negation,
            confirmation=self._definition.confirmation,
            correction=self._definition.correction,
            pending_question_resolution=self._definition.pending_question_resolution,
            risk_signal_ids=self._definition.risk_signal_ids,
        )

    def _match(self, text: str) -> str | None:
        if self._definition.match_mode is TextMatchMode.EXACT:
            candidate = text if self._definition.case_sensitive else text.casefold()
            for pattern in self._definition.patterns:
                expected = (
                    pattern if self._definition.case_sensitive else pattern.casefold()
                )
                if candidate == expected:
                    return text
            return None

        for compiled_pattern in self._compiled_patterns:
            if self._definition.match_mode is TextMatchMode.FULLMATCH:
                match = compiled_pattern.fullmatch(text)
            else:
                match = compiled_pattern.search(text)
            if match is not None:
                return match.group(0)
        return None

    @staticmethod
    def _compile_patterns(
        definition: DeterministicRuleDefinition,
    ) -> tuple[re.Pattern[str], ...]:
        if definition.match_mode is TextMatchMode.EXACT:
            return ()
        flags = 0 if definition.case_sensitive else re.IGNORECASE
        return tuple(re.compile(pattern, flags) for pattern in definition.patterns)


@dataclass(frozen=True, slots=True)
class RuleParseResult:
    """Deterministic partial understanding produced before deep interpretation."""

    matched_rule_ids: tuple[str, ...]
    intents: tuple[IntentResult, ...]
    speech_acts: tuple[SpeechAct, ...]
    negation: bool | None
    confirmation: bool | None
    correction: bool | None
    pending_question_resolution: str | None
    risk_signal_ids: tuple[str, ...]
    evidence: tuple[UnderstandingEvidence, ...]
    confidence: float | None

    @property
    def matched(self) -> bool:
        return bool(self.matched_rule_ids)


class DeterministicRuleParser:
    """Evaluate injected deterministic rules and aggregate their partial results."""

    def __init__(self, rules: tuple[DeterministicUnderstandingRule, ...]) -> None:
        rule_ids = tuple(rule.rule_id for rule in rules)
        if any(not rule_id.strip() for rule_id in rule_ids):
            raise InvalidDeterministicRuleError("rule_id must not be blank")
        if len(set(rule_ids)) != len(rule_ids):
            raise InvalidDeterministicRuleError("duplicate deterministic rule_id")
        self._rules = rules

    def parse(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext,
    ) -> RuleParseResult:
        findings: list[DeterministicRuleFinding] = []
        for rule in self._rules:
            try:
                finding = rule.evaluate(runtime_input, runtime_context)
            except DeterministicUnderstandingConflictError:
                raise
            except Exception as exc:
                raise DeterministicRuleExecutionError(
                    f"deterministic rule execution failed: {rule.rule_id}"
                ) from exc
            if finding is not None:
                if finding.rule_id != rule.rule_id:
                    raise DeterministicRuleExecutionError(
                        "rule finding rule_id does not match evaluator rule_id"
                    )
                findings.append(finding)

        return self._aggregate(runtime_input, findings)

    @staticmethod
    def _aggregate(
        runtime_input: RuntimeInput,
        findings: list[DeterministicRuleFinding],
    ) -> RuleParseResult:
        if not findings:
            return RuleParseResult(
                matched_rule_ids=(),
                intents=(),
                speech_acts=(),
                negation=None,
                confirmation=None,
                correction=None,
                pending_question_resolution=None,
                risk_signal_ids=(),
                evidence=(),
                confidence=None,
            )

        negation = _merge_optional_bool(findings, "negation")
        confirmation = _merge_optional_bool(findings, "confirmation")
        correction = _merge_optional_bool(findings, "correction")
        pending_resolution = _merge_optional_text(
            findings, "pending_question_resolution"
        )

        evidence: list[UnderstandingEvidence] = []
        evidence_ids_by_rule: dict[str, str] = {}
        for index, finding in enumerate(findings, start=1):
            evidence_id = f"rule:{finding.rule_id}:{index}"
            evidence_ids_by_rule[finding.rule_id] = evidence_id
            evidence.append(
                UnderstandingEvidence(
                    evidence_id=evidence_id,
                    source_type=UnderstandingEvidenceSource.RULE_MATCH,
                    source_ref=finding.rule_id,
                    text_or_value=finding.matched_text,
                    supports_field="deterministic_rule_parse",
                    strength=finding.confidence,
                )
            )

        intents_by_id: dict[str, IntentResult] = {}
        intent_evidence_ids: dict[str, list[str]] = {}
        for finding in findings:
            if finding.intent_id is None:
                continue
            evidence_id = evidence_ids_by_rule[finding.rule_id]
            intent_evidence_ids.setdefault(finding.intent_id, []).append(evidence_id)
            existing = intents_by_id.get(finding.intent_id)
            if existing is None or finding.confidence > existing.confidence:
                intents_by_id[finding.intent_id] = IntentResult(
                    intent_id=finding.intent_id,
                    confidence=finding.confidence,
                    source=IntentEvidenceSource.RULE,
                    evidence_ids=[evidence_id],
                )

        intents: list[IntentResult] = []
        for intent_id, intent in intents_by_id.items():
            intents.append(
                intent.model_copy(
                    update={"evidence_ids": intent_evidence_ids[intent_id]}
                )
            )

        speech_acts = _stable_unique(
            finding.speech_act for finding in findings if finding.speech_act is not None
        )
        risk_signal_ids = _stable_unique(
            signal_id for finding in findings for signal_id in finding.risk_signal_ids
        )
        confidence = max(finding.confidence for finding in findings)

        if runtime_input.request_id.strip() == "":
            raise DeterministicRuleExecutionError("request_id must not be blank")

        return RuleParseResult(
            matched_rule_ids=tuple(finding.rule_id for finding in findings),
            intents=tuple(intents),
            speech_acts=speech_acts,
            negation=negation,
            confirmation=confirmation,
            correction=correction,
            pending_question_resolution=pending_resolution,
            risk_signal_ids=risk_signal_ids,
            evidence=tuple(evidence),
            confidence=confidence,
        )


def _has_pending_question(runtime_context: RuntimeContext) -> bool:
    conversation_context = runtime_context.conversation_context
    if (
        conversation_context is not None
        and conversation_context.pending_question is not None
    ):
        return True
    return runtime_context.runtime_state_context.pending_question_id is not None


def _merge_optional_bool(
    findings: list[DeterministicRuleFinding],
    field_name: str,
) -> bool | None:
    values = {
        value
        for finding in findings
        if (value := getattr(finding, field_name)) is not None
    }
    if len(values) > 1:
        raise DeterministicUnderstandingConflictError(
            f"conflicting deterministic values for {field_name}"
        )
    return next(iter(values)) if values else None


def _merge_optional_text(
    findings: list[DeterministicRuleFinding],
    field_name: str,
) -> str | None:
    values = {
        value
        for finding in findings
        if (value := getattr(finding, field_name)) is not None
    }
    if len(values) > 1:
        raise DeterministicUnderstandingConflictError(
            f"conflicting deterministic values for {field_name}"
        )
    return next(iter(values)) if values else None


def _stable_unique(values: Iterable[UniqueType]) -> tuple[UniqueType, ...]:
    result: list[UniqueType] = []
    seen: set[UniqueType] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)
