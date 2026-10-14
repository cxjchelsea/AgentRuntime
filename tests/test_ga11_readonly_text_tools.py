"""GA-11 shared text tools reused by distinct domain Agent loops."""

from __future__ import annotations

import asyncio
import hashlib
import sys
from pathlib import Path
from typing import Any

import pytest

from agent_core.domain_application import bootstrap_domain_application
from agent_core.model_adapter import StructuredStrategyTransportAdapter
from agent_core.readonly_domain_lookup import ReadOnlyDomainLookup, ReadOnlyRecord
from agent_core.readonly_text_tools import ReadOnlyTextTools
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


@pytest.mark.parametrize("steps", [1, 2])
def test_shared_readonly_text_tools_two_domain_agent_loops(
    tmp_path: Path, steps: int
) -> None:
    async def scenario() -> None:
        snapshot = _snapshot(tmp_path / "domain", steps=steps)
        app = bootstrap_domain_application(snapshot)
        catalog = app.execution_catalog(snapshot)
        noun = "stock" if steps == 1 else "notes"
        values = ("a b c",) if steps == 1 else ("one two", "hello world!")
        records: dict[str, ReadOnlyRecord] = {}
        step_keys: dict[str, str] = {}
        operations: dict[str, str] = {}
        for number, step in enumerate(catalog.workflow.steps, 1):
            key = f"item-{number}"
            value = values[number - 1]
            records[key] = ReadOnlyRecord(
                catalog.domain_id,
                catalog.binding_fingerprint,
                key,
                value,
                hashlib.sha256(value.encode("utf-8")).hexdigest(),
            )
            step_keys[step.step_id] = key
            operations[step.step_id] = (
                "character_count" if number == 2 else "word_count"
            )
        lookup = ReadOnlyDomainLookup(catalog, records, step_keys)
        tools = ReadOnlyTextTools(lookup, operations)
        dispatcher = SandboxToolDispatcher(catalog, tools.handlers())
        operations.clear()
        records.clear()
        step_keys.clear()
        assert len(tools.step_operations) == steps

        async def model(payload: dict[str, Any]) -> dict[str, object]:
            role = "verify" if payload["last_agent_action"] == "FACT_1" else "collect"
            return {
                "strategy_id": role + "-strategy-" + noun,
                "action_ids": [role + "-" + noun],
                "reason_code": "SHARED_READONLY_TEXT_OPERATION",
            }

        class TextTurn(ModelDrivenSandboxTurn):
            def __post_init__(self) -> None:
                super().__post_init__()
                self.binding = app.prepare(self.initial, run_id="ga11-run")
                self._planner, self._validator, self._rechecker = app.m4(
                    StructuredStrategyTransportAdapter(model)
                )

            async def execute_and_observe(self, decision: Decision) -> ObservedFact:
                observed = await dispatcher.observe(
                    decision=decision,
                    step_index=self.actions,
                    run_id=self.binding.run_id,
                    execution_id=f"ga11-exec-{self.actions + 1}",
                )
                self.actions += 1
                return observed

        initial = build_runtime_input(text="analyze domain record using shared tools")
        result = await app.run(
            initial,
            run_id="ga11-run",
            step=TextTurn(initial),
            budget=LoopBudget(max_iterations=steps + 2, max_executions=steps + 1),
            execution_catalog=catalog,
        )
        assert result.kind is RunKind.FINISH
        assert result.executions == steps
        assert "WORD_COUNT_3" in result.observations[0].facts if steps == 1 else (
            "WORD_COUNT_2" in result.observations[0].facts
        )
        if steps == 2:
            assert "CHARACTER_COUNT_12" in result.observations[1].facts
        assert result.observations[-1].facts[-1] == "GOAL_SATISFIED"
        for step, observation in zip(
            catalog.workflow.steps, result.observations, strict=True
        ):
            record = lookup.records[lookup.step_keys[step.step_id]]
            assert "RECORD_SHA256_" + record.sha256 in observation.facts

    asyncio.run(scenario())


def test_text_tools_reject_unregistered_operation_and_cross_step(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        snapshot = _snapshot(tmp_path / "domain", steps=1)
        app = bootstrap_domain_application(snapshot)
        catalog = app.execution_catalog(snapshot)
        step = catalog.workflow.steps[0]
        value = "one two three"
        record = ReadOnlyRecord(
            catalog.domain_id,
            catalog.binding_fingerprint,
            "key",
            value,
            hashlib.sha256(value.encode()).hexdigest(),
        )
        lookup = ReadOnlyDomainLookup(
            catalog, {"key": record}, {step.step_id: "key"}
        )
        with pytest.raises(RunBoundaryError, match="operations"):
            ReadOnlyTextTools(lookup, {step.step_id: "write_file"})
        with pytest.raises(RunBoundaryError, match="operations"):
            ReadOnlyTextTools(lookup, {"foreign-step": "word_count"})
        mappings = {step.step_id: "word_count"}
        tools = ReadOnlyTextTools(lookup, mappings)
        mappings[step.step_id] = "write_file"
        assert tools.step_operations[step.step_id] == "word_count"
        handler = tools.handlers()[step.tool_id]
        with pytest.raises(RunBoundaryError, match="not bound"):
            await handler("foreign-step", step.tool_id)
        with pytest.raises(RunBoundaryError, match="not bound"):
            await handler(step.step_id, "foreign-tool")
        assert "WORD_COUNT_3" in await handler(step.step_id, step.tool_id)

    asyncio.run(scenario())
