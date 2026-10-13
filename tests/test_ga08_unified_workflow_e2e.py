"""GA-08 unified Domain Application: package -> retrieval -> model -> M4 -> sandbox loop.

A local injectable Chat Completions response is intentionally used: this is
not live LLM or a production tool authorization / execution attestation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from agent_core.chat_transport import ChatCompletionsConfig
from agent_core.domain_knowledge import DomainScope, KnowledgeDocument
from agent_core.domain_unified_application import bootstrap_unified_domain_application
from agent_core.runner import Decision, LoopBudget, ObservedFact, RunKind
from tests.orchestration_stubs import build_runtime_input
from tests.test_ga01_slice1 import SandboxTurn
from tests.test_ga01_slice2_loop import ModelDrivenSandboxTurn
from tests.test_ga08_execution_catalog import _snapshot

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="GA08 uses Linux-only verified package loader",
)


@pytest.mark.parametrize("steps", [1, 2])
def test_unified_workflow_package_retrieval_model_m4_sandbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, steps: int
) -> None:
    async def scenario() -> None:
        snapshot = _snapshot(tmp_path / "domain", steps=steps, with_content=True)
        calls: list[dict[str, Any]] = []
        scope_seen: list[DomainScope] = []

        def retrieve(
            scope: DomainScope, query: str, limit: int
        ) -> tuple[KnowledgeDocument, ...]:
            scope_seen.append(scope)
            assert query == "domain reference"
            assert limit == 2
            value = "domain reference verified evidence"
            return (
                KnowledgeDocument(
                    scope.domain_id,
                    scope.binding_fingerprint,
                    "document-one",
                    "sandbox-fixture",
                    hashlib.sha256(value.encode()).hexdigest(),
                    value,
                ),
            )

        unified = bootstrap_unified_domain_application(
            snapshot,
            retriever=retrieve,
            query="domain reference",
            model_config=ChatCompletionsConfig(
                endpoint="http://127.0.0.1:11434/v1/chat/completions",
                model="synthetic-model",
            ),
        )
        catalog = unified.execution_catalog
        assert catalog is not None
        assert len(catalog.workflow.steps) == steps
        noun = "stock" if steps == 1 else "notes"

        def respond(request: Any, timeout: float) -> bytes:
            assert timeout > 0
            envelope = json.loads(request.data)
            messages = envelope["messages"]
            assert [msg["role"] for msg in messages] == [
                "system",
                "user",
                "user",
            ]
            instruction = messages[0]["content"]
            assert "custom-domain-finish" not in instruction
            assert "last_agent_action is null" not in instruction
            assert all(step.action_id in instruction for step in catalog.workflow.steps)
            assert "UNTRUSTED_RETRIEVAL_DATA" in messages[2]["content"]
            task = json.loads(messages[1]["content"].removeprefix("TASK_JSON="))
            calls.append(task)
            role = "verify" if task.get("last_agent_action") == "FACT_1" else "collect"
            answer = {
                "strategy_id": role + "-strategy-" + noun,
                "action_ids": [role + "-" + noun],
                "reason_code": "UNIFIED_PACKAGE_DECISION",
            }
            return json.dumps(
                {"choices": [{"message": {"content": json.dumps(answer)}}]}
            ).encode()

        monkeypatch.setattr(
            unified.model_transport._transport, "_send_once", respond
        )
        initial = build_runtime_input(text="domain workflow task")

        class UnifiedTurn(ModelDrivenSandboxTurn):
            def __post_init__(self) -> None:
                super().__post_init__()
                self.binding = unified.app.prepare(self.initial, run_id="ga08-unified")
                self._planner = unified.planner
                self._validator = unified.validator
                self._rechecker = unified.rechecker

            async def execute_and_observe(self, decision: Decision) -> ObservedFact:
                assert decision.approved is not None
                index = self.actions
                step = catalog.workflow.steps[index]
                self.selected_actions.append(decision.approved.steps[0].action)
                self.facts = (step.completion_fact,)
                if index == steps - 1:
                    self.facts += ("GOAL_SATISFIED",)
                result = await SandboxTurn.execute_and_observe(self, decision)
                return replace(
                    result, workflow_step_id=step.step_id, tool_id=step.tool_id
                )

        turn = UnifiedTurn(initial)
        outcome = await unified.run(
            initial,
            run_id="ga08-unified",
            step=turn,
            budget=LoopBudget(max_iterations=steps + 2, max_executions=steps + 1),
        )
        assert outcome.kind is RunKind.FINISH
        assert outcome.executions == steps
        assert outcome.iterations == steps + 1
        assert turn.selected_actions == [
            step.action_id for step in catalog.workflow.steps
        ]
        assert len(calls) == steps
        assert len(scope_seen) == steps
        assert all(scope.domain_id == catalog.domain_id for scope in scope_seen)
        assert turn.mock_calls == steps

    asyncio.run(scenario())
