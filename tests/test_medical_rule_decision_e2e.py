"""Domain-owned synthetic medical rules change actual Agent decisions, not clinical advice."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from agent_core.runner import AgentRunCoordinator, LoopBudget, RunKind
from tests.orchestration_stubs import build_runtime_input
from tests.test_ga03_domain_prompt_rule_knowledge_e2e import GA03Turn, _load_case

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="verified fixture loader requires Linux",
)


@pytest.mark.parametrize(
    ("domain_id", "expected_actions", "expected_rule"),
    [
        ("medical.chronic-management", 2, "verify"),
        ("medical.mental-wellbeing", 1, "collect"),
    ],
)
def test_medical_package_rule_changes_approved_agent_execution(
    tmp_path: Path, domain_id: str, expected_actions: int, expected_rule: str
) -> None:
    async def scenario() -> None:
        domain = _load_case(
            tmp_path,
            (
                domain_id,
                "monitoring" if expected_actions == 2 else "wellbeing",
                "Review synthetic medical information without giving advice",
                "metric-guide" if expected_actions == 2 else "wellbeing-guide",
                "Synthetic domain guidance only, not clinical recommendations",
                expected_rule,
            ),
        )
        assert domain.completion_after == expected_rule
        initial = build_runtime_input(text="synthetic domain-specific task")
        turn = GA03Turn(initial, domain, available=frozenset({domain.knowledge_key}))
        outcome = await AgentRunCoordinator(
            turn, LoopBudget(max_iterations=4, max_executions=3)
        ).run(initial, turn.binding)
        assert outcome.kind is RunKind.FINISH
        assert outcome.executions == expected_actions
        assert len(turn.ga03_transport.calls) == expected_actions
        assert turn.selected_actions == [
            domain.m4.collect_action,
            *([domain.m4.verify_action] if expected_actions == 2 else []),
        ]
        assert turn.ga03_transport.projections == [
            (domain.prompt_focus, (domain.knowledge_fact,))
        ] * expected_actions

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "domain_id",
    ["medical.chronic-management", "medical.mental-wellbeing"],
)
def test_missing_own_medical_knowledge_blocks_action_before_m4(
    tmp_path: Path, domain_id: str
) -> None:
    async def scenario() -> None:
        chronic = domain_id == "medical.chronic-management"
        domain = _load_case(
            tmp_path,
            (
                domain_id,
                "monitoring" if chronic else "wellbeing",
                "Review synthetic medical information without giving advice",
                "metric-guide" if chronic else "wellbeing-guide",
                "Synthetic domain guidance only, not clinical recommendations",
                "verify" if chronic else "collect",
            ),
        )
        initial = build_runtime_input(text="synthetic task with unavailable knowledge")
        turn = GA03Turn(initial, domain, available=frozenset({"foreign.topic"}))
        outcome = await AgentRunCoordinator(
            turn, LoopBudget(max_iterations=4, max_executions=3)
        ).run(initial, turn.binding)
        assert outcome.kind is RunKind.WAIT
        assert outcome.reason == "GA03_REQUIRED_KNOWLEDGE_MISSING"
        assert outcome.executions == 0
        assert turn.ga03_transport.calls == []
        assert turn.mock_calls == 0

    asyncio.run(scenario())
