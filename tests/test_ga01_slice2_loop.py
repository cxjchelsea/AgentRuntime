"""End-to-end MODEL-BOUNDARY-driven Agent loop with actual M4 approvals.

Mock model and Mock Tool are test-only; production M6 stays deny-only.
"""

from __future__ import annotations

import asyncio

from agent_core.model_adapter import StructuredStrategyTransportAdapter
from agent_core.runner import (
    AgentRunCoordinator,
    Decision,
    LoopBudget,
    ObservedFact,
    RunKind,
)
from runtime.contracts import RuntimeContext, RuntimeInput, UnderstandingState
from runtime.contracts.context import InteractionContext
from runtime.contracts.enums import ProcessingPath
from runtime.contracts.understanding import GoalUnderstanding
from tests.orchestration_stubs import build_runtime_input
from tests.test_ga01_slice1 import SandboxTurn
from tests.test_ga01_slice2 import ObservationSensitiveFakeTransport
from tests.test_ga01_slice2_m4 import _build_model_planner
from tests.test_m2_runtime_integration_gate import RequestAwareUnderstandingEngine


class GoalAwareUnderstanding(RequestAwareUnderstandingEngine):
    """Request-aware M3 fixture with a generic goal and non-degraded routing."""

    async def understand(
        self, runtime_input: RuntimeInput, runtime_context: RuntimeContext
    ) -> UnderstandingState:
        result = await super().understand(runtime_input, runtime_context)
        return result.model_copy(
            update={
                "metadata": result.metadata.model_copy(
                    update={"processing_path": ProcessingPath.FAST_PATH}
                ),
                "goal": GoalUnderstanding(explicit_goal="DOMAIN_GOAL", confidence=1.0),
            }
        )


class ModelDrivenSandboxTurn(SandboxTurn):
    def __post_init__(self) -> None:
        super().__post_init__()
        self.fake_model = ObservationSensitiveFakeTransport()
        fixture = _build_model_planner(
            StructuredStrategyTransportAdapter(self.fake_model)
        )
        self._understanding = GoalAwareUnderstanding(self._recorder)
        self._planner = fixture.planner
        self._validator = fixture.validator
        self._rechecker = fixture.rechecker
        self.selected_actions: list[str] = []

    def model_observation_projection(
        self, observations: tuple[ObservedFact, ...]
    ) -> InteractionContext | None:
        if not observations:
            return None
        last = observations[-1]
        if (
            last.run_id != self.binding.run_id
            or last.domain_fingerprint != self.binding.binding_fingerprint
            or not last.execution_id
        ):
            raise ValueError("observation not from bound sandbox run")
        # Explicit test-only narrow projection; no raw ToolResult to the model.
        return InteractionContext(last_agent_action=last.facts[-1])

    async def execute_and_observe(self, decision: Decision) -> ObservedFact:
        if decision.approved is None or len(decision.approved.steps) != 1:
            raise ValueError("one approved sandbox action required")
        action = decision.approved.steps[0].action
        self.selected_actions.append(action)
        if action == "DOMAIN_ACTION_A":
            self.facts = ("MOCK_FOUND_NEEDS_VERIFICATION",)
        elif action == "DOMAIN_ACTION_B":
            self.facts = ("GOAL_SATISFIED",)
        else:
            raise ValueError("unregistered sandbox action")
        return await super().execute_and_observe(decision)


def test_slice2_two_model_selected_actions_then_verified_finish() -> None:
    async def scenario() -> None:
        initial = build_runtime_input(text="find then verify a safe sandbox fact")
        step = ModelDrivenSandboxTurn(initial)
        result = await AgentRunCoordinator(
            step,
            LoopBudget(max_iterations=4, max_executions=3),
        ).run(initial, step.binding)
        assert result.kind is RunKind.FINISH
        assert result.executions == 2
        assert result.iterations == 3
        assert step.selected_actions == ["DOMAIN_ACTION_A", "DOMAIN_ACTION_B"]
        assert len(step.fake_model.calls) == 2
        assert step.fake_model.calls[0]["last_agent_action"] is None
        assert step.fake_model.calls[1]["last_agent_action"] == (
            "MOCK_FOUND_NEEDS_VERIFICATION"
        )
        assert result.observations[0].facts == ("MOCK_FOUND_NEEDS_VERIFICATION",)
        assert result.observations[1].facts == ("GOAL_SATISFIED",)

    asyncio.run(scenario())
