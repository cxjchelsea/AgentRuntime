"""GA-17 goal-to-DAG, actual M4 execution, observation and safe replan."""

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
from agent_core.goal_driven_plan import AdmittedGoal, GoalPlan
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
    reason="GA-17 package fixtures require Linux",
)


def _proposal(*items: tuple[str, tuple[str, ...]]) -> dict[str, object]:
    return {
        "goal_id": "study-status",
        "steps": [{"step_id": step, "depends_on": list(deps)} for step, deps in items],
    }


def _admitted(tmp_path: Path) -> AdmittedGoal:
    snapshot = _snapshot(tmp_path / "domain", steps=2)
    catalog = bootstrap_domain_application(snapshot).execution_catalog(snapshot)
    return AdmittedGoal(catalog, "study-status", frozenset({"FACT_2"}))


@pytest.mark.parametrize(
    "bad",
    [
        _proposal(("step-1", ())),
        _proposal(("step-2", ("step-2",))),
        _proposal(("step-1", ("step-2",)), ("step-2", ("step-1",))),
        _proposal(("foreign", ()), ("step-2", ())),
        _proposal(("step-2", ("foreign",))),
        _proposal(("step-2", ()), ("step-2", ())),
        {"goal_id": "foreign", "steps": [{"step_id": "step-2", "depends_on": []}]},
        {
            "goal_id": "study-status",
            "steps": [{"step_id": "step-2", "depends_on": [], "tool_id": "evil"}],
        },
    ],
)
def test_goal_model_plan_rejects_unsafe_proposals(tmp_path: Path, bad: Any) -> None:
    with pytest.raises(RunBoundaryError):
        GoalPlan.from_model(_admitted(tmp_path), bad)


def test_goal_replanning_preserves_executed_evidence(tmp_path: Path) -> None:
    goal = _admitted(tmp_path)
    original = GoalPlan.from_model(
        goal, _proposal(("step-1", ()), ("step-2", ("step-1",)))
    )
    assert [step.step_id for step in original.eligible("run", ())] == ["step-1"]
    evidence = ObservedFact(
        "run",
        "req",
        "plan-1",
        "exec-1",
        goal.catalog.binding_fingerprint,
        ("FACT_1",),
        "step-1",
        goal.catalog.workflow.steps[0].tool_id,
    )
    assert [step.step_id for step in original.eligible("run", (evidence,))] == [
        "step-2"
    ]
    assert not original.completed("run", (evidence,))
    altered = GoalPlan.from_model(
        goal, _proposal(("step-1", (("step-2",))), ("step-2", ()))
    )
    with pytest.raises(RunBoundaryError, match="rewrote"):
        original.revise(altered, "run", (evidence,))
    replacement = GoalPlan.from_model(goal, _proposal(("step-1", ()), ("step-2", ())))
    assert original.revise(replacement, "run", (evidence,)) == replacement
    forged = replace(evidence, tool_id="wrong")
    assert not original.completed("run", (forged,))
    with pytest.raises(RunBoundaryError, match="unverified"):
        original.eligible("run", (forged,))


@pytest.mark.parametrize("live", [False, True])
def test_goal_plan_to_m4_dynamic_sqlite_agent_e2e(tmp_path: Path, live: bool) -> None:
    if live and os.getenv("GA17_LIVE_OPT_IN") != "1":
        pytest.skip("GA-17 live goal planning requires explicit opt-in")

    async def scenario() -> None:
        snapshot = _snapshot(tmp_path / "package", steps=2)
        app = bootstrap_domain_application(snapshot)
        catalog = app.execution_catalog(snapshot)
        goal = AdmittedGoal(catalog, "study-status", frozenset({"FACT_2"}))
        task_text = "查询学习状态，先读取笔记再检查结果"
        if live:
            config = ChatCompletionsConfig(
                endpoint=os.environ["GA01C_LLM_URL"],
                model=os.environ["GA01C_LLM_MODEL"],
                api_key=os.environ.get("GA01C_LLM_API_KEY", ""),
                timeout_seconds=45.0,
                max_tokens=220,
            )
            system = (
                "You are a sandbox goal planner. Return ONLY a JSON object "
                'with goal_id "study-status" and steps list. Each step MUST '
                "have exactly step_id (string) and depends_on (array). "
                "The goal requires FACT_2 from step-2. You may use step-1 "
                "to collect information before step-2. To satisfy the "
                "request to read notes first, output step-1 with empty "
                "dependencies, then step-2 depending on step-1. "
                "Do not invent any tools, fields, steps or external actions."
            )
            transport = ChatCompletionsStrategyTransport(
                config,
                system_instruction=system,
                message_builder=lambda _payload: (
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": (
                            "Goal: study-status; user asks: "
                            + task_text
                            + ". Only admitted step IDs: step-1, step-2; "
                            "step-1 produces FACT_1, step-2 produces FACT_2."
                        ),
                    },
                ),
            )
            proposed = await transport(
                {"legal_strategy_ids": [], "candidate_action_ids": []}
            )
        else:
            proposed = _proposal(("step-1", ()), ("step-2", ("step-1",)))
        plan = GoalPlan.from_model(goal, proposed)
        keys = {
            step.step_id: f"note-{i}"
            for i, step in enumerate(catalog.workflow.steps, 1)
        }
        database = tmp_path / "study.sqlite"
        _database(
            database,
            [
                _row(catalog, keys[step.step_id], {"completed": i, "total": 5})
                for i, step in enumerate(catalog.workflow.steps, 1)
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

        async def strategy(payload: dict[str, Any]) -> dict[str, object]:
            calls.append(payload)
            eligible = plan.eligible("goal-run", turn.prior)
            if len(eligible) != 1:
                raise RunBoundaryError("goal plan has non-unique ready action")
            action = eligible[0].action_id
            if action not in payload["candidate_action_ids"]:
                raise RunBoundaryError("goal action not allowed by M4")
            return {
                "strategy_id": action.replace("-notes", "-strategy-notes"),
                "action_ids": [action],
                "reason_code": "GA17_GOAL_PLAN_NEXT",
            }

        class GoalTurn(ModelDrivenSandboxTurn):
            def __post_init__(self) -> None:
                super().__post_init__()
                self.binding = app.prepare(self.initial, run_id="goal-run")
                self._planner, self._validator, self._rechecker = app.m4(
                    StructuredStrategyTransportAdapter(strategy)
                )
                self.prior: tuple[ObservedFact, ...] = ()

            async def decide(self, current_input, iteration, observations):
                self.prior = observations
                if plan.completed(self.binding.run_id, observations):
                    return Decision(
                        iteration,
                        "FINISH",
                        reason="GA17_GOAL_EVIDENCE_VERIFIED",
                        completion_fact="FACT_2",
                    )
                visible = tuple(
                    replace(
                        obs,
                        facts=tuple(
                            fact for fact in obs.facts if fact != "GOAL_SATISFIED"
                        ),
                    )
                    for obs in observations
                )
                return await super().decide(current_input, iteration, visible)

            async def execute_and_observe(self, decision: Decision) -> ObservedFact:
                eligible = plan.eligible(self.binding.run_id, self.prior)
                matches = [
                    (i, step)
                    for i, step in enumerate(catalog.workflow.steps)
                    if step in eligible
                    and decision.approved is not None
                    and decision.approved.steps[0].action == step.action_id
                ]
                if len(matches) != 1:
                    raise RunBoundaryError("goal plan action not executable")
                index, _ = matches[0]
                observed = await dispatcher.observe(
                    decision=decision,
                    step_index=index,
                    run_id=self.binding.run_id,
                    execution_id=f"goal-execution-{self.actions + 1}",
                )
                self.actions += 1
                return observed

        initial = build_runtime_input(text=task_text)
        turn = GoalTurn(initial)

        def guard(
            decision: Decision, observation: ObservedFact | None, index: int
        ) -> bool:
            if index != len(turn.prior) or decision.approved is None:
                return False
            eligible = plan.eligible(turn.binding.run_id, turn.prior)
            candidate = [
                step
                for step in eligible
                if step.action_id == decision.approved.steps[0].action
            ]
            return len(candidate) == 1 and (
                observation is None
                or (
                    observation.workflow_step_id == candidate[0].step_id
                    and observation.tool_id == candidate[0].tool_id
                )
            )

        result = await AgentRunCoordinator(
            turn,
            LoopBudget(
                max_iterations=4,
                max_executions=3,
                max_decision_seconds=10.0,
            ),
            completion_check=plan.completed,
            execution_guard=guard,
        ).run(initial, turn.binding)
        assert result.kind is RunKind.FINISH
        assert result.executions == len(plan.steps)
        assert plan.completed(result.run_id, result.observations)
        assert len(calls) == result.executions
        assert database.exists()

    asyncio.run(scenario())
