"""GA-01B Slice 1: observe-driven Agent Loop with real M2/M3/M4 interfaces.

All physical executions and observation decisions remain in a test-only composition.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import cast

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
from runtime.context_building import DefaultContextBuilder
from runtime.contracts import (
    ActionPlanDraft,
    ApprovedActionPlan,
    DomainExtensions,
    RuntimeInput,
)
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
from tests.ga01.sandbox import LocalMockExecutionEngine, verify_local_mock
from tests.orchestration_stubs import (
    StubPlanValidator,
    build_action_plan_draft,
    build_execution_result,
    build_runtime_context,
    build_runtime_input,
)
from tests.test_m2_runtime_integration_gate import (
    CallRecorder,
    RequestAwarePlanner,
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
        self._planner = RequestAwarePlanner(self._recorder)
        self._validator = StubPlanValidator(self._recorder)
        self._rechecker = DefaultPolicyRechecker()
        self.mock_calls = 0

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
        draft = await self._planner.plan(context, understanding, policy)
        # Test fixture: enforce a unique plan identity across internal turns.
        draft = draft.model_copy(update={"plan_id": f"plan-{normalized.request_id}"})
        if not isinstance(draft, ActionPlanDraft):
            raise RunBoundaryError("invalid draft")
        validated = await self._validator.validate(draft)
        approved = await self._rechecker.recheck(validated, policy)
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
        engine = LocalMockExecutionEngine(execution)
        observed_execution = await engine.execute(approved, decision.context)
        self.mock_calls += engine.call_count
        sandbox_observation = verify_local_mock(
            binding=self.binding,
            iteration=decision.iteration,
            context=decision.context,
            approved=approved,
            execution=observed_execution,
            facts=self.facts,
        )
        assert sandbox_observation.plan_id == approved.plan_id
        return ObservedFact(
            run_id=self.binding.run_id,
            request_id=approved.request_id,
            plan_id=approved.plan_id,
            execution_id=execution.execution_id,
            domain_fingerprint=self.binding.binding_fingerprint,
            facts=sandbox_observation.facts,
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
        assert step.mock_calls == 1
        assert step._recorder.entries.count("PLAN") == 1
        assert step._recorder.entries.count("PLAN_VALIDATE") == 1
        assert step.visible_observations == [(), ("GOAL_SATISFIED",)]

    asyncio.run(scenario())


def test_slice1_observation_changes_completion_behavior() -> None:
    async def scenario() -> None:
        initial = build_runtime_input(text="find a safe fixture fact")
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
        initial = build_runtime_input(text="find a safe fixture fact")
        step = SandboxTurn(initial, facts=("INCOMPLETE",))
        result = await AgentRunCoordinator(
            step, LoopBudget(max_iterations=4, max_executions=1)
        ).run(initial, step.binding)
        assert result.kind is RunKind.BLOCK
        assert result.reason == "EXECUTION_BUDGET"
        assert result.executions == 1 and step.actions == 1

    asyncio.run(scenario())


def test_slice1_draft_cannot_enter_execution_even_with_fake_step() -> None:
    class UnauthorizedStep:
        calls = 0

        async def decide(
            self,
            current_input: RuntimeInput,
            iteration: IterationRef,
            observations: tuple[ObservedFact, ...],
        ) -> Decision:
            del current_input, observations
            # Malicious adapter abuses Python's runtime typing. Coordinator must reject it.
            return Decision(
                iteration,
                "ACT",
                context=build_runtime_context(),
                approved=cast(ApprovedActionPlan, build_action_plan_draft()),
            )

        async def execute_and_observe(self, decision: Decision) -> ObservedFact:
            self.calls += 1
            raise AssertionError("draft must never execute")

    async def scenario() -> None:
        initial = build_runtime_input(text="task fixture")
        binding = AgentRunBinding.from_input(
            initial,
            run_id="draft-block",
            domain_id="fixture-domain",
            domain_version="v1",
            binding_fingerprint="fixture-hash",
        )
        step = UnauthorizedStep()
        with pytest.raises(RunBoundaryError, match="unapproved"):
            await AgentRunCoordinator(step, LoopBudget()).run(initial, binding)
        assert step.calls == 0

    asyncio.run(scenario())


def test_slice1_invalid_binding_fails_before_any_tool_attempt() -> None:
    async def scenario() -> None:
        initial = build_runtime_input(text="find a safe fixture fact")
        step = SandboxTurn(initial)
        wrong = initial.model_copy(update={"subject_id": "attacker"})
        with pytest.raises((RunBoundaryError, ValueError)):
            await AgentRunCoordinator(step, LoopBudget()).run(wrong, step.binding)
        assert step.actions == 0

    asyncio.run(scenario())


def test_slice1_finish_without_matching_verified_fact_is_blocked() -> None:
    class UnsupportedCompletion:
        calls = 0

        async def decide(
            self,
            current_input: RuntimeInput,
            iteration: IterationRef,
            observations: tuple[ObservedFact, ...],
        ) -> Decision:
            del current_input, observations
            return Decision(
                iteration,
                "FINISH",
                reason="MODEL_SAID_DONE",
                completion_fact="NOT_OBSERVED",
            )

        async def execute_and_observe(self, decision: Decision) -> ObservedFact:
            self.calls += 1
            raise AssertionError("no tool expected")

    async def scenario() -> None:
        initial = build_runtime_input(text="fixture goal")
        binding = AgentRunBinding.from_input(
            initial,
            run_id="no-finish",
            domain_id="fixture-domain",
            domain_version="v1",
            binding_fingerprint="fixture-hash",
        )
        step = UnsupportedCompletion()
        with pytest.raises(RunBoundaryError, match="unsupported completion"):
            await AgentRunCoordinator(step, LoopBudget()).run(initial, binding)
        assert step.calls == 0

    asyncio.run(scenario())


def test_slice1_decision_timeout_never_calls_executor() -> None:
    class SlowDecision:
        calls = 0

        async def decide(
            self,
            current_input: RuntimeInput,
            iteration: IterationRef,
            observations: tuple[ObservedFact, ...],
        ) -> Decision:
            del current_input, iteration, observations
            await asyncio.sleep(1)
            raise AssertionError("unreachable")

        async def execute_and_observe(self, decision: Decision) -> ObservedFact:
            self.calls += 1
            raise AssertionError("unreachable")

    async def scenario() -> None:
        initial = build_runtime_input(text="fixture goal")
        binding = AgentRunBinding.from_input(
            initial,
            run_id="decision-timeout",
            domain_id="fixture-domain",
            domain_version="v1",
            binding_fingerprint="fixture-hash",
        )
        step = SlowDecision()
        with pytest.raises(RunBoundaryError, match="decision timed out"):
            await AgentRunCoordinator(step, LoopBudget(max_decision_seconds=0.001)).run(
                initial, binding
            )
        assert step.calls == 0

    asyncio.run(scenario())


def test_slice1_execution_timeout_remains_unknown_and_never_finishes() -> None:
    class SlowMock(SandboxTurn):
        async def execute_and_observe(self, decision: Decision) -> ObservedFact:
            self.actions += 1
            await asyncio.sleep(1)
            raise AssertionError("unreachable")

    async def scenario() -> None:
        initial = build_runtime_input(text="fixture goal")
        step = SlowMock(initial)
        with pytest.raises(RunBoundaryError, match="outcome UNKNOWN"):
            await AgentRunCoordinator(
                step, LoopBudget(max_execution_seconds=0.001)
            ).run(initial, step.binding)
        assert step.actions == 1
        assert step.rounds == 1

    asyncio.run(scenario())


def test_slice1_cancellation_propagates_without_finish() -> None:
    class CancelledMock(SandboxTurn):
        async def execute_and_observe(self, decision: Decision) -> ObservedFact:
            self.actions += 1
            raise asyncio.CancelledError()

    async def scenario() -> None:
        initial = build_runtime_input(text="fixture goal")
        step = CancelledMock(initial)
        with pytest.raises(asyncio.CancelledError):
            await AgentRunCoordinator(step, LoopBudget()).run(initial, step.binding)
        assert step.actions == 1

    asyncio.run(scenario())
