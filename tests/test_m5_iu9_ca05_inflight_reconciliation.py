"""CA-M5-IU9-05 durable in-flight terminal reconciliation tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from runtime.execution.control_application import (
    InFlightOperationHandle,
    InFlightOperationKind,
)
from runtime.execution.recovery import (
    ExecutionRecoveryClaim,
    InMemoryRecoveryClaimAuthority,
    RecoveryClaimRequest,
    RecoveryClaimStatus,
)
from runtime.execution.recovery_evidence import (
    DurableEvidenceMutationStatus,
    DurableInFlightOperationRegistry,
    InFlightEvidenceState,
    InFlightReconciliationBasis,
    InFlightTerminalReconciliation,
    InMemoryDurableRecoveryEvidenceStore,
)
from runtime.execution.recovery_resource_lock import (
    DurableOperationResourceLeaseRegistry,
    DurableResourceLockAuthority,
    InMemoryDurableResourceRecoveryStore,
    OperationRecoveryDecision,
    OperationRecoveryStatus,
    ProviderFenceDecision,
    ProviderFenceEvidence,
    ProviderFencePersistenceStatus,
    ProviderFenceStatus,
    ResourceRecoveryStatus,
    ToolResourceRecoveryCoordinator,
)
from runtime.execution.resource_lock import (
    ResourceLockAcquireRequest,
    ResourceLockAcquireStatus,
    ResourceLockOwner,
)
from runtime.execution.resource_lock_lifecycle import OperationResourceLeaseBinding

NOW = datetime(2026, 9, 23, 7, 0, tzinfo=UTC)


async def _claim(
    authority: InMemoryRecoveryClaimAuthority,
    *,
    claim_id: str,
    owner: str,
    expected_epoch: int,
    at: datetime,
) -> ExecutionRecoveryClaim:
    decision = await authority.claim(
        RecoveryClaimRequest(
            claim_id=claim_id,
            execution_id="execution-001",
            recovery_owner_id=owner,
            expected_current_epoch=expected_epoch,
            source_snapshot_generation=0,
            requested_at=at,
        )
    )
    assert decision.status is RecoveryClaimStatus.CLAIMED
    assert decision.claim is not None
    return decision.claim


def _handle(operation_handle_id: str = "tool-handle-001") -> InFlightOperationHandle:
    return InFlightOperationHandle(
        operation_handle_id=operation_handle_id,
        execution_id="execution-001",
        step_execution_id="step-exec-001",
        kind=InFlightOperationKind.TOOL,
        capability_id="tool-A",
        capability_version="v1",
        started_at=NOW + timedelta(seconds=2),
        parent_handle_id="owner-handle-001",
        tool_call_id="tool-call-001",
    )


class StaticProbe:
    def __init__(self, status: OperationRecoveryStatus) -> None:
        self._status = status

    async def probe(
        self,
        *,
        handle: InFlightOperationHandle,
    ) -> OperationRecoveryDecision:
        return OperationRecoveryDecision(
            operation_handle_id=handle.operation_handle_id,
            status=self._status,
            reason_codes=(f"PROBE_{self._status.value}",),
            observed_at=NOW + timedelta(seconds=8),
        )


class StaticFence:
    async def establish_fence(
        self,
        *,
        binding: OperationResourceLeaseBinding,
        recovery_claim: ExecutionRecoveryClaim,
        requested_at: datetime,
    ) -> ProviderFenceDecision:
        return ProviderFenceDecision(
            status=ProviderFenceStatus.ESTABLISHED,
            reason_codes=("PROVIDER_FENCE_ESTABLISHED",),
            evidence=ProviderFenceEvidence(
                operation_handle_id=binding.handle.operation_handle_id,
                fencing_token=(
                    f"fence:{recovery_claim.recovery_epoch}:"
                    f"{binding.handle.operation_handle_id}"
                ),
                established_at=requested_at,
                recovery_epoch=recovery_claim.recovery_epoch,
            ),
        )


async def _register_and_orphan(
    *,
    claims: InMemoryRecoveryClaimAuthority,
    evidence_store: InMemoryDurableRecoveryEvidenceStore,
    handle: InFlightOperationHandle,
) -> tuple[ExecutionRecoveryClaim, ExecutionRecoveryClaim]:
    first = await _claim(
        claims,
        claim_id="claim-001",
        owner="worker-a",
        expected_epoch=0,
        at=NOW,
    )
    registry = DurableInFlightOperationRegistry(
        store=evidence_store,
        recovery_claim=first,
        clock=lambda: NOW + timedelta(seconds=3),
    )
    assert await registry.register(handle)
    recovery = await _claim(
        claims,
        claim_id="claim-002",
        owner="worker-b",
        expected_epoch=1,
        at=NOW + timedelta(seconds=4),
    )
    transition = await evidence_store.recover_active_as_orphaned(
        execution_id=handle.execution_id,
        recovered_at=NOW + timedelta(seconds=5),
        required_claim=recovery,
    )
    assert transition.observations
    assert (
        transition.observations[0].state is InFlightEvidenceState.ORPHANED_UNCONFIRMED
    )
    return first, recovery


async def _bind_resource(
    *,
    claims: InMemoryRecoveryClaimAuthority,
    claim: ExecutionRecoveryClaim,
    evidence_store: InMemoryDurableRecoveryEvidenceStore,
    resource_store: InMemoryDurableResourceRecoveryStore,
    handle: InFlightOperationHandle,
) -> OperationResourceLeaseBinding:
    owner = ResourceLockOwner(
        owner_id=handle.operation_handle_id,
        execution_id=handle.execution_id,
        step_execution_id=handle.step_execution_id,
        tool_call_id="tool-call-001",
        physical_attempt=1,
    )
    authority = DurableResourceLockAuthority(
        store=resource_store,
        recovery_claim=claim,
    )
    acquired = await authority.acquire(
        ResourceLockAcquireRequest(
            lock_key="resource:A",
            owner=owner,
            acquisition_id=f"acq:{handle.operation_handle_id}",
            requested_at=NOW + timedelta(seconds=1),
        )
    )
    assert acquired.status is ResourceLockAcquireStatus.ACQUIRED
    assert acquired.lease is not None

    registry = DurableInFlightOperationRegistry(
        store=evidence_store,
        recovery_claim=claim,
        clock=lambda: NOW + timedelta(seconds=3),
    )
    assert await registry.register(handle)

    binding = OperationResourceLeaseBinding(
        handle=handle,
        owner=owner,
        leases=(acquired.lease,),
    )
    bindings = DurableOperationResourceLeaseRegistry(
        store=resource_store,
        recovery_claim=claim,
        clock=lambda: NOW + timedelta(seconds=3),
    )
    assert await bindings.register(binding)
    return binding


def test_orphaned_operation_can_commit_exact_completed_reconciliation() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        handle = _handle()
        _, recovery = await _register_and_orphan(
            claims=claims,
            evidence_store=store,
            handle=handle,
        )
        reconciliation = InFlightTerminalReconciliation(
            handle=handle,
            state=InFlightEvidenceState.COMPLETED,
            basis=InFlightReconciliationBasis.OPERATION_COMPLETED_CONFIRMED,
            observed_at=NOW + timedelta(seconds=8),
        )
        first = await store.commit_terminal_reconciliation(
            reconciliation=reconciliation,
            required_claim=recovery,
        )
        replay = await store.commit_terminal_reconciliation(
            reconciliation=reconciliation,
            required_claim=recovery,
        )
        assert first.status is DurableEvidenceMutationStatus.RECORDED
        assert replay.status is DurableEvidenceMutationStatus.ALREADY_CURRENT

        observations = await store.load_inflight(execution_id=handle.execution_id)
        assert len(observations) == 1
        assert observations[0].state is InFlightEvidenceState.COMPLETED
        assert (
            observations[0].reconciliation_basis
            is InFlightReconciliationBasis.OPERATION_COMPLETED_CONFIRMED
        )

    asyncio.run(scenario())


def test_stale_recovery_epoch_cannot_commit_orphan_terminal_reconciliation() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        handle = _handle()
        _, recovery = await _register_and_orphan(
            claims=claims,
            evidence_store=store,
            handle=handle,
        )
        newer = await _claim(
            claims,
            claim_id="claim-003",
            owner="worker-c",
            expected_epoch=2,
            at=NOW + timedelta(seconds=6),
        )
        assert newer.recovery_epoch == 3

        decision = await store.commit_terminal_reconciliation(
            reconciliation=InFlightTerminalReconciliation(
                handle=handle,
                state=InFlightEvidenceState.CONFIRMED_STOPPED,
                basis=InFlightReconciliationBasis.OPERATION_STOPPED_CONFIRMED,
                observed_at=NOW + timedelta(seconds=8),
            ),
            required_claim=recovery,
        )
        assert decision.status is DurableEvidenceMutationStatus.CONFLICT
        observations = await store.load_inflight(execution_id=handle.execution_id)
        assert observations[0].state is InFlightEvidenceState.ORPHANED_UNCONFIRMED

    asyncio.run(scenario())


def test_probe_stop_reclaims_resource_and_commits_confirmed_stopped() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        evidence = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        resources = InMemoryDurableResourceRecoveryStore(claim_authority=claims)
        handle = _handle()

        first = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
            at=NOW,
        )
        await _bind_resource(
            claims=claims,
            claim=first,
            evidence_store=evidence,
            resource_store=resources,
            handle=handle,
        )
        recovery = await _claim(
            claims,
            claim_id="claim-002",
            owner="worker-b",
            expected_epoch=1,
            at=NOW + timedelta(seconds=4),
        )
        await evidence.recover_active_as_orphaned(
            execution_id=handle.execution_id,
            recovered_at=NOW + timedelta(seconds=5),
            required_claim=recovery,
        )

        coordinator = ToolResourceRecoveryCoordinator(
            claim_authority=claims,
            lock_store=resources,
            binding_store=resources,
            inflight_store=evidence,
            operation_probe=StaticProbe(OperationRecoveryStatus.STOPPED_CONFIRMED),
        )
        decision = await coordinator.recover(
            operation_handle_id=handle.operation_handle_id,
            recovery_claim=recovery,
            recovered_at=NOW + timedelta(seconds=9),
        )
        assert decision.status is ResourceRecoveryStatus.RECLAIMED

        observations = await evidence.load_inflight(
            execution_id=handle.execution_id,
            step_execution_id=handle.step_execution_id,
        )
        assert observations[0].state is InFlightEvidenceState.CONFIRMED_STOPPED
        assert (
            observations[0].reconciliation_basis
            is InFlightReconciliationBasis.OPERATION_STOPPED_CONFIRMED
        )

    asyncio.run(scenario())


def test_provider_fence_commits_fenced_out_not_false_confirmed_stopped() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        evidence = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        resources = InMemoryDurableResourceRecoveryStore(claim_authority=claims)
        handle = _handle()

        first = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
            at=NOW,
        )
        await _bind_resource(
            claims=claims,
            claim=first,
            evidence_store=evidence,
            resource_store=resources,
            handle=handle,
        )
        recovery = await _claim(
            claims,
            claim_id="claim-002",
            owner="worker-b",
            expected_epoch=1,
            at=NOW + timedelta(seconds=4),
        )
        await evidence.recover_active_as_orphaned(
            execution_id=handle.execution_id,
            recovered_at=NOW + timedelta(seconds=5),
            required_claim=recovery,
        )

        coordinator = ToolResourceRecoveryCoordinator(
            claim_authority=claims,
            lock_store=resources,
            binding_store=resources,
            inflight_store=evidence,
            operation_probe=StaticProbe(OperationRecoveryStatus.RUNNING_CONFIRMED),
            provider_fencing=StaticFence(),
        )
        decision = await coordinator.recover(
            operation_handle_id=handle.operation_handle_id,
            recovery_claim=recovery,
            recovered_at=NOW + timedelta(seconds=9),
        )
        assert decision.status is ResourceRecoveryStatus.RECLAIMED

        observations = await evidence.load_inflight(execution_id=handle.execution_id)
        assert observations[0].state is InFlightEvidenceState.FENCED_OUT
        assert (
            observations[0].reconciliation_basis
            is InFlightReconciliationBasis.PROVIDER_FENCE_ESTABLISHED
        )

    asyncio.run(scenario())


def test_released_binding_tombstone_backfills_orphan_terminal_evidence() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        evidence = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        resources = InMemoryDurableResourceRecoveryStore(claim_authority=claims)
        handle = _handle()

        first = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
            at=NOW,
        )
        binding = await _bind_resource(
            claims=claims,
            claim=first,
            evidence_store=evidence,
            resource_store=resources,
            handle=handle,
        )
        recovery = await _claim(
            claims,
            claim_id="claim-002",
            owner="worker-b",
            expected_epoch=1,
            at=NOW + timedelta(seconds=4),
        )
        await evidence.recover_active_as_orphaned(
            execution_id=handle.execution_id,
            recovered_at=NOW + timedelta(seconds=5),
            required_claim=recovery,
        )

        fence = ProviderFenceEvidence(
            operation_handle_id=handle.operation_handle_id,
            fencing_token=f"fence:{recovery.recovery_epoch}:{handle.operation_handle_id}",
            established_at=NOW + timedelta(seconds=6),
            recovery_epoch=recovery.recovery_epoch,
        )
        persisted = await resources.record_provider_fence(
            binding,
            evidence=fence,
            recorded_at=NOW + timedelta(seconds=6),
            required_claim=recovery,
        )
        assert persisted.status is ProviderFencePersistenceStatus.RECORDED

        for lease in binding.leases:
            released = await resources.release(
                lease,
                released_at=NOW + timedelta(seconds=7),
                required_claim=recovery,
            )
            assert released.status.name in {"RELEASED", "ALREADY_RELEASED"}
        marked = await resources.mark_released(
            binding,
            released_at=NOW + timedelta(seconds=7),
            release_basis="PROVIDER_FENCE_ESTABLISHED",
            required_claim=recovery,
            provider_fence=fence,
        )
        assert marked

        coordinator = ToolResourceRecoveryCoordinator(
            claim_authority=claims,
            lock_store=resources,
            binding_store=resources,
            inflight_store=evidence,
        )
        decision = await coordinator.recover(
            operation_handle_id=handle.operation_handle_id,
            recovery_claim=recovery,
            recovered_at=NOW + timedelta(seconds=9),
        )
        assert decision.status is ResourceRecoveryStatus.ALREADY_RECLAIMED

        observations = await evidence.load_inflight(execution_id=handle.execution_id)
        assert observations[0].state is InFlightEvidenceState.FENCED_OUT
        assert (
            observations[0].reconciliation_basis
            is InFlightReconciliationBasis.PROVIDER_FENCE_ESTABLISHED
        )

    asyncio.run(scenario())


def test_unbound_orphan_with_strong_probe_can_converge_without_resource_lock() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        evidence = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        resources = InMemoryDurableResourceRecoveryStore(claim_authority=claims)
        handle = _handle()

        _, recovery = await _register_and_orphan(
            claims=claims,
            evidence_store=evidence,
            handle=handle,
        )
        coordinator = ToolResourceRecoveryCoordinator(
            claim_authority=claims,
            lock_store=resources,
            binding_store=resources,
            inflight_store=evidence,
            operation_probe=StaticProbe(OperationRecoveryStatus.COMPLETED_CONFIRMED),
        )
        decision = await coordinator.recover(
            operation_handle_id=handle.operation_handle_id,
            recovery_claim=recovery,
            recovered_at=NOW + timedelta(seconds=9),
        )
        assert decision.status is ResourceRecoveryStatus.NO_RESOURCE_LOCKS
        assert decision.operation_recovery is not None

        observations = await evidence.load_inflight(execution_id=handle.execution_id)
        assert observations[0].state is InFlightEvidenceState.COMPLETED
        assert (
            observations[0].reconciliation_basis
            is InFlightReconciliationBasis.OPERATION_COMPLETED_CONFIRMED
        )

    asyncio.run(scenario())


def test_not_found_with_proof_commits_proven_absent_not_false_stopped() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        evidence = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        resources = InMemoryDurableResourceRecoveryStore(claim_authority=claims)
        handle = _handle()

        _, recovery = await _register_and_orphan(
            claims=claims,
            evidence_store=evidence,
            handle=handle,
        )
        coordinator = ToolResourceRecoveryCoordinator(
            claim_authority=claims,
            lock_store=resources,
            binding_store=resources,
            inflight_store=evidence,
            operation_probe=StaticProbe(OperationRecoveryStatus.NOT_FOUND_WITH_PROOF),
        )
        decision = await coordinator.recover(
            operation_handle_id=handle.operation_handle_id,
            recovery_claim=recovery,
            recovered_at=NOW + timedelta(seconds=9),
        )
        assert decision.status is ResourceRecoveryStatus.NO_RESOURCE_LOCKS

        observations = await evidence.load_inflight(execution_id=handle.execution_id)
        assert observations[0].state is InFlightEvidenceState.PROVEN_ABSENT
        assert (
            observations[0].reconciliation_basis
            is InFlightReconciliationBasis.OPERATION_NOT_FOUND_WITH_PROOF
        )

    asyncio.run(scenario())


def test_running_probe_does_not_upgrade_orphan_to_terminal() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        evidence = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        resources = InMemoryDurableResourceRecoveryStore(claim_authority=claims)
        handle = _handle()

        _, recovery = await _register_and_orphan(
            claims=claims,
            evidence_store=evidence,
            handle=handle,
        )
        coordinator = ToolResourceRecoveryCoordinator(
            claim_authority=claims,
            lock_store=resources,
            binding_store=resources,
            inflight_store=evidence,
            operation_probe=StaticProbe(OperationRecoveryStatus.RUNNING_CONFIRMED),
        )
        decision = await coordinator.recover(
            operation_handle_id=handle.operation_handle_id,
            recovery_claim=recovery,
            recovered_at=NOW + timedelta(seconds=9),
        )
        assert decision.status is ResourceRecoveryStatus.UNKNOWN

        observations = await evidence.load_inflight(execution_id=handle.execution_id)
        assert observations[0].state is InFlightEvidenceState.ORPHANED_UNCONFIRMED
        assert observations[0].reconciliation_basis is None

    asyncio.run(scenario())
