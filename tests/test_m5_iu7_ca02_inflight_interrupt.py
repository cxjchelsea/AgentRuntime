"""CA-M5-IU7-02 in-flight interrupt and control-application gates."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

import pytest

from runtime.contracts.execution import ExecutionContext
from runtime.execution import (
    ExecutionControlApplication,
    ExecutionControlApplicationEvaluator,
    ExecutionControlDisposition,
    ExecutionControlSignal,
    ExecutionControlSignalType,
    HierarchicalInterruptStatus,
    HierarchicalInterruptSummary,
    InFlightInterruptCoordinator,
    InFlightOperationHandle,
    InFlightOperationKind,
    InMemoryInFlightOperationRegistry,
    InterruptOutcome,
    InterruptOutcomeStatus,
    LatchedExecutionControl,
    PreparedExecution,
    StepExecutionStatus,
    StepLifecycleSnapshot,
)
from runtime.execution.models import ExecutionRecord

FIXED_TIME = datetime(2026, 9, 22, 14, 0, tzinfo=UTC)


def _signal(
    signal_type: ExecutionControlSignalType = ExecutionControlSignalType.CANCEL,
) -> ExecutionControlSignal:
    return ExecutionControlSignal(
        signal_type=signal_type,
        reason_code=(
            "USER_STOP"
            if signal_type is ExecutionControlSignalType.CANCEL
            else "HIGH_PRIORITY_PREEMPTION"
        ),
        source="RUNTIME",
        signal_id="signal-001",
        target_execution_id="execution-001",
        issued_at=FIXED_TIME,
    )


def _latched(
    signal_type: ExecutionControlSignalType = ExecutionControlSignalType.CANCEL,
) -> LatchedExecutionControl:
    return LatchedExecutionControl(
        signal=_signal(signal_type),
        observed_at=FIXED_TIME,
        latched_at=FIXED_TIME,
    )


def _owner_handle() -> InFlightOperationHandle:
    return InFlightOperationHandle(
        operation_handle_id="owner-001",
        execution_id="execution-001",
        step_execution_id="step-exec-001",
        kind=InFlightOperationKind.SKILL,
        capability_id="skill-001",
        capability_version="1.0.0",
        started_at=FIXED_TIME,
    )


def _tool_handle(
    *,
    handle_id: str = "tool-001",
    tool_call_id: str = "call-001",
) -> InFlightOperationHandle:
    return InFlightOperationHandle(
        operation_handle_id=handle_id,
        execution_id="execution-001",
        step_execution_id="step-exec-001",
        kind=InFlightOperationKind.TOOL,
        capability_id="tool-001",
        capability_version="1.0.0",
        started_at=FIXED_TIME,
        parent_handle_id="owner-001",
        tool_call_id=tool_call_id,
    )


def _prepared(
    *,
    running_status: StepExecutionStatus = StepExecutionStatus.RUNNING,
    include_pending: bool = True,
    running_output: dict[str, str] | None = None,
) -> PreparedExecution:
    context = ExecutionContext(
        execution_id="execution-001",
        plan_id="plan-001",
        request_id="request-001",
        session_id="session-001",
        identity_scope="subject:001",
        policy_snapshot={"policy": "snapshot"},
        cancellation_token="execution-001",
    )
    record = ExecutionRecord(
        execution_id="execution-001",
        plan_id="plan-001",
        request_id="request-001",
        identity_scope="subject:001",
        status="RUNNING",
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )
    steps = [
        StepLifecycleSnapshot(
            step_execution_id="step-exec-001",
            step_id="step-001",
            action="action-001",
            status=running_status,
            skill_id="skill-001",
            output=running_output,
            started_at=FIXED_TIME,
            finished_at=(
                FIXED_TIME
                if running_status is not StepExecutionStatus.RUNNING
                else None
            ),
        )
    ]
    if include_pending:
        steps.append(
            StepLifecycleSnapshot(
                step_execution_id="step-exec-002",
                step_id="step-002",
                action="action-002",
                status=StepExecutionStatus.PENDING,
            )
        )
    return PreparedExecution(
        execution_context=context,
        execution_record=record,
        steps=tuple(steps),
        started_at=FIXED_TIME,
    )


class _Controller:
    def __init__(self, outcomes: dict[str, InterruptOutcomeStatus]) -> None:
        self._outcomes = outcomes
        self.calls: list[str] = []

    async def interrupt(
        self,
        *,
        handle: InFlightOperationHandle,
        signal: ExecutionControlSignal,
    ) -> InterruptOutcome:
        assert signal.target_execution_id == handle.execution_id
        self.calls.append(handle.operation_handle_id)
        status = self._outcomes[handle.operation_handle_id]
        return InterruptOutcome(
            operation_handle_id=handle.operation_handle_id,
            status=status,
            reason_codes=(f"INTERRUPT_{status.value}",),
        )


def _summary(
    outcome: InterruptOutcomeStatus,
) -> tuple[
    InMemoryInFlightOperationRegistry, _Controller, HierarchicalInterruptSummary
]:
    registry = InMemoryInFlightOperationRegistry()
    asyncio.run(registry.register(_owner_handle()))
    controller = _Controller({"owner-001": outcome})
    summary = asyncio.run(
        InFlightInterruptCoordinator(
            registry=registry,
            interrupt_controller=controller,
        ).interrupt(
            execution_id="execution-001",
            step_execution_id="step-exec-001",
            signal=_signal(),
        )
    )
    return registry, controller, summary


def test_nested_tool_interrupt_is_leaf_first_then_owner() -> None:
    registry = InMemoryInFlightOperationRegistry()
    asyncio.run(registry.register(_owner_handle()))
    asyncio.run(registry.register(_tool_handle()))
    controller = _Controller(
        {
            "tool-001": InterruptOutcomeStatus.CONFIRMED_STOPPED,
            "owner-001": InterruptOutcomeStatus.CONFIRMED_STOPPED,
        }
    )
    summary = asyncio.run(
        InFlightInterruptCoordinator(
            registry=registry,
            interrupt_controller=controller,
        ).interrupt(
            execution_id="execution-001",
            step_execution_id="step-exec-001",
            signal=_signal(),
        )
    )

    assert summary.status is HierarchicalInterruptStatus.ORDERED
    assert controller.calls == ["tool-001", "owner-001"]
    assert tuple(item.operation_handle_id for item in summary.handles) == (
        "tool-001",
        "owner-001",
    )


def test_multiple_active_leaves_fail_closed_without_interrupt() -> None:
    registry = InMemoryInFlightOperationRegistry()
    asyncio.run(registry.register(_owner_handle()))
    asyncio.run(registry.register(_tool_handle()))
    asyncio.run(
        registry.register(_tool_handle(handle_id="tool-002", tool_call_id="call-002"))
    )
    controller = _Controller({})
    summary = asyncio.run(
        InFlightInterruptCoordinator(
            registry=registry,
            interrupt_controller=controller,
        ).interrupt(
            execution_id="execution-001",
            step_execution_id="step-exec-001",
            signal=_signal(),
        )
    )

    assert summary.status is HierarchicalInterruptStatus.AMBIGUOUS
    assert summary.reason_codes == ("AMBIGUOUS_INFLIGHT_GRAPH",)
    assert controller.calls == []


def test_wrong_target_control_does_not_request_interrupt() -> None:
    registry = InMemoryInFlightOperationRegistry()
    asyncio.run(registry.register(_owner_handle()))
    controller = _Controller({})
    wrong_target = replace(_signal(), target_execution_id="execution-other")

    summary = asyncio.run(
        InFlightInterruptCoordinator(
            registry=registry,
            interrupt_controller=controller,
        ).interrupt(
            execution_id="execution-001",
            step_execution_id="step-exec-001",
            signal=wrong_target,
        )
    )

    assert summary.status is HierarchicalInterruptStatus.UNKNOWN
    assert summary.reason_codes == ("CONTROL_SIGNAL_TARGET_MISMATCH",)
    assert controller.calls == []


def test_in_memory_registry_is_live_only_and_identity_safe() -> None:
    registry = InMemoryInFlightOperationRegistry()
    owner = _owner_handle()

    assert asyncio.run(registry.register(owner)) is True
    assert asyncio.run(registry.register(owner)) is False
    assert asyncio.run(
        registry.active_chain(
            execution_id="execution-001",
            step_execution_id="step-exec-001",
        )
    ) == (owner,)
    assert asyncio.run(
        registry.complete(
            owner.operation_handle_id,
            completed_at=FIXED_TIME,
        )
    )
    assert (
        asyncio.run(
            registry.active_chain(
                execution_id="execution-001",
                step_execution_id="step-exec-001",
            )
        )
        == ()
    )


def test_handle_rejects_unparented_tool_and_naive_time() -> None:
    with pytest.raises(ValueError, match="parent_handle_id"):
        InFlightOperationHandle(
            operation_handle_id="tool-001",
            execution_id="execution-001",
            step_execution_id="step-exec-001",
            kind=InFlightOperationKind.TOOL,
            capability_id="tool-001",
            capability_version="1.0.0",
            started_at=FIXED_TIME,
            tool_call_id="call-001",
        )

    with pytest.raises(ValueError, match="timezone-aware"):
        InFlightOperationHandle(
            operation_handle_id="owner-001",
            execution_id="execution-001",
            step_execution_id="step-exec-001",
            kind=InFlightOperationKind.SKILL,
            capability_id="skill-001",
            capability_version="1.0.0",
            started_at=datetime(2026, 9, 22, 14, 0),  # noqa: DTZ001
        )


def test_confirmed_stop_is_only_path_that_marks_running_step_affected() -> None:
    _, _, summary = _summary(InterruptOutcomeStatus.CONFIRMED_STOPPED)

    application = ExecutionControlApplicationEvaluator().evaluate(
        latched_control=_latched(),
        prepared_at_latch=_prepared(),
        interrupt_summary=summary,
    )

    assert application.disposition is ExecutionControlDisposition.READY_TO_TERMINALIZE
    assert application.affected_step_ids == ("step-001", "step-002")
    assert application.preserve_running_step_result is False


def test_not_cancellable_keeps_barrier_and_waits() -> None:
    _, _, summary = _summary(InterruptOutcomeStatus.NOT_CANCELLABLE)

    application = ExecutionControlApplicationEvaluator().evaluate(
        latched_control=_latched(),
        prepared_at_latch=_prepared(),
        interrupt_summary=summary,
    )

    assert application.disposition is ExecutionControlDisposition.WAITING_IN_FLIGHT
    assert application.affected_step_ids == ("step-002",)
    assert application.preserve_running_step_result is True


def test_unknown_interrupt_never_becomes_terminal_authority() -> None:
    _, _, summary = _summary(InterruptOutcomeStatus.UNKNOWN)

    application = ExecutionControlApplicationEvaluator().evaluate(
        latched_control=_latched(),
        prepared_at_latch=_prepared(),
        interrupt_summary=summary,
    )

    assert application.disposition is ExecutionControlDisposition.UNKNOWN
    assert "step-001" not in application.affected_step_ids
    assert application.preserve_running_step_result is True


def test_already_completed_waits_until_real_lifecycle_commit() -> None:
    _, _, summary = _summary(InterruptOutcomeStatus.ALREADY_COMPLETED)

    application = ExecutionControlApplicationEvaluator().evaluate(
        latched_control=_latched(),
        prepared_at_latch=_prepared(),
        interrupt_summary=summary,
    )

    assert application.disposition is ExecutionControlDisposition.WAITING_IN_FLIGHT
    assert application.reason_codes == ("OWNER_COMPLETED_AWAITING_LIFECYCLE_COMMIT",)
    assert application.preserve_running_step_result is True


def test_already_completed_after_lifecycle_commit_preserves_real_result() -> None:
    _, _, summary = _summary(InterruptOutcomeStatus.ALREADY_COMPLETED)
    before = _prepared(include_pending=False)
    committed = _prepared(
        running_status=StepExecutionStatus.SUCCESS,
        include_pending=False,
        running_output={"side_effect": "already_happened"},
    )

    application = ExecutionControlApplicationEvaluator().evaluate(
        latched_control=_latched(),
        prepared_at_latch=before,
        interrupt_summary=summary,
        prepared_after_interrupt=committed,
    )

    assert application.disposition is ExecutionControlDisposition.ALREADY_TERMINAL
    assert application.affected_step_ids == ()
    assert application.preserve_running_step_result is True
    assert committed.steps[0].status is StepExecutionStatus.SUCCESS
    assert committed.steps[0].output == {"side_effect": "already_happened"}


def test_completed_running_step_with_pending_work_only_affects_pending() -> None:
    _, _, summary = _summary(InterruptOutcomeStatus.ALREADY_COMPLETED)
    before = _prepared()
    committed = _prepared(
        running_status=StepExecutionStatus.SUCCESS,
        running_output={"result": "preserve"},
    )

    application = ExecutionControlApplicationEvaluator().evaluate(
        latched_control=_latched(),
        prepared_at_latch=before,
        interrupt_summary=summary,
        prepared_after_interrupt=committed,
    )

    assert application.disposition is ExecutionControlDisposition.READY_TO_TERMINALIZE
    assert application.affected_step_ids == ("step-002",)
    assert application.preserve_running_step_result is True


def test_all_terminal_at_latch_is_late_control_no_rewrite() -> None:
    terminal = _prepared(
        running_status=StepExecutionStatus.SUCCESS,
        include_pending=False,
        running_output={"truth": "keep"},
    )

    application = ExecutionControlApplicationEvaluator().evaluate(
        latched_control=_latched(),
        prepared_at_latch=terminal,
        interrupt_summary=None,
    )

    assert application.disposition is ExecutionControlDisposition.ALREADY_TERMINAL
    assert application.affected_step_ids == ()
    assert terminal.steps[0].output == {"truth": "keep"}


def test_preempt_handoff_is_separate_from_lifecycle_rewrite() -> None:
    terminal = _prepared(
        running_status=StepExecutionStatus.SUCCESS,
        include_pending=False,
    )

    application = ExecutionControlApplicationEvaluator().evaluate(
        latched_control=_latched(ExecutionControlSignalType.PREEMPT),
        prepared_at_latch=terminal,
        interrupt_summary=None,
    )

    assert application.disposition is ExecutionControlDisposition.ALREADY_TERMINAL
    assert application.affected_step_ids == ()
    assert application.handoff_required is True


def test_application_contract_rejects_handoff_not_matching_signal() -> None:
    with pytest.raises(ValueError, match="handoff_required"):
        ExecutionControlApplication(
            signal=_signal(ExecutionControlSignalType.PREEMPT),
            disposition=ExecutionControlDisposition.UNKNOWN,
            reason_codes=("CONTROL_UNKNOWN",),
            handoff_required=False,
        )


def test_interrupt_outcome_rejects_non_enum_status() -> None:
    with pytest.raises(ValueError, match="InterruptOutcomeStatus"):
        InterruptOutcome(
            operation_handle_id="owner-001",
            status=cast(InterruptOutcomeStatus, "STOP_REQUESTED"),
            reason_codes=("REQUESTED_ONLY",),
        )
