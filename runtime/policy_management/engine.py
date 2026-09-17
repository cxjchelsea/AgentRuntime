"""M2-IU4 deterministic Policy Engine implementation."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from runtime.contracts import (
    PolicyDecision,
    RuntimeContext,
    SafetyPhase,
    SafetyResult,
    UnderstandingState,
    ValidationMode,
)
from runtime.interfaces.policy import PolicyEngine
from runtime.policy_management.definitions import PolicyFragment
from runtime.policy_management.errors import (
    DuplicatePolicyRuleError,
    InvalidPolicyFragmentError,
    PolicyConflictError,
    PolicyInvariantError,
    PolicyRuleExecutionError,
)
from runtime.policy_management.rules import PolicyRule

_VALIDATION_ORDER = {
    ValidationMode.FAST: 0,
    ValidationMode.STANDARD: 1,
    ValidationMode.STRICT: 2,
}


class DefaultPolicyEngine(PolicyEngine):
    """Aggregate Safety constraints and injected PolicyRules into PolicyDecision.

    This class does not plan, execute, mutate RuntimeState, or run preemption effects.
    Priority / Preemption outputs are intentionally not smuggled through hidden state;
    their formal aggregation waits for the later M2 integration boundary because the
    frozen PolicyEngine interface does not accept them.
    """

    def __init__(
        self,
        rules: Iterable[PolicyRule] = (),
        *,
        default_priority: int = 0,
        default_validation_mode: ValidationMode = ValidationMode.STANDARD,
        clock: Callable[[], datetime] | None = None,
        decision_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._rules = tuple(rules)
        self._default_priority = default_priority
        self._default_validation_mode = default_validation_mode
        self._clock = clock or (lambda: datetime.now(UTC))
        self._decision_id_factory = decision_id_factory or (lambda: str(uuid4()))
        seen: set[str] = set()
        for rule in self._rules:
            rule_id = rule.rule_id.strip()
            if not rule_id:
                raise InvalidPolicyFragmentError("PolicyRule.rule_id must not be blank")
            if rule_id in seen:
                raise DuplicatePolicyRuleError(f"duplicate policy rule: {rule_id}")
            seen.add(rule_id)

    async def evaluate(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        safety_result: SafetyResult,
    ) -> PolicyDecision:
        """Produce the turn-level canonical PolicyDecision."""
        self._validate_inputs(understanding_state, safety_result)
        fragments = [self._safety_fragment(safety_result)]
        for rule in self._rules:
            fragment = await self._run_rule(
                rule,
                runtime_context,
                understanding_state,
                safety_result,
            )
            if fragment is not None:
                if fragment.source_id != rule.rule_id:
                    raise InvalidPolicyFragmentError(
                        "PolicyFragment.source_id must match PolicyRule.rule_id"
                    )
                fragments.append(fragment)
        return self._aggregate(fragments)

    async def _run_rule(
        self,
        rule: PolicyRule,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        safety_result: SafetyResult,
    ) -> PolicyFragment | None:
        try:
            return await rule.evaluate(
                runtime_context,
                understanding_state,
                safety_result,
            )
        except Exception as error:
            if isinstance(
                error,
                (InvalidPolicyFragmentError, PolicyConflictError, PolicyInvariantError),
            ):
                raise
            raise PolicyRuleExecutionError(rule.rule_id, error) from error

    def _aggregate(self, fragments: list[PolicyFragment]) -> PolicyDecision:
        explicit_allowed = [f.allowed for f in fragments if f.allowed is not None]
        explicit_blocked = [f.blocked for f in fragments if f.blocked is not None]
        allowed = all(explicit_allowed) if explicit_allowed else True
        blocked = any(explicit_blocked) if explicit_blocked else False
        if not allowed:
            blocked = True
        if blocked:
            allowed = False

        priorities = [
            fragment.priority
            for fragment in fragments
            if fragment.priority is not None
        ]
        priority = max(priorities, default=self._default_priority)
        interrupt_current_task = any(
            fragment.interrupt_current_task is True for fragment in fragments
        )
        validation_mode = self._strictest_validation_mode(fragments)

        forced_workflow = self._single_hard_value(
            fragments,
            "forced_workflow",
            "forced_workflow",
        )
        forced_action = self._single_hard_value(
            fragments,
            "forced_action",
            "forced_action",
        )
        response_constraints = self._merge_response_constraints(fragments)

        forbidden_actions = self._union_values(fragments, "forbidden_actions")
        forbidden_skills = self._union_values(fragments, "forbidden_skills")
        forbidden_tools = self._union_values(fragments, "forbidden_tools")
        allowed_actions = self._intersection_values(fragments, "allowed_actions")
        allowed_skills = self._intersection_values(fragments, "allowed_skills")
        allowed_tools = self._intersection_values(fragments, "allowed_tools")
        allowed_actions = self._subtract(allowed_actions, forbidden_actions)
        allowed_skills = self._subtract(allowed_skills, forbidden_skills)
        allowed_tools = self._subtract(allowed_tools, forbidden_tools)

        return PolicyDecision(
            policy_decision_id=self._decision_id_factory(),
            allowed=allowed,
            blocked=blocked,
            priority=priority,
            interrupt_current_task=interrupt_current_task,
            validation_mode=validation_mode,
            reason_codes=list(self._stable_union(fragments, "reason_codes")),
            created_at=self._clock(),
            forced_workflow=forced_workflow,
            forced_action=forced_action,
            allowed_actions=self._as_list_or_none(allowed_actions),
            forbidden_actions=self._as_list_or_none(forbidden_actions),
            allowed_skills=self._as_list_or_none(allowed_skills),
            forbidden_skills=self._as_list_or_none(forbidden_skills),
            allowed_tools=self._as_list_or_none(allowed_tools),
            forbidden_tools=self._as_list_or_none(forbidden_tools),
            confirmation_required=any(
                fragment.confirmation_required is True for fragment in fragments
            ),
            response_constraints=response_constraints or None,
            policy_flags=list(self._stable_union(fragments, "policy_flags")) or None,
        )

    def _strictest_validation_mode(
        self,
        fragments: list[PolicyFragment],
    ) -> ValidationMode:
        modes = [self._default_validation_mode]
        modes.extend(
            fragment.validation_mode
            for fragment in fragments
            if fragment.validation_mode is not None
        )
        return max(modes, key=lambda mode: _VALIDATION_ORDER[mode])

    @staticmethod
    def _single_hard_value(
        fragments: list[PolicyFragment],
        field_name: str,
        label: str,
    ) -> str | None:
        values: set[str] = set()
        for fragment in fragments:
            value = getattr(fragment, field_name)
            if value is not None:
                values.add(value)
        if len(values) > 1:
            raise PolicyConflictError(f"conflicting {label} values")
        return next(iter(values), None)

    @staticmethod
    def _stable_union(
        fragments: list[PolicyFragment],
        field_name: str,
    ) -> tuple[str, ...]:
        output: list[str] = []
        seen: set[str] = set()
        for fragment in fragments:
            values = getattr(fragment, field_name) or ()
            for value in values:
                if value not in seen:
                    seen.add(value)
                    output.append(value)
        return tuple(output)

    @classmethod
    def _union_values(
        cls,
        fragments: list[PolicyFragment],
        field_name: str,
    ) -> tuple[str, ...] | None:
        values = cls._stable_union(fragments, field_name)
        return values or None

    @staticmethod
    def _intersection_values(
        fragments: list[PolicyFragment],
        field_name: str,
    ) -> tuple[str, ...] | None:
        constrained = [
            tuple(getattr(fragment, field_name))
            for fragment in fragments
            if getattr(fragment, field_name) is not None
        ]
        if not constrained:
            return None
        first = constrained[0]
        allowed = set(first)
        for values in constrained[1:]:
            allowed.intersection_update(values)
        return tuple(value for value in first if value in allowed)

    @staticmethod
    def _subtract(
        allowed: tuple[str, ...] | None,
        forbidden: tuple[str, ...] | None,
    ) -> tuple[str, ...] | None:
        if allowed is None or forbidden is None:
            return allowed
        forbidden_set = set(forbidden)
        return tuple(value for value in allowed if value not in forbidden_set)

    @staticmethod
    def _as_list_or_none(values: tuple[str, ...] | None) -> list[str] | None:
        return None if values is None else list(values)

    @staticmethod
    def _merge_response_constraints(
        fragments: list[PolicyFragment],
    ) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for fragment in fragments:
            for key, value in (fragment.response_constraints or {}).items():
                if key in merged and merged[key] != value:
                    raise PolicyConflictError(
                        f"conflicting response constraint for key: {key}"
                    )
                merged[key] = value
        return merged

    @staticmethod
    def _safety_fragment(safety_result: SafetyResult) -> PolicyFragment:
        flags: list[str] = []
        if safety_result.safety_lock_required:
            flags.append("SAFETY_LOCK_REQUIRED")
        if safety_result.requires_immediate_action:
            flags.append("IMMEDIATE_ACTION_REQUIRED")
        return PolicyFragment(
            source_id="CORE_SAFETY_RESULT",
            allowed=safety_result.allowed_to_continue_normal_flow,
            blocked=not safety_result.allowed_to_continue_normal_flow,
            interrupt_current_task=safety_result.interrupt_current_task,
            reason_codes=tuple(safety_result.reason_codes),
            forced_workflow=safety_result.force_workflow,
            forbidden_actions=tuple(safety_result.restricted_actions or ()) or None,
            policy_flags=tuple(flags),
        )

    @staticmethod
    def _validate_inputs(
        understanding_state: UnderstandingState,
        safety_result: SafetyResult,
    ) -> None:
        if safety_result.phase is not SafetyPhase.DEEP:
            raise PolicyInvariantError("PolicyEngine requires DEEP SafetyResult")
        if understanding_state.metadata.request_id != safety_result.request_id:
            raise PolicyInvariantError(
                "UnderstandingState and SafetyResult request_id must match"
            )
