"""CA-M5-IU10-00 terminal Step completion boundary.

This module closes only Step lifecycle gaps that must be resolved before plan
aggregation. It does not aggregate ExecutionResult, invoke capabilities, retry,
resume workflows, consult registries, or enter M6.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from runtime.contracts.planning import ApprovedActionPlan
from runtime.execution.foundation import ExecutionLifecycleService, PreparedExecution
from runtime.execution.scheduler import (
    SequentialStepScheduler,
    StepScheduleDecision,
    StepScheduleStatus,
)


class StepScheduler(Protocol):
    async def next_step(
        self,
        *,
        approved_plan: ApprovedActionPlan,
        prepared: PreparedExecution,
    ) -> StepScheduleDecision:
        """Return the current authoritative scheduler decision."""


class TerminalStepCompletionStatus(str, Enum):
    TERMINALIZED = "TERMINALIZED"
    READY = "READY"
    WAITING = "WAITING"
    COMPLETE = "COMPLETE"
    BLOCKED_UNKNOWN = "BLOCKED_UNKNOWN"


@dataclass(frozen=True, slots=True)
class TerminalStepCompletionDecision:
    status: TerminalStepCompletionStatus
    reason_codes: tuple[str, ...]
    prepared: PreparedExecution
    schedule_decision: StepScheduleDecision
    terminalized_step_id: str | None = None

    def __post_init__(self) -> None:
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        if self.status is TerminalStepCompletionStatus.TERMINALIZED:
            if self.terminalized_step_id is None or not self.terminalized_step_id.strip():
                raise ValueError("TERMINALIZED requires terminalized_step_id")
        elif self.terminalized_step_id is not None:
            raise ValueError("non-TERMINALIZED decision cannot carry terminalized_step_id")


class TerminalStepCompletionCoordinator:
    """Consume the current scheduler decision and close only authorized PENDING Steps."""

    _REMAINDER_SKIP_REASON = ("REQUIRED_PREVIOUS_STEP_NOT_SUCCESSFUL",)

    def __init__(
        self,
        *,
        scheduler: StepScheduler | None = None,
        lifecycle_service: ExecutionLifecycleService,
    ) -> None:
        self._scheduler = scheduler or SequentialStepScheduler()
        self._lifecycle_service = lifecycle_service

    async def advance(
        self,
        *,
        approved_plan: ApprovedActionPlan,
        prepared: PreparedExecution,
        at: datetime,
    ) -> TerminalStepCompletionDecision:
        decision = await self._scheduler.next_step(
            approved_plan=approved_plan,
            prepared=prepared,
        )

        if decision.status is StepScheduleStatus.SKIP:
            return await self._terminalize(
                prepared=prepared,
                decision=decision,
                at=at,
            )

        if (
            decision.status is StepScheduleStatus.BLOCKED
            and decision.step_id is not None
            and decision.reason_codes == self._REMAINDER_SKIP_REASON
        ):
            return await self._terminalize(
                prepared=prepared,
                decision=decision,
                at=at,
            )

        mapping = {
            StepScheduleStatus.READY: TerminalStepCompletionStatus.READY,
            StepScheduleStatus.WAITING: TerminalStepCompletionStatus.WAITING,
            StepScheduleStatus.COMPLETE: TerminalStepCompletionStatus.COMPLETE,
            StepScheduleStatus.BLOCKED: TerminalStepCompletionStatus.BLOCKED_UNKNOWN,
            StepScheduleStatus.UNKNOWN: TerminalStepCompletionStatus.BLOCKED_UNKNOWN,
        }
        status = mapping.get(decision.status)
        if status is None:
            status = TerminalStepCompletionStatus.BLOCKED_UNKNOWN
        return TerminalStepCompletionDecision(
            status=status,
            reason_codes=decision.reason_codes,
            prepared=prepared,
            schedule_decision=decision,
        )

    async def _terminalize(
        self,
        *,
        prepared: PreparedExecution,
        decision: StepScheduleDecision,
        at: datetime,
    ) -> TerminalStepCompletionDecision:
        step_id = decision.step_id
        if step_id is None or not step_id.strip():
            return TerminalStepCompletionDecision(
                status=TerminalStepCompletionStatus.BLOCKED_UNKNOWN,
                reason_codes=("SCHEDULER_TERMINALIZATION_STEP_UNKNOWN",),
                prepared=prepared,
                schedule_decision=decision,
            )
        updated = await self._lifecycle_service.skip_pending_step(
            prepared,
            step_id=step_id,
            reason_codes=decision.reason_codes,
            at=at,
        )
        return TerminalStepCompletionDecision(
            status=TerminalStepCompletionStatus.TERMINALIZED,
            reason_codes=decision.reason_codes,
            prepared=updated,
            schedule_decision=decision,
            terminalized_step_id=step_id,
        )
