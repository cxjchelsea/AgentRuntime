"""M4-IU3 legal action candidate generation.

Candidate generation is constrained by registered Action definitions, M2 PolicyDecision,
available capability IDs, planning mode, and injected eligibility rules. It never
executes an action.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from runtime.contracts import PolicyDecision, RuntimeContext, UnderstandingState
from runtime.contracts.enums import PlanningMode
from runtime.planning.errors import (
    ActionRegistryAmbiguityError,
    CandidateEligibilityError,
    InvalidActionCandidateError,
    PlanningBlockedByPolicyError,
    StrategyRegistryAmbiguityError,
)
from runtime.planning.goals import GoalResolutionResult
from runtime.registries import ActionDefinition, ActionRegistry, IntrusivenessLevel
from runtime.registries.strategy import StrategyRegistry


@dataclass(frozen=True, slots=True)
class PlanningActionCandidate:
    """Frozen M4 candidate shape plus provenance used internally."""

    action: str
    goal_fit: float | None
    need_fit: float | None
    context_fit: float | None
    policy_allowed: bool
    intrusiveness: IntrusivenessLevel
    repetition_penalty: float | None
    confidence: float | None
    source_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.action.strip():
            raise InvalidActionCandidateError("candidate action must not be blank")
        for field_name in (
            "goal_fit",
            "need_fit",
            "context_fit",
            "repetition_penalty",
            "confidence",
        ):
            value = getattr(self, field_name)
            if value is not None and not 0.0 <= value <= 1.0:
                raise InvalidActionCandidateError(f"{field_name} must be within [0, 1]")
        if not self.source_codes or any(not item.strip() for item in self.source_codes):
            raise InvalidActionCandidateError(
                "candidate source_codes must contain non-blank values"
            )


@dataclass(frozen=True, slots=True)
class CandidateContribution:
    """Injected/source contribution before registry/policy filtering."""

    action: str
    source_code: str
    goal_fit: float | None = None
    need_fit: float | None = None
    context_fit: float | None = None
    repetition_penalty: float | None = None
    confidence: float | None = None

    def __post_init__(self) -> None:
        if not self.action.strip() or not self.source_code.strip():
            raise InvalidActionCandidateError(
                "candidate contribution action/source_code must not be blank"
            )
        for field_name in (
            "goal_fit",
            "need_fit",
            "context_fit",
            "repetition_penalty",
            "confidence",
        ):
            value = getattr(self, field_name)
            if value is not None and not 0.0 <= value <= 1.0:
                raise InvalidActionCandidateError(f"{field_name} must be within [0, 1]")


class ActionCandidateProvider(Protocol):
    """Domain-injected source for goal/task/capability-compatible action candidates."""

    def collect(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        goals: GoalResolutionResult,
        policy_decision: PolicyDecision,
    ) -> tuple[CandidateContribution, ...]:
        """Return candidate contributions without authorizing or executing them."""


class CandidateEligibilityRule(Protocol):
    """Injected state/domain compatibility filter."""

    def is_eligible(
        self,
        action: ActionDefinition,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        goals: GoalResolutionResult,
    ) -> bool:
        """Return whether the registered action is compatible with current facts."""


class LegalActionCandidateBuilder:
    """Build the legal candidate action space before any soft strategy selection."""

    def __init__(
        self,
        *,
        action_registry: ActionRegistry,
        strategy_registry: StrategyRegistry,
        providers: tuple[ActionCandidateProvider, ...] = (),
        eligibility_rules: tuple[CandidateEligibilityRule, ...] = (),
    ) -> None:
        self._action_registry = action_registry
        self._strategy_registry = strategy_registry
        self._providers = providers
        self._eligibility_rules = eligibility_rules

    def build(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        goals: GoalResolutionResult,
        policy_decision: PolicyDecision,
        *,
        planning_mode: PlanningMode,
        available_capability_ids: frozenset[str],
    ) -> tuple[PlanningActionCandidate, ...]:
        if policy_decision.blocked or not policy_decision.allowed:
            raise PlanningBlockedByPolicyError(
                "M4 cannot generate candidates when M2 PolicyDecision blocks planning"
            )

        definitions = self._enabled_action_definitions()

        contributions: list[CandidateContribution] = []
        contributions.extend(self._from_policy_forced(policy_decision))
        contributions.extend(self._from_m3(understanding_state))
        contributions.extend(self._from_strategy_defaults())

        for provider in self._providers:
            try:
                contributions.extend(
                    provider.collect(
                        runtime_context,
                        understanding_state,
                        goals,
                        policy_decision,
                    )
                )
            except Exception as exc:
                if isinstance(exc, InvalidActionCandidateError):
                    raise
                raise InvalidActionCandidateError(
                    "action candidate provider execution failed"
                ) from exc

        merged: dict[str, PlanningActionCandidate] = {}
        order: list[str] = []
        for contribution in contributions:
            definition = definitions.get(contribution.action)
            if definition is None:
                raise InvalidActionCandidateError(
                    "candidate references an unregistered or disabled action"
                )
            if planning_mode not in definition.allowed_planning_modes:
                continue
            if not self._allowed_by_policy(contribution.action, policy_decision):
                continue
            if (
                definition.required_capability is not None
                and definition.required_capability not in available_capability_ids
            ):
                continue
            if not self._eligible(
                definition,
                runtime_context,
                understanding_state,
                goals,
            ):
                continue

            current = PlanningActionCandidate(
                action=contribution.action,
                goal_fit=contribution.goal_fit,
                need_fit=contribution.need_fit,
                context_fit=contribution.context_fit,
                policy_allowed=True,
                intrusiveness=definition.intrusiveness_level,
                repetition_penalty=contribution.repetition_penalty,
                confidence=contribution.confidence,
                source_codes=(contribution.source_code,),
            )
            existing = merged.get(current.action)
            if existing is None:
                merged[current.action] = current
                order.append(current.action)
            else:
                merged[current.action] = self._merge(existing, current)

        return tuple(merged[action_id] for action_id in order)

    def _enabled_action_definitions(self) -> dict[str, ActionDefinition]:
        output: dict[str, ActionDefinition] = {}
        for record in self._action_registry.list():
            definition = record.definition
            if not record.enabled or not definition.enabled:
                continue
            if definition.action_id in output:
                raise ActionRegistryAmbiguityError(
                    "multiple enabled versions exist for one action_id"
                )
            output[definition.action_id] = definition
        return output

    @staticmethod
    def _from_policy_forced(
        policy_decision: PolicyDecision,
    ) -> tuple[CandidateContribution, ...]:
        forced_action = policy_decision.forced_action
        if forced_action is None:
            return ()
        if not forced_action.strip():
            raise InvalidActionCandidateError(
                "PolicyDecision.forced_action must not be blank"
            )
        return (
            CandidateContribution(
                action=forced_action,
                source_code="POLICY_FORCED_ACTION",
                goal_fit=1.0,
                confidence=1.0,
            ),
        )

    def _from_strategy_defaults(self) -> tuple[CandidateContribution, ...]:
        output: list[CandidateContribution] = []
        seen_strategy_ids: set[str] = set()
        for record in self._strategy_registry.list():
            definition = record.definition
            if not record.enabled or not definition.enabled:
                continue
            if definition.strategy_id in seen_strategy_ids:
                raise StrategyRegistryAmbiguityError(
                    "multiple enabled versions exist for one strategy_id"
                )
            seen_strategy_ids.add(definition.strategy_id)
            output.extend(
                CandidateContribution(
                    action=action_id,
                    source_code=f"STRATEGY_DEFAULT:{definition.strategy_id}",
                )
                for action_id in definition.default_actions
            )
        return tuple(output)

    @staticmethod
    def _from_m3(
        understanding_state: UnderstandingState,
    ) -> tuple[CandidateContribution, ...]:
        output: list[CandidateContribution] = []
        for payload in understanding_state.candidate_actions or ():
            action = payload.get("action")
            confidence = payload.get("confidence")
            if not isinstance(action, str) or not action.strip():
                raise InvalidActionCandidateError(
                    "M3 candidate action must contain a non-blank action"
                )
            if confidence is not None and (
                not isinstance(confidence, (int, float))
                or isinstance(confidence, bool)
                or not 0.0 <= float(confidence) <= 1.0
            ):
                raise InvalidActionCandidateError(
                    "M3 candidate action confidence must be within [0, 1]"
                )
            output.append(
                CandidateContribution(
                    action=action,
                    source_code="M3_CANDIDATE",
                    confidence=float(confidence) if confidence is not None else None,
                )
            )
        return tuple(output)

    def _eligible(
        self,
        definition: ActionDefinition,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        goals: GoalResolutionResult,
    ) -> bool:
        for rule in self._eligibility_rules:
            try:
                if not rule.is_eligible(
                    definition,
                    runtime_context,
                    understanding_state,
                    goals,
                ):
                    return False
            except Exception as exc:
                raise CandidateEligibilityError(
                    "candidate eligibility rule execution failed"
                ) from exc
        return True

    @staticmethod
    def _allowed_by_policy(
        action_id: str,
        policy_decision: PolicyDecision,
    ) -> bool:
        if action_id in (policy_decision.forbidden_actions or ()):
            return False
        if policy_decision.allowed_actions is None:
            return True
        return action_id in policy_decision.allowed_actions

    @staticmethod
    def _merge(
        left: PlanningActionCandidate,
        right: PlanningActionCandidate,
    ) -> PlanningActionCandidate:
        return replace(
            left,
            goal_fit=LegalActionCandidateBuilder._max_optional(
                left.goal_fit, right.goal_fit
            ),
            need_fit=LegalActionCandidateBuilder._max_optional(
                left.need_fit, right.need_fit
            ),
            context_fit=LegalActionCandidateBuilder._max_optional(
                left.context_fit, right.context_fit
            ),
            repetition_penalty=LegalActionCandidateBuilder._max_optional(
                left.repetition_penalty, right.repetition_penalty
            ),
            confidence=LegalActionCandidateBuilder._max_optional(
                left.confidence, right.confidence
            ),
            source_codes=tuple(
                dict.fromkeys((*left.source_codes, *right.source_codes))
            ),
        )

    @staticmethod
    def _max_optional(left: float | None, right: float | None) -> float | None:
        values = [value for value in (left, right) if value is not None]
        return max(values) if values else None
