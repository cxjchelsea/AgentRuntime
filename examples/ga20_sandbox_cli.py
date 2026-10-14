"""GA-20 experimental interactive, read-only business Agent sandbox.

This entry point deliberately reuses GA-15's Linux test-package fixture and
M4 sandbox StepPort. It is NOT a production Domain Package or host authority.
No purchase, inventory update, or study-task mutation is implemented.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from agent_core.business_answer import render_business_answer
from agent_core.chat_transport import ChatCompletionsConfig, ChatCompletionsStrategyTransport
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

DEFAULT_QUESTIONS = {
    "inventory": "请查询库存并计算需要补货多少件",
    "learning": "请查询学习进度和剩余学习任务",
}
OPERATIONS = {
    "inventory": "inventory_replenishment",
    "learning": "learning_progress",
}


def validated_question(domain: str, question: str) -> str:
    """Reject out-of-scope tasks rather than quietly executing another task."""
    if domain not in OPERATIONS or not isinstance(question, str):
        raise ValueError("unsupported domain")
    question = question.strip()
    if not 1 <= len(question) <= 1000:
        raise ValueError("question must be 1..1000 characters")
    words = ("库存", "补货", "stock", "inventory", "reorder") if domain == "inventory" else (
        "学习", "进度", "任务", "study", "progress", "lesson",
    )
    if not any(word in question.lower() for word in words):
        raise ValueError("question is outside the selected read-only domain")
    return question


async def ask_once(domain: str, question: str, config: ChatCompletionsConfig) -> dict[str, object]:
    """Run the existing real-model/M4/SQLite read-only path, not a canned answer."""
    if not sys.platform.startswith("linux"):
        raise RuntimeError("GA-20 fixture-backed sandbox is Linux-only")
    question = validated_question(domain, question)
    steps = 1 if domain == "inventory" else 2
    operation = OPERATIONS[domain]
    with tempfile.TemporaryDirectory(prefix="ga20-sandbox-") as temp:
        root = Path(temp)
        snapshot = _snapshot(root / "package", steps=steps)
        app = bootstrap_domain_application(snapshot)
        catalog = app.execution_catalog(snapshot)
        step_keys = {
            step.step_id: f"business-{index}"
            for index, step in enumerate(catalog.workflow.steps, 1)
        }
        data = (
            ({"on_hand": 8, "reserved": 3, "target": 12},)
            if steps == 1 else
            ({"completed": 2, "total": 5}, {"completed": 2, "total": 5})
        )
        database = root / "business.sqlite"
        _database(
            database,
            [
                _row(catalog, step_keys[step.step_id], values)
                for step, values in zip(catalog.workflow.steps, data, strict=True)
            ],
        )
        lookup = load_sqlite_business_snapshot(
            catalog=catalog, database_file=database, step_keys=step_keys,
        )
        dispatcher = SandboxToolDispatcher(
            catalog,
            ReadOnlyBusinessTools(
                lookup, {step.step_id: operation for step in catalog.workflow.steps},
            ).handlers(),
        )

        async def selected(payload: dict[str, Any]) -> dict[str, object]:
            stage = "verify-" if payload.get("last_agent_action") == "FACT_1" else "collect-"
            bounded = dict(payload)
            bounded["candidate_action_ids"] = [
                value for value in payload["candidate_action_ids"]
                if value.startswith(stage)
            ]
            bounded["legal_strategy_ids"] = [
                value for value in payload["legal_strategy_ids"]
                if value.startswith(stage.removesuffix("-") + "-strategy-")
            ]
            if len(bounded["candidate_action_ids"]) != 1 or len(bounded["legal_strategy_ids"]) != 1:
                raise ValueError("no uniquely admitted business action")
            action = bounded["candidate_action_ids"][0]
            strategy = bounded["legal_strategy_ids"][0]
            instruction = (
                "You are a read-only business Agent. Return JSON with precisely "
                "strategy_id, action_ids, reason_code. Choose only strategy "
                f"{strategy!r} and action [{action!r}]. "
                "Set reason_code to BUSINESS_READ_ONLY_QUERY. "
                "Never claim any purchase, inventory update, or study completion."
            )
            transport = ChatCompletionsStrategyTransport(
                config, system_instruction=instruction,
            )
            for attempt in range(2):
                response = dict(await transport(bounded))
                if response.get("strategy_id") == strategy and response.get("action_ids") == [action]:
                    return response
                if attempt == 0:
                    bounded["previous_selection_invalid"] = True
            raise ValueError("model did not choose a legal action")

        initial = build_runtime_input(text=question)
        run_id = "ga20-sandbox-run"

        class InteractiveTurn(ModelDrivenSandboxTurn):
            def __post_init__(self) -> None:
                super().__post_init__()
                self.binding = app.prepare(self.initial, run_id=run_id)
                self._planner, self._validator, self._rechecker = app.m4(
                    StructuredStrategyTransportAdapter(selected),
                )

            async def execute_and_observe(self, decision: Decision) -> ObservedFact:
                evidence = await dispatcher.observe(
                    decision=decision,
                    step_index=self.actions,
                    run_id=self.binding.run_id,
                    execution_id=f"ga20-exec-{self.actions + 1}",
                )
                self.actions += 1
                return evidence

        outcome = await app.run(
            initial,
            run_id=run_id,
            step=InteractiveTurn(initial),
            budget=LoopBudget(
                max_iterations=steps + 2,
                max_executions=steps + 1,
                max_decision_seconds=55.0,
                max_execution_seconds=5.0,
            ),
            execution_catalog=catalog,
        )
        if outcome.kind is not RunKind.FINISH:
            raise RuntimeError(f"Agent did not finish: {outcome.kind.value}")
        baseline = render_business_answer(
            question=question, outcome=outcome, lookup=lookup, operation=operation,
        )
        answer = await generate_live_business_answer(
            baseline=baseline, operation=operation, config=config,
        )
        return {
            "domain": domain,
            "question": question,
            "answer": answer.text,
            "executions": outcome.executions,
            "evidence_digests": list(answer.source_digests),
            "read_only": True,
            "fixture_data": True,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="GA-20 experimental Linux-only Agent sandbox")
    parser.add_argument("--domain", choices=tuple(OPERATIONS), required=True)
    parser.add_argument("--question", help="One natural-language request (or interactive prompt)")
    args = parser.parse_args()
    try:
        question = args.question if args.question is not None else input("用户任务: ")
        question = validated_question(args.domain, question)
        config = ChatCompletionsConfig(
            endpoint=os.environ.get("GA01C_LLM_URL", "http://127.0.0.1:11434/v1/chat/completions"),
            model=os.environ.get("GA01C_LLM_MODEL", "qwen2.5:3b"),
            api_key=os.environ.get("GA01C_LLM_API_KEY", ""),
            timeout_seconds=45.0,
            max_tokens=200,
        )
        result = asyncio.run(ask_once(args.domain, question, config))
    except (ValueError, RuntimeError, OSError, EOFError) as exc:
        print(f"GA-20 sandbox declined: {exc}", file=sys.stderr)
        return 1
    print(result["answer"])
    print(f"[read-only sandbox; {result['executions']} verified tool observation(s); fixture data]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
