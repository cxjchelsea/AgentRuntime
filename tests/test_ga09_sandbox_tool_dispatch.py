"""GA-09 two-domain approved M4 -> registered sandbox handler -> observation E2E."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

from agent_core.domain_application import bootstrap_domain_application
from agent_core.iteration import IterationRef
from agent_core.model_adapter import StructuredStrategyTransportAdapter
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
    reason="D2-A verified package loader is Linux-only",
)


@pytest.mark.parametrize("steps", [1, 2])
def test_two_domains_registered_tool_dispatch_in_agent_loop(
    tmp_path: Path, steps: int
) -> None:
    async def scenario() -> None:
        snapshot = _snapshot(tmp_path / "domain", steps=steps)
        app = bootstrap_domain_application(snapshot)
        catalog = app.execution_catalog(snapshot)
        noun = "stock" if steps == 1 else "notes"
        calls: list[tuple[str, str]] = []

        async def handler(step_id: str, tool_id: str) -> tuple[str, ...]:
            calls.append((step_id, tool_id))
            index = int(step_id.removeprefix("step-"))
            expected = ("FACT_" + str(index),)
            if index == steps:
                return (*expected, "GOAL_SATISFIED")
            return expected

        dispatcher = SandboxToolDispatcher(
            catalog, dict.fromkeys(catalog.tool_ids, handler)
        )

        async def model(payload: dict[str, Any]) -> dict[str, object]:
            role = "verify" if payload["last_agent_action"] == "FACT_1" else "collect"
            return {
                "strategy_id": role + "-strategy-" + noun,
                "action_ids": [role + "-" + noun],
                "reason_code": "HANDLER_DRIVEN_DOMAIN_DECISION",
            }

        class HandlerTurn(ModelDrivenSandboxTurn):
            def __post_init__(self) -> None:
                super().__post_init__()
                self.binding = app.prepare(self.initial, run_id="ga09-run")
                self._planner, self._validator, self._rechecker = app.m4(
                    StructuredStrategyTransportAdapter(model)
                )

            async def execute_and_observe(self, decision: Decision) -> ObservedFact:
                index = self.actions
                observed = await dispatcher.observe(
                    decision=decision,
                    step_index=index,
                    run_id=self.binding.run_id,
                    execution_id="handler-execution-" + str(index + 1),
                )
                self.actions += 1
                return observed

        initial = build_runtime_input(text="perform sandbox package workflow")
        turn = HandlerTurn(initial)
        result = await app.run(
            initial,
            run_id="ga09-run",
            step=turn,
            budget=LoopBudget(max_iterations=steps + 2, max_executions=steps + 1),
            execution_catalog=catalog,
        )
        assert result.kind is RunKind.FINISH
        assert result.executions == steps
        assert calls == [
            (step.step_id, step.tool_id) for step in catalog.workflow.steps
        ]
        assert all(
            obs.workflow_step_id == step.step_id and obs.tool_id == step.tool_id
            for obs, step in zip(
                result.observations, catalog.workflow.steps, strict=True
            )
        )

    asyncio.run(scenario())


def test_handler_registry_rejects_missing_or_foreign_tools(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path / "domain", steps=1)
    catalog = bootstrap_domain_application(snapshot).execution_catalog(snapshot)
    with pytest.raises(RunBoundaryError, match="registry mismatch"):
        SandboxToolDispatcher(catalog, {})

    async def foreign(step_id: str, tool_id: str) -> tuple[str, ...]:
        return (step_id, tool_id)

    with pytest.raises(RunBoundaryError, match="registry mismatch"):
        SandboxToolDispatcher(catalog, {"foreign-tool": foreign})


def test_handler_fails_closed_on_incomplete_evidence(tmp_path: Path) -> None:
    async def scenario() -> None:
        snapshot = _snapshot(tmp_path / "domain", steps=1)
        app = bootstrap_domain_application(snapshot)
        catalog = app.execution_catalog(snapshot)
        calls = 0

        async def incomplete(step_id: str, tool_id: str) -> tuple[str, ...]:
            nonlocal calls
            calls += 1
            return ("UNRELATED",)

        dispatcher = SandboxToolDispatcher(catalog, {catalog.tool_ids[0]: incomplete})
        initial = build_runtime_input(text="validate incomplete tool")

        async def model(payload: dict[str, Any]) -> dict[str, object]:
            del payload
            return {
                "strategy_id": "collect-strategy-stock",
                "action_ids": ["collect-stock"],
                "reason_code": "SANDBOX_VALID_ACTION",
            }

        class PackageTurn(ModelDrivenSandboxTurn):
            def __post_init__(self) -> None:
                super().__post_init__()
                self.binding = app.prepare(self.initial, run_id="ga09-incomplete")
                self._planner, self._validator, self._rechecker = app.m4(
                    StructuredStrategyTransportAdapter(model)
                )

        turn = PackageTurn(initial)
        current = turn.binding.iteration_input(initial, ordinal=0)
        iteration = IterationRef.from_input(turn.binding, current, ordinal=0)
        decision = await turn.decide(current, iteration, ())
        assert decision.approved is not None
        with pytest.raises(RunBoundaryError, match="observation incomplete"):
            await dispatcher.observe(
                decision=decision,
                step_index=0,
                run_id="ga09-incomplete",
                execution_id="execution-1",
            )
        assert calls == 1

        async def broken(step_id: str, tool_id: str) -> tuple[str, ...]:
            raise ValueError("sensitive handler detail")

        registered = {catalog.tool_ids[0]: broken}
        isolated = SandboxToolDispatcher(catalog, registered)
        registered.clear()
        assert catalog.tool_ids[0] in isolated.handlers
        with pytest.raises(RunBoundaryError, match="sandbox tool handler failed") as error:
            await isolated.observe(
                decision=decision,
                step_index=0,
                run_id="ga09-incomplete",
                execution_id="execution-2",
            )
        assert "sensitive handler detail" not in str(error.value)

        async def cancelled(step_id: str, tool_id: str) -> tuple[str, ...]:
            raise asyncio.CancelledError()

        cancellation_dispatch = SandboxToolDispatcher(
            catalog, {catalog.tool_ids[0]: cancelled}
        )
        with pytest.raises(asyncio.CancelledError):
            await cancellation_dispatch.observe(
                decision=decision,
                step_index=0,
                run_id="ga09-incomplete",
                execution_id="execution-3",
            )

    asyncio.run(scenario())
