"""M5-IU9 CA-04 Workflow checkpoint and whole-recovery decision contracts.

This module closes the remaining IU9 readiness gaps without widening M5 authority:
- exact, durable Workflow WAITING checkpoint authority
- exact-version Workflow resume request
- fail-closed whole-recovery disposition ordering

Recovery never replans, substitutes capabilities, aggregates ExecutionResult, or enters M6.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from runtime.contracts.enums import ExecutionPlanStatus
from runtime.execution.control_application import InFlightOperationKind
from runtime.execution.foundation import StepLifecycleSnapshot
from runtime.execution.models import (
    M5WorkflowResult,
    StepExecutionStatus,
    WorkflowExecutionStatus,
)
from runtime.execution.recovery import (
    ExecutionRecoveryClaim,
    ExecutionRecoverySnapshot,
    ExecutionRecoverySnapshotStore,
    RecoveryClaimAuthority,
    RecoveryEpochValidationStatus,
)
from runtime.execution.recovery_evidence import (
    DurableControlReadStatus,
    DurableInFlightEvidenceStore,
    DurableTerminalControlStore,
    InFlightEvidenceState,
    InFlightRecoveryTransitionStatus,
)
from runtime.execution.recovery_resource_lock import (
    DurableOperationResourceBindingStore,
)


def _require_non_blank(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


class WorkflowRecoveryCheckpointStatus(str, Enum):
    WAITING_COMMITTED = "WAITING_COMMITTED"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True, slots=True)
class WorkflowRecoveryCheckpoint:
    checkpoint_id: str
    generation: int
    execution_id: str
    step_execution_id: str
    workflow_instance_id: str
    workflow_id: str
    workflow_version: str
    state_reference: str
    resume_token: str
    status: WorkflowRecoveryCheckpointStatus
    committed_at: datetime
    writer_recovery_epoch: int

    def __post_init__(self) -> None:
        for name, value in (
            ("checkpoint_id", self.checkpoint_id),
            ("execution_id", self.execution_id),
            ("step_execution_id", self.step_execution_id),
            ("workflow_instance_id", self.workflow_instance_id),
            ("workflow_id", self.workflow_id),
            ("workflow_version", self.workflow_version),
            ("state_reference", self.state_reference),
            ("resume_token", self.resume_token),
        ):
            _require_non_blank(value, name)
        if self.generation < 1:
            raise ValueError("generation must be >= 1")
        if self.writer_recovery_epoch < 1:
            raise ValueError("writer_recovery_epoch must be >= 1")
        if not isinstance(self.status, WorkflowRecoveryCheckpointStatus):
            raise TypeError("status must be WorkflowRecoveryCheckpointStatus")
        _require_aware(self.committed_at, "committed_at")


class WorkflowCheckpointWriteStatus(str, Enum):
    COMMITTED = "COMMITTED"
    ALREADY_CURRENT = "ALREADY_CURRENT"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class WorkflowCheckpointWriteDecision:
    status: WorkflowCheckpointWriteStatus
    reason_codes: tuple[str, ...]
    checkpoint: WorkflowRecoveryCheckpoint | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, WorkflowCheckpointWriteStatus):
            raise TypeError("status must be WorkflowCheckpointWriteStatus")
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        if self.status in {
            WorkflowCheckpointWriteStatus.COMMITTED,
            WorkflowCheckpointWriteStatus.ALREADY_CURRENT,
        }:
            if self.checkpoint is None:
                raise ValueError("successful checkpoint decision requires checkpoint")
        elif self.checkpoint is not None:
            raise ValueError(
                "CONFLICT/UNKNOWN checkpoint decision cannot carry checkpoint"
            )


class WorkflowRecoveryCheckpointStore(Protocol):
    async def commit(
        self,
        checkpoint: WorkflowRecoveryCheckpoint,
        *,
        expected_generation: int,
        required_claim: ExecutionRecoveryClaim,
    ) -> WorkflowCheckpointWriteDecision:
        """Fence recovery epoch and durably commit exact Workflow checkpoint."""

    async def load(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
    ) -> WorkflowRecoveryCheckpoint | None:
        """Load latest exact Workflow checkpoint for one Step execution."""


class InMemoryWorkflowRecoveryCheckpointStore:
    """Reference fenced checkpoint store; not a production durability claim."""

    def __init__(self, *, claim_authority: RecoveryClaimAuthority) -> None:
        self._claim_authority = claim_authority
        self._records: dict[tuple[str, str], WorkflowRecoveryCheckpoint] = {}
        self._lock = asyncio.Lock()

    async def commit(
        self,
        checkpoint: WorkflowRecoveryCheckpoint,
        *,
        expected_generation: int,
        required_claim: ExecutionRecoveryClaim,
    ) -> WorkflowCheckpointWriteDecision:
        if checkpoint.execution_id != required_claim.execution_id:
            return WorkflowCheckpointWriteDecision(
                status=WorkflowCheckpointWriteStatus.CONFLICT,
                reason_codes=("WORKFLOW_CHECKPOINT_CLAIM_EXECUTION_MISMATCH",),
            )
        if checkpoint.writer_recovery_epoch != required_claim.recovery_epoch:
            return WorkflowCheckpointWriteDecision(
                status=WorkflowCheckpointWriteStatus.CONFLICT,
                reason_codes=("WORKFLOW_CHECKPOINT_RECOVERY_EPOCH_MISMATCH",),
            )
        try:
            fence = await self._claim_authority.validate_current(required_claim)
        except Exception:  # noqa: BLE001
            return WorkflowCheckpointWriteDecision(
                status=WorkflowCheckpointWriteStatus.UNKNOWN,
                reason_codes=("WORKFLOW_CHECKPOINT_RECOVERY_FENCE_UNKNOWN",),
            )
        if fence.status is RecoveryEpochValidationStatus.STALE:
            return WorkflowCheckpointWriteDecision(
                status=WorkflowCheckpointWriteStatus.CONFLICT,
                reason_codes=("WORKFLOW_CHECKPOINT_STALE_RECOVERY_EPOCH",),
            )
        if fence.status is not RecoveryEpochValidationStatus.CURRENT:
            return WorkflowCheckpointWriteDecision(
                status=WorkflowCheckpointWriteStatus.UNKNOWN,
                reason_codes=("WORKFLOW_CHECKPOINT_RECOVERY_FENCE_UNKNOWN",),
            )

        key = (checkpoint.execution_id, checkpoint.step_execution_id)
        async with self._lock:
            current = self._records.get(key)
            if current is None:
                if expected_generation != 0 or checkpoint.generation != 1:
                    return WorkflowCheckpointWriteDecision(
                        status=WorkflowCheckpointWriteStatus.CONFLICT,
                        reason_codes=(
                            "WORKFLOW_CHECKPOINT_CREATE_GENERATION_CONFLICT",
                        ),
                    )
                stored = deepcopy(checkpoint)
                self._records[key] = stored
                return WorkflowCheckpointWriteDecision(
                    status=WorkflowCheckpointWriteStatus.COMMITTED,
                    reason_codes=("WORKFLOW_CHECKPOINT_DURABLY_COMMITTED",),
                    checkpoint=deepcopy(stored),
                )

            if current == checkpoint:
                if expected_generation not in {
                    current.generation - 1,
                    current.generation,
                }:
                    return WorkflowCheckpointWriteDecision(
                        status=WorkflowCheckpointWriteStatus.CONFLICT,
                        reason_codes=(
                            "WORKFLOW_CHECKPOINT_REPLAY_GENERATION_CONFLICT",
                        ),
                    )
                return WorkflowCheckpointWriteDecision(
                    status=WorkflowCheckpointWriteStatus.ALREADY_CURRENT,
                    reason_codes=("WORKFLOW_CHECKPOINT_EXACT_REPLAY",),
                    checkpoint=deepcopy(current),
                )

            if expected_generation != current.generation:
                return WorkflowCheckpointWriteDecision(
                    status=WorkflowCheckpointWriteStatus.CONFLICT,
                    reason_codes=("WORKFLOW_CHECKPOINT_EXPECTED_GENERATION_CONFLICT",),
                )
            if checkpoint.generation != current.generation + 1:
                return WorkflowCheckpointWriteDecision(
                    status=WorkflowCheckpointWriteStatus.CONFLICT,
                    reason_codes=("WORKFLOW_CHECKPOINT_NEXT_GENERATION_INVALID",),
                )
            if checkpoint.committed_at < current.committed_at:
                return WorkflowCheckpointWriteDecision(
                    status=WorkflowCheckpointWriteStatus.CONFLICT,
                    reason_codes=("WORKFLOW_CHECKPOINT_TIME_REGRESSION",),
                )
            immutable_identity = (
                checkpoint.execution_id,
                checkpoint.step_execution_id,
                checkpoint.workflow_instance_id,
                checkpoint.workflow_id,
                checkpoint.workflow_version,
            )
            current_identity = (
                current.execution_id,
                current.step_execution_id,
                current.workflow_instance_id,
                current.workflow_id,
                current.workflow_version,
            )
            if immutable_identity != current_identity:
                return WorkflowCheckpointWriteDecision(
                    status=WorkflowCheckpointWriteStatus.CONFLICT,
                    reason_codes=("WORKFLOW_CHECKPOINT_IDENTITY_DRIFT",),
                )
            stored = deepcopy(checkpoint)
            self._records[key] = stored
            return WorkflowCheckpointWriteDecision(
                status=WorkflowCheckpointWriteStatus.COMMITTED,
                reason_codes=("WORKFLOW_CHECKPOINT_ADVANCED",),
                checkpoint=deepcopy(stored),
            )

    async def load(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
    ) -> WorkflowRecoveryCheckpoint | None:
        key = (execution_id, step_execution_id)
        async with self._lock:
            value = self._records.get(key)
            return None if value is None else deepcopy(value)


class WorkflowCheckpointCoordinator:
    """Commit WAITING as resumable only after exact durable checkpoint persistence."""

    def __init__(
        self,
        *,
        store: WorkflowRecoveryCheckpointStore,
        claim_authority: RecoveryClaimAuthority,
    ) -> None:
        self._store = store
        self._claim_authority = claim_authority

    async def commit_waiting(
        self,
        *,
        result: M5WorkflowResult,
        execution_id: str,
        step_execution_id: str,
        workflow_version: str,
        checkpoint_id: str,
        generation: int,
        expected_generation: int,
        state_reference: str,
        resume_token: str,
        committed_at: datetime,
        recovery_claim: ExecutionRecoveryClaim,
    ) -> WorkflowCheckpointWriteDecision:
        if result.status is not WorkflowExecutionStatus.WAITING:
            return WorkflowCheckpointWriteDecision(
                status=WorkflowCheckpointWriteStatus.CONFLICT,
                reason_codes=("WORKFLOW_CHECKPOINT_REQUIRES_WAITING_RESULT",),
            )
        if recovery_claim.execution_id != execution_id:
            return WorkflowCheckpointWriteDecision(
                status=WorkflowCheckpointWriteStatus.CONFLICT,
                reason_codes=("WORKFLOW_CHECKPOINT_CLAIM_EXECUTION_MISMATCH",),
            )
        try:
            fence = await self._claim_authority.validate_current(recovery_claim)
        except Exception:  # noqa: BLE001
            return WorkflowCheckpointWriteDecision(
                status=WorkflowCheckpointWriteStatus.UNKNOWN,
                reason_codes=("WORKFLOW_CHECKPOINT_RECOVERY_FENCE_UNKNOWN",),
            )
        if fence.status is RecoveryEpochValidationStatus.STALE:
            return WorkflowCheckpointWriteDecision(
                status=WorkflowCheckpointWriteStatus.CONFLICT,
                reason_codes=("WORKFLOW_CHECKPOINT_STALE_RECOVERY_EPOCH",),
            )
        if fence.status is not RecoveryEpochValidationStatus.CURRENT:
            return WorkflowCheckpointWriteDecision(
                status=WorkflowCheckpointWriteStatus.UNKNOWN,
                reason_codes=("WORKFLOW_CHECKPOINT_RECOVERY_FENCE_UNKNOWN",),
            )
        checkpoint = WorkflowRecoveryCheckpoint(
            checkpoint_id=checkpoint_id,
            generation=generation,
            execution_id=execution_id,
            step_execution_id=step_execution_id,
            workflow_instance_id=result.workflow_instance_id,
            workflow_id=result.workflow_id,
            workflow_version=workflow_version,
            state_reference=state_reference,
            resume_token=resume_token,
            status=WorkflowRecoveryCheckpointStatus.WAITING_COMMITTED,
            committed_at=committed_at,
            writer_recovery_epoch=recovery_claim.recovery_epoch,
        )
        return await self._store.commit(
            checkpoint,
            expected_generation=expected_generation,
            required_claim=recovery_claim,
        )


@dataclass(frozen=True, slots=True)
class WorkflowResumeRequest:
    execution_id: str
    step_execution_id: str
    workflow_instance_id: str
    workflow_id: str
    workflow_version: str
    checkpoint_id: str
    checkpoint_generation: int
    state_reference: str
    resume_token: str

    def __post_init__(self) -> None:
        for name, value in (
            ("execution_id", self.execution_id),
            ("step_execution_id", self.step_execution_id),
            ("workflow_instance_id", self.workflow_instance_id),
            ("workflow_id", self.workflow_id),
            ("workflow_version", self.workflow_version),
            ("checkpoint_id", self.checkpoint_id),
            ("state_reference", self.state_reference),
            ("resume_token", self.resume_token),
        ):
            _require_non_blank(value, name)
        if self.checkpoint_generation < 1:
            raise ValueError("checkpoint_generation must be >= 1")

    @classmethod
    def from_checkpoint(
        cls,
        checkpoint: WorkflowRecoveryCheckpoint,
    ) -> WorkflowResumeRequest:
        return cls(
            execution_id=checkpoint.execution_id,
            step_execution_id=checkpoint.step_execution_id,
            workflow_instance_id=checkpoint.workflow_instance_id,
            workflow_id=checkpoint.workflow_id,
            workflow_version=checkpoint.workflow_version,
            checkpoint_id=checkpoint.checkpoint_id,
            checkpoint_generation=checkpoint.generation,
            state_reference=checkpoint.state_reference,
            resume_token=checkpoint.resume_token,
        )


@runtime_checkable
class WorkflowRecoveryImplementation(Protocol):
    async def resume_from_checkpoint(
        self,
        request: WorkflowResumeRequest,
        execution_context: Any,
        tool_invoker: Any,
    ) -> Any:
        """Resume exact Workflow instance/version from an exact committed checkpoint."""


class WorkflowVersionAuthority(Protocol):
    async def expected_version(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
        workflow_id: str,
    ) -> str | None:
        """Return exact approved Workflow version; never a mutable latest version."""


class StepRecoveryReplayStatus(str, Enum):
    SAFE = "SAFE"
    UNSAFE = "UNSAFE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class StepRecoveryReplayDecision:
    status: StepRecoveryReplayStatus
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.status, StepRecoveryReplayStatus):
            raise TypeError("status must be StepRecoveryReplayStatus")
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")


class StepRecoveryReplayEvaluator(Protocol):
    async def evaluate(
        self,
        *,
        snapshot: ExecutionRecoverySnapshot,
        step: StepLifecycleSnapshot,
    ) -> StepRecoveryReplayDecision:
        """Project IU6 whole-Step replay safety into recovery without changing IU6 rules."""


class RecoveryDisposition(str, Enum):
    TERMINAL_NO_ACTION = "TERMINAL_NO_ACTION"
    APPLY_LATCHED_CONTROL = "APPLY_LATCHED_CONTROL"
    RESUME_SCHEDULING = "RESUME_SCHEDULING"
    RESUME_WORKFLOW = "RESUME_WORKFLOW"
    RETRY_STEP = "RETRY_STEP"
    WAIT_RECONCILIATION = "WAIT_RECONCILIATION"
    UNKNOWN_BLOCKED = "UNKNOWN_BLOCKED"


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    disposition: RecoveryDisposition
    reason_codes: tuple[str, ...]
    snapshot_generation: int
    workflow_resume_request: WorkflowResumeRequest | None = None
    retry_step_execution_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, RecoveryDisposition):
            raise TypeError("disposition must be RecoveryDisposition")
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        if self.snapshot_generation < 1:
            raise ValueError("snapshot_generation must be >= 1")
        if self.disposition is RecoveryDisposition.RESUME_WORKFLOW:
            if self.workflow_resume_request is None:
                raise ValueError("RESUME_WORKFLOW requires workflow_resume_request")
        elif self.workflow_resume_request is not None:
            raise ValueError("only RESUME_WORKFLOW may carry workflow_resume_request")
        if self.disposition is RecoveryDisposition.RETRY_STEP:
            if self.retry_step_execution_id is None:
                raise ValueError("RETRY_STEP requires retry_step_execution_id")
        elif self.retry_step_execution_id is not None:
            raise ValueError("only RETRY_STEP may carry retry_step_execution_id")


class RecoveryCoordinator:
    """Whole-recovery decision coordinator with frozen fail-closed ordering."""

    def __init__(
        self,
        *,
        claim_authority: RecoveryClaimAuthority,
        snapshot_store: ExecutionRecoverySnapshotStore,
        control_store: DurableTerminalControlStore,
        inflight_store: DurableInFlightEvidenceStore,
        resource_binding_store: DurableOperationResourceBindingStore,
        workflow_checkpoint_store: WorkflowRecoveryCheckpointStore,
        workflow_version_authority: WorkflowVersionAuthority,
        step_replay_evaluator: StepRecoveryReplayEvaluator,
    ) -> None:
        self._claim_authority = claim_authority
        self._snapshot_store = snapshot_store
        self._control_store = control_store
        self._inflight_store = inflight_store
        self._resource_binding_store = resource_binding_store
        self._workflow_checkpoint_store = workflow_checkpoint_store
        self._workflow_version_authority = workflow_version_authority
        self._step_replay_evaluator = step_replay_evaluator

    async def decide(
        self,
        *,
        recovery_claim: ExecutionRecoveryClaim,
        recovered_at: datetime,
    ) -> RecoveryDecision:
        _require_aware(recovered_at, "recovered_at")
        try:
            fence = await self._claim_authority.validate_current(recovery_claim)
        except Exception:  # noqa: BLE001
            return self._unknown(1, "RECOVERY_EPOCH_VALIDATION_UNKNOWN")
        if fence.status is not RecoveryEpochValidationStatus.CURRENT:
            reason = (
                "RECOVERY_EPOCH_STALE"
                if fence.status is RecoveryEpochValidationStatus.STALE
                else "RECOVERY_EPOCH_VALIDATION_UNKNOWN"
            )
            return self._unknown(1, reason)

        try:
            snapshot = await self._snapshot_store.load(recovery_claim.execution_id)
        except Exception:  # noqa: BLE001
            return self._unknown(1, "RECOVERY_SNAPSHOT_LOOKUP_UNKNOWN")
        if snapshot is None:
            return self._unknown(1, "RECOVERY_SNAPSHOT_MISSING")
        if snapshot.generation != recovery_claim.source_snapshot_generation:
            return self._unknown(
                snapshot.generation, "RECOVERY_SNAPSHOT_GENERATION_DRIFT"
            )

        if snapshot.execution_record.status in {
            item.value for item in ExecutionPlanStatus
        }:
            return RecoveryDecision(
                disposition=RecoveryDisposition.TERMINAL_NO_ACTION,
                reason_codes=("RECOVERY_EXECUTION_ALREADY_TERMINAL",),
                snapshot_generation=snapshot.generation,
            )

        try:
            control = await self._control_store.read_latched(
                recovery_claim.execution_id
            )
        except Exception:  # noqa: BLE001
            return self._unknown(snapshot.generation, "RECOVERY_CONTROL_LOOKUP_UNKNOWN")
        if control.status is DurableControlReadStatus.UNKNOWN:
            return self._unknown(snapshot.generation, "RECOVERY_CONTROL_STATE_UNKNOWN")
        if control.status is DurableControlReadStatus.LATCHED:
            return RecoveryDecision(
                disposition=RecoveryDisposition.APPLY_LATCHED_CONTROL,
                reason_codes=("RECOVERY_TERMINAL_CONTROL_BARRIER_PRESENT",),
                snapshot_generation=snapshot.generation,
            )

        try:
            orphan_transition = await self._inflight_store.recover_active_as_orphaned(
                execution_id=recovery_claim.execution_id,
                recovered_at=recovered_at,
                required_claim=recovery_claim,
            )
        except Exception:  # noqa: BLE001
            return self._unknown(
                snapshot.generation, "RECOVERY_INFLIGHT_TRANSITION_UNKNOWN"
            )
        if orphan_transition.status in {
            InFlightRecoveryTransitionStatus.CONFLICT,
            InFlightRecoveryTransitionStatus.UNKNOWN,
        }:
            return self._unknown(
                snapshot.generation, "RECOVERY_INFLIGHT_TRANSITION_UNSAFE"
            )

        running_steps = tuple(
            step
            for step in snapshot.steps
            if step.status is StepExecutionStatus.RUNNING
        )
        if len(running_steps) > 1:
            return self._unknown(
                snapshot.generation,
                "RECOVERY_OWNER_FRAME_SUPERSESSION_RUNNING_STEP_AMBIGUOUS",
            )
        if len(running_steps) == 1:
            running_step = running_steps[0]
            owner_kind: InFlightOperationKind | None = None
            capability_id: str | None = None
            if running_step.workflow_id is not None:
                owner_kind = InFlightOperationKind.WORKFLOW
                capability_id = running_step.workflow_id
            elif running_step.skill_id is not None:
                owner_kind = InFlightOperationKind.SKILL
                capability_id = running_step.skill_id

            if owner_kind is not None and capability_id is not None:
                try:
                    owner_supersession = (
                        await self._inflight_store.supersede_orphaned_owner_frame(
                            execution_id=recovery_claim.execution_id,
                            step_execution_id=running_step.step_execution_id,
                            owner_kind=owner_kind,
                            capability_id=capability_id,
                            recovered_at=recovered_at,
                            required_claim=recovery_claim,
                        )
                    )
                except Exception:  # noqa: BLE001
                    return self._unknown(
                        snapshot.generation,
                        "RECOVERY_OWNER_FRAME_SUPERSESSION_UNKNOWN",
                    )
                if owner_supersession.status in {
                    InFlightRecoveryTransitionStatus.CONFLICT,
                    InFlightRecoveryTransitionStatus.UNKNOWN,
                }:
                    return self._unknown(
                        snapshot.generation,
                        "RECOVERY_OWNER_FRAME_SUPERSESSION_UNSAFE",
                    )

        try:
            inflight = await self._inflight_store.load_inflight(
                execution_id=recovery_claim.execution_id,
            )
        except Exception:  # noqa: BLE001
            return self._unknown(
                snapshot.generation, "RECOVERY_INFLIGHT_LOOKUP_UNKNOWN"
            )
        unresolved_states = {
            InFlightEvidenceState.ACTIVE_AT_CHECKPOINT,
            InFlightEvidenceState.ORPHANED_UNCONFIRMED,
            InFlightEvidenceState.UNKNOWN,
        }
        if any(item.state in unresolved_states for item in inflight):
            return RecoveryDecision(
                disposition=RecoveryDisposition.WAIT_RECONCILIATION,
                reason_codes=("RECOVERY_INFLIGHT_OPERATION_UNRESOLVED",),
                snapshot_generation=snapshot.generation,
            )

        try:
            active_bindings = await self._resource_binding_store.active_for_execution(
                recovery_claim.execution_id
            )
        except Exception:  # noqa: BLE001
            return self._unknown(
                snapshot.generation, "RECOVERY_RESOURCE_BINDING_LOOKUP_UNKNOWN"
            )
        if active_bindings:
            return RecoveryDecision(
                disposition=RecoveryDisposition.WAIT_RECONCILIATION,
                reason_codes=("RECOVERY_ACTIVE_RESOURCE_BINDING_REMAINS",),
                snapshot_generation=snapshot.generation,
            )

        if len(running_steps) > 1:
            return self._unknown(snapshot.generation, "RECOVERY_MULTIPLE_RUNNING_STEPS")
        if len(running_steps) == 1:
            step = running_steps[0]
            if step.workflow_id is not None:
                return await self._decide_workflow(snapshot, step)
            if step.skill_id is not None:
                return await self._decide_skill(snapshot, step)
            return self._unknown(
                snapshot.generation, "RECOVERY_RUNNING_STEP_OWNER_UNKNOWN"
            )

        return RecoveryDecision(
            disposition=RecoveryDisposition.RESUME_SCHEDULING,
            reason_codes=("RECOVERY_NO_RUNNING_STEP_SCHEDULER_REENTRY_ALLOWED",),
            snapshot_generation=snapshot.generation,
        )

    async def _decide_workflow(
        self,
        snapshot: ExecutionRecoverySnapshot,
        step: StepLifecycleSnapshot,
    ) -> RecoveryDecision:
        try:
            checkpoint = await self._workflow_checkpoint_store.load(
                execution_id=snapshot.execution_id,
                step_execution_id=step.step_execution_id,
            )
        except Exception:  # noqa: BLE001
            return self._unknown(
                snapshot.generation, "WORKFLOW_CHECKPOINT_LOOKUP_UNKNOWN"
            )
        if checkpoint is None:
            return RecoveryDecision(
                disposition=RecoveryDisposition.WAIT_RECONCILIATION,
                reason_codes=("WORKFLOW_WAITING_CHECKPOINT_NOT_DURABLE",),
                snapshot_generation=snapshot.generation,
            )
        if checkpoint.status is not WorkflowRecoveryCheckpointStatus.WAITING_COMMITTED:
            return self._unknown(
                snapshot.generation, "WORKFLOW_CHECKPOINT_NOT_RESUMABLE"
            )
        if checkpoint.execution_id != snapshot.execution_id:
            return self._unknown(
                snapshot.generation, "WORKFLOW_CHECKPOINT_EXECUTION_MISMATCH"
            )
        if checkpoint.step_execution_id != step.step_execution_id:
            return self._unknown(
                snapshot.generation, "WORKFLOW_CHECKPOINT_STEP_MISMATCH"
            )
        if checkpoint.workflow_id != step.workflow_id:
            return self._unknown(snapshot.generation, "WORKFLOW_CHECKPOINT_ID_MISMATCH")
        try:
            expected_version = await self._workflow_version_authority.expected_version(
                execution_id=snapshot.execution_id,
                step_execution_id=step.step_execution_id,
                workflow_id=checkpoint.workflow_id,
            )
        except Exception:  # noqa: BLE001
            expected_version = None
        if expected_version is None:
            return self._unknown(
                snapshot.generation, "WORKFLOW_APPROVED_VERSION_UNKNOWN"
            )
        if expected_version != checkpoint.workflow_version:
            return self._unknown(
                snapshot.generation, "WORKFLOW_CHECKPOINT_VERSION_MISMATCH"
            )
        return RecoveryDecision(
            disposition=RecoveryDisposition.RESUME_WORKFLOW,
            reason_codes=("WORKFLOW_EXACT_DURABLE_CHECKPOINT_RESUME_AUTHORIZED",),
            snapshot_generation=snapshot.generation,
            workflow_resume_request=WorkflowResumeRequest.from_checkpoint(checkpoint),
        )

    async def _decide_skill(
        self,
        snapshot: ExecutionRecoverySnapshot,
        step: StepLifecycleSnapshot,
    ) -> RecoveryDecision:
        try:
            replay = await self._step_replay_evaluator.evaluate(
                snapshot=snapshot,
                step=step,
            )
        except Exception:  # noqa: BLE001
            return self._unknown(snapshot.generation, "SKILL_REPLAY_EVALUATION_UNKNOWN")
        if replay.status is StepRecoveryReplayStatus.SAFE:
            return RecoveryDecision(
                disposition=RecoveryDisposition.RETRY_STEP,
                reason_codes=("SKILL_WHOLE_STEP_REPLAY_SAFE", *replay.reason_codes),
                snapshot_generation=snapshot.generation,
                retry_step_execution_id=step.step_execution_id,
            )
        if replay.status is StepRecoveryReplayStatus.UNSAFE:
            return RecoveryDecision(
                disposition=RecoveryDisposition.WAIT_RECONCILIATION,
                reason_codes=("SKILL_WHOLE_STEP_REPLAY_UNSAFE", *replay.reason_codes),
                snapshot_generation=snapshot.generation,
            )
        return self._unknown(
            snapshot.generation,
            "SKILL_WHOLE_STEP_REPLAY_UNKNOWN",
            *replay.reason_codes,
        )

    @staticmethod
    def _unknown(
        generation: int,
        *reason_codes: str,
    ) -> RecoveryDecision:
        return RecoveryDecision(
            disposition=RecoveryDisposition.UNKNOWN_BLOCKED,
            reason_codes=tuple(reason_codes),
            snapshot_generation=max(1, generation),
        )
