from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from runtime.execution.foundation import StepLifecycleSnapshot
from runtime.execution.models import (
    M5WorkflowResult,
    StepExecutionStatus,
    WorkflowExecutionStatus,
)
from runtime.execution.recovery import (
    ExecutionRecoveryClaim,
    RecoveryEpochValidationDecision,
    RecoveryEpochValidationStatus,
)
from runtime.execution.recovery_evidence import (
    DurableControlReadDecision,
    DurableControlReadStatus,
    InFlightRecoveryTransitionDecision,
    InFlightRecoveryTransitionStatus,
)
from runtime.execution.recovery_workflow import (
    InMemoryWorkflowRecoveryCheckpointStore,
    RecoveryCoordinator,
    RecoveryDisposition,
    StepRecoveryReplayDecision,
    StepRecoveryReplayStatus,
    WorkflowCheckpointCoordinator,
    WorkflowCheckpointWriteStatus,
    WorkflowRecoveryCheckpoint,
    WorkflowRecoveryCheckpointStatus,
    WorkflowResumeRequest,
)

NOW = datetime(2026, 9, 23, 6, 0, tzinfo=UTC)


class ClaimAuthority:
    async def validate_current(self, claim: ExecutionRecoveryClaim):
        return RecoveryEpochValidationDecision(
            status=RecoveryEpochValidationStatus.CURRENT,
            reason_codes=("CURRENT",),
            current_claim=claim,
        )

    async def claim(self, request):
        raise AssertionError("not used")

    async def current(self, execution_id):
        return None


def claim() -> ExecutionRecoveryClaim:
    return ExecutionRecoveryClaim(
        claim_id="claim-1",
        execution_id="exec-1",
        recovery_owner_id="worker-new",
        recovery_epoch=2,
        source_snapshot_generation=3,
        claimed_at=NOW,
    )


def checkpoint() -> WorkflowRecoveryCheckpoint:
    return WorkflowRecoveryCheckpoint(
        checkpoint_id="cp-wf-1",
        generation=1,
        execution_id="exec-1",
        step_execution_id="step-exec-1",
        workflow_instance_id="wf-instance-1",
        workflow_id="wf-1",
        workflow_version="v7",
        state_reference="state://wf/1",
        resume_token="resume-opaque-1",
        status=WorkflowRecoveryCheckpointStatus.WAITING_COMMITTED,
        committed_at=NOW,
        writer_recovery_epoch=2,
    )


def test_workflow_checkpoint_commit_is_fenced_and_exact_replay_idempotent() -> None:
    async def scenario() -> None:
        store = InMemoryWorkflowRecoveryCheckpointStore(
            claim_authority=ClaimAuthority(),
        )
        first = await store.commit(
            checkpoint(),
            expected_generation=0,
            required_claim=claim(),
        )
        second = await store.commit(
            checkpoint(),
            expected_generation=0,
            required_claim=claim(),
        )
        assert first.status is WorkflowCheckpointWriteStatus.COMMITTED
        assert second.status is WorkflowCheckpointWriteStatus.ALREADY_CURRENT

    asyncio.run(scenario())


def test_waiting_result_becomes_resumable_only_after_checkpoint_coordinator_commit() -> (
    None
):
    async def scenario() -> None:
        store = InMemoryWorkflowRecoveryCheckpointStore(
            claim_authority=ClaimAuthority(),
        )
        coordinator = WorkflowCheckpointCoordinator(
            store=store,
            claim_authority=ClaimAuthority(),
        )
        result = M5WorkflowResult(
            workflow_instance_id="wf-instance-1",
            workflow_id="wf-1",
            status=WorkflowExecutionStatus.WAITING,
            current_step="wait",
            pending_step="continue",
        )
        decision = await coordinator.commit_waiting(
            result=result,
            execution_id="exec-1",
            step_execution_id="step-exec-1",
            workflow_version="v7",
            checkpoint_id="cp-wf-1",
            generation=1,
            expected_generation=0,
            state_reference="state://wf/1",
            resume_token="resume-opaque-1",
            committed_at=NOW,
            recovery_claim=claim(),
        )
        assert decision.status is WorkflowCheckpointWriteStatus.COMMITTED
        stored = await store.load(
            execution_id="exec-1",
            step_execution_id="step-exec-1",
        )
        assert stored is not None
        assert stored.status is WorkflowRecoveryCheckpointStatus.WAITING_COMMITTED

    asyncio.run(scenario())


def test_non_waiting_workflow_result_cannot_create_resumable_checkpoint() -> None:
    async def scenario() -> None:
        store = InMemoryWorkflowRecoveryCheckpointStore(
            claim_authority=ClaimAuthority(),
        )
        coordinator = WorkflowCheckpointCoordinator(
            store=store,
            claim_authority=ClaimAuthority(),
        )
        result = M5WorkflowResult(
            workflow_instance_id="wf-instance-1",
            workflow_id="wf-1",
            status=WorkflowExecutionStatus.COMPLETED,
        )
        decision = await coordinator.commit_waiting(
            result=result,
            execution_id="exec-1",
            step_execution_id="step-exec-1",
            workflow_version="v7",
            checkpoint_id="cp-wf-1",
            generation=1,
            expected_generation=0,
            state_reference="state://wf/1",
            resume_token="resume-opaque-1",
            committed_at=NOW,
            recovery_claim=claim(),
        )
        assert decision.status is WorkflowCheckpointWriteStatus.CONFLICT

    asyncio.run(scenario())


def test_resume_request_preserves_exact_checkpoint_identity_and_version() -> None:
    request = WorkflowResumeRequest.from_checkpoint(checkpoint())
    assert request.workflow_instance_id == "wf-instance-1"
    assert request.workflow_id == "wf-1"
    assert request.workflow_version == "v7"
    assert request.checkpoint_id == "cp-wf-1"
    assert request.checkpoint_generation == 1
    assert request.resume_token == "resume-opaque-1"


class SnapshotStore:
    def __init__(self, snapshot) -> None:
        self.snapshot = snapshot

    async def load(self, execution_id: str):
        return self.snapshot


class ControlStore:
    def __init__(self, status: DurableControlReadStatus) -> None:
        self.status = status

    async def read_latched(self, execution_id: str):
        if self.status is DurableControlReadStatus.LATCHED:
            # Coordinator only inspects status before returning the control barrier.
            return SimpleNamespace(status=self.status)
        return DurableControlReadDecision(
            status=self.status,
            reason_codes=("CONTROL",),
        )


class InflightStore:
    async def recover_active_as_orphaned(self, **kwargs):
        return InFlightRecoveryTransitionDecision(
            status=InFlightRecoveryTransitionStatus.NO_ACTIVE,
            reason_codes=("NO_ACTIVE",),
        )

    async def supersede_orphaned_owner_frames(self, **kwargs):
        return InFlightRecoveryTransitionDecision(
            status=InFlightRecoveryTransitionStatus.NO_ACTIVE,
            reason_codes=("NO_ORPHANED_OWNER_FRAME",),
        )

    async def load_inflight(self, **kwargs):
        return ()


class ResourceStore:
    async def active_for_execution(self, execution_id: str):
        return ()


class CheckpointStore:
    def __init__(self, value) -> None:
        self.value = value

    async def load(self, **kwargs):
        return self.value


class VersionAuthority:
    def __init__(self, version: str | None) -> None:
        self.version = version

    async def expected_version(self, **kwargs):
        return self.version


class ReplayEvaluator:
    async def evaluate(self, **kwargs):
        return StepRecoveryReplayDecision(
            status=StepRecoveryReplayStatus.SAFE,
            reason_codes=("IU6_SAFE",),
        )


def make_snapshot(*, steps=(), status="RUNNING"):
    return SimpleNamespace(
        execution_id="exec-1",
        generation=3,
        execution_record=SimpleNamespace(status=status),
        steps=steps,
    )


def coordinator(
    snapshot, *, control=DurableControlReadStatus.NONE, cp=None, version="v7"
):
    return RecoveryCoordinator(
        claim_authority=ClaimAuthority(),
        snapshot_store=SnapshotStore(snapshot),
        control_store=ControlStore(control),
        inflight_store=InflightStore(),
        resource_binding_store=ResourceStore(),
        workflow_checkpoint_store=CheckpointStore(cp),
        workflow_version_authority=VersionAuthority(version),
        step_replay_evaluator=ReplayEvaluator(),
    )


def test_terminal_lifecycle_wins_before_resume() -> None:
    async def scenario() -> None:
        decision = await coordinator(
            make_snapshot(status="SUCCESS"),
            cp=checkpoint(),
        ).decide(recovery_claim=claim(), recovered_at=NOW)
        assert decision.disposition is RecoveryDisposition.TERMINAL_NO_ACTION

    asyncio.run(scenario())


def test_durable_control_barrier_wins_before_workflow_resume() -> None:
    async def scenario() -> None:
        step = StepLifecycleSnapshot(
            step_execution_id="step-exec-1",
            step_id="step-1",
            action="act",
            status=StepExecutionStatus.RUNNING,
            workflow_id="wf-1",
            started_at=NOW,
        )
        decision = await coordinator(
            make_snapshot(steps=(step,)),
            control=DurableControlReadStatus.LATCHED,
            cp=checkpoint(),
        ).decide(recovery_claim=claim(), recovered_at=NOW)
        assert decision.disposition is RecoveryDisposition.APPLY_LATCHED_CONTROL

    asyncio.run(scenario())


def test_waiting_workflow_without_durable_checkpoint_never_resumes() -> None:
    async def scenario() -> None:
        step = StepLifecycleSnapshot(
            step_execution_id="step-exec-1",
            step_id="step-1",
            action="act",
            status=StepExecutionStatus.RUNNING,
            workflow_id="wf-1",
            started_at=NOW,
        )
        decision = await coordinator(
            make_snapshot(steps=(step,)),
            cp=None,
        ).decide(recovery_claim=claim(), recovered_at=NOW)
        assert decision.disposition is RecoveryDisposition.WAIT_RECONCILIATION

    asyncio.run(scenario())


def test_exact_checkpoint_and_approved_version_authorize_same_instance_resume() -> None:
    async def scenario() -> None:
        step = StepLifecycleSnapshot(
            step_execution_id="step-exec-1",
            step_id="step-1",
            action="act",
            status=StepExecutionStatus.RUNNING,
            workflow_id="wf-1",
            started_at=NOW,
        )
        decision = await coordinator(
            make_snapshot(steps=(step,)),
            cp=checkpoint(),
            version="v7",
        ).decide(recovery_claim=claim(), recovered_at=NOW)
        assert decision.disposition is RecoveryDisposition.RESUME_WORKFLOW
        assert decision.workflow_resume_request is not None
        assert decision.workflow_resume_request.workflow_instance_id == "wf-instance-1"
        assert decision.workflow_resume_request.workflow_version == "v7"

    asyncio.run(scenario())


def test_checkpoint_version_mismatch_fails_closed() -> None:
    async def scenario() -> None:
        step = StepLifecycleSnapshot(
            step_execution_id="step-exec-1",
            step_id="step-1",
            action="act",
            status=StepExecutionStatus.RUNNING,
            workflow_id="wf-1",
            started_at=NOW,
        )
        decision = await coordinator(
            make_snapshot(steps=(step,)),
            cp=checkpoint(),
            version="v8",
        ).decide(recovery_claim=claim(), recovered_at=NOW)
        assert decision.disposition is RecoveryDisposition.UNKNOWN_BLOCKED

    asyncio.run(scenario())


def test_running_skill_uses_injected_iu6_replay_safety_projection() -> None:
    async def scenario() -> None:
        step = StepLifecycleSnapshot(
            step_execution_id="step-exec-1",
            step_id="step-1",
            action="act",
            status=StepExecutionStatus.RUNNING,
            skill_id="skill-1",
            started_at=NOW,
        )
        decision = await coordinator(
            make_snapshot(steps=(step,)),
        ).decide(recovery_claim=claim(), recovered_at=NOW)
        assert decision.disposition is RecoveryDisposition.RETRY_STEP
        assert decision.retry_step_execution_id == "step-exec-1"

    asyncio.run(scenario())


def test_no_running_step_reenters_existing_scheduler_only() -> None:
    async def scenario() -> None:
        decision = await coordinator(
            make_snapshot(steps=()),
        ).decide(recovery_claim=claim(), recovered_at=NOW)
        assert decision.disposition is RecoveryDisposition.RESUME_SCHEDULING

    asyncio.run(scenario())
