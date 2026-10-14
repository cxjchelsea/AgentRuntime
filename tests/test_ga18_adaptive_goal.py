"""GA-18 successful-but-incomplete observation -> real model replan -> verified goal."""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from agent_core.adaptive_goal import AdaptiveGoalSession, GoalVerdict
from agent_core.chat_transport import ChatCompletionsConfig, ChatCompletionsStrategyTransport
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
    reason="verified sandbox business fixtures require Linux",
)


def _proposal(*steps: tuple[str, tuple[str, ...]]) -> dict[str, object]:
    return {
        "goal_id": "study-check",
        "steps": [
            {"step_id": key, "depends_on": list(deps)} for key, deps in steps
        ],
    }


@pytest.mark.parametrize("live", [False, True])
def test_adaptive_replan_from_business_observation_to_verified_goal(
    tmp_path: Path, live: bool
) -> None:
    if live and os.getenv("GA18_LIVE_OPT_IN") != "1":
        pytest.skip("real Qwen adaptive goal replan requires opt-in")

    async def scenario() -> None:
        snapshot = _snapshot(tmp_path / "package", steps=2)
        app = bootstrap_domain_application(snapshot)
        catalog = app.execution_catalog(snapshot)
        goal = AdmittedGoal(catalog, "study-check", frozenset({"FACT_2"}))
        initial = GoalPlan.from_model(goal, _proposal(("step-2", ())))
        session = AdaptiveGoalSession(
            initial, "step-2", "LEARNING_INCOMPLETE", "step-1"
        )
        keys = {
            step.step_id: f"study-{index}"
            for index, step in enumerate(catalog.workflow.steps, 1)
        }
        database = tmp_path / "learning.sqlite"
        _database(
            database,
            [
                _row(catalog, keys[step.step_id], {"completed": 2, "total": 5})
                for step in catalog.workflow.steps
            ],
        )
        lookup = load_sqlite_business_snapshot(
            catalog=catalog, database_file=database, step_keys=keys
        )
        dispatcher = SandboxToolDispatcher(
            catalog,
            ReadOnlyBusinessTools(
                lookup,
                {
                    step.step_id: "learning_progress"
                    for step in catalog.workflow.steps
                },
            ).handlers(),
        )
        replan_calls = 0
        if live:
            config = ChatCompletionsConfig(
                endpoint=os.environ["GA01C_LLM_URL"],
                model=os.environ["GA01C_LLM_MODEL"],
                api_key=os.environ.get("GA01C_LLM_API_KEY", ""),
                timeout_seconds=45.0,
                max_tokens=230,
            )
            instruction = (
                "You are a JSON DAG re-planner for a sandbox READ ONLY goal. "
                "An executed study check step-2 returned FACT_2 and "
                "LEARNING_INCOMPLETE. The goal now needs a separate verification "
                "from step-1. Return exactly goal_id and steps. "
                "The first step MUST be step-2 with empty depends_on because "
                "it already executed; append step-1 with empty depends_on. "
                'Return JSON exactly shaped like {"goal_id":"study-check",'
                '"steps":[{"step_id":"step-2","depends_on":[]},'
                '{"step_id":"step-1","depends_on":[]}]}. '
                "Do not remove or rewrite executed step-2. Do not claim to "
                "have performed a task. No strategy_id, action_ids, extra keys."
            )
            model = ChatCompletionsStrategyTransport(
                config,
                system_instruction=instruction,
                message_builder=lambda data: (
                    {"role": "system", "content": instruction},
                    {
                        "role": "user",
                        "content": (
                            "Admitted goal study-check requires FACT_2. "
                            "Observation from step-2: FACT_2, LEARNING_INCOMPLETE. "
                            "Add step-1 to verify, preserve step-2. "
                            + (
                                "Fix JSON schema and do not add fields."
                                if data.get("invalid_replan")
                                else ""
                            )
                        ),
                    },
                ),
            )

        async def replan(run_id: str, observations: tuple[ObservedFact, ...]) -> None:
            nonlocal session, replan_calls
            replan_calls += 1
            if live:
                for attempt in range(2):
                    raw = await model(
                        {
                            "legal_strategy_ids": [],
                            "candidate_action_ids": [],
                            "invalid_replan": attempt > 0,
                        }
                    )
                    try:
                        proposed = GoalPlan.from_model(goal, raw)
                        session = session.revised(proposed, run_id, observations)
                        break
                    except RunBoundaryError:
                        if attempt:
                            raise
            else:
                proposed = GoalPlan.from_model(
                    goal, _proposal(("step-2", ()), ("step-1", ()))
                )
                session = session.revised(proposed, run_id, observations)

        decisions: list[str] = []

        async def select(payload: dict[str, Any]) -> dict[str, object]:
            eligible = session.plan.eligible("ga18-run", turn.prior)
            if len(eligible) != 1:
                raise RunBoundaryError("goal next step ambiguous")
            action = eligible[0].action_id
            if action not in payload["candidate_action_ids"]:
                raise RunBoundaryError("unapproved goal model action")
            decisions.append(action)
            return {
                "strategy_id": action.replace("-notes", "-strategy-notes"),
                "action_ids": [action],
                "reason_code": "GA18_OBSERVATION_DRIVEN_REPLAN",
            }

        class AdaptiveTurn(ModelDrivenSandboxTurn):
            def __post_init__(self) -> None:
                super().__post_init__()
                self.binding = app.prepare(self.initial, run_id="ga18-run")
                self._planner, self._validator, self._rechecker = app.m4(
                    StructuredStrategyTransportAdapter(select)
                )
                self.prior: tuple[ObservedFact, ...] = ()
                self.count = 0

            async def decide(self, current_input, iteration, observations):
                self.prior = observations
                verdict = session.assess(self.binding.run_id, observations)
                if verdict is GoalVerdict.NEEDS_REPLAN:
                    await replan(self.binding.run_id, observations)
                    verdict = session.assess(self.binding.run_id, observations)
                if verdict is GoalVerdict.VERIFIED:
                    return Decision(
                        iteration,
                        "FINISH",
                        reason="GA18_GOAL_EVIDENCE_VERIFIED",
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
                eligible = session.plan.eligible(self.binding.run_id, self.prior)
                matches = [
                    (index, step)
                    for index, step in enumerate(catalog.workflow.steps)
                    if step in eligible
                    and decision.approved is not None
                    and decision.approved.steps[0].action == step.action_id
                ]
                if len(matches) != 1:
                    raise RunBoundaryError("replanned step not executable")
                index, _ = matches[0]
                observation = await dispatcher.observe(
                    decision=decision,
                    step_index=index,
                    run_id=self.binding.run_id,
                    execution_id=f"ga18-exec-{self.count + 1}",
                )
                self.count += 1
                return observation

        initial_input = build_runtime_input(
            text="检查学习进度，如进度尚未完成则再核验学习记录"
        )
        turn = AdaptiveTurn(initial_input)

        def guard(
            decision: Decision, observation: ObservedFact | None, index: int
        ) -> bool:
            if index != len(turn.prior) or decision.approved is None:
                return False
            eligible = session.plan.eligible(turn.binding.run_id, turn.prior)
            matches = [
                step for step in eligible
                if step.action_id == decision.approved.steps[0].action
            ]
            return len(matches) == 1 and (
                observation is None
                or (
                    observation.workflow_step_id == matches[0].step_id
                    and observation.tool_id == matches[0].tool_id
                    and matches[0].completion_fact in observation.facts
                )
            )

        def completed(run_id: str, facts: tuple[ObservedFact, ...]) -> bool:
            return session.assess(run_id, facts) is GoalVerdict.VERIFIED

        result = await AgentRunCoordinator(
            turn,
            LoopBudget(max_iterations=4, max_executions=3),
            completion_check=completed,
            execution_guard=guard,
        ).run(initial_input, turn.binding)
        assert result.kind is RunKind.FINISH
        assert replan_calls == 1
        assert result.executions == 2
        assert decisions == ["verify-notes", "collect-notes"]
        assert [
            observed.workflow_step_id for observed in result.observations
        ] == ["step-2", "step-1"]
        assert completed(result.run_id, result.observations)
        assert session.replan_count == 1
        assert database.exists()

    asyncio.run(scenario())


def test_replan_requires_trigger_preserves_evidence_and_has_budget(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path / "package", steps=2)
    catalog = bootstrap_domain_application(snapshot).execution_catalog(snapshot)
    goal = AdmittedGoal(catalog, "study-check", frozenset({"FACT_2"}))
    original = GoalPlan.from_model(goal, _proposal(("step-2", ())))
    session = AdaptiveGoalSession(
        original, "step-2", "LEARNING_INCOMPLETE", "step-1"
    )
    step = catalog.workflow.steps[1]
    evidence = ObservedFact(
        "run", "request", "plan", "execution", catalog.binding_fingerprint,
        ("FACT_2", "LEARNING_INCOMPLETE"), "step-2", step.tool_id,
    )
    assert session.assess("run", ()) is GoalVerdict.CONTINUE
    assert session.assess("run", (evidence,)) is GoalVerdict.NEEDS_REPLAN
    unchanged = GoalPlan.from_model(goal, _proposal(("step-2", ())))
    with pytest.raises(RunBoundaryError, match="omits required verifier"):
        session.revised(unchanged, "run", (evidence,))
    changed = GoalPlan.from_model(
        goal, _proposal(("step-2", ()), ("step-1", ("step-2",)))
    )
    with pytest.raises(RunBoundaryError, match="not executable"):
        session.revised(changed, "run", (evidence,))
    replacement = GoalPlan.from_model(
        goal, _proposal(("step-2", ()), ("step-1", ()))
    )
    revised = session.revised(replacement, "run", (evidence,))
    assert revised.replan_count == 1
    with pytest.raises(RunBoundaryError, match="no authorized replan"):
        revised.revised(replacement, "run", (evidence,))
    forged = replace(evidence, plan_id="")
    with pytest.raises(RunBoundaryError, match="unverified"):
        session.assess("run", (forged,))
    with pytest.raises(RunBoundaryError, match="no authorized replan"):
        session.revised(replacement, "run", ())
