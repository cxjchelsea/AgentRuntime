"""GA-04 cross-domain evaluation: bounded real LLM with domain-owned context.

Offline tests verify composition and no-model WAIT. Real provider E2E is
strictly opt-in via GA04_LIVE_OPT_IN=1 and GA01C_LLM_URL/MODEL.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from agent_core.chat_transport import ChatCompletionsConfig
from agent_core.model_adapter import StructuredStrategyTransportAdapter
from agent_core.runner import AgentRunCoordinator, LoopBudget, RunKind
from tests.ga03_domain_content_assembly import SandboxDomainKnowledge
from tests.ga04_domain_real_transport import (
    DomainAwareRealTransport,
    domain_system_instruction,
)
from tests.orchestration_stubs import build_runtime_input
from tests.test_ga02_d4_two_domain_m4_e2e import _planner
from tests.test_ga03_domain_prompt_rule_knowledge_e2e import (
    _CASES,
    GA03Turn,
    _load_case,
)

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="GA04 uses the Linux-only D2-A local FD package loader",
)


class RealDomainTurn(GA03Turn):
    def __init__(
        self,
        initial,
        content: SandboxDomainKnowledge,
        *,
        available: frozenset[str],
        config: ChatCompletionsConfig,
    ) -> None:
        super().__init__(initial, content, available=available)
        self.real_transport = DomainAwareRealTransport(config, content)
        self._planner, self._validator, self._rechecker = _planner(
            content.m4, StructuredStrategyTransportAdapter(self.real_transport)
        )


def _config() -> ChatCompletionsConfig:
    return ChatCompletionsConfig(
        endpoint=os.environ["GA01C_LLM_URL"],
        model=os.environ["GA01C_LLM_MODEL"],
        api_key=os.environ.get("GA01C_LLM_API_KEY", ""),
        timeout_seconds=45,
        max_tokens=192,
    )


def _live_opt_in() -> bool:
    return (
        os.environ.get("GA04_LIVE_OPT_IN") == "1"
        and bool(os.environ.get("GA01C_LLM_URL"))
        and bool(os.environ.get("GA01C_LLM_MODEL"))
    )


@pytest.mark.parametrize("case", _CASES, ids=["inventory", "learning"])
def test_ga04_distinct_domain_instructions_and_candidates(
    tmp_path: Path, case: tuple[str, ...]
) -> None:
    domain = _load_case(tmp_path, case)
    instruction = domain_system_instruction(domain)
    assert domain.prompt_focus in instruction
    assert domain.m4.collect_strategy in instruction
    assert domain.m4.verify_strategy in instruction
    assert domain.knowledge_fact in instruction
    assert domain.m4.binding.domain_id in instruction
    assert "legal_strategy_ids" in instruction
    assert "never call tools" in instruction


def test_ga04_domain_context_is_not_interchangeable(tmp_path: Path) -> None:
    a_root = tmp_path / "stock"
    a_root.mkdir()
    b_root = tmp_path / "notes"
    b_root.mkdir()
    first = _load_case(a_root, _CASES[0])
    second = _load_case(b_root, _CASES[1])
    a_instruction = domain_system_instruction(first)
    b_instruction = domain_system_instruction(second)
    assert a_instruction != b_instruction
    assert first.knowledge_fact not in b_instruction
    assert second.knowledge_fact not in a_instruction
    assert first.m4.collect_action not in b_instruction
    assert second.m4.collect_action not in a_instruction


def test_ga04_absent_knowledge_waits_without_real_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Presence of a configured endpoint MUST NOT override the evidence gate.
    monkeypatch.setenv("GA01C_LLM_URL", "http://127.0.0.1:9/v1/chat/completions")
    monkeypatch.setenv("GA01C_LLM_MODEL", "synthetic-config-only")
    domain = _load_case(tmp_path, _CASES[0])
    initial = build_runtime_input(text="stock task missing knowledge")
    turn = RealDomainTurn(
        initial,
        domain,
        available=frozenset({"notes.index"}),
        config=_config(),
    )
    result = asyncio.run(
        AgentRunCoordinator(turn, LoopBudget()).run(initial, turn.binding)
    )
    assert result.kind is RunKind.WAIT
    assert result.executions == 0
    assert turn.real_transport.calls == []
    assert turn.mock_calls == 0


@pytest.mark.skipif(
    not _live_opt_in(),
    reason="opt-in GA04_LIVE_OPT_IN and GA01C model endpoint/model required",
)
def test_ga04_real_model_cross_domain_repeated_e2e(tmp_path: Path) -> None:
    """Model chooses legal M4 strategy itself; tools remain deterministic mocks.

    First model action must be collect, second (inventory only) verify.
    Each of 3 rounds covers both domains; no fake structured model output.
    """

    async def evaluate() -> None:
        config = _config()
        for repeat in range(3):
            for case in _CASES:
                root = tmp_path / f"run-{repeat}-{case[1]}"
                root.mkdir()
                domain = _load_case(root, case)
                initial = build_runtime_input(text=case[2])
                turn = RealDomainTurn(
                    initial,
                    domain,
                    available=frozenset({domain.knowledge_key}),
                    config=config,
                )
                outcome = await AgentRunCoordinator(
                    turn,
                    LoopBudget(
                        max_iterations=4,
                        max_executions=3,
                        max_decision_seconds=65,
                        max_execution_seconds=5,
                    ),
                ).run(initial, turn.binding)
                expected = 2 if domain.completion_after == "verify" else 1
                assert outcome.kind is RunKind.FINISH
                assert outcome.executions == expected
                assert turn.selected_actions == [
                    domain.m4.collect_action,
                    *([domain.m4.verify_action] if expected == 2 else []),
                ]
                assert len(turn.real_transport.calls) == expected
                assert outcome.observations[-1].facts == ("GOAL_SATISFIED",)

    asyncio.run(evaluate())
