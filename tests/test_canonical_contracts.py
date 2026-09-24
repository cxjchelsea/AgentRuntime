"""M0-IU1：首批 Core Contract 最小校验。

测试只覆盖 Canonical Registry 冻结语义，不引入业务实现。
"""

from datetime import UTC, datetime
from enum import Enum

import pytest
from pydantic import ValidationError

from runtime.contracts import (
    SCHEMA_VERSION,
    ActionPlanDraft,
    ApprovedActionPlan,
    BusinessStatus,
    ClaimPlan,
    ClaimPolicy,
    CommitResult,
    CommitStatus,
    CoreControlAction,
    CoreControlIntent,
    CoreControlStrategy,
    CoreIdentity,
    DomainExtensions,
    DomainIdentityExtension,
    EXECUTION_RESULT_SCHEMA_VERSION,
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
from runtime.contracts.planning import PLANNING_SCHEMA_VERSION, ActionStep
from runtime.contracts.understanding import (
    ProcessingPath,
    QualityAssessment,
    UncertaintyAssessment,
)


def _utc_now() -> datetime:
    """生成带时区的当前时间，避免 naive datetime。"""
    return datetime.now(UTC)


def _minimal_identity_context() -> IdentityContext:
    return IdentityContext(
        subject_id="subject-001",
        identity_scope="scope-001",
        identity_status=IdentityStatus.BOUND,
    )


def _minimal_session_context() -> SessionContext:
    return SessionContext(session_id="session-001")


def _minimal_runtime_state_context() -> RuntimeStateContext:
    return RuntimeStateContext(
        current_state=RuntimeControlState.IDLE,
        previous_state=None,
        interruptible=True,
        entered_at=_utc_now(),
    )


def _minimal_understanding_metadata() -> UnderstandingMetadata:
    return UnderstandingMetadata(
        understanding_id="understanding-001",
        request_id="request-001",
        timestamp=_utc_now(),
        processing_path=ProcessingPath.DEGRADED_PATH,
    )


def _unknown_intent() -> IntentResult:
    return IntentResult(
        intent_id=CoreControlIntent.UNKNOWN.value,
        confidence=0.0,
        source=IntentEvidenceSource.RULE,
    )


def _minimal_quality() -> QualityAssessment:
    return QualityAssessment()


def _minimal_uncertainty() -> UncertaintyAssessment:
    return UncertaintyAssessment()


def _minimal_planning_goal() -> PlanningGoal:
    return PlanningGoal(goal_id="goal-001")


def _minimal_action_step() -> ActionStep:
    return ActionStep(step_id="step-001", action=CoreControlAction.WAIT.value)


def _minimal_claim_policy() -> ClaimPolicy:
    return ClaimPolicy(allowed_claims=[], forbidden_claims=[])


def _minimal_claim_plan() -> ClaimPlan:
    return ClaimPlan(must_include_claims=[], forbidden_claims=[])


def _minimal_response_requirement() -> ResponseRequirement:
    return ResponseRequirement(required=True, response_type=ResponseType.NORMAL)


def _minimal_state_update() -> StateUpdate:
    return StateUpdate(
        previous_state=RuntimeControlState.IDLE,
        proposed_state=RuntimeControlState.PROCESSING,
        transition_status=TransitionStatus.NOT_REQUIRED,
    )


def _minimal_runtime_input() -> RuntimeInput:
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


def _minimal_safety_result(phase: SafetyPhase) -> SafetyResult:
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


def _minimal_runtime_context() -> RuntimeContext:
    return RuntimeContext(
        identity_context=_minimal_identity_context(),
        session_context=_minimal_session_context(),
        runtime_state_context=_minimal_runtime_state_context(),
    )


def _minimal_understanding_state() -> UnderstandingState:
    return UnderstandingState(
        metadata=_minimal_understanding_metadata(),
        intents=[_unknown_intent()],
        uncertainty=_minimal_uncertainty(),
        quality=_minimal_quality(),
    )


def _minimal_policy_decision() -> PolicyDecision:
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


def _minimal_action_plan_draft() -> ActionPlanDraft:
    return ActionPlanDraft(
        plan_id="plan-001",
        request_id="request-001",
        approval_status=PlanApprovalStatus.DRAFT,
        planning_mode=PlanningMode.DEGRADED,
        goals=[_minimal_planning_goal()],
        steps=[_minimal_action_step()],
        quality=_minimal_quality(),
    )


def _minimal_approved_action_plan() -> ApprovedActionPlan:
    return ApprovedActionPlan(
        plan_id="plan-001",
        request_id="request-001",
        approval_status=PlanApprovalStatus.APPROVED,
        planning_mode=PlanningMode.DEGRADED,
        goals=[_minimal_planning_goal()],
        steps=[_minimal_action_step()],
        policy_snapshot={"allowed": True},
        quality=_minimal_quality(),
    )


def _minimal_execution_result() -> ExecutionResult:
    return ExecutionResult(
        execution_id="execution-001",
        plan_id="plan-001",
        request_id="request-001",
        identity_scope="scope-001",
        plan_status=ExecutionPlanStatus.SUCCESS,
        step_results=[],
        timing=ExecutionTiming(),
    )


def _minimal_validated_result() -> ValidatedResult:
    return ValidatedResult(
        validation_id="validation-001",
        execution_id="execution-001",
        request_id="request-001",
        validation_status=ValidationStatus.VALIDATED,
        business_status=BusinessStatus.SUCCESS,
        claim_policy=_minimal_claim_policy(),
    )


def _minimal_response_plan() -> ResponsePlan:
    return ResponsePlan(
        response_plan_id="response-plan-001",
        request_id="request-001",
        response_requirement=_minimal_response_requirement(),
        claim_plan=_minimal_claim_plan(),
    )


def _minimal_runtime_response() -> RuntimeResponse:
    return RuntimeResponse(
        response_id="response-001",
        request_id="request-001",
        response_type=ResponseType.NORMAL,
        payload={"text": "ok"},
        response_validation_status=ResponseValidationStatus.VALID,
    )


def _minimal_update_result() -> UpdateResult:
    return UpdateResult(
        update_id="update-001",
        request_id="request-001",
        identity_scope="scope-001",
        state_update=_minimal_state_update(),
        commit_result=CommitResult(status=CommitStatus.ATOMIC),
    )


def test_fourteen_core_contracts_can_instantiate() -> None:
    """14 个核心 Contract 都可以按 Canonical 必填字段合法实例化。"""
    assert _minimal_runtime_input().schema_version == SCHEMA_VERSION
    assert _minimal_safety_result(SafetyPhase.EARLY).schema_version == SCHEMA_VERSION
    assert _minimal_runtime_context().schema_version == SCHEMA_VERSION
    assert _minimal_understanding_state().schema_version == SCHEMA_VERSION
    assert _minimal_policy_decision().schema_version == SCHEMA_VERSION
    # M4-CA1：Planning Contract 默认升到 1.1.0，全局 SCHEMA_VERSION 仍为 1.0.0
    assert _minimal_action_plan_draft().schema_version == PLANNING_SCHEMA_VERSION
    assert _minimal_approved_action_plan().schema_version == PLANNING_SCHEMA_VERSION
    assert (
        _minimal_execution_result().schema_version
        == EXECUTION_RESULT_SCHEMA_VERSION
    )
    assert _minimal_validated_result().schema_version == SCHEMA_VERSION
    assert _minimal_response_plan().schema_version == SCHEMA_VERSION
    assert _minimal_runtime_response().schema_version == SCHEMA_VERSION
    assert _minimal_state_update().schema_version == SCHEMA_VERSION
    assert MemoryUpdate(identity_scope="scope-001").schema_version == SCHEMA_VERSION
    assert _minimal_update_result().schema_version == SCHEMA_VERSION


def test_required_field_missing_fails() -> None:
    """缺少 Canonical 必填字段时校验失败。"""
    with pytest.raises(ValidationError):
        RuntimeInput.model_validate(
            {
                "request_id": "request-001",
                "trace_id": "trace-001",
                "session_id": "session-001",
                "subject_id": "subject-001",
                "source": "USER",
                "trigger_type": "USER_TEXT",
                "timestamp": _utc_now(),
            }
        )


def test_optional_fields_can_be_omitted() -> None:
    """Optional 字段可以缺省。"""
    runtime_input = _minimal_runtime_input()
    assert runtime_input.actor_id is None
    assert runtime_input.text is None
    assert runtime_input.input_payload is None


def test_schema_version_is_frozen_1_0_0() -> None:
    """schema_version 固定为 1.0.0。"""
    assert SCHEMA_VERSION == "1.0.0"
    assert _minimal_runtime_input().schema_version == "1.0.0"
    assert _minimal_update_result().schema_version == "1.0.0"


def test_illegal_enum_value_is_rejected() -> None:
    """非法枚举值被拒绝。"""
    with pytest.raises(ValidationError):
        RuntimeInput.model_validate(
            {
                "request_id": "request-001",
                "trace_id": "trace-001",
                "session_id": "session-001",
                "subject_id": "subject-001",
                "identity_scope": "scope-001",
                "source": "voice",
                "trigger_type": "USER_TEXT",
                "timestamp": _utc_now(),
            }
        )


def test_core_identity_rejects_domain_role_fields() -> None:
    """CoreIdentity 不接受 elder_id / patient_id 作为正式字段。"""
    with pytest.raises(ValidationError):
        CoreIdentity.model_validate(
            {
                "subject_id": "subject-001",
                "identity_scope": "scope-001",
                "source": "USER",
                "elder_id": "E001",
            }
        )
    with pytest.raises(ValidationError):
        CoreIdentity.model_validate(
            {
                "subject_id": "subject-001",
                "identity_scope": "scope-001",
                "source": "USER",
                "patient_id": "P001",
            }
        )


def test_draft_and_approved_are_distinct_types() -> None:
    """ActionPlanDraft 与 ApprovedActionPlan 是两个不同类型。"""
    draft_plan = _minimal_action_plan_draft()
    approved_plan = _minimal_approved_action_plan()
    assert type(draft_plan) is not type(approved_plan)
    assert draft_plan.approval_status is PlanApprovalStatus.DRAFT
    assert approved_plan.approval_status is PlanApprovalStatus.APPROVED
    assert not isinstance(draft_plan, ApprovedActionPlan)
    assert not isinstance(approved_plan, ActionPlanDraft)


def test_no_public_action_plan_type() -> None:
    """不存在公开 ActionPlan 类型。"""
    import runtime.contracts as contracts_package

    assert not hasattr(contracts_package, "ActionPlan")
    assert "ActionPlan" not in contracts_package.__all__


def test_safety_result_phase_distinguishes_early_and_deep() -> None:
    """SafetyResult 只能通过 phase 区分 EARLY / DEEP，不存在独立类型。"""
    import runtime.contracts as contracts_package

    early_result = _minimal_safety_result(SafetyPhase.EARLY)
    deep_result = _minimal_safety_result(SafetyPhase.DEEP)
    assert type(early_result) is type(deep_result)
    assert early_result.phase is SafetyPhase.EARLY
    assert deep_result.phase is SafetyPhase.DEEP
    assert not hasattr(contracts_package, "EarlySafetyResult")
    assert not hasattr(contracts_package, "DeepSafetyResult")


def test_update_result_contains_state_and_memory_update() -> None:
    """UpdateResult 可以包含 StateUpdate / MemoryUpdate。"""
    memory_update = MemoryUpdate(identity_scope="scope-001", writes=[])
    update_result = UpdateResult(
        update_id="update-001",
        request_id="request-001",
        identity_scope="scope-001",
        state_update=_minimal_state_update(),
        commit_result=CommitResult(status=CommitStatus.PARTIAL),
        memory_update=memory_update,
    )
    assert isinstance(update_result.state_update, StateUpdate)
    assert isinstance(update_result.memory_update, MemoryUpdate)


def test_state_and_memory_update_are_not_chain_terminus_markers() -> None:
    """StateUpdate / MemoryUpdate 带内部对象标记，不是主链终点。"""
    assert StateUpdate.CHAIN_TERMINUS is False
    assert MemoryUpdate.CHAIN_TERMINUS is False
    assert UpdateResult.CHAIN_TERMINUS is True


def test_domain_identity_extension_can_attach_to_context() -> None:
    """DomainIdentityExtension 可以挂入 RuntimeContext.domain_extensions.identity。"""
    domain_identity = DomainIdentityExtension(
        domain_id="example_domain",
        subject_type="elder",
        domain_subject_ref="E001",
    )
    runtime_context = RuntimeContext(
        identity_context=_minimal_identity_context(),
        session_context=_minimal_session_context(),
        runtime_state_context=_minimal_runtime_state_context(),
        domain_extensions=DomainExtensions(
            domain_id="example_domain",
            identity=domain_identity,
            domain_state={"phase": "idle"},
        ),
    )
    assert runtime_context.domain_extensions is not None
    assert runtime_context.domain_extensions.identity is not None
    assert runtime_context.domain_extensions.identity.subject_type == "elder"
    assert not hasattr(runtime_context.identity_context, "elder_id")


def test_domain_registered_values_are_not_core_enums() -> None:
    """Domain Registered Values 不得进入 Core Enum。"""
    forbidden_values = {
        "PLAY_CONTENT",
        "QUIET_COMPANION",
        "REMINDER_RESPONSE",
        "DISCOMFORT",
        "COMPANIONSHIP",
        "LISTENING_FIRST",
    }
    core_enum_types: list[type[Enum]] = [
        InputSource,
        InputTriggerType,
        RuntimeControlState,
        SafetyPhase,
        CoreControlIntent,
        CoreControlAction,
        CoreControlStrategy,
    ]
    collected_values = {
        enum_member.value for enum_type in core_enum_types for enum_member in enum_type
    }
    assert forbidden_values.isdisjoint(collected_values)


def test_serialization_round_trip() -> None:
    """核心 Contract 支持序列化往返。"""
    original_input = _minimal_runtime_input()
    restored_input = RuntimeInput.model_validate(original_input.model_dump(mode="json"))
    assert restored_input.request_id == original_input.request_id
    assert restored_input.source is InputSource.USER

    original_plan = _minimal_approved_action_plan()
    restored_plan = ApprovedActionPlan.model_validate(
        original_plan.model_dump(mode="json")
    )
    assert restored_plan.approval_status is PlanApprovalStatus.APPROVED

    original_update = _minimal_update_result()
    restored_update = UpdateResult.model_validate(
        original_update.model_dump(mode="json")
    )
    assert restored_update.state_update.proposed_state is RuntimeControlState.PROCESSING


def test_understanding_state_uses_nested_structure() -> None:
    """UnderstandingState 使用嵌套结构，不恢复扁平旧字段。"""
    understanding_state = _minimal_understanding_state()
    dumped_fields = understanding_state.model_dump()
    assert "intents" in dumped_fields
    assert "metadata" in dumped_fields
    assert "explicit_intents" not in dumped_fields
    assert "emotion_intensity" not in dumped_fields
    assert "ambiguity" not in dumped_fields


def test_policy_decision_uses_canonical_fields() -> None:
    """PolicyDecision 使用 reason_codes 与 interrupt_current_task。"""
    policy_decision = _minimal_policy_decision()
    dumped_fields = policy_decision.model_dump()
    assert "reason_codes" in dumped_fields
    assert "interrupt_current_task" in dumped_fields
    assert "reason" not in dumped_fields
    assert "interrupt_required" not in dumped_fields


def test_execution_result_uses_plan_status_and_step_results() -> None:
    """ExecutionResult 使用 plan_status 与 step_results 层级。"""
    execution_result = _minimal_execution_result()
    dumped_fields = execution_result.model_dump()
    assert execution_result.schema_version == "1.1.0"
    assert "plan_status" in dumped_fields
    assert "step_results" in dumped_fields
    assert "workflow_result" in dumped_fields
    assert "workflow_results" in dumped_fields
    assert execution_result.workflow_results is None
    assert "status" not in dumped_fields
    assert "executed_skill" not in dumped_fields
    assert "business_result" not in dumped_fields


def test_response_plan_uses_claim_plan() -> None:
    """ResponsePlan 使用 claim_plan，不恢复 facts_to_include。"""
    response_plan = _minimal_response_plan()
    dumped_fields = response_plan.model_dump()
    assert "claim_plan" in dumped_fields
    assert "facts_to_include" not in dumped_fields
    assert "facts_to_avoid" not in dumped_fields
