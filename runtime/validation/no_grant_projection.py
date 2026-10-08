"""M6-IU1 B1a: structural-only, nonauthoritative NoGrant projection.

This module does not verify external caller provenance, consume a B0 slot,
issue a positive grant, or authorize downstream Response/State updates.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from runtime.contracts import (
    ApprovedActionPlan,
    ExecutionResult,
    RuntimeContext,
)
from runtime.contracts.enums import BusinessStatus, ValidationStatus
from runtime.contracts.validation import ClaimPolicy, ValidatedResult
from runtime.validation.no_grant import NoGrant, NoGrantReason
from runtime.validation.slice_a import (
    AdmissionStatus,
    ValidationAdmissionDecision,
    admit_validation_input,
)

ValidationIdAllocator = Callable[[], str]


class NoGrantProjectionReason(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    ORIGIN_INVALID = "ORIGIN_INVALID"
    NO_GRANT_INVALID = "NO_GRANT_INVALID"
    ADMISSION_REJECTED = "ADMISSION_REJECTED"
    ADMISSION_INVALID = "ADMISSION_INVALID"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    RECHECK_REJECTED = "RECHECK_REJECTED"
    SOURCE_CHANGED = "SOURCE_CHANGED"
    VALIDATION_ID_INVALID = "VALIDATION_ID_INVALID"
    VALIDATION_ID_COLLISION = "VALIDATION_ID_COLLISION"
    PROJECTION_FAILED = "PROJECTION_FAILED"


class NoGrantProjectionError(ValueError):
    """A typed internal rejection. Never returned as a canonical success."""

    def __init__(self, reason: NoGrantProjectionReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


def _valid_identifier(value: object) -> bool:
    return type(value) is str and bool(value) and value == value.strip()


@dataclass(frozen=True, slots=True)
class ValidationOriginBinding:
    """Structural expectation only; not authenticated RuntimeInput provenance."""

    expected_request_id: str
    expected_session_id: str
    expected_identity_scope: str
    trust_level: Literal["STRUCTURAL_ONLY"] = "STRUCTURAL_ONLY"

    def __post_init__(self) -> None:
        if (
            not _valid_identifier(self.expected_request_id)
            or not _valid_identifier(self.expected_session_id)
            or not _valid_identifier(self.expected_identity_scope)
            or self.trust_level != "STRUCTURAL_ONLY"
        ):
            raise NoGrantProjectionError(NoGrantProjectionReason.ORIGIN_INVALID)


class NoGrantProjectionController:
    """Owns ID uniqueness only for this instance's lifetime.

    Not thread-safe or a durable replay/uniqueness authority.
    """

    __slots__ = ("_allocator", "_used_ids")

    def __init__(self, *, id_allocator: ValidationIdAllocator | None = None) -> None:
        if id_allocator is not None and not callable(id_allocator):
            raise NoGrantProjectionError(NoGrantProjectionReason.VALIDATION_ID_INVALID)
        self._allocator = id_allocator if id_allocator is not None else lambda: uuid.uuid4().hex
        self._used_ids: set[str] = set()

    def project(
        self,
        *,
        admission: ValidationAdmissionDecision,
        execution: ExecutionResult,
        approved: ApprovedActionPlan,
        context: RuntimeContext,
        origin: ValidationOriginBinding,
        no_grant: NoGrant,
    ) -> ValidatedResult:
        if (
            not isinstance(admission, ValidationAdmissionDecision)
            or not isinstance(execution, ExecutionResult)
            or not isinstance(approved, ApprovedActionPlan)
            or not isinstance(context, RuntimeContext)
        ):
            raise NoGrantProjectionError(NoGrantProjectionReason.INVALID_INPUT)
        if not isinstance(origin, ValidationOriginBinding):
            raise NoGrantProjectionError(NoGrantProjectionReason.ORIGIN_INVALID)
        if not isinstance(no_grant, NoGrant):
            raise NoGrantProjectionError(NoGrantProjectionReason.NO_GRANT_INVALID)
        if (
            admission.status is AdmissionStatus.REJECTED
            and admission.envelope is None
        ):
            raise NoGrantProjectionError(NoGrantProjectionReason.ADMISSION_REJECTED)
        if (
            admission.status is not AdmissionStatus.ADMITTED
            or admission.reasons
            or admission.envelope is None
            or admission.envelope.rule_binding_status != "UNRESOLVED"
        ):
            raise NoGrantProjectionError(NoGrantProjectionReason.ADMISSION_INVALID)
        if (
            not _valid_identifier(execution.execution_id)
            or not _valid_identifier(execution.plan_id)
            or not _valid_identifier(execution.request_id)
            or not _valid_identifier(execution.identity_scope)
            or not _valid_identifier(approved.plan_id)
            or not _valid_identifier(approved.request_id)
            or origin.expected_request_id != execution.request_id
            or origin.expected_request_id != approved.request_id
            or execution.plan_id != approved.plan_id
            or origin.expected_session_id != context.session_context.session_id
            or origin.expected_identity_scope != execution.identity_scope
            or origin.expected_identity_scope != context.identity_context.identity_scope
        ):
            raise NoGrantProjectionError(NoGrantProjectionReason.IDENTITY_MISMATCH)
        try:
            rechecked = admit_validation_input(
                execution,
                context,
                approved,
                expected_request_id=origin.expected_request_id,
                expected_session_id=origin.expected_session_id,
            )
        except (TypeError, ValueError, AttributeError) as exc:
            raise NoGrantProjectionError(NoGrantProjectionReason.RECHECK_REJECTED) from exc
        if (
            rechecked.status is not AdmissionStatus.ADMITTED
            or rechecked.envelope is None
        ):
            raise NoGrantProjectionError(NoGrantProjectionReason.RECHECK_REJECTED)
        if rechecked.envelope != admission.envelope:
            raise NoGrantProjectionError(NoGrantProjectionReason.SOURCE_CHANGED)
        if not isinstance(no_grant.reason, NoGrantReason):
            raise NoGrantProjectionError(NoGrantProjectionReason.NO_GRANT_INVALID)
        try:
            validation_id = self._allocator()
        except Exception as exc:
            raise NoGrantProjectionError(NoGrantProjectionReason.VALIDATION_ID_INVALID) from exc
        if not _valid_identifier(validation_id):
            raise NoGrantProjectionError(NoGrantProjectionReason.VALIDATION_ID_INVALID)
        if validation_id in self._used_ids:
            raise NoGrantProjectionError(NoGrantProjectionReason.VALIDATION_ID_COLLISION)
        self._used_ids.add(validation_id)
        try:
            return ValidatedResult(
                validation_id=validation_id,
                execution_id=execution.execution_id,
                request_id=execution.request_id,
                validation_status=ValidationStatus.UNKNOWN,
                business_status=BusinessStatus.UNKNOWN,
                claim_policy=ClaimPolicy(
                    allowed_claims=[],
                    forbidden_claims=[],
                    conditional_claims=[],
                    required_qualifiers=[
                        "No authorized validation profile; no positive claims"
                    ],
                    certainty_level=None,
                ),
                goal_validation=None,
                verified_facts=None,
                unverified_facts=None,
                conflicting_facts=None,
                followup=None,
                state_recommendation=None,
                validation_errors=[
                    {"code": "GRANT_MISSING", "reason": no_grant.reason.value}
                ],
                quality=None,
            )
        except Exception as exc:
            raise NoGrantProjectionError(NoGrantProjectionReason.PROJECTION_FAILED) from exc
