"""M3-IU4 evidence/uncertainty/candidate postprocessing gates."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.contracts import IntentResult
from runtime.contracts.enums import IntentEvidenceSource, ProcessingPath
from runtime.understanding import (
    CandidateAction,
    CandidateExtractionError,
    CandidateExtractionPipeline,
    CandidateExtractionResult,
    EvidenceNormalizer,
    InvalidModelEvidenceError,
    InvalidModelUncertaintyError,
    MemoryCandidate,
    MissingDeepUnderstandingResultError,
    ModelUnderstandingResult,
    RiskSignalNormalizer,
    RuleParseResult,
    UnderstandingEvidence,
    UnderstandingEvidenceSource,
    UnderstandingPostprocessor,
    UnderstandingRouteDecision,
    UncertaintyNormalizer,
)


def _evidence(
    evidence_id: str = "rule:r1:1",
    *,
    strength: float = 0.95,
) -> UnderstandingEvidence:
    return UnderstandingEvidence(
        evidence_id=evidence_id,
        source_type=UnderstandingEvidenceSource.RULE_MATCH,
        source_ref="r1",
        text_or_value="synthetic",
        supports_field="intents[0]",
        strength=strength,
    )


def _rule_result(
    *,
    matched: bool = True,
    risk_signal_ids: tuple[str, ...] = (),
) -> RuleParseResult:
    if not matched:
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
    evidence = _evidence()
    return RuleParseResult(
        matched_rule_ids=("r1",),
        intents=(
            IntentResult(
                intent_id="DOMAIN_INTENT",
                confidence=0.95,
                source=IntentEvidenceSource.RULE,
                evidence_ids=[evidence.evidence_id],
            ),
        ),
        speech_acts=(),
        negation=None,
        confirmation=None,
        correction=None,
        pending_question_resolution=None,
        risk_signal_ids=risk_signal_ids,
        evidence=(evidence,),
        confidence=0.95,
    )


def _route(
    processing_path: ProcessingPath = ProcessingPath.FAST_PATH,
    *,
    risk_signal_ids: tuple[str, ...] = (),
) -> UnderstandingRouteDecision:
    return UnderstandingRouteDecision(
        processing_path=processing_path,
        reason_codes=("TEST_ROUTE",),
        deterministic_result=_rule_result(
            matched=processing_path is not ProcessingPath.DEEP_PATH,
            risk_signal_ids=risk_signal_ids,
        ),
    )


def test_fast_postprocessing_uses_rule_evidence_without_model() -> None:
    result = UnderstandingPostprocessor().process(_route(), None)

    assert [item.evidence_id for item in result.evidence] == ["rule:r1:1"]
    assert result.uncertainty.uncertain_fields is None
    assert result.risk.signals == ()
    assert result.risk.requires_safety_review is False
    assert result.memory_candidates == ()
    assert result.candidate_actions == ()


def test_model_evidence_is_forced_to_model_inference_provenance() -> None:
    model_result = ModelUnderstandingResult(
        evidence=(
            {
                "evidence_id": "model:e1",
                "source_ref": "model-output",
                "text_or_value": "synthetic interpretation",
                "supports_field": "goal",
                "strength": 0.8,
            },
        )
    )

    evidence = EvidenceNormalizer().normalize(
        _route(ProcessingPath.HYBRID_PATH),
        model_result,
    )

    assert evidence[-1].evidence_id == "model:e1"
    assert evidence[-1].source_type is UnderstandingEvidenceSource.MODEL_INFERENCE


def test_model_cannot_spoof_evidence_source_or_duplicate_rule_evidence_id() -> None:
    with pytest.raises(InvalidModelEvidenceError):
        EvidenceNormalizer().normalize(
            _route(ProcessingPath.HYBRID_PATH),
            ModelUnderstandingResult(
                evidence=(
                    {
                        "evidence_id": "model:e1",
                        "source_type": "RULE_MATCH",
                        "text_or_value": "synthetic",
                        "supports_field": "goal",
                        "strength": 0.7,
                    },
                )
            ),
        )

    with pytest.raises(InvalidModelEvidenceError):
        EvidenceNormalizer().normalize(
            _route(ProcessingPath.HYBRID_PATH),
            ModelUnderstandingResult(
                evidence=(
                    {
                        "evidence_id": "rule:r1:1",
                        "text_or_value": "synthetic",
                        "supports_field": "goal",
                        "strength": 0.7,
                    },
                )
            ),
        )


def test_deep_or_hybrid_route_requires_a_model_result_before_postprocessing() -> None:
    with pytest.raises(MissingDeepUnderstandingResultError):
        UnderstandingPostprocessor().process(
            _route(ProcessingPath.DEEP_PATH),
            None,
        )

    with pytest.raises(MissingDeepUnderstandingResultError):
        UncertaintyNormalizer().normalize(
            _route(ProcessingPath.HYBRID_PATH),
            None,
        )


def test_uncertainty_normalizer_accepts_only_frozen_uncertainty_surface() -> None:
    result = UncertaintyNormalizer().normalize(
        _route(ProcessingPath.HYBRID_PATH),
        ModelUnderstandingResult(
            uncertainty={
                "uncertain_fields": ["goal"],
                "candidate_interpretations": ["A", "B"],
                "needs_clarification": True,
                "safe_to_infer": False,
            }
        ),
    )

    assert result.uncertain_fields == ["goal"]
    assert result.candidate_interpretations == ["A", "B"]
    assert result.needs_clarification is True
    assert result.safe_to_infer is False

    with pytest.raises(InvalidModelUncertaintyError):
        UncertaintyNormalizer().normalize(
            _route(ProcessingPath.HYBRID_PATH),
            ModelUnderstandingResult(uncertainty={"overall_level": "HIGH"}),
        )


def test_risk_normalization_keeps_signals_in_m3_and_requires_known_evidence() -> None:
    evidence = (
        _evidence(),
        UnderstandingEvidence(
            evidence_id="model:risk-evidence",
            source_type=UnderstandingEvidenceSource.MODEL_INFERENCE,
            source_ref="model-output",
            text_or_value="synthetic risk signal",
            supports_field="risk",
            strength=0.75,
        ),
    )
    result = RiskSignalNormalizer().normalize(
        _route(
            ProcessingPath.HYBRID_PATH,
            risk_signal_ids=("DOMAIN_RULE_RISK",),
        ),
        ModelUnderstandingResult(
            risk_signals=(
                {
                    "signal_id": "DOMAIN_MODEL_RISK",
                    "confidence": 0.75,
                    "evidence_ids": ["model:risk-evidence"],
                },
            )
        ),
        evidence,
    )

    assert result.signals == ("DOMAIN_RULE_RISK", "DOMAIN_MODEL_RISK")
    assert result.requires_safety_review is True
    assert not hasattr(result, "forced_workflow")
    assert not hasattr(result, "safety_result")

    with pytest.raises(InvalidModelEvidenceError):
        RiskSignalNormalizer().normalize(
            _route(ProcessingPath.HYBRID_PATH),
            ModelUnderstandingResult(
                risk_signals=(
                    {
                        "signal_id": "DOMAIN_MODEL_RISK",
                        "evidence_ids": ["missing-evidence"],
                    },
                )
            ),
            evidence,
        )


def test_candidate_pipeline_uses_injected_extractors_and_deduplicates_actions() -> None:
    class ExtractorA:
        @property
        def extractor_id(self) -> str:
            return "extractor-a"

        def extract(self, route, model_result, evidence):
            del route, model_result, evidence
            return CandidateExtractionResult(
                memory_candidates=(
                    MemoryCandidate(
                        candidate_id="memory-1",
                        memory_type="DOMAIN_MEMORY",
                        content="candidate only",
                        source="CURRENT_INPUT",
                        confidence=0.8,
                    ),
                ),
                candidate_actions=(
                    CandidateAction(
                        action="DOMAIN_ACTION",
                        target="target",
                        confidence=0.6,
                    ),
                ),
            )

    class ExtractorB:
        @property
        def extractor_id(self) -> str:
            return "extractor-b"

        def extract(self, route, model_result, evidence):
            del route, model_result, evidence
            return CandidateExtractionResult(
                candidate_actions=(
                    CandidateAction(
                        action="DOMAIN_ACTION",
                        target="target",
                        confidence=0.9,
                        reason_code="BETTER_CANDIDATE",
                    ),
                ),
            )

    result = CandidateExtractionPipeline((ExtractorA(), ExtractorB())).extract(
        _route(),
        None,
        (_evidence(),),
    )

    assert len(result.memory_candidates) == 1
    assert len(result.candidate_actions) == 1
    assert result.candidate_actions[0].confidence == 0.9
    assert not hasattr(result.candidate_actions[0], "approval_status")


def test_candidate_pipeline_fails_closed_on_conflicting_memory_ids() -> None:
    class ConflictingExtractor:
        def __init__(self, extractor_id: str, content: str) -> None:
            self._extractor_id = extractor_id
            self._content = content

        @property
        def extractor_id(self) -> str:
            return self._extractor_id

        def extract(self, route, model_result, evidence):
            del route, model_result, evidence
            return CandidateExtractionResult(
                memory_candidates=(
                    MemoryCandidate(
                        candidate_id="same-id",
                        memory_type="DOMAIN_MEMORY",
                        content=self._content,
                        source="CURRENT_INPUT",
                        confidence=0.8,
                    ),
                )
            )

    pipeline = CandidateExtractionPipeline(
        (
            ConflictingExtractor("a", "one"),
            ConflictingExtractor("b", "two"),
        )
    )

    with pytest.raises(CandidateExtractionError):
        pipeline.extract(_route(), None, (_evidence(),))


def test_candidate_extractor_exception_is_sanitized_and_preserves_cause() -> None:
    class ExplodingExtractor:
        @property
        def extractor_id(self) -> str:
            return "exploding-extractor"

        def extract(self, route, model_result, evidence):
            del route, model_result, evidence
            raise RuntimeError("private candidate extraction detail")

    with pytest.raises(CandidateExtractionError) as exc_info:
        CandidateExtractionPipeline((ExplodingExtractor(),)).extract(
            _route(),
            None,
            (_evidence(),),
        )

    assert "private candidate extraction detail" not in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_iu4_does_not_claim_final_understanding_or_downstream_authority() -> None:
    import runtime.understanding as understanding_module

    exported_names = set(dir(understanding_module))
    for forbidden_name in (
        "DefaultUnderstandingEngine",
        "UnderstandingOrchestrator",
        "Planner",
        "ToolExecutor",
        "MemoryWriter",
        "SafetyDecision",
    ):
        assert forbidden_name not in exported_names

    source_text = "\n".join(
        source_file.read_text(encoding="utf-8")
        for source_file in Path("runtime/understanding").glob("*.py")
    )
    assert "NotImplementedError" not in source_text
