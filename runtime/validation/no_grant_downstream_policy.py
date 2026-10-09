"""Pure B1b-P downstream deny-only policy; never attests origin or issues grants."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from runtime.contracts.enums import BusinessStatus, ValidationStatus
from runtime.contracts.validation import ValidatedResult


class NoGrantOriginClassification(StrEnum):
    NO_GRANT_INTERNAL = "NO_GRANT_INTERNAL"
    UNATTESTED_UNKNOWN = "UNATTESTED_UNKNOWN"


class NoGrantDownstreamReason(StrEnum):
    NO_AUTHORIZED_VALIDATION_GRANT = "NO_AUTHORIZED_VALIDATION_GRANT"
    AUTHORITY_UNATTESTED = "AUTHORITY_UNATTESTED"
    CORRELATION_MISMATCH = "CORRELATION_MISMATCH"
    CANONICAL_MISMATCH = "CANONICAL_MISMATCH"


class NoGrantDownstreamErrorCode(StrEnum):
    INVALID_CONTEXT = "INVALID_CONTEXT"
    INVALID_VALIDATED_RESULT = "INVALID_VALIDATED_RESULT"
    INVALID_CONTEXT_FIELD = "INVALID_CONTEXT_FIELD"


class NoGrantDownstreamError(ValueError):
    """Internal fail-closed rejection: callers must not fall back to validation."""

    def __init__(self, code: NoGrantDownstreamErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


def _valid_id(value: object) -> bool:
    return type(value) is str and bool(value) and value == value.strip()


@dataclass(frozen=True, slots=True)
class NoGrantDownstreamContext:
    """Caller-supplied structural input, NEVER proof of trusted provenance."""

    expected_request_id: str
    expected_execution_id: str
    expected_validation_id: str
    expected_identity_scope: str
    expected_session_id: str
    provenance_kind: NoGrantOriginClassification
    structural_only: Literal[True] = True

    def __post_init__(self) -> None:
        if (
            not all(
                _valid_id(value)
                for value in (
                    self.expected_request_id,
                    self.expected_execution_id,
                    self.expected_validation_id,
                    self.expected_identity_scope,
                    self.expected_session_id,
                )
            )
            or type(self.provenance_kind) is not NoGrantOriginClassification
            or self.structural_only is not True
        ):
            raise NoGrantDownstreamError(
                NoGrantDownstreamErrorCode.INVALID_CONTEXT_FIELD
            )


class NoGrantDownstreamDisposition(StrEnum):
    BLOCK_BEFORE_M7_M8 = "BLOCK_BEFORE_M7_M8"


@dataclass(frozen=True, slots=True)
class NoGrantDownstreamDecision:
    reason: NoGrantDownstreamReason
    origin_classification: NoGrantOriginClassification
    request_id: str | None = None
    execution_id: str | None = None
    validation_id: str | None = None
    disposition: Literal[NoGrantDownstreamDisposition.BLOCK_BEFORE_M7_M8] = field(
        default=NoGrantDownstreamDisposition.BLOCK_BEFORE_M7_M8, init=False
    )
    may_call_response_planner: Literal[False] = field(default=False, init=False)
    may_call_response_generator: Literal[False] = field(default=False, init=False)
    may_call_response_validator: Literal[False] = field(default=False, init=False)
    may_call_state_memory_updater: Literal[False] = field(default=False, init=False)
    may_emit_positive_claim: Literal[False] = field(default=False, init=False)
    may_commit_business_or_memory: Literal[False] = field(default=False, init=False)
    allowed_user_response: Literal["NONE"] = field(default="NONE", init=False)


def _valid_context_fields(context: NoGrantDownstreamContext) -> bool:
    return (
        all(
            _valid_id(value)
            for value in (
                context.expected_request_id,
                context.expected_execution_id,
                context.expected_validation_id,
                context.expected_identity_scope,
                context.expected_session_id,
            )
        )
        and type(context.provenance_kind) is NoGrantOriginClassification
        and context.structural_only is True
    )


def _canonical_nonaffirmative(validated: ValidatedResult) -> bool:
    try:
        policy = validated.claim_policy
        return (
            validated.validation_status is ValidationStatus.UNKNOWN
            and validated.business_status is BusinessStatus.UNKNOWN
            and not validated.verified_facts
            and not validated.goal_validation
            and not validated.state_recommendation
            and policy is not None
            and not policy.allowed_claims
            and not policy.conditional_claims
        )
    except (AttributeError, TypeError, ValueError):
        return False


def evaluate_no_grant_downstream(
    *,
    validated: ValidatedResult,
    context: NoGrantDownstreamContext,
) -> NoGrantDownstreamDecision:
    """Deny-only, pure structural classification. Never calls downstream owners."""
    if type(context) is not NoGrantDownstreamContext:
        raise NoGrantDownstreamError(NoGrantDownstreamErrorCode.INVALID_CONTEXT)
    if type(validated) is not ValidatedResult:
        raise NoGrantDownstreamError(NoGrantDownstreamErrorCode.INVALID_VALIDATED_RESULT)
    if not _valid_context_fields(context):
        raise NoGrantDownstreamError(NoGrantDownstreamErrorCode.INVALID_CONTEXT_FIELD)

    try:
        correlates = (
            _valid_id(validated.request_id)
            and _valid_id(validated.execution_id)
            and _valid_id(validated.validation_id)
            and validated.request_id == context.expected_request_id
            and validated.execution_id == context.expected_execution_id
            and validated.validation_id == context.expected_validation_id
        )
    except (AttributeError, TypeError, ValueError):
        correlates = False

    if not correlates:
        return NoGrantDownstreamDecision(
            reason=NoGrantDownstreamReason.CORRELATION_MISMATCH,
            origin_classification=context.provenance_kind,
        )

    ids = {
        "request_id": validated.request_id,
        "execution_id": validated.execution_id,
        "validation_id": validated.validation_id,
    }
    if not _canonical_nonaffirmative(validated):
        return NoGrantDownstreamDecision(
            reason=NoGrantDownstreamReason.CANONICAL_MISMATCH,
            origin_classification=context.provenance_kind,
            **ids,
        )
    reason = (
        NoGrantDownstreamReason.AUTHORITY_UNATTESTED
        if context.provenance_kind is NoGrantOriginClassification.UNATTESTED_UNKNOWN
        else NoGrantDownstreamReason.NO_AUTHORIZED_VALIDATION_GRANT
    )
    return NoGrantDownstreamDecision(
        reason=reason,
        origin_classification=context.provenance_kind,
        **ids,
    )
