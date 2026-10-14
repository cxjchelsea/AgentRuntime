"""GA-15 actual Qwen model strategy + answer over two SQLite business domains."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from agent_core.business_answer import render_business_answer
from agent_core.chat_transport import (
    ChatCompletionsConfig,
    ChatCompletionsStrategyTransport,
)
from agent_core.domain_application import bootstrap_domain_application
from agent_core.live_business_answer import generate_live_business_answer
from agent_core.model_adapter import StructuredStrategyTransportAdapter
from agent_core.readonly_business_tools import ReadOnlyBusinessTools
from agent_core.runner import Decision, LoopBudget, ObservedFact, RunKind
from agent_core.sandbox_tool_dispatch import SandboxToolDispatcher
from agent_core.sqlite_business_intake import load_sqlite_business_snapshot
from tests.orchestration_stubs import build_runtime_input
from tests.test_ga01_slice2_loop import ModelDrivenSandboxTurn
from tests.test_ga08_execution_catalog import _snapshot
from tests.test_ga13_sqlite_business_intake import _database, _row

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="verified domain package fixtures require Linux",
)


@pytest.mark.parametrize("steps", [1, 2])
@pytest.mark.skipif(
    os.environ.get("GA15_LIVE_OPT_IN") != "1",
    reason="GA-15 requires opt-in real local or approved provider",
)
def test_real_model_drives_business_actions_and_grounded_answer(
    tmp_path: Path, steps: int
) -> None:
    async def scenario() -> None:
        config = ChatCompletionsConfig(
            endpoint=os.environ["GA01C_LLM_URL"],
            model=os.environ["GA01C_LLM_MODEL"],
            api_key=os.environ.get("GA01C_LLM_API_KEY", ""),
            timeout_seconds=45.0,
            max_tokens=200,
        )
        snapshot = _snapshot(tmp_path / "domain", steps=steps)
        app = bootstrap_domain_application(snapshot)
        catalog = app.execution_catalog(snapshot)
        question = (
            "请帮我查库存，并算出现在需要补货多少件"
            if steps == 1
            else "请帮我查学习完成进度与剩余任务"
        )
        operation = "inventory_replenishment" if steps == 1 else "learning_progress"
        data = (
            ({"on_hand": 8, "reserved": 3, "target": 12},)
            if steps == 1
            else ({"completed": 2, "total": 5}, {"completed": 2, "total": 5})
        )
        keys = {
            step.step_id: f"business-{index}"
            for index, step in enumerate(catalog.workflow.steps, 1)
        }
        database = tmp_path / "business.sqlite"
        _database(
            database,
            [
                _row(catalog, keys[step.step_id], values)
                for step, values in zip(catalog.workflow.steps, data, strict=True)
            ],
        )
        lookup = load_sqlite_business_snapshot(
            catalog=catalog, database_file=database, step_keys=keys
        )
        dispatcher = SandboxToolDispatcher(
            catalog,
            ReadOnlyBusinessTools(
                lookup,
                {step.step_id: operation for step in catalog.workflow.steps},
            ).handlers(),
        )
        system_instruction = (
            "You are selecting a legally permitted business information lookup action. "
            "Return ONLY JSON with strategy_id, action_ids, reason_code. "
            "Choose exactly one action from candidate_action_ids and one strategy "
            "from legal_strategy_ids. For initial action, choose the ID that begins "
            "with collect-. If last_agent_action is FACT_1, choose the IDs beginning "
            "with verify-. The action may only READ data or calculate metrics, "
            "never mutate, ship, purchase, or complete learning tasks. "
            "Use reason_code BUSINESS_READ_ONLY_QUERY."
        )
        real_strategy = ChatCompletionsStrategyTransport(
            config, system_instruction=system_instruction
        )
        model_calls: list[dict[str, Any]] = []

        async def selected(payload: dict[str, Any]) -> dict[str, object]:
            # Advertise only the next workflow step to the real model.
            # M4 still validates the returned IDs against the full frozen catalog.
            stage = (
                "verify-"
                if payload.get("last_agent_action") == "FACT_1"
                else "collect-"
            )
            bounded = dict(payload)
            bounded["candidate_action_ids"] = [
                value
                for value in payload["candidate_action_ids"]
                if value.startswith(stage)
            ]
            bounded["legal_strategy_ids"] = [
                value
                for value in payload["legal_strategy_ids"]
                if value.startswith(stage.removesuffix("-") + "-strategy-")
            ]
            if (
                len(bounded["candidate_action_ids"]) != 1
                or len(bounded["legal_strategy_ids"]) != 1
            ):
                raise ValueError("no uniquely bounded workflow model candidates")
            model_calls.append(bounded)
            response = await real_strategy(bounded)
            return dict(response)

        class LiveBusinessTurn(ModelDrivenSandboxTurn):
            def __post_init__(self) -> None:
                super().__post_init__()
                self.binding = app.prepare(self.initial, run_id="ga15-run")
                self._planner, self._validator, self._rechecker = app.m4(
                    StructuredStrategyTransportAdapter(selected)
                )

            async def execute_and_observe(self, decision: Decision) -> ObservedFact:
                result = await dispatcher.observe(
                    decision=decision,
                    step_index=self.actions,
                    run_id=self.binding.run_id,
                    execution_id=f"ga15-exec-{self.actions + 1}",
                )
                self.actions += 1
                return result

        initial = build_runtime_input(text=question)
        outcome = await app.run(
            initial,
            run_id="ga15-run",
            step=LiveBusinessTurn(initial),
            budget=LoopBudget(
                max_iterations=steps + 2,
                max_executions=steps + 1,
                max_decision_seconds=55.0,
                max_execution_seconds=5.0,
            ),
            execution_catalog=catalog,
        )
        assert outcome.kind is RunKind.FINISH
        assert outcome.executions == steps
        assert len(model_calls) == steps
        baseline = render_business_answer(
            question=question,
            outcome=outcome,
            lookup=lookup,
            operation=operation,
        )
        answer = await generate_live_business_answer(
            baseline=baseline, operation=operation, config=config
        )
        assert answer.run_id == outcome.run_id
        assert answer.source_digests == baseline.source_digests
        if steps == 1:
            assert "5" in answer.text and "7" in answer.text
            assert "补货" in answer.text
        else:
            assert "40%" in answer.text and "3" in answer.text
            assert "学习" in answer.text

    asyncio.run(scenario())
