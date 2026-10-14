"""Medical subdomain switching acceptance, using nonclinical synthetic fixtures.

This tests host-scoped domain package substitution and M4 isolation only.
It is not validation of clinical reasoning, advice, or crisis handling.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from agent_core.model_adapter import StructuredStrategyTransportAdapter
from agent_core.runner import AgentRunCoordinator, LoopBudget, RunKind
from runtime.planning.errors import StrategyModelOutputError
from tests.orchestration_stubs import build_runtime_input
from tests.test_ga02_d4_two_domain_m4_e2e import DomainDrivenTurn, _load, _planner

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="verified domain-package loader requires Linux",
)

DOMAINS = (
    ("medical.chronic_management", "monitoring"),
    ("medical.mental_wellbeing", "wellbeing"),
)


@pytest.mark.parametrize(("domain_id", "noun"), DOMAINS)
def test_medical_domain_uses_same_unchanged_core_and_approved_loop(
    tmp_path: Path, domain_id: str, noun: str
) -> None:
    """Each synthetic domain binds distinct assets; real M4 and Agent loop run."""
    async def scenario() -> None:
        package = _load(tmp_path, domain_id, noun)
        initial = build_runtime_input(text=f"collect and verify synthetic {noun} data")
        turn = DomainDrivenTurn(initial, package)
        result = await AgentRunCoordinator(
            turn, LoopBudget(max_iterations=4, max_executions=3)
        ).run(initial, turn.binding)
        assert result.kind is RunKind.FINISH
        assert result.executions == 2
        assert turn.selected_actions == [f"collect-{noun}", f"verify-{noun}"]
        assert set(turn.transport.calls[0]["candidate_action_ids"]) == {
            f"collect-{noun}", f"verify-{noun}"
        }
        assert all(
            item.domain_fingerprint == turn.binding.binding_fingerprint
            for item in result.observations
        )

    asyncio.run(scenario())


def test_cross_medical_domain_switch_is_isolated(tmp_path: Path) -> None:
    """Switching domains creates a new pinned package, not shared actions."""
    (tmp_path / "chronic").mkdir()
    (tmp_path / "mental").mkdir()
    chronic = _load(tmp_path / "chronic", *DOMAINS[0])
    mental = _load(tmp_path / "mental", *DOMAINS[1])

    assert chronic.binding.domain_id != mental.binding.domain_id
    assert chronic.binding.binding_fingerprint != mental.binding.binding_fingerprint
    assert {chronic.collect_action, chronic.verify_action}.isdisjoint(
        {mental.collect_action, mental.verify_action}
    )
    assert {chronic.collect_strategy, chronic.verify_strategy}.isdisjoint(
        {mental.collect_strategy, mental.verify_strategy}
    )


@pytest.mark.parametrize(("selected", "foreign"), [(0, 1), (1, 0)])
def test_medical_domain_denies_foreign_action_before_execution(
    tmp_path: Path, selected: int, foreign: int
) -> None:
    """Both directions block the other domain's action at M4 validation."""
    async def scenario() -> None:
        selected_id, noun = DOMAINS[selected]
        _, foreign_noun = DOMAINS[foreign]
        package = _load(tmp_path, selected_id, noun)
        initial = build_runtime_input(text=f"inspect synthetic {noun}")
        turn = DomainDrivenTurn(initial, package)

        async def prohibited(_payload: dict[str, object]) -> dict[str, object]:
            return {
                "strategy_id": f"collect-strategy-{noun}",
                "action_ids": [f"collect-{foreign_noun}"],
                "reason_code": "CROSS_MEDICAL_DOMAIN_ACTION",
            }

        turn._planner, turn._validator, turn._rechecker = _planner(
            package, StructuredStrategyTransportAdapter(prohibited)
        )
        with pytest.raises(StrategyModelOutputError, match="outside the legal"):
            await AgentRunCoordinator(
                turn, LoopBudget(max_iterations=4, max_executions=3)
            ).run(initial, turn.binding)
        assert turn.mock_calls == 0
        assert turn.selected_actions == []

    asyncio.run(scenario())
