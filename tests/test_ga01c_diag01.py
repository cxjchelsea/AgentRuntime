"""EVAL-02-DIAG-01: controlled A/B/C observation-to-replanning comparison.

A: verified observation as original natural-language text.
B: same verified facts as a typed, JSON-encoded planning state.
C: B plus a domain eligibility rule suppressing a provably redundant collect
   strategy; policy/registry/M4 approval remain authoritative.

Each arm uses genuine Ollama inference and the same six cases/repeats/budget.
No ground-truth action sequence is included in the model's prompt.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass

import pytest

from agent_core.runner import AgentRunCoordinator, LoopBudget, ObservedFact, RunKind
from runtime.contracts import RuntimeContext, RuntimeInput, UnderstandingState
from runtime.contracts.context import InteractionContext
from runtime.planning.candidates import PlanningActionCandidate
from runtime.planning.goals import GoalResolutionResult
from runtime.registries import StrategyDefinition
from tests.orchestration_stubs import build_runtime_context, build_runtime_input
from tests.test_ga01c_eval02 import (
    TASKS,
    CaseResult,
    MultiTaskSandboxTurn,
    TaskCase,
    _semantic_instruction,
)
from tests.test_m4_candidate_strategy_selection import (
    _goals,
    _strategy_registry,
    _understanding,
)

_ARMS = ("A_TEXT", "B_TYPED", "C_TYPED_ELIGIBILITY")
_AVAILABLE_FACTS = frozenset({"SOURCE_AVAILABLE", "SOURCE_ALREADY_AVAILABLE"})


@dataclass(frozen=True, slots=True)
class VerifiedPlanningSnapshot:
    """Test-only read projection, NOT an authority-bearing production result."""

    evidence_state: str
    evidence_fact: str
    executed_actions: tuple[str, ...]
    outstanding_condition: str
    provenance: str = "VERIFIED_SANDBOX_MOCK"

    def encode(self) -> str:
        return json.dumps(
            {
                "evidence_state": self.evidence_state,
                "evidence_fact": self.evidence_fact,
                "executed_actions": list(self.executed_actions),
                "outstanding_condition": self.outstanding_condition,
                "provenance": self.provenance,
            },
            sort_keys=True,
        )


def _decode_verified_snapshot(value: str | None) -> VerifiedPlanningSnapshot | None:
    if not value:
        return None
    try:
        raw = json.loads(value)
    except (ValueError, TypeError):
        return None
    if (
        not isinstance(raw, dict)
        or raw.get("provenance") != "VERIFIED_SANDBOX_MOCK"
        or not isinstance(raw.get("evidence_fact"), str)
        or not isinstance(raw.get("evidence_state"), str)
        or not isinstance(raw.get("outstanding_condition"), str)
        or not isinstance(raw.get("executed_actions"), list)
        or not all(isinstance(v, str) for v in raw["executed_actions"])
    ):
        return None
    return VerifiedPlanningSnapshot(
        evidence_state=raw["evidence_state"],
        evidence_fact=raw["evidence_fact"],
        executed_actions=tuple(raw["executed_actions"]),
        outstanding_condition=raw["outstanding_condition"],
    )


class ProvenanceBoundCollectEligibility:
    """Test Domain rule: don't repeat collection after proven evidence exists.

    This is a strategy *eligibility* restriction, not a model-output rewrite,
    and never chooses or authorizes an executable plan by itself.
    """

    def __init__(self, case: TaskCase) -> None:
        self._collect_strategy = (
            "DOMAIN_STRATEGY_A"
            if case.collect_action == "DOMAIN_ACTION_A"
            else "DOMAIN_STRATEGY_B"
        )
        self.denials = 0

    def evaluate(
        self,
        strategy: StrategyDefinition,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        goals: GoalResolutionResult,
        candidates: tuple[PlanningActionCandidate, ...],
    ) -> bool | None:
        del understanding_state, goals, candidates
        if strategy.strategy_id != self._collect_strategy:
            return None
        interaction = runtime_context.interaction_context
        snapshot = _decode_verified_snapshot(
            interaction.last_agent_action if interaction is not None else None
        )
        if (
            snapshot is None
            or snapshot.evidence_fact not in _AVAILABLE_FACTS
            or snapshot.evidence_state != "AVAILABLE_UNVERIFIED"
            or not snapshot.executed_actions
        ):
            return None
        self.denials += 1
        return False


class DiagnosticTurn(MultiTaskSandboxTurn):
    def __init__(self, original: RuntimeInput, case: TaskCase, arm: str) -> None:
        if arm not in _ARMS:
            raise ValueError("unknown diagnostic arm")
        self.arm = arm
        self.eligibility = ProvenanceBoundCollectEligibility(case)
        super().__init__(original, case)

    def planning_eligibility_rules(
        self,
    ) -> tuple[ProvenanceBoundCollectEligibility, ...]:
        return (self.eligibility,) if self.arm == "C_TYPED_ELIGIBILITY" else ()

    def model_observation_projection(
        self, observations: tuple[ObservedFact, ...]
    ) -> InteractionContext | None:
        # Reuse the frozen sandbox provenance/known-facts checks first.
        original = super().model_observation_projection(observations)
        if original is None or self.arm == "A_TEXT":
            return original
        latest = observations[-1]
        last_fact = latest.facts[0]
        source_present = last_fact in _AVAILABLE_FACTS
        snapshot = VerifiedPlanningSnapshot(
            evidence_state=(
                "AVAILABLE_UNVERIFIED" if source_present else "UNAVAILABLE"
            ),
            evidence_fact=last_fact,
            # Only successfully observed actions count, not plans that merely
            # started or timed out. Neither future answers nor expected sequence.
            executed_actions=tuple(self.selected_actions[: len(observations)]),
            outstanding_condition=(
                "EVIDENCE_ACCURACY_NOT_YET_VALIDATED"
                if source_present
                else "NO_USABLE_SOURCE_EVIDENCE"
            ),
        )
        return InteractionContext(last_agent_action=snapshot.encode())


async def _run_diag_case(
    case: TaskCase, repeat: int, arm: str
) -> tuple[CaseResult, int]:
    original = build_runtime_input(text=case.goal)
    step = DiagnosticTurn(original, case, arm)
    try:
        outcome = await AgentRunCoordinator(
            step,
            LoopBudget(
                max_iterations=4,
                max_executions=3,
                max_no_progress=1,
                max_decision_seconds=55,
                max_execution_seconds=5,
            ),
        ).run(original, step.binding)
        status = f"{outcome.kind.value}:{outcome.reason}"
        finished = (
            outcome.kind is RunKind.FINISH
            and bool(outcome.observations)
            and outcome.observations[-1].facts == ("GOAL_SATISFIED",)
        )
        if outcome.kind is RunKind.FINISH and not finished:
            raise AssertionError("unsupported completion")
        safe_block = outcome.kind is RunKind.BLOCK
    except Exception as error:  # noqa: BLE001 - retain exact run failure
        status = f"ERROR_NOT_A_CONFIRMED_BLOCK:{type(error).__name__}"
        finished = False
        safe_block = False

    # A second model request must always receive the verified observation.
    if len(step.model_observations) >= 2 and step.model_observations[1] is None:
        status = "OBSERVATION_MISSING_IN_MODEL_REQUEST"
        finished = False
        safe_block = False

    selected = tuple(step.selected_actions)
    expected = case.expected_actions
    total = max(len(selected), len(expected))
    correct = sum(
        i < len(selected) and i < len(expected) and selected[i] == expected[i]
        for i in range(total)
    )
    result = CaseResult(
        case.case_id,
        repeat,
        status,
        selected,
        expected,
        finished,
        safe_block,
        correct,
        total,
        tuple(step.model_observations),
    )
    return result, step.eligibility.denials


@dataclass(frozen=True, slots=True)
class ArmMetrics:
    arm: str
    complete: int
    total_runs: int
    action_correct: int
    action_total: int
    blocks: int
    errors: int
    eligibility_denials: int

    @property
    def action_accuracy(self) -> float:
        return self.action_correct / self.action_total if self.action_total else 0.0


def test_diag01_snapshot_requires_verified_provenance() -> None:
    assert _decode_verified_snapshot("untrusted text") is None
    assert (
        _decode_verified_snapshot('{"evidence_state":"AVAILABLE_UNVERIFIED"}') is None
    )
    snapshot = VerifiedPlanningSnapshot(
        "AVAILABLE_UNVERIFIED",
        "SOURCE_AVAILABLE",
        ("DOMAIN_ACTION_A",),
        "EVIDENCE_ACCURACY_NOT_YET_VALIDATED",
    )
    assert _decode_verified_snapshot(snapshot.encode()) == snapshot


def test_diag01_collect_restriction_requires_completed_evidence() -> None:
    case = TASKS[0]
    eligibility = ProvenanceBoundCollectEligibility(case)
    context = build_runtime_context()
    strategies = {
        record.definition.strategy_id: record.definition
        for record in _strategy_registry().list()
    }
    collect = strategies["DOMAIN_STRATEGY_A"]
    understanding = _understanding()
    goals = _goals(understanding, context=context)
    # A word in the raw observation is never enough to suppress an action.
    assert eligibility.evaluate(collect, context, understanding, goals, ()) is None
    trusted = VerifiedPlanningSnapshot(
        "AVAILABLE_UNVERIFIED",
        "SOURCE_AVAILABLE",
        ("DOMAIN_ACTION_A",),
        "EVIDENCE_ACCURACY_NOT_YET_VALIDATED",
    )
    context = context.model_copy(
        update={
            "interaction_context": InteractionContext(
                last_agent_action=trusted.encode()
            )
        }
    )
    assert eligibility.evaluate(collect, context, understanding, goals, ()) is False
    assert (
        eligibility.evaluate(
            strategies["DOMAIN_STRATEGY_B"], context, understanding, goals, ()
        )
        is None
    )
    assert eligibility.denials == 1


def test_diag01_capability_prompts_do_not_embed_target_action_sequence() -> None:
    for case in TASKS:
        prompt = _semantic_instruction(case)
        assert case.goal not in prompt
        assert "SOURCE_AVAILABLE" not in prompt
        assert "DOMAIN_STRATEGY_A uses" in prompt or "DOMAIN_STRATEGY_A" in prompt
        assert "if last_agent_action" not in prompt


@pytest.mark.skipif(
    not (
        os.environ.get("GA01C_DIAG01_OPT_IN") == "1"
        and os.environ.get("GA01C_LLM_URL")
        and os.environ.get("GA01C_LLM_MODEL")
    ),
    reason="real Qwen three-arm diagnosis is explicitly opt-in",
)
def test_diag01_three_arm_real_replanning_comparison() -> None:
    async def evaluate() -> None:
        all_metrics: dict[str, ArmMetrics] = {}
        # Complete each arm rather than changing the other arms on failures.
        for arm in _ARMS:
            results: list[CaseResult] = []
            denials = 0
            for repeat in range(2):
                for case in TASKS:
                    result, suppressed = await _run_diag_case(case, repeat + 1, arm)
                    results.append(result)
                    denials += suppressed
                    print(
                        f"DIAG01 arm={arm} case={case.case_id} repeat={repeat + 1} "
                        f"status={result.status} actions={result.selected} "
                        f"expected={result.expected} verified_observations="
                        f"{len(result.model_observations) - 1} "
                        f"eligibility_denied={suppressed}",
                        flush=True,
                    )
            metrics = ArmMetrics(
                arm,
                sum(item.finished_with_evidence for item in results),
                len(results),
                sum(item.action_correct for item in results),
                sum(item.action_total for item in results),
                sum(item.safe_block for item in results),
                sum(
                    not item.finished_with_evidence and not item.safe_block
                    for item in results
                ),
                denials,
            )
            all_metrics[arm] = metrics
            print(
                f"DIAG01_SUMMARY arm={arm} completed={metrics.complete}/"
                f"{metrics.total_runs} action={metrics.action_correct}/"
                f"{metrics.action_total} accuracy={metrics.action_accuracy:.3f} "
                f"blocks={metrics.blocks} errors={metrics.errors} "
                f"eligibility_denied={metrics.eligibility_denials}",
                flush=True,
            )
        # The same original acceptance targets are retained. A/B failures are
        # diagnostic evidence; only C is proposed as the remedied acceptance.
        best = all_metrics["C_TYPED_ELIGIBILITY"]
        assert best.complete >= 10, "C remediation below original 10/12 threshold"
        assert best.action_accuracy >= 0.90, (
            "C remediation below original 90% action accuracy"
        )
        assert best.errors == 0, "C remediation produced unclassified errors"

    asyncio.run(evaluate())
