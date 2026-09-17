"""M3-IU3 Fast/Deep routing.

The router decides only which understanding path should run next. It does not call a
model, produce a final UnderstandingState, choose an action, or override M2 policy.
"""

from __future__ import annotations

from dataclasses import dataclass

from runtime.contracts.enums import ProcessingPath
from runtime.understanding.deterministic import RuleParseResult
from runtime.understanding.errors import InvalidUnderstandingRoutingPolicyError


@dataclass(frozen=True, slots=True)
class UnderstandingRoutingPolicy:
    """Generic thresholds for deciding whether deterministic parsing is sufficient."""

    fast_min_confidence: float = 0.9
    max_fast_intents: int = 1
    deep_on_risk_signal: bool = True
    deep_on_pending_question_resolution: bool = False

    def __post_init__(self) -> None:
        if not 0.0 <= self.fast_min_confidence <= 1.0:
            raise InvalidUnderstandingRoutingPolicyError(
                "fast_min_confidence must be within [0, 1]"
            )
        if self.max_fast_intents < 0:
            raise InvalidUnderstandingRoutingPolicyError(
                "max_fast_intents must be greater than or equal to zero"
            )


@dataclass(frozen=True, slots=True)
class UnderstandingRouteDecision:
    """Internal routing result. It is not a Canonical Contract."""

    processing_path: ProcessingPath
    reason_codes: tuple[str, ...]
    deterministic_result: RuleParseResult

    @property
    def requires_model(self) -> bool:
        return self.processing_path in {
            ProcessingPath.DEEP_PATH,
            ProcessingPath.HYBRID_PATH,
        }


class UnderstandingPathRouter:
    """Route deterministic findings to FAST, HYBRID, or DEEP understanding."""

    def __init__(self, policy: UnderstandingRoutingPolicy | None = None) -> None:
        self._policy = policy or UnderstandingRoutingPolicy()

    def route(self, rule_result: RuleParseResult) -> UnderstandingRouteDecision:
        """Choose the next M3 path without interpreting new semantic content."""
        if not rule_result.matched:
            return UnderstandingRouteDecision(
                processing_path=ProcessingPath.DEEP_PATH,
                reason_codes=("NO_DETERMINISTIC_MATCH",),
                deterministic_result=rule_result,
            )

        hybrid_reasons: list[str] = []
        if rule_result.confidence is None:
            hybrid_reasons.append("DETERMINISTIC_CONFIDENCE_MISSING")
        elif rule_result.confidence < self._policy.fast_min_confidence:
            hybrid_reasons.append("DETERMINISTIC_CONFIDENCE_BELOW_FAST_THRESHOLD")

        if len(rule_result.intents) > self._policy.max_fast_intents:
            hybrid_reasons.append("MULTIPLE_DETERMINISTIC_INTENTS")

        if self._policy.deep_on_risk_signal and rule_result.risk_signal_ids:
            hybrid_reasons.append("RISK_SIGNAL_REQUIRES_DEEP_REVIEW")

        if (
            self._policy.deep_on_pending_question_resolution
            and rule_result.pending_question_resolution is not None
        ):
            hybrid_reasons.append("PENDING_QUESTION_REQUIRES_DEEP_REVIEW")

        if hybrid_reasons:
            return UnderstandingRouteDecision(
                processing_path=ProcessingPath.HYBRID_PATH,
                reason_codes=tuple(hybrid_reasons),
                deterministic_result=rule_result,
            )

        return UnderstandingRouteDecision(
            processing_path=ProcessingPath.FAST_PATH,
            reason_codes=("DETERMINISTIC_RESULT_SUFFICIENT",),
            deterministic_result=rule_result,
        )
