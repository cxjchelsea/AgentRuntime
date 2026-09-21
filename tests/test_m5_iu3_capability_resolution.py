"""M5-IU3 approved Capability Resolution gates."""

from __future__ import annotations

import asyncio

import pytest

from runtime.contracts.enums import RuntimeControlState
from runtime.contracts.execution import ExecutionContext
from runtime.execution import (
    ApprovedToolInvoker,
    CapabilityExecutionOwner,
    CapabilityResolutionStatus,
    ExecutionImplementationResolver,
    ExecutionPermissionContext,
    M5SkillResult,
    M5ToolResult,
    M5WorkflowResult,
    PermissionDecision,
    PermissionDecisionStatus,
    SkillExecutionRequest,
    SkillExecutionStatus,
    StepCapabilityResolver,
    ToolExecutionStatus,
    ToolInvocationRequest,
    WorkflowExecutionRequest,
    WorkflowExecutionStatus,
)
from runtime.registries import (
    SkillDefinition,
    SkillRegistry,
    ToolDefinition,
    ToolRegistry,
    WorkflowDefinition,
    WorkflowRegistry,
)
from tests.orchestration_stubs import build_approved_action_plan


class RecordingSkill:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(
        self,
        request: SkillExecutionRequest,
        execution_context: ExecutionContext,
        tool_invoker: ApprovedToolInvoker,
    ) -> M5SkillResult:
        del execution_context, tool_invoker
        self.calls += 1
        return M5SkillResult(
            skill_id=request.skill_id,
            status=SkillExecutionStatus.SUCCESS,
        )


class RecordingWorkflow:
    def __init__(self) -> None:
        self.calls = 0

    async def start(
        self,
        request: WorkflowExecutionRequest,
        execution_context: ExecutionContext,
        tool_invoker: ApprovedToolInvoker,
    ) -> M5WorkflowResult:
        del execution_context, tool_invoker
        self.calls += 1
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
        self.calls += 1
        return M5WorkflowResult(
            workflow_instance_id=request.workflow_instance_id,
            workflow_id=request.workflow_id,
            status=WorkflowExecutionStatus.RUNNING,
        )


class RecordingTool:
    def __init__(self) -> None:
        self.calls = 0

    async def invoke(
        self,
        request: ToolInvocationRequest,
        execution_context: ExecutionContext,
    ) -> M5ToolResult:
        del execution_context
        self.calls += 1
        return M5ToolResult(
            tool_call_id=request.tool_call_id,
            tool_id=request.tool_id,
            status=ToolExecutionStatus.SUCCESS,
            attempt=request.attempt,
        )


class StaticPermissionProvider:
    def __init__(
        self,
        *,
        granted: frozenset[str] = frozenset({"TOOL_USE"}),
        denied: frozenset[str] = frozenset(),
    ) -> None:
        self._granted = granted
        self._denied = denied

    async def build(
        self,
        execution_context: ExecutionContext,
    ) -> ExecutionPermissionContext:
        return ExecutionPermissionContext(
            execution_id=execution_context.execution_id,
            identity_scope=execution_context.identity_scope,
            granted_permissions=self._granted,
            denied_permissions=self._denied,
        )


class FailIfCalledPermissionProvider:
    async def build(
        self,
        execution_context: ExecutionContext,
    ) -> ExecutionPermissionContext:
        del execution_context
        raise AssertionError("permission provider must not be called")


class TimeoutPermissionProvider:
    async def build(
        self,
        execution_context: ExecutionContext,
    ) -> ExecutionPermissionContext:
        del execution_context
        raise TimeoutError("permission facts unavailable")


class TimeoutPermissionEvaluator:
    def evaluate(
        self,
        tool_definition: ToolDefinition,
        permission_context: ExecutionPermissionContext,
    ) -> PermissionDecision:
        del tool_definition, permission_context
        raise TimeoutError("permission evaluation unavailable")


class StaticPermissionEvaluator:
    def evaluate(
        self,
        tool_definition: ToolDefinition,
        permission_context: ExecutionPermissionContext,
    ) -> PermissionDecision:
        required = tuple(tool_definition.required_permissions or ())
        denied = tuple(
            permission
            for permission in required
            if permission in permission_context.denied_permissions
        )
        if denied:
            return PermissionDecision(
                status=PermissionDecisionStatus.DENIED,
                reason_codes=("PERMISSION_DENIED",),
                missing_permissions=denied,
            )

        missing = tuple(
            permission
            for permission in required
            if permission not in permission_context.granted_permissions
        )
        if missing:
            return PermissionDecision(
                status=PermissionDecisionStatus.UNKNOWN,
                reason_codes=("PERMISSION_UNKNOWN",),
                missing_permissions=missing,
            )

        return PermissionDecision(
            status=PermissionDecisionStatus.ALLOWED,
            reason_codes=("PERMISSION_ALLOWED",),
        )


def _execution_context() -> ExecutionContext:
    return ExecutionContext(
        execution_id="execution-iu3",
        plan_id="plan-001",
        request_id="request-001",
        session_id="session-001",
        identity_scope="scope-001",
        policy_snapshot={"allowed": True},
        current_state=RuntimeControlState.PROCESSING,
    )


def _plan(
    *,
    skill_version: str | None = "1.0.0",
    workflow_version: str | None = "1.0.0",
    tool_versions: tuple[tuple[str, str | None], ...] = (("DOMAIN_TOOL", "1.0.0"),),
    workflow_id: str | None = "DOMAIN_WORKFLOW",
    tool_requirement: str | None = "DOMAIN_TOOL",
    forced_workflow: str | None = "DOMAIN_WORKFLOW",
    execution_owner: str | None = None,
):
    base = build_approved_action_plan()
    step = base.steps[0].model_copy(
        update={
            "action": "DOMAIN_ACTION",
            "skill_id": "DOMAIN_SKILL",
            "workflow_id": workflow_id,
            "tool_requirement": tool_requirement,
        }
    )

    owner = execution_owner or ("WORKFLOW" if workflow_id is not None else "SKILL")
    binding = {
        "action_id": "DOMAIN_ACTION",
        "skill_id": "DOMAIN_SKILL",
        "skill_version": skill_version,
        "workflow_id": workflow_id,
        "workflow_version": workflow_version if workflow_id is not None else None,
        "execution_owner": owner,
    }
    calls = [
        {
            "tool_id": tool_id,
            "tool_version": version,
            "required": True,
            "required_by_skills": ["DOMAIN_SKILL"] if owner == "SKILL" else [],
            "required_by_workflows": (
                [workflow_id]
                if owner == "WORKFLOW" and workflow_id is not None
                else []
            ),
            "timeout_policy": None,
            "retry_policy": None,
            "idempotency_mode": None,
            "side_effect_level": None,
        }
        for tool_id, version in tool_versions
    ]
    policy_snapshot: dict[str, object] = {"allowed": True}
    if forced_workflow is not None:
        policy_snapshot["forced_workflow"] = forced_workflow

    return base.model_copy(
        update={
            "steps": [step],
            "capability_plan": {
                "bindings": [binding],
                "selected_skills": ["DOMAIN_SKILL"],
                "selected_workflows": (
                    [workflow_id] if workflow_id is not None else []
                ),
            },
            "tool_plan": {
                "tool_calls": calls,
                "parallelizable": False,
                "required_success": bool(calls),
            },
            "policy_snapshot": policy_snapshot,
        }
    )


def _registries(
    *,
    skill_version: str = "1.0.0",
    workflow_version: str = "1.0.0",
    tool_versions: tuple[str, ...] = ("1.0.0",),
    enabled: bool = True,
    skill_states: list[str] | None = None,
    workflow_states: list[str] | None = None,
    tool_implementation: object | None = None,
):
    skill = RecordingSkill()
    workflow = RecordingWorkflow()
    default_tool = RecordingTool()

    skills = SkillRegistry()
    skills.register(
        SkillDefinition(
            skill_id="DOMAIN_SKILL",
            version=skill_version,
            enabled=enabled,
            supported_actions=["DOMAIN_ACTION"],
            allowed_states=skill_states,
        ),
        implementation_ref=skill,
    )

    workflows = WorkflowRegistry()
    workflows.register(
        WorkflowDefinition(
            workflow_id="DOMAIN_WORKFLOW",
            version=workflow_version,
            enabled=enabled,
            allowed_states=workflow_states,
        ),
        implementation_ref=workflow,
    )

    tools = ToolRegistry()
    tool_impls: dict[str, RecordingTool] = {}
    for version in tool_versions:
        implementation = (
            tool_implementation if tool_implementation is not None else RecordingTool()
        )
        tools.register(
            ToolDefinition(
                tool_id="DOMAIN_TOOL",
                version=version,
                enabled=enabled,
                required_permissions=["TOOL_USE"],
            ),
            implementation_ref=implementation,
        )
        if isinstance(implementation, RecordingTool):
            tool_impls[version] = implementation

    resolver = ExecutionImplementationResolver(
        skill_registry=skills,
        workflow_registry=workflows,
        tool_registry=tools,
    )
    return resolver, skill, workflow, default_tool, tool_impls


def _step_resolver(
    implementation_resolver: ExecutionImplementationResolver,
    *,
    granted: frozenset[str] = frozenset({"TOOL_USE"}),
    denied: frozenset[str] = frozenset(),
) -> StepCapabilityResolver:
    return StepCapabilityResolver(
        implementation_resolver=implementation_resolver,
        permission_context_provider=StaticPermissionProvider(
            granted=granted,
            denied=denied,
        ),
        permission_evaluator=StaticPermissionEvaluator(),
    )


def test_resolves_exact_approved_capabilities_without_invoking_them() -> None:
    plan = _plan()
    resolver, skill_impl, workflow_impl, _, tool_impls = _registries()

    decision = asyncio.run(
        _step_resolver(resolver).resolve(
            approved_plan=plan,
            step=plan.steps[0],
            execution_context=_execution_context(),
            current_state=RuntimeControlState.PROCESSING,
        )
    )

    assert decision.status is CapabilityResolutionStatus.RESOLVED
    assert decision.resolved is not None
    assert decision.resolved.execution_owner is CapabilityExecutionOwner.WORKFLOW
    assert decision.resolved.skill is not None
    assert decision.resolved.skill.version == "1.0.0"
    assert decision.resolved.workflow is not None
    assert decision.resolved.workflow.version == "1.0.0"
    assert [tool.version for tool in decision.resolved.tools] == ["1.0.0"]
    assert skill_impl.calls == 0
    assert workflow_impl.calls == 0
    assert tool_impls["1.0.0"].calls == 0


def test_core_step_without_external_capability_is_not_execution_success() -> None:
    plan = build_approved_action_plan()
    resolver = ExecutionImplementationResolver(
        skill_registry=SkillRegistry(),
        workflow_registry=WorkflowRegistry(),
        tool_registry=ToolRegistry(),
    )

    decision = asyncio.run(
        _step_resolver(resolver).resolve(
            approved_plan=plan,
            step=plan.steps[0],
            execution_context=_execution_context(),
            current_state=RuntimeControlState.PROCESSING,
        )
    )

    assert decision.status is CapabilityResolutionStatus.NO_EXTERNAL_CAPABILITY
    assert decision.reason_codes == ("NO_EXTERNAL_CAPABILITY",)
    assert decision.resolved is not None
    assert decision.resolved.has_external_capability is False


def test_unpinned_approved_version_fails_closed() -> None:
    plan = _plan(skill_version=None)
    resolver, *_ = _registries()

    decision = asyncio.run(
        _step_resolver(resolver).resolve(
            approved_plan=plan,
            step=plan.steps[0],
            execution_context=_execution_context(),
            current_state=RuntimeControlState.PROCESSING,
        )
    )

    assert decision.status is CapabilityResolutionStatus.BLOCKED
    assert decision.reason_codes == ("CAPABILITY_VERSION_UNPINNED",)


def test_missing_execution_owner_fails_closed() -> None:
    plan = _plan()
    capability_plan = dict(plan.capability_plan or {})
    bindings = [dict(item) for item in capability_plan["bindings"]]
    bindings[0].pop("execution_owner")
    capability_plan["bindings"] = bindings
    invalid = plan.model_copy(update={"capability_plan": capability_plan})
    resolver, *_ = _registries()

    decision = asyncio.run(
        _step_resolver(resolver).resolve(
            approved_plan=invalid,
            step=invalid.steps[0],
            execution_context=_execution_context(),
            current_state=RuntimeControlState.PROCESSING,
        )
    )

    assert decision.status is CapabilityResolutionStatus.BLOCKED
    assert decision.reason_codes == ("APPROVED_CAPABILITY_PLAN_INCONSISTENT",)


def test_workflow_owner_cannot_inherit_skill_tool_provenance() -> None:
    plan = _plan()
    tool_plan = dict(plan.tool_plan or {})
    calls = [dict(item) for item in tool_plan["tool_calls"]]
    calls[0]["required_by_skills"] = ["DOMAIN_SKILL"]
    calls[0]["required_by_workflows"] = []
    tool_plan["tool_calls"] = calls
    invalid = plan.model_copy(update={"tool_plan": tool_plan})
    resolver, *_ = _registries()

    decision = asyncio.run(
        _step_resolver(resolver).resolve(
            approved_plan=invalid,
            step=invalid.steps[0],
            execution_context=_execution_context(),
            current_state=RuntimeControlState.PROCESSING,
        )
    )

    assert decision.status is CapabilityResolutionStatus.BLOCKED
    assert decision.reason_codes == ("APPROVED_TOOL_PLAN_INCONSISTENT",)


def test_other_enabled_version_is_never_substituted_for_approved_version() -> None:
    plan = _plan(skill_version="1.0.0")
    resolver, *_ = _registries(skill_version="2.0.0")

    decision = asyncio.run(
        _step_resolver(resolver).resolve(
            approved_plan=plan,
            step=plan.steps[0],
            execution_context=_execution_context(),
            current_state=RuntimeControlState.PROCESSING,
        )
    )

    assert decision.status is CapabilityResolutionStatus.BLOCKED
    assert decision.reason_codes == ("CAPABILITY_NOT_FOUND",)


def test_disabled_exact_approved_version_is_blocked() -> None:
    plan = _plan()
    resolver, *_ = _registries(enabled=False)

    decision = asyncio.run(
        _step_resolver(resolver).resolve(
            approved_plan=plan,
            step=plan.steps[0],
            execution_context=_execution_context(),
            current_state=RuntimeControlState.PROCESSING,
        )
    )

    assert decision.status is CapabilityResolutionStatus.BLOCKED
    assert decision.reason_codes == ("CAPABILITY_DISABLED",)


def test_missing_implementation_ref_is_blocked() -> None:
    plan = _plan()
    skills = SkillRegistry()
    skills.register(
        SkillDefinition(
            skill_id="DOMAIN_SKILL",
            version="1.0.0",
            supported_actions=["DOMAIN_ACTION"],
        )
    )
    resolver = ExecutionImplementationResolver(
        skill_registry=skills,
        workflow_registry=WorkflowRegistry(),
        tool_registry=ToolRegistry(),
    )

    no_workflow = plan.model_copy(
        update={
            "steps": [plan.steps[0].model_copy(update={"workflow_id": None})],
            "capability_plan": {
                "bindings": [
                    {
                        "action_id": "DOMAIN_ACTION",
                        "skill_id": "DOMAIN_SKILL",
                        "skill_version": "1.0.0",
                        "workflow_id": None,
                        "workflow_version": None,
                        "execution_owner": "SKILL",
                    }
                ],
                "selected_skills": ["DOMAIN_SKILL"],
                "selected_workflows": [],
            },
            "tool_plan": {
                "tool_calls": [],
                "parallelizable": False,
                "required_success": False,
            },
            "policy_snapshot": {"allowed": True},
        }
    )
    no_workflow = no_workflow.model_copy(
        update={
            "steps": [
                no_workflow.steps[0].model_copy(update={"tool_requirement": None})
            ]
        }
    )

    decision = asyncio.run(
        _step_resolver(resolver).resolve(
            approved_plan=no_workflow,
            step=no_workflow.steps[0],
            execution_context=_execution_context(),
            current_state=RuntimeControlState.PROCESSING,
        )
    )

    assert decision.status is CapabilityResolutionStatus.BLOCKED
    assert decision.reason_codes == ("IMPLEMENTATION_REF_MISSING",)


def test_wrong_implementation_protocol_is_blocked() -> None:
    plan = _plan(workflow_id=None, forced_workflow=None)
    resolver, *_ = _registries(tool_implementation=object())

    decision = asyncio.run(
        _step_resolver(resolver).resolve(
            approved_plan=plan,
            step=plan.steps[0],
            execution_context=_execution_context(),
            current_state=RuntimeControlState.PROCESSING,
        )
    )

    assert decision.status is CapabilityResolutionStatus.BLOCKED
    assert decision.reason_codes == ("IMPLEMENTATION_PROTOCOL_INVALID",)


def test_skill_and_workflow_allowed_states_are_runtime_gates() -> None:
    plan = _plan()
    resolver, *_ = _registries(
        skill_states=["WAITING_EXTERNAL"],
        workflow_states=["PROCESSING"],
    )

    decision = asyncio.run(
        _step_resolver(resolver).resolve(
            approved_plan=plan,
            step=plan.steps[0],
            execution_context=_execution_context(),
            current_state=RuntimeControlState.PROCESSING,
        )
    )

    assert decision.status is CapabilityResolutionStatus.BLOCKED
    assert decision.reason_codes == ("CAPABILITY_STATE_INELIGIBLE",)


def test_required_capability_state_without_current_fact_is_unknown() -> None:
    plan = _plan()
    resolver, *_ = _registries(skill_states=["PROCESSING"])

    decision = asyncio.run(
        _step_resolver(resolver).resolve(
            approved_plan=plan,
            step=plan.steps[0],
            execution_context=_execution_context(),
            current_state=None,
        )
    )

    assert decision.status is CapabilityResolutionStatus.UNKNOWN
    assert decision.reason_codes == ("CAPABILITY_STATE_UNKNOWN",)


def test_forced_workflow_authority_cannot_drift() -> None:
    plan = _plan(forced_workflow="WF_FORCED")
    resolver, *_ = _registries()

    decision = asyncio.run(
        _step_resolver(resolver).resolve(
            approved_plan=plan,
            step=plan.steps[0],
            execution_context=_execution_context(),
            current_state=RuntimeControlState.PROCESSING,
        )
    )

    assert decision.status is CapabilityResolutionStatus.BLOCKED
    assert decision.reason_codes == ("WORKFLOW_AUTHORITY_INVALID",)


def test_tool_without_required_permissions_needs_no_permission_facts() -> None:
    plan = _plan(workflow_id=None, forced_workflow=None)

    skills = SkillRegistry()
    skills.register(
        SkillDefinition(
            skill_id="DOMAIN_SKILL",
            version="1.0.0",
            supported_actions=["DOMAIN_ACTION"],
        ),
        implementation_ref=RecordingSkill(),
    )
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            tool_id="DOMAIN_TOOL",
            version="1.0.0",
            required_permissions=None,
        ),
        implementation_ref=RecordingTool(),
    )
    implementation_resolver = ExecutionImplementationResolver(
        skill_registry=skills,
        workflow_registry=WorkflowRegistry(),
        tool_registry=tools,
    )
    resolver = StepCapabilityResolver(
        implementation_resolver=implementation_resolver,
        permission_context_provider=FailIfCalledPermissionProvider(),
        permission_evaluator=StaticPermissionEvaluator(),
    )

    decision = asyncio.run(
        resolver.resolve(
            approved_plan=plan,
            step=plan.steps[0],
            execution_context=_execution_context(),
            current_state=RuntimeControlState.PROCESSING,
        )
    )

    assert decision.status is CapabilityResolutionStatus.RESOLVED


@pytest.mark.parametrize(
    ("granted", "denied", "expected_status", "expected_reason"),
    [
        (
            frozenset(),
            frozenset({"TOOL_USE"}),
            CapabilityResolutionStatus.BLOCKED,
            "TOOL_PERMISSION_DENIED",
        ),
        (
            frozenset(),
            frozenset(),
            CapabilityResolutionStatus.UNKNOWN,
            "TOOL_PERMISSION_UNKNOWN",
        ),
    ],
)
def test_tool_permission_denied_or_unknown_never_becomes_allowed(
    granted: frozenset[str],
    denied: frozenset[str],
    expected_status: CapabilityResolutionStatus,
    expected_reason: str,
) -> None:
    plan = _plan()
    resolver, *_ = _registries()

    decision = asyncio.run(
        _step_resolver(
            resolver,
            granted=granted,
            denied=denied,
        ).resolve(
            approved_plan=plan,
            step=plan.steps[0],
            execution_context=_execution_context(),
            current_state=RuntimeControlState.PROCESSING,
        )
    )

    assert decision.status is expected_status
    assert decision.reason_codes == (expected_reason,)


def test_permission_provider_timeout_fails_closed_as_unknown() -> None:
    plan = _plan()
    implementation_resolver, *_ = _registries()
    resolver = StepCapabilityResolver(
        implementation_resolver=implementation_resolver,
        permission_context_provider=TimeoutPermissionProvider(),
        permission_evaluator=StaticPermissionEvaluator(),
    )

    decision = asyncio.run(
        resolver.resolve(
            approved_plan=plan,
            step=plan.steps[0],
            execution_context=_execution_context(),
            current_state=RuntimeControlState.PROCESSING,
        )
    )

    assert decision.status is CapabilityResolutionStatus.UNKNOWN
    assert decision.reason_codes == ("TOOL_PERMISSION_UNKNOWN",)


def test_permission_evaluator_timeout_fails_closed_as_unknown() -> None:
    plan = _plan()
    implementation_resolver, *_ = _registries()
    resolver = StepCapabilityResolver(
        implementation_resolver=implementation_resolver,
        permission_context_provider=StaticPermissionProvider(),
        permission_evaluator=TimeoutPermissionEvaluator(),
    )

    decision = asyncio.run(
        resolver.resolve(
            approved_plan=plan,
            step=plan.steps[0],
            execution_context=_execution_context(),
            current_state=RuntimeControlState.PROCESSING,
        )
    )

    assert decision.status is CapabilityResolutionStatus.UNKNOWN
    assert decision.reason_codes == ("TOOL_PERMISSION_UNKNOWN",)


def test_multiple_required_tools_are_projected_from_approved_tool_plan() -> None:
    plan = _plan(
        tool_versions=(
            ("DOMAIN_TOOL", "1.0.0"),
            ("DOMAIN_TOOL_2", "1.0.0"),
        ),
        tool_requirement=None,
    )

    skill = RecordingSkill()
    workflow = RecordingWorkflow()
    skills = SkillRegistry()
    skills.register(
        SkillDefinition(
            skill_id="DOMAIN_SKILL",
            version="1.0.0",
            supported_actions=["DOMAIN_ACTION"],
        ),
        implementation_ref=skill,
    )
    workflows = WorkflowRegistry()
    workflows.register(
        WorkflowDefinition(
            workflow_id="DOMAIN_WORKFLOW",
            version="1.0.0",
        ),
        implementation_ref=workflow,
    )
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            tool_id="DOMAIN_TOOL",
            version="1.0.0",
            required_permissions=["TOOL_USE"],
        ),
        implementation_ref=RecordingTool(),
    )
    tools.register(
        ToolDefinition(
            tool_id="DOMAIN_TOOL_2",
            version="1.0.0",
            required_permissions=["TOOL_USE"],
        ),
        implementation_ref=RecordingTool(),
    )
    resolver = ExecutionImplementationResolver(
        skill_registry=skills,
        workflow_registry=workflows,
        tool_registry=tools,
    )

    decision = asyncio.run(
        _step_resolver(resolver).resolve(
            approved_plan=plan,
            step=plan.steps[0],
            execution_context=_execution_context(),
            current_state=RuntimeControlState.PROCESSING,
        )
    )

    assert decision.status is CapabilityResolutionStatus.RESOLVED
    assert decision.resolved is not None
    assert [tool.capability_id for tool in decision.resolved.tools] == [
        "DOMAIN_TOOL",
        "DOMAIN_TOOL_2",
    ]


def test_step_tool_projection_must_exist_in_approved_tool_plan() -> None:
    plan = _plan(tool_versions=(), tool_requirement="DOMAIN_TOOL")
    resolver, *_ = _registries()

    decision = asyncio.run(
        _step_resolver(resolver).resolve(
            approved_plan=plan,
            step=plan.steps[0],
            execution_context=_execution_context(),
            current_state=RuntimeControlState.PROCESSING,
        )
    )

    assert decision.status is CapabilityResolutionStatus.BLOCKED
    assert decision.reason_codes == ("APPROVED_TOOL_PLAN_INCONSISTENT",)


def test_mutated_step_cannot_gain_capability_authority() -> None:
    plan = _plan()
    mutated = plan.steps[0].model_copy(update={"skill_id": "OTHER_SKILL"})
    resolver, *_ = _registries()

    decision = asyncio.run(
        _step_resolver(resolver).resolve(
            approved_plan=plan,
            step=mutated,
            execution_context=_execution_context(),
            current_state=RuntimeControlState.PROCESSING,
        )
    )

    assert decision.status is CapabilityResolutionStatus.BLOCKED
    assert decision.reason_codes == ("APPROVED_STEP_MISMATCH",)
