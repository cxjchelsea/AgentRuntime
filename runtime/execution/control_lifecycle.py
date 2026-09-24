"""CA-M5-IU7-03 control-specific lifecycle terminalization boundary.

This module owns only CANCEL/PREEMPT lifecycle mutation after CA-01 latch authority
and CA-02 safe control-application evidence have been established. It deliberately
does not perform interrupt, scheduling, aggregation, recovery, ResourceLock policy,
M6 validation, or Runtime handoff execution.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from runtime.contracts.enums import ExecutionPlanStatus
from runtime.execution.control import (
    ExecutionControlSignalType,
    LatchedExecutionControl,
)
from runtime.execution.control_application import (
    ExecutionControlApplication,
    ExecutionControlDisposition,
    HierarchicalInterruptStatus,
    InterruptOutcomeStatus,
)
from runtime.execution.foundation import (
    ExecutionLifecycleError,
    PreparedExecution,
    StepLifecycleSnapshot,
)
from runtime.execution.models import StepExecutionStatus
from runtime.execution.stores import ExecutionStateStore


class ExecutionControlLifecycleError(ExecutionLifecycleError):
    """Raised when control-specific lifecycle authority is incomplete or stale."""


class ExecutionControlLifecycleTransitioner:
    """Pure CANCEL/PREEMPT lifecycle transition authority.

    This boundary is intentionally separate from ExecutionLifecycleManager.finish_step:
    PENDING steps cancelled by an execution-level control signal never started and must
    not be routed through a RUNNING-only completion API.
    """

    _TERMINAL_STEP_STATUSES = frozenset(
        {
            StepExecutionStatus.SUCCESS,
            StepExecutionStatus.FAILED,
            StepExecutionStatus.SKIPPED,
            StepExecutionStatus.CANCELLED,
            StepExecutionStatus.TIMEOUT,
            StepExecutionStatus.PREEMPTED,
        }
    )
    _TERMINAL_EXECUTION_STATUSES = frozenset(item.value for item in ExecutionPlanStatus)

    def terminalize(
        self,
        prepared: PreparedExecution,
        *,
        latched_control: LatchedExecutionControl,
        application: ExecutionControlApplication,
        at: datetime,
    ) -> PreparedExecution:
        """Apply one proven control transition or return a legitimate late-control no-op."""

        self._validate_authority(
            prepared=prepared,
            latched_control=latched_control,
            application=application,
            at=at,
        )

        if application.disposition is ExecutionControlDisposition.ALREADY_TERMINAL:
            return prepared
        if (
            application.disposition
            is not ExecutionControlDisposition.READY_TO_TERMINALIZE
        ):
            raise ExecutionControlLifecycleError(
                "control lifecycle requires READY_TO_TERMINALIZE or ALREADY_TERMINAL"
            )

        signal = latched_control.signal
        step_status, execution_status = self._target_statuses(signal.signal_type)

        if prepared.execution_record.status in self._TERMINAL_EXECUTION_STATUSES:
            if self._is_exact_live_replay(
                prepared=prepared,
                application=application,
                step_status=step_status,
                execution_status=execution_status,
            ):
                return prepared
            raise ExecutionControlLifecycleError(
                "terminal execution cannot be rewritten by control"
            )

        if prepared.execution_record.status != "RUNNING":
            raise ExecutionControlLifecycleError(
                "control terminalization requires RUNNING execution"
            )
        if prepared.started_at is None:
            raise ExecutionControlLifecycleError(
                "control terminalization requires execution started_at"
            )

        affected_ids = set(application.affected_step_ids)
        step_ids = [step.step_id for step in prepared.steps]
        if len(set(step_ids)) != len(step_ids):
            raise ExecutionControlLifecycleError(
                "prepared execution contains duplicate step_id"
            )
        if not affected_ids.issubset(set(step_ids)):
            raise ExecutionControlLifecycleError(
                "affected_step_ids must resolve in prepared execution"
            )

        transitioned_ids: set[str] = set()
        transitioned_steps: list[StepLifecycleSnapshot] = []

        for step in prepared.steps:
            if step.status in self._TERMINAL_STEP_STATUSES:
                if step.step_id in affected_ids:
                    raise ExecutionControlLifecycleError(
                        "stale control application cannot rewrite terminal Step"
                    )
                transitioned_steps.append(step)
                continue

            if step.status is StepExecutionStatus.PENDING:
                if step.step_id not in affected_ids:
                    transitioned_steps.append(step)
                    continue
                transitioned_ids.add(step.step_id)
                transitioned_steps.append(
                    replace(
                        step,
                        status=step_status,
                        finished_at=at,
                    )
                )
                continue

            if step.status is StepExecutionStatus.RUNNING:
                if step.step_id not in affected_ids:
                    transitioned_steps.append(step)
                    continue
                self._validate_running_step_authority(
                    step=step,
                    application=application,
                )
                transitioned_ids.add(step.step_id)
                transitioned_steps.append(
                    replace(
                        step,
                        status=step_status,
                        finished_at=at,
                    )
                )
                continue

            raise ExecutionControlLifecycleError(
                "control terminalization observed unsupported Step status"
            )

        if transitioned_ids != affected_ids:
            raise ExecutionControlLifecycleError(
                "control terminalization must apply every affected Step exactly once"
            )

        steps = tuple(transitioned_steps)
        if any(step.status not in self._TERMINAL_STEP_STATUSES for step in steps):
            raise ExecutionControlLifecycleError(
                "execution cannot control-terminalize while a Step remains non-terminal"
            )

        return replace(
            prepared,
            steps=steps,
            finished_at=at,
            execution_record=replace(
                prepared.execution_record,
                status=execution_status.value,
                current_step=None,
                step_results=tuple(_snapshot_to_record_payload(step) for step in steps),
                updated_at=at,
            ),
        )

    def _validate_authority(
        self,
        *,
        prepared: PreparedExecution,
        latched_control: LatchedExecutionControl,
        application: ExecutionControlApplication,
        at: datetime,
    ) -> None:
        _require_aware_datetime(at, "terminalization time")

        signal = latched_control.signal
        if signal.signal_type not in {
            ExecutionControlSignalType.CANCEL,
            ExecutionControlSignalType.PREEMPT,
        }:
            raise ExecutionControlLifecycleError(
                "control lifecycle requires CANCEL/PREEMPT latch"
            )
        if application.signal != signal:
            raise ExecutionControlLifecycleError(
                "control application signal must match exact latched signal"
            )
        if signal.target_execution_id != prepared.execution_context.execution_id:
            raise ExecutionControlLifecycleError(
                "latched control target does not match execution"
            )
        if (
            prepared.execution_record.execution_id
            != prepared.execution_context.execution_id
        ):
            raise ExecutionControlLifecycleError(
                "prepared execution identity is inconsistent"
            )
        if at < latched_control.latched_at:
            raise ExecutionControlLifecycleError(
                "terminalization cannot precede control latch"
            )
        if prepared.started_at is not None and at < prepared.started_at:
            raise ExecutionControlLifecycleError(
                "terminalization cannot precede execution start"
            )
        if (
            prepared.execution_record.updated_at is not None
            and at < prepared.execution_record.updated_at
        ):
            raise ExecutionControlLifecycleError(
                "terminalization cannot precede latest execution observation"
            )
        for step in prepared.steps:
            if step.started_at is not None and at < step.started_at:
                raise ExecutionControlLifecycleError(
                    "terminalization cannot precede Step start"
                )
            if step.finished_at is not None and at < step.finished_at:
                raise ExecutionControlLifecycleError(
                    "terminalization cannot precede existing Step completion"
                )

        if application.disposition is ExecutionControlDisposition.ALREADY_TERMINAL:
            if application.affected_step_ids:
                raise ExecutionControlLifecycleError(
                    "late control no-op cannot claim affected Steps"
                )
            if any(
                step.status not in self._TERMINAL_STEP_STATUSES
                for step in prepared.steps
            ):
                raise ExecutionControlLifecycleError(
                    "ALREADY_TERMINAL requires all Steps terminal"
                )
            return

        if (
            application.disposition
            is not ExecutionControlDisposition.READY_TO_TERMINALIZE
        ):
            raise ExecutionControlLifecycleError(
                "unsafe control application cannot mutate lifecycle"
            )
        if not application.affected_step_ids:
            raise ExecutionControlLifecycleError(
                "control terminalization requires affected unfinished work"
            )

    @staticmethod
    def _validate_running_step_authority(
        *,
        step: StepLifecycleSnapshot,
        application: ExecutionControlApplication,
    ) -> None:
        if application.running_step_id != step.step_id:
            raise ExecutionControlLifecycleError(
                "RUNNING Step requires matching control application identity"
            )
        if application.preserve_running_step_result:
            raise ExecutionControlLifecycleError(
                "preserved RUNNING result cannot be overwritten by control"
            )

        summary = application.interrupt_summary
        if summary is None:
            raise ExecutionControlLifecycleError(
                "RUNNING Step requires confirmed interrupt evidence"
            )
        if summary.status is not HierarchicalInterruptStatus.ORDERED:
            raise ExecutionControlLifecycleError(
                "RUNNING Step requires ordered interrupt evidence"
            )
        application_signal = application.signal
        if application_signal is None:
            raise ExecutionControlLifecycleError(
                "RUNNING Step requires exact control signal authority"
            )
        if summary.execution_id != application_signal.target_execution_id:
            raise ExecutionControlLifecycleError(
                "interrupt evidence does not match execution"
            )
        if summary.step_execution_id != step.step_execution_id:
            raise ExecutionControlLifecycleError(
                "interrupt evidence does not match RUNNING Step"
            )
        if not summary.outcomes:
            raise ExecutionControlLifecycleError(
                "RUNNING Step requires owner interrupt outcome"
            )
        owner_outcome = summary.outcomes[-1]
        if owner_outcome.status is not InterruptOutcomeStatus.CONFIRMED_STOPPED:
            raise ExecutionControlLifecycleError(
                "RUNNING Step requires CONFIRMED_STOPPED owner"
            )
        if (
            not summary.handles
            or summary.handles[-1].operation_handle_id
            != owner_outcome.operation_handle_id
        ):
            raise ExecutionControlLifecycleError(
                "owner interrupt outcome identity is inconsistent"
            )

    @staticmethod
    def _target_statuses(
        signal_type: ExecutionControlSignalType,
    ) -> tuple[StepExecutionStatus, ExecutionPlanStatus]:
        if signal_type is ExecutionControlSignalType.CANCEL:
            return StepExecutionStatus.CANCELLED, ExecutionPlanStatus.CANCELLED
        if signal_type is ExecutionControlSignalType.PREEMPT:
            return StepExecutionStatus.PREEMPTED, ExecutionPlanStatus.PREEMPTED
        raise ExecutionControlLifecycleError(
            "control lifecycle target status requires CANCEL/PREEMPT"
        )

    @classmethod
    def _is_exact_live_replay(
        cls,
        *,
        prepared: PreparedExecution,
        application: ExecutionControlApplication,
        step_status: StepExecutionStatus,
        execution_status: ExecutionPlanStatus,
    ) -> bool:
        if prepared.execution_record.status != execution_status.value:
            return False
        if prepared.finished_at is None:
            return False
        affected = set(application.affected_step_ids)
        if not affected:
            return False
        matches = {
            step.step_id
            for step in prepared.steps
            if step.step_id in affected and step.status is step_status
        }
        if matches != affected:
            return False
        return all(
            step.status in cls._TERMINAL_STEP_STATUSES for step in prepared.steps
        )


class ExecutionControlLifecycleService:
    """Persist the output of the pure control lifecycle transition boundary."""

    def __init__(
        self,
        *,
        transitioner: ExecutionControlLifecycleTransitioner,
        execution_store: ExecutionStateStore,
    ) -> None:
        self._transitioner = transitioner
        self._execution_store = execution_store

    async def terminalize(
        self,
        prepared: PreparedExecution,
        *,
        latched_control: LatchedExecutionControl,
        application: ExecutionControlApplication,
        at: datetime,
    ) -> PreparedExecution:
        updated = self._transitioner.terminalize(
            prepared,
            latched_control=latched_control,
            application=application,
            at=at,
        )
        if updated is not prepared:
            await self._execution_store.save(updated.execution_record)
        return updated


def _snapshot_to_record_payload(snapshot: StepLifecycleSnapshot) -> dict[str, object]:
    return {
        "step_execution_id": snapshot.step_execution_id,
        "step_id": snapshot.step_id,
        "action": snapshot.action,
        "status": snapshot.status.value,
        "skill_id": snapshot.skill_id,
        "workflow_id": snapshot.workflow_id,
        "tool_call_ids": snapshot.tool_call_ids,
        "output": snapshot.output,
        "error": snapshot.error,
        "retry_count": snapshot.retry_count,
        "terminal_reason_codes": list(snapshot.terminal_reason_codes),
        "started_at": snapshot.started_at,
        "finished_at": snapshot.finished_at,
    }


def _require_aware_datetime(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ExecutionControlLifecycleError(f"{field_name} must be timezone-aware")
