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
from agent_core.iteration import IterationRef
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
        calls: list[tuple[str, ...]] = []

        async def choose(payload: dict[str, object]) -> dict[str, object]:
            actions = payload["candidate_action_ids"]
            strategies = payload["legal_strategy_ids"]
            assert isinstance(actions, list) and isinstance(strategies, list)
            pending = [
                action for action in actions if action not in step.selected_actions
            ]
            assert pending, "no unfinished action available"
            bounded = dict(payload)
            bounded["candidate_action_ids"] = pending
            bounded["legal_strategy_ids"] = [
                strategy
                for strategy in strategies
                if any(
                    strategy == action.replace("-sources", "-strategy-sources")
                    for action in pending
                )
            ]
            filtered_strategies = bounded["legal_strategy_ids"]
            assert isinstance(filtered_strategies, list)
            assert len(filtered_strategies) == len(pending)
            calls.append(tuple(pending))
            # The model must see the CURRENT legal subset and the previous
            # observation. It may still fail; never rewrite its output.
            guidance = (
                "Choose exactly one action from the current legal action list. "
                "Return JSON strategy_id, action_ids, reason_code. "
                "Do not repeat a completed action. "
                f"Current permitted actions: {pending}. "
                f"Current permitted strategies: {filtered_strategies}. "
                f"Previous observed action fact: {payload.get('last_agent_action')}. "
                "A source collection that returned "
                "MOCK_FOUND_NEEDS_VERIFICATION requires reference verification."
            )
            current_model = ChatCompletionsStrategyTransport(
                ChatCompletionsConfig(
                    endpoint=os.environ["GA01C_LLM_URL"],
                    model=os.environ["GA01C_LLM_MODEL"],
                    api_key=os.environ.get("GA01C_LLM_API_KEY", ""),
                    timeout_seconds=45.0,
                    max_tokens=200,
                ),
                system_instruction=guidance,
            )
            result = dict(await current_model(bounded))
            selected = result.get("action_ids")
            if (
                type(selected) is not list
                or len(selected) != 1
                or selected[0] not in pending
            ):
                raise ValueError("model selected an already executed research action")
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


@pytest.mark.parametrize(
    ("task_text", "expected_action"),
    [
        ("First collect evidence for a new claim", "collect-sources"),
        ("First verify an existing list of references", "verify-sources"),
    ],
)
def test_third_domain_semantic_first_action_live(
    tmp_path: Path, task_text: str, expected_action: str
) -> None:
    """Predeclared competing choices; no first-action answer in instruction."""
    if os.environ.get("GENERAL_AGENT_LIVE_OPT_IN") != "1":
        pytest.skip("Requires actual Qwen provider")

    async def scenario() -> None:
        package = _load(tmp_path, DOMAIN, NOUN)
        initial = build_runtime_input(text=task_text)
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
                "You are a research assistant choosing the next permitted "
                "read-only action. Return only JSON fields strategy_id, "
                "action_ids and reason_code. Available research tools are "
                "collect-sources / collect-strategy-sources for gathering new "
                "material, and verify-sources / verify-strategy-sources for "
                "checking already assembled references. Infer which comes "
                "first from the user's task. No invented tool or real source."
            ),
            message_builder=lambda payload: (
                {
                    "role": "system",
                    "content": "Select one legal strategy and action as JSON.",
                },
                {
                    "role": "user",
                    "content": (
                        f"User task: {task_text}. "
                        f"Legal strategies: {payload['legal_strategy_ids']}. "
                        f"Legal actions: {payload['candidate_action_ids']}."
                    ),
                },
            ),
        )

        async def select(payload: dict[str, object]) -> dict[str, object]:
            assert isinstance(payload["candidate_action_ids"], list)
            assert len(payload["candidate_action_ids"]) == 2
            return dict(await model(payload))

        step._planner, step._validator, step._rechecker = _planner(
            package, StructuredStrategyTransportAdapter(select)
        )
        current = step.binding.iteration_input(initial, ordinal=0)
        iteration = IterationRef.from_input(step.binding, current, ordinal=0)
        decision = await step.decide(current, iteration, ())
        selected = (
            decision.approved.steps[0].action if decision.approved is not None else None
        )
        print(
            f"RESEARCH_SEMANTIC_ACTION task={task_text!r} "
            f"selected={selected!r} expected={expected_action!r}",
            flush=True,
        )
        assert decision.kind == "ACT"
        assert selected == expected_action
        assert step.mock_calls == 0

    asyncio.run(scenario())
