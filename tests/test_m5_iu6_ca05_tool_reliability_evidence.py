"""CA-M5-IU6-05 Tool reliability evidence contract gates."""

from __future__ import annotations

import pytest

from runtime.execution import (
    IdempotencyMode,
    M5ToolResult,
    SideEffectClass,
    ToolExecutionStatus,
    ToolInvocationJournalEntry,
    ToolReliabilityEvidence,
)


def _result() -> M5ToolResult:
    return M5ToolResult(
        tool_call_id="tool-call-001",
        tool_id="TOOL_A",
        status=ToolExecutionStatus.SUCCESS,
    )


def test_tool_reliability_evidence_freezes_policy_and_idempotency_mode() -> None:
    evidence = ToolReliabilityEvidence(
        policy_identity="tool-policy@sha256:abc",
        idempotency_mode=IdempotencyMode.NON_IDEMPOTENT,
        side_effect_class=SideEffectClass.HIGH,
        invocation_started=True,
    )
    result = _result()
    from runtime.execution import ToolAttemptObservation

    attempt = ToolAttemptObservation(
        logical_tool_call_id=result.tool_call_id,
        tool_id=result.tool_id,
        tool_version="1.0.0",
        physical_attempt=1,
        result=result,
    )
    journal = ToolInvocationJournalEntry(
        tool_call_id=result.tool_call_id,
        tool_id=result.tool_id,
        tool_version="1.0.0",
        result=result,
        reliability_evidence=evidence,
        attempts=(attempt,),
    )

    assert journal.reliability_evidence is not None
    assert (
        journal.reliability_evidence.idempotency_mode
        is IdempotencyMode.NON_IDEMPOTENT
    )
    assert journal.reliability_evidence.invocation_started is True


def test_reliability_evidence_requires_policy_identity() -> None:
    with pytest.raises(ValueError, match="policy_identity"):
        ToolReliabilityEvidence(
            policy_identity="",
            idempotency_mode=IdempotencyMode.NATURAL,
            side_effect_class=SideEffectClass.NONE,
            invocation_started=False,
        )


def test_invocation_started_evidence_requires_physical_attempt() -> None:
    with pytest.raises(ValueError, match="requires attempts"):
        ToolInvocationJournalEntry(
            tool_call_id="tool-call-001",
            tool_id="TOOL_A",
            tool_version="1.0.0",
            result=_result(),
            reliability_evidence=ToolReliabilityEvidence(
                policy_identity="tool-policy@sha256:abc",
                idempotency_mode=IdempotencyMode.NON_IDEMPOTENT,
                side_effect_class=SideEffectClass.HIGH,
                invocation_started=True,
            ),
        )


def test_recovered_or_gate_only_logical_result_can_record_not_started() -> None:
    evidence = ToolReliabilityEvidence(
        policy_identity="tool-policy@sha256:abc",
        idempotency_mode=IdempotencyMode.KEY_BASED,
        side_effect_class=SideEffectClass.HIGH,
        invocation_started=False,
    )
    journal = ToolInvocationJournalEntry(
        tool_call_id="tool-call-001",
        tool_id="TOOL_A",
        tool_version="1.0.0",
        result=_result(),
        reliability_evidence=evidence,
    )

    assert journal.attempts == ()
    assert journal.reliability_evidence is not None
    assert journal.reliability_evidence.invocation_started is False


def test_legacy_iu4_journal_may_omit_reliability_evidence() -> None:
    journal = ToolInvocationJournalEntry(
        tool_call_id="tool-call-001",
        tool_id="TOOL_A",
        tool_version="1.0.0",
        result=_result(),
    )

    assert journal.reliability_evidence is None
