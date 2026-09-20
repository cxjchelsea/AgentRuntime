"""M5-IU2 sequential step scheduling.

The scheduler consumes the already-approved plan and authoritative IU1 lifecycle state.
It never reorders steps, invents actions, resolves capabilities, or executes fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from runtime.contracts import ApprovedActionPlan
from runtime.contracts.planning import ActionStep
from runtime.execution.foundation import PreparedExecution
from runtime.execution.models import StepExecutionStatus


class StepScheduleAction(str, Enum):
    READY = "READY"
    WAIT = "WAIT"
    SKIP = "SKIP"
    COMPLETE = "COMPLETE"


@dataclass(frozen=True, slots=True)
class StepScheduleDecision:
    action: StepScheduleAction
    reason_codes: tuple[str, ...]
    step_id: str | None = None

    def __post_init__(self) -> None:
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        if self.action in {StepScheduleAction.READY, StepScheduleAction.SKIP}:
            if self.step_id is None or not self.step_id.strip():
                raise ValueError("READY/SKIP scheduling decision requires step_id")
        elif self.step_id is not None:
            raise ValueError("WAIT/COMPLETE scheduling decision cannot carry step_id")


class StepEligibilityStatus(str, Enum):
    ALLOW = "ALLOW"
    WAIT = "WAIT"
    SKIP = "SKIP"


@dataclass(frozen=True, slots=True)
class StepEligibilityDecision:
    status: StepEligibilityStatus
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")


class StepEligibilityEvaluator(Protocol):
    def evaluate(
        self,
        step: ActionStep,
        prepared: PreparedExecution,
    ) -> StepEligibilityDecision:
        """Resolve simple injected run conditions for the current approved step."""


class StepFailureDirective(str, Enum):
    CONTINUE = "CONTINUE"
    STOP_PLAN = "STOP_PLAN"
    RUN_FALLBACK = "RUN_FALLBACK"


@dataclass(frozen=True, slots=True)
class StepFailureDecision:
    directive: StepFailureDirective
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")


class ContinueIfSafeEvaluator(Protocol):
    def allows_continue(
        self,
        step: ActionStep,
        prepared: PreparedExecution,
    ) -> bool:
        """Resolve CONTINUE_IF_SAFE without embedding Domain safety logic in Core."""


class FailureDirectiveResolver:
    """Resolve one finished step failure without changing the approved plan."""

    _FAILURE_STATUSES = frozenset(
        {
            StepExecutionStatus.FAILED,
            StepExecutionStatus.TIMEOUT,
            StepExecutionStatus.CANCELLED,
            StepExecutionStatus.PREEMPTED,
        }
    )
    _KNOWN_DIRECTIVES = frozenset(
        {"STOP_PLAN", "RUN_FALLBACK", "CONTINUE_IF_SAFE"}
    )

    def __init__(
        self,
        *,
        continue_if_safe_evaluator: ContinueIfSafeEvaluator | None = None,
    ) -> None:
        self._continue_if_safe_evaluator = continue_if_safe_evaluator

    def resolve(
        self,
        step: ActionStep,
        status: StepExecutionStatus,
        prepared: PreparedExecution,
    ) -> StepFailureDecision:
        if status not in self._FAILURE_STATUSES:
            raise ValueError("failure directive requires failed terminal step status")

        if status in {
            StepExecutionStatus.CANCELLED,
            StepExecutionStatus.PREEMPTED,
        }:
            return StepFailureDecision(
                directive=StepFailureDirective.STOP_PLAN,
                reason_codes=(f"STEP_{status.value}",),
            )

        directive = step.on_failure
        if directive is None:
            if step.optional is True:
                return StepFailureDecision(
                    directive=StepFailureDirective.CONTINUE,
                    reason_codes=("OPTIONAL_STEP_FAILURE_CONTINUE",),
                )
            return StepFailureDecision(
                directive=StepFailureDirective.STOP_PLAN,
                reason_codes=("REQUIRED_STEP_FAILURE_STOP",),
            )

        if directive not in self._KNOWN_DIRECTIVES:
            raise ValueError("unsupported ActionStep.on_failure directive")

        if directive == "STOP_PLAN":
            return StepFailureDecision(
                directive=StepFailureDirective.STOP_PLAN,
                reason_codes=("ON_FAILURE_STOP_PLAN",),
            )
        if directive == "RUN_FALLBACK":
            return StepFailureDecision(
                directive=StepFailureDirective.RUN_FALLBACK,
                reason_codes=("ON_FAILURE_RUN_FALLBACK",),
            )

        evaluator = self._continue_if_safe_evaluator
        if evaluator is None:
            return StepFailureDecision(
                directive=StepFailureDirective.STOP_PLAN,
                reason_codes=("CONTINUE_IF_SAFE_UNRESOLVED",),
            )
        if evaluator.allows_continue(step, prepared):
            return StepFailureDecision(
                directive=StepFailureDirective.CONTINUE,
                reason_codes=("CONTINUE_IF_SAFE_ALLOWED",),
            )
        return StepFailureDecision(
            directive=StepFailureDirective.STOP_PLAN,
            reason_codes=("CONTINUE_IF_SAFE_DENIED",),
        )


class SequentialStepScheduler:
    """Deterministic approved-order scheduler for the M5 first-version baseline."""

    def __init__(
        self,
        *,
        eligibility_evaluator: StepEligibilityEvaluator | None = None,
    ) -> None:
        self._eligibility_evaluator = eligibility_evaluator

    def next(
        self,
        approved_plan: ApprovedActionPlan,
        prepared: PreparedExecution,
    ) -> StepScheduleDecision:
        self._validate_alignment(approved_plan, prepared)

        if prepared.execution_record.status != "RUNNING":
            raise ValueError("step scheduler requires RUNNING execution")

        running = [
            item
            for item in prepared.steps
            if item.status is StepExecutionStatus.RUNNING
        ]
        if running:
            return StepScheduleDecision(
                action=StepScheduleAction.WAIT,
                reason_codes=("STEP_ALREADY_RUNNING",),
            )

        snapshots = {item.step_id: item for item in prepared.steps}
        for step in approved_plan.steps:
            snapshot = snapshots[step.step_id]
            if snapshot.status is not StepExecutionStatus.PENDING:
                continue

            dependencies = step.depends_on or []
            if any(
                snapshots[dependency].status
                in {StepExecutionStatus.PENDING, StepExecutionStatus.RUNNING}
                for dependency in dependencies
            ):
                return StepScheduleDecision(
                    action=StepScheduleAction.WAIT,
                    reason_codes=("DEPENDENCY_NOT_TERMINAL",),
                )

            failed_dependencies = [
                dependency
                for dependency in dependencies
                if snapshots[dependency].status is not StepExecutionStatus.SUCCESS
            ]
            if failed_dependencies:
                return StepScheduleDecision(
                    action=StepScheduleAction.SKIP,
                    step_id=step.step_id,
                    reason_codes=("DEPENDENCY_NOT_SUCCESSFUL",),
                )

            if self._eligibility_evaluator is not None:
                eligibility = self._eligibility_evaluator.evaluate(
                    step,
                    prepared,
                )
                if eligibility.status is StepEligibilityStatus.WAIT:
                    return StepScheduleDecision(
                        action=StepScheduleAction.WAIT,
                        reason_codes=eligibility.reason_codes,
                    )
                if eligibility.status is StepEligibilityStatus.SKIP:
                    return StepScheduleDecision(
                        action=StepScheduleAction.SKIP,
                        step_id=step.step_id,
                        reason_codes=eligibility.reason_codes,
                    )

            return StepScheduleDecision(
                action=StepScheduleAction.READY,
                step_id=step.step_id,
                reason_codes=("STEP_READY_IN_APPROVED_ORDER",),
            )

        return StepScheduleDecision(
            action=StepScheduleAction.COMPLETE,
            reason_codes=("NO_PENDING_STEPS",),
        )

    @staticmethod
    def _validate_alignment(
        approved_plan: ApprovedActionPlan,
        prepared: PreparedExecution,
    ) -> None:
        if approved_plan.plan_id != prepared.execution_record.plan_id:
            raise ValueError("approved plan_id does not match prepared execution")
        plan_step_ids = [step.step_id for step in approved_plan.steps]
        prepared_step_ids = [step.step_id for step in prepared.steps]
        if plan_step_ids != prepared_step_ids:
            raise ValueError("prepared steps must preserve approved plan order exactly")
