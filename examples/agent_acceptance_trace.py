"""Read-only, non-authoritative per-iteration evidence for the GA-20 acceptance UI.

This wrapper delegates to the existing approved StepPort; it cannot approve,
alter, retry, or execute any action by itself. Never exposes raw private facts.
"""
from __future__ import annotations

from agent_core.iteration import IterationRef
from agent_core.runner import Decision, ObservedFact, StepPort
from runtime.contracts import RuntimeInput


class AcceptanceTraceStep:
    def __init__(self, delegate: StepPort) -> None:
        self.delegate = delegate
        self.events: list[dict[str, object]] = []

    async def decide(
        self,
        current_input: RuntimeInput,
        iteration: IterationRef,
        observations: tuple[ObservedFact, ...],
    ) -> Decision:
        decision = await self.delegate.decide(current_input, iteration, observations)
        approved = decision.approved
        self.events.append({
            "type": "decision", "ordinal": len(self.events),
            "kind": decision.kind,
            "seen_observations": len(observations),
            "plan_id": approved.plan_id if approved is not None else None,
            "actions": [step.action for step in approved.steps] if approved else [],
            "reason": decision.reason or None,
        })
        return decision

    async def execute_and_observe(self, decision: Decision) -> ObservedFact:
        observation = await self.delegate.execute_and_observe(decision)
        self.events.append({
            "type": "observation", "ordinal": len(self.events),
            "plan_id": observation.plan_id,
            "workflow_step_id": observation.workflow_step_id,
            "tool_id": observation.tool_id,
            "fact_count": len(observation.facts),
            "execution_id": observation.execution_id,
        })
        return observation
