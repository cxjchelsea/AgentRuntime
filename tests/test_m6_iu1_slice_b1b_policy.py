"""B1b-P P01-P08: no origin attestation, no allow and no downstream effects."""

from dataclasses import FrozenInstanceError, replace

import pytest

from runtime.contracts import BusinessStatus, ValidationStatus
from runtime.validation.no_grant_downstream_policy import (
    NoGrantDownstreamContext,
    NoGrantDownstreamDecision,
    NoGrantDownstreamDisposition,
    NoGrantDownstreamError,
    NoGrantDownstreamErrorCode,
    NoGrantDownstreamReason,
    NoGrantOriginClassification,
    evaluate_no_grant_downstream,
)
from tests.orchestration_stubs import build_validated_result


def _context(
    *,
    kind: NoGrantOriginClassification = NoGrantOriginClassification.NO_GRANT_INTERNAL,
) -> NoGrantDownstreamContext:
    return NoGrantDownstreamContext(
        expected_request_id="request-001",
        expected_execution_id="execution-001",
        expected_validation_id="validation-001",
        expected_identity_scope="scope-001",
        expected_session_id="session-001",
        provenance_kind=kind,
    )


def _unknown():
    result = build_validated_result()
    result.validation_status = ValidationStatus.UNKNOWN
    result.business_status = BusinessStatus.UNKNOWN
    return result


def _decision(result=None, context=None) -> NoGrantDownstreamDecision:
    return evaluate_no_grant_downstream(
        validated=_unknown() if result is None else result,
        context=_context() if context is None else context,
    )


def test_p01_structural_no_grant_is_only_block() -> None:
    d = _decision()
    assert d.disposition is NoGrantDownstreamDisposition.BLOCK_BEFORE_M7_M8
    assert d.reason is NoGrantDownstreamReason.NO_AUTHORIZED_VALIDATION_GRANT
    assert (d.request_id, d.execution_id, d.validation_id) == (
        "request-001",
        "execution-001",
        "validation-001",
    )
    assert not any(
        (
            d.may_call_response_planner,
            d.may_call_response_generator,
            d.may_call_response_validator,
            d.may_call_state_memory_updater,
            d.may_emit_positive_claim,
            d.may_commit_business_or_memory,
        )
    )
    assert d.allowed_user_response == "NONE"


@pytest.mark.parametrize("field", ["allowed_claims", "conditional_claims"])
def test_p02_forged_claims_are_blocked(field: str) -> None:
    validated = _unknown()
    setattr(validated.claim_policy, field, ["business succeeded"])
    d = _decision(validated)
    assert d.reason is NoGrantDownstreamReason.CANONICAL_MISMATCH
    assert d.disposition is NoGrantDownstreamDisposition.BLOCK_BEFORE_M7_M8


@pytest.mark.parametrize(
    "field", ["verified_facts", "goal_validation", "state_recommendation"]
)
def test_p02_forged_verification_is_blocked(field: str) -> None:
    validated = _unknown()
    setattr(
        validated,
        field,
        [{"success": True}] if field == "verified_facts" else {"success": True},
    )
    assert _decision(validated).reason is NoGrantDownstreamReason.CANONICAL_MISMATCH


def test_p02_forged_error_tag_does_not_authorize() -> None:
    validated = _unknown()
    validated.validation_errors = [{"code": "AUTHORIZED", "reason": "GRANTED"}]
    assert (
        _decision(validated).reason
        is NoGrantDownstreamReason.NO_AUTHORIZED_VALIDATION_GRANT
    )


@pytest.mark.parametrize(
    "field",
    [
        "expected_request_id",
        "expected_execution_id",
        "expected_validation_id",
        "expected_identity_scope",
        "expected_session_id",
    ],
)
@pytest.mark.parametrize("value", ["", " ", " value ", 42])
def test_p03_context_rejects_invalid_identifier(field: str, value: object) -> None:
    payload: dict[str, object] = {
        "expected_request_id": "request-001",
        "expected_execution_id": "execution-001",
        "expected_validation_id": "validation-001",
        "expected_identity_scope": "scope-001",
        "expected_session_id": "session-001",
        "provenance_kind": NoGrantOriginClassification.NO_GRANT_INTERNAL,
    }
    payload[field] = value
    with pytest.raises(NoGrantDownstreamError) as err:
        NoGrantDownstreamContext(**payload)  # type: ignore[arg-type]
    assert err.value.code is NoGrantDownstreamErrorCode.INVALID_CONTEXT_FIELD


def test_p03_context_type_precedes_validated_type() -> None:
    with pytest.raises(NoGrantDownstreamError) as err:
        evaluate_no_grant_downstream(validated=None, context=None)  # type: ignore[arg-type]
    assert err.value.code is NoGrantDownstreamErrorCode.INVALID_CONTEXT


def test_p03_validated_type_rejected() -> None:
    with pytest.raises(NoGrantDownstreamError) as err:
        evaluate_no_grant_downstream(validated=None, context=_context())  # type: ignore[arg-type]
    assert err.value.code is NoGrantDownstreamErrorCode.INVALID_VALIDATED_RESULT


@pytest.mark.parametrize(
    "field",
    [
        "expected_request_id",
        "expected_execution_id",
        "expected_validation_id",
    ],
)
def test_p03_correlation_mismatch_suppresses_diagnostic_ids(field: str) -> None:
    baseline = _context()
    context = replace(
        baseline,
        expected_request_id=(
            "different"
            if field == "expected_request_id"
            else baseline.expected_request_id
        ),
        expected_execution_id=(
            "different"
            if field == "expected_execution_id"
            else baseline.expected_execution_id
        ),
        expected_validation_id=(
            "different"
            if field == "expected_validation_id"
            else baseline.expected_validation_id
        ),
    )
    d = _decision(context=context)
    assert d.reason is NoGrantDownstreamReason.CORRELATION_MISMATCH
    assert (d.request_id, d.execution_id, d.validation_id) == (None, None, None)


def test_p03_corrupted_frozen_context_rejected() -> None:
    context = _context()
    object.__setattr__(context, "structural_only", 1)
    with pytest.raises(NoGrantDownstreamError) as err:
        _decision(context=context)
    assert err.value.code is NoGrantDownstreamErrorCode.INVALID_CONTEXT_FIELD


def test_p04_positive_canonical_status_cannot_allow() -> None:
    positive = build_validated_result()
    assert _decision(positive).reason is NoGrantDownstreamReason.CANONICAL_MISMATCH


def test_p05_unattested_even_when_correlation_matches() -> None:
    d = _decision(context=_context(kind=NoGrantOriginClassification.UNATTESTED_UNKNOWN))
    assert d.reason is NoGrantDownstreamReason.AUTHORITY_UNATTESTED
    assert d.disposition is NoGrantDownstreamDisposition.BLOCK_BEFORE_M7_M8


def test_p05_replay_is_still_deny() -> None:
    c = _context()
    v = _unknown()
    a = _decision(v, c)
    b = _decision(v, c)
    assert a == b
    assert a.disposition is NoGrantDownstreamDisposition.BLOCK_BEFORE_M7_M8


def test_p06_context_and_decision_are_immutable() -> None:
    with pytest.raises(FrozenInstanceError):
        _context().expected_request_id = "forged"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        _decision().reason = NoGrantDownstreamReason.CANONICAL_MISMATCH  # type: ignore[misc]


def test_p07_correlation_precedes_canonical_status() -> None:
    positive = build_validated_result()
    context = replace(_context(), expected_request_id="other")
    d = _decision(positive, context)
    assert d.reason is NoGrantDownstreamReason.CORRELATION_MISMATCH
    assert d.validation_id is None


def test_p07_corrupted_claim_policy_is_safe_block() -> None:
    validated = _unknown()
    validated.claim_policy = None  # type: ignore[assignment]
    assert _decision(validated).reason is NoGrantDownstreamReason.CANONICAL_MISMATCH


def test_p07_invalid_origin_enum_and_flag_rejected() -> None:
    with pytest.raises(NoGrantDownstreamError) as origin_error:
        NoGrantDownstreamContext(
            "request-001",
            "execution-001",
            "validation-001",
            "scope-001",
            "session-001",
            "NO_GRANT_INTERNAL",  # type: ignore[arg-type]
        )
    assert origin_error.value.code is NoGrantDownstreamErrorCode.INVALID_CONTEXT_FIELD
    with pytest.raises(NoGrantDownstreamError) as flag_error:
        NoGrantDownstreamContext(
            "request-001",
            "execution-001",
            "validation-001",
            "scope-001",
            "session-001",
            NoGrantOriginClassification.NO_GRANT_INTERNAL,
            structural_only=1,  # type: ignore[arg-type]
        )
    assert flag_error.value.code is NoGrantDownstreamErrorCode.INVALID_CONTEXT_FIELD
