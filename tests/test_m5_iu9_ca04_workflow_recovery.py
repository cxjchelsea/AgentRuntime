from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from runtime.execution import (
    CapabilityExecutionOwner,
    CapabilityKind,
    DurableControlReadDecision,
    DurableControlReadStatus,
    ExecutionRecord,
    ExecutionRecoveryClaim,
    ExecutionRecoverySnapshot,
    InMemoryRecoveryClaimAuthority,
    InMemoryWorkflowRecoveryCheckpointStore,
    RecoveryClaimRequest,
    RecoveryClaimStatus,
    RecoveryCoordinator,
    RecoveryDisposition,
    RecoverySafeExecutionContext,
    ResolvedCapability,
    ResolvedStepCapabilities,
    StepExecutionStatus,
    StepLifecycleSnapshot,
    WorkflowCheckpointCommitStatus,
    WorkflowCheckpointMaterial,
    WorkflowCheckpointReadStatus,
    WorkflowExecutionStatus,
    WorkflowRecoveryCheckpoint,
    WorkflowResumeCoordinator,
    WorkflowResumeRequest,
    WorkflowResumeStatus,
    WorkflowWaitingCheckpointCoordinator,
)
from runtime.execution.capability_resolution import CapabilityReferenceSource
from runtime.execution.control import (
    ExecutionControlSignal,
    ExecutionControlSignalType,
    LatchedExecutionControl,
)
from runtime.execution.models import M5WorkflowResult
from runtime.registries.definitions import WorkflowDefinition


NOW = datetime(2026, 9, 23, 6, 0, tzinfo=UTC)


async def _claim(
    authority: InMemoryRecoveryClaimAuthority,
    *,
    owner: str = "worker-a",
    expected_epoch: int = 0,
) -> ExecutionRecoveryClaim:
    decision = await authority.claim(
        RecoveryClaimRequest(
            claim_id=f"claim-{owner}-{expected_epoch + 1}",
            execution_id="exec-1",
            recovery_owner_id=owner,
            expected_current_epoch=expected_epoch,
            source_snapshot_generation=1,
            requested_at=NOW,
        )
    )
    assert decision.status is RecoveryClaimStatus.CLAIMED
    assert decision.claim is not None
    return decision.claim


def _snapshot(
    *, status: StepExecutionStatus = StepExecutionStatus.RUNNING
) -> ExecutionRecoverySnapshot:
    context = RecoverySafeExecutionContext(
        execution_id="exec-1",
        plan_id="plan-1",
        request_id="req-1",
        session_id="session-1",
        identity_scope="user-1",
        policy_snapshot={"policy": "frozen"},
    )
    step = StepLifecycleSnapshot(
        step_execution_id="step-exec-1",
        step_id="step-1",
        action="do_work",
        status=status,
        workflow_id="wf-1" if status is StepExecutionStatus.RUNNING else None,
        started_at=NOW - timedelta(seconds=10)
        if status is StepExecutionStatus.RUNNING
        else None,
    )
    record = ExecutionRecord(
        execution_id="exec-1",
        plan_id="plan-1",
        request_id="req-1",
        identity_scope="user-1",
        status="RUNNING",
        current_step="step-1" if status is StepExecutionStatus.RUNNING else None,
        step_results=(
            {
                "step_execution_id": step.step_execution_id,
                "step_id": step.step_id,
                "action": step.action,
                "status": step.status.value,
                "skill_id": step.skill_id,
                "workflow_id": step.workflow_id,
                "tool_call_ids": list(step.tool_call_ids),
                "output": step.output,
                "error": step.error,
                "retry_count": step.retry_count,
                "started_at": step.started_at,
                "finished_at": step.finished_at,
            },
        ),
        created_at=NOW - timedelta(seconds=20),
        updated_at=NOW - timedelta(seconds=5),
    )
    return ExecutionRecoverySnapshot(
        checkpoint_id="execution-checkpoint-1",
        generation=1,
        execution_id="exec-1",
        captured_at=NOW,
        execution_context=context,
        execution_record=record,
        steps=(step,),
        execution_started_at=NOW - timedelta(seconds=15),
        execution_finished_at=None,
        writer_recovery_epoch=1,
        writer_recovery_owner_id="prior-worker",
    )


class StaticCheckpointAdapter:
    def __init__(self) -> None:
        self.calls = 0

    async def persist_waiting_state(
        self, **kwargs: object
    ) -> WorkflowCheckpointMaterial:
        self.calls += 1
        return WorkflowCheckpointMaterial(
            state_reference="state://wf-1/g1",
            resume_token="resume-token-1",
            state_schema_version="domain-state-v3",
        )


class NoControlStore:
    async def read_latched(self, execution_id: str) -> DurableControlReadDecision:
        return DurableControlReadDecision(
            status=DurableControlReadStatus.NONE,
            reason_codes=("NO_CONTROL",),
        )


class LatchedControlStore:
    async def read_latched(self, execution_id: str) -> DurableControlReadDecision:
        signal = ExecutionControlSignal(
            signal_type=ExecutionControlSignalType.CANCEL,
            reason_code="user_cancel",
            source="runtime",
            signal_id="signal-1",
            target_execution_id=execution_id,
            issued_at=NOW - timedelta(seconds=4),
        )
        return DurableControlReadDecision(
            status=DurableControlReadStatus.LATCHED,
            reason_codes=("CONTROL_FOUND",),
            latched_control=LatchedExecutionControl(
                signal=signal,
                observed_at=NOW - timedelta(seconds=3),
                latched_at=NOW - timedelta(seconds=2),
            ),
        )


class EmptyInflightStore:
    async def recover_active_as_orphaned(self, **kwargs: object):
        from runtime.execution import (
            InFlightRecoveryTransitionDecision,
            InFlightRecoveryTransitionStatus,
        )

        return InFlightRecoveryTransitionDecision(
            status=InFlightRecoveryTransitionStatus.NO_ACTIVE,
            reason_codes=("NO_ACTIVE",),
        )

    async def load_inflight(self, **kwargs: object):
        return ()


class EmptyBindingStore:
    async def active_for_execution(self, execution_id: str):
        return ()


class ResumableWorkflow:
    def __init__(self) -> None:
        self.last_request: WorkflowResumeRequest | None = None

    async def start(self, request, execution_context, tool_invoker):
        raise AssertionError("recovery must not start a new Workflow instance")

    async def resume(self, request, execution_context, tool_invoker):
        self.last_request = request
        return M5WorkflowResult(
            workflow_instance_id=request.workflow_instance_id,
            workflow_id=request.workflow_id,
            status=WorkflowExecutionStatus.COMPLETED,
        )


def _resolved_workflow(implementation: ResumableWorkflow) -> ResolvedStepCapabilities:
    definition = WorkflowDefinition(
        workflow_id="wf-1",
        version="7",
        checkpoint_enabled=True,
        resume_policy="EXACT_CHECKPOINT",
    )
    return ResolvedStepCapabilities(
        step_id="step-1",
        execution_owner=CapabilityExecutionOwner.WORKFLOW,
        workflow=ResolvedCapability(
            kind=CapabilityKind.WORKFLOW,
            capability_id="wf-1",
            version="7",
            definition=definition,
            implementation_ref=implementation,
            source=CapabilityReferenceSource.STEP_WORKFLOW,
        ),
    )


def test_waiting_workflow_becomes_recoverable_only_after_exact_durable_commit() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        claim = await _claim(claims)
        store = InMemoryWorkflowRecoveryCheckpointStore(claim_authority=claims)
        adapter = StaticCheckpointAdapter()
        coordinator = WorkflowWaitingCheckpointCoordinator(
            claim_authority=claims,
            store=store,
            adapter=adapter,
        )
        result = M5WorkflowResult(
            workflow_instance_id="wf-instance-1",
            workflow_id="wf-1",
            status=WorkflowExecutionStatus.WAITING,
            pending_step="await_event",
        )

        before = await store.read_latest(
            execution_id="exec-1",
            step_execution_id="step-exec-1",
        )
        assert before.status is WorkflowCheckpointReadStatus.NONE

        committed = await coordinator.commit_waiting(
            result=result,
            execution_id="exec-1",
            step_id="step-1",
            step_execution_id="step-exec-1",
            workflow_version="7",
            checkpoint_id="wf-checkpoint-1",
            expected_generation=0,
            recovery_claim=claim,
            observed_at=NOW + timedelta(seconds=1),
        )
        assert committed.status is WorkflowCheckpointCommitStatus.COMMITTED
        assert committed.checkpoint is not None
        assert committed.checkpoint.workflow_instance_id == "wf-instance-1"
        assert committed.checkpoint.workflow_version == "7"
        assert adapter.calls == 1

    asyncio.run(scenario())


def test_stale_recovery_epoch_cannot_commit_workflow_checkpoint() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        stale = await _claim(claims, owner="old")
        await _claim(claims, owner="new", expected_epoch=1)
        adapter = StaticCheckpointAdapter()
        coordinator = WorkflowWaitingCheckpointCoordinator(
            claim_authority=claims,
            store=InMemoryWorkflowRecoveryCheckpointStore(claim_authority=claims),
            adapter=adapter,
        )
        decision = await coordinator.commit_waiting(
            result=M5WorkflowResult(
                workflow_instance_id="wf-instance-1",
                workflow_id="wf-1",
                status=WorkflowExecutionStatus.WAITING,
            ),
            execution_id="exec-1",
            step_id="step-1",
            step_execution_id="step-exec-1",
            workflow_version="7",
            checkpoint_id="wf-checkpoint-1",
            expected_generation=0,
            recovery_claim=stale,
            observed_at=NOW + timedelta(seconds=2),
        )
        assert decision.status is WorkflowCheckpointCommitStatus.CONFLICT
        assert adapter.calls == 0

    asyncio.run(scenario())


def test_resume_uses_same_instance_exact_version_and_checkpoint_material() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        claim = await _claim(claims)
        implementation = ResumableWorkflow()
        checkpoint = WorkflowRecoveryCheckpoint(
            execution_id="exec-1",
            step_id="step-1",
            step_execution_id="step-exec-1",
            workflow_instance_id="wf-instance-1",
            workflow_id="wf-1",
            workflow_version="7",
            checkpoint_id="wf-checkpoint-1",
            generation=1,
            material=WorkflowCheckpointMaterial(
                state_reference="state://wf-1/g1",
                resume_token="token-g1",
                state_schema_version="domain-state-v3",
            ),
            committed_at=NOW,
            writer_recovery_epoch=1,
            writer_recovery_owner_id="worker-a",
        )
        store = InMemoryWorkflowRecoveryCheckpointStore(claim_authority=claims)
        committed = await store.commit(
            checkpoint,
            expected_generation=0,
            required_claim=claim,
        )
        assert committed.status is WorkflowCheckpointCommitStatus.COMMITTED
        coordinator = WorkflowResumeCoordinator(
            claim_authority=claims,
            checkpoint_store=store,
        )
        decision = await coordinator.authorize(
            checkpoint=checkpoint,
            resolved=_resolved_workflow(implementation),
            execution_context=_snapshot().execution_context.restore(),
            recovery_claim=claim,
        )
        assert decision.status is WorkflowResumeStatus.AUTHORIZED
        assert decision.request is not None
        assert decision.request.workflow_instance_id == "wf-instance-1"
        assert decision.request.workflow_version == "7"
        assert decision.request.checkpoint_generation == 1
        assert decision.request.state_reference == "state://wf-1/g1"
        assert decision.request.resume_token == "token-g1"
        assert implementation.last_request is None

    asyncio.run(scenario())


def test_recovery_control_barrier_precedes_workflow_resume() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        claim = await _claim(claims)
        checkpoint_store = InMemoryWorkflowRecoveryCheckpointStore(
            claim_authority=claims
        )
        coordinator = RecoveryCoordinator(
            claim_authority=claims,
            control_store=LatchedControlStore(),
            inflight_store=EmptyInflightStore(),
            binding_store=EmptyBindingStore(),
            workflow_checkpoint_store=checkpoint_store,
        )
        decision = await coordinator.decide(
            snapshot=_snapshot(),
            recovery_claim=claim,
            recovered_at=NOW + timedelta(seconds=5),
            resolved_active_step=_resolved_workflow(ResumableWorkflow()),
        )
        assert decision.disposition is RecoveryDisposition.APPLY_LATCHED_CONTROL

    asyncio.run(scenario())


def test_running_workflow_without_durable_checkpoint_waits_reconciliation() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        claim = await _claim(claims)
        coordinator = RecoveryCoordinator(
            claim_authority=claims,
            control_store=NoControlStore(),
            inflight_store=EmptyInflightStore(),
            binding_store=EmptyBindingStore(),
            workflow_checkpoint_store=InMemoryWorkflowRecoveryCheckpointStore(
                claim_authority=claims
            ),
        )
        decision = await coordinator.decide(
            snapshot=_snapshot(),
            recovery_claim=claim,
            recovered_at=NOW + timedelta(seconds=5),
            resolved_active_step=_resolved_workflow(ResumableWorkflow()),
        )
        assert decision.disposition is RecoveryDisposition.WAIT_RECONCILIATION
        assert (
            "RECOVERY_WAITING_WORKFLOW_HAS_NO_DURABLE_CHECKPOINT"
            in decision.reason_codes
        )

    asyncio.run(scenario())


def test_exact_checkpoint_authorizes_resume_workflow_disposition() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        claim = await _claim(claims)
        store = InMemoryWorkflowRecoveryCheckpointStore(claim_authority=claims)
        checkpoint = WorkflowRecoveryCheckpoint(
            execution_id="exec-1",
            step_id="step-1",
            step_execution_id="step-exec-1",
            workflow_instance_id="wf-instance-1",
            workflow_id="wf-1",
            workflow_version="7",
            checkpoint_id="wf-checkpoint-1",
            generation=1,
            material=WorkflowCheckpointMaterial(
                state_reference="state://wf-1/g1",
                resume_token="token-g1",
                state_schema_version="domain-state-v3",
            ),
            committed_at=NOW,
            writer_recovery_epoch=claim.recovery_epoch,
            writer_recovery_owner_id=claim.recovery_owner_id,
        )
        committed = await store.commit(
            checkpoint,
            expected_generation=0,
            required_claim=claim,
        )
        assert committed.status is WorkflowCheckpointCommitStatus.COMMITTED

        coordinator = RecoveryCoordinator(
            claim_authority=claims,
            control_store=NoControlStore(),
            inflight_store=EmptyInflightStore(),
            binding_store=EmptyBindingStore(),
            workflow_checkpoint_store=store,
        )
        decision = await coordinator.decide(
            snapshot=_snapshot(),
            recovery_claim=claim,
            recovered_at=NOW + timedelta(seconds=5),
            resolved_active_step=_resolved_workflow(ResumableWorkflow()),
        )
        assert decision.disposition is RecoveryDisposition.RESUME_WORKFLOW
        assert decision.workflow_checkpoint == checkpoint

    asyncio.run(scenario())


def test_no_running_step_with_pending_work_reenters_existing_scheduler() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        claim = await _claim(claims)
        coordinator = RecoveryCoordinator(
            claim_authority=claims,
            control_store=NoControlStore(),
            inflight_store=EmptyInflightStore(),
            binding_store=EmptyBindingStore(),
            workflow_checkpoint_store=InMemoryWorkflowRecoveryCheckpointStore(
                claim_authority=claims
            ),
        )
        decision = await coordinator.decide(
            snapshot=_snapshot(status=StepExecutionStatus.PENDING),
            recovery_claim=claim,
            recovered_at=NOW + timedelta(seconds=5),
        )
        assert decision.disposition is RecoveryDisposition.RESUME_SCHEDULING

    asyncio.run(scenario())


def test_exact_checkpoint_replay_does_not_repeat_domain_state_persistence() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        claim = await _claim(claims)
        store = InMemoryWorkflowRecoveryCheckpointStore(claim_authority=claims)
        adapter = StaticCheckpointAdapter()
        coordinator = WorkflowWaitingCheckpointCoordinator(
            claim_authority=claims,
            store=store,
            adapter=adapter,
        )
        result = M5WorkflowResult(
            workflow_instance_id="wf-instance-1",
            workflow_id="wf-1",
            status=WorkflowExecutionStatus.WAITING,
        )
        first = await coordinator.commit_waiting(
            result=result,
            execution_id="exec-1",
            step_id="step-1",
            step_execution_id="step-exec-1",
            workflow_version="7",
            checkpoint_id="wf-checkpoint-1",
            expected_generation=0,
            recovery_claim=claim,
            observed_at=NOW + timedelta(seconds=1),
        )
        second = await coordinator.commit_waiting(
            result=result,
            execution_id="exec-1",
            step_id="step-1",
            step_execution_id="step-exec-1",
            workflow_version="7",
            checkpoint_id="wf-checkpoint-1",
            expected_generation=0,
            recovery_claim=claim,
            observed_at=NOW + timedelta(seconds=2),
        )
        assert first.status is WorkflowCheckpointCommitStatus.COMMITTED
        assert second.status is WorkflowCheckpointCommitStatus.ALREADY_COMMITTED
        assert adapter.calls == 1

    asyncio.run(scenario())


def test_resume_rejects_checkpoint_that_is_no_longer_latest() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        claim = await _claim(claims)
        store = InMemoryWorkflowRecoveryCheckpointStore(claim_authority=claims)
        first = WorkflowRecoveryCheckpoint(
            execution_id="exec-1",
            step_id="step-1",
            step_execution_id="step-exec-1",
            workflow_instance_id="wf-instance-1",
            workflow_id="wf-1",
            workflow_version="7",
            checkpoint_id="wf-checkpoint-1",
            generation=1,
            material=WorkflowCheckpointMaterial(
                state_reference="state://wf-1/g1",
                resume_token="token-g1",
                state_schema_version="domain-state-v3",
            ),
            committed_at=NOW,
            writer_recovery_epoch=claim.recovery_epoch,
            writer_recovery_owner_id=claim.recovery_owner_id,
        )
        second = WorkflowRecoveryCheckpoint(
            execution_id="exec-1",
            step_id="step-1",
            step_execution_id="step-exec-1",
            workflow_instance_id="wf-instance-1",
            workflow_id="wf-1",
            workflow_version="7",
            checkpoint_id="wf-checkpoint-2",
            generation=2,
            material=WorkflowCheckpointMaterial(
                state_reference="state://wf-1/g2",
                resume_token="token-g2",
                state_schema_version="domain-state-v3",
            ),
            committed_at=NOW + timedelta(seconds=1),
            writer_recovery_epoch=claim.recovery_epoch,
            writer_recovery_owner_id=claim.recovery_owner_id,
        )
        assert (
            await store.commit(first, expected_generation=0, required_claim=claim)
        ).status is WorkflowCheckpointCommitStatus.COMMITTED
        assert (
            await store.commit(second, expected_generation=1, required_claim=claim)
        ).status is WorkflowCheckpointCommitStatus.COMMITTED

        coordinator = WorkflowResumeCoordinator(
            claim_authority=claims,
            checkpoint_store=store,
        )
        decision = await coordinator.authorize(
            checkpoint=first,
            resolved=_resolved_workflow(ResumableWorkflow()),
            execution_context=_snapshot().execution_context.restore(),
            recovery_claim=claim,
        )
        assert decision.status is WorkflowResumeStatus.UNKNOWN
        assert "WORKFLOW_RESUME_CHECKPOINT_IS_NOT_LATEST" in decision.reason_codes

    asyncio.run(scenario())


class CountingResumableWorkflow(ResumableWorkflow):
    def __init__(self) -> None:
        super().__init__()
        self.resume_calls = 0

    async def resume(self, request, execution_context, tool_invoker):
        self.resume_calls += 1
        return await super().resume(request, execution_context, tool_invoker)


class EpochAdvancingCheckpointStore:
    def __init__(
        self,
        *,
        delegate: InMemoryWorkflowRecoveryCheckpointStore,
        claims: InMemoryRecoveryClaimAuthority,
    ) -> None:
        self._delegate = delegate
        self._claims = claims
        self._advanced = False

    async def read_latest(self, *, execution_id: str, step_execution_id: str):
        decision = await self._delegate.read_latest(
            execution_id=execution_id,
            step_execution_id=step_execution_id,
        )
        if not self._advanced:
            self._advanced = True
            current = await self._claims.current(execution_id)
            assert current is not None
            takeover = await self._claims.claim(
                RecoveryClaimRequest(
                    claim_id="claim-takeover",
                    execution_id=execution_id,
                    recovery_owner_id="worker-new",
                    expected_current_epoch=current.recovery_epoch,
                    source_snapshot_generation=current.source_snapshot_generation,
                    requested_at=NOW + timedelta(seconds=1),
                )
            )
            assert takeover.status is RecoveryClaimStatus.CLAIMED
        return decision


def test_resume_rechecks_epoch_before_authorization_and_does_not_invoke() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        claim = await _claim(claims)
        store = InMemoryWorkflowRecoveryCheckpointStore(claim_authority=claims)
        checkpoint = WorkflowRecoveryCheckpoint(
            execution_id="exec-1",
            step_id="step-1",
            step_execution_id="step-exec-1",
            workflow_instance_id="wf-instance-1",
            workflow_id="wf-1",
            workflow_version="7",
            checkpoint_id="wf-checkpoint-1",
            generation=1,
            material=WorkflowCheckpointMaterial(
                state_reference="state://wf-1/g1",
                resume_token="token-g1",
                state_schema_version="domain-state-v3",
            ),
            committed_at=NOW,
            writer_recovery_epoch=claim.recovery_epoch,
            writer_recovery_owner_id=claim.recovery_owner_id,
        )
        assert (
            await store.commit(checkpoint, expected_generation=0, required_claim=claim)
        ).status is WorkflowCheckpointCommitStatus.COMMITTED

        implementation = CountingResumableWorkflow()
        coordinator = WorkflowResumeCoordinator(
            claim_authority=claims,
            checkpoint_store=EpochAdvancingCheckpointStore(
                delegate=store,
                claims=claims,
            ),
        )
        decision = await coordinator.authorize(
            checkpoint=checkpoint,
            resolved=_resolved_workflow(implementation),
            execution_context=_snapshot().execution_context.restore(),
            recovery_claim=claim,
        )
        assert decision.status is WorkflowResumeStatus.UNKNOWN
        assert "WORKFLOW_RESUME_AUTHORIZATION_STALE_RECOVERY_EPOCH" in decision.reason_codes
        assert implementation.resume_calls == 0

    asyncio.run(scenario())
