"""M5 stage-level Closure evidence harness.

This file does not create a second M5 execution semantics. It composes the
already-frozen IU1-IU10 runtime/test authorities into stage-level closure
scenarios and adds only stage-boundary assertions.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
from datetime import timedelta

import runtime.execution.aggregation_runtime as aggregation_runtime_module
import runtime.execution.capability_execution as capability_execution_module
import runtime.execution.recovery_runtime as recovery_runtime_module
import runtime.execution.result_collection as result_collection_module
import runtime.execution.runtime_check as runtime_check_module
import runtime.execution.scheduler as scheduler_module
from runtime.contracts.enums import ExecutionPlanStatus
from runtime.execution.aggregation_runtime import M5ExecutionAggregationRuntimeStatus
from runtime.execution.capability_resolution import CapabilityExecutionOwner
from runtime.execution.control import ExecutionControlSignalType
from runtime.execution.models import StepExecutionStatus
from runtime.execution.reliability_boundary import (
    StepFinalizationDecision,
    StepFinalizationDisposition,
    StepReliabilityDecision,
    StepReliabilityDisposition,
)
from runtime.execution.reliability_coordinator import StepReliabilityRunResult
from runtime.execution.result_collection import StepResultCollector
from tests import test_m5_iu4_capability_execution as iu4
from tests import test_m5_iu5_result_collection as iu5
from tests import test_m5_iu6_formal_implementation as iu6
from tests import test_m5_iu7_formal_implementation as iu7
from tests import test_m5_iu8_formal_implementation as iu8
from tests import test_m5_iu9_formal_implementation as iu9
from tests import test_m5_iu10_formal_implementation as iu10
from tests.test_m5_iu10_ca02_aggregation_evidence import NOW, _running


M5_GATE_IDS = tuple(f"M5-{index:02d}" for index in range(1, 26))

M5_GATE_EVIDENCE: dict[str, tuple[str, ...]] = {
    "M5-01": (
        ("tests/test_m5_iu1_execution_foundation.py::"\n        "test_execution_foundation_initializes_and_persists_without_executing_capability"),
        ("tests/test_m5_iu1_execution_foundation.py::"\n        "test_approved_plan_execution_validator_rejects_unsupported_schema"),
    ),
    "M5-02": (
        ("tests/test_m5_iu10_formal_implementation.py::"\n        "test_formal_runtime_completes_partial_success_and_publishes_canonical_result"),
    ),
    "M5-03": (
        ("tests/test_m5_iu1_execution_foundation.py::"\n        "test_step_lifecycle_is_independent_and_deterministic"),
    ),
    "M5-04": (
        ("tests/test_m5_iu4_capability_execution.py::"\n        "test_skill_owner_executes_exact_skill_and_approved_tool_once"),
        ("tests/test_m5_iu4_capability_execution.py::"\n        "test_workflow_owner_starts_fresh_workflow_and_never_resumes"),
    ),
    "M5-05": (
        ("tests/test_m5_iu4_capability_execution.py::"\n        "test_input_invalid_prevents_permission_and_tool_invocation"),
        ("tests/test_m5_iu4_capability_execution.py::"\n        "test_output_invalid_preserves_raw_success_but_final_truth_is_unknown"),
    ),
    "M5-06": (
        ("tests/test_m5_iu6_formal_implementation.py::"\n        "test_finalization_only_maps_authorized_terminal_statuses"),
        ("tests/test_m5_iu8_formal_implementation.py::"\n        "test_reliability_timeout_keeps_exact_tool_handle_and_resource_lease"),
    ),
    "M5-07": (
        ("tests/test_m5_iu4_capability_execution.py::"\n        "test_non_success_tool_result_is_not_output_validated_or_upgraded"),
        ("tests/test_m5_iu5_result_collection.py::"\n        "test_tool_unknown_is_second_latch_against_executed_owner_success"),
    ),
    "M5-08": (
        ("tests/test_m5_iu6_formal_implementation.py::"\n        "test_retry_evaluator_requires_safe_replay_and_budget"),
    ),
    "M5-09": (
        ("tests/test_m5_iu6_formal_implementation.py::"\n        "test_inmemory_idempotency_completion_is_atomic_and_recoverable"),
        ("tests/test_m5_iu10_formal_implementation.py::"\n        "test_core_tool_invoker_persists_logical_result_before_returning"),
    ),
    "M5-10": (
        "CORE_MECHANISM: M5-09 idempotency + domain help_event_id key",
    ),
    "M5-11": (
        ("tests/test_m5_iu7_formal_implementation.py::"\n        "test_formal_cancel_path_interrupts_owner_and_terminalizes_execution"),
    ),
    "M5-12": (
        ("tests/test_m5_iu7_formal_implementation.py::"\n        "test_preempt_pending_only_sets_handoff_without_starting_runtime_cycle"),
    ),
    "M5-13": (
        ("tests/test_m5_iu9_formal_implementation.py::"\n        "test_recovery_runtime_reenters_existing_scheduler_without_selecting_capability"),
        "tests/test_m5_closure.py::test_m5_closure_c10_preserves_stage_boundaries",
    ),
    "M5-14": (
        ("tests/test_m5_iu3_capability_resolution.py::"\n        "test_other_enabled_version_is_never_substituted_for_approved_version"),
        ("tests/test_m5_iu3_capability_resolution.py::"\n        "test_mutated_step_cannot_gain_capability_authority"),
    ),
    "M5-15": (
        "tests/test_m5_closure.py::test_m5_closure_c10_preserves_stage_boundaries",
    ),
    "M5-16": (
        "tests/test_m5_closure.py::test_m5_closure_c10_preserves_stage_boundaries",
    ),
    "M5-17": (
        "tests/test_m5_closure.py::test_m5_closure_c10_preserves_stage_boundaries",
    ),
    "M5-18": (
        ("tests/test_m5_iu9_formal_implementation.py::"\n        "test_workflow_resume_uses_exact_instance_version_and_current_epoch"),
    ),
    "M5-19": (
        ("tests/test_m5_iu6_formal_implementation.py::"\n        "test_key_based_step_replay_without_tool_evidence_is_unknown"),
        ("tests/test_m5_iu9_formal_implementation.py::"\n        "test_stale_recovery_epoch_blocks_skill_before_owner_side_effect"),
        ("tests/test_m5_iu10_formal_implementation.py::"\n        "test_recovered_current_attempt_tool_call_id_collision_blocks_before_physical_invoke"),
    ),
    "M5-20": (
        ("tests/test_m5_closure.py::"\n        "test_m5_closure_c01_capability_collection_and_canonical_aggregation"),
    ),
    "M5-21": (
        ("tests/test_m5_iu8_formal_implementation.py::"\n        "test_session_busy_blocks_step_before_skill_side_effect"),
    ),
    "M5-22": (
        ("tests/test_m5_iu8_formal_implementation.py::"\n        "test_baseline_tool_path_blocks_competing_resource_and_releases_on_completion"),
        ("tests/test_m5_iu8_formal_implementation.py::"\n        "test_reliability_retry_reenters_exact_tool_lock_boundary_each_attempt"),
    ),
    "M5-23": (
        "BOUNDARY_ONLY: Ongoing Activity is outside Execution lifecycle authority",
        "tests/test_m5_closure.py::test_m5_closure_c10_preserves_stage_boundaries",
    ),
    "M5-24": (
        ("tests/test_m5_iu4_capability_execution.py::"\n        "test_permission_is_rechecked_for_each_real_tool_invocation"),
        ("tests/test_m5_iu4_capability_execution.py::"\n        "test_permission_denied_prevents_tool_invocation"),
    ),
    "M5-25": (
        ("tests/test_m5_iu4_capability_execution.py::"\n        "test_output_invalid_preserves_raw_success_but_final_truth_is_unknown"),
        ("tests/test_m5_iu5_result_collection.py::"\n        "test_tool_unknown_is_second_latch_against_executed_owner_success"),
    ),
}


def test_m5_closure_gate_manifest_covers_exactly_m5_01_through_m5_25() -> None:
    assert tuple(M5_GATE_EVIDENCE) == M5_GATE_IDS
    assert all(M5_GATE_EVIDENCE[gate_id] for gate_id in M5_GATE_IDS)


def test_m5_closure_gate_evidence_nodeids_resolve() -> None:
    for evidence_items in M5_GATE_EVIDENCE.values():
        for evidence in evidence_items:
            if not evidence.startswith("tests/"):
                continue
            path, separator, test_name = evidence.partition("::")
            assert separator == "::"
            module_name = path.removesuffix(".py").replace("/", ".")
            module = importlib.import_module(module_name)
            candidate = getattr(module, test_name, None)
            assert callable(candidate), evidence


def test_m5_closure_c01_capability_collection_and_canonical_aggregation() -> None:
    async def scenario() -> None:
        plan, step = iu4._approved_step(owner=CapabilityExecutionOwner.SKILL)
        plan = plan.model_copy(
            update={
                "tool_plan": {
                    "tool_calls": [
                        {
                            "tool_id": "DOMAIN_TOOL",
                            "tool_version": "1.0.0",
                            "required": True,
                            "required_by_skills": ["DOMAIN_SKILL"],
                            "required_by_workflows": [],
                            "timeout_policy": None,
                            "retry_policy": None,
                            "idempotency_mode": None,
                            "side_effect_level": None,
                        }
                    ],
                    "parallelizable": False,
                    "required_success": True,
                }
            }
        )
        tool_impl = iu4.RecordingTool()
        skill_impl = iu4.RecordingSkill(tool_ids=("DOMAIN_TOOL",))
        resolved = iu4._skill_resolved(skill_impl, tools=(iu4._tool(tool_impl),))

        prepared, service, _ = await _running(plan)
        running = await service.start_step(
            prepared,
            step_id=step.step_id,
            at=NOW + timedelta(seconds=1),
        )
        snapshot = running.steps[0]

        executor = iu4._executor()
        capability_outcome = await executor.execute(
            approved_plan=plan,
            step=step,
            step_snapshot=snapshot,
            resolved=resolved,
            execution_context=running.execution_context,
        )
        assert capability_outcome.status.value == "EXECUTED"
        assert tool_impl.calls == 1

        observation = StepResultCollector().collect(
            step_snapshot=snapshot,
            outcome=capability_outcome,
            attempt_number=1,
            observed_at=NOW + timedelta(seconds=2),
        )
        assert observation.status.value == "SUCCESS"
        assert observation.tool_results == capability_outcome.tool_results

        reliability = StepReliabilityRunResult(
            attempts=(observation,),
            reliability_decision=StepReliabilityDecision(
                disposition=StepReliabilityDisposition.FINALIZE,
                reason_codes=("M5_CLOSURE_FINALIZE",),
            ),
            finalization_decision=StepFinalizationDecision(
                disposition=StepFinalizationDisposition.FINALIZE,
                reason_codes=("M5_CLOSURE_TERMINAL",),
                terminal_status=StepExecutionStatus.SUCCESS,
            ),
        )
        runtime, _, _, _ = iu10._runtime(lifecycle_service=service)
        final = await runtime.complete_running_step(
            approved_plan=plan,
            prepared=running,
            reliability_result=reliability,
            at=NOW + timedelta(seconds=3),
        )

        assert final.status is M5ExecutionAggregationRuntimeStatus.AGGREGATED
        assert final.aggregation_result is not None
        result = final.aggregation_result.execution_result
        assert result.plan_status is ExecutionPlanStatus.SUCCESS
        assert result.plan_id == plan.plan_id
        assert result.request_id == plan.request_id
        assert result.tool_results is not None
        assert len(result.tool_results) == 1
        assert result.tool_results[0]["tool_id"] == "DOMAIN_TOOL"

    asyncio.run(scenario())


def test_m5_closure_c02_multistep_and_degraded_aggregation() -> None:
    iu10.test_formal_runtime_completes_partial_success_and_publishes_canonical_result()
    iu10.test_formal_runtime_closes_required_failure_remainder_before_failed_aggregation()


def test_m5_closure_c03_retry_idempotency_and_lock_boundaries() -> None:
    iu6.test_retry_evaluator_requires_safe_replay_and_budget()
    iu6.test_inmemory_idempotency_completion_is_atomic_and_recoverable()
    iu8.test_reliability_retry_reenters_exact_tool_lock_boundary_each_attempt()


def test_m5_closure_c04_cancellation_cleanup_and_terminal_truth() -> None:
    iu7.test_formal_cancel_path_interrupts_owner_and_terminalizes_execution()
    iu8.test_confirmed_stop_control_cleans_tool_lock_before_terminalization()
    iu10.test_formal_runtime_uses_durable_control_applicability_for_terminal_result(
        ExecutionControlSignalType.CANCEL,
        ExecutionPlanStatus.CANCELLED,
    )


def test_m5_closure_c05_preemption_does_not_start_new_runtime_cycle() -> None:
    iu7.test_preempt_pending_only_sets_handoff_without_starting_runtime_cycle()
    iu9.test_recovery_runtime_reenters_existing_scheduler_without_selecting_capability()


def test_m5_closure_c06_session_and_resource_contention_fail_closed() -> None:
    iu8.test_session_busy_blocks_step_before_skill_side_effect()
    iu8.test_baseline_tool_path_blocks_competing_resource_and_releases_on_completion()


def test_m5_closure_c07_crash_recovery_reenters_existing_authorities() -> None:
    iu9.test_recovered_skill_retry_claims_next_attempt_through_iu6_authority()
    iu10.test_recovered_workflow_resume_reuses_current_attempt_and_enters_iu10_completion()


def test_m5_closure_c08_unknown_side_effect_never_becomes_safe_or_success() -> None:
    iu6.test_key_based_step_replay_without_tool_evidence_is_unknown()
    iu4.test_output_invalid_preserves_raw_success_but_final_truth_is_unknown()
    iu5.test_tool_unknown_is_second_latch_against_executed_owner_success()
    iu9.test_stale_recovery_epoch_blocks_skill_before_owner_side_effect()


def test_m5_closure_c09_terminal_replay_is_durable_and_deterministic() -> None:
    iu10.test_formal_runtime_existing_terminal_replay_is_identical()
    iu10.test_formal_control_projection_reads_durable_current_attempt_not_retry_count()
    iu10.test_recovered_current_attempt_tool_call_id_collision_blocks_before_physical_invoke()


def test_m5_closure_c10_preserves_stage_boundaries() -> None:
    modules = (
        capability_execution_module,
        result_collection_module,
        runtime_check_module,
        scheduler_module,
        recovery_runtime_module,
        aggregation_runtime_module,
    )
    source = "\n".join(inspect.getsource(module) for module in modules)

    forbidden_imports = (
        "runtime.validation",
        "runtime.response",
        "runtime.memory",
        "runtime.state_memory",
    )
    for forbidden in forbidden_imports:
        assert forbidden not in source

    aggregation_source = inspect.getsource(aggregation_runtime_module)
    assert "StaticAggregationControlAuthority" not in aggregation_source
    assert "CanonicalExecutionResultProjector(" in aggregation_source
    assert "DurableAggregationControlAuthority(" in aggregation_source
    assert "ExecutionLifecycleService.finish_execution" not in inspect.getsource(
        scheduler_module
    )
    recovery_source = inspect.getsource(recovery_runtime_module)
    forbidden_recovery_imports = (
        "from runtime.planning",
        "import runtime.planning",
        "from runtime.registries",
        "import runtime.registries",
    )
    for forbidden in forbidden_recovery_imports:
        assert forbidden not in recovery_source
