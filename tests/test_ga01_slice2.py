"""GA-01B Slice 2: structured model choices are observation-sensitive AND legal.

This is a deterministic fake *model transport* replacing an external LLM.
No API calls, production positive M6 grant or real tools are involved.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest

from agent_core.model_adapter import StructuredStrategyTransportAdapter
from runtime.contracts.context import InteractionContext
from runtime.contracts.enums import PlanningMode
from runtime.planning import HybridStrategySelector, StrategyModelOutputError
from tests.orchestration_stubs import build_policy_decision, build_runtime_context
from tests.test_m4_candidate_strategy_selection import (
    _candidate,
    _goals,
    _strategy_registry,
    _understanding,
)


class ObservationSensitiveFakeTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, payload: dict[str, Any]) -> Mapping[str, object]:
        self.calls.append(payload)
        # A real provider would determine this from prompt/context.
        # This fixture proves differing observations reach the model boundary.
        changed = payload["last_agent_action"] == "MOCK_FOUND_NEEDS_VERIFICATION"
        strategy = "DOMAIN_STRATEGY_B" if changed else "DOMAIN_STRATEGY_A"
        action = "DOMAIN_ACTION_B" if changed else "DOMAIN_ACTION_A"
        return {
            "strategy_id": strategy,
            "action_ids": [action],
            "confidence": 0.92,
            "reason_code": "SANDBOX_MODEL_CHOICE",
        }


def _run_soft_selection(
    model: StructuredStrategyTransportAdapter,
    *,
    observation: str | None = None,
):
    understanding = _understanding()
    context = build_runtime_context().model_copy(
        update={
            "interaction_context": InteractionContext(last_agent_action=observation)
        }
    )
    return HybridStrategySelector(
        strategy_registry=_strategy_registry(),
        model=model,
    ).select(
        planning_mode=PlanningMode.AGENT_PLANNED,
        runtime_context=context,
        understanding_state=understanding,
        goals=_goals(understanding, context=context),
        candidates=(_candidate("DOMAIN_ACTION_A"), _candidate("DOMAIN_ACTION_B")),
        policy_decision=build_policy_decision(),
        available_capability_ids=frozenset(),
    )


def test_model_receives_observation_projection_and_changes_legal_action() -> None:
    async def scenario() -> None:
        fake = ObservationSensitiveFakeTransport()
        model = StructuredStrategyTransportAdapter(fake)
        before = await _run_soft_selection(model)
        after = await _run_soft_selection(
            model, observation="MOCK_FOUND_NEEDS_VERIFICATION"
        )
        assert before.selection_path == "MODEL"
        assert after.selection_path == "MODEL"
        assert before.selected_action_ids == ("DOMAIN_ACTION_A",)
        assert after.selected_action_ids == ("DOMAIN_ACTION_B",)
        assert len(fake.calls) == 2
        assert fake.calls[0]["last_agent_action"] is None
        assert fake.calls[1]["last_agent_action"] == "MOCK_FOUND_NEEDS_VERIFICATION"
        assert set(fake.calls[1]["legal_strategy_ids"]) == {
            "DOMAIN_STRATEGY_A",
            "DOMAIN_STRATEGY_B",
        }
        assert "recent_tool_results" not in fake.calls[1]
        assert "identity_context" not in fake.calls[1]
        assert "tool_context" not in fake.calls[1]

    asyncio.run(scenario())


def test_model_cannot_invent_tool_or_strategy() -> None:
    async def invalid(_payload: dict[str, Any]) -> Mapping[str, object]:
        return {
            "strategy_id": "INVENTED_STRATEGY",
            "action_ids": ["INVENTED_TOOL"],
            "grant": True,
        }

    with pytest.raises(StrategyModelOutputError):
        asyncio.run(_run_soft_selection(StructuredStrategyTransportAdapter(invalid)))


def test_model_transport_failure_is_fail_closed() -> None:
    async def offline(_payload: dict[str, Any]) -> Mapping[str, object]:
        raise ConnectionError("simulated offline provider")

    with pytest.raises(Exception, match="strategy model execution failed"):
        asyncio.run(_run_soft_selection(StructuredStrategyTransportAdapter(offline)))


def test_model_transport_rejects_non_mapping() -> None:
    async def invalid(_payload: dict[str, Any]) -> Mapping[str, object]:
        return {}  # Test invalid model choice shape through existing M4 validator

    with pytest.raises(StrategyModelOutputError):
        asyncio.run(
            _run_soft_selection(StructuredStrategyTransportAdapter(invalid))
        )


def test_adapter_itself_does_not_call_transport_for_non_model_path() -> None:
    from tests.test_m4_candidate_strategy_selection import StaticStrategyRule

    async def scenario() -> None:
        fake = ObservationSensitiveFakeTransport()
        model = StructuredStrategyTransportAdapter(fake)
        understanding = _understanding()
        selector = HybridStrategySelector(
            strategy_registry=_strategy_registry(),
            rules=(StaticStrategyRule("DOMAIN_STRATEGY_A"),),
            model=model,
        )
        result = await selector.select(
            planning_mode=PlanningMode.AGENT_PLANNED,
            runtime_context=build_runtime_context(),
            understanding_state=understanding,
            goals=_goals(understanding),
            candidates=(_candidate("DOMAIN_ACTION_A"), _candidate("DOMAIN_ACTION_B")),
            policy_decision=build_policy_decision(),
            available_capability_ids=frozenset(),
        )
        assert result.selection_path == "RULE"
        assert fake.calls == []

    asyncio.run(scenario())
