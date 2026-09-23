"""CA-M5-IU9-03 durable ResourceLock recovery and fencing tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from runtime.contracts.execution import ExecutionContext
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
    DurableInFlightOperationRegistry,
    InFlightEvidenceState,
    InMemoryDurableRecoveryEvidenceStore,
)
from runtime.execution.recovery_resource_lock import (
    DurableOperationResourceBindingReadStatus,
    DurableOperationResourceLeaseRegistry,
    DurableResourceLockAuthority,
    DurableResourceLockReadStatus,
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
    ResourceLockLease,
    ResourceLockOwner,
    ResourceLockReleaseStatus,
)
from runtime.execution.resource_lock_lifecycle import (
    OperationResourceLeaseBinding,
    OperationResourceReleaseCoordinator,
    OperationResourceReleaseStatus,
    SessionExecutionAcquireStatus,
    SessionExecutionLockCoordinator,
    Sha256SessionExecutionLockIdentityFactory,
)

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)


async def _claim(
    authority: InMemoryRecoveryClaimAuthority,
    *,
    claim_id: str,
    owner: str,
    expected_epoch: int,
    execution_id: str = "execution-001",
    source_generation: int = 0,
    at: datetime = NOW,
) -> ExecutionRecoveryClaim:
    decision = await authority.claim(
        RecoveryClaimRequest(
            claim_id=claim_id,
            execution_id=execution_id,
            recovery_owner_id=owner,
            expected_current_epoch=expected_epoch,
            source_snapshot_generation=source_generation,
            requested_at=at,
        )
    )
    assert decision.status is RecoveryClaimStatus.CLAIMED
    assert decision.claim is not None
    return decision.claim


def _execution_context(
    *,
    execution_id: str,
    session_id: str = "session-001",
) -> ExecutionContext:
    return ExecutionContext(
        execution_id=execution_id,
        plan_id="plan-001",
        request_id=f"request-{execution_id}",
        session_id=session_id,
        identity_scope="scope-001",
        policy_snapshot={"version": "p1"},
    )


def _tool_owner(
    *,
    operation_handle_id: str = "tool-handle-001",
    execution_id: str = "execution-001",
) -> ResourceLockOwner:
    return ResourceLockOwner(
        owner_id=operation_handle_id,
        execution_id=execution_id,
        step_execution_id="step-exec-001",
        tool_call_id="tool-call-001",
        physical_attempt=1,
    )


def _tool_handle(
    *,
    operation_handle_id: str = "tool-handle-001",
    execution_id: str = "execution-001",
) -> InFlightOperationHandle:
    return InFlightOperationHandle(
        operation_handle_id=operation_handle_id,
        execution_id=execution_id,
        step_execution_id="step-exec-001",
        kind=InFlightOperationKind.TOOL,
        capability_id="tool-A",
        capability_version="v1",
        started_at=NOW + timedelta(seconds=2),
        parent_handle_id="owner-handle-001",
        tool_call_id="tool-call-001",
    )


class FaultingInflightEvidenceStore(InMemoryDurableRecoveryEvidenceStore):
    async def load_inflight(
        self,
        *,
        execution_id: str,
        step_execution_id: str | None = None,
    ):
        raise RuntimeError("simulated durable inflight read failure")


class FailingReleaseResourceStore(InMemoryDurableResourceRecoveryStore):
    def __init__(
        self,
        *,
        claim_authority: InMemoryRecoveryClaimAuthority,
        fail_acquisition_id: str,
    ) -> None:
        super().__init__(claim_authority=claim_authority)
        self._fail_acquisition_id = fail_acquisition_id

    async def release(
        self,
        lease: ResourceLockLease,
        *,
        released_at: datetime,
        required_claim: ExecutionRecoveryClaim,
    ):
        if lease.acquisition_id == self._fail_acquisition_id:
            raise RuntimeError("simulated durable lock release failure")
        return await super().release(
            lease,
            released_at=released_at,
            required_claim=required_claim,
        )


class StaticProbe:
    def __init__(
        self,
        status: OperationRecoveryStatus,
        *,
        observed_at: datetime | None = None,
        returned_operation_handle_id: str | None = None,
    ) -> None:
        self._status = status
        self._observed_at = observed_at or NOW + timedelta(seconds=8)
        self._returned_operation_handle_id = returned_operation_handle_id
        self.calls: list[str] = []

    async def probe(
        self,
        *,
        handle: InFlightOperationHandle,
    ) -> OperationRecoveryDecision:
        self.calls.append(handle.operation_handle_id)
        return OperationRecoveryDecision(
            operation_handle_id=(
                self._returned_operation_handle_id or handle.operation_handle_id
            ),
            status=self._status,
            reason_codes=(f"PROBE_{self._status.value}",),
            observed_at=self._observed_at,
        )


class StaticFence:
    def __init__(
        self,
        status: ProviderFenceStatus,
    ) -> None:
        self._status = status
        self.calls: list[str] = []

    async def establish_fence(
        self,
        *,
        binding: OperationResourceLeaseBinding,
        recovery_claim: ExecutionRecoveryClaim,
        requested_at: datetime,
    ) -> ProviderFenceDecision:
        handle_id = binding.handle.operation_handle_id
        self.calls.append(handle_id)
        if self._status is ProviderFenceStatus.ESTABLISHED:
            return ProviderFenceDecision(
                status=ProviderFenceStatus.ESTABLISHED,
                reason_codes=("PROVIDER_FENCE_ESTABLISHED",),
                evidence=ProviderFenceEvidence(
                    operation_handle_id=handle_id,
                    fencing_token=f"fence:{recovery_claim.recovery_epoch}:{handle_id}",
                    established_at=requested_at,
                    recovery_epoch=recovery_claim.recovery_epoch,
                ),
            )
        return ProviderFenceDecision(
            status=self._status,
            reason_codes=(f"PROVIDER_FENCE_{self._status.value}",),
        )


async def _setup_bound_tool(
    *,
    claims: InMemoryRecoveryClaimAuthority,
    claim: ExecutionRecoveryClaim,
    resource_store: InMemoryDurableResourceRecoveryStore,
    evidence_store: InMemoryDurableRecoveryEvidenceStore,
    operation_handle_id: str = "tool-handle-001",
    lock_keys: tuple[str, ...] = ("resource:A",),
) -> tuple[
    InFlightOperationHandle,
    OperationResourceLeaseBinding,
]:
    owner = _tool_owner(
        operation_handle_id=operation_handle_id,
        execution_id=claim.execution_id,
    )
    authority = DurableResourceLockAuthority(
        store=resource_store,
        recovery_claim=claim,
    )
    leases = []
    for index, lock_key in enumerate(lock_keys, start=1):
        decision = await authority.acquire(
            ResourceLockAcquireRequest(
                lock_key=lock_key,
                owner=owner,
                acquisition_id=f"acq:{operation_handle_id}:{index}",
                requested_at=NOW + timedelta(seconds=1),
            )
        )
        assert decision.status is ResourceLockAcquireStatus.ACQUIRED
        assert decision.lease is not None
        leases.append(decision.lease)

    handle = _tool_handle(
        operation_handle_id=operation_handle_id,
        execution_id=claim.execution_id,
    )
    inflight = DurableInFlightOperationRegistry(
        store=evidence_store,
        recovery_claim=claim,
        clock=lambda: NOW + timedelta(seconds=3),
    )
    assert await inflight.register(handle)

    binding = OperationResourceLeaseBinding(
        handle=handle,
        owner=owner,
        leases=tuple(leases),
    )
    registry = DurableOperationResourceLeaseRegistry(
        store=resource_store,
        recovery_claim=claim,
        clock=lambda: NOW + timedelta(seconds=3),
    )
    assert await registry.register(binding)
    return handle, binding


async def _takeover_and_orphan(
    *,
    claims: InMemoryRecoveryClaimAuthority,
    evidence_store: InMemoryDurableRecoveryEvidenceStore,
    execution_id: str = "execution-001",
) -> ExecutionRecoveryClaim:
    claim = await _claim(
        claims,
        claim_id="claim-002",
        owner="worker-b",
        expected_epoch=1,
        execution_id=execution_id,
        at=NOW + timedelta(seconds=4),
    )
    transition = await evidence_store.recover_active_as_orphaned(
        execution_id=execution_id,
        recovered_at=NOW + timedelta(seconds=5),
        required_claim=claim,
    )
    assert all(
        item.state is not InFlightEvidenceState.ACTIVE_AT_CHECKPOINT
        for item in transition.observations
    )
    return claim


def test_session_lock_exact_execution_reattaches_after_restart_and_competitor_is_busy() -> (
    None
):
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        first_claim = await _claim(
            claims,
            claim_id="claim-e1-1",
            owner="worker-a",
            expected_epoch=0,
            execution_id="execution-001",
        )
        store = InMemoryDurableResourceRecoveryStore(claim_authority=claims)
        coordinator = SessionExecutionLockCoordinator(
            authority=DurableResourceLockAuthority(
                store=store,
                recovery_claim=first_claim,
            ),
            identity_factory=Sha256SessionExecutionLockIdentityFactory(),
        )
        context = _execution_context(execution_id="execution-001")

        first = await coordinator.acquire(
            execution_context=context,
            requested_at=NOW + timedelta(seconds=1),
        )
        assert first.status is SessionExecutionAcquireStatus.ACQUIRED
        assert first.session_lease is not None

        takeover = await _claim(
            claims,
            claim_id="claim-e1-2",
            owner="worker-b",
            expected_epoch=1,
            execution_id="execution-001",
            at=NOW + timedelta(seconds=2),
        )
        recreated = SessionExecutionLockCoordinator(
            authority=DurableResourceLockAuthority(
                store=store,
                recovery_claim=takeover,
            ),
            identity_factory=Sha256SessionExecutionLockIdentityFactory(),
        )
        replay = await recreated.acquire(
            execution_context=context,
            requested_at=NOW + timedelta(seconds=3),
        )
        assert replay.status is SessionExecutionAcquireStatus.ALREADY_ACQUIRED
        assert replay.session_lease == first.session_lease

        competing_claim = await _claim(
            claims,
            claim_id="claim-e2-1",
            owner="worker-c",
            expected_epoch=0,
            execution_id="execution-002",
            at=NOW + timedelta(seconds=3),
        )
        competitor = SessionExecutionLockCoordinator(
            authority=DurableResourceLockAuthority(
                store=store,
                recovery_claim=competing_claim,
            ),
            identity_factory=Sha256SessionExecutionLockIdentityFactory(),
        )
        busy = await competitor.acquire(
            execution_context=_execution_context(
                execution_id="execution-002",
                session_id="session-001",
            ),
            requested_at=NOW + timedelta(seconds=4),
        )
        assert busy.status is SessionExecutionAcquireStatus.BUSY

    asyncio.run(scenario())


def test_stale_recovery_epoch_cannot_release_newer_owned_lease() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        first_claim = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
        )
        store = InMemoryDurableResourceRecoveryStore(claim_authority=claims)
        stale_authority = DurableResourceLockAuthority(
            store=store,
            recovery_claim=first_claim,
        )
        owner = _tool_owner()
        acquired = await stale_authority.acquire(
            ResourceLockAcquireRequest(
                lock_key="resource:A",
                owner=owner,
                acquisition_id="acq:001",
                requested_at=NOW + timedelta(seconds=1),
            )
        )
        assert acquired.lease is not None

        await _claim(
            claims,
            claim_id="claim-002",
            owner="worker-b",
            expected_epoch=1,
            at=NOW + timedelta(seconds=2),
        )
        stale_release = await stale_authority.release(
            acquired.lease,
            released_at=NOW + timedelta(seconds=3),
        )
        assert stale_release.status is ResourceLockReleaseStatus.UNKNOWN
        assert stale_release.reason_codes == (
            "DURABLE_LOCK_RELEASE_RECOVERY_EPOCH_NOT_CURRENT",
        )

        read = await store.read_by_acquisition("acq:001")
        assert read.status is DurableResourceLockReadStatus.ACTIVE

    asyncio.run(scenario())


def test_existing_iu8_release_coordinator_works_with_durable_adapters() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        claim = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
        )
        store = InMemoryDurableResourceRecoveryStore(claim_authority=claims)
        authority = DurableResourceLockAuthority(
            store=store,
            recovery_claim=claim,
        )
        owner = _tool_owner()
        acquired = await authority.acquire(
            ResourceLockAcquireRequest(
                lock_key="resource:A",
                owner=owner,
                acquisition_id="acq:001",
                requested_at=NOW + timedelta(seconds=1),
            )
        )
        assert acquired.lease is not None
        handle = _tool_handle()
        binding = OperationResourceLeaseBinding(
            handle=handle,
            owner=owner,
            leases=(acquired.lease,),
        )
        registry = DurableOperationResourceLeaseRegistry(
            store=store,
            recovery_claim=claim,
            clock=lambda: NOW + timedelta(seconds=4),
        )
        release = OperationResourceReleaseCoordinator(
            authority=authority,
            registry=registry,
        )
        assert await release.bind(binding)

        decision = await release.release_after_completion(
            binding=binding,
            completed_handle=handle,
            completed_at=NOW + timedelta(seconds=4),
        )
        assert decision.status is OperationResourceReleaseStatus.RELEASED

        lock_read = await store.read_by_acquisition("acq:001")
        assert lock_read.status is DurableResourceLockReadStatus.RELEASED
        binding_read = await store.read(handle.operation_handle_id)
        assert binding_read.status is DurableOperationResourceBindingReadStatus.RELEASED
        assert binding_read.record is not None
        assert binding_read.record.release_basis == "LIVE_OPERATION_TERMINAL_RELEASE"

    asyncio.run(scenario())


def test_crashed_orphan_without_probe_is_retained_even_after_long_time() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        first_claim = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
        )
        resource_store = InMemoryDurableResourceRecoveryStore(claim_authority=claims)
        evidence_store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        handle, binding = await _setup_bound_tool(
            claims=claims,
            claim=first_claim,
            resource_store=resource_store,
            evidence_store=evidence_store,
        )
        recovery_claim = await _takeover_and_orphan(
            claims=claims,
            evidence_store=evidence_store,
        )

        coordinator = ToolResourceRecoveryCoordinator(
            claim_authority=claims,
            lock_store=resource_store,
            binding_store=resource_store,
            inflight_store=evidence_store,
        )
        decision = await coordinator.recover(
            operation_handle_id=handle.operation_handle_id,
            recovery_claim=recovery_claim,
            recovered_at=NOW + timedelta(days=365),
        )

        assert decision.status is ResourceRecoveryStatus.RETAINED
        assert decision.reason_codes == ("RESOURCE_RECONCILIATION_REQUIRED",)
        assert decision.retained_leases == binding.leases
        for lease in binding.leases:
            read = await resource_store.read_by_acquisition(lease.acquisition_id)
            assert read.status is DurableResourceLockReadStatus.ACTIVE

    asyncio.run(scenario())


def test_stopped_confirmed_probe_permits_exact_reclaim() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        first_claim = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
        )
        resource_store = InMemoryDurableResourceRecoveryStore(claim_authority=claims)
        evidence_store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        handle, binding = await _setup_bound_tool(
            claims=claims,
            claim=first_claim,
            resource_store=resource_store,
            evidence_store=evidence_store,
            lock_keys=("resource:A", "resource:B"),
        )
        recovery_claim = await _takeover_and_orphan(
            claims=claims,
            evidence_store=evidence_store,
        )
        probe = StaticProbe(OperationRecoveryStatus.STOPPED_CONFIRMED)
        coordinator = ToolResourceRecoveryCoordinator(
            claim_authority=claims,
            lock_store=resource_store,
            binding_store=resource_store,
            inflight_store=evidence_store,
            operation_probe=probe,
        )

        decision = await coordinator.recover(
            operation_handle_id=handle.operation_handle_id,
            recovery_claim=recovery_claim,
            recovered_at=NOW + timedelta(seconds=9),
        )

        assert decision.status is ResourceRecoveryStatus.RECLAIMED
        assert decision.released_leases == binding.leases
        assert probe.calls == [handle.operation_handle_id]
        binding_read = await resource_store.read(handle.operation_handle_id)
        assert binding_read.status is DurableOperationResourceBindingReadStatus.RELEASED
        assert binding_read.record is not None
        assert binding_read.record.release_basis == "PROBE_STOPPED_CONFIRMED"
        for lease in binding.leases:
            read = await resource_store.read_by_acquisition(lease.acquisition_id)
            assert read.status is DurableResourceLockReadStatus.RELEASED

    asyncio.run(scenario())


def test_completed_durable_inflight_evidence_reclaims_without_probe() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        first_claim = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
        )
        resource_store = InMemoryDurableResourceRecoveryStore(claim_authority=claims)
        evidence_store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        handle, binding = await _setup_bound_tool(
            claims=claims,
            claim=first_claim,
            resource_store=resource_store,
            evidence_store=evidence_store,
        )
        live = DurableInFlightOperationRegistry(
            store=evidence_store,
            recovery_claim=first_claim,
        )
        assert await live.complete(
            handle.operation_handle_id,
            completed_at=NOW + timedelta(seconds=4),
        )

        recovery_claim = await _claim(
            claims,
            claim_id="claim-002",
            owner="worker-b",
            expected_epoch=1,
            at=NOW + timedelta(seconds=5),
        )
        probe = StaticProbe(OperationRecoveryStatus.UNKNOWN)
        coordinator = ToolResourceRecoveryCoordinator(
            claim_authority=claims,
            lock_store=resource_store,
            binding_store=resource_store,
            inflight_store=evidence_store,
            operation_probe=probe,
        )
        decision = await coordinator.recover(
            operation_handle_id=handle.operation_handle_id,
            recovery_claim=recovery_claim,
            recovered_at=NOW + timedelta(seconds=7),
        )

        assert decision.status is ResourceRecoveryStatus.RECLAIMED
        assert decision.reason_codes[0] == "DURABLE_INFLIGHT_COMPLETED"
        assert decision.released_leases == binding.leases
        assert probe.calls == []

    asyncio.run(scenario())


def test_running_confirmed_without_provider_fence_retains_lock() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        first_claim = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
        )
        resource_store = InMemoryDurableResourceRecoveryStore(claim_authority=claims)
        evidence_store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        handle, binding = await _setup_bound_tool(
            claims=claims,
            claim=first_claim,
            resource_store=resource_store,
            evidence_store=evidence_store,
        )
        recovery_claim = await _takeover_and_orphan(
            claims=claims,
            evidence_store=evidence_store,
        )
        coordinator = ToolResourceRecoveryCoordinator(
            claim_authority=claims,
            lock_store=resource_store,
            binding_store=resource_store,
            inflight_store=evidence_store,
            operation_probe=StaticProbe(OperationRecoveryStatus.RUNNING_CONFIRMED),
        )

        decision = await coordinator.recover(
            operation_handle_id=handle.operation_handle_id,
            recovery_claim=recovery_claim,
            recovered_at=NOW + timedelta(seconds=9),
        )

        assert decision.status is ResourceRecoveryStatus.RETAINED
        assert decision.reason_codes == ("OPERATION_RUNNING_RESOURCE_RETAINED",)
        assert decision.retained_leases == binding.leases

    asyncio.run(scenario())


def test_provider_fence_allows_reclaim_of_running_old_operation() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        first_claim = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
        )
        resource_store = InMemoryDurableResourceRecoveryStore(claim_authority=claims)
        evidence_store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        handle, _binding = await _setup_bound_tool(
            claims=claims,
            claim=first_claim,
            resource_store=resource_store,
            evidence_store=evidence_store,
        )
        recovery_claim = await _takeover_and_orphan(
            claims=claims,
            evidence_store=evidence_store,
        )
        fence = StaticFence(ProviderFenceStatus.ESTABLISHED)
        coordinator = ToolResourceRecoveryCoordinator(
            claim_authority=claims,
            lock_store=resource_store,
            binding_store=resource_store,
            inflight_store=evidence_store,
            operation_probe=StaticProbe(OperationRecoveryStatus.RUNNING_CONFIRMED),
            provider_fencing=fence,
        )

        decision = await coordinator.recover(
            operation_handle_id=handle.operation_handle_id,
            recovery_claim=recovery_claim,
            recovered_at=NOW + timedelta(seconds=9),
        )

        assert decision.status is ResourceRecoveryStatus.RECLAIMED
        assert decision.provider_fence is not None
        assert decision.provider_fence.recovery_epoch == recovery_claim.recovery_epoch
        assert fence.calls == [handle.operation_handle_id]

        binding_read = await resource_store.read(handle.operation_handle_id)
        assert binding_read.record is not None
        assert binding_read.record.release_basis == "PROVIDER_FENCE_ESTABLISHED"
        assert binding_read.record.provider_fence == decision.provider_fence

    asyncio.run(scenario())


def test_provider_fence_unsupported_does_not_authorize_reclaim() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        first_claim = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
        )
        resource_store = InMemoryDurableResourceRecoveryStore(claim_authority=claims)
        evidence_store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        handle, binding = await _setup_bound_tool(
            claims=claims,
            claim=first_claim,
            resource_store=resource_store,
            evidence_store=evidence_store,
        )
        recovery_claim = await _takeover_and_orphan(
            claims=claims,
            evidence_store=evidence_store,
        )
        coordinator = ToolResourceRecoveryCoordinator(
            claim_authority=claims,
            lock_store=resource_store,
            binding_store=resource_store,
            inflight_store=evidence_store,
            operation_probe=StaticProbe(OperationRecoveryStatus.RUNNING_CONFIRMED),
            provider_fencing=StaticFence(ProviderFenceStatus.UNSUPPORTED),
        )

        decision = await coordinator.recover(
            operation_handle_id=handle.operation_handle_id,
            recovery_claim=recovery_claim,
            recovered_at=NOW + timedelta(seconds=9),
        )

        assert decision.status is ResourceRecoveryStatus.RETAINED
        assert decision.retained_leases == binding.leases

    asyncio.run(scenario())


def test_not_found_with_proof_is_strong_provider_evidence() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        first_claim = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
        )
        resource_store = InMemoryDurableResourceRecoveryStore(claim_authority=claims)
        evidence_store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        handle, _ = await _setup_bound_tool(
            claims=claims,
            claim=first_claim,
            resource_store=resource_store,
            evidence_store=evidence_store,
        )
        recovery_claim = await _takeover_and_orphan(
            claims=claims,
            evidence_store=evidence_store,
        )
        coordinator = ToolResourceRecoveryCoordinator(
            claim_authority=claims,
            lock_store=resource_store,
            binding_store=resource_store,
            inflight_store=evidence_store,
            operation_probe=StaticProbe(OperationRecoveryStatus.NOT_FOUND_WITH_PROOF),
        )

        decision = await coordinator.recover(
            operation_handle_id=handle.operation_handle_id,
            recovery_claim=recovery_claim,
            recovered_at=NOW + timedelta(seconds=9),
        )

        assert decision.status is ResourceRecoveryStatus.RECLAIMED
        assert decision.reason_codes[0] == "PROBE_NOT_FOUND_WITH_PROOF"

    asyncio.run(scenario())


def test_stale_recovery_claim_cannot_reclaim_bound_tool_resources() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        first_claim = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
        )
        resource_store = InMemoryDurableResourceRecoveryStore(claim_authority=claims)
        evidence_store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        handle, binding = await _setup_bound_tool(
            claims=claims,
            claim=first_claim,
            resource_store=resource_store,
            evidence_store=evidence_store,
        )
        await _claim(
            claims,
            claim_id="claim-002",
            owner="worker-b",
            expected_epoch=1,
            at=NOW + timedelta(seconds=4),
        )
        coordinator = ToolResourceRecoveryCoordinator(
            claim_authority=claims,
            lock_store=resource_store,
            binding_store=resource_store,
            inflight_store=evidence_store,
            operation_probe=StaticProbe(OperationRecoveryStatus.STOPPED_CONFIRMED),
        )

        decision = await coordinator.recover(
            operation_handle_id=handle.operation_handle_id,
            recovery_claim=first_claim,
            recovered_at=NOW + timedelta(seconds=9),
        )

        assert decision.status is ResourceRecoveryStatus.UNKNOWN
        assert decision.reason_codes == ("RESOURCE_RECOVERY_STALE_EPOCH",)
        for lease in binding.leases:
            read = await resource_store.read_by_acquisition(lease.acquisition_id)
            assert read.status is DurableResourceLockReadStatus.ACTIVE

    asyncio.run(scenario())


def test_unbound_active_tool_lease_is_discoverable_and_retained() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        first_claim = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
        )
        resource_store = InMemoryDurableResourceRecoveryStore(claim_authority=claims)
        evidence_store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        owner = _tool_owner()
        authority = DurableResourceLockAuthority(
            store=resource_store,
            recovery_claim=first_claim,
        )
        acquired = await authority.acquire(
            ResourceLockAcquireRequest(
                lock_key="resource:A",
                owner=owner,
                acquisition_id="acq:unbound",
                requested_at=NOW + timedelta(seconds=1),
            )
        )
        assert acquired.status is ResourceLockAcquireStatus.ACQUIRED
        assert acquired.lease is not None

        recovery_claim = await _claim(
            claims,
            claim_id="claim-002",
            owner="worker-b",
            expected_epoch=1,
            at=NOW + timedelta(seconds=3),
        )
        coordinator = ToolResourceRecoveryCoordinator(
            claim_authority=claims,
            lock_store=resource_store,
            binding_store=resource_store,
            inflight_store=evidence_store,
        )
        decision = await coordinator.recover(
            operation_handle_id=owner.owner_id,
            recovery_claim=recovery_claim,
            recovered_at=NOW + timedelta(seconds=8),
        )

        assert decision.status is ResourceRecoveryStatus.RETAINED
        assert decision.reason_codes == (
            "UNBOUND_ACTIVE_RESOURCE_LEASES_REQUIRE_RECONCILIATION",
        )
        assert decision.retained_leases == (acquired.lease,)

    asyncio.run(scenario())


def test_reclaimed_lock_can_be_acquired_by_new_exact_acquisition() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        first_claim = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
        )
        resource_store = InMemoryDurableResourceRecoveryStore(claim_authority=claims)
        evidence_store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        handle, binding = await _setup_bound_tool(
            claims=claims,
            claim=first_claim,
            resource_store=resource_store,
            evidence_store=evidence_store,
        )
        recovery_claim = await _takeover_and_orphan(
            claims=claims,
            evidence_store=evidence_store,
        )
        coordinator = ToolResourceRecoveryCoordinator(
            claim_authority=claims,
            lock_store=resource_store,
            binding_store=resource_store,
            inflight_store=evidence_store,
            operation_probe=StaticProbe(OperationRecoveryStatus.STOPPED_CONFIRMED),
        )
        reclaimed = await coordinator.recover(
            operation_handle_id=handle.operation_handle_id,
            recovery_claim=recovery_claim,
            recovered_at=NOW + timedelta(seconds=9),
        )
        assert reclaimed.status is ResourceRecoveryStatus.RECLAIMED

        new_owner = ResourceLockOwner(
            owner_id="tool-handle-002",
            execution_id="execution-001",
            step_execution_id="step-exec-002",
            tool_call_id="tool-call-002",
            physical_attempt=1,
        )
        current_authority = DurableResourceLockAuthority(
            store=resource_store,
            recovery_claim=recovery_claim,
        )
        reacquired = await current_authority.acquire(
            ResourceLockAcquireRequest(
                lock_key=binding.leases[0].lock_key,
                owner=new_owner,
                acquisition_id="acq:new-operation",
                requested_at=NOW + timedelta(seconds=10),
            )
        )
        assert reacquired.status is ResourceLockAcquireStatus.ACQUIRED
        assert reacquired.lease is not None
        assert reacquired.lease.owner == new_owner

    asyncio.run(scenario())

def test_probe_evidence_for_different_operation_cannot_authorize_reclaim() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        first_claim = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
        )
        resource_store = InMemoryDurableResourceRecoveryStore(claim_authority=claims)
        evidence_store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        handle, binding = await _setup_bound_tool(
            claims=claims,
            claim=first_claim,
            resource_store=resource_store,
            evidence_store=evidence_store,
        )
        recovery_claim = await _takeover_and_orphan(
            claims=claims,
            evidence_store=evidence_store,
        )
        probe = StaticProbe(
            OperationRecoveryStatus.STOPPED_CONFIRMED,
            returned_operation_handle_id="different-operation",
        )
        coordinator = ToolResourceRecoveryCoordinator(
            claim_authority=claims,
            lock_store=resource_store,
            binding_store=resource_store,
            inflight_store=evidence_store,
            operation_probe=probe,
        )

        decision = await coordinator.recover(
            operation_handle_id=handle.operation_handle_id,
            recovery_claim=recovery_claim,
            recovered_at=NOW + timedelta(seconds=9),
        )

        assert decision.status is ResourceRecoveryStatus.RETAINED
        assert decision.reason_codes == ("RESOURCE_RECONCILIATION_REQUIRED",)
        assert decision.operation_recovery is not None
        assert decision.operation_recovery.status is OperationRecoveryStatus.UNKNOWN
        assert decision.operation_recovery.reason_codes == (
            "OPERATION_RECOVERY_PROBE_IDENTITY_MISMATCH",
        )
        for lease in binding.leases:
            read = await resource_store.read_by_acquisition(lease.acquisition_id)
            assert read.status is DurableResourceLockReadStatus.ACTIVE

    asyncio.run(scenario())


def test_durable_provider_fence_survives_second_recovery_takeover() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        first_claim = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
        )
        resource_store = InMemoryDurableResourceRecoveryStore(claim_authority=claims)
        evidence_store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        handle, binding = await _setup_bound_tool(
            claims=claims,
            claim=first_claim,
            resource_store=resource_store,
            evidence_store=evidence_store,
        )
        second_claim = await _takeover_and_orphan(
            claims=claims,
            evidence_store=evidence_store,
        )

        fence = ProviderFenceEvidence(
            operation_handle_id=handle.operation_handle_id,
            fencing_token="fence:2:tool-handle-001",
            established_at=NOW + timedelta(seconds=6),
            recovery_epoch=second_claim.recovery_epoch,
        )
        persisted = await resource_store.record_provider_fence(
            binding,
            evidence=fence,
            recorded_at=NOW + timedelta(seconds=6),
            required_claim=second_claim,
        )
        assert persisted.status is ProviderFencePersistenceStatus.RECORDED

        third_claim = await _claim(
            claims,
            claim_id="claim-003",
            owner="worker-c",
            expected_epoch=2,
            at=NOW + timedelta(seconds=7),
        )
        coordinator = ToolResourceRecoveryCoordinator(
            claim_authority=claims,
            lock_store=resource_store,
            binding_store=resource_store,
            inflight_store=evidence_store,
        )
        decision = await coordinator.recover(
            operation_handle_id=handle.operation_handle_id,
            recovery_claim=third_claim,
            recovered_at=NOW + timedelta(seconds=9),
        )

        assert decision.status is ResourceRecoveryStatus.RECLAIMED
        assert decision.reason_codes[0] == "DURABLE_PROVIDER_FENCE"
        assert decision.provider_fence == fence
        binding_read = await resource_store.read(handle.operation_handle_id)
        assert binding_read.status is DurableOperationResourceBindingReadStatus.RELEASED
        assert binding_read.record is not None
        assert binding_read.record.provider_fence == fence

    asyncio.run(scenario())

def test_inflight_store_exception_retains_known_binding_leases() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        first_claim = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
        )
        resource_store = InMemoryDurableResourceRecoveryStore(claim_authority=claims)
        setup_evidence = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        handle, binding = await _setup_bound_tool(
            claims=claims,
            claim=first_claim,
            resource_store=resource_store,
            evidence_store=setup_evidence,
        )
        recovery_claim = await _takeover_and_orphan(
            claims=claims,
            evidence_store=setup_evidence,
        )
        faulting_evidence = FaultingInflightEvidenceStore(claim_authority=claims)
        coordinator = ToolResourceRecoveryCoordinator(
            claim_authority=claims,
            lock_store=resource_store,
            binding_store=resource_store,
            inflight_store=faulting_evidence,
        )

        decision = await coordinator.recover(
            operation_handle_id=handle.operation_handle_id,
            recovery_claim=recovery_claim,
            recovered_at=NOW + timedelta(seconds=9),
        )

        assert decision.status is ResourceRecoveryStatus.RETAINED
        assert decision.reason_codes == (
            "RESOURCE_RECOVERY_INFLIGHT_READ_EXCEPTION",
        )
        assert decision.retained_leases == binding.leases

    asyncio.run(scenario())


def test_single_lock_release_exception_is_typed_partial_reclaim_unknown() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        first_claim = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
        )
        resource_store = FailingReleaseResourceStore(
            claim_authority=claims,
            fail_acquisition_id="acq:tool-handle-001:1",
        )
        evidence_store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        handle, binding = await _setup_bound_tool(
            claims=claims,
            claim=first_claim,
            resource_store=resource_store,
            evidence_store=evidence_store,
            lock_keys=("resource:A", "resource:B"),
        )
        recovery_claim = await _takeover_and_orphan(
            claims=claims,
            evidence_store=evidence_store,
        )
        coordinator = ToolResourceRecoveryCoordinator(
            claim_authority=claims,
            lock_store=resource_store,
            binding_store=resource_store,
            inflight_store=evidence_store,
            operation_probe=StaticProbe(OperationRecoveryStatus.STOPPED_CONFIRMED),
        )

        decision = await coordinator.recover(
            operation_handle_id=handle.operation_handle_id,
            recovery_claim=recovery_claim,
            recovered_at=NOW + timedelta(seconds=9),
        )

        assert decision.status is ResourceRecoveryStatus.UNKNOWN
        assert decision.reason_codes == ("RESOURCE_RECLAIM_RELEASE_UNCERTAIN",)
        assert decision.retained_leases == (binding.leases[0],)
        assert decision.released_leases == (binding.leases[1],)

        first_read = await resource_store.read_by_acquisition(
            binding.leases[0].acquisition_id
        )
        second_read = await resource_store.read_by_acquisition(
            binding.leases[1].acquisition_id
        )
        assert first_read.status is DurableResourceLockReadStatus.ACTIVE
        assert second_read.status is DurableResourceLockReadStatus.RELEASED

        binding_read = await resource_store.read(handle.operation_handle_id)
        assert binding_read.status is DurableOperationResourceBindingReadStatus.ACTIVE

    asyncio.run(scenario())

