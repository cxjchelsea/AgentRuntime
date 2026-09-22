"""CA-M5-IU6-02 Tool attempt, idempotency, sequence, and finalization gates."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from runtime.contracts.enums import RuntimeControlState
from runtime.contracts.execution import ExecutionContext
from runtime.execution import (
    CapabilityKind,
    CapabilityReferenceSource,
    CoreApprovedToolInvoker,
    ExecutionPermissionContext,
    IdempotencyPreflightDecision,
    IdempotencyPreflightStatus,
    IdempotencyRecord,
    IdempotencyStatus,
    M5ToolResult,
    PermissionDecision,
    PermissionDecisionStatus,
    ResolvedCapability,
    StepAttemptSequenceDecision,
    StepAttemptSequenceStatus,
    StepExecutionStatus,
    StepFinalizationDecision,
    StepFinalizationDisposition,
    StepReliabilityDecision,
    StepReliabilityDisposition,
    ToolAttemptObservation,
    ToolExecutionStatus,
    ToolInvocationBoundaryError,
    ToolInvocationRequest,
    ToolOperationCorrelationDecision,
    ToolOperationCorrelationKey,
    ToolOperationCorrelationStatus,
    ToolOperationOccurrenceDecision,
    ToolOperationOccurrenceStatus,
    ToolPayloadValidationDecision,
    ToolPayloadValidationStatus,
)
from runtime.registries import ToolDefinition


class ValidValidator:
    def validate(self, tool_definition, payload):
        del tool_definition, payload
        return ToolPayloadValidationDecision(
            status=ToolPayloadValidationStatus.VALID,
            reason_codes=("VALID",),
        )


class CountingPermissionProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def build(self, execution_context: ExecutionContext):
        self.calls += 1
        return ExecutionPermissionContext(
            execution_id=execution_context.execution_id,
            identity_scope=execution_context.identity_scope,
            granted_permissions=frozenset({"TOOL_USE"}),
        )


class CountingPermissionEvaluator:
    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, tool_definition, permission_context):
        del tool_definition, permission_context
        self.calls += 1
        return PermissionDecision(
            status=PermissionDecisionStatus.ALLOWED,
            reason_codes=("PERMISSION_ALLOWED",),
        )


class StaticIdentifierFactory:
    def new_tool_call_id(self, *, step_execution_id: str, tool_id: str) -> str:
        return f"{step_execution_id}:{tool_id}:logical-1"

    def new_workflow_instance_id(
        self,
        *,
        step_execution_id: str,
        workflow_id: str,
    ) -> str:
        return f"{step_execution_id}:{workflow_id}:workflow-1"


class SequencedTool:
    def __init__(self, statuses: tuple[ToolExecutionStatus, ...]) -> None:
        self.statuses = list(statuses)
        self.requests: list[ToolInvocationRequest] = []

    async def invoke(self, request, execution_context):
        del execution_context
        self.requests.append(request)
        status = self.statuses.pop(0)
        return M5ToolResult(
            tool_call_id=request.tool_call_id,
            tool_id=request.tool_id,
            status=status,
            attempt=request.attempt,
            data={"attempt": request.attempt}
            if status is ToolExecutionStatus.SUCCESS
            else None,
        )


def _context() -> ExecutionContext:
    return ExecutionContext(
        execution_id="execution-001",
        plan_id="plan-001",
        request_id="request-001",
        session_id="session-001",
        identity_scope="scope-001",
        policy_snapshot={"allowed": True},
        current_state=RuntimeControlState.PROCESSING,
    )


def _invoker(
    tool: SequencedTool,
) -> tuple[
    CoreApprovedToolInvoker,
    CountingPermissionProvider,
    CountingPermissionEvaluator,
]:
    resolved = ResolvedCapability(
        kind=CapabilityKind.TOOL,
        capability_id="DOMAIN_TOOL",
        version="1.0.0",
        definition=ToolDefinition(
            tool_id="DOMAIN_TOOL",
            version="1.0.0",
            required_permissions=["TOOL_USE"],
        ),
        implementation_ref=tool,
        source=CapabilityReferenceSource.APPROVED_TOOL_PLAN,
    )
    provider = CountingPermissionProvider()
    evaluator = CountingPermissionEvaluator()
    return (
        CoreApprovedToolInvoker(
            resolved_tools=(resolved,),
            execution_context=_context(),
            step_execution_id="step-execution-001",
            permission_context_provider=provider,
            permission_evaluator=evaluator,
            input_validator=ValidValidator(),
            output_validator=ValidValidator(),
            identifier_factory=StaticIdentifierFactory(),
        ),
        provider,
        evaluator,
    )


def test_core_physical_attempts_share_one_logical_journal_entry() -> None:
    tool = SequencedTool((ToolExecutionStatus.FAILED, ToolExecutionStatus.SUCCESS))
    invoker, provider, evaluator = _invoker(tool)

    first = asyncio.run(
        invoker.execute_physical_attempt(
            logical_tool_call_id="logical-call-001",
            tool_id="DOMAIN_TOOL",
            input_payload={"value": 1},
            physical_attempt=1,
            idempotency_key="idem-001",
            operation_key="operation-001",
            operation_fingerprint="sha256:abc",
        )
    )
    second = asyncio.run(
        invoker.execute_physical_attempt(
            logical_tool_call_id="logical-call-001",
            tool_id="DOMAIN_TOOL",
            input_payload={"value": 1},
            physical_attempt=2,
            idempotency_key="idem-001",
            operation_key="operation-001",
            operation_fingerprint="sha256:abc",
        )
    )

    assert first.physical_attempt == 1
    assert second.physical_attempt == 2
    assert [request.attempt for request in tool.requests] == [1, 2]
    assert [request.idempotency_key for request in tool.requests] == [
        "idem-001",
        "idem-001",
    ]
    assert provider.calls == 2
    assert evaluator.calls == 2

    entries = invoker.entries()
    assert len(entries) == 1
    assert entries[0].tool_call_id == "logical-call-001"
    assert entries[0].operation_key == "operation-001"
    assert entries[0].idempotency_key == "idem-001"
    assert len(entries[0].attempts) == 2
    assert entries[0].result == second.result
    assert entries[0].result.status is ToolExecutionStatus.SUCCESS


def test_physical_attempt_cannot_start_at_attempt_two() -> None:
    invoker, _, _ = _invoker(SequencedTool((ToolExecutionStatus.SUCCESS,)))

    with pytest.raises(
        ToolInvocationBoundaryError,
        match="first local physical Tool attempt",
    ):
        asyncio.run(
            invoker.execute_physical_attempt(
                logical_tool_call_id="logical-call-001",
                tool_id="DOMAIN_TOOL",
                input_payload={"value": 1},
                physical_attempt=2,
                idempotency_key="idem-001",
                operation_key="operation-001",
                operation_fingerprint="sha256:abc",
            )
        )


def test_physical_attempt_identity_cannot_drift_between_attempts() -> None:
    tool = SequencedTool((ToolExecutionStatus.FAILED, ToolExecutionStatus.SUCCESS))
    invoker, _, _ = _invoker(tool)
    asyncio.run(
        invoker.execute_physical_attempt(
            logical_tool_call_id="logical-call-001",
            tool_id="DOMAIN_TOOL",
            input_payload={"value": 1},
            physical_attempt=1,
            idempotency_key="idem-001",
            operation_key="operation-001",
            operation_fingerprint="sha256:abc",
        )
    )

    with pytest.raises(
        ToolInvocationBoundaryError,
        match="changed logical operation identity",
    ):
        asyncio.run(
            invoker.execute_physical_attempt(
                logical_tool_call_id="logical-call-001",
                tool_id="DOMAIN_TOOL",
                input_payload={"value": 1},
                physical_attempt=2,
                idempotency_key="idem-DIFFERENT",
                operation_key="operation-001",
                operation_fingerprint="sha256:abc",
            )
        )

    assert len(tool.requests) == 1


def test_physical_attempt_fingerprint_cannot_drift_between_attempts() -> None:
    tool = SequencedTool((ToolExecutionStatus.FAILED, ToolExecutionStatus.SUCCESS))
    invoker, _, _ = _invoker(tool)
    asyncio.run(
        invoker.execute_physical_attempt(
            logical_tool_call_id="logical-call-001",
            tool_id="DOMAIN_TOOL",
            input_payload={"value": 1},
            physical_attempt=1,
            idempotency_key="idem-001",
            operation_key="operation-001",
            operation_fingerprint="sha256:abc",
        )
    )

    with pytest.raises(
        ToolInvocationBoundaryError,
        match="changed logical operation identity",
    ):
        asyncio.run(
            invoker.execute_physical_attempt(
                logical_tool_call_id="logical-call-001",
                tool_id="DOMAIN_TOOL",
                input_payload={"value": 2},
                physical_attempt=2,
                idempotency_key="idem-001",
                operation_key="operation-001",
                operation_fingerprint="sha256:DIFFERENT",
            )
        )

    assert len(tool.requests) == 1


def test_identified_correlation_requires_core_occurrence() -> None:
    with pytest.raises(ValueError, match="operation_occurrence"):
        ToolOperationCorrelationDecision(
            status=ToolOperationCorrelationStatus.CORRELATED,
            reason_codes=("MATCHED_PRIOR_OPERATION",),
            operation_key=ToolOperationCorrelationKey("operation-001"),
            logical_tool_call_id="logical-call-001",
        )


def test_identical_calls_can_have_distinct_core_occurrences() -> None:
    first = ToolOperationCorrelationDecision(
        status=ToolOperationCorrelationStatus.NEW,
        reason_codes=("NEW_OPERATION",),
        operation_key=ToolOperationCorrelationKey("operation-001"),
        logical_tool_call_id="logical-call-001",
        operation_occurrence=1,
    )
    second = ToolOperationCorrelationDecision(
        status=ToolOperationCorrelationStatus.NEW,
        reason_codes=("NEW_OPERATION",),
        operation_key=ToolOperationCorrelationKey("operation-002"),
        logical_tool_call_id="logical-call-002",
        operation_occurrence=2,
    )

    assert first.operation_occurrence == 1
    assert second.operation_occurrence == 2
    assert first.operation_key != second.operation_key


def test_tool_attempt_requires_operation_key_and_fingerprint_together() -> None:
    result = M5ToolResult(
        tool_call_id="logical-call-001",
        tool_id="DOMAIN_TOOL",
        status=ToolExecutionStatus.SUCCESS,
        attempt=1,
    )

    with pytest.raises(ValueError, match="present together"):
        ToolAttemptObservation(
            logical_tool_call_id="logical-call-001",
            tool_id="DOMAIN_TOOL",
            tool_version="1.0.0",
            physical_attempt=1,
            result=result,
            operation_key="operation-001",
            operation_fingerprint=None,
        )


def test_domain_facing_invoke_remains_single_attempt_baseline() -> None:
    tool = SequencedTool((ToolExecutionStatus.SUCCESS,))
    invoker, _, _ = _invoker(tool)

    result = asyncio.run(
        invoker.invoke(tool_id="DOMAIN_TOOL", input_payload={"value": 1})
    )

    assert result.attempt == 1
    assert tool.requests[0].idempotency_key is None
    entry = invoker.entries()[0]
    assert len(entry.attempts) == 1
    assert entry.result == result


def _record(
    status: IdempotencyStatus,
    *,
    result_reference: str | None = None,
    tool_call_id: str | None = "logical-call-001",
) -> IdempotencyRecord:
    return IdempotencyRecord(
        key="idem-001",
        execution_id="execution-001",
        step_id="step-001",
        step_execution_id="step-execution-001",
        tool_id="DOMAIN_TOOL",
        tool_version="1.0.0",
        operation_key="operation-001",
        operation_fingerprint="sha256:abc",
        status=status,
        tool_call_id=tool_call_id,
        result_reference=result_reference,
        created_at=datetime(2026, 9, 21, 10, 0, tzinfo=UTC),
    )


def test_idempotency_record_freezes_exact_operation_provenance() -> None:
    record = _record(IdempotencyStatus.RESERVED)

    assert record.step_execution_id == "step-execution-001"
    assert record.tool_id == "DOMAIN_TOOL"
    assert record.tool_version == "1.0.0"
    assert record.operation_key == "operation-001"
    assert record.operation_fingerprint == "sha256:abc"


def test_completed_idempotency_record_requires_recoverable_result_reference() -> None:
    completed = _record(
        IdempotencyStatus.COMPLETED,
        result_reference="result://tool/001",
    )
    assert completed.status is IdempotencyStatus.COMPLETED

    with pytest.raises(ValueError, match="requires tool_call_id/result_reference"):
        _record(IdempotencyStatus.COMPLETED, result_reference=None)


def test_failed_idempotency_record_is_distinct_from_unknown() -> None:
    failed = _record(IdempotencyStatus.FAILED)
    unknown = _record(IdempotencyStatus.UNKNOWN)

    assert failed.status is IdempotencyStatus.FAILED
    assert unknown.status is IdempotencyStatus.UNKNOWN


def test_correlation_requires_core_identity_or_explicit_unknown() -> None:
    correlated = ToolOperationCorrelationDecision(
        status=ToolOperationCorrelationStatus.CORRELATED,
        reason_codes=("MATCHED_PRIOR_OPERATION",),
        operation_key=ToolOperationCorrelationKey("operation-001"),
        logical_tool_call_id="logical-call-001",
        operation_occurrence=1,
    )
    assert correlated.operation_key is not None

    unknown = ToolOperationCorrelationDecision(
        status=ToolOperationCorrelationStatus.UNKNOWN,
        reason_codes=("CORRELATION_UNCERTAIN",),
    )
    assert unknown.operation_key is None

    with pytest.raises(ValueError, match="must not invent identity"):
        ToolOperationCorrelationDecision(
            status=ToolOperationCorrelationStatus.UNKNOWN,
            reason_codes=("CORRELATION_UNCERTAIN",),
            operation_key=ToolOperationCorrelationKey("invented"),
            logical_tool_call_id="invented-call",
            operation_occurrence=1,
        )


def test_idempotency_preflight_requires_status_record_alignment() -> None:
    completed = _record(
        IdempotencyStatus.COMPLETED,
        result_reference="result://tool/001",
    )
    decision = IdempotencyPreflightDecision(
        status=IdempotencyPreflightStatus.RECOVER_COMPLETED,
        reason_codes=("IDEMPOTENCY_COMPLETED",),
        existing_record=completed,
    )
    assert decision.existing_record is completed

    with pytest.raises(ValueError, match="does not match record status"):
        IdempotencyPreflightDecision(
            status=IdempotencyPreflightStatus.REOPEN_FAILED,
            reason_codes=("WRONG_STATUS",),
            existing_record=completed,
        )


def test_reserve_new_preflight_cannot_carry_existing_record() -> None:
    with pytest.raises(ValueError, match="RESERVE_NEW"):
        IdempotencyPreflightDecision(
            status=IdempotencyPreflightStatus.RESERVE_NEW,
            reason_codes=("NEW_OPERATION",),
            existing_record=_record(IdempotencyStatus.RESERVED),
        )


def test_unknown_idempotency_preflight_stays_fail_closed() -> None:
    unknown = _record(IdempotencyStatus.UNKNOWN)
    decision = IdempotencyPreflightDecision(
        status=IdempotencyPreflightStatus.FAIL_UNKNOWN,
        reason_codes=("IDEMPOTENCY_STATE_UNKNOWN",),
        existing_record=unknown,
    )
    assert decision.status is IdempotencyPreflightStatus.FAIL_UNKNOWN


def test_occurrence_authority_decision_never_invents_unknown_occurrence() -> None:
    claimed = ToolOperationOccurrenceDecision(
        status=ToolOperationOccurrenceStatus.CLAIMED,
        reason_codes=("OCCURRENCE_CLAIMED",),
        occurrence=2,
    )
    assert claimed.occurrence == 2

    with pytest.raises(ValueError, match="must not invent occurrence"):
        ToolOperationOccurrenceDecision(
            status=ToolOperationOccurrenceStatus.UNKNOWN,
            reason_codes=("OCCURRENCE_UNKNOWN",),
            occurrence=1,
        )


def test_step_attempt_sequence_claim_must_increment_exactly_once() -> None:
    claimed = StepAttemptSequenceDecision(
        status=StepAttemptSequenceStatus.CLAIMED,
        step_execution_id="step-execution-001",
        expected_current_attempt=1,
        next_attempt=2,
        claim_token="claim-002",
        reason_codes=("ATTEMPT_CLAIMED",),
    )
    assert claimed.next_attempt == 2

    with pytest.raises(ValueError, match="increment by exactly one"):
        StepAttemptSequenceDecision(
            status=StepAttemptSequenceStatus.CLAIMED,
            step_execution_id="step-execution-001",
            expected_current_attempt=1,
            next_attempt=3,
            claim_token="claim-003",
            reason_codes=("ATTEMPT_CLAIMED",),
        )


def test_step_sequence_conflict_does_not_invent_next_attempt() -> None:
    decision = StepAttemptSequenceDecision(
        status=StepAttemptSequenceStatus.CONFLICT,
        step_execution_id="step-execution-001",
        expected_current_attempt=1,
        reason_codes=("ATTEMPT_ALREADY_CLAIMED",),
    )
    assert decision.next_attempt is None
    assert decision.claim_token is None


def test_step_reliability_retry_requires_explicit_next_attempt() -> None:
    decision = StepReliabilityDecision(
        disposition=StepReliabilityDisposition.RETRY,
        reason_codes=("STEP_RETRY_AUTHORIZED",),
        next_attempt=2,
    )
    assert decision.next_attempt == 2

    with pytest.raises(ValueError, match="next_attempt"):
        StepReliabilityDecision(
            disposition=StepReliabilityDisposition.RETRY,
            reason_codes=("STEP_RETRY_AUTHORIZED",),
        )


def test_only_explicit_finalize_decision_can_carry_terminal_status() -> None:
    final = StepFinalizationDecision(
        disposition=StepFinalizationDisposition.FINALIZE,
        reason_codes=("STEP_SUCCESS_FINALIZED",),
        terminal_status=StepExecutionStatus.SUCCESS,
    )
    assert final.terminal_status is StepExecutionStatus.SUCCESS

    with pytest.raises(ValueError, match="non-FINALIZE"):
        StepFinalizationDecision(
            disposition=StepFinalizationDisposition.KEEP_RUNNING,
            reason_codes=("WAITING_FOR_NEXT_ATTEMPT",),
            terminal_status=StepExecutionStatus.SUCCESS,
        )


@pytest.mark.parametrize(
    "status",
    [
        StepExecutionStatus.CANCELLED,
        StepExecutionStatus.PREEMPTED,
    ],
)
def test_iu6_finalization_does_not_claim_control_terminal_status(
    status: StepExecutionStatus,
) -> None:
    with pytest.raises(ValueError, match="allowed terminal"):
        StepFinalizationDecision(
            disposition=StepFinalizationDisposition.FINALIZE,
            reason_codes=("CONTROL_STATUS_REQUIRES_STEP9",),
            terminal_status=status,
        )


def test_finalization_cannot_use_skipped_as_running_attempt_terminal_mapping() -> None:
    with pytest.raises(ValueError, match="allowed terminal"):
        StepFinalizationDecision(
            disposition=StepFinalizationDisposition.FINALIZE,
            reason_codes=("INVALID_MAPPING",),
            terminal_status=StepExecutionStatus.SKIPPED,
        )
