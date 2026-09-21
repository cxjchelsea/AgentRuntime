"""M5-IU5 result collection and step-attempt observation gates."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from runtime.execution import (
    CapabilityExecutionOwner,
    CapabilityExecutionStatus,
    M5SkillResult,
    M5ToolResult,
    M5WorkflowResult,
    SkillExecutionStatus,
    StepCapabilityExecutionOutcome,
    StepExecutionStatus,
    StepLifecycleSnapshot,
    ToolExecutionStatus,
    ToolInvocationJournalEntry,
    WorkflowExecutionStatus,
)
from runtime.execution.result_collection import (
    StepAttemptObservation,
    StepAttemptStatus,
    StepResultCollectionError,
    StepResultCollector,
)


STARTED_AT = datetime(2026, 9, 21, 9, 0, tzinfo=UTC)
OBSERVED_AT = STARTED_AT + timedelta(seconds=1)


def _snapshot(
    *,
    status: StepExecutionStatus = StepExecutionStatus.RUNNING,
    started_at: datetime | None = STARTED_AT,
) -> StepLifecycleSnapshot:
    return StepLifecycleSnapshot(
        step_execution_id="step-execution-001",
        step_id="step-001",
        action="DOMAIN_ACTION",
        status=status,
        skill_id="DOMAIN_SKILL",
        started_at=started_at,
    )


def _skill_result(
    status: SkillExecutionStatus = SkillExecutionStatus.SUCCESS,
) -> M5SkillResult:
    return M5SkillResult(
        skill_id="DOMAIN_SKILL",
        status=status,
        business_outputs=({"value": 1},),
        events=({"event": "domain-observation"},),
    )


def _workflow_result(
    status: WorkflowExecutionStatus,
) -> M5WorkflowResult:
    return M5WorkflowResult(
        workflow_instance_id="workflow-instance-001",
        workflow_id="DOMAIN_WORKFLOW",
        status=status,
        important_outputs={"workflow": "value"},
    )


def _tool_journal(
    status: ToolExecutionStatus,
    *,
    raw_status: ToolExecutionStatus | None = None,
) -> tuple[ToolInvocationJournalEntry, ...]:
    final = M5ToolResult(
        tool_call_id="tool-call-001",
        tool_id="DOMAIN_TOOL",
        status=status,
    )
    raw = (
        M5ToolResult(
            tool_call_id="tool-call-001",
            tool_id="DOMAIN_TOOL",
            status=raw_status,
        )
        if raw_status is not None
        else None
    )
    return (
        ToolInvocationJournalEntry(
            tool_call_id="tool-call-001",
            tool_id="DOMAIN_TOOL",
            tool_version="1.0.0",
            result=final,
            raw_result=raw,
        ),
    )


def _skill_outcome(
    *,
    execution_status: CapabilityExecutionStatus = CapabilityExecutionStatus.EXECUTED,
    skill_status: SkillExecutionStatus = SkillExecutionStatus.SUCCESS,
    journal: tuple[ToolInvocationJournalEntry, ...] = (),
    reason_codes: tuple[str, ...] = ("SKILL_EXECUTED",),
) -> StepCapabilityExecutionOutcome:
    return StepCapabilityExecutionOutcome(
        step_id="step-001",
        step_execution_id="step-execution-001",
        status=execution_status,
        execution_owner=CapabilityExecutionOwner.SKILL,
        reason_codes=reason_codes,
        owner_capability_id="DOMAIN_SKILL",
        owner_capability_version="1.2.3",
        skill_result=_skill_result(skill_status),
        tool_results=tuple(entry.result for entry in journal),
        tool_journal=journal,
    )


def _workflow_outcome(
    workflow_status: WorkflowExecutionStatus,
    *,
    execution_status: CapabilityExecutionStatus | None = None,
) -> StepCapabilityExecutionOutcome:
    top_level = execution_status or (
        CapabilityExecutionStatus.WAITING
        if workflow_status is WorkflowExecutionStatus.WAITING
        else CapabilityExecutionStatus.EXECUTED
    )
    return StepCapabilityExecutionOutcome(
        step_id="step-001",
        step_execution_id="step-execution-001",
        status=top_level,
        execution_owner=CapabilityExecutionOwner.WORKFLOW,
        reason_codes=("WORKFLOW_OBSERVED",),
        owner_capability_id="DOMAIN_WORKFLOW",
        owner_capability_version="4.5.6",
        workflow_result=_workflow_result(workflow_status),
    )


def _collect(
    outcome: StepCapabilityExecutionOutcome,
    *,
    snapshot: StepLifecycleSnapshot | None = None,
    attempt_number: int = 1,
    observed_at: datetime = OBSERVED_AT,
) -> StepAttemptObservation:
    return StepResultCollector().collect(
        step_snapshot=snapshot or _snapshot(),
        outcome=outcome,
        attempt_number=attempt_number,
        observed_at=observed_at,
    )


@pytest.mark.parametrize(
    ("skill_status", "expected"),
    [
        (SkillExecutionStatus.SUCCESS, StepAttemptStatus.SUCCESS),
        (
            SkillExecutionStatus.PARTIAL_SUCCESS,
            StepAttemptStatus.PARTIAL_SUCCESS,
        ),
        (SkillExecutionStatus.FAILED, StepAttemptStatus.FAILED),
        (SkillExecutionStatus.CANCELLED, StepAttemptStatus.CANCELLED),
        (SkillExecutionStatus.TIMEOUT, StepAttemptStatus.TIMEOUT),
        (SkillExecutionStatus.PREEMPTED, StepAttemptStatus.PREEMPTED),
    ],
)
def test_skill_status_is_classified_without_terminalizing_step(
    skill_status: SkillExecutionStatus,
    expected: StepAttemptStatus,
) -> None:
    observation = _collect(_skill_outcome(skill_status=skill_status))

    assert observation.status is expected
    assert observation.attempt_number == 1
    assert observation.skill_result is not None
    assert observation.business_outputs == ({"value": 1},)
    assert observation.capability_events == ({"event": "domain-observation"},)
    assert observation.reason_codes == ("SKILL_EXECUTED", "RESULT_COLLECTED")


@pytest.mark.parametrize(
    ("workflow_status", "expected"),
    [
        (WorkflowExecutionStatus.COMPLETED, StepAttemptStatus.SUCCESS),
        (WorkflowExecutionStatus.FAILED, StepAttemptStatus.FAILED),
        (WorkflowExecutionStatus.CANCELLED, StepAttemptStatus.CANCELLED),
        (WorkflowExecutionStatus.TIMEOUT, StepAttemptStatus.TIMEOUT),
        (WorkflowExecutionStatus.PREEMPTED, StepAttemptStatus.PREEMPTED),
        (WorkflowExecutionStatus.WAITING, StepAttemptStatus.WAITING),
        (WorkflowExecutionStatus.RUNNING, StepAttemptStatus.IN_PROGRESS),
        (WorkflowExecutionStatus.CREATED, StepAttemptStatus.IN_PROGRESS),
    ],
)
def test_workflow_status_is_classified_losslessly(
    workflow_status: WorkflowExecutionStatus,
    expected: StepAttemptStatus,
) -> None:
    observation = _collect(_workflow_outcome(workflow_status))

    assert observation.status is expected
    assert observation.workflow_result is not None
    assert observation.business_outputs == ({"workflow": "value"},)
    assert observation.capability_events == ()


def test_blocked_stays_blocked_and_preserves_owner_evidence() -> None:
    outcome = _skill_outcome(
        execution_status=CapabilityExecutionStatus.BLOCKED,
        reason_codes=("TOOL_NOT_APPROVED_FOR_STEP",),
    )

    observation = _collect(outcome)

    assert observation.status is StepAttemptStatus.BLOCKED
    assert observation.skill_result is outcome.skill_result
    assert observation.reason_codes == (
        "TOOL_NOT_APPROVED_FOR_STEP",
        "RESULT_COLLECTED",
    )


def test_unknown_stays_unknown_and_preserves_raw_outputs() -> None:
    outcome = _skill_outcome(
        execution_status=CapabilityExecutionStatus.UNKNOWN,
        reason_codes=("SKILL_EXECUTION_EXCEPTION",),
    )

    observation = _collect(outcome)

    assert observation.status is StepAttemptStatus.UNKNOWN
    assert observation.business_outputs == ({"value": 1},)
    assert observation.capability_events == ({"event": "domain-observation"},)


def test_no_external_execution_is_not_success() -> None:
    outcome = StepCapabilityExecutionOutcome(
        step_id="step-001",
        step_execution_id="step-execution-001",
        status=CapabilityExecutionStatus.NO_EXTERNAL_EXECUTION,
        execution_owner=CapabilityExecutionOwner.NONE,
        reason_codes=("NO_EXTERNAL_EXECUTION",),
    )

    observation = _collect(outcome)

    assert observation.status is StepAttemptStatus.NO_EXTERNAL_EXECUTION
    assert observation.business_outputs == ()
    assert observation.tool_results == ()


def test_tool_unknown_is_second_latch_against_executed_owner_success() -> None:
    journal = _tool_journal(ToolExecutionStatus.UNKNOWN)
    outcome = _skill_outcome(journal=journal)

    observation = _collect(outcome)

    assert observation.status is StepAttemptStatus.UNKNOWN
    assert observation.reason_codes == (
        "SKILL_EXECUTED",
        "TOOL_UNKNOWN_NOT_PROPAGATED",
        "RESULT_COLLECTED",
    )
    assert observation.has_unknown_tool_observation is True
    assert observation.has_non_success_tool_observation is True
    assert observation.tool_journal is journal


def test_failed_tool_does_not_override_skill_success() -> None:
    journal = _tool_journal(ToolExecutionStatus.FAILED)
    outcome = _skill_outcome(journal=journal)

    observation = _collect(outcome)

    assert observation.status is StepAttemptStatus.SUCCESS
    assert observation.has_non_success_tool_observation is True
    assert observation.has_unknown_tool_observation is False
    assert observation.tool_results[0].status is ToolExecutionStatus.FAILED


def test_raw_success_final_unknown_sets_untrusted_success_evidence() -> None:
    journal = _tool_journal(
        ToolExecutionStatus.UNKNOWN,
        raw_status=ToolExecutionStatus.SUCCESS,
    )
    outcome = _skill_outcome(
        execution_status=CapabilityExecutionStatus.UNKNOWN,
        journal=journal,
        reason_codes=("TOOL_INVALID_OUTPUT",),
    )

    observation = _collect(outcome)

    assert observation.status is StepAttemptStatus.UNKNOWN
    assert observation.has_untrusted_success_observation is True
    assert observation.tool_journal[0].raw_result is not None
    assert (
        observation.tool_journal[0].raw_result.status
        is ToolExecutionStatus.SUCCESS
    )


def test_owner_result_inconsistency_becomes_unknown_not_structural_error() -> None:
    outcome = StepCapabilityExecutionOutcome(
        step_id="step-001",
        step_execution_id="step-execution-001",
        status=CapabilityExecutionStatus.EXECUTED,
        execution_owner=CapabilityExecutionOwner.SKILL,
        reason_codes=("OWNER_RETURNED",),
        owner_capability_id="DOMAIN_SKILL",
        owner_capability_version="1.2.3",
    )

    observation = _collect(outcome)

    assert observation.status is StepAttemptStatus.UNKNOWN
    assert observation.reason_codes == (
        "OWNER_RETURNED",
        "RESULT_COLLECTION_OWNER_RESULT_INCONSISTENT",
        "RESULT_COLLECTED",
    )


def test_workflow_waiting_cannot_hide_behind_executed_top_level() -> None:
    outcome = _workflow_outcome(
        WorkflowExecutionStatus.WAITING,
        execution_status=CapabilityExecutionStatus.EXECUTED,
    )

    observation = _collect(outcome)

    assert observation.status is StepAttemptStatus.UNKNOWN
    assert "RESULT_COLLECTION_OWNER_RESULT_INCONSISTENT" in (
        observation.reason_codes
    )


@pytest.mark.parametrize(
    ("snapshot", "reason"),
    [
        (
            _snapshot(status=StepExecutionStatus.PENDING),
            "RESULT_COLLECTION_STEP_NOT_RUNNING",
        ),
        (
            _snapshot(started_at=None),
            "RESULT_COLLECTION_START_TIME_MISSING",
        ),
    ],
)
def test_invalid_snapshot_is_structural_collection_error(
    snapshot: StepLifecycleSnapshot,
    reason: str,
) -> None:
    with pytest.raises(StepResultCollectionError) as exc_info:
        _collect(_skill_outcome(), snapshot=snapshot)

    assert exc_info.value.reason_code == reason


def test_step_identity_mismatch_is_structural_collection_error() -> None:
    outcome = _skill_outcome()
    wrong_snapshot = StepLifecycleSnapshot(
        step_execution_id="other-execution",
        step_id="step-001",
        action="DOMAIN_ACTION",
        status=StepExecutionStatus.RUNNING,
        started_at=STARTED_AT,
    )

    with pytest.raises(StepResultCollectionError) as exc_info:
        _collect(outcome, snapshot=wrong_snapshot)

    assert exc_info.value.reason_code == "RESULT_COLLECTION_IDENTITY_MISMATCH"


def test_attempt_number_must_be_positive() -> None:
    with pytest.raises(StepResultCollectionError) as exc_info:
        _collect(_skill_outcome(), attempt_number=0)

    assert exc_info.value.reason_code == "RESULT_COLLECTION_ATTEMPT_INVALID"


def test_observation_cannot_precede_step_start() -> None:
    with pytest.raises(StepResultCollectionError) as exc_info:
        _collect(
            _skill_outcome(),
            observed_at=STARTED_AT - timedelta(microseconds=1),
        )

    assert exc_info.value.reason_code == "RESULT_COLLECTION_TIME_INVALID"


def test_incomparable_timestamps_are_structural_collection_error() -> None:
    with pytest.raises(StepResultCollectionError) as exc_info:
        _collect(
            _skill_outcome(),
            observed_at=datetime(2026, 9, 21, 9, 0),
        )

    assert exc_info.value.reason_code == "RESULT_COLLECTION_TIME_INVALID"


def test_reason_codes_preserve_upstream_order_duplicates_and_collector_code() -> None:
    outcome = _skill_outcome(
        reason_codes=("FIRST", "FIRST", "RESULT_COLLECTED", "SECOND"),
    )

    observation = _collect(outcome)

    assert observation.reason_codes == (
        "FIRST",
        "FIRST",
        "RESULT_COLLECTED",
        "SECOND",
    )


def test_core_supplied_attempt_number_is_preserved() -> None:
    observation = _collect(_skill_outcome(), attempt_number=2)

    assert observation.attempt_number == 2


def test_collection_does_not_mutate_running_step_lifecycle() -> None:
    snapshot = _snapshot()
    before = snapshot

    observation = _collect(_skill_outcome(), snapshot=snapshot)

    assert observation.status is StepAttemptStatus.SUCCESS
    assert snapshot == before
    assert snapshot.status is StepExecutionStatus.RUNNING
    assert snapshot.finished_at is None


def test_attempt_observation_flags_must_match_preserved_tool_truth() -> None:
    journal = _tool_journal(ToolExecutionStatus.FAILED)
    with pytest.raises(ValueError, match="non-success Tool evidence"):
        StepAttemptObservation(
            step_id="step-001",
            step_execution_id="step-execution-001",
            attempt_number=1,
            status=StepAttemptStatus.SUCCESS,
            execution_owner=CapabilityExecutionOwner.SKILL,
            reason_codes=("TEST",),
            observed_at=OBSERVED_AT,
            owner_capability_id="DOMAIN_SKILL",
            owner_capability_version="1.2.3",
            skill_result=_skill_result(),
            tool_results=tuple(entry.result for entry in journal),
            tool_journal=journal,
            has_non_success_tool_observation=False,
        )
