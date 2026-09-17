"""M2-IU5 Runtime Constraint integration tests."""

from __future__ import annotations

import asyncio

import pytest

from runtime.constraint_management import (
    RuntimeConstraintEvaluator,
    RuntimeConstraintInvariantError,
)
from runtime.contracts import SafetyPhase, SafetyRiskLevel
from runtime.policy_management import DefaultPolicyEngine
from runtime.priority_management import (
    CleanupPolicy,
    IncomingDisposition,
    MissingPreemptionRuleError,
    PreemptionEngine,
    PreemptionRule,
    PriorityRelation,
    PrioritySubject,
    ResumePolicy,
)
from tests.orchestration_stubs import (
    build_runtime_context,
    build_safety_result,
    build_understanding_state,
)


def _subject(subject_id: str, kind: str, priority: int) -> PrioritySubject:
    return PrioritySubject(subject_id=subject_id, kind=kind, priority=priority)


def _evaluator(*rules: PreemptionRule) -> RuntimeConstraintEvaluator:
    return RuntimeConstraintEvaluator(
        policy_engine=DefaultPolicyEngine(),
        preemption_engine=PreemptionEngine(rules),
    )


def test_constraint_evaluator_aggregates_explicit_m2_decisions() -> None:
    current = _subject("current", "TEST_CURRENT", 20)
    incoming = _subject("incoming", "TEST_INCOMING", 100)
    evaluator = _evaluator(
        PreemptionRule(
            current_kind="TEST_CURRENT",
            incoming_kind="TEST_INCOMING",
            relation=PriorityRelation.HIGHER,
            interrupt=True,
            disposition=IncomingDisposition.PROCESS_NOW,
            when_not_interruptible=IncomingDisposition.QUEUE,
            cleanup_policy=CleanupPolicy.CHECKPOINT,
            resume_policy=ResumePolicy.REPLAN,
        )
    )

    result = asyncio.run(
        evaluator.evaluate(
            runtime_context=build_runtime_context(),
            understanding_state=build_understanding_state(),
            safety_result=build_safety_result(SafetyPhase.DEEP),
            current_priority_subject=current,
            incoming_priority_subject=incoming,
        )
    )

    assert result.request_id == "request-001"
    assert result.state_decision.interruptible is True
    assert result.priority_decision.relation is PriorityRelation.HIGHER
    assert result.priority_decision.current_subject_id == "current"
    assert result.priority_decision.incoming_subject_id == "incoming"
    assert result.preemption_decision.interrupt is True
    assert result.preemption_decision.cleanup_policy is CleanupPolicy.CHECKPOINT
    assert result.preemption_decision.resume_policy is ResumePolicy.REPLAN
    assert result.policy_decision.allowed is True
    assert result.requires_interruption is True
    assert result.incoming_disposition is IncomingDisposition.PROCESS_NOW


def test_runtime_state_interruptibility_drives_preemption_inside_constraint_chain() -> None:
    context = build_runtime_context()
    state = context.runtime_state_context.model_copy(update={"interruptible": False})
    context = context.model_copy(update={"runtime_state_context": state})
    current = _subject("current", "TEST_CURRENT", 20)
    incoming = _subject("incoming", "TEST_INCOMING", 100)
    evaluator = _evaluator(
        PreemptionRule(
            current_kind="TEST_CURRENT",
            incoming_kind="TEST_INCOMING",
            relation=PriorityRelation.HIGHER,
            interrupt=True,
            disposition=IncomingDisposition.PROCESS_NOW,
            when_not_interruptible=IncomingDisposition.DROP,
        )
    )

    result = asyncio.run(
        evaluator.evaluate(
            runtime_context=context,
            understanding_state=build_understanding_state(),
            safety_result=build_safety_result(SafetyPhase.DEEP),
            current_priority_subject=current,
            incoming_priority_subject=incoming,
        )
    )

    assert result.state_decision.interruptible is False
    assert result.preemption_decision.interrupt is False
    assert result.preemption_decision.can_interrupt is False
    assert result.incoming_disposition is IncomingDisposition.DROP
    assert result.requires_interruption is False


def test_no_current_activity_needs_no_preemption_rule() -> None:
    result = asyncio.run(
        _evaluator().evaluate(
            runtime_context=build_runtime_context(),
            understanding_state=build_understanding_state(),
            safety_result=build_safety_result(SafetyPhase.DEEP),
            current_priority_subject=None,
            incoming_priority_subject=_subject("incoming", "TEST_INCOMING", 10),
        )
    )

    assert result.priority_decision.current_subject_id is None
    assert result.preemption_decision.interrupt is False
    assert result.incoming_disposition is IncomingDisposition.PROCESS_NOW


def test_missing_preemption_rule_fails_closed_inside_constraint_chain() -> None:
    with pytest.raises(MissingPreemptionRuleError):
        asyncio.run(
            _evaluator().evaluate(
                runtime_context=build_runtime_context(),
                understanding_state=build_understanding_state(),
                safety_result=build_safety_result(SafetyPhase.DEEP),
                current_priority_subject=_subject("current", "TEST_CURRENT", 50),
                incoming_priority_subject=_subject("incoming", "TEST_INCOMING", 50),
            )
        )


def test_constraint_chain_recomputes_priority_relation_from_subjects() -> None:
    result = asyncio.run(
        _evaluator(
            PreemptionRule(
                current_kind="TEST_CURRENT",
                incoming_kind="TEST_INCOMING",
                relation=PriorityRelation.LOWER,
                interrupt=False,
                disposition=IncomingDisposition.DEFER,
            )
        ).evaluate(
            runtime_context=build_runtime_context(),
            understanding_state=build_understanding_state(),
            safety_result=build_safety_result(SafetyPhase.DEEP),
            current_priority_subject=_subject("current", "TEST_CURRENT", 100),
            incoming_priority_subject=_subject("incoming", "TEST_INCOMING", 10),
        )
    )

    assert result.priority_decision.current_priority == 100
    assert result.priority_decision.incoming_priority == 10
    assert result.priority_decision.relation is PriorityRelation.LOWER
    assert result.incoming_disposition is IncomingDisposition.DEFER


def test_safety_hard_constraints_remain_visible_in_runtime_constraint() -> None:
    safety = build_safety_result(SafetyPhase.DEEP).model_copy(
        update={
            "risk_detected": True,
            "risk_level": SafetyRiskLevel.HIGH,
            "allowed_to_continue_normal_flow": False,
            "interrupt_current_task": True,
            "safety_lock_required": True,
            "force_workflow": "TEST_SAFETY_WORKFLOW",
            "reason_codes": ["TEST_SAFETY_REASON"],
        }
    )

    result = asyncio.run(
        _evaluator().evaluate(
            runtime_context=build_runtime_context(),
            understanding_state=build_understanding_state(),
            safety_result=safety,
            current_priority_subject=None,
            incoming_priority_subject=_subject("incoming", "TEST_INCOMING", 100),
        )
    )

    assert result.safety_result.risk_level is SafetyRiskLevel.HIGH
    assert result.policy_decision.allowed is False
    assert result.policy_decision.blocked is True
    assert result.policy_decision.interrupt_current_task is True
    assert result.policy_decision.forced_workflow == "TEST_SAFETY_WORKFLOW"
    assert result.requires_interruption is True


def test_constraint_evaluator_requires_deep_safety() -> None:
    with pytest.raises(RuntimeConstraintInvariantError, match="DEEP"):
        asyncio.run(
            _evaluator().evaluate(
                runtime_context=build_runtime_context(),
                understanding_state=build_understanding_state(),
                safety_result=build_safety_result(SafetyPhase.EARLY),
                current_priority_subject=None,
                incoming_priority_subject=_subject("incoming", "TEST_INCOMING", 1),
            )
        )


def test_constraint_evaluator_rejects_cross_turn_understanding() -> None:
    understanding = build_understanding_state()
    metadata = understanding.metadata.model_copy(update={"request_id": "other-request"})
    understanding = understanding.model_copy(update={"metadata": metadata})

    with pytest.raises(RuntimeConstraintInvariantError, match="request_id"):
        asyncio.run(
            _evaluator().evaluate(
                runtime_context=build_runtime_context(),
                understanding_state=understanding,
                safety_result=build_safety_result(SafetyPhase.DEEP),
                current_priority_subject=None,
                incoming_priority_subject=_subject("incoming", "TEST_INCOMING", 1),
            )
        )


def test_constraint_evaluation_does_not_mutate_runtime_state() -> None:
    context = build_runtime_context()
    before = context.runtime_state_context.model_dump()

    asyncio.run(
        _evaluator().evaluate(
            runtime_context=context,
            understanding_state=build_understanding_state(),
            safety_result=build_safety_result(SafetyPhase.DEEP),
            current_priority_subject=None,
            incoming_priority_subject=_subject("incoming", "TEST_INCOMING", 1),
        )
    )

    assert context.runtime_state_context.model_dump() == before
