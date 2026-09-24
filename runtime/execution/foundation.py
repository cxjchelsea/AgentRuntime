"""M5-IU1 Execution Foundation.

This unit establishes the execution lifecycle without invoking any Skill, Workflow, Tool,
network service, K0, M6 validator, response generator, or state/memory writer.

Scope:
- validate the ApprovedActionPlan execution envelope
- create an M5-only ExecutionContext from the minimum RuntimeContext projection
- allocate execution / step execution identifiers
- create and persist the initial ExecutionRecord
- maintain deterministic execution/step lifecycle transitions
- project terminal execution observations into the existing Canonical ExecutionResult
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol

from runtime.contracts import ApprovedActionPlan, ExecutionResult, RuntimeContext
from runtime.contracts.enums import ExecutionPlanStatus, PlanApprovalStatus
from runtime.contracts.execution import (
    ExecutionContext,
    ExecutionTiming,
    StepExecutionResult,
)
from runtime.contracts.planning import PLANNING_SCHEMA_VERSION
from runtime.execution.models import ExecutionRecord, StepExecutionStatus
from runtime.execution.stores import ExecutionStateStore


class ExecutionFoundationError(RuntimeError):
    """Base error for M5-IU1 execution foundation."""


class ApprovedPlanExecutionError(ExecutionFoundationError):
    """Raised when an execution input is not a valid approved-plan envelope."""


class ExecutionContextBuildError(ExecutionFoundationError):
    """Raised when the minimum M5 execution context cannot be constructed."""


class ExecutionLifecycleError(ExecutionFoundationError):
    """Raised when an execution/step lifecycle transition is invalid."""


class ExecutionIdentifierFactory(Protocol):
    def new_execution_id(self) -> str:
        """Create one execution_id."""

    def new_step_execution_id(self, step_id: str) -> str:
        """Create one step_execution_id bound to a plan step."""


@dataclass(frozen=True, slots=True)
class CallableExecutionIdentifierFactory:
    """Adapter for injected callables without imposing UUID policy on Core."""

    execution_id_factory: Callable[[], str]
    step_execution_id_factory: Callable[[str], str]

    def new_execution_id(self) -> str:
        value = self.execution_id_factory()
        if not value.strip():
            raise ExecutionContextBuildError("execution_id must not be blank")
        return value

    def new_step_execution_id(self, step_id: str) -> str:
        value = self.step_execution_id_factory(step_id)
        if not value.strip():
            raise ExecutionContextBuildError("step_execution_id must not be blank")
        return value


@dataclass(frozen=True, slots=True)
class StepLifecycleSnapshot:
    step_execution_id: str
    step_id: str
    action: str
    status: StepExecutionStatus
    skill_id: str | None = None
    workflow_id: str | None = None
    tool_call_ids: tuple[str, ...] = ()
    output: dict[str, Any] | None = None
    error: str | None = None
    retry_count: int = 0
    terminal_reason_codes: tuple[str, ...] = ()
    degraded: bool = False
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def __post_init__(self) -> None:
        values = (self.step_execution_id, self.step_id, self.action)
        if any(not value.strip() for value in values):
            raise ValueError("step lifecycle identifiers must not be blank")
        if self.retry_count < 0:
            raise ValueError("retry_count must be >= 0")
        if any(not reason.strip() for reason in self.terminal_reason_codes):
            raise ValueError("terminal_reason_codes must not contain blank values")
        if self.degraded and self.status is not StepExecutionStatus.SUCCESS:
            raise ValueError("degraded Step lifecycle requires SUCCESS status")


class PendingStepSkipAuthorityKind(str, Enum):
    SCHEDULER_SKIP = "SCHEDULER_SKIP"
    REQUIRED_PREVIOUS_STEP_NOT_SUCCESSFUL = "REQUIRED_PREVIOUS_STEP_NOT_SUCCESSFUL"


@dataclass(frozen=True, slots=True)
class PendingStepSkipAuthority:
    execution_id: str
    plan_id: str
    step_execution_id: str
    step_id: str
    kind: PendingStepSkipAuthorityKind
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        values = (
            self.execution_id,
            self.plan_id,
            self.step_execution_id,
            self.step_id,
        )
        if any(not value.strip() for value in values):
            raise ValueError("pending Step skip authority identifiers must not be blank")
        if not isinstance(self.kind, PendingStepSkipAuthorityKind):
            raise ValueError("kind must be PendingStepSkipAuthorityKind")
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError(
                "pending Step skip authority requires non-blank reason_codes"
            )
        required_failure_reason = ("REQUIRED_PREVIOUS_STEP_NOT_SUCCESSFUL",)
        if (
            self.kind
            is PendingStepSkipAuthorityKind.REQUIRED_PREVIOUS_STEP_NOT_SUCCESSFUL
            and self.reason_codes != required_failure_reason
        ):
            raise ValueError(
                "required-previous-step skip authority requires exact reason"
            )
        if (
            self.kind is PendingStepSkipAuthorityKind.SCHEDULER_SKIP
            and self.reason_codes == required_failure_reason
        ):
            raise ValueError(
                "scheduler SKIP authority cannot impersonate required-failure BLOCKED"
            )


@dataclass(frozen=True, slots=True)
class PreparedExecution:
    execution_context: ExecutionContext
    execution_record: ExecutionRecord
    steps: tuple[StepLifecycleSnapshot, ...]
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ExecutionTerminalObserver(Protocol):
    async def on_terminal_execution(
        self,
        prepared: PreparedExecution,
        *,
        observed_at: datetime,
    ) -> None:
        """Observe an already-authoritative terminal execution without rewriting it."""


class ExecutionCreationStore(ExecutionStateStore, Protocol):
    """IU1 requires atomic creation in addition to the readiness store surface."""

    async def create(self, record: ExecutionRecord) -> bool:
        """Atomically create one execution; return False when execution_id exists."""


class ApprovedPlanExecutionValidator:
    """Validate the M5 entry envelope without re-running M4/M2 decisions."""

    def __init__(
        self,
        *,
        supported_schema_versions: frozenset[str] | None = None,
    ) -> None:
        self._supported_schema_versions = supported_schema_versions or frozenset(
            {PLANNING_SCHEMA_VERSION}
        )

    def validate(self, approved_plan: ApprovedActionPlan) -> None:
        if approved_plan.approval_status is not PlanApprovalStatus.APPROVED:
            raise ApprovedPlanExecutionError("M5 accepts ApprovedActionPlan only")
        if not approved_plan.plan_id.strip() or not approved_plan.request_id.strip():
            raise ApprovedPlanExecutionError("plan_id/request_id must not be blank")
        if approved_plan.schema_version not in self._supported_schema_versions:
            raise ApprovedPlanExecutionError(
                "ApprovedActionPlan schema_version is unsupported by M5"
            )
        if not approved_plan.policy_snapshot:
            raise ApprovedPlanExecutionError(
                "ApprovedActionPlan requires non-empty policy_snapshot"
            )

        step_ids = [step.step_id for step in approved_plan.steps]
        if not step_ids:
            raise ApprovedPlanExecutionError("ApprovedActionPlan requires steps")
        if any(not step_id.strip() for step_id in step_ids):
            raise ApprovedPlanExecutionError("step_id must not be blank")
        if len(set(step_ids)) != len(step_ids):
            raise ApprovedPlanExecutionError("step_id values must be unique")

        seen: set[str] = set()
        for step in approved_plan.steps:
            dependencies = step.depends_on or []
            if any(dependency not in seen for dependency in dependencies):
                raise ApprovedPlanExecutionError(
                    "step dependencies must reference prior approved steps"
                )
            seen.add(step.step_id)


class ExecutionContextBuilder:
    """Project only M5-required fields from RuntimeContext."""

    def __init__(
        self,
        *,
        identifier_factory: ExecutionIdentifierFactory,
        deadline_resolver: Callable[
            [ApprovedActionPlan, RuntimeContext],
            datetime | None,
        ]
        | None = None,
        trace_context_resolver: Callable[
            [ApprovedActionPlan, RuntimeContext],
            dict[str, Any] | None,
        ]
        | None = None,
    ) -> None:
        self._identifier_factory = identifier_factory
        self._deadline_resolver = deadline_resolver
        self._trace_context_resolver = trace_context_resolver

    def build(
        self,
        approved_plan: ApprovedActionPlan,
        runtime_context: RuntimeContext,
    ) -> ExecutionContext:
        session_id = runtime_context.session_context.session_id
        identity_scope = runtime_context.identity_context.identity_scope
        if not session_id.strip() or not identity_scope.strip():
            raise ExecutionContextBuildError(
                "session_id and identity_scope must not be blank"
            )

        execution_id = self._identifier_factory.new_execution_id()
        tool_context = (
            runtime_context.tool_context.model_dump(mode="python")
            if runtime_context.tool_context is not None
            else None
        )
        deadline = (
            self._deadline_resolver(approved_plan, runtime_context)
            if self._deadline_resolver is not None
            else None
        )
        trace_context = (
            self._trace_context_resolver(approved_plan, runtime_context)
            if self._trace_context_resolver is not None
            else None
        )

        step_state = {
            step.step_id: {
                "action": step.action,
                "skill_id": step.skill_id,
                "workflow_id": step.workflow_id,
            }
            for step in approved_plan.steps
        }

        return ExecutionContext(
            execution_id=execution_id,
            plan_id=approved_plan.plan_id,
            request_id=approved_plan.request_id,
            session_id=session_id,
            identity_scope=identity_scope,
            policy_snapshot=dict(approved_plan.policy_snapshot),
            device_id=runtime_context.identity_context.device_id,
            current_state=runtime_context.runtime_state_context.current_state,
            step_state=step_state,
            tool_context=tool_context,
            deadline=deadline,
            cancellation_token=execution_id,
            trace_context=trace_context,
        )


class ExecutionRecordFactory:
    """Create the initial persisted execution observation."""

    def __init__(
        self,
        *,
        identifier_factory: ExecutionIdentifierFactory,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._identifier_factory = identifier_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def create(
        self,
        approved_plan: ApprovedActionPlan,
        execution_context: ExecutionContext,
    ) -> PreparedExecution:
        now = self._clock()
        step_snapshots = tuple(
            StepLifecycleSnapshot(
                step_execution_id=self._identifier_factory.new_step_execution_id(
                    step.step_id
                ),
                step_id=step.step_id,
                action=step.action,
                status=StepExecutionStatus.PENDING,
                skill_id=step.skill_id,
                workflow_id=step.workflow_id,
            )
            for step in approved_plan.steps
        )
        step_execution_ids = [item.step_execution_id for item in step_snapshots]
        if len(set(step_execution_ids)) != len(step_execution_ids):
            raise ExecutionContextBuildError(
                "step_execution_id values must be unique within one execution"
            )

        record = ExecutionRecord(
            execution_id=execution_context.execution_id,
            plan_id=approved_plan.plan_id,
            request_id=approved_plan.request_id,
            identity_scope=execution_context.identity_scope,
            status="CREATED",
            current_step=None,
            step_results=tuple(
                _snapshot_to_record_payload(item) for item in step_snapshots
            ),
            created_at=now,
            updated_at=now,
        )
        return PreparedExecution(
            execution_context=execution_context,
            execution_record=record,
            steps=step_snapshots,
        )


class ExecutionLifecycleManager:
    """Pure lifecycle transition rules for plan and step observations."""

    _TERMINAL_STEP_STATUSES = frozenset(
        {
            StepExecutionStatus.SUCCESS,
            StepExecutionStatus.FAILED,
            StepExecutionStatus.SKIPPED,
            StepExecutionStatus.CANCELLED,
            StepExecutionStatus.TIMEOUT,
            StepExecutionStatus.PREEMPTED,
        }
    )
    _TERMINAL_EXECUTION_STATUSES = frozenset(
        {
            "SUCCESS",
            "PARTIAL_SUCCESS",
            "FAILED",
            "CANCELLED",
            "TIMEOUT",
            "PREEMPTED",
        }
    )

    def start_execution(
        self,
        prepared: PreparedExecution,
        *,
        at: datetime,
    ) -> PreparedExecution:
        if prepared.execution_record.status != "CREATED":
            raise ExecutionLifecycleError("only CREATED execution can start")
        if (
            prepared.execution_record.created_at is not None
            and at < prepared.execution_record.created_at
        ):
            raise ExecutionLifecycleError("execution cannot start before creation time")
        return replace(
            prepared,
            started_at=at,
            execution_record=replace(
                prepared.execution_record,
                status="RUNNING",
                updated_at=at,
            ),
        )

    def start_step(
        self,
        prepared: PreparedExecution,
        *,
        step_id: str,
        at: datetime,
    ) -> PreparedExecution:
        target = self._step(prepared, step_id)
        if target.status is not StepExecutionStatus.PENDING:
            raise ExecutionLifecycleError("only PENDING step can start")
        if prepared.execution_record.status != "RUNNING":
            raise ExecutionLifecycleError("step requires RUNNING execution")
        if any(item.status is StepExecutionStatus.RUNNING for item in prepared.steps):
            raise ExecutionLifecycleError(
                "IU1 sequential baseline allows only one RUNNING step"
            )
        if prepared.started_at is None:
            raise ExecutionLifecycleError("step requires execution started_at")
        if at < prepared.started_at:
            raise ExecutionLifecycleError(
                "step cannot start before execution start time"
            )

        steps = tuple(
            replace(item, status=StepExecutionStatus.RUNNING, started_at=at)
            if item.step_id == step_id
            else item
            for item in prepared.steps
        )
        return self._replace_steps(
            prepared,
            steps,
            current_step=step_id,
            updated_at=at,
        )

    def finish_step(
        self,
        prepared: PreparedExecution,
        *,
        step_id: str,
        status: StepExecutionStatus,
        at: datetime,
        output: dict[str, Any] | None = None,
        error: str | None = None,
        tool_call_ids: tuple[str, ...] = (),
        retry_count: int | None = None,
        terminal_reason_codes: tuple[str, ...] = (),
        degraded: bool = False,
    ) -> PreparedExecution:
        target = self._step(prepared, step_id)
        if target.status is not StepExecutionStatus.RUNNING:
            raise ExecutionLifecycleError("only RUNNING step can finish")
        if status not in self._TERMINAL_STEP_STATUSES:
            raise ExecutionLifecycleError("finish_step requires terminal status")
        if target.started_at is not None and at < target.started_at:
            raise ExecutionLifecycleError("step cannot finish before it starts")
        if retry_count is not None and retry_count < 0:
            raise ExecutionLifecycleError("retry_count must be >= 0")
        if any(not reason.strip() for reason in terminal_reason_codes):
            raise ExecutionLifecycleError(
                "terminal_reason_codes must not contain blank values"
            )
        if degraded and status is not StepExecutionStatus.SUCCESS:
            raise ExecutionLifecycleError(
                "degraded Step lifecycle requires SUCCESS status"
            )

        steps = tuple(
            replace(
                item,
                status=status,
                output=output,
                error=error,
                tool_call_ids=tool_call_ids,
                retry_count=item.retry_count if retry_count is None else retry_count,
                terminal_reason_codes=terminal_reason_codes,
                degraded=degraded,
                finished_at=at,
            )
            if item.step_id == step_id
            else item
            for item in prepared.steps
        )
        return self._replace_steps(
            prepared,
            steps,
            current_step=None,
            updated_at=at,
        )

    def skip_pending_step(
        self,
        prepared: PreparedExecution,
        *,
        authority: PendingStepSkipAuthority,
        at: datetime,
    ) -> PreparedExecution:
        """Terminalize one exact unstarted PENDING Step as SKIPPED."""

        if prepared.execution_record.status != "RUNNING":
            raise ExecutionLifecycleError(
                "pending Step skip requires RUNNING execution"
            )
        if (
            authority.execution_id != prepared.execution_context.execution_id
            or authority.execution_id != prepared.execution_record.execution_id
            or authority.plan_id != prepared.execution_record.plan_id
        ):
            raise ExecutionLifecycleError(
                "pending Step skip authority does not match execution provenance"
            )
        if any(
            item.status is StepExecutionStatus.RUNNING for item in prepared.steps
        ):
            raise ExecutionLifecycleError(
                "pending Step skip cannot occur while another Step is RUNNING"
            )

        target = self._step(prepared, authority.step_id)
        if target.step_execution_id != authority.step_execution_id:
            raise ExecutionLifecycleError(
                "pending Step skip authority step_execution_id mismatch"
            )
        if target.status is not StepExecutionStatus.PENDING:
            raise ExecutionLifecycleError(
                "only PENDING Step can be scheduler-terminalized"
            )
        if target.started_at is not None:
            raise ExecutionLifecycleError(
                "PENDING Step selected for skip must not have started_at"
            )
        if (
            prepared.execution_record.updated_at is not None
            and at < prepared.execution_record.updated_at
        ):
            raise ExecutionLifecycleError(
                "pending Step skip cannot precede latest execution observation"
            )

        steps = tuple(
            replace(
                item,
                status=StepExecutionStatus.SKIPPED,
                terminal_reason_codes=authority.reason_codes,
                finished_at=at,
            )
            if item.step_id == authority.step_id
            else item
            for item in prepared.steps
        )
        return self._replace_steps(
            prepared,
            steps,
            current_step=None,
            updated_at=at,
        )

    def finish_execution(
        self,
        prepared: PreparedExecution,
        *,
        status: ExecutionPlanStatus,
        at: datetime,
    ) -> PreparedExecution:
        if prepared.execution_record.status != "RUNNING":
            raise ExecutionLifecycleError("only RUNNING execution can finish")
        if any(
            item.status in {StepExecutionStatus.PENDING, StepExecutionStatus.RUNNING}
            for item in prepared.steps
        ):
            raise ExecutionLifecycleError(
                "execution cannot finish while a step is non-terminal"
            )
        if (
            prepared.execution_record.updated_at is not None
            and at < prepared.execution_record.updated_at
        ):
            raise ExecutionLifecycleError(
                "execution cannot finish before its last observation"
            )
        value = status.value
        if value not in self._TERMINAL_EXECUTION_STATUSES:
            raise ExecutionLifecycleError("execution terminal status is unsupported")
        if prepared.started_at is None:
            raise ExecutionLifecycleError("terminal execution requires started_at")
        if at < prepared.started_at:
            raise ExecutionLifecycleError("execution cannot finish before it starts")
        return replace(
            prepared,
            finished_at=at,
            execution_record=replace(
                prepared.execution_record,
                status=value,
                current_step=None,
                step_results=tuple(
                    _snapshot_to_record_payload(item) for item in prepared.steps
                ),
                updated_at=at,
            ),
        )

    @staticmethod
    def _step(
        prepared: PreparedExecution,
        step_id: str,
    ) -> StepLifecycleSnapshot:
        matches = [item for item in prepared.steps if item.step_id == step_id]
        if len(matches) != 1:
            raise ExecutionLifecycleError(
                "step_id must resolve to exactly one prepared step"
            )
        return matches[0]

    @staticmethod
    def _replace_steps(
        prepared: PreparedExecution,
        steps: tuple[StepLifecycleSnapshot, ...],
        *,
        current_step: str | None,
        updated_at: datetime,
    ) -> PreparedExecution:
        return replace(
            prepared,
            steps=steps,
            execution_record=replace(
                prepared.execution_record,
                current_step=current_step,
                step_results=tuple(_snapshot_to_record_payload(item) for item in steps),
                updated_at=updated_at,
            ),
        )


class ExecutionLifecycleService:
    """Persist every authoritative lifecycle transition.

    ExecutionLifecycleManager remains a pure transition engine. This service is the
    M5-IU1 mutation boundary: callers that change execution/step lifecycle state must
    go through it so ExecutionStateStore remains aligned with PreparedExecution.
    """

    def __init__(
        self,
        *,
        lifecycle_manager: ExecutionLifecycleManager,
        execution_store: ExecutionStateStore,
        terminal_observer: ExecutionTerminalObserver | None = None,
    ) -> None:
        self._lifecycle_manager = lifecycle_manager
        self._execution_store = execution_store
        self._terminal_observer = terminal_observer

    async def start_execution(
        self,
        prepared: PreparedExecution,
        *,
        at: datetime,
    ) -> PreparedExecution:
        updated = self._lifecycle_manager.start_execution(prepared, at=at)
        await self._persist(updated)
        return updated

    async def start_step(
        self,
        prepared: PreparedExecution,
        *,
        step_id: str,
        at: datetime,
    ) -> PreparedExecution:
        updated = self._lifecycle_manager.start_step(
            prepared,
            step_id=step_id,
            at=at,
        )
        await self._persist(updated)
        return updated

    async def finish_step(
        self,
        prepared: PreparedExecution,
        *,
        step_id: str,
        status: StepExecutionStatus,
        at: datetime,
        output: dict[str, Any] | None = None,
        error: str | None = None,
        tool_call_ids: tuple[str, ...] = (),
        retry_count: int | None = None,
        terminal_reason_codes: tuple[str, ...] = (),
        degraded: bool = False,
    ) -> PreparedExecution:
        updated = self._lifecycle_manager.finish_step(
            prepared,
            step_id=step_id,
            status=status,
            at=at,
            output=output,
            error=error,
            tool_call_ids=tool_call_ids,
            retry_count=retry_count,
            terminal_reason_codes=terminal_reason_codes,
            degraded=degraded,
        )
        await self._persist(updated)
        return updated

    async def skip_pending_step(
        self,
        prepared: PreparedExecution,
        *,
        authority: PendingStepSkipAuthority,
        at: datetime,
    ) -> PreparedExecution:
        updated = self._lifecycle_manager.skip_pending_step(
            prepared,
            authority=authority,
            at=at,
        )
        await self._persist(updated)
        return updated

    async def finish_execution(
        self,
        prepared: PreparedExecution,
        *,
        status: ExecutionPlanStatus,
        at: datetime,
    ) -> PreparedExecution:
        updated = self._lifecycle_manager.finish_execution(
            prepared,
            status=status,
            at=at,
        )
        await self._persist(updated)
        if self._terminal_observer is not None:
            try:
                await self._terminal_observer.on_terminal_execution(
                    updated,
                    observed_at=at,
                )
            except Exception:  # noqa: BLE001,S110
                # Terminal lifecycle is already authoritative and persisted.
                # Observer uncertainty must retain its side authority, not
                # retroactively make the lifecycle transition appear failed.
                pass
        return updated

    async def _persist(self, prepared: PreparedExecution) -> None:
        await self._execution_store.save(prepared.execution_record)


class ExecutionResultProjector:
    """Project terminal M5 observations into the existing Canonical ExecutionResult."""

    _STATUS_MAP: Mapping[str, ExecutionPlanStatus] = {
        item.value: item for item in ExecutionPlanStatus
    }

    def project(self, prepared: PreparedExecution) -> ExecutionResult:
        status = self._STATUS_MAP.get(prepared.execution_record.status)
        if status is None:
            raise ExecutionLifecycleError(
                "ExecutionResult requires a terminal execution status"
            )
        if prepared.execution_record.created_at is None:
            raise ExecutionLifecycleError("ExecutionRecord requires created_at")
        if prepared.execution_record.updated_at is None:
            raise ExecutionLifecycleError("ExecutionRecord requires updated_at")

        return ExecutionResult(
            execution_id=prepared.execution_record.execution_id,
            plan_id=prepared.execution_record.plan_id,
            request_id=prepared.execution_record.request_id,
            identity_scope=prepared.execution_record.identity_scope,
            plan_status=status,
            step_results=[
                StepExecutionResult(
                    step_execution_id=item.step_execution_id,
                    step_id=item.step_id,
                    action=item.action,
                    status=item.status.value,
                    skill_id=item.skill_id,
                    workflow_id=item.workflow_id,
                    tool_call_ids=list(item.tool_call_ids) or None,
                    output=item.output,
                    error=item.error,
                    retry_count=item.retry_count,
                    started_at=item.started_at,
                    finished_at=item.finished_at,
                )
                for item in prepared.steps
            ],
            timing=ExecutionTiming(
                started_at=prepared.started_at,
                finished_at=prepared.finished_at,
            ),
            skill_results=None,
            workflow_result=None,
            tool_results=None,
            business_outputs=None,
            execution_events=None,
            state_observations=None,
            errors=None,
            cancellation=None,
            quality=None,
        )


class ExecutionFoundation:
    """M5-IU1 initializer; no capability execution occurs here."""

    def __init__(
        self,
        *,
        plan_validator: ApprovedPlanExecutionValidator,
        context_builder: ExecutionContextBuilder,
        record_factory: ExecutionRecordFactory,
        execution_store: ExecutionCreationStore,
    ) -> None:
        self._plan_validator = plan_validator
        self._context_builder = context_builder
        self._record_factory = record_factory
        self._execution_store = execution_store

    async def initialize(
        self,
        approved_plan: ApprovedActionPlan,
        runtime_context: RuntimeContext,
    ) -> PreparedExecution:
        self._plan_validator.validate(approved_plan)
        execution_context = self._context_builder.build(
            approved_plan,
            runtime_context,
        )
        prepared = self._record_factory.create(
            approved_plan,
            execution_context,
        )
        created = await self._execution_store.create(prepared.execution_record)
        if not created:
            raise ExecutionLifecycleError(
                "execution_id already exists in ExecutionStateStore"
            )
        return prepared


class InMemoryExecutionStateStore:
    """Simple M5-IU1 store for mechanism tests; not a production persistence claim."""

    def __init__(self) -> None:
        self._records: dict[str, ExecutionRecord] = {}

    async def create(self, record: ExecutionRecord) -> bool:
        if record.execution_id in self._records:
            return False
        self._records[record.execution_id] = record
        return True

    async def save(self, record: ExecutionRecord) -> None:
        existing = self._records.get(record.execution_id)
        if existing is not None and (
            existing.plan_id != record.plan_id
            or existing.request_id != record.request_id
            or existing.identity_scope != record.identity_scope
        ):
            raise ExecutionLifecycleError(
                "execution_id cannot be rebound to another plan/request/identity scope"
            )
        if (
            existing is not None
            and existing.updated_at is not None
            and record.updated_at is not None
            and record.updated_at < existing.updated_at
        ):
            raise ExecutionLifecycleError(
                "execution observation cannot move backward in time"
            )
        self._records[record.execution_id] = record

    async def load(self, execution_id: str) -> ExecutionRecord | None:
        return self._records.get(execution_id)


def _snapshot_to_record_payload(snapshot: StepLifecycleSnapshot) -> dict[str, Any]:
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
        "terminal_reason_codes": list(snapshot.terminal_reason_codes),
        "degraded": snapshot.degraded,
        "started_at": snapshot.started_at,
        "finished_at": snapshot.finished_at,
    }
