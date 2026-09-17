"""Runtime Orchestrator：固定 10 节点主链的 Sequence + Wiring + Lifecycle。

Trace / Logging 作为横向能力附着，不增加业务阶段。
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
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
from runtime.orchestration.trace import (
    StageEventStatus,
    StageTraceEvent,
    TraceContext,
    TraceStatus,
)
from runtime.registries import SkillRegistry

StageResultType = TypeVar("StageResultType")


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
        self.last_trace: TraceContext | None = None

    async def run(self, runtime_input: RuntimeInput) -> RuntimeTurnOutcome:
        """按冻结主链执行一轮。成功才返回 Response + UpdateResult。"""
        turn_context = self._open_turn(runtime_input)

        processed_input = await self._run_stage(
            turn_context,
            "INPUT",
            self.input_processor.process(runtime_input),
            RuntimeInput,
            input_contract_type="RuntimeInput",
        )

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

        validated_result = await self._run_stage(
            turn_context,
            "RESULT_VALIDATE",
            self.result_validator.validate(
                execution_result, runtime_context, approved_action_plan
            ),
            ValidatedResult,
            input_contract_type="ExecutionResult",
        )

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
        self._emit_log(turn_context, event="TURN_START", status="RUNNING")
        return turn_context

    def _close_turn(
        self, turn_context: TurnExecutionContext, status: TraceStatus
    ) -> None:
        """结束本轮 Trace，不改写 session_id。"""
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
        self._emit_log(
            turn_context,
            event="STAGE_START",
            stage_name=stage_name,
            status="STARTED",
        )

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
        self._emit_log(
            turn_context,
            event="STAGE_END",
            stage_name=stage_name,
            status="SUCCESS",
            duration_ms=duration_ms,
            output_contract_type=type(stage_result).__name__,
        )
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
        self._close_turn(turn_context, TraceStatus.ERROR)
        orchestration_error.trace_context = turn_context.trace
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
