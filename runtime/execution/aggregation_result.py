"""CA-M5-IU10-03 Canonical ExecutionResult projection and terminal aggregation.

This module consumes only already-authoritative M5 execution facts:
- ApprovedActionPlan ordering/optionality
- CA-01 aggregation authority
- CA-02 crash-safe terminal Step evidence
- IU7/IU9 durable control provenance

It does not invoke capabilities, consult registries, retry/resume work, enter M6,
generate a response, or infer business truth.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Protocol

from runtime.contracts.enums import ExecutionPlanStatus
from runtime.contracts.execution import (
    ExecutionResult,
    ExecutionTiming,
    StepExecutionResult,
)
from runtime.contracts.planning import ApprovedActionPlan
from runtime.execution.aggregation_authority import (
    AggregationControlApplicabilityDecision,
    AggregationControlApplicabilityStatus,
    AggregationEvidenceReadinessStatus,
    ExecutionAggregationAuthority,
    ExecutionAggregationEligibilityDecision,
    ExecutionAggregationEligibilityStatus,
)
from runtime.execution.aggregation_evidence import (
    StepAggregationTerminalizationKind,
    project_ca01_evidence_inputs,
)
from runtime.execution.capability_resolution import (
    ApprovedCapabilityProjectionError,
    ApprovedStepCapabilityProjector,
)
from runtime.execution.control import (
    ExecutionControlSignalType,
    LatchedExecutionControl,
)
from runtime.execution.foundation import (
    ExecutionLifecycleService,
    PreparedExecution,
    StepLifecycleSnapshot,
)
from runtime.execution.invocation import ToolInvocationJournalEntry
from runtime.execution.recovery_evidence import (
    DurableControlReadDecision,
    DurableControlReadStatus,
    StepAttemptCursorRecord,
)


class ExecutionAggregationProjectionError(RuntimeError):
    """Fail-closed CA-03 projection/integration error."""

    def __init__(self, reason_code: str, message: str | None = None) -> None:
        if not reason_code.strip():
            raise ValueError("reason_code must not be blank")
        super().__init__(message or reason_code)
        self.reason_code = reason_code


class ControlTerminalToolJournalStore(Protocol):
    async def load_step_attempt_cursor(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
    ) -> StepAttemptCursorRecord | None:
        """Load the durable current attempt cursor for one Step."""

    async def load_tool_journal(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
        step_attempt_number: int,
    ) -> tuple[ToolInvocationJournalEntry, ...]:
        """Load the exact durable Tool journal for one Step attempt."""


class ControlTerminalToolEvidenceReader(Protocol):
    async def load(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
    ) -> tuple[ToolInvocationJournalEntry, ...] | None:
        """Return None when no durable Step attempt exists."""


class DurableControlTerminalToolEvidenceReader:
    """Join control-terminal Tool truth through the durable current-attempt cursor."""

    def __init__(self, *, store: ControlTerminalToolJournalStore) -> None:
        self._store = store

    async def load(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
    ) -> tuple[ToolInvocationJournalEntry, ...] | None:
        cursor = await self._store.load_step_attempt_cursor(
            execution_id=execution_id,
            step_execution_id=step_execution_id,
        )
        if cursor is None:
            return None
        if (
            cursor.execution_id != execution_id
            or cursor.step_execution_id != step_execution_id
        ):
            raise ExecutionAggregationProjectionError(
                "EXECUTION_RESULT_CONTROL_ATTEMPT_CURSOR_MISMATCH"
            )
        return await self._store.load_tool_journal(
            execution_id=execution_id,
            step_execution_id=step_execution_id,
            step_attempt_number=cursor.current_attempt,
        )


@dataclass(frozen=True, slots=True)
class ExecutionAggregationRunResult:
    prepared: PreparedExecution
    eligibility: ExecutionAggregationEligibilityDecision
    execution_result: ExecutionResult


class CanonicalExecutionResultProjector:
    """Project one CA-01-authorized terminal execution deterministically."""

    _CONTROL_STATUSES = frozenset(
        {
            ExecutionPlanStatus.CANCELLED,
            ExecutionPlanStatus.PREEMPTED,
        }
    )

    def __init__(
        self,
        *,
        control_tool_evidence_reader: ControlTerminalToolEvidenceReader
        | None = None,
    ) -> None:
        self._control_tool_evidence_reader = control_tool_evidence_reader

    async def project(
        self,
        *,
        approved_plan: ApprovedActionPlan,
        prepared: PreparedExecution,
        eligibility: ExecutionAggregationEligibilityDecision,
        control: DurableControlReadDecision,
        control_applicability: AggregationControlApplicabilityDecision,
    ) -> ExecutionResult:
        decision = eligibility.aggregation_decision
        if (
            eligibility.status
            is not ExecutionAggregationEligibilityStatus.READY_EXISTING_TERMINAL
            or decision is None
        ):
            raise ExecutionAggregationProjectionError(
                "EXECUTION_RESULT_AGGREGATION_NOT_READY"
            )

        record = prepared.execution_record
        if (
            decision.execution_id != record.execution_id
            or decision.plan_id != approved_plan.plan_id
            or record.plan_id != approved_plan.plan_id
            or record.request_id != approved_plan.request_id
        ):
            raise ExecutionAggregationProjectionError(
                "EXECUTION_RESULT_PROVENANCE_MISMATCH"
            )

        if record.status != decision.plan_status.value:
            raise ExecutionAggregationProjectionError(
                "EXECUTION_RESULT_TERMINAL_STATUS_MISMATCH"
            )
        if prepared.started_at is None or prepared.finished_at is None:
            raise ExecutionAggregationProjectionError(
                "EXECUTION_RESULT_EXECUTION_TIMING_MISSING"
            )
        _require_time_order(
            prepared.started_at,
            prepared.finished_at,
            "EXECUTION_RESULT_EXECUTION_TIMING_INVALID",
        )

        evidence_readiness, _ = project_ca01_evidence_inputs(
            approved_plan=approved_plan,
            prepared=prepared,
        )
        if (
            evidence_readiness.status
            is not AggregationEvidenceReadinessStatus.READY
        ):
            raise ExecutionAggregationProjectionError(
                "EXECUTION_RESULT_EVIDENCE_NOT_READY"
            )

        prepared_step_ids = tuple(step.step_id for step in prepared.steps)
        approved_step_ids = tuple(step.step_id for step in approved_plan.steps)
        if (
            prepared_step_ids != approved_step_ids
            or len(set(prepared_step_ids)) != len(prepared_step_ids)
        ):
            raise ExecutionAggregationProjectionError(
                "EXECUTION_RESULT_STEP_ORDER_MISMATCH"
            )
        step_by_id = {step.step_id: step for step in prepared.steps}

        step_results: list[StepExecutionResult] = []
        skill_results: list[dict[str, Any]] = []
        workflow_results: list[dict[str, Any]] = []
        tool_results: list[dict[str, Any]] = []
        business_outputs: list[dict[str, Any]] = []
        execution_events: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        step_durations: list[dict[str, Any]] = []
        tool_durations: list[dict[str, Any]] = []

        seen_tool_journal: dict[str, dict[str, Any]] = {}
        approved_capability_projector = ApprovedStepCapabilityProjector()

        for plan_index, plan_step in enumerate(approved_plan.steps):
            step = step_by_id[plan_step.step_id]
            evidence = step.aggregation_evidence
            if evidence is None:
                raise ExecutionAggregationProjectionError(
                    "EXECUTION_RESULT_STEP_EVIDENCE_MISSING"
                )

            step_results.append(_project_step_result(step))
            step_durations.append(
                _project_step_timing(
                    step=step,
                    plan_index=plan_index,
                )
            )

            if evidence.skill_result is not None:
                skill_results.append(deepcopy(evidence.skill_result))
                skill_error = evidence.skill_result.get("error")
                if isinstance(skill_error, str) and skill_error:
                    errors.append(
                        {
                            "source": "SKILL",
                            "step_id": step.step_id,
                            "skill_id": evidence.skill_result.get("skill_id"),
                            "message": skill_error,
                        }
                    )

            if evidence.workflow_result is not None:
                workflow_results.append(deepcopy(evidence.workflow_result))
                workflow_error = evidence.workflow_result.get("error")
                if isinstance(workflow_error, str) and workflow_error:
                    errors.append(
                        {
                            "source": "WORKFLOW",
                            "step_id": step.step_id,
                            "workflow_id": evidence.workflow_result.get(
                                "workflow_id"
                            ),
                            "message": workflow_error,
                        }
                    )

            journal_entries: tuple[
                Mapping[str, Any] | ToolInvocationJournalEntry, ...
            ]
            if (
                evidence.terminalization_kind
                is StepAggregationTerminalizationKind.CONTROL_TERMINALIZED
            ):
                if self._control_tool_evidence_reader is None:
                    raise ExecutionAggregationProjectionError(
                        "EXECUTION_RESULT_CONTROL_TOOL_EVIDENCE_READER_MISSING"
                    )
                loaded = await self._control_tool_evidence_reader.load(
                    execution_id=record.execution_id,
                    step_execution_id=step.step_execution_id,
                )
                joined = () if loaded is None else loaded
                joined_ids = tuple(item.tool_call_id for item in joined)
                if joined_ids != evidence.tool_call_ids:
                    raise ExecutionAggregationProjectionError(
                        "EXECUTION_RESULT_CONTROL_TOOL_JOURNAL_MISMATCH"
                    )
                if joined:
                    try:
                        approved_capabilities = approved_capability_projector.project(
                            approved_plan=approved_plan,
                            step=plan_step,
                        )
                    except ApprovedCapabilityProjectionError as exc:
                        raise ExecutionAggregationProjectionError(
                            "EXECUTION_RESULT_CONTROL_APPROVED_CAPABILITY_UNKNOWN"
                        ) from exc
                    approved_tool_versions = {
                        item.capability_id: item.version
                        for item in approved_capabilities.tools
                    }
                    for item in joined:
                        if (
                            approved_tool_versions.get(item.tool_id)
                            != item.tool_version
                        ):
                            raise ExecutionAggregationProjectionError(
                                "EXECUTION_RESULT_CONTROL_TOOL_NOT_APPROVED"
                            )
                journal_entries = joined
            else:
                journal_entries = evidence.tool_journal

            for source_index, entry in enumerate(journal_entries):
                _collect_tool_result(
                    entry=entry,
                    step=step,
                    plan_index=plan_index,
                    source_index=source_index,
                    seen_tool_journal=seen_tool_journal,
                    tool_results=tool_results,
                    tool_durations=tool_durations,
                    errors=errors,
                )

            business_outputs.extend(deepcopy(list(evidence.business_outputs)))
            execution_events.extend(deepcopy(list(evidence.capability_events)))

            if step.error:
                errors.append(
                    {
                        "source": "STEP",
                        "step_id": step.step_id,
                        "message": step.error,
                    }
                )

        cancellation = self._project_control(
            plan_status=decision.plan_status,
            execution_id=record.execution_id,
            control=control,
            control_applicability=control_applicability,
        )

        legacy_workflow_result = (
            deepcopy(workflow_results[0]) if len(workflow_results) == 1 else None
        )
        degraded = (
            decision.plan_status is ExecutionPlanStatus.PARTIAL_SUCCESS
            or any(step.degraded for step in prepared.steps)
        )

        timing = ExecutionTiming.model_validate(
            {
                "started_at": prepared.started_at,
                "finished_at": prepared.finished_at,
                "total_duration_ms": _duration_ms(
                    prepared.started_at,
                    prepared.finished_at,
                    "EXECUTION_RESULT_EXECUTION_TIMING_INVALID",
                ),
                "step_durations": step_durations,
                "tool_durations": tool_durations,
            }
        )

        return ExecutionResult(
            execution_id=record.execution_id,
            plan_id=record.plan_id,
            request_id=record.request_id,
            identity_scope=record.identity_scope,
            plan_status=decision.plan_status,
            step_results=step_results,
            timing=timing,
            skill_results=skill_results,
            workflow_result=legacy_workflow_result,
            workflow_results=workflow_results,
            tool_results=tool_results,
            business_outputs=business_outputs,
            execution_events=execution_events,
            state_observations=[],
            errors=errors,
            cancellation=cancellation,
            quality={
                "aggregation_evidence_ready": True,
                "degraded": degraded,
                "aggregation_reason_codes": list(decision.reason_codes),
            },
        )

    @classmethod
    def _project_control(
        cls,
        *,
        plan_status: ExecutionPlanStatus,
        execution_id: str,
        control: DurableControlReadDecision,
        control_applicability: AggregationControlApplicabilityDecision,
    ) -> dict[str, Any] | None:
        if plan_status not in cls._CONTROL_STATUSES:
            if (
                control_applicability.status
                is AggregationControlApplicabilityStatus.APPLIES
            ):
                raise ExecutionAggregationProjectionError(
                    "EXECUTION_RESULT_CONTROL_STATUS_MISMATCH"
                )
            return None

        if (
            control.status is not DurableControlReadStatus.LATCHED
            or control.latched_control is None
            or control_applicability.status
            is not AggregationControlApplicabilityStatus.APPLIES
            or control_applicability.latched_control != control.latched_control
        ):
            raise ExecutionAggregationProjectionError(
                "EXECUTION_RESULT_CONTROL_PROVENANCE_MISSING"
            )

        latched = control.latched_control
        signal = latched.signal
        expected_type = {
            ExecutionPlanStatus.CANCELLED: ExecutionControlSignalType.CANCEL,
            ExecutionPlanStatus.PREEMPTED: ExecutionControlSignalType.PREEMPT,
        }[plan_status]
        if (
            signal.signal_type is not expected_type
            or signal.target_execution_id != execution_id
        ):
            raise ExecutionAggregationProjectionError(
                "EXECUTION_RESULT_CONTROL_PROVENANCE_MISMATCH"
            )

        return _control_payload(latched)


class ExecutionAggregator:
    """CA-03 integration boundary for natural commit and terminal replay."""

    def __init__(
        self,
        *,
        authority: ExecutionAggregationAuthority,
        lifecycle_service: ExecutionLifecycleService,
        projector: CanonicalExecutionResultProjector,
    ) -> None:
        self._authority = authority
        self._lifecycle_service = lifecycle_service
        self._projector = projector

    async def aggregate(
        self,
        *,
        approved_plan: ApprovedActionPlan,
        prepared: PreparedExecution,
        control: DurableControlReadDecision,
        control_applicability: AggregationControlApplicabilityDecision,
        at: datetime,
    ) -> ExecutionAggregationRunResult:
        evidence_readiness, skip_decisions = project_ca01_evidence_inputs(
            approved_plan=approved_plan,
            prepared=prepared,
        )
        eligibility = self._authority.evaluate(
            approved_plan=approved_plan,
            prepared=prepared,
            control=control,
            control_applicability=control_applicability,
            evidence_readiness=evidence_readiness,
            skip_decisions=skip_decisions,
        )
        if eligibility.status not in {
            ExecutionAggregationEligibilityStatus.READY_NATURAL,
            ExecutionAggregationEligibilityStatus.READY_EXISTING_TERMINAL,
        }:
            raise ExecutionAggregationProjectionError(
                eligibility.reason_codes[0],
                "execution is not eligible for Canonical aggregation",
            )

        current = prepared
        if (
            eligibility.status
            is ExecutionAggregationEligibilityStatus.READY_NATURAL
        ):
            decision = eligibility.aggregation_decision
            if decision is None:
                raise ExecutionAggregationProjectionError(
                    "EXECUTION_RESULT_AGGREGATION_DECISION_MISSING"
                )
            current = await self._lifecycle_service.finish_execution(
                prepared,
                status=decision.plan_status,
                at=at,
            )
            evidence_readiness, skip_decisions = project_ca01_evidence_inputs(
                approved_plan=approved_plan,
                prepared=current,
            )
            eligibility = self._authority.evaluate(
                approved_plan=approved_plan,
                prepared=current,
                control=control,
                control_applicability=control_applicability,
                evidence_readiness=evidence_readiness,
                skip_decisions=skip_decisions,
            )
            if (
                eligibility.status
                is not ExecutionAggregationEligibilityStatus.READY_EXISTING_TERMINAL
            ):
                raise ExecutionAggregationProjectionError(
                    "EXECUTION_RESULT_TERMINAL_REPLAY_RECHECK_FAILED"
                )

        execution_result = await self._projector.project(
            approved_plan=approved_plan,
            prepared=current,
            eligibility=eligibility,
            control=control,
            control_applicability=control_applicability,
        )
        return ExecutionAggregationRunResult(
            prepared=current,
            eligibility=eligibility,
            execution_result=execution_result,
        )

def _project_step_result(step: StepLifecycleSnapshot) -> StepExecutionResult:
    return StepExecutionResult(
        step_execution_id=step.step_execution_id,
        step_id=step.step_id,
        action=step.action,
        status=step.status.value,
        skill_id=step.skill_id,
        workflow_id=step.workflow_id,
        tool_call_ids=list(step.tool_call_ids) or None,
        output=deepcopy(step.output),
        error=step.error,
        retry_count=step.retry_count,
        started_at=step.started_at,
        finished_at=step.finished_at,
    )


def _project_step_timing(
    *,
    step: StepLifecycleSnapshot,
    plan_index: int,
) -> dict[str, Any]:
    duration_ms: float | None = None
    if step.started_at is not None and step.finished_at is not None:
        duration_ms = _duration_ms(
            step.started_at,
            step.finished_at,
            "EXECUTION_RESULT_STEP_TIMING_INVALID",
        )
    return {
        "plan_index": plan_index,
        "step_id": step.step_id,
        "step_execution_id": step.step_execution_id,
        "started_at": step.started_at,
        "finished_at": step.finished_at,
        "duration_ms": duration_ms,
    }


def _collect_tool_result(
    *,
    entry: Mapping[str, Any] | ToolInvocationJournalEntry,
    step: StepLifecycleSnapshot,
    plan_index: int,
    source_index: int,
    seen_tool_journal: dict[str, dict[str, Any]],
    tool_results: list[dict[str, Any]],
    tool_durations: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> None:
    frozen = _freeze_projection_value(entry)
    if not isinstance(frozen, dict):
        raise ExecutionAggregationProjectionError(
            "EXECUTION_RESULT_TOOL_JOURNAL_INVALID"
        )
    tool_call_id = frozen.get("tool_call_id")
    result = frozen.get("result")
    if (
        not isinstance(tool_call_id, str)
        or not tool_call_id.strip()
        or not isinstance(result, Mapping)
    ):
        raise ExecutionAggregationProjectionError(
            "EXECUTION_RESULT_TOOL_JOURNAL_INVALID"
        )

    frozen_entry = frozen
    existing = seen_tool_journal.get(tool_call_id)
    if existing is not None:
        if existing != frozen_entry:
            raise ExecutionAggregationProjectionError(
                "EXECUTION_RESULT_TOOL_CALL_CONFLICT"
            )
        return
    seen_tool_journal[tool_call_id] = frozen_entry

    result_payload = deepcopy(dict(result))
    tool_results.append(result_payload)

    started_at = result_payload.get("started_at")
    finished_at = result_payload.get("finished_at")
    duration_ms: float | None = None
    if isinstance(started_at, datetime) and isinstance(finished_at, datetime):
        duration_ms = _duration_ms(
            started_at,
            finished_at,
            "EXECUTION_RESULT_TOOL_TIMING_INVALID",
        )
    tool_durations.append(
        {
            "plan_index": plan_index,
            "source_index": source_index,
            "step_id": step.step_id,
            "tool_call_id": tool_call_id,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_ms": duration_ms,
        }
    )

    error_code = result_payload.get("error_code")
    error_message = result_payload.get("error_message")
    if error_code or error_message:
        errors.append(
            {
                "source": "TOOL",
                "step_id": step.step_id,
                "tool_call_id": tool_call_id,
                "tool_id": result_payload.get("tool_id"),
                "error_code": error_code,
                "message": error_message,
            }
        )


def _freeze_projection_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _freeze_projection_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ExecutionAggregationProjectionError(
                "EXECUTION_RESULT_TOOL_JOURNAL_INVALID"
            )
        return {
            key: _freeze_projection_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [_freeze_projection_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise ExecutionAggregationProjectionError(
        "EXECUTION_RESULT_TOOL_JOURNAL_INVALID"
    )


def _control_payload(latched: LatchedExecutionControl) -> dict[str, Any]:
    signal = latched.signal
    is_cancel = signal.signal_type is ExecutionControlSignalType.CANCEL
    is_preempt = signal.signal_type is ExecutionControlSignalType.PREEMPT
    return {
        "signal_type": signal.signal_type.value,
        "signal_id": signal.signal_id,
        "reason_code": signal.reason_code,
        "source": signal.source,
        "target_execution_id": signal.target_execution_id,
        "requested_at": signal.issued_at,
        "observed_at": latched.observed_at,
        "latched_at": latched.latched_at,
        "cancelled": is_cancel,
        "preempted": is_preempt,
    }


def _duration_ms(
    started_at: datetime,
    finished_at: datetime,
    reason_code: str,
) -> float:
    _require_time_order(started_at, finished_at, reason_code)
    return (finished_at - started_at).total_seconds() * 1000.0


def _require_time_order(
    started_at: datetime,
    finished_at: datetime,
    reason_code: str,
) -> None:
    if (
        started_at.tzinfo is None
        or started_at.utcoffset() is None
        or finished_at.tzinfo is None
        or finished_at.utcoffset() is None
        or finished_at < started_at
    ):
        raise ExecutionAggregationProjectionError(reason_code)
