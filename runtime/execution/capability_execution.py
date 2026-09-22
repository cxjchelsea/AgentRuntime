"""M5-IU4 exact capability execution.

This module executes only the capability owner already frozen by M4 and exact-resolved
by IU3. It never replans, re-resolves Registry entries, retries, resumes Workflows,
manages locks/idempotency, aggregates canonical ExecutionResult, or invokes M6.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from runtime.contracts import ApprovedActionPlan
from runtime.contracts.execution import ExecutionContext
from runtime.contracts.planning import ActionStep
from runtime.execution.capability_resolution import (
    CapabilityExecutionOwner,
    CapabilityKind,
    ResolvedCapability,
    ResolvedStepCapabilities,
)
from runtime.execution.foundation import StepLifecycleSnapshot
from runtime.execution.invocation import (
    ApprovedToolInvoker,
    CapabilityInvocationIdentifierFactory,
    PhysicalToolAttemptExecutor,
    ToolAttemptObservation,
    ToolInputValidator,
    ToolInvocationJournalEntry,
    ToolInvocationJournalReader,
    ToolOutputValidator,
    ToolPayloadValidationDecision,
    ToolPayloadValidationStatus,
)
from runtime.execution.models import (
    M5SkillResult,
    M5ToolResult,
    M5WorkflowResult,
    SkillExecutionRequest,
    SkillExecutionStatus,
    StepExecutionStatus,
    ToolExecutionStatus,
    ToolInvocationRequest,
    WorkflowExecutionRequest,
    WorkflowExecutionStatus,
)
from runtime.execution.permission import (
    ExecutionPermissionContext,
    ExecutionPermissionContextProvider,
    ExecutionPermissionEvaluator,
    PermissionDecisionStatus,
)
from runtime.execution.protocols import (
    SkillImplementation,
    ToolImplementation,
    WorkflowImplementation,
)
from runtime.execution.reliability import (
    IdempotencyMode,
    ReliabilityCapabilityKind,
    ReplaySafetyContext,
    ReplaySafetyDecision,
    ReplaySafetyStatus,
    ResolvedReliabilityPolicy,
    RetryDecision,
    RetryDecisionContext,
    RetryDecisionStatus,
    RetryTriggerStatus,
    TimeoutRunStatus,
)
from runtime.execution.reliability_boundary import (
    IdempotencyPreflightDecision,
    IdempotencyPreflightStatus,
    ToolOperationCorrelationDecision,
    ToolOperationCorrelationStatus,
    ToolOperationOccurrenceDecision,
    ToolOperationOccurrenceStatus,
)
from runtime.execution.reliability_runtime import ToolReliabilityRuntime
from runtime.execution.stores import (
    IdempotencyCompletionDecision,
    IdempotencyCompletionStatus,
    IdempotencyRecord,
    IdempotencyStatus,
)
from runtime.registries.definitions import ToolDefinition


class CapabilityExecutionStatus(str, Enum):
    EXECUTED = "EXECUTED"
    WAITING = "WAITING"
    NO_EXTERNAL_EXECUTION = "NO_EXTERNAL_EXECUTION"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class StepCapabilityExecutionOutcome:
    """IU4 execution observation; not canonical ExecutionResult and not M6 truth."""

    step_id: str
    step_execution_id: str
    status: CapabilityExecutionStatus
    execution_owner: CapabilityExecutionOwner
    reason_codes: tuple[str, ...]
    owner_capability_id: str | None = None
    owner_capability_version: str | None = None
    skill_result: M5SkillResult | None = None
    workflow_result: M5WorkflowResult | None = None
    tool_results: tuple[M5ToolResult, ...] = ()
    tool_journal: tuple[ToolInvocationJournalEntry, ...] = ()

    def __post_init__(self) -> None:
        if not self.step_id.strip() or not self.step_execution_id.strip():
            raise ValueError("step execution identifiers must not be blank")
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        if (self.owner_capability_id is None) != (
            self.owner_capability_version is None
        ):
            raise ValueError("owner capability id/version must be present together")
        if self.skill_result is not None and self.workflow_result is not None:
            raise ValueError(
                "one IU4 outcome cannot carry both Skill and Workflow result"
            )
        if self.tool_results != tuple(entry.result for entry in self.tool_journal):
            raise ValueError("tool_results must exactly match the Core Tool journal")
        if self.execution_owner is CapabilityExecutionOwner.NONE and (
            self.owner_capability_id is not None
            or self.skill_result is not None
            or self.workflow_result is not None
            or self.tool_results
            or self.tool_journal
        ):
            raise ValueError("NONE execution_owner cannot carry execution results")
        if (
            self.status is CapabilityExecutionStatus.NO_EXTERNAL_EXECUTION
            and self.execution_owner is not CapabilityExecutionOwner.NONE
        ):
            raise ValueError("NO_EXTERNAL_EXECUTION requires NONE execution_owner")
        if self.status is CapabilityExecutionStatus.WAITING and (
            self.execution_owner is not CapabilityExecutionOwner.WORKFLOW
            or self.workflow_result is None
            or self.workflow_result.status is not WorkflowExecutionStatus.WAITING
        ):
            raise ValueError("WAITING requires a WAITING Workflow result")


class ToolInvocationBoundaryError(RuntimeError):
    """Internal signal when the Core invocation boundary cannot create a safe call."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class CoreApprovedToolInvoker(
    ApprovedToolInvoker,
    ToolInvocationJournalReader,
    PhysicalToolAttemptExecutor,
):
    """Invoke only IU3 exact-resolved Tools through Core-owned gates."""

    def __init__(
        self,
        *,
        resolved_tools: tuple[ResolvedCapability, ...],
        execution_context: ExecutionContext,
        step_execution_id: str,
        permission_context_provider: ExecutionPermissionContextProvider,
        permission_evaluator: ExecutionPermissionEvaluator,
        input_validator: ToolInputValidator,
        output_validator: ToolOutputValidator,
        identifier_factory: CapabilityInvocationIdentifierFactory,
        step_id: str | None = None,
        step_attempt_number: int = 1,
        prior_attempt_journal: tuple[ToolInvocationJournalEntry, ...] = (),
        reliability_runtime: ToolReliabilityRuntime | None = None,
    ) -> None:
        if not step_execution_id.strip():
            raise ValueError("step_execution_id must not be blank")
        if step_attempt_number < 1:
            raise ValueError("step_attempt_number must be >= 1")
        if reliability_runtime is not None and (
            step_id is None or not step_id.strip()
        ):
            raise ValueError("reliable Tool invocation requires non-blank step_id")
        self._execution_context = execution_context
        self._step_execution_id = step_execution_id
        self._step_id = step_id
        self._step_attempt_number = step_attempt_number
        self._prior_attempt_journal = prior_attempt_journal
        self._reliability_runtime = reliability_runtime
        self._permission_context_provider = permission_context_provider
        self._permission_evaluator = permission_evaluator
        self._input_validator = input_validator
        self._output_validator = output_validator
        self._identifier_factory = identifier_factory
        self._resolved_tools = self._index_tools(resolved_tools)
        self._journal: list[ToolInvocationJournalEntry] = []
        self._boundary_faults: list[str] = []
        self._issued_tool_call_ids: set[str] = set()

    async def invoke(
        self,
        *,
        tool_id: str,
        input_payload: dict[str, Any],
    ) -> M5ToolResult:
        if self._boundary_faults:
            raise ToolInvocationBoundaryError(
                self._boundary_faults[0],
                "Tool invocation boundary is already fail-closed for this step",
            )
        if not isinstance(tool_id, str) or not tool_id.strip():
            self._record_fault("TOOL_ID_INVALID")
            raise ToolInvocationBoundaryError(
                "TOOL_ID_INVALID",
                "Tool invocation requires non-blank tool_id",
            )

        if self._reliability_runtime is not None:
            return await self._invoke_with_reliability(
                tool_id=tool_id,
                input_payload=input_payload,
            )

        tool_call_id = self._new_tool_call_id(tool_id)
        attempt = await self.execute_physical_attempt(
            logical_tool_call_id=tool_call_id,
            tool_id=tool_id,
            input_payload=input_payload,
            physical_attempt=1,
            idempotency_key=None,
            operation_key=None,
            operation_fingerprint=None,
        )
        return attempt.result

    async def execute_physical_attempt(
        self,
        *,
        logical_tool_call_id: str,
        tool_id: str,
        input_payload: dict[str, Any],
        physical_attempt: int,
        idempotency_key: str | None,
        operation_key: str | None,
        operation_fingerprint: str | None,
    ) -> ToolAttemptObservation:
        if self._boundary_faults:
            raise ToolInvocationBoundaryError(
                self._boundary_faults[0],
                "Tool invocation boundary is already fail-closed for this step",
            )
        if (
            not isinstance(logical_tool_call_id, str)
            or not logical_tool_call_id.strip()
        ):
            self._record_fault("TOOL_CALL_ID_INVALID")
            raise ToolInvocationBoundaryError(
                "TOOL_CALL_ID_INVALID",
                "physical Tool attempt requires logical_tool_call_id",
            )
        if not isinstance(tool_id, str) or not tool_id.strip():
            self._record_fault("TOOL_ID_INVALID")
            raise ToolInvocationBoundaryError(
                "TOOL_ID_INVALID",
                "physical Tool attempt requires non-blank tool_id",
            )
        if physical_attempt < 1:
            self._record_fault("TOOL_ATTEMPT_INVALID")
            raise ToolInvocationBoundaryError(
                "TOOL_ATTEMPT_INVALID",
                "physical Tool attempt must be >= 1",
            )
        if idempotency_key is not None and not idempotency_key.strip():
            self._record_fault("IDEMPOTENCY_KEY_INVALID")
            raise ToolInvocationBoundaryError(
                "IDEMPOTENCY_KEY_INVALID",
                "idempotency_key must not be blank when present",
            )
        if operation_key is not None and not operation_key.strip():
            self._record_fault("TOOL_OPERATION_KEY_INVALID")
            raise ToolInvocationBoundaryError(
                "TOOL_OPERATION_KEY_INVALID",
                "operation_key must not be blank when present",
            )
        if operation_fingerprint is not None and not operation_fingerprint.strip():
            self._record_fault("TOOL_OPERATION_FINGERPRINT_INVALID")
            raise ToolInvocationBoundaryError(
                "TOOL_OPERATION_FINGERPRINT_INVALID",
                "operation_fingerprint must not be blank when present",
            )

        existing = self._journal_entry(logical_tool_call_id)
        if existing is None:
            if logical_tool_call_id in self._issued_tool_call_ids:
                self._record_fault("TOOL_CALL_ID_COLLISION")
                raise ToolInvocationBoundaryError(
                    "TOOL_CALL_ID_COLLISION",
                    "logical Tool call id is already issued",
                )
            if physical_attempt != 1:
                self._record_fault("TOOL_ATTEMPT_SEQUENCE_INVALID")
                raise ToolInvocationBoundaryError(
                    "TOOL_ATTEMPT_SEQUENCE_INVALID",
                    "first local physical Tool attempt must be attempt 1",
                )
            self._issued_tool_call_ids.add(logical_tool_call_id)
        else:
            expected_attempt = len(existing.attempts) + 1
            if not existing.attempts:
                expected_attempt = existing.result.attempt + 1
            if physical_attempt != expected_attempt:
                self._record_fault("TOOL_ATTEMPT_SEQUENCE_INVALID")
                raise ToolInvocationBoundaryError(
                    "TOOL_ATTEMPT_SEQUENCE_INVALID",
                    "physical Tool attempts must be contiguous",
                )
            if (
                existing.tool_id != tool_id
                or existing.operation_key != operation_key
                or existing.operation_fingerprint != operation_fingerprint
                or existing.idempotency_key != idempotency_key
            ):
                self._record_fault("TOOL_ATTEMPT_IDENTITY_MISMATCH")
                raise ToolInvocationBoundaryError(
                    "TOOL_ATTEMPT_IDENTITY_MISMATCH",
                    "physical Tool attempt changed logical operation identity",
                )

        resolved = self._resolved_tools.get(tool_id)
        if resolved is None:
            self._record_fault("TOOL_NOT_APPROVED_FOR_STEP")
            raise ToolInvocationBoundaryError(
                "TOOL_NOT_APPROVED_FOR_STEP",
                "Tool is not approved/resolved for the current step",
            )

        if not isinstance(input_payload, dict):
            result = self._generated_result(
                tool_call_id=logical_tool_call_id,
                tool_id=tool_id,
                status=ToolExecutionStatus.REJECTED,
                error_code="INVALID_PARAMETER",
                reason_codes=("TOOL_INPUT_PAYLOAD_NOT_OBJECT",),
                attempt=physical_attempt,
            )
            return self._append_journal_attempt(
                resolved=resolved,
                result=result,
                permission_status=None,
                input_status=ToolPayloadValidationStatus.INVALID,
                output_status=None,
                idempotency_key=idempotency_key,
                operation_key=operation_key,
                operation_fingerprint=operation_fingerprint,
            )

        if (
            resolved.kind is not CapabilityKind.TOOL
            or not isinstance(resolved.definition, ToolDefinition)
            or not isinstance(resolved.implementation_ref, ToolImplementation)
        ):
            self._record_fault("APPROVED_TOOL_BINDING_INVALID")
            raise ToolInvocationBoundaryError(
                "APPROVED_TOOL_BINDING_INVALID",
                "IU3 resolved Tool binding is internally inconsistent",
            )

        definition = resolved.definition

        input_decision = self._validate_input(definition, input_payload)
        if input_decision.status is ToolPayloadValidationStatus.INVALID:
            result = self._generated_result(
                tool_call_id=logical_tool_call_id,
                tool_id=tool_id,
                status=ToolExecutionStatus.REJECTED,
                error_code="INVALID_PARAMETER",
                reason_codes=input_decision.reason_codes,
                attempt=physical_attempt,
            )
            return self._append_journal_attempt(
                resolved=resolved,
                result=result,
                permission_status=None,
                input_status=input_decision.status,
                output_status=None,
                idempotency_key=idempotency_key,
                operation_key=operation_key,
                operation_fingerprint=operation_fingerprint,
            )
        if input_decision.status is ToolPayloadValidationStatus.UNKNOWN:
            result = self._generated_result(
                tool_call_id=logical_tool_call_id,
                tool_id=tool_id,
                status=ToolExecutionStatus.UNKNOWN,
                error_code="TOOL_INPUT_VALIDATION_UNKNOWN",
                reason_codes=input_decision.reason_codes,
                attempt=physical_attempt,
            )
            return self._append_journal_attempt(
                resolved=resolved,
                result=result,
                permission_status=None,
                input_status=input_decision.status,
                output_status=None,
                idempotency_key=idempotency_key,
                operation_key=operation_key,
                operation_fingerprint=operation_fingerprint,
            )

        permission_status = await self._permission_status(definition)
        if permission_status is PermissionDecisionStatus.DENIED:
            result = self._generated_result(
                tool_call_id=logical_tool_call_id,
                tool_id=tool_id,
                status=ToolExecutionStatus.REJECTED,
                error_code="PERMISSION_DENIED",
                attempt=physical_attempt,
            )
            return self._append_journal_attempt(
                resolved=resolved,
                result=result,
                permission_status=permission_status,
                input_status=input_decision.status,
                output_status=None,
                idempotency_key=idempotency_key,
                operation_key=operation_key,
                operation_fingerprint=operation_fingerprint,
            )
        if permission_status is PermissionDecisionStatus.UNKNOWN:
            result = self._generated_result(
                tool_call_id=logical_tool_call_id,
                tool_id=tool_id,
                status=ToolExecutionStatus.UNKNOWN,
                error_code="TOOL_PERMISSION_UNKNOWN",
                attempt=physical_attempt,
            )
            return self._append_journal_attempt(
                resolved=resolved,
                result=result,
                permission_status=permission_status,
                input_status=input_decision.status,
                output_status=None,
                idempotency_key=idempotency_key,
                operation_key=operation_key,
                operation_fingerprint=operation_fingerprint,
            )

        request = ToolInvocationRequest(
            tool_call_id=logical_tool_call_id,
            tool_id=tool_id,
            input_payload=dict(input_payload),
            attempt=physical_attempt,
            idempotency_key=idempotency_key,
        )

        try:
            raw_result = await resolved.implementation_ref.invoke(
                request,
                self._execution_context,
            )
        except Exception:  # noqa: BLE001
            result = self._generated_result(
                tool_call_id=logical_tool_call_id,
                tool_id=tool_id,
                status=ToolExecutionStatus.UNKNOWN,
                error_code="TOOL_EXECUTION_EXCEPTION",
                attempt=physical_attempt,
            )
            return self._append_journal_attempt(
                resolved=resolved,
                result=result,
                permission_status=permission_status,
                input_status=input_decision.status,
                output_status=None,
                idempotency_key=idempotency_key,
                operation_key=operation_key,
                operation_fingerprint=operation_fingerprint,
            )

        if not isinstance(raw_result, M5ToolResult) or not isinstance(
            raw_result.status, ToolExecutionStatus
        ):
            result = self._generated_result(
                tool_call_id=logical_tool_call_id,
                tool_id=tool_id,
                status=ToolExecutionStatus.UNKNOWN,
                error_code="TOOL_RESULT_INVALID",
                attempt=physical_attempt,
            )
            return self._append_journal_attempt(
                resolved=resolved,
                result=result,
                permission_status=permission_status,
                input_status=input_decision.status,
                output_status=None,
                idempotency_key=idempotency_key,
                operation_key=operation_key,
                operation_fingerprint=operation_fingerprint,
            )

        if (
            raw_result.tool_call_id != logical_tool_call_id
            or raw_result.tool_id != tool_id
            or raw_result.attempt != physical_attempt
        ):
            result = self._generated_result(
                tool_call_id=logical_tool_call_id,
                tool_id=tool_id,
                status=ToolExecutionStatus.UNKNOWN,
                error_code="TOOL_RESULT_IDENTITY_MISMATCH",
                attempt=physical_attempt,
            )
            return self._append_journal_attempt(
                resolved=resolved,
                result=result,
                permission_status=permission_status,
                input_status=input_decision.status,
                output_status=None,
                idempotency_key=idempotency_key,
                operation_key=operation_key,
                operation_fingerprint=operation_fingerprint,
            )

        if raw_result.status is not ToolExecutionStatus.SUCCESS:
            return self._append_journal_attempt(
                resolved=resolved,
                result=raw_result,
                raw_result=raw_result,
                permission_status=permission_status,
                input_status=input_decision.status,
                output_status=None,
                idempotency_key=idempotency_key,
                operation_key=operation_key,
                operation_fingerprint=operation_fingerprint,
            )

        output_decision = self._validate_output(definition, raw_result)
        if output_decision.status is ToolPayloadValidationStatus.VALID:
            final_result = raw_result
        elif output_decision.status is ToolPayloadValidationStatus.INVALID:
            final_result = self._generated_result(
                tool_call_id=logical_tool_call_id,
                tool_id=tool_id,
                status=ToolExecutionStatus.UNKNOWN,
                error_code="TOOL_INVALID_OUTPUT",
                reason_codes=output_decision.reason_codes,
                attempt=physical_attempt,
            )
        else:
            final_result = self._generated_result(
                tool_call_id=logical_tool_call_id,
                tool_id=tool_id,
                status=ToolExecutionStatus.UNKNOWN,
                error_code="TOOL_OUTPUT_VALIDATION_UNKNOWN",
                reason_codes=output_decision.reason_codes,
                attempt=physical_attempt,
            )

        return self._append_journal_attempt(
            resolved=resolved,
            result=final_result,
            raw_result=raw_result,
            permission_status=permission_status,
            input_status=input_decision.status,
            output_status=output_decision.status,
            idempotency_key=idempotency_key,
            operation_key=operation_key,
            operation_fingerprint=operation_fingerprint,
        )

    def entries(self) -> tuple[ToolInvocationJournalEntry, ...]:
        return tuple(self._journal)

    @property
    def boundary_faults(self) -> tuple[str, ...]:
        return tuple(self._boundary_faults)

    @staticmethod
    def _index_tools(
        resolved_tools: tuple[ResolvedCapability, ...],
    ) -> dict[str, ResolvedCapability]:
        indexed: dict[str, ResolvedCapability] = {}
        for resolved in resolved_tools:
            if (
                resolved.kind is not CapabilityKind.TOOL
                or not isinstance(resolved.capability_id, str)
                or not resolved.capability_id.strip()
                or not isinstance(resolved.version, str)
                or not resolved.version.strip()
                or not isinstance(resolved.definition, ToolDefinition)
                or not isinstance(resolved.implementation_ref, ToolImplementation)
                or resolved.definition.tool_id != resolved.capability_id
                or resolved.definition.version != resolved.version
            ):
                raise ValueError("resolved Tool binding is internally inconsistent")
            if resolved.capability_id in indexed:
                raise ValueError("resolved Tool ids must be unique for one step")
            indexed[resolved.capability_id] = resolved
        return indexed

    def _new_tool_call_id(self, tool_id: str) -> str:
        try:
            value = self._identifier_factory.new_tool_call_id(
                step_execution_id=self._step_execution_id,
                tool_id=tool_id,
            )
        except Exception as exc:
            self._record_fault("TOOL_CALL_ID_UNAVAILABLE")
            raise ToolInvocationBoundaryError(
                "TOOL_CALL_ID_UNAVAILABLE",
                "Tool call id factory failed",
            ) from exc
        if not isinstance(value, str) or not value.strip():
            self._record_fault("TOOL_CALL_ID_UNAVAILABLE")
            raise ToolInvocationBoundaryError(
                "TOOL_CALL_ID_UNAVAILABLE",
                "Tool call id factory returned invalid id",
            )
        if value in self._issued_tool_call_ids:
            self._record_fault("TOOL_CALL_ID_COLLISION")
            raise ToolInvocationBoundaryError(
                "TOOL_CALL_ID_COLLISION",
                "Tool call id factory returned a duplicate id",
            )
        return value

    def _validate_input(
        self,
        definition: ToolDefinition,
        input_payload: dict[str, Any],
    ) -> ToolPayloadValidationDecision:
        try:
            decision = self._input_validator.validate(definition, input_payload)
        except Exception:  # noqa: BLE001
            return ToolPayloadValidationDecision(
                status=ToolPayloadValidationStatus.UNKNOWN,
                reason_codes=("TOOL_INPUT_VALIDATOR_FAILURE",),
            )
        if not isinstance(decision, ToolPayloadValidationDecision) or not isinstance(
            decision.status, ToolPayloadValidationStatus
        ):
            return ToolPayloadValidationDecision(
                status=ToolPayloadValidationStatus.UNKNOWN,
                reason_codes=("TOOL_INPUT_VALIDATOR_INVALID_RESULT",),
            )
        return decision

    def _validate_output(
        self,
        definition: ToolDefinition,
        result: M5ToolResult,
    ) -> ToolPayloadValidationDecision:
        try:
            decision = self._output_validator.validate(definition, result)
        except Exception:  # noqa: BLE001
            return ToolPayloadValidationDecision(
                status=ToolPayloadValidationStatus.UNKNOWN,
                reason_codes=("TOOL_OUTPUT_VALIDATOR_FAILURE",),
            )
        if not isinstance(decision, ToolPayloadValidationDecision) or not isinstance(
            decision.status, ToolPayloadValidationStatus
        ):
            return ToolPayloadValidationDecision(
                status=ToolPayloadValidationStatus.UNKNOWN,
                reason_codes=("TOOL_OUTPUT_VALIDATOR_INVALID_RESULT",),
            )
        return decision

    async def _permission_status(
        self,
        definition: ToolDefinition,
    ) -> PermissionDecisionStatus:
        if not definition.required_permissions:
            return PermissionDecisionStatus.ALLOWED

        try:
            context = await self._permission_context_provider.build(
                self._execution_context
            )
        except Exception:  # noqa: BLE001
            return PermissionDecisionStatus.UNKNOWN

        if not isinstance(context, ExecutionPermissionContext):
            return PermissionDecisionStatus.UNKNOWN
        if not self._permission_context_matches(context):
            return PermissionDecisionStatus.UNKNOWN

        try:
            decision = self._permission_evaluator.evaluate(definition, context)
        except Exception:  # noqa: BLE001
            return PermissionDecisionStatus.UNKNOWN
        if not hasattr(decision, "status") or not isinstance(
            decision.status, PermissionDecisionStatus
        ):
            return PermissionDecisionStatus.UNKNOWN
        return decision.status

    def _permission_context_matches(
        self,
        context: ExecutionPermissionContext,
    ) -> bool:
        return (
            context.execution_id == self._execution_context.execution_id
            and context.identity_scope == self._execution_context.identity_scope
        )

    def _journal_entry(
        self,
        logical_tool_call_id: str,
    ) -> ToolInvocationJournalEntry | None:
        for entry in self._journal:
            if entry.tool_call_id == logical_tool_call_id:
                return entry
        return None

    def _append_journal_attempt(
        self,
        *,
        resolved: ResolvedCapability,
        result: M5ToolResult,
        permission_status: PermissionDecisionStatus | None,
        input_status: ToolPayloadValidationStatus | None,
        output_status: ToolPayloadValidationStatus | None,
        idempotency_key: str | None,
        operation_key: str | None,
        operation_fingerprint: str | None,
        raw_result: M5ToolResult | None = None,
    ) -> ToolAttemptObservation:
        attempt_observation = ToolAttemptObservation(
            logical_tool_call_id=result.tool_call_id,
            tool_id=result.tool_id,
            tool_version=resolved.version,
            physical_attempt=result.attempt,
            result=result,
            operation_key=operation_key,
            operation_fingerprint=operation_fingerprint,
            idempotency_key=idempotency_key,
            raw_result=raw_result,
            permission_status=permission_status,
            input_validation_status=input_status,
            output_validation_status=output_status,
            started_at=result.started_at,
            finished_at=result.finished_at,
        )

        existing_index: int | None = None
        existing: ToolInvocationJournalEntry | None = None
        for index, entry in enumerate(self._journal):
            if entry.tool_call_id == result.tool_call_id:
                existing_index = index
                existing = entry
                break

        if existing is None:
            if result.attempt != 1:
                self._record_fault("TOOL_ATTEMPT_JOURNAL_MISMATCH")
                raise ToolInvocationBoundaryError(
                    "TOOL_ATTEMPT_JOURNAL_MISMATCH",
                    "new logical Tool journal must start at attempt 1",
                )
            self._journal.append(
                ToolInvocationJournalEntry(
                    tool_call_id=result.tool_call_id,
                    tool_id=result.tool_id,
                    tool_version=resolved.version,
                    result=result,
                    raw_result=raw_result,
                    permission_status=permission_status,
                    input_validation_status=input_status,
                    output_validation_status=output_status,
                    operation_key=operation_key,
                    operation_fingerprint=operation_fingerprint,
                    idempotency_key=idempotency_key,
                    attempts=(attempt_observation,),
                )
            )
            return attempt_observation

        expected_attempt = len(existing.attempts) + 1
        if (
            existing_index is None
            or existing.tool_id != result.tool_id
            or existing.tool_version != resolved.version
            or existing.operation_key != operation_key
            or existing.operation_fingerprint != operation_fingerprint
            or existing.idempotency_key != idempotency_key
            or result.attempt != expected_attempt
        ):
            self._record_fault("TOOL_ATTEMPT_JOURNAL_MISMATCH")
            raise ToolInvocationBoundaryError(
                "TOOL_ATTEMPT_JOURNAL_MISMATCH",
                "physical Tool attempt is inconsistent with logical Tool journal",
            )

        self._journal[existing_index] = replace(
            existing,
            result=result,
            raw_result=raw_result,
            permission_status=permission_status,
            input_validation_status=input_status,
            output_validation_status=output_status,
            attempts=(*existing.attempts, attempt_observation),
        )
        return attempt_observation

    def _record_fault(self, reason_code: str) -> None:
        if reason_code not in self._boundary_faults:
            self._boundary_faults.append(reason_code)

    @staticmethod
    def _generated_result(
        *,
        tool_call_id: str,
        tool_id: str,
        status: ToolExecutionStatus,
        error_code: str,
        reason_codes: tuple[str, ...] = (),
        attempt: int = 1,
    ) -> M5ToolResult:
        metadata: dict[str, Any] = {}
        if reason_codes:
            metadata["reason_codes"] = list(reason_codes)
        return M5ToolResult(
            tool_call_id=tool_call_id,
            tool_id=tool_id,
            status=status,
            error_code=error_code,
            attempt=attempt,
            metadata=metadata,
        )


class StepCapabilityExecutor:
    """Execute one IU3-resolved owner through the frozen IU4 Core boundary."""

    def __init__(
        self,
        *,
        permission_context_provider: ExecutionPermissionContextProvider,
        permission_evaluator: ExecutionPermissionEvaluator,
        input_validator: ToolInputValidator,
        output_validator: ToolOutputValidator,
        identifier_factory: CapabilityInvocationIdentifierFactory,
    ) -> None:
        self._permission_context_provider = permission_context_provider
        self._permission_evaluator = permission_evaluator
        self._input_validator = input_validator
        self._output_validator = output_validator
        self._identifier_factory = identifier_factory

    async def execute(
        self,
        *,
        approved_plan: ApprovedActionPlan,
        step: ActionStep,
        step_snapshot: StepLifecycleSnapshot,
        resolved: ResolvedStepCapabilities,
        execution_context: ExecutionContext,
    ) -> StepCapabilityExecutionOutcome:
        authority_error = self._validate_authority(
            approved_plan=approved_plan,
            step=step,
            step_snapshot=step_snapshot,
            resolved=resolved,
            execution_context=execution_context,
        )
        if authority_error is not None:
            return self._outcome(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                status=CapabilityExecutionStatus.BLOCKED,
                reason_codes=(authority_error,),
            )

        if resolved.execution_owner is CapabilityExecutionOwner.NONE:
            return self._outcome(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                status=CapabilityExecutionStatus.NO_EXTERNAL_EXECUTION,
                reason_codes=("NO_EXTERNAL_EXECUTION",),
            )

        try:
            tool_invoker = CoreApprovedToolInvoker(
                resolved_tools=resolved.tools,
                execution_context=execution_context,
                step_execution_id=step_snapshot.step_execution_id,
                permission_context_provider=self._permission_context_provider,
                permission_evaluator=self._permission_evaluator,
                input_validator=self._input_validator,
                output_validator=self._output_validator,
                identifier_factory=self._identifier_factory,
            )
        except (TypeError, ValueError):
            return self._outcome(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                status=CapabilityExecutionStatus.UNKNOWN,
                reason_codes=("TOOL_GATEWAY_CONSTRUCTION_FAILED",),
            )

        if resolved.execution_owner is CapabilityExecutionOwner.SKILL:
            return await self._execute_skill(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                execution_context=execution_context,
                tool_invoker=tool_invoker,
            )

        return await self._execute_workflow(
            step=step,
            step_snapshot=step_snapshot,
            resolved=resolved,
            execution_context=execution_context,
            tool_invoker=tool_invoker,
        )

    async def _execute_skill(
        self,
        *,
        step: ActionStep,
        step_snapshot: StepLifecycleSnapshot,
        resolved: ResolvedStepCapabilities,
        execution_context: ExecutionContext,
        tool_invoker: CoreApprovedToolInvoker,
    ) -> StepCapabilityExecutionOutcome:
        skill = resolved.skill
        if (
            skill is None
            or skill.kind is not CapabilityKind.SKILL
            or not isinstance(skill.implementation_ref, SkillImplementation)
        ):
            return self._outcome(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                status=CapabilityExecutionStatus.BLOCKED,
                reason_codes=("SKILL_OWNER_BINDING_INVALID",),
            )

        request = SkillExecutionRequest(
            step_execution_id=step_snapshot.step_execution_id,
            step_id=step.step_id,
            action=step.action,
            skill_id=skill.capability_id,
            parameters=dict(step.parameters or {}),
        )

        try:
            result = await skill.implementation_ref.execute(
                request,
                execution_context,
                tool_invoker,
            )
        except Exception:  # noqa: BLE001
            reason_codes = self._exception_reasons(
                tool_invoker,
                default="SKILL_EXECUTION_EXCEPTION",
            )
            return self._outcome(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                status=self._fault_status(tool_invoker),
                reason_codes=reason_codes,
                tool_results=self._journal_results(tool_invoker),
                tool_journal=tool_invoker.entries(),
            )

        if (
            not isinstance(result, M5SkillResult)
            or not isinstance(result.status, SkillExecutionStatus)
            or result.skill_id != skill.capability_id
        ):
            return self._outcome(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                status=CapabilityExecutionStatus.UNKNOWN,
                reason_codes=("SKILL_RESULT_INVALID",),
                tool_results=self._journal_results(tool_invoker),
                tool_journal=tool_invoker.entries(),
            )

        journal_results = self._journal_results(tool_invoker)
        boundary_outcome = self._boundary_outcome(
            step=step,
            step_snapshot=step_snapshot,
            resolved=resolved,
            tool_invoker=tool_invoker,
            tool_results=journal_results,
            skill_result=result,
        )
        if boundary_outcome is not None:
            return boundary_outcome

        if result.tool_results and result.tool_results != journal_results:
            return self._outcome(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                status=CapabilityExecutionStatus.UNKNOWN,
                reason_codes=("CAPABILITY_RESULT_TOOL_TRACE_MISMATCH",),
                skill_result=result,
                tool_results=journal_results,
                tool_journal=tool_invoker.entries(),
            )

        normalized = replace(result, tool_results=journal_results)
        if any(item.status is ToolExecutionStatus.UNKNOWN for item in journal_results):
            return self._outcome(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                status=CapabilityExecutionStatus.UNKNOWN,
                reason_codes=("TOOL_EXECUTION_UNKNOWN",),
                skill_result=normalized,
                tool_results=journal_results,
                tool_journal=tool_invoker.entries(),
            )

        return self._outcome(
            step=step,
            step_snapshot=step_snapshot,
            resolved=resolved,
            status=CapabilityExecutionStatus.EXECUTED,
            reason_codes=("SKILL_EXECUTED",),
            skill_result=normalized,
            tool_results=journal_results,
            tool_journal=tool_invoker.entries(),
        )

    async def _execute_workflow(
        self,
        *,
        step: ActionStep,
        step_snapshot: StepLifecycleSnapshot,
        resolved: ResolvedStepCapabilities,
        execution_context: ExecutionContext,
        tool_invoker: CoreApprovedToolInvoker,
    ) -> StepCapabilityExecutionOutcome:
        workflow = resolved.workflow
        if (
            workflow is None
            or workflow.kind is not CapabilityKind.WORKFLOW
            or not isinstance(workflow.implementation_ref, WorkflowImplementation)
        ):
            return self._outcome(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                status=CapabilityExecutionStatus.BLOCKED,
                reason_codes=("WORKFLOW_OWNER_BINDING_INVALID",),
            )

        try:
            workflow_instance_id = self._identifier_factory.new_workflow_instance_id(
                step_execution_id=step_snapshot.step_execution_id,
                workflow_id=workflow.capability_id,
            )
        except Exception:  # noqa: BLE001
            return self._outcome(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                status=CapabilityExecutionStatus.UNKNOWN,
                reason_codes=("WORKFLOW_INSTANCE_ID_UNAVAILABLE",),
            )
        if (
            not isinstance(workflow_instance_id, str)
            or not workflow_instance_id.strip()
        ):
            return self._outcome(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                status=CapabilityExecutionStatus.UNKNOWN,
                reason_codes=("WORKFLOW_INSTANCE_ID_UNAVAILABLE",),
            )

        request = WorkflowExecutionRequest(
            workflow_instance_id=workflow_instance_id,
            workflow_id=workflow.capability_id,
            event=None,
            inputs=dict(step.parameters or {}),
        )

        try:
            result = await workflow.implementation_ref.start(
                request,
                execution_context,
                tool_invoker,
            )
        except Exception:  # noqa: BLE001
            reason_codes = self._exception_reasons(
                tool_invoker,
                default="WORKFLOW_EXECUTION_EXCEPTION",
            )
            return self._outcome(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                status=self._fault_status(tool_invoker),
                reason_codes=reason_codes,
                tool_results=self._journal_results(tool_invoker),
                tool_journal=tool_invoker.entries(),
            )

        if (
            not isinstance(result, M5WorkflowResult)
            or not isinstance(result.status, WorkflowExecutionStatus)
            or result.workflow_id != workflow.capability_id
            or result.workflow_instance_id != workflow_instance_id
        ):
            return self._outcome(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                status=CapabilityExecutionStatus.UNKNOWN,
                reason_codes=("WORKFLOW_RESULT_INVALID",),
                tool_results=self._journal_results(tool_invoker),
                tool_journal=tool_invoker.entries(),
            )

        journal_results = self._journal_results(tool_invoker)
        boundary_outcome = self._boundary_outcome(
            step=step,
            step_snapshot=step_snapshot,
            resolved=resolved,
            tool_invoker=tool_invoker,
            tool_results=journal_results,
            workflow_result=result,
        )
        if boundary_outcome is not None:
            return boundary_outcome

        if result.tool_results and result.tool_results != journal_results:
            return self._outcome(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                status=CapabilityExecutionStatus.UNKNOWN,
                reason_codes=("CAPABILITY_RESULT_TOOL_TRACE_MISMATCH",),
                workflow_result=result,
                tool_results=journal_results,
                tool_journal=tool_invoker.entries(),
            )

        normalized = replace(result, tool_results=journal_results)
        if any(item.status is ToolExecutionStatus.UNKNOWN for item in journal_results):
            return self._outcome(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                status=CapabilityExecutionStatus.UNKNOWN,
                reason_codes=("TOOL_EXECUTION_UNKNOWN",),
                workflow_result=normalized,
                tool_results=journal_results,
                tool_journal=tool_invoker.entries(),
            )

        status = (
            CapabilityExecutionStatus.WAITING
            if normalized.status is WorkflowExecutionStatus.WAITING
            else CapabilityExecutionStatus.EXECUTED
        )
        reason = (
            "WORKFLOW_WAITING"
            if status is CapabilityExecutionStatus.WAITING
            else "WORKFLOW_STARTED"
        )
        return self._outcome(
            step=step,
            step_snapshot=step_snapshot,
            resolved=resolved,
            status=status,
            reason_codes=(reason,),
            workflow_result=normalized,
            tool_results=journal_results,
            tool_journal=tool_invoker.entries(),
        )

    @staticmethod
    def _validate_authority(
        *,
        approved_plan: ApprovedActionPlan,
        step: ActionStep,
        step_snapshot: StepLifecycleSnapshot,
        resolved: ResolvedStepCapabilities,
        execution_context: ExecutionContext,
    ) -> str | None:
        if (
            execution_context.plan_id != approved_plan.plan_id
            or execution_context.request_id != approved_plan.request_id
        ):
            return "EXECUTION_CONTEXT_PLAN_MISMATCH"
        matches = [item for item in approved_plan.steps if item.step_id == step.step_id]
        if len(matches) != 1 or matches[0] != step:
            return "APPROVED_STEP_MISMATCH"
        if (
            step_snapshot.step_id != step.step_id
            or step_snapshot.action != step.action
            or step_snapshot.status is not StepExecutionStatus.RUNNING
        ):
            return "STEP_EXECUTION_SNAPSHOT_INVALID"
        if resolved.step_id != step.step_id:
            return "RESOLVED_STEP_MISMATCH"

        binding_error = StepCapabilityExecutor._validate_approved_owner_binding(
            approved_plan=approved_plan,
            step=step,
            resolved=resolved,
        )
        if binding_error is not None:
            return binding_error

        if resolved.execution_owner is CapabilityExecutionOwner.SKILL:
            if (
                step.skill_id is None
                or resolved.skill is None
                or resolved.skill.capability_id != step.skill_id
                or resolved.workflow is not None
            ):
                return "SKILL_OWNER_BINDING_INVALID"
        elif resolved.execution_owner is CapabilityExecutionOwner.WORKFLOW:
            if (
                step.workflow_id is None
                or resolved.workflow is None
                or resolved.workflow.capability_id != step.workflow_id
                or resolved.skill is not None
            ):
                return "WORKFLOW_OWNER_BINDING_INVALID"
        else:
            if (
                step.skill_id is not None
                or step.workflow_id is not None
                or resolved.skill is not None
                or resolved.workflow is not None
                or resolved.tools
            ):
                return "NONE_OWNER_BINDING_INVALID"
        return None

    @staticmethod
    def _validate_approved_owner_binding(
        *,
        approved_plan: ApprovedActionPlan,
        step: ActionStep,
        resolved: ResolvedStepCapabilities,
    ) -> str | None:
        capability_plan = approved_plan.capability_plan
        if capability_plan is None:
            return "APPROVED_EXECUTION_OWNER_MISSING"
        bindings = capability_plan.get("bindings")
        if not isinstance(bindings, list):
            return "APPROVED_EXECUTION_OWNER_MISSING"

        matches = [
            item
            for item in bindings
            if isinstance(item, dict) and item.get("action_id") == step.action
        ]
        if len(matches) != 1:
            return "APPROVED_EXECUTION_OWNER_MISSING"

        binding = matches[0]
        if binding.get("execution_owner") != resolved.execution_owner.value:
            return "APPROVED_EXECUTION_OWNER_MISMATCH"

        if resolved.execution_owner is CapabilityExecutionOwner.SKILL:
            skill = resolved.skill
            if (
                skill is None
                or binding.get("skill_id") != skill.capability_id
                or binding.get("skill_version") != skill.version
            ):
                return "APPROVED_OWNER_IDENTITY_MISMATCH"
        elif resolved.execution_owner is CapabilityExecutionOwner.WORKFLOW:
            workflow = resolved.workflow
            if (
                workflow is None
                or binding.get("workflow_id") != workflow.capability_id
                or binding.get("workflow_version") != workflow.version
            ):
                return "APPROVED_OWNER_IDENTITY_MISMATCH"
        else:
            if (
                binding.get("skill_id") is not None
                or binding.get("workflow_id") is not None
            ):
                return "APPROVED_OWNER_IDENTITY_MISMATCH"
        return None

    def _boundary_outcome(
        self,
        *,
        step: ActionStep,
        step_snapshot: StepLifecycleSnapshot,
        resolved: ResolvedStepCapabilities,
        tool_invoker: CoreApprovedToolInvoker,
        tool_results: tuple[M5ToolResult, ...],
        skill_result: M5SkillResult | None = None,
        workflow_result: M5WorkflowResult | None = None,
    ) -> StepCapabilityExecutionOutcome | None:
        if not tool_invoker.boundary_faults:
            return None
        return self._outcome(
            step=step,
            step_snapshot=step_snapshot,
            resolved=resolved,
            status=self._fault_status(tool_invoker),
            reason_codes=tool_invoker.boundary_faults,
            skill_result=skill_result,
            workflow_result=workflow_result,
            tool_results=tool_results,
            tool_journal=tool_invoker.entries(),
        )

    @staticmethod
    def _fault_status(
        tool_invoker: CoreApprovedToolInvoker,
    ) -> CapabilityExecutionStatus:
        if "TOOL_NOT_APPROVED_FOR_STEP" in tool_invoker.boundary_faults:
            return CapabilityExecutionStatus.BLOCKED
        return CapabilityExecutionStatus.UNKNOWN

    @staticmethod
    def _exception_reasons(
        tool_invoker: CoreApprovedToolInvoker,
        *,
        default: str,
    ) -> tuple[str, ...]:
        return tool_invoker.boundary_faults or (default,)

    @staticmethod
    def _journal_results(
        tool_invoker: CoreApprovedToolInvoker,
    ) -> tuple[M5ToolResult, ...]:
        return tuple(entry.result for entry in tool_invoker.entries())

    @staticmethod
    def _outcome(
        *,
        step: ActionStep,
        step_snapshot: StepLifecycleSnapshot,
        resolved: ResolvedStepCapabilities,
        status: CapabilityExecutionStatus,
        reason_codes: tuple[str, ...],
        skill_result: M5SkillResult | None = None,
        workflow_result: M5WorkflowResult | None = None,
        tool_results: tuple[M5ToolResult, ...] = (),
        tool_journal: tuple[ToolInvocationJournalEntry, ...] = (),
    ) -> StepCapabilityExecutionOutcome:
        owner = resolved.execution_owner
        owner_capability: ResolvedCapability | None
        if owner is CapabilityExecutionOwner.SKILL:
            owner_capability = resolved.skill
        elif owner is CapabilityExecutionOwner.WORKFLOW:
            owner_capability = resolved.workflow
        else:
            owner_capability = None

        return StepCapabilityExecutionOutcome(
            step_id=step.step_id,
            step_execution_id=step_snapshot.step_execution_id,
            status=status,
            execution_owner=owner,
            reason_codes=reason_codes,
            owner_capability_id=(
                owner_capability.capability_id if owner_capability is not None else None
            ),
            owner_capability_version=(
                owner_capability.version if owner_capability is not None else None
            ),
            skill_result=skill_result,
            workflow_result=workflow_result,
            tool_results=tool_results,
            tool_journal=tool_journal,
        )
