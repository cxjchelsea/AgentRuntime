"""M5-IU7 Formal Implementation behavioral gates."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from runtime.contracts.execution import ExecutionContext
from runtime.execution import (
    CapabilityExecutionOwner,
    ExecutionControlApplicationEvaluator,
    ExecutionControlCoordinator,
    ExecutionControlDisposition,
    ExecutionControlLatchStatus,
    ExecutionControlLifecycleService,
    ExecutionControlLifecycleTransitioner,
    ExecutionControlRuntimeError,
    ExecutionControlSignal,
    ExecutionControlSignalType,
    HierarchicalInterruptStatus,
    InFlightInterruptCoordinator,
    InFlightOperationHandle,
    InFlightOperationKind,
    InMemoryExecutionControlLatch,
    InMemoryExecutionStateStore,
    InMemoryInFlightOperationRegistry,
    InterruptOutcome,
    InterruptOutcomeStatus,
    M5SkillResult,
    M5ToolResult,
    ObservedExecutionControl,
    PreparedExecution,
    SkillExecutionStatus,
    StepCapabilityExecutor,
    StepExecutionStatus,
    StepLifecycleSnapshot,
    ToolExecutionStatus,
)
from runtime.execution.models import ExecutionRecord
from tests.test_m5_iu4_capability_execution import (
    CountingIdentifierFactory,
    StaticPermissionEvaluator,
    StaticPermissionProvider,
    StaticValidator,
    _approved_step,
    _skill_resolved,
    _snapshot,
    _tool,
)

START = datetime(2026, 9, 22, 15, 0, tzinfo=UTC)
CONTROL_AT = START + timedelta(seconds=5)
TERMINAL_AT = START + timedelta(seconds=10)


class StaticWatcher:
    def __init__(self, observed: ObservedExecutionControl) -> None:
        self.observed = observed
        self.calls = 0

    async def wait_for_terminal_signal(
        self,
        *,
        execution_id: str,
        cancellation_token: str | None,
    ) -> ObservedExecutionControl:
        del execution_id, cancellation_token
        self.calls += 1
        return self.observed


class ExplodingWatcher(StaticWatcher):
    async def wait_for_terminal_signal(
        self,
        *,
        execution_id: str,
        cancellation_token: str | None,
    ) -> ObservedExecutionControl:
        del execution_id, cancellation_token
        raise RuntimeError("watch failed")


class StaticInterruptController:
    def __init__(
        self,
        status: InterruptOutcomeStatus = InterruptOutcomeStatus.CONFIRMED_STOPPED,
    ) -> None:
        self.status = status
        self.handles: list[InFlightOperationHandle] = []

    async def interrupt(
        self,
        *,
        handle: InFlightOperationHandle,
        signal: ExecutionControlSignal,
    ) -> InterruptOutcome:
        del signal
        self.handles.append(handle)
        return InterruptOutcome(
            operation_handle_id=handle.operation_handle_id,
            status=self.status,
            reason_codes=(self.status.value,),
        )


class InFlightIds:
    def new_owner_handle_id(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
        kind: InFlightOperationKind,
        capability_id: str,
    ) -> str:
        return f"{execution_id}:{step_execution_id}:{kind.value}:{capability_id}:owner"

    def new_tool_handle_id(
        self,
        *,
        execution_id: str,
        step_execution_id: str,
        parent_handle_id: str,
        tool_call_id: str,
        physical_attempt: int,
    ) -> str:
        del parent_handle_id
        return (
            f"{execution_id}:{step_execution_id}:TOOL:{tool_call_id}:{physical_attempt}"
        )


class BlockingTool:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def invoke(self, request, execution_context):
        del execution_context
        self.started.set()
        await self.release.wait()
        return M5ToolResult(
            tool_call_id=request.tool_call_id,
            tool_id=request.tool_id,
            status=ToolExecutionStatus.SUCCESS,
            data={"ok": True},
            attempt=request.attempt,
        )


class ToolCallingSkill:
    async def execute(self, request, execution_context, tool_invoker):
        del execution_context
        result = await tool_invoker.invoke(
            tool_id="DOMAIN_TOOL",
            input_payload={"value": 1},
        )
        return M5SkillResult(
            skill_id=request.skill_id,
            status=SkillExecutionStatus.SUCCESS,
            tool_results=(result,),
        )


def _signal(
    signal_type: ExecutionControlSignalType = ExecutionControlSignalType.CANCEL,
    *,
    signal_id: str = "signal-001",
    target_execution_id: str = "execution-001",
) -> ExecutionControlSignal:
    return ExecutionControlSignal(
        signal_type=signal_type,
        reason_code=(
            "USER_STOP"
            if signal_type is ExecutionControlSignalType.CANCEL
            else "HIGH_PRIORITY_PREEMPTION"
        ),
        source="RUNTIME",
        signal_id=signal_id,
        target_execution_id=target_execution_id,
        issued_at=START,
    )


def _observed(
    signal_type: ExecutionControlSignalType = ExecutionControlSignalType.CANCEL,
    *,
    signal_id: str = "signal-001",
    target_execution_id: str = "execution-001",
) -> ObservedExecutionControl:
    return ObservedExecutionControl(
        signal=_signal(
            signal_type,
            signal_id=signal_id,
            target_execution_id=target_execution_id,
        ),
        observed_at=CONTROL_AT,
    )


def _prepared(*, running: bool = True) -> PreparedExecution:
    context = ExecutionContext(
        execution_id="execution-001",
        plan_id="plan-001",
        request_id="request-001",
        session_id="session-001",
        identity_scope="scope-001",
        policy_snapshot={"policy": "frozen"},
        cancellation_token="execution-001",
    )
    steps = (
        StepLifecycleSnapshot(
            step_execution_id="step-exec-001",
            step_id="step-001",
            action="done",
            status=StepExecutionStatus.SUCCESS,
            output={"side_effect": "committed"},
            tool_call_ids=("tool-call-committed",),
            started_at=START,
            finished_at=START + timedelta(seconds=1),
        ),
        StepLifecycleSnapshot(
            step_execution_id="step-exec-002",
            step_id="step-002",
            action="running" if running else "not-started",
            status=(
                StepExecutionStatus.RUNNING if running else StepExecutionStatus.PENDING
            ),
            skill_id="skill-002",
            started_at=START + timedelta(seconds=2) if running else None,
        ),
        StepLifecycleSnapshot(
            step_execution_id="step-exec-003",
            step_id="step-003",
            action="pending",
            status=StepExecutionStatus.PENDING,
            skill_id="skill-003",
        ),
    )
    record = ExecutionRecord(
        execution_id="execution-001",
        plan_id="plan-001",
        request_id="request-001",
        identity_scope="scope-001",
        status="RUNNING",
        current_step="step-002" if running else None,
        step_results=(),
        created_at=START,
        updated_at=START + timedelta(seconds=2),
    )
    return PreparedExecution(
        execution_context=context,
        execution_record=record,
        steps=steps,
        started_at=START,
    )


async def _coordinator(
    *,
    prepared: PreparedExecution,
    observed: ObservedExecutionControl,
    controller: StaticInterruptController,
    registry: InMemoryInFlightOperationRegistry,
) -> tuple[ExecutionControlCoordinator, InMemoryExecutionStateStore]:
    store = InMemoryExecutionStateStore()
    assert await store.create(prepared.execution_record) is True
    coordinator = ExecutionControlCoordinator(
        watcher=StaticWatcher(observed),
        latch=InMemoryExecutionControlLatch(),
        interrupt_coordinator=InFlightInterruptCoordinator(
            registry=registry,
            interrupt_controller=controller,
        ),
        application_evaluator=ExecutionControlApplicationEvaluator(),
        lifecycle_service=ExecutionControlLifecycleService(
            transitioner=ExecutionControlLifecycleTransitioner(),
            execution_store=store,
        ),
        clock=lambda: TERMINAL_AT,
    )
    return coordinator, store


def test_inmemory_latch_is_idempotent_and_conflict_safe() -> None:
    async def scenario() -> None:
        latch = InMemoryExecutionControlLatch()
        first = await latch.latch(observed=_observed(), latched_at=CONTROL_AT)
        replay = await latch.latch(observed=_observed(), latched_at=TERMINAL_AT)
        conflict = await latch.latch(
            observed=_observed(
                ExecutionControlSignalType.PREEMPT,
                signal_id="signal-preempt",
            ),
            latched_at=TERMINAL_AT,
        )

        assert first.status is ExecutionControlLatchStatus.LATCHED
        assert replay.status is ExecutionControlLatchStatus.ALREADY_LATCHED
        assert replay.latched_control == first.latched_control
        assert conflict.status is ExecutionControlLatchStatus.CONFLICT
        assert conflict.latched_control == first.latched_control

    asyncio.run(scenario())


def test_formal_cancel_path_interrupts_owner_and_terminalizes_execution() -> None:
    async def scenario() -> None:
        prepared = _prepared()
        registry = InMemoryInFlightOperationRegistry()
        owner = InFlightOperationHandle(
            operation_handle_id="owner-001",
            execution_id="execution-001",
            step_execution_id="step-exec-002",
            kind=InFlightOperationKind.SKILL,
            capability_id="skill-002",
            capability_version="1.0.0",
            started_at=START + timedelta(seconds=2),
        )
        assert await registry.register(owner) is True
        controller = StaticInterruptController()
        coordinator, store = await _coordinator(
            prepared=prepared,
            observed=_observed(),
            controller=controller,
            registry=registry,
        )

        result = await coordinator.watch_and_apply(prepared)

        assert (
            result.application.disposition
            is ExecutionControlDisposition.READY_TO_TERMINALIZE
        )
        assert result.lifecycle_mutated is True
        assert result.prepared.execution_record.status == "CANCELLED"
        assert result.prepared.steps[0] is prepared.steps[0]
        assert result.prepared.steps[1].status is StepExecutionStatus.CANCELLED
        assert result.prepared.steps[2].status is StepExecutionStatus.CANCELLED
        assert [item.operation_handle_id for item in controller.handles] == [
            "owner-001"
        ]
        stored = await store.load("execution-001")
        assert stored is not None
        assert stored.status == "CANCELLED"

    asyncio.run(scenario())


def test_preempt_pending_only_sets_handoff_without_starting_runtime_cycle() -> None:
    async def scenario() -> None:
        prepared = _prepared(running=False)
        registry = InMemoryInFlightOperationRegistry()
        controller = StaticInterruptController()
        coordinator, _ = await _coordinator(
            prepared=prepared,
            observed=_observed(ExecutionControlSignalType.PREEMPT),
            controller=controller,
            registry=registry,
        )

        result = await coordinator.watch_and_apply(prepared)

        assert result.handoff_required is True
        assert result.prepared.execution_record.status == "PREEMPTED"
        assert result.prepared.steps[1].status is StepExecutionStatus.PREEMPTED
        assert result.prepared.steps[2].status is StepExecutionStatus.PREEMPTED
        assert controller.handles == []

    asyncio.run(scenario())


def test_wrong_target_fails_closed_before_latch_or_lifecycle_mutation() -> None:
    async def scenario() -> None:
        prepared = _prepared()
        registry = InMemoryInFlightOperationRegistry()
        controller = StaticInterruptController()
        coordinator, _ = await _coordinator(
            prepared=prepared,
            observed=_observed(target_execution_id="execution-other"),
            controller=controller,
            registry=registry,
        )

        result = await coordinator.watch_and_apply(prepared)

        assert result.latch_decision.status is ExecutionControlLatchStatus.UNKNOWN
        assert result.application.disposition is ExecutionControlDisposition.UNKNOWN
        assert result.lifecycle_mutated is False
        assert result.prepared is prepared
        assert controller.handles == []

    asyncio.run(scenario())


def test_already_completed_waits_then_reconciles_real_completion() -> None:
    async def scenario() -> None:
        prepared = _prepared()
        registry = InMemoryInFlightOperationRegistry()
        owner = InFlightOperationHandle(
            operation_handle_id="owner-001",
            execution_id="execution-001",
            step_execution_id="step-exec-002",
            kind=InFlightOperationKind.SKILL,
            capability_id="skill-002",
            capability_version="1.0.0",
            started_at=START + timedelta(seconds=2),
        )
        assert await registry.register(owner) is True
        controller = StaticInterruptController(InterruptOutcomeStatus.ALREADY_COMPLETED)
        coordinator, _ = await _coordinator(
            prepared=prepared,
            observed=_observed(),
            controller=controller,
            registry=registry,
        )

        waiting = await coordinator.watch_and_apply(prepared)
        assert (
            waiting.application.disposition
            is ExecutionControlDisposition.WAITING_IN_FLIGHT
        )
        assert waiting.lifecycle_mutated is False

        real_completion = replace(
            prepared.steps[1],
            status=StepExecutionStatus.SUCCESS,
            output={"actual": "result"},
            finished_at=START + timedelta(seconds=7),
        )
        reconciled_prepared = replace(
            prepared,
            steps=(prepared.steps[0], real_completion, prepared.steps[2]),
            execution_record=replace(
                prepared.execution_record,
                current_step=None,
                updated_at=START + timedelta(seconds=7),
            ),
        )

        result = await coordinator.reconcile(
            prepared_at_latch=prepared,
            prior_result=waiting,
            prepared_after_interrupt=reconciled_prepared,
        )

        assert (
            result.application.disposition
            is ExecutionControlDisposition.READY_TO_TERMINALIZE
        )
        assert result.prepared.steps[1] is real_completion
        assert result.prepared.steps[1].status is StepExecutionStatus.SUCCESS
        assert result.prepared.steps[1].output == {"actual": "result"}
        assert result.prepared.steps[2].status is StepExecutionStatus.CANCELLED
        assert result.prepared.execution_record.status == "CANCELLED"

    asyncio.run(scenario())


def test_watcher_failure_never_mutates_lifecycle() -> None:
    async def scenario() -> None:
        prepared = _prepared()
        store = InMemoryExecutionStateStore()
        assert await store.create(prepared.execution_record) is True
        coordinator = ExecutionControlCoordinator(
            watcher=ExplodingWatcher(_observed()),
            latch=InMemoryExecutionControlLatch(),
            interrupt_coordinator=InFlightInterruptCoordinator(
                registry=InMemoryInFlightOperationRegistry(),
                interrupt_controller=StaticInterruptController(),
            ),
            application_evaluator=ExecutionControlApplicationEvaluator(),
            lifecycle_service=ExecutionControlLifecycleService(
                transitioner=ExecutionControlLifecycleTransitioner(),
                execution_store=store,
            ),
            clock=lambda: TERMINAL_AT,
        )

        with pytest.raises(ExecutionControlRuntimeError, match="watcher failed"):
            await coordinator.watch_and_apply(prepared)

        stored = await store.load("execution-001")
        assert stored == prepared.execution_record

    asyncio.run(scenario())


def test_formal_executor_registers_owner_and_nested_tool_chain() -> None:
    async def scenario() -> None:
        registry = InMemoryInFlightOperationRegistry()
        tool = BlockingTool()
        skill = ToolCallingSkill()
        approved_plan, step = _approved_step(owner=CapabilityExecutionOwner.SKILL)
        resolved = _skill_resolved(skill, tools=(_tool(tool),))
        snapshot = _snapshot(step)

        executor = StepCapabilityExecutor(
            permission_context_provider=StaticPermissionProvider(),
            permission_evaluator=StaticPermissionEvaluator(),
            input_validator=StaticValidator(),
            output_validator=StaticValidator(),
            identifier_factory=CountingIdentifierFactory(),
            inflight_registry=registry,
            inflight_identifier_factory=InFlightIds(),
            inflight_clock=lambda: START + timedelta(seconds=3),
        )

        task = asyncio.create_task(
            executor.execute(
                approved_plan=approved_plan,
                step=step,
                step_snapshot=snapshot,
                resolved=resolved,
                execution_context=ExecutionContext(
                    execution_id="execution-iu4",
                    plan_id=approved_plan.plan_id,
                    request_id=approved_plan.request_id,
                    session_id="session-001",
                    identity_scope="scope-001",
                    policy_snapshot={"allowed": True},
                ),
            )
        )

        await tool.started.wait()
        chain = await registry.active_chain(
            execution_id="execution-iu4",
            step_execution_id="step-execution-001",
        )
        assert len(chain) == 2
        owner = next(item for item in chain if item.kind is InFlightOperationKind.SKILL)
        leaf = next(item for item in chain if item.kind is InFlightOperationKind.TOOL)
        assert leaf.parent_handle_id == owner.operation_handle_id

        interrupt = StaticInterruptController(InterruptOutcomeStatus.NOT_CANCELLABLE)
        summary = await InFlightInterruptCoordinator(
            registry=registry,
            interrupt_controller=interrupt,
        ).interrupt(
            execution_id="execution-iu4",
            step_execution_id="step-execution-001",
            signal=_signal(target_execution_id="execution-iu4"),
        )

        assert summary.status is HierarchicalInterruptStatus.ORDERED
        assert [item.kind for item in summary.handles] == [
            InFlightOperationKind.TOOL,
            InFlightOperationKind.SKILL,
        ]
        assert [item.kind for item in interrupt.handles] == [
            InFlightOperationKind.TOOL,
            InFlightOperationKind.SKILL,
        ]

        tool.release.set()
        outcome = await task
        assert outcome.status.value == "EXECUTED"
        assert (
            await registry.active_chain(
                execution_id="execution-iu4",
                step_execution_id="step-execution-001",
            )
            == ()
        )

    asyncio.run(scenario())
