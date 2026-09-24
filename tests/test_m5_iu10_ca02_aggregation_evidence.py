"""CA-M5-IU10-02 crash-safe terminal Step aggregation evidence gates."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from runtime.execution.aggregation_authority import (
    AggregationEvidenceReadinessStatus,
    StepSkipAggregationDisposition,
)
from runtime.execution.aggregation_evidence import (
    StepAggregationEvidence,
    StepAggregationEvidenceAuthority,
    StepAggregationEvidenceReadStatus,
    StepAggregationTerminalizationKind,
    project_ca01_evidence_inputs,
)
from runtime.execution.capability_resolution import CapabilityExecutionOwner
from runtime.execution.control_lifecycle import ExecutionControlLifecycleTransitioner
from runtime.execution.foundation import (
    ApprovedPlanExecutionValidator,
    CallableExecutionIdentifierFactory,
    ExecutionContextBuilder,
    ExecutionFoundation,
    ExecutionLifecycleManager,
    ExecutionLifecycleService,
    ExecutionRecordFactory,
    InMemoryExecutionStateStore,
)
from runtime.execution.invocation import ToolInvocationJournalEntry
from runtime.execution.models import (
    M5SkillResult,
    M5ToolResult,
    M5WorkflowResult,
    SkillExecutionStatus,
    StepExecutionStatus,
    ToolExecutionStatus,
    WorkflowExecutionStatus,
)
from runtime.execution.recovery import (
    ExecutionRecoveryClaim,
    ExecutionRecoverySnapshotFactory,
)
from runtime.execution.reliability_boundary import (
    StepFinalizationDecision,
    StepFinalizationDisposition,
    StepReliabilityDecision,
    StepReliabilityDisposition,
)
from runtime.execution.reliability_coordinator import (
    RecoveredStepReliabilityRunResult,
    StepReliabilityRunResult,
)
from runtime.execution.result_collection import (
    StepAttemptObservation,
    StepAttemptStatus,
)
from runtime.execution.scheduler import StepScheduleDecision, StepScheduleStatus
from runtime.execution.step_completion import (
    RunningStepCompletionCoordinator,
    TerminalStepCompletionCoordinator,
)
from tests.orchestration_stubs import (
    build_approved_action_plan,
    build_runtime_context,
)
from tests.test_m5_iu7_ca03_control_lifecycle import (
    TERMINALIZED as CONTROL_TERMINALIZED_AT,
    _application as control_application,
    _latched as control_latched,
    _prepared as control_prepared,
)

NOW = datetime(2026, 9, 24, 11, 0, tzinfo=UTC)


def _skill_plan():
    base = build_approved_action_plan()
    step = base.steps[0].model_copy(
        update={
            "action": "SKILL_ACTION",
            "skill_id": "skill-001",
            "optional": False,
        }
    )
    return base.model_copy(
        update={
            "steps": [step],
            "capability_plan": {
                "bindings": [
                    {
                        "action_id": "SKILL_ACTION",
                        "skill_id": "skill-001",
                        "skill_version": "1.0.0",
                        "workflow_id": None,
                        "workflow_version": None,
                        "execution_owner": "SKILL",
                    }
                ],
                "selected_skills": ["skill-001"],
                "selected_workflows": [],
            },
            "tool_plan": {
                "tool_calls": [
                    {
                        "tool_id": "tool-001",
                        "tool_version": "1.0.0",
                        "required": True,
                        "required_by_skills": ["skill-001"],
                        "required_by_workflows": [],
                        "timeout_policy": None,
                        "retry_policy": None,
                        "idempotency_mode": None,
                        "side_effect_level": None,
                    }
                ],
                "parallelizable": False,
                "required_success": True,
            },
        }
    )


def _workflow_plan():
    base = build_approved_action_plan()
    step = base.steps[0].model_copy(
        update={
            "action": "WORKFLOW_ACTION",
            "skill_id": None,
            "workflow_id": "workflow-001",
            "optional": False,
        }
    )
    return base.model_copy(
        update={
            "steps": [step],
            "capability_plan": {
                "bindings": [
                    {
                        "action_id": "WORKFLOW_ACTION",
                        "skill_id": None,
                        "skill_version": None,
                        "workflow_id": "workflow-001",
                        "workflow_version": "1.0.0",
                        "execution_owner": "WORKFLOW",
                    }
                ],
                "selected_skills": [],
                "selected_workflows": ["workflow-001"],
            },
            "tool_plan": {
                "tool_calls": [],
                "parallelizable": False,
                "required_success": False,
            },
        }
    )


def _plain_plan():
    base = build_approved_action_plan()
    step = base.steps[0].model_copy(
        update={
            "action": "NO_OWNER_ACTION",
            "skill_id": None,
            "workflow_id": None,
            "optional": False,
        }
    )
    return base.model_copy(update={"steps": [step]})


async def _running(plan):
    ids = CallableExecutionIdentifierFactory(
        execution_id_factory=lambda: "execution-iu10-ca02",
        step_execution_id_factory=lambda step_id: f"exec:{step_id}",
    )
    store = InMemoryExecutionStateStore()
    foundation = ExecutionFoundation(
        plan_validator=ApprovedPlanExecutionValidator(),
        context_builder=ExecutionContextBuilder(identifier_factory=ids),
        record_factory=ExecutionRecordFactory(
            identifier_factory=ids,
            clock=lambda: NOW,
        ),
        execution_store=store,
    )
    prepared = await foundation.initialize(plan, build_runtime_context())
    service = ExecutionLifecycleService(
        lifecycle_manager=ExecutionLifecycleManager(),
        execution_store=store,
    )
    running = await service.start_execution(prepared, at=NOW)
    return running, service, store


def _skill_observation(
    *,
    step_execution_id: str,
    metadata: dict[str, Any] | None = None,
) -> StepAttemptObservation:
    tool_result = M5ToolResult(
        tool_call_id="tool-call-001",
        tool_id="tool-001",
        status=ToolExecutionStatus.SUCCESS,
        data={"value": 1},
        started_at=NOW + timedelta(seconds=1),
        finished_at=NOW + timedelta(seconds=2),
        attempt=1,
    )
    journal = ToolInvocationJournalEntry(
        tool_call_id="tool-call-001",
        tool_id="tool-001",
        tool_version="1.0.0",
        result=tool_result,
    )
    skill_result = M5SkillResult(
        skill_id="skill-001",
        status=SkillExecutionStatus.PARTIAL_SUCCESS,
        business_outputs=({"kind": "partial-output"},),
        tool_results=(tool_result,),
        events=({"event": "skill-partial"},),
        metadata={} if metadata is None else metadata,
    )
    return StepAttemptObservation(
        step_id="step-001",
        step_execution_id=step_execution_id,
        attempt_number=1,
        status=StepAttemptStatus.PARTIAL_SUCCESS,
        execution_owner=CapabilityExecutionOwner.SKILL,
        reason_codes=("SKILL_PARTIAL",),
        observed_at=NOW + timedelta(seconds=2),
        owner_capability_id="skill-001",
        owner_capability_version="1.0.0",
        skill_result=skill_result,
        tool_results=(tool_result,),
        tool_journal=(journal,),
        business_outputs=({"kind": "partial-output"},),
        capability_events=({"event": "skill-partial"},),
        has_non_success_tool_observation=False,
        has_unknown_tool_observation=False,
        has_untrusted_success_observation=False,
    )


def _workflow_observation(
    *,
    step_execution_id: str,
    status: WorkflowExecutionStatus = WorkflowExecutionStatus.COMPLETED,
    attempt_number: int = 1,
) -> StepAttemptObservation:
    workflow_result = M5WorkflowResult(
        workflow_instance_id="workflow-instance-001",
        workflow_id="workflow-001",
        status=status,
        completed_steps=("node-001",) if status is WorkflowExecutionStatus.COMPLETED else (),
        important_outputs={"answer": "done"},
    )
    attempt_status = {
        WorkflowExecutionStatus.COMPLETED: StepAttemptStatus.SUCCESS,
        WorkflowExecutionStatus.FAILED: StepAttemptStatus.FAILED,
        WorkflowExecutionStatus.TIMEOUT: StepAttemptStatus.TIMEOUT,
        WorkflowExecutionStatus.WAITING: StepAttemptStatus.WAITING,
        WorkflowExecutionStatus.RUNNING: StepAttemptStatus.IN_PROGRESS,
        WorkflowExecutionStatus.CREATED: StepAttemptStatus.IN_PROGRESS,
        WorkflowExecutionStatus.CANCELLED: StepAttemptStatus.CANCELLED,
        WorkflowExecutionStatus.PREEMPTED: StepAttemptStatus.PREEMPTED,
    }[status]
    return StepAttemptObservation(
        step_id="step-001",
        step_execution_id=step_execution_id,
        attempt_number=attempt_number,
        status=attempt_status,
        execution_owner=CapabilityExecutionOwner.WORKFLOW,
        reason_codes=(f"WORKFLOW_{status.value}",),
        observed_at=NOW + timedelta(seconds=2),
        owner_capability_id="workflow-001",
        owner_capability_version="1.0.0",
        workflow_result=workflow_result,
        business_outputs=({"answer": "done"},),
        capability_events=(),
        has_non_success_tool_observation=False,
        has_unknown_tool_observation=False,
        has_untrusted_success_observation=False,
    )


def _partial_reliability_result(
    *,
    step_execution_id: str,
) -> StepReliabilityRunResult:
    observation = _skill_observation(step_execution_id=step_execution_id)
    return StepReliabilityRunResult(
        attempts=(observation,),
        reliability_decision=StepReliabilityDecision(
            disposition=StepReliabilityDisposition.FINALIZE,
            reason_codes=("STEP_RETRY_NOT_AUTHORIZED",),
        ),
        finalization_decision=StepFinalizationDecision(
            disposition=StepFinalizationDisposition.FINALIZE,
            reason_codes=("STEP_PARTIAL_SUCCESS_FINALIZATION_AUTHORIZED",),
            terminal_status=StepExecutionStatus.SUCCESS,
            degraded=True,
        ),
        owner_policy_identity="skill-policy@1",
    )


class StaticScheduler:
    def __init__(self, decision: StepScheduleDecision) -> None:
        self.decision = decision

    async def next_step(self, *, approved_plan, prepared) -> StepScheduleDecision:
        del approved_plan, prepared
        return self.decision


def test_attempt_finalization_persists_rich_evidence_atomically() -> None:
    async def scenario() -> None:
        plan = _skill_plan()
        prepared, service, store = await _running(plan)
        running = await service.start_step(
            prepared,
            step_id="step-001",
            at=NOW + timedelta(seconds=1),
        )
        decision = await RunningStepCompletionCoordinator(
            lifecycle_service=service
        ).complete(
            prepared=running,
            reliability_result=_partial_reliability_result(
                step_execution_id=running.steps[0].step_execution_id
            ),
            at=NOW + timedelta(seconds=3),
        )

        step = decision.prepared.steps[0]
        evidence = step.aggregation_evidence
        assert evidence is not None
        assert (
            evidence.terminalization_kind
            is StepAggregationTerminalizationKind.ATTEMPT_FINALIZED
        )
        assert evidence.execution_id == "execution-iu10-ca02"
        assert evidence.step_execution_id == step.step_execution_id
        assert evidence.terminal_step_status is StepExecutionStatus.SUCCESS
        assert evidence.degraded is True
        assert evidence.final_attempt_number == 1
        assert evidence.final_attempt_status == "PARTIAL_SUCCESS"
        assert evidence.final_attempt_reason_codes == ("SKILL_PARTIAL",)
        assert evidence.execution_owner == "SKILL"
        assert evidence.owner_capability_id == "skill-001"
        assert evidence.skill_result is not None
        assert evidence.skill_result["status"] == "PARTIAL_SUCCESS"
        assert evidence.tool_call_ids == ("tool-call-001",)
        assert evidence.tool_journal[0]["tool_call_id"] == "tool-call-001"
        assert evidence.business_outputs == ({"kind": "partial-output"},)
        assert evidence.capability_events == ({"event": "skill-partial"},)

        stored = await store.load("execution-iu10-ca02")
        assert stored is not None
        assert stored.step_results[0]["aggregation_evidence"] == evidence.to_payload()

        readiness, skips = project_ca01_evidence_inputs(approved_plan=plan, prepared=decision.prepared)
        assert readiness.status is AggregationEvidenceReadinessStatus.READY
        assert skips == {}
        raw_assessment, _ = StepAggregationEvidenceAuthority().assess(
            approved_plan=plan,
            prepared=decision.prepared,
        )
        assert raw_assessment.status is StepAggregationEvidenceReadStatus.READY

    asyncio.run(scenario())


def test_attempt_evidence_survives_recovery_snapshot_roundtrip() -> None:
    async def scenario() -> None:
        plan = _skill_plan()
        prepared, service, _ = await _running(plan)
        running = await service.start_step(
            prepared,
            step_id="step-001",
            at=NOW + timedelta(seconds=1),
        )
        completed = await RunningStepCompletionCoordinator(
            lifecycle_service=service
        ).complete(
            prepared=running,
            reliability_result=_partial_reliability_result(
                step_execution_id=running.steps[0].step_execution_id
            ),
            at=NOW + timedelta(seconds=3),
        )
        claim = ExecutionRecoveryClaim(
            claim_id="claim-ca02",
            execution_id="execution-iu10-ca02",
            recovery_owner_id="worker-ca02",
            recovery_epoch=1,
            source_snapshot_generation=0,
            claimed_at=NOW + timedelta(seconds=3),
        )

        snapshot = ExecutionRecoverySnapshotFactory().capture(
            completed.prepared,
            checkpoint_id="checkpoint-ca02",
            generation=1,
            captured_at=NOW + timedelta(seconds=4),
            claim=claim,
        )
        restored = snapshot.restore_prepared_execution()

        assert (
            restored.steps[0].aggregation_evidence
            == completed.prepared.steps[0].aggregation_evidence
        )
        readiness, skips = project_ca01_evidence_inputs(approved_plan=plan, prepared=restored)
        assert readiness.status is AggregationEvidenceReadinessStatus.READY
        assert skips == {}

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("reason_codes", "expected"),
    [
        (("CONDITION_FALSE",), StepSkipAggregationDisposition.NOT_APPLICABLE),
        (
            ("DEPENDENCY_NOT_SUCCESSFUL",),
            StepSkipAggregationDisposition.UNSATISFIED,
        ),
    ],
)
def test_scheduler_skip_persists_explicit_skip_semantics(
    reason_codes: tuple[str, ...],
    expected: StepSkipAggregationDisposition,
) -> None:
    async def scenario() -> None:
        plan = _plain_plan()
        prepared, service, store = await _running(plan)
        coordinator = TerminalStepCompletionCoordinator(
            scheduler=StaticScheduler(
                StepScheduleDecision(
                    status=StepScheduleStatus.SKIP,
                    step_id="step-001",
                    reason_codes=reason_codes,
                )
            ),
            lifecycle_service=service,
        )

        decision = await coordinator.advance(
            approved_plan=plan,
            prepared=prepared,
            at=NOW + timedelta(seconds=1),
        )

        step = decision.prepared.steps[0]
        evidence = step.aggregation_evidence
        assert evidence is not None
        assert (
            evidence.terminalization_kind
            is StepAggregationTerminalizationKind.SCHEDULER_SKIPPED
        )
        assert evidence.scheduler_skip_disposition == expected.value
        assert evidence.terminal_reason_codes == reason_codes

        stored = await store.load("execution-iu10-ca02")
        assert stored is not None
        assert stored.step_results[0]["aggregation_evidence"] == evidence.to_payload()

        readiness, skips = project_ca01_evidence_inputs(approved_plan=plan, prepared=decision.prepared)
        assert readiness.status is AggregationEvidenceReadinessStatus.READY
        assert skips["step-001"].disposition is expected
        assert skips["step-001"].step_execution_id == step.step_execution_id

    asyncio.run(scenario())


def test_required_previous_failure_blocked_terminalization_is_unsatisfied() -> None:
    async def scenario() -> None:
        plan = _plain_plan()
        prepared, service, _ = await _running(plan)
        coordinator = TerminalStepCompletionCoordinator(
            scheduler=StaticScheduler(
                StepScheduleDecision(
                    status=StepScheduleStatus.BLOCKED,
                    step_id="step-001",
                    reason_codes=("REQUIRED_PREVIOUS_STEP_NOT_SUCCESSFUL",),
                )
            ),
            lifecycle_service=service,
        )

        decision = await coordinator.advance(
            approved_plan=plan,
            prepared=prepared,
            at=NOW + timedelta(seconds=1),
        )

        evidence = decision.prepared.steps[0].aggregation_evidence
        assert evidence is not None
        assert evidence.scheduler_skip_disposition == "UNSATISFIED"
        readiness, skips = project_ca01_evidence_inputs(approved_plan=plan, prepared=decision.prepared)
        assert readiness.status is AggregationEvidenceReadinessStatus.READY
        assert (
            skips["step-001"].disposition
            is StepSkipAggregationDisposition.UNSATISFIED
        )

    asyncio.run(scenario())


def test_terminal_step_without_aggregation_evidence_is_missing_not_invented() -> None:
    async def scenario() -> None:
        plan = _plain_plan()
        prepared, service, _ = await _running(plan)
        running = await service.start_step(
            prepared,
            step_id="step-001",
            at=NOW + timedelta(seconds=1),
        )
        legacy_terminal = await service.finish_step(
            running,
            step_id="step-001",
            status=StepExecutionStatus.SUCCESS,
            at=NOW + timedelta(seconds=2),
            terminal_reason_codes=("LEGACY_DIRECT_FINISH",),
        )

        readiness, skips = project_ca01_evidence_inputs(approved_plan=plan, prepared=legacy_terminal)

        assert readiness.status is AggregationEvidenceReadinessStatus.MISSING
        assert readiness.reason_codes == (
            "AGGREGATION_EVIDENCE_TERMINAL_STEP_MISSING",
        )
        assert skips == {}

    asyncio.run(scenario())


def test_persisted_evidence_drift_is_unknown_not_ready() -> None:
    async def scenario() -> None:
        plan = _skill_plan()
        prepared, service, _ = await _running(plan)
        running = await service.start_step(
            prepared,
            step_id="step-001",
            at=NOW + timedelta(seconds=1),
        )
        completed = await RunningStepCompletionCoordinator(
            lifecycle_service=service
        ).complete(
            prepared=running,
            reliability_result=_partial_reliability_result(
                step_execution_id=running.steps[0].step_execution_id
            ),
            at=NOW + timedelta(seconds=3),
        )
        payload: dict[str, Any] = dict(
            completed.prepared.execution_record.step_results[0]
        )
        evidence_payload: dict[str, Any] = dict(payload["aggregation_evidence"])
        evidence_payload["degraded"] = False
        payload["aggregation_evidence"] = evidence_payload
        drifted = replace(
            completed.prepared,
            execution_record=replace(
                completed.prepared.execution_record,
                step_results=(payload,),
            ),
        )

        assessment, skips = project_ca01_evidence_inputs(approved_plan=plan, prepared=drifted)

        assert assessment.status is AggregationEvidenceReadinessStatus.UNKNOWN
        assert assessment.reason_codes == (
            "AGGREGATION_EVIDENCE_PERSISTED_PAYLOAD_MISMATCH",
        )
        assert skips == {}

    asyncio.run(scenario())


def test_legacy_terminal_payload_without_evidence_remains_recovery_readable() -> None:
    async def scenario() -> None:
        plan = _plain_plan()
        prepared, service, _ = await _running(plan)
        running = await service.start_step(
            prepared,
            step_id="step-001",
            at=NOW + timedelta(seconds=1),
        )
        legacy_terminal = await service.finish_step(
            running,
            step_id="step-001",
            status=StepExecutionStatus.SUCCESS,
            at=NOW + timedelta(seconds=2),
            terminal_reason_codes=("LEGACY_DIRECT_FINISH",),
        )
        assert "aggregation_evidence" not in (
            legacy_terminal.execution_record.step_results[0]
        )
        claim = ExecutionRecoveryClaim(
            claim_id="claim-ca02-legacy",
            execution_id="execution-iu10-ca02",
            recovery_owner_id="worker-ca02",
            recovery_epoch=1,
            source_snapshot_generation=0,
            claimed_at=NOW + timedelta(seconds=2),
        )

        snapshot = ExecutionRecoverySnapshotFactory().capture(
            legacy_terminal,
            checkpoint_id="checkpoint-ca02-legacy",
            generation=1,
            captured_at=NOW + timedelta(seconds=3),
            claim=claim,
        )
        restored = snapshot.restore_prepared_execution()

        assert restored.steps[0].aggregation_evidence is None
        readiness, _ = project_ca01_evidence_inputs(approved_plan=plan, prepared=restored)
        assert readiness.status is AggregationEvidenceReadinessStatus.MISSING

    asyncio.run(scenario())


def test_control_terminalization_attaches_minimal_step_evidence() -> None:
    prepared = control_prepared()
    updated = ExecutionControlLifecycleTransitioner().terminalize(
        prepared,
        latched_control=control_latched(),
        application=control_application(),
        at=CONTROL_TERMINALIZED_AT,
    )

    assert updated.steps[0].aggregation_evidence is None
    for step in updated.steps[1:]:
        evidence = step.aggregation_evidence
        assert evidence is not None
        assert (
            evidence.terminalization_kind
            is StepAggregationTerminalizationKind.CONTROL_TERMINALIZED
        )
        assert evidence.terminal_step_status is StepExecutionStatus.CANCELLED
        assert evidence.terminal_reason_codes == (
            "CONTROL_SAFE_BOUNDARY_CONFIRMED",
        )
        assert evidence.execution_owner is None
        assert evidence.skill_result is None
        assert evidence.workflow_result is None


def test_evidence_payload_roundtrip_is_exact() -> None:
    observation = _skill_observation(step_execution_id="exec:step-001")
    evidence = StepAggregationEvidence.from_attempt_finalization(
        execution_id="execution-iu10-ca02",
        observation=observation,
        terminal_step_status=StepExecutionStatus.SUCCESS,
        terminal_reason_codes=("STEP_PARTIAL_SUCCESS_FINALIZATION_AUTHORIZED",),
        degraded=True,
        terminalized_at=NOW + timedelta(seconds=3),
    )

    restored = StepAggregationEvidence.from_payload(evidence.to_payload())

    assert restored == evidence
    assert restored.to_payload() == evidence.to_payload()


def test_live_runtime_object_cannot_enter_crash_safe_evidence() -> None:
    observation = _skill_observation(
        step_execution_id="exec:step-001",
        metadata={"process_handle": object()},
    )

    with pytest.raises(ValueError, match="unsupported aggregation evidence value type"):
        StepAggregationEvidence.from_attempt_finalization(
            execution_id="execution-iu10-ca02",
            observation=observation,
            terminal_step_status=StepExecutionStatus.SUCCESS,
            terminal_reason_codes=(
                "STEP_PARTIAL_SUCCESS_FINALIZATION_AUTHORIZED",
            ),
            degraded=True,
            terminalized_at=NOW + timedelta(seconds=3),
        )



def test_workflow_completed_terminal_evidence_is_ready() -> None:
    async def scenario() -> None:
        plan = _workflow_plan()
        prepared, service, _ = await _running(plan)
        running = await service.start_step(
            prepared,
            step_id="step-001",
            at=NOW + timedelta(seconds=1),
        )
        observation = _workflow_observation(
            step_execution_id=running.steps[0].step_execution_id
        )
        result = StepReliabilityRunResult(
            attempts=(observation,),
            reliability_decision=StepReliabilityDecision(
                disposition=StepReliabilityDisposition.FINALIZE,
                reason_codes=("STEP_RETRY_NOT_AUTHORIZED",),
            ),
            finalization_decision=StepFinalizationDecision(
                disposition=StepFinalizationDisposition.FINALIZE,
                reason_codes=("STEP_SUCCESS_FINALIZATION_AUTHORIZED",),
                terminal_status=StepExecutionStatus.SUCCESS,
            ),
        )

        completed = await RunningStepCompletionCoordinator(
            lifecycle_service=service
        ).complete(
            prepared=running,
            reliability_result=result,
            at=NOW + timedelta(seconds=3),
        )

        evidence = completed.prepared.steps[0].aggregation_evidence
        assert evidence is not None
        assert evidence.execution_owner == "WORKFLOW"
        assert evidence.workflow_result is not None
        assert evidence.workflow_result["status"] == "COMPLETED"
        assert evidence.business_outputs == ({"answer": "done"},)
        readiness, _ = project_ca01_evidence_inputs(approved_plan=plan, prepared=completed.prepared)
        assert readiness.status is AggregationEvidenceReadinessStatus.READY

    asyncio.run(scenario())


def test_workflow_waiting_payload_cannot_masquerade_as_terminal_success() -> None:
    async def scenario() -> None:
        plan = _workflow_plan()
        prepared, service, _ = await _running(plan)
        running = await service.start_step(
            prepared,
            step_id="step-001",
            at=NOW + timedelta(seconds=1),
        )
        valid_observation = _workflow_observation(
            step_execution_id=running.steps[0].step_execution_id
        )
        valid_result = StepReliabilityRunResult(
            attempts=(valid_observation,),
            reliability_decision=StepReliabilityDecision(
                disposition=StepReliabilityDisposition.FINALIZE,
                reason_codes=("STEP_RETRY_NOT_AUTHORIZED",),
            ),
            finalization_decision=StepFinalizationDecision(
                disposition=StepFinalizationDisposition.FINALIZE,
                reason_codes=("STEP_SUCCESS_FINALIZATION_AUTHORIZED",),
                terminal_status=StepExecutionStatus.SUCCESS,
            ),
        )
        completed = await RunningStepCompletionCoordinator(
            lifecycle_service=service
        ).complete(
            prepared=running,
            reliability_result=valid_result,
            at=NOW + timedelta(seconds=3),
        )
        step = completed.prepared.steps[0]
        assert step.aggregation_evidence is not None
        waiting_payload = dict(step.aggregation_evidence.workflow_result or {})
        waiting_payload["status"] = "WAITING"
        forged_evidence = replace(
            step.aggregation_evidence,
            workflow_result=waiting_payload,
        )
        forged_step = replace(step, aggregation_evidence=forged_evidence)
        persisted: dict[str, Any] = dict(
            completed.prepared.execution_record.step_results[0]
        )
        persisted["aggregation_evidence"] = forged_evidence.to_payload()
        forged = replace(
            completed.prepared,
            steps=(forged_step,),
            execution_record=replace(
                completed.prepared.execution_record,
                step_results=(persisted,),
            ),
        )

        readiness, _ = project_ca01_evidence_inputs(approved_plan=plan, prepared=forged)

        assert readiness.status is AggregationEvidenceReadinessStatus.UNKNOWN
        assert readiness.reason_codes == (
            "AGGREGATION_EVIDENCE_WORKFLOW_STATUS_MISMATCH",
        )

    asyncio.run(scenario())


def test_unknown_tool_truth_blocks_terminal_evidence_readiness() -> None:
    async def scenario() -> None:
        plan = _skill_plan()
        prepared, service, _ = await _running(plan)
        running = await service.start_step(
            prepared,
            step_id="step-001",
            at=NOW + timedelta(seconds=1),
        )
        completed = await RunningStepCompletionCoordinator(
            lifecycle_service=service
        ).complete(
            prepared=running,
            reliability_result=_partial_reliability_result(
                step_execution_id=running.steps[0].step_execution_id
            ),
            at=NOW + timedelta(seconds=3),
        )
        step = completed.prepared.steps[0]
        assert step.aggregation_evidence is not None
        forged_evidence = replace(
            step.aggregation_evidence,
            has_unknown_tool_observation=True,
        )
        forged_step = replace(step, aggregation_evidence=forged_evidence)
        persisted: dict[str, Any] = dict(
            completed.prepared.execution_record.step_results[0]
        )
        persisted["aggregation_evidence"] = forged_evidence.to_payload()
        forged = replace(
            completed.prepared,
            steps=(forged_step,),
            execution_record=replace(
                completed.prepared.execution_record,
                step_results=(persisted,),
            ),
        )

        readiness, _ = project_ca01_evidence_inputs(approved_plan=plan, prepared=forged)

        assert readiness.status is AggregationEvidenceReadinessStatus.UNKNOWN
        assert readiness.reason_codes == (
            "AGGREGATION_EVIDENCE_TOOL_TRUTH_UNKNOWN",
        )

    asyncio.run(scenario())


def test_recovered_attempt_number_survives_terminal_evidence() -> None:
    async def scenario() -> None:
        plan = _workflow_plan()
        prepared, service, _ = await _running(plan)
        running = await service.start_step(
            prepared,
            step_id="step-001",
            at=NOW + timedelta(seconds=1),
        )
        observation = _workflow_observation(
            step_execution_id=running.steps[0].step_execution_id,
            attempt_number=2,
        )
        recovered = RecoveredStepReliabilityRunResult(
            prior_attempt_number=1,
            attempts=(observation,),
            reliability_decision=StepReliabilityDecision(
                disposition=StepReliabilityDisposition.FINALIZE,
                reason_codes=("STEP_RETRY_NOT_AUTHORIZED",),
            ),
            finalization_decision=StepFinalizationDecision(
                disposition=StepFinalizationDisposition.FINALIZE,
                reason_codes=("STEP_SUCCESS_FINALIZATION_AUTHORIZED",),
                terminal_status=StepExecutionStatus.SUCCESS,
            ),
        )

        completed = await RunningStepCompletionCoordinator(
            lifecycle_service=service
        ).complete(
            prepared=running,
            reliability_result=recovered,
            at=NOW + timedelta(seconds=3),
        )

        step = completed.prepared.steps[0]
        assert step.retry_count == 1
        assert step.aggregation_evidence is not None
        assert step.aggregation_evidence.final_attempt_number == 2
        readiness, _ = project_ca01_evidence_inputs(approved_plan=plan, prepared=completed.prepared)
        assert readiness.status is AggregationEvidenceReadinessStatus.READY

    asyncio.run(scenario())



def test_serialized_evidence_rejects_extra_or_coerced_fields() -> None:
    observation = _skill_observation(step_execution_id="exec:step-001")
    evidence = StepAggregationEvidence.from_attempt_finalization(
        execution_id="execution-iu10-ca02",
        observation=observation,
        terminal_step_status=StepExecutionStatus.SUCCESS,
        terminal_reason_codes=("STEP_PARTIAL_SUCCESS_FINALIZATION_AUTHORIZED",),
        degraded=True,
        terminalized_at=NOW + timedelta(seconds=3),
    )
    payload = evidence.to_payload()

    with_extra = dict(payload)
    with_extra["unexpected"] = "value"
    with pytest.raises(ValueError, match="payload keys"):
        StepAggregationEvidence.from_payload(with_extra)

    coerced = dict(payload)
    coerced["execution_id"] = 123
    with pytest.raises(ValueError, match="execution_id"):
        StepAggregationEvidence.from_payload(coerced)


def test_tool_truth_flags_cannot_be_forged() -> None:
    observation = _skill_observation(step_execution_id="exec:step-001")

    with pytest.raises(ValueError, match="unknown Tool evidence flag"):
        StepAggregationEvidence(
            schema_version="m5-iu10-ca02-v1",
            execution_id="execution-iu10-ca02",
            step_execution_id=observation.step_execution_id,
            step_id=observation.step_id,
            terminalization_kind=StepAggregationTerminalizationKind.ATTEMPT_FINALIZED,
            terminal_step_status=StepExecutionStatus.SUCCESS,
            terminal_reason_codes=("STEP_PARTIAL_SUCCESS_FINALIZATION_AUTHORIZED",),
            degraded=True,
            observed_at=observation.observed_at,
            terminalized_at=NOW + timedelta(seconds=3),
            final_attempt_number=1,
            final_attempt_status="PARTIAL_SUCCESS",
            final_attempt_reason_codes=observation.reason_codes,
            execution_owner="SKILL",
            owner_capability_id="skill-001",
            owner_capability_version="1.0.0",
            skill_result={
                "skill_id": "skill-001",
                "status": "PARTIAL_SUCCESS",
                "business_outputs": [],
                "tool_results": [],
                "events": [],
                "error": None,
                "metadata": {},
            },
            has_unknown_tool_observation=True,
        )


def test_ambiguous_skill_and_workflow_owner_is_unknown() -> None:
    async def scenario() -> None:
        plan = _skill_plan()
        ambiguous_step = plan.steps[0].model_copy(
            update={"workflow_id": "workflow-001"}
        )
        plan = plan.model_copy(update={"steps": [ambiguous_step]})
        prepared, service, _ = await _running(plan)
        running = await service.start_step(
            prepared,
            step_id="step-001",
            at=NOW + timedelta(seconds=1),
        )
        completed = await RunningStepCompletionCoordinator(
            lifecycle_service=service
        ).complete(
            prepared=running,
            reliability_result=_partial_reliability_result(
                step_execution_id=running.steps[0].step_execution_id
            ),
            at=NOW + timedelta(seconds=3),
        )

        readiness, _ = project_ca01_evidence_inputs(approved_plan=plan, prepared=completed.prepared)

        assert readiness.status is AggregationEvidenceReadinessStatus.UNKNOWN
        assert readiness.reason_codes == (
            "AGGREGATION_EVIDENCE_STEP_OWNER_AMBIGUOUS",
        )

    asyncio.run(scenario())
