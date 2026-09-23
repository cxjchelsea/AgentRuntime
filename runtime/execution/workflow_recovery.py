"""CA-M5-IU9-04 Workflow checkpoint and recovery-decision authority.

This module closes the crash-recovery authority gap without adding replanning,
ExecutionResult aggregation, or M6 validation.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from runtime.contracts.execution import ExecutionContext
from runtime.execution.capability_resolution import (
    CapabilityExecutionOwner,
    CapabilityKind,
    ResolvedStepCapabilities,
)
from runtime.execution.control_application import InFlightOperationHandle
from runtime.execution.invocation import ApprovedToolInvoker
from runtime.execution.models import (
    M5WorkflowResult,
    StepExecutionStatus,
    WorkflowExecutionStatus,
    WorkflowResumeRequest,
)
from runtime.execution.protocols import WorkflowImplementation
from runtime.execution.recovery import (
    ExecutionRecoveryClaim,
    ExecutionRecoverySnapshot,
    RecoveryClaimAuthority,
    RecoveryEpochValidationStatus,
)
from runtime.execution.recovery_evidence import (
    DurableControlReadDecision,
    DurableControlReadStatus,
    DurableInFlightOperationObservation,
    InFlightRecoveryTransitionDecision,
    InFlightEvidenceState,
    InFlightRecoveryTransitionStatus,
)
from runtime.execution.recovery_resource_lock import (
    DurableOperationResourceBindingRecord,
    OperationRecoveryDecision,
    OperationRecoveryProbe,
    OperationRecoveryStatus,
    ResourceRecoveryStatus,
    ToolResourceRecoveryCoordinator,
)
from runtime.execution.reliability import ReplaySafetyStatus
from runtime.execution.reliability_boundary import (
    StepAttemptSequenceAuthority,
    StepAttemptSequenceStatus,
    StepReplaySafetyEvaluator,
    StepReplaySafetyRequest,
)
from runtime.registries.definitions import WorkflowDefinition


WORKFLOW_RECOVERY_CHECKPOINT_SCHEMA_VERSION = "m5-iu9-workflow-checkpoint-v1"


def _require_non_blank(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be blank")


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


class WorkflowRecoveryCheckpointStatus(str, Enum):
    COMMITTED = "COMMITTED"


@dataclass(frozen=True, slots=True)
class WorkflowCheckpointMaterial:
    """Opaque Domain/adapter state reference returned after durable state persistence."""

    state_reference: str
    resume_token: str
    state_schema_version: str

    def __post_init__(self) -> None:
        _require_non_blank(self.state_reference, "state_reference")
        _require_non_blank(self.resume_token, "resume_token")
        _require_non_blank(self.state_schema_version, "state_schema_version")


@dataclass(frozen=True, slots=True)
class WorkflowRecoveryCheckpoint:
    execution_id: str
    step_id: str
    step_execution_id: str
    workflow_instance_id: str
    workflow_id: str
    workflow_version: str
    checkpoint_id: str
    generation: int
    material: WorkflowCheckpointMaterial
    committed_at: datetime
    writer_recovery_epoch: int
    writer_recovery_owner_id: str
    status: WorkflowRecoveryCheckpointStatus = WorkflowRecoveryCheckpointStatus.COMMITTED
    schema_version: str = WORKFLOW_RECOVERY_CHECKPOINT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name, value in (
            ("execution_id", self.execution_id),
            ("step_id", self.step_id),
            ("step_execution_id", self.step_execution_id),
            ("workflow_instance_id", self.workflow_instance_id),
            ("workflow_id", self.workflow_id),
            ("workflow_version", self.workflow_version),
            ("checkpoint_id", self.checkpoint_id),
            ("writer_recovery_owner_id", self.writer_recovery_owner_id),
        ):
            _require_non_blank(value, name)
        if self.generation < 1:
            raise ValueError("generation must be >= 1")
        if self.writer_recovery_epoch < 1:
            raise ValueError("writer_recovery_epoch must be >= 1")
        if not isinstance(self.status, WorkflowRecoveryCheckpointStatus):
            raise TypeError("status must be WorkflowRecoveryCheckpointStatus")
        if self.status is not WorkflowRecoveryCheckpointStatus.COMMITTED:
            raise ValueError("only COMMITTED checkpoint is resumable")
        if self.schema_version != WORKFLOW_RECOVERY_CHECKPOINT_SCHEMA_VERSION:
            raise ValueError("workflow recovery checkpoint schema is unsupported")
        _require_aware(self.committed_at, "committed_at")


class WorkflowCheckpointCommitStatus(str, Enum):
    COMMITTED = "COMMITTED"
    ALREADY_COMMITTED = "ALREADY_COMMITTED"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class WorkflowCheckpointCommitDecision:
    status: WorkflowCheckpointCommitStatus
    reason_codes: tuple[str, ...]
    checkpoint: WorkflowRecoveryCheckpoint | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, WorkflowCheckpointCommitStatus):
            raise TypeError("status must be WorkflowCheckpointCommitStatus")
        if not self.reason_codes or any(not item.strip() for item in self.reason_codes):
            raise ValueError("reason_codes must contain non-blank values")
        if self.status in {
            WorkflowCheckpointCommitStatus.COMMITTED,
            WorkflowCheckpointCommitStatus.ALREADY_COMMITTED,
        }:
            if self.checkpoint is None:
                raise ValueError("successful checkpoint commit requires checkpoint")
        elif self.checkpoint is not None:
            raise ValueError("CONFLICT/UNKNOWN cannot expose checkpoint authority")


class WorkflowCheckpointReadStatus(str, Enum):
    NONE = "NONE"
    COMMITTED = "COMMITTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class WorkflowCheckpointReadDecision:
    status: WorkflowCheckpointReadStatus
    reason_codes: tuple[str, ...]
    checkpoint: WorkflowRecoveryCheckpoint | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, WorkflowCheckpointReadStatus):
            raise TypeError("status must be WorkflowCheckpointReadStatus")
        if not self.reason_codes or any(not item.strip() for item in self.reason_codes):
            raise ValueError("reason_codes must contain non-blank values")
        if self.status is WorkflowCheckpointReadStatus.COMMITTED:
            if self.checkpoint is None:
                raise ValueError("COMMITTED checkpoint read requires checkpoint")
        elif self.checkpoint is not None:
            raise ValueError("NONE/UNKNOWN checkpoint read cannot expose checkpoint")


class WorkflowRecoveryCheckpointStore(Protocol):
    async def commit(
        self,
        checkpoint: WorkflowRecoveryCheckpoint,
        *,
        expected_generation: int,
        required_claim: ExecutionRecoveryClaim,
    ) -> WorkflowCheckpointCommitDecision:
        """CAS-commit one exact Workflow recovery checkpoint."""

    async def read_latest(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
    ) -> WorkflowCheckpointReadDecision:
        """Read the latest exact checkpoint without collapsing uncertainty to NONE."""


class WorkflowCheckpointAdapter(Protocol):
    async def persist_waiting_state(
        self,
        *,
        execution_id: str,
        step_id: str,
        step_execution_id: str,
        workflow_instance_id: str,
        workflow_id: str,
        workflow_version: str,
        result: M5WorkflowResult,
        checkpoint_id: str,
        generation: int,
        requested_at: datetime,
    ) -> WorkflowCheckpointMaterial:
        """Persist Domain/Workflow state and return opaque durable recovery material."""


class InMemoryWorkflowRecoveryCheckpointStore(WorkflowRecoveryCheckpointStore):
    """Reference CAS store. Production adapters must provide equivalent durability."""

    def __init__(self, *, claim_authority: RecoveryClaimAuthority) -> None:
        self._claim_authority = claim_authority
        self._lock = asyncio.Lock()
        self._latest: dict[tuple[str, str], WorkflowRecoveryCheckpoint] = {}
        self._by_checkpoint_id: dict[str, WorkflowRecoveryCheckpoint] = {}

    async def commit(
        self,
        checkpoint: WorkflowRecoveryCheckpoint,
        *,
        expected_generation: int,
        required_claim: ExecutionRecoveryClaim,
    ) -> WorkflowCheckpointCommitDecision:
        if expected_generation < 0:
            return WorkflowCheckpointCommitDecision(
                status=WorkflowCheckpointCommitStatus.UNKNOWN,
                reason_codes=("WORKFLOW_CHECKPOINT_EXPECTED_GENERATION_INVALID",),
            )
        if checkpoint.execution_id != required_claim.execution_id:
            return WorkflowCheckpointCommitDecision(
                status=WorkflowCheckpointCommitStatus.UNKNOWN,
                reason_codes=("WORKFLOW_CHECKPOINT_RECOVERY_EXECUTION_MISMATCH",),
            )
        try:
            epoch = await self._claim_authority.validate_current(required_claim)
        except Exception:  # noqa: BLE001
            return WorkflowCheckpointCommitDecision(
                status=WorkflowCheckpointCommitStatus.UNKNOWN,
                reason_codes=("WORKFLOW_CHECKPOINT_RECOVERY_EPOCH_CHECK_EXCEPTION",),
            )
        if epoch.status is not RecoveryEpochValidationStatus.CURRENT:
            return WorkflowCheckpointCommitDecision(
                status=(
                    WorkflowCheckpointCommitStatus.CONFLICT
                    if epoch.status is RecoveryEpochValidationStatus.STALE
                    else WorkflowCheckpointCommitStatus.UNKNOWN
                ),
                reason_codes=(
                    "WORKFLOW_CHECKPOINT_STALE_RECOVERY_EPOCH"
                    if epoch.status is RecoveryEpochValidationStatus.STALE
                    else "WORKFLOW_CHECKPOINT_RECOVERY_EPOCH_UNKNOWN"
                ,),
            )

        key = (checkpoint.execution_id, checkpoint.step_execution_id)
        async with self._lock:
            replay = self._by_checkpoint_id.get(checkpoint.checkpoint_id)
            if replay is not None:
                if replay == checkpoint:
                    return WorkflowCheckpointCommitDecision(
                        status=WorkflowCheckpointCommitStatus.ALREADY_COMMITTED,
                        reason_codes=("WORKFLOW_CHECKPOINT_EXACT_REPLAY",),
                        checkpoint=deepcopy(replay),
                    )
                return WorkflowCheckpointCommitDecision(
                    status=WorkflowCheckpointCommitStatus.CONFLICT,
                    reason_codes=("WORKFLOW_CHECKPOINT_IDENTITY_REBIND_CONFLICT",),
                )

            current = self._latest.get(key)
            current_generation = 0 if current is None else current.generation
            if expected_generation != current_generation:
                return WorkflowCheckpointCommitDecision(
                    status=WorkflowCheckpointCommitStatus.CONFLICT,
                    reason_codes=("WORKFLOW_CHECKPOINT_GENERATION_CONFLICT",),
                )
            if checkpoint.generation != expected_generation + 1:
                return WorkflowCheckpointCommitDecision(
                    status=WorkflowCheckpointCommitStatus.CONFLICT,
                    reason_codes=("WORKFLOW_CHECKPOINT_GENERATION_NOT_CONTIGUOUS",),
                )
            if current is not None:
                if (
                    current.execution_id != checkpoint.execution_id
                    or current.step_id != checkpoint.step_id
                    or current.step_execution_id != checkpoint.step_execution_id
                    or current.workflow_instance_id != checkpoint.workflow_instance_id
                    or current.workflow_id != checkpoint.workflow_id
                    or current.workflow_version != checkpoint.workflow_version
                ):
                    return WorkflowCheckpointCommitDecision(
                        status=WorkflowCheckpointCommitStatus.CONFLICT,
                        reason_codes=("WORKFLOW_CHECKPOINT_PROVENANCE_DRIFT",),
                    )
                if checkpoint.committed_at < current.committed_at:
                    return WorkflowCheckpointCommitDecision(
                        status=WorkflowCheckpointCommitStatus.CONFLICT,
                        reason_codes=("WORKFLOW_CHECKPOINT_TIME_REGRESSION",),
                    )

            self._latest[key] = deepcopy(checkpoint)
            self._by_checkpoint_id[checkpoint.checkpoint_id] = deepcopy(checkpoint)
            return WorkflowCheckpointCommitDecision(
                status=WorkflowCheckpointCommitStatus.COMMITTED,
                reason_codes=("WORKFLOW_CHECKPOINT_DURABLY_COMMITTED",),
                checkpoint=deepcopy(checkpoint),
            )

    async def read_latest(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
    ) -> WorkflowCheckpointReadDecision:
        if (
            not isinstance(execution_id, str)
            or not execution_id.strip()
            or not isinstance(step_execution_id, str)
            or not step_execution_id.strip()
        ):
            return WorkflowCheckpointReadDecision(
                status=WorkflowCheckpointReadStatus.UNKNOWN,
                reason_codes=("WORKFLOW_CHECKPOINT_READ_IDENTITY_INVALID",),
            )
        async with self._lock:
            current = self._latest.get((execution_id, step_execution_id))
            if current is None:
                return WorkflowCheckpointReadDecision(
                    status=WorkflowCheckpointReadStatus.NONE,
                    reason_codes=("WORKFLOW_CHECKPOINT_NOT_FOUND",),
                )
            return WorkflowCheckpointReadDecision(
                status=WorkflowCheckpointReadStatus.COMMITTED,
                reason_codes=("WORKFLOW_CHECKPOINT_FOUND",),
                checkpoint=deepcopy(current),
            )


class WorkflowWaitingCheckpointCoordinator:
    """Make WAITING recoverable only after exact Domain state + Core checkpoint commit."""

    def __init__(
        self,
        *,
        claim_authority: RecoveryClaimAuthority,
        store: WorkflowRecoveryCheckpointStore,
        adapter: WorkflowCheckpointAdapter,
    ) -> None:
        self._claim_authority = claim_authority
        self._store = store
        self._adapter = adapter

    async def commit_waiting(
        self,
        *,
        result: M5WorkflowResult,
        execution_id: str,
        step_id: str,
        step_execution_id: str,
        workflow_version: str,
        checkpoint_id: str,
        expected_generation: int,
        recovery_claim: ExecutionRecoveryClaim,
        observed_at: datetime,
    ) -> WorkflowCheckpointCommitDecision:
        _require_aware(observed_at, "observed_at")
        for name, value in (
            ("execution_id", execution_id),
            ("step_id", step_id),
            ("step_execution_id", step_execution_id),
            ("workflow_version", workflow_version),
            ("checkpoint_id", checkpoint_id),
        ):
            _require_non_blank(value, name)
        if result.status is not WorkflowExecutionStatus.WAITING:
            return WorkflowCheckpointCommitDecision(
                status=WorkflowCheckpointCommitStatus.UNKNOWN,
                reason_codes=("WORKFLOW_CHECKPOINT_REQUIRES_WAITING_RESULT",),
            )
        if expected_generation < 0:
            return WorkflowCheckpointCommitDecision(
                status=WorkflowCheckpointCommitStatus.UNKNOWN,
                reason_codes=("WORKFLOW_CHECKPOINT_EXPECTED_GENERATION_INVALID",),
            )
        if recovery_claim.execution_id != execution_id:
            return WorkflowCheckpointCommitDecision(
                status=WorkflowCheckpointCommitStatus.UNKNOWN,
                reason_codes=("WORKFLOW_CHECKPOINT_RECOVERY_EXECUTION_MISMATCH",),
            )
        try:
            epoch = await self._claim_authority.validate_current(recovery_claim)
        except Exception:  # noqa: BLE001
            return WorkflowCheckpointCommitDecision(
                status=WorkflowCheckpointCommitStatus.UNKNOWN,
                reason_codes=("WORKFLOW_CHECKPOINT_RECOVERY_EPOCH_CHECK_EXCEPTION",),
            )
        if epoch.status is not RecoveryEpochValidationStatus.CURRENT:
            return WorkflowCheckpointCommitDecision(
                status=(
                    WorkflowCheckpointCommitStatus.CONFLICT
                    if epoch.status is RecoveryEpochValidationStatus.STALE
                    else WorkflowCheckpointCommitStatus.UNKNOWN
                ),
                reason_codes=(
                    "WORKFLOW_CHECKPOINT_STALE_RECOVERY_EPOCH"
                    if epoch.status is RecoveryEpochValidationStatus.STALE
                    else "WORKFLOW_CHECKPOINT_RECOVERY_EPOCH_UNKNOWN"
                ,),
            )

        try:
            preflight = await self._store.read_latest(
                execution_id=execution_id,
                step_execution_id=step_execution_id,
            )
        except Exception:  # noqa: BLE001
            return WorkflowCheckpointCommitDecision(
                status=WorkflowCheckpointCommitStatus.UNKNOWN,
                reason_codes=("WORKFLOW_CHECKPOINT_PREFLIGHT_READ_EXCEPTION",),
            )
        if preflight.status is WorkflowCheckpointReadStatus.UNKNOWN:
            return WorkflowCheckpointCommitDecision(
                status=WorkflowCheckpointCommitStatus.UNKNOWN,
                reason_codes=preflight.reason_codes,
            )
        if preflight.status is WorkflowCheckpointReadStatus.COMMITTED:
            current = preflight.checkpoint
            if current is None:
                return WorkflowCheckpointCommitDecision(
                    status=WorkflowCheckpointCommitStatus.UNKNOWN,
                    reason_codes=("WORKFLOW_CHECKPOINT_PREFLIGHT_INVALID",),
                )
            if (
                current.checkpoint_id == checkpoint_id
                and current.generation == expected_generation + 1
                and current.execution_id == execution_id
                and current.step_id == step_id
                and current.step_execution_id == step_execution_id
                and current.workflow_instance_id == result.workflow_instance_id
                and current.workflow_id == result.workflow_id
                and current.workflow_version == workflow_version
            ):
                return WorkflowCheckpointCommitDecision(
                    status=WorkflowCheckpointCommitStatus.ALREADY_COMMITTED,
                    reason_codes=("WORKFLOW_CHECKPOINT_EXACT_REPLAY_PREFLIGHT",),
                    checkpoint=current,
                )
            if current.generation != expected_generation:
                return WorkflowCheckpointCommitDecision(
                    status=WorkflowCheckpointCommitStatus.CONFLICT,
                    reason_codes=("WORKFLOW_CHECKPOINT_GENERATION_CONFLICT",),
                )
            if (
                current.execution_id != execution_id
                or current.step_id != step_id
                or current.step_execution_id != step_execution_id
                or current.workflow_instance_id != result.workflow_instance_id
                or current.workflow_id != result.workflow_id
                or current.workflow_version != workflow_version
            ):
                return WorkflowCheckpointCommitDecision(
                    status=WorkflowCheckpointCommitStatus.CONFLICT,
                    reason_codes=("WORKFLOW_CHECKPOINT_PROVENANCE_DRIFT",),
                )
        elif expected_generation != 0:
            return WorkflowCheckpointCommitDecision(
                status=WorkflowCheckpointCommitStatus.CONFLICT,
                reason_codes=("WORKFLOW_CHECKPOINT_BASE_GENERATION_MISSING",),
            )

        generation = expected_generation + 1
        try:
            material = await self._adapter.persist_waiting_state(
                execution_id=execution_id,
                step_id=step_id,
                step_execution_id=step_execution_id,
                workflow_instance_id=result.workflow_instance_id,
                workflow_id=result.workflow_id,
                workflow_version=workflow_version,
                result=result,
                checkpoint_id=checkpoint_id,
                generation=generation,
                requested_at=observed_at,
            )
        except Exception:  # noqa: BLE001
            return WorkflowCheckpointCommitDecision(
                status=WorkflowCheckpointCommitStatus.UNKNOWN,
                reason_codes=("WORKFLOW_STATE_PERSISTENCE_EXCEPTION",),
            )
        if not isinstance(material, WorkflowCheckpointMaterial):
            return WorkflowCheckpointCommitDecision(
                status=WorkflowCheckpointCommitStatus.UNKNOWN,
                reason_codes=("WORKFLOW_STATE_PERSISTENCE_INVALID_RESULT",),
            )

        checkpoint = WorkflowRecoveryCheckpoint(
            execution_id=execution_id,
            step_id=step_id,
            step_execution_id=step_execution_id,
            workflow_instance_id=result.workflow_instance_id,
            workflow_id=result.workflow_id,
            workflow_version=workflow_version,
            checkpoint_id=checkpoint_id,
            generation=generation,
            material=material,
            committed_at=observed_at,
            writer_recovery_epoch=recovery_claim.recovery_epoch,
            writer_recovery_owner_id=recovery_claim.recovery_owner_id,
        )
        return await self._store.commit(
            checkpoint,
            expected_generation=expected_generation,
            required_claim=recovery_claim,
        )


class WorkflowResumeStatus(str, Enum):
    RESUMED = "RESUMED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class WorkflowResumeDecision:
    status: WorkflowResumeStatus
    reason_codes: tuple[str, ...]
    result: M5WorkflowResult | None = None
    checkpoint_commit_required: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.status, WorkflowResumeStatus):
            raise TypeError("status must be WorkflowResumeStatus")
        if not self.reason_codes or any(not item.strip() for item in self.reason_codes):
            raise ValueError("reason_codes must contain non-blank values")
        if self.status is WorkflowResumeStatus.RESUMED:
            if self.result is None:
                raise ValueError("RESUMED requires Workflow result")
            expected = self.result.status is WorkflowExecutionStatus.WAITING
            if self.checkpoint_commit_required is not expected:
                raise ValueError(
                    "WAITING resumed result must require a new durable checkpoint"
                )
        elif self.result is not None or self.checkpoint_commit_required:
            raise ValueError("UNKNOWN resume cannot claim result/checkpoint requirement")


class WorkflowResumeCoordinator:
    """Resume the same exact Workflow instance and approved version from latest checkpoint."""

    def __init__(
        self,
        *,
        claim_authority: RecoveryClaimAuthority,
        checkpoint_store: WorkflowRecoveryCheckpointStore,
    ) -> None:
        self._claim_authority = claim_authority
        self._checkpoint_store = checkpoint_store

    async def resume(
        self,
        *,
        checkpoint: WorkflowRecoveryCheckpoint,
        resolved: ResolvedStepCapabilities,
        execution_context: ExecutionContext,
        tool_invoker: ApprovedToolInvoker,
        recovery_claim: ExecutionRecoveryClaim,
        event: str | None = None,
    ) -> WorkflowResumeDecision:
        try:
            epoch = await self._claim_authority.validate_current(recovery_claim)
        except Exception:  # noqa: BLE001
            return self._unknown("WORKFLOW_RESUME_RECOVERY_EPOCH_CHECK_EXCEPTION")
        if epoch.status is not RecoveryEpochValidationStatus.CURRENT:
            return self._unknown(
                "WORKFLOW_RESUME_STALE_RECOVERY_EPOCH"
                if epoch.status is RecoveryEpochValidationStatus.STALE
                else "WORKFLOW_RESUME_RECOVERY_EPOCH_UNKNOWN"
            )
        if (
            checkpoint.execution_id != recovery_claim.execution_id
            or execution_context.execution_id != checkpoint.execution_id
            or resolved.step_id != checkpoint.step_id
        ):
            return self._unknown("WORKFLOW_RESUME_EXECUTION_PROVENANCE_MISMATCH")
        try:
            latest = await self._checkpoint_store.read_latest(
                execution_id=checkpoint.execution_id,
                step_execution_id=checkpoint.step_execution_id,
            )
        except Exception:  # noqa: BLE001
            return self._unknown("WORKFLOW_RESUME_CHECKPOINT_READ_EXCEPTION")
        if (
            latest.status is not WorkflowCheckpointReadStatus.COMMITTED
            or latest.checkpoint is None
        ):
            return self._unknown("WORKFLOW_RESUME_LATEST_CHECKPOINT_UNAVAILABLE")
        if latest.checkpoint != checkpoint:
            return self._unknown("WORKFLOW_RESUME_CHECKPOINT_IS_NOT_LATEST")
        if (
            resolved.execution_owner is not CapabilityExecutionOwner.WORKFLOW
            or resolved.workflow is None
            or resolved.workflow.kind is not CapabilityKind.WORKFLOW
        ):
            return self._unknown("WORKFLOW_RESUME_OWNER_BINDING_INVALID")

        workflow = resolved.workflow
        definition = workflow.definition
        implementation = workflow.implementation_ref
        if not isinstance(definition, WorkflowDefinition) or not isinstance(
            implementation, WorkflowImplementation
        ):
            return self._unknown("WORKFLOW_RESUME_BINDING_TYPE_INVALID")
        if (
            workflow.capability_id != checkpoint.workflow_id
            or workflow.version != checkpoint.workflow_version
            or definition.workflow_id != checkpoint.workflow_id
            or definition.version != checkpoint.workflow_version
        ):
            return self._unknown("WORKFLOW_RESUME_EXACT_VERSION_MISMATCH")
        if definition.checkpoint_enabled is not True:
            return self._unknown("WORKFLOW_RESUME_CHECKPOINT_NOT_ENABLED")
        if definition.resume_policy is None or not definition.resume_policy.strip():
            return self._unknown("WORKFLOW_RESUME_POLICY_MISSING")

        request = WorkflowResumeRequest(
            execution_id=checkpoint.execution_id,
            step_execution_id=checkpoint.step_execution_id,
            workflow_instance_id=checkpoint.workflow_instance_id,
            workflow_id=checkpoint.workflow_id,
            workflow_version=checkpoint.workflow_version,
            checkpoint_id=checkpoint.checkpoint_id,
            checkpoint_generation=checkpoint.generation,
            state_reference=checkpoint.material.state_reference,
            resume_token=checkpoint.material.resume_token,
            checkpoint_schema_version=checkpoint.material.state_schema_version,
            event=event,
            inputs={},
        )
        try:
            result = await implementation.resume(
                request,
                execution_context,
                tool_invoker,
            )
        except Exception:  # noqa: BLE001
            return self._unknown("WORKFLOW_RESUME_IMPLEMENTATION_EXCEPTION")
        if (
            not isinstance(result, M5WorkflowResult)
            or not isinstance(result.status, WorkflowExecutionStatus)
            or result.workflow_id != checkpoint.workflow_id
            or result.workflow_instance_id != checkpoint.workflow_instance_id
        ):
            return self._unknown("WORKFLOW_RESUME_RESULT_IDENTITY_MISMATCH")
        return WorkflowResumeDecision(
            status=WorkflowResumeStatus.RESUMED,
            reason_codes=("WORKFLOW_RESUMED_FROM_EXACT_CHECKPOINT",),
            result=result,
            checkpoint_commit_required=(
                result.status is WorkflowExecutionStatus.WAITING
            ),
        )

    @staticmethod
    def _unknown(reason: str) -> WorkflowResumeDecision:
        return WorkflowResumeDecision(
            status=WorkflowResumeStatus.UNKNOWN,
            reason_codes=(reason,),
        )


class SkillRecoveryReplayStatus(str, Enum):
    SAFE = "SAFE"
    UNSAFE = "UNSAFE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class SkillRecoveryReplayDecision:
    status: SkillRecoveryReplayStatus
    reason_codes: tuple[str, ...]
    next_attempt: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, SkillRecoveryReplayStatus):
            raise TypeError("status must be SkillRecoveryReplayStatus")
        if not self.reason_codes or any(not item.strip() for item in self.reason_codes):
            raise ValueError("reason_codes must contain non-blank values")
        if self.status is SkillRecoveryReplayStatus.SAFE:
            if self.next_attempt is None or self.next_attempt < 2:
                raise ValueError("SAFE Skill recovery requires next_attempt >= 2")
        elif self.next_attempt is not None:
            raise ValueError("UNSAFE/UNKNOWN Skill recovery cannot carry next_attempt")


class SkillRecoveryReplayAuthority(Protocol):
    async def evaluate(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
        capability_id: str,
        capability_version: str,
    ) -> SkillRecoveryReplayDecision:
        """Reuse IU6 whole-Step replay safety and durable attempt sequencing."""


class SkillRecoveryEvidenceProvider(Protocol):
    async def build_request(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
        capability_id: str,
        capability_version: str,
    ) -> StepReplaySafetyRequest | None:
        """Reconstruct exact IU6 replay evidence from durable recovery facts."""


class IU6SkillRecoveryReplayAuthority(SkillRecoveryReplayAuthority):
    """Adapter that reuses IU6 replay-safety semantics and attempt authority."""

    def __init__(
        self,
        *,
        evidence_provider: SkillRecoveryEvidenceProvider,
        replay_safety_evaluator: StepReplaySafetyEvaluator,
        attempt_sequence: StepAttemptSequenceAuthority,
    ) -> None:
        self._evidence_provider = evidence_provider
        self._replay_safety_evaluator = replay_safety_evaluator
        self._attempt_sequence = attempt_sequence

    async def evaluate(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
        capability_id: str,
        capability_version: str,
    ) -> SkillRecoveryReplayDecision:
        try:
            request = await self._evidence_provider.build_request(
                execution_id=execution_id,
                step_execution_id=step_execution_id,
                capability_id=capability_id,
                capability_version=capability_version,
            )
        except Exception:  # noqa: BLE001
            return self._unknown("SKILL_RECOVERY_EVIDENCE_EXCEPTION")
        if not isinstance(request, StepReplaySafetyRequest):
            return self._unknown("SKILL_RECOVERY_EVIDENCE_MISSING")
        try:
            replay = await self._replay_safety_evaluator.evaluate(request)
        except Exception:  # noqa: BLE001
            return self._unknown("SKILL_RECOVERY_REPLAY_EVALUATION_EXCEPTION")
        if replay.status is ReplaySafetyStatus.UNSAFE:
            return SkillRecoveryReplayDecision(
                status=SkillRecoveryReplayStatus.UNSAFE,
                reason_codes=("SKILL_RECOVERY_REPLAY_UNSAFE", *replay.reason_codes),
            )
        if replay.status is not ReplaySafetyStatus.SAFE:
            return self._unknown(
                "SKILL_RECOVERY_REPLAY_UNKNOWN",
                *replay.reason_codes,
            )

        try:
            current = await self._attempt_sequence.current_attempt(step_execution_id)
        except Exception:  # noqa: BLE001
            return self._unknown("SKILL_RECOVERY_ATTEMPT_CURSOR_EXCEPTION")
        if current is None or current < 1:
            return self._unknown("SKILL_RECOVERY_ATTEMPT_CURSOR_UNKNOWN")
        try:
            claimed = await self._attempt_sequence.claim_next(
                step_execution_id=step_execution_id,
                expected_current_attempt=current,
            )
        except Exception:  # noqa: BLE001
            return self._unknown("SKILL_RECOVERY_ATTEMPT_CLAIM_EXCEPTION")
        if claimed.status is not StepAttemptSequenceStatus.CLAIMED:
            return self._unknown(
                "SKILL_RECOVERY_ATTEMPT_CLAIM_NOT_GRANTED",
                *claimed.reason_codes,
            )
        if claimed.next_attempt is None:
            return self._unknown("SKILL_RECOVERY_ATTEMPT_CLAIM_INVALID")
        return SkillRecoveryReplayDecision(
            status=SkillRecoveryReplayStatus.SAFE,
            reason_codes=("SKILL_RECOVERY_REPLAY_SAFE",),
            next_attempt=claimed.next_attempt,
        )

    @staticmethod
    def _unknown(*reasons: str) -> SkillRecoveryReplayDecision:
        normalized = tuple(item for item in reasons if item)
        return SkillRecoveryReplayDecision(
            status=SkillRecoveryReplayStatus.UNKNOWN,
            reason_codes=normalized or ("SKILL_RECOVERY_UNKNOWN",),
        )


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
    execution_id: str
    reason_codes: tuple[str, ...]
    active_step_id: str | None = None
    workflow_checkpoint: WorkflowRecoveryCheckpoint | None = None
    next_attempt: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, RecoveryDisposition):
            raise TypeError("disposition must be RecoveryDisposition")
        _require_non_blank(self.execution_id, "execution_id")
        if not self.reason_codes or any(not item.strip() for item in self.reason_codes):
            raise ValueError("reason_codes must contain non-blank values")
        if self.disposition is RecoveryDisposition.RESUME_WORKFLOW:
            if self.workflow_checkpoint is None or self.active_step_id is None:
                raise ValueError(
                    "RESUME_WORKFLOW requires active step and exact checkpoint"
                )
        elif self.workflow_checkpoint is not None:
            raise ValueError("only RESUME_WORKFLOW may carry workflow checkpoint")
        if self.disposition is RecoveryDisposition.RETRY_STEP:
            if self.next_attempt is None or self.next_attempt < 2:
                raise ValueError("RETRY_STEP requires next_attempt >= 2")
            if self.active_step_id is None:
                raise ValueError("RETRY_STEP requires active_step_id")
        elif self.next_attempt is not None:
            raise ValueError("only RETRY_STEP may carry next_attempt")


class RecoveryControlReader(Protocol):
    async def read_latched(self, execution_id: str) -> DurableControlReadDecision:
        """Read durable terminal control for recovery ordering."""


class RecoveryInFlightReader(Protocol):
    async def recover_active_as_orphaned(
        self,
        *,
        execution_id: str,
        recovered_at: datetime,
        required_claim: ExecutionRecoveryClaim,
    ) -> InFlightRecoveryTransitionDecision:
        """Fence crash-time ACTIVE evidence into ORPHANED_UNCONFIRMED."""

    async def load_inflight(
        self,
        *,
        execution_id: str,
        step_execution_id: str | None = None,
    ) -> tuple[DurableInFlightOperationObservation, ...]:
        """Load durable in-flight observations."""


class RecoveryBindingReader(Protocol):
    async def active_for_execution(
        self,
        execution_id: str,
    ) -> tuple[DurableOperationResourceBindingRecord, ...]:
        """Load active operation-resource bindings for one execution."""


class RecoveryCoordinator:
    """Order all durable recovery authorities before resume/retry/scheduler re-entry."""

    _TERMINAL_EXECUTION = frozenset(
        {"SUCCESS", "PARTIAL_SUCCESS", "FAILED", "CANCELLED", "TIMEOUT", "PREEMPTED"}
    )
    _TERMINAL_INFLIGHT = frozenset(
        {InFlightEvidenceState.COMPLETED, InFlightEvidenceState.CONFIRMED_STOPPED}
    )
    _STRONG_OPERATION_RECOVERY = frozenset(
        {
            OperationRecoveryStatus.COMPLETED_CONFIRMED,
            OperationRecoveryStatus.STOPPED_CONFIRMED,
            OperationRecoveryStatus.NOT_FOUND_WITH_PROOF,
        }
    )

    def __init__(
        self,
        *,
        claim_authority: RecoveryClaimAuthority,
        control_store: RecoveryControlReader,
        inflight_store: RecoveryInFlightReader,
        binding_store: RecoveryBindingReader,
        workflow_checkpoint_store: WorkflowRecoveryCheckpointStore,
        operation_probe: OperationRecoveryProbe | None = None,
        resource_recovery: ToolResourceRecoveryCoordinator | None = None,
        skill_replay_authority: SkillRecoveryReplayAuthority | None = None,
    ) -> None:
        self._claim_authority = claim_authority
        self._control_store = control_store
        self._inflight_store = inflight_store
        self._binding_store = binding_store
        self._workflow_checkpoint_store = workflow_checkpoint_store
        self._operation_probe = operation_probe
        self._resource_recovery = resource_recovery
        self._skill_replay_authority = skill_replay_authority

    async def decide(
        self,
        *,
        snapshot: ExecutionRecoverySnapshot,
        recovery_claim: ExecutionRecoveryClaim,
        recovered_at: datetime,
        resolved_active_step: ResolvedStepCapabilities | None = None,
    ) -> RecoveryDecision:
        _require_aware(recovered_at, "recovered_at")
        execution_id = snapshot.execution_id
        if recovery_claim.execution_id != execution_id:
            return self._unknown(execution_id, "RECOVERY_CLAIM_EXECUTION_MISMATCH")
        try:
            epoch = await self._claim_authority.validate_current(recovery_claim)
        except Exception:  # noqa: BLE001
            return self._unknown(execution_id, "RECOVERY_EPOCH_CHECK_EXCEPTION")
        if epoch.status is not RecoveryEpochValidationStatus.CURRENT:
            return self._unknown(
                execution_id,
                "RECOVERY_EPOCH_STALE"
                if epoch.status is RecoveryEpochValidationStatus.STALE
                else "RECOVERY_EPOCH_UNKNOWN",
            )

        if snapshot.execution_record.status in self._TERMINAL_EXECUTION:
            return RecoveryDecision(
                disposition=RecoveryDisposition.TERMINAL_NO_ACTION,
                execution_id=execution_id,
                reason_codes=("RECOVERY_EXECUTION_ALREADY_TERMINAL",),
            )

        try:
            control = await self._control_store.read_latched(execution_id)
        except Exception:  # noqa: BLE001
            return self._unknown(execution_id, "RECOVERY_CONTROL_READ_EXCEPTION")
        if control.status is DurableControlReadStatus.UNKNOWN:
            return self._unknown(execution_id, *control.reason_codes)
        if control.status is DurableControlReadStatus.LATCHED:
            if (
                control.latched_control is None
                or control.latched_control.signal.target_execution_id != execution_id
            ):
                return self._unknown(
                    execution_id,
                    "RECOVERY_CONTROL_LATCH_IDENTITY_INVALID",
                )
            return RecoveryDecision(
                disposition=RecoveryDisposition.APPLY_LATCHED_CONTROL,
                execution_id=execution_id,
                reason_codes=("RECOVERY_LATCHED_CONTROL_PRECEDES_RESUME",),
            )

        try:
            transitioned = await self._inflight_store.recover_active_as_orphaned(
                execution_id=execution_id,
                recovered_at=recovered_at,
                required_claim=recovery_claim,
            )
        except Exception:  # noqa: BLE001
            return self._unknown(execution_id, "RECOVERY_INFLIGHT_TRANSITION_EXCEPTION")
        if transitioned.status in {
            InFlightRecoveryTransitionStatus.CONFLICT,
            InFlightRecoveryTransitionStatus.UNKNOWN,
        }:
            return self._unknown(execution_id, *transitioned.reason_codes)

        try:
            observations = await self._inflight_store.load_inflight(
                execution_id=execution_id
            )
        except Exception:  # noqa: BLE001
            return self._unknown(execution_id, "RECOVERY_INFLIGHT_READ_EXCEPTION")

        for observation in observations:
            if observation.state in self._TERMINAL_INFLIGHT:
                continue
            reconciled = await self._reconcile_operation(
                observation.handle,
                recovery_claim=recovery_claim,
                recovered_at=recovered_at,
            )
            if reconciled is not None:
                return reconciled

        try:
            active_bindings = await self._binding_store.active_for_execution(execution_id)
        except Exception:  # noqa: BLE001
            return self._unknown(execution_id, "RECOVERY_RESOURCE_BINDING_READ_EXCEPTION")
        if active_bindings:
            return RecoveryDecision(
                disposition=RecoveryDisposition.WAIT_RECONCILIATION,
                execution_id=execution_id,
                reason_codes=("RECOVERY_ACTIVE_RESOURCE_BINDING_REMAINS",),
            )

        running = [
            item for item in snapshot.steps if item.status is StepExecutionStatus.RUNNING
        ]
        if len(running) > 1:
            return self._unknown(execution_id, "RECOVERY_MULTIPLE_RUNNING_STEPS")
        if not running:
            if any(
                item.status is StepExecutionStatus.PENDING for item in snapshot.steps
            ):
                return RecoveryDecision(
                    disposition=RecoveryDisposition.RESUME_SCHEDULING,
                    execution_id=execution_id,
                    reason_codes=("RECOVERY_SAFE_TO_REENTER_EXISTING_SCHEDULER",),
                )
            return self._unknown(
                execution_id,
                "RECOVERY_NO_PENDING_OR_RUNNING_STEP_AGGREGATION_DEFERRED",
            )

        step = running[0]
        if resolved_active_step is None or resolved_active_step.step_id != step.step_id:
            return self._unknown(
                execution_id,
                "RECOVERY_ACTIVE_STEP_CAPABILITY_BINDING_MISSING",
                active_step_id=step.step_id,
            )

        if resolved_active_step.execution_owner is CapabilityExecutionOwner.WORKFLOW:
            workflow = resolved_active_step.workflow
            if workflow is None:
                return self._unknown(
                    execution_id,
                    "RECOVERY_WORKFLOW_BINDING_MISSING",
                    active_step_id=step.step_id,
                )
            try:
                checkpoint_read = await self._workflow_checkpoint_store.read_latest(
                    execution_id=execution_id,
                    step_execution_id=step.step_execution_id,
                )
            except Exception:  # noqa: BLE001
                return self._unknown(
                    execution_id,
                    "RECOVERY_WORKFLOW_CHECKPOINT_READ_EXCEPTION",
                    active_step_id=step.step_id,
                )
            if checkpoint_read.status is WorkflowCheckpointReadStatus.UNKNOWN:
                return self._unknown(
                    execution_id,
                    *checkpoint_read.reason_codes,
                    active_step_id=step.step_id,
                )
            if checkpoint_read.status is WorkflowCheckpointReadStatus.NONE:
                return RecoveryDecision(
                    disposition=RecoveryDisposition.WAIT_RECONCILIATION,
                    execution_id=execution_id,
                    active_step_id=step.step_id,
                    reason_codes=(
                        "RECOVERY_WAITING_WORKFLOW_HAS_NO_DURABLE_CHECKPOINT",
                    ),
                )
            checkpoint = checkpoint_read.checkpoint
            if checkpoint is None:
                return self._unknown(
                    execution_id,
                    "RECOVERY_WORKFLOW_CHECKPOINT_READ_INVALID",
                    active_step_id=step.step_id,
                )
            if (
                checkpoint.step_id != step.step_id
                or checkpoint.step_execution_id != step.step_execution_id
                or checkpoint.workflow_id != workflow.capability_id
                or checkpoint.workflow_version != workflow.version
            ):
                return self._unknown(
                    execution_id,
                    "RECOVERY_WORKFLOW_CHECKPOINT_PROVENANCE_MISMATCH",
                    active_step_id=step.step_id,
                )
            return RecoveryDecision(
                disposition=RecoveryDisposition.RESUME_WORKFLOW,
                execution_id=execution_id,
                active_step_id=step.step_id,
                reason_codes=("RECOVERY_EXACT_WORKFLOW_CHECKPOINT_AUTHORIZED",),
                workflow_checkpoint=checkpoint,
            )

        if resolved_active_step.execution_owner is CapabilityExecutionOwner.SKILL:
            skill = resolved_active_step.skill
            if skill is None or self._skill_replay_authority is None:
                return self._unknown(
                    execution_id,
                    "RECOVERY_SKILL_REPLAY_AUTHORITY_MISSING",
                    active_step_id=step.step_id,
                )
            try:
                replay = await self._skill_replay_authority.evaluate(
                    execution_id=execution_id,
                    step_execution_id=step.step_execution_id,
                    capability_id=skill.capability_id,
                    capability_version=skill.version,
                )
            except Exception:  # noqa: BLE001
                return self._unknown(
                    execution_id,
                    "RECOVERY_SKILL_REPLAY_AUTHORITY_EXCEPTION",
                    active_step_id=step.step_id,
                )
            if replay.status is SkillRecoveryReplayStatus.SAFE:
                if replay.next_attempt is None:
                    return self._unknown(
                        execution_id,
                        "RECOVERY_SKILL_REPLAY_DECISION_INVALID",
                        active_step_id=step.step_id,
                    )
                return RecoveryDecision(
                    disposition=RecoveryDisposition.RETRY_STEP,
                    execution_id=execution_id,
                    active_step_id=step.step_id,
                    reason_codes=replay.reason_codes,
                    next_attempt=replay.next_attempt,
                )
            if replay.status is SkillRecoveryReplayStatus.UNSAFE:
                return RecoveryDecision(
                    disposition=RecoveryDisposition.WAIT_RECONCILIATION,
                    execution_id=execution_id,
                    active_step_id=step.step_id,
                    reason_codes=replay.reason_codes,
                )
            return self._unknown(
                execution_id,
                *replay.reason_codes,
                active_step_id=step.step_id,
            )

        return self._unknown(
            execution_id,
            "RECOVERY_RUNNING_STEP_HAS_NO_RESUMABLE_OWNER",
            active_step_id=step.step_id,
        )

    async def _reconcile_operation(
        self,
        handle: InFlightOperationHandle,
        *,
        recovery_claim: ExecutionRecoveryClaim,
        recovered_at: datetime,
    ) -> RecoveryDecision | None:
        operation_handle_id = getattr(handle, "operation_handle_id", None)
        execution_id = getattr(handle, "execution_id", recovery_claim.execution_id)
        if not isinstance(operation_handle_id, str) or not operation_handle_id.strip():
            return self._unknown(execution_id, "RECOVERY_OPERATION_HANDLE_INVALID")
        if self._operation_probe is None:
            return RecoveryDecision(
                disposition=RecoveryDisposition.WAIT_RECONCILIATION,
                execution_id=execution_id,
                reason_codes=("RECOVERY_OPERATION_PROBE_MISSING",),
            )
        try:
            probe = await self._operation_probe.probe(handle=handle)
        except Exception:  # noqa: BLE001
            return RecoveryDecision(
                disposition=RecoveryDisposition.WAIT_RECONCILIATION,
                execution_id=execution_id,
                reason_codes=("RECOVERY_OPERATION_PROBE_EXCEPTION",),
            )
        if not isinstance(probe, OperationRecoveryDecision):
            return self._unknown(execution_id, "RECOVERY_OPERATION_PROBE_INVALID_RESULT")
        started_at = getattr(handle, "started_at", None)
        if (
            probe.operation_handle_id != operation_handle_id
            or not isinstance(started_at, datetime)
            or probe.observed_at < started_at
            or probe.observed_at > recovered_at
        ):
            return self._unknown(execution_id, "RECOVERY_OPERATION_PROBE_PROVENANCE_INVALID")

        strong = probe.status in self._STRONG_OPERATION_RECOVERY
        if not strong:
            if self._resource_recovery is not None:
                resource = await self._resource_recovery.recover(
                    operation_handle_id=operation_handle_id,
                    recovery_claim=recovery_claim,
                    recovered_at=recovered_at,
                )
                if (
                    resource.status
                    in {
                        ResourceRecoveryStatus.RECLAIMED,
                        ResourceRecoveryStatus.ALREADY_RECLAIMED,
                    }
                    and resource.provider_fence is not None
                ):
                    return None
                if resource.status is ResourceRecoveryStatus.UNKNOWN:
                    return self._unknown(execution_id, *resource.reason_codes)
            return RecoveryDecision(
                disposition=RecoveryDisposition.WAIT_RECONCILIATION,
                execution_id=execution_id,
                reason_codes=probe.reason_codes,
            )

        if self._resource_recovery is not None:
            resource = await self._resource_recovery.recover(
                operation_handle_id=operation_handle_id,
                recovery_claim=recovery_claim,
                recovered_at=recovered_at,
            )
            if resource.status is ResourceRecoveryStatus.UNKNOWN:
                return self._unknown(execution_id, *resource.reason_codes)
            if resource.status is ResourceRecoveryStatus.RETAINED:
                return RecoveryDecision(
                    disposition=RecoveryDisposition.WAIT_RECONCILIATION,
                    execution_id=execution_id,
                    reason_codes=resource.reason_codes,
                )
        return None

    @staticmethod
    def _unknown(
        execution_id: str,
        *reasons: str,
        active_step_id: str | None = None,
    ) -> RecoveryDecision:
        normalized = tuple(item for item in reasons if item)
        return RecoveryDecision(
            disposition=RecoveryDisposition.UNKNOWN_BLOCKED,
            execution_id=execution_id,
            active_step_id=active_step_id,
            reason_codes=normalized or ("RECOVERY_UNKNOWN",),
        )
