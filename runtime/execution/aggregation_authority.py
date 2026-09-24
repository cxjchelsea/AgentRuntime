"""CA-M5-IU10-01 aggregation eligibility and plan-status authority.

This module decides only whether an execution is eligible for aggregation and,
when eligible, which execution-layer terminal plan status is authorized.
It does not build Canonical ExecutionResult, persist rich aggregation evidence,
invoke capabilities, or enter M6.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from runtime.contracts.enums import ExecutionPlanStatus
from runtime.contracts.planning import ApprovedActionPlan
from runtime.execution.control import (
    ExecutionControlSignalType,
    LatchedExecutionControl,
)
from runtime.execution.foundation import PreparedExecution, StepLifecycleSnapshot
from runtime.execution.models import StepExecutionStatus
from runtime.execution.recovery_evidence import (
    DurableControlReadDecision,
    DurableControlReadStatus,
)


class AggregationEvidenceReadinessStatus(str, Enum):
    READY = "READY"
    MISSING = "MISSING"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class AggregationEvidenceReadinessDecision:
    execution_id: str
    status: AggregationEvidenceReadinessStatus
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.execution_id.strip():
            raise ValueError("execution_id must not be blank")
        if not isinstance(self.status, AggregationEvidenceReadinessStatus):
            raise ValueError(
                "status must be AggregationEvidenceReadinessStatus"
            )  # noqa: TRY004
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")


class AggregationControlApplicabilityStatus(str, Enum):
    NONE = "NONE"
    APPLIES = "APPLIES"
    LATE_NOOP = "LATE_NOOP"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class AggregationControlApplicabilityDecision:
    status: AggregationControlApplicabilityStatus
    reason_codes: tuple[str, ...]
    latched_control: LatchedExecutionControl | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, AggregationControlApplicabilityStatus):
            raise ValueError(
                "status must be AggregationControlApplicabilityStatus"
            )  # noqa: TRY004
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        if self.status in {
            AggregationControlApplicabilityStatus.APPLIES,
            AggregationControlApplicabilityStatus.LATE_NOOP,
        }:
            if self.latched_control is None:
                raise ValueError(
                    "APPLIES/LATE_NOOP requires exact latched_control"
                )
        elif self.latched_control is not None:
            raise ValueError(
                "NONE/UNKNOWN control applicability cannot carry latched_control"
            )


class StepSkipAggregationDisposition(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNSATISFIED = "UNSATISFIED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class StepSkipAggregationDecision:
    execution_id: str
    step_execution_id: str
    step_id: str
    disposition: StepSkipAggregationDisposition
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.execution_id,
                self.step_execution_id,
                self.step_id,
            )
        ):
            raise ValueError("skip aggregation identifiers must not be blank")
        if not isinstance(self.disposition, StepSkipAggregationDisposition):
            raise ValueError(
                "disposition must be StepSkipAggregationDisposition"
            )  # noqa: TRY004
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")


class StepAggregationEffect(str, Enum):
    SATISFIED = "SATISFIED"
    DEGRADED = "DEGRADED"
    UNSATISFIED = "UNSATISFIED"
    TIMEOUT = "TIMEOUT"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ExecutionAggregationEligibilityStatus(str, Enum):
    READY_NATURAL = "READY_NATURAL"
    READY_EXISTING_TERMINAL = "READY_EXISTING_TERMINAL"
    WAITING = "WAITING"
    BLOCKED_UNKNOWN = "BLOCKED_UNKNOWN"


@dataclass(frozen=True, slots=True)
class ExecutionAggregationDecision:
    execution_id: str
    plan_id: str
    plan_status: ExecutionPlanStatus
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.execution_id.strip() or not self.plan_id.strip():
            raise ValueError("aggregation decision identifiers must not be blank")
        if not isinstance(self.plan_status, ExecutionPlanStatus):
            raise ValueError("plan_status must be ExecutionPlanStatus")  # noqa: TRY004
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")


@dataclass(frozen=True, slots=True)
class ExecutionAggregationEligibilityDecision:
    status: ExecutionAggregationEligibilityStatus
    reason_codes: tuple[str, ...]
    aggregation_decision: ExecutionAggregationDecision | None = None
    existing_plan_status: ExecutionPlanStatus | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ExecutionAggregationEligibilityStatus):
            raise ValueError(
                "status must be ExecutionAggregationEligibilityStatus"
            )  # noqa: TRY004
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        if self.status in {
            ExecutionAggregationEligibilityStatus.READY_NATURAL,
            ExecutionAggregationEligibilityStatus.READY_EXISTING_TERMINAL,
        }:
            if self.aggregation_decision is None:
                raise ValueError("READY aggregation requires aggregation_decision")
        elif self.aggregation_decision is not None:
            raise ValueError(
                "WAITING/BLOCKED aggregation cannot carry aggregation_decision"
            )

        if (
            self.status
            is ExecutionAggregationEligibilityStatus.READY_EXISTING_TERMINAL
        ):
            if self.existing_plan_status is None:
                raise ValueError(
                    "READY_EXISTING_TERMINAL requires existing_plan_status"
                )
        elif self.existing_plan_status is not None:
            raise ValueError(
                "only READY_EXISTING_TERMINAL can carry existing_plan_status"
            )


class ExecutionAggregationAuthority:
    """Pure IU10 authority over aggregation eligibility and terminal plan status."""

    _TERMINAL_EXECUTION_STATUSES = {
        item.value: item for item in ExecutionPlanStatus
    }

    def evaluate(
        self,
        *,
        approved_plan: ApprovedActionPlan,
        prepared: PreparedExecution,
        control: DurableControlReadDecision,
        control_applicability: AggregationControlApplicabilityDecision,
        evidence_readiness: AggregationEvidenceReadinessDecision,
        skip_decisions: Mapping[str, StepSkipAggregationDecision],
    ) -> ExecutionAggregationEligibilityDecision:
        alignment_error = self._alignment_error(approved_plan, prepared)
        if alignment_error is not None:
            return self._blocked(alignment_error)

        lifecycle_error = self._lifecycle_consistency_error(prepared)
        if lifecycle_error is not None:
            return self._blocked(lifecycle_error)

        if control.status is DurableControlReadStatus.UNKNOWN:
            return self._blocked("AGGREGATION_CONTROL_STATE_UNKNOWN")

        if (
            evidence_readiness.execution_id
            != prepared.execution_record.execution_id
        ):
            return self._blocked("AGGREGATION_EVIDENCE_EXECUTION_MISMATCH")

        if control_applicability.status is AggregationControlApplicabilityStatus.UNKNOWN:
            return self._blocked("AGGREGATION_CONTROL_APPLICABILITY_UNKNOWN")

        if control.status is DurableControlReadStatus.NONE:
            if control_applicability.status is not AggregationControlApplicabilityStatus.NONE:
                return self._blocked("AGGREGATION_CONTROL_APPLICABILITY_MISMATCH")
        else:
            if control_applicability.status is AggregationControlApplicabilityStatus.NONE:
                return self._blocked("AGGREGATION_CONTROL_APPLICABILITY_MISMATCH")
            if (
                control.latched_control is None
                or control_applicability.latched_control != control.latched_control
            ):
                return self._blocked(
                    "AGGREGATION_CONTROL_APPLICABILITY_AUTHORITY_MISMATCH"
                )

        existing = self._TERMINAL_EXECUTION_STATUSES.get(
            prepared.execution_record.status
        )

        if control.status is DurableControlReadStatus.LATCHED:
            if (
                control_applicability.status
                is AggregationControlApplicabilityStatus.APPLIES
            ):
                return self._evaluate_latched_control(
                    prepared=prepared,
                    control=control,
                    existing=existing,
                    evidence_readiness=evidence_readiness,
                )
            if (
                control_applicability.status
                is AggregationControlApplicabilityStatus.LATE_NOOP
            ):
                late_control_error = self._late_control_error(
                    prepared=prepared,
                    existing=existing,
                )
                if late_control_error is not None:
                    return self._blocked(late_control_error)
            else:
                return self._blocked("AGGREGATION_CONTROL_APPLICABILITY_MISMATCH")

        if existing in {
            ExecutionPlanStatus.CANCELLED,
            ExecutionPlanStatus.PREEMPTED,
        }:
            return self._blocked("AGGREGATION_CONTROL_PROVENANCE_MISSING")

        if prepared.execution_record.status == "CREATED":
            return self._waiting("AGGREGATION_EXECUTION_NOT_STARTED")

        if prepared.execution_record.status not in {
            "RUNNING",
            *self._TERMINAL_EXECUTION_STATUSES,
        }:
            return self._blocked("AGGREGATION_EXECUTION_STATUS_UNKNOWN")

        nonterminal = tuple(
            step
            for step in prepared.steps
            if step.status in {
                StepExecutionStatus.PENDING,
                StepExecutionStatus.RUNNING,
            }
        )
        if nonterminal:
            if existing is not None:
                return self._blocked(
                    "AGGREGATION_TERMINAL_EXECUTION_HAS_NONTERMINAL_STEP"
                )
            return self._waiting("AGGREGATION_STEPS_NOT_TERMINAL")

        if any(
            step.status
            in {
                StepExecutionStatus.CANCELLED,
                StepExecutionStatus.PREEMPTED,
            }
            for step in prepared.steps
        ):
            return self._blocked("AGGREGATION_STEP_CONTROL_PROVENANCE_MISSING")

        evidence_error = self._evidence_error(evidence_readiness)
        if evidence_error is not None:
            return self._blocked(evidence_error)

        effects = self._step_effects(
            approved_plan=approved_plan,
            prepared=prepared,
            skip_decisions=skip_decisions,
        )
        if effects is None:
            return self._blocked("AGGREGATION_STEP_EFFECT_UNKNOWN")

        aggregation = self._natural_plan_status(
            approved_plan=approved_plan,
            prepared=prepared,
            effects=effects,
        )

        if existing is None:
            return ExecutionAggregationEligibilityDecision(
                status=ExecutionAggregationEligibilityStatus.READY_NATURAL,
                reason_codes=("AGGREGATION_NATURAL_STATUS_AUTHORIZED",),
                aggregation_decision=aggregation,
            )

        if existing is not aggregation.plan_status:
            return self._blocked("AGGREGATION_EXISTING_TERMINAL_STATUS_MISMATCH")

        return ExecutionAggregationEligibilityDecision(
            status=ExecutionAggregationEligibilityStatus.READY_EXISTING_TERMINAL,
            reason_codes=("AGGREGATION_EXISTING_TERMINAL_REPLAY_AUTHORIZED",),
            aggregation_decision=aggregation,
            existing_plan_status=existing,
        )

    def _evaluate_latched_control(
        self,
        *,
        prepared: PreparedExecution,
        control: DurableControlReadDecision,
        existing: ExecutionPlanStatus | None,
        evidence_readiness: AggregationEvidenceReadinessDecision,
    ) -> ExecutionAggregationEligibilityDecision:
        latched = control.latched_control
        if latched is None:
            return self._blocked("AGGREGATION_LATCHED_CONTROL_MISSING")

        target_execution_id = latched.signal.target_execution_id
        if target_execution_id != prepared.execution_record.execution_id:
            return self._blocked("AGGREGATION_CONTROL_TARGET_MISMATCH")

        expected = {
            ExecutionControlSignalType.CANCEL: ExecutionPlanStatus.CANCELLED,
            ExecutionControlSignalType.PREEMPT: ExecutionPlanStatus.PREEMPTED,
        }.get(latched.signal.signal_type)
        if expected is None:
            return self._blocked("AGGREGATION_CONTROL_TYPE_UNKNOWN")

        if existing is None:
            return self._blocked("AGGREGATION_CONTROL_TERMINALIZATION_REQUIRED")

        if existing is not expected:
            return self._blocked("AGGREGATION_CONTROL_TERMINAL_STATUS_MISMATCH")

        if any(
            step.status in {
                StepExecutionStatus.PENDING,
                StepExecutionStatus.RUNNING,
            }
            for step in prepared.steps
        ):
            return self._blocked(
                "AGGREGATION_CONTROL_TERMINAL_HAS_NONTERMINAL_STEP"
            )

        opposite_step_status = {
            ExecutionPlanStatus.CANCELLED: StepExecutionStatus.PREEMPTED,
            ExecutionPlanStatus.PREEMPTED: StepExecutionStatus.CANCELLED,
        }[expected]
        if any(step.status is opposite_step_status for step in prepared.steps):
            return self._blocked(
                "AGGREGATION_CONTROL_STEP_TERMINAL_STATUS_MISMATCH"
            )

        evidence_error = self._evidence_error(evidence_readiness)
        if evidence_error is not None:
            return self._blocked(evidence_error)

        return ExecutionAggregationEligibilityDecision(
            status=ExecutionAggregationEligibilityStatus.READY_EXISTING_TERMINAL,
            reason_codes=("AGGREGATION_CONTROL_TERMINAL_REPLAY_AUTHORIZED",),
            aggregation_decision=ExecutionAggregationDecision(
                execution_id=prepared.execution_record.execution_id,
                plan_id=prepared.execution_record.plan_id,
                plan_status=expected,
                reason_codes=("AGGREGATION_CONTROL_STATUS_PRESERVED",),
            ),
            existing_plan_status=existing,
        )

    @staticmethod
    def _alignment_error(
        approved_plan: ApprovedActionPlan,
        prepared: PreparedExecution,
    ) -> str | None:
        record = prepared.execution_record
        if (
            record.plan_id != approved_plan.plan_id
            or record.request_id != approved_plan.request_id
            or prepared.execution_context.plan_id != approved_plan.plan_id
            or prepared.execution_context.request_id != approved_plan.request_id
            or prepared.execution_context.execution_id != record.execution_id
            or prepared.execution_context.identity_scope != record.identity_scope
        ):
            return "AGGREGATION_EXECUTION_PROVENANCE_MISMATCH"

        plan_ids = tuple(step.step_id for step in approved_plan.steps)
        lifecycle_ids = tuple(step.step_id for step in prepared.steps)
        if plan_ids != lifecycle_ids or len(set(plan_ids)) != len(plan_ids):
            return "AGGREGATION_STEP_ALIGNMENT_MISMATCH"

        if len(record.step_results) != len(prepared.steps):
            return "AGGREGATION_PERSISTED_STEP_COUNT_MISMATCH"

        for plan_step, lifecycle, persisted in zip(
            approved_plan.steps,
            prepared.steps,
            record.step_results,
            strict=True,
        ):
            if (
                lifecycle.action != plan_step.action
                or lifecycle.skill_id != plan_step.skill_id
                or lifecycle.workflow_id != plan_step.workflow_id
            ):
                return "AGGREGATION_STEP_PROVENANCE_MISMATCH"
            if not lifecycle.step_execution_id.strip():
                return "AGGREGATION_STEP_EXECUTION_ID_INVALID"
            if not cls._persisted_step_matches(
                lifecycle=lifecycle,
                persisted=persisted,
            ):
                return "AGGREGATION_PERSISTED_STEP_FACT_MISMATCH"

        running = tuple(
            step
            for step in prepared.steps
            if step.status is StepExecutionStatus.RUNNING
        )
        if len(running) > 1:
            return "AGGREGATION_MULTIPLE_RUNNING_STEPS"
        expected_current = running[0].step_id if running else None
        if record.current_step != expected_current:
            return "AGGREGATION_CURRENT_STEP_MISMATCH"
        return None

    @staticmethod
    def _persisted_step_matches(
        *,
        lifecycle: StepLifecycleSnapshot,
        persisted: Mapping[str, object],
    ) -> bool:
        expected: dict[str, object] = {
            "step_execution_id": lifecycle.step_execution_id,
            "step_id": lifecycle.step_id,
            "action": lifecycle.action,
            "status": lifecycle.status.value,
            "skill_id": lifecycle.skill_id,
            "workflow_id": lifecycle.workflow_id,
            "tool_call_ids": list(lifecycle.tool_call_ids),
            "output": lifecycle.output,
            "error": lifecycle.error,
            "retry_count": lifecycle.retry_count,
            "terminal_reason_codes": list(lifecycle.terminal_reason_codes),
            "degraded": lifecycle.degraded,
            "started_at": lifecycle.started_at,
            "finished_at": lifecycle.finished_at,
        }
        normalized = dict(persisted)
        normalized.setdefault("terminal_reason_codes", [])
        normalized.setdefault("degraded", False)
        return all(normalized.get(key) == value for key, value in expected.items())

    @classmethod
    def _lifecycle_consistency_error(
        cls,
        prepared: PreparedExecution,
    ) -> str | None:
        status = prepared.execution_record.status
        terminal_execution = status in cls._TERMINAL_EXECUTION_STATUSES

        if status == "RUNNING":
            if prepared.started_at is None:
                return "AGGREGATION_RUNNING_EXECUTION_START_MISSING"
            if prepared.finished_at is not None:
                return "AGGREGATION_RUNNING_EXECUTION_HAS_FINISHED_AT"
        elif terminal_execution:
            if prepared.started_at is None or prepared.finished_at is None:
                return "AGGREGATION_TERMINAL_EXECUTION_TIMING_MISSING"
            if prepared.finished_at < prepared.started_at:
                return "AGGREGATION_EXECUTION_TIME_REGRESSION"

        for step in prepared.steps:
            if step.status is StepExecutionStatus.PENDING:
                if step.started_at is not None or step.finished_at is not None:
                    return "AGGREGATION_PENDING_STEP_TIMING_INVALID"
                continue
            if step.status is StepExecutionStatus.RUNNING:
                if step.started_at is None or step.finished_at is not None:
                    return "AGGREGATION_RUNNING_STEP_TIMING_INVALID"
                continue
            if step.finished_at is None:
                return "AGGREGATION_TERMINAL_STEP_FINISH_MISSING"
            if (
                step.status
                in {
                    StepExecutionStatus.SUCCESS,
                    StepExecutionStatus.FAILED,
                    StepExecutionStatus.TIMEOUT,
                }
                and step.started_at is None
            ):
                return "AGGREGATION_EXECUTED_STEP_START_MISSING"
            if step.started_at is not None and step.finished_at < step.started_at:
                return "AGGREGATION_STEP_TIME_REGRESSION"

        return None

    @staticmethod
    def _late_control_error(
        *,
        prepared: PreparedExecution,
        existing: ExecutionPlanStatus | None,
    ) -> str | None:
        if any(
            step.status in {
                StepExecutionStatus.PENDING,
                StepExecutionStatus.RUNNING,
            }
            for step in prepared.steps
        ):
            return "AGGREGATION_LATE_CONTROL_HAS_UNFINISHED_WORK"
        if existing in {
            ExecutionPlanStatus.CANCELLED,
            ExecutionPlanStatus.PREEMPTED,
        }:
            return "AGGREGATION_LATE_CONTROL_TERMINAL_STATUS_MISMATCH"
        return None

    @staticmethod
    def _evidence_error(
        evidence_readiness: AggregationEvidenceReadinessDecision,
    ) -> str | None:
        if evidence_readiness.status is AggregationEvidenceReadinessStatus.READY:
            return None
        if (
            evidence_readiness.status
            is AggregationEvidenceReadinessStatus.MISSING
        ):
            return "AGGREGATION_EVIDENCE_MISSING"
        return "AGGREGATION_EVIDENCE_UNKNOWN"

    @staticmethod
    def _step_effects(
        *,
        approved_plan: ApprovedActionPlan,
        prepared: PreparedExecution,
        skip_decisions: Mapping[str, StepSkipAggregationDecision],
    ) -> dict[str, StepAggregationEffect] | None:
        effects: dict[str, StepAggregationEffect] = {}
        lifecycle_by_id = {step.step_id: step for step in prepared.steps}

        for plan_step in approved_plan.steps:
            step = lifecycle_by_id[plan_step.step_id]
            if step.status is StepExecutionStatus.SUCCESS:
                effects[step.step_id] = (
                    StepAggregationEffect.DEGRADED
                    if step.degraded
                    else StepAggregationEffect.SATISFIED
                )
                continue
            if step.status is StepExecutionStatus.FAILED:
                effects[step.step_id] = StepAggregationEffect.UNSATISFIED
                continue
            if step.status is StepExecutionStatus.TIMEOUT:
                effects[step.step_id] = StepAggregationEffect.TIMEOUT
                continue
            if step.status is StepExecutionStatus.SKIPPED:
                skip_decision = skip_decisions.get(step.step_id)
                if skip_decision is None:
                    return None
                if (
                    skip_decision.execution_id
                    != prepared.execution_record.execution_id
                    or skip_decision.step_execution_id != step.step_execution_id
                    or skip_decision.step_id != step.step_id
                ):
                    return None
                disposition = skip_decision.disposition
                if disposition is StepSkipAggregationDisposition.NOT_APPLICABLE:
                    effects[step.step_id] = StepAggregationEffect.NOT_APPLICABLE
                    continue
                if disposition is StepSkipAggregationDisposition.UNSATISFIED:
                    effects[step.step_id] = StepAggregationEffect.UNSATISFIED
                    continue
                return None
            return None

        extra_skip_ids = set(skip_decisions) - {
            step.step_id
            for step in prepared.steps
            if step.status is StepExecutionStatus.SKIPPED
        }
        if extra_skip_ids:
            return None
        return effects

    @staticmethod
    def _natural_plan_status(
        *,
        approved_plan: ApprovedActionPlan,
        prepared: PreparedExecution,
        effects: Mapping[str, StepAggregationEffect],
    ) -> ExecutionAggregationDecision:
        required_effects = [
            effects[step.step_id]
            for step in approved_plan.steps
            if step.optional is not True
        ]
        optional_effects = [
            effects[step.step_id]
            for step in approved_plan.steps
            if step.optional is True
        ]

        if StepAggregationEffect.TIMEOUT in required_effects:
            return ExecutionAggregationDecision(
                execution_id=prepared.execution_record.execution_id,
                plan_id=approved_plan.plan_id,
                plan_status=ExecutionPlanStatus.TIMEOUT,
                reason_codes=("AGGREGATION_REQUIRED_STEP_TIMEOUT",),
            )

        if StepAggregationEffect.UNSATISFIED in required_effects:
            return ExecutionAggregationDecision(
                execution_id=prepared.execution_record.execution_id,
                plan_id=approved_plan.plan_id,
                plan_status=ExecutionPlanStatus.FAILED,
                reason_codes=("AGGREGATION_REQUIRED_STEP_UNSATISFIED",),
            )

        if StepAggregationEffect.DEGRADED in required_effects:
            return ExecutionAggregationDecision(
                execution_id=prepared.execution_record.execution_id,
                plan_id=approved_plan.plan_id,
                plan_status=ExecutionPlanStatus.PARTIAL_SUCCESS,
                reason_codes=("AGGREGATION_REQUIRED_STEP_DEGRADED",),
            )

        optional_problem = any(
            effect
            in {
                StepAggregationEffect.DEGRADED,
                StepAggregationEffect.UNSATISFIED,
                StepAggregationEffect.TIMEOUT,
            }
            for effect in optional_effects
        )
        if not optional_problem:
            return ExecutionAggregationDecision(
                execution_id=prepared.execution_record.execution_id,
                plan_id=approved_plan.plan_id,
                plan_status=ExecutionPlanStatus.SUCCESS,
                reason_codes=("AGGREGATION_ALL_APPLICABLE_STEPS_SATISFIED",),
            )

        all_effects = list(required_effects) + list(optional_effects)
        has_progress = any(
            effect
            in {
                StepAggregationEffect.SATISFIED,
                StepAggregationEffect.DEGRADED,
            }
            for effect in all_effects
        )
        if has_progress:
            return ExecutionAggregationDecision(
                execution_id=prepared.execution_record.execution_id,
                plan_id=approved_plan.plan_id,
                plan_status=ExecutionPlanStatus.PARTIAL_SUCCESS,
                reason_codes=("AGGREGATION_OPTIONAL_STEP_NOT_FULLY_SATISFIED",),
            )

        if StepAggregationEffect.TIMEOUT in optional_effects:
            return ExecutionAggregationDecision(
                execution_id=prepared.execution_record.execution_id,
                plan_id=approved_plan.plan_id,
                plan_status=ExecutionPlanStatus.TIMEOUT,
                reason_codes=("AGGREGATION_ALL_APPLICABLE_WORK_TIMED_OUT",),
            )

        return ExecutionAggregationDecision(
            execution_id=prepared.execution_record.execution_id,
            plan_id=approved_plan.plan_id,
            plan_status=ExecutionPlanStatus.FAILED,
            reason_codes=("AGGREGATION_ALL_APPLICABLE_WORK_UNSATISFIED",),
        )

    @staticmethod
    def _waiting(reason: str) -> ExecutionAggregationEligibilityDecision:
        return ExecutionAggregationEligibilityDecision(
            status=ExecutionAggregationEligibilityStatus.WAITING,
            reason_codes=(reason,),
        )

    @staticmethod
    def _blocked(reason: str) -> ExecutionAggregationEligibilityDecision:
        return ExecutionAggregationEligibilityDecision(
            status=ExecutionAggregationEligibilityStatus.BLOCKED_UNKNOWN,
            reason_codes=(reason,),
        )
