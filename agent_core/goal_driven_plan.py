"""GA-17 bounded goal-driven plan proposals, dependency gates and replanning.

The application admits goal outcomes and a domain catalog, while the model
proposes a bounded DAG of read-only steps. Only validated plan steps may reach
the existing M4/AgentRunCoordinator sandbox. This is NOT M6 authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_core.domain_execution_catalog import DomainExecutionCatalog, DomainStep
from agent_core.runner import ObservedFact, RunBoundaryError


@dataclass(frozen=True, slots=True)
class AdmittedGoal:
    """Trusted goal obligations, not untrusted model-selected requirements."""

    catalog: DomainExecutionCatalog
    goal_id: str
    required_facts: frozenset[str]

    def __post_init__(self) -> None:
        known = {step.completion_fact for step in self.catalog.workflow.steps}
        if (
            type(self.catalog) is not DomainExecutionCatalog
            or type(self.goal_id) is not str
            or not 1 <= len(self.goal_id) <= 96
            or type(self.required_facts) is not frozenset
            or not self.required_facts
            or any(type(fact) is not str for fact in self.required_facts)
            or not self.required_facts.issubset(known)
        ):
            raise RunBoundaryError("unadmitted goal requirements")


@dataclass(frozen=True, slots=True)
class PlannedStep:
    step_id: str
    depends_on: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GoalPlan:
    goal: AdmittedGoal
    steps: tuple[PlannedStep, ...]

    def __post_init__(self) -> None:
        catalog_steps = {
            step.step_id: step for step in self.goal.catalog.workflow.steps
        }
        if (
            type(self.goal) is not AdmittedGoal
            or type(self.steps) is not tuple
            or not 1 <= len(self.steps) <= 6
            or any(type(step) is not PlannedStep for step in self.steps)
        ):
            raise RunBoundaryError("invalid goal plan")
        ids = [step.step_id for step in self.steps]
        if len(set(ids)) != len(ids) or not set(ids).issubset(catalog_steps):
            raise RunBoundaryError("goal plan has duplicate or foreign tool")
        if not self.goal.required_facts.issubset(
            {catalog_steps[step_id].completion_fact for step_id in ids}
        ):
            raise RunBoundaryError("goal plan omits required outcome")
        for step in self.steps:
            deps = step.depends_on
            if (
                type(deps) is not tuple
                or any(type(dep) is not str for dep in deps)
                or len(set(deps)) != len(deps)
                or step.step_id in deps
                or not set(deps).issubset(ids)
            ):
                raise RunBoundaryError("invalid plan dependencies")
        # Disallow any cycle, regardless of proposed sequence.
        pending = {step.step_id: set(step.depends_on) for step in self.steps}
        resolved: set[str] = set()
        while pending:
            ready = {key for key, deps in pending.items() if deps <= resolved}
            if not ready:
                raise RunBoundaryError("cyclic goal plan")
            resolved.update(ready)
            for key in ready:
                del pending[key]

    @classmethod
    def from_model(cls, goal: AdmittedGoal, candidate: Any) -> GoalPlan:
        """Fail closed on extra keys, duplicate IDs, malformed or cyclic DAGs."""
        if type(candidate) is not dict or set(candidate) != {"goal_id", "steps"}:
            raise RunBoundaryError("model goal plan contract mismatch")
        if candidate["goal_id"] != goal.goal_id:
            raise RunBoundaryError("model changed admitted goal")
        raw_steps = candidate["steps"]
        if type(raw_steps) is not list or not 1 <= len(raw_steps) <= 6:
            raise RunBoundaryError("invalid model goal steps")
        proposed: list[PlannedStep] = []
        for item in raw_steps:
            if type(item) is not dict or set(item) != {"step_id", "depends_on"}:
                raise RunBoundaryError("invalid model step fields")
            deps = item["depends_on"]
            if (
                type(item["step_id"]) is not str
                or type(deps) is not list
                or len(deps) > 5
                or any(type(dep) is not str for dep in deps)
            ):
                raise RunBoundaryError("invalid model dependency fields")
            proposed.append(PlannedStep(item["step_id"], tuple(deps)))
        return cls(goal, tuple(proposed))

    def _verified_done(
        self, run_id: str, observations: tuple[ObservedFact, ...]
    ) -> set[str]:
        if type(run_id) is not str or not run_id:
            raise RunBoundaryError("invalid goal run")
        listed = {step.step_id: step for step in self.steps}
        declared = {
            step.step_id: step for step in self.goal.catalog.workflow.steps
        }
        seen: set[str] = set()
        plans: set[str] = set()
        executions: set[str] = set()
        for observation in observations:
            if type(observation) is not ObservedFact:
                raise RunBoundaryError("invalid goal observation")
            step_id = observation.workflow_step_id
            if step_id not in listed or step_id in seen:
                raise RunBoundaryError("unplanned or repeated goal step")
            step = declared[step_id]
            if (
                observation.run_id != run_id
                or observation.domain_fingerprint
                != self.goal.catalog.binding_fingerprint
                or observation.tool_id != step.tool_id
                or step.completion_fact not in observation.facts
                or not observation.request_id
                or not observation.plan_id
                or not observation.execution_id
                or observation.plan_id in plans
                or observation.execution_id in executions
                or not set(listed[step_id].depends_on).issubset(seen)
            ):
                raise RunBoundaryError("unverified goal step or dependency")
            seen.add(step_id)
            plans.add(observation.plan_id)
            executions.add(observation.execution_id)
        return seen

    def eligible(
        self, run_id: str, observations: tuple[ObservedFact, ...]
    ) -> tuple[DomainStep, ...]:
        done = self._verified_done(run_id, observations)
        declared = {
            step.step_id: step for step in self.goal.catalog.workflow.steps
        }
        return tuple(
            declared[step.step_id]
            for step in self.steps
            if step.step_id not in done
            and set(step.depends_on).issubset(done)
        )

    def completed(self, run_id: str, observations: tuple[ObservedFact, ...]) -> bool:
        try:
            done = self._verified_done(run_id, observations)
        except RunBoundaryError:
            return False
        catalog = {
            step.step_id: step for step in self.goal.catalog.workflow.steps
        }
        return done == {step.step_id for step in self.steps} and (
            self.goal.required_facts
            <= {catalog[step_id].completion_fact for step_id in done}
        )

    def revise(
        self, replacement: GoalPlan, run_id: str,
        observations: tuple[ObservedFact, ...],
    ) -> GoalPlan:
        """A replan may change pending work, never erase executed evidence."""
        if replacement.goal != self.goal:
            raise RunBoundaryError("replan changed goal authority")
        done = self._verified_done(run_id, observations)
        prior = {step.step_id: step for step in self.steps}
        updated = {step.step_id: step for step in replacement.steps}
        if any(step_id not in updated or updated[step_id] != prior[step_id]
               for step_id in done):
            raise RunBoundaryError("replan rewrote executed step")
        # Validate dependency eligibility for the preserved observation prefix.
        replacement._verified_done(run_id, observations)
        return replacement
