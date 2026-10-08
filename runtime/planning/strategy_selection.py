"""M4-IU3 hybrid strategy selection and soft-selection model boundary.

Hard legality is established before the optional model is called. The model may only
choose among registered, enabled, policy-compatible actions and eligible strategies.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from runtime.contracts import PolicyDecision, RuntimeContext, UnderstandingState
from runtime.contracts.enums import PlanningMode
from runtime.contracts.planning import StrategySelection
from runtime.planning.candidates import PlanningActionCandidate
from runtime.planning.errors import (
    InvalidStrategySelectionError,
    StrategyModelExecutionError,
    StrategyModelOutputError,
    StrategyModelUnavailableError,
    StrategyRegistryAmbiguityError,
    StrategyRuleExecutionError,
)
from runtime.planning.goals import GoalResolutionResult
from runtime.registries import StrategyDefinition, StrategyRegistry


@dataclass(frozen=True, slots=True)
class StrategyRuleChoice:
    """Deterministic injected strategy choice."""

    strategy_id: str
    reason_code: str
    action_ids: tuple[str, ...] = ()
    confidence: float | None = None

    def __post_init__(self) -> None:
        if not self.strategy_id.strip() or not self.reason_code.strip():
            raise InvalidStrategySelectionError(
                "strategy rule choice id/reason must not be blank"
            )
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise InvalidStrategySelectionError(
                "strategy rule confidence must be within [0, 1]"
            )


class StrategySelectionRule(Protocol):
    """Injected deterministic selector for rule-like strategies."""

    def select(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        goals: GoalResolutionResult,
        candidates: tuple[PlanningActionCandidate, ...],
        policy_decision: PolicyDecision,
        legal_strategy_ids: tuple[str, ...],
    ) -> StrategyRuleChoice | None:
        """Choose only from legal IDs or return None."""


class StrategyEligibilityRule(Protocol):
    """Injected evaluator for Domain strategy conditions."""

    def evaluate(
        self,
        strategy: StrategyDefinition,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        goals: GoalResolutionResult,
        candidates: tuple[PlanningActionCandidate, ...],
    ) -> bool | None:
        """True affirms conditions, False rejects, None means no judgment."""


@dataclass(frozen=True, slots=True)
class PlanningUnderstandingSummary:
    """Allow-listed M3 projection for the optional strategy model."""

    intent_ids: tuple[str, ...]
    explicit_goal: str | None
    implicit_need: str | None
    topic: str | None
    needs_clarification: bool | None


@dataclass(frozen=True, slots=True)
class PlanningModelContext:
    """Allow-listed RuntimeContext projection; never exposes whole context."""

    current_runtime_state: str
    active_task_id: str | None
    current_topic: str | None
    recent_agent_action: str | None
    recent_questions_count: int | None


@dataclass(frozen=True, slots=True)
class StrategyModelRequest:
    """Frozen soft-selection input surface."""

    request_id: str
    planning_mode: PlanningMode
    understanding: PlanningUnderstandingSummary
    context: PlanningModelContext
    primary_goal_id: str | None
    candidate_action_ids: tuple[str, ...]
    legal_strategy_ids: tuple[str, ...]
    available_capability_ids: tuple[str, ...]


class StructuredStrategyModel(Protocol):
    """Provider-neutral model boundary for soft strategy selection."""

    async def infer(self, request: StrategyModelRequest) -> Mapping[str, object]:
        """Return structured choice data only; never call tools or generate response."""


@dataclass(frozen=True, slots=True)
class StrategyModelChoice:
    """Validated model choice."""

    strategy_id: str
    action_ids: tuple[str, ...]
    confidence: float | None
    reason_code: str | None


@dataclass(frozen=True, slots=True)
class StrategySelectionResult:
    """Internal IU3 result. StrategySelection remains the Canonical projection."""

    strategy: StrategySelection
    selected_action_ids: tuple[str, ...]
    selection_path: str


class StrategyModelRequestBuilder:
    """Project only the data the strategy model is allowed to see."""

    def build(
        self,
        *,
        planning_mode: PlanningMode,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        goals: GoalResolutionResult,
        candidates: tuple[PlanningActionCandidate, ...],
        legal_strategy_ids: tuple[str, ...],
        available_capability_ids: frozenset[str],
    ) -> StrategyModelRequest:
        conversation = runtime_context.conversation_context
        interaction = runtime_context.interaction_context
        active_task_id = runtime_context.runtime_state_context.active_task_id
        if active_task_id is None and runtime_context.task_context is not None:
            active_task_id = runtime_context.task_context.task_id

        goal = understanding_state.goal
        return StrategyModelRequest(
            request_id=understanding_state.metadata.request_id,
            planning_mode=planning_mode,
            understanding=PlanningUnderstandingSummary(
                intent_ids=tuple(
                    intent.intent_id for intent in understanding_state.intents
                ),
                explicit_goal=goal.explicit_goal if goal is not None else None,
                implicit_need=goal.implicit_need if goal is not None else None,
                topic=understanding_state.topic,
                needs_clarification=understanding_state.uncertainty.needs_clarification,
            ),
            context=PlanningModelContext(
                current_runtime_state=runtime_context.runtime_state_context.current_state.value,
                active_task_id=active_task_id,
                current_topic=(
                    conversation.current_topic if conversation is not None else None
                ),
                recent_agent_action=(
                    interaction.last_agent_action if interaction is not None else None
                ),
                recent_questions_count=(
                    interaction.recent_questions_count
                    if interaction is not None
                    else None
                ),
            ),
            primary_goal_id=(
                goals.primary_goal.goal_id if goals.primary_goal is not None else None
            ),
            candidate_action_ids=tuple(candidate.action for candidate in candidates),
            legal_strategy_ids=legal_strategy_ids,
            available_capability_ids=tuple(sorted(available_capability_ids)),
        )


class StrategyModelOutputValidator:
    """Reject any model output outside the legal-choice surface."""

    _ALLOWED_FIELDS = frozenset(
        {"strategy_id", "action_ids", "confidence", "reason_code"}
    )

    def validate(
        self,
        payload: Mapping[str, object],
        *,
        legal_strategy_ids: frozenset[str],
        legal_action_ids: frozenset[str],
    ) -> StrategyModelChoice:
        extra_fields = set(payload) - self._ALLOWED_FIELDS
        if extra_fields:
            raise StrategyModelOutputError(
                "strategy model output contains unsupported fields"
            )

        strategy_id = payload.get("strategy_id")
        if not isinstance(strategy_id, str) or not strategy_id.strip():
            raise StrategyModelOutputError("strategy_id must be non-blank text")
        if strategy_id not in legal_strategy_ids:
            raise StrategyModelOutputError(
                "strategy model selected an unregistered or ineligible strategy"
            )

        raw_action_ids = payload.get("action_ids", ())
        if not isinstance(raw_action_ids, (list, tuple)) or any(
            not isinstance(item, str) or not item.strip() for item in raw_action_ids
        ):
            raise StrategyModelOutputError(
                "action_ids must be an array of non-blank action IDs"
            )
        action_ids = tuple(raw_action_ids)
        if len(set(action_ids)) != len(action_ids):
            raise StrategyModelOutputError("action_ids must not contain duplicates")
        if not set(action_ids) <= legal_action_ids:
            raise StrategyModelOutputError(
                "strategy model selected an action outside the legal candidate space"
            )

        confidence = payload.get("confidence")
        normalized_confidence: float | None = None
        if confidence is not None:
            if (
                not isinstance(confidence, (int, float))
                or isinstance(confidence, bool)
                or not 0.0 <= float(confidence) <= 1.0
            ):
                raise StrategyModelOutputError(
                    "confidence must be numeric within [0, 1]"
                )
            normalized_confidence = float(confidence)

        reason_code = payload.get("reason_code")
        if reason_code is not None and (
            not isinstance(reason_code, str) or not reason_code.strip()
        ):
            raise StrategyModelOutputError(
                "reason_code must be non-blank text when present"
            )

        return StrategyModelChoice(
            strategy_id=strategy_id,
            action_ids=action_ids,
            confidence=normalized_confidence,
            reason_code=reason_code,
        )


class HybridStrategySelector:
    """Rules first, then optional model soft selection within the legal space."""

    def __init__(
        self,
        *,
        strategy_registry: StrategyRegistry,
        rules: tuple[StrategySelectionRule, ...] = (),
        eligibility_rules: tuple[StrategyEligibilityRule, ...] = (),
        model: StructuredStrategyModel | None = None,
        request_builder: StrategyModelRequestBuilder | None = None,
        output_validator: StrategyModelOutputValidator | None = None,
    ) -> None:
        self._strategy_registry = strategy_registry
        self._rules = rules
        self._eligibility_rules = eligibility_rules
        self._model = model
        self._request_builder = request_builder or StrategyModelRequestBuilder()
        self._output_validator = output_validator or StrategyModelOutputValidator()

    async def select(
        self,
        *,
        planning_mode: PlanningMode,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        goals: GoalResolutionResult,
        candidates: tuple[PlanningActionCandidate, ...],
        policy_decision: PolicyDecision,
        available_capability_ids: frozenset[str],
    ) -> StrategySelectionResult:
        legal_strategies = self._legal_strategies(
            runtime_context,
            understanding_state,
            goals,
            candidates,
        )
        if not legal_strategies:
            raise InvalidStrategySelectionError("no legal strategy is available")

        legal_strategy_ids = tuple(legal_strategies)
        legal_action_ids = frozenset(candidate.action for candidate in candidates)

        rule_choices: list[StrategyRuleChoice] = []
        for rule in self._rules:
            try:
                rule_choice = rule.select(
                    runtime_context,
                    understanding_state,
                    goals,
                    candidates,
                    policy_decision,
                    legal_strategy_ids,
                )
            except Exception as exc:
                if isinstance(exc, InvalidStrategySelectionError):
                    raise
                raise StrategyRuleExecutionError(
                    "strategy selection rule execution failed"
                ) from exc
            if rule_choice is not None:
                self._validate_choice(
                    rule_choice.strategy_id,
                    rule_choice.action_ids,
                    legal_strategy_ids=frozenset(legal_strategy_ids),
                    legal_action_ids=legal_action_ids,
                )
                rule_choices.append(rule_choice)

        if rule_choices:
            first = rule_choices[0]
            if any(
                choice.strategy_id != first.strategy_id
                or choice.action_ids != first.action_ids
                for choice in rule_choices[1:]
            ):
                raise InvalidStrategySelectionError(
                    "deterministic strategy rules produced conflicting choices"
                )
            return StrategySelectionResult(
                strategy=StrategySelection(
                    strategy_id=first.strategy_id,
                    reason_code=first.reason_code,
                    confidence=first.confidence,
                ),
                selected_action_ids=first.action_ids,
                selection_path="RULE",
            )

        if len(legal_strategy_ids) == 1:
            strategy_id = legal_strategy_ids[0]
            return StrategySelectionResult(
                strategy=StrategySelection(
                    strategy_id=strategy_id,
                    reason_code="ONLY_LEGAL_STRATEGY",
                    confidence=None,
                ),
                selected_action_ids=(),
                selection_path="SINGLE_LEGAL",
            )

        if planning_mode is not PlanningMode.AGENT_PLANNED:
            raise InvalidStrategySelectionError(
                "multiple legal strategies require deterministic resolution "
                "outside AGENT_PLANNED mode"
            )
        if self._model is None:
            raise StrategyModelUnavailableError(
                "AGENT_PLANNED strategy selection requires a model when rules "
                "cannot resolve multiple legal strategies"
            )

        request = self._request_builder.build(
            planning_mode=planning_mode,
            runtime_context=runtime_context,
            understanding_state=understanding_state,
            goals=goals,
            candidates=candidates,
            legal_strategy_ids=legal_strategy_ids,
            available_capability_ids=available_capability_ids,
        )
        try:
            payload = await self._model.infer(request)
        except Exception as exc:
            raise StrategyModelExecutionError(
                "strategy model execution failed"
            ) from exc

        # 模型选择与规则选择分变量保存，避免类型收窄冲突
        model_choice = self._output_validator.validate(
            payload,
            legal_strategy_ids=frozenset(legal_strategy_ids),
            legal_action_ids=legal_action_ids,
        )
        return StrategySelectionResult(
            strategy=StrategySelection(
                strategy_id=model_choice.strategy_id,
                reason_code=model_choice.reason_code,
                confidence=model_choice.confidence,
            ),
            selected_action_ids=model_choice.action_ids,
            selection_path="MODEL",
        )

    def _legal_strategies(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        goals: GoalResolutionResult,
        candidates: tuple[PlanningActionCandidate, ...],
    ) -> dict[str, StrategyDefinition]:
        legal_action_ids = {candidate.action for candidate in candidates}
        output: dict[str, StrategyDefinition] = {}

        for record in self._strategy_registry.list():
            definition = record.definition
            if not record.enabled or not definition.enabled:
                continue
            if definition.strategy_id in output:
                raise StrategyRegistryAmbiguityError(
                    "multiple enabled versions exist for one strategy_id"
                )
            if not set(definition.default_actions) <= legal_action_ids:
                continue

            judgments: list[bool] = []
            for rule in self._eligibility_rules:
                judgment = rule.evaluate(
                    definition,
                    runtime_context,
                    understanding_state,
                    goals,
                    candidates,
                )
                if judgment is not None:
                    judgments.append(judgment)
            if False in judgments:
                continue
            if (
                definition.required_conditions or definition.avoid_conditions
            ) and True not in judgments:
                continue

            output[definition.strategy_id] = definition

        return output

    @staticmethod
    def _validate_choice(
        strategy_id: str,
        action_ids: tuple[str, ...],
        *,
        legal_strategy_ids: frozenset[str],
        legal_action_ids: frozenset[str],
    ) -> None:
        if strategy_id not in legal_strategy_ids:
            raise InvalidStrategySelectionError(
                "strategy rule selected outside the legal strategy space"
            )
        if len(set(action_ids)) != len(action_ids):
            raise InvalidStrategySelectionError(
                "strategy rule action_ids must not contain duplicates"
            )
        if not set(action_ids) <= legal_action_ids:
            raise InvalidStrategySelectionError(
                "strategy rule selected outside the legal action candidate space"
            )
