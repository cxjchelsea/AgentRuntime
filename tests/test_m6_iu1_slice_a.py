"""Slice A pure boundary tests; no business-success or M2 grant assumptions."""
from runtime.contracts.execution import StepExecutionResult
from runtime.validation.slice_a import AdmissionReason, AdmissionStatus, admit_validation_input
from tests.orchestration_stubs import (
    build_approved_action_plan,
    build_execution_result,
    build_runtime_context,
)


def _inputs():
    return build_execution_result(), build_runtime_context(), build_approved_action_plan()


def test_healthy_admission_deterministic_and_no_success_promotion():
    execution, context, approved = _inputs()
    first = admit_validation_input(execution, context, approved)
    second = admit_validation_input(execution, context, approved)
    assert first == second
    assert first.status is AdmissionStatus.ADMITTED
    assert first.reasons == ()
    assert first.envelope is not None
    assert first.envelope.rule_binding_status == "UNRESOLVED"
    assert not hasattr(first.envelope, "verified_facts")


def test_plan_request_and_scope_mismatch_fail_closed():
    execution, context, approved = _inputs()
    execution.plan_id = "other"
    execution.request_id = "other"
    execution.identity_scope = "wrong"
    result = admit_validation_input(execution, context, approved)
    assert result.status is AdmissionStatus.REJECTED
    assert result.envelope is None
    assert set(result.reasons) == {
        AdmissionReason.REQUEST_MISMATCH,
        AdmissionReason.PLAN_MISMATCH,
        AdmissionReason.IDENTITY_SCOPE_MISMATCH,
    }


def test_trusted_session_expectation_is_never_guessed():
    execution, context, approved = _inputs()
    result = admit_validation_input(execution, context, approved, expected_session_id="another")
    assert result.status is AdmissionStatus.REJECTED
    assert AdmissionReason.SESSION_MISMATCH in result.reasons


def test_unknown_and_duplicate_steps_fail_closed():
    execution, context, approved = _inputs()
    execution.step_results = [
        StepExecutionResult(step_id="unknown", tool_call_ids=["call-1"]),
        StepExecutionResult(step_id="unknown", tool_call_ids=["call-1"]),
    ]
    result = admit_validation_input(execution, context, approved)
    assert result.envelope is None
    assert AdmissionReason.UNKNOWN_EXECUTION_STEP in result.reasons
    assert AdmissionReason.DUPLICATE_EXECUTION_STEP in result.reasons
    assert AdmissionReason.DUPLICATE_TOOL_CALL in result.reasons


def test_step_reference_keeps_unobserved_time_absent_and_inputs_unchanged():
    execution, context, approved = _inputs()
    execution.step_results = [
        StepExecutionResult(step_id="step-001", tool_call_ids=["call-1"])
    ]
    before = execution.model_dump(mode="json")
    result = admit_validation_input(execution, context, approved)
    assert result.envelope is not None
    assert [x.source_path for x in result.envelope.evidence_refs] == [
        "step_results[0]", "step_results[0].tool_call_ids[0]"
    ]
    assert all(x.observed_at is None for x in result.envelope.evidence_refs)
    assert execution.model_dump(mode="json") == before


def test_duplicate_approved_step_ids_rejected():
    execution, context, approved = _inputs()
    approved.steps.append(approved.steps[0].model_copy(deep=True))
    result = admit_validation_input(execution, context, approved)
    assert result.status is AdmissionStatus.REJECTED
    assert AdmissionReason.DUPLICATE_PLAN_STEP in result.reasons
