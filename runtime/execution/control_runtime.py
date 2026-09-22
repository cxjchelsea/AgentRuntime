"""M5-IU7 Formal Implementation runtime coordinator.

This module composes the three frozen controlled amendments into one live control
path. It does not choose control priority, recompute Policy, manage ResourceLock,
perform durable recovery, aggregate ExecutionResult, or start a new Runtime cycle.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from runtime.execution.control import (
    ExecutionControlLatch,
    ExecutionControlLatchDecision,
    ExecutionControlLatchStatus,
    ExecutionControlSignalType,
    ExecutionControlWatcher,
    LatchedExecutionControl,
    ObservedExecutionControl,
)
from runtime.execution.control_application import (
    ExecutionControlApplication,
    ExecutionControlApplicationEvaluator,
    ExecutionControlDisposition,
    HierarchicalInterruptSummary,
    InFlightInterruptCoordinator,
)
from runtime.execution.control_lifecycle import ExecutionControlLifecycleService
from runtime.execution.foundation import PreparedExecution
from runtime.execution.models import StepExecutionStatus


class ExecutionControlRuntimeError(RuntimeError):
    """Raised when live control authority cannot be obtained safely."""


@dataclass(frozen=True, slots=True)
class ExecutionControlRuntimeResult:
    """One IU7 control application observation, not canonical ExecutionResult."""

    latch_decision: ExecutionControlLatchDecision
    application: ExecutionControlApplication
    prepared: PreparedExecution
    lifecycle_mutated: bool

    @property
    def handoff_required(self) -> bool:
        return self.application.handoff_required


class ExecutionControlCoordinator:
    """Compose watcher/latch, interrupt, application, and lifecycle authorities."""

    def __init__(
        self,
        *,
        watcher: ExecutionControlWatcher,
        latch: ExecutionControlLatch,
        interrupt_coordinator: InFlightInterruptCoordinator,
        application_evaluator: ExecutionControlApplicationEvaluator,
        lifecycle_service: ExecutionControlLifecycleService,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._watcher = watcher
        self._latch = latch
        self._interrupt_coordinator = interrupt_coordinator
        self._application_evaluator = application_evaluator
        self._lifecycle_service = lifecycle_service
        self._clock = clock or (lambda: datetime.now(UTC))

    async def watch_and_apply(
        self,
        prepared: PreparedExecution,
        *,
        prepared_after_interrupt: PreparedExecution | None = None,
    ) -> ExecutionControlRuntimeResult:
        """Wait for one live terminal signal and apply it through the frozen chain."""

        try:
            observed = await self._watcher.wait_for_terminal_signal(
                execution_id=prepared.execution_context.execution_id,
                cancellation_token=prepared.execution_context.cancellation_token,
            )
        except Exception as exc:
            raise ExecutionControlRuntimeError(
                "control watcher failed before exact authority was observed"
            ) from exc

        if not isinstance(observed, ObservedExecutionControl):
            raise ExecutionControlRuntimeError(
                "control watcher returned invalid observed control"
            )

        return await self.observe_and_apply(
            prepared,
            observed=observed,
            prepared_after_interrupt=prepared_after_interrupt,
        )

    async def observe_and_apply(
        self,
        prepared: PreparedExecution,
        *,
        observed: ObservedExecutionControl,
        prepared_after_interrupt: PreparedExecution | None = None,
    ) -> ExecutionControlRuntimeResult:
        """Apply one already-observed terminal signal without re-reading priority."""

        signal = observed.signal
        execution_id = prepared.execution_context.execution_id
        if signal.target_execution_id != execution_id:
            application = self._non_mutating_application(
                prepared=prepared,
                observed=observed,
                disposition=ExecutionControlDisposition.UNKNOWN,
                reason_codes=("CONTROL_SIGNAL_TARGET_MISMATCH",),
            )
            return ExecutionControlRuntimeResult(
                latch_decision=ExecutionControlLatchDecision(
                    status=ExecutionControlLatchStatus.UNKNOWN,
                    reason_codes=("CONTROL_SIGNAL_TARGET_MISMATCH",),
                ),
                application=application,
                prepared=prepared,
                lifecycle_mutated=False,
            )

        latched_at = self._now()
        try:
            latch_decision = await self._latch.latch(
                observed=observed,
                latched_at=latched_at,
            )
        except Exception as exc:
            raise ExecutionControlRuntimeError("control latch failed") from exc

        if not isinstance(latch_decision, ExecutionControlLatchDecision):
            raise ExecutionControlRuntimeError("control latch returned invalid decision")

        if latch_decision.status is ExecutionControlLatchStatus.UNKNOWN:
            return ExecutionControlRuntimeResult(
                latch_decision=latch_decision,
                application=self._non_mutating_application(
                    prepared=prepared,
                    observed=observed,
                    disposition=ExecutionControlDisposition.UNKNOWN,
                    reason_codes=latch_decision.reason_codes,
                ),
                prepared=prepared,
                lifecycle_mutated=False,
            )

        if latch_decision.status is ExecutionControlLatchStatus.CONFLICT:
            return ExecutionControlRuntimeResult(
                latch_decision=latch_decision,
                application=self._non_mutating_application(
                    prepared=prepared,
                    observed=observed,
                    disposition=ExecutionControlDisposition.CONFLICT,
                    reason_codes=latch_decision.reason_codes,
                ),
                prepared=prepared,
                lifecycle_mutated=False,
            )

        latched_control = latch_decision.latched_control
        if latched_control is None:
            raise ExecutionControlRuntimeError(
                "successful control latch decision omitted latched authority"
            )

        return await self._apply_latched(
            prepared,
            latch_decision=latch_decision,
            latched_control=latched_control,
            prepared_after_interrupt=prepared_after_interrupt,
        )

    async def reconcile(
        self,
        *,
        prepared_at_latch: PreparedExecution,
        prior_result: ExecutionControlRuntimeResult,
        prepared_after_interrupt: PreparedExecution,
    ) -> ExecutionControlRuntimeResult:
        """Re-evaluate WAITING control after authoritative lifecycle reconciliation.

        This does not re-interrupt the owner. It reuses the exact latched signal and
        prior interrupt summary, allowing ALREADY_COMPLETED to preserve real
        completion before pending work is control-terminalized.
        """

        latched_control = prior_result.latch_decision.latched_control
        if latched_control is None:
            raise ExecutionControlRuntimeError(
                "control reconciliation requires exact latched authority"
            )
        if prior_result.application.disposition is not ExecutionControlDisposition.WAITING_IN_FLIGHT:
            raise ExecutionControlRuntimeError(
                "control reconciliation requires WAITING_IN_FLIGHT"
            )

        application = self._application_evaluator.evaluate(
            latched_control=latched_control,
            prepared_at_latch=prepared_at_latch,
            interrupt_summary=prior_result.application.interrupt_summary,
            prepared_after_interrupt=prepared_after_interrupt,
        )
        return await self._finalize_application(
            latch_decision=prior_result.latch_decision,
            latched_control=latched_control,
            application=application,
            current_prepared=prepared_after_interrupt,
        )

    async def _apply_latched(
        self,
        prepared: PreparedExecution,
        *,
        latch_decision: ExecutionControlLatchDecision,
        latched_control: LatchedExecutionControl,
        prepared_after_interrupt: PreparedExecution | None,
    ) -> ExecutionControlRuntimeResult:
        running = tuple(
            step
            for step in prepared.steps
            if step.status is StepExecutionStatus.RUNNING
        )

        interrupt_summary: HierarchicalInterruptSummary | None = None
        if len(running) == 1:
            interrupt_summary = await self._interrupt_coordinator.interrupt(
                execution_id=prepared.execution_context.execution_id,
                step_execution_id=running[0].step_execution_id,
                signal=latched_control.signal,
            )

        application = self._application_evaluator.evaluate(
            latched_control=latched_control,
            prepared_at_latch=prepared,
            interrupt_summary=interrupt_summary,
            prepared_after_interrupt=prepared_after_interrupt,
        )

        current_prepared = prepared_after_interrupt or prepared
        return await self._finalize_application(
            latch_decision=latch_decision,
            latched_control=latched_control,
            application=application,
            current_prepared=current_prepared,
        )

    async def _finalize_application(
        self,
        *,
        latch_decision: ExecutionControlLatchDecision,
        latched_control: LatchedExecutionControl,
        application: ExecutionControlApplication,
        current_prepared: PreparedExecution,
    ) -> ExecutionControlRuntimeResult:
        if application.disposition not in {
            ExecutionControlDisposition.READY_TO_TERMINALIZE,
            ExecutionControlDisposition.ALREADY_TERMINAL,
        }:
            return ExecutionControlRuntimeResult(
                latch_decision=latch_decision,
                application=application,
                prepared=current_prepared,
                lifecycle_mutated=False,
            )

        terminalized = await self._lifecycle_service.terminalize(
            current_prepared,
            latched_control=latched_control,
            application=application,
            at=self._now(),
        )
        return ExecutionControlRuntimeResult(
            latch_decision=latch_decision,
            application=application,
            prepared=terminalized,
            lifecycle_mutated=terminalized is not current_prepared,
        )

    def _non_mutating_application(
        self,
        *,
        prepared: PreparedExecution,
        observed: ObservedExecutionControl,
        disposition: ExecutionControlDisposition,
        reason_codes: tuple[str, ...],
    ) -> ExecutionControlApplication:
        nonterminal = tuple(
            step.step_id
            for step in prepared.steps
            if step.status
            not in {
                StepExecutionStatus.SUCCESS,
                StepExecutionStatus.FAILED,
                StepExecutionStatus.SKIPPED,
                StepExecutionStatus.CANCELLED,
                StepExecutionStatus.TIMEOUT,
                StepExecutionStatus.PREEMPTED,
            }
        )
        running = tuple(
            step.step_id
            for step in prepared.steps
            if step.status is StepExecutionStatus.RUNNING
        )
        return ExecutionControlApplication(
            signal=observed.signal,
            disposition=disposition,
            reason_codes=reason_codes,
            running_step_id=running[0] if len(running) == 1 else None,
            nonterminal_step_ids_at_latch=nonterminal,
            affected_step_ids=(),
            preserve_running_step_result=bool(running),
            handoff_required=(
                observed.signal.signal_type is ExecutionControlSignalType.PREEMPT
            ),
        )

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise ExecutionControlRuntimeError("control clock returned invalid time")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ExecutionControlRuntimeError(
                "control clock must return timezone-aware time"
            )
        return value
