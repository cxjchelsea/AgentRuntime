"""M4-IU5 execution preplanning.

This module converts already-legal M4 action choices into memory/capability/tool/
confirmation/sequence/fallback planning objects. It never executes a Skill, Workflow,
Tool, writes Memory, or approves an ActionPlan.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from runtime.contracts import PolicyDecision, RuntimeContext
from runtime.contracts.planning import ActionStep
from runtime.planning.errors import (
    CapabilityPlanningError,
    ConfirmationPlanningError,
    FallbackPlanningError,
    MemoryUsagePlanningError,
    PlanningBlockedByPolicyError,
    SequencePlanningError,
    ToolPlanningError,
)
from runtime.registries import (
    ActionDefinition,
    ActionRegistry,
    SkillDefinition,
    SkillRegistry,
    ToolDefinition,
    ToolRegistry,
    WorkflowDefinition,
    WorkflowRegistry,
)


@dataclass(frozen=True, slots=True)
class MemoryUsageDecision:
    """Internal typed projection for ActionPlanDraft.memory_usage."""

    use_memory: bool
    memory_ids: tuple[str, ...] = ()
    usage_mode: str | None = None
    reason: str | None = None
    risk: str | None = None


class MemoryUsageRule(Protocol):
    """Injected rule for how already-retrieved user memory may be used."""

    def decide(
        self,
        runtime_context: RuntimeContext,
        selected_action_ids: tuple[str, ...],
    ) -> MemoryUsageDecision | None:
        """Return a decision or None. This never reads/writes persistent Memory."""


class MemoryUsagePlanner:
    """Plan use of M1-provided MemoryContext without creating new memories."""

    def __init__(self, rules: tuple[MemoryUsageRule, ...] = ()) -> None:
        self._rules = rules

    def plan(
        self,
        runtime_context: RuntimeContext,
        selected_action_ids: tuple[str, ...],
    ) -> MemoryUsageDecision:
        decisions: list[MemoryUsageDecision] = []
        for rule in self._rules:
            try:
                decision = rule.decide(runtime_context, selected_action_ids)
            except Exception as exc:
                if isinstance(exc, MemoryUsagePlanningError):
                    raise
                raise MemoryUsagePlanningError(
                    "memory usage rule execution failed"
                ) from exc
            if decision is not None:
                decisions.append(decision)

        if not decisions:
            return MemoryUsageDecision(
                use_memory=False,
                reason="NO_MEMORY_USAGE_RULE",
            )

        first = decisions[0]
        if any(decision != first for decision in decisions[1:]):
            raise MemoryUsagePlanningError(
                "memory usage rules produced conflicting decisions"
            )
        self._validate(first, runtime_context)
        return first

    @staticmethod
    def _validate(
        decision: MemoryUsageDecision,
        runtime_context: RuntimeContext,
    ) -> None:
        if not decision.use_memory:
            if decision.memory_ids:
                raise MemoryUsagePlanningError(
                    "use_memory=false cannot carry memory_ids"
                )
            return

        if not decision.memory_ids:
            raise MemoryUsagePlanningError(
                "use_memory=true requires explicit memory_ids"
            )

        memory_context = runtime_context.memory_context
        if memory_context is None or not memory_context.retrieved_memories:
            raise MemoryUsagePlanningError(
                "memory usage may reference only memories already present in RuntimeContext"
            )

        available_ids: set[str] = set()
        for item in memory_context.retrieved_memories:
            memory_id = item.get("memory_id")
            if isinstance(memory_id, str) and memory_id.strip():
                available_ids.add(memory_id)

        if not set(decision.memory_ids) <= available_ids:
            raise MemoryUsagePlanningError(
                "memory usage references memory not present in RuntimeContext"
            )


@dataclass(frozen=True, slots=True)
class CapabilityBinding:
    """One action's selected execution capability references."""

    action_id: str
    skill_id: str | None = None
    skill_version: str | None = None
    workflow_id: str | None = None
    workflow_version: str | None = None


class CapabilityBindingRule(Protocol):
    """Injected resolver when Registry metadata is insufficient/ambiguous."""

    def bind(
        self,
        action_id: str,
        runtime_context: RuntimeContext,
        policy_decision: PolicyDecision,
    ) -> CapabilityBinding | None:
        """Return a legal registered binding or None."""


@dataclass(frozen=True, slots=True)
class CapabilitySelection:
    """Internal typed projection for ActionPlanDraft.capability_plan."""

    bindings: tuple[CapabilityBinding, ...]
    selected_skills: tuple[str, ...]
    selected_workflows: tuple[str, ...]


class CapabilityPlanner:
    """Map legal actions to enabled Skill/Workflow definitions without execution."""

    def __init__(
        self,
        *,
        skill_registry: SkillRegistry,
        workflow_registry: WorkflowRegistry,
        binding_rules: tuple[CapabilityBindingRule, ...] = (),
    ) -> None:
        self._skill_registry = skill_registry
        self._workflow_registry = workflow_registry
        self._binding_rules = binding_rules

    def plan(
        self,
        selected_action_ids: tuple[str, ...],
        runtime_context: RuntimeContext,
        policy_decision: PolicyDecision,
    ) -> CapabilitySelection:
        if not selected_action_ids:
            return CapabilitySelection(
                bindings=(),
                selected_skills=(),
                selected_workflows=(),
            )

        skills = self._enabled_skills()
        workflows = self._enabled_workflows()

        bindings: list[CapabilityBinding] = []
        for action_id in selected_action_ids:
            rule_bindings = self._rule_bindings(
                action_id,
                runtime_context,
                policy_decision,
            )
            if rule_bindings:
                unique = tuple(dict.fromkeys(rule_bindings))
                if len(unique) != 1:
                    raise CapabilityPlanningError(
                        "capability binding rules produced conflicting bindings"
                    )
                binding = unique[0]
                self._validate_binding(binding, skills, workflows, policy_decision)
                bindings.append(
                    self._pin_binding_versions(binding, skills, workflows)
                )
                continue

            supporting_skills = tuple(
                definition.skill_id
                for definition in skills.values()
                if action_id in (definition.supported_actions or ())
            )
            matching_skills = tuple(
                skill_id
                for skill_id in supporting_skills
                if self._skill_allowed(skill_id, policy_decision)
            )
            if supporting_skills and not matching_skills:
                raise CapabilityPlanningError(
                    "all registered skills for selected action are disallowed by policy"
                )
            if len(matching_skills) > 1:
                raise CapabilityPlanningError(
                    "multiple enabled skills support one action; binding rule required"
                )
            selected_skill_id = matching_skills[0] if matching_skills else None
            bindings.append(
                CapabilityBinding(
                    action_id=action_id,
                    skill_id=selected_skill_id,
                    skill_version=(
                        skills[selected_skill_id].version
                        if selected_skill_id is not None
                        else None
                    ),
                )
            )

        if policy_decision.forced_workflow is not None:
            forced_workflow = policy_decision.forced_workflow
            if forced_workflow not in workflows:
                raise CapabilityPlanningError(
                    "M2 forced workflow is unavailable in WorkflowRegistry"
                )
            if not bindings:
                raise CapabilityPlanningError(
                    "M2 forced workflow requires at least one selected action"
                )
            first = bindings[0]
            if first.workflow_id is not None and first.workflow_id != forced_workflow:
                raise CapabilityPlanningError(
                    "selected workflow conflicts with M2 forced workflow"
                )
            bindings[0] = CapabilityBinding(
                action_id=first.action_id,
                skill_id=first.skill_id,
                skill_version=first.skill_version,
                workflow_id=forced_workflow,
                workflow_version=workflows[forced_workflow].version,
            )

        selected_skills = tuple(
            dict.fromkeys(
                binding.skill_id for binding in bindings if binding.skill_id is not None
            )
        )
        selected_workflows = tuple(
            dict.fromkeys(
                binding.workflow_id
                for binding in bindings
                if binding.workflow_id is not None
            )
        )
        return CapabilitySelection(
            bindings=tuple(bindings),
            selected_skills=selected_skills,
            selected_workflows=selected_workflows,
        )

    def _rule_bindings(
        self,
        action_id: str,
        runtime_context: RuntimeContext,
        policy_decision: PolicyDecision,
    ) -> list[CapabilityBinding]:
        output: list[CapabilityBinding] = []
        for rule in self._binding_rules:
            try:
                binding = rule.bind(
                    action_id,
                    runtime_context,
                    policy_decision,
                )
            except Exception as exc:
                if isinstance(exc, CapabilityPlanningError):
                    raise
                raise CapabilityPlanningError(
                    "capability binding rule execution failed"
                ) from exc
            if binding is not None:
                if binding.action_id != action_id:
                    raise CapabilityPlanningError(
                        "capability binding changed the selected action"
                    )
                output.append(binding)
        return output

    def _enabled_skills(self) -> dict[str, SkillDefinition]:
        output: dict[str, SkillDefinition] = {}
        for record in self._skill_registry.list():
            definition = record.definition
            if not record.enabled or not definition.enabled:
                continue
            if definition.skill_id in output:
                raise CapabilityPlanningError(
                    "multiple enabled versions exist for one skill_id"
                )
            output[definition.skill_id] = definition
        return output

    def _enabled_workflows(self) -> dict[str, WorkflowDefinition]:
        output: dict[str, WorkflowDefinition] = {}
        for record in self._workflow_registry.list():
            definition = record.definition
            if not record.enabled or not definition.enabled:
                continue
            if definition.workflow_id in output:
                raise CapabilityPlanningError(
                    "multiple enabled versions exist for one workflow_id"
                )
            output[definition.workflow_id] = definition
        return output

    def _validate_binding(
        self,
        binding: CapabilityBinding,
        skills: dict[str, SkillDefinition],
        workflows: dict[str, WorkflowDefinition],
        policy_decision: PolicyDecision,
    ) -> None:
        if binding.skill_id is not None:
            definition = skills.get(binding.skill_id)
            if definition is None:
                raise CapabilityPlanningError("binding references unavailable skill")
            if binding.action_id not in (definition.supported_actions or ()):
                raise CapabilityPlanningError(
                    "binding skill does not support selected action"
                )
            if not self._skill_allowed(binding.skill_id, policy_decision):
                raise CapabilityPlanningError(
                    "binding references policy-disallowed skill"
                )

        if binding.skill_id is None and binding.skill_version is not None:
            raise CapabilityPlanningError(
                "binding skill_version requires skill_id"
            )
        if binding.skill_id is not None:
            definition = skills[binding.skill_id]
            if (
                binding.skill_version is not None
                and binding.skill_version != definition.version
            ):
                raise CapabilityPlanningError(
                    "binding skill_version does not match selected Skill definition"
                )

        if binding.workflow_id is not None and binding.workflow_id not in workflows:
            raise CapabilityPlanningError("binding references unavailable workflow")
        if binding.workflow_id is None and binding.workflow_version is not None:
            raise CapabilityPlanningError(
                "binding workflow_version requires workflow_id"
            )
        if binding.workflow_id is not None:
            definition = workflows[binding.workflow_id]
            if (
                binding.workflow_version is not None
                and binding.workflow_version != definition.version
            ):
                raise CapabilityPlanningError(
                    "binding workflow_version does not match selected Workflow definition"
                )

    @staticmethod
    def _pin_binding_versions(
        binding: CapabilityBinding,
        skills: dict[str, SkillDefinition],
        workflows: dict[str, WorkflowDefinition],
    ) -> CapabilityBinding:
        return CapabilityBinding(
            action_id=binding.action_id,
            skill_id=binding.skill_id,
            skill_version=(
                skills[binding.skill_id].version
                if binding.skill_id is not None
                else None
            ),
            workflow_id=binding.workflow_id,
            workflow_version=(
                workflows[binding.workflow_id].version
                if binding.workflow_id is not None
                else None
            ),
        )

    @staticmethod
    def _skill_allowed(skill_id: str, policy_decision: PolicyDecision) -> bool:
        if skill_id in (policy_decision.forbidden_skills or ()):
            return False
        if policy_decision.allowed_skills is None:
            return True
        return skill_id in policy_decision.allowed_skills


@dataclass(frozen=True, slots=True)
class ToolCallPlan:
    """A selected Tool reference; no call is executed."""

    tool_id: str
    required: bool
    required_by_skills: tuple[str, ...]
    timeout_policy: str | None
    retry_policy: str | None
    idempotency_mode: str | None
    side_effect_level: str | None
    tool_version: str | None = None


@dataclass(frozen=True, slots=True)
class ToolPlanDecision:
    """Internal typed projection for ActionPlanDraft.tool_plan."""

    tool_calls: tuple[ToolCallPlan, ...]
    parallelizable: bool
    required_success: bool


class ToolPlanningRule(Protocol):
    """Injected rule for optional tools/parallelization semantics."""

    def select_optional_tools(
        self,
        capability_selection: CapabilitySelection,
        runtime_context: RuntimeContext,
    ) -> tuple[str, ...]:
        """Return optional tool IDs to include in the plan."""


class ToolPlanner:
    """Resolve registered Tool requirements from selected skills."""

    def __init__(
        self,
        *,
        skill_registry: SkillRegistry,
        tool_registry: ToolRegistry,
        rules: tuple[ToolPlanningRule, ...] = (),
    ) -> None:
        self._skill_registry = skill_registry
        self._tool_registry = tool_registry
        self._rules = rules

    def plan(
        self,
        capability_selection: CapabilitySelection,
        runtime_context: RuntimeContext,
        policy_decision: PolicyDecision,
    ) -> ToolPlanDecision:
        skills = self._enabled_skills()
        tools = self._enabled_tools()

        required: list[str] = []
        required_by: dict[str, list[str]] = {}
        optional_available: set[str] = set()
        for skill_id in capability_selection.selected_skills:
            skill = skills.get(skill_id)
            if skill is None:
                raise ToolPlanningError("selected skill became unavailable")
            for tool_id in skill.required_tools or ():
                required.append(tool_id)
                required_by.setdefault(tool_id, []).append(skill_id)
            optional_available.update(skill.optional_tools or ())

        selected_optional: list[str] = []
        for rule in self._rules:
            try:
                chosen = rule.select_optional_tools(
                    capability_selection,
                    runtime_context,
                )
            except Exception as exc:
                if isinstance(exc, ToolPlanningError):
                    raise
                raise ToolPlanningError("tool planning rule execution failed") from exc
            for tool_id in chosen:
                if tool_id not in optional_available:
                    raise ToolPlanningError(
                        "tool planning rule selected non-optional tool"
                    )
                selected_optional.append(tool_id)

        tool_ids = tuple(dict.fromkeys((*required, *selected_optional)))
        calls: list[ToolCallPlan] = []
        required_set = set(required)
        for tool_id in tool_ids:
            definition = tools.get(tool_id)
            if definition is None:
                raise ToolPlanningError(
                    "planned tool is unregistered, disabled, or version-ambiguous"
                )
            if not self._tool_allowed(tool_id, policy_decision):
                raise ToolPlanningError(
                    "planned tool is disallowed by M2 PolicyDecision"
                )
            calls.append(
                ToolCallPlan(
                    tool_id=tool_id,
                    tool_version=definition.version,
                    required=tool_id in required_set,
                    required_by_skills=tuple(
                        dict.fromkeys(required_by.get(tool_id, []))
                    ),
                    timeout_policy=definition.timeout_policy,
                    retry_policy=definition.retry_policy,
                    idempotency_mode=definition.idempotency_mode,
                    side_effect_level=definition.side_effect_level,
                )
            )

        return ToolPlanDecision(
            tool_calls=tuple(calls),
            parallelizable=False,
            required_success=bool(required_set),
        )

    def _enabled_skills(self) -> dict[str, SkillDefinition]:
        output: dict[str, SkillDefinition] = {}
        for record in self._skill_registry.list():
            definition = record.definition
            if not record.enabled or not definition.enabled:
                continue
            if definition.skill_id in output:
                raise ToolPlanningError(
                    "multiple enabled versions exist for one skill_id"
                )
            output[definition.skill_id] = definition
        return output

    def _enabled_tools(self) -> dict[str, ToolDefinition]:
        output: dict[str, ToolDefinition] = {}
        for record in self._tool_registry.list():
            definition = record.definition
            if not record.enabled or not definition.enabled:
                continue
            if definition.tool_id in output:
                raise ToolPlanningError(
                    "multiple enabled versions exist for one tool_id"
                )
            output[definition.tool_id] = definition
        return output

    @staticmethod
    def _tool_allowed(tool_id: str, policy_decision: PolicyDecision) -> bool:
        if tool_id in (policy_decision.forbidden_tools or ()):
            return False
        if policy_decision.allowed_tools is None:
            return True
        return tool_id in policy_decision.allowed_tools


@dataclass(frozen=True, slots=True)
class ConfirmationDecision:
    """Internal projection for ActionPlanDraft.confirmation_plan."""

    required: bool
    action_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]


class ConfirmationPlanner:
    """Combine M2 and ActionDefinition confirmation requirements."""

    def __init__(self, action_registry: ActionRegistry) -> None:
        self._action_registry = action_registry

    def plan(
        self,
        selected_action_ids: tuple[str, ...],
        policy_decision: PolicyDecision,
    ) -> ConfirmationDecision:
        actions = self._enabled_actions()
        required_actions: list[str] = []
        for action_id in selected_action_ids:
            definition = actions.get(action_id)
            if definition is None:
                raise ConfirmationPlanningError(
                    "selected action is unavailable during confirmation planning"
                )
            if definition.requires_confirmation:
                required_actions.append(action_id)

        reasons: list[str] = []
        if policy_decision.confirmation_required:
            reasons.append("POLICY_CONFIRMATION_REQUIRED")
        if required_actions:
            reasons.append("ACTION_CONFIRMATION_REQUIRED")

        if policy_decision.confirmation_required and not selected_action_ids:
            raise ConfirmationPlanningError(
                "policy requires confirmation but no selected action exists"
            )

        return ConfirmationDecision(
            required=bool(reasons),
            action_ids=tuple(required_actions)
            if required_actions
            else (selected_action_ids if policy_decision.confirmation_required else ()),
            reason_codes=tuple(reasons),
        )

    def _enabled_actions(self) -> dict[str, ActionDefinition]:
        output: dict[str, ActionDefinition] = {}
        for record in self._action_registry.list():
            definition = record.definition
            if not record.enabled or not definition.enabled:
                continue
            if definition.action_id in output:
                raise ConfirmationPlanningError(
                    "multiple enabled versions exist for one action_id"
                )
            output[definition.action_id] = definition
        return output


class SequenceDependencyRule(Protocol):
    """Injected rule for explicit action dependencies."""

    def dependencies_for(
        self,
        action_id: str,
        prior_action_ids: tuple[str, ...],
    ) -> tuple[str, ...] | None:
        """Return action IDs this action depends on, or None for default sequencing."""


@dataclass(frozen=True, slots=True)
class SequencePlan:
    """Internal action-sequence result."""

    steps: tuple[ActionStep, ...]


class SequencePlanner:
    """Build ordered ActionSteps without executing them."""

    def __init__(
        self,
        rules: tuple[SequenceDependencyRule, ...] = (),
    ) -> None:
        self._rules = rules

    def plan(
        self,
        selected_action_ids: tuple[str, ...],
        capability_selection: CapabilitySelection,
        tool_plan: ToolPlanDecision,
    ) -> SequencePlan:
        if len(set(selected_action_ids)) != len(selected_action_ids):
            raise SequencePlanningError("selected actions must not contain duplicates")

        bindings = {
            binding.action_id: binding for binding in capability_selection.bindings
        }
        if set(bindings) != set(selected_action_ids):
            raise SequencePlanningError(
                "capability bindings must cover exactly the selected actions"
            )

        step_ids_by_action: dict[str, str] = {}
        steps: list[ActionStep] = []
        for index, action_id in enumerate(selected_action_ids, start=1):
            step_id = f"step-{index}"
            dependencies = self._dependencies(
                action_id,
                tuple(selected_action_ids[: index - 1]),
                step_ids_by_action,
            )
            binding = bindings[action_id]

            required_tools = tuple(
                call.tool_id
                for call in tool_plan.tool_calls
                if call.required
                and binding.skill_id is not None
                and binding.skill_id in call.required_by_skills
            )
            tool_requirement = required_tools[0] if len(required_tools) == 1 else None

            steps.append(
                ActionStep(
                    step_id=step_id,
                    action=action_id,
                    skill_id=binding.skill_id,
                    workflow_id=binding.workflow_id,
                    tool_requirement=tool_requirement,
                    depends_on=list(dependencies) or None,
                )
            )
            step_ids_by_action[action_id] = step_id

        return SequencePlan(steps=tuple(steps))

    def _dependencies(
        self,
        action_id: str,
        prior_action_ids: tuple[str, ...],
        step_ids_by_action: dict[str, str],
    ) -> tuple[str, ...]:
        explicit: list[tuple[str, ...]] = []
        for rule in self._rules:
            try:
                dependencies = rule.dependencies_for(action_id, prior_action_ids)
            except Exception as exc:
                if isinstance(exc, SequencePlanningError):
                    raise
                raise SequencePlanningError(
                    "sequence dependency rule execution failed"
                ) from exc
            if dependencies is not None:
                explicit.append(dependencies)

        if explicit:
            first = explicit[0]
            if any(value != first for value in explicit[1:]):
                raise SequencePlanningError(
                    "sequence rules produced conflicting dependencies"
                )
            if not set(first) <= set(prior_action_ids):
                raise SequencePlanningError(
                    "action dependency must reference a prior selected action"
                )
            return tuple(step_ids_by_action[item] for item in first)

        if not prior_action_ids:
            return ()
        return (step_ids_by_action[prior_action_ids[-1]],)


@dataclass(frozen=True, slots=True)
class FallbackDecision:
    """Internal projection for ActionPlanDraft.fallback_plan."""

    mode: str
    allowed_actions: tuple[str, ...]
    reason_codes: tuple[str, ...]


class FallbackRule(Protocol):
    """Injected Domain/config fallback decision."""

    def plan(
        self,
        selected_action_ids: tuple[str, ...],
        capability_selection: CapabilitySelection,
        tool_plan: ToolPlanDecision,
    ) -> FallbackDecision | None:
        """Return a fallback decision or None."""


class FallbackPlanner:
    """Plan fallback behavior without using model knowledge as hidden truth."""

    def __init__(
        self,
        *,
        action_registry: ActionRegistry,
        rules: tuple[FallbackRule, ...] = (),
    ) -> None:
        self._action_registry = action_registry
        self._rules = rules

    def plan(
        self,
        selected_action_ids: tuple[str, ...],
        capability_selection: CapabilitySelection,
        tool_plan: ToolPlanDecision,
        policy_decision: PolicyDecision,
    ) -> FallbackDecision:
        decisions: list[FallbackDecision] = []
        for rule in self._rules:
            try:
                decision = rule.plan(
                    selected_action_ids,
                    capability_selection,
                    tool_plan,
                )
            except Exception as exc:
                if isinstance(exc, FallbackPlanningError):
                    raise
                raise FallbackPlanningError("fallback rule execution failed") from exc
            if decision is not None:
                decisions.append(decision)

        if not decisions:
            return FallbackDecision(
                mode="FAIL_CLOSED",
                allowed_actions=(),
                reason_codes=("NO_FALLBACK_RULE",),
            )

        first = decisions[0]
        if any(decision != first for decision in decisions[1:]):
            raise FallbackPlanningError("fallback rules produced conflicting decisions")
        if not first.mode.strip():
            raise FallbackPlanningError("fallback mode must not be blank")
        if any(not action.strip() for action in first.allowed_actions):
            raise FallbackPlanningError(
                "fallback actions must be non-blank registered action IDs"
            )

        available_actions = self._enabled_actions()
        for action_id in first.allowed_actions:
            if action_id not in available_actions:
                raise FallbackPlanningError(
                    "fallback action is unregistered, disabled, or version-ambiguous"
                )
            if action_id in (policy_decision.forbidden_actions or ()):
                raise FallbackPlanningError(
                    "fallback action is forbidden by M2 PolicyDecision"
                )
            if (
                policy_decision.allowed_actions is not None
                and action_id not in policy_decision.allowed_actions
            ):
                raise FallbackPlanningError(
                    "fallback action is outside M2 allowed_actions"
                )
        return first

    def _enabled_actions(self) -> dict[str, ActionDefinition]:
        output: dict[str, ActionDefinition] = {}
        for record in self._action_registry.list():
            definition = record.definition
            if not record.enabled or not definition.enabled:
                continue
            if definition.action_id in output:
                raise FallbackPlanningError(
                    "multiple enabled versions exist for one fallback action_id"
                )
            output[definition.action_id] = definition
        return output


@dataclass(frozen=True, slots=True)
class ExecutionPreplanningResult:
    """M4-IU5 typed result for later ActionPlanDraft assembly."""

    memory_usage: MemoryUsageDecision
    capability_selection: CapabilitySelection
    tool_plan: ToolPlanDecision
    confirmation: ConfirmationDecision
    sequence: SequencePlan
    stop_conditions: tuple[str, ...]
    fallback: FallbackDecision


class ExecutionPreplanner:
    """Compose M4 steps 11-16 without execution or plan approval."""

    def __init__(
        self,
        *,
        memory_planner: MemoryUsagePlanner,
        capability_planner: CapabilityPlanner,
        tool_planner: ToolPlanner,
        confirmation_planner: ConfirmationPlanner,
        sequence_planner: SequencePlanner,
        fallback_planner: FallbackPlanner,
    ) -> None:
        self._memory_planner = memory_planner
        self._capability_planner = capability_planner
        self._tool_planner = tool_planner
        self._confirmation_planner = confirmation_planner
        self._sequence_planner = sequence_planner
        self._fallback_planner = fallback_planner

    def plan(
        self,
        *,
        selected_action_ids: tuple[str, ...],
        runtime_context: RuntimeContext,
        policy_decision: PolicyDecision,
        goal_completion_conditions: tuple[str, ...] = (),
    ) -> ExecutionPreplanningResult:
        if policy_decision.blocked or not policy_decision.allowed:
            raise PlanningBlockedByPolicyError(
                "M4-IU5 cannot preplan execution when M2 blocks planning"
            )

        memory_usage = self._memory_planner.plan(
            runtime_context,
            selected_action_ids,
        )
        capability_selection = self._capability_planner.plan(
            selected_action_ids,
            runtime_context,
            policy_decision,
        )
        tool_plan = self._tool_planner.plan(
            capability_selection,
            runtime_context,
            policy_decision,
        )
        confirmation = self._confirmation_planner.plan(
            selected_action_ids,
            policy_decision,
        )
        sequence = self._sequence_planner.plan(
            selected_action_ids,
            capability_selection,
            tool_plan,
        )
        fallback = self._fallback_planner.plan(
            selected_action_ids,
            capability_selection,
            tool_plan,
            policy_decision,
        )
        return ExecutionPreplanningResult(
            memory_usage=memory_usage,
            capability_selection=capability_selection,
            tool_plan=tool_plan,
            confirmation=confirmation,
            sequence=sequence,
            stop_conditions=tuple(
                dict.fromkeys(
                    condition
                    for condition in goal_completion_conditions
                    if condition.strip()
                )
            ),
            fallback=fallback,
        )
