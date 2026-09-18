"""M3-IU5 final UnderstandingState assembly.

This module merges deterministic/model/postprocessed Understanding artifacts into
the frozen Canonical UnderstandingState. It does not plan, execute, respond,
persist memory, mutate Runtime state, or make Safety decisions.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import ValidationError

from runtime.contracts import QualityAssessment, RuntimeInput, UnderstandingState
from runtime.contracts.common import SCHEMA_VERSION
from runtime.contracts.enums import IntentEvidenceSource, SpeechAct
from runtime.contracts.understanding import (
    GoalUnderstanding,
    IntentResult,
    Reference,
    SemanticUnderstanding,
    UnderstandingMetadata,
)
from runtime.understanding.errors import (
    InvalidModelUnderstandingFragmentError,
    UnderstandingMergeConflictError,
)
from runtime.understanding.model_boundary import ModelUnderstandingResult
from runtime.understanding.postprocessing import UnderstandingPostprocessResult
from runtime.understanding.routing import UnderstandingRouteDecision

_MODEL_INTENT_FIELDS = frozenset({"intent_id", "confidence", "evidence_ids"})


class UnderstandingStateAssembler:
    """Assemble one Canonical UnderstandingState using fixed merge precedence.

    Deterministic rule facts remain authoritative for fields they explicitly set.
    Model output may add Understanding information but cannot rewrite deterministic
    facts, provenance, or downstream authority.
    """

    def assemble(
        self,
        runtime_input: RuntimeInput,
        route: UnderstandingRouteDecision,
        model_result: ModelUnderstandingResult | None,
        postprocess: UnderstandingPostprocessResult,
    ) -> UnderstandingState:
        evidence_ids = {item.evidence_id for item in postprocess.evidence}

        semantic = self._merge_semantic(route, model_result)
        intents = self._merge_intents(route, model_result, evidence_ids)
        goal = self._parse_goal(model_result)
        references = self._parse_references(model_result)

        try:
            return UnderstandingState(
                metadata=UnderstandingMetadata(
                    understanding_id=f"understanding:{runtime_input.request_id}",
                    request_id=runtime_input.request_id,
                    timestamp=runtime_input.timestamp,
                    processing_path=route.processing_path,
                    schema_version=SCHEMA_VERSION,
                ),
                intents=intents,
                uncertainty=postprocess.uncertainty,
                quality=QualityAssessment(),
                semantic=semantic,
                goal=goal,
                references=references,
                emotion=(
                    deepcopy(model_result.emotion)
                    if model_result is not None and model_result.emotion is not None
                    else None
                ),
                needs=(
                    [deepcopy(item) for item in model_result.needs]
                    if model_result is not None and model_result.needs
                    else None
                ),
                interaction=(
                    deepcopy(model_result.interaction)
                    if model_result is not None and model_result.interaction is not None
                    else None
                ),
                risk=postprocess.risk.to_payload(),
                evidence=[item.to_payload() for item in postprocess.evidence],
                memory_candidates=[
                    item.to_payload() for item in postprocess.memory_candidates
                ]
                or None,
                candidate_actions=[
                    item.to_payload() for item in postprocess.candidate_actions
                ]
                or None,
            )
        except ValidationError as exc:
            raise InvalidModelUnderstandingFragmentError(
                "assembled UnderstandingState failed Canonical validation"
            ) from exc

    def _merge_semantic(
        self,
        route: UnderstandingRouteDecision,
        model_result: ModelUnderstandingResult | None,
    ) -> SemanticUnderstanding | None:
        payload: dict[str, Any] = {}
        if model_result is not None and model_result.semantic is not None:
            payload = deepcopy(model_result.semantic)

        deterministic = route.deterministic_result

        selected_speech_act = self._resolve_speech_act(
            deterministic.speech_acts,
            payload.get("speech_act"),
        )
        if selected_speech_act is not None:
            payload["speech_act"] = selected_speech_act

        for field_name, deterministic_value in (
            ("negation", deterministic.negation),
            ("confirmation", deterministic.confirmation),
            ("correction", deterministic.correction),
        ):
            if deterministic_value is not None:
                payload[field_name] = deterministic_value

        if not payload:
            return None

        try:
            return SemanticUnderstanding.model_validate(payload)
        except ValidationError as exc:
            raise InvalidModelUnderstandingFragmentError(
                "semantic model fragment is incompatible with the Canonical schema"
            ) from exc

    @staticmethod
    def _resolve_speech_act(
        deterministic_acts: tuple[SpeechAct, ...],
        model_value: object,
    ) -> SpeechAct | None:
        if len(deterministic_acts) == 1:
            return deterministic_acts[0]

        if len(deterministic_acts) > 1:
            if model_value is None:
                raise UnderstandingMergeConflictError(
                    "multiple deterministic speech acts require model disambiguation"
                )
            try:
                selected = SpeechAct(model_value)
            except (TypeError, ValueError) as exc:
                raise InvalidModelUnderstandingFragmentError(
                    "model speech_act is invalid"
                ) from exc
            if selected not in deterministic_acts:
                raise UnderstandingMergeConflictError(
                    "model speech_act contradicts deterministic candidates"
                )
            return selected

        if model_value is None:
            return None
        try:
            return SpeechAct(model_value)
        except (TypeError, ValueError) as exc:
            raise InvalidModelUnderstandingFragmentError(
                "model speech_act is invalid"
            ) from exc

    def _merge_intents(
        self,
        route: UnderstandingRouteDecision,
        model_result: ModelUnderstandingResult | None,
        known_evidence_ids: set[str],
    ) -> list[IntentResult]:
        merged: dict[str, IntentResult] = {
            intent.intent_id: intent.model_copy(deep=True)
            for intent in route.deterministic_result.intents
        }

        if model_result is None:
            return list(merged.values())

        for payload in model_result.intents:
            unknown_fields = set(payload) - _MODEL_INTENT_FIELDS
            if unknown_fields:
                raise InvalidModelUnderstandingFragmentError(
                    "model intent contains unsupported fields"
                )

            intent_id = payload.get("intent_id")
            confidence = payload.get("confidence")
            evidence_ids = payload.get("evidence_ids")

            if not isinstance(intent_id, str) or not intent_id.strip():
                raise InvalidModelUnderstandingFragmentError(
                    "model intent_id must be non-blank text"
                )
            if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
                raise InvalidModelUnderstandingFragmentError(
                    "model intent confidence must be numeric"
                )
            numeric_confidence = float(confidence)
            if not 0.0 <= numeric_confidence <= 1.0:
                raise InvalidModelUnderstandingFragmentError(
                    "model intent confidence must be within [0, 1]"
                )

            normalized_evidence_ids: list[str] | None = None
            if evidence_ids is not None:
                if not isinstance(evidence_ids, list) or any(
                    not isinstance(item, str) or not item.strip()
                    for item in evidence_ids
                ):
                    raise InvalidModelUnderstandingFragmentError(
                        "model intent evidence_ids must be an array of non-blank text"
                    )
                if set(evidence_ids) - known_evidence_ids:
                    raise InvalidModelUnderstandingFragmentError(
                        "model intent references unknown evidence_ids"
                    )
                normalized_evidence_ids = list(evidence_ids)

            if intent_id in merged:
                continue

            try:
                merged[intent_id] = IntentResult(
                    intent_id=intent_id,
                    confidence=numeric_confidence,
                    source=IntentEvidenceSource.INFERRED,
                    evidence_ids=normalized_evidence_ids,
                )
            except ValidationError as exc:
                raise InvalidModelUnderstandingFragmentError(
                    "model intent is incompatible with the Canonical schema"
                ) from exc

        return list(merged.values())

    @staticmethod
    def _parse_goal(
        model_result: ModelUnderstandingResult | None,
    ) -> GoalUnderstanding | None:
        if model_result is None or model_result.goal is None:
            return None
        try:
            return GoalUnderstanding.model_validate(deepcopy(model_result.goal))
        except ValidationError as exc:
            raise InvalidModelUnderstandingFragmentError(
                "goal model fragment is incompatible with the Canonical schema"
            ) from exc

    @staticmethod
    def _parse_references(
        model_result: ModelUnderstandingResult | None,
    ) -> list[Reference] | None:
        if model_result is None or not model_result.references:
            return None
        try:
            return [
                Reference.model_validate(deepcopy(payload))
                for payload in model_result.references
            ]
        except ValidationError as exc:
            raise InvalidModelUnderstandingFragmentError(
                "reference model fragment is incompatible with the Canonical schema"
            ) from exc
