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


@dataclass(frozen=True, slots=True)
class StepRevision:
    step_id: str
    action_id: str
    effect_keys: frozenset[str]
    source_digest: str


@dataclass(frozen=True, slots=True)
class PlanRevision:
    previous_version: int
    next_version: int
    retained_step_ids: tuple[str, ...]
    replanned_step_ids: tuple[str, ...]
    requires_m4_reapproval: bool = True

    def __post_init__(self) -> None:
        if (
            self.next_version < self.previous_version
            or set(self.retained_step_ids) & set(self.replanned_step_ids)
            or not self.requires_m4_reapproval
        ):
            raise ValueError("invalid plan revision")


def revise_step_plan(
    *,
    previous: GoalState,
    decision: ReplanDecision,
    steps: tuple[StepRevision, ...],
    changed_keys: frozenset[str],
    domain_fingerprint_matches: bool,
) -> PlanRevision:
    """Classify steps, but never transfer old execution evidence to a new run.

    Retained means only immutable *step definitions* remain eligible for the
    new M4 approval. Replanned means the action/plan must be regenerated and
    approved. Neither category grants tool execution nor skips GA-09.
    """
    if (
        previous.version != decision.expected_version
        or decision.action is ReplanAction.NEW_RUN
        or not domain_fingerprint_matches
        or not steps
        or any(
            type(step) is not StepRevision
            or not step.step_id
            or not step.action_id
            or not step.source_digest
            for step in steps
        )
        or len({step.step_id for step in steps}) != len(steps)
        or not changed_keys
    ):
        raise ValueError("step revision provenance or request mismatch")
    retained: list[str] = []
    replanned: list[str] = []
    for step in steps:
        if "*" not in step.effect_keys and step.effect_keys.isdisjoint(changed_keys):
            retained.append(step.step_id)
        else:
            replanned.append(step.step_id)
    return PlanRevision(
        previous.version, decision.next_version,
        tuple(retained), tuple(replanned),
    )


@dataclass(frozen=True, slots=True)
class StepContinuation:
    """Explicitly chosen next-run step work; never a tool grant."""

    step_id: str
    disposition: str
    approved_action_id: str
    evidence_digest: str


def authorize_revision_selection(
    *,
    revision: PlanRevision,
    steps: tuple[StepRevision, ...],
    approved_actions: dict[str, str],
    freshly_verified_digests: dict[str, str],
) -> tuple[StepContinuation, ...]:
    """Require a new M4-approved action for EVERY retained or revised step.

    Skipping an unaffected read step is permitted only when a fresh independent
    source read has reverified the EXACT digest for the step. Otherwise, the
    caller must execute the newly approved action; previous-run observations
    are never injected into AgentRunCoordinator.
    """
    known = {item.step_id: item for item in steps}
    expected = set(revision.retained_step_ids) | set(revision.replanned_step_ids)
    if (
        len(known) != len(steps)
        or set(known) != expected
        or type(approved_actions) is not dict
        or set(approved_actions) != expected
        or type(freshly_verified_digests) is not dict
        or not set(freshly_verified_digests).issubset(expected)
        or any(
            type(action) is not str
            or not action
            or action != known[step_id].action_id
            for step_id, action in approved_actions.items()
        )
    ):
        raise ValueError("plan revision not approved for every step")
    result: list[StepContinuation] = []
    for item in steps:
        fresh = freshly_verified_digests.get(item.step_id)
        if fresh is not None and (
            type(fresh) is not str or not fresh
        ):
            raise ValueError("invalid fresh observation digest")
        reusable = (
            item.step_id in revision.retained_step_ids
            and fresh is not None
            and fresh == item.source_digest
        )
        result.append(
            StepContinuation(
                item.step_id,
                "REVALIDATED_NO_TOOL" if reusable else "EXECUTE_APPROVED",
                approved_actions[item.step_id],
                fresh if reusable and fresh is not None else "",
            )
        )
    return tuple(result)


@dataclass(frozen=True, slots=True)
class PreviousStepSources:
    """Prior successful run's source fingerprints, scoped to one conversation."""

    domain: str
    binding_fingerprint: str
    goal_version: int
    goal_key: str
    step_sources: tuple[tuple[str, str], ...]
    session_id: str
    subject_id: str

    def __post_init__(self) -> None:
        if (
            not self.domain
            or not self.session_id
            or not self.subject_id
            or len(self.binding_fingerprint) != 64
            or self.goal_version < 1
            or not self.goal_key
            or not self.step_sources
            or len({key for key, _ in self.step_sources}) != len(self.step_sources)
            or any(
                not step or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)
                for step, digest in self.step_sources
            )
        ):
            raise ValueError("invalid previous step source evidence")
