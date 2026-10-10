"""DIAG-03: typed M4 observation, source verification, real model compatibility."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest

from agent_core.chat_transport import (
    ChatCompletionsConfig,
    ChatCompletionsStrategyTransport,
)
from agent_core.iteration import AgentRunBinding
from agent_core.model_adapter import StructuredStrategyTransportAdapter
from agent_core.runner import (
    AgentRunCoordinator,
    LoopBudget,
    ObservedFact,
    RunKind,
)
from runtime.planning.strategy_selection import (
    PlanningObservationContext,
    StrategyModelRequestBuilder,
)
from tests.ga01.initial_evidence import admit_initial_evidence
from tests.ga01.typed_observation import (
    after_verified_execution,
    from_initial_evidence,
)
from tests.orchestration_stubs import build_runtime_input
from tests.test_ga01_slice2_m4 import _build_model_planner
from tests.test_ga01c_diag02_e2e import (
    _NOW,
    InitialEvidenceTurn,
    _seed_store,
)
from tests.test_ga01c_eval02 import TASKS, TaskCase, _semantic_instruction


class TypedPlanningTurn(InitialEvidenceTurn):
    def __post_init__(self) -> None:
        super().__post_init__()
        self._typed_initial = from_initial_evidence(
            self.initial_rule.accepted, self.binding
        )
        self._typed = self._typed_initial
        self.model_payloads: list[dict[str, Any]] = []
        config = ChatCompletionsConfig(
            endpoint=os.environ["GA01C_LLM_URL"],
            model=os.environ["GA01C_LLM_MODEL"],
            timeout_seconds=45,
            max_tokens=160,
        )
        live = ChatCompletionsStrategyTransport(
            config, system_instruction=_semantic_instruction(self.case)
        )

        async def capture(payload: dict[str, Any]) -> dict[str, object]:
            self.model_payloads.append(payload)
            return dict(await live(payload))

        planner = _build_model_planner(
            StructuredStrategyTransportAdapter(
                capture, include_legacy_agent_action=False
            ),
            eligibility_rules=self.planning_eligibility_rules(),
            request_builder=StrategyModelRequestBuilder(
                observation_provider=lambda: self._typed
            ),
        )
        self._planner = planner.planner
        self._validator = planner.validator
        self._rechecker = planner.rechecker

    def model_observation_projection(self, observations: tuple[ObservedFact, ...]):
        # Legacy DIAG-02 M4 eligibility still uses the checked sandbox snapshot
        # internally. It is explicitly omitted from the model input.
        legacy = super().model_observation_projection(observations)
        if observations:
            self._typed = after_verified_execution(
                self.binding,
                observations,
                self.projector,
                tuple(self.selected_actions),
                self._typed_initial,
            )
        return legacy


def _make_step(case: TaskCase) -> TypedPlanningTurn:
    initial = build_runtime_input(text=case.goal)
    binding = AgentRunBinding.from_input(
        initial,
        run_id=f"eval02-{case.case_id}",
        domain_id=f"eval02-{case.family}",
        domain_version="v1",
        binding_fingerprint=f"eval02-{case.family}-v1",
    )
    provider, evidence_id = _seed_store(binding, case)
    admitted = admit_initial_evidence(binding, provider, evidence_id, now=_NOW)
    return TypedPlanningTurn(initial, case, admitted)


def test_typed_contract_bounds_and_explicit_unknown() -> None:
    unknown = PlanningObservationContext(1, "UNKNOWN", (), (), (), "NONE")
    assert unknown.evidence_refs == ()
    with pytest.raises(ValueError):
        PlanningObservationContext(2, "UNKNOWN", (), (), (), "NONE")
    with pytest.raises(ValueError):
        PlanningObservationContext(1, "CLAIMED_VALID", (), (), (), "NONE")
    with pytest.raises(ValueError):
        PlanningObservationContext(1, "UNKNOWN", ("tool:" + "x" * 130,), (), (), "NONE")


def test_initial_evidence_becomes_typed_context_without_goal_or_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GA01C_LLM_URL", "http://127.0.0.1:11434/v1/chat/completions")
    monkeypatch.setenv("GA01C_LLM_MODEL", "not-called")
    for case in (TASKS[0], TASKS[3]):
        step = _make_step(case)
        observation = step._typed
        assert observation.evidence_state == (
            "AVAILABLE_UNVERIFIED" if case.source_available else "UNKNOWN"
        )
        assert case.goal not in repr(observation)
        assert case.expected_actions[0] not in observation.executed_action_ids


def test_foreign_observation_does_not_enter_typed_model_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GA01C_LLM_URL", "http://127.0.0.1:11434/v1/chat/completions")
    monkeypatch.setenv("GA01C_LLM_MODEL", "not-called")
    step = _make_step(TASKS[0])
    fake = ObservedFact(
        run_id="other-run",
        request_id="fake-req",
        plan_id="fake-plan",
        execution_id="fake-exec",
        domain_fingerprint=step.binding.binding_fingerprint,
        facts=("SOURCE_AVAILABLE",),
    )
    with pytest.raises(ValueError):
        step.model_observation_projection((fake,))
    assert step._typed.evidence_state == "UNKNOWN"


@pytest.mark.skipif(
    not (
        os.environ.get("GA01C_DIAG03_OPT_IN") == "1"
        and os.environ.get("GA01C_LLM_URL")
        and os.environ.get("GA01C_LLM_MODEL")
    ),
    reason="real local typed-planning Qwen test requires explicit opt-in",
)
def test_diag03_real_model_typed_multitask_e2e() -> None:
    async def evaluate() -> None:
        completed = 0
        correct = 0
        total = 0
        for repeat in (1, 2):
            for case in TASKS:
                step = _make_step(case)
                result = await AgentRunCoordinator(
                    step,
                    LoopBudget(
                        max_iterations=4,
                        max_executions=3,
                        max_no_progress=1,
                        max_decision_seconds=55,
                        max_execution_seconds=5,
                    ),
                ).run(step.initial, step.binding)
                actions = tuple(step.selected_actions)
                expected = case.expected_actions
                finished = (
                    result.kind is RunKind.FINISH
                    and bool(result.observations)
                    and result.observations[-1].facts == ("GOAL_SATISFIED",)
                )
                completed += int(finished)
                count = max(len(actions), len(expected))
                total += count
                correct += sum(
                    i < len(actions) and i < len(expected) and actions[i] == expected[i]
                    for i in range(count)
                )
                assert all("last_agent_action" not in p for p in step.model_payloads)
                assert all("planning_observation" in p for p in step.model_payloads)
                print(
                    f"DIAG03 case={case.case_id} repeat={repeat} actions={actions} "
                    f"expected={expected} finished={finished} "
                    f"typed_model_requests={len(step.model_payloads)}",
                    flush=True,
                )
        accuracy = correct / total if total else 0.0
        print(
            f"DIAG03_SUMMARY complete={completed}/12 "
            f"correct={correct}/{total} accuracy={accuracy:.3f}",
            flush=True,
        )
        assert completed >= 10
        assert accuracy >= 0.90

    asyncio.run(evaluate())
