"""GA-01B Slice 1: observe-driven Agent Loop with real M2/M3/M4 interfaces.

All physical executions and observation decisions remain in a test-only composition.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from agent_core.iteration import AgentRunBinding, IterationRef
from agent_core.runner import (
    AgentRunCoordinator,
    Decision,
    LoopBudget,
    ObservedFact,
    RunBoundaryError,
    RunKind,
)
from runtime.constraint_management import RuntimeConstraintEvaluator
from runtime.contracts import (
    ActionPlanDraft,
    ApprovedActionPlan,
    DomainExtensions,
    RuntimeInput,
)
from runtime.context_building import DefaultContextBuilder
from runtime.contracts.context import ToolContext
from runtime.input_processing import DefaultInputProcessor
from runtime.orchestration.m2_admission import (
    assert_admission_allows_flow,
    evaluate_m2_admission,
)
from runtime.policy_enforcement import DefaultPolicyRechecker
from runtime.policy_management import DefaultPolicyEngine
from runtime.priority_management import PreemptionEngine
from runtime.safety import DefaultSafetyGuard
from runtime.state_management import EngineRuntimeStateProvider
from tests.ga01.sandbox import verify_local_mock
from tests.orchestration_stubs import (
    build_action_plan_draft,
    build_execution_result,
    build_runtime_input,
)
from tests.test_m2_runtime_integration_gate import (
    CallRecorder,
    RequestAwareUnderstandingEngine,
    StaticPrioritySubjectResolver,
    _build_state_engine,
    _incoming,
)


@dataclass
class SandboxTurn:
    """Test-only stage assembly; does NOT use RuntimeOrchestrator.run()."""

    initial: RuntimeInput
    facts: tuple[str, ...] = ("MOCK_EXECUTION_OBSERVED",)

    def __post_init__(self) -> None:
        self.binding = AgentRunBinding.from_input(
            self.initial,
            run_id="loop-fixture",
            domain_id="fixture-domain",
            domain_version="v1",
            binding_fingerprint="fixture-hash",
        )
        self.actions = 0
        self.rounds = 0
        self.visible_observations: list[tuple[str, ...]] = []
        self._recorder = CallRecorder()
        self._understanding = RequestAwareUnderstandingEngine(self._recorder)
        self._safety = DefaultSafetyGuard(rules=[])
        self._policy = DefaultPolicyEngine(rules=[])
        self._constraint = RuntimeConstraintEvaluator(
            policy_engine=self._policy, preemption_engine=PreemptionEngine(rules=[])
        )
        self._resolver = StaticPrioritySubjectResolver(
            current=None, incoming=_incoming()
        )
        self._rechecker = DefaultPolicyRechecker()

    async def decide(
        self,
        current_input: RuntimeInput,
        iteration: IterationRef,
        observations: tuple[ObservedFact, ...],
    ) -> Decision:
        self.rounds += 1
        normalized = await DefaultInputProcessor().process(current_input)
        early = await self._safety.evaluate_early(normalized)
        state = await _build_state_engine(normalized)
        context = await DefaultContextBuilder(
            runtime_state_provider=EngineRuntimeStateProvider(state),
        ).build(normalized, early)
        observed_facts = tuple(f for obs in observations for f in obs.facts)
        self.visible_observations.append(observed_facts)
        context = context.model_copy(
            update={
                "domain_extensions": DomainExtensions(domain_id=self.binding.domain_id),
                "tool_context": ToolContext(
                    recent_tool_results=[{"fact": fact} for fact in observed_facts]
                ),
            }
        )
        understanding = await self._understanding.understand(normalized, context)
        deep = await self._safety.evaluate_deep(
            normalized, context, understanding, early
        )
        constraint = await evaluate_m2_admission(
            runtime_input=normalized,
            runtime_context=context,
            understanding_state=understanding,
            safety_result=deep,
            priority_subject_resolver=self._resolver,
            runtime_constraint_evaluator=self._constraint,
        )
        policy = constraint.policy_decision
        assert_admission_allows_flow(
            constraint=constraint,
            request_id=normalized.request_id,
            policy_decision=policy,
        )
        # Completion is a deterministic fixture predicate over sandbox evidence.
        if (
            context.tool_context is not None
            and context.tool_context.recent_tool_results is not None
            and any(
                result.get("fact") == "GOAL_SATISFIED"
                for result in context.tool_context.recent_tool_results
            )
        ):
            return Decision(
                iteration,
                "FINISH",
                reason="SANDBOX_GOAL_SATISFIED",
                completion_fact="GOAL_SATISFIED",
            )
        draft = build_action_plan_draft().model_copy(
            update={
                "request_id": normalized.request_id,
                "plan_id": f"plan-{normalized.request_id}",
            }
        )
        if not isinstance(draft, ActionPlanDraft):
            raise RunBoundaryError("invalid draft")
        # Adapter test still uses the real Policy Rechecker, never fabricates Approved.
        approved = await self._rechecker.recheck(draft, policy)
        assert isinstance(approved, ApprovedActionPlan)
        return Decision(iteration, "ACT", context=context, approved=approved)

    async def execute_and_observe(self, decision: Decision) -> ObservedFact:
        if decision.approved is None or decision.context is None:
            raise RunBoundaryError("no approved action")
        approved = decision.approved
        self.actions += 1
        # May execute multiple distinct approved plans, never an implicit replay.
        if self.actions > 1 and approved.request_id == self.initial.request_id:
            raise RunBoundaryError("repeated same request")
        execution = build_execution_result().model_copy(
            update={
                "request_id": approved.request_id,
                "plan_id": approved.plan_id,
                "execution_id": f"execution-{approved.request_id}",
            }
        )
        sandbox_observation = verify_local_mock(
            binding=self.binding,
            iteration=decision.iteration,
            context=decision.context,
            approved=approved,
            execution=execution,
        )
        assert sandbox_observation.plan_id == approved.plan_id
        return ObservedFact(
            run_id=self.binding.run_id,
            request_id=approved.request_id,
            plan_id=approved.plan_id,
            execution_id=execution.execution_id,
            domain_fingerprint=self.binding.binding_fingerprint,
            facts=self.facts,
        )


def test_slice1_goal_satisfied_after_single_action_and_second_decision() -> None:
    async def scenario() -> None:
        initial = build_runtime_input(text="find a safe fixture fact")
        step = SandboxTurn(initial, facts=("GOAL_SATISFIED",))
        result = await AgentRunCoordinator(step, LoopBudget()).run(
            initial, step.binding
        )
        assert result.kind is RunKind.FINISH
        assert result.reason == "SANDBOX_GOAL_SATISFIED"
        assert result.executions == 1
        assert result.iterations == 2
        assert step.rounds == 2 and step.actions == 1
        assert step.visible_observations == [(), ("GOAL_SATISFIED",)]

    asyncio.run(scenario())


def test_slice1_observation_changes_completion_behavior() -> None:
    async def scenario() -> None:
        initial = build_runtime_input()
        step = SandboxTurn(initial, facts=("SEARCH_FOUND_BUT_NOT_DONE",))
        result = await AgentRunCoordinator(
            step, LoopBudget(max_iterations=2, max_executions=2)
        ).run(initial, step.binding)
        assert result.kind is RunKind.BLOCK
        assert result.reason in ("NO_PROGRESS", "ITERATION_BUDGET")
        assert result.executions == 2
        assert step.rounds == 2

    asyncio.run(scenario())


def test_slice1_execution_budget_stops_before_second_side_effect() -> None:
    async def scenario() -> None:
        initial = build_runtime_input()
        step = SandboxTurn(initial, facts=("INCOMPLETE",))
        result = await AgentRunCoordinator(
            step, LoopBudget(max_iterations=4, max_executions=1)
        ).run(initial, step.binding)
        assert result.kind is RunKind.BLOCK
        assert result.reason == "EXECUTION_BUDGET"
        assert result.executions == 1 and step.actions == 1

    asyncio.run(scenario())


def test_slice1_invalid_binding_fails_before_any_tool_attempt() -> None:
    async def scenario() -> None:
        initial = build_runtime_input()
        step = SandboxTurn(initial)
        wrong = initial.model_copy(update={"subject_id": "attacker"})
        with pytest.raises((RunBoundaryError, ValueError)):
            await AgentRunCoordinator(step, LoopBudget()).run(wrong, step.binding)
        assert step.actions == 0

    asyncio.run(scenario())
