"""M4 closure evaluation harness.

This module provides mechanism-level evaluation infrastructure only. Domain packages own
real Golden Planning Sets, business labels, clinical rules, and production thresholds.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


class M4EvalGate(str, Enum):
    """Frozen M4 evaluation gate categories."""

    POLICY = "POLICY"
    BEHAVIOR = "BEHAVIOR"
    MEMORY_TOOL = "MEMORY_TOOL"
    ACTIVE_SAFETY = "ACTIVE_SAFETY"


@dataclass(frozen=True, slots=True)
class PlanningEvalCase:
    """One Domain-supplied planning evaluation case."""

    case_id: str
    gate: M4EvalGate
    tags: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id must not be blank")
        if any(not tag.strip() for tag in self.tags):
            raise ValueError("tags must not contain blank values")


@dataclass(frozen=True, slots=True)
class PlanningEvalResult:
    """Evaluator result for one case."""

    case_id: str
    gate: M4EvalGate
    passed: bool
    reason_codes: tuple[str, ...] = ()
    metrics: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id must not be blank")
        if any(not code.strip() for code in self.reason_codes):
            raise ValueError("reason_codes must not contain blank values")
        for name, value in self.metrics.items():
            if not name.strip():
                raise ValueError("metric name must not be blank")
            # 指标值只接受数值类型，布尔值单独排除以免被当成 0/1
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeError("metric values must be numeric")


class PlanningCaseEvaluator(Protocol):
    """Domain/config supplied evaluator for one planning case."""

    def evaluate(self, case: PlanningEvalCase) -> PlanningEvalResult:
        """Evaluate one case without changing Runtime or Planner state."""


@dataclass(frozen=True, slots=True)
class M4GateThresholds:
    """Pass-rate thresholds for the four frozen gate categories."""

    policy: float = 1.0
    behavior: float = 1.0
    memory_tool: float = 1.0
    active_safety: float = 1.0

    def __post_init__(self) -> None:
        for value in (
            self.policy,
            self.behavior,
            self.memory_tool,
            self.active_safety,
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError("gate thresholds must be within [0, 1]")

    def for_gate(self, gate: M4EvalGate) -> float:
        if gate is M4EvalGate.POLICY:
            return self.policy
        if gate is M4EvalGate.BEHAVIOR:
            return self.behavior
        if gate is M4EvalGate.MEMORY_TOOL:
            return self.memory_tool
        return self.active_safety


@dataclass(frozen=True, slots=True)
class M4GateSummary:
    gate: M4EvalGate
    total: int
    passed: int
    pass_rate: float
    threshold: float
    gate_passed: bool


@dataclass(frozen=True, slots=True)
class M4EvalReport:
    """Mechanism-level evaluation report."""

    results: tuple[PlanningEvalResult, ...]
    gates: tuple[M4GateSummary, ...]

    @property
    def passed(self) -> bool:
        return all(summary.gate_passed for summary in self.gates)


class M4EvalRunner:
    """Run Domain-supplied cases and aggregate the four frozen gates."""

    def __init__(
        self,
        *,
        evaluator: PlanningCaseEvaluator,
        thresholds: M4GateThresholds | None = None,
    ) -> None:
        self._evaluator = evaluator
        self._thresholds = thresholds or M4GateThresholds()

    def run(self, cases: Sequence[PlanningEvalCase]) -> M4EvalReport:
        case_ids = [case.case_id for case in cases]
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("planning eval case_id values must be unique")

        results: list[PlanningEvalResult] = []
        for case in cases:
            result = self._evaluator.evaluate(case)
            if result.case_id != case.case_id:
                raise ValueError("evaluator changed case_id")
            if result.gate is not case.gate:
                raise ValueError("evaluator changed gate category")
            results.append(result)

        summaries: list[M4GateSummary] = []
        for gate in M4EvalGate:
            gate_results = [result for result in results if result.gate is gate]
            total = len(gate_results)
            passed = sum(1 for result in gate_results if result.passed)
            pass_rate = passed / total if total else 0.0
            threshold = self._thresholds.for_gate(gate)
            summaries.append(
                M4GateSummary(
                    gate=gate,
                    total=total,
                    passed=passed,
                    pass_rate=pass_rate,
                    threshold=threshold,
                    gate_passed=total > 0 and pass_rate >= threshold,
                )
            )

        return M4EvalReport(
            results=tuple(results),
            gates=tuple(summaries),
        )
