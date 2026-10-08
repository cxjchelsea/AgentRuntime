"""M6-IU1 Slice A: read-only admission, correlation and provenance.

This module never promotes execution observations to business truth.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from runtime.contracts import ApprovedActionPlan, ExecutionResult, RuntimeContext


class AdmissionStatus(StrEnum):
    ADMITTED = "ADMITTED"
    REJECTED = "REJECTED"


class AdmissionReason(StrEnum):
    REQUEST_MISMATCH = "REQUEST_MISMATCH"
    PLAN_MISMATCH = "PLAN_MISMATCH"
    IDENTITY_SCOPE_MISMATCH = "IDENTITY_SCOPE_MISMATCH"
    SESSION_MISMATCH = "SESSION_MISMATCH"
    DUPLICATE_PLAN_STEP = "DUPLICATE_PLAN_STEP"
    DUPLICATE_EXECUTION_STEP = "DUPLICATE_EXECUTION_STEP"
    UNKNOWN_EXECUTION_STEP = "UNKNOWN_EXECUTION_STEP"
    DUPLICATE_TOOL_CALL = "DUPLICATE_TOOL_CALL"
    MISSING_STEP_ID = "MISSING_STEP_ID"
    EMPTY_IDENTITY = "EMPTY_IDENTITY"
    INVALID_POLICY_SNAPSHOT = "INVALID_POLICY_SNAPSHOT"
    TOOL_OWNER_MISMATCH = "TOOL_OWNER_MISMATCH"
    DUPLICATE_GOAL = "DUPLICATE_GOAL"
    NONCANONICAL_SOURCE = "NONCANONICAL_SOURCE"


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    reference_id: str
    source_path: str
    source_id: str
    observed_at: str | None


@dataclass(frozen=True, slots=True)
class ValidationInputEnvelope:
    """Serialized, frozen source snapshots; never an authority grant."""

    execution_json: str
    approved_plan_json: str
    context_json: str
    policy_snapshot_json: str
    fingerprint: str
    evidence_refs: tuple[EvidenceReference, ...]
    rule_binding_status: str = "UNRESOLVED"


@dataclass(frozen=True, slots=True)
class ValidationAdmissionDecision:
    status: AdmissionStatus
    reasons: tuple[AdmissionReason, ...]
    envelope: ValidationInputEnvelope | None

    def __post_init__(self) -> None:
        if self.status is AdmissionStatus.ADMITTED:
            if self.reasons or self.envelope is None:
                raise ValueError("ADMITTED requires envelope and no reasons")
        elif not self.reasons or self.envelope is not None:
            raise ValueError("REJECTED requires reasons and no envelope")


def _serialized(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _ref(path: str, source_id: str, observed_at: Any) -> EvidenceReference:
    timestamp = observed_at.isoformat() if observed_at is not None else None
    return EvidenceReference(_digest(_serialized((path, source_id))), path, source_id, timestamp)


def admit_validation_input(
    execution: ExecutionResult,
    context: RuntimeContext,
    approved: ApprovedActionPlan,
    *,
    expected_request_id: str,
    expected_session_id: str,
) -> ValidationAdmissionDecision:
    """Only checks explicitly available correlation; absent trusted request is not guessed."""
    errors: list[AdmissionReason] = []

    def reject(code: AdmissionReason) -> None:
        if code not in errors:
            errors.append(code)

    if not expected_request_id or execution.request_id != approved.request_id or execution.request_id != expected_request_id:
        reject(AdmissionReason.REQUEST_MISMATCH)
    if execution.plan_id != approved.plan_id:
        reject(AdmissionReason.PLAN_MISMATCH)
    if not execution.identity_scope or not context.identity_context.identity_scope:
        reject(AdmissionReason.EMPTY_IDENTITY)
    elif execution.identity_scope != context.identity_context.identity_scope:
        reject(AdmissionReason.IDENTITY_SCOPE_MISMATCH)
    if not expected_session_id or context.session_context.session_id != expected_session_id:
        reject(AdmissionReason.SESSION_MISMATCH)

    policy = approved.policy_snapshot
    if not isinstance(policy, dict) or not all(
        k in policy for k in ("policy_decision_id", "allowed", "blocked", "validation_mode")
    ) or policy.get("allowed") is not True or policy.get("blocked") is not False:
        reject(AdmissionReason.INVALID_POLICY_SNAPSHOT)
    goal_ids = [goal.goal_id for goal in approved.goals]
    if len(goal_ids) != len(set(goal_ids)):
        reject(AdmissionReason.DUPLICATE_GOAL)
    plan_step_ids = [s.step_id for s in approved.steps]
    if len(plan_step_ids) != len(set(plan_step_ids)):
        reject(AdmissionReason.DUPLICATE_PLAN_STEP)
    known_steps = set(plan_step_ids)
    observed_steps: set[str] = set()
    observed_calls: set[str] = set()
    for step in execution.step_results:
        if not step.step_id:
            reject(AdmissionReason.MISSING_STEP_ID)
        elif step.step_id in observed_steps:
            reject(AdmissionReason.DUPLICATE_EXECUTION_STEP)
        elif step.step_id not in known_steps:
            reject(AdmissionReason.UNKNOWN_EXECUTION_STEP)
        if step.step_id:
            observed_steps.add(step.step_id)
        for call_id in step.tool_call_ids or ():
            if not call_id or call_id in observed_calls:
                reject(AdmissionReason.DUPLICATE_TOOL_CALL)
            observed_calls.add(call_id)
    for result in execution.tool_results or ():
        if not isinstance(result, dict):
            reject(AdmissionReason.NONCANONICAL_SOURCE)
            continue
        call_id = result.get("tool_call_id", result.get("call_id"))
        step_id = result.get("step_id")
        if not isinstance(call_id, str) or call_id not in observed_calls:
            reject(AdmissionReason.TOOL_OWNER_MISMATCH)
        if step_id is not None:
            owners = {step.step_id for step in execution.step_results
                      if call_id in (step.tool_call_ids or ())}
            if not isinstance(step_id, str) or step_id not in owners:
                reject(AdmissionReason.TOOL_OWNER_MISMATCH)
    if errors:
        return ValidationAdmissionDecision(AdmissionStatus.REJECTED, tuple(errors), None)

    try:
        execution_json = _serialized(execution.model_dump(mode="json"))
        approved_json = _serialized(approved.model_dump(mode="json"))
        context_json = _serialized(context.model_dump(mode="json"))
        policy_json = _serialized(approved.policy_snapshot)
    except (TypeError, ValueError, OverflowError):
        return ValidationAdmissionDecision(
            AdmissionStatus.REJECTED, (AdmissionReason.NONCANONICAL_SOURCE,), None
        )
    digest = _digest(_serialized((execution_json, approved_json, context_json, policy_json)))
    refs: list[EvidenceReference] = []
    for index, step in enumerate(execution.step_results):
        if step.step_id:
            path = f"step_results[{index}]"
            refs.append(_ref(path, step.step_id, step.finished_at))
            for n, call_id in enumerate(step.tool_call_ids or ()):
                refs.append(_ref(f"{path}.tool_call_ids[{n}]", call_id, None))
    for index, result in enumerate(execution.tool_results or ()):
        call_id = result.get("tool_call_id", result.get("call_id"))
        if isinstance(call_id, str):
            refs.append(_ref(f"tool_results[{index}]", call_id, None))
    return ValidationAdmissionDecision(
        AdmissionStatus.ADMITTED,
        (),
        ValidationInputEnvelope(execution_json, approved_json, context_json, policy_json, digest, tuple(refs)),
    )
