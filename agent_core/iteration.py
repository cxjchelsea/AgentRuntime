"""Internal GA-01B Slice-0 correlation envelope; not a Canonical contract.

No execution, result validation, response generation, or state writes occur here.
"""

from __future__ import annotations

from dataclasses import dataclass

from runtime.contracts import (
    ApprovedActionPlan,
    ExecutionResult,
    InputSource,
    InputTriggerType,
    RuntimeContext,
    RuntimeInput,
)
from runtime.validation.slice_a import AdmissionStatus, admit_validation_input


class IterationCorrelationError(ValueError):
    """Fail closed on missing or contradictory run/iteration provenance."""


@dataclass(frozen=True, slots=True)
class AgentRunBinding:
    run_id: str
    original_request_id: str
    original_trace_id: str
    session_id: str
    subject_id: str
    identity_scope: str
    tenant_id: str | None
    domain_id: str
    domain_version: str
    binding_fingerprint: str

    @classmethod
    def from_input(
        cls,
        runtime_input: RuntimeInput,
        *,
        run_id: str,
        domain_id: str,
        domain_version: str,
        binding_fingerprint: str,
    ) -> AgentRunBinding:
        values = (
            run_id,
            runtime_input.request_id,
            runtime_input.trace_id,
            runtime_input.session_id,
            runtime_input.subject_id,
            runtime_input.identity_scope,
            domain_id,
            domain_version,
            binding_fingerprint,
        )
        if not all(value and value.strip() for value in values):
            raise IterationCorrelationError("run identity / domain binding missing")
        return cls(
            run_id=run_id,
            original_request_id=runtime_input.request_id,
            original_trace_id=runtime_input.trace_id,
            session_id=runtime_input.session_id,
            subject_id=runtime_input.subject_id,
            identity_scope=runtime_input.identity_scope,
            tenant_id=runtime_input.tenant_id,
            domain_id=domain_id,
            domain_version=domain_version,
            binding_fingerprint=binding_fingerprint,
        )

    def iteration_input(
        self, original_input: RuntimeInput, *, ordinal: int
    ) -> RuntimeInput:
        """Build an internal event without laundering tool text as user text."""
        if ordinal < 0:
            raise IterationCorrelationError("negative iteration")
        self.assert_identity(original_input)
        if ordinal == 0:
            if original_input.request_id != self.original_request_id:
                raise IterationCorrelationError("original request mismatch")
            if original_input.trace_id != self.original_trace_id:
                raise IterationCorrelationError("original trace mismatch")
            return original_input.model_copy(deep=True)

        payload = original_input.model_dump(mode="python")
        payload.update(
            request_id=f"{self.run_id}-iteration-{ordinal}",
            trace_id=f"{self.run_id}-trace-{ordinal}",
            source=InputSource.SYSTEM,
            trigger_type=InputTriggerType.SYSTEM_EVENT,
            # The original user goal remains a reference, not a forged new message.
            text=None,
            raw_text=None,
            segments=None,
            input_payload={
                "event_type": "AGENT_INTERNAL_ITERATION",
                "parent_request_id": self.original_request_id,
                "run_id": self.run_id,
                "iteration_ordinal": ordinal,
            },
        )
        return RuntimeInput.model_validate(payload)

    def assert_identity(self, runtime_input: RuntimeInput) -> None:
        if (
            runtime_input.session_id != self.session_id
            or runtime_input.subject_id != self.subject_id
            or runtime_input.identity_scope != self.identity_scope
            or runtime_input.tenant_id != self.tenant_id
        ):
            raise IterationCorrelationError("identity / session / tenant mismatch")


@dataclass(frozen=True, slots=True)
class IterationRef:
    run_id: str
    ordinal: int
    request_id: str
    trace_id: str
    domain_fingerprint: str

    @classmethod
    def from_input(
        cls, binding: AgentRunBinding, runtime_input: RuntimeInput, *, ordinal: int
    ) -> IterationRef:
        if ordinal < 0:
            raise IterationCorrelationError("negative iteration")
        expected = (
            (binding.original_request_id, binding.original_trace_id)
            if ordinal == 0
            else (
                f"{binding.run_id}-iteration-{ordinal}",
                f"{binding.run_id}-trace-{ordinal}",
            )
        )
        binding.assert_identity(runtime_input)
        if (runtime_input.request_id, runtime_input.trace_id) != expected:
            raise IterationCorrelationError("request / trace mismatch")
        return cls(
            binding.run_id,
            ordinal,
            runtime_input.request_id,
            runtime_input.trace_id,
            binding.binding_fingerprint,
        )


def assert_execution_correlation(
    *,
    binding: AgentRunBinding,
    iteration: IterationRef,
    runtime_context: RuntimeContext,
    approved: ApprovedActionPlan,
    execution: ExecutionResult,
) -> None:
    """Reuse M6 structural admission without manufacturing a validation grant."""
    if (
        iteration.run_id != binding.run_id
        or iteration.domain_fingerprint != binding.binding_fingerprint
        or runtime_context.identity_context.subject_id != binding.subject_id
        or runtime_context.identity_context.tenant_id != binding.tenant_id
        or runtime_context.session_context.session_id != binding.session_id
        or runtime_context.domain_extensions is None
        or runtime_context.domain_extensions.domain_id != binding.domain_id
        or runtime_context.identity_context.identity_scope != binding.identity_scope
        or approved.request_id != iteration.request_id
        or execution.request_id != iteration.request_id
        or execution.plan_id != approved.plan_id
        or execution.identity_scope != binding.identity_scope
    ):
        raise IterationCorrelationError("execution binding or identity mismatch")
    decision = admit_validation_input(
        execution,
        runtime_context,
        approved,
        expected_request_id=iteration.request_id,
        expected_session_id=binding.session_id,
    )
    if decision.status is not AdmissionStatus.ADMITTED:
        raise IterationCorrelationError(
            "M6 structural admission rejected: "
            + ",".join(reason.value for reason in decision.reasons)
        )
