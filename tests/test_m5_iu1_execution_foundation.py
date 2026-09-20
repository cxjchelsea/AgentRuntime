"""M5-IU1 Execution Foundation gates."""

from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime, timedelta

import pytest

import runtime.execution.foundation as foundation_module
from runtime.contracts import ExecutionPlanStatus, RuntimeControlState
from runtime.contracts.context import TaskContext, ToolContext
from runtime.execution import (
    ApprovedPlanExecutionError,
    ApprovedPlanExecutionValidator,
    CallableExecutionIdentifierFactory,
    ExecutionContextBuildError,
    ExecutionContextBuilder,
    ExecutionFoundation,
    ExecutionLifecycleError,
    ExecutionLifecycleManager,
    ExecutionRecordFactory,
    ExecutionResultProjector,
    InMemoryExecutionStateStore,
    StepExecutionStatus,
)
from tests.orchestration_stubs import (
    build_approved_action_plan,
    build_runtime_context,
)


FIXED_TIME = datetime(2026, 9, 20, 7, 30, tzinfo=UTC)


def _identifier_factory(
    execution_id: str = "execution-iu1-001",
) -> CallableExecutionIdentifierFactory:
    return CallableExecutionIdentifierFactory(
        execution_id_factory=lambda: execution_id,
        step_execution_id_factory=lambda step_id: f"{execution_id}:{step_id}",
    )


def _foundation(
    *,
    execution_id: str = "execution-iu1-001",
) -> tuple[ExecutionFoundation, InMemoryExecutionStateStore]:
    ids = _identifier_factory(execution_id)
    store = InMemoryExecutionStateStore()
    foundation = ExecutionFoundation(
        plan_validator=ApprovedPlanExecutionValidator(),
        context_builder=ExecutionContextBuilder(identifier_factory=ids),
        record_factory=ExecutionRecordFactory(
            identifier_factory=ids,
            clock=lambda: FIXED_TIME,
        ),
        execution_store=store,
    )
    return foundation, store


def test_execution_foundation_initializes_and_persists_without_executing_capability() -> None:
    foundation, store = _foundation()

    prepared = asyncio.run(
        foundation.initialize(
            build_approved_action_plan(),
            build_runtime_context(),
        )
    )

    assert prepared.execution_context.execution_id == "execution-iu1-001"
    assert prepared.execution_record.status == "CREATED"
    assert prepared.execution_record.identity_scope == "scope-001"
    assert len(prepared.steps) == 1
    assert prepared.steps[0].status is StepExecutionStatus.PENDING

    persisted = asyncio.run(store.load("execution-iu1-001"))
    assert persisted == prepared.execution_record


def test_m5_context_builder_projects_minimum_runtime_context_only() -> None:
    plan = build_approved_action_plan().model_copy(
        update={"trace": {"planning_path": "DETERMINISTIC"}}
    )
    runtime_context = build_runtime_context().model_copy(
        update={
            "task_context": TaskContext(
                timeout_at=FIXED_TIME + timedelta(minutes=5)
            ),
            "tool_context": ToolContext(network_status="ONLINE"),
        }
    )
    builder = ExecutionContextBuilder(
        identifier_factory=_identifier_factory()
    )

    context = builder.build(plan, runtime_context)

    assert context.plan_id == plan.plan_id
    assert context.request_id == plan.request_id
    assert context.session_id == "session-001"
    assert context.identity_scope == "scope-001"
    assert context.current_state is RuntimeControlState.IDLE
    assert context.cancellation_token == "execution-iu1-001"
    assert context.deadline is None
    assert context.trace_context is None
    assert context.tool_context == {
        "active_tool_calls": None,
        "recent_tool_results": None,
        "network_status": "ONLINE",
    }
    assert "conversation_context" not in context.__class__.model_fields
    assert "memory_context" not in context.__class__.model_fields


def test_deadline_and_trace_projection_require_explicit_resolvers() -> None:
    plan = build_approved_action_plan().model_copy(
        update={"trace": {"planning_path": "DETERMINISTIC"}}
    )
    runtime_context = build_runtime_context().model_copy(
        update={
            "task_context": TaskContext(
                timeout_at=FIXED_TIME + timedelta(minutes=5)
            )
        }
    )
    builder = ExecutionContextBuilder(
        identifier_factory=_identifier_factory(),
        deadline_resolver=lambda approved_plan, context: (
            context.task_context.timeout_at
            if context.task_context is not None
            else None
        ),
        trace_context_resolver=lambda approved_plan, context: {
            "source": "injected-execution-trace",
            "plan_id": approved_plan.plan_id,
        },
    )

    context = builder.build(plan, runtime_context)

    assert context.deadline == FIXED_TIME + timedelta(minutes=5)
    assert context.trace_context == {
        "source": "injected-execution-trace",
        "plan_id": plan.plan_id,
    }


def test_approved_plan_execution_validator_rejects_unsupported_schema() -> None:
    plan = build_approved_action_plan().model_copy(
        update={"schema_version": "9.9.9"}
    )

    with pytest.raises(ApprovedPlanExecutionError, match="schema_version"):
        ApprovedPlanExecutionValidator().validate(plan)


def test_approved_plan_execution_validator_rejects_non_prior_dependency() -> None:
    plan = build_approved_action_plan()
    step = plan.steps[0].model_copy(update={"depends_on": ["future-step"]})
    plan = plan.model_copy(update={"steps": [step]})

    with pytest.raises(ApprovedPlanExecutionError, match="dependencies"):
        ApprovedPlanExecutionValidator().validate(plan)


def test_step_execution_ids_must_be_unique_within_execution() -> None:
    ids = CallableExecutionIdentifierFactory(
        execution_id_factory=lambda: "execution-duplicate-step-id",
        step_execution_id_factory=lambda step_id: "same-step-execution-id",
    )
    plan = build_approved_action_plan()
    second = plan.steps[0].model_copy(
        update={
            "step_id": "step-002",
            "depends_on": ["step-001"],
        }
    )
    plan = plan.model_copy(update={"steps": [plan.steps[0], second]})
    foundation = ExecutionFoundation(
        plan_validator=ApprovedPlanExecutionValidator(),
        context_builder=ExecutionContextBuilder(identifier_factory=ids),
        record_factory=ExecutionRecordFactory(
            identifier_factory=ids,
            clock=lambda: FIXED_TIME,
        ),
        execution_store=InMemoryExecutionStateStore(),
    )

    with pytest.raises(ExecutionContextBuildError, match="unique"):
        asyncio.run(foundation.initialize(plan, build_runtime_context()))


def test_execution_id_collision_fails_closed_before_overwrite() -> None:
    foundation, store = _foundation(execution_id="execution-collision")
    plan = build_approved_action_plan()
    context = build_runtime_context()

    asyncio.run(foundation.initialize(plan, context))

    with pytest.raises(ExecutionLifecycleError, match="already exists"):
        asyncio.run(foundation.initialize(plan, context))

    persisted = asyncio.run(store.load("execution-collision"))
    assert persisted is not None
    assert persisted.plan_id == plan.plan_id




def test_execution_creation_is_atomic_for_duplicate_execution_id() -> None:
    foundation, store = _foundation(execution_id="execution-atomic")
    plan = build_approved_action_plan()
    context = build_runtime_context()

    async def run_both() -> tuple[object, object]:
        results = await asyncio.gather(
            foundation.initialize(plan, context),
            foundation.initialize(plan, context),
            return_exceptions=True,
        )
        return results[0], results[1]

    first, second = asyncio.run(run_both())
    outcomes = (first, second)

    assert sum(not isinstance(item, Exception) for item in outcomes) == 1
    assert sum(isinstance(item, ExecutionLifecycleError) for item in outcomes) == 1
    persisted = asyncio.run(store.load("execution-atomic"))
    assert persisted is not None
    assert persisted.execution_id == "execution-atomic"

def test_in_memory_store_does_not_rebind_execution_identity_scope() -> None:
    foundation, store = _foundation(execution_id="execution-scope")
    prepared = asyncio.run(
        foundation.initialize(
            build_approved_action_plan(),
            build_runtime_context(),
        )
    )
    rebound = prepared.execution_record.__class__(
        execution_id=prepared.execution_record.execution_id,
        plan_id=prepared.execution_record.plan_id,
        request_id=prepared.execution_record.request_id,
        identity_scope="other-scope",
        status=prepared.execution_record.status,
        current_step=prepared.execution_record.current_step,
        step_results=prepared.execution_record.step_results,
        created_at=prepared.execution_record.created_at,
        updated_at=prepared.execution_record.updated_at,
    )

    with pytest.raises(ExecutionLifecycleError, match="rebound"):
        asyncio.run(store.save(rebound))




def test_execution_start_time_is_distinct_from_record_creation_time() -> None:
    foundation, _ = _foundation()
    prepared = asyncio.run(
        foundation.initialize(
            build_approved_action_plan(),
            build_runtime_context(),
        )
    )
    lifecycle = ExecutionLifecycleManager()
    start_time = FIXED_TIME + timedelta(seconds=5)

    running = lifecycle.start_execution(prepared, at=start_time)

    assert running.execution_record.created_at == FIXED_TIME
    assert running.started_at == start_time


def test_execution_cannot_start_before_creation_time() -> None:
    foundation, _ = _foundation()
    prepared = asyncio.run(
        foundation.initialize(
            build_approved_action_plan(),
            build_runtime_context(),
        )
    )

    with pytest.raises(ExecutionLifecycleError, match="before creation"):
        ExecutionLifecycleManager().start_execution(
            prepared,
            at=FIXED_TIME - timedelta(seconds=1),
        )

def test_step_lifecycle_is_independent_and_deterministic() -> None:
    foundation, _ = _foundation()
    prepared = asyncio.run(
        foundation.initialize(
            build_approved_action_plan(),
            build_runtime_context(),
        )
    )
    lifecycle = ExecutionLifecycleManager()

    running = lifecycle.start_execution(prepared, at=FIXED_TIME)
    step_running = lifecycle.start_step(
        running,
        step_id="step-001",
        at=FIXED_TIME + timedelta(seconds=1),
    )
    step_done = lifecycle.finish_step(
        step_running,
        step_id="step-001",
        status=StepExecutionStatus.SUCCESS,
        at=FIXED_TIME + timedelta(seconds=2),
        output={"observed": True},
        tool_call_ids=("tool-call-001",),
    )
    completed = lifecycle.finish_execution(
        step_done,
        status=ExecutionPlanStatus.SUCCESS,
        at=FIXED_TIME + timedelta(seconds=3),
    )

    assert completed.execution_record.status == "SUCCESS"
    assert completed.steps[0].status is StepExecutionStatus.SUCCESS
    assert completed.steps[0].output == {"observed": True}
    assert completed.steps[0].tool_call_ids == ("tool-call-001",)


def test_iu1_sequential_baseline_rejects_two_running_steps() -> None:
    plan = build_approved_action_plan()
    second = plan.steps[0].model_copy(
        update={
            "step_id": "step-002",
            "depends_on": ["step-001"],
        }
    )
    plan = plan.model_copy(update={"steps": [plan.steps[0], second]})
    foundation, _ = _foundation()
    prepared = asyncio.run(
        foundation.initialize(
            plan,
            build_runtime_context(),
        )
    )
    lifecycle = ExecutionLifecycleManager()
    running = lifecycle.start_execution(prepared, at=FIXED_TIME)
    first_running = lifecycle.start_step(
        running,
        step_id="step-001",
        at=FIXED_TIME + timedelta(seconds=1),
    )

    with pytest.raises(ExecutionLifecycleError, match="one RUNNING step"):
        lifecycle.start_step(
            first_running,
            step_id="step-002",
            at=FIXED_TIME + timedelta(seconds=2),
        )


def test_execution_cannot_finish_while_step_is_pending_or_running() -> None:
    foundation, _ = _foundation()
    prepared = asyncio.run(
        foundation.initialize(
            build_approved_action_plan(),
            build_runtime_context(),
        )
    )
    lifecycle = ExecutionLifecycleManager()
    running = lifecycle.start_execution(prepared, at=FIXED_TIME)

    with pytest.raises(ExecutionLifecycleError, match="non-terminal"):
        lifecycle.finish_execution(
            running,
            status=ExecutionPlanStatus.SUCCESS,
            at=FIXED_TIME + timedelta(seconds=1),
        )


def test_execution_result_projection_preserves_observation_not_business_truth() -> None:
    foundation, _ = _foundation()
    prepared = asyncio.run(
        foundation.initialize(
            build_approved_action_plan(),
            build_runtime_context(),
        )
    )
    lifecycle = ExecutionLifecycleManager()
    running = lifecycle.start_execution(prepared, at=FIXED_TIME)
    step_running = lifecycle.start_step(
        running,
        step_id="step-001",
        at=FIXED_TIME + timedelta(seconds=1),
    )
    step_done = lifecycle.finish_step(
        step_running,
        step_id="step-001",
        status=StepExecutionStatus.SUCCESS,
        at=FIXED_TIME + timedelta(seconds=2),
        output={"tool_observation": "returned"},
    )
    completed = lifecycle.finish_execution(
        step_done,
        status=ExecutionPlanStatus.SUCCESS,
        at=FIXED_TIME + timedelta(seconds=3),
    )

    result = ExecutionResultProjector().project(completed)

    assert result.plan_status is ExecutionPlanStatus.SUCCESS
    assert result.timing.started_at == FIXED_TIME
    assert result.timing.finished_at == FIXED_TIME + timedelta(seconds=3)
    assert result.step_results[0].status == "SUCCESS"
    assert result.step_results[0].output == {"tool_observation": "returned"}
    assert result.business_outputs is None
    assert result.state_observations is None
    assert result.quality is None


def test_result_projection_rejects_non_terminal_execution() -> None:
    foundation, _ = _foundation()
    prepared = asyncio.run(
        foundation.initialize(
            build_approved_action_plan(),
            build_runtime_context(),
        )
    )

    with pytest.raises(ExecutionLifecycleError, match="terminal"):
        ExecutionResultProjector().project(prepared)


def test_iu1_foundation_has_no_skill_workflow_tool_invocation_or_m6_dependency() -> None:
    source = inspect.getsource(foundation_module)

    forbidden = (
        ".invoke(",
        ".execute(",
        ".start(",
        ".resume(",
        "runtime.validation",
        "runtime.knowledge",
        "runtime.response",
        "runtime.update",
        "httpx",
        "requests",
    )
    for token in forbidden:
        assert token not in source
