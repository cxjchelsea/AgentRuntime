"""GA-13: two real SQLite read-only intake paths through unchanged Agent Loop."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest

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

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="verified package fixture requires Linux",
)


def _database(path: Path, rows: list[tuple[str, str, str, str, str]]) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE business_records (domain_id TEXT, binding_fingerprint TEXT, "
            "record_key TEXT, value TEXT, sha256 TEXT)"
        )
        conn.executemany("INSERT INTO business_records VALUES (?, ?, ?, ?, ?)", rows)


def _row(
    catalog: Any, key: str, data: dict[str, int]
) -> tuple[str, str, str, str, str]:
    value = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return (
        catalog.domain_id,
        catalog.binding_fingerprint,
        key,
        value,
        hashlib.sha256(value.encode()).hexdigest(),
    )


@pytest.mark.parametrize("steps", [1, 2])
def test_sqlite_intake_real_db_two_domain_agent_e2e(tmp_path: Path, steps: int) -> None:
    async def scenario() -> None:
        snapshot = _snapshot(tmp_path / "package", steps=steps)
        app = bootstrap_domain_application(snapshot)
        catalog = app.execution_catalog(snapshot)
        noun = "stock" if steps == 1 else "notes"
        data = (
            ({"on_hand": 8, "reserved": 3, "target": 12},)
            if steps == 1
            else ({"completed": 2, "total": 5}, {"completed": 5, "total": 5})
        )
        step_keys = {
            step.step_id: f"item-{index}"
            for index, step in enumerate(catalog.workflow.steps, 1)
        }
        database = tmp_path / "actual-business.sqlite"
        _database(
            database,
            [
                _row(catalog, step_keys[step.step_id], record)
                for step, record in zip(catalog.workflow.steps, data, strict=True)
            ],
        )
        before = database.read_bytes()
        lookup = load_sqlite_business_snapshot(
            catalog=catalog, database_file=database, step_keys=step_keys
        )
        assert database.read_bytes() == before
        step_keys.clear()
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
                "reason_code": "GA13_SQLITE_BUSINESS_RESULT",
            }

        class SQLiteTurn(ModelDrivenSandboxTurn):
            def __post_init__(self) -> None:
                super().__post_init__()
                self.binding = app.prepare(self.initial, run_id="ga13-run")
                self._planner, self._validator, self._rechecker = app.m4(
                    StructuredStrategyTransportAdapter(model)
                )

            async def execute_and_observe(self, decision: Decision) -> ObservedFact:
                observation = await dispatcher.observe(
                    decision=decision,
                    step_index=self.actions,
                    run_id=self.binding.run_id,
                    execution_id=f"ga13-execution-{self.actions + 1}",
                )
                self.actions += 1
                return observation

        initial = build_runtime_input(text="calculate from SQLite business data")
        result = await app.run(
            initial,
            run_id="ga13-run",
            step=SQLiteTurn(initial),
            budget=LoopBudget(max_iterations=steps + 2, max_executions=steps + 1),
            execution_catalog=catalog,
        )
        assert result.kind is RunKind.FINISH
        assert result.executions == steps
        if steps == 1:
            assert "REPLENISH_QTY_7" in result.observations[0].facts
            assert "AVAILABLE_5" in result.observations[0].facts
        else:
            assert "PROGRESS_PERCENT_40" in result.observations[0].facts
            assert "PROGRESS_PERCENT_100" in result.observations[1].facts
        for step, observation in zip(
            catalog.workflow.steps, result.observations, strict=True
        ):
            record = lookup.records[lookup.step_keys[step.step_id]]
            assert "RECORD_SHA256_" + record.sha256 in observation.facts
        assert database.read_bytes() == before

    asyncio.run(scenario())


def test_sqlite_intake_immutable_after_external_database_changes(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path / "package", steps=1)
    catalog = bootstrap_domain_application(snapshot).execution_catalog(snapshot)
    path = tmp_path / "data.sqlite"
    _database(
        path, [_row(catalog, "sku-1", {"on_hand": 8, "reserved": 3, "target": 12})]
    )
    step = catalog.workflow.steps[0]
    lookup = load_sqlite_business_snapshot(
        catalog=catalog, database_file=path, step_keys={step.step_id: "sku-1"}
    )
    original = lookup.records["sku-1"].value
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE business_records SET value=?, sha256=?",
            (
                '{"on_hand":100,"reserved":0,"target":0}',
                hashlib.sha256(b'{"on_hand":100,"reserved":0,"target":0}').hexdigest(),
            ),
        )
    assert lookup.records["sku-1"].value == original
    assert original != '{"on_hand":100,"reserved":0,"target":0}'


@pytest.mark.parametrize(
    "problem",
    ["missing", "duplicate", "bad_digest", "foreign", "missing_db", "symlink"],
)
def test_sqlite_intake_fail_closed_on_untrusted_rows(
    tmp_path: Path, problem: str
) -> None:
    snapshot = _snapshot(tmp_path / "package", steps=1)
    catalog = bootstrap_domain_application(snapshot).execution_catalog(snapshot)
    key = "sku-1"
    row = _row(catalog, key, {"on_hand": 8, "reserved": 3, "target": 12})
    if problem == "missing":
        rows = []
    elif problem == "duplicate":
        rows = [row, row]
    elif problem == "bad_digest":
        rows = [(*row[:-1], "0" * 64)]
    elif problem == "foreign":
        rows = [("another.domain", *row[1:])]
    else:
        rows = [row]
    database = tmp_path / "data.sqlite"
    if problem != "missing_db":
        _database(database, rows)
    if problem == "symlink":
        link = tmp_path / "linked.sqlite"
        link.symlink_to(database)
        database = link
    with pytest.raises(RunBoundaryError, match="SQLite|record snapshot"):
        load_sqlite_business_snapshot(
            catalog=catalog,
            database_file=database,
            step_keys={catalog.workflow.steps[0].step_id: key},
        )
