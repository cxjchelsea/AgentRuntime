"""M5-IU4 exact Skill / fresh Workflow / approved Tool execution gates."""

from __future__ import annotations

import asyncio
from typing import Any

from runtime.contracts.enums import RuntimeControlState
from runtime.contracts.execution import ExecutionContext
from runtime.execution import (
    CapabilityExecutionOwner,
    CapabilityKind,
    CapabilityReferenceSource,
    M5SkillResult,
    M5ToolResult,
    M5WorkflowResult,
    PermissionDecision,
    PermissionDecisionStatus,
    ResolvedCapability,
    ResolvedStepCapabilities,
    SkillExecutionStatus,
    StepExecutionStatus,
    StepLifecycleSnapshot,
    ToolExecutionStatus,
    ToolPayloadValidationDecision,
    ToolPayloadValidationStatus,
    WorkflowExecutionStatus,
)
from runtime.execution.capability_execution import (
    CapabilityExecutionStatus,
    StepCapabilityExecutor,
)
from runtime.registries import SkillDefinition, ToolDefinition, WorkflowDefinition
from tests.orchestration_stubs import build_approved_action_plan


class CountingIdentifierFactory:
    def __init__(self) -> None:
        self.tool_counter = 0
        self.workflow_counter = 0

    def new_tool_call_id(
        self,
        *,
        step_execution_id: str,
        tool_id: str,
    ) -> str:
        self.tool_counter += 1
        return f"{step_execution_id}:{tool_id}:{self.tool_counter}"

    def new_workflow_instance_id(
        self,
        *,
        step_execution_id: str,
        workflow_id: str,
    ) -> str:
        self.workflow_counter += 1
        return f"{step_execution_id}:{workflow_id}:{self.workflow_counter}"


class BrokenIdentifierFactory(CountingIdentifierFactory):
    def new_tool_call_id(
        self,
        *,
        step_execution_id: str,
        tool_id: str,
    ) -> str:
        del step_execution_id, tool_id
        raise RuntimeError("id service unavailable")


class StaticValidator:
    def __init__(
        self,
        status: ToolPayloadValidationStatus = ToolPayloadValidationStatus.VALID,
        reason: str = "VALID",
    ) -> None:
        self.status = status
        self.reason = reason
        self.calls = 0

    def validate(
        self,
        tool_definition: ToolDefinition,
        payload: object,
    ) -> ToolPayloadValidationDecision:
        del tool_definition, payload
        self.calls += 1
        return ToolPayloadValidationDecision(
            status=self.status,
            reason_codes=(self.reason,),
        )


class ExplodingValidator(StaticValidator):
    def validate(
        self,
        tool_definition: ToolDefinition,
        payload: object,
    ) -> ToolPayloadValidationDecision:
        del tool_definition, payload
        self.calls += 1
        raise RuntimeError("validator unavailable")


class StaticPermissionProvider:
    def __init__(
        self,
        *,
        granted: frozenset[str] = frozenset({"TOOL_USE"}),
        denied: frozenset[str] = frozenset(),
    ) -> None:
        self.granted = granted
        self.denied = denied
        self.calls = 0

    async def build(
        self,
        execution_context: ExecutionContext,
    ):
        from runtime.execution import ExecutionPermissionContext

        self.calls += 1
        return ExecutionPermissionContext(
            execution_id=execution_context.execution_id,
            identity_scope=execution_context.identity_scope,
            granted_permissions=self.granted,
            denied_permissions=self.denied,
        )


class StaticPermissionEvaluator:
    def __init__(
        self,
        status: PermissionDecisionStatus = PermissionDecisionStatus.ALLOWED,
    ) -> None:
        self.status = status
        self.calls = 0

    def evaluate(
        self,
        tool_definition: ToolDefinition,
        permission_context,
    ) -> PermissionDecision:
        del tool_definition, permission_context
        self.calls += 1
        if self.status is PermissionDecisionStatus.ALLOWED:
            return PermissionDecision(
                status=self.status,
                reason_codes=("PERMISSION_ALLOWED",),
            )
        return PermissionDecision(
            status=self.status,
            reason_codes=("PERMISSION_NOT_ALLOWED",),
            missing_permissions=("TOOL_USE",),
        )


class RecordingTool:
    def __init__(
        self,
        *,
        status: ToolExecutionStatus = ToolExecutionStatus.SUCCESS,
    ) -> None:
        self.status = status
        self.calls = 0
        self.requests = []

    async def invoke(self, request, execution_context):
        del execution_context
        self.calls += 1
        self.requests.append(request)
        return M5ToolResult(
            tool_call_id=request.tool_call_id,
            tool_id=request.tool_id,
            status=self.status,
            data={"ok": True} if self.status is ToolExecutionStatus.SUCCESS else None,
            attempt=request.attempt,
        )


class RecordingSkill:
    def __init__(
        self,
        *,
        tool_ids: tuple[str, ...] = (),
        report_tool_results: bool = False,
        fabricated_tool_result: M5ToolResult | None = None,
        fail_after_tools: bool = False,
    ) -> None:
        self.tool_ids = tool_ids
        self.report_tool_results = report_tool_results
        self.fabricated_tool_result = fabricated_tool_result
        self.fail_after_tools = fail_after_tools
        self.calls = 0
        self.requests = []

    async def execute(self, request, execution_context, tool_invoker):
        del execution_context
        self.calls += 1
        self.requests.append(request)
        results = []
        for tool_id in self.tool_ids:
            results.append(
                await tool_invoker.invoke(
                    tool_id=tool_id,
                    input_payload={"value": 1},
                )
            )
        if self.fail_after_tools:
            raise RuntimeError("skill failed after Tool observation")
        if self.fabricated_tool_result is not None:
            reported = (self.fabricated_tool_result,)
        elif self.report_tool_results:
            reported = tuple(results)
        else:
            reported = ()
        return M5SkillResult(
            skill_id=request.skill_id,
            status=SkillExecutionStatus.SUCCESS,
            business_outputs=({"skill": "done"},),
            tool_results=reported,
        )


class RecordingWorkflow:
    def __init__(
        self,
        *,
        tool_ids: tuple[str, ...] = (),
        status: WorkflowExecutionStatus = WorkflowExecutionStatus.COMPLETED,
        wrong_instance: bool = False,
    ) -> None:
        self.tool_ids = tool_ids
        self.status = status
        self.wrong_instance = wrong_instance
        self.start_calls = 0
        self.resume_calls = 0
        self.requests = []

    async def start(self, request, execution_context, tool_invoker):
        del execution_context
        self.start_calls += 1
        self.requests.append(request)
        results = []
        for tool_id in self.tool_ids:
            results.append(
                await tool_invoker.invoke(
                    tool_id=tool_id,
                    input_payload={"value": 1},
                )
            )
        return M5WorkflowResult(
            workflow_instance_id=(
                "wrong-instance"
                if self.wrong_instance
                else request.workflow_instance_id
            ),
            workflow_id=request.workflow_id,
            status=self.status,
            tool_results=tuple(results),
        )

    async def resume(self, request, execution_context, tool_invoker):
        del request, execution_context, tool_invoker
        self.resume_calls += 1
        raise AssertionError("M5-IU4 must not call Workflow.resume")


def _execution_context() -> ExecutionContext:
    return ExecutionContext(
        execution_id="execution-iu4",
        plan_id="plan-001",
        request_id="request-001",
        session_id="session-001",
        identity_scope="scope-001",
        policy_snapshot={"allowed": True},
        current_state=RuntimeControlState.PROCESSING,
    )


def _approved_step(
    *,
    owner: CapabilityExecutionOwner,
):
    base = build_approved_action_plan()
    step = base.steps[0].model_copy(
        update={
            "action": "DOMAIN_ACTION",
            "parameters": {"p": 1},
            "skill_id": "DOMAIN_SKILL" if owner is CapabilityExecutionOwner.SKILL else None,
            "workflow_id": (
                "DOMAIN_WORKFLOW"
                if owner is CapabilityExecutionOwner.WORKFLOW
                else None
            ),
            "tool_requirement": None,
        }
    )
    return base.model_copy(update={"steps": [step]}), step


def _snapshot(step, *, status: StepExecutionStatus = StepExecutionStatus.RUNNING):
    return StepLifecycleSnapshot(
        step_execution_id="step-execution-001",
        step_id=step.step_id,
        action=step.action,
        status=status,
        skill_id=step.skill_id,
        workflow_id=step.workflow_id,
    )


def _tool(
    implementation: RecordingTool,
    *,
    required_permissions: list[str] | None = None,
    tool_id: str = "DOMAIN_TOOL",
) -> ResolvedCapability:
    return ResolvedCapability(
        kind=CapabilityKind.TOOL,
        capability_id=tool_id,
        version="1.0.0",
        definition=ToolDefinition(
            tool_id=tool_id,
            version="1.0.0",
            required_permissions=required_permissions,
        ),
        implementation_ref=implementation,
        source=CapabilityReferenceSource.APPROVED_TOOL_PLAN,
    )


def _skill_resolved(
    skill: RecordingSkill,
    *,
    tools: tuple[ResolvedCapability, ...] = (),
) -> ResolvedStepCapabilities:
    return ResolvedStepCapabilities(
        step_id="step-001",
        execution_owner=CapabilityExecutionOwner.SKILL,
        skill=ResolvedCapability(
            kind=CapabilityKind.SKILL,
            capability_id="DOMAIN_SKILL",
            version="3.2.1",
            definition=SkillDefinition(
                skill_id="DOMAIN_SKILL",
                version="3.2.1",
                supported_actions=["DOMAIN_ACTION"],
            ),
            implementation_ref=skill,
            source=CapabilityReferenceSource.STEP_SKILL,
        ),
        tools=tools,
    )


def _workflow_resolved(
    workflow: RecordingWorkflow,
    *,
    tools: tuple[ResolvedCapability, ...] = (),
) -> ResolvedStepCapabilities:
    return ResolvedStepCapabilities(
        step_id="step-001",
        execution_owner=CapabilityExecutionOwner.WORKFLOW,
        workflow=ResolvedCapability(
            kind=CapabilityKind.WORKFLOW,
            capability_id="DOMAIN_WORKFLOW",
            version="4.5.6",
            definition=WorkflowDefinition(
                workflow_id="DOMAIN_WORKFLOW",
                version="4.5.6",
            ),
            implementation_ref=workflow,
            source=CapabilityReferenceSource.STEP_WORKFLOW,
        ),
        tools=tools,
    )


def _executor(
    *,
    provider: StaticPermissionProvider | None = None,
    evaluator: StaticPermissionEvaluator | None = None,
    input_validator: StaticValidator | None = None,
    output_validator: StaticValidator | None = None,
    identifier_factory: CountingIdentifierFactory | None = None,
) -> StepCapabilityExecutor:
    return StepCapabilityExecutor(
        permission_context_provider=provider or StaticPermissionProvider(),
        permission_evaluator=evaluator or StaticPermissionEvaluator(),
        input_validator=input_validator or StaticValidator(),
        output_validator=output_validator or StaticValidator(),
        identifier_factory=identifier_factory or CountingIdentifierFactory(),
    )


def test_skill_owner_executes_exact_skill_and_approved_tool_once() -> None:
    plan, step = _approved_step(owner=CapabilityExecutionOwner.SKILL)
    tool_impl = RecordingTool()
    skill_impl = RecordingSkill(tool_ids=("DOMAIN_TOOL",))
    resolved = _skill_resolved(skill_impl, tools=(_tool(tool_impl),))

    outcome = asyncio.run(
        _executor().execute(
            approved_plan=plan,
            step=step,
            step_snapshot=_snapshot(step),
            resolved=resolved,
            execution_context=_execution_context(),
        )
    )

    assert outcome.status is CapabilityExecutionStatus.EXECUTED
    assert outcome.owner_capability_id == "DOMAIN_SKILL"
    assert outcome.owner_capability_version == "3.2.1"
    assert skill_impl.calls == 1
    assert skill_impl.requests[0].parameters == {"p": 1}
    assert tool_impl.calls == 1
    assert tool_impl.requests[0].attempt == 1
    assert tool_impl.requests[0].idempotency_key is None
    assert len(outcome.tool_results) == 1
    assert outcome.skill_result is not None
    assert outcome.skill_result.tool_results == outcome.tool_results


def test_workflow_owner_starts_fresh_workflow_and_never_resumes() -> None:
    plan, step = _approved_step(owner=CapabilityExecutionOwner.WORKFLOW)
    workflow = RecordingWorkflow(status=WorkflowExecutionStatus.WAITING)
    resolved = _workflow_resolved(workflow)

    outcome = asyncio.run(
        _executor().execute(
            approved_plan=plan,
            step=step,
            step_snapshot=_snapshot(step),
            resolved=resolved,
            execution_context=_execution_context(),
        )
    )

    assert outcome.status is CapabilityExecutionStatus.WAITING
    assert outcome.owner_capability_version == "4.5.6"
    assert workflow.start_calls == 1
    assert workflow.resume_calls == 0
    assert workflow.requests[0].inputs == {"p": 1}


def test_unapproved_tool_request_is_blocked_and_never_invoked() -> None:
    plan, step = _approved_step(owner=CapabilityExecutionOwner.SKILL)
    approved_tool = RecordingTool()
    skill = RecordingSkill(tool_ids=("UNAPPROVED_TOOL",))
    resolved = _skill_resolved(skill, tools=(_tool(approved_tool),))

    outcome = asyncio.run(
        _executor().execute(
            approved_plan=plan,
            step=step,
            step_snapshot=_snapshot(step),
            resolved=resolved,
            execution_context=_execution_context(),
        )
    )

    assert outcome.status is CapabilityExecutionStatus.BLOCKED
    assert "TOOL_NOT_APPROVED_FOR_STEP" in outcome.reason_codes
    assert approved_tool.calls == 0


def test_input_invalid_prevents_permission_and_tool_invocation() -> None:
    plan, step = _approved_step(owner=CapabilityExecutionOwner.SKILL)
    tool_impl = RecordingTool()
    skill = RecordingSkill(tool_ids=("DOMAIN_TOOL",))
    provider = StaticPermissionProvider()
    input_validator = StaticValidator(
        ToolPayloadValidationStatus.INVALID,
        "INPUT_INVALID",
    )
    resolved = _skill_resolved(
        skill,
        tools=(_tool(tool_impl, required_permissions=["TOOL_USE"]),),
    )

    outcome = asyncio.run(
        _executor(
            provider=provider,
            input_validator=input_validator,
        ).execute(
            approved_plan=plan,
            step=step,
            step_snapshot=_snapshot(step),
            resolved=resolved,
            execution_context=_execution_context(),
        )
    )

    assert tool_impl.calls == 0
    assert provider.calls == 0
    assert outcome.tool_results[0].status is ToolExecutionStatus.REJECTED
    assert outcome.tool_results[0].error_code == "INVALID_PARAMETER"


def test_input_validator_failure_is_unknown_and_never_invokes_tool() -> None:
    plan, step = _approved_step(owner=CapabilityExecutionOwner.SKILL)
    tool_impl = RecordingTool()
    skill = RecordingSkill(tool_ids=("DOMAIN_TOOL",))
    resolved = _skill_resolved(skill, tools=(_tool(tool_impl),))

    outcome = asyncio.run(
        _executor(input_validator=ExplodingValidator()).execute(
            approved_plan=plan,
            step=step,
            step_snapshot=_snapshot(step),
            resolved=resolved,
            execution_context=_execution_context(),
        )
    )

    assert outcome.status is CapabilityExecutionStatus.UNKNOWN
    assert outcome.reason_codes == ("TOOL_EXECUTION_UNKNOWN",)
    assert tool_impl.calls == 0
    assert outcome.tool_results[0].error_code == "TOOL_INPUT_VALIDATION_UNKNOWN"


def test_permission_is_rechecked_for_each_real_tool_invocation() -> None:
    plan, step = _approved_step(owner=CapabilityExecutionOwner.SKILL)
    tool_impl = RecordingTool()
    skill = RecordingSkill(tool_ids=("DOMAIN_TOOL", "DOMAIN_TOOL"))
    provider = StaticPermissionProvider()
    evaluator = StaticPermissionEvaluator()
    resolved = _skill_resolved(
        skill,
        tools=(_tool(tool_impl, required_permissions=["TOOL_USE"]),),
    )

    outcome = asyncio.run(
        _executor(provider=provider, evaluator=evaluator).execute(
            approved_plan=plan,
            step=step,
            step_snapshot=_snapshot(step),
            resolved=resolved,
            execution_context=_execution_context(),
        )
    )

    assert outcome.status is CapabilityExecutionStatus.EXECUTED
    assert provider.calls == 2
    assert evaluator.calls == 2
    assert tool_impl.calls == 2
    assert len({item.tool_call_id for item in outcome.tool_results}) == 2


def test_permission_denied_prevents_tool_invocation() -> None:
    plan, step = _approved_step(owner=CapabilityExecutionOwner.SKILL)
    tool_impl = RecordingTool()
    skill = RecordingSkill(tool_ids=("DOMAIN_TOOL",))
    resolved = _skill_resolved(
        skill,
        tools=(_tool(tool_impl, required_permissions=["TOOL_USE"]),),
    )

    outcome = asyncio.run(
        _executor(
            evaluator=StaticPermissionEvaluator(PermissionDecisionStatus.DENIED)
        ).execute(
            approved_plan=plan,
            step=step,
            step_snapshot=_snapshot(step),
            resolved=resolved,
            execution_context=_execution_context(),
        )
    )

    assert tool_impl.calls == 0
    assert outcome.tool_results[0].status is ToolExecutionStatus.REJECTED
    assert outcome.tool_results[0].error_code == "PERMISSION_DENIED"


def test_output_invalid_preserves_raw_success_but_final_truth_is_unknown() -> None:
    plan, step = _approved_step(owner=CapabilityExecutionOwner.SKILL)
    tool_impl = RecordingTool()
    skill = RecordingSkill(tool_ids=("DOMAIN_TOOL",))
    resolved = _skill_resolved(skill, tools=(_tool(tool_impl),))

    outcome = asyncio.run(
        _executor(
            output_validator=StaticValidator(
                ToolPayloadValidationStatus.INVALID,
                "OUTPUT_INVALID",
            )
        ).execute(
            approved_plan=plan,
            step=step,
            step_snapshot=_snapshot(step),
            resolved=resolved,
            execution_context=_execution_context(),
        )
    )

    assert tool_impl.calls == 1
    assert outcome.status is CapabilityExecutionStatus.UNKNOWN
    assert outcome.tool_results[0].status is ToolExecutionStatus.UNKNOWN
    assert outcome.tool_results[0].error_code == "TOOL_INVALID_OUTPUT"


def test_non_success_tool_result_is_not_output_validated_or_upgraded() -> None:
    plan, step = _approved_step(owner=CapabilityExecutionOwner.SKILL)
    tool_impl = RecordingTool(status=ToolExecutionStatus.FAILED)
    skill = RecordingSkill(tool_ids=("DOMAIN_TOOL",))
    output_validator = StaticValidator()
    resolved = _skill_resolved(skill, tools=(_tool(tool_impl),))

    outcome = asyncio.run(
        _executor(output_validator=output_validator).execute(
            approved_plan=plan,
            step=step,
            step_snapshot=_snapshot(step),
            resolved=resolved,
            execution_context=_execution_context(),
        )
    )

    assert output_validator.calls == 0
    assert outcome.status is CapabilityExecutionStatus.EXECUTED
    assert outcome.tool_results[0].status is ToolExecutionStatus.FAILED


def test_domain_fabricated_tool_result_cannot_override_core_journal() -> None:
    plan, step = _approved_step(owner=CapabilityExecutionOwner.SKILL)
    fabricated = M5ToolResult(
        tool_call_id="fake-call",
        tool_id="DOMAIN_TOOL",
        status=ToolExecutionStatus.SUCCESS,
    )
    skill = RecordingSkill(fabricated_tool_result=fabricated)
    resolved = _skill_resolved(skill)

    outcome = asyncio.run(
        _executor().execute(
            approved_plan=plan,
            step=step,
            step_snapshot=_snapshot(step),
            resolved=resolved,
            execution_context=_execution_context(),
        )
    )

    assert outcome.status is CapabilityExecutionStatus.UNKNOWN
    assert outcome.reason_codes == ("CAPABILITY_RESULT_TOOL_TRACE_MISMATCH",)
    assert outcome.tool_results == ()


def test_skill_exception_after_tool_call_preserves_core_tool_observation() -> None:
    plan, step = _approved_step(owner=CapabilityExecutionOwner.SKILL)
    tool_impl = RecordingTool()
    skill = RecordingSkill(
        tool_ids=("DOMAIN_TOOL",),
        fail_after_tools=True,
    )
    resolved = _skill_resolved(skill, tools=(_tool(tool_impl),))

    outcome = asyncio.run(
        _executor().execute(
            approved_plan=plan,
            step=step,
            step_snapshot=_snapshot(step),
            resolved=resolved,
            execution_context=_execution_context(),
        )
    )

    assert outcome.status is CapabilityExecutionStatus.UNKNOWN
    assert outcome.reason_codes == ("SKILL_EXECUTION_EXCEPTION",)
    assert len(outcome.tool_results) == 1
    assert outcome.tool_results[0].status is ToolExecutionStatus.SUCCESS


def test_wrong_workflow_instance_result_fails_closed() -> None:
    plan, step = _approved_step(owner=CapabilityExecutionOwner.WORKFLOW)
    workflow = RecordingWorkflow(wrong_instance=True)
    resolved = _workflow_resolved(workflow)

    outcome = asyncio.run(
        _executor().execute(
            approved_plan=plan,
            step=step,
            step_snapshot=_snapshot(step),
            resolved=resolved,
            execution_context=_execution_context(),
        )
    )

    assert outcome.status is CapabilityExecutionStatus.UNKNOWN
    assert outcome.reason_codes == ("WORKFLOW_RESULT_INVALID",)
    assert workflow.resume_calls == 0


def test_none_owner_produces_no_external_execution_not_success() -> None:
    plan, step = _approved_step(owner=CapabilityExecutionOwner.NONE)
    resolved = ResolvedStepCapabilities(
        step_id=step.step_id,
        execution_owner=CapabilityExecutionOwner.NONE,
    )

    outcome = asyncio.run(
        _executor().execute(
            approved_plan=plan,
            step=step,
            step_snapshot=_snapshot(step),
            resolved=resolved,
            execution_context=_execution_context(),
        )
    )

    assert outcome.status is CapabilityExecutionStatus.NO_EXTERNAL_EXECUTION
    assert outcome.reason_codes == ("NO_EXTERNAL_EXECUTION",)


def test_mutated_step_or_non_running_snapshot_cannot_execute() -> None:
    plan, step = _approved_step(owner=CapabilityExecutionOwner.SKILL)
    skill = RecordingSkill()
    resolved = _skill_resolved(skill)

    mutated = step.model_copy(update={"parameters": {"tampered": True}})
    mutated_outcome = asyncio.run(
        _executor().execute(
            approved_plan=plan,
            step=mutated,
            step_snapshot=_snapshot(step),
            resolved=resolved,
            execution_context=_execution_context(),
        )
    )
    pending_outcome = asyncio.run(
        _executor().execute(
            approved_plan=plan,
            step=step,
            step_snapshot=_snapshot(step, status=StepExecutionStatus.PENDING),
            resolved=resolved,
            execution_context=_execution_context(),
        )
    )

    assert mutated_outcome.status is CapabilityExecutionStatus.BLOCKED
    assert mutated_outcome.reason_codes == ("APPROVED_STEP_MISMATCH",)
    assert pending_outcome.status is CapabilityExecutionStatus.BLOCKED
    assert pending_outcome.reason_codes == ("STEP_EXECUTION_SNAPSHOT_INVALID",)
    assert skill.calls == 0


def test_tool_identifier_failure_is_unknown_and_no_tool_is_called() -> None:
    plan, step = _approved_step(owner=CapabilityExecutionOwner.SKILL)
    tool_impl = RecordingTool()
    skill = RecordingSkill(tool_ids=("DOMAIN_TOOL",))
    resolved = _skill_resolved(skill, tools=(_tool(tool_impl),))

    outcome = asyncio.run(
        _executor(identifier_factory=BrokenIdentifierFactory()).execute(
            approved_plan=plan,
            step=step,
            step_snapshot=_snapshot(step),
            resolved=resolved,
            execution_context=_execution_context(),
        )
    )

    assert outcome.status is CapabilityExecutionStatus.UNKNOWN
    assert "TOOL_CALL_ID_UNAVAILABLE" in outcome.reason_codes
    assert tool_impl.calls == 0
