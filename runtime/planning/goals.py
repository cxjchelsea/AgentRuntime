"""M4-IU2 Goal Resolution.

The resolver follows the frozen source hierarchy without inventing Domain goal values.
Critical-task and agent-opportunity semantics remain injectable because current Core
contracts do not contain enough generic facts to infer them safely.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from runtime.contracts import (
    PlanningGoal,
    PolicyDecision,
    RuntimeContext,
    UnderstandingState,
)
from runtime.contracts.enums import TaskStatus
from runtime.planning.errors import (
    GoalProviderExecutionError,
    InvalidGoalCandidateError,
)


class GoalSource(str, Enum):
    """Frozen M4 goal-source precedence."""

    FORCED_POLICY = "FORCED_POLICY"
    CRITICAL_ACTIVE_TASK = "CRITICAL_ACTIVE_TASK"
    EXPLICIT_USER_GOAL = "EXPLICIT_USER_GOAL"
    REQUIRED_TASK_CONTINUATION = "REQUIRED_TASK_CONTINUATION"
    STRONG_IMPLICIT_NEED = "STRONG_IMPLICIT_NEED"
    AGENT_OPPORTUNITY = "AGENT_OPPORTUNITY"


_SOURCE_PRIORITY = {
    GoalSource.FORCED_POLICY: 600,
    GoalSource.CRITICAL_ACTIVE_TASK: 500,
    GoalSource.EXPLICIT_USER_GOAL: 400,
    GoalSource.REQUIRED_TASK_CONTINUATION: 300,
    GoalSource.STRONG_IMPLICIT_NEED: 200,
    GoalSource.AGENT_OPPORTUNITY: 100,
}


@dataclass(frozen=True, slots=True)
class GoalResolutionPolicy:
    """Configurable thresholds for facts not numerically frozen by M4 design."""

    strong_implicit_need_threshold: float | None = None

    def __post_init__(self) -> None:
        threshold = self.strong_implicit_need_threshold
        if threshold is not None and not 0.0 <= threshold <= 1.0:
            raise InvalidGoalCandidateError(
                "strong_implicit_need_threshold must be within [0, 1]"
            )


@dataclass(frozen=True, slots=True)
class GoalCandidate:
    """Internal M4 goal candidate before Canonical PlanningGoal projection."""

    goal_id: str
    source: GoalSource
    goal_type: str | None = None
    parameters: dict[str, Any] | None = None
    completion_condition: str | None = None
    confidence: float | None = None

    def __post_init__(self) -> None:
        if not self.goal_id.strip():
            raise InvalidGoalCandidateError("goal_id must not be blank")
        if self.goal_type is not None and not self.goal_type.strip():
            raise InvalidGoalCandidateError("goal_type must not be blank")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise InvalidGoalCandidateError("confidence must be within [0, 1]")


class GoalCandidateProvider(Protocol):
    """Injected provider for goal sources Core cannot infer generically."""

    def collect(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        policy_decision: PolicyDecision,
    ) -> tuple[GoalCandidate, ...]:
        """Return zero or more typed candidates."""


@dataclass(frozen=True, slots=True)
class GoalResolutionResult:
    """Internal result consumed by later M4 units."""

    primary_goal: PlanningGoal | None
    secondary_goals: tuple[PlanningGoal, ...]
    candidates: tuple[GoalCandidate, ...]


class GoalResolver:
    """Resolve goals using frozen precedence and conservative generic extraction."""

    def __init__(
        self,
        *,
        policy: GoalResolutionPolicy | None = None,
        providers: tuple[GoalCandidateProvider, ...] = (),
    ) -> None:
        self._policy = policy or GoalResolutionPolicy()
        self._providers = providers

    def resolve(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        policy_decision: PolicyDecision,
    ) -> GoalResolutionResult:
        candidates: list[GoalCandidate] = []
        candidates.extend(self._forced_policy_candidates(policy_decision))
        candidates.extend(self._explicit_goal_candidates(understanding_state))
        candidates.extend(self._task_continuation_candidates(runtime_context))
        candidates.extend(self._implicit_need_candidates(understanding_state))

        for provider in self._providers:
            try:
                provided = provider.collect(
                    runtime_context,
                    understanding_state,
                    policy_decision,
                )
            except Exception as exc:
                if isinstance(exc, InvalidGoalCandidateError):
                    raise
                raise GoalProviderExecutionError(
                    "goal candidate provider execution failed"
                ) from exc
            candidates.extend(provided)

        ordered = self._stable_ranked_unique(candidates)
        projected = tuple(
            PlanningGoal(
                goal_id=candidate.goal_id,
                goal_type=candidate.goal_type,
                primary=index == 0,
                goal_source=candidate.source.value,
                goal_priority=_SOURCE_PRIORITY[candidate.source],
                parameters=deepcopy(candidate.parameters),
                completion_condition=candidate.completion_condition,
            )
            for index, candidate in enumerate(ordered)
        )

        return GoalResolutionResult(
            primary_goal=projected[0] if projected else None,
            secondary_goals=projected[1:],
            candidates=tuple(ordered),
        )

    @staticmethod
    def _forced_policy_candidates(
        policy_decision: PolicyDecision,
    ) -> tuple[GoalCandidate, ...]:
        output: list[GoalCandidate] = []
        if policy_decision.forced_workflow is not None:
            output.append(
                GoalCandidate(
                    goal_id=f"forced-workflow:{policy_decision.forced_workflow}",
                    source=GoalSource.FORCED_POLICY,
                    parameters={"forced_workflow": policy_decision.forced_workflow},
                )
            )
        if policy_decision.forced_action is not None:
            output.append(
                GoalCandidate(
                    goal_id=f"forced-action:{policy_decision.forced_action}",
                    source=GoalSource.FORCED_POLICY,
                    parameters={"forced_action": policy_decision.forced_action},
                )
            )
        return tuple(output)

    @staticmethod
    def _explicit_goal_candidates(
        understanding_state: UnderstandingState,
    ) -> tuple[GoalCandidate, ...]:
        goal = understanding_state.goal
        if goal is None or goal.explicit_goal is None or not goal.explicit_goal.strip():
            return ()
        return (
            GoalCandidate(
                goal_id=goal.explicit_goal,
                goal_type=goal.explicit_goal,
                source=GoalSource.EXPLICIT_USER_GOAL,
                parameters=deepcopy(goal.goal_parameters),
                confidence=goal.confidence,
            ),
        )

    @staticmethod
    def _task_continuation_candidates(
        runtime_context: RuntimeContext,
    ) -> tuple[GoalCandidate, ...]:
        task = runtime_context.task_context
        if task is None or task.status not in {
            TaskStatus.ACTIVE,
            TaskStatus.WAITING_USER,
            TaskStatus.WAITING_EXTERNAL,
        }:
            return ()

        stable_id = task.task_id or task.active_task
        if stable_id is None or not stable_id.strip():
            return ()

        parameters: dict[str, Any] = {}
        if task.task_stage is not None:
            parameters["task_stage"] = task.task_stage
        if task.next_required_field is not None:
            parameters["next_required_field"] = task.next_required_field

        return (
            GoalCandidate(
                goal_id=f"task:{stable_id}",
                goal_type=task.task_type,
                source=GoalSource.REQUIRED_TASK_CONTINUATION,
                parameters=parameters or None,
            ),
        )

    def _implicit_need_candidates(
        self,
        understanding_state: UnderstandingState,
    ) -> tuple[GoalCandidate, ...]:
        threshold = self._policy.strong_implicit_need_threshold
        goal = understanding_state.goal
        if threshold is None or goal is None or goal.implicit_need is None:
            return ()
        if not goal.implicit_need.strip():
            return ()
        if goal.confidence is None or goal.confidence < threshold:
            return ()
        return (
            GoalCandidate(
                goal_id=f"implicit-need:{goal.implicit_need}",
                goal_type=goal.implicit_need,
                source=GoalSource.STRONG_IMPLICIT_NEED,
                parameters=deepcopy(goal.goal_parameters),
                confidence=goal.confidence,
            ),
        )

    @staticmethod
    def _stable_ranked_unique(
        candidates: list[GoalCandidate],
    ) -> list[GoalCandidate]:
        indexed = list(enumerate(candidates))
        indexed.sort(
            key=lambda item: (
                -_SOURCE_PRIORITY[item[1].source],
                item[0],
            )
        )

        output: list[GoalCandidate] = []
        seen: set[str] = set()
        for _, candidate in indexed:
            if candidate.goal_id in seen:
                continue
            seen.add(candidate.goal_id)
            output.append(candidate)
        return output
