"""GA-16 bounded dynamic task evidence and executable-step policy.

A verified domain package declares the *set* of candidate tools. A task may
select a subset and the model may reorder it, but cannot add tools, repeat
steps, or finish without task-specific evidence. Sandbox only; no M6 grants.
This policy composes with the unchanged AgentRunCoordinator and GA-09 dispatcher.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_core.domain_execution_catalog import DomainExecutionCatalog, DomainStep
from agent_core.runner import Decision, ObservedFact, RunBoundaryError


@dataclass(frozen=True, slots=True)
class DynamicBusinessTask:
    catalog: DomainExecutionCatalog
    required_steps: frozenset[str]

    def __post_init__(self) -> None:
        if (
            type(self.catalog) is not DomainExecutionCatalog
            or type(self.required_steps) is not frozenset
            or not self.required_steps
            or any(type(step_id) is not str for step_id in self.required_steps)
            or not self.required_steps.issubset(
                {step.step_id for step in self.catalog.workflow.steps}
            )
        ):
            raise RunBoundaryError("dynamic task outside approved catalog")

    def completed(self, run_id: str, observations: tuple[ObservedFact, ...]) -> bool:
        if type(run_id) is not str or not run_id:
            return False
        if len(observations) != len(self.required_steps):
            return False
        steps = {step.step_id: step for step in self.catalog.workflow.steps}
        seen: set[str] = set()
        executions: set[str] = set()
        plans: set[str] = set()
        for observed in observations:
            step_id = observed.workflow_step_id
            if (
                type(observed) is not ObservedFact
                or step_id is None
                or step_id not in self.required_steps
                or step_id in seen
            ):
                return False
            step = steps[step_id]
            if (
                observed.run_id != run_id
                or observed.domain_fingerprint != self.catalog.binding_fingerprint
                or observed.tool_id != step.tool_id
                or step.completion_fact not in observed.facts
                or not observed.request_id
                or not observed.plan_id
                or not observed.execution_id
                or observed.plan_id in plans
                or observed.execution_id in executions
            ):
                return False
            seen.add(step_id)
            plans.add(observed.plan_id)
            executions.add(observed.execution_id)
        return seen == self.required_steps

    def approved_next(
        self, decision: Decision, observations: tuple[ObservedFact, ...]
    ) -> tuple[int, DomainStep]:
        """Exact approved action maps to one not-yet-used task tool."""
        approved = decision.approved
        if approved is None or len(approved.steps) != 1 or decision.kind != "ACT":
            raise RunBoundaryError("dynamic task requires one approved action")
        done = {obs.workflow_step_id for obs in observations}
        matches = [
            (index, step)
            for index, step in enumerate(self.catalog.workflow.steps)
            if step.step_id in self.required_steps
            and step.step_id not in done
            and step.action_id == approved.steps[0].action
        ]
        if len(matches) != 1:
            raise RunBoundaryError("dynamic model action is not pending or unique")
        return matches[0]

    def guard(
        self,
        decision: Decision,
        observation: ObservedFact | None,
        index: int,
        observations: tuple[ObservedFact, ...],
    ) -> bool:
        if type(index) is not int or index != len(observations):
            return False
        try:
            _, step = self.approved_next(decision, observations)
        except RunBoundaryError:
            return False
        return observation is None or (
            observation.workflow_step_id == step.step_id
            and observation.tool_id == step.tool_id
            and step.completion_fact in observation.facts
        )
