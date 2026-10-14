"""General Agent product validation: third domain, unchanged Core and M4.

Synthetic research evidence is deliberately NOT a production retrieval claim.
Acceptance is a predeclared, bounded test of domain substitution and authorization.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from agent_core.chat_transport import (
    ChatCompletionsConfig,
    ChatCompletionsStrategyTransport,
)
from agent_core.model_adapter import StructuredStrategyTransportAdapter
from agent_core.runner import AgentRunCoordinator, LoopBudget, RunKind
from runtime.planning.errors import StrategyModelOutputError
from tests.orchestration_stubs import build_runtime_input
from tests.test_ga02_d4_two_domain_m4_e2e import (
    DomainDrivenTurn,
    _load,
    _planner,
)

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Verified package loader Linux-only"
)

DOMAIN = "research.evidence"
NOUN = "sources"


@pytest.mark.parametrize(
    "task_text",
    [
        "Collect research sources and independently verify the references",
        "Prepare a research note with source verification before summarizing",
        "Check the evidence for a disputed claim using the source tools",
    ],
)
def test_third_domain_runs_real_core_m4_and_two_package_tools(
    tmp_path: Path, task_text: str
) -> None:
    async def scenario() -> None:
        package = _load(tmp_path, DOMAIN, NOUN)
        initial = build_runtime_input(text=task_text)
        step = DomainDrivenTurn(initial, package)
        outcome = await AgentRunCoordinator(
            step, LoopBudget(max_iterations=4, max_executions=3)
        ).run(initial, step.binding)
        assert outcome.kind is RunKind.FINISH
        assert step.selected_actions == ["collect-sources", "verify-sources"]
        assert outcome.executions == 2
        assert len(step.transport.calls[0]["candidate_action_ids"]) == 2
        assert len(step.transport.calls[0]["legal_strategy_ids"]) == 2
        assert all(
            obs.domain_fingerprint == package.binding.binding_fingerprint
            for obs in outcome.observations
        )

    asyncio.run(scenario())


def test_third_domain_rejects_foreign_action_and_invalid_evidence(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        package = _load(tmp_path, DOMAIN, NOUN)
        initial = build_runtime_input(text="Investigate a claim")
        step = DomainDrivenTurn(initial, package)

        async def foreign(_payload: dict[str, object]) -> dict[str, object]:
            return {
                "strategy_id": "collect-strategy-sources",
                "action_ids": ["collect-stock"],
                "reason_code": "UNAUTHORIZED_FOREIGN_ACTION",
            }

        step._planner, step._validator, step._rechecker = _planner(
            package, StructuredStrategyTransportAdapter(foreign)
        )
        with pytest.raises(StrategyModelOutputError, match="outside the legal"):
            await AgentRunCoordinator(
                step, LoopBudget(max_iterations=4, max_executions=3)
            ).run(initial, step.binding)
        assert step.mock_calls == 0

    asyncio.run(scenario())


def test_third_domain_has_distinct_package_binding(tmp_path: Path) -> None:
    (tmp_path / "research").mkdir()
    (tmp_path / "inventory").mkdir()
    research = _load(tmp_path / "research", DOMAIN, NOUN)
    inventory = _load(tmp_path / "inventory", "inventory.reconcile", "stock")
    assert research.binding.domain_id != inventory.binding.domain_id
    assert research.binding.binding_fingerprint != inventory.binding.binding_fingerprint
    assert research.collect_action != inventory.collect_action


def test_third_domain_real_qwen_with_multiple_first_turn_candidates(
    tmp_path: Path,
) -> None:
    """Live model chooses from both actions; no canned transport replacement."""
    if os.environ.get("GENERAL_AGENT_LIVE_OPT_IN") != "1":
        pytest.skip("Third-domain real Qwen evaluation requires opt-in")

    async def scenario() -> None:
        package = _load(tmp_path, DOMAIN, NOUN)
        initial = build_runtime_input(
            text="Collect source evidence first, then independently verify references"
        )
        step = DomainDrivenTurn(initial, package)
        model = ChatCompletionsStrategyTransport(
            ChatCompletionsConfig(
                endpoint=os.environ["GA01C_LLM_URL"],
                model=os.environ["GA01C_LLM_MODEL"],
                api_key=os.environ.get("GA01C_LLM_API_KEY", ""),
                timeout_seconds=45.0,
                max_tokens=200,
            ),
            system_instruction=(
                "You choose one action for a sandbox research evidence workflow. "
                "Return a JSON object with exactly strategy_id, action_ids and "
                "reason_code. The two legal tasks are collect-sources using "
                "collect-strategy-sources and verify-sources using "
                "verify-strategy-sources. Choose collect-sources first to gather "
                "the source evidence. When last_agent_action is "
                "MOCK_FOUND_NEEDS_VERIFICATION, choose verify-sources. "
                "Use reason_code RESEARCH_EVIDENCE_WORKFLOW. "
                "Never claim retrieval of real literature."
            ),
        )
        calls: list[tuple[str, ...]] = []

        async def choose(payload: dict[str, object]) -> dict[str, object]:
            actions = payload["candidate_action_ids"]
            assert isinstance(actions, list)
            calls.append(tuple(actions))
            result = dict(await model(payload))
            return result

        step._planner, step._validator, step._rechecker = _planner(
            package, StructuredStrategyTransportAdapter(choose)
        )
        outcome = await AgentRunCoordinator(
            step,
            LoopBudget(max_iterations=4, max_executions=3, max_decision_seconds=70.0),
        ).run(initial, step.binding)
        print(
            "THIRD_DOMAIN_LIVE_DIAG "
            f"kind={outcome.kind.value} "
            f"reason={outcome.reason} "
            f"selected={step.selected_actions} "
            f"candidates={calls}",
            flush=True,
        )
        assert outcome.kind is RunKind.FINISH
        assert step.selected_actions == ["collect-sources", "verify-sources"]
        assert len(calls) == 2
        assert len(calls[0]) == 2
        assert outcome.executions == 2
        print(
            "THIRD_DOMAIN_LIVE_PASS actions="
            + ",".join(step.selected_actions)
            + " first_candidates="
            + str(len(calls[0]))
        )

    asyncio.run(scenario())
