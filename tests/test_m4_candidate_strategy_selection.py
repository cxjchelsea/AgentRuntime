"""M4-IU3 legal candidate generation and hybrid strategy selection gates."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from runtime.contracts import PolicyDecision, RuntimeContext, UnderstandingState
from runtime.contracts.enums import PlanningMode, ProcessingPath
from runtime.contracts.understanding import GoalUnderstanding
from runtime.planning import (
    ActionRegistryAmbiguityError,
    GoalResolver,
    HybridStrategySelector,
    InvalidActionCandidateError,
    InvalidStrategySelectionError,
    LegalActionCandidateBuilder,
    PlanningActionCandidate,
    StrategyModelOutputError,
    StrategyModelRequest,
    StrategyModelUnavailableError,
    StrategyRuleChoice,
)
from runtime.registries import (
    ActionDefinition,
    ActionRegistry,
    IntrusivenessLevel,
    StrategyDefinition,
    StrategyRegistry,
)
from tests.orchestration_stubs import (
    build_policy_decision,
    build_runtime_context,
    build_understanding_state,
)


def _action(
    action_id: str,
    *,
    version: str = "1.0.0",
    required_capability: str | None = None,
) -> ActionDefinition:
    return ActionDefinition(
        action_id=action_id,
        version=version,
        category="DOMAIN_CATEGORY",
        description="domain action",
        intrusiveness_level=IntrusivenessLevel.LOW,
        requires_confirmation=False,
        required_capability=required_capability,
        allowed_planning_modes=[
            PlanningMode.DETERMINISTIC,
            PlanningMode.AGENT_PLANNED,
        ],
    )


def _strategy(
    strategy_id: str,
    *,
    default_actions: list[str],
    version: str = "1.0.0",
    required_conditions: list[str] | None = None,
    avoid_conditions: list[str] | None = None,
) -> StrategyDefinition:
    return StrategyDefinition(
        strategy_id=strategy_id,
        version=version,
        description="domain strategy",
        preferred_goals=[],
        preferred_needs=[],
        compatible_emotions=[],
        required_conditions=required_conditions or [],
        avoid_conditions=avoid_conditions or [],
        default_actions=default_actions,
        intrusiveness_level=IntrusivenessLevel.LOW,
    )


def _understanding(
    *,
    candidate_actions: list[dict[str, object]] | None = None,
) -> UnderstandingState:
    base = build_understanding_state()
    return base.model_copy(
        update={
            "metadata": base.metadata.model_copy(
                update={"processing_path": ProcessingPath.FAST_PATH}
            ),
            "goal": GoalUnderstanding(
                explicit_goal="DOMAIN_GOAL",
                confidence=1.0,
            ),
            "candidate_actions": candidate_actions,
        }
    )


def _goals(
    understanding: UnderstandingState,
    *,
    context: RuntimeContext | None = None,
    policy: PolicyDecision | None = None,
):
    return GoalResolver().resolve(
        context or build_runtime_context(),
        understanding,
        policy or build_policy_decision(),
    )


def test_candidate_builder_uses_registered_m3_candidate_and_strategy_defaults() -> None:
    actions = ActionRegistry()
    actions.register(_action("DOMAIN_ACTION_A"))
    actions.register(_action("DOMAIN_ACTION_B"))
    strategies = StrategyRegistry()
    strategies.register(
        _strategy(
            "DOMAIN_STRATEGY",
            default_actions=["DOMAIN_ACTION_B"],
        )
    )
    understanding = _understanding(
        candidate_actions=[
            {"action": "DOMAIN_ACTION_A", "confidence": 0.8},
        ]
    )

    candidates = LegalActionCandidateBuilder(
        action_registry=actions,
        strategy_registry=strategies,
    ).build(
        build_runtime_context(),
        understanding,
        _goals(understanding),
        build_policy_decision(),
        available_capability_ids=frozenset(),
    )

    by_id = {candidate.action: candidate for candidate in candidates}
    assert tuple(by_id) == ("DOMAIN_ACTION_A", "DOMAIN_ACTION_B")
    assert by_id["DOMAIN_ACTION_A"].confidence == 0.8
    assert by_id["DOMAIN_ACTION_A"].source_codes == ("M3_CANDIDATE",)
    assert by_id["DOMAIN_ACTION_B"].source_codes == (
        "STRATEGY_DEFAULT:DOMAIN_STRATEGY",
    )


def test_policy_filters_candidate_before_soft_selection() -> None:
    actions = ActionRegistry()
    actions.register(_action("ALLOWED_DOMAIN_ACTION"))
    actions.register(_action("FORBIDDEN_DOMAIN_ACTION"))
    strategies = StrategyRegistry()
    understanding = _understanding(
        candidate_actions=[
            {"action": "ALLOWED_DOMAIN_ACTION", "confidence": 0.8},
            {"action": "FORBIDDEN_DOMAIN_ACTION", "confidence": 0.9},
        ]
    )
    policy = build_policy_decision().model_copy(
        update={
            "allowed_actions": ["ALLOWED_DOMAIN_ACTION"],
            "forbidden_actions": ["FORBIDDEN_DOMAIN_ACTION"],
        }
    )

    candidates = LegalActionCandidateBuilder(
        action_registry=actions,
        strategy_registry=strategies,
    ).build(
        build_runtime_context(),
        understanding,
        _goals(understanding, policy=policy),
        policy,
        available_capability_ids=frozenset(),
    )

    assert [candidate.action for candidate in candidates] == [
        "ALLOWED_DOMAIN_ACTION"
    ]
    assert candidates[0].policy_allowed is True


def test_unavailable_required_capability_removes_candidate() -> None:
    actions = ActionRegistry()
    actions.register(
        _action(
            "DOMAIN_ACTION",
            required_capability="DOMAIN_CAPABILITY",
        )
    )
    strategies = StrategyRegistry()
    understanding = _understanding(
        candidate_actions=[{"action": "DOMAIN_ACTION", "confidence": 0.8}]
    )
    builder = LegalActionCandidateBuilder(
        action_registry=actions,
        strategy_registry=strategies,
    )

    unavailable = builder.build(
        build_runtime_context(),
        understanding,
        _goals(understanding),
        build_policy_decision(),
        available_capability_ids=frozenset(),
    )
    available = builder.build(
        build_runtime_context(),
        understanding,
        _goals(understanding),
        build_policy_decision(),
        available_capability_ids=frozenset({"DOMAIN_CAPABILITY"}),
    )

    assert unavailable == ()
    assert [candidate.action for candidate in available] == ["DOMAIN_ACTION"]


def test_unregistered_m3_candidate_fails_closed() -> None:
    understanding = _understanding(
        candidate_actions=[{"action": "UNREGISTERED_ACTION", "confidence": 0.8}]
    )

    with pytest.raises(InvalidActionCandidateError):
        LegalActionCandidateBuilder(
            action_registry=ActionRegistry(),
            strategy_registry=StrategyRegistry(),
        ).build(
            build_runtime_context(),
            understanding,
            _goals(understanding),
            build_policy_decision(),
            available_capability_ids=frozenset(),
        )


def test_multiple_enabled_versions_for_same_action_id_fail_closed() -> None:
    actions = ActionRegistry()
    actions.register(_action("DOMAIN_ACTION", version="1.0.0"))
    actions.register(_action("DOMAIN_ACTION", version="2.0.0"))
    understanding = _understanding(
        candidate_actions=[{"action": "DOMAIN_ACTION", "confidence": 0.8}]
    )

    with pytest.raises(ActionRegistryAmbiguityError):
        LegalActionCandidateBuilder(
            action_registry=actions,
            strategy_registry=StrategyRegistry(),
        ).build(
            build_runtime_context(),
            understanding,
            _goals(understanding),
            build_policy_decision(),
            available_capability_ids=frozenset(),
        )


@dataclass
class RecordingStrategyModel:
    payload: dict[str, object]

    def __post_init__(self) -> None:
        self.requests: list[StrategyModelRequest] = []

    async def infer(self, request: StrategyModelRequest) -> dict[str, object]:
        self.requests.append(request)
        return self.payload


def _candidate(action_id: str) -> PlanningActionCandidate:
    return PlanningActionCandidate(
        action=action_id,
        goal_fit=None,
        need_fit=None,
        context_fit=None,
        policy_allowed=True,
        intrusiveness=IntrusivenessLevel.LOW,
        repetition_penalty=None,
        confidence=0.8,
        source_codes=("TEST",),
    )


def _strategy_registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    registry.register(
        _strategy("DOMAIN_STRATEGY_A", default_actions=["DOMAIN_ACTION_A"])
    )
    registry.register(
        _strategy("DOMAIN_STRATEGY_B", default_actions=["DOMAIN_ACTION_B"])
    )
    return registry


def test_model_soft_selects_only_within_legal_strategy_and_action_space() -> None:
    model = RecordingStrategyModel(
        {
            "strategy_id": "DOMAIN_STRATEGY_B",
            "action_ids": ["DOMAIN_ACTION_B"],
            "confidence": 0.77,
            "reason_code": "MODEL_SOFT_CHOICE",
        }
    )
    understanding = _understanding()
    result = asyncio.run(
        HybridStrategySelector(
            strategy_registry=_strategy_registry(),
            model=model,
        ).select(
            planning_mode=PlanningMode.AGENT_PLANNED,
            runtime_context=build_runtime_context(),
            understanding_state=understanding,
            goals=_goals(understanding),
            candidates=(
                _candidate("DOMAIN_ACTION_A"),
                _candidate("DOMAIN_ACTION_B"),
            ),
            policy_decision=build_policy_decision(),
            available_capability_ids=frozenset({"DOMAIN_CAPABILITY"}),
        )
    )

    assert result.strategy.strategy_id == "DOMAIN_STRATEGY_B"
    assert result.selected_action_ids == ("DOMAIN_ACTION_B",)
    assert result.selection_path == "MODEL"
    assert len(model.requests) == 1
    request = model.requests[0]
    assert request.legal_strategy_ids == (
        "DOMAIN_STRATEGY_A",
        "DOMAIN_STRATEGY_B",
    )
    assert request.candidate_action_ids == (
        "DOMAIN_ACTION_A",
        "DOMAIN_ACTION_B",
    )


def test_model_request_does_not_expose_full_context_or_recent_turns() -> None:
    model = RecordingStrategyModel(
        {
            "strategy_id": "DOMAIN_STRATEGY_A",
            "action_ids": [],
        }
    )
    context = build_runtime_context()
    understanding = _understanding()

    asyncio.run(
        HybridStrategySelector(
            strategy_registry=_strategy_registry(),
            model=model,
        ).select(
            planning_mode=PlanningMode.AGENT_PLANNED,
            runtime_context=context,
            understanding_state=understanding,
            goals=_goals(understanding),
            candidates=(
                _candidate("DOMAIN_ACTION_A"),
                _candidate("DOMAIN_ACTION_B"),
            ),
            policy_decision=build_policy_decision(),
            available_capability_ids=frozenset(),
        )
    )

    request = model.requests[0]
    assert not hasattr(request, "runtime_context")
    assert not hasattr(request, "recent_turns")
    assert not hasattr(request, "memory_context")
    assert not hasattr(request, "tool_context")
    assert not hasattr(request, "domain_extensions")


def test_model_cannot_invent_strategy_or_action() -> None:
    understanding = _understanding()
    selector = HybridStrategySelector(
        strategy_registry=_strategy_registry(),
        model=RecordingStrategyModel(
            {
                "strategy_id": "INVENTED_STRATEGY",
                "action_ids": ["INVENTED_ACTION"],
            }
        ),
    )

    with pytest.raises(StrategyModelOutputError):
        asyncio.run(
            selector.select(
                planning_mode=PlanningMode.AGENT_PLANNED,
                runtime_context=build_runtime_context(),
                understanding_state=understanding,
                goals=_goals(understanding),
                candidates=(
                    _candidate("DOMAIN_ACTION_A"),
                    _candidate("DOMAIN_ACTION_B"),
                ),
                policy_decision=build_policy_decision(),
                available_capability_ids=frozenset(),
            )
        )


@dataclass(frozen=True)
class StaticStrategyRule:
    strategy_id: str

    def select(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        goals: Any,
        candidates: tuple[PlanningActionCandidate, ...],
        policy_decision: PolicyDecision,
        legal_strategy_ids: tuple[str, ...],
    ) -> StrategyRuleChoice | None:
        del (
            runtime_context,
            understanding_state,
            goals,
            candidates,
            policy_decision,
            legal_strategy_ids,
        )
        return StrategyRuleChoice(
            strategy_id=self.strategy_id,
            reason_code="RULE_CHOICE",
            action_ids=("DOMAIN_ACTION_A",),
            confidence=1.0,
        )


def test_rule_selection_precedes_model_and_model_is_not_called() -> None:
    model = RecordingStrategyModel(
        {
            "strategy_id": "DOMAIN_STRATEGY_B",
            "action_ids": ["DOMAIN_ACTION_B"],
        }
    )
    understanding = _understanding()

    result = asyncio.run(
        HybridStrategySelector(
            strategy_registry=_strategy_registry(),
            rules=(StaticStrategyRule("DOMAIN_STRATEGY_A"),),
            model=model,
        ).select(
            planning_mode=PlanningMode.AGENT_PLANNED,
            runtime_context=build_runtime_context(),
            understanding_state=understanding,
            goals=_goals(understanding),
            candidates=(
                _candidate("DOMAIN_ACTION_A"),
                _candidate("DOMAIN_ACTION_B"),
            ),
            policy_decision=build_policy_decision(),
            available_capability_ids=frozenset(),
        )
    )

    assert result.strategy.strategy_id == "DOMAIN_STRATEGY_A"
    assert result.selection_path == "RULE"
    assert model.requests == []


def test_non_agent_mode_never_falls_through_to_model_for_ambiguous_strategies() -> None:
    model = RecordingStrategyModel(
        {
            "strategy_id": "DOMAIN_STRATEGY_A",
            "action_ids": [],
        }
    )
    understanding = _understanding()

    with pytest.raises(InvalidStrategySelectionError):
        asyncio.run(
            HybridStrategySelector(
                strategy_registry=_strategy_registry(),
                model=model,
            ).select(
                planning_mode=PlanningMode.DETERMINISTIC,
                runtime_context=build_runtime_context(),
                understanding_state=understanding,
                goals=_goals(understanding),
                candidates=(
                    _candidate("DOMAIN_ACTION_A"),
                    _candidate("DOMAIN_ACTION_B"),
                ),
                policy_decision=build_policy_decision(),
                available_capability_ids=frozenset(),
            )
        )

    assert model.requests == []


def test_agent_mode_requires_model_when_rules_cannot_resolve_multiple_strategies() -> None:
    understanding = _understanding()

    with pytest.raises(StrategyModelUnavailableError):
        asyncio.run(
            HybridStrategySelector(
                strategy_registry=_strategy_registry(),
            ).select(
                planning_mode=PlanningMode.AGENT_PLANNED,
                runtime_context=build_runtime_context(),
                understanding_state=understanding,
                goals=_goals(understanding),
                candidates=(
                    _candidate("DOMAIN_ACTION_A"),
                    _candidate("DOMAIN_ACTION_B"),
                ),
                policy_decision=build_policy_decision(),
                available_capability_ids=frozenset(),
            )
        )
