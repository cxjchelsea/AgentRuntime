"""Runtime Orchestrator：固定 10 节点主链的 Sequence + Wiring + Lifecycle。

Trace / Logging 作为横向能力附着，不增加业务阶段。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import TypeVar

from pydantic import ValidationError

from runtime.contracts import (
    ActionPlanDraft,
    ApprovedActionPlan,
    ExecutionResult,
    PolicyDecision,
    ResponsePlan,
    RuntimeContext,
    RuntimeInput,
    RuntimeResponse,
    SafetyPhase,
    SafetyResult,
    UnderstandingState,
    UpdateResult,
    ValidatedResult,
)
from runtime.interfaces.context import ContextBuilder
from runtime.interfaces.execution import ExecutionEngine
from runtime.interfaces.input import InputProcessor
from runtime.interfaces.planning import Planner, PlanValidator, PolicyRechecker
from runtime.interfaces.policy import PolicyEngine
from runtime.interfaces.response import (
    ResponseGenerator,
    ResponsePlanner,
    ResponseValidator,
)
from runtime.interfaces.safety import SafetyGuard
from runtime.interfaces.understanding import UnderstandingEngine
from runtime.interfaces.update import StateMemoryUpdater
from runtime.interfaces.validation import ResultValidator
from runtime.orchestration.context import RuntimeTurnOutcome, TurnExecutionContext
from runtime.orchestration.errors import (
    ContractValidationError,
    DependencyMissingError,
    OrchestrationInvariantError,
    RuntimeOrchestrationError,
    StageExecutionError,
)
from runtime.orchestration.logging import RuntimeLogHook, StdlibStructuredLogHook
from runtime.orchestration.m6_terminalization import finish_turn_once
from runtime.orchestration.trace import (
    StageEventStatus,
    StageTraceEvent,
    TraceContext,
    TraceStatus,
)
from runtime.registries import SkillRegistry
from runtime.validation.m6_no_grant_facade import (
    M6NoGrantFacadeFactory,
    M6NoGrantTurnHandle,
    TurnOriginSnapshot,
)
from runtime.validation.no_grant_downstream_policy import (
    NoGrantDownstreamDecision,
    NoGrantDownstreamDisposition,
)

StageResultType = TypeVar("StageResultType")


class M6IntegrationMode(StrEnum):
    LEGACY_TEST_COMPAT = "LEGACY_TEST_COMPAT"
    DENY_ONLY_GATED = "DENY_ONLY_GATED"


class M6DownstreamBlocked(RuntimeOrchestrationError):
    def __init__(self) -> None:
        super().__init__(
            "M6 downstream blocked",
            error_code="NO_GRANT_DOWNSTREAM_BLOCKED",
            stage_name="RESULT_VALIDATE",
        )


async def _gated_validate(
    handle: M6NoGrantTurnHandle,
    execution: ExecutionResult,
    context: RuntimeContext,
    approved: ApprovedActionPlan,
    decisions: list[NoGrantDownstreamDecision],
) -> ValidatedResult:
    bundle = await handle.validate(execution, context, approved)
    if decisions:
        raise M6DownstreamBlocked()
    decisions.append(bundle.decision)
    return bundle.validated


def _assert_denied(
    decisions: list[NoGrantDownstreamDecision],
    validated: ValidatedResult,
    execution: ExecutionResult,
    context: RuntimeContext,
    origin: TurnOriginSnapshot,
) -> None:
    if len(decisions) != 1 or type(decisions[0]) is not NoGrantDownstreamDecision:
        raise M6DownstreamBlocked()
    decision = decisions[0]
    if (
        decision.disposition is not NoGrantDownstreamDisposition.BLOCK_BEFORE_M7_M8
        or any(
            (
                decision.may_call_response_planner,
                decision.may_call_response_generator,
                decision.may_call_response_validator,
                decision.may_call_state_memory_updater,
                decision.may_emit_positive_claim,
                decision.may_commit_business_or_memory,
            )
        )
        or decision.allowed_user_response != "NONE"
        or decision.request_id != origin.request_id
        or decision.execution_id != execution.execution_id
        or decision.validation_id != validated.validation_id
        or validated.request_id != origin.request_id
        or validated.execution_id != execution.execution_id
        or context.identity_context.identity_scope != origin.identity_scope
        or context.session_context.session_id != origin.session_id
    ):
        raise M6DownstreamBlocked()


class RuntimeOrchestrator:
    """统一 Runtime Turn Pipeline。只负责调用顺序、Contract 传递与可观察性。"""

    def __init__(
        self,
        *,
        input_processor: InputProcessor,
        safety_guard: SafetyGuard,
        context_builder: ContextBuilder,
        understanding_engine: UnderstandingEngine,
        policy_engine: PolicyEngine,
        planner: Planner,
        plan_validator: PlanValidator,
        policy_rechecker: PolicyRechecker,
        execution_engine: ExecutionEngine,
        result_validator: ResultValidator,
        response_planner: ResponsePlanner,
        response_generator: ResponseGenerator,
        response_validator: ResponseValidator,
        state_memory_updater: StateMemoryUpdater,
        skill_registry: SkillRegistry | None = None,
        log_hook: RuntimeLogHook | None = None,
        m6_integration_mode: M6IntegrationMode = M6IntegrationMode.LEGACY_TEST_COMPAT,
        m6_no_grant_factory: M6NoGrantFacadeFactory | None = None,
    ) -> None:
        required_dependencies: dict[str, object | None] = {
            "input_processor": input_processor,
            "safety_guard": safety_guard,
            "context_builder": context_builder,
            "understanding_engine": understanding_engine,
            "policy_engine": policy_engine,
            "planner": planner,
            "plan_validator": plan_validator,
            "policy_rechecker": policy_rechecker,
            "execution_engine": execution_engine,
            "result_validator": result_validator,
            "response_planner": response_planner,
            "response_generator": response_generator,
            "response_validator": response_validator,
            "state_memory_updater": state_memory_updater,
        }
        missing_dependency_names = [
            dependency_name
            for dependency_name, dependency in required_dependencies.items()
            if dependency is None
        ]
        if missing_dependency_names:
            raise DependencyMissingError(missing_dependency_names)

        self.input_processor = input_processor
        self.safety_guard = safety_guard
        self.context_builder = context_builder
        self.understanding_engine = understanding_engine
        self.policy_engine = policy_engine
        self.planner = planner
        self.plan_validator = plan_validator
        self.policy_rechecker = policy_rechecker
        self.execution_engine = execution_engine
        self.result_validator = result_validator
        self.response_planner = response_planner
        self.response_generator = response_generator
        self.response_validator = response_validator
        self.state_memory_updater = state_memory_updater
        # Registry 仅可注入、可访问，不用于动态发现或执行业务
        self.skill_registry = skill_registry
        self.log_hook: RuntimeLogHook = (
            log_hook if log_hook is not None else StdlibStructuredLogHook()
        )
        if type(m6_integration_mode) is not M6IntegrationMode:
            raise ValueError("Invalid G1 integration mode")
        if m6_integration_mode is M6IntegrationMode.DENY_ONLY_GATED:
            if type(self) is not RuntimeOrchestrator:
                raise ValueError("G1 mode is not authorized for subclasses")
            if type(m6_no_grant_factory) is not M6NoGrantFacadeFactory:
                raise ValueError("Gated mode requires an exact M6 facade factory")
        elif m6_no_grant_factory is not None:
            raise ValueError("Legacy mode cannot accept a gated facade")
        self._m6_mode = m6_integration_mode
        self._m6_factory = m6_no_grant_factory
        self.last_trace: TraceContext | None = None

    async def run(self, runtime_input: RuntimeInput) -> RuntimeTurnOutcome:
        """Explicit G1 protection; inherited M2 run remains separately controlled."""
        if self._m6_mode is M6IntegrationMode.LEGACY_TEST_COMPAT:
            return await self._run_pipeline(runtime_input, None, None, None)
        origin = TurnOriginSnapshot.from_runtime_input(runtime_input)
        if self._m6_factory is None:
            raise RuntimeError("G1 factory is missing")
        handle = self._m6_factory.open_turn(origin)
        owned_turns: list[TurnExecutionContext] = []
        primary: BaseException | None = None
        try:
            await self._run_pipeline(runtime_input, origin, handle, owned_turns)
            raise M6DownstreamBlocked()
        except BaseException as error:
            primary = error
            if owned_turns:
                turn = owned_turns[0]
                reason = (
                    "TURN_CANCELLED"
                    if isinstance(error, asyncio.CancelledError)
                    else error.error_code
                    if isinstance(error, RuntimeOrchestrationError)
                    else "G1_TURN_FAILURE"
                )
                try:
                    finish_turn_once(
                        turn.trace,
                        TraceStatus.ERROR,
                        reason,
                        primary_exception=error,
                        emit_turn_end=lambda trace: self._emit_log(
                            turn, event="TURN_END", status=trace.status.value
                        ),
                    )
                except Exception:  # noqa: BLE001,S110
                    pass
            raise
        finally:
            try:
                handle.close()
            except Exception as cleanup:
                if primary is None:
                    raise StageExecutionError("M6_CLEANUP", cleanup) from cleanup

    async def _run_pipeline(
        self,
        runtime_input: RuntimeInput,
        origin: TurnOriginSnapshot | None,
        handle: M6NoGrantTurnHandle | None,
        owned_turns: list[TurnExecutionContext] | None,
    ) -> RuntimeTurnOutcome:
        """Existing stage sequence, with a single gated RESULT_VALIDATE alternative."""
        turn_context = self._open_turn(runtime_input)
        if owned_turns is not None:
            owned_turns.append(turn_context)

        processed_input = await self._run_stage(
            turn_context,
            "INPUT",
            self.input_processor.process(runtime_input),
            RuntimeInput,
            input_contract_type="RuntimeInput",
        )

        if origin is not None:
            origin.assert_processed_identity(processed_input)

        early_safety = await self._run_stage(
            turn_context,
            "SAFETY_EARLY",
            self.safety_guard.evaluate_early(processed_input),
            SafetyResult,
            input_contract_type="RuntimeInput",
            invariant_check=lambda safety_result: self._assert_safety_phase(
                safety_result, SafetyPhase.EARLY, "SAFETY_EARLY"
            ),
        )

        runtime_context = await self._run_stage(
            turn_context,
            "CONTEXT",
            self.context_builder.build(processed_input, early_safety),
            RuntimeContext,
            input_contract_type="RuntimeInput",
        )

        understanding_state = await self._run_stage(
            turn_context,
            "UNDERSTANDING",
            self.understanding_engine.understand(processed_input, runtime_context),
            UnderstandingState,
            input_contract_type="RuntimeInput",
        )

        deep_safety = await self._run_stage(
            turn_context,
            "SAFETY_DEEP",
            self.safety_guard.evaluate_deep(
                processed_input,
                runtime_context,
                understanding_state,
                early_safety,
            ),
            SafetyResult,
            input_contract_type="UnderstandingState",
            invariant_check=lambda safety_result: self._assert_safety_phase(
                safety_result, SafetyPhase.DEEP, "SAFETY_DEEP"
            ),
        )

        policy_decision = await self._run_stage(
            turn_context,
            "POLICY",
            self.policy_engine.evaluate(
                runtime_context, understanding_state, deep_safety
            ),
            PolicyDecision,
            input_contract_type="SafetyResult",
        )

        action_plan_draft = await self._run_stage(
            turn_context,
            "PLAN",
            self.planner.plan(runtime_context, understanding_state, policy_decision),
            ActionPlanDraft,
            input_contract_type="PolicyDecision",
        )

        validated_draft = await self._run_stage(
            turn_context,
            "PLAN_VALIDATE",
            self.plan_validator.validate(action_plan_draft),
            ActionPlanDraft,
            input_contract_type="ActionPlanDraft",
        )

        approved_action_plan = await self._run_stage(
            turn_context,
            "POLICY_RECHECK",
            self.policy_rechecker.recheck(validated_draft, policy_decision),
            ApprovedActionPlan,
            input_contract_type="ActionPlanDraft",
            invariant_check=self._assert_approved_for_execution,
        )

        execution_result = await self._run_stage(
            turn_context,
            "EXECUTE",
            self.execution_engine.execute(approved_action_plan, runtime_context),
            ExecutionResult,
            input_contract_type="ApprovedActionPlan",
        )

        decisions: list[NoGrantDownstreamDecision] = []
        validation_call = (
            _gated_validate(
                handle,
                execution_result,
                runtime_context,
                approved_action_plan,
                decisions,
            )
            if handle is not None
            else self.result_validator.validate(
                execution_result, runtime_context, approved_action_plan
            )
        )
        validated_result = await self._run_stage(
            turn_context,
            "RESULT_VALIDATE",
            validation_call,
            ValidatedResult,
            input_contract_type="ExecutionResult",
        )
        if origin is not None:
            _assert_denied(
                decisions, validated_result, execution_result, runtime_context, origin
            )
            raise M6DownstreamBlocked()

        response_plan = await self._run_stage(
            turn_context,
            "RESPONSE_PLAN",
            self.response_planner.plan(
                validated_result,
                runtime_context,
                understanding_state,
                approved_action_plan,
            ),
            ResponsePlan,
            input_contract_type="ValidatedResult",
        )

        generated_response = await self._run_stage(
            turn_context,
            "RESPONSE_GENERATE",
            self.response_generator.generate(response_plan),
            RuntimeResponse,
            input_contract_type="ResponsePlan",
        )

        runtime_response = await self._run_stage(
            turn_context,
            "RESPONSE_VALIDATE",
            self.response_validator.validate(generated_response, validated_result),
            RuntimeResponse,
            input_contract_type="RuntimeResponse",
        )

        update_result = await self._run_stage(
            turn_context,
            "UPDATE",
            self.state_memory_updater.update(
                processed_input,
                runtime_context,
                understanding_state,
                approved_action_plan,
                validated_result,
                runtime_response,
            ),
            UpdateResult,
            input_contract_type="RuntimeResponse",
        )

        self._close_turn(turn_context, TraceStatus.SUCCESS)
        return RuntimeTurnOutcome(
            runtime_response=runtime_response,
            update_result=update_result,
            turn_context=turn_context,
        )

    def _open_turn(self, runtime_input: RuntimeInput) -> TurnExecutionContext:
        """创建本轮 lifecycle + observability。复用 Canonical 已有 identity。"""
        trace_context = TraceContext(
            request_id=runtime_input.request_id,
            trace_id=runtime_input.trace_id,
            session_id=runtime_input.session_id,
            turn_id=uuid.uuid4().hex,
            started_at=datetime.now(UTC),
        )
        turn_context = TurnExecutionContext(trace=trace_context)
        self.last_trace = trace_context
        try:
            self._emit_log(turn_context, event="TURN_START", status="RUNNING")
        except Exception as start_error:
            if self._m6_mode is M6IntegrationMode.DENY_ONLY_GATED:
                finish_turn_once(
                    trace_context,
                    TraceStatus.ERROR,
                    "TURN_START_LOG_FAILURE",
                    primary_exception=start_error,
                    emit_turn_end=lambda trace: self._emit_log(
                        turn_context, event="TURN_END", status=trace.status.value
                    ),
                )
            raise
        return turn_context

    def _close_turn(
        self, turn_context: TurnExecutionContext, status: TraceStatus
    ) -> None:
        """结束本轮 Trace，不改写 session_id。"""
        if self._m6_mode is M6IntegrationMode.DENY_ONLY_GATED:
            finish_turn_once(
                turn_context.trace,
                status,
                turn_context.trace.error if status is TraceStatus.ERROR else None,
                emit_turn_end=lambda trace: self._emit_log(
                    turn_context, event="TURN_END", status=trace.status.value
                ),
            )
            return
        turn_context.trace.status = status
        turn_context.trace.finished_at = datetime.now(UTC)
        self.last_trace = turn_context.trace
        duration_ms = (
            turn_context.trace.finished_at - turn_context.trace.started_at
        ).total_seconds() * 1000
        self._emit_log(
            turn_context,
            event="TURN_END",
            status=status.value,
            duration_ms=duration_ms,
        )

    async def _run_stage(
        self,
        turn_context: TurnExecutionContext,
        stage_name: str,
        awaitable: Awaitable[StageResultType],
        expected_type: type[StageResultType],
        *,
        input_contract_type: str | None = None,
        invariant_check: Callable[[StageResultType], None] | None = None,
    ) -> StageResultType:
        """统一 stage wrapper：START / 调用 / 计时 / 类型校验 / END 或 ERROR。"""
        started_at = datetime.now(UTC)
        started_perf = time.perf_counter()
        stage_event = StageTraceEvent(
            stage_name=stage_name,
            trace_id=turn_context.trace.trace_id,
            started_at=started_at,
            input_contract_type=input_contract_type,
        )
        turn_context.trace.stage_events.append(stage_event)
        try:
            self._emit_log(
                turn_context,
                event="STAGE_START",
                stage_name=stage_name,
                status="STARTED",
            )
        except Exception as start_error:
            if self._m6_mode is M6IntegrationMode.DENY_ONLY_GATED:
                close = getattr(awaitable, "close", None)
                if callable(close):
                    close()
                orchestration_error = StageExecutionError(stage_name, start_error)
                self._fail_stage(
                    turn_context, stage_event, started_perf, orchestration_error
                )
                raise orchestration_error from start_error
            raise

        try:
            stage_result = await awaitable
            if not isinstance(stage_result, expected_type):
                raise ContractValidationError(
                    stage_name,
                    f"{stage_name} 返回类型不匹配: 期望 {expected_type.__name__}，"
                    f"实际 {type(stage_result).__name__}",
                )
            if invariant_check is not None:
                invariant_check(stage_result)
        except RuntimeOrchestrationError as orchestration_error:
            self._fail_stage(
                turn_context, stage_event, started_perf, orchestration_error
            )
            raise
        except ValidationError as validation_error:
            contract_error = ContractValidationError(
                stage_name, f"{stage_name} Contract 校验失败"
            )
            self._fail_stage(turn_context, stage_event, started_perf, contract_error)
            raise contract_error from validation_error
        except Exception as stage_error:
            execution_error = StageExecutionError(stage_name, stage_error)
            self._fail_stage(turn_context, stage_event, started_perf, execution_error)
            raise execution_error from stage_error

        duration_ms = (time.perf_counter() - started_perf) * 1000
        stage_event.finished_at = datetime.now(UTC)
        stage_event.duration_ms = duration_ms
        stage_event.status = StageEventStatus.SUCCESS
        stage_event.output_contract_type = type(stage_result).__name__
        # 生命周期只记类型名，避免把完整 payload 留在可观察面
        turn_context.stage_results[stage_name] = type(stage_result).__name__
        try:
            self._emit_log(
                turn_context,
                event="STAGE_END",
                stage_name=stage_name,
                status="SUCCESS",
                duration_ms=duration_ms,
                output_contract_type=type(stage_result).__name__,
            )
        except Exception as end_error:
            if self._m6_mode is M6IntegrationMode.DENY_ONLY_GATED:
                end_stage_error = StageExecutionError(stage_name, end_error)
                self._fail_stage(
                    turn_context, stage_event, started_perf, end_stage_error
                )
                raise end_stage_error from end_error
            raise
        return stage_result

    def _fail_stage(
        self,
        turn_context: TurnExecutionContext,
        stage_event: StageTraceEvent,
        started_perf: float,
        orchestration_error: RuntimeOrchestrationError,
    ) -> None:
        """标记 stage / turn 为 ERROR，并把 Trace 挂到异常上。"""
        duration_ms = (time.perf_counter() - started_perf) * 1000
        stage_event.finished_at = datetime.now(UTC)
        stage_event.duration_ms = duration_ms
        stage_event.status = StageEventStatus.ERROR
        stage_event.error_type = type(orchestration_error).__name__
        stage_event.error_message = orchestration_error.error_code
        turn_context.trace.error = orchestration_error.error_code
        orchestration_error.trace_context = turn_context.trace
        if self._m6_mode is M6IntegrationMode.DENY_ONLY_GATED:
            try:
                finish_turn_once(
                    turn_context.trace,
                    TraceStatus.ERROR,
                    orchestration_error.error_code,
                    primary_exception=orchestration_error,
                    emit_turn_end=lambda trace: self._emit_log(
                        turn_context, event="TURN_END", status=trace.status.value
                    ),
                )
            except Exception:  # noqa: BLE001,S110
                pass
            try:
                self._emit_log(
                    turn_context,
                    event="STAGE_ERROR",
                    stage_name=stage_event.stage_name,
                    status="ERROR",
                    duration_ms=duration_ms,
                    error_type=type(orchestration_error).__name__,
                )
            except Exception:  # noqa: BLE001,S110
                pass
        else:
            self._close_turn(turn_context, TraceStatus.ERROR)
            self._emit_log(
                turn_context,
                event="STAGE_ERROR",
                stage_name=stage_event.stage_name,
                status="ERROR",
                duration_ms=duration_ms,
                error_type=type(orchestration_error).__name__,
            )

    def _emit_log(
        self,
        turn_context: TurnExecutionContext,
        *,
        event: str,
        status: str,
        stage_name: str | None = None,
        duration_ms: float | None = None,
        error_type: str | None = None,
        output_contract_type: str | None = None,
    ) -> None:
        """只记录身份、阶段、状态与类型，不记录敏感 payload。"""
        record: dict[str, object] = {
            "event": event,
            "trace_id": turn_context.trace.trace_id,
            "session_id": turn_context.trace.session_id,
            "turn_id": turn_context.trace.turn_id,
            "status": status,
        }
        if stage_name is not None:
            record["stage_name"] = stage_name
        if duration_ms is not None:
            record["duration_ms"] = duration_ms
        if error_type is not None:
            record["error_type"] = error_type
        if output_contract_type is not None:
            record["output_contract_type"] = output_contract_type
        self.log_hook.emit(record)

    def _assert_safety_phase(
        self,
        safety_result: SafetyResult,
        expected_phase: SafetyPhase,
        stage_name: str,
    ) -> None:
        """Deep Safety 不产生独立 Contract，只用 phase 区分。"""
        if safety_result.phase is not expected_phase:
            raise OrchestrationInvariantError(
                stage_name,
                f"{stage_name} 的 SafetyResult.phase 必须为 {expected_phase.value}",
            )

    def _assert_approved_for_execution(
        self, approved_action_plan: ApprovedActionPlan
    ) -> None:
        """M5 永远只收到 ApprovedActionPlan，Draft 不得跨越。"""
        if isinstance(approved_action_plan, ActionPlanDraft):
            raise OrchestrationInvariantError(
                "EXECUTE", "ActionPlanDraft 不得进入 ExecutionEngine"
            )
        if not isinstance(approved_action_plan, ApprovedActionPlan):
            raise OrchestrationInvariantError(
                "EXECUTE", "ExecutionEngine 只能接收 ApprovedActionPlan"
            )
