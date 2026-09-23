"""CA-M5-IU9-06 owner-frame supersession and recovery-unblock tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from runtime.execution.control_application import (
    InFlightOperationHandle,
    InFlightOperationKind,
)
from runtime.execution.foundation import StepLifecycleSnapshot
from runtime.execution.models import StepExecutionStatus
from runtime.execution.recovery import (
    ExecutionRecoveryClaim,
    InMemoryRecoveryClaimAuthority,
    RecoveryClaimRequest,
    RecoveryClaimStatus,
)
from runtime.execution.recovery_evidence import (
    DurableControlReadDecision,
    DurableControlReadStatus,
    DurableInFlightOperationRegistry,
    InFlightEvidenceState,
    InFlightReconciliationBasis,
    InFlightRecoveryTransitionStatus,
    InFlightTerminalReconciliation,
    InMemoryDurableRecoveryEvidenceStore,
    OwnerFrameSupersessionBasis,
)
from runtime.execution.recovery_workflow import (
    RecoveryCoordinator,
    RecoveryDisposition,
    StepRecoveryReplayDecision,
    StepRecoveryReplayStatus,
    WorkflowRecoveryCheckpoint,
    WorkflowRecoveryCheckpointStatus,
)

NOW = datetime(2026, 9, 23, 8, 0, tzinfo=UTC)


async def _claim(
    authority: InMemoryRecoveryClaimAuthority,
    *,
    claim_id: str,
    owner: str,
    expected_epoch: int,
    source_generation: int,
    at: datetime,
) -> ExecutionRecoveryClaim:
    decision = await authority.claim(
        RecoveryClaimRequest(
            claim_id=claim_id,
            execution_id="exec-1",
            recovery_owner_id=owner,
            expected_current_epoch=expected_epoch,
            source_snapshot_generation=source_generation,
            requested_at=at,
        )
    )
    assert decision.status is RecoveryClaimStatus.CLAIMED
    assert decision.claim is not None
    return decision.claim


def _owner_handle(kind: InFlightOperationKind) -> InFlightOperationHandle:
    return InFlightOperationHandle(
        operation_handle_id=f"owner:{kind.value.lower()}",
        execution_id="exec-1",
        step_execution_id="step-exec-1",
        kind=kind,
        capability_id="skill-1" if kind is InFlightOperationKind.SKILL else "wf-1",
        capability_version="v7",
        started_at=NOW + timedelta(seconds=1),
    )


def _tool_handle(parent: InFlightOperationHandle) -> InFlightOperationHandle:
    return InFlightOperationHandle(
        operation_handle_id="tool:1",
        execution_id=parent.execution_id,
        step_execution_id=parent.step_execution_id,
        kind=InFlightOperationKind.TOOL,
        capability_id="tool-1",
        capability_version="v1",
        started_at=NOW + timedelta(seconds=2),
        parent_handle_id=parent.operation_handle_id,
        tool_call_id="tool-call-1",
    )


async def _register(
    *,
    store: InMemoryDurableRecoveryEvidenceStore,
    claim: ExecutionRecoveryClaim,
    handle: InFlightOperationHandle,
) -> None:
    registry = DurableInFlightOperationRegistry(
        store=store,
        recovery_claim=claim,
        clock=lambda: NOW + timedelta(seconds=3),
    )
    assert await registry.register(handle)


class SnapshotStore:
    def __init__(self, snapshot) -> None:
        self.snapshot = snapshot

    async def load(self, execution_id: str):
        assert execution_id == "exec-1"
        return self.snapshot


class ControlStore:
    async def read_latched(self, execution_id: str):
        assert execution_id == "exec-1"
        return DurableControlReadDecision(
            status=DurableControlReadStatus.NONE,
            reason_codes=("NO_CONTROL",),
        )


class ResourceStore:
    async def active_for_execution(self, execution_id: str):
        assert execution_id == "exec-1"
        return ()


class CheckpointStore:
    def __init__(self, value) -> None:
        self.value = value

    async def load(self, **kwargs):
        return self.value


class VersionAuthority:
    async def expected_version(self, **kwargs):
        return "v7"


class SafeReplay:
    async def evaluate(self, **kwargs):
        return StepRecoveryReplayDecision(
            status=StepRecoveryReplayStatus.SAFE,
            reason_codes=("IU6_SAFE",),
        )


def _snapshot(step: StepLifecycleSnapshot):
    return SimpleNamespace(
        execution_id="exec-1",
        generation=3,
        execution_record=SimpleNamespace(status="RUNNING"),
        steps=(step,),
    )


def _checkpoint() -> WorkflowRecoveryCheckpoint:
    return WorkflowRecoveryCheckpoint(
        checkpoint_id="cp-wf-1",
        generation=1,
        execution_id="exec-1",
        step_execution_id="step-exec-1",
        workflow_instance_id="wf-instance-1",
        workflow_id="wf-1",
        workflow_version="v7",
        state_reference="state://wf/1",
        resume_token="resume-1",
        status=WorkflowRecoveryCheckpointStatus.WAITING_COMMITTED,
        committed_at=NOW + timedelta(seconds=4),
        writer_recovery_epoch=2,
    )


def test_owner_supersession_only_transitions_skill_and_workflow_not_tool() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        first = await _claim(
            claims,
            claim_id="claim-1",
            owner="worker-old",
            expected_epoch=0,
            source_generation=0,
            at=NOW,
        )
        owner = _owner_handle(InFlightOperationKind.SKILL)
        tool = _tool_handle(owner)
        await _register(store=store, claim=first, handle=owner)
        await _register(store=store, claim=first, handle=tool)

        recovery = await _claim(
            claims,
            claim_id="claim-2",
            owner="worker-new",
            expected_epoch=1,
            source_generation=3,
            at=NOW + timedelta(seconds=4),
        )
        orphaned = await store.recover_active_as_orphaned(
            execution_id="exec-1",
            recovered_at=NOW + timedelta(seconds=5),
            required_claim=recovery,
        )
        assert orphaned.status is InFlightRecoveryTransitionStatus.TRANSITIONED

        superseded = await store.supersede_orphaned_owner_frame(
            execution_id="exec-1",
            step_execution_id="step-exec-1",
            owner_kind=owner.kind,
            capability_id=owner.capability_id,
            recovered_at=NOW + timedelta(seconds=6),
            required_claim=recovery,
        )
        assert superseded.status is InFlightRecoveryTransitionStatus.TRANSITIONED
        observations = await store.load_inflight(execution_id="exec-1")
        by_kind = {item.handle.kind: item for item in observations}

        assert (
            by_kind[InFlightOperationKind.SKILL].state
            is InFlightEvidenceState.OWNER_FRAME_SUPERSEDED
        )
        assert (
            by_kind[InFlightOperationKind.SKILL].owner_supersession_basis
            is OwnerFrameSupersessionBasis.RECOVERY_EPOCH_TAKEOVER
        )
        assert by_kind[InFlightOperationKind.SKILL].reconciliation_basis is None
        assert (
            by_kind[InFlightOperationKind.TOOL].state
            is InFlightEvidenceState.ORPHANED_UNCONFIRMED
        )
        assert by_kind[InFlightOperationKind.TOOL].owner_supersession_basis is None

    asyncio.run(scenario())


def test_owner_supersession_exact_replay_is_idempotent() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        first = await _claim(
            claims,
            claim_id="claim-1",
            owner="worker-old",
            expected_epoch=0,
            source_generation=0,
            at=NOW,
        )
        owner = _owner_handle(InFlightOperationKind.WORKFLOW)
        await _register(store=store, claim=first, handle=owner)
        recovery = await _claim(
            claims,
            claim_id="claim-2",
            owner="worker-new",
            expected_epoch=1,
            source_generation=3,
            at=NOW + timedelta(seconds=4),
        )
        await store.recover_active_as_orphaned(
            execution_id="exec-1",
            recovered_at=NOW + timedelta(seconds=5),
            required_claim=recovery,
        )
        first_decision = await store.supersede_orphaned_owner_frame(
            execution_id="exec-1",
            step_execution_id="step-exec-1",
            owner_kind=owner.kind,
            capability_id=owner.capability_id,
            recovered_at=NOW + timedelta(seconds=6),
            required_claim=recovery,
        )
        before = (await store.load_inflight(execution_id="exec-1"))[0]
        replay = await store.supersede_orphaned_owner_frame(
            execution_id="exec-1",
            step_execution_id="step-exec-1",
            owner_kind=owner.kind,
            capability_id=owner.capability_id,
            recovered_at=NOW + timedelta(seconds=7),
            required_claim=recovery,
        )
        after = (await store.load_inflight(execution_id="exec-1"))[0]

        assert first_decision.status is InFlightRecoveryTransitionStatus.TRANSITIONED
        assert replay.status is InFlightRecoveryTransitionStatus.NO_ACTIVE
        assert after == before

    asyncio.run(scenario())


def test_stale_recovery_epoch_cannot_supersede_owner_frame() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        first = await _claim(
            claims,
            claim_id="claim-1",
            owner="worker-old",
            expected_epoch=0,
            source_generation=0,
            at=NOW,
        )
        owner = _owner_handle(InFlightOperationKind.SKILL)
        await _register(store=store, claim=first, handle=owner)
        recovery = await _claim(
            claims,
            claim_id="claim-2",
            owner="worker-new",
            expected_epoch=1,
            source_generation=3,
            at=NOW + timedelta(seconds=4),
        )
        await store.recover_active_as_orphaned(
            execution_id="exec-1",
            recovered_at=NOW + timedelta(seconds=5),
            required_claim=recovery,
        )
        newer = await _claim(
            claims,
            claim_id="claim-3",
            owner="worker-newer",
            expected_epoch=2,
            source_generation=3,
            at=NOW + timedelta(seconds=6),
        )
        assert newer.recovery_epoch == 3

        decision = await store.supersede_orphaned_owner_frame(
            execution_id="exec-1",
            step_execution_id="step-exec-1",
            owner_kind=owner.kind,
            capability_id=owner.capability_id,
            recovered_at=NOW + timedelta(seconds=7),
            required_claim=recovery,
        )
        assert decision.status is InFlightRecoveryTransitionStatus.CONFLICT
        observation = (await store.load_inflight(execution_id="exec-1"))[0]
        assert observation.state is InFlightEvidenceState.ORPHANED_UNCONFIRMED

    asyncio.run(scenario())


def test_workflow_owner_supersession_unblocks_exact_checkpoint_resume() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        first = await _claim(
            claims,
            claim_id="claim-1",
            owner="worker-old",
            expected_epoch=0,
            source_generation=0,
            at=NOW,
        )
        owner = _owner_handle(InFlightOperationKind.WORKFLOW)
        await _register(store=store, claim=first, handle=owner)
        recovery = await _claim(
            claims,
            claim_id="claim-2",
            owner="worker-new",
            expected_epoch=1,
            source_generation=3,
            at=NOW + timedelta(seconds=4),
        )
        step = StepLifecycleSnapshot(
            step_execution_id="step-exec-1",
            step_id="step-1",
            action="act",
            status=StepExecutionStatus.RUNNING,
            workflow_id="wf-1",
            started_at=NOW + timedelta(seconds=1),
        )
        coordinator = RecoveryCoordinator(
            claim_authority=claims,
            snapshot_store=SnapshotStore(_snapshot(step)),
            control_store=ControlStore(),
            inflight_store=store,
            resource_binding_store=ResourceStore(),
            workflow_checkpoint_store=CheckpointStore(_checkpoint()),
            workflow_version_authority=VersionAuthority(),
            step_replay_evaluator=SafeReplay(),
        )
        decision = await coordinator.decide(
            recovery_claim=recovery,
            recovered_at=NOW + timedelta(seconds=6),
        )

        assert decision.disposition is RecoveryDisposition.RESUME_WORKFLOW
        assert decision.workflow_resume_request is not None
        observations = await store.load_inflight(execution_id="exec-1")
        assert observations[0].state is InFlightEvidenceState.OWNER_FRAME_SUPERSEDED

    asyncio.run(scenario())


def test_skill_owner_supersession_unblocks_iu6_whole_step_replay() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        first = await _claim(
            claims,
            claim_id="claim-1",
            owner="worker-old",
            expected_epoch=0,
            source_generation=0,
            at=NOW,
        )
        owner = _owner_handle(InFlightOperationKind.SKILL)
        await _register(store=store, claim=first, handle=owner)
        recovery = await _claim(
            claims,
            claim_id="claim-2",
            owner="worker-new",
            expected_epoch=1,
            source_generation=3,
            at=NOW + timedelta(seconds=4),
        )
        step = StepLifecycleSnapshot(
            step_execution_id="step-exec-1",
            step_id="step-1",
            action="act",
            status=StepExecutionStatus.RUNNING,
            skill_id="skill-1",
            started_at=NOW + timedelta(seconds=1),
        )
        coordinator = RecoveryCoordinator(
            claim_authority=claims,
            snapshot_store=SnapshotStore(_snapshot(step)),
            control_store=ControlStore(),
            inflight_store=store,
            resource_binding_store=ResourceStore(),
            workflow_checkpoint_store=CheckpointStore(None),
            workflow_version_authority=VersionAuthority(),
            step_replay_evaluator=SafeReplay(),
        )
        decision = await coordinator.decide(
            recovery_claim=recovery,
            recovered_at=NOW + timedelta(seconds=6),
        )

        assert decision.disposition is RecoveryDisposition.RETRY_STEP
        assert decision.retry_step_execution_id == "step-exec-1"
        observations = await store.load_inflight(execution_id="exec-1")
        assert observations[0].state is InFlightEvidenceState.OWNER_FRAME_SUPERSEDED

    asyncio.run(scenario())


def test_nested_tool_orphan_still_blocks_after_owner_frame_supersession() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        first = await _claim(
            claims,
            claim_id="claim-1",
            owner="worker-old",
            expected_epoch=0,
            source_generation=0,
            at=NOW,
        )
        owner = _owner_handle(InFlightOperationKind.WORKFLOW)
        tool = _tool_handle(owner)
        await _register(store=store, claim=first, handle=owner)
        await _register(store=store, claim=first, handle=tool)
        recovery = await _claim(
            claims,
            claim_id="claim-2",
            owner="worker-new",
            expected_epoch=1,
            source_generation=3,
            at=NOW + timedelta(seconds=4),
        )
        step = StepLifecycleSnapshot(
            step_execution_id="step-exec-1",
            step_id="step-1",
            action="act",
            status=StepExecutionStatus.RUNNING,
            workflow_id="wf-1",
            started_at=NOW + timedelta(seconds=1),
        )
        coordinator = RecoveryCoordinator(
            claim_authority=claims,
            snapshot_store=SnapshotStore(_snapshot(step)),
            control_store=ControlStore(),
            inflight_store=store,
            resource_binding_store=ResourceStore(),
            workflow_checkpoint_store=CheckpointStore(_checkpoint()),
            workflow_version_authority=VersionAuthority(),
            step_replay_evaluator=SafeReplay(),
        )
        decision = await coordinator.decide(
            recovery_claim=recovery,
            recovered_at=NOW + timedelta(seconds=6),
        )

        assert decision.disposition is RecoveryDisposition.WAIT_RECONCILIATION
        observations = await store.load_inflight(execution_id="exec-1")
        by_kind = {item.handle.kind: item for item in observations}
        assert (
            by_kind[InFlightOperationKind.WORKFLOW].state
            is InFlightEvidenceState.OWNER_FRAME_SUPERSEDED
        )
        assert (
            by_kind[InFlightOperationKind.TOOL].state
            is InFlightEvidenceState.ORPHANED_UNCONFIRMED
        )

    asyncio.run(scenario())



def test_external_terminal_reconciliation_rejects_skill_owner_handle() -> None:
    owner = _owner_handle(InFlightOperationKind.SKILL)

    try:
        InFlightTerminalReconciliation(
            handle=owner,
            state=InFlightEvidenceState.CONFIRMED_STOPPED,
            basis=InFlightReconciliationBasis.OPERATION_STOPPED_CONFIRMED,
            observed_at=NOW + timedelta(seconds=8),
        )
    except ValueError as exc:
        assert "only valid for Tool operations" in str(exc)
    else:
        raise AssertionError("Skill owner must not accept external reconciliation truth")


def test_non_running_orphan_owner_is_not_silently_superseded() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        first = await _claim(
            claims,
            claim_id="claim-1",
            owner="worker-old",
            expected_epoch=0,
            source_generation=0,
            at=NOW,
        )
        stale_owner = InFlightOperationHandle(
            operation_handle_id="owner:stale-skill",
            execution_id="exec-1",
            step_execution_id="step-exec-old",
            kind=InFlightOperationKind.SKILL,
            capability_id="skill-old",
            capability_version="v1",
            started_at=NOW + timedelta(seconds=1),
        )
        await _register(store=store, claim=first, handle=stale_owner)
        recovery = await _claim(
            claims,
            claim_id="claim-2",
            owner="worker-new",
            expected_epoch=1,
            source_generation=3,
            at=NOW + timedelta(seconds=4),
        )
        step = StepLifecycleSnapshot(
            step_execution_id="step-exec-1",
            step_id="step-1",
            action="act",
            status=StepExecutionStatus.RUNNING,
            skill_id="skill-1",
            started_at=NOW + timedelta(seconds=1),
        )
        coordinator = RecoveryCoordinator(
            claim_authority=claims,
            snapshot_store=SnapshotStore(_snapshot(step)),
            control_store=ControlStore(),
            inflight_store=store,
            resource_binding_store=ResourceStore(),
            workflow_checkpoint_store=CheckpointStore(None),
            workflow_version_authority=VersionAuthority(),
            step_replay_evaluator=SafeReplay(),
        )
        decision = await coordinator.decide(
            recovery_claim=recovery,
            recovered_at=NOW + timedelta(seconds=6),
        )

        assert decision.disposition is RecoveryDisposition.WAIT_RECONCILIATION
        observation = (await store.load_inflight(execution_id="exec-1"))[0]
        assert observation.state is InFlightEvidenceState.ORPHANED_UNCONFIRMED

    asyncio.run(scenario())
