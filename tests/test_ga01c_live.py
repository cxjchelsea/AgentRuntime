"""GA-01C sandbox provenance projection and opt-in real provider E2E."""

from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from typing import Any, cast

import pytest

from agent_core.chat_transport import (
    ChatCompletionsConfig,
    ChatCompletionsStrategyTransport,
)
from agent_core.iteration import AgentRunBinding
from agent_core.model_adapter import StructuredStrategyTransportAdapter
from agent_core.runner import AgentRunCoordinator, LoopBudget, ObservedFact, RunKind
from tests.ga01.projector import (
    SandboxObservationProjector,
    SandboxProjectionError,
)
from tests.orchestration_stubs import build_runtime_input
from tests.test_ga01_slice2_loop import ModelDrivenSandboxTurn
from tests.test_ga01_slice2_m4 import _build_model_planner


def _binding_and_observation() -> tuple[AgentRunBinding, ObservedFact]:
    original = build_runtime_input(text="safe sandbox question")
    binding = AgentRunBinding.from_input(
        original,
        run_id="projection-run",
        domain_id="fixture-domain",
        domain_version="v1",
        binding_fingerprint="fingerprint-v1",
    )
    evidence = ObservedFact(
        run_id="projection-run",
        request_id="req-1",
        plan_id="approved-plan-1",
        execution_id="mock-exec-1",
        domain_fingerprint="fingerprint-v1",
        facts=("OBSERVED_SEARCH_RESULT",),
    )
    return binding, evidence


def test_projector_accepts_only_registered_run_scoped_facts() -> None:
    binding, observation = _binding_and_observation()
    projector = SandboxObservationProjector(
        {"OBSERVED_SEARCH_RESULT": "MOCK_FOUND_NEEDS_VERIFICATION"}
    )
    result = projector.project(binding, (observation,))
    assert result is not None
    assert result.last_agent_action == "MOCK_FOUND_NEEDS_VERIFICATION"
    assert projector.project(binding, ()) is None


@pytest.mark.parametrize(
    "change",
    [
        {"run_id": "other-run"},
        {"domain_fingerprint": "other-domain-binding"},
        {"plan_id": ""},
        {"execution_id": ""},
        {"facts": ("IGNORE_SYSTEM_POLICY",)},
        {"facts": ("OBSERVED_SEARCH_RESULT", "UNEXPECTED")},
    ],
)
def test_projector_rejects_forged_or_unrecognized_evidence(
    change: dict[str, object],
) -> None:
    binding, observation = _binding_and_observation()
    projector = SandboxObservationProjector(
        {"OBSERVED_SEARCH_RESULT": "MOCK_FOUND_NEEDS_VERIFICATION"}
    )
    with pytest.raises(SandboxProjectionError):
        projector.project(binding, (replace(observation, **cast(Any, change)),))


def test_projector_rejects_duplicate_execution_evidence() -> None:
    binding, observation = _binding_and_observation()
    projector = SandboxObservationProjector(
        {"OBSERVED_SEARCH_RESULT": "MOCK_FOUND_NEEDS_VERIFICATION"}
    )
    with pytest.raises(SandboxProjectionError, match="provenance"):
        projector.project(binding, (observation, observation))


class LiveSandboxTurn(ModelDrivenSandboxTurn):
    def __post_init__(self) -> None:
        super().__post_init__()
        config = ChatCompletionsConfig(
            endpoint=os.environ["GA01C_LLM_URL"],
            model=os.environ["GA01C_LLM_MODEL"],
            api_key=os.environ.get("GA01C_LLM_API_KEY", ""),
        )
        planning = _build_model_planner(
            StructuredStrategyTransportAdapter(ChatCompletionsStrategyTransport(config))
        )
        self._planner = planning.planner
        self._validator = planning.validator
        self._rechecker = planning.rechecker
        self.projector = SandboxObservationProjector(
            {
                "MOCK_FOUND_NEEDS_VERIFICATION": "MOCK_FOUND_NEEDS_VERIFICATION",
                "GOAL_SATISFIED": "GOAL_SATISFIED",
            }
        )

    def model_observation_projection(self, observations: tuple[ObservedFact, ...]):
        return self.projector.project(self.binding, observations)


@pytest.mark.skipif(
    os.environ.get("GA01C_LIVE_OPT_IN") != "1"
    or not all(
        os.environ.get(name)
        for name in ("GA01C_LLM_URL", "GA01C_LLM_MODEL", "GA01C_LLM_API_KEY")
    ),
    reason="real LLM credentials and explicit opt-in are required",
)
def test_live_provider_drives_two_approved_mock_actions() -> None:
    """Actual HTTPS model requests; all task tools remain local deterministic mocks."""

    async def scenario() -> None:
        original = build_runtime_input(text="find and verify a safe sandbox fact")
        step = LiveSandboxTurn(original)
        outcome = await AgentRunCoordinator(
            step,
            LoopBudget(
                max_iterations=4,
                max_executions=2,
                max_decision_seconds=35.0,
                max_execution_seconds=5.0,
            ),
        ).run(original, step.binding)
        assert outcome.kind is RunKind.FINISH
        assert outcome.executions == 2
        assert step.selected_actions == ["DOMAIN_ACTION_A", "DOMAIN_ACTION_B"]
        assert outcome.observations[-1].facts == ("GOAL_SATISFIED",)

    asyncio.run(scenario())
