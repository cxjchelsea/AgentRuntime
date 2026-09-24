"""CA-M5-IU10-04 durable control applicability authority.

This module turns IU7 control-application truth into crash-safe applicability
provenance for IU10 aggregation. It does not decide control priority, mutate the
execution lifecycle, aggregate plan status, or enter M6.

Reference in-memory storage models the contract only. Production adapters must
persist the same mutation atomically with recovery-epoch validation.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from runtime.execution.aggregation_authority import (
    AggregationControlApplicabilityDecision,
    AggregationControlApplicabilityStatus,
)
from runtime.execution.control import LatchedExecutionControl
from runtime.execution.control_application import (
    ExecutionControlApplication,
    ExecutionControlDisposition,
)
from runtime.execution.recovery import (
    ExecutionRecoveryClaim,
    InMemoryRecoveryClaimAuthority,
    RecoveryEpochValidationStatus,
)
from runtime.execution.recovery_evidence import (
    DurableControlReadDecision,
    DurableControlReadStatus,
    DurableTerminalControlStore,
)


def _require_non_blank(value: str | None, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


class ControlApplicabilityEvidenceStatus(str, Enum):
    APPLIES = "APPLIES"
    LATE_NOOP = "LATE_NOOP"


@dataclass(frozen=True, slots=True)
class DurableControlApplicabilityRecord:
    execution_id: str
    latched_control: LatchedExecutionControl
    status: ControlApplicabilityEvidenceStatus
    source_disposition: ExecutionControlDisposition
    source_reason_codes: tuple[str, ...]
    source_nonterminal_step_ids_at_latch: tuple[str, ...]
    source_affected_step_ids: tuple[str, ...]
    source_running_step_id: str | None
    source_preserve_running_step_result: bool
    revision: int
    recorded_at: datetime
    writer_recovery_epoch: int

    def __post_init__(self) -> None:
        _require_non_blank(self.execution_id, "execution_id")
        if self.latched_control.signal.target_execution_id != self.execution_id:
            raise ValueError("latched control target does not match execution_id")
        if not isinstance(self.status, ControlApplicabilityEvidenceStatus):
            raise TypeError("status must be ControlApplicabilityEvidenceStatus")
        if not isinstance(self.source_disposition, ExecutionControlDisposition):
            raise TypeError("source_disposition must be ExecutionControlDisposition")
        expected = {
            ControlApplicabilityEvidenceStatus.APPLIES: (
                ExecutionControlDisposition.READY_TO_TERMINALIZE
            ),
            ControlApplicabilityEvidenceStatus.LATE_NOOP: (
                ExecutionControlDisposition.ALREADY_TERMINAL
            ),
        }[self.status]
        if self.source_disposition is not expected:
            raise ValueError("applicability status/source disposition mismatch")
        if not self.source_reason_codes or any(
            not item.strip() for item in self.source_reason_codes
        ):
            raise ValueError("source_reason_codes must contain non-blank values")
        if len(set(self.source_nonterminal_step_ids_at_latch)) != len(
            self.source_nonterminal_step_ids_at_latch
        ):
            raise ValueError("source nonterminal Step ids must be unique")
        if len(set(self.source_affected_step_ids)) != len(
            self.source_affected_step_ids
        ):
            raise ValueError("source affected Step ids must be unique")
        if not set(self.source_affected_step_ids).issubset(
            set(self.source_nonterminal_step_ids_at_latch)
        ):
            raise ValueError("source affected Steps must be nonterminal at latch")
        if (
            self.source_running_step_id is not None
            and self.source_running_step_id
            not in self.source_nonterminal_step_ids_at_latch
        ):
            raise ValueError("source running Step must be nonterminal at latch")
        if (
            self.source_preserve_running_step_result
            and self.source_running_step_id is None
        ):
            raise ValueError(
                "preserved running result requires source running Step"
            )
        if (
            self.status is ControlApplicabilityEvidenceStatus.APPLIES
            and not self.source_affected_step_ids
        ):
            raise ValueError("APPLIES evidence requires affected Step provenance")
        if (
            self.status is ControlApplicabilityEvidenceStatus.LATE_NOOP
            and self.source_affected_step_ids
        ):
            raise ValueError("LATE_NOOP evidence cannot claim affected Steps")
        if self.revision < 1:
            raise ValueError("revision must be >= 1")
        if self.writer_recovery_epoch < 1:
            raise ValueError("writer_recovery_epoch must be >= 1")
        _require_aware(self.recorded_at, "recorded_at")
        if self.recorded_at < self.latched_control.latched_at:
            raise ValueError("recorded_at cannot precede control latch")


class ControlApplicabilityWriteStatus(str, Enum):
    RECORDED = "RECORDED"
    ALREADY_CURRENT = "ALREADY_CURRENT"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ControlApplicabilityWriteDecision:
    status: ControlApplicabilityWriteStatus
    reason_codes: tuple[str, ...]
    revision: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ControlApplicabilityWriteStatus):
            raise TypeError("status must be ControlApplicabilityWriteStatus")
        if not self.reason_codes or any(
            not item.strip() for item in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        if self.status in {
            ControlApplicabilityWriteStatus.RECORDED,
            ControlApplicabilityWriteStatus.ALREADY_CURRENT,
        }:
            if self.revision is None or self.revision < 1:
                raise ValueError("successful write requires revision >= 1")
        elif self.revision is not None:
            raise ValueError("CONFLICT/UNKNOWN cannot claim accepted revision")


class ControlApplicabilityReadStatus(str, Enum):
    NONE = "NONE"
    RECORDED = "RECORDED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ControlApplicabilityReadDecision:
    status: ControlApplicabilityReadStatus
    reason_codes: tuple[str, ...]
    record: DurableControlApplicabilityRecord | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ControlApplicabilityReadStatus):
            raise TypeError("status must be ControlApplicabilityReadStatus")
        if not self.reason_codes or any(
            not item.strip() for item in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        if self.status is ControlApplicabilityReadStatus.RECORDED:
            if self.record is None:
                raise ValueError("RECORDED read requires record")
        elif self.record is not None:
            raise ValueError("NONE/UNKNOWN read cannot expose record")


class DurableControlApplicabilityStore(Protocol):
    async def record(
        self,
        *,
        latched_control: LatchedExecutionControl,
        application: ExecutionControlApplication,
        recorded_at: datetime,
        required_claim: ExecutionRecoveryClaim,
    ) -> ControlApplicabilityWriteDecision:
        """Persist first immutable applicability outcome under recovery fencing."""

    async def read(
        self,
        execution_id: str,
    ) -> ControlApplicabilityReadDecision:
        """Read applicability without collapsing uncertainty to absence."""


class InMemoryDurableControlApplicabilityStore:
    """Reference applicability store with recovery-epoch fencing."""

    def __init__(
        self,
        *,
        claim_authority: InMemoryRecoveryClaimAuthority,
    ) -> None:
        self._claim_authority = claim_authority
        self._lock = asyncio.Lock()
        self._records: dict[str, DurableControlApplicabilityRecord] = {}

    async def record(
        self,
        *,
        latched_control: LatchedExecutionControl,
        application: ExecutionControlApplication,
        recorded_at: datetime,
        required_claim: ExecutionRecoveryClaim,
    ) -> ControlApplicabilityWriteDecision:
        execution_id = _require_non_blank(
            latched_control.signal.target_execution_id,
            "execution_id",
        )
        _require_aware(recorded_at, "recorded_at")
        if recorded_at < latched_control.latched_at:
            return ControlApplicabilityWriteDecision(
                status=ControlApplicabilityWriteStatus.UNKNOWN,
                reason_codes=("CONTROL_APPLICABILITY_TIME_REGRESSION",),
            )
        if required_claim.execution_id != execution_id:
            return ControlApplicabilityWriteDecision(
                status=ControlApplicabilityWriteStatus.UNKNOWN,
                reason_codes=("CONTROL_APPLICABILITY_CLAIM_EXECUTION_MISMATCH",),
            )
        if application.signal != latched_control.signal:
            return ControlApplicabilityWriteDecision(
                status=ControlApplicabilityWriteStatus.UNKNOWN,
                reason_codes=("CONTROL_APPLICABILITY_SIGNAL_MISMATCH",),
            )

        mapped = {
            ExecutionControlDisposition.READY_TO_TERMINALIZE: (
                ControlApplicabilityEvidenceStatus.APPLIES
            ),
            ExecutionControlDisposition.ALREADY_TERMINAL: (
                ControlApplicabilityEvidenceStatus.LATE_NOOP
            ),
        }.get(application.disposition)
        if mapped is None:
            return ControlApplicabilityWriteDecision(
                status=ControlApplicabilityWriteStatus.UNKNOWN,
                reason_codes=("CONTROL_APPLICABILITY_SOURCE_NOT_FINAL",),
            )

        async with self._lock:
            fence = self._claim_authority._validate_current_sync(required_claim)
            if fence.status is RecoveryEpochValidationStatus.STALE:
                return ControlApplicabilityWriteDecision(
                    status=ControlApplicabilityWriteStatus.CONFLICT,
                    reason_codes=("CONTROL_APPLICABILITY_STALE_RECOVERY_EPOCH",),
                )
            if fence.status is not RecoveryEpochValidationStatus.CURRENT:
                return ControlApplicabilityWriteDecision(
                    status=ControlApplicabilityWriteStatus.UNKNOWN,
                    reason_codes=("CONTROL_APPLICABILITY_RECOVERY_EPOCH_UNKNOWN",),
                )

            existing = self._records.get(execution_id)
            if existing is not None:
                if (
                    existing.latched_control == latched_control
                    and existing.status is mapped
                    and existing.source_disposition is application.disposition
                    and existing.source_reason_codes == application.reason_codes
                    and existing.source_nonterminal_step_ids_at_latch
                    == application.nonterminal_step_ids_at_latch
                    and existing.source_affected_step_ids
                    == application.affected_step_ids
                    and existing.source_running_step_id == application.running_step_id
                    and existing.source_preserve_running_step_result
                    == application.preserve_running_step_result
                ):
                    return ControlApplicabilityWriteDecision(
                        status=ControlApplicabilityWriteStatus.ALREADY_CURRENT,
                        reason_codes=("CONTROL_APPLICABILITY_EXACT_REPLAY",),
                        revision=existing.revision,
                    )
                return ControlApplicabilityWriteDecision(
                    status=ControlApplicabilityWriteStatus.CONFLICT,
                    reason_codes=("CONTROL_APPLICABILITY_IMMUTABLE_CONFLICT",),
                )

            record = DurableControlApplicabilityRecord(
                execution_id=execution_id,
                latched_control=deepcopy(latched_control),
                status=mapped,
                source_disposition=application.disposition,
                source_reason_codes=application.reason_codes,
                source_nonterminal_step_ids_at_latch=(
                    application.nonterminal_step_ids_at_latch
                ),
                source_affected_step_ids=application.affected_step_ids,
                source_running_step_id=application.running_step_id,
                source_preserve_running_step_result=(
                    application.preserve_running_step_result
                ),
                revision=1,
                recorded_at=recorded_at,
                writer_recovery_epoch=required_claim.recovery_epoch,
            )
            self._records[execution_id] = record
            return ControlApplicabilityWriteDecision(
                status=ControlApplicabilityWriteStatus.RECORDED,
                reason_codes=("CONTROL_APPLICABILITY_DURABLY_RECORDED",),
                revision=record.revision,
            )

    async def read(
        self,
        execution_id: str,
    ) -> ControlApplicabilityReadDecision:
        if not isinstance(execution_id, str) or not execution_id.strip():
            return ControlApplicabilityReadDecision(
                status=ControlApplicabilityReadStatus.UNKNOWN,
                reason_codes=("CONTROL_APPLICABILITY_READ_EXECUTION_ID_INVALID",),
            )
        async with self._lock:
            record = self._records.get(execution_id)
            if record is None:
                return ControlApplicabilityReadDecision(
                    status=ControlApplicabilityReadStatus.NONE,
                    reason_codes=("CONTROL_APPLICABILITY_NOT_RECORDED",),
                )
            return ControlApplicabilityReadDecision(
                status=ControlApplicabilityReadStatus.RECORDED,
                reason_codes=("CONTROL_APPLICABILITY_RECORD_FOUND",),
                record=deepcopy(record),
            )


class ControlApplicabilityRecorder(Protocol):
    async def record(
        self,
        *,
        latched_control: LatchedExecutionControl,
        application: ExecutionControlApplication,
        recorded_at: datetime,
    ) -> ControlApplicabilityWriteDecision:
        """Persist one final IU7 applicability outcome before lifecycle mutation."""


class DurableControlApplicabilityRecorder:
    def __init__(
        self,
        *,
        store: DurableControlApplicabilityStore,
        recovery_claim: ExecutionRecoveryClaim,
    ) -> None:
        self._store = store
        self._claim = recovery_claim

    async def record(
        self,
        *,
        latched_control: LatchedExecutionControl,
        application: ExecutionControlApplication,
        recorded_at: datetime,
    ) -> ControlApplicabilityWriteDecision:
        return await self._store.record(
            latched_control=latched_control,
            application=application,
            recorded_at=recorded_at,
            required_claim=self._claim,
        )


@dataclass(frozen=True, slots=True)
class AggregationControlAuthoritySnapshot:
    control: DurableControlReadDecision
    applicability: AggregationControlApplicabilityDecision


class AggregationControlAuthority(Protocol):
    async def resolve(
        self,
        *,
        execution_id: str,
    ) -> AggregationControlAuthoritySnapshot:
        """Resolve exact durable control + applicability for aggregation."""


class DurableAggregationControlAuthority:
    """Only formal producer of AggregationControlApplicabilityDecision."""

    def __init__(
        self,
        *,
        control_store: DurableTerminalControlStore,
        applicability_store: DurableControlApplicabilityStore,
    ) -> None:
        self._control_store = control_store
        self._applicability_store = applicability_store

    async def resolve(
        self,
        *,
        execution_id: str,
    ) -> AggregationControlAuthoritySnapshot:
        try:
            control = await self._control_store.read_latched(execution_id)
        except Exception:  # noqa: BLE001
            control = DurableControlReadDecision(
                status=DurableControlReadStatus.UNKNOWN,
                reason_codes=("DURABLE_CONTROL_READ_UNKNOWN",),
            )
        try:
            evidence = await self._applicability_store.read(execution_id)
        except Exception:  # noqa: BLE001
            evidence = ControlApplicabilityReadDecision(
                status=ControlApplicabilityReadStatus.UNKNOWN,
                reason_codes=("CONTROL_APPLICABILITY_READ_UNKNOWN",),
            )

        if control.status is DurableControlReadStatus.UNKNOWN:
            return self._snapshot(
                control,
                AggregationControlApplicabilityStatus.UNKNOWN,
                "AGGREGATION_CONTROL_STATE_UNKNOWN",
            )

        if evidence.status is ControlApplicabilityReadStatus.UNKNOWN:
            return self._snapshot(
                control,
                AggregationControlApplicabilityStatus.UNKNOWN,
                "AGGREGATION_CONTROL_APPLICABILITY_READ_UNKNOWN",
            )

        if control.status is DurableControlReadStatus.NONE:
            if evidence.status is ControlApplicabilityReadStatus.NONE:
                return self._snapshot(
                    control,
                    AggregationControlApplicabilityStatus.NONE,
                    "AGGREGATION_CONTROL_NONE_DURABLE",
                )
            return self._snapshot(
                control,
                AggregationControlApplicabilityStatus.UNKNOWN,
                "AGGREGATION_CONTROL_APPLICABILITY_ORPHAN_EVIDENCE",
            )

        latched = control.latched_control
        if latched is None:
            return self._snapshot(
                DurableControlReadDecision(
                    status=DurableControlReadStatus.UNKNOWN,
                    reason_codes=("DURABLE_CONTROL_LATCH_MISSING",),
                ),
                AggregationControlApplicabilityStatus.UNKNOWN,
                "AGGREGATION_CONTROL_LATCH_MISSING",
            )

        if (
            evidence.status is ControlApplicabilityReadStatus.NONE
            or evidence.record is None
        ):
            return self._snapshot(
                control,
                AggregationControlApplicabilityStatus.UNKNOWN,
                "AGGREGATION_CONTROL_APPLICABILITY_EVIDENCE_MISSING",
            )

        record = evidence.record
        if (
            record.execution_id != execution_id
            or record.latched_control != latched
        ):
            return self._snapshot(
                control,
                AggregationControlApplicabilityStatus.UNKNOWN,
                "AGGREGATION_CONTROL_APPLICABILITY_AUTHORITY_MISMATCH",
            )

        mapped = {
            ControlApplicabilityEvidenceStatus.APPLIES: (
                AggregationControlApplicabilityStatus.APPLIES
            ),
            ControlApplicabilityEvidenceStatus.LATE_NOOP: (
                AggregationControlApplicabilityStatus.LATE_NOOP
            ),
        }[record.status]
        return AggregationControlAuthoritySnapshot(
            control=control,
            applicability=AggregationControlApplicabilityDecision(
                status=mapped,
                reason_codes=record.source_reason_codes,
                latched_control=latched,
            ),
        )

    @staticmethod
    def _snapshot(
        control: DurableControlReadDecision,
        status: AggregationControlApplicabilityStatus,
        reason_code: str,
    ) -> AggregationControlAuthoritySnapshot:
        return AggregationControlAuthoritySnapshot(
            control=control,
            applicability=AggregationControlApplicabilityDecision(
                status=status,
                reason_codes=(reason_code,),
            ),
        )
