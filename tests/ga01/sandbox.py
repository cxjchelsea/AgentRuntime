"""Explicit no-IO sandbox verifier; only test code may import this module."""

from __future__ import annotations

from dataclasses import dataclass

from agent_core.iteration import (
    AgentRunBinding,
    IterationCorrelationError,
    IterationRef,
    assert_execution_correlation,
)
from runtime.contracts import (
    ApprovedActionPlan,
    ExecutionPlanStatus,
    ExecutionResult,
    RuntimeContext,
)
from runtime.interfaces.execution import ExecutionEngine


@dataclass(frozen=True, slots=True)
class SandboxObservation:
    iteration_id: str
    execution_id: str
    plan_id: str
    facts: tuple[str, ...]


class LocalMockExecutionEngine(ExecutionEngine):
    """No network, no DB, no actual tools; fixed in-memory ExecutionResult."""

    def __init__(self, prepared: ExecutionResult) -> None:
        self.prepared = prepared
        self.call_count = 0

    async def execute(
        self, approved_action_plan: ApprovedActionPlan, runtime_context: RuntimeContext
    ) -> ExecutionResult:
        self.call_count += 1
        if (
            type(approved_action_plan) is not ApprovedActionPlan
            or approved_action_plan.plan_id != self.prepared.plan_id
            or approved_action_plan.request_id != self.prepared.request_id
            or runtime_context.identity_context.identity_scope
            != self.prepared.identity_scope
        ):
            raise IterationCorrelationError("mock execution rejected invalid approval")
        if self.call_count > 1:
            raise IterationCorrelationError("mock may not silently repeat an attempt")
        return self.prepared


def verify_local_mock(
    *,
    binding: AgentRunBinding,
    iteration: IterationRef,
    context: RuntimeContext,
    approved: ApprovedActionPlan,
    execution: ExecutionResult,
) -> SandboxObservation:
    assert_execution_correlation(
        binding=binding,
        iteration=iteration,
        runtime_context=context,
        approved=approved,
        execution=execution,
    )
    if execution.plan_status is not ExecutionPlanStatus.SUCCESS:
        raise IterationCorrelationError("non-success terminal execution evidence")
    # Deliberately not a ValidatedResult: local facts do not grant M6 authority.
    return SandboxObservation(
        iteration_id=iteration.request_id,
        execution_id=execution.execution_id,
        plan_id=execution.plan_id,
        facts=("MOCK_EXECUTION_OBSERVED",),
    )
