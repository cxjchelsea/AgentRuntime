"""GA-14 user question to grounded final answer, using GA-13 real SQLite E2E."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from agent_core.business_answer import render_business_answer
from agent_core.domain_application import bootstrap_domain_application
from agent_core.model_adapter import StructuredStrategyTransportAdapter
from agent_core.readonly_business_tools import ReadOnlyBusinessTools
from agent_core.runner import (
    Decision,
    LoopBudget,
    ObservedFact,
    RunBoundaryError,
    RunKind,
)
from agent_core.sandbox_tool_dispatch import SandboxToolDispatcher
from agent_core.sqlite_business_intake import load_sqlite_business_snapshot
from tests.orchestration_stubs import build_runtime_input
from tests.test_ga01_slice2_loop import ModelDrivenSandboxTurn
from tests.test_ga08_execution_catalog import _snapshot
from tests.test_ga13_sqlite_business_intake import _database, _row

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="verified domain package requires Linux",
)


@pytest.mark.parametrize("steps", [1, 2])
def test_natural_language_business_answer_from_sqlite_agent_e2e(
    tmp_path: Path, steps: int
) -> None:
    async def scenario() -> None:
        snapshot = _snapshot(tmp_path / "package", steps=steps)
        app = bootstrap_domain_application(snapshot)
        catalog = app.execution_catalog(snapshot)
        noun = "stock" if steps == 1 else "notes"
        question = (
            "我们的库存还需要补多少货？"
            if steps == 1
            else "帮我看看学习任务完成进度，还有多少项？"
        )
        operation = (
            "inventory_replenishment" if steps == 1 else "learning_progress"
        )
        payloads = (
            ({"on_hand": 8, "reserved": 3, "target": 12},)
            if steps == 1
            else ({"completed": 2, "total": 5}, {"completed": 2, "total": 5})
        )
        keys = {
            step.step_id: f"record-{index}"
            for index, step in enumerate(catalog.workflow.steps, 1)
        }
        database = tmp_path / "business.sqlite"
        _database(
            database,
            [
                _row(catalog, keys[step.step_id], data)
                for step, data in zip(catalog.workflow.steps, payloads, strict=True)
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

        async def model(payload: dict[str, Any]) -> dict[str, object]:
            role = "verify" if payload["last_agent_action"] == "FACT_1" else "collect"
            return {
                "strategy_id": role + "-strategy-" + noun,
                "action_ids": [role + "-" + noun],
                "reason_code": "GA14_GROUNDED_BUSINESS_ANSWER",
            }

        class QuestionTurn(ModelDrivenSandboxTurn):
            def __post_init__(self) -> None:
                super().__post_init__()
                self.binding = app.prepare(self.initial, run_id="ga14-run")
                self._planner, self._validator, self._rechecker = app.m4(
                    StructuredStrategyTransportAdapter(model)
                )

            async def execute_and_observe(self, decision: Decision) -> ObservedFact:
                observed = await dispatcher.observe(
                    decision=decision,
                    step_index=self.actions,
                    run_id=self.binding.run_id,
                    execution_id=f"ga14-exec-{self.actions + 1}",
                )
                self.actions += 1
                return observed

        initial = build_runtime_input(text=question)
        outcome = await app.run(
            initial,
            run_id="ga14-run",
            step=QuestionTurn(initial),
            budget=LoopBudget(
                max_iterations=steps + 2, max_executions=steps + 1
            ),
            execution_catalog=catalog,
        )
        answer = render_business_answer(
            question=question, outcome=outcome, lookup=lookup, operation=operation
        )
        assert outcome.kind is RunKind.FINISH
        assert answer.domain_id == catalog.domain_id
        assert len(answer.source_digests) == steps
        assert answer.question == question
        if steps == 1:
            assert "可用库存为 5 件" in answer.text
            assert "建议补货 7 件" in answer.text
            assert "尚未执行采购" in answer.text
        else:
            assert "进度为 40%" in answer.text
            assert "剩余 3 项" in answer.text
            assert "没有替你完成任何学习任务" in answer.text

        with pytest.raises(RunBoundaryError, match="unsupported"):
            render_business_answer(
                question="帮我修改账户余额",
                outcome=outcome,
                lookup=lookup,
                operation=operation,
            )
        with pytest.raises(RunBoundaryError, match="completed"):
            render_business_answer(
                question=question,
                outcome=replace(outcome, kind=RunKind.WAIT),
                lookup=lookup,
                operation=operation,
            )
        altered = replace(
            outcome.observations[0],
            facts=tuple(
                fact
                for fact in outcome.observations[0].facts
                if not fact.startswith("RECORD_SHA256_")
            ),
        )
        with pytest.raises(RunBoundaryError, match="observation"):
            render_business_answer(
                question=question,
                outcome=replace(
                    outcome,
                    observations=(altered, *outcome.observations[1:]),
                ),
                lookup=lookup,
                operation=operation,
            )
        if steps == 2:
            with pytest.raises(RunBoundaryError, match="completed"):
                render_business_answer(
                    question=question,
                    outcome=replace(outcome, observations=outcome.observations[:1]),
                    lookup=lookup,
                    operation=operation,
                )

    asyncio.run(scenario())
