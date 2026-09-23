"""M5-IU8 Formal Implementation behavioral gates."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from runtime.contracts.enums import ExecutionPlanStatus
from runtime.contracts.execution import ExecutionContext
from runtime.execution import (
    CapabilityExecutionOwner,
    CapabilityExecutionStatus,
    CapabilityKind,
    CapabilityReferenceSource,
    CoreApprovedToolInvoker,
    ExecutionConcurrencyAdmissionStatus,
    ExecutionConcurrencyRuntime,
    ExecutionControlApplicationEvaluator,
    ExecutionControlCoordinator,
    ExecutionControlLifecycleService,
    ExecutionControlLifecycleTransitioner,
    ExecutionControlSignal,
    ExecutionControlSignalType,
    ExecutionLifecycleManager,
    ExecutionLifecycleService,
    IdempotencyMode,
    InFlightInterruptCoordinator,
    InFlightOperationHandle,
    InFlightOperationKind,
    InMemoryExecutionControlLatch,
    InMemoryExecutionStateStore,
    InMemoryInFlightOperationRegistry,
    InMemoryOperationResourceLeaseRegistry,
    InMemoryResourceLockAuthority,
    InterruptOutcome,
    InterruptOutcomeStatus,
    M5ToolResult,
    ObservedExecutionControl,
    OperationResourceReleaseCoordinator,
    PreparedExecution,
    ResolvedCapability,
    ResolvedIdempotencyPolicy,
    ResolvedReliabilityPolicy,
    ResolvedResourceLock,
    ResolvedRetryPolicy,
    ResolvedTimeoutPolicy,
    ResourceLockRequirement,
    ResourceLockResolutionDecision,
    ResourceLockResolutionStatus,
    ResourceLockSetCoordinator,
    RetryTriggerStatus,
    SessionExecutionLockCoordinator,
    SessionExecutionReleaseStatus,
    Sha256ResourceLockAcquisitionIdentifierFactory,
    Sha256SessionExecutionLockIdentityFactory,
    SideEffectClass,
    StepCapabilityExecutor,
    StepExecutionStatus,
    StepLifecycleSnapshot,
    TimeoutRunResult,
    TimeoutRunStatus,
    ToolConcurrencyRuntime,
    ToolExecutionStatus,
    ToolOperationCorrelationDecision,
    ToolOperationCorrelationKey,
    ToolOperationCorrelationStatus,
    ToolOperationOccurrenceDecision,
    ToolOperationOccurrenceStatus,
    ToolReliabilityRuntime,
    ToolResourceLockProjector,
)
from runtime.execution.models import ExecutionRecord
from runtime.execution.reliability import (
    ReplaySafetyDecision,
    ReplaySafetyStatus,
    RetryDecision,
    RetryDecisionStatus,
)
from runtime.registries.definitions import ToolDefinition
from tests.test_m5_iu4_capability_execution import (
    CountingIdentifierFactory,
    RecordingSkill,
    RecordingTool,
    StaticPermissionEvaluator,
    StaticPermissionProvider,
    StaticValidator,
    _approved_step,
    _skill_resolved,
    _snapshot,
)

NOW = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)


class StaticClock:
    def __init__(self, current: datetime = NOW) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current


class StaticResourceResolver:
    async def resolve(
        self,
        *,
        requirement: ResourceLockRequirement,
        execution_context: ExecutionContext,
        tool_call_id: str,
        physical_attempt: int,
    ) -> ResourceLockResolutionDecision:
        del tool_call_id, physical_attempt
        return ResourceLockResolutionDecision(
            status=ResourceLockResolutionStatus.RESOLVED,
            reason_codes=("RESOURCE_LOCK_RESOLVED",),
            resolved_lock=ResolvedResourceLock(
                resource_ref=requirement.resource_ref,
                lock_key=f"{execution_context.device_id or 'shared'}:exclusive",
                provenance=("formal-test-resolver",),
            ),
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
            f"{execution_id}:{step_execution_id}:TOOL:"
            f"{tool_call_id}:attempt-{physical_attempt}"
        )


class BlockingTool:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def invoke(self, request, execution_context):
        del execution_context
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return M5ToolResult(
            tool_call_id=request.tool_call_id,
            tool_id=request.tool_id,
            status=ToolExecutionStatus.SUCCESS,
            attempt=request.attempt,
            data={"ok": True},
        )


class TimeoutWithoutStopRunner:
    async def run(self, *, timeout_seconds: float, operation):
        del timeout_seconds, operation
        return TimeoutRunResult(
            status=TimeoutRunStatus.TIMED_OUT,
            reason_codes=("TIMEOUT_WITHOUT_STOP_CONFIRMATION",),
        )


class FixedPolicyResolver:
    def resolve(self, **kwargs):
        return ResolvedReliabilityPolicy(
            capability_kind=kwargs["capability_kind"],
            capability_id=kwargs["capability_id"],
            capability_version=kwargs["capability_version"],
            policy_identity="formal-policy@sha256:1",
            timeout=ResolvedTimeoutPolicy(timeout_seconds=1.0),
            retry=ResolvedRetryPolicy(
                enabled=False,
                max_attempts=1,
                retry_on_statuses=(),
                backoff_seconds=0.0,
            ),
            idempotency=ResolvedIdempotencyPolicy(mode=IdempotencyMode.NATURAL),
            side_effect_class=SideEffectClass.HIGH,
        )


class FingerprintFactory:
    def fingerprint(self, **kwargs) -> str:
        del kwargs
        return "sha256:formal-operation"


class OccurrenceAuthority:
    async def claim_next(self, **kwargs):
        del kwargs
        return ToolOperationOccurrenceDecision(
            status=ToolOperationOccurrenceStatus.CLAIMED,
            reason_codes=("OCCURRENCE_CLAIMED",),
            occurrence=1,
        )


class Correlator:
    def correlate(self, **kwargs):
        del kwargs
        return ToolOperationCorrelationDecision(
            status=ToolOperationCorrelationStatus.NEW,
            reason_codes=("NEW_OPERATION",),
            operation_key=ToolOperationCorrelationKey("operation-formal-001"),
            logical_tool_call_id="logical-formal-001",
            operation_occurrence=1,
        )


class RetryingPolicyResolver:
    def resolve(self, **kwargs):
        return ResolvedReliabilityPolicy(
            capability_kind=kwargs["capability_kind"],
            capability_id=kwargs["capability_id"],
            capability_version=kwargs["capability_version"],
            policy_identity="retry-policy@sha256:1",
            timeout=ResolvedTimeoutPolicy(timeout_seconds=None),
            retry=ResolvedRetryPolicy(
                enabled=True,
                max_attempts=2,
                retry_on_statuses=(RetryTriggerStatus.FAILED,),
                backoff_seconds=0.0,
            ),
            idempotency=ResolvedIdempotencyPolicy(mode=IdempotencyMode.NATURAL),
            side_effect_class=SideEffectClass.NONE,
        )


class SafeReplayEvaluator:
    def evaluate(self, context):
        del context
        return ReplaySafetyDecision(
            status=ReplaySafetyStatus.SAFE,
            reason_codes=("SAFE_REPLAY",),
        )


class RetryOnceEvaluator:
    def evaluate(self, *, policy, context):
        del policy
        if context.current_attempt == 1:
            return RetryDecision(
                status=RetryDecisionStatus.RETRY,
                reason_codes=("RETRY_SECOND_ATTEMPT",),
                next_attempt=2,
                backoff_seconds=0.0,
            )
        return RetryDecision(
            status=RetryDecisionStatus.STOP,
            reason_codes=("RETRY_BUDGET_EXHAUSTED",),
        )


class NoopRetrySleeper:
    async def sleep(self, seconds: float) -> None:
        del seconds


class FailThenSucceedTool:
    def __init__(self) -> None:
        self.attempts: list[int] = []

    async def invoke(self, request, execution_context):
        del execution_context
        self.attempts.append(request.attempt)
        status = (
            ToolExecutionStatus.FAILED
            if request.attempt == 1
            else ToolExecutionStatus.SUCCESS
        )
        return M5ToolResult(
            tool_call_id=request.tool_call_id,
            tool_id=request.tool_id,
            status=status,
            attempt=request.attempt,
            data={"attempt": request.attempt},
        )


class StaticWatcher:
    def __init__(self, observed: ObservedExecutionControl) -> None:
        self.observed = observed

    async def wait_for_terminal_signal(
        self,
        *,
        execution_id: str,
        cancellation_token: str | None,
    ) -> ObservedExecutionControl:
        del execution_id, cancellation_token
        return self.observed


class ConfirmingInterruptController:
    async def interrupt(
        self,
        *,
        handle: InFlightOperationHandle,
        signal: ExecutionControlSignal,
    ) -> InterruptOutcome:
        del signal
        return InterruptOutcome(
            operation_handle_id=handle.operation_handle_id,
            status=InterruptOutcomeStatus.CONFIRMED_STOPPED,
            reason_codes=("CONFIRMED_STOPPED",),
        )


def _context(
    *,
    execution_id: str,
    session_id: str = "session-001",
    device_id: str = "device-001",
) -> ExecutionContext:
    return ExecutionContext(
        execution_id=execution_id,
        plan_id=f"plan-{execution_id}",
        request_id=f"request-{execution_id}",
        session_id=session_id,
        identity_scope="scope-001",
        policy_snapshot={"allowed": True},
        device_id=device_id,
        cancellation_token=execution_id,
    )


def _resolved_tool(
    implementation,
) -> ResolvedCapability:
    return ResolvedCapability(
        kind=CapabilityKind.TOOL,
        capability_id="DOMAIN_TOOL",
        version="1.0.0",
        definition=ToolDefinition(
            tool_id="DOMAIN_TOOL",
            version="1.0.0",
            required_permissions=["TOOL_USE"],
            resource_locks=["exclusive-device"],
        ),
        implementation_ref=implementation,
        source=CapabilityReferenceSource.APPROVED_TOOL_PLAN,
    )


def _tool_runtime():
    authority = InMemoryResourceLockAuthority()
    inflight = InMemoryInFlightOperationRegistry()
    ids = InFlightIds()
    operation_registry = InMemoryOperationResourceLeaseRegistry()
    release = OperationResourceReleaseCoordinator(
        authority=authority,
        registry=operation_registry,
    )
    runtime = ToolConcurrencyRuntime(
        projector=ToolResourceLockProjector(StaticResourceResolver()),
        lock_set_coordinator=ResourceLockSetCoordinator(
            authority=authority,
            clock=StaticClock(),
            identifier_factory=Sha256ResourceLockAcquisitionIdentifierFactory(),
        ),
        resource_release_coordinator=release,
        operation_resource_registry=operation_registry,
        inflight_registry=inflight,
        inflight_identifier_factory=ids,
        clock=lambda: NOW,
    )
    return runtime, authority, inflight, operation_registry, ids


async def _register_owner(
    inflight: InMemoryInFlightOperationRegistry,
    ids: InFlightIds,
    *,
    execution_id: str,
    step_execution_id: str,
) -> InFlightOperationHandle:
    handle = InFlightOperationHandle(
        operation_handle_id=ids.new_owner_handle_id(
            execution_id=execution_id,
            step_execution_id=step_execution_id,
            kind=InFlightOperationKind.SKILL,
            capability_id="SKILL_A",
        ),
        execution_id=execution_id,
        step_execution_id=step_execution_id,
        kind=InFlightOperationKind.SKILL,
        capability_id="SKILL_A",
        capability_version="1.0.0",
        started_at=NOW,
    )
    assert await inflight.register(handle) is True
    return handle


def _invoker(
    *,
    resolved: ResolvedCapability,
    execution_context: ExecutionContext,
    parent: InFlightOperationHandle,
    inflight: InMemoryInFlightOperationRegistry,
    ids: InFlightIds,
    tool_runtime: ToolConcurrencyRuntime,
    reliability_runtime: ToolReliabilityRuntime | None = None,
) -> CoreApprovedToolInvoker:
    return CoreApprovedToolInvoker(
        resolved_tools=(resolved,),
        execution_context=execution_context,
        step_execution_id=parent.step_execution_id,
        permission_context_provider=StaticPermissionProvider(),
        permission_evaluator=StaticPermissionEvaluator(),
        input_validator=StaticValidator(),
        output_validator=StaticValidator(),
        identifier_factory=CountingIdentifierFactory(),
        step_id="step-001",
        reliability_runtime=reliability_runtime,
        inflight_registry=inflight,
        inflight_identifier_factory=ids,
        inflight_parent_handle_id=parent.operation_handle_id,
        inflight_clock=lambda: NOW,
        tool_concurrency_runtime=tool_runtime,
    )


def _session_runtime(
    authority: InMemoryResourceLockAuthority,
) -> ExecutionConcurrencyRuntime:
    return ExecutionConcurrencyRuntime(
        session_coordinator=SessionExecutionLockCoordinator(
            authority=authority,
            identity_factory=Sha256SessionExecutionLockIdentityFactory(),
        ),
        clock=lambda: NOW,
    )


def test_session_busy_blocks_step_before_skill_side_effect() -> None:
    async def scenario() -> None:
        authority = InMemoryResourceLockAuthority()
        session_runtime = _session_runtime(authority)
        first = await session_runtime.admit(
            _context(execution_id="execution-001", session_id="session-shared")
        )
        assert first.status is ExecutionConcurrencyAdmissionStatus.ADMITTED

        skill = RecordingSkill()
        approved_plan, step = _approved_step(owner=CapabilityExecutionOwner.SKILL)
        resolved = _skill_resolved(skill)
        snapshot = _snapshot(step)
        executor = StepCapabilityExecutor(
            permission_context_provider=StaticPermissionProvider(),
            permission_evaluator=StaticPermissionEvaluator(),
            input_validator=StaticValidator(),
            output_validator=StaticValidator(),
            identifier_factory=CountingIdentifierFactory(),
            execution_concurrency_runtime=session_runtime,
        )

        second_context = ExecutionContext(
            execution_id="execution-002",
            plan_id=approved_plan.plan_id,
            request_id=approved_plan.request_id,
            session_id="session-shared",
            identity_scope="scope-001",
            policy_snapshot={"allowed": True},
            device_id="device-001",
            cancellation_token="execution-002",
        )
        outcome = await executor.execute(
            approved_plan=approved_plan,
            step=step,
            step_snapshot=snapshot,
            resolved=resolved,
            execution_context=second_context,
        )

        assert outcome.status is CapabilityExecutionStatus.BLOCKED
        assert outcome.reason_codes == ("SESSION_EXECUTION_LOCK_BUSY",)
        assert skill.calls == 0

    asyncio.run(scenario())


def test_normal_terminal_execution_releases_session_lease_via_lifecycle_hook() -> None:
    async def scenario() -> None:
        authority = InMemoryResourceLockAuthority()
        session_runtime = _session_runtime(authority)
        context = _context(execution_id="execution-001")
        admitted = await session_runtime.admit(context)
        assert admitted.status is ExecutionConcurrencyAdmissionStatus.ADMITTED

        step = StepLifecycleSnapshot(
            step_execution_id="step-exec-001",
            step_id="step-001",
            action="ACTION_A",
            status=StepExecutionStatus.PENDING,
        )
        prepared = PreparedExecution(
            execution_context=context,
            execution_record=ExecutionRecord(
                execution_id=context.execution_id,
                plan_id=context.plan_id,
                request_id=context.request_id,
                identity_scope=context.identity_scope,
                status="CREATED",
                current_step=None,
                step_results=(),
                created_at=NOW,
                updated_at=NOW,
            ),
            steps=(step,),
        )
        store = InMemoryExecutionStateStore()
        assert await store.create(prepared.execution_record) is True
        lifecycle = ExecutionLifecycleService(
            lifecycle_manager=ExecutionLifecycleManager(),
            execution_store=store,
            terminal_observer=session_runtime,
        )
        running = await lifecycle.start_execution(
            prepared,
            at=NOW + timedelta(seconds=1),
        )
        running = await lifecycle.start_step(
            running,
            step_id="step-001",
            at=NOW + timedelta(seconds=2),
        )
        running = await lifecycle.finish_step(
            running,
            step_id="step-001",
            status=StepExecutionStatus.SUCCESS,
            at=NOW + timedelta(seconds=3),
        )
        terminal = await lifecycle.finish_execution(
            running,
            status=ExecutionPlanStatus.SUCCESS,
            at=NOW + timedelta(seconds=4),
        )

        assert terminal.execution_record.status == "SUCCESS"
        assert session_runtime.active_session_lease(context.execution_id) is None
        released = session_runtime.last_release_decision(context.execution_id)
        assert released is not None
        assert released.status is SessionExecutionReleaseStatus.RELEASED

    asyncio.run(scenario())


def test_baseline_tool_path_blocks_competing_resource_and_releases_on_completion() -> (
    None
):
    async def scenario() -> None:
        runtime, authority, inflight, operation_registry, ids = _tool_runtime()
        del operation_registry
        blocker = BlockingTool()
        first_context = _context(
            execution_id="execution-001",
            session_id="session-001",
        )
        first_parent = await _register_owner(
            inflight,
            ids,
            execution_id=first_context.execution_id,
            step_execution_id="step-exec-001",
        )
        first = _invoker(
            resolved=_resolved_tool(blocker),
            execution_context=first_context,
            parent=first_parent,
            inflight=inflight,
            ids=ids,
            tool_runtime=runtime,
        )

        task = asyncio.create_task(
            first.invoke(tool_id="DOMAIN_TOOL", input_payload={"value": 1})
        )
        await blocker.started.wait()
        assert authority.active_lease("device-001:exclusive") is not None

        second_tool = RecordingTool()
        second_context = _context(
            execution_id="execution-002",
            session_id="session-002",
        )
        second_parent = await _register_owner(
            inflight,
            ids,
            execution_id=second_context.execution_id,
            step_execution_id="step-exec-002",
        )
        second = _invoker(
            resolved=_resolved_tool(second_tool),
            execution_context=second_context,
            parent=second_parent,
            inflight=inflight,
            ids=ids,
            tool_runtime=runtime,
        )
        denied = await second.invoke(
            tool_id="DOMAIN_TOOL",
            input_payload={"value": 1},
        )

        assert denied.status is ToolExecutionStatus.UNKNOWN
        assert denied.error_code == "RESOURCE_LOCK_BUSY"
        assert second_tool.calls == 0

        blocker.release.set()
        completed = await task
        assert completed.status is ToolExecutionStatus.SUCCESS
        assert authority.active_lease("device-001:exclusive") is None
        assert (
            await inflight.active_chain(
                execution_id=first_context.execution_id,
                step_execution_id="step-exec-001",
            )
        ) == (first_parent,)

    asyncio.run(scenario())


def test_reliability_timeout_keeps_exact_tool_handle_and_resource_lease() -> None:
    async def scenario() -> None:
        runtime, authority, inflight, operation_registry, ids = _tool_runtime()
        tool = RecordingTool()
        context = _context(execution_id="execution-reliable")
        parent = await _register_owner(
            inflight,
            ids,
            execution_id=context.execution_id,
            step_execution_id="step-exec-reliable",
        )
        reliability = ToolReliabilityRuntime(
            policy_resolver=FixedPolicyResolver(),
            clock=StaticClock(),
            timeout_runner=TimeoutWithoutStopRunner(),
            replay_safety_evaluator=cast(Any, object()),
            retry_decision_evaluator=cast(Any, object()),
            retry_sleeper=cast(Any, object()),
            fingerprint_factory=FingerprintFactory(),
            occurrence_authority=OccurrenceAuthority(),
            correlator=Correlator(),
            idempotency_key_factory=cast(Any, object()),
            idempotency_store=cast(Any, object()),
            idempotency_preflight_evaluator=cast(Any, object()),
            idempotency_completion_authority=cast(Any, object()),
            idempotency_result_resolver=cast(Any, object()),
        )
        invoker = _invoker(
            resolved=_resolved_tool(tool),
            execution_context=context,
            parent=parent,
            inflight=inflight,
            ids=ids,
            tool_runtime=runtime,
            reliability_runtime=reliability,
        )

        result = await invoker.invoke(
            tool_id="DOMAIN_TOOL",
            input_payload={"value": 1},
        )

        assert result.status is ToolExecutionStatus.TIMEOUT
        assert tool.calls == 0
        assert authority.active_lease("device-001:exclusive") is not None
        chain = await inflight.active_chain(
            execution_id=context.execution_id,
            step_execution_id=parent.step_execution_id,
        )
        tool_handles = [
            item for item in chain if item.kind is InFlightOperationKind.TOOL
        ]
        assert len(tool_handles) == 1
        binding = await operation_registry.get(tool_handles[0].operation_handle_id)
        assert binding is not None
        assert binding.owner.owner_id == tool_handles[0].operation_handle_id

    asyncio.run(scenario())


def test_reliability_retry_reenters_exact_tool_lock_boundary_each_attempt() -> None:
    async def scenario() -> None:
        runtime, authority, inflight, operation_registry, ids = _tool_runtime()
        tool = FailThenSucceedTool()
        context = _context(execution_id="execution-retry")
        parent = await _register_owner(
            inflight,
            ids,
            execution_id=context.execution_id,
            step_execution_id="step-exec-retry",
        )
        reliability = ToolReliabilityRuntime(
            policy_resolver=RetryingPolicyResolver(),
            clock=StaticClock(),
            timeout_runner=cast(Any, object()),
            replay_safety_evaluator=SafeReplayEvaluator(),
            retry_decision_evaluator=RetryOnceEvaluator(),
            retry_sleeper=NoopRetrySleeper(),
            fingerprint_factory=FingerprintFactory(),
            occurrence_authority=OccurrenceAuthority(),
            correlator=Correlator(),
            idempotency_key_factory=cast(Any, object()),
            idempotency_store=cast(Any, object()),
            idempotency_preflight_evaluator=cast(Any, object()),
            idempotency_completion_authority=cast(Any, object()),
            idempotency_result_resolver=cast(Any, object()),
        )
        invoker = _invoker(
            resolved=_resolved_tool(tool),
            execution_context=context,
            parent=parent,
            inflight=inflight,
            ids=ids,
            tool_runtime=runtime,
            reliability_runtime=reliability,
        )

        result = await invoker.invoke(
            tool_id="DOMAIN_TOOL",
            input_payload={"value": 1},
        )

        assert result.status is ToolExecutionStatus.SUCCESS
        assert result.attempt == 2
        assert tool.attempts == [1, 2]
        assert authority.active_lease("device-001:exclusive") is None
        chain = await inflight.active_chain(
            execution_id=context.execution_id,
            step_execution_id=parent.step_execution_id,
        )
        assert chain == (parent,)
        assert (
            await operation_registry.get(
                f"{context.execution_id}:{parent.step_execution_id}:"
                "TOOL:logical-formal-001:attempt-1"
            )
            is None
        )
        assert (
            await operation_registry.get(
                f"{context.execution_id}:{parent.step_execution_id}:"
                "TOOL:logical-formal-001:attempt-2"
            )
            is None
        )

    asyncio.run(scenario())


def test_confirmed_stop_control_cleans_tool_lock_before_terminalization() -> None:
    async def scenario() -> None:
        runtime, authority, inflight, operation_registry, ids = _tool_runtime()
        context = _context(execution_id="execution-control")
        owner = await _register_owner(
            inflight,
            ids,
            execution_id=context.execution_id,
            step_execution_id="step-exec-control",
        )
        admission = await runtime.admit(
            tool_definition=cast(
                ToolDefinition, _resolved_tool(RecordingTool()).definition
            ),
            tool_id="DOMAIN_TOOL",
            tool_version="1.0.0",
            execution_context=context,
            step_execution_id="step-exec-control",
            parent_handle_id=owner.operation_handle_id,
            logical_tool_call_id="logical-control-001",
            physical_attempt=1,
        )
        assert admission.handle is not None
        assert authority.active_lease("device-001:exclusive") is not None

        running_step = StepLifecycleSnapshot(
            step_execution_id="step-exec-control",
            step_id="step-001",
            action="ACTION_A",
            status=StepExecutionStatus.RUNNING,
            skill_id="SKILL_A",
            started_at=NOW,
        )
        prepared = PreparedExecution(
            execution_context=context,
            execution_record=ExecutionRecord(
                execution_id=context.execution_id,
                plan_id=context.plan_id,
                request_id=context.request_id,
                identity_scope=context.identity_scope,
                status="RUNNING",
                current_step="step-001",
                step_results=(),
                created_at=NOW - timedelta(seconds=1),
                updated_at=NOW,
            ),
            steps=(running_step,),
            started_at=NOW - timedelta(seconds=1),
        )
        store = InMemoryExecutionStateStore()
        assert await store.create(prepared.execution_record) is True
        signal = ExecutionControlSignal(
            signal_type=ExecutionControlSignalType.CANCEL,
            reason_code="USER_STOP",
            source="RUNTIME",
            signal_id="signal-control-001",
            target_execution_id=context.execution_id,
            issued_at=NOW,
        )
        observed = ObservedExecutionControl(
            signal=signal,
            observed_at=NOW + timedelta(seconds=1),
        )
        coordinator = ExecutionControlCoordinator(
            watcher=StaticWatcher(observed),
            latch=InMemoryExecutionControlLatch(),
            interrupt_coordinator=InFlightInterruptCoordinator(
                registry=inflight,
                interrupt_controller=ConfirmingInterruptController(),
            ),
            application_evaluator=ExecutionControlApplicationEvaluator(),
            lifecycle_service=ExecutionControlLifecycleService(
                transitioner=ExecutionControlLifecycleTransitioner(),
                execution_store=store,
            ),
            clock=lambda: NOW + timedelta(seconds=2),
            tool_concurrency_runtime=runtime,
        )

        result = await coordinator.watch_and_apply(prepared)

        assert result.prepared.execution_record.status == "CANCELLED"
        assert authority.active_lease("device-001:exclusive") is None
        assert (
            await operation_registry.get(admission.handle.operation_handle_id) is None
        )
        chain = await inflight.active_chain(
            execution_id=context.execution_id,
            step_execution_id="step-exec-control",
        )
        assert admission.handle not in chain
        assert owner in chain

    asyncio.run(scenario())


class ExplodingTerminalObserver:
    async def on_terminal_execution(
        self,
        prepared: PreparedExecution,
        *,
        observed_at: datetime,
    ) -> None:
        del prepared, observed_at
        raise RuntimeError("terminal observer unavailable")


def test_terminal_observer_failure_does_not_reverse_persisted_execution() -> None:
    async def scenario() -> None:
        context = _context(execution_id="execution-observer")
        step = StepLifecycleSnapshot(
            step_execution_id="step-exec-observer",
            step_id="step-observer",
            action="ACTION_A",
            status=StepExecutionStatus.PENDING,
        )
        prepared = PreparedExecution(
            execution_context=context,
            execution_record=ExecutionRecord(
                execution_id=context.execution_id,
                plan_id=context.plan_id,
                request_id=context.request_id,
                identity_scope=context.identity_scope,
                status="CREATED",
                current_step=None,
                step_results=(),
                created_at=NOW,
                updated_at=NOW,
            ),
            steps=(step,),
        )
        store = InMemoryExecutionStateStore()
        assert await store.create(prepared.execution_record) is True
        lifecycle = ExecutionLifecycleService(
            lifecycle_manager=ExecutionLifecycleManager(),
            execution_store=store,
            terminal_observer=ExplodingTerminalObserver(),
        )
        running = await lifecycle.start_execution(
            prepared,
            at=NOW + timedelta(seconds=1),
        )
        running = await lifecycle.start_step(
            running,
            step_id="step-observer",
            at=NOW + timedelta(seconds=2),
        )
        running = await lifecycle.finish_step(
            running,
            step_id="step-observer",
            status=StepExecutionStatus.SUCCESS,
            at=NOW + timedelta(seconds=3),
        )

        terminal = await lifecycle.finish_execution(
            running,
            status=ExecutionPlanStatus.SUCCESS,
            at=NOW + timedelta(seconds=4),
        )

        assert terminal.execution_record.status == "SUCCESS"
        stored = await store.load(context.execution_id)
        assert stored is not None
        assert stored.status == "SUCCESS"

    asyncio.run(scenario())


def test_concurrency_boundary_rejects_mismatched_tool_definition_identity() -> None:
    async def scenario() -> None:
        runtime, authority, inflight, operation_registry, ids = _tool_runtime()
        del operation_registry
        context = _context(execution_id="execution-definition-mismatch")
        parent = await _register_owner(
            inflight,
            ids,
            execution_id=context.execution_id,
            step_execution_id="step-exec-definition-mismatch",
        )

        decision = await runtime.admit(
            tool_definition=ToolDefinition(
                tool_id="OTHER_TOOL",
                version="1.0.0",
                resource_locks=["exclusive-device"],
            ),
            tool_id="DOMAIN_TOOL",
            tool_version="1.0.0",
            execution_context=context,
            step_execution_id=parent.step_execution_id,
            parent_handle_id=parent.operation_handle_id,
            logical_tool_call_id="logical-mismatch-001",
            physical_attempt=1,
        )

        assert decision.status.value == "UNKNOWN"
        assert decision.reason_codes == (
            "TOOL_CONCURRENCY_DEFINITION_IDENTITY_MISMATCH",
        )
        assert authority.active_lease("device-001:exclusive") is None
        chain = await inflight.active_chain(
            execution_id=context.execution_id,
            step_execution_id=parent.step_execution_id,
        )
        assert chain == (parent,)

    asyncio.run(scenario())


def test_control_terminal_observer_failure_does_not_reverse_cancellation() -> None:
    async def scenario() -> None:
        context = _context(execution_id="execution-control-observer")
        owner = InFlightOperationHandle(
            operation_handle_id="owner-control-observer",
            execution_id=context.execution_id,
            step_execution_id="step-exec-control-observer",
            kind=InFlightOperationKind.SKILL,
            capability_id="SKILL_A",
            capability_version="1.0.0",
            started_at=NOW,
        )
        inflight = InMemoryInFlightOperationRegistry()
        assert await inflight.register(owner) is True
        step = StepLifecycleSnapshot(
            step_execution_id=owner.step_execution_id,
            step_id="step-control-observer",
            action="ACTION_A",
            status=StepExecutionStatus.RUNNING,
            skill_id="SKILL_A",
            started_at=NOW,
        )
        prepared = PreparedExecution(
            execution_context=context,
            execution_record=ExecutionRecord(
                execution_id=context.execution_id,
                plan_id=context.plan_id,
                request_id=context.request_id,
                identity_scope=context.identity_scope,
                status="RUNNING",
                current_step=step.step_id,
                step_results=(),
                created_at=NOW - timedelta(seconds=1),
                updated_at=NOW,
            ),
            steps=(step,),
            started_at=NOW - timedelta(seconds=1),
        )
        store = InMemoryExecutionStateStore()
        assert await store.create(prepared.execution_record) is True
        signal = ExecutionControlSignal(
            signal_type=ExecutionControlSignalType.CANCEL,
            reason_code="USER_STOP",
            source="RUNTIME",
            signal_id="signal-control-observer",
            target_execution_id=context.execution_id,
            issued_at=NOW,
        )
        coordinator = ExecutionControlCoordinator(
            watcher=StaticWatcher(
                ObservedExecutionControl(
                    signal=signal,
                    observed_at=NOW + timedelta(seconds=1),
                )
            ),
            latch=InMemoryExecutionControlLatch(),
            interrupt_coordinator=InFlightInterruptCoordinator(
                registry=inflight,
                interrupt_controller=ConfirmingInterruptController(),
            ),
            application_evaluator=ExecutionControlApplicationEvaluator(),
            lifecycle_service=ExecutionControlLifecycleService(
                transitioner=ExecutionControlLifecycleTransitioner(),
                execution_store=store,
            ),
            clock=lambda: NOW + timedelta(seconds=2),
            terminal_observer=ExplodingTerminalObserver(),
        )

        result = await coordinator.watch_and_apply(prepared)

        assert result.prepared.execution_record.status == "CANCELLED"
        stored = await store.load(context.execution_id)
        assert stored is not None
        assert stored.status == "CANCELLED"

    asyncio.run(scenario())
