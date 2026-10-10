"""Task-level minimal loop with no tool, response or validation authority.

The injected StepPort may ONLY be assembled by an isolated test harness in Slice 1.
This module does not import SandboxObservation, M6 Grant or any Tool adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from agent_core.iteration import AgentRunBinding, IterationRef
from runtime.contracts import ApprovedActionPlan, RuntimeContext, RuntimeInput


class RunKind(str, Enum):
    FINISH = "FINISH"
    BLOCK = "BLOCK"
    WAIT = "WAIT"


class RunBoundaryError(ValueError):
    """A candidate action/observation crosses the current task boundary."""


@dataclass(frozen=True, slots=True)
class LoopBudget:
    max_iterations: int = 3
    max_executions: int = 2
    max_no_progress: int = 1

    def __post_init__(self) -> None:
        if min(self.max_iterations, self.max_executions, self.max_no_progress) < 1:
            raise ValueError("Loop budgets must all be positive")


@dataclass(frozen=True, slots=True)
class ObservedFact:
    """Test evidence data, NEVER an M6 authority-bearing ValidatedResult."""

    run_id: str
    request_id: str
    plan_id: str
    execution_id: str
    domain_fingerprint: str
    facts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Decision:
    iteration: IterationRef
    kind: str  # ACT, FINISH, WAIT, BLOCK
    context: RuntimeContext | None = None
    approved: ApprovedActionPlan | None = None
    reason: str = ""
    completion_fact: str | None = None


@dataclass(frozen=True, slots=True)
class RunOutcome:
    run_id: str
    kind: RunKind
    reason: str
    iterations: int
    executions: int
    observations: tuple[ObservedFact, ...]
    # Intentionally NOT RuntimeResponse, ValidatedResult, or UpdateResult.


class StepPort(Protocol):
    async def decide(
        self,
        current_input: RuntimeInput,
        iteration: IterationRef,
        observations: tuple[ObservedFact, ...],
    ) -> Decision: ...

    async def execute_and_observe(
        self,
        decision: Decision,
    ) -> ObservedFact: ...


class AgentRunCoordinator:
    """One-owner bounded Agent loop; never retries external side effects."""

    def __init__(self, step: StepPort, budget: LoopBudget) -> None:
        self._step = step
        self._budget = budget

    async def run(
        self, original_input: RuntimeInput, binding: AgentRunBinding
    ) -> RunOutcome:
        if original_input.request_id != binding.original_request_id:
            raise RunBoundaryError("original request mismatch")
        observations: list[ObservedFact] = []
        seen: set[tuple[str, ...]] = set()
        no_progress = 0
        executions = 0
        used_plan_ids: set[str] = set()
        for ordinal in range(self._budget.max_iterations):
            current_input = binding.iteration_input(original_input, ordinal=ordinal)
            iteration = IterationRef.from_input(binding, current_input, ordinal=ordinal)
            decision = await self._step.decide(
                current_input, iteration, tuple(observations)
            )
            if decision.iteration != iteration:
                raise RunBoundaryError("decision iteration mismatch")
            if decision.kind == "FINISH":
                # A task may finish only AFTER evidence from an approved execution.
                if (
                    not observations
                    or not decision.reason
                    or decision.completion_fact is None
                    or not any(
                        decision.completion_fact in observed.facts
                        for observed in observations
                    )
                ):
                    raise RunBoundaryError("unsupported completion claim")
                return RunOutcome(
                    binding.run_id,
                    RunKind.FINISH,
                    decision.reason,
                    ordinal + 1,
                    executions,
                    tuple(observations),
                )
            if decision.kind in ("WAIT", "BLOCK"):
                return RunOutcome(
                    binding.run_id,
                    RunKind(decision.kind),
                    decision.reason or decision.kind,
                    ordinal + 1,
                    executions,
                    tuple(observations),
                )
            if decision.kind != "ACT":
                raise RunBoundaryError("illegal decision")
            if executions >= self._budget.max_executions:
                return RunOutcome(
                    binding.run_id,
                    RunKind.BLOCK,
                    "EXECUTION_BUDGET",
                    ordinal + 1,
                    executions,
                    tuple(observations),
                )
            plan = decision.approved
            ctx = decision.context
            if type(plan) is not ApprovedActionPlan or ctx is None:
                raise RunBoundaryError("unapproved or context-free action")
            if plan.plan_id in used_plan_ids:
                raise RunBoundaryError("duplicate approved plan must not replay")
            if plan.request_id != iteration.request_id:
                raise RunBoundaryError("plan request mismatch")
            if (
                ctx.identity_context.subject_id != binding.subject_id
                or ctx.identity_context.identity_scope != binding.identity_scope
                or ctx.identity_context.tenant_id != binding.tenant_id
                or ctx.session_context.session_id != binding.session_id
                or ctx.domain_extensions is None
                or ctx.domain_extensions.domain_id != binding.domain_id
            ):
                raise RunBoundaryError("context scope mismatch")
            # Claim identity before any physical attempt; failed attempts must not replay.
            used_plan_ids.add(plan.plan_id)
            observation = await self._step.execute_and_observe(decision)
            executions += 1
            if (
                observation.run_id != binding.run_id
                or observation.request_id != iteration.request_id
                or observation.plan_id != plan.plan_id
                or observation.domain_fingerprint != binding.binding_fingerprint
                or not observation.execution_id
            ):
                raise RunBoundaryError("observation provenance mismatch")
            if not observation.facts:
                return RunOutcome(
                    binding.run_id,
                    RunKind.BLOCK,
                    "EMPTY_OBSERVATION",
                    ordinal + 1,
                    executions,
                    tuple(observations),
                )
            fingerprint = tuple(observation.facts)
            no_progress = no_progress + 1 if fingerprint in seen else 0
            seen.add(fingerprint)
            observations.append(observation)
            if no_progress >= self._budget.max_no_progress:
                return RunOutcome(
                    binding.run_id,
                    RunKind.BLOCK,
                    "NO_PROGRESS",
                    ordinal + 1,
                    executions,
                    tuple(observations),
                )
        return RunOutcome(
            binding.run_id,
            RunKind.BLOCK,
            "ITERATION_BUDGET",
            self._budget.max_iterations,
            executions,
            tuple(observations),
        )
