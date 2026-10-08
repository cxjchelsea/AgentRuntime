"""M4 closure fix gates for Eval Harness and deferred Replan contract."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, fields

import pytest

import runtime.planning.evaluation as evaluation_module
from runtime.planning import (
    M4EvalGate,
    M4EvalRunner,
    M4GateThresholds,
    PlanningEvalCase,
    PlanningEvalResult,
    ReplanEntryRequest,
)


@dataclass(frozen=True)
class StaticEvaluator:
    outcomes: dict[str, bool]

    def evaluate(self, case: PlanningEvalCase) -> PlanningEvalResult:
        return PlanningEvalResult(
            case_id=case.case_id,
            gate=case.gate,
            passed=self.outcomes[case.case_id],
            reason_codes=("PASS",) if self.outcomes[case.case_id] else ("FAIL",),
            metrics={"score": 1.0 if self.outcomes[case.case_id] else 0.0},
        )


def _cases() -> tuple[PlanningEvalCase, ...]:
    return (
        PlanningEvalCase(case_id="policy-1", gate=M4EvalGate.POLICY),
        PlanningEvalCase(case_id="behavior-1", gate=M4EvalGate.BEHAVIOR),
        PlanningEvalCase(case_id="memory-tool-1", gate=M4EvalGate.MEMORY_TOOL),
        PlanningEvalCase(case_id="active-safety-1", gate=M4EvalGate.ACTIVE_SAFETY),
    )


def test_eval_runner_requires_all_four_frozen_gate_categories() -> None:
    evaluator = StaticEvaluator(
        outcomes={
            "policy-1": True,
            "behavior-1": True,
            "memory-tool-1": True,
            "active-safety-1": True,
        }
    )

    report = M4EvalRunner(evaluator=evaluator).run(_cases())

    assert report.passed is True
    assert {summary.gate for summary in report.gates} == set(M4EvalGate)
    assert all(summary.total == 1 for summary in report.gates)


def test_eval_gate_fails_when_category_has_no_cases() -> None:
    evaluator = StaticEvaluator(outcomes={"policy-1": True})

    report = M4EvalRunner(evaluator=evaluator).run(
        (PlanningEvalCase(case_id="policy-1", gate=M4EvalGate.POLICY),)
    )

    assert report.passed is False
    missing = {summary.gate for summary in report.gates if summary.total == 0}
    assert missing == {
        M4EvalGate.BEHAVIOR,
        M4EvalGate.MEMORY_TOOL,
        M4EvalGate.ACTIVE_SAFETY,
    }


def test_eval_thresholds_are_mechanism_config_not_business_labels() -> None:
    evaluator = StaticEvaluator(
        outcomes={
            "policy-1": True,
            "policy-2": False,
            "behavior-1": True,
            "memory-tool-1": True,
            "active-safety-1": True,
        }
    )
    cases = (
        PlanningEvalCase(case_id="policy-1", gate=M4EvalGate.POLICY),
        PlanningEvalCase(case_id="policy-2", gate=M4EvalGate.POLICY),
        PlanningEvalCase(case_id="behavior-1", gate=M4EvalGate.BEHAVIOR),
        PlanningEvalCase(case_id="memory-tool-1", gate=M4EvalGate.MEMORY_TOOL),
        PlanningEvalCase(case_id="active-safety-1", gate=M4EvalGate.ACTIVE_SAFETY),
    )

    report = M4EvalRunner(
        evaluator=evaluator,
        thresholds=M4GateThresholds(policy=0.5),
    ).run(cases)

    assert report.passed is True
    policy = next(
        summary for summary in report.gates if summary.gate is M4EvalGate.POLICY
    )
    assert policy.pass_rate == 0.5
    assert policy.threshold == 0.5


def test_eval_runner_rejects_duplicate_case_ids() -> None:
    evaluator = StaticEvaluator(outcomes={"dup": True})

    with pytest.raises(ValueError, match="unique"):
        M4EvalRunner(evaluator=evaluator).run(
            (
                PlanningEvalCase(case_id="dup", gate=M4EvalGate.POLICY),
                PlanningEvalCase(case_id="dup", gate=M4EvalGate.BEHAVIOR),
            )
        )


def test_replan_entry_is_cross_stage_contract_only() -> None:
    request = ReplanEntryRequest(
        request_id="request-001",
        prior_plan_id="plan-001",
        trigger_stage="RESULT_VALIDATE",
        reason_codes=("RESULT_INCOMPLETE",),
        evidence_refs=("validated-result-ref",),
    )

    assert request.trigger_stage == "RESULT_VALIDATE"
    assert request.preserve_goal is True


def test_replan_entry_rejects_non_validation_trigger() -> None:
    with pytest.raises(ValueError, match="RESULT_VALIDATE"):
        ReplanEntryRequest(
            request_id="request-001",
            prior_plan_id="plan-001",
            trigger_stage="EXECUTE",
            reason_codes=("TOOL_FAILED",),
        )


def test_eval_harness_hardcodes_no_business_taxonomy() -> None:
    source = inspect.getsource(evaluation_module)

    for token in ("HEALTH", "WEATHER", "NEWS", "CONTENT", "MEDICAL"):
        assert token not in source


def test_replan_entry_contract_stores_only_cross_stage_references() -> None:
    assert [field.name for field in fields(ReplanEntryRequest)] == [
        "request_id",
        "prior_plan_id",
        "trigger_stage",
        "reason_codes",
        "evidence_refs",
        "preserve_goal",
    ]
