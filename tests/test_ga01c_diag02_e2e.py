"""DIAG-02: trusted synthetic initial source evidence and M4 strategy eligibility.

This deliberately does NOT use case.expected_actions as an authority signal.
Independent synthetic state provider supplies an initial record only for
populated test tasks. All M4 planning and approvals remain unchanged.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from agent_core.iteration import AgentRunBinding
from agent_core.runner import AgentRunCoordinator, LoopBudget
from runtime.contracts import RuntimeContext, UnderstandingState
from runtime.planning.candidates import PlanningActionCandidate
from runtime.planning.goals import GoalResolutionResult
from runtime.registries import StrategyDefinition
from tests.ga01.initial_evidence import (
    AcceptedInitialEvidence,
    InitialEvidenceRecord,
    SyntheticInitialEvidenceProvider,
    admit_initial_evidence,
)
from tests.orchestration_stubs import build_runtime_input
from tests.test_ga01c_diag01 import (
    DiagnosticTurn,
    _run_diag_case,
)
from tests.test_ga01c_eval02 import TASKS, TaskCase

_NOW = datetime(2026, 10, 10, 1, tzinfo=timezone.utc)


class InitiallyAvailableEligibility:
    """Read-only M4 Domain condition based on an already admitted record."""

    def __init__(self, case: TaskCase) -> None:
        self.collect_strategy = (
            "DOMAIN_STRATEGY_A"
            if case.collect_action == "DOMAIN_ACTION_A"
            else "DOMAIN_STRATEGY_B"
        )
        self.accepted: AcceptedInitialEvidence | None = None
        self.denials = 0

    def evaluate(
        self,
        strategy: StrategyDefinition,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        goals: GoalResolutionResult,
        candidates: tuple[PlanningActionCandidate, ...],
    ) -> bool | None:
        del runtime_context, understanding_state, goals, candidates
        if (
            strategy.strategy_id == self.collect_strategy
            and self.accepted is not None
            and self.accepted.status == "AVAILABLE_UNVERIFIED"
        ):
            self.denials += 1
            return False
        return None


class InitialEvidenceTurn(DiagnosticTurn):
    def __init__(
        self,
        original,
        case: TaskCase,
        admitted: AcceptedInitialEvidence | None,
    ) -> None:
        self.initial_rule = InitiallyAvailableEligibility(case)
        self.initial_rule.accepted = admitted
        super().__init__(original, case, "C_TYPED_ELIGIBILITY")

    def planning_eligibility_rules(self):
        return (self.eligibility, self.initial_rule)


def _seed_store(
    binding: AgentRunBinding, case: TaskCase
) -> tuple[SyntheticInitialEvidenceProvider, str]:
    record_id = f"state-record-{binding.domain_id}-{binding.run_id}"
    if not case.source_available:
        # No evidence record: absence is not a positive claim of missing data.
        return SyntheticInitialEvidenceProvider({}), record_id
    record = InitialEvidenceRecord(
        evidence_id=record_id,
        run_id=binding.run_id,
        subject_id=binding.subject_id,
        session_id=binding.session_id,
        identity_scope=binding.identity_scope,
        tenant_id=binding.tenant_id,
        domain_id=binding.domain_id,
        domain_version=binding.domain_version,
        domain_fingerprint=binding.binding_fingerprint,
        record_revision=1,
        observed_at=_NOW - timedelta(minutes=30),
        expires_at=_NOW + timedelta(hours=1),
        status="AVAILABLE_UNVERIFIED",
        source_kind="ISOLATED_SYNTHETIC_STATE_STORE",
    )
    return SyntheticInitialEvidenceProvider({record_id: record}), record_id


@dataclass(frozen=True)
class OutcomeRecord:
    case_id: str
    repetition: int
    finished: bool
    actions: tuple[str, ...]
    expected: tuple[str, ...]
    initial_denials: int
    post_execution_denials: int
    status: str


async def _run_evidence_case(case: TaskCase, repetition: int) -> OutcomeRecord:
    original = build_runtime_input(text=case.goal)
    # Construct binding without granting planning rights; actual turn independently
    # constructs its binding with the same requested run and domain identity.
    binding = AgentRunBinding.from_input(
        original,
        run_id=f"eval02-{case.case_id}",
        domain_id=f"eval02-{case.family}",
        domain_version="v1",
        binding_fingerprint=f"eval02-{case.family}-v1",
    )
    store, record_id = _seed_store(binding, case)
    admitted = admit_initial_evidence(binding, store, record_id, now=_NOW)
    turn = InitialEvidenceTurn(original, case, admitted)
    try:
        result = await AgentRunCoordinator(
            turn,
            LoopBudget(
                max_iterations=4,
                max_executions=3,
                max_no_progress=1,
                max_decision_seconds=55,
                max_execution_seconds=5,
            ),
        ).run(original, turn.binding)
        finished = (
            result.kind.value == "FINISH"
            and bool(result.observations)
            and result.observations[-1].facts == ("GOAL_SATISFIED",)
        )
        status = result.kind.value
    except Exception as exc:  # noqa: BLE001 - record all actual model failures
        finished = False
        status = f"ERROR:{type(exc).__name__}"
    return OutcomeRecord(
        case.case_id,
        repetition,
        finished,
        tuple(turn.selected_actions),
        case.expected_actions,
        turn.initial_rule.denials,
        turn.eligibility.denials,
        status,
    )


def test_initial_rule_with_no_evidence_does_not_deny() -> None:
    rule = InitiallyAvailableEligibility(TASKS[0])
    assert rule.accepted is None
    assert rule.denials == 0


@pytest.mark.skipif(
    not (
        os.environ.get("GA01C_DIAG02_OPT_IN") == "1"
        and os.environ.get("GA01C_LLM_URL")
        and os.environ.get("GA01C_LLM_MODEL")
    ),
    reason="real model initial evidence DIAG-02 requires opt in",
)
def test_diag02_real_model_initial_evidence_reliability() -> None:
    async def evaluate() -> None:
        outcomes: list[OutcomeRecord] = []
        for repeat in (1, 2):
            for case in TASKS:
                outcome = await _run_evidence_case(case, repeat)
                outcomes.append(outcome)
                print(
                    f"DIAG02 case={outcome.case_id} repeat={outcome.repetition} "
                    f"status={outcome.status} actions={outcome.actions} "
                    f"expected={outcome.expected} "
                    f"initial_denied={outcome.initial_denials} "
                    f"post_denied={outcome.post_execution_denials}",
                    flush=True,
                )
        completed = sum(x.finished for x in outcomes)
        numer = sum(
            sum(
                i < len(x.actions)
                and i < len(x.expected)
                and x.actions[i] == x.expected[i]
                for i in range(max(len(x.actions), len(x.expected)))
            )
            for x in outcomes
        )
        denom = sum(max(len(x.actions), len(x.expected)) for x in outcomes)
        accuracy = numer / denom if denom else 0.0
        print(
            f"DIAG02_SUMMARY complete={completed}/12 correct={numer}/{denom} "
            f"accuracy={accuracy:.3f}",
            flush=True,
        )
        assert completed >= 10, "original minimum completion threshold not met"
        assert accuracy >= 0.90, "original action accuracy threshold not met"

    asyncio.run(evaluate())
