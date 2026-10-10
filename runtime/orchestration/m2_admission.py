"""Shared M2 admission semantics for G2 and future task-level Agent steps.

An admission decision never executes preemption, workflows, or tool side effects.
Do not change the ordering of the legacy G2 policy gate.
"""

from __future__ import annotations

from runtime.constraint_management import RuntimeConstraint, RuntimeConstraintEvaluator
from runtime.contracts import (
    PolicyDecision,
    RuntimeContext,
    RuntimeInput,
    SafetyResult,
    UnderstandingState,
)
from runtime.orchestration.errors import OrchestrationInvariantError
from runtime.orchestration.m2_control import (
    AlternatePathRequiredError,
    PreemptionEffectRequiredError,
    PrioritySubjectResolver,
    RuntimeControlBlockedError,
)
from runtime.priority_management import IncomingDisposition


async def evaluate_m2_admission(
    *,
    runtime_input: RuntimeInput,
    runtime_context: RuntimeContext,
    understanding_state: UnderstandingState,
    safety_result: SafetyResult,
    priority_subject_resolver: PrioritySubjectResolver,
    runtime_constraint_evaluator: RuntimeConstraintEvaluator,
) -> RuntimeConstraint:
    """Return the original M2 RuntimeConstraint, with no new approval authority."""
    subjects = await priority_subject_resolver.resolve(
        runtime_input,
        runtime_context,
        understanding_state,
        safety_result,
    )
    return await runtime_constraint_evaluator.evaluate(
        runtime_context=runtime_context,
        understanding_state=understanding_state,
        safety_result=safety_result,
        current_priority_subject=subjects.current,
        incoming_priority_subject=subjects.incoming,
    )


def assert_admission_allows_flow(
    *,
    constraint: RuntimeConstraint,
    request_id: str,
    policy_decision: PolicyDecision,
) -> None:
    """Keep G2's correlation, blocked, disposition, preemption priority exact."""
    if constraint.request_id != request_id:
        raise OrchestrationInvariantError(
            "POLICY",
            "RuntimeConstraint.request_id must match current RuntimeInput",
        )
    if constraint.policy_decision != policy_decision:
        raise OrchestrationInvariantError(
            "POLICY",
            "RuntimeConstraint policy decision must match POLICY output",
        )

    if policy_decision.blocked or not policy_decision.allowed:
        if policy_decision.forced_workflow is not None:
            raise AlternatePathRequiredError(policy_decision.forced_workflow)
        raise RuntimeControlBlockedError("POLICY_BLOCKED")

    if constraint.incoming_disposition is not IncomingDisposition.PROCESS_NOW:
        raise RuntimeControlBlockedError(
            f"INCOMING_{constraint.incoming_disposition.value}",
            disposition=constraint.incoming_disposition,
        )

    if (
        constraint.requires_interruption
        and constraint.preemption_decision.current_subject_id is not None
    ):
        raise PreemptionEffectRequiredError()
