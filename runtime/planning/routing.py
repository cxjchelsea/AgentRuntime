"""M4-IU2 PlanningMode routing.

Routing is generic and policy-first. Core never hardcodes Domain intent/action values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from runtime.contracts import PolicyDecision, RuntimeContext, UnderstandingState
from runtime.contracts.enums import PlanningMode, ProcessingPath
from runtime.planning.errors import (
    InvalidPlanningRouteRuleError,
    PlanningBlockedByPolicyError,
    PlanningRouteConflictError,
)


@dataclass(frozen=True, slots=True)
class PlanningRouteSignal:
    """One injected generic routing signal."""

    mode: PlanningMode
    reason_code: str

    def __post_init__(self) -> None:
        if not self.reason_code.strip():
            raise InvalidPlanningRouteRuleError("reason_code must not be blank")


class PlanningModeRule(Protocol):
    """Injected routing rule. Domain-specific semantics stay outside Core."""

    def evaluate(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        policy_decision: PolicyDecision,
    ) -> PlanningRouteSignal | None:
        """Return a planning-mode signal or None."""


@dataclass(frozen=True, slots=True)
class PlanningRouteDecision:
    """Internal M4 routing result; not a Canonical Contract."""

    mode: PlanningMode
    reason_codes: tuple[str, ...]
    forced_action: str | None = None
    forced_workflow: str | None = None


class PlanningModeRouter:
    """Route one turn into FORCED / DETERMINISTIC / AGENT / DEGRADED."""

    def __init__(self, rules: tuple[PlanningModeRule, ...] = ()) -> None:
        self._rules = rules

    def route(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        policy_decision: PolicyDecision,
    ) -> PlanningRouteDecision:
        if policy_decision.blocked or not policy_decision.allowed:
            raise PlanningBlockedByPolicyError(
                "M4 cannot plan when M2 PolicyDecision blocks ordinary planning"
            )

        forced_reasons: list[str] = []
        if policy_decision.forced_workflow is not None:
            forced_reasons.append("POLICY_FORCED_WORKFLOW")
        if policy_decision.forced_action is not None:
            forced_reasons.append("POLICY_FORCED_ACTION")
        if forced_reasons:
            return PlanningRouteDecision(
                mode=PlanningMode.FORCED,
                reason_codes=tuple(forced_reasons),
                forced_action=policy_decision.forced_action,
                forced_workflow=policy_decision.forced_workflow,
            )

        if understanding_state.metadata.processing_path is ProcessingPath.DEGRADED_PATH:
            return PlanningRouteDecision(
                mode=PlanningMode.DEGRADED,
                reason_codes=("UNDERSTANDING_DEGRADED",),
            )

        signals: list[PlanningRouteSignal] = []
        for rule in self._rules:
            signal = rule.evaluate(
                runtime_context,
                understanding_state,
                policy_decision,
            )
            if signal is None:
                continue
            if signal.mode is PlanningMode.FORCED:
                raise PlanningRouteConflictError(
                    "injected rule cannot create FORCED planning without M2 force"
                )
            signals.append(signal)

        selected_modes = {signal.mode for signal in signals}
        if len(selected_modes) > 1:
            raise PlanningRouteConflictError(
                "planning route rules produced conflicting planning modes"
            )
        if signals:
            mode = signals[0].mode
            return PlanningRouteDecision(
                mode=mode,
                reason_codes=tuple(signal.reason_code for signal in signals),
            )

        return PlanningRouteDecision(
            mode=PlanningMode.AGENT_PLANNED,
            reason_codes=("DEFAULT_AGENT_PLANNED",),
        )
