"""CA-M5-IU10-04 durable control applicability authority gates."""

from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime, timedelta
from typing import cast

import runtime.execution.control_applicability as control_applicability_module
from runtime.execution.aggregation_authority import (
    AggregationControlApplicabilityDecision,
    AggregationControlApplicabilityStatus,
    ExecutionAggregationAuthority,
    ExecutionAggregationEligibilityStatus,
)
from runtime.execution.aggregation_result import (
    CanonicalExecutionResultProjector,
    ExecutionAggregator,
)
from runtime.execution.control import (
    ExecutionControlLatchStatus,
    ExecutionControlSignal,
    ExecutionControlSignalType,
    LatchedExecutionControl,
    ObservedExecutionControl,
)
from runtime.execution.control_application import (
    ExecutionControlApplication,
    ExecutionControlDisposition,
)
from runtime.execution.control_applicability import (
    AggregationControlAuthoritySnapshot,
    ControlApplicabilityEvidenceStatus,
    ControlApplicabilityReadDecision,
    ControlApplicabilityReadStatus,
    ControlApplicabilityWriteStatus,
    DurableAggregationControlAuthority,
    DurableControlApplicabilityRecorder,
    DurableControlApplicabilityStore,
    InMemoryDurableControlApplicabilityStore,
)
from runtime.execution.control_runtime import ExecutionControlCoordinator
from runtime.execution.recovery import (
    ExecutionRecoveryClaim,
    InMemoryRecoveryClaimAuthority,
    RecoveryClaimRequest,
    RecoveryClaimStatus,
)
from runtime.execution.recovery_evidence import (
    DurableControlReadDecision,
    DurableControlReadStatus,
    DurableExecutionControlLatch,
    InMemoryDurableRecoveryEvidenceStore,
)
from runtime.execution.step_completion import RunningStepCompletionCoordinator
from tests.test_m5_iu10_ca02_aggregation_evidence import (
    NOW as CA02_NOW,
    _partial_reliability_result,
    _running,
    _skill_plan,
)

NOW = datetime(2026, 9, 24, 14, 0, tzinfo=UTC)


async def _claim(
    authority: InMemoryRecoveryClaimAuthority,
    *,
    claim_id: str,
    owner: str,
    expected_epoch: int,
    execution_id: str = "execution-ca04",
    at: datetime = NOW,
) -> ExecutionRecoveryClaim:
    decision = await authority.claim(
        RecoveryClaimRequest(
            claim_id=claim_id,
            execution_id=execution_id,
            recovery_owner_id=owner,
            expected_current_epoch=expected_epoch,
            source_snapshot_generation=0,
            requested_at=at,
        )
    )
    assert decision.status is RecoveryClaimStatus.CLAIMED
    assert decision.claim is not None
    return decision.claim


def _observed(
    *,
    signal_id: str = "signal-ca04",
    reason_code: str = "USER_CANCELLED",
    signal_type: ExecutionControlSignalType = ExecutionControlSignalType.CANCEL,
) -> ObservedExecutionControl:
    issued_at = NOW + timedelta(seconds=1)
    return ObservedExecutionControl(
        signal=ExecutionControlSignal(
            signal_type=signal_type,
            reason_code=reason_code,
            source="runtime",
            signal_id=signal_id,
            target_execution_id="execution-ca04",
            issued_at=issued_at,
        ),
        observed_at=issued_at + timedelta(seconds=1),
    )


def _application(
    signal: ExecutionControlSignal,
    *,
    disposition: ExecutionControlDisposition,
    reason_codes: tuple[str, ...] | None = None,
) -> ExecutionControlApplication:
    if disposition is ExecutionControlDisposition.READY_TO_TERMINALIZE:
        nonterminal = ("step-001",)
        affected = ("step-001",)
    elif disposition is ExecutionControlDisposition.ALREADY_TERMINAL:
        nonterminal = ()
        affected = ()
    else:
        nonterminal = ("step-001",)
        affected = ()

    return ExecutionControlApplication(
        signal=signal,
        disposition=disposition,
        reason_codes=reason_codes
        or (
            (
                "CONTROL_AFFECTS_PENDING_WORK"
                if disposition is ExecutionControlDisposition.READY_TO_TERMINALIZE
                else "CONTROL_ARRIVED_AFTER_EXECUTION_TERMINAL"
            ),
        ),
        nonterminal_step_ids_at_latch=nonterminal,
        affected_step_ids=affected,
        handoff_required=signal.signal_type is ExecutionControlSignalType.PREEMPT,
    )


async def _latched_fixture(
    *,
    signal_id: str = "signal-ca04",
) -> tuple[
    InMemoryRecoveryClaimAuthority,
    ExecutionRecoveryClaim,
    InMemoryDurableRecoveryEvidenceStore,
    LatchedExecutionControl,
]:
    claims = InMemoryRecoveryClaimAuthority()
    claim = await _claim(
        claims,
        claim_id="claim-ca04-1",
        owner="worker-a",
        expected_epoch=0,
    )
    control_store = InMemoryDurableRecoveryEvidenceStore(
        claim_authority=claims
    )
    latch = DurableExecutionControlLatch(
        store=control_store,
        recovery_claim=claim,
    )
    decision = await latch.latch(
        observed=_observed(signal_id=signal_id),
        latched_at=NOW + timedelta(seconds=3),
    )
    assert decision.status is ExecutionControlLatchStatus.LATCHED
    assert decision.latched_control is not None
    return claims, claim, control_store, decision.latched_control


def test_none_requires_durable_control_none_and_no_orphan_evidence() -> None:
    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        await _claim(
            claims,
            claim_id="claim-ca04-none",
            owner="worker-a",
            expected_epoch=0,
        )
        control_store = InMemoryDurableRecoveryEvidenceStore(
            claim_authority=claims
        )
        applicability_store = InMemoryDurableControlApplicabilityStore(
            claim_authority=claims
        )
        authority = DurableAggregationControlAuthority(
            control_store=control_store,
            applicability_store=applicability_store,
        )

        snapshot = await authority.resolve(execution_id="execution-ca04")

        assert snapshot.control.status is DurableControlReadStatus.NONE
        assert (
            snapshot.applicability.status
            is AggregationControlApplicabilityStatus.NONE
        )
        assert snapshot.applicability.latched_control is None

    asyncio.run(scenario())


def test_applicability_read_failure_never_collapses_to_none() -> None:
    class RaisingApplicabilityStore:
        async def read(
            self,
            execution_id: str,
        ) -> ControlApplicabilityReadDecision:
            del execution_id
            raise RuntimeError("storage unavailable")

    async def scenario() -> None:
        claims = InMemoryRecoveryClaimAuthority()
        await _claim(
            claims,
            claim_id="claim-ca04-read-unknown",
            owner="worker-a",
            expected_epoch=0,
        )
        control_store = InMemoryDurableRecoveryEvidenceStore(
            claim_authority=claims
        )
        authority = DurableAggregationControlAuthority(
            control_store=control_store,
            applicability_store=cast(
                DurableControlApplicabilityStore,
                RaisingApplicabilityStore(),
            ),
        )

        snapshot = await authority.resolve(execution_id="execution-ca04")

        assert snapshot.control.status is DurableControlReadStatus.NONE
        assert (
            snapshot.applicability.status
            is AggregationControlApplicabilityStatus.UNKNOWN
        )
        assert snapshot.applicability.reason_codes == (
            "AGGREGATION_CONTROL_APPLICABILITY_READ_UNKNOWN",
        )

    asyncio.run(scenario())


def test_latched_control_without_applicability_evidence_is_unknown() -> None:
    async def scenario() -> None:
        claims, _, control_store, _ = await _latched_fixture()
        applicability_store = InMemoryDurableControlApplicabilityStore(
            claim_authority=claims
        )
        authority = DurableAggregationControlAuthority(
            control_store=control_store,
            applicability_store=applicability_store,
        )

        snapshot = await authority.resolve(execution_id="execution-ca04")

        assert snapshot.control.status is DurableControlReadStatus.LATCHED
        assert (
            snapshot.applicability.status
            is AggregationControlApplicabilityStatus.UNKNOWN
        )
        assert snapshot.applicability.reason_codes == (
            "AGGREGATION_CONTROL_APPLICABILITY_EVIDENCE_MISSING",
        )

    asyncio.run(scenario())


def test_applies_evidence_survives_authority_recreation() -> None:
    async def scenario() -> None:
        claims, claim, control_store, latched = await _latched_fixture()
        applicability_store = InMemoryDurableControlApplicabilityStore(
            claim_authority=claims
        )
        recorder = DurableControlApplicabilityRecorder(
            store=applicability_store,
            recovery_claim=claim,
        )
        application = _application(
            latched.signal,
            disposition=ExecutionControlDisposition.READY_TO_TERMINALIZE,
        )

        write = await recorder.record(
            latched_control=latched,
            application=application,
            recorded_at=NOW + timedelta(seconds=4),
        )
        assert write.status is ControlApplicabilityWriteStatus.RECORDED

        first = DurableAggregationControlAuthority(
            control_store=control_store,
            applicability_store=applicability_store,
        )
        first_snapshot = await first.resolve(execution_id="execution-ca04")
        recreated = DurableAggregationControlAuthority(
            control_store=control_store,
            applicability_store=applicability_store,
        )
        replay_snapshot = await recreated.resolve(execution_id="execution-ca04")

        assert (
            first_snapshot.applicability.status
            is AggregationControlApplicabilityStatus.APPLIES
        )
        assert first_snapshot.applicability.latched_control == latched
        assert replay_snapshot == first_snapshot

    asyncio.run(scenario())


def test_late_noop_evidence_survives_authority_recreation() -> None:
    async def scenario() -> None:
        claims, claim, control_store, latched = await _latched_fixture()
        applicability_store = InMemoryDurableControlApplicabilityStore(
            claim_authority=claims
        )
        recorder = DurableControlApplicabilityRecorder(
            store=applicability_store,
            recovery_claim=claim,
        )
        application = _application(
            latched.signal,
            disposition=ExecutionControlDisposition.ALREADY_TERMINAL,
        )

        write = await recorder.record(
            latched_control=latched,
            application=application,
            recorded_at=NOW + timedelta(seconds=4),
        )
        assert write.status is ControlApplicabilityWriteStatus.RECORDED

        authority = DurableAggregationControlAuthority(
            control_store=control_store,
            applicability_store=applicability_store,
        )
        snapshot = await authority.resolve(execution_id="execution-ca04")

        assert (
            snapshot.applicability.status
            is AggregationControlApplicabilityStatus.LATE_NOOP
        )
        assert snapshot.applicability.latched_control == latched

    asyncio.run(scenario())


def test_exact_applicability_replay_is_idempotent() -> None:
    async def scenario() -> None:
        claims, claim, _, latched = await _latched_fixture()
        store = InMemoryDurableControlApplicabilityStore(
            claim_authority=claims
        )
        recorder = DurableControlApplicabilityRecorder(
            store=store,
            recovery_claim=claim,
        )
        application = _application(
            latched.signal,
            disposition=ExecutionControlDisposition.READY_TO_TERMINALIZE,
        )

        first = await recorder.record(
            latched_control=latched,
            application=application,
            recorded_at=NOW + timedelta(seconds=4),
        )
        replay = await recorder.record(
            latched_control=latched,
            application=application,
            recorded_at=NOW + timedelta(seconds=20),
        )
        read = await store.read("execution-ca04")

        assert first.status is ControlApplicabilityWriteStatus.RECORDED
        assert replay.status is ControlApplicabilityWriteStatus.ALREADY_CURRENT
        assert first.revision == replay.revision == 1
        assert read.status is ControlApplicabilityReadStatus.RECORDED
        assert read.record is not None
        assert read.record.revision == 1
        assert read.record.recorded_at == NOW + timedelta(seconds=4)
        assert read.record.status is ControlApplicabilityEvidenceStatus.APPLIES
        assert read.record.source_nonterminal_step_ids_at_latch == ("step-001",)
        assert read.record.source_affected_step_ids == ("step-001",)
        assert read.record.source_running_step_id is None
        assert read.record.source_preserve_running_step_result is False

    asyncio.run(scenario())


def test_applies_cannot_be_overwritten_by_later_already_terminal_replay() -> None:
    async def scenario() -> None:
        claims, claim, control_store, latched = await _latched_fixture()
        store = InMemoryDurableControlApplicabilityStore(
            claim_authority=claims
        )
        recorder = DurableControlApplicabilityRecorder(
            store=store,
            recovery_claim=claim,
        )

        first = await recorder.record(
            latched_control=latched,
            application=_application(
                latched.signal,
                disposition=ExecutionControlDisposition.READY_TO_TERMINALIZE,
            ),
            recorded_at=NOW + timedelta(seconds=4),
        )
        conflict = await recorder.record(
            latched_control=latched,
            application=_application(
                latched.signal,
                disposition=ExecutionControlDisposition.ALREADY_TERMINAL,
            ),
            recorded_at=NOW + timedelta(seconds=10),
        )

        assert first.status is ControlApplicabilityWriteStatus.RECORDED
        assert conflict.status is ControlApplicabilityWriteStatus.CONFLICT
        assert conflict.reason_codes == (
            "CONTROL_APPLICABILITY_IMMUTABLE_CONFLICT",
        )

        authority = DurableAggregationControlAuthority(
            control_store=control_store,
            applicability_store=store,
        )
        snapshot = await authority.resolve(execution_id="execution-ca04")
        assert (
            snapshot.applicability.status
            is AggregationControlApplicabilityStatus.APPLIES
        )

    asyncio.run(scenario())


def test_stale_recovery_epoch_cannot_write_applicability() -> None:
    async def scenario() -> None:
        claims, first_claim, _, latched = await _latched_fixture()
        store = InMemoryDurableControlApplicabilityStore(
            claim_authority=claims
        )
        stale_recorder = DurableControlApplicabilityRecorder(
            store=store,
            recovery_claim=first_claim,
        )
        second_claim = await _claim(
            claims,
            claim_id="claim-ca04-2",
            owner="worker-b",
            expected_epoch=1,
            at=NOW + timedelta(seconds=4),
        )
        assert second_claim.recovery_epoch == 2

        decision = await stale_recorder.record(
            latched_control=latched,
            application=_application(
                latched.signal,
                disposition=ExecutionControlDisposition.READY_TO_TERMINALIZE,
            ),
            recorded_at=NOW + timedelta(seconds=5),
        )

        assert decision.status is ControlApplicabilityWriteStatus.CONFLICT
        assert decision.reason_codes == (
            "CONTROL_APPLICABILITY_STALE_RECOVERY_EPOCH",
        )

    asyncio.run(scenario())


def test_nonfinal_control_application_cannot_become_applicability_truth() -> None:
    async def scenario() -> None:
        claims, claim, _, latched = await _latched_fixture()
        store = InMemoryDurableControlApplicabilityStore(
            claim_authority=claims
        )
        recorder = DurableControlApplicabilityRecorder(
            store=store,
            recovery_claim=claim,
        )

        decision = await recorder.record(
            latched_control=latched,
            application=_application(
                latched.signal,
                disposition=ExecutionControlDisposition.WAITING_IN_FLIGHT,
                reason_codes=("CONTROL_WAITING_FOR_INFLIGHT",),
            ),
            recorded_at=NOW + timedelta(seconds=4),
        )

        assert decision.status is ControlApplicabilityWriteStatus.UNKNOWN
        assert decision.reason_codes == (
            "CONTROL_APPLICABILITY_SOURCE_NOT_FINAL",
        )
        read = await store.read("execution-ca04")
        assert read.status is ControlApplicabilityReadStatus.NONE

    asyncio.run(scenario())


def test_orphan_applicability_without_durable_latch_is_unknown() -> None:
    async def scenario() -> None:
        claims, claim, _, latched = await _latched_fixture()
        applicability_store = InMemoryDurableControlApplicabilityStore(
            claim_authority=claims
        )
        recorder = DurableControlApplicabilityRecorder(
            store=applicability_store,
            recovery_claim=claim,
        )
        await recorder.record(
            latched_control=latched,
            application=_application(
                latched.signal,
                disposition=ExecutionControlDisposition.ALREADY_TERMINAL,
            ),
            recorded_at=NOW + timedelta(seconds=4),
        )

        empty_control_store = InMemoryDurableRecoveryEvidenceStore(
            claim_authority=claims
        )
        authority = DurableAggregationControlAuthority(
            control_store=empty_control_store,
            applicability_store=applicability_store,
        )
        snapshot = await authority.resolve(execution_id="execution-ca04")

        assert snapshot.control.status is DurableControlReadStatus.NONE
        assert (
            snapshot.applicability.status
            is AggregationControlApplicabilityStatus.UNKNOWN
        )
        assert snapshot.applicability.reason_codes == (
            "AGGREGATION_CONTROL_APPLICABILITY_ORPHAN_EVIDENCE",
        )

    asyncio.run(scenario())


def test_applicability_must_bind_exact_durable_latch() -> None:
    async def scenario() -> None:
        claims, claim, _, latched_a = await _latched_fixture(
            signal_id="signal-ca04-a"
        )
        applicability_store = InMemoryDurableControlApplicabilityStore(
            claim_authority=claims
        )
        recorder = DurableControlApplicabilityRecorder(
            store=applicability_store,
            recovery_claim=claim,
        )
        await recorder.record(
            latched_control=latched_a,
            application=_application(
                latched_a.signal,
                disposition=ExecutionControlDisposition.READY_TO_TERMINALIZE,
            ),
            recorded_at=NOW + timedelta(seconds=4),
        )

        control_store_b = InMemoryDurableRecoveryEvidenceStore(
            claim_authority=claims
        )
        latch_b = DurableExecutionControlLatch(
            store=control_store_b,
            recovery_claim=claim,
        )
        decision_b = await latch_b.latch(
            observed=_observed(signal_id="signal-ca04-b"),
            latched_at=NOW + timedelta(seconds=5),
        )
        assert decision_b.status is ExecutionControlLatchStatus.LATCHED

        authority = DurableAggregationControlAuthority(
            control_store=control_store_b,
            applicability_store=applicability_store,
        )
        snapshot = await authority.resolve(execution_id="execution-ca04")

        assert snapshot.control.status is DurableControlReadStatus.LATCHED
        assert (
            snapshot.applicability.status
            is AggregationControlApplicabilityStatus.UNKNOWN
        )
        assert snapshot.applicability.reason_codes == (
            "AGGREGATION_CONTROL_APPLICABILITY_AUTHORITY_MISMATCH",
        )

    asyncio.run(scenario())


class SequenceAggregationControlAuthority:
    def __init__(
        self,
        snapshots: tuple[AggregationControlAuthoritySnapshot, ...],
    ) -> None:
        self._snapshots = snapshots
        self.resolve_count = 0

    async def resolve(
        self,
        *,
        execution_id: str,
    ) -> AggregationControlAuthoritySnapshot:
        del execution_id
        index = min(self.resolve_count, len(self._snapshots) - 1)
        self.resolve_count += 1
        return self._snapshots[index]


def test_natural_commit_re_resolves_control_authority_before_replay() -> None:
    async def scenario() -> None:
        plan = _skill_plan()
        prepared, service, _ = await _running(plan)
        running = await service.start_step(
            prepared,
            step_id="step-001",
            at=CA02_NOW + timedelta(seconds=1),
        )
        step_done = (
            await RunningStepCompletionCoordinator(
                lifecycle_service=service
            ).complete(
                prepared=running,
                reliability_result=_partial_reliability_result(
                    step_execution_id=running.steps[0].step_execution_id
                ),
                at=CA02_NOW + timedelta(seconds=3),
            )
        ).prepared

        no_control = AggregationControlAuthoritySnapshot(
            control=DurableControlReadDecision(
                status=DurableControlReadStatus.NONE,
                reason_codes=("DURABLE_CONTROL_NOT_LATCHED",),
            ),
            applicability=AggregationControlApplicabilityDecision(
                status=AggregationControlApplicabilityStatus.NONE,
                reason_codes=("AGGREGATION_CONTROL_NONE_DURABLE",),
            ),
        )
        late_signal = ExecutionControlSignal(
            signal_type=ExecutionControlSignalType.CANCEL,
            reason_code="LATE_CANCEL",
            source="runtime",
            signal_id="signal-ca04-late",
            target_execution_id=step_done.execution_record.execution_id,
            issued_at=CA02_NOW + timedelta(seconds=3, milliseconds=100),
        )
        late_latch = LatchedExecutionControl(
            signal=late_signal,
            observed_at=CA02_NOW + timedelta(seconds=3, milliseconds=200),
            latched_at=CA02_NOW + timedelta(seconds=3, milliseconds=300),
        )
        late_noop = AggregationControlAuthoritySnapshot(
            control=DurableControlReadDecision(
                status=DurableControlReadStatus.LATCHED,
                reason_codes=("DURABLE_CONTROL_LATCH_FOUND",),
                latched_control=late_latch,
            ),
            applicability=AggregationControlApplicabilityDecision(
                status=AggregationControlApplicabilityStatus.LATE_NOOP,
                reason_codes=("CONTROL_ARRIVED_AFTER_EXECUTION_TERMINAL",),
                latched_control=late_latch,
            ),
        )
        control_authority = SequenceAggregationControlAuthority(
            (no_control, late_noop)
        )
        aggregator = ExecutionAggregator(
            authority=ExecutionAggregationAuthority(),
            lifecycle_service=service,
            projector=CanonicalExecutionResultProjector(),
            control_authority=control_authority,
        )

        result = await aggregator.aggregate(
            approved_plan=plan,
            prepared=step_done,
            at=CA02_NOW + timedelta(seconds=4),
        )

        assert control_authority.resolve_count == 2
        assert (
            result.eligibility.status
            is ExecutionAggregationEligibilityStatus.READY_EXISTING_TERMINAL
        )
        assert result.execution_result.cancellation is None

    asyncio.run(scenario())


def test_execution_aggregator_no_longer_accepts_hand_built_applicability() -> None:
    params = inspect.signature(ExecutionAggregator.aggregate).parameters

    assert "control" not in params
    assert "control_applicability" not in params
    assert "approved_plan" in params
    assert "prepared" in params
    assert "at" in params


def test_control_runtime_persists_applicability_before_lifecycle_mutation() -> None:
    source = inspect.getsource(ExecutionControlCoordinator._finalize_application)

    record_at = source.index("self._control_applicability_recorder.record")
    terminalize_at = source.index("self._lifecycle_service.terminalize")
    assert record_at < terminalize_at


def test_ca04_does_not_infer_late_noop_from_timestamps() -> None:
    source = inspect.getsource(
        control_applicability_module.DurableAggregationControlAuthority
    )

    assert "finished_at" not in source
    assert "latched_at >" not in source
    assert "all Steps terminal" not in source
