"""M3-IU1 Understanding contract-alignment and internal-type gates."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from pathlib import Path

import pytest

from runtime.contracts import (
    CoreControlIntent,
    IntentEvidenceSource,
    QualityAssessment,
    UnderstandingMetadata,
    UnderstandingState,
)
from runtime.contracts.common import CanonicalModel, VersionedContract
from runtime.contracts.enums import ProcessingPath
from runtime.contracts.understanding import UncertaintyAssessment
from runtime.interfaces import UnderstandingEngine
from runtime.understanding import (
    CandidateAction,
    CandidateActionCatalog,
    CandidateActionDefinition,
    IntentCatalog,
    IntentDefinition,
    InvalidUnderstandingCandidateError,
    InvalidUnderstandingDefinitionError,
    InvalidUnderstandingEvidenceError,
    MemoryCandidate,
    NeedCatalog,
    NeedDefinition,
    NeedResult,
    RiskSignalSet,
    UnderstandingEvidence,
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


def test_m3_iu1_keeps_frozen_understanding_interface() -> None:
    signature = inspect.signature(UnderstandingEngine.understand)
    assert tuple(signature.parameters) == (
        "self",
        "runtime_input",
        "runtime_context",
    )
    assert inspect.iscoroutinefunction(UnderstandingEngine.understand)


def test_understanding_state_keeps_frozen_nested_surface() -> None:
    assert set(UnderstandingState.model_fields) == {
        "schema_version",
        "metadata",
        "intents",
        "uncertainty",
        "quality",
        "semantic",
        "goal",
        "entities",
        "references",
        "topic",
        "emotion",
        "needs",
        "interaction",
        "risk",
        "evidence",
        "memory_candidates",
        "candidate_actions",
    }
    for forbidden_flat_field in (
        "primary_intent",
        "emotion_label",
        "risk_level",
        "action_plan",
        "tool_call",
    ):
        assert forbidden_flat_field not in UnderstandingState.model_fields


def test_m3_internal_types_are_not_canonical_contracts() -> None:
    internal_types = (
        IntentDefinition,
        NeedDefinition,
        CandidateActionDefinition,
        UnderstandingEvidence,
        NeedResult,
        RiskSignalSet,
        MemoryCandidate,
        CandidateAction,
    )
    for internal_type in internal_types:
        assert not issubclass(internal_type, CanonicalModel)
        assert not issubclass(internal_type, VersionedContract)


def test_intent_catalog_accepts_domain_registered_values_without_core_enum_change() -> (
    None
):
    catalog = IntentCatalog()
    definition = IntentDefinition(
        intent_id="DOMAIN_CUSTOM_INTENT",
        version="1.0.0",
        namespace="example-domain",
        description="injected domain value",
    )

    catalog.register_definition(definition)

    record = catalog.get(
        "DOMAIN_CUSTOM_INTENT",
        "1.0.0",
        namespace="example-domain",
    )
    assert record.definition == definition
    assert record.implementation_ref is None


def test_core_control_intent_definition_must_match_frozen_value() -> None:
    definition = IntentDefinition(
        intent_id=CoreControlIntent.STOP.value,
        version="1.0.0",
        namespace="core",
        core_control_intent=CoreControlIntent.STOP,
    )
    assert definition.intent_id == "STOP"

    with pytest.raises(InvalidUnderstandingDefinitionError):
        IntentDefinition(
            intent_id="NOT_STOP",
            version="1.0.0",
            namespace="core",
            core_control_intent=CoreControlIntent.STOP,
        )


def test_need_and_candidate_action_catalogs_are_metadata_only() -> None:
    need_catalog = NeedCatalog()
    action_catalog = CandidateActionCatalog()
    need = NeedDefinition(
        need_id="DOMAIN_NEED",
        version="1.0.0",
        namespace="example-domain",
    )
    action = CandidateActionDefinition(
        action_id="DOMAIN_SEMANTIC_ACTION",
        version="1.0.0",
        namespace="example-domain",
    )

    need_catalog.register_definition(need)
    action_catalog.register_definition(action)

    assert (
        need_catalog.get("DOMAIN_NEED", "1.0.0", namespace="example-domain").definition
        == need
    )
    assert (
        action_catalog.get(
            "DOMAIN_SEMANTIC_ACTION", "1.0.0", namespace="example-domain"
        ).definition
        == action
    )


def test_evidence_and_candidates_project_into_frozen_dictionary_fields() -> None:
    evidence = UnderstandingEvidence(
        evidence_id="e-1",
        source_type=UnderstandingEvidenceSource.CURRENT_INPUT,
        source_ref="text",
        text_or_value="please stop",
        supports_field="intents[0]",
        strength=0.95,
    )
    need = NeedResult(
        need_type="DOMAIN_NEED",
        confidence=0.65,
        source=IntentEvidenceSource.INFERRED,
        evidence_ids=("e-1",),
    )
    risk = RiskSignalSet(
        signals=("DOMAIN_RISK_SIGNAL",),
        requires_safety_review=True,
        confidence=0.7,
        evidence_ids=("e-1",),
    )
    memory = MemoryCandidate(
        candidate_id="m-1",
        memory_type="DOMAIN_MEMORY_TYPE",
        content="candidate only",
        source="CURRENT_INPUT",
        confidence=0.8,
        suggested_scope="SESSION",
    )
    action = CandidateAction(
        action="DOMAIN_SEMANTIC_ACTION",
        confidence=0.75,
        target="target-1",
        reason_code="UNDERSTANDING_CANDIDATE",
    )

    state = UnderstandingState(
        metadata=UnderstandingMetadata(
            understanding_id="u-1",
            request_id="r-1",
            timestamp=datetime.now(UTC),
            processing_path=ProcessingPath.FAST_PATH,
        ),
        intents=[],
        uncertainty=UncertaintyAssessment(),
        quality=QualityAssessment(),
        needs=[need.to_payload()],
        risk=risk.to_payload(),
        evidence=[evidence.to_payload()],
        memory_candidates=[memory.to_payload()],
        candidate_actions=[action.to_payload()],
    )

    assert state.evidence == [evidence.to_payload()]
    assert state.needs == [need.to_payload()]
    assert state.risk == risk.to_payload()
    assert state.memory_candidates == [memory.to_payload()]
    assert state.candidate_actions == [action.to_payload()]


def test_candidate_action_is_not_execution_authorization() -> None:
    candidate = CandidateAction(action="DOMAIN_ACTION", confidence=0.9)
    payload = candidate.to_payload()

    assert "steps" not in payload
    assert "approval_status" not in payload
    assert "policy_snapshot" not in payload
    assert "tool_requirement" not in payload


def test_m3_foundation_rejects_invalid_confidence_and_blank_ids() -> None:
    with pytest.raises(InvalidUnderstandingEvidenceError):
        UnderstandingEvidence(
            evidence_id="e-1",
            source_type=UnderstandingEvidenceSource.MODEL_INFERENCE,
            source_ref=None,
            text_or_value="value",
            supports_field="goal",
            strength=1.1,
        )

    with pytest.raises(InvalidUnderstandingCandidateError):
        CandidateAction(action="DOMAIN_ACTION", confidence=-0.01)

    with pytest.raises(InvalidUnderstandingDefinitionError):
        NeedDefinition(need_id=" ", version="1.0.0")


def test_runtime_understanding_package_has_no_domain_hardcoding() -> None:
    package_root = Path("runtime/understanding")
    source_text = "\n".join(
        source_file.read_text(encoding="utf-8")
        for source_file in package_root.glob("*.py")
    )
    for forbidden_value in FORBIDDEN_DOMAIN_VALUES:
        assert forbidden_value not in source_text


def test_runtime_understanding_package_preserves_m0_hygiene() -> None:
    package_root = Path("runtime/understanding")
    for source_file in package_root.glob("*.py"):
        assert "NotImplementedError" not in source_file.read_text(encoding="utf-8")


def test_m3_iu1_does_not_claim_a_real_understanding_engine() -> None:
    import runtime.understanding as understanding_module

    exported_names = set(dir(understanding_module))
    assert "DefaultUnderstandingEngine" not in exported_names
    assert "UnderstandingOrchestrator" not in exported_names
    assert "LLMUnderstandingEngine" not in exported_names
