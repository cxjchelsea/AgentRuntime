"""M5-IU5 result collection and step-attempt observation.

This module is deliberately observational. It classifies facts already produced by
IU4 without invoking capabilities, consulting registries, mutating lifecycle state,
persisting stores, deciding retries, aggregating a plan, or entering M6.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from runtime.execution.capability_execution import (
    CapabilityExecutionStatus,
    StepCapabilityExecutionOutcome,
)
from runtime.execution.capability_resolution import CapabilityExecutionOwner
from runtime.execution.foundation import StepLifecycleSnapshot
from runtime.execution.invocation import ToolInvocationJournalEntry
from runtime.execution.models import (
    M5SkillResult,
    M5ToolResult,
    M5WorkflowResult,
    SkillExecutionStatus,
    StepExecutionStatus,
    ToolExecutionStatus,
    WorkflowExecutionStatus,
)


class StepAttemptStatus(str, Enum):
    """One capability-execution attempt observation, not terminal Step lifecycle."""

    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"
    WAITING = "WAITING"
    IN_PROGRESS = "IN_PROGRESS"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    PREEMPTED = "PREEMPTED"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"
    NO_EXTERNAL_EXECUTION = "NO_EXTERNAL_EXECUTION"


@dataclass(frozen=True, slots=True)
class StepAttemptObservation:
    """M5-internal evidence collected from one IU4 capability execution attempt."""

    step_id: str
    step_execution_id: str
    attempt_number: int
    status: StepAttemptStatus
    execution_owner: CapabilityExecutionOwner
    reason_codes: tuple[str, ...]
    observed_at: datetime
    owner_capability_id: str | None = None
    owner_capability_version: str | None = None
    skill_result: M5SkillResult | None = None
    workflow_result: M5WorkflowResult | None = None
    tool_results: tuple[M5ToolResult, ...] = ()
    tool_journal: tuple[ToolInvocationJournalEntry, ...] = ()
    business_outputs: tuple[dict[str, Any], ...] = ()
    capability_events: tuple[dict[str, Any], ...] = ()
    has_non_success_tool_observation: bool = False
    has_unknown_tool_observation: bool = False
    has_untrusted_success_observation: bool = False

    def __post_init__(self) -> None:
        if not self.step_id.strip() or not self.step_execution_id.strip():
            raise ValueError("step attempt identifiers must not be blank")
        if self.attempt_number < 1:
            raise ValueError("attempt_number must be >= 1")
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        if (self.owner_capability_id is None) != (
            self.owner_capability_version is None
        ):
            raise ValueError("owner capability id/version must be present together")
        if self.skill_result is not None and self.workflow_result is not None:
            raise ValueError(
                "one step attempt cannot carry both Skill and Workflow result"
            )
        if self.tool_results != tuple(entry.result for entry in self.tool_journal):
            raise ValueError("tool_results must exactly match the Core Tool journal")

        non_success = any(
            item.status is not ToolExecutionStatus.SUCCESS
            for item in self.tool_results
        )
        unknown = any(
            item.status is ToolExecutionStatus.UNKNOWN for item in self.tool_results
        )
        untrusted_success = any(
            entry.raw_result is not None
            and entry.raw_result.status is ToolExecutionStatus.SUCCESS
            and entry.result.status is ToolExecutionStatus.UNKNOWN
            for entry in self.tool_journal
        )
        if self.has_non_success_tool_observation is not non_success:
            raise ValueError("non-success Tool evidence flag is inconsistent")
        if self.has_unknown_tool_observation is not unknown:
            raise ValueError("unknown Tool evidence flag is inconsistent")
        if self.has_untrusted_success_observation is not untrusted_success:
            raise ValueError("untrusted-success Tool evidence flag is inconsistent")


class StepResultCollectionError(RuntimeError):
    """Structural/integration fault at the IU5 collection boundary."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        if not reason_code.strip():
            raise ValueError("reason_code must not be blank")
        self.reason_code = reason_code


class StepResultCollector:
    """Collect one IU4 outcome into an M5-internal attempt observation."""

    _SKILL_STATUS_MAP = {
        SkillExecutionStatus.SUCCESS: StepAttemptStatus.SUCCESS,
        SkillExecutionStatus.PARTIAL_SUCCESS: StepAttemptStatus.PARTIAL_SUCCESS,
        SkillExecutionStatus.FAILED: StepAttemptStatus.FAILED,
        SkillExecutionStatus.CANCELLED: StepAttemptStatus.CANCELLED,
        SkillExecutionStatus.TIMEOUT: StepAttemptStatus.TIMEOUT,
        SkillExecutionStatus.PREEMPTED: StepAttemptStatus.PREEMPTED,
    }

    _WORKFLOW_STATUS_MAP = {
        WorkflowExecutionStatus.COMPLETED: StepAttemptStatus.SUCCESS,
        WorkflowExecutionStatus.FAILED: StepAttemptStatus.FAILED,
        WorkflowExecutionStatus.CANCELLED: StepAttemptStatus.CANCELLED,
        WorkflowExecutionStatus.TIMEOUT: StepAttemptStatus.TIMEOUT,
        WorkflowExecutionStatus.PREEMPTED: StepAttemptStatus.PREEMPTED,
        WorkflowExecutionStatus.WAITING: StepAttemptStatus.WAITING,
        WorkflowExecutionStatus.RUNNING: StepAttemptStatus.IN_PROGRESS,
        WorkflowExecutionStatus.CREATED: StepAttemptStatus.IN_PROGRESS,
    }

    def collect(
        self,
        *,
        step_snapshot: StepLifecycleSnapshot,
        outcome: StepCapabilityExecutionOutcome,
        attempt_number: int,
        observed_at: datetime,
    ) -> StepAttemptObservation:
        self._validate_collection_envelope(
            step_snapshot=step_snapshot,
            outcome=outcome,
            attempt_number=attempt_number,
            observed_at=observed_at,
        )
        self._validate_tool_truth(outcome)

        status, collector_reasons = self._classify(outcome)
        business_outputs, capability_events = self._collect_owner_payloads(outcome)
        tool_results = outcome.tool_results
        tool_journal = outcome.tool_journal

        return StepAttemptObservation(
            step_id=outcome.step_id,
            step_execution_id=outcome.step_execution_id,
            attempt_number=attempt_number,
            status=status,
            execution_owner=outcome.execution_owner,
            reason_codes=self._append_reason_codes(
                outcome.reason_codes,
                collector_reasons,
                ("RESULT_COLLECTED",),
            ),
            observed_at=observed_at,
            owner_capability_id=outcome.owner_capability_id,
            owner_capability_version=outcome.owner_capability_version,
            skill_result=outcome.skill_result,
            workflow_result=outcome.workflow_result,
            tool_results=tool_results,
            tool_journal=tool_journal,
            business_outputs=business_outputs,
            capability_events=capability_events,
            has_non_success_tool_observation=any(
                item.status is not ToolExecutionStatus.SUCCESS
                for item in tool_results
            ),
            has_unknown_tool_observation=any(
                item.status is ToolExecutionStatus.UNKNOWN for item in tool_results
            ),
            has_untrusted_success_observation=any(
                entry.raw_result is not None
                and entry.raw_result.status is ToolExecutionStatus.SUCCESS
                and entry.result.status is ToolExecutionStatus.UNKNOWN
                for entry in tool_journal
            ),
        )

    @staticmethod
    def _validate_collection_envelope(
        *,
        step_snapshot: StepLifecycleSnapshot,
        outcome: StepCapabilityExecutionOutcome,
        attempt_number: int,
        observed_at: datetime,
    ) -> None:
        if step_snapshot.status is not StepExecutionStatus.RUNNING:
            raise StepResultCollectionError(
                "RESULT_COLLECTION_STEP_NOT_RUNNING",
                "IU5 can collect results only for a RUNNING step",
            )
        if step_snapshot.started_at is None:
            raise StepResultCollectionError(
                "RESULT_COLLECTION_START_TIME_MISSING",
                "RUNNING step requires started_at before result collection",
            )
        if (
            outcome.step_id != step_snapshot.step_id
            or outcome.step_execution_id != step_snapshot.step_execution_id
        ):
            raise StepResultCollectionError(
                "RESULT_COLLECTION_IDENTITY_MISMATCH",
                "IU4 outcome does not belong to the supplied step snapshot",
            )
        if attempt_number < 1:
            raise StepResultCollectionError(
                "RESULT_COLLECTION_ATTEMPT_INVALID",
                "attempt_number must be >= 1",
            )
        try:
            if observed_at < step_snapshot.started_at:
                raise StepResultCollectionError(
                    "RESULT_COLLECTION_TIME_INVALID",
                    "observed_at cannot precede the step start time",
                )
        except TypeError as exc:
            raise StepResultCollectionError(
                "RESULT_COLLECTION_TIME_INVALID",
                "observed_at and step started_at are not comparable",
            ) from exc

    @staticmethod
    def _validate_tool_truth(outcome: StepCapabilityExecutionOutcome) -> None:
        journal_results = tuple(entry.result for entry in outcome.tool_journal)
        if outcome.tool_results != journal_results:
            raise StepResultCollectionError(
                "RESULT_COLLECTION_TOOL_TRUTH_MISMATCH",
                "IU4 tool_results must exactly match the Core Tool journal",
            )

    def _classify(
        self,
        outcome: StepCapabilityExecutionOutcome,
    ) -> tuple[StepAttemptStatus, tuple[str, ...]]:
        if outcome.status is CapabilityExecutionStatus.BLOCKED:
            return StepAttemptStatus.BLOCKED, ()
        if outcome.status is CapabilityExecutionStatus.UNKNOWN:
            return StepAttemptStatus.UNKNOWN, ()
        if outcome.status is CapabilityExecutionStatus.NO_EXTERNAL_EXECUTION:
            return StepAttemptStatus.NO_EXTERNAL_EXECUTION, ()
        if outcome.status is CapabilityExecutionStatus.WAITING:
            if (
                outcome.execution_owner is CapabilityExecutionOwner.WORKFLOW
                and outcome.workflow_result is not None
                and outcome.workflow_result.status
                is WorkflowExecutionStatus.WAITING
            ):
                return StepAttemptStatus.WAITING, ()
            return (
                StepAttemptStatus.UNKNOWN,
                ("RESULT_COLLECTION_OWNER_RESULT_INCONSISTENT",),
            )

        if outcome.status is not CapabilityExecutionStatus.EXECUTED:
            return (
                StepAttemptStatus.UNKNOWN,
                ("RESULT_COLLECTION_OWNER_RESULT_INCONSISTENT",),
            )

        if any(
            item.status is ToolExecutionStatus.UNKNOWN
            for item in outcome.tool_results
        ):
            return (
                StepAttemptStatus.UNKNOWN,
                ("TOOL_UNKNOWN_NOT_PROPAGATED",),
            )

        if outcome.execution_owner is CapabilityExecutionOwner.SKILL:
            return self._classify_skill(outcome)
        if outcome.execution_owner is CapabilityExecutionOwner.WORKFLOW:
            return self._classify_workflow(outcome)

        return (
            StepAttemptStatus.UNKNOWN,
            ("RESULT_COLLECTION_OWNER_RESULT_INCONSISTENT",),
        )

    def _classify_skill(
        self,
        outcome: StepCapabilityExecutionOutcome,
    ) -> tuple[StepAttemptStatus, tuple[str, ...]]:
        result = outcome.skill_result
        if (
            result is None
            or outcome.workflow_result is not None
            or not isinstance(result.status, SkillExecutionStatus)
            or outcome.owner_capability_id != result.skill_id
        ):
            return (
                StepAttemptStatus.UNKNOWN,
                ("RESULT_COLLECTION_OWNER_RESULT_INCONSISTENT",),
            )
        status = self._SKILL_STATUS_MAP.get(result.status)
        if status is None:
            return (
                StepAttemptStatus.UNKNOWN,
                ("RESULT_COLLECTION_OWNER_RESULT_INCONSISTENT",),
            )
        return status, ()

    def _classify_workflow(
        self,
        outcome: StepCapabilityExecutionOutcome,
    ) -> tuple[StepAttemptStatus, tuple[str, ...]]:
        result = outcome.workflow_result
        if (
            result is None
            or outcome.skill_result is not None
            or not isinstance(result.status, WorkflowExecutionStatus)
            or outcome.owner_capability_id != result.workflow_id
        ):
            return (
                StepAttemptStatus.UNKNOWN,
                ("RESULT_COLLECTION_OWNER_RESULT_INCONSISTENT",),
            )
        status = self._WORKFLOW_STATUS_MAP.get(result.status)
        if status is None:
            return (
                StepAttemptStatus.UNKNOWN,
                ("RESULT_COLLECTION_OWNER_RESULT_INCONSISTENT",),
            )
        if (
            result.status is WorkflowExecutionStatus.WAITING
            and outcome.status is not CapabilityExecutionStatus.WAITING
        ):
            return (
                StepAttemptStatus.UNKNOWN,
                ("RESULT_COLLECTION_OWNER_RESULT_INCONSISTENT",),
            )
        return status, ()

    @staticmethod
    def _collect_owner_payloads(
        outcome: StepCapabilityExecutionOutcome,
    ) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
        if outcome.skill_result is not None:
            return (
                tuple(dict(item) for item in outcome.skill_result.business_outputs),
                tuple(dict(item) for item in outcome.skill_result.events),
            )
        if outcome.workflow_result is not None:
            outputs = (
                (dict(outcome.workflow_result.important_outputs),)
                if outcome.workflow_result.important_outputs
                else ()
            )
            return outputs, ()
        return (), ()

    @staticmethod
    def _append_reason_codes(
        base: tuple[str, ...],
        *extras: tuple[str, ...],
    ) -> tuple[str, ...]:
        merged = list(base)
        for group in extras:
            for reason in group:
                if reason not in merged:
                    merged.append(reason)
        return tuple(merged)
