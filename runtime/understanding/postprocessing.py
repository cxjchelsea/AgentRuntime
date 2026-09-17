"""M3-IU4 evidence, uncertainty, risk, and candidate postprocessing.

This module turns deterministic/model partial Understanding into typed internal
artifacts. It does not build the final ``UnderstandingState`` and does not grant
planning, safety, execution, response, or persistence authority.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from runtime.contracts.understanding import UncertaintyAssessment
from runtime.understanding.definitions import (
    CandidateAction,
    MemoryCandidate,
    RiskSignalSet,
    UnderstandingEvidence,
    UnderstandingEvidenceSource,
)
from runtime.understanding.errors import (
    CandidateExtractionError,
    InvalidModelEvidenceError,
    InvalidModelUncertaintyError,
    MissingDeepUnderstandingResultError,
)
from runtime.understanding.model_boundary import ModelUnderstandingResult
from runtime.understanding.routing import UnderstandingRouteDecision

_ALLOWED_UNCERTAINTY_FIELDS = frozenset(
    {
        "uncertain_fields",
        "candidate_interpretations",
        "needs_clarification",
        "safe_to_infer",
    }
)


@dataclass(frozen=True, slots=True)
class CandidateExtractionResult:
    """Candidates emitted by one injected extractor.

    These are still M3 candidates. They are not execution authorization and they
    are not persisted memory records.
    """

    memory_candidates: tuple[MemoryCandidate, ...] = ()
    candidate_actions: tuple[CandidateAction, ...] = ()


class UnderstandingCandidateExtractor(Protocol):
    """Domain-injected extraction boundary for post-understanding candidates."""

    @property
    def extractor_id(self) -> str:
        """Stable extractor identifier used for diagnostics."""
        ...

    def extract(
        self,
        route: UnderstandingRouteDecision,
        model_result: ModelUnderstandingResult | None,
        evidence: tuple[UnderstandingEvidence, ...],
    ) -> CandidateExtractionResult:
        """Return candidate-only artifacts with no side effects."""
        ...


@dataclass(frozen=True, slots=True)
class UnderstandingPostprocessResult:
    """Internal postprocessing result consumed by the later M3 merger/orchestrator."""

    evidence: tuple[UnderstandingEvidence, ...]
    uncertainty: UncertaintyAssessment
    risk: RiskSignalSet
    memory_candidates: tuple[MemoryCandidate, ...]
    candidate_actions: tuple[CandidateAction, ...]


class EvidenceNormalizer:
    """Normalize rule/model interpretation evidence into one M3 evidence stream."""

    def normalize(
        self,
        route: UnderstandingRouteDecision,
        model_result: ModelUnderstandingResult | None,
    ) -> tuple[UnderstandingEvidence, ...]:
        evidence = list(route.deterministic_result.evidence)
        seen_ids = {item.evidence_id for item in evidence}

        if model_result is None:
            return tuple(evidence)

        for index, payload in enumerate(model_result.evidence, start=1):
            normalized = self._normalize_model_evidence(payload, index)
            if normalized.evidence_id in seen_ids:
                raise InvalidModelEvidenceError("duplicate understanding evidence_id")
            seen_ids.add(normalized.evidence_id)
            evidence.append(normalized)

        return tuple(evidence)

    @staticmethod
    def _normalize_model_evidence(
        payload: Mapping[str, Any],
        index: int,
    ) -> UnderstandingEvidence:
        allowed_fields = {
            "evidence_id",
            "source_ref",
            "text_or_value",
            "supports_field",
            "strength",
        }
        if set(payload) - allowed_fields:
            raise InvalidModelEvidenceError(
                "model evidence contains unsupported fields"
            )

        evidence_id = payload.get("evidence_id")
        source_ref = payload.get("source_ref")
        text_or_value = payload.get("text_or_value")
        supports_field = payload.get("supports_field")
        strength = payload.get("strength")

        if evidence_id is None:
            evidence_id = f"model:{index}"
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            raise InvalidModelEvidenceError("model evidence_id must be non-blank text")
        if source_ref is not None and (
            not isinstance(source_ref, str) or not source_ref.strip()
        ):
            raise InvalidModelEvidenceError("model source_ref must be non-blank text")
        if not isinstance(text_or_value, str) or not text_or_value.strip():
            raise InvalidModelEvidenceError(
                "model text_or_value must be non-blank text"
            )
        if not isinstance(supports_field, str) or not supports_field.strip():
            raise InvalidModelEvidenceError(
                "model supports_field must be non-blank text"
            )
        if not isinstance(strength, (int, float)) or isinstance(strength, bool):
            raise InvalidModelEvidenceError("model evidence strength must be numeric")
        numeric_strength = float(strength)
        if not 0.0 <= numeric_strength <= 1.0:
            raise InvalidModelEvidenceError(
                "model evidence strength must be within [0, 1]"
            )

        return UnderstandingEvidence(
            evidence_id=evidence_id,
            source_type=UnderstandingEvidenceSource.MODEL_INFERENCE,
            source_ref=source_ref,
            text_or_value=text_or_value,
            supports_field=supports_field,
            strength=numeric_strength,
        )


class UncertaintyNormalizer:
    """Normalize model uncertainty without pretending confidence that was not given."""

    def normalize(
        self,
        route: UnderstandingRouteDecision,
        model_result: ModelUnderstandingResult | None,
    ) -> UncertaintyAssessment:
        if route.requires_model and model_result is None:
            raise MissingDeepUnderstandingResultError(
                "model-required route has no deep understanding result"
            )
        if model_result is None or model_result.uncertainty is None:
            return UncertaintyAssessment()

        payload = model_result.uncertainty
        if set(payload) - _ALLOWED_UNCERTAINTY_FIELDS:
            raise InvalidModelUncertaintyError(
                "model uncertainty contains unsupported fields"
            )

        uncertain_fields = _optional_string_list(payload, "uncertain_fields")
        candidate_interpretations = _optional_string_list(
            payload,
            "candidate_interpretations",
        )
        needs_clarification = _optional_bool(payload, "needs_clarification")
        safe_to_infer = _optional_bool(payload, "safe_to_infer")

        return UncertaintyAssessment(
            uncertain_fields=uncertain_fields,
            candidate_interpretations=candidate_interpretations,
            needs_clarification=needs_clarification,
            safe_to_infer=safe_to_infer,
        )


class RiskSignalNormalizer:
    """Merge deterministic/model M3 risk signals without creating a SafetyDecision."""

    def normalize(
        self,
        route: UnderstandingRouteDecision,
        model_result: ModelUnderstandingResult | None,
        evidence: tuple[UnderstandingEvidence, ...],
    ) -> RiskSignalSet:
        signal_ids = list(route.deterministic_result.risk_signal_ids)
        signal_confidences: list[float] = []
        evidence_ids: list[str] = []

        # RuleParseResult does not preserve per-risk evidence linkage. Do not invent
        # one by attaching every rule evidence item or the overall parse confidence.
        known_evidence_ids = {item.evidence_id for item in evidence}
        if model_result is not None:
            for payload in model_result.risk_signals:
                signal_id = payload.get("signal_id")
                confidence = payload.get("confidence")
                payload_evidence_ids = payload.get("evidence_ids", [])

                if not isinstance(signal_id, str) or not signal_id.strip():
                    raise InvalidModelEvidenceError(
                        "model risk signal_id must be non-blank text"
                    )
                if confidence is not None:
                    if not isinstance(confidence, (int, float)) or isinstance(
                        confidence, bool
                    ):
                        raise InvalidModelEvidenceError(
                            "model risk confidence must be numeric"
                        )
                    numeric_confidence = float(confidence)
                    if not 0.0 <= numeric_confidence <= 1.0:
                        raise InvalidModelEvidenceError(
                            "model risk confidence must be within [0, 1]"
                        )
                    signal_confidences.append(numeric_confidence)
                if not isinstance(payload_evidence_ids, list) or any(
                    not isinstance(item, str) or not item.strip()
                    for item in payload_evidence_ids
                ):
                    raise InvalidModelEvidenceError(
                        "model risk evidence_ids must be an array of non-blank text"
                    )
                unknown_evidence = set(payload_evidence_ids) - known_evidence_ids
                if unknown_evidence:
                    raise InvalidModelEvidenceError(
                        "model risk signal references unknown evidence_ids"
                    )

                if signal_id not in signal_ids:
                    signal_ids.append(signal_id)
                for evidence_id in payload_evidence_ids:
                    if evidence_id not in evidence_ids:
                        evidence_ids.append(evidence_id)

        return RiskSignalSet(
            signals=tuple(signal_ids),
            requires_safety_review=bool(signal_ids),
            confidence=max(signal_confidences) if signal_confidences else None,
            evidence_ids=tuple(evidence_ids),
        )


class CandidateExtractionPipeline:
    """Run injected candidate extractors and merge candidates deterministically."""

    def __init__(
        self,
        extractors: tuple[UnderstandingCandidateExtractor, ...] = (),
    ) -> None:
        extractor_ids = tuple(extractor.extractor_id for extractor in extractors)
        if any(not extractor_id.strip() for extractor_id in extractor_ids):
            raise CandidateExtractionError("extractor_id must not be blank")
        if len(set(extractor_ids)) != len(extractor_ids):
            raise CandidateExtractionError("duplicate candidate extractor_id")
        self._extractors = extractors

    def extract(
        self,
        route: UnderstandingRouteDecision,
        model_result: ModelUnderstandingResult | None,
        evidence: tuple[UnderstandingEvidence, ...],
    ) -> CandidateExtractionResult:
        memory_by_id: dict[str, MemoryCandidate] = {}
        action_by_key: dict[tuple[str, str | None], CandidateAction] = {}

        for extractor in self._extractors:
            try:
                result = extractor.extract(route, model_result, evidence)
            except CandidateExtractionError:
                raise
            except Exception as exc:
                raise CandidateExtractionError(
                    f"candidate extractor failed: {extractor.extractor_id}"
                ) from exc

            for memory in result.memory_candidates:
                existing = memory_by_id.get(memory.candidate_id)
                if existing is not None and existing != memory:
                    raise CandidateExtractionError(
                        "conflicting memory candidates share the same candidate_id"
                    )
                memory_by_id[memory.candidate_id] = memory

            for action in result.candidate_actions:
                key = (action.action, action.target)
                existing = action_by_key.get(key)
                if existing is None or action.confidence > existing.confidence:
                    action_by_key[key] = action

        return CandidateExtractionResult(
            memory_candidates=tuple(memory_by_id.values()),
            candidate_actions=tuple(action_by_key.values()),
        )


class UnderstandingPostprocessor:
    """Coordinate IU4 normalizers without building final UnderstandingState."""

    def __init__(
        self,
        *,
        evidence_normalizer: EvidenceNormalizer | None = None,
        uncertainty_normalizer: UncertaintyNormalizer | None = None,
        risk_normalizer: RiskSignalNormalizer | None = None,
        candidate_pipeline: CandidateExtractionPipeline | None = None,
    ) -> None:
        self._evidence_normalizer = evidence_normalizer or EvidenceNormalizer()
        self._uncertainty_normalizer = (
            uncertainty_normalizer or UncertaintyNormalizer()
        )
        self._risk_normalizer = risk_normalizer or RiskSignalNormalizer()
        self._candidate_pipeline = candidate_pipeline or CandidateExtractionPipeline()

    def process(
        self,
        route: UnderstandingRouteDecision,
        model_result: ModelUnderstandingResult | None,
    ) -> UnderstandingPostprocessResult:
        evidence = self._evidence_normalizer.normalize(route, model_result)
        uncertainty = self._uncertainty_normalizer.normalize(route, model_result)
        risk = self._risk_normalizer.normalize(route, model_result, evidence)
        candidates = self._candidate_pipeline.extract(route, model_result, evidence)

        return UnderstandingPostprocessResult(
            evidence=evidence,
            uncertainty=uncertainty,
            risk=risk,
            memory_candidates=candidates.memory_candidates,
            candidate_actions=candidates.candidate_actions,
        )


def _optional_string_list(
    payload: Mapping[str, Any],
    field_name: str,
) -> list[str] | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise InvalidModelUncertaintyError(
            f"{field_name} must be an array of non-blank text"
        )
    return deepcopy(value)


def _optional_bool(payload: Mapping[str, Any], field_name: str) -> bool | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise InvalidModelUncertaintyError(f"{field_name} must be boolean")
    return value
