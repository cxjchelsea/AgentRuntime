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
from runtime.execution.foundation import (
    ExecutionLifecycleService,
    PendingStepSkipAuthority,
    PendingStepSkipAuthorityKind,
    PreparedExecution,
)
from runtime.execution.models import StepExecutionStatus
from runtime.execution.reliability_boundary import (
    StepFinalizationDisposition,
)
from runtime.execution.reliability_coordinator import (
    RecoveredStepReliabilityRunResult,
    StepReliabilityRunResult,
)
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
        matches = tuple(step for step in prepared.steps if step.step_id == step_id)
        if len(matches) != 1:
            return TerminalStepCompletionDecision(
                status=TerminalStepCompletionStatus.BLOCKED_UNKNOWN,
                reason_codes=("SCHEDULER_TERMINALIZATION_STEP_IDENTITY_UNKNOWN",),
                prepared=prepared,
                schedule_decision=decision,
            )
        target = matches[0]
        if decision.status is StepScheduleStatus.SKIP:
            kind = PendingStepSkipAuthorityKind.SCHEDULER_SKIP
        elif (
            decision.status is StepScheduleStatus.BLOCKED
            and decision.reason_codes == self._REMAINDER_SKIP_REASON
        ):
            kind = (
                PendingStepSkipAuthorityKind.REQUIRED_PREVIOUS_STEP_NOT_SUCCESSFUL
            )
        else:
            return TerminalStepCompletionDecision(
                status=TerminalStepCompletionStatus.BLOCKED_UNKNOWN,
                reason_codes=("SCHEDULER_TERMINALIZATION_AUTHORITY_INVALID",),
                prepared=prepared,
                schedule_decision=decision,
            )

        authority = PendingStepSkipAuthority(
            execution_id=prepared.execution_record.execution_id,
            plan_id=prepared.execution_record.plan_id,
            step_execution_id=target.step_execution_id,
            step_id=target.step_id,
            kind=kind,
            reason_codes=decision.reason_codes,
        )
        updated = await self._lifecycle_service.skip_pending_step(
            prepared,
            authority=authority,
            at=at,
        )
        return TerminalStepCompletionDecision(
            status=TerminalStepCompletionStatus.TERMINALIZED,
            reason_codes=decision.reason_codes,
            prepared=updated,
            schedule_decision=decision,
            terminalized_step_id=step_id,
        )



class RunningStepCompletionStatus(str, Enum):
    TERMINALIZED = "TERMINALIZED"
    KEEP_RUNNING = "KEEP_RUNNING"
    WAIT_RECOVERY = "WAIT_RECOVERY"
    BLOCKED_UNKNOWN = "BLOCKED_UNKNOWN"


@dataclass(frozen=True, slots=True)
class RunningStepCompletionDecision:
    status: RunningStepCompletionStatus
    reason_codes: tuple[str, ...]
    prepared: PreparedExecution
    step_id: str
    degraded: bool = False

    def __post_init__(self) -> None:
        if not self.step_id.strip():
            raise ValueError("step_id must not be blank")
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        if self.degraded and self.status is not RunningStepCompletionStatus.TERMINALIZED:
            raise ValueError("degraded completion requires TERMINALIZED status")


class RunningStepCompletionCoordinator:
    """Commit one IU6-authorized final Step result through the existing lifecycle service."""

    def __init__(self, *, lifecycle_service: ExecutionLifecycleService) -> None:
        self._lifecycle_service = lifecycle_service

    async def complete(
        self,
        *,
        prepared: PreparedExecution,
        reliability_result: StepReliabilityRunResult | RecoveredStepReliabilityRunResult,
        at: datetime,
    ) -> RunningStepCompletionDecision:
        observation = reliability_result.final_observation
        finalization = reliability_result.finalization_decision

        matches = tuple(
            step for step in prepared.steps if step.step_id == observation.step_id
        )
        if len(matches) != 1:
            return RunningStepCompletionDecision(
                status=RunningStepCompletionStatus.BLOCKED_UNKNOWN,
                reason_codes=("STEP_COMPLETION_IDENTITY_UNKNOWN",),
                prepared=prepared,
                step_id=observation.step_id,
            )
        target = matches[0]
        if prepared.execution_record.status != "RUNNING":
            return RunningStepCompletionDecision(
                status=RunningStepCompletionStatus.BLOCKED_UNKNOWN,
                reason_codes=("STEP_COMPLETION_EXECUTION_NOT_RUNNING",),
                prepared=prepared,
                step_id=observation.step_id,
            )
        if target.step_execution_id != observation.step_execution_id:
            return RunningStepCompletionDecision(
                status=RunningStepCompletionStatus.BLOCKED_UNKNOWN,
                reason_codes=("STEP_COMPLETION_EXECUTION_IDENTITY_MISMATCH",),
                prepared=prepared,
                step_id=observation.step_id,
            )
        if target.status is not StepExecutionStatus.RUNNING:
            return RunningStepCompletionDecision(
                status=RunningStepCompletionStatus.BLOCKED_UNKNOWN,
                reason_codes=("STEP_COMPLETION_STEP_NOT_RUNNING",),
                prepared=prepared,
                step_id=observation.step_id,
            )

        if finalization.disposition is StepFinalizationDisposition.KEEP_RUNNING:
            return RunningStepCompletionDecision(
                status=RunningStepCompletionStatus.KEEP_RUNNING,
                reason_codes=finalization.reason_codes,
                prepared=prepared,
                step_id=observation.step_id,
            )
        if finalization.disposition is StepFinalizationDisposition.WAIT_RECOVERY:
            return RunningStepCompletionDecision(
                status=RunningStepCompletionStatus.WAIT_RECOVERY,
                reason_codes=finalization.reason_codes,
                prepared=prepared,
                step_id=observation.step_id,
            )
        if finalization.disposition is not StepFinalizationDisposition.FINALIZE:
            return RunningStepCompletionDecision(
                status=RunningStepCompletionStatus.BLOCKED_UNKNOWN,
                reason_codes=finalization.reason_codes,
                prepared=prepared,
                step_id=observation.step_id,
            )
        if finalization.terminal_status is None:
            return RunningStepCompletionDecision(
                status=RunningStepCompletionStatus.BLOCKED_UNKNOWN,
                reason_codes=("STEP_COMPLETION_TERMINAL_STATUS_MISSING",),
                prepared=prepared,
                step_id=observation.step_id,
            )

        tool_call_ids = tuple(entry.tool_call_id for entry in observation.tool_journal)
        updated = await self._lifecycle_service.finish_step(
            prepared,
            step_id=observation.step_id,
            status=finalization.terminal_status,
            at=at,
            tool_call_ids=tool_call_ids,
            retry_count=observation.attempt_number - 1,
            terminal_reason_codes=finalization.reason_codes,
            degraded=finalization.degraded,
        )
        return RunningStepCompletionDecision(
            status=RunningStepCompletionStatus.TERMINALIZED,
            reason_codes=finalization.reason_codes,
            prepared=updated,
            step_id=observation.step_id,
            degraded=finalization.degraded,
        )
