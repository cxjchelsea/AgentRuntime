"""CA-M5-IU7-03 control lifecycle terminalization gates."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from runtime.contracts.execution import ExecutionContext
from runtime.execution.control import (
    ExecutionControlSignal,
    ExecutionControlSignalType,
    LatchedExecutionControl,
)
from runtime.execution.control_application import (
    ExecutionControlApplication,
    ExecutionControlDisposition,
    HierarchicalInterruptStatus,
    HierarchicalInterruptSummary,
    InFlightOperationHandle,
    InFlightOperationKind,
    InterruptOutcome,
    InterruptOutcomeStatus,
)
from runtime.execution.control_lifecycle import (
    ExecutionControlLifecycleError,
    ExecutionControlLifecycleService,
    ExecutionControlLifecycleTransitioner,
)
from runtime.execution.foundation import (
    InMemoryExecutionStateStore,
    PreparedExecution,
    StepLifecycleSnapshot,
)
from runtime.execution.models import ExecutionRecord, StepExecutionStatus
from runtime.execution.recovery import (
    ExecutionRecoveryClaim,
    ExecutionRecoverySnapshotFactory,
)

START = datetime(2026, 9, 22, 14, 0, tzinfo=UTC)
LATCHED = START + timedelta(seconds=5)
TERMINALIZED = START + timedelta(seconds=10)


def _signal(
    signal_type: ExecutionControlSignalType = ExecutionControlSignalType.CANCEL,
    *,
    signal_id: str = "signal-001",
) -> ExecutionControlSignal:
    return ExecutionControlSignal(
        signal_type=signal_type,
        reason_code=(
            "USER_STOP"
            if signal_type is ExecutionControlSignalType.CANCEL
            else "HIGH_PRIORITY_PREEMPTION"
        ),
        source="RUNTIME",
        signal_id=signal_id,
        target_execution_id="execution-001",
        issued_at=START,
    )


def _latched(
    signal_type: ExecutionControlSignalType = ExecutionControlSignalType.CANCEL,
    *,
    signal_id: str = "signal-001",
) -> LatchedExecutionControl:
    return LatchedExecutionControl(
        signal=_signal(signal_type, signal_id=signal_id),
        observed_at=LATCHED,
        latched_at=LATCHED,
    )


def _summary(
    signal_type: ExecutionControlSignalType = ExecutionControlSignalType.CANCEL,
) -> HierarchicalInterruptSummary:
    del signal_type
    owner = InFlightOperationHandle(
        operation_handle_id="owner-001",
        execution_id="execution-001",
        step_execution_id="step-exec-002",
        kind=InFlightOperationKind.SKILL,
        capability_id="skill-002",
        capability_version="1.0.0",
        started_at=START + timedelta(seconds=2),
    )
    return HierarchicalInterruptSummary(
        execution_id="execution-001",
        step_execution_id="step-exec-002",
        status=HierarchicalInterruptStatus.ORDERED,
        handles=(owner,),
        outcomes=(
            InterruptOutcome(
                operation_handle_id="owner-001",
                status=InterruptOutcomeStatus.CONFIRMED_STOPPED,
                reason_codes=("INTERRUPT_CONFIRMED_STOPPED",),
            ),
        ),
        reason_codes=("INTERRUPT_CHAIN_OBSERVED",),
    )


def _prepared() -> PreparedExecution:
    context = ExecutionContext(
        execution_id="execution-001",
        plan_id="plan-001",
        request_id="request-001",
        session_id="session-001",
        identity_scope="subject:001",
        policy_snapshot={"policy": "snapshot"},
        cancellation_token="execution-001",
    )
    completed_at = START + timedelta(seconds=1)
    steps = (
        StepLifecycleSnapshot(
            step_execution_id="step-exec-001",
            step_id="step-001",
            action="already-done",
            status=StepExecutionStatus.SUCCESS,
            skill_id="skill-001",
            tool_call_ids=("tool-call-committed",),
            output={"side_effect": "committed"},
            retry_count=1,
            started_at=START,
            finished_at=completed_at,
        ),
        StepLifecycleSnapshot(
            step_execution_id="step-exec-002",
            step_id="step-002",
            action="running",
            status=StepExecutionStatus.RUNNING,
            skill_id="skill-002",
            tool_call_ids=("tool-call-observed",),
            output={"partial_observation": "keep"},
            retry_count=2,
            started_at=START + timedelta(seconds=2),
        ),
        StepLifecycleSnapshot(
            step_execution_id="step-exec-003",
            step_id="step-003",
            action="pending",
            status=StepExecutionStatus.PENDING,
            skill_id="skill-003",
        ),
    )
    record = ExecutionRecord(
        execution_id="execution-001",
        plan_id="plan-001",
        request_id="request-001",
        identity_scope="subject:001",
        status="RUNNING",
        current_step="step-002",
        step_results=(),
        created_at=START,
        updated_at=START + timedelta(seconds=2),
    )
    return PreparedExecution(
        execution_context=context,
        execution_record=record,
        steps=steps,
        started_at=START,
    )


def _application(
    signal_type: ExecutionControlSignalType = ExecutionControlSignalType.CANCEL,
) -> ExecutionControlApplication:
    return ExecutionControlApplication(
        signal=_signal(signal_type),
        disposition=ExecutionControlDisposition.READY_TO_TERMINALIZE,
        reason_codes=("CONTROL_SAFE_BOUNDARY_CONFIRMED",),
        running_step_id="step-002",
        interrupt_summary=_summary(signal_type),
        nonterminal_step_ids_at_latch=("step-002", "step-003"),
        affected_step_ids=("step-002", "step-003"),
        preserve_running_step_result=False,
        handoff_required=signal_type is ExecutionControlSignalType.PREEMPT,
    )


def test_cancel_terminalizes_only_affected_unfinished_work() -> None:
    prepared = _prepared()
    original_terminal = prepared.steps[0]

    updated = ExecutionControlLifecycleTransitioner().terminalize(
        prepared,
        latched_control=_latched(),
        application=_application(),
        at=TERMINALIZED,
    )

    assert updated.execution_record.status == "CANCELLED"
    assert updated.finished_at == TERMINALIZED
    assert updated.execution_record.current_step is None
    assert updated.steps[0] is original_terminal
    assert updated.steps[0].output == {"side_effect": "committed"}
    assert updated.steps[0].tool_call_ids == ("tool-call-committed",)
    assert updated.steps[1].status is StepExecutionStatus.CANCELLED
    assert updated.steps[1].output == {"partial_observation": "keep"}
    assert updated.steps[1].tool_call_ids == ("tool-call-observed",)
    assert updated.steps[1].retry_count == 2
    assert updated.steps[1].finished_at == TERMINALIZED
    assert updated.steps[2].status is StepExecutionStatus.CANCELLED
    assert updated.steps[2].started_at is None
    assert updated.steps[2].finished_at == TERMINALIZED


def test_preempt_maps_step_and_execution_status_without_starting_new_cycle() -> None:
    updated = ExecutionControlLifecycleTransitioner().terminalize(
        _prepared(),
        latched_control=_latched(ExecutionControlSignalType.PREEMPT),
        application=_application(ExecutionControlSignalType.PREEMPT),
        at=TERMINALIZED,
    )

    assert updated.execution_record.status == "PREEMPTED"
    assert updated.steps[1].status is StepExecutionStatus.PREEMPTED
    assert updated.steps[2].status is StepExecutionStatus.PREEMPTED


def test_pending_only_control_terminalization_does_not_fake_step_start() -> None:
    prepared = _prepared()
    finished_running = replace(
        prepared.steps[1],
        status=StepExecutionStatus.SUCCESS,
        output={"actual": "result"},
        finished_at=START + timedelta(seconds=4),
    )
    current = replace(
        prepared,
        steps=(prepared.steps[0], finished_running, prepared.steps[2]),
        execution_record=replace(
            prepared.execution_record,
            current_step=None,
            updated_at=START + timedelta(seconds=4),
        ),
    )
    application = ExecutionControlApplication(
        signal=_signal(),
        disposition=ExecutionControlDisposition.READY_TO_TERMINALIZE,
        reason_codes=("RUNNING_STEP_COMPLETION_PRESERVED",),
        running_step_id="step-002",
        interrupt_summary=None,
        nonterminal_step_ids_at_latch=("step-002", "step-003"),
        affected_step_ids=("step-003",),
        preserve_running_step_result=True,
        handoff_required=False,
    )

    updated = ExecutionControlLifecycleTransitioner().terminalize(
        current,
        latched_control=_latched(),
        application=application,
        at=TERMINALIZED,
    )

    assert updated.steps[1] is finished_running
    assert updated.steps[1].status is StepExecutionStatus.SUCCESS
    assert updated.steps[1].output == {"actual": "result"}
    assert updated.steps[2].status is StepExecutionStatus.CANCELLED
    assert updated.steps[2].started_at is None
    assert updated.execution_record.status == "CANCELLED"


def test_running_step_requires_confirmed_stopped_owner() -> None:
    application = replace(
        _application(),
        interrupt_summary=replace(
            _summary(),
            outcomes=(
                InterruptOutcome(
                    operation_handle_id="owner-001",
                    status=InterruptOutcomeStatus.NOT_CANCELLABLE,
                    reason_codes=("NOT_CANCELLABLE",),
                ),
            ),
        ),
    )

    with pytest.raises(ExecutionControlLifecycleError, match="CONFIRMED_STOPPED"):
        ExecutionControlLifecycleTransitioner().terminalize(
            _prepared(),
            latched_control=_latched(),
            application=application,
            at=TERMINALIZED,
        )


@pytest.mark.parametrize(
    "disposition",
    [
        ExecutionControlDisposition.WAITING_IN_FLIGHT,
        ExecutionControlDisposition.UNKNOWN,
        ExecutionControlDisposition.CONFLICT,
    ],
)
def test_unsafe_application_cannot_mutate_lifecycle(
    disposition: ExecutionControlDisposition,
) -> None:
    application = ExecutionControlApplication(
        signal=_signal(),
        disposition=disposition,
        reason_codes=("NOT_SAFE_TO_TERMINALIZE",),
        running_step_id="step-002",
        interrupt_summary=None,
        nonterminal_step_ids_at_latch=("step-002", "step-003"),
        affected_step_ids=("step-003",),
        preserve_running_step_result=True,
        handoff_required=False,
    )

    with pytest.raises(ExecutionControlLifecycleError, match="unsafe control"):
        ExecutionControlLifecycleTransitioner().terminalize(
            _prepared(),
            latched_control=_latched(),
            application=application,
            at=TERMINALIZED,
        )


def test_running_interrupt_evidence_must_match_execution() -> None:
    other_owner = InFlightOperationHandle(
        operation_handle_id="owner-other",
        execution_id="execution-other",
        step_execution_id="step-exec-002",
        kind=InFlightOperationKind.SKILL,
        capability_id="skill-002",
        capability_version="1.0.0",
        started_at=START + timedelta(seconds=2),
    )
    other_summary = HierarchicalInterruptSummary(
        execution_id="execution-other",
        step_execution_id="step-exec-002",
        status=HierarchicalInterruptStatus.ORDERED,
        handles=(other_owner,),
        outcomes=(
            InterruptOutcome(
                operation_handle_id="owner-other",
                status=InterruptOutcomeStatus.CONFIRMED_STOPPED,
                reason_codes=("INTERRUPT_CONFIRMED_STOPPED",),
            ),
        ),
        reason_codes=("INTERRUPT_CHAIN_OBSERVED",),
    )
    application = replace(
        _application(),
        interrupt_summary=other_summary,
    )

    with pytest.raises(ExecutionControlLifecycleError, match="match execution"):
        ExecutionControlLifecycleTransitioner().terminalize(
            _prepared(),
            latched_control=_latched(),
            application=application,
            at=TERMINALIZED,
        )


def test_exact_latched_signal_must_match_application_signal() -> None:
    with pytest.raises(ExecutionControlLifecycleError, match="exact latched signal"):
        ExecutionControlLifecycleTransitioner().terminalize(
            _prepared(),
            latched_control=_latched(signal_id="signal-other"),
            application=_application(),
            at=TERMINALIZED,
        )


def test_stale_application_cannot_rewrite_real_terminal_step() -> None:
    prepared = _prepared()
    current = replace(
        prepared,
        steps=(
            prepared.steps[0],
            replace(
                prepared.steps[1],
                status=StepExecutionStatus.SUCCESS,
                output={"actual": "already-completed"},
                finished_at=START + timedelta(seconds=4),
            ),
            prepared.steps[2],
        ),
        execution_record=replace(
            prepared.execution_record,
            current_step=None,
            updated_at=START + timedelta(seconds=4),
        ),
    )

    with pytest.raises(ExecutionControlLifecycleError, match="stale control"):
        ExecutionControlLifecycleTransitioner().terminalize(
            current,
            latched_control=_latched(),
            application=_application(),
            at=TERMINALIZED,
        )


def test_unaffected_nonterminal_step_prevents_execution_terminalization() -> None:
    application = replace(
        _application(),
        affected_step_ids=("step-002",),
    )

    with pytest.raises(ExecutionControlLifecycleError, match="remains non-terminal"):
        ExecutionControlLifecycleTransitioner().terminalize(
            _prepared(),
            latched_control=_latched(),
            application=application,
            at=TERMINALIZED,
        )


def test_already_terminal_claim_rejects_nonterminal_lifecycle() -> None:
    application = ExecutionControlApplication(
        signal=_signal(),
        disposition=ExecutionControlDisposition.ALREADY_TERMINAL,
        reason_codes=("CONTROL_ARRIVED_AFTER_EXECUTION_TERMINAL",),
        nonterminal_step_ids_at_latch=(),
        affected_step_ids=(),
        handoff_required=False,
    )

    with pytest.raises(ExecutionControlLifecycleError, match="all Steps terminal"):
        ExecutionControlLifecycleTransitioner().terminalize(
            _prepared(),
            latched_control=_latched(),
            application=application,
            at=TERMINALIZED,
        )


def test_late_control_already_terminal_is_noop_not_rewrite() -> None:
    prepared = _prepared()
    terminal_steps = tuple(
        replace(
            step,
            status=StepExecutionStatus.SUCCESS,
            finished_at=START + timedelta(seconds=4),
        )
        if step.status in {StepExecutionStatus.RUNNING, StepExecutionStatus.PENDING}
        else step
        for step in prepared.steps
    )
    current = replace(
        prepared,
        steps=terminal_steps,
        execution_record=replace(
            prepared.execution_record,
            current_step=None,
            updated_at=START + timedelta(seconds=4),
        ),
    )
    application = ExecutionControlApplication(
        signal=_signal(),
        disposition=ExecutionControlDisposition.ALREADY_TERMINAL,
        reason_codes=("CONTROL_ARRIVED_AFTER_EXECUTION_TERMINAL",),
        nonterminal_step_ids_at_latch=(),
        affected_step_ids=(),
        handoff_required=False,
    )

    updated = ExecutionControlLifecycleTransitioner().terminalize(
        current,
        latched_control=_latched(),
        application=application,
        at=TERMINALIZED,
    )

    assert updated is current
    assert updated.execution_record.status == "RUNNING"
    assert all(step.status is StepExecutionStatus.SUCCESS for step in updated.steps)


def test_terminalization_time_cannot_precede_latch() -> None:
    with pytest.raises(ExecutionControlLifecycleError, match="control latch"):
        ExecutionControlLifecycleTransitioner().terminalize(
            _prepared(),
            latched_control=_latched(),
            application=_application(),
            at=LATCHED - timedelta(seconds=1),
        )


def test_exact_live_replay_is_idempotent() -> None:
    transitioner = ExecutionControlLifecycleTransitioner()
    first = transitioner.terminalize(
        _prepared(),
        latched_control=_latched(),
        application=_application(),
        at=TERMINALIZED,
    )

    replay = transitioner.terminalize(
        first,
        latched_control=_latched(),
        application=_application(),
        at=TERMINALIZED + timedelta(seconds=1),
    )

    assert replay is first
    assert replay.execution_record.status == "CANCELLED"


def test_terminal_execution_cannot_be_rewritten_by_different_control() -> None:
    transitioner = ExecutionControlLifecycleTransitioner()
    cancelled = transitioner.terminalize(
        _prepared(),
        latched_control=_latched(),
        application=_application(),
        at=TERMINALIZED,
    )

    with pytest.raises(ExecutionControlLifecycleError, match="cannot be rewritten"):
        transitioner.terminalize(
            cancelled,
            latched_control=_latched(
                ExecutionControlSignalType.PREEMPT,
                signal_id="signal-preempt",
            ),
            application=replace(
                _application(ExecutionControlSignalType.PREEMPT),
                signal=_signal(
                    ExecutionControlSignalType.PREEMPT,
                    signal_id="signal-preempt",
                ),
            ),
            at=TERMINALIZED + timedelta(seconds=1),
        )


def test_service_persists_mutation_but_not_late_control_noop() -> None:
    store = InMemoryExecutionStateStore()
    prepared = _prepared()
    asyncio.run(store.create(prepared.execution_record))
    service = ExecutionControlLifecycleService(
        transitioner=ExecutionControlLifecycleTransitioner(),
        execution_store=store,
    )

    updated = asyncio.run(
        service.terminalize(
            prepared,
            latched_control=_latched(),
            application=_application(),
            at=TERMINALIZED,
        )
    )

    stored = asyncio.run(store.load("execution-001"))
    assert stored is not None
    assert stored.status == "CANCELLED"
    assert stored.updated_at == TERMINALIZED

    terminal_steps = tuple(
        replace(
            step,
            status=StepExecutionStatus.SUCCESS,
            finished_at=START + timedelta(seconds=4),
        )
        if step.status in {StepExecutionStatus.RUNNING, StepExecutionStatus.PENDING}
        else step
        for step in prepared.steps
    )
    late = replace(
        prepared,
        steps=terminal_steps,
        execution_record=replace(
            prepared.execution_record,
            current_step=None,
            updated_at=START + timedelta(seconds=4),
        ),
    )
    late_application = ExecutionControlApplication(
        signal=_signal(signal_id="signal-late"),
        disposition=ExecutionControlDisposition.ALREADY_TERMINAL,
        reason_codes=("CONTROL_ARRIVED_AFTER_EXECUTION_TERMINAL",),
        nonterminal_step_ids_at_latch=(),
        affected_step_ids=(),
        handoff_required=False,
    )
    late_result = asyncio.run(
        service.terminalize(
            late,
            latched_control=_latched(signal_id="signal-late"),
            application=late_application,
            at=TERMINALIZED + timedelta(seconds=2),
        )
    )

    assert late_result is late
    stored_after_noop = asyncio.run(store.load("execution-001"))
    assert stored_after_noop == updated.execution_record



def test_control_terminalized_payload_can_be_captured_by_recovery_snapshot() -> None:
    prepared = _prepared()
    updated = ExecutionControlLifecycleTransitioner().terminalize(
        prepared,
        latched_control=_latched(),
        application=_application(),
        at=TERMINALIZED,
    )
    claim = ExecutionRecoveryClaim(
        claim_id="claim-control-terminal",
        execution_id=updated.execution_record.execution_id,
        recovery_owner_id="worker-control-terminal",
        recovery_epoch=1,
        source_snapshot_generation=0,
        claimed_at=TERMINALIZED,
    )

    snapshot = ExecutionRecoverySnapshotFactory().capture(
        updated,
        checkpoint_id="checkpoint-control-terminal",
        generation=1,
        captured_at=TERMINALIZED + timedelta(seconds=1),
        claim=claim,
    )

    restored = snapshot.restore_prepared_execution()
    assert restored.execution_record.status == "CANCELLED"
    assert restored.execution_record.step_results[0]["tool_call_ids"] == [
        "tool-call-committed"
    ]
    assert restored.execution_record.step_results[0]["degraded"] is False
