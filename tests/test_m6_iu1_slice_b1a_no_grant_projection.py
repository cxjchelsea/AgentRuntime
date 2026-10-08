"""Independent negative-contract tests for the B1a structural projector."""

from collections.abc import Callable

import pytest

from runtime.contracts import BusinessStatus, ValidationStatus
from runtime.contracts.validation import ValidatedResult
from runtime.validation.no_grant import NoGrant, NoGrantReason, NoGrantTurnSlot
from runtime.validation.no_grant_projection import (
    NoGrantProjectionController,
    NoGrantProjectionError,
    NoGrantProjectionReason,
    ValidationOriginBinding,
)
from runtime.validation.slice_a import (
    AdmissionStatus,
    ValidationAdmissionDecision,
    admit_validation_input,
)
from tests.orchestration_stubs import (
    build_approved_action_plan,
    build_execution_result,
    build_policy_decision,
    build_runtime_context,
)


def _case() -> dict[str, object]:
    execution = build_execution_result()
    approved = build_approved_action_plan()
    approved.policy_snapshot = build_policy_decision().model_dump(mode="json")
    context = build_runtime_context()
    origin = ValidationOriginBinding(
        expected_request_id="request-001",
        expected_session_id="session-001",
        expected_identity_scope="scope-001",
    )
    admission = admit_validation_input(
        execution,
        context,
        approved,
        expected_request_id=origin.expected_request_id,
        expected_session_id=origin.expected_session_id,
    )
    assert admission.status is AdmissionStatus.ADMITTED
    return {
        "admission": admission,
        "execution": execution,
        "approved": approved,
        "context": context,
        "origin": origin,
        "no_grant": NoGrant(NoGrantReason.NO_AUTHORIZED_POLICY_EVIDENCE),
    }


def _reject(
    reason: NoGrantProjectionReason, args: dict[str, object],
    *, controller: NoGrantProjectionController | None = None,
) -> None:
    with pytest.raises(NoGrantProjectionError) as error:
        (controller or NoGrantProjectionController()).project(**args)  # type: ignore[arg-type]
    assert error.value.reason is reason


def test_valid_projection_never_promotes_execution_success() -> None:
    result = NoGrantProjectionController().project(**_case())  # type: ignore[arg-type]
    assert isinstance(result, ValidatedResult)
    assert result.validation_status is ValidationStatus.UNKNOWN
    assert result.business_status is BusinessStatus.UNKNOWN
    assert result.claim_policy.allowed_claims == []
    assert result.claim_policy.conditional_claims == []
    assert result.verified_facts is None
    assert result.goal_validation is None
    assert result.state_recommendation is None
    assert result.validation_errors == [
        {"code": "GRANT_MISSING", "reason": "NO_AUTHORIZED_POLICY_EVIDENCE"}
    ]
    assert ValidatedResult.model_validate(result.model_dump(mode="json")) == result


def test_rejected_admission_precedes_allocator() -> None:
    args = _case()
    args["admission"] = ValidationAdmissionDecision(
        AdmissionStatus.REJECTED, (), None
    ) if False else ValidationAdmissionDecision(
        AdmissionStatus.REJECTED,
        ( __import__("runtime.validation.slice_a", fromlist=["AdmissionReason"]).AdmissionReason.REQUEST_MISMATCH,),
        None,
    )
    invoked = 0

    def allocator() -> str:
        nonlocal invoked
        invoked += 1
        return "never"

    _reject(
        NoGrantProjectionReason.ADMISSION_REJECTED, args,
        controller=NoGrantProjectionController(id_allocator=allocator),
    )
    assert invoked == 0


@pytest.mark.parametrize("field,reason", [
    ("admission", NoGrantProjectionReason.INVALID_INPUT),
    ("execution", NoGrantProjectionReason.INVALID_INPUT),
    ("approved", NoGrantProjectionReason.INVALID_INPUT),
    ("context", NoGrantProjectionReason.INVALID_INPUT),
    ("origin", NoGrantProjectionReason.ORIGIN_INVALID),
    ("no_grant", NoGrantProjectionReason.NO_GRANT_INVALID),
])
def test_bad_input_types_fail_typed(field: str, reason: NoGrantProjectionReason) -> None:
    args = _case()
    args[field] = None
    _reject(reason, args)


@pytest.mark.parametrize("field", ["expected_request_id", "expected_session_id", "expected_identity_scope"])
def test_mismatching_origins_fail_before_allocation(field: str) -> None:
    args = _case()
    values = {
        "expected_request_id": "request-001",
        "expected_session_id": "session-001",
        "expected_identity_scope": "scope-001",
    }
    values[field] = "other"
    args["origin"] = ValidationOriginBinding(**values)
    _reject(NoGrantProjectionReason.IDENTITY_MISMATCH, args)


def test_stale_source_fails_closed() -> None:
    args = _case()
    execution = args["execution"]
    execution.execution_events = [{"unexpected": True}]  # type: ignore[union-attr]
    _reject(NoGrantProjectionReason.SOURCE_CHANGED, args)


def test_resolved_binding_cannot_claim_authority() -> None:
    from dataclasses import replace

    args = _case()
    admission = args["admission"]
    args["admission"] = replace(
        admission, envelope=replace(admission.envelope, rule_binding_status="RESOLVED")  # type: ignore[union-attr]
    )
    _reject(NoGrantProjectionReason.ADMISSION_INVALID, args)


def test_directly_constructed_no_grant_remains_nonaffirmative() -> None:
    args = _case()
    args["no_grant"] = NoGrant(NoGrantReason.UNTRUSTED_RECEIPT)
    result = NoGrantProjectionController().project(**args)  # type: ignore[arg-type]
    assert result.business_status is BusinessStatus.UNKNOWN
    assert result.validation_errors == [{"code": "GRANT_MISSING", "reason": "UNTRUSTED_RECEIPT"}]


def test_b0_slot_is_not_considered_authority_certificate() -> None:
    args = _case()
    with NoGrantTurnSlot(NoGrantReason.AUTHORITY_UNAVAILABLE) as slot:
        args["no_grant"] = slot.take_once()
    result = NoGrantProjectionController().project(**args)  # type: ignore[arg-type]
    assert result.validation_status is ValidationStatus.UNKNOWN


def test_controller_local_duplicate_id_rejected() -> None:
    ctl = NoGrantProjectionController(id_allocator=lambda: "same-id")
    first = ctl.project(**_case())  # type: ignore[arg-type]
    _reject(NoGrantProjectionReason.VALIDATION_ID_COLLISION, _case(), controller=ctl)
    assert first.validation_id == "same-id"


def test_distinct_invocations_get_distinct_ids() -> None:
    values = iter(["id-one", "id-two"])
    ctl = NoGrantProjectionController(id_allocator=lambda: next(values))
    a = ctl.project(**_case())  # type: ignore[arg-type]
    b = ctl.project(**_case())  # type: ignore[arg-type]
    assert a.validation_id != b.validation_id
    assert a.business_status is b.business_status is BusinessStatus.UNKNOWN


@pytest.mark.parametrize("value", ["", " ", 17])
def test_bad_allocator_value_is_typed(value: object) -> None:
    ctl = NoGrantProjectionController(id_allocator=lambda: value)  # type: ignore[arg-type]
    _reject(NoGrantProjectionReason.VALIDATION_ID_INVALID, _case(), controller=ctl)


def test_allocator_error_is_typed() -> None:
    def fail() -> str:
        raise RuntimeError("allocation unavailable")
    _reject(
        NoGrantProjectionReason.VALIDATION_ID_INVALID, _case(),
        controller=NoGrantProjectionController(id_allocator=fail),
    )


def test_invalid_origin_rejected_on_construction() -> None:
    with pytest.raises(NoGrantProjectionError) as error:
        ValidationOriginBinding(" ", "session-001", "scope-001")
    assert error.value.reason is NoGrantProjectionReason.ORIGIN_INVALID


def test_no_external_effects_or_positive_issuance_api() -> None:
    ctl = NoGrantProjectionController()
    for name in ("issue_grant", "execute", "persist", "update", "run", "resolve_profile"):
        assert not hasattr(ctl, name)
