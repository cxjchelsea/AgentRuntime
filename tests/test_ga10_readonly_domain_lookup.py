"""GA-10 real immutable record lookup in two package-owned sandbox Agent loops."""

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
from agent_core.runner import (
    Decision,
    LoopBudget,
    ObservedFact,
    RunBoundaryError,
    RunKind,
)
from tests.orchestration_stubs import build_runtime_input
from tests.test_ga01_slice2_loop import ModelDrivenSandboxTurn
from tests.test_ga08_execution_catalog import _snapshot

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="verified domain package fixture requires Linux",
)


def _records(domain: str, count: int) -> dict[str, ReadOnlyRecord]:
    result = {}
    for index in range(1, count + 1):
        key = f"record-{index}"
        value = f"{domain}: verified read-only value {index}"
        result[key] = ReadOnlyRecord(
            domain, key, value, hashlib.sha256(value.encode()).hexdigest()
        )
    return result


@pytest.mark.parametrize("steps", [1, 2])
def test_readonly_lookup_runs_complete_two_domains(tmp_path: Path, steps: int) -> None:
    async def scenario() -> None:
        snapshot = _snapshot(tmp_path / "domain", steps=steps)
        app = bootstrap_domain_application(snapshot)
        catalog = app.execution_catalog(snapshot)
        noun = "stock" if steps == 1 else "notes"
        records = _records(catalog.domain_id, steps)
        keys = {
            step.step_id: f"record-{i}"
            for i, step in enumerate(catalog.workflow.steps, 1)
        }
        lookup = ReadOnlyDomainLookup(catalog, records, keys)
        dispatcher = lookup.dispatcher()
        records.clear()
        keys.clear()
        assert len(lookup.records) == steps

        async def model(payload: dict[str, Any]) -> dict[str, object]:
            role = "verify" if payload["last_agent_action"] == "FACT_1" else "collect"
            return {
                "strategy_id": role + "-strategy-" + noun,
                "action_ids": [role + "-" + noun],
                "reason_code": "READONLY_LOOKUP_DECISION",
            }

        class ReadOnlyTurn(ModelDrivenSandboxTurn):
            def __post_init__(self) -> None:
                super().__post_init__()
                self.binding = app.prepare(self.initial, run_id="ga10-run")
                self._planner, self._validator, self._rechecker = app.m4(
                    StructuredStrategyTransportAdapter(model)
                )

            async def execute_and_observe(self, decision: Decision) -> ObservedFact:
                observation = await dispatcher.observe(
                    decision=decision,
                    step_index=self.actions,
                    run_id=self.binding.run_id,
                    execution_id=f"readonly-{self.actions + 1}",
                )
                self.actions += 1
                return observation

        initial = build_runtime_input(text="look up approved domain records")
        result = await app.run(
            initial,
            run_id="ga10-run",
            step=ReadOnlyTurn(initial),
            budget=LoopBudget(max_iterations=steps + 2, max_executions=steps + 1),
            execution_catalog=catalog,
        )
        assert result.kind is RunKind.FINISH
        assert result.executions == steps
        assert result.observations[-1].facts[-1] == "GOAL_SATISFIED"
        assert all(
            step.completion_fact in fact.facts
            for step, fact in zip(
                catalog.workflow.steps, result.observations, strict=True
            )
        )

    asyncio.run(scenario())


def test_readonly_lookup_rejects_foreign_tampered_or_missing_records(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path / "stock", steps=1)
    catalog = bootstrap_domain_application(snapshot).execution_catalog(snapshot)
    step = catalog.workflow.steps[0]
    records = _records(catalog.domain_id, 1)
    key_map = {step.step_id: "record-1"}
    with pytest.raises(RunBoundaryError, match="scope mismatch"):
        ReadOnlyDomainLookup(catalog, records, {step.step_id: "not-found"})
    foreign = _records("other-domain", 1)
    with pytest.raises(RunBoundaryError, match="scope mismatch"):
        ReadOnlyDomainLookup(catalog, foreign, key_map)
    with pytest.raises(RunBoundaryError, match="invalid read-only record"):
        ReadOnlyRecord(catalog.domain_id, "record-1", "tampered", "0" * 64)
    with pytest.raises(RunBoundaryError, match="explicit snapshots"):
        ReadOnlyDomainLookup(catalog, records, {}) if False else ReadOnlyDomainLookup(
            catalog, records, type("NotDict", (), {})()
        )
