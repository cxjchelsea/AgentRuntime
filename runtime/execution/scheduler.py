"""M5-IU2 deterministic sequential step scheduling.

The scheduler selects the next approved step from the existing plan. It does not execute
steps, mutate lifecycle state, resolve capabilities, or invent fallback behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from runtime.contracts.planning import ActionStep, ApprovedActionPlan
from runtime.execution.foundation import PreparedExecution
from runtime.execution.models import StepExecutionStatus


class StepConditionStatus(str, Enum):
    SATISFIED = "SATISFIED"
    NOT_SATISFIED = "NOT_SATISFIED"
    WAITING = "WAITING"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class StepConditionDecision:
    status: StepConditionStatus
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.reason_codes:
            raise ValueError("reason_codes must not be empty")
        if any(not reason.strip() for reason in self.reason_codes):
            raise ValueError("reason_codes must not contain blank values")


class StepConditionEvaluator(Protocol):
    async def evaluate(
        self,
        *,
        step: ActionStep,
        prepared: PreparedExecution,
    ) -> StepConditionDecision:
        """Evaluate an injected simple execution condition without changing the plan."""


class NoopStepConditionEvaluator:
    """Default IU2 condition evaluator when no execution condition is registered."""

    async def evaluate(
        self,
        *,
        step: ActionStep,
        prepared: PreparedExecution,
    ) -> StepConditionDecision:
        del step, prepared
        return StepConditionDecision(
            status=StepConditionStatus.SATISFIED,
            reason_codes=("NO_EXECUTION_CONDITION",),
        )


class StepScheduleStatus(str, Enum):
    READY = "READY"
    WAITING = "WAITING"
    SKIP = "SKIP"
    BLOCKED = "BLOCKED"
    COMPLETE = "COMPLETE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class StepScheduleDecision:
    status: StepScheduleStatus
    step_id: str | None
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.reason_codes:
            raise ValueError("reason_codes must not be empty")
        if any(not reason.strip() for reason in self.reason_codes):
            raise ValueError("reason_codes must not contain blank values")
        # READY/SKIP 必须指向具体 Approved Step，不能只给状态
        if self.status in {
            StepScheduleStatus.READY,
            StepScheduleStatus.SKIP,
        } and (self.step_id is None or not self.step_id.strip()):
            raise ValueError("READY/SKIP schedule decision requires step_id")


class SequentialStepScheduler:
    """First-version scheduler for approved sequential plans.

    It preserves ApprovedActionPlan order. Required-step failure is fail-closed because
    ActionStep.on_failure is not a frozen Core enum and IU2 must not invent fallback
    semantics. Optional failed steps may be followed by the next approved step.
    """

    _NON_SUCCESS_TERMINAL = frozenset(
        {
            StepExecutionStatus.FAILED,
            StepExecutionStatus.SKIPPED,
            StepExecutionStatus.CANCELLED,
            StepExecutionStatus.TIMEOUT,
            StepExecutionStatus.PREEMPTED,
        }
    )

    def __init__(
        self,
        *,
        condition_evaluator: StepConditionEvaluator | None = None,
    ) -> None:
        self._condition_evaluator = condition_evaluator or NoopStepConditionEvaluator()

    async def next_step(
        self,
        *,
        approved_plan: ApprovedActionPlan,
        prepared: PreparedExecution,
    ) -> StepScheduleDecision:
        self._validate_alignment(approved_plan, prepared)

        if prepared.execution_record.status != "RUNNING":
            return StepScheduleDecision(
                status=StepScheduleStatus.BLOCKED,
                step_id=None,
                reason_codes=("EXECUTION_NOT_RUNNING",),
            )

        running = [
            step
            for step in prepared.steps
            if step.status is StepExecutionStatus.RUNNING
        ]
        if running:
            if len(running) != 1:
                return StepScheduleDecision(
                    status=StepScheduleStatus.BLOCKED,
                    step_id=None,
                    reason_codes=("MULTIPLE_RUNNING_STEPS",),
                )
            return StepScheduleDecision(
                status=StepScheduleStatus.WAITING,
                step_id=running[0].step_id,
                reason_codes=("STEP_ALREADY_RUNNING",),
            )

        step_by_id = {step.step_id: step for step in prepared.steps}
        pending_index: int | None = None
        for index, plan_step in enumerate(approved_plan.steps):
            lifecycle = step_by_id[plan_step.step_id]
            if lifecycle.status is StepExecutionStatus.PENDING:
                pending_index = index
                break

        if pending_index is None:
            return StepScheduleDecision(
                status=StepScheduleStatus.COMPLETE,
                step_id=None,
                reason_codes=("NO_PENDING_STEPS",),
            )

        for later_step in approved_plan.steps[pending_index + 1 :]:
            if step_by_id[later_step.step_id].status is not StepExecutionStatus.PENDING:
                return StepScheduleDecision(
                    status=StepScheduleStatus.BLOCKED,
                    step_id=None,
                    reason_codes=("SEQUENTIAL_ORDER_VIOLATION",),
                )

        candidate = approved_plan.steps[pending_index]

        for prior_step in approved_plan.steps[:pending_index]:
            prior_lifecycle = step_by_id[prior_step.step_id]
            if (
                (
                    prior_lifecycle.status in self._NON_SUCCESS_TERMINAL
                    or prior_lifecycle.degraded
                )
                and prior_step.optional is not True
            ):
                return StepScheduleDecision(
                    status=StepScheduleStatus.BLOCKED,
                    step_id=candidate.step_id,
                    reason_codes=("REQUIRED_PREVIOUS_STEP_NOT_SUCCESSFUL",),
                )

        dependencies = candidate.depends_on or []
        for dependency_id in dependencies:
            dependency = step_by_id[dependency_id]
            if dependency.status in {
                StepExecutionStatus.PENDING,
                StepExecutionStatus.RUNNING,
            }:
                return StepScheduleDecision(
                    status=StepScheduleStatus.WAITING,
                    step_id=candidate.step_id,
                    reason_codes=("DEPENDENCY_NOT_TERMINAL",),
                )
            if (
                dependency.status is not StepExecutionStatus.SUCCESS
                or dependency.degraded
            ):
                return StepScheduleDecision(
                    status=StepScheduleStatus.SKIP,
                    step_id=candidate.step_id,
                    reason_codes=("DEPENDENCY_NOT_SUCCESSFUL",),
                )

        condition = await self._condition_evaluator.evaluate(
            step=candidate,
            prepared=prepared,
        )
        if condition.status is StepConditionStatus.NOT_SATISFIED:
            return StepScheduleDecision(
                status=StepScheduleStatus.SKIP,
                step_id=candidate.step_id,
                reason_codes=condition.reason_codes,
            )
        if condition.status is StepConditionStatus.WAITING:
            return StepScheduleDecision(
                status=StepScheduleStatus.WAITING,
                step_id=candidate.step_id,
                reason_codes=condition.reason_codes,
            )
        if condition.status is StepConditionStatus.UNKNOWN:
            return StepScheduleDecision(
                status=StepScheduleStatus.UNKNOWN,
                step_id=candidate.step_id,
                reason_codes=condition.reason_codes,
            )

        return StepScheduleDecision(
            status=StepScheduleStatus.READY,
            step_id=candidate.step_id,
            reason_codes=("NEXT_APPROVED_STEP_READY",),
        )

    @staticmethod
    def _validate_alignment(
        approved_plan: ApprovedActionPlan,
        prepared: PreparedExecution,
    ) -> None:
        if prepared.execution_record.plan_id != approved_plan.plan_id:
            raise ValueError(
                "PreparedExecution plan_id does not match ApprovedActionPlan"
            )
        if prepared.execution_record.request_id != approved_plan.request_id:
            raise ValueError(
                "PreparedExecution request_id does not match ApprovedActionPlan"
            )

        plan_ids = [step.step_id for step in approved_plan.steps]
        lifecycle_ids = [step.step_id for step in prepared.steps]
        if plan_ids != lifecycle_ids:
            raise ValueError(
                "PreparedExecution steps must exactly match ApprovedActionPlan order"
            )

        if len(set(plan_ids)) != len(plan_ids):
            raise ValueError("ApprovedActionPlan step_id values must be unique")

        for step in approved_plan.steps:
            for dependency in step.depends_on or []:
                if dependency not in plan_ids:
                    raise ValueError("step dependency must exist in ApprovedActionPlan")
