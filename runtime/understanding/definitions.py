"""M3-IU1 internal Understanding structural types.

These are Runtime implementation types, not new Canonical Contracts. They exist to
make M3 inputs/outputs traceable and typed without changing the frozen
``UnderstandingState`` schema. Domain-specific intent / need / action values remain
injected data and must not be hardcoded here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from runtime.contracts import CoreControlIntent
from runtime.contracts.enums import IntentEvidenceSource
from runtime.understanding.errors import (
    InvalidUnderstandingCandidateError,
    InvalidUnderstandingDefinitionError,
    InvalidUnderstandingEvidenceError,
    UnderstandingFoundationError,
)


class UnderstandingEvidenceSource(str, Enum):
    """Where an M3 interpretation obtained supporting evidence.

    This enum describes interpretation evidence only. It is not M6 validation
    evidence and does not establish real-world truth.
    """

    CURRENT_INPUT = "CURRENT_INPUT"
    RECENT_TURN = "RECENT_TURN"
    SESSION_CONTEXT = "SESSION_CONTEXT"
    TASK_CONTEXT = "TASK_CONTEXT"
    SYSTEM_STATE = "SYSTEM_STATE"
    MEMORY = "MEMORY"
    RULE_MATCH = "RULE_MATCH"
    MODEL_INFERENCE = "MODEL_INFERENCE"


@dataclass(frozen=True, slots=True)
class IntentDefinition:
    """Registrable intent vocabulary entry.

    ``intent_id`` may be a Core control intent or an arbitrary Domain-registered
    value. This object contains metadata only and performs no classification.
    """

    intent_id: str
    version: str
    namespace: str | None = None
    description: str | None = None
    core_control_intent: CoreControlIntent | None = None

    def __post_init__(self) -> None:
        _require_non_blank(
            self.intent_id, "intent_id", InvalidUnderstandingDefinitionError
        )
        _require_non_blank(
            self.version, "version", InvalidUnderstandingDefinitionError
        )
        _require_optional_non_blank(
            self.namespace, "namespace", InvalidUnderstandingDefinitionError
        )
        _require_optional_non_blank(
            self.description, "description", InvalidUnderstandingDefinitionError
        )

        if self.core_control_intent is not None and (
            self.intent_id != self.core_control_intent.value
        ):
            raise InvalidUnderstandingDefinitionError(
                "intent_id must equal core_control_intent.value when a Core control "
                "intent is declared"
            )


@dataclass(frozen=True, slots=True)
class NeedDefinition:
    """Registrable need vocabulary entry. Concrete Need values are Domain-owned."""

    need_id: str
    version: str
    namespace: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        _require_non_blank(
            self.need_id, "need_id", InvalidUnderstandingDefinitionError
        )
        _require_non_blank(
            self.version, "version", InvalidUnderstandingDefinitionError
        )
        _require_optional_non_blank(
            self.namespace, "namespace", InvalidUnderstandingDefinitionError
        )
        _require_optional_non_blank(
            self.description, "description", InvalidUnderstandingDefinitionError
        )


@dataclass(frozen=True, slots=True)
class CandidateActionDefinition:
    """Registrable semantic-affordance action entry.

    Registration does not authorize execution. M4/M2 remain authoritative for
    planning and policy approval.
    """

    action_id: str
    version: str
    namespace: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        _require_non_blank(
            self.action_id, "action_id", InvalidUnderstandingDefinitionError
        )
        _require_non_blank(
            self.version, "version", InvalidUnderstandingDefinitionError
        )
        _require_optional_non_blank(
            self.namespace, "namespace", InvalidUnderstandingDefinitionError
        )
        _require_optional_non_blank(
            self.description, "description", InvalidUnderstandingDefinitionError
        )


@dataclass(frozen=True, slots=True)
class UnderstandingEvidence:
    """Evidence explaining why M3 interpreted a field in a particular way."""

    evidence_id: str
    source_type: UnderstandingEvidenceSource
    source_ref: str | None
    text_or_value: str
    supports_field: str
    strength: float

    def __post_init__(self) -> None:
        _require_non_blank(
            self.evidence_id, "evidence_id", InvalidUnderstandingEvidenceError
        )
        _require_optional_non_blank(
            self.source_ref, "source_ref", InvalidUnderstandingEvidenceError
        )
        _require_non_blank(
            self.text_or_value, "text_or_value", InvalidUnderstandingEvidenceError
        )
        _require_non_blank(
            self.supports_field, "supports_field", InvalidUnderstandingEvidenceError
        )
        _require_confidence(
            self.strength, "strength", InvalidUnderstandingEvidenceError
        )

    def to_payload(self) -> dict[str, Any]:
        """Project into frozen ``UnderstandingState.evidence`` dictionary shape."""
        return {
            "evidence_id": self.evidence_id,
            "source_type": self.source_type.value,
            "source_ref": self.source_ref,
            "text_or_value": self.text_or_value,
            "supports_field": self.supports_field,
            "strength": self.strength,
        }


@dataclass(frozen=True, slots=True)
class NeedResult:
    """One interpreted need candidate; not a planning or response decision."""

    need_type: str
    confidence: float
    source: IntentEvidenceSource
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_non_blank(
            self.need_type, "need_type", InvalidUnderstandingCandidateError
        )
        _require_confidence(
            self.confidence, "confidence", InvalidUnderstandingCandidateError
        )
        _require_non_blank_tuple(
            self.evidence_ids, "evidence_ids", InvalidUnderstandingCandidateError
        )

    def to_payload(self) -> dict[str, Any]:
        """Project into frozen ``UnderstandingState.needs`` dictionary shape."""
        return {
            "need_type": self.need_type,
            "confidence": self.confidence,
            "explicit_or_inferred": self.source.value,
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True, slots=True)
class RiskSignalSet:
    """M3 risk signals requiring possible M2 review; never a SafetyDecision."""

    signals: tuple[str, ...]
    requires_safety_review: bool
    confidence: float | None = None
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_non_blank_tuple(
            self.signals, "signals", InvalidUnderstandingCandidateError
        )
        _require_non_blank_tuple(
            self.evidence_ids, "evidence_ids", InvalidUnderstandingCandidateError
        )
        if self.confidence is not None:
            _require_confidence(
                self.confidence, "confidence", InvalidUnderstandingCandidateError
            )

    def to_payload(self) -> dict[str, Any]:
        """Project into frozen ``UnderstandingState.risk`` dictionary shape."""
        return {
            "signals": list(self.signals),
            "requires_safety_review": self.requires_safety_review,
            "confidence": self.confidence,
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    """Candidate memory discovered by M3; it is not a persisted MemoryRecord."""

    candidate_id: str
    memory_type: str
    content: str
    source: str
    confidence: float
    structured_value: dict[str, Any] | None = None
    suggested_scope: str | None = None
    sensitivity: str | None = None

    def __post_init__(self) -> None:
        _require_non_blank(
            self.candidate_id, "candidate_id", InvalidUnderstandingCandidateError
        )
        _require_non_blank(
            self.memory_type, "memory_type", InvalidUnderstandingCandidateError
        )
        _require_non_blank(
            self.content, "content", InvalidUnderstandingCandidateError
        )
        _require_non_blank(
            self.source, "source", InvalidUnderstandingCandidateError
        )
        _require_confidence(
            self.confidence, "confidence", InvalidUnderstandingCandidateError
        )
        _require_optional_non_blank(
            self.suggested_scope,
            "suggested_scope",
            InvalidUnderstandingCandidateError,
        )
        _require_optional_non_blank(
            self.sensitivity, "sensitivity", InvalidUnderstandingCandidateError
        )

    def to_payload(self) -> dict[str, Any]:
        """Project into frozen ``UnderstandingState.memory_candidates`` shape."""
        return {
            "candidate_id": self.candidate_id,
            "memory_type": self.memory_type,
            "content": self.content,
            "structured_value": self.structured_value,
            "source": self.source,
            "confidence": self.confidence,
            "suggested_scope": self.suggested_scope,
            "sensitivity": self.sensitivity,
        }


@dataclass(frozen=True, slots=True)
class CandidateAction:
    """Semantic affordance produced by M3; never an executable plan."""

    action: str
    confidence: float
    target: str | None = None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        _require_non_blank(
            self.action, "action", InvalidUnderstandingCandidateError
        )
        _require_confidence(
            self.confidence, "confidence", InvalidUnderstandingCandidateError
        )
        _require_optional_non_blank(
            self.target, "target", InvalidUnderstandingCandidateError
        )
        _require_optional_non_blank(
            self.reason_code, "reason_code", InvalidUnderstandingCandidateError
        )

    def to_payload(self) -> dict[str, Any]:
        """Project into frozen ``UnderstandingState.candidate_actions`` shape."""
        return {
            "action": self.action,
            "target": self.target,
            "confidence": self.confidence,
            "reason_code": self.reason_code,
        }


def _require_non_blank(
    value: str,
    field_name: str,
    error_type: type[UnderstandingFoundationError],
) -> None:
    if not value.strip():
        raise error_type(f"{field_name} must not be blank")


def _require_optional_non_blank(
    value: str | None,
    field_name: str,
    error_type: type[UnderstandingFoundationError],
) -> None:
    if value is not None and not value.strip():
        raise error_type(f"{field_name} must not be blank")


def _require_non_blank_tuple(
    values: tuple[str, ...],
    field_name: str,
    error_type: type[UnderstandingFoundationError],
) -> None:
    if any(not value.strip() for value in values):
        raise error_type(f"{field_name} must not contain blank values")


def _require_confidence(
    value: float,
    field_name: str,
    error_type: type[UnderstandingFoundationError],
) -> None:
    if not 0.0 <= value <= 1.0:
        raise error_type(f"{field_name} must be within [0, 1]")
