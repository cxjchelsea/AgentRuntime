"""M2-IU5 internal RuntimeConstraint integration types.

These types aggregate already-defined M2 decisions without becoming new Canonical
Contracts. They exist to make the M2 decision chain explicit and traceable before
Planner integration is implemented.
"""

from __future__ import annotations

from dataclasses import dataclass

from runtime.contracts import PolicyDecision, RuntimeControlState, SafetyResult
from runtime.priority_management import (
    IncomingDisposition,
    PreemptionDecision,
    PriorityDecision,
)


@dataclass(frozen=True, slots=True)
class StateConstraintDecision:
    """Explicit projection of the frozen RuntimeStateContext into M2 evaluation."""

    current_state: RuntimeControlState
    interruptible: bool
    active_task_id: str | None
    active_workflow_id: str | None
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RuntimeConstraint:
    """Internal aggregate of M2 decisions for one post-understanding evaluation."""

    request_id: str
    safety_result: SafetyResult
    state_decision: StateConstraintDecision
    priority_decision: PriorityDecision
    preemption_decision: PreemptionDecision
    policy_decision: PolicyDecision

    @property
    def requires_interruption(self) -> bool:
        """Whether either hard Policy or Preemption requires interrupting current work."""
        return (
            self.policy_decision.interrupt_current_task
            or self.preemption_decision.interrupt
        )

    @property
    def incoming_disposition(self) -> IncomingDisposition:
        """Expose the explicit incoming-event disposition without executing it."""
        return self.preemption_decision.disposition
