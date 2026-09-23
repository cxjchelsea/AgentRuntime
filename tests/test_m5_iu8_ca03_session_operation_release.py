"""CA-M5-IU8-03 session lock and operation-bound release gates."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from runtime.contracts.execution import ExecutionContext
from runtime.execution.control_application import (
    HierarchicalInterruptStatus,
    HierarchicalInterruptSummary,
    InFlightOperationHandle,
    InFlightOperationKind,
    InterruptOutcome,
    InterruptOutcomeStatus,
)
from runtime.execution.foundation import PreparedExecution, StepLifecycleSnapshot
from runtime.execution.models import ExecutionRecord, StepExecutionStatus
from runtime.execution.resource_lock import (
    InMemoryResourceLockAuthority,
    ResourceLockAcquireRequest,
    ResourceLockAcquireStatus,
    ResourceLockLease,
    ResourceLockOwner,
    ResourceLockReleaseDecision,
    ResourceLockReleaseStatus,
)
from runtime.execution.resource_lock_lifecycle import (
    InMemoryOperationResourceLeaseRegistry,
    OperationResourceLeaseBinding,
    OperationResourceReleaseCoordinator,
    OperationResourceReleaseStatus,
    SessionExecutionAcquireStatus,
    SessionExecutionLockCoordinator,
    SessionExecutionReleaseStatus,
    Sha256SessionExecutionLockIdentityFactory,
)

NOW = datetime(2026, 9, 23, 9, 0, tzinfo=UTC)


def _context(
    *,
    execution_id: str = "execution-001",
    session_id: str = "session-001",
) -> ExecutionContext:
    return ExecutionContext(
        execution_id=execution_id,
        plan_id="plan-001",
        request_id="request-001",
        session_id=session_id,
        identity_scope="subject-001",
        policy_snapshot={"policy": "snapshot"},
    )


def _prepared(
    *,
    execution_id: str = "execution-001",
    session_id: str = "session-001",
    execution_status: str = "RUNNING",
    step_status: StepExecutionStatus = StepExecutionStatus.RUNNING,
    terminal: bool = False,
) -> PreparedExecution:
    context = _context(execution_id=execution_id, session_id=session_id)
    finished_at = NOW + timedelta(seconds=20) if terminal else None
    step_finished_at = NOW + timedelta(seconds=15) if terminal else None
    step = StepLifecycleSnapshot(
        step_execution_id="step-exec-001",
        step_id="step-001",
        action="ACTION_A",
        status=step_status,
        started_at=NOW + timedelta(seconds=1),
        finished_at=step_finished_at,
    )
    record = ExecutionRecord(
        execution_id=execution_id,
        plan_id="plan-001",
        request_id="request-001",
        identity_scope="subject-001",
        status=execution_status,
        current_step=None if terminal else "step-001",
        created_at=NOW,
        updated_at=finished_at or (NOW + timedelta(seconds=2)),
    )
    return PreparedExecution(
        execution_context=context,
        execution_record=record,
        steps=(step,),
        started_at=NOW,
        finished_at=finished_at,
    )


def _session_coordinator(
    authority: InMemoryResourceLockAuthority | object,
) -> SessionExecutionLockCoordinator:
    return SessionExecutionLockCoordinator(
        authority=authority,  # type: ignore[arg-type]
        identity_factory=Sha256SessionExecutionLockIdentityFactory(),
    )


def _tool_owner(
    *,
    execution_id: str = "execution-001",
    step_execution_id: str = "step-exec-001",
    tool_call_id: str = "tool-call-001",
    physical_attempt: int = 1,
) -> ResourceLockOwner:
    return ResourceLockOwner(
        owner_id=(
            f"{execution_id}:{step_execution_id}:{tool_call_id}:"
            f"attempt-{physical_attempt}"
        ),
        execution_id=execution_id,
        step_execution_id=step_execution_id,
        tool_call_id=tool_call_id,
        physical_attempt=physical_attempt,
    )


def _tool_handle(
    *,
    operation_handle_id: str = "tool-handle-001",
    execution_id: str = "execution-001",
    step_execution_id: str = "step-exec-001",
    tool_call_id: str = "tool-call-001",
) -> InFlightOperationHandle:
    return InFlightOperationHandle(
        operation_handle_id=operation_handle_id,
        execution_id=execution_id,
        step_execution_id=step_execution_id,
        kind=InFlightOperationKind.TOOL,
        capability_id="TOOL_A",
        capability_version="1.0.0",
        started_at=NOW + timedelta(seconds=2),
        parent_handle_id="owner-handle-001",
        tool_call_id=tool_call_id,
    )


def _owner_handle() -> InFlightOperationHandle:
    return InFlightOperationHandle(
        operation_handle_id="owner-handle-001",
        execution_id="execution-001",
        step_execution_id="step-exec-001",
        kind=InFlightOperationKind.SKILL,
        capability_id="SKILL_A",
        capability_version="1.0.0",
        started_at=NOW + timedelta(seconds=1),
    )


async def _acquire_tool_lease(
    authority: InMemoryResourceLockAuthority,
    *,
    lock_key: str,
    acquisition_id: str,
    owner: ResourceLockOwner,
) -> ResourceLockLease:
    decision = await authority.acquire(
        ResourceLockAcquireRequest(
            lock_key=lock_key,
            owner=owner,
            acquisition_id=acquisition_id,
            requested_at=NOW + timedelta(seconds=2),
        )
    )
    assert decision.status is ResourceLockAcquireStatus.ACQUIRED
    assert decision.lease is not None
    return decision.lease


def _interrupt_summary(
    *,
    tool_status: InterruptOutcomeStatus,
) -> HierarchicalInterruptSummary:
    tool = _tool_handle()
    owner = _owner_handle()
    return HierarchicalInterruptSummary(
        execution_id="execution-001",
        step_execution_id="step-exec-001",
        status=HierarchicalInterruptStatus.ORDERED,
        handles=(tool, owner),
        outcomes=(
            InterruptOutcome(
                operation_handle_id=tool.operation_handle_id,
                status=tool_status,
                reason_codes=("TOOL_INTERRUPT_OBSERVED",),
            ),
            InterruptOutcome(
                operation_handle_id=owner.operation_handle_id,
                status=InterruptOutcomeStatus.CONFIRMED_STOPPED,
                reason_codes=("OWNER_STOPPED",),
            ),
        ),
        reason_codes=("INTERRUPT_CHAIN_OBSERVED",),
    )


def test_same_session_second_execution_is_busy_without_preemption() -> None:
    authority = InMemoryResourceLockAuthority()
    coordinator = _session_coordinator(authority)

    first = asyncio.run(
        coordinator.acquire(
            execution_context=_context(execution_id="execution-001"),
            requested_at=NOW,
        )
    )
    second = asyncio.run(
        coordinator.acquire(
            execution_context=_context(execution_id="execution-002"),
            requested_at=NOW + timedelta(seconds=1),
        )
    )

    assert first.status is SessionExecutionAcquireStatus.ACQUIRED
    assert second.status is SessionExecutionAcquireStatus.BUSY
    assert second.session_lease is None


def test_same_execution_session_lock_exact_replay_is_idempotent() -> None:
    authority = InMemoryResourceLockAuthority()
    coordinator = _session_coordinator(authority)
    context = _context()

    first = asyncio.run(coordinator.acquire(execution_context=context, requested_at=NOW))
    replay = asyncio.run(
        coordinator.acquire(
            execution_context=context,
            requested_at=NOW + timedelta(seconds=1),
        )
    )

    assert first.status is SessionExecutionAcquireStatus.ACQUIRED
    assert replay.status is SessionExecutionAcquireStatus.ALREADY_ACQUIRED
    assert replay.session_lease == first.session_lease


def test_different_sessions_do_not_share_session_execution_lock() -> None:
    authority = InMemoryResourceLockAuthority()
    coordinator = _session_coordinator(authority)

    first = asyncio.run(
        coordinator.acquire(
            execution_context=_context(
                execution_id="execution-001",
                session_id="session-001",
            ),
            requested_at=NOW,
        )
    )
    second = asyncio.run(
        coordinator.acquire(
            execution_context=_context(
                execution_id="execution-002",
                session_id="session-002",
            ),
            requested_at=NOW,
        )
    )

    assert first.status is SessionExecutionAcquireStatus.ACQUIRED
    assert second.status is SessionExecutionAcquireStatus.ACQUIRED
    assert first.session_lease is not None
    assert second.session_lease is not None
    assert first.session_lease.lease.lock_key != second.session_lease.lease.lock_key


def test_session_lock_is_retained_while_execution_is_running() -> None:
    authority = InMemoryResourceLockAuthority()
    coordinator = _session_coordinator(authority)
    acquired = asyncio.run(
        coordinator.acquire(execution_context=_context(), requested_at=NOW)
    )
    assert acquired.session_lease is not None

    decision = asyncio.run(
        coordinator.release_if_terminal(
            prepared=_prepared(),
            session_lease=acquired.session_lease,
            released_at=NOW + timedelta(seconds=10),
        )
    )

    assert decision.status is SessionExecutionReleaseStatus.RETAINED
    assert authority.active_lease(acquired.session_lease.lease.lock_key) is not None


def test_session_lock_releases_only_after_authoritative_terminal_execution() -> None:
    authority = InMemoryResourceLockAuthority()
    coordinator = _session_coordinator(authority)
    acquired = asyncio.run(
        coordinator.acquire(execution_context=_context(), requested_at=NOW)
    )
    assert acquired.session_lease is not None
    prepared = _prepared(
        execution_status="SUCCESS",
        step_status=StepExecutionStatus.SUCCESS,
        terminal=True,
    )

    decision = asyncio.run(
        coordinator.release_if_terminal(
            prepared=prepared,
            session_lease=acquired.session_lease,
            released_at=NOW + timedelta(seconds=21),
        )
    )

    assert decision.status is SessionExecutionReleaseStatus.RELEASED
    assert authority.active_lease(acquired.session_lease.lease.lock_key) is None


def test_terminal_execution_status_with_nonterminal_step_does_not_release_session() -> None:
    authority = InMemoryResourceLockAuthority()
    coordinator = _session_coordinator(authority)
    acquired = asyncio.run(
        coordinator.acquire(execution_context=_context(), requested_at=NOW)
    )
    assert acquired.session_lease is not None
    prepared = _prepared(
        execution_status="SUCCESS",
        step_status=StepExecutionStatus.RUNNING,
        terminal=True,
    )

    decision = asyncio.run(
        coordinator.release_if_terminal(
            prepared=prepared,
            session_lease=acquired.session_lease,
            released_at=NOW + timedelta(seconds=21),
        )
    )

    assert decision.status is SessionExecutionReleaseStatus.RETAINED


def test_forged_session_lease_identity_cannot_release_resource() -> None:
    authority = InMemoryResourceLockAuthority()
    coordinator = _session_coordinator(authority)
    acquired = asyncio.run(
        coordinator.acquire(execution_context=_context(), requested_at=NOW)
    )
    assert acquired.session_lease is not None
    forged = replace(
        acquired.session_lease,
        lease=replace(
            acquired.session_lease.lease,
            lock_key="other-resource-lock",
        ),
    )

    decision = asyncio.run(
        coordinator.release_if_terminal(
            prepared=_prepared(
                execution_status="SUCCESS",
                step_status=StepExecutionStatus.SUCCESS,
                terminal=True,
            ),
            session_lease=forged,
            released_at=NOW + timedelta(seconds=21),
        )
    )

    assert decision.status is SessionExecutionReleaseStatus.UNKNOWN
    assert decision.reason_codes == ("SESSION_LEASE_LOCK_KEY_MISMATCH",)
    assert authority.active_lease(acquired.session_lease.lease.lock_key) is not None


def test_operation_binding_requires_exact_tool_provenance() -> None:
    owner = _tool_owner()
    lease = ResourceLockLease(
        lock_key="resource-001",
        owner=owner,
        acquisition_id="acq-001",
        acquired_at=NOW + timedelta(seconds=2),
    )

    with pytest.raises(ValueError, match="tool_call_id mismatch"):
        OperationResourceLeaseBinding(
            handle=_tool_handle(tool_call_id="tool-call-other"),
            owner=owner,
            leases=(lease,),
        )


def test_operation_binding_rejects_lease_acquired_after_operation_start() -> None:
    owner = _tool_owner()
    handle = _tool_handle()

    with pytest.raises(ValueError, match="acquired before operation start"):
        OperationResourceLeaseBinding(
            handle=handle,
            owner=owner,
            leases=(
                ResourceLockLease(
                    lock_key="resource-001",
                    owner=owner,
                    acquisition_id="acq-001",
                    acquired_at=handle.started_at + timedelta(seconds=1),
                ),
            ),
        )


def test_operation_binding_registry_rejects_rebinding() -> None:
    registry = InMemoryOperationResourceLeaseRegistry()
    owner = _tool_owner()
    handle = _tool_handle()
    first = OperationResourceLeaseBinding(
        handle=handle,
        owner=owner,
        leases=(
            ResourceLockLease(
                lock_key="resource-001",
                owner=owner,
                acquisition_id="acq-001",
                acquired_at=NOW + timedelta(seconds=2),
            ),
        ),
    )
    second = replace(
        first,
        leases=(
            replace(first.leases[0], lock_key="resource-002"),
        ),
    )

    assert asyncio.run(registry.register(first)) is True
    with pytest.raises(ValueError, match="cannot be rebound"):
        asyncio.run(registry.register(second))


def test_normal_completion_releases_exact_operation_resources() -> None:
    authority = InMemoryResourceLockAuthority()
    registry = InMemoryOperationResourceLeaseRegistry()
    coordinator = OperationResourceReleaseCoordinator(
        authority=authority,
        registry=registry,
    )
    owner = _tool_owner()
    handle = _tool_handle()
    lease = asyncio.run(
        _acquire_tool_lease(
            authority,
            lock_key="resource-001",
            acquisition_id="acq-001",
            owner=owner,
        )
    )
    binding = OperationResourceLeaseBinding(
        handle=handle,
        owner=owner,
        leases=(lease,),
    )
    asyncio.run(coordinator.bind(binding))

    decision = asyncio.run(
        coordinator.release_after_completion(
            binding=binding,
            completed_handle=handle,
            completed_at=NOW + timedelta(seconds=10),
        )
    )

    assert decision.status is OperationResourceReleaseStatus.RELEASED
    assert decision.released_leases == (lease,)
    assert authority.active_lease("resource-001") is None
    assert asyncio.run(registry.get(handle.operation_handle_id)) is None


def test_completion_identity_mismatch_retains_resource() -> None:
    authority = InMemoryResourceLockAuthority()
    registry = InMemoryOperationResourceLeaseRegistry()
    coordinator = OperationResourceReleaseCoordinator(
        authority=authority,
        registry=registry,
    )
    owner = _tool_owner()
    handle = _tool_handle()
    lease = asyncio.run(
        _acquire_tool_lease(
            authority,
            lock_key="resource-001",
            acquisition_id="acq-001",
            owner=owner,
        )
    )
    binding = OperationResourceLeaseBinding(handle=handle, owner=owner, leases=(lease,))
    asyncio.run(coordinator.bind(binding))

    decision = asyncio.run(
        coordinator.release_after_completion(
            binding=binding,
            completed_handle=replace(handle, operation_handle_id="other-handle"),
            completed_at=NOW + timedelta(seconds=10),
        )
    )

    assert decision.status is OperationResourceReleaseStatus.UNKNOWN
    assert decision.retained_leases == (lease,)
    assert authority.active_lease("resource-001") == lease


def test_interrupt_confirmed_stopped_releases_tool_resources() -> None:
    authority = InMemoryResourceLockAuthority()
    registry = InMemoryOperationResourceLeaseRegistry()
    coordinator = OperationResourceReleaseCoordinator(
        authority=authority,
        registry=registry,
    )
    owner = _tool_owner()
    handle = _tool_handle()
    lease = asyncio.run(
        _acquire_tool_lease(
            authority,
            lock_key="resource-001",
            acquisition_id="acq-001",
            owner=owner,
        )
    )
    binding = OperationResourceLeaseBinding(handle=handle, owner=owner, leases=(lease,))
    asyncio.run(coordinator.bind(binding))

    decision = asyncio.run(
        coordinator.release_after_interrupt(
            binding=binding,
            interrupt_summary=_interrupt_summary(
                tool_status=InterruptOutcomeStatus.CONFIRMED_STOPPED
            ),
            observed_at=NOW + timedelta(seconds=10),
        )
    )

    assert decision.status is OperationResourceReleaseStatus.RELEASED
    assert authority.active_lease("resource-001") is None


@pytest.mark.parametrize(
    ("tool_status", "reason"),
    [
        (
            InterruptOutcomeStatus.ALREADY_COMPLETED,
            "ALREADY_COMPLETED_AWAITING_REAL_COMPLETION",
        ),
        (
            InterruptOutcomeStatus.NOT_CANCELLABLE,
            "NOT_CANCELLABLE_RESOURCE_RETAINED",
        ),
        (
            InterruptOutcomeStatus.UNKNOWN,
            "INTERRUPT_UNKNOWN_RESOURCE_RETAINED",
        ),
    ],
)
def test_unproven_interrupt_outcomes_retain_resource(
    tool_status: InterruptOutcomeStatus,
    reason: str,
) -> None:
    authority = InMemoryResourceLockAuthority()
    registry = InMemoryOperationResourceLeaseRegistry()
    coordinator = OperationResourceReleaseCoordinator(
        authority=authority,
        registry=registry,
    )
    owner = _tool_owner()
    handle = _tool_handle()
    lease = asyncio.run(
        _acquire_tool_lease(
            authority,
            lock_key="resource-001",
            acquisition_id="acq-001",
            owner=owner,
        )
    )
    binding = OperationResourceLeaseBinding(handle=handle, owner=owner, leases=(lease,))
    asyncio.run(coordinator.bind(binding))

    decision = asyncio.run(
        coordinator.release_after_interrupt(
            binding=binding,
            interrupt_summary=_interrupt_summary(tool_status=tool_status),
            observed_at=NOW + timedelta(seconds=10),
        )
    )

    assert decision.status is OperationResourceReleaseStatus.RETAINED
    assert decision.reason_codes == (reason,)
    assert decision.retained_leases == (lease,)
    assert authority.active_lease("resource-001") == lease


def test_ambiguous_interrupt_summary_cannot_release_resource() -> None:
    authority = InMemoryResourceLockAuthority()
    registry = InMemoryOperationResourceLeaseRegistry()
    coordinator = OperationResourceReleaseCoordinator(
        authority=authority,
        registry=registry,
    )
    owner = _tool_owner()
    handle = _tool_handle()
    lease = asyncio.run(
        _acquire_tool_lease(
            authority,
            lock_key="resource-001",
            acquisition_id="acq-001",
            owner=owner,
        )
    )
    binding = OperationResourceLeaseBinding(handle=handle, owner=owner, leases=(lease,))
    asyncio.run(coordinator.bind(binding))
    summary = HierarchicalInterruptSummary(
        execution_id="execution-001",
        step_execution_id="step-exec-001",
        status=HierarchicalInterruptStatus.AMBIGUOUS,
        handles=(handle,),
        outcomes=(),
        reason_codes=("AMBIGUOUS_INFLIGHT_GRAPH",),
    )

    decision = asyncio.run(
        coordinator.release_after_interrupt(
            binding=binding,
            interrupt_summary=summary,
            observed_at=NOW + timedelta(seconds=10),
        )
    )

    assert decision.status is OperationResourceReleaseStatus.UNKNOWN
    assert decision.retained_leases == (lease,)
    assert authority.active_lease("resource-001") == lease


def test_partial_release_uncertainty_keeps_binding_for_safe_retry() -> None:
    class PartialReleaseAuthority:
        def __init__(self) -> None:
            self.released: list[str] = []

        async def release(
            self,
            lease: ResourceLockLease,
            *,
            released_at: datetime,
        ) -> ResourceLockReleaseDecision:
            del released_at
            if lease.lock_key == "resource-002":
                return ResourceLockReleaseDecision(
                    status=ResourceLockReleaseStatus.UNKNOWN,
                    reason_codes=("RELEASE_UNKNOWN",),
                    lease=lease,
                )
            self.released.append(lease.lock_key)
            return ResourceLockReleaseDecision(
                status=ResourceLockReleaseStatus.RELEASED,
                reason_codes=("LOCK_RELEASED",),
                lease=lease,
            )

    authority = PartialReleaseAuthority()
    registry = InMemoryOperationResourceLeaseRegistry()
    coordinator = OperationResourceReleaseCoordinator(
        authority=authority,  # type: ignore[arg-type]
        registry=registry,
    )
    owner = _tool_owner()
    handle = _tool_handle()
    leases = (
        ResourceLockLease(
            lock_key="resource-001",
            owner=owner,
            acquisition_id="acq-001",
            acquired_at=NOW + timedelta(seconds=2),
        ),
        ResourceLockLease(
            lock_key="resource-002",
            owner=owner,
            acquisition_id="acq-002",
            acquired_at=NOW + timedelta(seconds=2),
        ),
    )
    binding = OperationResourceLeaseBinding(handle=handle, owner=owner, leases=leases)
    asyncio.run(coordinator.bind(binding))

    decision = asyncio.run(
        coordinator.release_after_completion(
            binding=binding,
            completed_handle=handle,
            completed_at=NOW + timedelta(seconds=10),
        )
    )

    assert decision.status is OperationResourceReleaseStatus.UNKNOWN
    assert tuple(item.lock_key for item in decision.released_leases) == ("resource-001",)
    assert tuple(item.lock_key for item in decision.retained_leases) == ("resource-002",)
    assert asyncio.run(registry.get(handle.operation_handle_id)) == binding


def test_release_requires_active_exact_operation_binding() -> None:
    authority = InMemoryResourceLockAuthority()
    registry = InMemoryOperationResourceLeaseRegistry()
    coordinator = OperationResourceReleaseCoordinator(
        authority=authority,
        registry=registry,
    )
    owner = _tool_owner()
    handle = _tool_handle()
    lease = asyncio.run(
        _acquire_tool_lease(
            authority,
            lock_key="resource-001",
            acquisition_id="acq-001",
            owner=owner,
        )
    )
    binding = OperationResourceLeaseBinding(handle=handle, owner=owner, leases=(lease,))

    decision = asyncio.run(
        coordinator.release_after_completion(
            binding=binding,
            completed_handle=handle,
            completed_at=NOW + timedelta(seconds=10),
        )
    )

    assert decision.status is OperationResourceReleaseStatus.UNKNOWN
    assert decision.reason_codes == ("OPERATION_RESOURCE_BINDING_NOT_ACTIVE",)
    assert authority.active_lease("resource-001") == lease
