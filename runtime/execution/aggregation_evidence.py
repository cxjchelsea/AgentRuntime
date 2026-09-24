"""CA-M5-IU10-02 crash-safe terminal Step aggregation evidence.

The evidence object is a Core-owned terminal observation. It contains only frozen,
recovery-safe values and never carries live Runtime objects, credentials, handles,
implementations, or mutable registries.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Mapping

from runtime.execution.models import StepExecutionStatus

if TYPE_CHECKING:
    from runtime.execution.aggregation_authority import (
        AggregationEvidenceReadinessDecision,
        StepSkipAggregationDecision,
    )
    from runtime.execution.foundation import PreparedExecution, StepLifecycleSnapshot
    from runtime.execution.result_collection import StepAttemptObservation


AGGREGATION_EVIDENCE_SCHEMA_VERSION = "m5-iu10-ca02-v1"


class StepAggregationTerminalizationKind(str, Enum):
    ATTEMPT_FINALIZED = "ATTEMPT_FINALIZED"
    SCHEDULER_SKIPPED = "SCHEDULER_SKIPPED"
    CONTROL_TERMINALIZED = "CONTROL_TERMINALIZED"


class StepAggregationEvidenceReadStatus(str, Enum):
    READY = "READY"
    MISSING = "MISSING"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class StepAggregationEvidence:
    schema_version: str
    execution_id: str
    step_execution_id: str
    step_id: str
    terminalization_kind: StepAggregationTerminalizationKind
    terminal_step_status: StepExecutionStatus
    terminal_reason_codes: tuple[str, ...]
    degraded: bool
    observed_at: datetime
    terminalized_at: datetime
    final_attempt_number: int | None = None
    final_attempt_status: str | None = None
    final_attempt_reason_codes: tuple[str, ...] = ()
    execution_owner: str | None = None
    owner_capability_id: str | None = None
    owner_capability_version: str | None = None
    skill_result: dict[str, Any] | None = None
    workflow_result: dict[str, Any] | None = None
    tool_call_ids: tuple[str, ...] = ()
    tool_journal: tuple[dict[str, Any], ...] = ()
    business_outputs: tuple[dict[str, Any], ...] = ()
    capability_events: tuple[dict[str, Any], ...] = ()
    has_non_success_tool_observation: bool = False
    has_unknown_tool_observation: bool = False
    has_untrusted_success_observation: bool = False
    scheduler_skip_disposition: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != AGGREGATION_EVIDENCE_SCHEMA_VERSION:
            raise ValueError("unsupported aggregation evidence schema_version")
        values = (self.execution_id, self.step_execution_id, self.step_id)
        if any(not value.strip() for value in values):
            raise ValueError("aggregation evidence identifiers must not be blank")
        if not isinstance(
            self.terminalization_kind,
            StepAggregationTerminalizationKind,
        ):
            raise ValueError(
                "terminalization_kind must be StepAggregationTerminalizationKind"
            )  # noqa: TRY004
        if not isinstance(self.terminal_step_status, StepExecutionStatus):
            raise ValueError(
                "terminal_step_status must be StepExecutionStatus"
            )  # noqa: TRY004
        if self.terminal_step_status in {
            StepExecutionStatus.PENDING,
            StepExecutionStatus.RUNNING,
        }:
            raise ValueError("aggregation evidence requires terminal Step status")
        if not self.terminal_reason_codes or any(
            not reason.strip() for reason in self.terminal_reason_codes
        ):
            raise ValueError(
                "aggregation evidence requires non-blank terminal_reason_codes"
            )
        _require_aware(self.observed_at, "observed_at")
        _require_aware(self.terminalized_at, "terminalized_at")
        if self.terminalized_at < self.observed_at:
            raise ValueError("terminalized_at cannot precede observed_at")
        if self.degraded and self.terminal_step_status is not StepExecutionStatus.SUCCESS:
            raise ValueError("degraded terminal evidence requires SUCCESS Step status")
        if any(not reason.strip() for reason in self.final_attempt_reason_codes):
            raise ValueError(
                "final_attempt_reason_codes must not contain blank values"
            )
        if (self.owner_capability_id is None) != (
            self.owner_capability_version is None
        ):
            raise ValueError("owner capability id/version must be present together")
        if self.skill_result is not None and self.workflow_result is not None:
            raise ValueError(
                "one terminal Step cannot carry both Skill and Workflow final result"
            )
        if any(not item.strip() for item in self.tool_call_ids):
            raise ValueError("tool_call_ids must not contain blank values")
        if len(set(self.tool_call_ids)) != len(self.tool_call_ids):
            raise ValueError("tool_call_ids must be unique in terminal evidence")
        journal_ids = tuple(
            str(entry.get("tool_call_id", "")) for entry in self.tool_journal
        )
        if any(not value.strip() for value in journal_ids):
            raise ValueError("tool_journal entries require tool_call_id")
        if len(set(journal_ids)) != len(journal_ids):
            raise ValueError("tool_journal tool_call_id values must be unique")
        derived_non_success = False
        derived_unknown = False
        derived_untrusted_success = False
        for entry in self.tool_journal:
            tool_call_id = entry.get("tool_call_id")
            tool_id = entry.get("tool_id")
            result = entry.get("result")
            if (
                not isinstance(tool_call_id, str)
                or not tool_call_id.strip()
                or not isinstance(tool_id, str)
                or not tool_id.strip()
                or not isinstance(result, Mapping)
            ):
                raise ValueError("tool_journal entry structure is invalid")
            if (
                result.get("tool_call_id") != tool_call_id
                or result.get("tool_id") != tool_id
            ):
                raise ValueError("tool_journal result identity mismatch")
            result_status = result.get("status")
            if not isinstance(result_status, str) or not result_status.strip():
                raise ValueError("tool_journal result status is invalid")
            if result_status != "SUCCESS":
                derived_non_success = True
            if result_status == "UNKNOWN":
                derived_unknown = True
            raw_result = entry.get("raw_result")
            if raw_result is not None:
                if not isinstance(raw_result, Mapping):
                    raise ValueError("tool_journal raw_result must be mapping")
                if (
                    raw_result.get("tool_call_id") != tool_call_id
                    or raw_result.get("tool_id") != tool_id
                ):
                    raise ValueError("tool_journal raw_result identity mismatch")
                if (
                    raw_result.get("status") == "SUCCESS"
                    and result_status == "UNKNOWN"
                ):
                    derived_untrusted_success = True
        if self.has_non_success_tool_observation is not derived_non_success:
            raise ValueError("non-success Tool evidence flag is inconsistent")
        if self.has_unknown_tool_observation is not derived_unknown:
            raise ValueError("unknown Tool evidence flag is inconsistent")
        if self.has_untrusted_success_observation is not derived_untrusted_success:
            raise ValueError("untrusted-success Tool evidence flag is inconsistent")

        if (
            self.terminalization_kind
            is StepAggregationTerminalizationKind.ATTEMPT_FINALIZED
        ):
            self._validate_attempt_finalized(journal_ids)
        elif (
            self.terminalization_kind
            is StepAggregationTerminalizationKind.SCHEDULER_SKIPPED
        ):
            self._validate_scheduler_skipped()
        else:
            self._validate_control_terminalized()

    def _validate_attempt_finalized(self, journal_ids: tuple[str, ...]) -> None:
        if self.terminal_step_status not in {
            StepExecutionStatus.SUCCESS,
            StepExecutionStatus.FAILED,
            StepExecutionStatus.TIMEOUT,
        }:
            raise ValueError(
                "ATTEMPT_FINALIZED supports SUCCESS/FAILED/TIMEOUT lifecycle only"
            )
        if self.final_attempt_number is None or self.final_attempt_number < 1:
            raise ValueError("ATTEMPT_FINALIZED requires final_attempt_number >= 1")
        if self.final_attempt_status is None or not self.final_attempt_status.strip():
            raise ValueError("ATTEMPT_FINALIZED requires final_attempt_status")
        if not self.final_attempt_reason_codes:
            raise ValueError(
                "ATTEMPT_FINALIZED requires final_attempt_reason_codes"
            )
        expected_attempt_status = {
            (StepExecutionStatus.SUCCESS, False): "SUCCESS",
            (StepExecutionStatus.SUCCESS, True): "PARTIAL_SUCCESS",
            (StepExecutionStatus.FAILED, False): "FAILED",
            (StepExecutionStatus.TIMEOUT, False): "TIMEOUT",
        }.get((self.terminal_step_status, self.degraded))
        if self.final_attempt_status != expected_attempt_status:
            raise ValueError(
                "ATTEMPT_FINALIZED final attempt status must match terminal lifecycle"
            )
        if self.execution_owner is None or not self.execution_owner.strip():
            raise ValueError("ATTEMPT_FINALIZED requires execution_owner")
        if self.scheduler_skip_disposition is not None:
            raise ValueError(
                "ATTEMPT_FINALIZED cannot carry scheduler_skip_disposition"
            )
        if journal_ids != self.tool_call_ids:
            raise ValueError(
                "ATTEMPT_FINALIZED tool_call_ids must equal Tool journal order"
            )

    def _validate_scheduler_skipped(self) -> None:
        if self.terminal_step_status is not StepExecutionStatus.SKIPPED:
            raise ValueError("SCHEDULER_SKIPPED requires SKIPPED Step status")
        if self.final_attempt_number is not None:
            raise ValueError("SCHEDULER_SKIPPED cannot carry final_attempt_number")
        if self.final_attempt_status is not None or self.final_attempt_reason_codes:
            raise ValueError("SCHEDULER_SKIPPED cannot carry final attempt evidence")
        if self.execution_owner is not None:
            raise ValueError("SCHEDULER_SKIPPED cannot carry execution_owner")
        if self.owner_capability_id is not None:
            raise ValueError("SCHEDULER_SKIPPED cannot carry owner capability")
        if self.skill_result is not None or self.workflow_result is not None:
            raise ValueError("SCHEDULER_SKIPPED cannot carry owner result")
        if self.tool_call_ids or self.tool_journal:
            raise ValueError("SCHEDULER_SKIPPED cannot carry Tool execution evidence")
        if (
            self.has_non_success_tool_observation
            or self.has_unknown_tool_observation
            or self.has_untrusted_success_observation
        ):
            raise ValueError("SCHEDULER_SKIPPED cannot carry Tool truth flags")
        if self.business_outputs or self.capability_events:
            raise ValueError(
                "SCHEDULER_SKIPPED cannot carry capability-produced payloads"
            )
        if self.scheduler_skip_disposition not in {
            "NOT_APPLICABLE",
            "UNSATISFIED",
        }:
            raise ValueError(
                "SCHEDULER_SKIPPED requires explicit skip disposition"
            )

    def _validate_control_terminalized(self) -> None:
        if self.terminal_step_status not in {
            StepExecutionStatus.CANCELLED,
            StepExecutionStatus.PREEMPTED,
        }:
            raise ValueError(
                "CONTROL_TERMINALIZED requires CANCELLED/PREEMPTED Step status"
            )
        if self.final_attempt_number is not None:
            raise ValueError("CONTROL_TERMINALIZED cannot invent final attempt")
        if self.final_attempt_status is not None or self.final_attempt_reason_codes:
            raise ValueError("CONTROL_TERMINALIZED cannot invent final attempt evidence")
        if self.execution_owner is not None:
            raise ValueError("CONTROL_TERMINALIZED cannot invent execution owner")
        if self.owner_capability_id is not None:
            raise ValueError("CONTROL_TERMINALIZED cannot invent owner capability")
        if self.skill_result is not None or self.workflow_result is not None:
            raise ValueError("CONTROL_TERMINALIZED cannot invent owner final result")
        if self.tool_journal:
            raise ValueError(
                "CONTROL_TERMINALIZED does not reconstruct live Tool journal in CA-02"
            )
        if (
            self.has_non_success_tool_observation
            or self.has_unknown_tool_observation
            or self.has_untrusted_success_observation
        ):
            raise ValueError("CONTROL_TERMINALIZED cannot invent Tool truth flags")
        if self.business_outputs or self.capability_events:
            raise ValueError(
                "CONTROL_TERMINALIZED cannot invent capability payloads"
            )
        if self.scheduler_skip_disposition is not None:
            raise ValueError(
                "CONTROL_TERMINALIZED cannot carry scheduler skip disposition"
            )

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "execution_id": self.execution_id,
            "step_execution_id": self.step_execution_id,
            "step_id": self.step_id,
            "terminalization_kind": self.terminalization_kind.value,
            "terminal_step_status": self.terminal_step_status.value,
            "terminal_reason_codes": list(self.terminal_reason_codes),
            "degraded": self.degraded,
            "observed_at": self.observed_at,
            "terminalized_at": self.terminalized_at,
            "final_attempt_number": self.final_attempt_number,
            "final_attempt_status": self.final_attempt_status,
            "final_attempt_reason_codes": list(self.final_attempt_reason_codes),
            "execution_owner": self.execution_owner,
            "owner_capability_id": self.owner_capability_id,
            "owner_capability_version": self.owner_capability_version,
            "skill_result": deepcopy(self.skill_result),
            "workflow_result": deepcopy(self.workflow_result),
            "tool_call_ids": list(self.tool_call_ids),
            "tool_journal": deepcopy(list(self.tool_journal)),
            "business_outputs": deepcopy(list(self.business_outputs)),
            "capability_events": deepcopy(list(self.capability_events)),
            "has_non_success_tool_observation": self.has_non_success_tool_observation,
            "has_unknown_tool_observation": self.has_unknown_tool_observation,
            "has_untrusted_success_observation": (
                self.has_untrusted_success_observation
            ),
            "scheduler_skip_disposition": self.scheduler_skip_disposition,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "StepAggregationEvidence":
        try:
            return cls(
                schema_version=str(payload["schema_version"]),
                execution_id=str(payload["execution_id"]),
                step_execution_id=str(payload["step_execution_id"]),
                step_id=str(payload["step_id"]),
                terminalization_kind=StepAggregationTerminalizationKind(
                    str(payload["terminalization_kind"])
                ),
                terminal_step_status=StepExecutionStatus(
                    str(payload["terminal_step_status"])
                ),
                terminal_reason_codes=tuple(
                    str(item) for item in payload["terminal_reason_codes"]
                ),
                degraded=bool(payload["degraded"]),
                observed_at=payload["observed_at"],
                terminalized_at=payload["terminalized_at"],
                final_attempt_number=_optional_int(
                    payload.get("final_attempt_number")
                ),
                final_attempt_status=_optional_str(
                    payload.get("final_attempt_status")
                ),
                final_attempt_reason_codes=tuple(
                    str(item)
                    for item in payload.get("final_attempt_reason_codes", ())
                ),
                execution_owner=_optional_str(payload.get("execution_owner")),
                owner_capability_id=_optional_str(
                    payload.get("owner_capability_id")
                ),
                owner_capability_version=_optional_str(
                    payload.get("owner_capability_version")
                ),
                skill_result=_optional_dict(payload.get("skill_result")),
                workflow_result=_optional_dict(payload.get("workflow_result")),
                tool_call_ids=tuple(
                    str(item) for item in payload.get("tool_call_ids", ())
                ),
                tool_journal=_tuple_of_dicts(payload.get("tool_journal", ())),
                business_outputs=_tuple_of_dicts(
                    payload.get("business_outputs", ())
                ),
                capability_events=_tuple_of_dicts(
                    payload.get("capability_events", ())
                ),
                has_non_success_tool_observation=bool(
                    payload.get("has_non_success_tool_observation", False)
                ),
                has_unknown_tool_observation=bool(
                    payload.get("has_unknown_tool_observation", False)
                ),
                has_untrusted_success_observation=bool(
                    payload.get("has_untrusted_success_observation", False)
                ),
                scheduler_skip_disposition=_optional_str(
                    payload.get("scheduler_skip_disposition")
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid StepAggregationEvidence payload") from exc

    @classmethod
    def from_attempt_finalization(
        cls,
        *,
        execution_id: str,
        observation: "StepAttemptObservation",
        terminal_step_status: StepExecutionStatus,
        terminal_reason_codes: tuple[str, ...],
        degraded: bool,
        terminalized_at: datetime,
    ) -> "StepAggregationEvidence":
        return cls(
            schema_version=AGGREGATION_EVIDENCE_SCHEMA_VERSION,
            execution_id=execution_id,
            step_execution_id=observation.step_execution_id,
            step_id=observation.step_id,
            terminalization_kind=(
                StepAggregationTerminalizationKind.ATTEMPT_FINALIZED
            ),
            terminal_step_status=terminal_step_status,
            terminal_reason_codes=terminal_reason_codes,
            degraded=degraded,
            observed_at=observation.observed_at,
            terminalized_at=terminalized_at,
            final_attempt_number=observation.attempt_number,
            final_attempt_status=observation.status.value,
            final_attempt_reason_codes=observation.reason_codes,
            execution_owner=observation.execution_owner.value,
            owner_capability_id=observation.owner_capability_id,
            owner_capability_version=observation.owner_capability_version,
            skill_result=_freeze_optional_dataclass(observation.skill_result),
            workflow_result=_freeze_optional_dataclass(
                observation.workflow_result
            ),
            tool_call_ids=tuple(
                entry.tool_call_id for entry in observation.tool_journal
            ),
            tool_journal=tuple(
                _freeze_dataclass(entry) for entry in observation.tool_journal
            ),
            business_outputs=tuple(
                deepcopy(item) for item in observation.business_outputs
            ),
            capability_events=tuple(
                deepcopy(item) for item in observation.capability_events
            ),
            has_non_success_tool_observation=(
                observation.has_non_success_tool_observation
            ),
            has_unknown_tool_observation=observation.has_unknown_tool_observation,
            has_untrusted_success_observation=(
                observation.has_untrusted_success_observation
            ),
        )

    @classmethod
    def from_scheduler_skip(
        cls,
        *,
        execution_id: str,
        step_execution_id: str,
        step_id: str,
        terminal_reason_codes: tuple[str, ...],
        scheduler_skip_disposition: str,
        terminalized_at: datetime,
    ) -> "StepAggregationEvidence":
        return cls(
            schema_version=AGGREGATION_EVIDENCE_SCHEMA_VERSION,
            execution_id=execution_id,
            step_execution_id=step_execution_id,
            step_id=step_id,
            terminalization_kind=(
                StepAggregationTerminalizationKind.SCHEDULER_SKIPPED
            ),
            terminal_step_status=StepExecutionStatus.SKIPPED,
            terminal_reason_codes=terminal_reason_codes,
            degraded=False,
            observed_at=terminalized_at,
            terminalized_at=terminalized_at,
            scheduler_skip_disposition=scheduler_skip_disposition,
        )

    @classmethod
    def from_control_terminalization(
        cls,
        *,
        execution_id: str,
        step: "StepLifecycleSnapshot",
        terminal_step_status: StepExecutionStatus,
        terminal_reason_codes: tuple[str, ...],
        terminalized_at: datetime,
    ) -> "StepAggregationEvidence":
        return cls(
            schema_version=AGGREGATION_EVIDENCE_SCHEMA_VERSION,
            execution_id=execution_id,
            step_execution_id=step.step_execution_id,
            step_id=step.step_id,
            terminalization_kind=(
                StepAggregationTerminalizationKind.CONTROL_TERMINALIZED
            ),
            terminal_step_status=terminal_step_status,
            terminal_reason_codes=terminal_reason_codes,
            degraded=False,
            observed_at=terminalized_at,
            terminalized_at=terminalized_at,
            tool_call_ids=step.tool_call_ids,
        )


@dataclass(frozen=True, slots=True)
class StepAggregationEvidenceAssessment:
    status: StepAggregationEvidenceReadStatus
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.status, StepAggregationEvidenceReadStatus):
            raise ValueError(
                "status must be StepAggregationEvidenceReadStatus"
            )  # noqa: TRY004
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")


class StepAggregationEvidenceAuthority:
    """Validate crash-safe terminal evidence and project CA-01 input authorities."""

    def assess(
        self,
        prepared: "PreparedExecution",
    ) -> tuple[
        StepAggregationEvidenceAssessment,
        dict[str, "StepSkipAggregationDecision"],
    ]:
        from runtime.execution.aggregation_authority import (
            StepSkipAggregationDecision,
            StepSkipAggregationDisposition,
        )

        skip_decisions: dict[str, StepSkipAggregationDecision] = {}
        execution_id = prepared.execution_record.execution_id
        persisted_by_step: dict[str, Mapping[str, Any]] = {}
        for payload in prepared.execution_record.step_results:
            step_id = payload.get("step_id")
            if not isinstance(step_id, str) or not step_id.strip():
                return (
                    StepAggregationEvidenceAssessment(
                        status=StepAggregationEvidenceReadStatus.UNKNOWN,
                        reason_codes=(
                            "AGGREGATION_EVIDENCE_PERSISTED_STEP_ID_INVALID",
                        ),
                    ),
                    {},
                )
            if step_id in persisted_by_step:
                return (
                    StepAggregationEvidenceAssessment(
                        status=StepAggregationEvidenceReadStatus.UNKNOWN,
                        reason_codes=(
                            "AGGREGATION_EVIDENCE_PERSISTED_STEP_DUPLICATE",
                        ),
                    ),
                    {},
                )
            persisted_by_step[step_id] = payload

        if len(persisted_by_step) != len(prepared.steps):
            return (
                StepAggregationEvidenceAssessment(
                    status=StepAggregationEvidenceReadStatus.UNKNOWN,
                    reason_codes=("AGGREGATION_EVIDENCE_PERSISTED_STEP_COUNT_MISMATCH",),
                ),
                {},
            )

        for step in prepared.steps:
            if step.status in {
                StepExecutionStatus.PENDING,
                StepExecutionStatus.RUNNING,
            }:
                return (
                    StepAggregationEvidenceAssessment(
                        status=StepAggregationEvidenceReadStatus.UNKNOWN,
                        reason_codes=("AGGREGATION_EVIDENCE_STEP_NOT_TERMINAL",),
                    ),
                    {},
                )

            evidence = step.aggregation_evidence
            persisted = persisted_by_step.get(step.step_id)
            if persisted is None:
                return (
                    StepAggregationEvidenceAssessment(
                        status=StepAggregationEvidenceReadStatus.UNKNOWN,
                        reason_codes=(
                            "AGGREGATION_EVIDENCE_PERSISTED_STEP_MISSING",
                        ),
                    ),
                    {},
                )
            if evidence is None:
                if persisted.get("aggregation_evidence") is not None:
                    return (
                        StepAggregationEvidenceAssessment(
                            status=StepAggregationEvidenceReadStatus.UNKNOWN,
                            reason_codes=(
                                "AGGREGATION_EVIDENCE_TYPED_PERSISTED_MISMATCH",
                            ),
                        ),
                        {},
                    )
                return (
                    StepAggregationEvidenceAssessment(
                        status=StepAggregationEvidenceReadStatus.MISSING,
                        reason_codes=("AGGREGATION_EVIDENCE_TERMINAL_STEP_MISSING",),
                    ),
                    {},
                )

            persisted_evidence = persisted.get("aggregation_evidence")
            if persisted_evidence != evidence.to_payload():
                return (
                    StepAggregationEvidenceAssessment(
                        status=StepAggregationEvidenceReadStatus.UNKNOWN,
                        reason_codes=(
                            "AGGREGATION_EVIDENCE_PERSISTED_PAYLOAD_MISMATCH",
                        ),
                    ),
                    {},
                )

            reason = self._validate_step_evidence(
                execution_id=execution_id,
                step=step,
                evidence=evidence,
            )
            if reason is not None:
                return (
                    StepAggregationEvidenceAssessment(
                        status=StepAggregationEvidenceReadStatus.UNKNOWN,
                        reason_codes=(reason,),
                    ),
                    {},
                )

            if (
                evidence.terminalization_kind
                is StepAggregationTerminalizationKind.SCHEDULER_SKIPPED
            ):
                disposition = StepSkipAggregationDisposition(
                    evidence.scheduler_skip_disposition
                )
                skip_decisions[step.step_id] = StepSkipAggregationDecision(
                    execution_id=execution_id,
                    step_execution_id=step.step_execution_id,
                    step_id=step.step_id,
                    disposition=disposition,
                    reason_codes=evidence.terminal_reason_codes,
                )

        return (
            StepAggregationEvidenceAssessment(
                status=StepAggregationEvidenceReadStatus.READY,
                reason_codes=("AGGREGATION_EVIDENCE_ALL_TERMINAL_STEPS_READY",),
            ),
            skip_decisions,
        )

    @staticmethod
    def _validate_step_evidence(
        *,
        execution_id: str,
        step: "StepLifecycleSnapshot",
        evidence: StepAggregationEvidence,
    ) -> str | None:
        if (
            evidence.execution_id != execution_id
            or evidence.step_execution_id != step.step_execution_id
            or evidence.step_id != step.step_id
        ):
            return "AGGREGATION_EVIDENCE_IDENTITY_MISMATCH"
        if evidence.terminal_step_status is not step.status:
            return "AGGREGATION_EVIDENCE_STATUS_MISMATCH"
        if evidence.terminal_reason_codes != step.terminal_reason_codes:
            return "AGGREGATION_EVIDENCE_REASON_MISMATCH"
        if evidence.degraded is not step.degraded:
            return "AGGREGATION_EVIDENCE_DEGRADED_MISMATCH"
        if step.finished_at is None or evidence.terminalized_at != step.finished_at:
            return "AGGREGATION_EVIDENCE_TERMINAL_TIME_MISMATCH"
        if evidence.tool_call_ids != step.tool_call_ids:
            return "AGGREGATION_EVIDENCE_TOOL_IDENTITY_MISMATCH"

        if (
            evidence.terminalization_kind
            is StepAggregationTerminalizationKind.ATTEMPT_FINALIZED
        ):
            if step.status is StepExecutionStatus.SKIPPED:
                return "AGGREGATION_EVIDENCE_KIND_STATUS_MISMATCH"
            if step.skill_id is not None and step.workflow_id is not None:
                return "AGGREGATION_EVIDENCE_STEP_OWNER_AMBIGUOUS"
            if (
                evidence.has_unknown_tool_observation
                or evidence.has_untrusted_success_observation
            ):
                return "AGGREGATION_EVIDENCE_TOOL_TRUTH_UNKNOWN"
            expected_attempt_status = {
                (StepExecutionStatus.SUCCESS, False): "SUCCESS",
                (StepExecutionStatus.SUCCESS, True): "PARTIAL_SUCCESS",
                (StepExecutionStatus.FAILED, False): "FAILED",
                (StepExecutionStatus.TIMEOUT, False): "TIMEOUT",
            }.get((step.status, step.degraded))
            if evidence.final_attempt_status != expected_attempt_status:
                return "AGGREGATION_EVIDENCE_FINAL_ATTEMPT_STATUS_MISMATCH"
            if step.skill_id is not None:
                if (
                    evidence.execution_owner != "SKILL"
                    or evidence.owner_capability_id != step.skill_id
                    or evidence.skill_result is None
                    or evidence.skill_result.get("skill_id") != step.skill_id
                ):
                    return "AGGREGATION_EVIDENCE_SKILL_OWNER_MISMATCH"
                expected_skill_status = {
                    (StepExecutionStatus.SUCCESS, False): "SUCCESS",
                    (StepExecutionStatus.SUCCESS, True): "PARTIAL_SUCCESS",
                    (StepExecutionStatus.FAILED, False): "FAILED",
                    (StepExecutionStatus.TIMEOUT, False): "TIMEOUT",
                }.get((step.status, step.degraded))
                if evidence.skill_result.get("status") != expected_skill_status:
                    return "AGGREGATION_EVIDENCE_SKILL_STATUS_MISMATCH"
                if evidence.skill_result.get("business_outputs", []) != list(
                    evidence.business_outputs
                ):
                    return "AGGREGATION_EVIDENCE_SKILL_OUTPUT_MISMATCH"
                if evidence.skill_result.get("events", []) != list(
                    evidence.capability_events
                ):
                    return "AGGREGATION_EVIDENCE_SKILL_EVENT_MISMATCH"
            elif step.workflow_id is not None:
                if (
                    evidence.execution_owner != "WORKFLOW"
                    or evidence.owner_capability_id != step.workflow_id
                    or evidence.workflow_result is None
                    or evidence.workflow_result.get("workflow_id") != step.workflow_id
                ):
                    return "AGGREGATION_EVIDENCE_WORKFLOW_OWNER_MISMATCH"
                expected_workflow_status = {
                    StepExecutionStatus.SUCCESS: "COMPLETED",
                    StepExecutionStatus.FAILED: "FAILED",
                    StepExecutionStatus.TIMEOUT: "TIMEOUT",
                }.get(step.status)
                if evidence.workflow_result.get("status") != expected_workflow_status:
                    return "AGGREGATION_EVIDENCE_WORKFLOW_STATUS_MISMATCH"
                important_outputs = evidence.workflow_result.get(
                    "important_outputs",
                    {},
                )
                expected_outputs = (
                    [important_outputs]
                    if isinstance(important_outputs, dict) and important_outputs
                    else []
                )
                if expected_outputs != list(evidence.business_outputs):
                    return "AGGREGATION_EVIDENCE_WORKFLOW_OUTPUT_MISMATCH"
                if evidence.capability_events:
                    return "AGGREGATION_EVIDENCE_WORKFLOW_EVENT_MISMATCH"
            elif (
                evidence.execution_owner != "NONE"
                or evidence.owner_capability_id is not None
                or evidence.skill_result is not None
                or evidence.workflow_result is not None
            ):
                return "AGGREGATION_EVIDENCE_OWNER_MISMATCH"
            if (
                evidence.final_attempt_number is None
                or evidence.final_attempt_number - 1 != step.retry_count
            ):
                return "AGGREGATION_EVIDENCE_ATTEMPT_COUNT_MISMATCH"

        if (
            evidence.terminalization_kind
            is StepAggregationTerminalizationKind.SCHEDULER_SKIPPED
            and step.status is not StepExecutionStatus.SKIPPED
        ):
            return "AGGREGATION_EVIDENCE_SKIP_STATUS_MISMATCH"

        if (
            evidence.terminalization_kind
            is StepAggregationTerminalizationKind.CONTROL_TERMINALIZED
            and step.status
            not in {
                StepExecutionStatus.CANCELLED,
                StepExecutionStatus.PREEMPTED,
            }
        ):
            return "AGGREGATION_EVIDENCE_CONTROL_STATUS_MISMATCH"

        return None


def project_ca01_evidence_inputs(
    prepared: "PreparedExecution",
) -> tuple[
    "AggregationEvidenceReadinessDecision",
    dict[str, "StepSkipAggregationDecision"],
]:
    """Project exact CA-01 inputs without letting callers hand-construct READY."""

    from runtime.execution.aggregation_authority import (
        AggregationEvidenceReadinessDecision,
        AggregationEvidenceReadinessStatus,
    )

    assessment, skip_decisions = StepAggregationEvidenceAuthority().assess(prepared)
    status_map = {
        StepAggregationEvidenceReadStatus.READY: (
            AggregationEvidenceReadinessStatus.READY
        ),
        StepAggregationEvidenceReadStatus.MISSING: (
            AggregationEvidenceReadinessStatus.MISSING
        ),
        StepAggregationEvidenceReadStatus.UNKNOWN: (
            AggregationEvidenceReadinessStatus.UNKNOWN
        ),
    }
    decision = AggregationEvidenceReadinessDecision(
        execution_id=prepared.execution_record.execution_id,
        status=status_map[assessment.status],
        reason_codes=assessment.reason_codes,
    )
    return decision, skip_decisions


def _freeze_optional_dataclass(value: object | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return _freeze_dataclass(value)


def _freeze_dataclass(value: object) -> dict[str, Any]:
    frozen = _freeze_value(value)
    if not isinstance(frozen, dict):
        raise ValueError("aggregation evidence dataclass projection must be mapping")
    return frozen


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        _require_aware(value, "evidence datetime")
        return value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _freeze_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError(
                "aggregation evidence mappings require string keys"
            )
        return {
            key: _freeze_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [_freeze_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise ValueError(
        f"unsupported aggregation evidence value type: {type(value).__name__}"
    )


def _tuple_of_dicts(value: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (tuple, list)):
        raise ValueError("expected sequence of mappings")
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("expected sequence of mappings")
        result.append(deepcopy(dict(item)))
    return tuple(result)


def _optional_int(value: object | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("expected optional int")
    return value


def _optional_str(value: object | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("expected optional str")
    return value


def _optional_dict(value: object | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("expected optional mapping")
    return deepcopy(dict(value))


def _require_aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise ValueError(f"{field_name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
