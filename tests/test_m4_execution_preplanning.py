"""M4-IU5 execution preplanning gates."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from runtime.contracts import PolicyDecision, RuntimeContext
from runtime.contracts.context import MemoryContext
from runtime.contracts.enums import PlanningMode
from runtime.planning import (
    CapabilityBinding,
    CapabilityPlanner,
    CapabilityPlanningError,
    ConfirmationPlanner,
    ExecutionPreplanner,
    FallbackDecision,
    FallbackPlanner,
    MemoryUsageDecision,
    MemoryUsagePlanner,
    MemoryUsagePlanningError,
    PlanningBlockedByPolicyError,
    SequencePlanner,
    ToolPlanner,
    ToolPlanningError,
)
from runtime.registries import (
    ActionDefinition,
    ActionRegistry,
    IntrusivenessLevel,
    SkillDefinition,
    SkillRegistry,
    ToolDefinition,
    ToolRegistry,
    WorkflowDefinition,
    WorkflowRegistry,
)
from tests.orchestration_stubs import (
    build_policy_decision,
    build_runtime_context,
)


def _action(
    action_id: str,
    *,
    requires_confirmation: bool = False,
) -> ActionDefinition:
    return ActionDefinition(
        action_id=action_id,
        version="1.0.0",
        category="DOMAIN_CATEGORY",
        description="domain action",
        intrusiveness_level=IntrusivenessLevel.LOW,
        requires_confirmation=requires_confirmation,
        required_capability=None,
        allowed_planning_modes=[PlanningMode.AGENT_PLANNED],
    )


def _runtime_with_memory() -> RuntimeContext:
    return build_runtime_context().model_copy(
        update={
            "memory_context": MemoryContext(
                retrieved_memories=[
                    {"memory_id": "MEM-1", "value": "domain memory"},
                    {"memory_id": "MEM-2", "value": "domain memory 2"},
                ],
                service_status="AVAILABLE",
            )
        }
    )


@dataclass(frozen=True)
class StaticMemoryRule:
    decision: MemoryUsageDecision | None

    def decide(
        self,
        runtime_context: RuntimeContext,
        selected_action_ids: tuple[str, ...],
    ) -> MemoryUsageDecision | None:
        del runtime_context, selected_action_ids
        return self.decision


@dataclass(frozen=True)
class StaticBindingRule:
    binding: CapabilityBinding | None

    def bind(
        self,
        action_id: str,
        runtime_context: RuntimeContext,
        policy_decision: PolicyDecision,
    ) -> CapabilityBinding | None:
        del runtime_context, policy_decision
        if self.binding is None:
            return None
        if self.binding.action_id != action_id:
            return None
        return self.binding


@dataclass(frozen=True)
class StaticFallbackRule:
    decision: FallbackDecision | None

    def plan(
        self,
        selected_action_ids: tuple[str, ...],
        capability_selection: object,
        tool_plan: object,
    ) -> FallbackDecision | None:
        del selected_action_ids, capability_selection, tool_plan
        return self.decision


def _registries() -> tuple[
    ActionRegistry,
    SkillRegistry,
    WorkflowRegistry,
    ToolRegistry,
]:
    actions = ActionRegistry()
    actions.register(_action("DOMAIN_ACTION"))
    actions.register(_action("DOMAIN_FALLBACK"))

    skills = SkillRegistry()
    skills.register(
        SkillDefinition(
            skill_id="DOMAIN_SKILL",
            version="1.0.0",
            supported_actions=["DOMAIN_ACTION"],
            required_tools=["DOMAIN_TOOL"],
        )
    )

    workflows = WorkflowRegistry()
    workflows.register(
        WorkflowDefinition(
            workflow_id="DOMAIN_WORKFLOW",
            version="1.0.0",
        )
    )

    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            tool_id="DOMAIN_TOOL",
            version="1.0.0",
            timeout_policy="DOMAIN_TIMEOUT",
            retry_policy="DOMAIN_RETRY",
            idempotency_mode="DOMAIN_IDEMPOTENCY",
            side_effect_level="DOMAIN_SIDE_EFFECT",
        )
    )
    return actions, skills, workflows, tools


def test_memory_usage_defaults_to_no_memory_without_explicit_rule() -> None:
    result = MemoryUsagePlanner().plan(
        _runtime_with_memory(),
        ("DOMAIN_ACTION",),
    )

    assert result.use_memory is False
    assert result.memory_ids == ()
    assert result.reason == "NO_MEMORY_USAGE_RULE"


def test_memory_usage_can_reference_only_retrieved_memory_ids() -> None:
    planner = MemoryUsagePlanner(
        rules=(
            StaticMemoryRule(
                MemoryUsageDecision(
                    use_memory=True,
                    memory_ids=("MEM-1",),
                    usage_mode="DOMAIN_MODE",
                    reason="DOMAIN_REASON",
                )
            ),
        )
    )

    result = planner.plan(_runtime_with_memory(), ("DOMAIN_ACTION",))
    assert result.memory_ids == ("MEM-1",)

    invalid = MemoryUsagePlanner(
        rules=(
            StaticMemoryRule(
                MemoryUsageDecision(
                    use_memory=True,
                    memory_ids=("UNKNOWN",),
                )
            ),
        )
    )
    with pytest.raises(MemoryUsagePlanningError):
        invalid.plan(_runtime_with_memory(), ("DOMAIN_ACTION",))


def test_capability_planner_selects_unique_registered_skill() -> None:
    _, skills, workflows, _ = _registries()

    result = CapabilityPlanner(
        skill_registry=skills,
        workflow_registry=workflows,
    ).plan(
        ("DOMAIN_ACTION",),
        build_runtime_context(),
        build_policy_decision(),
    )

    assert result.selected_skills == ("DOMAIN_SKILL",)
    assert result.bindings[0].skill_id == "DOMAIN_SKILL"


def test_capability_planner_fails_on_ambiguous_or_policy_blocked_skills() -> None:
    _, skills, workflows, _ = _registries()
    skills.register(
        SkillDefinition(
            skill_id="DOMAIN_SKILL_2",
            version="1.0.0",
            supported_actions=["DOMAIN_ACTION"],
        )
    )

    with pytest.raises(CapabilityPlanningError):
        CapabilityPlanner(
            skill_registry=skills,
            workflow_registry=workflows,
        ).plan(
            ("DOMAIN_ACTION",),
            build_runtime_context(),
            build_policy_decision(),
        )

    clean_skills = SkillRegistry()
    clean_skills.register(
        SkillDefinition(
            skill_id="DOMAIN_SKILL",
            version="1.0.0",
            supported_actions=["DOMAIN_ACTION"],
        )
    )
    policy = build_policy_decision().model_copy(
        update={"forbidden_skills": ["DOMAIN_SKILL"]}
    )
    with pytest.raises(CapabilityPlanningError):
        CapabilityPlanner(
            skill_registry=clean_skills,
            workflow_registry=workflows,
        ).plan(("DOMAIN_ACTION",), build_runtime_context(), policy)


def test_forced_workflow_from_m2_is_preserved() -> None:
    _, skills, workflows, _ = _registries()
    policy = build_policy_decision().model_copy(
        update={"forced_workflow": "DOMAIN_WORKFLOW"}
    )

    result = CapabilityPlanner(
        skill_registry=skills,
        workflow_registry=workflows,
    ).plan(
        ("DOMAIN_ACTION",),
        build_runtime_context(),
        policy,
    )

    assert result.bindings[0].workflow_id == "DOMAIN_WORKFLOW"
    assert result.selected_workflows == ("DOMAIN_WORKFLOW",)


def test_tool_planner_resolves_required_registered_tool_without_execution() -> None:
    _, skills, workflows, tools = _registries()
    capability = CapabilityPlanner(
        skill_registry=skills,
        workflow_registry=workflows,
    ).plan(
        ("DOMAIN_ACTION",),
        build_runtime_context(),
        build_policy_decision(),
    )

    result = ToolPlanner(
        skill_registry=skills,
        tool_registry=tools,
    ).plan(
        capability,
        build_runtime_context(),
        build_policy_decision(),
    )

    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].tool_id == "DOMAIN_TOOL"
    assert result.tool_calls[0].required is True
    assert result.tool_calls[0].required_by_skills == ("DOMAIN_SKILL",)
    assert result.required_success is True


def test_tool_planner_fails_when_required_tool_is_policy_forbidden() -> None:
    _, skills, workflows, tools = _registries()
    capability = CapabilityPlanner(
        skill_registry=skills,
        workflow_registry=workflows,
    ).plan(
        ("DOMAIN_ACTION",),
        build_runtime_context(),
        build_policy_decision(),
    )
    policy = build_policy_decision().model_copy(
        update={"forbidden_tools": ["DOMAIN_TOOL"]}
    )

    with pytest.raises(ToolPlanningError):
        ToolPlanner(
            skill_registry=skills,
            tool_registry=tools,
        ).plan(capability, build_runtime_context(), policy)


def test_confirmation_combines_action_and_policy_requirements() -> None:
    actions = ActionRegistry()
    actions.register(_action("DOMAIN_ACTION", requires_confirmation=True))

    action_result = ConfirmationPlanner(actions).plan(
        ("DOMAIN_ACTION",),
        build_policy_decision(),
    )
    assert action_result.required is True
    assert action_result.action_ids == ("DOMAIN_ACTION",)
    assert "ACTION_CONFIRMATION_REQUIRED" in action_result.reason_codes

    policy = build_policy_decision().model_copy(
        update={"confirmation_required": True}
    )
    policy_result = ConfirmationPlanner(actions).plan(
        ("DOMAIN_ACTION",),
        policy,
    )
    assert "POLICY_CONFIRMATION_REQUIRED" in policy_result.reason_codes


def test_sequence_planner_builds_ordered_dependencies_without_execution() -> None:
    actions, skills, workflows, tools = _registries()
    actions.register(_action("DOMAIN_ACTION_2"))
    capability = CapabilityPlanner(
        skill_registry=skills,
        workflow_registry=workflows,
    ).plan(
        ("DOMAIN_ACTION", "DOMAIN_ACTION_2"),
        build_runtime_context(),
        build_policy_decision(),
    )
    tool_plan = ToolPlanner(
        skill_registry=skills,
        tool_registry=tools,
    ).plan(
        capability,
        build_runtime_context(),
        build_policy_decision(),
    )

    sequence = SequencePlanner().plan(
        ("DOMAIN_ACTION", "DOMAIN_ACTION_2"),
        capability,
        tool_plan,
    )

    assert [step.action for step in sequence.steps] == [
        "DOMAIN_ACTION",
        "DOMAIN_ACTION_2",
    ]
    assert sequence.steps[0].depends_on is None
    assert sequence.steps[1].depends_on == ["step-1"]
    assert sequence.steps[0].tool_requirement == "DOMAIN_TOOL"


def test_fallback_defaults_fail_closed_and_validates_injected_actions() -> None:
    actions, _, _, _ = _registries()

    default = FallbackPlanner(action_registry=actions).plan(
        (),
        capability_selection=CapabilityPlanner(
            skill_registry=SkillRegistry(),
            workflow_registry=WorkflowRegistry(),
        ).plan((), build_runtime_context(), build_policy_decision()),
        tool_plan=ToolPlanner(
            skill_registry=SkillRegistry(),
            tool_registry=ToolRegistry(),
        ).plan(
            CapabilityPlanner(
                skill_registry=SkillRegistry(),
                workflow_registry=WorkflowRegistry(),
            ).plan((), build_runtime_context(), build_policy_decision()),
            build_runtime_context(),
            build_policy_decision(),
        ),
        policy_decision=build_policy_decision(),
    )
    assert default.mode == "FAIL_CLOSED"
    assert default.allowed_actions == ()

    planner = FallbackPlanner(
        action_registry=actions,
        rules=(
            StaticFallbackRule(
                FallbackDecision(
                    mode="DOMAIN_FALLBACK_MODE",
                    allowed_actions=("DOMAIN_FALLBACK",),
                    reason_codes=("DOMAIN_REASON",),
                )
            ),
        ),
    )
    empty_capability = CapabilityPlanner(
        skill_registry=SkillRegistry(),
        workflow_registry=WorkflowRegistry(),
    ).plan((), build_runtime_context(), build_policy_decision())
    empty_tool = ToolPlanner(
        skill_registry=SkillRegistry(),
        tool_registry=ToolRegistry(),
    ).plan(empty_capability, build_runtime_context(), build_policy_decision())

    result = planner.plan(
        (),
        empty_capability,
        empty_tool,
        build_policy_decision(),
    )
    assert result.allowed_actions == ("DOMAIN_FALLBACK",)

    policy = build_policy_decision().model_copy(
        update={"forbidden_actions": ["DOMAIN_FALLBACK"]}
    )
    with pytest.raises(Exception):
        planner.plan((), empty_capability, empty_tool, policy)


def test_execution_preplanner_composes_iu5_without_execution_or_approval() -> None:
    actions, skills, workflows, tools = _registries()
    preplanner = ExecutionPreplanner(
        memory_planner=MemoryUsagePlanner(),
        capability_planner=CapabilityPlanner(
            skill_registry=skills,
            workflow_registry=workflows,
        ),
        tool_planner=ToolPlanner(
            skill_registry=skills,
            tool_registry=tools,
        ),
        confirmation_planner=ConfirmationPlanner(actions),
        sequence_planner=SequencePlanner(),
        fallback_planner=FallbackPlanner(action_registry=actions),
    )

    result = preplanner.plan(
        selected_action_ids=("DOMAIN_ACTION",),
        runtime_context=_runtime_with_memory(),
        policy_decision=build_policy_decision(),
        goal_completion_conditions=("DOMAIN_DONE", "DOMAIN_DONE"),
    )

    assert result.memory_usage.use_memory is False
    assert result.capability_selection.selected_skills == ("DOMAIN_SKILL",)
    assert result.tool_plan.tool_calls[0].tool_id == "DOMAIN_TOOL"
    assert result.sequence.steps[0].action == "DOMAIN_ACTION"
    assert result.stop_conditions == ("DOMAIN_DONE",)
    assert result.fallback.mode == "FAIL_CLOSED"


def test_execution_preplanner_fails_before_planning_when_m2_blocks() -> None:
    actions, skills, workflows, tools = _registries()
    preplanner = ExecutionPreplanner(
        memory_planner=MemoryUsagePlanner(),
        capability_planner=CapabilityPlanner(
            skill_registry=skills,
            workflow_registry=workflows,
        ),
        tool_planner=ToolPlanner(
            skill_registry=skills,
            tool_registry=tools,
        ),
        confirmation_planner=ConfirmationPlanner(actions),
        sequence_planner=SequencePlanner(),
        fallback_planner=FallbackPlanner(action_registry=actions),
    )
    policy = build_policy_decision().model_copy(
        update={"allowed": False, "blocked": True}
    )

    with pytest.raises(PlanningBlockedByPolicyError):
        preplanner.plan(
            selected_action_ids=("DOMAIN_ACTION",),
            runtime_context=build_runtime_context(),
            policy_decision=policy,
        )
