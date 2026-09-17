"""M0-IU2：Module Interface 最小校验。

只验证接口可被 Stub 实现、输入输出为 Canonical Contract。
不在 runtime/ 中放置真实业务 Stub。
"""

from __future__ import annotations

import ast
import asyncio
import inspect
from datetime import UTC, datetime
from pathlib import Path

import pytest

from runtime.contracts import (
    ActionPlanDraft,
    ApprovedActionPlan,
    BusinessStatus,
    ClaimPlan,
    ClaimPolicy,
    CommitResult,
    CommitStatus,
    CoreControlAction,
    CoreControlIntent,
    ExecutionPlanStatus,
    ExecutionResult,
    ExecutionTiming,
    IdentityContext,
    IdentityStatus,
    InputSource,
    InputTriggerType,
    IntentEvidenceSource,
    IntentResult,
    MemoryUpdate,
    PlanApprovalStatus,
    PlanningGoal,
    PlanningMode,
    PolicyDecision,
    QualityAssessment,
    ResponsePlan,
    ResponseRequirement,
    ResponseType,
    ResponseValidationStatus,
    RuntimeContext,
    RuntimeControlState,
    RuntimeInput,
    RuntimeResponse,
    RuntimeStateContext,
    SafetyPhase,
    SafetyResult,
    SafetyRiskLevel,
    SessionContext,
    StateUpdate,
    TransitionStatus,
    UnderstandingMetadata,
    UnderstandingState,
    UpdateResult,
    ValidatedResult,
    ValidationMode,
    ValidationStatus,
)
from runtime.contracts.planning import ActionStep
from runtime.contracts.understanding import ProcessingPath
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


def _utc_now() -> datetime:
    """生成带时区的当前时间。"""
    return datetime.now(UTC)


def _runtime_input() -> RuntimeInput:
    return RuntimeInput(
        request_id="request-001",
        trace_id="trace-001",
        session_id="session-001",
        subject_id="subject-001",
        identity_scope="scope-001",
        source=InputSource.USER,
        trigger_type=InputTriggerType.USER_TEXT,
        timestamp=_utc_now(),
    )


def _runtime_context() -> RuntimeContext:
    return RuntimeContext(
        identity_context=IdentityContext(
            subject_id="subject-001",
            identity_scope="scope-001",
            identity_status=IdentityStatus.BOUND,
        ),
        session_context=SessionContext(session_id="session-001"),
        runtime_state_context=RuntimeStateContext(
            current_state=RuntimeControlState.IDLE,
            previous_state=None,
            interruptible=True,
            entered_at=_utc_now(),
        ),
    )


def _safety_result(phase: SafetyPhase) -> SafetyResult:
    return SafetyResult(
        safety_result_id="safety-001",
        request_id="request-001",
        phase=phase,
        risk_detected=False,
        risk_level=SafetyRiskLevel.NONE,
        interrupt_current_task=False,
        allowed_to_continue_normal_flow=True,
        safety_lock_required=False,
        reason_codes=["SAFE"],
        created_at=_utc_now(),
    )


def _understanding_state_valid() -> UnderstandingState:
    from runtime.contracts.understanding import UncertaintyAssessment

    return UnderstandingState(
        metadata=UnderstandingMetadata(
            understanding_id="understanding-001",
            request_id="request-001",
            timestamp=_utc_now(),
            processing_path=ProcessingPath.DEGRADED_PATH,
        ),
        intents=[
            IntentResult(
                intent_id=CoreControlIntent.UNKNOWN.value,
                confidence=0.0,
                source=IntentEvidenceSource.RULE,
            )
        ],
        uncertainty=UncertaintyAssessment(),
        quality=QualityAssessment(),
    )


def _policy_decision() -> PolicyDecision:
    return PolicyDecision(
        policy_decision_id="policy-001",
        allowed=True,
        blocked=False,
        priority=50,
        interrupt_current_task=False,
        validation_mode=ValidationMode.STANDARD,
        reason_codes=["ALLOW"],
        created_at=_utc_now(),
    )


def _action_plan_draft() -> ActionPlanDraft:
    return ActionPlanDraft(
        plan_id="plan-001",
        request_id="request-001",
        approval_status=PlanApprovalStatus.DRAFT,
        planning_mode=PlanningMode.DEGRADED,
        goals=[PlanningGoal(goal_id="goal-001")],
        steps=[ActionStep(step_id="step-001", action=CoreControlAction.WAIT.value)],
        quality=QualityAssessment(),
    )


def _approved_action_plan() -> ApprovedActionPlan:
    return ApprovedActionPlan(
        plan_id="plan-001",
        request_id="request-001",
        approval_status=PlanApprovalStatus.APPROVED,
        planning_mode=PlanningMode.DEGRADED,
        goals=[PlanningGoal(goal_id="goal-001")],
        steps=[ActionStep(step_id="step-001", action=CoreControlAction.WAIT.value)],
        policy_snapshot={"allowed": True},
        quality=QualityAssessment(),
    )


def _execution_result() -> ExecutionResult:
    return ExecutionResult(
        execution_id="execution-001",
        plan_id="plan-001",
        request_id="request-001",
        identity_scope="scope-001",
        plan_status=ExecutionPlanStatus.SUCCESS,
        step_results=[],
        timing=ExecutionTiming(),
    )


def _validated_result() -> ValidatedResult:
    return ValidatedResult(
        validation_id="validation-001",
        execution_id="execution-001",
        request_id="request-001",
        validation_status=ValidationStatus.VALIDATED,
        business_status=BusinessStatus.SUCCESS,
        claim_policy=ClaimPolicy(allowed_claims=[], forbidden_claims=[]),
    )


def _response_plan() -> ResponsePlan:
    return ResponsePlan(
        response_plan_id="response-plan-001",
        request_id="request-001",
        response_requirement=ResponseRequirement(
            required=True, response_type=ResponseType.NORMAL
        ),
        claim_plan=ClaimPlan(must_include_claims=[], forbidden_claims=[]),
    )


def _runtime_response() -> RuntimeResponse:
    return RuntimeResponse(
        response_id="response-001",
        request_id="request-001",
        response_type=ResponseType.NORMAL,
        payload={"text": "ok"},
        response_validation_status=ResponseValidationStatus.VALID,
    )


def _update_result() -> UpdateResult:
    return UpdateResult(
        update_id="update-001",
        request_id="request-001",
        identity_scope="scope-001",
        state_update=StateUpdate(
            previous_state=RuntimeControlState.IDLE,
            proposed_state=RuntimeControlState.PROCESSING,
            transition_status=TransitionStatus.NOT_REQUIRED,
        ),
        commit_result=CommitResult(status=CommitStatus.ATOMIC),
        memory_update=MemoryUpdate(identity_scope="scope-001", writes=[]),
    )


class _InputProcessorStub(InputProcessor):
    async def process(self, runtime_input: RuntimeInput) -> RuntimeInput:
        return runtime_input


class _SafetyGuardStub(SafetyGuard):
    async def evaluate_early(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext | None = None,
    ) -> SafetyResult:
        return _safety_result(SafetyPhase.EARLY)

    async def evaluate_deep(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        early_safety: SafetyResult,
    ) -> SafetyResult:
        return _safety_result(SafetyPhase.DEEP)


class _ContextBuilderStub(ContextBuilder):
    async def build(
        self,
        runtime_input: RuntimeInput,
        safety_result: SafetyResult,
    ) -> RuntimeContext:
        return _runtime_context()


class _UnderstandingEngineStub(UnderstandingEngine):
    async def understand(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext,
    ) -> UnderstandingState:
        return _understanding_state_valid()


class _PolicyEngineStub(PolicyEngine):
    async def evaluate(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        safety_result: SafetyResult,
    ) -> PolicyDecision:
        return _policy_decision()


class _PlannerStub(Planner):
    async def plan(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        policy_decision: PolicyDecision,
    ) -> ActionPlanDraft:
        return _action_plan_draft()


class _PlanValidatorStub(PlanValidator):
    async def validate(self, action_plan_draft: ActionPlanDraft) -> ActionPlanDraft:
        return action_plan_draft


class _PolicyRecheckerStub(PolicyRechecker):
    async def recheck(
        self,
        action_plan_draft: ActionPlanDraft,
        policy_decision: PolicyDecision,
    ) -> ApprovedActionPlan:
        return _approved_action_plan()


class _ExecutionEngineStub(ExecutionEngine):
    async def execute(
        self,
        approved_action_plan: ApprovedActionPlan,
        runtime_context: RuntimeContext,
    ) -> ExecutionResult:
        if not isinstance(approved_action_plan, ApprovedActionPlan):
            raise TypeError("ExecutionEngine 只接受 ApprovedActionPlan")
        return _execution_result()


class _ResultValidatorStub(ResultValidator):
    async def validate(
        self,
        execution_result: ExecutionResult,
        runtime_context: RuntimeContext,
        approved_action_plan: ApprovedActionPlan,
    ) -> ValidatedResult:
        return _validated_result()


class _ResponsePlannerStub(ResponsePlanner):
    async def plan(
        self,
        validated_result: ValidatedResult,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        approved_action_plan: ApprovedActionPlan,
    ) -> ResponsePlan:
        return _response_plan()


class _ResponseGeneratorStub(ResponseGenerator):
    async def generate(self, response_plan: ResponsePlan) -> RuntimeResponse:
        return _runtime_response()


class _ResponseValidatorStub(ResponseValidator):
    async def validate(
        self,
        runtime_response: RuntimeResponse,
        validated_result: ValidatedResult,
    ) -> RuntimeResponse:
        return runtime_response


class _StateMemoryUpdaterStub(StateMemoryUpdater):
    async def update(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        approved_action_plan: ApprovedActionPlan,
        validated_result: ValidatedResult,
        runtime_response: RuntimeResponse,
    ) -> UpdateResult:
        return _update_result()


INTERFACE_TYPES = [
    InputProcessor,
    SafetyGuard,
    ContextBuilder,
    UnderstandingEngine,
    PolicyEngine,
    Planner,
    PlanValidator,
    PolicyRechecker,
    ExecutionEngine,
    ResultValidator,
    ResponsePlanner,
    ResponseGenerator,
    ResponseValidator,
    StateMemoryUpdater,
]


def test_all_interfaces_can_be_stubbed() -> None:
    """所有 Core Interface 都可以被最小 Stub 实现。"""

    async def exercise_interfaces() -> None:
        input_processor = _InputProcessorStub()
        safety_guard = _SafetyGuardStub()
        context_builder = _ContextBuilderStub()
        understanding_engine = _UnderstandingEngineStub()
        policy_engine = _PolicyEngineStub()
        planner = _PlannerStub()
        plan_validator = _PlanValidatorStub()
        policy_rechecker = _PolicyRecheckerStub()
        execution_engine = _ExecutionEngineStub()
        result_validator = _ResultValidatorStub()
        response_planner = _ResponsePlannerStub()
        response_generator = _ResponseGeneratorStub()
        response_validator = _ResponseValidatorStub()
        state_memory_updater = _StateMemoryUpdaterStub()

        runtime_input = await input_processor.process(_runtime_input())
        early_safety = await safety_guard.evaluate_early(runtime_input)
        runtime_context = await context_builder.build(runtime_input, early_safety)
        understanding_state = await understanding_engine.understand(
            runtime_input, runtime_context
        )
        deep_safety = await safety_guard.evaluate_deep(
            runtime_input, runtime_context, understanding_state, early_safety
        )
        policy_decision = await policy_engine.evaluate(
            runtime_context, understanding_state, deep_safety
        )
        action_plan_draft = await planner.plan(
            runtime_context, understanding_state, policy_decision
        )
        validated_draft = await plan_validator.validate(action_plan_draft)
        approved_action_plan = await policy_rechecker.recheck(
            validated_draft, policy_decision
        )
        execution_result = await execution_engine.execute(
            approved_action_plan, runtime_context
        )
        validated_result = await result_validator.validate(
            execution_result, runtime_context, approved_action_plan
        )
        response_plan = await response_planner.plan(
            validated_result,
            runtime_context,
            understanding_state,
            approved_action_plan,
        )
        runtime_response = await response_generator.generate(response_plan)
        checked_response = await response_validator.validate(
            runtime_response, validated_result
        )
        update_result = await state_memory_updater.update(
            runtime_input,
            runtime_context,
            understanding_state,
            approved_action_plan,
            validated_result,
            checked_response,
        )

        assert isinstance(runtime_input, RuntimeInput)
        assert isinstance(early_safety, SafetyResult)
        assert isinstance(runtime_context, RuntimeContext)
        assert isinstance(understanding_state, UnderstandingState)
        assert isinstance(policy_decision, PolicyDecision)
        assert isinstance(action_plan_draft, ActionPlanDraft)
        assert isinstance(approved_action_plan, ApprovedActionPlan)
        assert isinstance(execution_result, ExecutionResult)
        assert isinstance(validated_result, ValidatedResult)
        assert isinstance(response_plan, ResponsePlan)
        assert isinstance(runtime_response, RuntimeResponse)
        assert isinstance(update_result, UpdateResult)

    asyncio.run(exercise_interfaces())


def test_execution_engine_annotation_accepts_only_approved_plan() -> None:
    """ExecutionEngine 正式输入注解必须是 ApprovedActionPlan。"""
    execute_signature = inspect.signature(ExecutionEngine.execute)
    approved_plan_parameter = execute_signature.parameters["approved_action_plan"]
    assert approved_plan_parameter.annotation is ApprovedActionPlan
    assert ActionPlanDraft is not approved_plan_parameter.annotation


def test_execution_engine_stub_rejects_draft_plan() -> None:
    """ActionPlanDraft 不允许作为 M5 正式输入。"""

    async def reject_draft() -> None:
        execution_engine = _ExecutionEngineStub()
        with pytest.raises(TypeError):
            await execution_engine.execute(_action_plan_draft(), _runtime_context())  # type: ignore[arg-type]

    asyncio.run(reject_draft())


def test_safety_early_and_deep_return_same_contract() -> None:
    """Safety EARLY / DEEP 都返回 SafetyResult，不存在独立 Contract。"""

    async def evaluate_both_phases() -> None:
        safety_guard = _SafetyGuardStub()
        runtime_input = _runtime_input()
        runtime_context = _runtime_context()
        early_safety = await safety_guard.evaluate_early(runtime_input, runtime_context)
        deep_safety = await safety_guard.evaluate_deep(
            runtime_input, runtime_context, _understanding_state_valid(), early_safety
        )
        assert type(early_safety) is SafetyResult
        assert type(deep_safety) is SafetyResult
        assert early_safety.phase is SafetyPhase.EARLY
        assert deep_safety.phase is SafetyPhase.DEEP

    asyncio.run(evaluate_both_phases())


def test_response_generator_consumes_only_response_plan() -> None:
    """ResponseGenerator 只消费 ResponsePlan。"""
    generate_signature = inspect.signature(ResponseGenerator.generate)
    response_plan_parameter = generate_signature.parameters["response_plan"]
    assert response_plan_parameter.annotation is ResponsePlan

    async def generate_from_plan() -> None:
        runtime_response = await _ResponseGeneratorStub().generate(_response_plan())
        assert isinstance(runtime_response, RuntimeResponse)

    asyncio.run(generate_from_plan())


def test_state_memory_updater_returns_update_result() -> None:
    """StateMemoryUpdater 正式输出只能是 UpdateResult。"""
    update_signature = inspect.signature(StateMemoryUpdater.update)
    assert update_signature.return_annotation is UpdateResult

    async def commit_update() -> None:
        update_result = await _StateMemoryUpdaterStub().update(
            _runtime_input(),
            _runtime_context(),
            _understanding_state_valid(),
            _approved_action_plan(),
            _validated_result(),
            _runtime_response(),
        )
        assert isinstance(update_result, UpdateResult)
        assert isinstance(update_result.state_update, StateUpdate)

    asyncio.run(commit_update())


def test_interfaces_have_no_domain_specific_tokens() -> None:
    """接口源码不得出现 Domain 专属语义。"""
    forbidden_tokens = {
        "elder",
        "patient",
        "student",
        "customer",
        "PLAY_CONTENT",
        "DISCOMFORT",
        "REMINDER",
        "clinical",
        "companion",
    }
    interfaces_directory = Path("runtime/interfaces")
    for python_file in interfaces_directory.glob("*.py"):
        source_text = python_file.read_text(encoding="utf-8")
        for forbidden_token in forbidden_tokens:
            assert forbidden_token not in source_text, python_file.name


def test_all_interface_methods_are_async() -> None:
    """所有接口方法遵守统一 async 模型。"""
    for interface_type in INTERFACE_TYPES:
        for method_name, method_object in inspect.getmembers(
            interface_type, predicate=inspect.isfunction
        ):
            if method_name.startswith("_"):
                continue
            assert inspect.iscoroutinefunction(method_object), method_name


def test_runtime_core_has_no_orchestrator_or_business_logic() -> None:
    """Runtime Core 尚未出现编排器或真实业务逻辑。"""
    runtime_root = Path("runtime")
    forbidden_names = {"Orchestrator", "RuntimeLoop", "handle_request"}
    collected_source = []
    for python_file in runtime_root.rglob("*.py"):
        collected_source.append(python_file.read_text(encoding="utf-8"))
        module_tree = ast.parse(python_file.read_text(encoding="utf-8"))
        for syntax_node in ast.walk(module_tree):
            if isinstance(syntax_node, ast.ClassDef):
                assert syntax_node.name not in forbidden_names
    joined_source = "\n".join(collected_source)
    defined_class_names = {
        syntax_node.name
        for python_file in runtime_root.rglob("*.py")
        for syntax_node in ast.walk(ast.parse(python_file.read_text(encoding="utf-8")))
        if isinstance(syntax_node, ast.ClassDef)
    }
    assert "PLAY_CONTENT" not in joined_source
    assert "ActionPlan" not in defined_class_names


def test_planner_outputs_draft_and_rechecker_outputs_approved() -> None:
    """Planner → Draft，PolicyRechecker → Approved。"""
    planner_return = inspect.signature(Planner.plan).return_annotation
    rechecker_return = inspect.signature(PolicyRechecker.recheck).return_annotation
    assert planner_return is ActionPlanDraft
    assert rechecker_return is ApprovedActionPlan
    assert "ActionPlan" not in dir(
        __import__("runtime.interfaces.planning", fromlist=["*"])
    )
