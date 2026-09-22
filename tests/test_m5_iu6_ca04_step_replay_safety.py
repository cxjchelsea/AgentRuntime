"""CA-M5-IU6-04 Step replay safety contract gates."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from runtime.execution import (
    CapabilityExecutionOwner,
    IdempotencyMode,
    ReliabilityCapabilityKind,
    ResolvedIdempotencyPolicy,
    ResolvedReliabilityPolicy,
    ResolvedRetryPolicy,
    ResolvedTimeoutPolicy,
    SideEffectClass,
    StepAttemptObservation,
    StepAttemptStatus,
    StepReplaySafetyRequest,
)


def _observation() -> StepAttemptObservation:
    return StepAttemptObservation(
        step_id="step-001",
        step_execution_id="step-exec-001",
        attempt_number=1,
        status=StepAttemptStatus.FAILED,
        execution_owner=CapabilityExecutionOwner.SKILL,
        reason_codes=("SKILL_FAILED", "RESULT_COLLECTED"),
        observed_at=datetime(2026, 9, 22, 9, 0, tzinfo=UTC),
        owner_capability_id="SKILL_A",
        owner_capability_version="1.0.0",
    )


def _policy(kind: ReliabilityCapabilityKind) -> ResolvedReliabilityPolicy:
    return ResolvedReliabilityPolicy(
        capability_kind=kind,
        capability_id="SKILL_A"
        if kind is ReliabilityCapabilityKind.SKILL
        else "TOOL_A",
        capability_version="1.0.0",
        policy_identity="policy@sha256:abc",
        timeout=ResolvedTimeoutPolicy(timeout_seconds=None),
        retry=ResolvedRetryPolicy(enabled=False, max_attempts=1),
        idempotency=ResolvedIdempotencyPolicy(mode=IdempotencyMode.NATURAL),
        side_effect_class=SideEffectClass.NONE,
    )


def test_step_replay_safety_requires_skill_policy() -> None:
    request = StepReplaySafetyRequest(
        observation=_observation(),
        owner_policy=_policy(ReliabilityCapabilityKind.SKILL),
    )

    assert request.owner_policy.capability_kind is ReliabilityCapabilityKind.SKILL


def test_step_replay_safety_rejects_tool_policy() -> None:
    with pytest.raises(ValueError, match="SKILL reliability policy"):
        StepReplaySafetyRequest(
            observation=_observation(),
            owner_policy=_policy(ReliabilityCapabilityKind.TOOL),
        )


def test_step_replay_safety_rejects_non_skill_owner() -> None:
    with pytest.raises(ValueError, match="SKILL execution owner"):
        StepReplaySafetyRequest(
            observation=replace(
                _observation(),
                execution_owner=CapabilityExecutionOwner.WORKFLOW,
            ),
            owner_policy=_policy(ReliabilityCapabilityKind.SKILL),
        )


def test_step_replay_safety_rejects_policy_identity_mismatch() -> None:
    with pytest.raises(ValueError, match="exact observed Skill"):
        StepReplaySafetyRequest(
            observation=replace(
                _observation(),
                owner_capability_version="2.0.0",
            ),
            owner_policy=_policy(ReliabilityCapabilityKind.SKILL),
        )
