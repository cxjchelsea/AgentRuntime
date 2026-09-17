"""M2-IU3 deterministic Priority / Preemption Engines."""

from __future__ import annotations

from collections.abc import Iterable

from runtime.priority_management.definitions import (
    CleanupPolicy,
    IncomingDisposition,
    PreemptionDecision,
    PreemptionRule,
    PriorityDecision,
    PriorityRelation,
    PrioritySubject,
    ResumePolicy,
)
from runtime.priority_management.errors import (
    AmbiguousPreemptionRuleError,
    DuplicatePreemptionRuleError,
    MissingPreemptionRuleError,
    PriorityDecisionMismatchError,
)


class PriorityEngine:
    """Compare resolved numeric priorities without inventing Domain priority values."""

    @staticmethod
    def evaluate(
        *,
        current: PrioritySubject | None,
        incoming: PrioritySubject,
    ) -> PriorityDecision:
        if current is None:
            return PriorityDecision(
                current_subject_id=None,
                incoming_subject_id=incoming.subject_id,
                current_priority=None,
                incoming_priority=incoming.priority,
                relation=PriorityRelation.HIGHER,
                higher_than_current=True,
                reason_codes=("NO_CURRENT_ACTIVITY",),
            )
        if incoming.priority > current.priority:
            relation = PriorityRelation.HIGHER
            reason = "INCOMING_PRIORITY_HIGHER"
        elif incoming.priority == current.priority:
            relation = PriorityRelation.EQUAL
            reason = "INCOMING_PRIORITY_EQUAL"
        else:
            relation = PriorityRelation.LOWER
            reason = "INCOMING_PRIORITY_LOWER"
        return PriorityDecision(
            current_subject_id=current.subject_id,
            incoming_subject_id=incoming.subject_id,
            current_priority=current.priority,
            incoming_priority=incoming.priority,
            relation=relation,
            higher_than_current=relation is PriorityRelation.HIGHER,
            reason_codes=(reason,),
        )


class PreemptionEngine:
    """Evaluate interruption using explicit injected rules.

    This engine is pure: it does not cancel tasks, mutate RuntimeState, enqueue events,
    or perform Safety / Policy decisions.
    """

    def __init__(self, rules: Iterable[PreemptionRule]) -> None:
        self._rules = tuple(rules)
        seen: set[tuple[str, str, PriorityRelation]] = set()
        for rule in self._rules:
            key = (rule.current_kind, rule.incoming_kind, rule.relation)
            if key in seen:
                raise DuplicatePreemptionRuleError(
                    "duplicate preemption rule for current/incoming/relation"
                )
            seen.add(key)

    def evaluate(
        self,
        *,
        current: PrioritySubject | None,
        incoming: PrioritySubject,
        current_interruptible: bool,
        priority_decision: PriorityDecision,
    ) -> PreemptionDecision:
        self._validate_priority_decision(current, incoming, priority_decision)

        if current is None:
            return PreemptionDecision(
                current_subject_id=None,
                incoming_subject_id=incoming.subject_id,
                interrupt=False,
                can_interrupt=False,
                disposition=IncomingDisposition.PROCESS_NOW,
                on_interrupt=None,
                cleanup_policy=CleanupPolicy.NONE,
                resume_policy=ResumePolicy.NO_RESUME,
                priority_decision=priority_decision,
                reason_codes=("NO_CURRENT_ACTIVITY",),
            )

        rule = self._select_rule(
            current_kind=current.kind,
            incoming_kind=incoming.kind,
            relation=priority_decision.relation,
        )
        can_interrupt = current_interruptible and rule.interrupt

        if rule.interrupt and not current_interruptible:
            if rule.when_not_interruptible is None:
                raise AssertionError("validated rule missing when_not_interruptible")
            return PreemptionDecision(
                current_subject_id=current.subject_id,
                incoming_subject_id=incoming.subject_id,
                interrupt=False,
                can_interrupt=False,
                disposition=rule.when_not_interruptible,
                on_interrupt=None,
                cleanup_policy=CleanupPolicy.NONE,
                resume_policy=ResumePolicy.NO_RESUME,
                priority_decision=priority_decision,
                reason_codes=("CURRENT_ACTIVITY_NOT_INTERRUPTIBLE",),
            )

        reason = (
            "PREEMPT_CURRENT_ACTIVITY"
            if rule.interrupt
            else f"INCOMING_{rule.disposition.value}"
        )
        return PreemptionDecision(
            current_subject_id=current.subject_id,
            incoming_subject_id=incoming.subject_id,
            interrupt=rule.interrupt,
            can_interrupt=can_interrupt,
            disposition=rule.disposition,
            on_interrupt=rule.on_interrupt,
            cleanup_policy=rule.cleanup_policy,
            resume_policy=rule.resume_policy,
            priority_decision=priority_decision,
            reason_codes=(reason,),
        )

    @staticmethod
    def _validate_priority_decision(
        current: PrioritySubject | None,
        incoming: PrioritySubject,
        decision: PriorityDecision,
    ) -> None:
        current_id = None if current is None else current.subject_id
        current_priority = None if current is None else current.priority
        if decision.current_subject_id != current_id:
            raise PriorityDecisionMismatchError(
                "PriorityDecision current_subject_id does not match current activity"
            )
        if decision.incoming_subject_id != incoming.subject_id:
            raise PriorityDecisionMismatchError(
                "PriorityDecision incoming_subject_id does not match incoming event"
            )
        if decision.current_priority != current_priority:
            raise PriorityDecisionMismatchError(
                "PriorityDecision current_priority does not match current activity"
            )
        if decision.incoming_priority != incoming.priority:
            raise PriorityDecisionMismatchError(
                "PriorityDecision incoming_priority does not match incoming event"
            )

    def _select_rule(
        self,
        *,
        current_kind: str,
        incoming_kind: str,
        relation: PriorityRelation,
    ) -> PreemptionRule:
        exact = [
            rule
            for rule in self._rules
            if rule.current_kind == current_kind
            and rule.incoming_kind == incoming_kind
            and rule.relation is relation
        ]
        if len(exact) > 1:
            raise AmbiguousPreemptionRuleError("multiple exact preemption rules matched")
        if exact:
            return exact[0]

        fallback = [
            rule
            for rule in self._rules
            if rule.current_kind == current_kind
            and rule.incoming_kind == incoming_kind
            and rule.relation is PriorityRelation.ANY
        ]
        if len(fallback) > 1:
            raise AmbiguousPreemptionRuleError("multiple fallback preemption rules matched")
        if fallback:
            return fallback[0]

        raise MissingPreemptionRuleError(
            "no explicit preemption rule matched current/incoming/relation"
        )
