"""M5 Readiness Contract Fix Pack gates."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

import pytest

import runtime.execution.authority as authority_module
import runtime.execution.control as control_module
import runtime.execution.models as models_module
import runtime.execution.permission as permission_module
import runtime.execution.protocols as protocols_module
import runtime.execution.resolution as resolution_module
import runtime.execution.stores as stores_module
from runtime.contracts import (
    ApprovedActionPlan,
    ExecutionResult,
    PolicyDecision,
    RuntimeContext,
)
from runtime.contracts.execution import ExecutionContext
from runtime.execution import (
    ApprovedToolInvoker,
    ApprovedWorkflowAuthority,
    ExecutionControlSignal,
    ExecutionControlSignalSource,
    ExecutionControlSignalType,
    ExecutionImplementationResolver,
    ExecutionImplementationTypeError,
    ExecutionPermissionContext,
    ExecutionPermissionContextProvider,
    ExecutionPermissionEvaluator,
    ExecutionRegistryResolutionError,
    ExecutionStateStore,
    IdempotencyRecord,
    IdempotencyStatus,
    IdempotencyStore,
    M5SkillResult,
    M5ToolResult,
    M5WorkflowResult,
    PermissionDecision,
    PermissionDecisionStatus,
    ResourceLockProvider,
    SkillExecutionRequest,
    SkillExecutionStatus,
    SkillImplementation,
    ToolExecutionStatus,
    ToolImplementation,
    ToolInvocationRequest,
    WorkflowCheckpointStore,
    WorkflowExecutionRequest,
    WorkflowExecutionStatus,
    WorkflowImplementation,
    project_workflow_authority,
)
from runtime.interfaces.execution import ExecutionEngine
from runtime.registries import (
    SkillDefinition,
    SkillRegistry,
    ToolDefinition,
    ToolRegistry,
    WorkflowDefinition,
    WorkflowRegistry,
)
from tests.orchestration_stubs import build_approved_action_plan


def _execution_context() -> ExecutionContext:
    return ExecutionContext(
        execution_id="execution-001",
        plan_id="plan-001",
        request_id="request-001",
        session_id="session-001",
        identity_scope="scope-001",
        policy_snapshot={"allowed": True},
    )


class GoodTool:
    async def invoke(
        self,
        request: ToolInvocationRequest,
        execution_context: ExecutionContext,
    ) -> M5ToolResult:
        del execution_context
        return M5ToolResult(
            tool_call_id=request.tool_call_id,
            tool_id=request.tool_id,
            status=ToolExecutionStatus.SUCCESS,
            attempt=request.attempt,
        )


class GoodSkill:
    async def execute(
        self,
        request: SkillExecutionRequest,
        execution_context: ExecutionContext,
        tool_invoker: ApprovedToolInvoker,
    ) -> M5SkillResult:
        del execution_context, tool_invoker
        return M5SkillResult(
            skill_id=request.skill_id,
            status=SkillExecutionStatus.SUCCESS,
        )


class LegacySkillWithoutToolInvoker:
    async def execute(
        self,
        request: SkillExecutionRequest,
        execution_context: ExecutionContext,
    ) -> M5SkillResult:
        del execution_context
        return M5SkillResult(
            skill_id=request.skill_id,
            status=SkillExecutionStatus.SUCCESS,
        )


class LegacyWorkflowWithoutToolInvoker:
    async def start(
        self,
        request: WorkflowExecutionRequest,
        execution_context: ExecutionContext,
    ) -> M5WorkflowResult:
        del execution_context
        return M5WorkflowResult(
            workflow_instance_id=request.workflow_instance_id,
            workflow_id=request.workflow_id,
            status=WorkflowExecutionStatus.RUNNING,
        )

    async def resume(
        self,
        request: WorkflowExecutionRequest,
        execution_context: ExecutionContext,
    ) -> M5WorkflowResult:
        del execution_context
        return M5WorkflowResult(
            workflow_instance_id=request.workflow_instance_id,
            workflow_id=request.workflow_id,
            status=WorkflowExecutionStatus.RUNNING,
        )


class GoodWorkflow:
    async def start(
        self,
        request: WorkflowExecutionRequest,
        execution_context: ExecutionContext,
        tool_invoker: ApprovedToolInvoker,
    ) -> M5WorkflowResult:
        del execution_context, tool_invoker
        return M5WorkflowResult(
            workflow_instance_id=request.workflow_instance_id,
            workflow_id=request.workflow_id,
            status=WorkflowExecutionStatus.RUNNING,
        )

    async def resume(
        self,
        request: WorkflowExecutionRequest,
        execution_context: ExecutionContext,
        tool_invoker: ApprovedToolInvoker,
    ) -> M5WorkflowResult:
        del execution_context, tool_invoker
        return M5WorkflowResult(
            workflow_instance_id=request.workflow_instance_id,
            workflow_id=request.workflow_id,
            status=WorkflowExecutionStatus.RUNNING,
        )


def test_internal_tool_status_formally_supports_unknown() -> None:
    result = M5ToolResult(
        tool_call_id="tool-call-001",
        tool_id="DOMAIN_TOOL",
        status=ToolExecutionStatus.UNKNOWN,
        error_code="RESULT_UNCONFIRMED",
    )

    assert result.status is ToolExecutionStatus.UNKNOWN


def test_execution_result_internal_contracts_use_business_outputs_plural() -> None:
    result = M5SkillResult(
        skill_id="DOMAIN_SKILL",
        status=SkillExecutionStatus.SUCCESS,
        business_outputs=({"result": "observed"},),
    )

    assert result.business_outputs == ({"result": "observed"},)


def test_registry_metadata_extension_is_backward_compatible() -> None:
    legacy_workflow = WorkflowDefinition(
        workflow_id="LEGACY_WORKFLOW",
        version="1.0.0",
    )
    legacy_tool = ToolDefinition(
        tool_id="LEGACY_TOOL",
        version="1.0.0",
    )

    assert legacy_workflow.checkpoint_enabled is None
    assert legacy_workflow.resume_policy is None
    assert legacy_workflow.required_tools is None
    assert legacy_workflow.optional_tools is None
    assert legacy_tool.resource_locks is None


def test_registry_metadata_can_express_checkpoint_recovery_and_locks() -> None:
    workflow = WorkflowDefinition(
        workflow_id="DOMAIN_WORKFLOW",
        version="1.0.0",
        supported_events=["CALLBACK"],
        allowed_states=["PROCESSING"],
        checkpoint_enabled=True,
        timeout_policy="WORKFLOW_STANDARD",
        resume_policy="SAFE_RESUME_ONLY",
        required_tools=["DOMAIN_TOOL"],
        optional_tools=["OPTIONAL_TOOL"],
    )
    tool = ToolDefinition(
        tool_id="DOMAIN_TOOL",
        version="1.0.0",
        resource_locks=["shared-resource"],
    )

    assert workflow.checkpoint_enabled is True
    assert workflow.resume_policy == "SAFE_RESUME_ONLY"
    assert workflow.required_tools == ["DOMAIN_TOOL"]
    assert workflow.optional_tools == ["OPTIONAL_TOOL"]
    assert tool.resource_locks == ["shared-resource"]


def test_runtime_checkable_execution_protocols_accept_matching_implementations() -> (
    None
):
    assert isinstance(GoodTool(), ToolImplementation)
    assert isinstance(GoodSkill(), SkillImplementation)
    assert isinstance(GoodWorkflow(), WorkflowImplementation)


def test_execution_implementation_resolver_enforces_protocols() -> None:
    skills = SkillRegistry()
    workflows = WorkflowRegistry()
    tools = ToolRegistry()
    skills.register(
        SkillDefinition(skill_id="DOMAIN_SKILL", version="1.0.0"),
        implementation_ref=GoodSkill(),
    )
    workflows.register(
        WorkflowDefinition(workflow_id="DOMAIN_WORKFLOW", version="1.0.0"),
        implementation_ref=GoodWorkflow(),
    )
    tools.register(
        ToolDefinition(tool_id="DOMAIN_TOOL", version="1.0.0"),
        implementation_ref=GoodTool(),
    )

    resolver = ExecutionImplementationResolver(
        skill_registry=skills,
        workflow_registry=workflows,
        tool_registry=tools,
    )

    assert isinstance(
        resolver.resolve_skill("DOMAIN_SKILL", "1.0.0").implementation_ref,
        SkillImplementation,
    )
    assert isinstance(
        resolver.resolve_workflow("DOMAIN_WORKFLOW", "1.0.0").implementation_ref,
        WorkflowImplementation,
    )
    assert isinstance(
        resolver.resolve_tool("DOMAIN_TOOL", "1.0.0").implementation_ref,
        ToolImplementation,
    )


def test_execution_resolver_rejects_legacy_skill_without_tool_invoker() -> None:
    skills = SkillRegistry()
    skills.register(
        SkillDefinition(skill_id="LEGACY_SKILL", version="1.0.0"),
        implementation_ref=LegacySkillWithoutToolInvoker(),
    )
    resolver = ExecutionImplementationResolver(
        skill_registry=skills,
        workflow_registry=WorkflowRegistry(),
        tool_registry=ToolRegistry(),
    )

    with pytest.raises(ExecutionImplementationTypeError, match="ApprovedToolInvoker"):
        resolver.resolve_skill("LEGACY_SKILL", "1.0.0")


def test_execution_resolver_rejects_legacy_workflow_without_tool_invoker() -> None:
    workflows = WorkflowRegistry()
    workflows.register(
        WorkflowDefinition(workflow_id="LEGACY_WORKFLOW", version="1.0.0"),
        implementation_ref=LegacyWorkflowWithoutToolInvoker(),
    )
    resolver = ExecutionImplementationResolver(
        skill_registry=SkillRegistry(),
        workflow_registry=workflows,
        tool_registry=ToolRegistry(),
    )

    with pytest.raises(ExecutionImplementationTypeError, match="ApprovedToolInvoker"):
        resolver.resolve_workflow("LEGACY_WORKFLOW", "1.0.0")


def test_execution_implementation_resolver_rejects_wrong_implementation_type() -> None:
    skills = SkillRegistry()
    workflows = WorkflowRegistry()
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(tool_id="DOMAIN_TOOL", version="1.0.0"),
        implementation_ref=object(),
    )
    resolver = ExecutionImplementationResolver(
        skill_registry=skills,
        workflow_registry=workflows,
        tool_registry=tools,
    )

    with pytest.raises(ExecutionImplementationTypeError):
        resolver.resolve_tool("DOMAIN_TOOL", "1.0.0")


def test_execution_implementation_resolver_uses_exact_approved_version() -> None:
    skills = SkillRegistry()
    workflows = WorkflowRegistry()
    tools = ToolRegistry()
    v1 = GoodTool()
    v2 = GoodTool()
    tools.register(
        ToolDefinition(tool_id="DOMAIN_TOOL", version="1.0.0"),
        implementation_ref=v1,
    )
    tools.register(
        ToolDefinition(tool_id="DOMAIN_TOOL", version="2.0.0"),
        implementation_ref=v2,
    )
    resolver = ExecutionImplementationResolver(
        skill_registry=skills,
        workflow_registry=workflows,
        tool_registry=tools,
    )

    assert resolver.resolve_tool("DOMAIN_TOOL", "1.0.0").implementation_ref is v1
    assert resolver.resolve_tool("DOMAIN_TOOL", "2.0.0").implementation_ref is v2

    with pytest.raises(ExecutionRegistryResolutionError):
        resolver.resolve_tool("DOMAIN_TOOL", "3.0.0")


def test_control_signal_distinguishes_cancel_preempt_and_none() -> None:
    none = ExecutionControlSignal(signal_type=ExecutionControlSignalType.NONE)
    cancel = ExecutionControlSignal(
        signal_type=ExecutionControlSignalType.CANCEL,
        reason_code="USER_STOP",
        source="RUNTIME",
    )
    preempt = ExecutionControlSignal(
        signal_type=ExecutionControlSignalType.PREEMPT,
        reason_code="HIGH_PRIORITY_PREEMPTION",
        source="M2",
    )

    assert none.signal_type is ExecutionControlSignalType.NONE
    assert cancel.signal_type is ExecutionControlSignalType.CANCEL
    assert preempt.signal_type is ExecutionControlSignalType.PREEMPT


def test_control_signal_does_not_allow_unexplained_cancel_or_preempt() -> None:
    with pytest.raises(ValueError, match="reason_code"):
        ExecutionControlSignal(signal_type=ExecutionControlSignalType.CANCEL)


def test_idempotency_record_has_unknown_state_for_unconfirmed_side_effect() -> None:
    record = IdempotencyRecord(
        key="request-001:plan-001:step-001:action",
        execution_id="execution-001",
        step_id="step-001",
        step_execution_id="step-execution-001",
        tool_id="DOMAIN_TOOL",
        tool_version="1.0.0",
        operation_key="operation-001",
        operation_fingerprint="sha256:operation",
        status=IdempotencyStatus.UNKNOWN,
        tool_call_id="tool-call-001",
        created_at=datetime.now(UTC),
    )

    assert record.status is IdempotencyStatus.UNKNOWN


def test_readiness_package_contains_no_domain_execution_taxonomy() -> None:
    source = "\n".join(
        inspect.getsource(module)
        for module in (
            authority_module,
            control_module,
            models_module,
            permission_module,
            protocols_module,
            resolution_module,
            stores_module,
        )
    )

    for token in (
        "WEATHER",
        "NEWS",
        "PLAYBACK",
        "NOTIFY",
        "MEDICAL",
        "HELP_WORKFLOW",
    ):
        assert token not in source


def test_execution_store_protocols_freeze_required_method_surface() -> None:
    assert set(ExecutionStateStore.__dict__) >= {"save", "load"}
    assert set(WorkflowCheckpointStore.__dict__) >= {"save", "load"}
    assert set(IdempotencyStore.__dict__) >= {
        "get",
        "reserve",
        "mark_completed",
        "mark_failed",
        "reopen_failed",
        "mark_unknown",
    }
    assert set(ResourceLockProvider.__dict__) >= {"acquire", "release"}
    assert "get_signal" in ExecutionControlSignalSource.__dict__


def test_execution_permission_context_distinguishes_current_permission_facts() -> None:
    context = ExecutionPermissionContext(
        execution_id="execution-001",
        identity_scope="scope-001",
        granted_permissions=frozenset({"TOOL_USE"}),
        denied_permissions=frozenset({"ADMIN_ONLY"}),
        evidence_refs=("binding:subject-001",),
    )

    assert "TOOL_USE" in context.granted_permissions
    assert "ADMIN_ONLY" in context.denied_permissions


def test_execution_permission_context_rejects_conflicting_permission_fact() -> None:
    with pytest.raises(ValueError, match="both granted and denied"):
        ExecutionPermissionContext(
            execution_id="execution-001",
            identity_scope="scope-001",
            granted_permissions=frozenset({"TOOL_USE"}),
            denied_permissions=frozenset({"TOOL_USE"}),
        )


class StaticPermissionProvider:
    async def build(
        self,
        execution_context: ExecutionContext,
    ) -> ExecutionPermissionContext:
        return ExecutionPermissionContext(
            execution_id=execution_context.execution_id,
            identity_scope=execution_context.identity_scope,
            granted_permissions=frozenset({"TOOL_USE"}),
        )


class StaticPermissionEvaluator:
    def evaluate(
        self,
        tool_definition: ToolDefinition,
        permission_context: ExecutionPermissionContext,
    ) -> PermissionDecision:
        required = tuple(tool_definition.required_permissions or ())
        missing = tuple(
            permission
            for permission in required
            if permission not in permission_context.granted_permissions
        )
        return PermissionDecision(
            status=(
                PermissionDecisionStatus.ALLOWED
                if not missing
                else PermissionDecisionStatus.DENIED
            ),
            reason_codes=("PERMISSION_EVALUATED",),
            missing_permissions=missing,
        )


def test_permission_contract_is_runtime_checkable_by_static_type_surface() -> None:
    provider: ExecutionPermissionContextProvider = StaticPermissionProvider()
    evaluator: ExecutionPermissionEvaluator = StaticPermissionEvaluator()

    assert provider is not None
    assert evaluator is not None


def test_permission_decision_supports_unknown_without_replanning() -> None:
    decision = PermissionDecision(
        status=PermissionDecisionStatus.UNKNOWN,
        reason_codes=("PERMISSION_FACT_UNAVAILABLE",),
        missing_permissions=("TOOL_USE",),
    )

    assert decision.status is PermissionDecisionStatus.UNKNOWN


def test_allowed_permission_decision_cannot_carry_missing_permissions() -> None:
    with pytest.raises(ValueError, match="ALLOWED"):
        PermissionDecision(
            status=PermissionDecisionStatus.ALLOWED,
            reason_codes=("PERMISSION_ALLOWED",),
            missing_permissions=("TOOL_USE",),
        )


def test_workflow_authority_comes_from_approved_plan_and_existing_forced_workflow() -> (
    None
):
    plan = build_approved_action_plan().model_copy(
        update={
            "steps": [
                build_approved_action_plan()
                .steps[0]
                .model_copy(update={"workflow_id": "WF_FORCED"})
            ],
            "policy_snapshot": {
                "allowed": True,
                "forced_workflow": "WF_FORCED",
            },
        }
    )

    authority = project_workflow_authority(plan)

    assert isinstance(authority, ApprovedWorkflowAuthority)
    assert authority.approved_workflow_ids == frozenset({"WF_FORCED"})
    assert authority.forced_workflow == "WF_FORCED"


def test_policy_decision_has_no_generic_workflow_allow_or_forbid_fields() -> None:
    fields = PolicyDecision.model_fields

    assert "allowed_workflows" not in fields
    assert "forbidden_workflows" not in fields


def test_workflow_authority_does_not_expect_generic_allowed_workflows() -> None:
    plan = build_approved_action_plan().model_copy(
        update={
            "steps": [
                build_approved_action_plan()
                .steps[0]
                .model_copy(update={"workflow_id": "WF_A"})
            ],
            "policy_snapshot": {"allowed": True},
        }
    )

    authority = project_workflow_authority(plan)

    assert authority.approved_workflow_ids == frozenset({"WF_A"})
    assert authority.forced_workflow is None


def test_workflow_authority_rejects_plan_that_violates_forced_workflow_snapshot() -> (
    None
):
    plan = build_approved_action_plan().model_copy(
        update={
            "steps": [
                build_approved_action_plan()
                .steps[0]
                .model_copy(update={"workflow_id": "WF_OTHER"})
            ],
            "policy_snapshot": {
                "allowed": True,
                "forced_workflow": "WF_FORCED",
            },
        }
    )

    with pytest.raises(ValueError, match="forced_workflow"):
        project_workflow_authority(plan)


def test_frozen_execution_engine_main_chain_signature_is_unchanged() -> None:
    signature = inspect.signature(ExecutionEngine.execute)
    assert list(signature.parameters) == [
        "self",
        "approved_action_plan",
        "runtime_context",
    ]
    assert signature.parameters["approved_action_plan"].annotation is ApprovedActionPlan
    assert signature.parameters["runtime_context"].annotation is RuntimeContext
    assert signature.return_annotation is ExecutionResult
