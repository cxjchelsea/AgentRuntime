"""GA-16: dynamic tool ordering/subset and observation-driven replanning E2E."""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from agent_core.chat_transport import (
    ChatCompletionsConfig,
    ChatCompletionsStrategyTransport,
)
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
    ("order", "required", "live"),
    [
        (("verify-notes", "collect-notes"), frozenset({"step-1", "step-2"}), False),
        (("collect-notes", "verify-notes"), frozenset({"step-1", "step-2"}), False),
        (("collect-notes",), frozenset({"step-1"}), False),
        (("verify-notes", "collect-notes"), frozenset({"step-1", "step-2"}), True),
    ],
)
def test_dynamic_model_tool_choice_and_replanning(
    tmp_path: Path, order: tuple[str, ...], required: frozenset[str], live: bool
) -> None:
    if live and os.environ.get("GA16_LIVE_OPT_IN") != "1":
        pytest.skip("GA-16 dynamic Qwen test requires local-model opt-in")

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
        live_model = None
        if live:
            config = ChatCompletionsConfig(
                endpoint=os.environ["GA01C_LLM_URL"],
                model=os.environ["GA01C_LLM_MODEL"],
                api_key=os.environ.get("GA01C_LLM_API_KEY", ""),
                timeout_seconds=45.0,
                max_tokens=180,
            )
            live_model = ChatCompletionsStrategyTransport(
                config,
                system_instruction=(
                    "You are a sandbox read-only learning task agent. Choose a "
                    "strategy and action ONLY from legal_strategy_ids and "
                    "candidate_action_ids, and return exactly a JSON object "
                    "strategy_id, action_ids, reason_code. The user requests "
                    "verification FIRST and then a collection based on that result. "
                    "If last_agent_action is FACT_2, select collect-strategy-notes "
                    "and collect-notes. Otherwise select verify-strategy-notes "
                    "and verify-notes. Do not invent tools or claim external actions. "
                    "Set reason_code DYNAMIC_REPLAN_AFTER_OBSERVATION."
                ),
            )

        async def model(payload: dict[str, Any]) -> dict[str, object]:
            calls.append(payload)
            if live_model is not None:
                # The first choice may use the full task-allowed set; after an
                # observation, only never-executed steps remain eligible.
                completed = {obs.workflow_step_id for obs in turn.prior}
                remaining = [
                    step.action_id
                    for step in catalog.workflow.steps
                    if step.step_id in task.required_steps
                    and step.step_id not in completed
                ]
                bounded = dict(payload)
                bounded["candidate_action_ids"] = [
                    action
                    for action in payload["candidate_action_ids"]
                    if action in remaining
                ]
                bounded["legal_strategy_ids"] = [
                    strategy
                    for strategy in payload["legal_strategy_ids"]
                    if any(
                        strategy == action.replace("-notes", "-strategy-notes")
                        for action in remaining
                    )
                ]
                if not bounded["candidate_action_ids"] or len(
                    bounded["candidate_action_ids"]
                ) != len(bounded["legal_strategy_ids"]):
                    raise ValueError("no current task-approved model candidates")
                # Correction is permitted only before a physical tool attempt.
                for attempt in range(2):
                    proposed = dict(await live_model(bounded))
                    selected = proposed.get("action_ids")
                    if (
                        type(selected) is list
                        and len(selected) == 1
                        and selected[0] in bounded["candidate_action_ids"]
                        and proposed.get("strategy_id")
                        == selected[0].replace("-notes", "-strategy-notes")
                    ):
                        return proposed
                    if attempt == 0:
                        bounded["previous_choice_invalid"] = True
                raise ValueError("real model did not select a pending action")
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
            LoopBudget(
                max_iterations=4,
                max_executions=3,
                max_decision_seconds=70.0 if live else 5.0,
            ),
            completion_check=task.completed,
            execution_guard=lambda decision, observation, index: task.guard(
                decision, observation, index, turn.prior
            ),
        ).run(initial, turn.binding)
        assert outcome.kind is RunKind.FINISH
        assert outcome.executions == len(order)
        assert set(turn.chosen) == set(order) if live else turn.chosen == list(order)
        assert [x.workflow_step_id for x in outcome.observations] == [
            "step-2" if item == "verify-notes" else "step-1" for item in turn.chosen
        ]
        assert len(calls) == len(order)
        if len(order) == 2:
            assert calls[1]["last_agent_action"] in {"FACT_1", "FACT_2"}
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
