"""M4-IU2 PlanningMode routing and Goal Resolution gates."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from runtime.contracts import PolicyDecision, RuntimeContext, UnderstandingState
from runtime.contracts.context import TaskContext
from runtime.contracts.enums import PlanningMode, ProcessingPath, TaskStatus
from runtime.contracts.understanding import GoalUnderstanding
from runtime.planning import (
    GoalCandidate,
    GoalResolutionPolicy,
    GoalResolver,
    GoalSource,
    PlanningBlockedByPolicyError,
    PlanningModeRouter,
    PlanningRouteConflictError,
    PlanningRouteSignal,
)
from tests.orchestration_stubs import (
    build_policy_decision,
    build_runtime_context,
    build_understanding_state,
)


def _understanding(
    *,
    path: ProcessingPath = ProcessingPath.FAST_PATH,
    explicit_goal: str | None = None,
    implicit_need: str | None = None,
    confidence: float | None = None,
) -> UnderstandingState:
    base = build_understanding_state()
    metadata = base.metadata.model_copy(update={"processing_path": path})
    goal = None
    if explicit_goal is not None or implicit_need is not None:
        goal = GoalUnderstanding(
            explicit_goal=explicit_goal,
            implicit_need=implicit_need,
            confidence=confidence,
        )
    return base.model_copy(update={"metadata": metadata, "goal": goal})


def _policy(**updates: object) -> PolicyDecision:
    return build_policy_decision().model_copy(update=updates)


@dataclass(frozen=True)
class StaticRouteRule:
    signal: PlanningRouteSignal | None

    def evaluate(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        policy_decision: PolicyDecision,
    ) -> PlanningRouteSignal | None:
        del runtime_context, understanding_state, policy_decision
        return self.signal


def test_forced_policy_always_routes_forced_before_injected_rules() -> None:
    router = PlanningModeRouter(
        rules=(
            StaticRouteRule(
                PlanningRouteSignal(
                    mode=PlanningMode.DETERMINISTIC,
                    reason_code="DOMAIN_DETERMINISTIC",
                )
            ),
        )
    )

    decision = router.route(
        build_runtime_context(),
        _understanding(),
        _policy(forced_action="DOMAIN_FORCED_ACTION"),
    )

    assert decision.mode is PlanningMode.FORCED
    assert decision.forced_action == "DOMAIN_FORCED_ACTION"
    assert decision.reason_codes == ("POLICY_FORCED_ACTION",)


def test_blocked_policy_fails_before_any_planning_route() -> None:
    router = PlanningModeRouter()

    with pytest.raises(PlanningBlockedByPolicyError):
        router.route(
            build_runtime_context(),
            _understanding(),
            _policy(allowed=False, blocked=True),
        )


def test_degraded_understanding_routes_degraded_without_domain_semantics() -> None:
    decision = PlanningModeRouter().route(
        build_runtime_context(),
        _understanding(path=ProcessingPath.DEGRADED_PATH),
        _policy(),
    )

    assert decision.mode is PlanningMode.DEGRADED
    assert decision.reason_codes == ("UNDERSTANDING_DEGRADED",)


def test_injected_rule_can_route_deterministic_without_core_domain_catalog() -> None:
    router = PlanningModeRouter(
        rules=(
            StaticRouteRule(
                PlanningRouteSignal(
                    mode=PlanningMode.DETERMINISTIC,
                    reason_code="DOMAIN_UNIQUE_MAPPING",
                )
            ),
        )
    )

    decision = router.route(
        build_runtime_context(),
        _understanding(),
        _policy(),
    )

    assert decision.mode is PlanningMode.DETERMINISTIC


def test_conflicting_injected_route_signals_fail_closed() -> None:
    router = PlanningModeRouter(
        rules=(
            StaticRouteRule(
                PlanningRouteSignal(
                    mode=PlanningMode.DETERMINISTIC,
                    reason_code="RULE_A",
                )
            ),
            StaticRouteRule(
                PlanningRouteSignal(
                    mode=PlanningMode.AGENT_PLANNED,
                    reason_code="RULE_B",
                )
            ),
        )
    )

    with pytest.raises(PlanningRouteConflictError):
        router.route(
            build_runtime_context(),
            _understanding(),
            _policy(),
        )


def test_injected_rule_cannot_fabricate_forced_mode() -> None:
    router = PlanningModeRouter(
        rules=(
            StaticRouteRule(
                PlanningRouteSignal(
                    mode=PlanningMode.FORCED,
                    reason_code="DOMAIN_TRIES_FORCE",
                )
            ),
        )
    )

    with pytest.raises(PlanningRouteConflictError):
        router.route(
            build_runtime_context(),
            _understanding(),
            _policy(),
        )


def test_default_non_forced_non_degraded_route_is_agent_planned() -> None:
    decision = PlanningModeRouter().route(
        build_runtime_context(),
        _understanding(),
        _policy(),
    )

    assert decision.mode is PlanningMode.AGENT_PLANNED
    assert decision.reason_codes == ("DEFAULT_AGENT_PLANNED",)


def test_goal_resolution_honors_forced_over_explicit_and_task_and_implicit() -> None:
    context = build_runtime_context().model_copy(
        update={
            "task_context": TaskContext(
                task_id="task-001",
                task_type="DOMAIN_TASK",
                active_task="DOMAIN_TASK_INSTANCE",
                status=TaskStatus.ACTIVE,
            )
        }
    )
    understanding = _understanding(
        explicit_goal="DOMAIN_EXPLICIT_GOAL",
        implicit_need="DOMAIN_IMPLICIT_NEED",
        confidence=0.95,
    )
    resolver = GoalResolver(
        policy=GoalResolutionPolicy(strong_implicit_need_threshold=0.8)
    )

    result = resolver.resolve(
        context,
        understanding,
        _policy(forced_workflow="DOMAIN_FORCED_WORKFLOW"),
    )

    assert result.primary_goal is not None
    assert result.primary_goal.goal_source == GoalSource.FORCED_POLICY.value
    assert result.primary_goal.parameters == {
        "forced_workflow": "DOMAIN_FORCED_WORKFLOW"
    }
    assert [goal.goal_source for goal in result.secondary_goals] == [
        GoalSource.EXPLICIT_USER_GOAL.value,
        GoalSource.REQUIRED_TASK_CONTINUATION.value,
        GoalSource.STRONG_IMPLICIT_NEED.value,
    ]


def test_implicit_need_is_not_promoted_without_explicit_threshold_policy() -> None:
    result = GoalResolver().resolve(
        build_runtime_context(),
        _understanding(
            implicit_need="DOMAIN_IMPLICIT_NEED",
            confidence=0.99,
        ),
        _policy(),
    )

    assert result.primary_goal is None
    assert result.candidates == ()


def test_implicit_need_requires_configured_strength_threshold() -> None:
    resolver = GoalResolver(
        policy=GoalResolutionPolicy(strong_implicit_need_threshold=0.8)
    )

    weak = resolver.resolve(
        build_runtime_context(),
        _understanding(
            implicit_need="DOMAIN_IMPLICIT_NEED",
            confidence=0.7,
        ),
        _policy(),
    )
    strong = resolver.resolve(
        build_runtime_context(),
        _understanding(
            implicit_need="DOMAIN_IMPLICIT_NEED",
            confidence=0.9,
        ),
        _policy(),
    )

    assert weak.primary_goal is None
    assert strong.primary_goal is not None
    assert strong.primary_goal.goal_source == GoalSource.STRONG_IMPLICIT_NEED.value


@dataclass(frozen=True)
class CriticalTaskProvider:
    def collect(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        policy_decision: PolicyDecision,
    ) -> tuple[GoalCandidate, ...]:
        del runtime_context, understanding_state, policy_decision
        return (
            GoalCandidate(
                goal_id="DOMAIN_CRITICAL_TASK_GOAL",
                goal_type="DOMAIN_CRITICAL_TASK_GOAL",
                source=GoalSource.CRITICAL_ACTIVE_TASK,
            ),
        )


@dataclass(frozen=True)
class OpportunityProvider:
    def collect(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        policy_decision: PolicyDecision,
    ) -> tuple[GoalCandidate, ...]:
        del runtime_context, understanding_state, policy_decision
        return (
            GoalCandidate(
                goal_id="DOMAIN_AGENT_OPPORTUNITY",
                goal_type="DOMAIN_AGENT_OPPORTUNITY",
                source=GoalSource.AGENT_OPPORTUNITY,
            ),
        )


def test_critical_task_semantics_are_injected_and_rank_above_explicit_goal() -> None:
    result = GoalResolver(providers=(CriticalTaskProvider(),)).resolve(
        build_runtime_context(),
        _understanding(explicit_goal="DOMAIN_EXPLICIT_GOAL", confidence=1.0),
        _policy(),
    )

    assert result.primary_goal is not None
    assert result.primary_goal.goal_source == GoalSource.CRITICAL_ACTIVE_TASK.value
    assert result.secondary_goals[0].goal_source == GoalSource.EXPLICIT_USER_GOAL.value


def test_agent_opportunity_is_injected_and_ranks_below_explicit_goal() -> None:
    result = GoalResolver(providers=(OpportunityProvider(),)).resolve(
        build_runtime_context(),
        _understanding(explicit_goal="DOMAIN_EXPLICIT_GOAL", confidence=1.0),
        _policy(),
    )

    assert result.primary_goal is not None
    assert result.primary_goal.goal_source == GoalSource.EXPLICIT_USER_GOAL.value
    assert result.secondary_goals[0].goal_source == GoalSource.AGENT_OPPORTUNITY.value
