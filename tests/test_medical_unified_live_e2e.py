"""One verified medical package: knowledge gate -> real M4 -> SQLite tools.

Synthetic educational fixtures only; neither diagnosis nor crisis triage.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from agent_core.chat_transport import (
    ChatCompletionsConfig,
    ChatCompletionsStrategyTransport,
)
from agent_core.domain_application import bootstrap_domain_application
from agent_core.domain_knowledge import (
    DomainKnowledgeCapability,
    DomainScope,
    KnowledgeDocument,
    build_domain_model_messages,
)
from agent_core.model_adapter import StructuredStrategyTransportAdapter
from agent_core.runner import Decision, LoopBudget, ObservedFact, RunKind
from agent_core.sandbox_tool_dispatch import SandboxToolDispatcher
from agent_core.sqlite_business_intake import load_sqlite_business_snapshot
from tests.orchestration_stubs import build_runtime_input
from tests.test_ga01_slice2_loop import ModelDrivenSandboxTurn
from tests.test_ga13_sqlite_business_intake import _database, _row
from tests.test_medical_domain_readonly_e2e import DOMAINS, _medical_package

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="secure package fixture is Linux-only"
)


@pytest.mark.parametrize(("domain_id", "topic", "values"), DOMAINS)
@pytest.mark.parametrize("live", [False, True])
def test_unified_medical_package_knowledge_policy_model_and_readonly_tools(
    tmp_path: Path,
    domain_id: str,
    topic: str,
    values: dict[str, int],
    live: bool,
) -> None:
    if live and os.getenv("MEDICAL_LIVE_OPT_IN") != "1":
        pytest.skip("Medical live Qwen acceptance requires explicit opt-in")

    async def scenario() -> None:
        snapshot = _medical_package(tmp_path / "package", domain_id)
        app = bootstrap_domain_application(snapshot)
        catalog = app.execution_catalog(snapshot)
        assets = {
            asset.ref.kind: json.loads(asset.content_bytes)
            for asset in snapshot.assets
            if asset.ref.kind in {"knowledge", "prompt", "rule"}
        }
        knowledge = assets["knowledge"]
        rule = assets["rule"]
        prompt = assets["prompt"]
        assert rule["required_knowledge"] == knowledge["key"]
        assert isinstance(knowledge["fact"], str)
        scope = DomainScope(catalog.domain_id, catalog.binding_fingerprint)
        content = knowledge["fact"]
        document = KnowledgeDocument(
            scope.domain_id,
            scope.binding_fingerprint,
            "medical-synthetic-source",
            "synthetic://medical-source",
            hashlib.sha256(content.encode()).hexdigest(),
            content,
        )
        capability = DomainKnowledgeCapability(
            scope, lambda _scope, _query, _limit: (document,)
        )
        # Domain-specific, explicit matching terms, not generic model guesswork.
        query = "blood pressure" if "chronic" in domain_id else "mood sleep"
        admitted = capability.retrieve_and_admit(query)
        assert admitted.accepted
        assert admitted.documents[0].source_ref == "synthetic://medical-source"
        keys = {
            step.step_id: f"{topic}-{i}"
            for i, step in enumerate(catalog.workflow.steps)
        }
        db = tmp_path / "synthetic-medical.sqlite"
        _database(
            db,
            [
                _row(catalog, keys[step.step_id], values)
                for step in catalog.workflow.steps
            ],
        )
        original_bytes = db.read_bytes()
        lookup = load_sqlite_business_snapshot(
            catalog=catalog, database_file=db, step_keys=keys
        )
        dispatcher = SandboxToolDispatcher(catalog, lookup.handlers())
        model_calls: list[dict[str, Any]] = []
        live_transport = (
            ChatCompletionsStrategyTransport(
                ChatCompletionsConfig(
                    endpoint=os.environ["GA01C_LLM_URL"],
                    model=os.environ["GA01C_LLM_MODEL"],
                    api_key=os.getenv("GA01C_LLM_API_KEY", ""),
                    timeout_seconds=45.0,
                    max_tokens=180,
                ),
                message_builder=lambda payload: build_domain_model_messages(
                    scope=scope,
                    system_instruction=(
                        "Choose only the provided legal read-only synthetic medical "
                        "strategy and action. Return JSON strategy_id, action_ids, "
                        "reason_code. No clinical advice. Collect first, verify "
                        "after observation FACT_1. The required_workflow_step in "
                        "TASK_JSON is enforced by the application workflow; "
                        "follow it exactly. Never invent source facts."
                    ),
                    task_payload={
                        "domain": scope.domain_id,
                        "rule": rule,
                        "focus": prompt["focus"],
                        "legal_strategy_ids": payload["legal_strategy_ids"],
                        "candidate_action_ids": payload["candidate_action_ids"],
                        "last_agent_action": payload["last_agent_action"],
                        "required_workflow_step": (
                            "collect-notes"
                            if payload["last_agent_action"] is None
                            else "verify-notes"
                        ),
                    },
                    admission=admitted,
                ),
            )
            if live
            else None
        )

        async def choose(payload: dict[str, Any]) -> dict[str, object]:
            model_calls.append(dict(payload))
            assert admitted.accepted
            assert rule["required_knowledge"] == knowledge["key"]
            messages = build_domain_model_messages(
                scope=scope,
                system_instruction=(
                    "Only use legal actions in task. Do not offer clinical advice."
                ),
                task_payload={
                    "domain": scope.domain_id,
                    "policy": rule,
                    "focus": prompt["focus"],
                    "candidates": payload["candidate_action_ids"],
                },
                admission=admitted,
            )
            assert messages[2]["role"] == "user"
            assert "UNTRUSTED_RETRIEVAL_DATA" in messages[2]["content"]
            if live_transport is not None:
                return dict(await live_transport(payload))
            role = "verify" if payload["last_agent_action"] == "FACT_1" else "collect"
            return {
                "strategy_id": f"{role}-strategy-notes",
                "action_ids": [f"{role}-notes"],
                "reason_code": "MEDICAL_UNIFIED_SYNTHETIC_DECISION",
            }

        class UnifiedMedicalTurn(ModelDrivenSandboxTurn):
            def __post_init__(self) -> None:
                super().__post_init__()
                self.binding = app.prepare(self.initial, run_id="medical-unified-run")
                self._planner, self._validator, self._rechecker = app.m4(
                    StructuredStrategyTransportAdapter(choose)
                )

            async def decide(
                self, current_input, iteration, observations: tuple[ObservedFact, ...]
            ) -> Decision:
                if not admitted.accepted:
                    return Decision(
                        iteration, "WAIT", reason="REQUIRED_KNOWLEDGE_MISSING"
                    )
                return await super().decide(current_input, iteration, observations)

            async def execute_and_observe(self, decision: Decision) -> ObservedFact:
                observation = await dispatcher.observe(
                    decision=decision,
                    step_index=self.actions,
                    run_id=self.binding.run_id,
                    execution_id=f"medical-tool-{self.actions + 1}",
                )
                self.actions += 1
                return observation

        initial = build_runtime_input(text=f"Review synthetic {topic} records")
        result = await app.run(
            initial,
            run_id="medical-unified-run",
            step=UnifiedMedicalTurn(initial),
            budget=LoopBudget(
                max_iterations=4, max_executions=3, max_decision_seconds=60.0
            ),
            execution_catalog=catalog,
        )
        assert result.kind is RunKind.FINISH
        assert result.executions == 2
        assert [item.workflow_step_id for item in result.observations] == [
            "step-1",
            "step-2",
        ]
        assert len(model_calls) == 2
        assert db.read_bytes() == original_bytes
        print(
            f"MEDICAL_UNIFIED_PASS domain={domain_id} "
            f"live={live} observations={len(result.observations)}",
            flush=True,
        )

    asyncio.run(scenario())
