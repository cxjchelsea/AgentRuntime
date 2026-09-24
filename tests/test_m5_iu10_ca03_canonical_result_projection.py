"""CA-M5-IU10-03 Canonical ExecutionResult projection + cardinality gates."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest

import runtime.execution.aggregation_result as aggregation_result_module
from runtime.contracts import EXECUTION_RESULT_SCHEMA_VERSION, ExecutionPlanStatus
from runtime.execution.aggregation_authority import (
    AggregationControlApplicabilityDecision,
    AggregationControlApplicabilityStatus,
    ExecutionAggregationAuthority,
    ExecutionAggregationEligibilityStatus,
)
from runtime.execution.aggregation_evidence import (
    StepAggregationEvidence,
    project_ca01_evidence_inputs,
)
from runtime.execution.aggregation_result import (
    CanonicalExecutionResultProjector,
    ExecutionAggregationProjectionError,
    ExecutionAggregator,
)
from runtime.execution.capability_resolution import CapabilityExecutionOwner
from runtime.execution.control import (
    ExecutionControlSignal,
    ExecutionControlSignalType,
    LatchedExecutionControl,
)
from runtime.execution.foundation import (
    ApprovedPlanExecutionValidator,
    CallableExecutionIdentifierFactory,
    ExecutionContextBuilder,
    ExecutionFoundation,
    ExecutionLifecycleManager,
    ExecutionLifecycleService,
    ExecutionRecordFactory,
    InMemoryExecutionStateStore,
    PreparedExecution,
    StepLifecycleSnapshot,
)
from runtime.execution.models import (
    M5WorkflowResult,
    StepExecutionStatus,
    WorkflowExecutionStatus,
)
from runtime.execution.recovery_evidence import (
    DurableControlReadDecision,
    DurableControlReadStatus,
)
from runtime.execution.reliability_boundary import (
    StepFinalizationDecision,
    StepFinalizationDisposition,
    StepReliabilityDecision,
    StepReliabilityDisposition,
)
from runtime.execution.reliability_coordinator import StepReliabilityRunResult
from runtime.execution.result_collection import (
    StepAttemptObservation,
    StepAttemptStatus,
)
from runtime.execution.step_completion import RunningStepCompletionCoordinator
from tests.orchestration_stubs import (
    build_approved_action_plan,
    build_runtime_context,
)
from tests.test_m5_iu10_ca02_aggregation_evidence import (
    NOW,
    _partial_reliability_result,
    _running,
    _skill_plan,
    _workflow_observation as ca02_workflow_observation,
    _workflow_plan,
)


def _no_control() -> DurableControlReadDecision:
    return DurableControlReadDecision(
        status=DurableControlReadStatus.NONE,
        reason_codes=("NO_CONTROL",),
    )


def _no_control_applicability() -> AggregationControlApplicabilityDecision:
    return AggregationControlApplicabilityDecision(
        status=AggregationControlApplicabilityStatus.NONE,
        reason_codes=("CONTROL_NONE",),
    )


def _latched_control(
    *,
    execution_id: str,
    signal_type: ExecutionControlSignalType,
):
    signal = ExecutionControlSignal(
        signal_type=signal_type,
        reason_code="CONTROL_REASON",
        source="runtime",
        signal_id="signal-ca03",
        target_execution_id=execution_id,
        issued_at=NOW + timedelta(seconds=1),
    )
    latched = LatchedExecutionControl(
        signal=signal,
        observed_at=NOW + timedelta(seconds=2),
        latched_at=NOW + timedelta(seconds=3),
    )
    control = DurableControlReadDecision(
        status=DurableControlReadStatus.LATCHED,
        reason_codes=("CONTROL_LATCHED",),
        latched_control=latched,
    )
    applicability = AggregationControlApplicabilityDecision(
        status=AggregationControlApplicabilityStatus.APPLIES,
        reason_codes=("CONTROL_APPLIES",),
        latched_control=latched,
    )
    return control, applicability


def _persisted_step_payload(step: StepLifecycleSnapshot) -> dict[str, object]:
    payload: dict[str, object] = {
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
        "terminal_reason_codes": list(step.terminal_reason_codes),
        "degraded": step.degraded,
        "started_at": step.started_at,
        "finished_at": step.finished_at,
    }
    if step.aggregation_evidence is not None:
        payload["aggregation_evidence"] = step.aggregation_evidence.to_payload()
    return payload


async def _base_running(plan, *, execution_id: str) -> tuple[
    PreparedExecution,
    ExecutionLifecycleService,
]:
    ids = CallableExecutionIdentifierFactory(
        execution_id_factory=lambda: execution_id,
        step_execution_id_factory=lambda step_id: f"{execution_id}:{step_id}",
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
    created = await foundation.initialize(plan, build_runtime_context())
    service = ExecutionLifecycleService(
        lifecycle_manager=ExecutionLifecycleManager(),
        execution_store=store,
    )
    return await service.start_execution(created, at=NOW), service


def _multi_workflow_plan():
    base = build_approved_action_plan()
    source = base.steps[0]
    step_1 = source.model_copy(
        update={
            "step_id": "step-001",
            "action": "WORKFLOW_ACTION_1",
            "skill_id": None,
            "workflow_id": "workflow-001",
            "optional": False,
        }
    )
    step_2 = source.model_copy(
        update={
            "step_id": "step-002",
            "action": "WORKFLOW_ACTION_2",
            "skill_id": None,
            "workflow_id": "workflow-002",
            "depends_on": ["step-001"],
            "optional": False,
        }
    )
    return base.model_copy(
        update={
            "steps": [step_1, step_2],
            "capability_plan": {
                "bindings": [
                    {
                        "action_id": "WORKFLOW_ACTION_1",
                        "skill_id": None,
                        "skill_version": None,
                        "workflow_id": "workflow-001",
                        "workflow_version": "1.0.0",
                        "execution_owner": "WORKFLOW",
                    },
                    {
                        "action_id": "WORKFLOW_ACTION_2",
                        "skill_id": None,
                        "skill_version": None,
                        "workflow_id": "workflow-002",
                        "workflow_version": "2.0.0",
                        "execution_owner": "WORKFLOW",
                    },
                ],
                "selected_skills": [],
                "selected_workflows": ["workflow-001", "workflow-002"],
            },
            "tool_plan": {
                "tool_calls": [],
                "parallelizable": False,
                "required_success": False,
            },
        }
    )


def _workflow_observation(
    *,
    step: StepLifecycleSnapshot,
    workflow_id: str,
    workflow_version: str,
    instance_id: str,
    output_value: str,
    observed_offset: int,
) -> StepAttemptObservation:
    result = M5WorkflowResult(
        workflow_instance_id=instance_id,
        workflow_id=workflow_id,
        status=WorkflowExecutionStatus.COMPLETED,
        completed_steps=("node-001",),
        important_outputs={"value": output_value},
    )
    return StepAttemptObservation(
        step_id=step.step_id,
        step_execution_id=step.step_execution_id,
        attempt_number=1,
        status=StepAttemptStatus.SUCCESS,
        execution_owner=CapabilityExecutionOwner.WORKFLOW,
        reason_codes=("WORKFLOW_COMPLETED",),
        observed_at=NOW + timedelta(seconds=observed_offset),
        owner_capability_id=workflow_id,
        owner_capability_version=workflow_version,
        workflow_result=result,
        business_outputs=({"value": output_value},),
        capability_events=(),
        has_non_success_tool_observation=False,
        has_unknown_tool_observation=False,
        has_untrusted_success_observation=False,
    )


async def _multi_workflow_terminal():
    plan = _multi_workflow_plan()
    running, service = await _base_running(
        plan,
        execution_id="execution-iu10-ca03-workflows",
    )
    current = running
    specs = (
        ("step-001", "workflow-001", "1.0.0", "wf-instance-001", "first"),
        ("step-002", "workflow-002", "2.0.0", "wf-instance-002", "second"),
    )
    for index, (
        step_id,
        workflow_id,
        workflow_version,
        instance_id,
        output_value,
    ) in enumerate(specs, start=1):
        current = await service.start_step(
            current,
            step_id=step_id,
            at=NOW + timedelta(seconds=index * 2 - 1),
        )
        step = next(item for item in current.steps if item.step_id == step_id)
        observation = _workflow_observation(
            step=step,
            workflow_id=workflow_id,
            workflow_version=workflow_version,
            instance_id=instance_id,
            output_value=output_value,
            observed_offset=index * 2,
        )
        reliability = StepReliabilityRunResult(
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
        current = (
            await RunningStepCompletionCoordinator(
                lifecycle_service=service
            ).complete(
                prepared=current,
                reliability_result=reliability,
                at=NOW + timedelta(seconds=index * 2),
            )
        ).prepared

    completed = await service.finish_execution(
        current,
        status=ExecutionPlanStatus.SUCCESS,
        at=NOW + timedelta(seconds=5),
    )
    return plan, completed


async def _control_terminal(
    signal_type: ExecutionControlSignalType,
):
    plan = build_approved_action_plan().model_copy(
        update={
            "steps": [
                build_approved_action_plan().steps[0].model_copy(
                    update={
                        "action": "CONTROLLED_ACTION",
                        "skill_id": None,
                        "workflow_id": None,
                        "optional": False,
                    }
                )
            ]
        }
    )
    running, _ = await _base_running(
        plan,
        execution_id=f"execution-iu10-ca03-{signal_type.value.lower()}",
    )
    source = running.steps[0]
    step_status = {
        ExecutionControlSignalType.CANCEL: StepExecutionStatus.CANCELLED,
        ExecutionControlSignalType.PREEMPT: StepExecutionStatus.PREEMPTED,
    }[signal_type]
    plan_status = {
        ExecutionControlSignalType.CANCEL: ExecutionPlanStatus.CANCELLED,
        ExecutionControlSignalType.PREEMPT: ExecutionPlanStatus.PREEMPTED,
    }[signal_type]
    terminal_at = NOW + timedelta(seconds=4)
    evidence = StepAggregationEvidence.from_control_terminalization(
        execution_id=running.execution_record.execution_id,
        step=source,
        terminal_step_status=step_status,
        terminal_reason_codes=("CONTROL_SAFE_BOUNDARY_CONFIRMED",),
        terminalized_at=terminal_at,
    )
    terminal_step = replace(
        source,
        status=step_status,
        terminal_reason_codes=("CONTROL_SAFE_BOUNDARY_CONFIRMED",),
        aggregation_evidence=evidence,
        finished_at=terminal_at,
    )
    prepared = replace(
        running,
        steps=(terminal_step,),
        finished_at=terminal_at,
        execution_record=replace(
            running.execution_record,
            status=plan_status.value,
            current_step=None,
            step_results=(_persisted_step_payload(terminal_step),),
            updated_at=terminal_at,
        ),
    )
    control, applicability = _latched_control(
        execution_id=prepared.execution_record.execution_id,
        signal_type=signal_type,
    )
    return plan, prepared, control, applicability


def _ready_eligibility(
    *,
    plan,
    prepared,
    control,
    applicability,
):
    evidence, skips = project_ca01_evidence_inputs(
        approved_plan=plan,
        prepared=prepared,
    )
    return ExecutionAggregationAuthority().evaluate(
        approved_plan=plan,
        prepared=prepared,
        control=control,
        control_applicability=applicability,
        evidence_readiness=evidence,
        skip_decisions=skips,
    )


def test_natural_aggregation_commits_once_then_replays_identically() -> None:
    async def scenario() -> None:
        plan = _skill_plan()
        prepared, service, store = await _running(plan)
        running_step = await service.start_step(
            prepared,
            step_id="step-001",
            at=NOW + timedelta(seconds=1),
        )
        step_done = (
            await RunningStepCompletionCoordinator(
                lifecycle_service=service
            ).complete(
                prepared=running_step,
                reliability_result=_partial_reliability_result(
                    step_execution_id=running_step.steps[0].step_execution_id
                ),
                at=NOW + timedelta(seconds=3),
            )
        ).prepared

        aggregator = ExecutionAggregator(
            authority=ExecutionAggregationAuthority(),
            lifecycle_service=service,
            projector=CanonicalExecutionResultProjector(),
        )
        first = await aggregator.aggregate(
            approved_plan=plan,
            prepared=step_done,
            control=_no_control(),
            control_applicability=_no_control_applicability(),
            at=NOW + timedelta(seconds=4),
        )

        assert (
            first.eligibility.status
            is ExecutionAggregationEligibilityStatus.READY_EXISTING_TERMINAL
        )
        assert first.execution_result.plan_status is ExecutionPlanStatus.PARTIAL_SUCCESS
        assert first.execution_result.schema_version == EXECUTION_RESULT_SCHEMA_VERSION
        assert first.execution_result.skill_results is not None
        assert len(first.execution_result.skill_results) == 1
        assert first.execution_result.workflow_result is None
        assert first.execution_result.workflow_results == []
        assert first.execution_result.tool_results is not None
        assert len(first.execution_result.tool_results) == 1
        assert first.execution_result.business_outputs == [
            {"kind": "partial-output"}
        ]
        assert first.execution_result.execution_events == [
            {"event": "skill-partial"}
        ]
        assert first.execution_result.state_observations == []
        assert first.execution_result.quality is not None
        assert first.execution_result.quality["degraded"] is True

        persisted = await store.load(first.prepared.execution_record.execution_id)
        assert persisted is not None
        assert persisted.status == ExecutionPlanStatus.PARTIAL_SUCCESS.value

        replay = await aggregator.aggregate(
            approved_plan=plan,
            prepared=first.prepared,
            control=_no_control(),
            control_applicability=_no_control_applicability(),
            at=NOW + timedelta(seconds=10),
        )
        assert replay.prepared == first.prepared
        assert (
            replay.execution_result.model_dump(mode="python")
            == first.execution_result.model_dump(mode="python")
        )

    asyncio.run(scenario())


def test_multiple_workflows_are_lossless_and_legacy_field_is_not_ambiguous() -> None:
    async def scenario() -> None:
        plan, prepared = await _multi_workflow_terminal()
        control = _no_control()
        applicability = _no_control_applicability()
        eligibility = _ready_eligibility(
            plan=plan,
            prepared=prepared,
            control=control,
            applicability=applicability,
        )
        assert (
            eligibility.status
            is ExecutionAggregationEligibilityStatus.READY_EXISTING_TERMINAL
        )

        result = CanonicalExecutionResultProjector().project(
            approved_plan=plan,
            prepared=prepared,
            eligibility=eligibility,
            control=control,
            control_applicability=applicability,
        )

        assert result.workflow_result is None
        assert result.workflow_results is not None
        assert [item["workflow_id"] for item in result.workflow_results] == [
            "workflow-001",
            "workflow-002",
        ]
        assert [item["workflow_instance_id"] for item in result.workflow_results] == [
            "wf-instance-001",
            "wf-instance-002",
        ]
        assert result.business_outputs == [
            {"value": "first"},
            {"value": "second"},
        ]

    asyncio.run(scenario())


def test_single_workflow_populates_both_legacy_and_plural_fields() -> None:
    async def scenario() -> None:
        plan = _workflow_plan()
        prepared, service, _ = await _running(plan)
        running = await service.start_step(
            prepared,
            step_id="step-001",
            at=NOW + timedelta(seconds=1),
        )
        observation = ca02_workflow_observation(
            step_execution_id=running.steps[0].step_execution_id
        )
        reliability = StepReliabilityRunResult(
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
        step_done = (
            await RunningStepCompletionCoordinator(
                lifecycle_service=service
            ).complete(
                prepared=running,
                reliability_result=reliability,
                at=NOW + timedelta(seconds=3),
            )
        ).prepared
        completed = await service.finish_execution(
            step_done,
            status=ExecutionPlanStatus.SUCCESS,
            at=NOW + timedelta(seconds=4),
        )

        control = _no_control()
        applicability = _no_control_applicability()
        eligibility = _ready_eligibility(
            plan=plan,
            prepared=completed,
            control=control,
            applicability=applicability,
        )
        result = CanonicalExecutionResultProjector().project(
            approved_plan=plan,
            prepared=completed,
            eligibility=eligibility,
            control=control,
            control_applicability=applicability,
        )

        assert result.workflow_results is not None
        assert len(result.workflow_results) == 1
        assert result.workflow_result == result.workflow_results[0]
        assert result.workflow_result["workflow_id"] == "workflow-001"

    asyncio.run(scenario())

@pytest.mark.parametrize(
    ("signal_type", "expected_status", "cancelled", "preempted"),
    [
        (
            ExecutionControlSignalType.CANCEL,
            ExecutionPlanStatus.CANCELLED,
            True,
            False,
        ),
        (
            ExecutionControlSignalType.PREEMPT,
            ExecutionPlanStatus.PREEMPTED,
            False,
            True,
        ),
    ],
)
def test_control_result_projects_exact_durable_provenance(
    signal_type: ExecutionControlSignalType,
    expected_status: ExecutionPlanStatus,
    cancelled: bool,
    preempted: bool,
) -> None:
    async def scenario() -> None:
        plan, prepared, control, applicability = await _control_terminal(signal_type)
        eligibility = _ready_eligibility(
            plan=plan,
            prepared=prepared,
            control=control,
            applicability=applicability,
        )
        result = CanonicalExecutionResultProjector().project(
            approved_plan=plan,
            prepared=prepared,
            eligibility=eligibility,
            control=control,
            control_applicability=applicability,
        )

        assert result.plan_status is expected_status
        assert result.cancellation is not None
        assert result.cancellation["signal_type"] == signal_type.value
        assert result.cancellation["signal_id"] == "signal-ca03"
        assert result.cancellation["reason_code"] == "CONTROL_REASON"
        assert result.cancellation["source"] == "runtime"
        assert result.cancellation["cancelled"] is cancelled
        assert result.cancellation["preempted"] is preempted

    asyncio.run(scenario())


def test_control_terminal_result_rejects_missing_provenance() -> None:
    async def scenario() -> None:
        plan, prepared, control, applicability = await _control_terminal(
            ExecutionControlSignalType.CANCEL
        )
        eligibility = _ready_eligibility(
            plan=plan,
            prepared=prepared,
            control=control,
            applicability=applicability,
        )

        with pytest.raises(
            ExecutionAggregationProjectionError,
            match="EXECUTION_RESULT_CONTROL_PROVENANCE_MISSING",
        ):
            CanonicalExecutionResultProjector().project(
                approved_plan=plan,
                prepared=prepared,
                eligibility=eligibility,
                control=_no_control(),
                control_applicability=_no_control_applicability(),
            )

    asyncio.run(scenario())


def test_projector_rejects_non_ready_aggregation() -> None:
    async def scenario() -> None:
        plan = _skill_plan()
        prepared, _, _ = await _running(plan)
        evidence, skips = project_ca01_evidence_inputs(
            approved_plan=plan,
            prepared=prepared,
        )
        eligibility = ExecutionAggregationAuthority().evaluate(
            approved_plan=plan,
            prepared=prepared,
            control=_no_control(),
            control_applicability=_no_control_applicability(),
            evidence_readiness=evidence,
            skip_decisions=skips,
        )
        assert eligibility.status is ExecutionAggregationEligibilityStatus.WAITING

        with pytest.raises(
            ExecutionAggregationProjectionError,
            match="EXECUTION_RESULT_AGGREGATION_NOT_READY",
        ):
            CanonicalExecutionResultProjector().project(
                approved_plan=plan,
                prepared=prepared,
                eligibility=eligibility,
                control=_no_control(),
                control_applicability=_no_control_applicability(),
            )

    asyncio.run(scenario())


def test_ca03_has_no_execution_or_downstream_authority_leak() -> None:
    source = inspect.getsource(aggregation_result_module)

    forbidden = (
        "runtime.validation",
        "runtime.response",
        "runtime.update",
        "runtime.registries",
        "runtime.knowledge",
        ".invoke(",
        ".resume(",
        ".retry(",
        "requests",
        "httpx",
    )
    for token in forbidden:
        assert token not in source
