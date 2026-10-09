"""M6-IU1 B2 Foundation F: turn-local structural NoGrant composition.

Not wired into either Orchestrator. No positive grant or provenance certification.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from runtime.contracts import (
    ApprovedActionPlan,
    ExecutionResult,
    RuntimeContext,
    RuntimeInput,
)
from runtime.contracts.validation import ValidatedResult
from runtime.validation.no_grant import NoGrantReason, NoGrantTurnSlot
from runtime.validation.no_grant_downstream_policy import (
    NoGrantDownstreamContext,
    NoGrantDownstreamDecision,
    NoGrantOriginClassification,
    evaluate_no_grant_downstream,
)
from runtime.validation.no_grant_projection import (
    NoGrantProjectionController,
    ValidationOriginBinding,
)
from runtime.validation.slice_a import AdmissionStatus, admit_validation_input


class M6FoundationErrorCode(StrEnum):
    INVALID_ORIGIN = "INVALID_ORIGIN"
    ORIGIN_CHANGED = "ORIGIN_CHANGED"
    CLOSED_TURN = "CLOSED_TURN"
    ALREADY_VALIDATED = "ALREADY_VALIDATED"
    ADMISSION_REJECTED = "ADMISSION_REJECTED"
    INVALID_INPUT = "INVALID_INPUT"


class M6FoundationError(ValueError):
    def __init__(self, code: M6FoundationErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


def _valid_id(value: object) -> bool:
    return type(value) is str and bool(value) and value == value.strip()


@dataclass(frozen=True, slots=True)
class TurnOriginSnapshot:
    request_id: str
    session_id: str
    identity_scope: str
    trace_id: str

    def __post_init__(self) -> None:
        if not all(
            _valid_id(v)
            for v in (
                self.request_id,
                self.session_id,
                self.identity_scope,
                self.trace_id,
            )
        ):
            raise M6FoundationError(M6FoundationErrorCode.INVALID_ORIGIN)

    @classmethod
    def from_runtime_input(cls, raw: RuntimeInput) -> TurnOriginSnapshot:
        if type(raw) is not RuntimeInput:
            raise M6FoundationError(M6FoundationErrorCode.INVALID_ORIGIN)
        return cls(raw.request_id, raw.session_id, raw.identity_scope, raw.trace_id)

    def assert_processed_identity(self, processed: RuntimeInput) -> None:
        if type(processed) is not RuntimeInput or (
            processed.request_id,
            processed.session_id,
            processed.identity_scope,
            processed.trace_id,
        ) != (self.request_id, self.session_id, self.identity_scope, self.trace_id):
            raise M6FoundationError(M6FoundationErrorCode.ORIGIN_CHANGED)


@dataclass(frozen=True, slots=True)
class M6NoGrantValidation:
    validated: ValidatedResult
    decision: NoGrantDownstreamDecision
    origin: TurnOriginSnapshot


class M6NoGrantTurnHandle:
    """Single-use turn owner. Failures cannot be retried using the same slot."""

    __slots__ = ("_closed", "_controller", "_slot", "_used", "origin")

    def __init__(self, origin: TurnOriginSnapshot) -> None:
        if type(origin) is not TurnOriginSnapshot or not all(
            _valid_id(v)
            for v in (
                origin.request_id,
                origin.session_id,
                origin.identity_scope,
                origin.trace_id,
            )
        ):
            raise M6FoundationError(M6FoundationErrorCode.INVALID_ORIGIN)
        self.origin = origin
        self._slot = NoGrantTurnSlot(NoGrantReason.NO_AUTHORIZED_POLICY_EVIDENCE)
        self._controller = NoGrantProjectionController()
        self._closed = False
        self._used = False

    def close(self) -> None:
        self._closed = True
        self._slot.close()

    async def validate(
        self,
        execution: ExecutionResult,
        context: RuntimeContext,
        approved: ApprovedActionPlan,
    ) -> M6NoGrantValidation:
        if self._closed:
            raise M6FoundationError(M6FoundationErrorCode.CLOSED_TURN)
        if self._used:
            raise M6FoundationError(M6FoundationErrorCode.ALREADY_VALIDATED)
        self._used = True  # burn before input admission; no second attempt after errors
        if not all(
            _valid_id(v)
            for v in (
                self.origin.request_id,
                self.origin.session_id,
                self.origin.identity_scope,
                self.origin.trace_id,
            )
        ):
            raise M6FoundationError(M6FoundationErrorCode.INVALID_ORIGIN)
        if (
            type(execution) is not ExecutionResult
            or type(context) is not RuntimeContext
            or type(approved) is not ApprovedActionPlan
        ):
            raise M6FoundationError(M6FoundationErrorCode.INVALID_INPUT)
        admission = admit_validation_input(
            execution,
            context,
            approved,
            expected_request_id=self.origin.request_id,
            expected_session_id=self.origin.session_id,
        )
        if admission.status is not AdmissionStatus.ADMITTED:
            raise M6FoundationError(M6FoundationErrorCode.ADMISSION_REJECTED)
        origin_binding = ValidationOriginBinding(
            expected_request_id=self.origin.request_id,
            expected_session_id=self.origin.session_id,
            expected_identity_scope=self.origin.identity_scope,
        )
        no_grant = self._slot.take_once()
        validated = self._controller.project(
            admission=admission,
            execution=execution,
            approved=approved,
            context=context,
            origin=origin_binding,
            no_grant=no_grant,
        )
        decision = evaluate_no_grant_downstream(
            validated=validated,
            context=NoGrantDownstreamContext(
                expected_request_id=self.origin.request_id,
                expected_execution_id=execution.execution_id,
                expected_validation_id=validated.validation_id,
                expected_identity_scope=self.origin.identity_scope,
                expected_session_id=self.origin.session_id,
                provenance_kind=NoGrantOriginClassification.NO_GRANT_INTERNAL,
            ),
        )
        return M6NoGrantValidation(validated, decision, self.origin)


class M6NoGrantFacadeFactory:
    """Factory deliberately has no cached slot or global turn state."""

    def open_turn(self, origin: TurnOriginSnapshot) -> M6NoGrantTurnHandle:
        return M6NoGrantTurnHandle(origin)
