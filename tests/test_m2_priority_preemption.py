"""M2-IU3 Priority / Preemption Engine tests."""

from __future__ import annotations

import pytest

from runtime.priority_management import (
    CleanupPolicy,
    DuplicatePreemptionRuleError,
    IncomingDisposition,
    InvalidPrioritySubjectError,
    MissingPreemptionRuleError,
    PreemptionEngine,
    PreemptionRule,
    PriorityEngine,
    PriorityRelation,
    PrioritySubject,
    ResumePolicy,
)


def _subject(
    subject_id: str,
    kind: str,
    priority: int,
) -> PrioritySubject:
    return PrioritySubject(subject_id=subject_id, kind=kind, priority=priority)


def test_priority_engine_compares_higher_equal_and_lower() -> None:
    current = _subject("current", "TEST_CURRENT", 50)

    higher = PriorityEngine.evaluate(
        current=current,
        incoming=_subject("higher", "TEST_INCOMING", 80),
    )
    equal = PriorityEngine.evaluate(
        current=current,
        incoming=_subject("equal", "TEST_INCOMING", 50),
    )
    lower = PriorityEngine.evaluate(
        current=current,
        incoming=_subject("lower", "TEST_INCOMING", 20),
    )

    assert higher.relation is PriorityRelation.HIGHER
    assert higher.higher_than_current is True
    assert equal.relation is PriorityRelation.EQUAL
    assert equal.higher_than_current is False
    assert lower.relation is PriorityRelation.LOWER
    assert lower.higher_than_current is False


def test_no_current_activity_is_processable_without_preemption_rule() -> None:
    incoming = _subject("incoming", "TEST_INCOMING", 10)
    priority = PriorityEngine.evaluate(current=None, incoming=incoming)
    decision = PreemptionEngine(rules=[]).evaluate(
        current=None,
        incoming=incoming,
        current_interruptible=False,
        priority_decision=priority,
    )

    assert priority.current_priority is None
    assert decision.interrupt is False
    assert decision.can_interrupt is False
    assert decision.disposition is IncomingDisposition.PROCESS_NOW
    assert decision.reason_codes == ("NO_CURRENT_ACTIVITY",)


def test_higher_priority_can_preempt_when_explicit_rule_allows() -> None:
    current = _subject("current", "TEST_CURRENT", 20)
    incoming = _subject("incoming", "TEST_INCOMING", 100)
    priority = PriorityEngine.evaluate(current=current, incoming=incoming)
    engine = PreemptionEngine(
        rules=[
            PreemptionRule(
                current_kind="TEST_CURRENT",
                incoming_kind="TEST_INCOMING",
                relation=PriorityRelation.HIGHER,
                interrupt=True,
                disposition=IncomingDisposition.PROCESS_NOW,
                when_not_interruptible=IncomingDisposition.QUEUE,
                on_interrupt="TEST_STOP_CURRENT",
                cleanup_policy=CleanupPolicy.CHECKPOINT,
                resume_policy=ResumePolicy.REPLAN,
            )
        ]
    )

    decision = engine.evaluate(
        current=current,
        incoming=incoming,
        current_interruptible=True,
        priority_decision=priority,
    )

    assert decision.interrupt is True
    assert decision.can_interrupt is True
    assert decision.disposition is IncomingDisposition.PROCESS_NOW
    assert decision.cleanup_policy is CleanupPolicy.CHECKPOINT
    assert decision.resume_policy is ResumePolicy.REPLAN
    assert decision.on_interrupt == "TEST_STOP_CURRENT"


def test_noninterruptible_current_uses_explicit_blocked_disposition() -> None:
    current = _subject("current", "TEST_CURRENT", 20)
    incoming = _subject("incoming", "TEST_INCOMING", 100)
    priority = PriorityEngine.evaluate(current=current, incoming=incoming)
    engine = PreemptionEngine(
        rules=[
            PreemptionRule(
                current_kind="TEST_CURRENT",
                incoming_kind="TEST_INCOMING",
                relation=PriorityRelation.HIGHER,
                interrupt=True,
                disposition=IncomingDisposition.PROCESS_NOW,
                when_not_interruptible=IncomingDisposition.QUEUE,
                cleanup_policy=CleanupPolicy.CANCEL,
                resume_policy=ResumePolicy.NO_RESUME,
            )
        ]
    )

    decision = engine.evaluate(
        current=current,
        incoming=incoming,
        current_interruptible=False,
        priority_decision=priority,
    )

    assert decision.interrupt is False
    assert decision.can_interrupt is False
    assert decision.disposition is IncomingDisposition.QUEUE
    assert decision.cleanup_policy is CleanupPolicy.NONE
    assert decision.resume_policy is ResumePolicy.NO_RESUME
    assert decision.reason_codes == ("CURRENT_ACTIVITY_NOT_INTERRUPTIBLE",)


def test_lower_priority_can_be_deferred_by_explicit_rule() -> None:
    current = _subject("current", "TEST_CURRENT", 80)
    incoming = _subject("incoming", "TEST_INCOMING", 10)
    priority = PriorityEngine.evaluate(current=current, incoming=incoming)
    engine = PreemptionEngine(
        rules=[
            PreemptionRule(
                current_kind="TEST_CURRENT",
                incoming_kind="TEST_INCOMING",
                relation=PriorityRelation.LOWER,
                interrupt=False,
                disposition=IncomingDisposition.DEFER,
            )
        ]
    )

    decision = engine.evaluate(
        current=current,
        incoming=incoming,
        current_interruptible=True,
        priority_decision=priority,
    )

    assert decision.interrupt is False
    assert decision.disposition is IncomingDisposition.DEFER
    assert decision.reason_codes == ("INCOMING_DEFER",)


def test_equal_priority_policy_is_not_invented_by_core() -> None:
    current = _subject("current", "TEST_CURRENT", 50)
    incoming = _subject("incoming", "TEST_INCOMING", 50)
    priority = PriorityEngine.evaluate(current=current, incoming=incoming)

    with pytest.raises(MissingPreemptionRuleError):
        PreemptionEngine(rules=[]).evaluate(
            current=current,
            incoming=incoming,
            current_interruptible=True,
            priority_decision=priority,
        )


def test_any_relation_rule_is_fallback_but_exact_rule_wins() -> None:
    current = _subject("current", "TEST_CURRENT", 20)
    incoming = _subject("incoming", "TEST_INCOMING", 100)
    priority = PriorityEngine.evaluate(current=current, incoming=incoming)
    engine = PreemptionEngine(
        rules=[
            PreemptionRule(
                current_kind="TEST_CURRENT",
                incoming_kind="TEST_INCOMING",
                relation=PriorityRelation.ANY,
                interrupt=False,
                disposition=IncomingDisposition.DEFER,
            ),
            PreemptionRule(
                current_kind="TEST_CURRENT",
                incoming_kind="TEST_INCOMING",
                relation=PriorityRelation.HIGHER,
                interrupt=True,
                disposition=IncomingDisposition.PROCESS_NOW,
                when_not_interruptible=IncomingDisposition.DROP,
            ),
        ]
    )

    decision = engine.evaluate(
        current=current,
        incoming=incoming,
        current_interruptible=True,
        priority_decision=priority,
    )
    assert decision.interrupt is True


def test_duplicate_rule_key_is_rejected() -> None:
    rule = PreemptionRule(
        current_kind="TEST_CURRENT",
        incoming_kind="TEST_INCOMING",
        relation=PriorityRelation.ANY,
        interrupt=False,
        disposition=IncomingDisposition.DEFER,
    )
    with pytest.raises(DuplicatePreemptionRuleError):
        PreemptionEngine(rules=[rule, rule])


def test_interrupt_rule_requires_explicit_noninterruptible_behavior() -> None:
    with pytest.raises(ValueError, match="when_not_interruptible"):
        PreemptionRule(
            current_kind="TEST_CURRENT",
            incoming_kind="TEST_INCOMING",
            relation=PriorityRelation.HIGHER,
            interrupt=True,
            disposition=IncomingDisposition.PROCESS_NOW,
        )


def test_priority_subject_rejects_blank_identifiers() -> None:
    with pytest.raises(InvalidPrioritySubjectError):
        PrioritySubject(subject_id=" ", kind="TEST", priority=1)
    with pytest.raises(InvalidPrioritySubjectError):
        PrioritySubject(subject_id="id", kind=" ", priority=1)


def test_priority_numbers_and_kinds_remain_injected_values() -> None:
    current = _subject("current", "TEST_BACKGROUND", -5)
    incoming = _subject("incoming", "TEST_FOREGROUND", 7)
    decision = PriorityEngine.evaluate(current=current, incoming=incoming)

    assert decision.current_priority == -5
    assert decision.incoming_priority == 7
    assert decision.relation is PriorityRelation.HIGHER
