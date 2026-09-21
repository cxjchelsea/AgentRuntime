"""M5-IU3 approved capability projection and exact runtime resolution.

This module resolves only capability references already frozen in ApprovedActionPlan.
It does not select, substitute, invoke, retry, or validate business outputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from runtime.contracts import ApprovedActionPlan
from runtime.contracts.enums import RuntimeControlState
from runtime.contracts.execution import ExecutionContext
from runtime.contracts.planning import ActionStep
from runtime.execution.authority import project_workflow_authority
from runtime.execution.errors import (
    ExecutionCapabilityDisabledError,
    ExecutionCapabilityNotFoundError,
    ExecutionImplementationMissingError,
    ExecutionImplementationTypeError,
    ExecutionRegistryResolutionError,
)
from runtime.execution.permission import (
    ExecutionPermissionContextProvider,
    ExecutionPermissionEvaluator,
    PermissionDecisionStatus,
)
from runtime.execution.protocols import (
    SkillImplementation,
    ToolImplementation,
    WorkflowImplementation,
)
from runtime.execution.resolution import (
    ExecutionImplementationResolver,
    ResolvedExecutionImplementation,
)
from runtime.registries.definitions import (
    SkillDefinition,
    ToolDefinition,
    WorkflowDefinition,
)


class CapabilityKind(str, Enum):
    SKILL = "SKILL"
    WORKFLOW = "WORKFLOW"
    TOOL = "TOOL"


class CapabilityReferenceSource(str, Enum):
    STEP_SKILL = "STEP_SKILL"
    STEP_WORKFLOW = "STEP_WORKFLOW"
    APPROVED_TOOL_PLAN = "APPROVED_TOOL_PLAN"
    STEP_TOOL_PROJECTION = "STEP_TOOL_PROJECTION"


class CapabilityResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    NO_EXTERNAL_CAPABILITY = "NO_EXTERNAL_CAPABILITY"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ApprovedCapabilityReference:
    kind: CapabilityKind
    capability_id: str
    version: str
    source: CapabilityReferenceSource

    def __post_init__(self) -> None:
        if not self.capability_id.strip() or not self.version.strip():
            raise ValueError("approved capability id/version must not be blank")


@dataclass(frozen=True, slots=True)
class ApprovedStepCapabilityReferences:
    step_id: str
    skill: ApprovedCapabilityReference | None = None
    workflow: ApprovedCapabilityReference | None = None
    tools: tuple[ApprovedCapabilityReference, ...] = ()

    def __post_init__(self) -> None:
        if not self.step_id.strip():
            raise ValueError("step_id must not be blank")

    @property
    def has_external_capability(self) -> bool:
        return self.skill is not None or self.workflow is not None or bool(self.tools)


CapabilityDefinition = SkillDefinition | WorkflowDefinition | ToolDefinition
CapabilityImplementation = (
    SkillImplementation | WorkflowImplementation | ToolImplementation
)
ResolvedImplementation = (
    ResolvedExecutionImplementation[SkillDefinition, SkillImplementation]
    | ResolvedExecutionImplementation[WorkflowDefinition, WorkflowImplementation]
    | ResolvedExecutionImplementation[ToolDefinition, ToolImplementation]
)


@dataclass(frozen=True, slots=True)
class ResolvedCapability:
    kind: CapabilityKind
    capability_id: str
    version: str
    definition: CapabilityDefinition
    implementation_ref: CapabilityImplementation
    source: CapabilityReferenceSource


@dataclass(frozen=True, slots=True)
class ResolvedStepCapabilities:
    step_id: str
    skill: ResolvedCapability | None = None
    workflow: ResolvedCapability | None = None
    tools: tuple[ResolvedCapability, ...] = ()

    def __post_init__(self) -> None:
        if not self.step_id.strip():
            raise ValueError("step_id must not be blank")

    @property
    def has_external_capability(self) -> bool:
        return self.skill is not None or self.workflow is not None or bool(self.tools)


@dataclass(frozen=True, slots=True)
class CapabilityResolutionDecision:
    status: CapabilityResolutionStatus
    reason_codes: tuple[str, ...]
    resolved: ResolvedStepCapabilities | None = None

    def __post_init__(self) -> None:
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        if self.status in {
            CapabilityResolutionStatus.RESOLVED,
            CapabilityResolutionStatus.NO_EXTERNAL_CAPABILITY,
        }:
            if self.resolved is None:
                raise ValueError("successful resolution status requires resolved payload")
        elif self.resolved is not None:
            raise ValueError("blocked/unknown resolution cannot expose partial payload")


class ApprovedCapabilityProjectionError(RuntimeError):
    """ApprovedPlan capability subplans are missing or internally inconsistent."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class ApprovedStepCapabilityProjector:
    """Project exact capability authority for one approved step."""

    def project(
        self,
        *,
        approved_plan: ApprovedActionPlan,
        step: ActionStep,
    ) -> ApprovedStepCapabilityReferences:
        self._validate_step_identity(approved_plan, step)
        binding = self._capability_binding(approved_plan, step)

        skill_ref: ApprovedCapabilityReference | None = None
        workflow_ref: ApprovedCapabilityReference | None = None

        if binding is not None:
            skill_ref = self._binding_reference(
                binding,
                id_field="skill_id",
                version_field="skill_version",
                expected_id=step.skill_id,
                kind=CapabilityKind.SKILL,
                source=CapabilityReferenceSource.STEP_SKILL,
            )
            workflow_ref = self._binding_reference(
                binding,
                id_field="workflow_id",
                version_field="workflow_version",
                expected_id=step.workflow_id,
                kind=CapabilityKind.WORKFLOW,
                source=CapabilityReferenceSource.STEP_WORKFLOW,
            )
        elif step.skill_id is not None or step.workflow_id is not None:
            raise ApprovedCapabilityProjectionError(
                "APPROVED_CAPABILITY_PLAN_INCONSISTENT",
                "step capability reference has no approved capability binding",
            )

        tool_refs = self._tool_references(approved_plan, step)

        return ApprovedStepCapabilityReferences(
            step_id=step.step_id,
            skill=skill_ref,
            workflow=workflow_ref,
            tools=tool_refs,
        )

    @staticmethod
    def _validate_step_identity(
        approved_plan: ApprovedActionPlan,
        step: ActionStep,
    ) -> None:
        matches = [
            approved_step
            for approved_step in approved_plan.steps
            if approved_step.step_id == step.step_id
        ]
        if len(matches) != 1 or matches[0] != step:
            raise ApprovedCapabilityProjectionError(
                "APPROVED_STEP_MISMATCH",
                "step is not the exact ApprovedActionPlan step",
            )

    @staticmethod
    def _capability_binding(
        approved_plan: ApprovedActionPlan,
        step: ActionStep,
    ) -> dict[str, object] | None:
        capability_plan = approved_plan.capability_plan
        if capability_plan is None:
            return None

        bindings = capability_plan.get("bindings")
        if not isinstance(bindings, list):
            raise ApprovedCapabilityProjectionError(
                "APPROVED_CAPABILITY_PLAN_INCONSISTENT",
                "approved capability_plan.bindings must be a list",
            )

        matches: list[dict[str, object]] = []
        for item in bindings:
            if not isinstance(item, dict):
                raise ApprovedCapabilityProjectionError(
                    "APPROVED_CAPABILITY_PLAN_INCONSISTENT",
                    "approved capability binding must be an object",
                )
            if item.get("action_id") == step.action:
                matches.append(item)

        if len(matches) != 1:
            raise ApprovedCapabilityProjectionError(
                "APPROVED_CAPABILITY_PLAN_INCONSISTENT",
                "approved step must have exactly one capability binding",
            )
        return matches[0]

    @staticmethod
    def _binding_reference(
        binding: dict[str, object],
        *,
        id_field: str,
        version_field: str,
        expected_id: str | None,
        kind: CapabilityKind,
        source: CapabilityReferenceSource,
    ) -> ApprovedCapabilityReference | None:
        capability_id = binding.get(id_field)
        version = binding.get(version_field)

        if expected_id is None:
            if capability_id is not None or version is not None:
                raise ApprovedCapabilityProjectionError(
                    "APPROVED_CAPABILITY_PLAN_INCONSISTENT",
                    "approved capability binding does not match ActionStep",
                )
            return None

        if capability_id != expected_id:
            raise ApprovedCapabilityProjectionError(
                "APPROVED_CAPABILITY_PLAN_INCONSISTENT",
                "approved capability binding id does not match ActionStep",
            )
        if not isinstance(version, str) or not version.strip():
            raise ApprovedCapabilityProjectionError(
                "CAPABILITY_VERSION_UNPINNED",
                "approved capability reference has no pinned version",
            )
        return ApprovedCapabilityReference(
            kind=kind,
            capability_id=expected_id,
            version=version,
            source=source,
        )

    @staticmethod
    def _tool_references(
        approved_plan: ApprovedActionPlan,
        step: ActionStep,
    ) -> tuple[ApprovedCapabilityReference, ...]:
        tool_plan = approved_plan.tool_plan
        if tool_plan is None:
            if step.tool_requirement is not None or step.skill_id is not None:
                raise ApprovedCapabilityProjectionError(
                    "APPROVED_TOOL_PLAN_INCONSISTENT",
                    "approved executable capability requires an explicit tool_plan",
                )
            return ()

        calls = tool_plan.get("tool_calls")
        if not isinstance(calls, list):
            raise ApprovedCapabilityProjectionError(
                "APPROVED_TOOL_PLAN_INCONSISTENT",
                "approved tool_plan.tool_calls must be a list",
            )

        selected: dict[str, ApprovedCapabilityReference] = {}
        direct_requirement_found = step.tool_requirement is None

        for call in calls:
            if not isinstance(call, dict):
                raise ApprovedCapabilityProjectionError(
                    "APPROVED_TOOL_PLAN_INCONSISTENT",
                    "approved tool call must be an object",
                )
            tool_id = call.get("tool_id")
            tool_version = call.get("tool_version")
            required_by = call.get("required_by_skills", [])

            if not isinstance(tool_id, str) or not tool_id.strip():
                raise ApprovedCapabilityProjectionError(
                    "APPROVED_TOOL_PLAN_INCONSISTENT",
                    "approved tool call requires non-blank tool_id",
                )
            if not isinstance(required_by, list) or any(
                not isinstance(skill_id, str) or not skill_id.strip()
                for skill_id in required_by
            ):
                raise ApprovedCapabilityProjectionError(
                    "APPROVED_TOOL_PLAN_INCONSISTENT",
                    "approved tool required_by_skills must be a string list",
                )

            selected_by_skill = (
                step.skill_id is not None and step.skill_id in required_by
            )
            selected_by_step = step.tool_requirement == tool_id
            if not selected_by_skill and not selected_by_step:
                continue

            if not isinstance(tool_version, str) or not tool_version.strip():
                raise ApprovedCapabilityProjectionError(
                    "CAPABILITY_VERSION_UNPINNED",
                    "approved Tool reference has no pinned version",
                )

            source = (
                CapabilityReferenceSource.APPROVED_TOOL_PLAN
                if selected_by_skill
                else CapabilityReferenceSource.STEP_TOOL_PROJECTION
            )
            reference = ApprovedCapabilityReference(
                kind=CapabilityKind.TOOL,
                capability_id=tool_id,
                version=tool_version,
                source=source,
            )
            existing = selected.get(tool_id)
            if existing is not None and existing.version != reference.version:
                raise ApprovedCapabilityProjectionError(
                    "APPROVED_TOOL_PLAN_INCONSISTENT",
                    "one approved Tool id resolves to conflicting versions",
                )
            selected[tool_id] = reference

            if selected_by_step:
                direct_requirement_found = True

        if not direct_requirement_found:
            raise ApprovedCapabilityProjectionError(
                "APPROVED_TOOL_PLAN_INCONSISTENT",
                "ActionStep.tool_requirement is absent from approved tool_plan",
            )

        return tuple(selected.values())


class StepCapabilityResolver:
    """Resolve and gate one already-approved step without replanning."""

    def __init__(
        self,
        *,
        implementation_resolver: ExecutionImplementationResolver,
        permission_context_provider: ExecutionPermissionContextProvider,
        permission_evaluator: ExecutionPermissionEvaluator,
        projector: ApprovedStepCapabilityProjector | None = None,
    ) -> None:
        self._implementation_resolver = implementation_resolver
        self._permission_context_provider = permission_context_provider
        self._permission_evaluator = permission_evaluator
        self._projector = projector or ApprovedStepCapabilityProjector()

    async def resolve(
        self,
        *,
        approved_plan: ApprovedActionPlan,
        step: ActionStep,
        execution_context: ExecutionContext,
        current_state: RuntimeControlState | None,
    ) -> CapabilityResolutionDecision:
        try:
            references = self._projector.project(
                approved_plan=approved_plan,
                step=step,
            )
        except ApprovedCapabilityProjectionError as exc:
            return self._blocked(exc.reason_code)

        if not references.has_external_capability:
            return CapabilityResolutionDecision(
                status=CapabilityResolutionStatus.NO_EXTERNAL_CAPABILITY,
                reason_codes=("NO_EXTERNAL_CAPABILITY",),
                resolved=ResolvedStepCapabilities(step_id=step.step_id),
            )

        if references.workflow is not None:
            try:
                authority = project_workflow_authority(approved_plan)
            except (TypeError, ValueError):
                return self._blocked("WORKFLOW_AUTHORITY_INVALID")
            if (
                references.workflow.capability_id
                not in authority.approved_workflow_ids
            ):
                return self._blocked("WORKFLOW_AUTHORITY_INVALID")

        resolved_skill: ResolvedCapability | None = None
        resolved_workflow: ResolvedCapability | None = None
        resolved_tools: list[ResolvedCapability] = []

        if references.skill is not None:
            resolved = self._resolve_reference(references.skill)
            if isinstance(resolved, CapabilityResolutionDecision):
                return resolved
            resolved_skill = resolved
            state_decision = self._check_state(
                resolved.definition,
                current_state=current_state,
            )
            if state_decision is not None:
                return state_decision

        if references.workflow is not None:
            resolved = self._resolve_reference(references.workflow)
            if isinstance(resolved, CapabilityResolutionDecision):
                return resolved
            resolved_workflow = resolved
            state_decision = self._check_state(
                resolved.definition,
                current_state=current_state,
            )
            if state_decision is not None:
                return state_decision

        for reference in references.tools:
            resolved = self._resolve_reference(reference)
            if isinstance(resolved, CapabilityResolutionDecision):
                return resolved
            resolved_tools.append(resolved)

        if resolved_tools:
            try:
                permission_context = await self._permission_context_provider.build(
                    execution_context
                )
            except Exception:
                return self._unknown("TOOL_PERMISSION_UNKNOWN")

            if (
                permission_context.execution_id != execution_context.execution_id
                or permission_context.identity_scope
                != execution_context.identity_scope
            ):
                return self._unknown("TOOL_PERMISSION_UNKNOWN")

            for tool in resolved_tools:
                if not isinstance(tool.definition, ToolDefinition):
                    return self._blocked("IMPLEMENTATION_PROTOCOL_INVALID")
                try:
                    permission = self._permission_evaluator.evaluate(
                        tool.definition,
                        permission_context,
                    )
                except Exception:
                    return self._unknown("TOOL_PERMISSION_UNKNOWN")

                if permission.status is PermissionDecisionStatus.DENIED:
                    return self._blocked("TOOL_PERMISSION_DENIED")
                if permission.status is PermissionDecisionStatus.UNKNOWN:
                    return self._unknown("TOOL_PERMISSION_UNKNOWN")

        return CapabilityResolutionDecision(
            status=CapabilityResolutionStatus.RESOLVED,
            reason_codes=("CAPABILITIES_RESOLVED",),
            resolved=ResolvedStepCapabilities(
                step_id=step.step_id,
                skill=resolved_skill,
                workflow=resolved_workflow,
                tools=tuple(resolved_tools),
            ),
        )

    def _resolve_reference(
        self,
        reference: ApprovedCapabilityReference,
    ) -> ResolvedCapability | CapabilityResolutionDecision:
        try:
            resolved: ResolvedImplementation
            if reference.kind is CapabilityKind.SKILL:
                resolved = self._implementation_resolver.resolve_skill(
                    reference.capability_id,
                    reference.version,
                )
            elif reference.kind is CapabilityKind.WORKFLOW:
                resolved = self._implementation_resolver.resolve_workflow(
                    reference.capability_id,
                    reference.version,
                )
            else:
                resolved = self._implementation_resolver.resolve_tool(
                    reference.capability_id,
                    reference.version,
                )
        except ExecutionCapabilityNotFoundError:
            return self._blocked("CAPABILITY_NOT_FOUND")
        except ExecutionCapabilityDisabledError:
            return self._blocked("CAPABILITY_DISABLED")
        except ExecutionImplementationMissingError:
            return self._blocked("IMPLEMENTATION_REF_MISSING")
        except ExecutionImplementationTypeError:
            return self._blocked("IMPLEMENTATION_PROTOCOL_INVALID")
        except ExecutionRegistryResolutionError:
            return self._blocked("CAPABILITY_NOT_FOUND")

        return ResolvedCapability(
            kind=reference.kind,
            capability_id=reference.capability_id,
            version=reference.version,
            definition=resolved.definition,
            implementation_ref=resolved.implementation_ref,
            source=reference.source,
        )

    @staticmethod
    def _check_state(
        definition: CapabilityDefinition,
        *,
        current_state: RuntimeControlState | None,
    ) -> CapabilityResolutionDecision | None:
        if isinstance(definition, ToolDefinition):
            return None

        allowed_states = definition.allowed_states
        if not allowed_states:
            return None
        if current_state is None:
            return StepCapabilityResolver._unknown("CAPABILITY_STATE_UNKNOWN")
        if current_state.value not in allowed_states:
            return StepCapabilityResolver._blocked(
                "CAPABILITY_STATE_INELIGIBLE"
            )
        return None

    @staticmethod
    def _blocked(reason_code: str) -> CapabilityResolutionDecision:
        return CapabilityResolutionDecision(
            status=CapabilityResolutionStatus.BLOCKED,
            reason_codes=(reason_code,),
        )

    @staticmethod
    def _unknown(reason_code: str) -> CapabilityResolutionDecision:
        return CapabilityResolutionDecision(
            status=CapabilityResolutionStatus.UNKNOWN,
            reason_codes=(reason_code,),
        )
