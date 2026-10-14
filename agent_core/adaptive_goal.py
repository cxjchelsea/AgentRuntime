"""GA-18 bounded post-observation goal assessment and adaptive replan.

Read-only sandbox: an apparently completed goal can require a distinct,
not-yet-executed verification step based on trusted observations. UNKNOWN
execution results remain blocked by AgentRunCoordinator (no replay).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from agent_core.goal_driven_plan import GoalPlan
from agent_core.runner import ObservedFact, RunBoundaryError


class GoalVerdict(str, Enum):
    CONTINUE = "CONTINUE"
    NEEDS_REPLAN = "NEEDS_REPLAN"
    VERIFIED = "VERIFIED"


@dataclass(frozen=True, slots=True)
class AdaptiveGoalSession:
    plan: GoalPlan
    trigger_step_id: str
    trigger_fact: str
    verification_step_id: str
    replan_count: int = 0
    max_replans: int = 1

    def __post_init__(self) -> None:
        steps = {
            step.step_id for step in self.plan.goal.catalog.workflow.steps
        }
        if (
            type(self.plan) is not GoalPlan
            or type(self.trigger_step_id) is not str
            or type(self.verification_step_id) is not str
            or self.trigger_step_id == self.verification_step_id
            or not {self.trigger_step_id, self.verification_step_id} <= steps
            or type(self.trigger_fact) is not str
            or not 1 <= len(self.trigger_fact) <= 96
            or type(self.replan_count) is not int
            or type(self.max_replans) is not int
            or not 0 <= self.replan_count <= self.max_replans <= 2
        ):
            raise RunBoundaryError("invalid adaptive goal policy")

    def assess(
        self, run_id: str, observations: tuple[ObservedFact, ...]
    ) -> GoalVerdict:
        # Strictly validate observed step identity, run scope, facts and
        # previously declared dependencies before any goal interpretation.
        done = self.plan._verified_done(run_id, observations)
        trigger = next(
            (
                obs for obs in observations
                if obs.workflow_step_id == self.trigger_step_id
            ),
            None,
        )
        if trigger is not None and self.trigger_fact in trigger.facts:
            if self.verification_step_id not in done:
                planned = {step.step_id for step in self.plan.steps}
                return (
                    GoalVerdict.CONTINUE
                    if self.verification_step_id in planned
                    else GoalVerdict.NEEDS_REPLAN
                )
            # Both original goal evidence and added independent verifier must
            # be present: model output alone never marks a goal successful.
            if self.plan.completed(run_id, observations):
                return GoalVerdict.VERIFIED
            return GoalVerdict.CONTINUE
        if self.plan.completed(run_id, observations):
            return GoalVerdict.VERIFIED
        return GoalVerdict.CONTINUE

    def revised(
        self,
        proposal: GoalPlan,
        run_id: str,
        observations: tuple[ObservedFact, ...],
    ) -> AdaptiveGoalSession:
        if self.assess(run_id, observations) != GoalVerdict.NEEDS_REPLAN:
            raise RunBoundaryError("goal has no authorized replan trigger")
        if self.replan_count >= self.max_replans:
            raise RunBoundaryError("goal replan budget exhausted")
        if proposal.goal != self.plan.goal:
            raise RunBoundaryError("goal changed during replan")
        required = {
            step.step_id for step in proposal.steps
        }
        if self.verification_step_id not in required:
            raise RunBoundaryError("replan omits required verifier")
        replacement = self.plan.revise(proposal, run_id, observations)
        # The verification must not be dependent on yet-unexecutable
        # conditions or claim it preceded evidence already observed.
        eligible = replacement.eligible(run_id, observations)
        if self.verification_step_id not in {step.step_id for step in eligible}:
            raise RunBoundaryError("replan verifier not executable")
        return AdaptiveGoalSession(
            plan=replacement,
            trigger_step_id=self.trigger_step_id,
            trigger_fact=self.trigger_fact,
            verification_step_id=self.verification_step_id,
            replan_count=self.replan_count + 1,
            max_replans=self.max_replans,
        )
