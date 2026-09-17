"""M0-IU4 测试用 Stub。只返回合法 Canonical Contract，不含业务语义。

不得放入 runtime/。不得调用 LLM / Tool / 真实 Domain。
"""

from __future__ import annotations

from datetime import UTC, datetime

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
from runtime.contracts.understanding import ProcessingPath, UncertaintyAssessment
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


class CallRecorder:
    """记录实现层 15 个调用点，供顺序断言。"""

    def __init__(self) -> None:
        self.entries: list[str] = []

    def record(self, stage_name: str) -> None:
        """追加一次调用点。"""
        self.entries.append(stage_name)


def utc_now() -> datetime:
    """带时区的当前时间。"""
    return datetime.now(UTC)


def build_runtime_input(
    *,
    request_id: str = "request-001",
    trace_id: str = "trace-001",
    session_id: str = "session-001",
    text: str | None = None,
    input_payload: dict[str, object] | None = None,
) -> RuntimeInput:
    """构造最小合法 RuntimeInput。"""
    return RuntimeInput(
        request_id=request_id,
        trace_id=trace_id,
        session_id=session_id,
        subject_id="subject-001",
        identity_scope="scope-001",
        source=InputSource.USER,
        trigger_type=InputTriggerType.USER_TEXT,
        timestamp=utc_now(),
        text=text,
        input_payload=input_payload,
    )


def build_runtime_context() -> RuntimeContext:
    """构造最小合法 RuntimeContext。"""
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
            entered_at=utc_now(),
        ),
    )


def build_safety_result(phase: SafetyPhase) -> SafetyResult:
    """构造最小合法 SafetyResult。"""
    return SafetyResult(
        safety_result_id=f"safety-{phase.value}",
        request_id="request-001",
        phase=phase,
        risk_detected=False,
        risk_level=SafetyRiskLevel.NONE,
        interrupt_current_task=False,
        allowed_to_continue_normal_flow=True,
        safety_lock_required=False,
        reason_codes=["SAFE"],
        created_at=utc_now(),
    )


def build_understanding_state() -> UnderstandingState:
    """构造最小合法 UnderstandingState。仅使用 Core Control Intent。"""
    return UnderstandingState(
        metadata=UnderstandingMetadata(
            understanding_id="understanding-001",
            request_id="request-001",
            timestamp=utc_now(),
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


def build_policy_decision() -> PolicyDecision:
    """构造最小合法 PolicyDecision。"""
    return PolicyDecision(
        policy_decision_id="policy-001",
        allowed=True,
        blocked=False,
        priority=50,
        interrupt_current_task=False,
        validation_mode=ValidationMode.STANDARD,
        reason_codes=["ALLOW"],
        created_at=utc_now(),
    )


def build_action_plan_draft() -> ActionPlanDraft:
    """构造最小合法 ActionPlanDraft。"""
    return ActionPlanDraft(
        plan_id="plan-001",
        request_id="request-001",
        approval_status=PlanApprovalStatus.DRAFT,
        planning_mode=PlanningMode.DEGRADED,
        goals=[PlanningGoal(goal_id="goal-001")],
        steps=[ActionStep(step_id="step-001", action=CoreControlAction.WAIT.value)],
        quality=QualityAssessment(),
    )


def build_approved_action_plan() -> ApprovedActionPlan:
    """构造最小合法 ApprovedActionPlan。"""
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


def build_execution_result() -> ExecutionResult:
    """构造最小合法 ExecutionResult。"""
    return ExecutionResult(
        execution_id="execution-001",
        plan_id="plan-001",
        request_id="request-001",
        identity_scope="scope-001",
        plan_status=ExecutionPlanStatus.SUCCESS,
        step_results=[],
        timing=ExecutionTiming(),
    )


def build_validated_result() -> ValidatedResult:
    """构造最小合法 ValidatedResult。"""
    return ValidatedResult(
        validation_id="validation-001",
        execution_id="execution-001",
        request_id="request-001",
        validation_status=ValidationStatus.VALIDATED,
        business_status=BusinessStatus.SUCCESS,
        claim_policy=ClaimPolicy(allowed_claims=[], forbidden_claims=[]),
    )


def build_response_plan() -> ResponsePlan:
    """构造最小合法 ResponsePlan。"""
    return ResponsePlan(
        response_plan_id="response-plan-001",
        request_id="request-001",
        response_requirement=ResponseRequirement(
            required=True, response_type=ResponseType.NORMAL
        ),
        claim_plan=ClaimPlan(must_include_claims=[], forbidden_claims=[]),
    )


def build_runtime_response() -> RuntimeResponse:
    """构造最小合法 RuntimeResponse。"""
    return RuntimeResponse(
        response_id="response-001",
        request_id="request-001",
        response_type=ResponseType.NORMAL,
        payload={"text": "ok"},
        response_validation_status=ResponseValidationStatus.VALID,
    )


def build_update_result() -> UpdateResult:
    """构造最小合法 UpdateResult。"""
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


class StubInputProcessor(InputProcessor):
    """透传 RuntimeInput。"""

    def __init__(self, call_recorder: CallRecorder) -> None:
        self._call_recorder = call_recorder

    async def process(self, runtime_input: RuntimeInput) -> RuntimeInput:
        self._call_recorder.record("INPUT")
        return runtime_input


class StubSafetyGuard(SafetyGuard):
    """返回 phase 正确的 SafetyResult，不做风险分类。"""

    def __init__(self, call_recorder: CallRecorder) -> None:
        self._call_recorder = call_recorder

    async def evaluate_early(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext | None = None,
    ) -> SafetyResult:
        self._call_recorder.record("SAFETY_EARLY")
        return build_safety_result(SafetyPhase.EARLY)

    async def evaluate_deep(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        early_safety: SafetyResult,
    ) -> SafetyResult:
        self._call_recorder.record("SAFETY_DEEP")
        return build_safety_result(SafetyPhase.DEEP)


class StubContextBuilder(ContextBuilder):
    """返回最小 RuntimeContext。"""

    def __init__(self, call_recorder: CallRecorder) -> None:
        self._call_recorder = call_recorder

    async def build(
        self,
        runtime_input: RuntimeInput,
        safety_result: SafetyResult,
    ) -> RuntimeContext:
        self._call_recorder.record("CONTEXT")
        return build_runtime_context()


class StubUnderstandingEngine(UnderstandingEngine):
    """返回 Core Control Intent=UNKNOWN，不含 Domain Intent。"""

    def __init__(self, call_recorder: CallRecorder) -> None:
        self._call_recorder = call_recorder

    async def understand(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext,
    ) -> UnderstandingState:
        self._call_recorder.record("UNDERSTANDING")
        return build_understanding_state()


class StubPolicyEngine(PolicyEngine):
    """返回允许继续的 PolicyDecision。"""

    def __init__(self, call_recorder: CallRecorder) -> None:
        self._call_recorder = call_recorder

    async def evaluate(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        safety_result: SafetyResult,
    ) -> PolicyDecision:
        self._call_recorder.record("POLICY")
        return build_policy_decision()


class StubPlanner(Planner):
    """只输出 ActionPlanDraft。"""

    def __init__(self, call_recorder: CallRecorder) -> None:
        self._call_recorder = call_recorder
        self.last_output: ActionPlanDraft | None = None

    async def plan(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        policy_decision: PolicyDecision,
    ) -> ActionPlanDraft:
        self._call_recorder.record("PLAN")
        self.last_output = build_action_plan_draft()
        return self.last_output


class StubPlanValidator(PlanValidator):
    """透传 Draft，不改 approval_status。"""

    def __init__(self, call_recorder: CallRecorder) -> None:
        self._call_recorder = call_recorder
        self.last_output: ActionPlanDraft | None = None

    async def validate(self, action_plan_draft: ActionPlanDraft) -> ActionPlanDraft:
        self._call_recorder.record("PLAN_VALIDATE")
        self.last_output = action_plan_draft
        return action_plan_draft


class StubPolicyRechecker(PolicyRechecker):
    """输出 ApprovedActionPlan。"""

    def __init__(self, call_recorder: CallRecorder) -> None:
        self._call_recorder = call_recorder
        self.last_output: ApprovedActionPlan | None = None

    async def recheck(
        self,
        action_plan_draft: ActionPlanDraft,
        policy_decision: PolicyDecision,
    ) -> ApprovedActionPlan:
        self._call_recorder.record("POLICY_RECHECK")
        self.last_output = build_approved_action_plan()
        return self.last_output


class StubExecutionEngine(ExecutionEngine):
    """记录收到的计划类型，不调用 Tool。"""

    def __init__(self, call_recorder: CallRecorder) -> None:
        self._call_recorder = call_recorder
        self.received_plan: object | None = None

    async def execute(
        self,
        approved_action_plan: ApprovedActionPlan,
        runtime_context: RuntimeContext,
    ) -> ExecutionResult:
        self._call_recorder.record("EXECUTE")
        self.received_plan = approved_action_plan
        if not isinstance(approved_action_plan, ApprovedActionPlan):
            raise TypeError("ExecutionEngine 只接受 ApprovedActionPlan")
        if isinstance(approved_action_plan, ActionPlanDraft):
            raise TypeError("ActionPlanDraft 不得进入 ExecutionEngine")
        return build_execution_result()


class StubResultValidator(ResultValidator):
    """把 ExecutionResult 提升为 ValidatedResult。"""

    def __init__(self, call_recorder: CallRecorder) -> None:
        self._call_recorder = call_recorder
        self.received_execution_result: ExecutionResult | None = None

    async def validate(
        self,
        execution_result: ExecutionResult,
        runtime_context: RuntimeContext,
        approved_action_plan: ApprovedActionPlan,
    ) -> ValidatedResult:
        self._call_recorder.record("RESULT_VALIDATE")
        self.received_execution_result = execution_result
        return build_validated_result()


class StubResponsePlanner(ResponsePlanner):
    """只消费 ValidatedResult。"""

    def __init__(self, call_recorder: CallRecorder) -> None:
        self._call_recorder = call_recorder
        self.received_validated_result: ValidatedResult | None = None

    async def plan(
        self,
        validated_result: ValidatedResult,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        approved_action_plan: ApprovedActionPlan,
    ) -> ResponsePlan:
        self._call_recorder.record("RESPONSE_PLAN")
        self.received_validated_result = validated_result
        return build_response_plan()


class StubResponseGenerator(ResponseGenerator):
    """只消费 ResponsePlan。"""

    def __init__(self, call_recorder: CallRecorder) -> None:
        self._call_recorder = call_recorder
        self.received_response_plan: ResponsePlan | None = None

    async def generate(self, response_plan: ResponsePlan) -> RuntimeResponse:
        self._call_recorder.record("RESPONSE_GENERATE")
        self.received_response_plan = response_plan
        return build_runtime_response()


class StubResponseValidator(ResponseValidator):
    """透传 RuntimeResponse。"""

    def __init__(self, call_recorder: CallRecorder) -> None:
        self._call_recorder = call_recorder
        self.called = False

    async def validate(
        self,
        runtime_response: RuntimeResponse,
        validated_result: ValidatedResult,
    ) -> RuntimeResponse:
        self._call_recorder.record("RESPONSE_VALIDATE")
        self.called = True
        return runtime_response


class StubStateMemoryUpdater(StateMemoryUpdater):
    """最后提交 UpdateResult。"""

    def __init__(self, call_recorder: CallRecorder) -> None:
        self._call_recorder = call_recorder

    async def update(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        approved_action_plan: ApprovedActionPlan,
        validated_result: ValidatedResult,
        runtime_response: RuntimeResponse,
    ) -> UpdateResult:
        self._call_recorder.record("UPDATE")
        return build_update_result()


class ExplodingUnderstandingEngine(StubUnderstandingEngine):
    """CASE-02：中间节点 UNDERSTANDING 失败。"""

    async def understand(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext,
    ) -> UnderstandingState:
        self._call_recorder.record("UNDERSTANDING")
        raise RuntimeError("understanding exploded")


class ExplodingExecutionEngine(StubExecutionEngine):
    """CASE-02：中间节点 EXECUTE 失败。"""

    async def execute(
        self,
        approved_action_plan: ApprovedActionPlan,
        runtime_context: RuntimeContext,
    ) -> ExecutionResult:
        self._call_recorder.record("EXECUTE")
        self.received_plan = approved_action_plan
        raise RuntimeError("execution exploded")


class ExplodingPlanner(StubPlanner):
    """用于验证 stage 异常不会伪造成功。"""

    async def plan(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        policy_decision: PolicyDecision,
    ) -> ActionPlanDraft:
        self._call_recorder.record("PLAN")
        raise RuntimeError("planner exploded")


class WrongTypePlanner(StubPlanner):
    """返回错误 Contract 类型，触发 ContractValidationError。"""

    async def plan(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        policy_decision: PolicyDecision,
    ) -> ActionPlanDraft:
        self._call_recorder.record("PLAN")
        return build_policy_decision()  # type: ignore[return-value]


class WrongPhaseSafetyGuard(StubSafetyGuard):
    """Early 返回 DEEP phase，触发 OrchestrationInvariantError。"""

    async def evaluate_early(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext | None = None,
    ) -> SafetyResult:
        self._call_recorder.record("SAFETY_EARLY")
        return build_safety_result(SafetyPhase.DEEP)
