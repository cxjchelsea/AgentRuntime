"""GA-22 bounded cross-turn goal state and replanning admission.

Application-owned decision record, not a new planner or execution grant.
Any change/refresh must return through the existing M3/M4/GA-09 pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from examples.ga22_goal_policy import DomainGoalPolicy, GoalUpdate


class ReplanAction(str, Enum):
    NEW_RUN = "NEW_RUN"
    REPLAN_WITH_FRESH_EVIDENCE = "REPLAN_WITH_FRESH_EVIDENCE"
    REFRESH_WITH_FRESH_EVIDENCE = "REFRESH_WITH_FRESH_EVIDENCE"


@dataclass(frozen=True, slots=True)
class GoalState:
    domain: str
    question: str
    version: int
    update: GoalUpdate | None
    evidence_digests: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReplanDecision:
    action: ReplanAction
    expected_version: int
    next_version: int
    update: GoalUpdate | None
    must_execute: bool = True

    def __post_init__(self) -> None:
        if (
            self.expected_version < 0
            or self.next_version < 1
            or not self.must_execute
        ):
            raise ValueError("invalid replanning admission")


def decide_replanning(
    *,
    previous: GoalState | None,
    domain: str,
    question: str,
    policy: DomainGoalPolicy | None,
    update_text: str | None = None,
    refresh: bool = False,
) -> ReplanDecision:
    """Fail closed: never use cached observations to satisfy a changed goal."""
    if not domain or not question or (update_text is not None and refresh):
        raise ValueError("invalid replanning request")
    if previous is None:
        if update_text is not None or refresh:
            raise ValueError("no prior verified goal")
        return ReplanDecision(ReplanAction.NEW_RUN, 0, 1, None)
    if previous.domain != domain or previous.question != question:
        if update_text is not None or refresh:
            raise ValueError("goal scope mismatch")
        return ReplanDecision(
            ReplanAction.NEW_RUN, previous.version, previous.version + 1, None
        )
    if update_text is not None:
        if policy is None or policy.domain != domain:
            raise ValueError("no matching goal policy")
        change = policy.parse(update_text)
        if previous.update == change:
            # Same parameter is still a new requested run, not permission
            # to assert cached observations are fresh.
            return ReplanDecision(
                ReplanAction.REFRESH_WITH_FRESH_EVIDENCE,
                previous.version, previous.version, change
            )
        return ReplanDecision(
            ReplanAction.REPLAN_WITH_FRESH_EVIDENCE,
            previous.version, previous.version + 1, change
        )
    if refresh:
        return ReplanDecision(
            ReplanAction.REFRESH_WITH_FRESH_EVIDENCE,
            previous.version, previous.version, previous.update
        )
    return ReplanDecision(
        ReplanAction.NEW_RUN, previous.version, previous.version + 1, None
    )
