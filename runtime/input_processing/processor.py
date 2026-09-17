"""Default real implementation for M1 node ① Input Processor.

The processor normalizes already-adapted ``RuntimeInput`` instances.  It does
not infer intent, emotion, need, strategy, Domain values, or Tool actions.

Raw source adapters (voice SDK payloads, scheduler payloads, HTTP callbacks,
etc.) remain outside this class because the frozen M0 interface accepts a
Canonical ``RuntimeInput`` and returns a normalized ``RuntimeInput``.
"""

from __future__ import annotations

import math
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

from runtime.contracts import InputTriggerType, RuntimeInput
from runtime.interfaces.input import InputProcessor
from runtime.input_processing.errors import InputNormalizationError

_WHITESPACE_RE = re.compile(r"\s+")
_ZERO_WIDTH_SPACE = "\u200b"
_BOM = "\ufeff"

_REQUIRED_IDENTIFIERS = (
    "request_id",
    "trace_id",
    "session_id",
    "subject_id",
    "identity_scope",
)

_USER_TRIGGERS = {
    InputTriggerType.USER_VOICE,
    InputTriggerType.USER_TEXT,
    InputTriggerType.USER_OTHER,
}


class DefaultInputProcessor(InputProcessor):
    """Normalize one Canonical ``RuntimeInput`` without semantic inference.

    Responsibilities implemented for M1-IU1:
    - validate required runtime identifiers are non-blank;
    - normalize visible text while preserving pre-normalization ``raw_text``;
    - normalize timestamps to timezone-aware UTC;
    - validate optional confidence is finite and within [0, 1];
    - reject empty user-originated inputs;
    - preserve payload / segments / metadata without adding Domain semantics.

    Deliberately not implemented here:
    - source-specific RawInput adapters;
    - ASR punctuation restoration requiring a model;
    - duplicate suppression requiring lifecycle / store semantics;
    - understanding, routing, policy, Tool execution, or Domain behavior.
    """

    async def process(self, runtime_input: RuntimeInput) -> RuntimeInput:
        """Return a validated, normalized copy of ``runtime_input``.

        The input model is never mutated in place.  Failures are explicit and
        are later wrapped by the Runtime Orchestrator's stage error boundary.
        """
        data = runtime_input.model_dump(mode="python")

        for field_name in _REQUIRED_IDENTIFIERS:
            data[field_name] = self._normalize_required_identifier(
                field_name, data[field_name]
            )

        for field_name in ("actor_id", "device_id", "tenant_id"):
            data[field_name] = self._normalize_optional_identifier(
                field_name, data.get(field_name)
            )

        original_text = data.get("text")
        original_raw_text = data.get("raw_text")

        if original_raw_text is None and original_text is not None:
            # ``raw_text`` means pre-normalization source text.  When the caller
            # only supplied ``text``, preserve that value before normalization.
            data["raw_text"] = original_text

        text_source = original_text if original_text is not None else original_raw_text
        data["text"] = self._normalize_text(text_source)

        data["input_type"] = self._normalize_optional_string(data.get("input_type"))
        data["timestamp"] = self._normalize_timestamp(data["timestamp"])
        data["confidence"] = self._normalize_confidence(data.get("confidence"))

        self._validate_meaningful_input(
            trigger_type=data["trigger_type"],
            text=data.get("text"),
            raw_text=data.get("raw_text"),
            input_payload=data.get("input_payload"),
            segments=data.get("segments"),
        )

        # Re-validate through the Canonical Pydantic contract rather than using
        # ``model_copy(update=...)``, whose updates are not validated by default.
        return RuntimeInput.model_validate(data)

    @staticmethod
    def _normalize_required_identifier(field_name: str, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise InputNormalizationError(field_name, "must not be blank")
        return normalized

    @staticmethod
    def _normalize_optional_identifier(field_name: str, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if any(character.isspace() for character in normalized):
            raise InputNormalizationError(
                field_name, "identifier must not contain whitespace"
            )
        return normalized

    @staticmethod
    def _normalize_optional_string(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _normalize_text(value: str | None) -> str | None:
        if value is None:
            return None

        # NFKC unifies common compatibility forms (for example full-width
        # Latin characters) without introducing semantic interpretation.
        normalized = unicodedata.normalize("NFKC", value)
        normalized = normalized.replace(_BOM, "").replace(_ZERO_WIDTH_SPACE, "")
        normalized = _WHITESPACE_RE.sub(" ", normalized).strip()
        return normalized or None

    @staticmethod
    def _normalize_timestamp(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise InputNormalizationError(
                "timestamp", "must be timezone-aware; timezone must not be guessed"
            )
        return value.astimezone(UTC)

    @staticmethod
    def _normalize_confidence(value: float | None) -> float | None:
        if value is None:
            return None
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise InputNormalizationError(
                "confidence", "must be a finite number between 0 and 1"
            )
        return value

    @staticmethod
    def _validate_meaningful_input(
        *,
        trigger_type: InputTriggerType,
        text: str | None,
        raw_text: str | None,
        input_payload: dict[str, Any] | None,
        segments: list[dict[str, Any]] | None,
    ) -> None:
        if trigger_type not in _USER_TRIGGERS:
            return

        has_text = bool(text) or bool(raw_text and raw_text.strip())
        has_payload = bool(input_payload)
        has_segments = bool(segments)
        if not (has_text or has_payload or has_segments):
            raise InputNormalizationError(
                "input",
                "user-originated input must contain text, payload, or segments",
            )
