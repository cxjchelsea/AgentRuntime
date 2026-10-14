"""GA-16: dynamic tool ordering/subset and observation-driven replanning E2E."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from agent_core.domain_application import bootstrap_domain_application
from agent_core.dynamic_business_task import DynamicBusinessTask
from agent_core.model_adapter import StructuredStrategyTransportAdapter
from agent_core.readonly_business_tools import ReadOnlyBusinessTools
from agent_core.runner import (
    AgentRunCoordinator,
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
    reason="GA-16 verified domain package fixture requires Linux",
)


@pytest.mark.parametrize(
    ("order", "required"),
    [
        (("verify-notes", "collect-notes"), frozenset({"step-1", "step-2"})),
        (("collect-notes", "verify-notes"), frozenset({"step-1", "step-2"})),
        (("collect-notes",), frozenset({"step-1"})),
    ],
)
def test_dynamic_model_tool_choice_and_replanning(
    tmp_path: Path, order: tuple[str, ...], required: frozenset[str]
) -> None:
    async def scenario() -> None:
        snapshot = _snapshot(tmp_path / "domain", steps=2)
        app = bootstrap_domain_application(snapshot)
        catalog = app.execution_catalog(snapshot)
        task = DynamicBusinessTask(catalog, required)
        keys = {
            step.step_id: f"learning-{i}"
            for i, step in enumerate(catalog.workflow.steps)
        }
        database = tmp_path / "learning.sqlite"
        _database(
            database,
            [
                _row(catalog, keys[step.step_id], {"completed": index, "total": 5})
                for index, step in enumerate(catalog.workflow.steps, 1)
            ],
        )
        lookup = load_sqlite_business_snapshot(
            catalog=catalog, database_file=database, step_keys=keys
        )
        dispatcher = SandboxToolDispatcher(
            catalog,
            ReadOnlyBusinessTools(
                lookup,
                {step.step_id: "learning_progress" for step in catalog.workflow.steps},
            ).handlers(),
        )
        calls: list[dict[str, Any]] = []

        async def model(payload: dict[str, Any]) -> dict[str, object]:
            calls.append(payload)
            selected = order[len(calls) - 1]
            assert selected in payload["candidate_action_ids"]
            return {
                "strategy_id": selected.replace("-notes", "-strategy-notes"),
                "action_ids": [selected],
                "reason_code": "DYNAMIC_REPLAN_AFTER_OBSERVATION",
            }

        class DynamicTurn(ModelDrivenSandboxTurn):
            def __post_init__(self) -> None:
                super().__post_init__()
                self.binding = app.prepare(self.initial, run_id="ga16-run")
                self._planner, self._validator, self._rechecker = app.m4(
                    StructuredStrategyTransportAdapter(model)
                )
                self.prior: tuple[ObservedFact, ...] = ()
                self.chosen: list[str] = []

            async def decide(self, current_input, iteration, observations):
                self.prior = observations
                if task.completed(self.binding.run_id, observations):
                    # Completion is determined by task-specific correlated evidence,
                    # not a model's premature GOAL_SATISFIED claim.
                    last_id = observations[-1].workflow_step_id
                    step = next(
                        step
                        for step in catalog.workflow.steps
                        if step.step_id == last_id
                    )
                    return Decision(
                        iteration,
                        "FINISH",
                        reason="GA16_TASK_GOAL_VERIFIED",
                        completion_fact=step.completion_fact,
                    )
                # Catalogue GOAL_SATISFIED means only a catalogue last step;
                # it must not terminate a dynamic task with pending steps.
                visible = tuple(
                    replace(
                        obs,
                        facts=tuple(f for f in obs.facts if f != "GOAL_SATISFIED"),
                    )
                    for obs in observations
                )
                return await super().decide(current_input, iteration, visible)

            async def execute_and_observe(self, decision: Decision) -> ObservedFact:
                index, step = task.approved_next(decision, self.prior)
                observation = await dispatcher.observe(
                    decision=decision,
                    step_index=index,
                    run_id=self.binding.run_id,
                    execution_id=f"ga16-execution-{self.actions + 1}",
                )
                self.actions += 1
                self.chosen.append(step.action_id)
                return observation

        question = "先核查学习进度，再根据查询结果决定下一步"
        initial = build_runtime_input(text=question)
        turn = DynamicTurn(initial)
        outcome = await AgentRunCoordinator(
            turn,
            LoopBudget(max_iterations=4, max_executions=3),
            completion_check=task.completed,
            execution_guard=lambda decision, observation, index: task.guard(
                decision, observation, index, turn.prior
            ),
        ).run(initial, turn.binding)
        assert outcome.kind is RunKind.FINISH
        assert outcome.executions == len(order)
        assert turn.chosen == list(order)
        assert [x.workflow_step_id for x in outcome.observations] == [
            "step-2" if item == "verify-notes" else "step-1" for item in order
        ]
        assert len(calls) == len(order)
        if order[0] == "verify-notes" and len(order) == 2:
            assert "FACT_2" in calls[1]["last_agent_action"]
        assert database.exists()

    asyncio.run(scenario())


def test_dynamic_task_rejects_foreign_and_replayed_steps(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path / "domain", steps=2)
    catalog = bootstrap_domain_application(snapshot).execution_catalog(snapshot)
    with pytest.raises(RunBoundaryError, match="outside approved"):
        DynamicBusinessTask(catalog, frozenset({"foreign-step"}))
    with pytest.raises(RunBoundaryError, match="outside approved"):
        DynamicBusinessTask(catalog, frozenset())
    task = DynamicBusinessTask(catalog, frozenset({"step-1"}))
    assert not task.completed(
        "ga16-run",
        (
            ObservedFact(
                "ga16-run",
                "req",
                "plan",
                "exec",
                catalog.binding_fingerprint,
                ("FACT_1",),
            ),
        ),
    )
    assert not task.completed(
        "ga16-run",
        (
            ObservedFact(
                "another-run",
                "req",
                "plan",
                "exec",
                catalog.binding_fingerprint,
                ("FACT_1",),
                "step-1",
                catalog.workflow.steps[0].tool_id,
            ),
        ),
    )
