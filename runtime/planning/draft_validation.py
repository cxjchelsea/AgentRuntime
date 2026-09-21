"""M4-IU6 ActionPlanDraft assembly and validation.

This module is the first place where prior M4 planning outputs are projected into the
Canonical ActionPlanDraft. It validates structure and current registry/capability
references only. It does not approve the plan; M2 PolicyRechecker remains IU7.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from runtime.contracts import ActionPlanDraft, QualityAssessment
from runtime.contracts.enums import PlanApprovalStatus, PlanningMode, RetrievalMode
from runtime.contracts.planning import PlanningGoal
from runtime.planning.errors import (
    DraftAssemblyError,
    PlanValidationError,
    ResponseStrategyPlanningError,
)
from runtime.planning.execution_preplanning import ExecutionPreplanningResult
from runtime.planning.goals import GoalResolutionResult
from runtime.planning.knowledge_planning import (
    KnowledgeCapabilityContext,
    KnowledgePlanningResult,
)
from runtime.planning.strategy_selection import StrategySelectionResult
from runtime.registries import (
    ActionRegistry,
    RegistryItemNotFoundError,
    SkillRegistry,
    StrategyRegistry,
    ToolRegistry,
    WorkflowRegistry,
)


@dataclass(frozen=True, slots=True)
class ResponseStrategyDecision:
    """Internal typed projection for ActionPlanDraft.response_strategy."""

    communicative_goal: str | None = None
    tone: str | None = None
    length: str | None = None
    question_mode: str | None = None
    memory_reference_mode: str | None = None
    content_order: tuple[str, ...] = ()


class ResponseStrategyRule(Protocol):
    """Injected Domain/config rule for M4 response-strategy planning."""

    def plan(
        self,
        strategy: StrategySelectionResult,
        execution_preplanning: ExecutionPreplanningResult,
        knowledge_planning: KnowledgePlanningResult,
    ) -> ResponseStrategyDecision | None:
        """Return a response-strategy decision or None."""


class ResponseStrategyBuilder:
    """Build response strategy without generating user-visible text."""

    def __init__(self, rules: tuple[ResponseStrategyRule, ...] = ()) -> None:
        self._rules = rules

    def build(
        self,
        strategy: StrategySelectionResult,
        execution_preplanning: ExecutionPreplanningResult,
        knowledge_planning: KnowledgePlanningResult,
    ) -> ResponseStrategyDecision | None:
        decisions: list[ResponseStrategyDecision] = []
        for rule in self._rules:
            try:
                decision = rule.plan(
                    strategy,
                    execution_preplanning,
                    knowledge_planning,
                )
            except Exception as exc:
                if isinstance(exc, ResponseStrategyPlanningError):
                    raise
                raise ResponseStrategyPlanningError(
                    "response strategy rule execution failed"
                ) from exc
            if decision is not None:
                decisions.append(decision)

        if not decisions:
            return None

        first = decisions[0]
        if any(decision != first for decision in decisions[1:]):
            raise ResponseStrategyPlanningError(
                "response strategy rules produced conflicting decisions"
            )
        self._validate(first)
        return first

    @staticmethod
    def _validate(decision: ResponseStrategyDecision) -> None:
        for field_name in (
            "communicative_goal",
            "tone",
            "length",
            "question_mode",
            "memory_reference_mode",
        ):
            value = getattr(decision, field_name)
            if value is not None and not value.strip():
                raise ResponseStrategyPlanningError(
                    f"{field_name} must not be blank when present"
                )
        if any(not item.strip() for item in decision.content_order):
            raise ResponseStrategyPlanningError(
                "content_order values must be non-blank"
            )


class ActionPlanDraftAssembler:
    """Project IU2-IU5 typed results into Canonical ActionPlanDraft."""

    def build(
        self,
        *,
        plan_id: str,
        request_id: str,
        planning_mode: PlanningMode,
        goals: GoalResolutionResult,
        strategy: StrategySelectionResult,
        knowledge_planning: KnowledgePlanningResult,
        execution_preplanning: ExecutionPreplanningResult,
        response_strategy: ResponseStrategyDecision | None,
        quality: QualityAssessment | None = None,
        state_intent: dict[str, Any] | None = None,
        trace: dict[str, Any] | None = None,
    ) -> ActionPlanDraft:
        if not plan_id.strip() or not request_id.strip():
            raise DraftAssemblyError("plan_id and request_id must not be blank")
        if goals.primary_goal is None:
            raise DraftAssemblyError("ActionPlanDraft requires a primary goal")

        all_goals = (goals.primary_goal, *goals.secondary_goals)
        if len({goal.goal_id for goal in all_goals}) != len(all_goals):
            raise DraftAssemblyError("planning goals must have unique goal_id values")

        step_actions = tuple(
            step.action for step in execution_preplanning.sequence.steps
        )
        if strategy.selected_action_ids != step_actions:
            raise DraftAssemblyError(
                "strategy selected_action_ids must exactly match planned step actions"
            )

        return ActionPlanDraft(
            plan_id=plan_id,
            request_id=request_id,
            planning_mode=planning_mode,
            goals=list(all_goals),
            steps=list(execution_preplanning.sequence.steps),
            quality=quality or QualityAssessment(),
            strategy=strategy.strategy,
            knowledge_requirement=knowledge_planning.knowledge_requirement,
            retrieval_plan=knowledge_planning.retrieval_plan,
            evidence_requirement=knowledge_planning.evidence_requirement,
            memory_usage=self._memory_usage_dict(execution_preplanning),
            capability_plan=self._capability_plan_dict(execution_preplanning),
            tool_plan=self._tool_plan_dict(execution_preplanning),
            confirmation_plan=self._confirmation_plan_dict(execution_preplanning),
            response_strategy=self._response_strategy_dict(response_strategy),
            state_intent=state_intent,
            stop_conditions=list(execution_preplanning.stop_conditions) or None,
            fallback_plan=self._fallback_plan_dict(execution_preplanning),
            trace=trace,
        )

    @staticmethod
    def _memory_usage_dict(
        preplanning: ExecutionPreplanningResult,
    ) -> dict[str, Any]:
        decision = preplanning.memory_usage
        return {
            "use_memory": decision.use_memory,
            "memory_ids": list(decision.memory_ids),
            "usage_mode": decision.usage_mode,
            "reason": decision.reason,
            "risk": decision.risk,
        }

    @staticmethod
    def _capability_plan_dict(
        preplanning: ExecutionPreplanningResult,
    ) -> dict[str, Any]:
        selection = preplanning.capability_selection
        return {
            "bindings": [
                {
                    "action_id": binding.action_id,
                    "skill_id": binding.skill_id,
                    "skill_version": binding.skill_version,
                    "workflow_id": binding.workflow_id,
                    "workflow_version": binding.workflow_version,
                }
                for binding in selection.bindings
            ],
            "selected_skills": list(selection.selected_skills),
            "selected_workflows": list(selection.selected_workflows),
        }

    @staticmethod
    def _tool_plan_dict(
        preplanning: ExecutionPreplanningResult,
    ) -> dict[str, Any]:
        decision = preplanning.tool_plan
        return {
            "tool_calls": [
                {
                    "tool_id": call.tool_id,
                    "tool_version": call.tool_version,
                    "required": call.required,
                    "required_by_skills": list(call.required_by_skills),
                    "timeout_policy": call.timeout_policy,
                    "retry_policy": call.retry_policy,
                    "idempotency_mode": call.idempotency_mode,
                    "side_effect_level": call.side_effect_level,
                }
                for call in decision.tool_calls
            ],
            "parallelizable": decision.parallelizable,
            "required_success": decision.required_success,
        }

    @staticmethod
    def _confirmation_plan_dict(
        preplanning: ExecutionPreplanningResult,
    ) -> dict[str, Any]:
        decision = preplanning.confirmation
        return {
            "required": decision.required,
            "action_ids": list(decision.action_ids),
            "reason_codes": list(decision.reason_codes),
        }

    @staticmethod
    def _fallback_plan_dict(
        preplanning: ExecutionPreplanningResult,
    ) -> dict[str, Any]:
        decision = preplanning.fallback
        return {
            "mode": decision.mode,
            "allowed_actions": list(decision.allowed_actions),
            "reason_codes": list(decision.reason_codes),
        }

    @staticmethod
    def _response_strategy_dict(
        decision: ResponseStrategyDecision | None,
    ) -> dict[str, Any] | None:
        if decision is None:
            return None
        return {
            "communicative_goal": decision.communicative_goal,
            "tone": decision.tone,
            "length": decision.length,
            "question_mode": decision.question_mode,
            "memory_reference_mode": decision.memory_reference_mode,
            "content_order": list(decision.content_order),
        }


@dataclass(frozen=True, slots=True)
class PlanValidationContext:
    """Current registries/capabilities used to validate Draft references."""

    action_registry: ActionRegistry
    strategy_registry: StrategyRegistry
    skill_registry: SkillRegistry
    workflow_registry: WorkflowRegistry
    tool_registry: ToolRegistry
    knowledge_capabilities: KnowledgeCapabilityContext
    knowledge_skill_ids: frozenset[str] = frozenset()


class PlanValidationRule(Protocol):
    """Injected Domain/config validation beyond generic Core invariants."""

    def validate(
        self,
        draft: ActionPlanDraft,
        context: PlanValidationContext,
    ) -> str | None:
        """Raise PlanValidationError to reject or return an audit code."""


@dataclass(frozen=True, slots=True)
class PlanValidationResult:
    """Successful IU6 validation result. Approval remains false by definition."""

    draft: ActionPlanDraft
    validation_codes: tuple[str, ...]


class PlanValidator:
    """Validate ActionPlanDraft structure and references; never approve it."""

    def __init__(self, rules: tuple[PlanValidationRule, ...] = ()) -> None:
        self._rules = rules

    def validate(
        self,
        draft: ActionPlanDraft,
        context: PlanValidationContext,
    ) -> PlanValidationResult:
        self._validate_identity_and_status(draft)
        self._validate_goals(draft.goals)
        self._validate_strategy(draft, context.strategy_registry)
        self._validate_steps(draft, context)
        self._validate_knowledge(draft, context.knowledge_capabilities)
        self._validate_memory(draft)
        self._validate_capability_plan(draft, context)
        self._validate_tool_plan(draft, context)
        self._validate_confirmation(draft, context.action_registry)
        self._validate_fallback(draft, context.action_registry)
        self._validate_response_strategy(draft)
        self._validate_stop_conditions(draft)

        codes = [
            "DRAFT_STRUCTURE_VALID",
            "REGISTRY_REFERENCES_VALID",
            "KNOWLEDGE_PLAN_VALID",
        ]
        for rule in self._rules:
            try:
                code = rule.validate(draft, context)
            except Exception as exc:
                if isinstance(exc, PlanValidationError):
                    raise
                raise PlanValidationError(
                    "injected plan validation rule execution failed"
                ) from exc
            if code is not None:
                if not code.strip():
                    raise PlanValidationError(
                        "plan validation rule audit code must not be blank"
                    )
                codes.append(code)

        return PlanValidationResult(
            draft=draft,
            validation_codes=tuple(dict.fromkeys(codes)),
        )

    @staticmethod
    def _validate_identity_and_status(draft: ActionPlanDraft) -> None:
        if not draft.plan_id.strip() or not draft.request_id.strip():
            raise PlanValidationError("plan_id/request_id must not be blank")
        if draft.approval_status is not PlanApprovalStatus.DRAFT:
            raise PlanValidationError("IU6 may validate only DRAFT plans")

    @staticmethod
    def _validate_goals(goals: list[PlanningGoal]) -> None:
        if not goals:
            raise PlanValidationError("ActionPlanDraft must contain at least one goal")
        goal_ids = [goal.goal_id for goal in goals]
        if len(set(goal_ids)) != len(goal_ids):
            raise PlanValidationError("goal_id values must be unique")
        primary = [goal for goal in goals if goal.primary is True]
        if len(primary) != 1:
            raise PlanValidationError(
                "ActionPlanDraft must have exactly one primary goal"
            )
        if goals[0].goal_id != primary[0].goal_id:
            raise PlanValidationError("primary goal must be first in goals")

    def _validate_strategy(
        self,
        draft: ActionPlanDraft,
        strategy_registry: StrategyRegistry,
    ) -> None:
        if draft.strategy is None:
            raise PlanValidationError("ActionPlanDraft requires StrategySelection")
        strategies = self._enabled_definitions(
            strategy_registry,
            "strategy_id",
            "Strategy",
        )
        if draft.strategy.strategy_id not in strategies:
            raise PlanValidationError("Draft strategy is unregistered or disabled")

    def _validate_steps(
        self,
        draft: ActionPlanDraft,
        context: PlanValidationContext,
    ) -> None:
        action_defs = self._enabled_definitions(
            context.action_registry,
            "action_id",
            "Action",
        )
        skill_defs = self._enabled_definitions(
            context.skill_registry,
            "skill_id",
            "Skill",
        )
        workflow_defs = self._enabled_definitions(
            context.workflow_registry,
            "workflow_id",
            "Workflow",
        )
        tool_defs = self._enabled_definitions(
            context.tool_registry,
            "tool_id",
            "Tool",
        )

        step_ids = [step.step_id for step in draft.steps]
        if len(set(step_ids)) != len(step_ids):
            raise PlanValidationError("step_id values must be unique")

        seen_steps: set[str] = set()
        for step in draft.steps:
            action_definition = action_defs.get(step.action)
            if action_definition is None:
                raise PlanValidationError(
                    "ActionStep references unregistered or disabled Action"
                )
            if draft.planning_mode not in action_definition.allowed_planning_modes:
                raise PlanValidationError(
                    "ActionStep Action is incompatible with Draft planning_mode"
                )
            if step.skill_id is not None:
                skill = skill_defs.get(step.skill_id)
                if skill is None:
                    raise PlanValidationError("ActionStep references unavailable Skill")
                if step.action not in (skill.supported_actions or ()):
                    raise PlanValidationError(
                        "ActionStep Skill does not support step Action"
                    )
            if step.workflow_id is not None and step.workflow_id not in workflow_defs:
                raise PlanValidationError("ActionStep references unavailable Workflow")
            if (
                step.tool_requirement is not None
                and step.tool_requirement not in tool_defs
            ):
                raise PlanValidationError("ActionStep references unavailable Tool")

            for dependency in step.depends_on or ():
                if dependency not in seen_steps:
                    raise PlanValidationError(
                        "ActionStep dependency must reference an earlier step"
                    )
            seen_steps.add(step.step_id)

        if (
            draft.knowledge_requirement is not None
            and draft.knowledge_requirement.required
        ):
            if not context.knowledge_skill_ids:
                raise PlanValidationError(
                    "required knowledge needs configured knowledge_skill_ids"
                )
            used_skills = {
                step.skill_id for step in draft.steps if step.skill_id is not None
            }
            if not (used_skills & context.knowledge_skill_ids):
                raise PlanValidationError(
                    "required knowledge plan must use a configured knowledge Skill"
                )

    @staticmethod
    def _validate_knowledge(
        draft: ActionPlanDraft,
        capabilities: KnowledgeCapabilityContext,
    ) -> None:
        requirement = draft.knowledge_requirement
        retrieval = draft.retrieval_plan
        evidence = draft.evidence_requirement

        if requirement is None:
            if retrieval is not None or evidence is not None:
                raise PlanValidationError(
                    "Retrieval/Evidence plan cannot exist without KnowledgeRequirement"
                )
            return

        if not requirement.required:
            if retrieval is not None or evidence is not None:
                raise PlanValidationError(
                    "required=false must not carry Retrieval/Evidence plans"
                )
            return

        if retrieval is None or evidence is None:
            raise PlanValidationError(
                "required knowledge needs RetrievalPlan and EvidenceRequirement"
            )
        if not retrieval.required or not evidence.required:
            raise PlanValidationError(
                "required knowledge needs required=true retrieval/evidence plans"
            )
        if requirement.domain is None or retrieval.domain != requirement.domain:
            raise PlanValidationError("knowledge and retrieval domains must match")
        if requirement.domain not in capabilities.available_domains:
            raise PlanValidationError("knowledge domain is unavailable")
        if retrieval.retrieval_mode is None:
            raise PlanValidationError("required RetrievalPlan needs retrieval_mode")
        if retrieval.retrieval_mode is RetrievalMode.NONE:
            raise PlanValidationError(
                "required RetrievalPlan cannot use RetrievalMode.NONE"
            )
        if retrieval.retrieval_mode not in capabilities.supported_retrieval_modes:
            raise PlanValidationError("retrieval mode is unsupported")
        if retrieval.query is None or not retrieval.query.strip():
            raise PlanValidationError("required RetrievalPlan query must not be blank")
        if retrieval.source_policy is not None and (
            retrieval.source_policy not in capabilities.source_policies
        ):
            raise PlanValidationError("retrieval source_policy is unsupported")
        if requirement.freshness_requirement is not None and (
            requirement.freshness_requirement not in capabilities.freshness_capabilities
        ):
            raise PlanValidationError("freshness requirement is unsupported")
        filters = retrieval.filters or {}
        if filters:
            unsupported = set(filters) - capabilities.supported_filters
            if unsupported:
                raise PlanValidationError(
                    "RetrievalPlan contains unsupported metadata filters"
                )

        expected_constraints: dict[str, object | None] = {
            "domain": requirement.domain,
            "population": requirement.population,
            "scenario": requirement.scenario,
            "safety_level": requirement.safety_level,
        }
        for key, value in expected_constraints.items():
            if value is None or key not in capabilities.supported_filters:
                continue
            if filters.get(key) != value:
                raise PlanValidationError(
                    "RetrievalPlan silently changed a KnowledgeRequirement constraint"
                )
        if requirement.source_constraints:
            if "source_constraints" not in capabilities.supported_filters:
                raise PlanValidationError(
                    "source_constraints are unsupported by current capabilities"
                )
            if filters.get("source_constraints") != requirement.source_constraints:
                raise PlanValidationError(
                    "RetrievalPlan silently changed source_constraints"
                )
        if retrieval.freshness_requirement != requirement.freshness_requirement:
            raise PlanValidationError(
                "RetrievalPlan freshness must match KnowledgeRequirement"
            )

        if (
            evidence.minimum_count is not None
            and retrieval.minimum_evidence is not None
            and evidence.minimum_count < retrieval.minimum_evidence
        ):
            raise PlanValidationError(
                "EvidenceRequirement cannot weaken RetrievalPlan.minimum_evidence"
            )

    @staticmethod
    def _validate_memory(draft: ActionPlanDraft) -> None:
        memory = draft.memory_usage
        if memory is None:
            return
        use_memory = memory.get("use_memory")
        memory_ids = memory.get("memory_ids")
        if not isinstance(use_memory, bool):
            raise PlanValidationError("memory_usage.use_memory must be bool")
        if not isinstance(memory_ids, list) or any(
            not isinstance(item, str) or not item.strip() for item in memory_ids
        ):
            raise PlanValidationError("memory_usage.memory_ids must be string list")
        if not use_memory and memory_ids:
            raise PlanValidationError("use_memory=false cannot carry memory_ids")
        if use_memory and not memory_ids:
            raise PlanValidationError("use_memory=true requires memory_ids")

    def _validate_capability_plan(
        self,
        draft: ActionPlanDraft,
        context: PlanValidationContext,
    ) -> None:
        capability = draft.capability_plan
        if capability is None:
            raise PlanValidationError("IU6 Draft requires capability_plan")

        bindings = capability.get("bindings")
        selected_skills = capability.get("selected_skills")
        selected_workflows = capability.get("selected_workflows")
        if not isinstance(bindings, list):
            raise PlanValidationError("capability_plan.bindings must be list")
        if not isinstance(selected_skills, list) or any(
            not isinstance(item, str) for item in selected_skills
        ):
            raise PlanValidationError(
                "capability_plan.selected_skills must be string list"
            )
        if not isinstance(selected_workflows, list) or any(
            not isinstance(item, str) for item in selected_workflows
        ):
            raise PlanValidationError(
                "capability_plan.selected_workflows must be string list"
            )

        actions = {step.action for step in draft.steps}
        bound_actions: set[str] = set()
        skills = self._enabled_definitions(
            context.skill_registry,
            "skill_id",
            "Skill",
        )
        workflows = self._enabled_definitions(
            context.workflow_registry,
            "workflow_id",
            "Workflow",
        )

        for binding in bindings:
            if not isinstance(binding, dict):
                raise PlanValidationError("capability binding must be object")
            action_id = binding.get("action_id")
            skill_id = binding.get("skill_id")
            skill_version = binding.get("skill_version")
            workflow_id = binding.get("workflow_id")
            workflow_version = binding.get("workflow_version")
            if not isinstance(action_id, str) or action_id not in actions:
                raise PlanValidationError(
                    "capability binding must reference a Draft Action"
                )
            if action_id in bound_actions:
                raise PlanValidationError(
                    "Draft Action must have exactly one capability binding"
                )
            bound_actions.add(action_id)

            if skill_id is None:
                if skill_version is not None:
                    raise PlanValidationError(
                        "skill_version requires capability binding skill_id"
                    )
            else:
                if not isinstance(skill_id, str) or skill_id not in skills:
                    raise PlanValidationError(
                        "capability binding references unavailable Skill"
                    )
                if not isinstance(skill_version, str) or not skill_version.strip():
                    raise PlanValidationError(
                        "capability binding requires pinned skill_version"
                    )
                try:
                    skill_record = context.skill_registry.get(skill_id, skill_version)
                except RegistryItemNotFoundError as exc:
                    raise PlanValidationError(
                        "capability binding references unavailable Skill version"
                    ) from exc
                if not skill_record.enabled or not skill_record.definition.enabled:
                    raise PlanValidationError(
                        "capability binding Skill version is disabled"
                    )
                if action_id not in (skill_record.definition.supported_actions or ()):
                    raise PlanValidationError(
                        "capability Skill does not support bound Action"
                    )

            if workflow_id is None:
                if workflow_version is not None:
                    raise PlanValidationError(
                        "workflow_version requires capability binding workflow_id"
                    )
            else:
                if not isinstance(workflow_id, str) or workflow_id not in workflows:
                    raise PlanValidationError(
                        "capability binding references unavailable Workflow"
                    )
                if (
                    not isinstance(workflow_version, str)
                    or not workflow_version.strip()
                ):
                    raise PlanValidationError(
                        "capability binding requires pinned workflow_version"
                    )
                try:
                    workflow_record = context.workflow_registry.get(
                        workflow_id, workflow_version
                    )
                except RegistryItemNotFoundError as exc:
                    raise PlanValidationError(
                        "capability binding references unavailable Workflow version"
                    ) from exc
                if (
                    not workflow_record.enabled
                    or not workflow_record.definition.enabled
                ):
                    raise PlanValidationError(
                        "capability binding Workflow version is disabled"
                    )

        if bound_actions != actions:
            raise PlanValidationError(
                "capability bindings must cover every Draft Action"
            )

        bound_skills = {
            binding.get("skill_id")
            for binding in bindings
            if binding.get("skill_id") is not None
        }
        bound_workflows = {
            binding.get("workflow_id")
            for binding in bindings
            if binding.get("workflow_id") is not None
        }
        if set(selected_skills) != bound_skills:
            raise PlanValidationError(
                "selected_skills must exactly match capability bindings"
            )
        if set(selected_workflows) != bound_workflows:
            raise PlanValidationError(
                "selected_workflows must exactly match capability bindings"
            )

    def _validate_tool_plan(
        self,
        draft: ActionPlanDraft,
        context: PlanValidationContext,
    ) -> None:
        tool_plan = draft.tool_plan
        if tool_plan is None:
            raise PlanValidationError("IU6 Draft requires tool_plan")
        calls = tool_plan.get("tool_calls")
        parallelizable = tool_plan.get("parallelizable")
        required_success = tool_plan.get("required_success")
        if not isinstance(calls, list):
            raise PlanValidationError("tool_plan.tool_calls must be list")
        if not isinstance(parallelizable, bool):
            raise PlanValidationError("tool_plan.parallelizable must be bool")
        if not isinstance(required_success, bool):
            raise PlanValidationError("tool_plan.required_success must be bool")

        tools = self._enabled_definitions(
            context.tool_registry,
            "tool_id",
            "Tool",
        )
        seen: set[str] = set()
        required_by_skill: dict[str, set[str]] = {}
        for call in calls:
            if not isinstance(call, dict):
                raise PlanValidationError("tool call plan must be object")
            tool_id = call.get("tool_id")
            tool_version = call.get("tool_version")
            required = call.get("required")
            if not isinstance(required, bool):
                raise PlanValidationError("tool call required must be bool")
            if not isinstance(tool_id, str) or tool_id not in tools:
                raise PlanValidationError("tool plan references unavailable Tool")
            if not isinstance(tool_version, str) or not tool_version.strip():
                raise PlanValidationError("tool plan requires pinned tool_version")
            try:
                tool_record = context.tool_registry.get(tool_id, tool_version)
            except RegistryItemNotFoundError as exc:
                raise PlanValidationError(
                    "tool plan references unavailable Tool version"
                ) from exc
            if not tool_record.enabled or not tool_record.definition.enabled:
                raise PlanValidationError("tool plan Tool version is disabled")
            if tool_id in seen:
                raise PlanValidationError("tool plan must not duplicate tool_id")
            seen.add(tool_id)

            definition = tool_record.definition
            metadata_pairs = {
                "timeout_policy": definition.timeout_policy,
                "retry_policy": definition.retry_policy,
                "idempotency_mode": definition.idempotency_mode,
                "side_effect_level": definition.side_effect_level,
            }
            for field_name, expected in metadata_pairs.items():
                if call.get(field_name) != expected:
                    raise PlanValidationError(
                        "tool plan metadata does not match ToolRegistry definition"
                    )

            required_by = call.get("required_by_skills")
            if not isinstance(required_by, list) or any(
                not isinstance(item, str) for item in required_by
            ):
                raise PlanValidationError(
                    "tool call required_by_skills must be string list"
                )
            for skill_id in required_by:
                required_by_skill.setdefault(skill_id, set()).add(tool_id)

        capability = draft.capability_plan or {}
        selected_skills = capability.get("selected_skills", [])
        if not set(required_by_skill) <= set(selected_skills):
            raise PlanValidationError(
                "tool required_by_skills references unselected Skill"
            )
        skill_defs = self._enabled_definitions(
            context.skill_registry,
            "skill_id",
            "Skill",
        )
        for skill_id in selected_skills:
            skill = skill_defs[skill_id]
            required_tools = set(skill.required_tools or ())
            if not required_tools <= seen:
                raise PlanValidationError("tool plan omits a Skill required_tool")
            if not required_tools <= required_by_skill.get(skill_id, set()):
                raise PlanValidationError(
                    "tool required_by_skills provenance is incomplete"
                )

    def _validate_confirmation(
        self,
        draft: ActionPlanDraft,
        action_registry: ActionRegistry,
    ) -> None:
        confirmation = draft.confirmation_plan
        if confirmation is None:
            raise PlanValidationError("IU6 Draft requires confirmation_plan")
        required = confirmation.get("required")
        action_ids = confirmation.get("action_ids")
        if not isinstance(required, bool):
            raise PlanValidationError("confirmation.required must be bool")
        if not isinstance(action_ids, list) or any(
            not isinstance(item, str) for item in action_ids
        ):
            raise PlanValidationError("confirmation.action_ids must be string list")
        draft_actions = {step.action for step in draft.steps}
        if not set(action_ids) <= draft_actions:
            raise PlanValidationError("confirmation actions must exist in Draft steps")
        if required and not action_ids:
            raise PlanValidationError(
                "required confirmation must identify at least one action"
            )
        if not required and action_ids:
            raise PlanValidationError(
                "non-required confirmation cannot carry action_ids"
            )

        action_defs = self._enabled_definitions(
            action_registry,
            "action_id",
            "Action",
        )
        required_by_action = {
            action_id
            for action_id in draft_actions
            if action_defs[action_id].requires_confirmation
        }
        if not required_by_action <= set(action_ids):
            raise PlanValidationError(
                "confirmation plan omits Action-required confirmation"
            )

    def _validate_fallback(
        self,
        draft: ActionPlanDraft,
        action_registry: ActionRegistry,
    ) -> None:
        fallback = draft.fallback_plan
        if fallback is None:
            raise PlanValidationError("IU6 Draft requires fallback_plan")
        mode = fallback.get("mode")
        actions = fallback.get("allowed_actions")
        if not isinstance(mode, str) or not mode.strip():
            raise PlanValidationError("fallback mode must be non-blank")
        if not isinstance(actions, list) or any(
            not isinstance(item, str) or not item.strip() for item in actions
        ):
            raise PlanValidationError("fallback.allowed_actions must be string list")

        action_defs = self._enabled_definitions(
            action_registry,
            "action_id",
            "Action",
        )
        if not set(actions) <= set(action_defs):
            raise PlanValidationError(
                "fallback references unregistered or disabled Action"
            )
        for action_id in actions:
            if draft.planning_mode not in action_defs[action_id].allowed_planning_modes:
                raise PlanValidationError(
                    "fallback Action is incompatible with Draft planning_mode"
                )

    @staticmethod
    def _validate_response_strategy(draft: ActionPlanDraft) -> None:
        response_strategy = draft.response_strategy
        if response_strategy is None:
            return
        allowed = {
            "communicative_goal",
            "tone",
            "length",
            "question_mode",
            "memory_reference_mode",
            "content_order",
        }
        if set(response_strategy) - allowed:
            raise PlanValidationError(
                "response_strategy contains unsupported IU6 fields"
            )
        for key in allowed - {"content_order"}:
            value = response_strategy.get(key)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise PlanValidationError(
                    "response_strategy text values must be non-blank strings"
                )
        content_order = response_strategy.get("content_order")
        if not isinstance(content_order, list) or any(
            not isinstance(item, str) or not item.strip() for item in content_order
        ):
            raise PlanValidationError(
                "response_strategy.content_order must be string list"
            )

    @staticmethod
    def _validate_stop_conditions(draft: ActionPlanDraft) -> None:
        if draft.stop_conditions is None:
            return
        if any(
            not isinstance(condition, str) or not condition.strip()
            for condition in draft.stop_conditions
        ):
            raise PlanValidationError("stop_conditions must contain non-blank strings")
        if len(set(draft.stop_conditions)) != len(draft.stop_conditions):
            raise PlanValidationError("stop_conditions must not contain duplicates")

    @staticmethod
    def _enabled_definitions(
        registry: Any,
        id_field: str,
        label: str,
    ) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for record in registry.list():
            definition = record.definition
            if not record.enabled or not definition.enabled:
                continue
            item_id = getattr(definition, id_field)
            if item_id in output:
                raise PlanValidationError(
                    f"multiple enabled versions exist for one {label} id"
                )
            output[item_id] = definition
        return output
