"""GA-12 business-use-case proof: inventory and learning share the Agent core."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from agent_core.domain_application import bootstrap_domain_application
from agent_core.model_adapter import StructuredStrategyTransportAdapter
from agent_core.readonly_business_tools import ReadOnlyBusinessTools
from agent_core.readonly_domain_lookup import ReadOnlyDomainLookup, ReadOnlyRecord
from agent_core.runner import (
    Decision,
    LoopBudget,
    ObservedFact,
    RunBoundaryError,
    RunKind,
)
from agent_core.sandbox_tool_dispatch import SandboxToolDispatcher
from tests.orchestration_stubs import build_runtime_input
from tests.test_ga01_slice2_loop import ModelDrivenSandboxTurn
from tests.test_ga08_execution_catalog import _snapshot

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="verified domain package fixture requires Linux",
)


def _business_lookup(
    catalog: Any, payloads: tuple[dict[str, int], ...]
) -> ReadOnlyDomainLookup:
    records: dict[str, ReadOnlyRecord] = {}
    step_keys: dict[str, str] = {}
    for index, (step, payload) in enumerate(
        zip(catalog.workflow.steps, payloads, strict=True), 1
    ):
        key = f"business-{index}"
        value = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        records[key] = ReadOnlyRecord(
            catalog.domain_id,
            catalog.binding_fingerprint,
            key,
            value,
            hashlib.sha256(value.encode()).hexdigest(),
        )
        step_keys[step.step_id] = key
    return ReadOnlyDomainLookup(catalog, records, step_keys)


@pytest.mark.parametrize("steps", [1, 2])
def test_real_business_tasks_share_agent_loop(tmp_path: Path, steps: int) -> None:
    async def scenario() -> None:
        snapshot = _snapshot(tmp_path / "domain", steps=steps)
        app = bootstrap_domain_application(snapshot)
        catalog = app.execution_catalog(snapshot)
        noun = "stock" if steps == 1 else "notes"
        payloads = (
            ({"on_hand": 8, "reserved": 3, "target": 12},)
            if steps == 1
            else (
                {"completed": 2, "total": 5},
                {"completed": 5, "total": 5},
            )
        )
        lookup = _business_lookup(catalog, payloads)
        operation = "inventory_replenishment" if steps == 1 else "learning_progress"
        tools = ReadOnlyBusinessTools(
            lookup, {step.step_id: operation for step in catalog.workflow.steps}
        )
        dispatcher = SandboxToolDispatcher(catalog, tools.handlers())

        async def model(payload: dict[str, Any]) -> dict[str, object]:
            role = "verify" if payload["last_agent_action"] == "FACT_1" else "collect"
            return {
                "strategy_id": role + "-strategy-" + noun,
                "action_ids": [role + "-" + noun],
                "reason_code": "GA12_BUSINESS_RESULT",
            }

        class BusinessTurn(ModelDrivenSandboxTurn):
            def __post_init__(self) -> None:
                super().__post_init__()
                self.binding = app.prepare(self.initial, run_id="ga12-run")
                self._planner, self._validator, self._rechecker = app.m4(
                    StructuredStrategyTransportAdapter(model)
                )

            async def execute_and_observe(self, decision: Decision) -> ObservedFact:
                result = await dispatcher.observe(
                    decision=decision,
                    step_index=self.actions,
                    run_id=self.binding.run_id,
                    execution_id=f"ga12-execution-{self.actions + 1}",
                )
                self.actions += 1
                return result

        initial = build_runtime_input(text="complete a real business calculation")
        result = await app.run(
            initial,
            run_id="ga12-run",
            step=BusinessTurn(initial),
            budget=LoopBudget(max_iterations=steps + 2, max_executions=steps + 1),
            execution_catalog=catalog,
        )
        assert result.kind is RunKind.FINISH
        assert result.executions == steps
        if steps == 1:
            assert "AVAILABLE_5" in result.observations[0].facts
            assert "REPLENISH_QTY_7" in result.observations[0].facts
            assert "REPLENISH_REQUIRED" in result.observations[0].facts
        else:
            assert "PROGRESS_PERCENT_40" in result.observations[0].facts
            assert "REMAINING_TASKS_3" in result.observations[0].facts
            assert "PROGRESS_PERCENT_100" in result.observations[1].facts
            assert "LEARNING_COMPLETE" in result.observations[1].facts
        assert "GOAL_SATISFIED" in result.observations[-1].facts
        for step, observation in zip(
            catalog.workflow.steps, result.observations, strict=True
        ):
            record = lookup.records[lookup.step_keys[step.step_id]]
            assert "RECORD_SHA256_" + record.sha256 in observation.facts

    asyncio.run(scenario())


def test_business_rejections_and_record_integrity(tmp_path: Path) -> None:
    async def scenario() -> None:
        snapshot = _snapshot(tmp_path / "domain", steps=1)
        app = bootstrap_domain_application(snapshot)
        catalog = app.execution_catalog(snapshot)
        lookup = _business_lookup(
            catalog, ({"on_hand": 8, "reserved": 3, "target": 12},)
        )
        step = catalog.workflow.steps[0]
        mapping = {step.step_id: "inventory_replenishment"}
        tools = ReadOnlyBusinessTools(lookup, mapping)
        mapping[step.step_id] = "send_notification"
        assert tools.step_operations[step.step_id] == "inventory_replenishment"
        with pytest.raises(RunBoundaryError, match="operation map"):
            ReadOnlyBusinessTools(lookup, {step.step_id: "send_notification"})
        with pytest.raises(RunBoundaryError, match="operation map"):
            ReadOnlyBusinessTools(lookup, {"foreign": "learning_progress"})
        handler = tools.handlers()[step.tool_id]
        with pytest.raises(RunBoundaryError, match="not bound"):
            await handler(step.step_id, "foreign")
        with pytest.raises(RunBoundaryError, match="not bound"):
            await handler("foreign", step.tool_id)
        assert "REPLENISH_QTY_7" in await handler(step.step_id, step.tool_id)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("domain", "payload", "reason"),
    [
        (1, {"on_hand": 2, "reserved": 3, "target": 8}, "reserved quantity"),
        (1, {"on_hand": -1, "reserved": 0, "target": 8}, "quantity"),
        (1, {"on_hand": 8, "reserved": 3}, "schema"),
        (1, {"on_hand": True, "reserved": 1, "target": 5}, "quantity"),
        (2, {"completed": 4, "total": 3}, "learning progress"),
        (2, {"completed": 0, "total": 0}, "learning progress"),
        (2, {"completed": 2}, "schema"),
    ],
)
def test_invalid_business_records_fail_closed(
    tmp_path: Path, domain: int, payload: dict[str, Any], reason: str
) -> None:
    async def scenario() -> None:
        snapshot = _snapshot(tmp_path / "domain", steps=domain)
        catalog = bootstrap_domain_application(snapshot).execution_catalog(snapshot)
        first = catalog.workflow.steps[0]
        payloads = (
            (payload,) if domain == 1 else (payload, {"completed": 5, "total": 5})
        )
        lookup = _business_lookup(catalog, payloads)
        op = "inventory_replenishment" if domain == 1 else "learning_progress"
        tools = ReadOnlyBusinessTools(
            lookup, {step.step_id: op for step in catalog.workflow.steps}
        )
        with pytest.raises(RunBoundaryError, match=reason):
            await tools.handlers()[first.tool_id](first.step_id, first.tool_id)

    asyncio.run(scenario())
