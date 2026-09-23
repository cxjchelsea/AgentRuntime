"""M5-IU9 CA-01 durable execution snapshot and recovery-claim contracts.

This unit freezes crash-recovery execution state, monotonic checkpoint/CAS semantics,
recovery ownership epochs, and the guard used by later Formal Implementation before
state mutation or a new external side effect.

The in-memory implementations are reference mechanisms for contract verification.
They do not claim process-crash durability by themselves; production durability is
provided by adapters implementing the same protocols.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Protocol

from runtime.contracts.enums import RuntimeControlState
from runtime.contracts.execution import ExecutionContext
from runtime.execution.foundation import PreparedExecution, StepLifecycleSnapshot
from runtime.execution.models import ExecutionRecord

RECOVERY_SNAPSHOT_SCHEMA_VERSION = "M5-IU9-RECOVERY-1"


def _require_non_blank(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _step_payload(snapshot: StepLifecycleSnapshot) -> dict[str, Any]:
    return {
        "step_execution_id": snapshot.step_execution_id,
        "step_id": snapshot.step_id,
        "action": snapshot.action,
        "status": snapshot.status.value,
        "skill_id": snapshot.skill_id,
        "workflow_id": snapshot.workflow_id,
        "tool_call_ids": list(snapshot.tool_call_ids),
        "output": deepcopy(snapshot.output),
        "error": snapshot.error,
        "retry_count": snapshot.retry_count,
        "started_at": snapshot.started_at,
        "finished_at": snapshot.finished_at,
    }


@dataclass(frozen=True, slots=True)
class RecoverySafeExecutionContext:
    """Crash-safe projection of ExecutionContext.

    Raw tool_context is deliberately excluded because it can contain credentials,
    connection handles, or process-local objects. The optional opaque reference is
    metadata only and never recreates current Tool authorization.
    """

    execution_id: str
    plan_id: str
    request_id: str
    session_id: str
    identity_scope: str
    policy_snapshot: dict[str, Any]
    device_id: str | None = None
    current_state: RuntimeControlState | None = None
    step_state: dict[str, Any] | None = None
    deadline: datetime | None = None
    cancellation_token: str | None = None
    trace_context: dict[str, Any] | None = None
    tool_context_reference: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("execution_id", self.execution_id),
            ("plan_id", self.plan_id),
            ("request_id", self.request_id),
            ("session_id", self.session_id),
            ("identity_scope", self.identity_scope),
        ):
            _require_non_blank(value, name)
        if not self.policy_snapshot:
            raise ValueError("policy_snapshot must not be empty")
        if self.deadline is not None:
            _require_aware(self.deadline, "deadline")
        if self.cancellation_token is not None:
            _require_non_blank(self.cancellation_token, "cancellation_token")
        if self.tool_context_reference is not None:
            _require_non_blank(self.tool_context_reference, "tool_context_reference")

    @classmethod
    def capture(
        cls,
        context: ExecutionContext,
        *,
        tool_context_reference: str | None = None,
    ) -> RecoverySafeExecutionContext:
        return cls(
            execution_id=context.execution_id,
            plan_id=context.plan_id,
            request_id=context.request_id,
            session_id=context.session_id,
            identity_scope=context.identity_scope,
            policy_snapshot=deepcopy(context.policy_snapshot),
            device_id=context.device_id,
            current_state=context.current_state,
            step_state=deepcopy(context.step_state),
            deadline=context.deadline,
            cancellation_token=context.cancellation_token,
            trace_context=deepcopy(context.trace_context),
            tool_context_reference=tool_context_reference,
        )

    def restore(self) -> ExecutionContext:
        """Rebuild Core execution context without restoring stale Tool credentials."""

        return ExecutionContext(
            execution_id=self.execution_id,
            plan_id=self.plan_id,
            request_id=self.request_id,
            session_id=self.session_id,
            identity_scope=self.identity_scope,
            policy_snapshot=deepcopy(self.policy_snapshot),
            device_id=self.device_id,
            current_state=self.current_state,
            step_state=deepcopy(self.step_state),
            tool_context=None,
            deadline=self.deadline,
            cancellation_token=self.cancellation_token,
            trace_context=deepcopy(self.trace_context),
        )


@dataclass(frozen=True, slots=True)
class RecoveryClaimRequest:
    claim_id: str
    execution_id: str
    recovery_owner_id: str
    expected_current_epoch: int
    source_snapshot_generation: int
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_non_blank(self.claim_id, "claim_id")
        _require_non_blank(self.execution_id, "execution_id")
        _require_non_blank(self.recovery_owner_id, "recovery_owner_id")
        if self.expected_current_epoch < 0:
            raise ValueError("expected_current_epoch must be >= 0")
        if self.source_snapshot_generation < 0:
            raise ValueError("source_snapshot_generation must be >= 0")
        _require_aware(self.requested_at, "requested_at")


@dataclass(frozen=True, slots=True)
class ExecutionRecoveryClaim:
    claim_id: str
    execution_id: str
    recovery_owner_id: str
    recovery_epoch: int
    source_snapshot_generation: int
    claimed_at: datetime

    def __post_init__(self) -> None:
        _require_non_blank(self.claim_id, "claim_id")
        _require_non_blank(self.execution_id, "execution_id")
        _require_non_blank(self.recovery_owner_id, "recovery_owner_id")
        if self.recovery_epoch < 1:
            raise ValueError("recovery_epoch must be >= 1")
        if self.source_snapshot_generation < 0:
            raise ValueError("source_snapshot_generation must be >= 0")
        _require_aware(self.claimed_at, "claimed_at")


class RecoveryClaimStatus(str, Enum):
    CLAIMED = "CLAIMED"
    ALREADY_CLAIMED = "ALREADY_CLAIMED"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class RecoveryClaimDecision:
    status: RecoveryClaimStatus
    reason_codes: tuple[str, ...]
    claim: ExecutionRecoveryClaim | None = None
    current_claim: ExecutionRecoveryClaim | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, RecoveryClaimStatus):
            raise TypeError("status must be RecoveryClaimStatus")
        if not self.reason_codes or any(not item.strip() for item in self.reason_codes):
            raise ValueError("reason_codes must contain non-blank values")
        if self.status in {
            RecoveryClaimStatus.CLAIMED,
            RecoveryClaimStatus.ALREADY_CLAIMED,
        }:
            if self.claim is None:
                raise ValueError("successful recovery claim decision requires claim")
        elif self.claim is not None:
            raise ValueError("CONFLICT/UNKNOWN must not expose accepted claim")
        if self.status is RecoveryClaimStatus.CONFLICT and self.current_claim is None:
            raise ValueError("CONFLICT requires current_claim")


class RecoveryEpochValidationStatus(str, Enum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class RecoveryEpochValidationDecision:
    status: RecoveryEpochValidationStatus
    reason_codes: tuple[str, ...]
    current_claim: ExecutionRecoveryClaim | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, RecoveryEpochValidationStatus):
            raise TypeError("status must be RecoveryEpochValidationStatus")
        if not self.reason_codes or any(not item.strip() for item in self.reason_codes):
            raise ValueError("reason_codes must contain non-blank values")
        if (
            self.status
            in {
                RecoveryEpochValidationStatus.CURRENT,
                RecoveryEpochValidationStatus.STALE,
            }
            and self.current_claim is None
        ):
            raise ValueError("CURRENT/STALE validation requires current_claim")


class RecoveryClaimAuthority(Protocol):
    async def claim(self, request: RecoveryClaimRequest) -> RecoveryClaimDecision:
        """Atomically claim expected_current_epoch + 1."""

    async def current(self, execution_id: str) -> ExecutionRecoveryClaim | None:
        """Return the current execution recovery ownership claim."""

    async def validate_current(
        self,
        claim: ExecutionRecoveryClaim,
    ) -> RecoveryEpochValidationDecision:
        """Validate the epoch before state mutation or external side-effect admission."""


class InMemoryRecoveryClaimAuthority:
    """Reference atomic recovery-epoch authority.

    The object can be shared across recreated runtime coordinators for contract tests,
    but it is not a production crash-durable store.
    """

    def __init__(self) -> None:
        self._current_by_execution: dict[str, ExecutionRecoveryClaim] = {}
        self._claims_by_id: dict[str, ExecutionRecoveryClaim] = {}
        self._requests_by_id: dict[str, RecoveryClaimRequest] = {}

    async def claim(self, request: RecoveryClaimRequest) -> RecoveryClaimDecision:
        prior_request = self._requests_by_id.get(request.claim_id)
        if prior_request is not None:
            prior_claim = self._claims_by_id[request.claim_id]
            current = self._current_by_execution.get(request.execution_id)
            if prior_request != request:
                return RecoveryClaimDecision(
                    status=RecoveryClaimStatus.UNKNOWN,
                    reason_codes=("RECOVERY_CLAIM_IDENTITY_REUSE_CONFLICT",),
                    current_claim=current,
                )
            if current == prior_claim:
                return RecoveryClaimDecision(
                    status=RecoveryClaimStatus.ALREADY_CLAIMED,
                    reason_codes=("RECOVERY_CLAIM_EXACT_REPLAY",),
                    claim=prior_claim,
                    current_claim=current,
                )
            return RecoveryClaimDecision(
                status=RecoveryClaimStatus.CONFLICT,
                reason_codes=("RECOVERY_CLAIM_REPLAY_IS_STALE",),
                current_claim=current,
            )

        current = self._current_by_execution.get(request.execution_id)
        current_epoch = 0 if current is None else current.recovery_epoch
        if request.expected_current_epoch != current_epoch:
            if current is None:
                return RecoveryClaimDecision(
                    status=RecoveryClaimStatus.UNKNOWN,
                    reason_codes=("RECOVERY_CLAIM_BASELINE_UNKNOWN",),
                )
            return RecoveryClaimDecision(
                status=RecoveryClaimStatus.CONFLICT,
                reason_codes=("RECOVERY_CLAIM_EPOCH_CONFLICT",),
                current_claim=current,
            )
        if (
            current is not None
            and request.source_snapshot_generation < current.source_snapshot_generation
        ):
            return RecoveryClaimDecision(
                status=RecoveryClaimStatus.CONFLICT,
                reason_codes=("RECOVERY_CLAIM_SOURCE_GENERATION_STALE",),
                current_claim=current,
            )

        claim = ExecutionRecoveryClaim(
            claim_id=request.claim_id,
            execution_id=request.execution_id,
            recovery_owner_id=request.recovery_owner_id,
            recovery_epoch=current_epoch + 1,
            source_snapshot_generation=request.source_snapshot_generation,
            claimed_at=request.requested_at,
        )
        self._current_by_execution[request.execution_id] = claim
        self._claims_by_id[request.claim_id] = claim
        self._requests_by_id[request.claim_id] = request
        return RecoveryClaimDecision(
            status=RecoveryClaimStatus.CLAIMED,
            reason_codes=("RECOVERY_CLAIM_ACQUIRED",),
            claim=claim,
            current_claim=claim,
        )

    async def current(self, execution_id: str) -> ExecutionRecoveryClaim | None:
        if not isinstance(execution_id, str) or not execution_id.strip():
            return None
        return self._current_by_execution.get(execution_id)

    async def validate_current(
        self,
        claim: ExecutionRecoveryClaim,
    ) -> RecoveryEpochValidationDecision:
        current = self._current_by_execution.get(claim.execution_id)
        if current is None:
            return RecoveryEpochValidationDecision(
                status=RecoveryEpochValidationStatus.UNKNOWN,
                reason_codes=("RECOVERY_EPOCH_CURRENT_CLAIM_UNKNOWN",),
            )
        if current == claim:
            return RecoveryEpochValidationDecision(
                status=RecoveryEpochValidationStatus.CURRENT,
                reason_codes=("RECOVERY_EPOCH_CURRENT",),
                current_claim=current,
            )
        return RecoveryEpochValidationDecision(
            status=RecoveryEpochValidationStatus.STALE,
            reason_codes=("RECOVERY_EPOCH_STALE",),
            current_claim=current,
        )


@dataclass(frozen=True, slots=True)
class ExecutionRecoverySnapshot:
    checkpoint_id: str
    generation: int
    execution_id: str
    captured_at: datetime
    execution_context: RecoverySafeExecutionContext
    execution_record: ExecutionRecord
    steps: tuple[StepLifecycleSnapshot, ...]
    execution_started_at: datetime | None
    execution_finished_at: datetime | None
    writer_recovery_epoch: int
    writer_recovery_owner_id: str
    schema_version: str = RECOVERY_SNAPSHOT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_non_blank(self.checkpoint_id, "checkpoint_id")
        _require_non_blank(self.execution_id, "execution_id")
        _require_non_blank(self.writer_recovery_owner_id, "writer_recovery_owner_id")
        if self.generation < 1:
            raise ValueError("generation must be >= 1")
        if self.writer_recovery_epoch < 1:
            raise ValueError("writer_recovery_epoch must be >= 1")
        if self.schema_version != RECOVERY_SNAPSHOT_SCHEMA_VERSION:
            raise ValueError("recovery snapshot schema_version is unsupported")
        _require_aware(self.captured_at, "captured_at")
        if not self.steps:
            raise ValueError("recovery snapshot requires steps")

        context = self.execution_context
        record = self.execution_record
        if (
            self.execution_id != context.execution_id
            or self.execution_id != record.execution_id
        ):
            raise ValueError("recovery snapshot execution identity mismatch")
        if (
            context.plan_id != record.plan_id
            or context.request_id != record.request_id
            or context.identity_scope != record.identity_scope
        ):
            raise ValueError("recovery snapshot execution provenance mismatch")

        if record.created_at is None or record.updated_at is None:
            raise ValueError("recovery snapshot requires execution record timestamps")
        _require_aware(record.created_at, "execution_record.created_at")
        _require_aware(record.updated_at, "execution_record.updated_at")
        if record.updated_at < record.created_at:
            raise ValueError("execution record updated_at cannot precede created_at")
        if self.captured_at < record.updated_at:
            raise ValueError("captured_at cannot precede latest execution observation")

        if self.execution_started_at is not None:
            _require_aware(self.execution_started_at, "execution_started_at")
            if self.execution_started_at < record.created_at:
                raise ValueError("execution_started_at cannot precede creation")
        if self.execution_finished_at is not None:
            _require_aware(self.execution_finished_at, "execution_finished_at")
            if self.execution_started_at is None:
                raise ValueError("finished execution requires execution_started_at")
            if self.execution_finished_at < self.execution_started_at:
                raise ValueError("execution_finished_at cannot precede start")
            if record.updated_at > self.execution_finished_at:
                raise ValueError("terminal snapshot cannot predate record update")

        step_ids = [item.step_id for item in self.steps]
        step_execution_ids = [item.step_execution_id for item in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("recovery snapshot step_id values must be unique")
        if len(step_execution_ids) != len(set(step_execution_ids)):
            raise ValueError(
                "recovery snapshot step_execution_id values must be unique"
            )
        expected_payload = tuple(_step_payload(item) for item in self.steps)
        if record.step_results != expected_payload:
            raise ValueError(
                "recovery snapshot typed steps must match ExecutionRecord.step_results"
            )

        running = tuple(item for item in self.steps if item.status.value == "RUNNING")
        if record.current_step is None:
            if running:
                raise ValueError("running recovery step requires current_step")
        elif len(running) != 1 or running[0].step_id != record.current_step:
            raise ValueError("current_step must match exactly one RUNNING step")

    def restore_prepared_execution(self) -> PreparedExecution:
        """Reconstruct PreparedExecution without restoring raw Tool authorization."""

        return PreparedExecution(
            execution_context=self.execution_context.restore(),
            execution_record=deepcopy(self.execution_record),
            steps=deepcopy(self.steps),
            started_at=self.execution_started_at,
            finished_at=self.execution_finished_at,
        )


class ExecutionRecoverySnapshotFactory:
    def capture(
        self,
        prepared: PreparedExecution,
        *,
        checkpoint_id: str,
        generation: int,
        captured_at: datetime,
        claim: ExecutionRecoveryClaim,
        tool_context_reference: str | None = None,
    ) -> ExecutionRecoverySnapshot:
        if claim.execution_id != prepared.execution_context.execution_id:
            raise ValueError("recovery claim does not match prepared execution")
        return ExecutionRecoverySnapshot(
            checkpoint_id=checkpoint_id,
            generation=generation,
            execution_id=prepared.execution_context.execution_id,
            captured_at=captured_at,
            execution_context=RecoverySafeExecutionContext.capture(
                prepared.execution_context,
                tool_context_reference=tool_context_reference,
            ),
            execution_record=deepcopy(prepared.execution_record),
            steps=deepcopy(prepared.steps),
            execution_started_at=prepared.started_at,
            execution_finished_at=prepared.finished_at,
            writer_recovery_epoch=claim.recovery_epoch,
            writer_recovery_owner_id=claim.recovery_owner_id,
        )


class RecoverySnapshotWriteStatus(str, Enum):
    CREATED = "CREATED"
    UPDATED = "UPDATED"
    ALREADY_CURRENT = "ALREADY_CURRENT"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class RecoverySnapshotWriteDecision:
    status: RecoverySnapshotWriteStatus
    reason_codes: tuple[str, ...]
    accepted_snapshot: ExecutionRecoverySnapshot | None = None
    current_snapshot: ExecutionRecoverySnapshot | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, RecoverySnapshotWriteStatus):
            raise TypeError("status must be RecoverySnapshotWriteStatus")
        if not self.reason_codes or any(not item.strip() for item in self.reason_codes):
            raise ValueError("reason_codes must contain non-blank values")
        if self.status in {
            RecoverySnapshotWriteStatus.CREATED,
            RecoverySnapshotWriteStatus.UPDATED,
            RecoverySnapshotWriteStatus.ALREADY_CURRENT,
        }:
            if self.accepted_snapshot is None:
                raise ValueError("successful snapshot write requires accepted_snapshot")
        elif self.accepted_snapshot is not None:
            raise ValueError("CONFLICT/UNKNOWN cannot expose accepted_snapshot")


class ExecutionRecoverySnapshotStore(Protocol):
    async def load(self, execution_id: str) -> ExecutionRecoverySnapshot | None:
        """Load the latest durable recovery snapshot."""

    async def compare_and_set(
        self,
        snapshot: ExecutionRecoverySnapshot,
        *,
        expected_generation: int,
    ) -> RecoverySnapshotWriteDecision:
        """Persist generation + 1 or exact replay without stale overwrite."""


class InMemoryExecutionRecoverySnapshotStore:
    """Reference CAS store; not a production durability claim."""

    def __init__(self) -> None:
        self._snapshots: dict[str, ExecutionRecoverySnapshot] = {}

    async def load(self, execution_id: str) -> ExecutionRecoverySnapshot | None:
        if not isinstance(execution_id, str) or not execution_id.strip():
            return None
        snapshot = self._snapshots.get(execution_id)
        return None if snapshot is None else deepcopy(snapshot)

    async def compare_and_set(
        self,
        snapshot: ExecutionRecoverySnapshot,
        *,
        expected_generation: int,
    ) -> RecoverySnapshotWriteDecision:
        if expected_generation < 0:
            return RecoverySnapshotWriteDecision(
                status=RecoverySnapshotWriteStatus.UNKNOWN,
                reason_codes=("RECOVERY_SNAPSHOT_EXPECTED_GENERATION_INVALID",),
            )
        current = self._snapshots.get(snapshot.execution_id)
        if current is None:
            if expected_generation != 0 or snapshot.generation != 1:
                return RecoverySnapshotWriteDecision(
                    status=RecoverySnapshotWriteStatus.CONFLICT,
                    reason_codes=("RECOVERY_SNAPSHOT_CREATE_GENERATION_CONFLICT",),
                )
            stored = deepcopy(snapshot)
            self._snapshots[snapshot.execution_id] = stored
            return RecoverySnapshotWriteDecision(
                status=RecoverySnapshotWriteStatus.CREATED,
                reason_codes=("RECOVERY_SNAPSHOT_CREATED",),
                accepted_snapshot=deepcopy(stored),
                current_snapshot=deepcopy(stored),
            )

        if snapshot == current:
            if expected_generation not in {
                current.generation - 1,
                current.generation,
            }:
                return RecoverySnapshotWriteDecision(
                    status=RecoverySnapshotWriteStatus.CONFLICT,
                    reason_codes=("RECOVERY_SNAPSHOT_REPLAY_GENERATION_CONFLICT",),
                    current_snapshot=deepcopy(current),
                )
            return RecoverySnapshotWriteDecision(
                status=RecoverySnapshotWriteStatus.ALREADY_CURRENT,
                reason_codes=("RECOVERY_SNAPSHOT_EXACT_REPLAY",),
                accepted_snapshot=deepcopy(current),
                current_snapshot=deepcopy(current),
            )

        if expected_generation != current.generation:
            return RecoverySnapshotWriteDecision(
                status=RecoverySnapshotWriteStatus.CONFLICT,
                reason_codes=("RECOVERY_SNAPSHOT_EXPECTED_GENERATION_CONFLICT",),
                current_snapshot=deepcopy(current),
            )
        if snapshot.generation != current.generation + 1:
            return RecoverySnapshotWriteDecision(
                status=RecoverySnapshotWriteStatus.CONFLICT,
                reason_codes=("RECOVERY_SNAPSHOT_NEXT_GENERATION_INVALID",),
                current_snapshot=deepcopy(current),
            )
        if snapshot.captured_at < current.captured_at:
            return RecoverySnapshotWriteDecision(
                status=RecoverySnapshotWriteStatus.CONFLICT,
                reason_codes=("RECOVERY_SNAPSHOT_TIME_REGRESSION",),
                current_snapshot=deepcopy(current),
            )

        stored = deepcopy(snapshot)
        self._snapshots[snapshot.execution_id] = stored
        return RecoverySnapshotWriteDecision(
            status=RecoverySnapshotWriteStatus.UPDATED,
            reason_codes=("RECOVERY_SNAPSHOT_UPDATED",),
            accepted_snapshot=deepcopy(stored),
            current_snapshot=deepcopy(stored),
        )


class RecoveryClaimCoordinator:
    """Acquire a recovery epoch only from the latest known snapshot generation."""

    def __init__(
        self,
        *,
        snapshot_store: ExecutionRecoverySnapshotStore,
        claim_authority: RecoveryClaimAuthority,
    ) -> None:
        self._snapshot_store = snapshot_store
        self._claim_authority = claim_authority

    async def claim(self, request: RecoveryClaimRequest) -> RecoveryClaimDecision:
        try:
            latest = await self._snapshot_store.load(request.execution_id)
        except Exception:  # noqa: BLE001
            return RecoveryClaimDecision(
                status=RecoveryClaimStatus.UNKNOWN,
                reason_codes=("RECOVERY_CLAIM_SNAPSHOT_LOOKUP_UNKNOWN",),
            )
        latest_generation = 0 if latest is None else latest.generation
        if request.source_snapshot_generation != latest_generation:
            current = await self._safe_current(request.execution_id)
            if current is None:
                return RecoveryClaimDecision(
                    status=RecoveryClaimStatus.UNKNOWN,
                    reason_codes=("RECOVERY_CLAIM_SOURCE_SNAPSHOT_UNKNOWN",),
                )
            return RecoveryClaimDecision(
                status=RecoveryClaimStatus.CONFLICT,
                reason_codes=("RECOVERY_CLAIM_SOURCE_SNAPSHOT_STALE",),
                current_claim=current,
            )
        try:
            return await self._claim_authority.claim(request)
        except Exception:  # noqa: BLE001
            return RecoveryClaimDecision(
                status=RecoveryClaimStatus.UNKNOWN,
                reason_codes=("RECOVERY_CLAIM_AUTHORITY_UNKNOWN",),
            )

    async def _safe_current(
        self,
        execution_id: str,
    ) -> ExecutionRecoveryClaim | None:
        try:
            return await self._claim_authority.current(execution_id)
        except Exception:  # noqa: BLE001
            return None


class ExecutionRecoverySnapshotCoordinator:
    """Guard snapshot mutation with current recovery ownership and CAS."""

    def __init__(
        self,
        *,
        snapshot_store: ExecutionRecoverySnapshotStore,
        epoch_guard: RecoveryClaimAuthority,
    ) -> None:
        self._snapshot_store = snapshot_store
        self._epoch_guard = epoch_guard

    async def save(
        self,
        snapshot: ExecutionRecoverySnapshot,
        *,
        expected_generation: int,
        claim: ExecutionRecoveryClaim,
    ) -> RecoverySnapshotWriteDecision:
        if (
            snapshot.execution_id != claim.execution_id
            or snapshot.writer_recovery_epoch != claim.recovery_epoch
            or snapshot.writer_recovery_owner_id != claim.recovery_owner_id
        ):
            return RecoverySnapshotWriteDecision(
                status=RecoverySnapshotWriteStatus.UNKNOWN,
                reason_codes=("RECOVERY_SNAPSHOT_WRITER_CLAIM_MISMATCH",),
            )
        try:
            validation = await self._epoch_guard.validate_current(claim)
        except Exception:  # noqa: BLE001
            validation = None
        if (
            not isinstance(validation, RecoveryEpochValidationDecision)
            or validation.status is RecoveryEpochValidationStatus.UNKNOWN
        ):
            return RecoverySnapshotWriteDecision(
                status=RecoverySnapshotWriteStatus.UNKNOWN,
                reason_codes=("RECOVERY_SNAPSHOT_EPOCH_UNKNOWN",),
                current_snapshot=await self._safe_load(snapshot.execution_id),
            )
        if validation.status is RecoveryEpochValidationStatus.STALE:
            return RecoverySnapshotWriteDecision(
                status=RecoverySnapshotWriteStatus.CONFLICT,
                reason_codes=("RECOVERY_SNAPSHOT_STALE_WRITER",),
                current_snapshot=await self._safe_load(snapshot.execution_id),
            )
        try:
            return await self._snapshot_store.compare_and_set(
                snapshot,
                expected_generation=expected_generation,
            )
        except Exception:  # noqa: BLE001
            return RecoverySnapshotWriteDecision(
                status=RecoverySnapshotWriteStatus.UNKNOWN,
                reason_codes=("RECOVERY_SNAPSHOT_STORE_UNKNOWN",),
                current_snapshot=await self._safe_load(snapshot.execution_id),
            )

    async def _safe_load(
        self,
        execution_id: str,
    ) -> ExecutionRecoverySnapshot | None:
        try:
            return await self._snapshot_store.load(execution_id)
        except Exception:  # noqa: BLE001
            return None
