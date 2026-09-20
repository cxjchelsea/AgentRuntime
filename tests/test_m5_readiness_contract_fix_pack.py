"""M5 Readiness Contract Fix Pack gates."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

import pytest

import runtime.execution as execution_module
from runtime.contracts.execution import ExecutionContext
from runtime.execution import (
    ExecutionControlSignal,
    ExecutionControlSignalType,
    ExecutionImplementationResolver,
    ExecutionImplementationTypeError,
    ExecutionRegistryResolutionError,
    IdempotencyRecord,
    IdempotencyStatus,
    M5SkillResult,
    M5ToolResult,
    M5WorkflowResult,
    SkillExecutionRequest,
    SkillExecutionStatus,
    SkillImplementation,
    ToolExecutionStatus,
    ToolImplementation,
    ToolInvocationRequest,
    WorkflowExecutionRequest,
    WorkflowExecutionStatus,
    WorkflowImplementation,
)
from runtime.registries import (
    SkillDefinition,
    SkillRegistry,
    ToolDefinition,
    ToolRegistry,
    WorkflowDefinition,
    WorkflowRegistry,
)


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
    ) -> M5SkillResult:
        del execution_context
        return M5SkillResult(
            skill_id=request.skill_id,
            status=SkillExecutionStatus.SUCCESS,
        )


class GoodWorkflow:
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
    )
    tool = ToolDefinition(
        tool_id="DOMAIN_TOOL",
        version="1.0.0",
        resource_locks=["shared-resource"],
    )

    assert workflow.checkpoint_enabled is True
    assert workflow.resume_policy == "SAFE_RESUME_ONLY"
    assert tool.resource_locks == ["shared-resource"]


def test_runtime_checkable_execution_protocols_accept_matching_implementations() -> None:
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

    assert isinstance(resolver.resolve_skill("DOMAIN_SKILL"), SkillImplementation)
    assert isinstance(
        resolver.resolve_workflow("DOMAIN_WORKFLOW"),
        WorkflowImplementation,
    )
    assert isinstance(resolver.resolve_tool("DOMAIN_TOOL"), ToolImplementation)


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
        resolver.resolve_tool("DOMAIN_TOOL")


def test_execution_implementation_resolver_rejects_enabled_version_ambiguity() -> None:
    skills = SkillRegistry()
    workflows = WorkflowRegistry()
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(tool_id="DOMAIN_TOOL", version="1.0.0"),
        implementation_ref=GoodTool(),
    )
    tools.register(
        ToolDefinition(tool_id="DOMAIN_TOOL", version="2.0.0"),
        implementation_ref=GoodTool(),
    )
    resolver = ExecutionImplementationResolver(
        skill_registry=skills,
        workflow_registry=workflows,
        tool_registry=tools,
    )

    with pytest.raises(ExecutionRegistryResolutionError, match="exactly one"):
        resolver.resolve_tool("DOMAIN_TOOL")


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
        status=IdempotencyStatus.UNKNOWN,
        created_at=datetime.now(UTC),
    )

    assert record.status is IdempotencyStatus.UNKNOWN


def test_readiness_package_contains_no_domain_execution_taxonomy() -> None:
    source = inspect.getsource(execution_module)

    for token in (
        "WEATHER",
        "NEWS",
        "PLAYBACK",
        "NOTIFY",
        "MEDICAL",
        "HELP_WORKFLOW",
    ):
        assert token not in source
