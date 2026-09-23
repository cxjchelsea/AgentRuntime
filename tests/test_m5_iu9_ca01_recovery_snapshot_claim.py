"""CA-M5-IU9-01 recovery snapshot and recovery-claim gates."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from runtime.contracts.execution import ExecutionContext
from runtime.execution.foundation import PreparedExecution, StepLifecycleSnapshot
from runtime.execution.models import ExecutionRecord, StepExecutionStatus
from runtime.execution.recovery import (
    ExecutionRecoverySnapshotCoordinator,
    ExecutionRecoverySnapshotFactory,
    InMemoryExecutionRecoverySnapshotStore,
    InMemoryRecoveryClaimAuthority,
    RecoveryClaimCoordinator,
    RecoveryClaimRequest,
    RecoveryClaimStatus,
    RecoveryEpochValidationStatus,
    RecoverySnapshotWriteStatus,
)

NOW = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)


def _step_payload(snapshot: StepLifecycleSnapshot) -> dict[str, object]:
    return {
        "step_execution_id": snapshot.step_execution_id,
        "step_id": snapshot.step_id,
        "action": snapshot.action,
        "status": snapshot.status.value,
        "skill_id": snapshot.skill_id,
        "workflow_id": snapshot.workflow_id,
        "tool_call_ids": list(snapshot.tool_call_ids),
        "output": snapshot.output,
        "error": snapshot.error,
        "retry_count": snapshot.retry_count,
        "started_at": snapshot.started_at,
        "finished_at": snapshot.finished_at,
    }


def _prepared(
    *,
    execution_id: str = "execution-001",
    status: str = "RUNNING",
    step_status: StepExecutionStatus = StepExecutionStatus.RUNNING,
    finished: bool = False,
) -> PreparedExecution:
    context = ExecutionContext(
        execution_id=execution_id,
        plan_id="plan-001",
        request_id="request-001",
        session_id="session-001",
        identity_scope="subject-001",
        policy_snapshot={"policy": {"version": "v1"}},
        device_id="device-001",
        step_state={"step-001": {"action": "ACTION_A"}},
        tool_context={
            "credential": "must-not-be-persisted",
            "connection": object(),
        },
        deadline=NOW + timedelta(minutes=5),
        cancellation_token=execution_id,
        trace_context={"trace_id": "trace-001"},
    )
    step = StepLifecycleSnapshot(
        step_execution_id="step-exec-001",
        step_id="step-001",
        action="ACTION_A",
        status=step_status,
        skill_id="SKILL_A",
        started_at=NOW + timedelta(seconds=1)
        if step_status is not StepExecutionStatus.PENDING
        else None,
        finished_at=NOW + timedelta(seconds=3)
        if step_status
        in {
            StepExecutionStatus.SUCCESS,
            StepExecutionStatus.FAILED,
            StepExecutionStatus.SKIPPED,
            StepExecutionStatus.CANCELLED,
            StepExecutionStatus.TIMEOUT,
            StepExecutionStatus.PREEMPTED,
        }
        else None,
    )
    record = ExecutionRecord(
        execution_id=execution_id,
        plan_id="plan-001",
        request_id="request-001",
        identity_scope="subject-001",
        status=status,
        current_step="step-001" if step_status is StepExecutionStatus.RUNNING else None,
        step_results=(_step_payload(step),),
        created_at=NOW,
        updated_at=NOW + timedelta(seconds=4 if finished else 2),
    )
    return PreparedExecution(
        execution_context=context,
        execution_record=record,
        steps=(step,),
        started_at=NOW + timedelta(seconds=1) if status != "CREATED" else None,
        finished_at=NOW + timedelta(seconds=4) if finished else None,
    )


def _request(
    *,
    claim_id: str,
    owner: str,
    expected_epoch: int,
    source_generation: int,
    execution_id: str = "execution-001",
    at: datetime = NOW,
) -> RecoveryClaimRequest:
    return RecoveryClaimRequest(
        claim_id=claim_id,
        execution_id=execution_id,
        recovery_owner_id=owner,
        expected_current_epoch=expected_epoch,
        source_snapshot_generation=source_generation,
        requested_at=at,
    )


def _claim_and_snapshot_runtime():
    store = InMemoryExecutionRecoverySnapshotStore()
    authority = InMemoryRecoveryClaimAuthority()
    claim_coordinator = RecoveryClaimCoordinator(
        snapshot_store=store,
        claim_authority=authority,
    )
    snapshot_coordinator = ExecutionRecoverySnapshotCoordinator(
        snapshot_store=store,
        epoch_guard=authority,
    )
    return store, authority, claim_coordinator, snapshot_coordinator


def test_recovery_safe_context_never_persists_raw_tool_context() -> None:
    async def scenario() -> None:
        store, _authority, claim_coordinator, snapshot_coordinator = (
            _claim_and_snapshot_runtime()
        )
        claim_decision = await claim_coordinator.claim(
            _request(
                claim_id="claim-001",
                owner="worker-a",
                expected_epoch=0,
                source_generation=0,
            )
        )
        assert claim_decision.status is RecoveryClaimStatus.CLAIMED
        assert claim_decision.claim is not None

        prepared = _prepared()
        snapshot = ExecutionRecoverySnapshotFactory().capture(
            prepared,
            checkpoint_id="checkpoint-001",
            generation=1,
            captured_at=NOW + timedelta(seconds=3),
            claim=claim_decision.claim,
            tool_context_reference="vault://runtime/tool-context-001",
        )
        decision = await snapshot_coordinator.save(
            snapshot,
            expected_generation=0,
            claim=claim_decision.claim,
        )
        assert decision.status is RecoverySnapshotWriteStatus.CREATED

        loaded = await store.load("execution-001")
        assert loaded is not None
        assert not hasattr(loaded.execution_context, "tool_context")
        assert loaded.execution_context.tool_context_reference == (
            "vault://runtime/tool-context-001"
        )
        restored = loaded.restore_prepared_execution()
        assert restored.execution_context.tool_context is None
        assert restored.execution_context.policy_snapshot == {
            "policy": {"version": "v1"}
        }
        assert restored.execution_context.trace_context == {"trace_id": "trace-001"}
        assert restored.execution_context.deadline == NOW + timedelta(minutes=5)

    asyncio.run(scenario())


def test_snapshot_capture_deep_copies_recovery_safe_context() -> None:
    async def scenario() -> None:
        _, _, claim_coordinator, _ = _claim_and_snapshot_runtime()
        claim_decision = await claim_coordinator.claim(
            _request(
                claim_id="claim-001",
                owner="worker-a",
                expected_epoch=0,
                source_generation=0,
            )
        )
        assert claim_decision.claim is not None
        prepared = _prepared()
        snapshot = ExecutionRecoverySnapshotFactory().capture(
            prepared,
            checkpoint_id="checkpoint-001",
            generation=1,
            captured_at=NOW + timedelta(seconds=3),
            claim=claim_decision.claim,
        )

        prepared.execution_context.policy_snapshot["policy"]["version"] = "mutated"
        assert prepared.execution_context.trace_context is not None
        prepared.execution_context.trace_context["trace_id"] = "mutated"

        assert snapshot.execution_context.policy_snapshot == {
            "policy": {"version": "v1"}
        }
        assert snapshot.execution_context.trace_context == {"trace_id": "trace-001"}

    asyncio.run(scenario())


def test_snapshot_rejects_typed_step_and_record_mismatch() -> None:
    async def scenario() -> None:
        _, _, claim_coordinator, _ = _claim_and_snapshot_runtime()
        claim_decision = await claim_coordinator.claim(
            _request(
                claim_id="claim-001",
                owner="worker-a",
                expected_epoch=0,
                source_generation=0,
            )
        )
        assert claim_decision.claim is not None
        prepared = _prepared()
        broken = replace(
            prepared,
            execution_record=replace(prepared.execution_record, step_results=()),
        )

        with pytest.raises(ValueError, match="typed steps"):
            ExecutionRecoverySnapshotFactory().capture(
                broken,
                checkpoint_id="checkpoint-001",
                generation=1,
                captured_at=NOW + timedelta(seconds=3),
                claim=claim_decision.claim,
            )

    asyncio.run(scenario())


def test_snapshot_store_create_update_and_exact_replay_are_monotonic() -> None:
    async def scenario() -> None:
        store, authority, claim_coordinator, snapshot_coordinator = (
            _claim_and_snapshot_runtime()
        )
        claim_decision = await claim_coordinator.claim(
            _request(
                claim_id="claim-001",
                owner="worker-a",
                expected_epoch=0,
                source_generation=0,
            )
        )
        assert claim_decision.claim is not None
        claim = claim_decision.claim
        factory = ExecutionRecoverySnapshotFactory()

        first = factory.capture(
            _prepared(),
            checkpoint_id="checkpoint-001",
            generation=1,
            captured_at=NOW + timedelta(seconds=3),
            claim=claim,
        )
        created = await snapshot_coordinator.save(
            first,
            expected_generation=0,
            claim=claim,
        )
        assert created.status is RecoverySnapshotWriteStatus.CREATED

        replay = await snapshot_coordinator.save(
            first,
            expected_generation=0,
            claim=claim,
        )
        assert replay.status is RecoverySnapshotWriteStatus.ALREADY_CURRENT

        updated_prepared = replace(
            _prepared(),
            execution_record=replace(
                _prepared().execution_record,
                updated_at=NOW + timedelta(seconds=4),
            ),
        )
        second = factory.capture(
            updated_prepared,
            checkpoint_id="checkpoint-002",
            generation=2,
            captured_at=NOW + timedelta(seconds=5),
            claim=claim,
        )
        updated = await snapshot_coordinator.save(
            second,
            expected_generation=1,
            claim=claim,
        )
        assert updated.status is RecoverySnapshotWriteStatus.UPDATED
        loaded = await store.load("execution-001")
        assert loaded == second

        validation = await authority.validate_current(claim)
        assert validation.status is RecoveryEpochValidationStatus.CURRENT

    asyncio.run(scenario())


def test_snapshot_store_rejects_stale_generation_without_overwrite() -> None:
    async def scenario() -> None:
        store, _, claim_coordinator, snapshot_coordinator = (
            _claim_and_snapshot_runtime()
        )
        claim_decision = await claim_coordinator.claim(
            _request(
                claim_id="claim-001",
                owner="worker-a",
                expected_epoch=0,
                source_generation=0,
            )
        )
        assert claim_decision.claim is not None
        claim = claim_decision.claim
        factory = ExecutionRecoverySnapshotFactory()
        first = factory.capture(
            _prepared(),
            checkpoint_id="checkpoint-001",
            generation=1,
            captured_at=NOW + timedelta(seconds=3),
            claim=claim,
        )
        await snapshot_coordinator.save(first, expected_generation=0, claim=claim)

        stale = replace(
            first,
            checkpoint_id="checkpoint-stale",
            generation=2,
            captured_at=NOW + timedelta(seconds=4),
        )
        decision = await snapshot_coordinator.save(
            stale,
            expected_generation=0,
            claim=claim,
        )

        assert decision.status is RecoverySnapshotWriteStatus.CONFLICT
        loaded = await store.load("execution-001")
        assert loaded == first

    asyncio.run(scenario())


def test_recovery_claim_exact_replay_is_idempotent_while_current() -> None:
    async def scenario() -> None:
        _, authority, coordinator, _ = _claim_and_snapshot_runtime()
        request = _request(
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
            source_generation=0,
        )

        first = await coordinator.claim(request)
        replay = await coordinator.claim(request)

        assert first.status is RecoveryClaimStatus.CLAIMED
        assert replay.status is RecoveryClaimStatus.ALREADY_CLAIMED
        assert replay.claim == first.claim
        assert first.claim is not None
        validation = await authority.validate_current(first.claim)
        assert validation.status is RecoveryEpochValidationStatus.CURRENT

    asyncio.run(scenario())


def test_recovery_claim_takeover_fences_old_epoch() -> None:
    async def scenario() -> None:
        store, authority, claim_coordinator, snapshot_coordinator = (
            _claim_and_snapshot_runtime()
        )
        first_decision = await claim_coordinator.claim(
            _request(
                claim_id="claim-001",
                owner="worker-a",
                expected_epoch=0,
                source_generation=0,
            )
        )
        assert first_decision.claim is not None
        first_claim = first_decision.claim
        first_snapshot = ExecutionRecoverySnapshotFactory().capture(
            _prepared(),
            checkpoint_id="checkpoint-001",
            generation=1,
            captured_at=NOW + timedelta(seconds=3),
            claim=first_claim,
        )
        await snapshot_coordinator.save(
            first_snapshot,
            expected_generation=0,
            claim=first_claim,
        )

        takeover = await claim_coordinator.claim(
            _request(
                claim_id="claim-002",
                owner="worker-b",
                expected_epoch=1,
                source_generation=1,
                at=NOW + timedelta(seconds=4),
            )
        )
        assert takeover.status is RecoveryClaimStatus.CLAIMED
        assert takeover.claim is not None
        assert takeover.claim.recovery_epoch == 2

        stale = await authority.validate_current(first_claim)
        current = await authority.validate_current(takeover.claim)
        assert stale.status is RecoveryEpochValidationStatus.STALE
        assert current.status is RecoveryEpochValidationStatus.CURRENT

        stale_snapshot = replace(
            first_snapshot,
            checkpoint_id="checkpoint-stale",
            generation=2,
            captured_at=NOW + timedelta(seconds=5),
        )
        stale_write = await snapshot_coordinator.save(
            stale_snapshot,
            expected_generation=1,
            claim=first_claim,
        )
        assert stale_write.status is RecoverySnapshotWriteStatus.CONFLICT
        assert stale_write.reason_codes == ("RECOVERY_SNAPSHOT_STALE_WRITER",)
        assert await store.load("execution-001") == first_snapshot

    asyncio.run(scenario())


def test_concurrent_takeover_from_same_epoch_allows_only_one_new_owner() -> None:
    async def scenario() -> None:
        _, _, claim_coordinator, snapshot_coordinator = _claim_and_snapshot_runtime()
        first = await claim_coordinator.claim(
            _request(
                claim_id="claim-001",
                owner="worker-a",
                expected_epoch=0,
                source_generation=0,
            )
        )
        assert first.claim is not None
        snapshot = ExecutionRecoverySnapshotFactory().capture(
            _prepared(),
            checkpoint_id="checkpoint-001",
            generation=1,
            captured_at=NOW + timedelta(seconds=3),
            claim=first.claim,
        )
        await snapshot_coordinator.save(
            snapshot, expected_generation=0, claim=first.claim
        )

        winner = await claim_coordinator.claim(
            _request(
                claim_id="claim-002",
                owner="worker-b",
                expected_epoch=1,
                source_generation=1,
                at=NOW + timedelta(seconds=4),
            )
        )
        loser = await claim_coordinator.claim(
            _request(
                claim_id="claim-003",
                owner="worker-c",
                expected_epoch=1,
                source_generation=1,
                at=NOW + timedelta(seconds=4),
            )
        )

        assert winner.status is RecoveryClaimStatus.CLAIMED
        assert loser.status is RecoveryClaimStatus.CONFLICT
        assert loser.current_claim == winner.claim

    asyncio.run(scenario())


def test_claim_based_on_stale_snapshot_generation_is_rejected() -> None:
    async def scenario() -> None:
        _, _, claim_coordinator, snapshot_coordinator = _claim_and_snapshot_runtime()
        first = await claim_coordinator.claim(
            _request(
                claim_id="claim-001",
                owner="worker-a",
                expected_epoch=0,
                source_generation=0,
            )
        )
        assert first.claim is not None
        factory = ExecutionRecoverySnapshotFactory()
        snapshot1 = factory.capture(
            _prepared(),
            checkpoint_id="checkpoint-001",
            generation=1,
            captured_at=NOW + timedelta(seconds=3),
            claim=first.claim,
        )
        await snapshot_coordinator.save(
            snapshot1, expected_generation=0, claim=first.claim
        )
        snapshot2 = replace(
            snapshot1,
            checkpoint_id="checkpoint-002",
            generation=2,
            captured_at=NOW + timedelta(seconds=4),
        )
        await snapshot_coordinator.save(
            snapshot2, expected_generation=1, claim=first.claim
        )

        stale = await claim_coordinator.claim(
            _request(
                claim_id="claim-002",
                owner="worker-b",
                expected_epoch=1,
                source_generation=1,
                at=NOW + timedelta(seconds=5),
            )
        )

        assert stale.status is RecoveryClaimStatus.CONFLICT
        assert stale.reason_codes == ("RECOVERY_CLAIM_SOURCE_SNAPSHOT_STALE",)

    asyncio.run(scenario())


def test_reused_claim_id_with_changed_payload_is_unknown() -> None:
    async def scenario() -> None:
        _, _, coordinator, _ = _claim_and_snapshot_runtime()
        first = await coordinator.claim(
            _request(
                claim_id="claim-001",
                owner="worker-a",
                expected_epoch=0,
                source_generation=0,
            )
        )
        assert first.status is RecoveryClaimStatus.CLAIMED

        changed = await coordinator.claim(
            _request(
                claim_id="claim-001",
                owner="worker-b",
                expected_epoch=0,
                source_generation=0,
            )
        )
        assert changed.status is RecoveryClaimStatus.UNKNOWN
        assert changed.reason_codes == ("RECOVERY_CLAIM_IDENTITY_REUSE_CONFLICT",)

    asyncio.run(scenario())


def test_old_claim_exact_replay_after_takeover_is_conflict_not_success() -> None:
    async def scenario() -> None:
        _, _, coordinator, snapshot_coordinator = _claim_and_snapshot_runtime()
        original_request = _request(
            claim_id="claim-001",
            owner="worker-a",
            expected_epoch=0,
            source_generation=0,
        )
        original = await coordinator.claim(original_request)
        assert original.claim is not None
        snapshot = ExecutionRecoverySnapshotFactory().capture(
            _prepared(),
            checkpoint_id="checkpoint-001",
            generation=1,
            captured_at=NOW + timedelta(seconds=3),
            claim=original.claim,
        )
        await snapshot_coordinator.save(
            snapshot, expected_generation=0, claim=original.claim
        )

        takeover = await coordinator.claim(
            _request(
                claim_id="claim-002",
                owner="worker-b",
                expected_epoch=1,
                source_generation=1,
                at=NOW + timedelta(seconds=4),
            )
        )
        assert takeover.status is RecoveryClaimStatus.CLAIMED

        replay = await coordinator.claim(original_request)
        assert replay.status is RecoveryClaimStatus.CONFLICT
        assert replay.reason_codes == ("RECOVERY_CLAIM_SOURCE_SNAPSHOT_STALE",)
        assert replay.current_claim == takeover.claim

    asyncio.run(scenario())


def test_snapshot_writer_claim_identity_mismatch_fails_closed() -> None:
    async def scenario() -> None:
        _, _, coordinator, snapshot_coordinator = _claim_and_snapshot_runtime()
        first = await coordinator.claim(
            _request(
                claim_id="claim-001",
                owner="worker-a",
                expected_epoch=0,
                source_generation=0,
            )
        )
        assert first.claim is not None
        snapshot = ExecutionRecoverySnapshotFactory().capture(
            _prepared(),
            checkpoint_id="checkpoint-001",
            generation=1,
            captured_at=NOW + timedelta(seconds=3),
            claim=first.claim,
        )
        forged = replace(first.claim, recovery_owner_id="worker-forged")

        decision = await snapshot_coordinator.save(
            snapshot,
            expected_generation=0,
            claim=forged,
        )

        assert decision.status is RecoverySnapshotWriteStatus.UNKNOWN
        assert decision.reason_codes == ("RECOVERY_SNAPSHOT_WRITER_CLAIM_MISMATCH",)

    asyncio.run(scenario())


def test_terminal_snapshot_restores_terminal_timing_exactly() -> None:
    async def scenario() -> None:
        _, _, coordinator, _ = _claim_and_snapshot_runtime()
        claim = await coordinator.claim(
            _request(
                claim_id="claim-001",
                owner="worker-a",
                expected_epoch=0,
                source_generation=0,
            )
        )
        assert claim.claim is not None
        prepared = _prepared(
            status="SUCCESS",
            step_status=StepExecutionStatus.SUCCESS,
            finished=True,
        )
        snapshot = ExecutionRecoverySnapshotFactory().capture(
            prepared,
            checkpoint_id="checkpoint-terminal",
            generation=1,
            captured_at=NOW + timedelta(seconds=5),
            claim=claim.claim,
        )

        restored = snapshot.restore_prepared_execution()
        assert restored.execution_record.status == "SUCCESS"
        assert restored.steps[0].status is StepExecutionStatus.SUCCESS
        assert restored.started_at == prepared.started_at
        assert restored.finished_at == prepared.finished_at

    asyncio.run(scenario())
