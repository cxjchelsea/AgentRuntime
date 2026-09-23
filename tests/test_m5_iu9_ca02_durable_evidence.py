"""CA-M5-IU9-02 durable reliability/control/in-flight evidence tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from runtime.execution.control import (
    ExecutionControlLatchStatus,
    ExecutionControlSignal,
    ExecutionControlSignalType,
    ObservedExecutionControl,
)
from runtime.execution.control_application import (
    InFlightOperationHandle,
    InFlightOperationKind,
)
from runtime.execution.invocation import ToolInvocationJournalEntry
from runtime.execution.models import M5ToolResult, ToolExecutionStatus
from runtime.execution.recovery import (
    ExecutionRecoveryClaim,
    InMemoryRecoveryClaimAuthority,
    RecoveryClaimRequest,
    RecoveryClaimStatus,
)
from runtime.execution.recovery_evidence import (
    DurableControlReadDecision,
    DurableControlReadStatus,
    DurableEvidenceMutationStatus,
    DurableExecutionControlLatch,
    DurableInFlightOperationRegistry,
    DurableStepAttemptSequenceAuthority,
    DurableToolJournalEvidence,
    DurableToolOperationOccurrenceAuthority,
    InFlightEvidenceState,
    InFlightRecoveryTransitionStatus,
    InMemoryDurableRecoveryEvidenceStore,
    ToolJournalWriteStatus,
)
from runtime.execution.reliability_boundary import (
    StepAttemptSequenceStatus,
    ToolOperationOccurrenceStatus,
)

NOW = datetime(2026, 9, 23, 11, 0, tzinfo=UTC)


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


def _journal_entry(
    *,
    tool_call_id: str = "tool-call-001",
    tool_id: str = "tool-A",
    operation_key: str = "operation-001",
    fingerprint: str = "sha256:abc",
) -> ToolInvocationJournalEntry:
    result = M5ToolResult(
        tool_call_id=tool_call_id,
        tool_id=tool_id,
        status=ToolExecutionStatus.SUCCESS,
        data={"ok": True},
        attempt=1,
    )
    return ToolInvocationJournalEntry(
        tool_call_id=tool_call_id,
        tool_id=tool_id,
        tool_version="v1",
        result=result,
        operation_key=operation_key,
        operation_fingerprint=fingerprint,
        idempotency_key=f"idem:{operation_key}",
    )


def _control(
    *,
    signal_id: str = "signal-001",
    reason: str = "USER_CANCELLED",
    issued_at: datetime = NOW,
) -> ObservedExecutionControl:
    return ObservedExecutionControl(
        signal=ExecutionControlSignal(
            signal_type=ExecutionControlSignalType.CANCEL,
            reason_code=reason,
            source="runtime",
            signal_id=signal_id,
            target_execution_id="execution-001",
            issued_at=issued_at,
        ),
        observed_at=issued_at + timedelta(seconds=1),
    )


def _owner_handle(
    *,
    handle_id: str = "owner-handle-001",
    capability_id: str = "skill-A",
) -> InFlightOperationHandle:
    return InFlightOperationHandle(
        operation_handle_id=handle_id,
        execution_id="execution-001",
        step_execution_id="step-exec-001",
        kind=InFlightOperationKind.SKILL,
        capability_id=capability_id,
        capability_version="v1",
        started_at=NOW + timedelta(seconds=1),
    )


def _tool_handle(
    *,
    handle_id: str = "tool-handle-001",
    parent_id: str = "owner-handle-001",
) -> InFlightOperationHandle:
    return InFlightOperationHandle(
        operation_handle_id=handle_id,
        execution_id="execution-001",
        step_execution_id="step-exec-001",
        kind=InFlightOperationKind.TOOL,
        capability_id="tool-A",
        capability_version="v1",
        started_at=NOW + timedelta(seconds=2),
        parent_handle_id=parent_id,
        tool_call_id="tool-call-001",
    )


def test_step_attempt_cursor_survives_authority_recreation() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        claim = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
        )
        store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        first = DurableStepAttemptSequenceAuthority(
            store=store,
            execution_id="execution-001",
            recovery_claim=claim,
            clock=lambda: NOW + timedelta(seconds=2),
        )

        baseline = await first.ensure_baseline(step_execution_id="step-exec-001")
        assert baseline.status is DurableEvidenceMutationStatus.RECORDED
        assert await first.current_attempt("step-exec-001") == 1

        retry = await first.claim_next(
            step_execution_id="step-exec-001",
            expected_current_attempt=1,
        )
        assert retry.status is StepAttemptSequenceStatus.CLAIMED
        assert retry.next_attempt == 2
        assert retry.claim_token is not None
        assert "attempt:2" in retry.claim_token

        recreated = DurableStepAttemptSequenceAuthority(
            store=store,
            execution_id="execution-001",
            recovery_claim=claim,
            clock=lambda: NOW + timedelta(seconds=3),
        )
        assert await recreated.current_attempt("step-exec-001") == 2
        second_retry = await recreated.claim_next(
            step_execution_id="step-exec-001",
            expected_current_attempt=2,
        )
        assert second_retry.status is StepAttemptSequenceStatus.CLAIMED
        assert second_retry.next_attempt == 3

    asyncio.run(scenario())


def test_stale_recovery_epoch_cannot_advance_reliability_evidence() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        first_claim = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
        )
        store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        step = DurableStepAttemptSequenceAuthority(
            store=store,
            execution_id="execution-001",
            recovery_claim=first_claim,
            clock=lambda: NOW + timedelta(seconds=1),
        )
        await step.ensure_baseline(step_execution_id="step-exec-001")

        second_claim = await _claim(
            claims,
            claim_id="claim-002",
            owner="worker-b",
            expected_epoch=1,
            at=NOW + timedelta(seconds=2),
        )
        assert second_claim.recovery_epoch == 2

        stale_retry = await step.claim_next(
            step_execution_id="step-exec-001",
            expected_current_attempt=1,
        )
        assert stale_retry.status is StepAttemptSequenceStatus.CONFLICT
        assert stale_retry.reason_codes == ("STEP_ATTEMPT_STALE_RECOVERY_EPOCH",)

        stale_occurrence = DurableToolOperationOccurrenceAuthority(
            store=store,
            execution_id="execution-001",
            recovery_claim=first_claim,
            clock=lambda: NOW + timedelta(seconds=3),
        )
        occurrence = await stale_occurrence.claim_next(
            step_execution_id="step-exec-001",
            step_attempt_number=1,
            tool_id="tool-A",
            tool_version="v1",
            operation_fingerprint="sha256:abc",
        )
        assert occurrence.status is ToolOperationOccurrenceStatus.UNKNOWN
        assert occurrence.reason_codes == (
            "TOOL_OCCURRENCE_RECOVERY_EPOCH_NOT_CURRENT",
        )

        stale_journal = DurableToolJournalEvidence(
            store=store,
            execution_id="execution-001",
            recovery_claim=first_claim,
            clock=lambda: NOW + timedelta(seconds=4),
        )
        journal_write = await stale_journal.append(
            step_execution_id="step-exec-001",
            step_attempt_number=1,
            expected_current_length=0,
            entry=_journal_entry(),
        )
        assert journal_write.status is ToolJournalWriteStatus.CONFLICT
        assert journal_write.reason_codes == ("TOOL_JOURNAL_STALE_RECOVERY_EPOCH",)

    asyncio.run(scenario())


def test_tool_occurrence_cursor_survives_restart_and_is_exactly_scoped() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        claim = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
        )
        store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)

        first = DurableToolOperationOccurrenceAuthority(
            store=store,
            execution_id="execution-001",
            recovery_claim=claim,
            clock=lambda: NOW + timedelta(seconds=1),
        )
        one = await first.claim_next(
            step_execution_id="step-exec-001",
            step_attempt_number=1,
            tool_id="tool-A",
            tool_version="v1",
            operation_fingerprint="sha256:abc",
        )
        two = await first.claim_next(
            step_execution_id="step-exec-001",
            step_attempt_number=1,
            tool_id="tool-A",
            tool_version="v1",
            operation_fingerprint="sha256:abc",
        )
        assert (one.occurrence, two.occurrence) == (1, 2)

        recreated = DurableToolOperationOccurrenceAuthority(
            store=store,
            execution_id="execution-001",
            recovery_claim=claim,
            clock=lambda: NOW + timedelta(seconds=2),
        )
        three = await recreated.claim_next(
            step_execution_id="step-exec-001",
            step_attempt_number=1,
            tool_id="tool-A",
            tool_version="v1",
            operation_fingerprint="sha256:abc",
        )
        new_attempt = await recreated.claim_next(
            step_execution_id="step-exec-001",
            step_attempt_number=2,
            tool_id="tool-A",
            tool_version="v1",
            operation_fingerprint="sha256:abc",
        )
        different_fingerprint = await recreated.claim_next(
            step_execution_id="step-exec-001",
            step_attempt_number=1,
            tool_id="tool-A",
            tool_version="v1",
            operation_fingerprint="sha256:def",
        )
        assert three.occurrence == 3
        assert new_attempt.occurrence == 1
        assert different_fingerprint.occurrence == 1

    asyncio.run(scenario())


def test_tool_journal_is_monotonic_replayable_and_restart_readable() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        claim = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
        )
        store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        first = DurableToolJournalEvidence(
            store=store,
            execution_id="execution-001",
            recovery_claim=claim,
            clock=lambda: NOW + timedelta(seconds=1),
        )
        entry1 = _journal_entry()

        appended = await first.append(
            step_execution_id="step-exec-001",
            step_attempt_number=1,
            expected_current_length=0,
            entry=entry1,
        )
        replay = await first.append(
            step_execution_id="step-exec-001",
            step_attempt_number=1,
            expected_current_length=0,
            entry=entry1,
        )
        assert appended.status is ToolJournalWriteStatus.APPENDED
        assert replay.status is ToolJournalWriteStatus.ALREADY_CURRENT

        entry2 = _journal_entry(
            tool_call_id="tool-call-002",
            operation_key="operation-002",
            fingerprint="sha256:def",
        )
        second = await first.append(
            step_execution_id="step-exec-001",
            step_attempt_number=1,
            expected_current_length=1,
            entry=entry2,
        )
        assert second.status is ToolJournalWriteStatus.APPENDED
        assert second.entry_index == 2

        recreated = DurableToolJournalEvidence(
            store=store,
            execution_id="execution-001",
            recovery_claim=claim,
        )
        loaded = await recreated.load(
            step_execution_id="step-exec-001",
            step_attempt_number=1,
        )
        assert loaded == (entry1, entry2)

        stale_append = await recreated.append(
            step_execution_id="step-exec-001",
            step_attempt_number=1,
            expected_current_length=0,
            entry=_journal_entry(
                tool_call_id="tool-call-003",
                operation_key="operation-003",
                fingerprint="sha256:ghi",
            ),
        )
        assert stale_append.status is ToolJournalWriteStatus.CONFLICT
        assert stale_append.current_length == 2

    asyncio.run(scenario())


def test_durable_terminal_control_latch_survives_restart() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        claim = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
        )
        store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        latch = DurableExecutionControlLatch(store=store, recovery_claim=claim)
        observed = _control()

        first = await latch.latch(
            observed=observed,
            latched_at=NOW + timedelta(seconds=2),
        )
        assert first.status is ExecutionControlLatchStatus.LATCHED

        recreated = DurableExecutionControlLatch(store=store, recovery_claim=claim)
        recovered = await recreated.get_latched("execution-001")
        assert recovered == first.latched_control

        replay = await recreated.latch(
            observed=observed,
            latched_at=NOW + timedelta(seconds=10),
        )
        assert replay.status is ExecutionControlLatchStatus.ALREADY_LATCHED
        assert replay.latched_control == first.latched_control

        conflict = await recreated.latch(
            observed=_control(
                signal_id="signal-002",
                reason="ADMIN_CANCELLED",
                issued_at=NOW + timedelta(seconds=3),
            ),
            latched_at=NOW + timedelta(seconds=5),
        )
        assert conflict.status is ExecutionControlLatchStatus.CONFLICT
        assert conflict.latched_control == first.latched_control

    asyncio.run(scenario())


def test_stale_worker_cannot_latch_new_terminal_control_after_takeover() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        first_claim = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
        )
        store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        stale_latch = DurableExecutionControlLatch(
            store=store,
            recovery_claim=first_claim,
        )

        await _claim(
            claims,
            claim_id="claim-002",
            owner="worker-b",
            expected_epoch=1,
            at=NOW + timedelta(seconds=1),
        )
        decision = await stale_latch.latch(
            observed=_control(),
            latched_at=NOW + timedelta(seconds=2),
        )
        assert decision.status is ExecutionControlLatchStatus.UNKNOWN
        assert decision.reason_codes == ("CONTROL_LATCH_RECOVERY_EPOCH_NOT_CURRENT",)
        assert await stale_latch.get_latched("execution-001") is None

    asyncio.run(scenario())


def test_active_at_crash_becomes_orphaned_unconfirmed_not_stopped() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        first_claim = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
        )
        store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        live = DurableInFlightOperationRegistry(
            store=store,
            recovery_claim=first_claim,
            clock=lambda: NOW + timedelta(seconds=3),
        )
        owner = _owner_handle()
        tool = _tool_handle()
        assert await live.register(owner)
        assert await live.register(tool)

        recreated_live = DurableInFlightOperationRegistry(
            store=store,
            recovery_claim=first_claim,
        )
        active = await recreated_live.active_chain(
            execution_id="execution-001",
            step_execution_id="step-exec-001",
        )
        assert set(active) == {owner, tool}

        recovery_claim = await _claim(
            claims,
            claim_id="claim-002",
            owner="worker-b",
            expected_epoch=1,
            at=NOW + timedelta(seconds=4),
        )
        recovery = await store.recover_active_as_orphaned(
            execution_id="execution-001",
            recovered_at=NOW + timedelta(seconds=5),
            required_claim=recovery_claim,
        )
        assert recovery.status is InFlightRecoveryTransitionStatus.TRANSITIONED
        observations = recovery.observations
        assert len(observations) == 2
        assert {item.state for item in observations} == {
            InFlightEvidenceState.ORPHANED_UNCONFIRMED
        }
        assert all(item.terminal_at is None for item in observations)
        assert all(
            item.state
            not in {
                InFlightEvidenceState.COMPLETED,
                InFlightEvidenceState.CONFIRMED_STOPPED,
            }
            for item in observations
        )

        recovered_registry = DurableInFlightOperationRegistry(
            store=store,
            recovery_claim=recovery_claim,
        )
        assert (
            await recovered_registry.active_chain(
                execution_id="execution-001",
                step_execution_id="step-exec-001",
            )
            == ()
        )

    asyncio.run(scenario())


def test_completed_inflight_evidence_is_not_downgraded_to_orphaned() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        first_claim = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
        )
        store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        live = DurableInFlightOperationRegistry(
            store=store,
            recovery_claim=first_claim,
            clock=lambda: NOW + timedelta(seconds=3),
        )
        owner = _owner_handle()
        tool = _tool_handle()
        await live.register(owner)
        await live.register(tool)
        assert await live.complete(
            tool.operation_handle_id,
            completed_at=NOW + timedelta(seconds=4),
        )

        recovery_claim = await _claim(
            claims,
            claim_id="claim-002",
            owner="worker-b",
            expected_epoch=1,
            at=NOW + timedelta(seconds=5),
        )
        recovery = await store.recover_active_as_orphaned(
            execution_id="execution-001",
            recovered_at=NOW + timedelta(seconds=6),
            required_claim=recovery_claim,
        )
        assert recovery.status is InFlightRecoveryTransitionStatus.TRANSITIONED
        by_id = {
            item.handle.operation_handle_id: item
            for item in recovery.observations
        }
        assert by_id[owner.operation_handle_id].state is (
            InFlightEvidenceState.ORPHANED_UNCONFIRMED
        )
        assert by_id[tool.operation_handle_id].state is InFlightEvidenceState.COMPLETED
        assert by_id[tool.operation_handle_id].terminal_at == NOW + timedelta(seconds=4)

    asyncio.run(scenario())


def test_stale_inflight_registry_cannot_complete_after_takeover() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        first_claim = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
        )
        store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        stale = DurableInFlightOperationRegistry(
            store=store,
            recovery_claim=first_claim,
            clock=lambda: NOW + timedelta(seconds=2),
        )
        owner = _owner_handle()
        await stale.register(owner)

        await _claim(
            claims,
            claim_id="claim-002",
            owner="worker-b",
            expected_epoch=1,
            at=NOW + timedelta(seconds=3),
        )

        with pytest.raises(
            RuntimeError, match="INFLIGHT_COMPLETION_STALE_RECOVERY_EPOCH"
        ):
            await stale.complete(
                owner.operation_handle_id,
                completed_at=NOW + timedelta(seconds=4),
            )

        observations = await store.load_inflight(execution_id="execution-001")
        assert len(observations) == 1
        assert observations[0].state is InFlightEvidenceState.ACTIVE_AT_CHECKPOINT

    asyncio.run(scenario())


def test_step_retry_requires_durable_attempt_one_baseline() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        claim = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
        )
        store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        authority = DurableStepAttemptSequenceAuthority(
            store=store,
            execution_id="execution-001",
            recovery_claim=claim,
            clock=lambda: NOW + timedelta(seconds=1),
        )

        decision = await authority.claim_next(
            step_execution_id="step-exec-001",
            expected_current_attempt=1,
        )

        assert decision.status is StepAttemptSequenceStatus.CONFLICT
        assert decision.reason_codes == ("STEP_ATTEMPT_DURABLE_BASELINE_MISSING",)
        assert await authority.current_attempt("step-exec-001") is None

    asyncio.run(scenario())


def test_durable_control_unknown_read_never_becomes_no_control() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        claim = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
        )

        class UnknownControlStore:
            async def latch(
                self,
                *,
                observed,
                latched_at,
                required_claim,
            ):
                raise AssertionError("latch must not be called")

            async def read_latched(self, execution_id: str):
                assert execution_id == "execution-001"
                return DurableControlReadDecision(
                    status=DurableControlReadStatus.UNKNOWN,
                    reason_codes=("DURABLE_CONTROL_STORE_UNAVAILABLE",),
                )

        latch = DurableExecutionControlLatch(
            store=UnknownControlStore(),
            recovery_claim=claim,
        )

        with pytest.raises(RuntimeError, match="DURABLE_CONTROL_STORE_UNAVAILABLE"):
            await latch.get_latched("execution-001")

    asyncio.run(scenario())


def test_orphan_transition_stale_epoch_is_conflict_not_empty_success() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        first_claim = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
        )
        store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        registry = DurableInFlightOperationRegistry(
            store=store,
            recovery_claim=first_claim,
            clock=lambda: NOW + timedelta(seconds=2),
        )
        await registry.register(_owner_handle())

        await _claim(
            claims,
            claim_id="claim-002",
            owner="worker-b",
            expected_epoch=1,
            at=NOW + timedelta(seconds=3),
        )

        decision = await store.recover_active_as_orphaned(
            execution_id="execution-001",
            recovered_at=NOW + timedelta(seconds=4),
            required_claim=first_claim,
        )

        assert decision.status is InFlightRecoveryTransitionStatus.CONFLICT
        assert decision.reason_codes == ("INFLIGHT_RECOVERY_STALE_RECOVERY_EPOCH",)
        assert decision.observations == ()
        persisted = await store.load_inflight(execution_id="execution-001")
        assert len(persisted) == 1
        assert persisted[0].state is InFlightEvidenceState.ACTIVE_AT_CHECKPOINT

    asyncio.run(scenario())


def test_orphan_transition_no_active_is_explicit() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        claim = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
        )
        store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)

        decision = await store.recover_active_as_orphaned(
            execution_id="execution-001",
            recovered_at=NOW + timedelta(seconds=1),
            required_claim=claim,
        )

        assert decision.status is InFlightRecoveryTransitionStatus.NO_ACTIVE
        assert decision.reason_codes == ("INFLIGHT_NO_ACTIVE_AT_RECOVERY",)
        assert decision.observations == ()

    asyncio.run(scenario())


def test_inflight_handle_identity_cannot_be_rebound() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        claim = await _claim(
            claims,
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
        )
        store = InMemoryDurableRecoveryEvidenceStore(claim_authority=claims)
        registry = DurableInFlightOperationRegistry(
            store=store,
            recovery_claim=claim,
            clock=lambda: NOW + timedelta(seconds=2),
        )
        original = _owner_handle()
        assert await registry.register(original)

        rebound = replace(original, capability_id="skill-B")
        with pytest.raises(
            RuntimeError, match="INFLIGHT_HANDLE_REBIND_OR_STATE_CONFLICT"
        ):
            await registry.register(rebound)

        observations = await store.load_inflight(execution_id="execution-001")
        assert observations[0].handle == original

    asyncio.run(scenario())
