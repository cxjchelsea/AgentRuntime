"""M2-IU5 explicit post-understanding Runtime Constraint integration."""

from __future__ import annotations

from runtime.constraint_management.definitions import (
    RuntimeConstraint,
    StateConstraintDecision,
)
from runtime.constraint_management.errors import RuntimeConstraintInvariantError
from runtime.contracts import (
    RuntimeContext,
    SafetyPhase,
    SafetyResult,
    UnderstandingState,
)
from runtime.interfaces.policy import PolicyEngine
from runtime.priority_management import (
    PreemptionEngine,
    PriorityEngine,
    PrioritySubject,
)


class RuntimeConstraintEvaluator:
    """Compose M2 state, priority, preemption, and policy decisions explicitly.

    The evaluator is intentionally side-effect free. It does not mutate RuntimeState,
    cancel tasks, enqueue events, execute cleanup/resume, or change Orchestrator flow.
    Priority kinds/numbers and Preemption rules remain injected inputs/configuration.
    """

    def __init__(
        self,
        *,
        policy_engine: PolicyEngine,
        preemption_engine: PreemptionEngine,
    ) -> None:
        self._policy_engine = policy_engine
        self._preemption_engine = preemption_engine

    async def evaluate(
        self,
        *,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        safety_result: SafetyResult,
        current_priority_subject: PrioritySubject | None,
        incoming_priority_subject: PrioritySubject,
    ) -> RuntimeConstraint:
        """Evaluate the explicit M2 post-understanding constraint chain."""
        self._validate_turn_continuity(understanding_state, safety_result)
        state_decision = self._evaluate_state(runtime_context)
        priority_decision = PriorityEngine.evaluate(
            current=current_priority_subject,
            incoming=incoming_priority_subject,
        )
        preemption_decision = self._preemption_engine.evaluate(
            current=current_priority_subject,
            incoming=incoming_priority_subject,
            current_interruptible=state_decision.interruptible,
            priority_decision=priority_decision,
        )
        policy_decision = await self._policy_engine.evaluate(
            runtime_context,
            understanding_state,
            safety_result,
        )
        return RuntimeConstraint(
            request_id=safety_result.request_id,
            safety_result=safety_result,
            state_decision=state_decision,
            priority_decision=priority_decision,
            preemption_decision=preemption_decision,
            policy_decision=policy_decision,
        )

    @staticmethod
    def _evaluate_state(runtime_context: RuntimeContext) -> StateConstraintDecision:
        state = runtime_context.runtime_state_context
        return StateConstraintDecision(
            current_state=state.current_state,
            interruptible=state.interruptible,
            active_task_id=state.active_task_id,
            active_workflow_id=state.active_workflow_id,
            reason_codes=("RUNTIME_STATE_CONTEXT_OBSERVED",),
        )

    @staticmethod
    def _validate_turn_continuity(
        understanding_state: UnderstandingState,
        safety_result: SafetyResult,
    ) -> None:
        if safety_result.phase is not SafetyPhase.DEEP:
            raise RuntimeConstraintInvariantError(
                "RuntimeConstraintEvaluator requires DEEP SafetyResult"
            )
        if understanding_state.metadata.request_id != safety_result.request_id:
            raise RuntimeConstraintInvariantError(
                "UnderstandingState and SafetyResult request_id must match"
            )
