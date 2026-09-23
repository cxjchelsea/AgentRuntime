"""M5-IU4 exact capability execution.

This module executes only the capability owner already frozen by M4 and exact-resolved
by IU3. IU6 may add reliability coordination inside the same Core Tool gateway, but it
still never replans, re-resolves Registry entries, resumes Workflows, aggregates
canonical ExecutionResult, or invokes M6.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
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
from runtime.execution.concurrency_runtime import (
    ExecutionConcurrencyAdmissionStatus,
    ExecutionConcurrencyRuntime,
    ToolConcurrencyAdmissionDecision,
    ToolConcurrencyAdmissionStatus,
    ToolConcurrencyCompletionStatus,
    ToolConcurrencyRuntime,
)
from runtime.execution.control_application import (
    InFlightOperationHandle,
    InFlightOperationIdentifierFactory,
    InFlightOperationKind,
    InFlightOperationRegistry,
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
from runtime.execution.recovery import (
    RecoverySideEffectAdmissionGuard,
    RecoverySideEffectAdmissionStatus,
)
from runtime.execution.recovery_workflow import (
    WorkflowRecoveryImplementation,
    WorkflowResumeRequest,
)
from runtime.execution.reliability import (
    AsyncTimeoutRunner,
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
    TimeoutRunResult,
    TimeoutRunStatus,
)
from runtime.execution.reliability_boundary import (
    IdempotencyPreflightDecision,
    IdempotencyPreflightStatus,
    ToolOperationCorrelationDecision,
    ToolOperationCorrelationKey,
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
        inflight_registry: InFlightOperationRegistry | None = None,
        inflight_identifier_factory: InFlightOperationIdentifierFactory | None = None,
        inflight_parent_handle_id: str | None = None,
        inflight_clock: Callable[[], datetime] | None = None,
        tool_concurrency_runtime: ToolConcurrencyRuntime | None = None,
        side_effect_admission_guard: RecoverySideEffectAdmissionGuard | None = None,
    ) -> None:
        if not step_execution_id.strip():
            raise ValueError("step_execution_id must not be blank")
        if step_attempt_number < 1:
            raise ValueError("step_attempt_number must be >= 1")
        if reliability_runtime is not None and (step_id is None or not step_id.strip()):
            raise ValueError("reliable Tool invocation requires non-blank step_id")
        if tool_concurrency_runtime is not None:
            if inflight_parent_handle_id is None:
                raise ValueError(
                    "Tool concurrency runtime requires owner parent handle"
                )
            if (
                inflight_registry is not None
                and inflight_registry is not tool_concurrency_runtime.inflight_registry
            ):
                raise ValueError(
                    "Tool concurrency runtime must share IU7 in-flight registry"
                )
            if (
                inflight_identifier_factory is not None
                and inflight_identifier_factory
                is not tool_concurrency_runtime.inflight_identifier_factory
            ):
                raise ValueError(
                    "Tool concurrency runtime must share IU7 identifier factory"
                )
            inflight_registry = tool_concurrency_runtime.inflight_registry
            inflight_identifier_factory = (
                tool_concurrency_runtime.inflight_identifier_factory
            )

        tracking_values = (
            inflight_registry,
            inflight_identifier_factory,
            inflight_parent_handle_id,
        )
        if any(value is not None for value in tracking_values) and not all(
            value is not None for value in tracking_values
        ):
            raise ValueError(
                "Tool in-flight tracking requires registry/factory/parent handle together"
            )
        if (
            inflight_parent_handle_id is not None
            and not inflight_parent_handle_id.strip()
        ):
            raise ValueError("inflight_parent_handle_id must not be blank")
        self._execution_context = execution_context
        self._step_execution_id = step_execution_id
        self._step_id = step_id
        self._step_attempt_number = step_attempt_number
        self._prior_attempt_journal = prior_attempt_journal
        self._reliability_runtime = reliability_runtime
        self._inflight_registry = inflight_registry
        self._inflight_identifier_factory = inflight_identifier_factory
        self._inflight_parent_handle_id = inflight_parent_handle_id
        self._inflight_clock = inflight_clock or (lambda: datetime.now(UTC))
        self._tool_concurrency_runtime = tool_concurrency_runtime
        self._side_effect_admission_guard = side_effect_admission_guard
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

    async def _invoke_with_reliability(
        self,
        *,
        tool_id: str,
        input_payload: dict[str, Any],
    ) -> M5ToolResult:
        runtime = self._reliability_runtime
        if runtime is None:
            raise RuntimeError("reliability runtime is not configured")

        resolved = self._resolved_tools.get(tool_id)
        if resolved is None:
            self._record_fault("TOOL_NOT_APPROVED_FOR_STEP")
            raise ToolInvocationBoundaryError(
                "TOOL_NOT_APPROVED_FOR_STEP",
                "Tool is not approved/resolved for the current step",
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

        if not isinstance(input_payload, dict):
            logical_tool_call_id = self._new_tool_call_id(tool_id)
            result = self._generated_result(
                tool_call_id=logical_tool_call_id,
                tool_id=tool_id,
                status=ToolExecutionStatus.REJECTED,
                error_code="INVALID_PARAMETER",
                reason_codes=("TOOL_INPUT_PAYLOAD_NOT_OBJECT",),
            )
            self._append_logical_result_without_attempt(
                resolved=resolved,
                result=result,
                permission_status=None,
                input_status=ToolPayloadValidationStatus.INVALID,
                output_status=None,
                operation_key=None,
                operation_fingerprint=None,
                idempotency_key=None,
            )
            return result

        policy, policy_error = self._resolve_tool_reliability_policy(resolved)
        if policy is None:
            return self._reliability_unknown_without_attempt(
                resolved=resolved,
                tool_id=tool_id,
                reason_code=policy_error or "TOOL_RELIABILITY_POLICY_UNKNOWN",
            )

        try:
            operation_fingerprint = runtime.fingerprint_factory.fingerprint(
                tool_id=tool_id,
                tool_version=resolved.version,
                input_payload=dict(input_payload),
            )
        except Exception:  # noqa: BLE001
            operation_fingerprint = ""
        if (
            not isinstance(operation_fingerprint, str)
            or not operation_fingerprint.strip()
        ):
            return self._reliability_unknown_without_attempt(
                resolved=resolved,
                tool_id=tool_id,
                reason_code="TOOL_OPERATION_FINGERPRINT_UNKNOWN",
            )

        try:
            occurrence_decision = await runtime.occurrence_authority.claim_next(
                step_execution_id=self._step_execution_id,
                step_attempt_number=self._step_attempt_number,
                tool_id=tool_id,
                tool_version=resolved.version,
                operation_fingerprint=operation_fingerprint,
            )
        except Exception:  # noqa: BLE001
            occurrence_decision = None
        if (
            not isinstance(occurrence_decision, ToolOperationOccurrenceDecision)
            or not isinstance(
                occurrence_decision.status,
                ToolOperationOccurrenceStatus,
            )
            or occurrence_decision.status is not ToolOperationOccurrenceStatus.CLAIMED
            or occurrence_decision.occurrence is None
        ):
            return self._reliability_unknown_without_attempt(
                resolved=resolved,
                tool_id=tool_id,
                reason_code="TOOL_OPERATION_OCCURRENCE_UNKNOWN",
            )
        operation_occurrence = occurrence_decision.occurrence

        try:
            correlation = runtime.correlator.correlate(
                step_execution_id=self._step_execution_id,
                step_attempt_number=self._step_attempt_number,
                tool_id=tool_id,
                tool_version=resolved.version,
                operation_fingerprint=operation_fingerprint,
                operation_occurrence=operation_occurrence,
                prior_attempt_journal=self._prior_attempt_journal,
            )
        except Exception:  # noqa: BLE001
            correlation = None
        if (
            not isinstance(correlation, ToolOperationCorrelationDecision)
            or not isinstance(
                correlation.status,
                ToolOperationCorrelationStatus,
            )
            or correlation.status is ToolOperationCorrelationStatus.UNKNOWN
            or correlation.operation_key is None
            or correlation.logical_tool_call_id is None
            or correlation.operation_occurrence != operation_occurrence
        ):
            return self._reliability_unknown_without_attempt(
                resolved=resolved,
                tool_id=tool_id,
                reason_code="TOOL_OPERATION_CORRELATION_UNKNOWN",
            )

        logical_tool_call_id = correlation.logical_tool_call_id
        operation_key = correlation.operation_key.value

        current_attempt = 1
        idempotency_key: str | None = None
        reserved_record: IdempotencyRecord | None = None

        while True:
            input_decision = self._validate_input(
                resolved.definition,
                input_payload,
            )
            if input_decision.status is ToolPayloadValidationStatus.INVALID:
                return self._append_reliable_gate_result(
                    resolved=resolved,
                    logical_tool_call_id=logical_tool_call_id,
                    tool_id=tool_id,
                    physical_attempt=current_attempt,
                    status=ToolExecutionStatus.REJECTED,
                    error_code="INVALID_PARAMETER",
                    reason_codes=input_decision.reason_codes,
                    permission_status=None,
                    input_status=input_decision.status,
                    operation_key=operation_key,
                    operation_fingerprint=operation_fingerprint,
                    idempotency_key=idempotency_key,
                )
            if input_decision.status is ToolPayloadValidationStatus.UNKNOWN:
                return self._append_reliable_gate_result(
                    resolved=resolved,
                    logical_tool_call_id=logical_tool_call_id,
                    tool_id=tool_id,
                    physical_attempt=current_attempt,
                    status=ToolExecutionStatus.UNKNOWN,
                    error_code="TOOL_INPUT_VALIDATION_UNKNOWN",
                    reason_codes=input_decision.reason_codes,
                    permission_status=None,
                    input_status=input_decision.status,
                    operation_key=operation_key,
                    operation_fingerprint=operation_fingerprint,
                    idempotency_key=idempotency_key,
                )

            permission_status = await self._permission_status(resolved.definition)
            if permission_status is PermissionDecisionStatus.DENIED:
                return self._append_reliable_gate_result(
                    resolved=resolved,
                    logical_tool_call_id=logical_tool_call_id,
                    tool_id=tool_id,
                    physical_attempt=current_attempt,
                    status=ToolExecutionStatus.REJECTED,
                    error_code="PERMISSION_DENIED",
                    reason_codes=("PERMISSION_DENIED",),
                    permission_status=permission_status,
                    input_status=input_decision.status,
                    operation_key=operation_key,
                    operation_fingerprint=operation_fingerprint,
                    idempotency_key=idempotency_key,
                )
            if permission_status is PermissionDecisionStatus.UNKNOWN:
                return self._append_reliable_gate_result(
                    resolved=resolved,
                    logical_tool_call_id=logical_tool_call_id,
                    tool_id=tool_id,
                    physical_attempt=current_attempt,
                    status=ToolExecutionStatus.UNKNOWN,
                    error_code="TOOL_PERMISSION_UNKNOWN",
                    reason_codes=("TOOL_PERMISSION_UNKNOWN",),
                    permission_status=permission_status,
                    input_status=input_decision.status,
                    operation_key=operation_key,
                    operation_fingerprint=operation_fingerprint,
                    idempotency_key=idempotency_key,
                )

            deadline_remaining, deadline_error = self._deadline_remaining_seconds()
            if deadline_error is not None:
                return self._append_reliable_gate_result(
                    resolved=resolved,
                    logical_tool_call_id=logical_tool_call_id,
                    tool_id=tool_id,
                    physical_attempt=current_attempt,
                    status=ToolExecutionStatus.UNKNOWN,
                    error_code=deadline_error,
                    reason_codes=(deadline_error,),
                    permission_status=permission_status,
                    input_status=input_decision.status,
                    operation_key=operation_key,
                    operation_fingerprint=operation_fingerprint,
                    idempotency_key=idempotency_key,
                )
            if deadline_remaining is not None and deadline_remaining <= 0:
                return self._append_reliable_gate_result(
                    resolved=resolved,
                    logical_tool_call_id=logical_tool_call_id,
                    tool_id=tool_id,
                    physical_attempt=current_attempt,
                    status=ToolExecutionStatus.TIMEOUT,
                    error_code="EXECUTION_DEADLINE_EXPIRED",
                    reason_codes=("EXECUTION_DEADLINE_EXPIRED",),
                    permission_status=permission_status,
                    input_status=input_decision.status,
                    operation_key=operation_key,
                    operation_fingerprint=operation_fingerprint,
                    idempotency_key=idempotency_key,
                )

            if (
                current_attempt == 1
                and policy.idempotency.mode is IdempotencyMode.KEY_BASED
            ):
                (
                    idempotency_key,
                    reserved_record,
                    recovered_result,
                    idempotency_error,
                ) = await self._prepare_key_based_idempotency(
                    resolved=resolved,
                    logical_tool_call_id=logical_tool_call_id,
                    operation_key=operation_key,
                    operation_fingerprint=operation_fingerprint,
                )
                if recovered_result is not None:
                    self._append_logical_result_without_attempt(
                        resolved=resolved,
                        result=recovered_result,
                        permission_status=permission_status,
                        input_status=input_decision.status,
                        output_status=None,
                        operation_key=operation_key,
                        operation_fingerprint=operation_fingerprint,
                        idempotency_key=idempotency_key,
                    )
                    return recovered_result
                if idempotency_error is not None:
                    result = self._generated_result(
                        tool_call_id=logical_tool_call_id,
                        tool_id=tool_id,
                        status=ToolExecutionStatus.UNKNOWN,
                        error_code=idempotency_error,
                        reason_codes=(idempotency_error,),
                    )
                    self._append_logical_result_without_attempt(
                        resolved=resolved,
                        result=result,
                        permission_status=permission_status,
                        input_status=input_decision.status,
                        output_status=None,
                        operation_key=operation_key,
                        operation_fingerprint=operation_fingerprint,
                        idempotency_key=idempotency_key,
                    )
                    return result

            effective_timeout = self._effective_timeout_seconds(
                policy=policy,
                deadline_remaining_seconds=deadline_remaining,
            )
            self._claim_reliable_attempt_identity(
                logical_tool_call_id=logical_tool_call_id,
                tool_id=tool_id,
                physical_attempt=current_attempt,
                operation_key=operation_key,
                operation_fingerprint=operation_fingerprint,
                idempotency_key=idempotency_key,
            )
            attempt = await self._execute_reliable_tool_attempt(
                resolved=resolved,
                logical_tool_call_id=logical_tool_call_id,
                tool_id=tool_id,
                input_payload=input_payload,
                physical_attempt=current_attempt,
                operation_key=operation_key,
                operation_fingerprint=operation_fingerprint,
                idempotency_key=idempotency_key,
                input_decision=input_decision,
                permission_status=permission_status,
                timeout_seconds=effective_timeout,
            )
            result = attempt.result

            if result.status is ToolExecutionStatus.SUCCESS:
                if (
                    policy.idempotency.mode is IdempotencyMode.KEY_BASED
                    and reserved_record is not None
                ):
                    return await self._complete_key_based_idempotency(
                        reserved_record=reserved_record,
                        result=result,
                    )
                return result

            trigger_status = self._retry_trigger_status(result.status)
            if (
                trigger_status is None
                or not policy.retry.enabled
                or current_attempt >= policy.retry.max_attempts
            ):
                await self._mark_reserved_unknown(reserved_record)
                return result

            replay_safety = self._evaluate_replay_safety(
                policy=policy,
                attempt=attempt,
            )
            retry_decision = self._evaluate_retry_decision(
                policy=policy,
                attempt=result,
                current_attempt=current_attempt,
                trigger_status=trigger_status,
                replay_safety=replay_safety,
            )

            if retry_decision.status is RetryDecisionStatus.RETRY:
                if (
                    replay_safety.status is not ReplaySafetyStatus.SAFE
                    or retry_decision.next_attempt != current_attempt + 1
                    or retry_decision.next_attempt > policy.retry.max_attempts
                ):
                    await self._mark_reserved_unknown(reserved_record)
                    return self._override_last_attempt_as_unknown(
                        logical_tool_call_id=logical_tool_call_id,
                        error_code="RETRY_DECISION_INVALID_OR_UNSAFE",
                    )
                try:
                    if retry_decision.backoff_seconds:
                        await runtime.retry_sleeper.sleep(
                            retry_decision.backoff_seconds
                        )
                except Exception:  # noqa: BLE001
                    await self._mark_reserved_unknown(reserved_record)
                    return self._override_last_attempt_as_unknown(
                        logical_tool_call_id=logical_tool_call_id,
                        error_code="RETRY_BACKOFF_FAILURE",
                    )
                current_attempt = retry_decision.next_attempt
                continue

            if retry_decision.status is RetryDecisionStatus.UNKNOWN:
                await self._mark_reserved_unknown(reserved_record)
                return self._override_last_attempt_as_unknown(
                    logical_tool_call_id=logical_tool_call_id,
                    error_code="RETRY_DECISION_UNKNOWN",
                )

            await self._mark_reserved_unknown(reserved_record)
            return result

    def _resolve_tool_reliability_policy(
        self,
        resolved: ResolvedCapability,
    ) -> tuple[ResolvedReliabilityPolicy | None, str | None]:
        runtime = self._reliability_runtime
        if runtime is None or not isinstance(resolved.definition, ToolDefinition):
            return None, "TOOL_RELIABILITY_RUNTIME_MISSING"
        definition = resolved.definition
        try:
            policy = runtime.policy_resolver.resolve(
                capability_kind=ReliabilityCapabilityKind.TOOL,
                capability_id=resolved.capability_id,
                capability_version=resolved.version,
                timeout_policy_ref=definition.timeout_policy,
                retry_policy_ref=definition.retry_policy,
                idempotency_policy_ref=definition.idempotency_mode,
                side_effect_level_ref=definition.side_effect_level,
            )
        except Exception:  # noqa: BLE001
            return None, "TOOL_RELIABILITY_POLICY_RESOLUTION_FAILED"
        if (
            not isinstance(policy, ResolvedReliabilityPolicy)
            or policy.capability_kind is not ReliabilityCapabilityKind.TOOL
            or policy.capability_id != resolved.capability_id
            or policy.capability_version != resolved.version
        ):
            return None, "TOOL_RELIABILITY_POLICY_IDENTITY_MISMATCH"
        return policy, None

    async def _prepare_key_based_idempotency(
        self,
        *,
        resolved: ResolvedCapability,
        logical_tool_call_id: str,
        operation_key: str,
        operation_fingerprint: str,
    ) -> tuple[
        str | None,
        IdempotencyRecord | None,
        M5ToolResult | None,
        str | None,
    ]:
        runtime = self._reliability_runtime
        step_id = self._step_id
        if runtime is None or step_id is None:
            return None, None, None, "IDEMPOTENCY_RUNTIME_MISSING"
        try:
            key = runtime.idempotency_key_factory.create(
                execution_id=self._execution_context.execution_id,
                step_execution_id=self._step_execution_id,
                operation_key=ToolOperationCorrelationKey(operation_key),
                tool_id=resolved.capability_id,
                tool_version=resolved.version,
                operation_fingerprint=operation_fingerprint,
            )
        except Exception:  # noqa: BLE001
            return None, None, None, "IDEMPOTENCY_KEY_UNAVAILABLE"
        if not isinstance(key, str) or not key.strip():
            return None, None, None, "IDEMPOTENCY_KEY_UNAVAILABLE"

        try:
            existing = await runtime.idempotency_store.get(key)
        except Exception:  # noqa: BLE001
            return key, None, None, "IDEMPOTENCY_READ_UNKNOWN"

        try:
            decision = runtime.idempotency_preflight_evaluator.evaluate(
                existing_record=existing,
                expected_execution_id=self._execution_context.execution_id,
                expected_step_execution_id=self._step_execution_id,
                expected_tool_id=resolved.capability_id,
                expected_tool_version=resolved.version,
                expected_operation_key=operation_key,
                expected_operation_fingerprint=operation_fingerprint,
            )
        except Exception:  # noqa: BLE001
            decision = None
        if not isinstance(decision, IdempotencyPreflightDecision) or not isinstance(
            decision.status, IdempotencyPreflightStatus
        ):
            return key, None, None, "IDEMPOTENCY_PREFLIGHT_UNKNOWN"

        if (
            decision.existing_record is not None
            and not self._idempotency_record_matches_expected(
                record=decision.existing_record,
                key=key,
                resolved=resolved,
                operation_key=operation_key,
                operation_fingerprint=operation_fingerprint,
            )
        ):
            return key, None, None, "IDEMPOTENCY_PROVENANCE_MISMATCH"

        if decision.status is IdempotencyPreflightStatus.RECOVER_COMPLETED:
            record = decision.existing_record
            if record is None:
                return key, None, None, "IDEMPOTENCY_COMPLETED_RECORD_MISSING"
            try:
                recovered = await runtime.idempotency_result_resolver.resolve_completed(
                    record
                )
            except Exception:  # noqa: BLE001
                recovered = None
            if (
                not isinstance(recovered, M5ToolResult)
                or recovered.tool_call_id != logical_tool_call_id
                or recovered.tool_id != resolved.capability_id
                or record.tool_call_id != logical_tool_call_id
            ):
                return key, None, None, "IDEMPOTENCY_COMPLETED_RESULT_INVALID"
            return key, None, recovered, None

        if decision.status in (
            IdempotencyPreflightStatus.WAIT_IN_FLIGHT,
            IdempotencyPreflightStatus.FAIL_UNKNOWN,
            IdempotencyPreflightStatus.REJECT_PROVENANCE,
        ):
            return key, None, None, f"IDEMPOTENCY_{decision.status.value}"

        now, now_error = self._clock_now()
        if now_error is not None:
            return key, None, None, now_error
        record = IdempotencyRecord(
            key=key,
            execution_id=self._execution_context.execution_id,
            step_id=step_id,
            step_execution_id=self._step_execution_id,
            tool_id=resolved.capability_id,
            tool_version=resolved.version,
            operation_key=operation_key,
            operation_fingerprint=operation_fingerprint,
            status=IdempotencyStatus.RESERVED,
            created_at=now,
            updated_at=now,
        )

        if decision.status is IdempotencyPreflightStatus.REOPEN_FAILED:
            failed_record = decision.existing_record
            if failed_record is None:
                return key, None, None, "IDEMPOTENCY_FAILED_RECORD_MISSING"
            try:
                reopened = await runtime.idempotency_store.reopen_failed(failed_record)
            except Exception:  # noqa: BLE001
                reopened = False
            if not reopened:
                return key, None, None, "IDEMPOTENCY_REOPEN_CONFLICT"
            return key, record, None, None

        if decision.status is not IdempotencyPreflightStatus.RESERVE_NEW:
            return key, None, None, "IDEMPOTENCY_PREFLIGHT_UNKNOWN"

        try:
            reserved = await runtime.idempotency_store.reserve(record)
        except Exception:  # noqa: BLE001
            reserved = False
        if not reserved:
            return key, None, None, "IDEMPOTENCY_RESERVE_CONFLICT"
        return key, record, None, None

    def _idempotency_record_matches_expected(
        self,
        *,
        record: IdempotencyRecord,
        key: str,
        resolved: ResolvedCapability,
        operation_key: str,
        operation_fingerprint: str,
    ) -> bool:
        return (
            self._step_id is not None
            and record.key == key
            and record.execution_id == self._execution_context.execution_id
            and record.step_id == self._step_id
            and record.step_execution_id == self._step_execution_id
            and record.tool_id == resolved.capability_id
            and record.tool_version == resolved.version
            and record.operation_key == operation_key
            and record.operation_fingerprint == operation_fingerprint
        )

    async def _complete_key_based_idempotency(
        self,
        *,
        reserved_record: IdempotencyRecord,
        result: M5ToolResult,
    ) -> M5ToolResult:
        runtime = self._reliability_runtime
        if runtime is None or reserved_record.status is not IdempotencyStatus.RESERVED:
            return self._override_last_attempt_as_unknown(
                logical_tool_call_id=result.tool_call_id,
                error_code="IDEMPOTENCY_COMPLETION_PRECONDITION_INVALID",
            )
        try:
            decision = await runtime.idempotency_completion_authority.complete(
                reserved_record=reserved_record,
                result=result,
            )
        except Exception:  # noqa: BLE001
            decision = None
        if (
            not isinstance(decision, IdempotencyCompletionDecision)
            or not isinstance(decision.status, IdempotencyCompletionStatus)
            or decision.status is not IdempotencyCompletionStatus.COMPLETED
            or decision.completed_record is None
            or not self._completed_record_matches(
                reserved_record=reserved_record,
                completed_record=decision.completed_record,
                result=result,
            )
        ):
            return self._override_last_attempt_as_unknown(
                logical_tool_call_id=result.tool_call_id,
                error_code="IDEMPOTENCY_COMPLETION_UNKNOWN",
            )
        return result

    @staticmethod
    def _completed_record_matches(
        *,
        reserved_record: IdempotencyRecord,
        completed_record: IdempotencyRecord,
        result: M5ToolResult,
    ) -> bool:
        return (
            completed_record.status is IdempotencyStatus.COMPLETED
            and completed_record.key == reserved_record.key
            and completed_record.execution_id == reserved_record.execution_id
            and completed_record.step_id == reserved_record.step_id
            and completed_record.step_execution_id == reserved_record.step_execution_id
            and completed_record.tool_id == reserved_record.tool_id
            and completed_record.tool_version == reserved_record.tool_version
            and completed_record.operation_key == reserved_record.operation_key
            and completed_record.operation_fingerprint
            == reserved_record.operation_fingerprint
            and completed_record.tool_call_id == result.tool_call_id
            and completed_record.result_reference is not None
            and bool(completed_record.result_reference.strip())
        )

    async def _execute_reliable_tool_attempt(
        self,
        *,
        resolved: ResolvedCapability,
        logical_tool_call_id: str,
        tool_id: str,
        input_payload: dict[str, Any],
        physical_attempt: int,
        operation_key: str,
        operation_fingerprint: str,
        idempotency_key: str | None,
        input_decision: ToolPayloadValidationDecision,
        permission_status: PermissionDecisionStatus,
        timeout_seconds: float | None,
    ) -> ToolAttemptObservation:
        request = ToolInvocationRequest(
            tool_call_id=logical_tool_call_id,
            tool_id=tool_id,
            input_payload=dict(input_payload),
            attempt=physical_attempt,
            idempotency_key=idempotency_key,
        )

        raw_result: Any
        timeout_status: TimeoutRunStatus | None = None
        execution_exception = False
        runtime = self._reliability_runtime
        if runtime is None:
            raise RuntimeError("reliability runtime is not configured")

        # 物理尝试入口再次收窄 Tool 绑定，避免 union 类型泄漏到 invoke / 校验。
        tool_definition = resolved.definition
        tool_implementation = resolved.implementation_ref
        if (
            resolved.kind is not CapabilityKind.TOOL
            or not isinstance(tool_definition, ToolDefinition)
            or not isinstance(tool_implementation, ToolImplementation)
        ):
            self._record_fault("APPROVED_TOOL_BINDING_INVALID")
            raise ToolInvocationBoundaryError(
                "APPROVED_TOOL_BINDING_INVALID",
                "IU3 resolved Tool binding is internally inconsistent",
            )

        await self._authorize_recovery_side_effect()

        (
            concurrency_admission,
            inflight_handle,
            admission_reasons,
        ) = await self._begin_physical_tool_operation(
            resolved=resolved,
            logical_tool_call_id=logical_tool_call_id,
            physical_attempt=physical_attempt,
        )
        if admission_reasons:
            error_code = (
                "RESOURCE_LOCK_BUSY"
                if concurrency_admission is not None
                and concurrency_admission.status is ToolConcurrencyAdmissionStatus.BUSY
                else admission_reasons[0]
            )
            result = self._generated_result(
                tool_call_id=logical_tool_call_id,
                tool_id=tool_id,
                status=ToolExecutionStatus.UNKNOWN,
                error_code=error_code,
                reason_codes=admission_reasons,
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

        operation_completion_ok: bool | None = None
        if timeout_seconds is None:
            try:
                raw_result = await tool_implementation.invoke(
                    request,
                    self._execution_context,
                )
                operation_completion_ok = await self._complete_physical_tool_operation(
                    concurrency_admission=concurrency_admission,
                    inflight_handle=inflight_handle,
                )
            except Exception:  # noqa: BLE001
                raw_result = None
                execution_exception = True
                operation_completion_ok = await self._complete_physical_tool_operation(
                    concurrency_admission=concurrency_admission,
                    inflight_handle=inflight_handle,
                )
        else:
            try:
                timeout_result = await runtime.timeout_runner.run(
                    timeout_seconds=timeout_seconds,
                    operation=lambda: tool_implementation.invoke(
                        request,
                        self._execution_context,
                    ),
                )
            except Exception:  # noqa: BLE001
                timeout_result = None
            if not isinstance(timeout_result, TimeoutRunResult) or not isinstance(
                timeout_result.status, TimeoutRunStatus
            ):
                raw_result = None
                timeout_status = TimeoutRunStatus.UNKNOWN
            elif timeout_result.status is TimeoutRunStatus.COMPLETED:
                raw_result = timeout_result.value
                timeout_status = TimeoutRunStatus.COMPLETED
                operation_completion_ok = await self._complete_physical_tool_operation(
                    concurrency_admission=concurrency_admission,
                    inflight_handle=inflight_handle,
                )
            else:
                raw_result = None
                timeout_status = timeout_result.status

        if operation_completion_ok is False:
            raw_identity_valid = (
                isinstance(raw_result, M5ToolResult)
                and isinstance(raw_result.status, ToolExecutionStatus)
                and raw_result.tool_call_id == logical_tool_call_id
                and raw_result.tool_id == tool_id
                and raw_result.attempt == physical_attempt
            )
            result = self._generated_result(
                tool_call_id=logical_tool_call_id,
                tool_id=tool_id,
                status=ToolExecutionStatus.UNKNOWN,
                error_code="TOOL_CONCURRENCY_COMPLETION_UNKNOWN",
                reason_codes=("TOOL_CONCURRENCY_COMPLETION_UNKNOWN",),
                attempt=physical_attempt,
            )
            return self._append_journal_attempt(
                resolved=resolved,
                result=result,
                raw_result=raw_result if raw_identity_valid else None,
                permission_status=permission_status,
                input_status=input_decision.status,
                output_status=None,
                idempotency_key=idempotency_key,
                operation_key=operation_key,
                operation_fingerprint=operation_fingerprint,
            )

        if timeout_seconds is None and execution_exception:
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

        if timeout_seconds is not None and timeout_status is TimeoutRunStatus.TIMED_OUT:
            result = self._generated_result(
                tool_call_id=logical_tool_call_id,
                tool_id=tool_id,
                status=ToolExecutionStatus.TIMEOUT,
                error_code="TOOL_TIMEOUT",
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

        if timeout_seconds is not None and timeout_status is TimeoutRunStatus.UNKNOWN:
            result = self._generated_result(
                tool_call_id=logical_tool_call_id,
                tool_id=tool_id,
                status=ToolExecutionStatus.UNKNOWN,
                error_code="TOOL_TIMEOUT_BOUNDARY_UNKNOWN",
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
            raw_result.status,
            ToolExecutionStatus,
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

        output_decision = self._validate_output(tool_definition, raw_result)
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

    def _append_reliable_gate_result(
        self,
        *,
        resolved: ResolvedCapability,
        logical_tool_call_id: str,
        tool_id: str,
        physical_attempt: int,
        status: ToolExecutionStatus,
        error_code: str,
        reason_codes: tuple[str, ...],
        permission_status: PermissionDecisionStatus | None,
        input_status: ToolPayloadValidationStatus | None,
        operation_key: str,
        operation_fingerprint: str,
        idempotency_key: str | None,
    ) -> M5ToolResult:
        self._claim_reliable_attempt_identity(
            logical_tool_call_id=logical_tool_call_id,
            tool_id=tool_id,
            physical_attempt=physical_attempt,
            operation_key=operation_key,
            operation_fingerprint=operation_fingerprint,
            idempotency_key=idempotency_key,
        )
        result = self._generated_result(
            tool_call_id=logical_tool_call_id,
            tool_id=tool_id,
            status=status,
            error_code=error_code,
            reason_codes=reason_codes,
            attempt=physical_attempt,
        )
        return self._append_journal_attempt(
            resolved=resolved,
            result=result,
            permission_status=permission_status,
            input_status=input_status,
            output_status=None,
            idempotency_key=idempotency_key,
            operation_key=operation_key,
            operation_fingerprint=operation_fingerprint,
        ).result

    def _claim_reliable_attempt_identity(
        self,
        *,
        logical_tool_call_id: str,
        tool_id: str,
        physical_attempt: int,
        operation_key: str,
        operation_fingerprint: str,
        idempotency_key: str | None,
    ) -> None:
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
                    "first physical attempt must be attempt 1",
                )
            self._issued_tool_call_ids.add(logical_tool_call_id)
            return

        expected_attempt = len(existing.attempts) + 1
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

    def _append_logical_result_without_attempt(
        self,
        *,
        resolved: ResolvedCapability,
        result: M5ToolResult,
        permission_status: PermissionDecisionStatus | None,
        input_status: ToolPayloadValidationStatus | None,
        output_status: ToolPayloadValidationStatus | None,
        operation_key: str | None,
        operation_fingerprint: str | None,
        idempotency_key: str | None,
    ) -> None:
        if self._journal_entry(result.tool_call_id) is not None:
            raise ToolInvocationBoundaryError(
                "TOOL_CALL_ID_COLLISION",
                "logical Tool call already has a journal entry",
            )
        if result.tool_call_id in self._issued_tool_call_ids:
            raise ToolInvocationBoundaryError(
                "TOOL_CALL_ID_COLLISION",
                "logical Tool call id is already issued",
            )
        self._issued_tool_call_ids.add(result.tool_call_id)
        self._journal.append(
            ToolInvocationJournalEntry(
                tool_call_id=result.tool_call_id,
                tool_id=result.tool_id,
                tool_version=resolved.version,
                result=result,
                permission_status=permission_status,
                input_validation_status=input_status,
                output_validation_status=output_status,
                operation_key=operation_key,
                operation_fingerprint=operation_fingerprint,
                idempotency_key=idempotency_key,
                attempts=(),
            )
        )

    def _reliability_unknown_without_attempt(
        self,
        *,
        resolved: ResolvedCapability,
        tool_id: str,
        reason_code: str,
    ) -> M5ToolResult:
        logical_tool_call_id = self._new_tool_call_id(tool_id)
        result = self._generated_result(
            tool_call_id=logical_tool_call_id,
            tool_id=tool_id,
            status=ToolExecutionStatus.UNKNOWN,
            error_code=reason_code,
            reason_codes=(reason_code,),
        )
        self._append_logical_result_without_attempt(
            resolved=resolved,
            result=result,
            permission_status=None,
            input_status=None,
            output_status=None,
            operation_key=None,
            operation_fingerprint=None,
            idempotency_key=None,
        )
        return result

    def _deadline_remaining_seconds(
        self,
    ) -> tuple[float | None, str | None]:
        deadline = self._execution_context.deadline
        if deadline is None:
            return None, None
        now, error = self._clock_now()
        if error is not None or now is None:
            return None, error or "EXECUTION_CLOCK_UNKNOWN"
        try:
            return (deadline - now).total_seconds(), None
        except (TypeError, ValueError):
            return None, "EXECUTION_DEADLINE_COMPARISON_UNKNOWN"

    def _clock_now(self) -> tuple[Any | None, str | None]:
        runtime = self._reliability_runtime
        if runtime is None:
            return None, "EXECUTION_CLOCK_UNKNOWN"
        try:
            now = runtime.clock.now()
        except Exception:  # noqa: BLE001
            return None, "EXECUTION_CLOCK_UNKNOWN"
        return now, None

    @staticmethod
    def _effective_timeout_seconds(
        *,
        policy: ResolvedReliabilityPolicy,
        deadline_remaining_seconds: float | None,
    ) -> float | None:
        values = [
            value
            for value in (
                policy.timeout.timeout_seconds,
                deadline_remaining_seconds,
            )
            if value is not None
        ]
        return min(values) if values else None

    @staticmethod
    def _retry_trigger_status(
        status: ToolExecutionStatus,
    ) -> RetryTriggerStatus | None:
        mapping = {
            ToolExecutionStatus.FAILED: RetryTriggerStatus.FAILED,
            ToolExecutionStatus.TIMEOUT: RetryTriggerStatus.TIMEOUT,
            ToolExecutionStatus.UNAVAILABLE: RetryTriggerStatus.UNAVAILABLE,
        }
        return mapping.get(status)

    def _evaluate_replay_safety(
        self,
        *,
        policy: ResolvedReliabilityPolicy,
        attempt: ToolAttemptObservation,
    ) -> ReplaySafetyDecision:
        runtime = self._reliability_runtime
        if runtime is None:
            return ReplaySafetyDecision(
                status=ReplaySafetyStatus.UNKNOWN,
                reason_codes=("REPLAY_SAFETY_RUNTIME_MISSING",),
            )
        raw_success = (
            attempt.raw_result is not None
            and attempt.raw_result.status is ToolExecutionStatus.SUCCESS
            and attempt.result.status is ToolExecutionStatus.UNKNOWN
        )
        context = ReplaySafetyContext(
            idempotency_mode=policy.idempotency.mode,
            side_effect_class=policy.side_effect_class,
            invocation_started=True,
            current_status=attempt.result.status,
            has_unknown_side_effect=attempt.result.status
            in {
                ToolExecutionStatus.TIMEOUT,
                ToolExecutionStatus.UNKNOWN,
            },
            has_untrusted_success=raw_success,
            idempotency_state_unknown=False,
        )
        try:
            decision = runtime.replay_safety_evaluator.evaluate(context)
        except Exception:  # noqa: BLE001
            decision = None
        if not isinstance(decision, ReplaySafetyDecision) or not isinstance(
            decision.status, ReplaySafetyStatus
        ):
            return ReplaySafetyDecision(
                status=ReplaySafetyStatus.UNKNOWN,
                reason_codes=("REPLAY_SAFETY_EVALUATOR_UNKNOWN",),
            )
        return decision

    def _evaluate_retry_decision(
        self,
        *,
        policy: ResolvedReliabilityPolicy,
        attempt: M5ToolResult,
        current_attempt: int,
        trigger_status: RetryTriggerStatus,
        replay_safety: ReplaySafetyDecision,
    ) -> RetryDecision:
        runtime = self._reliability_runtime
        if runtime is None:
            return RetryDecision(
                status=RetryDecisionStatus.UNKNOWN,
                reason_codes=("RETRY_RUNTIME_MISSING",),
            )
        deadline_remaining, deadline_error = self._deadline_remaining_seconds()
        if deadline_error is not None:
            return RetryDecision(
                status=RetryDecisionStatus.UNKNOWN,
                reason_codes=(deadline_error,),
            )
        context = RetryDecisionContext(
            current_attempt=current_attempt,
            result_status=trigger_status,
            error_code=attempt.error_code,
            replay_safety=replay_safety,
            deadline_remaining_seconds=(
                max(deadline_remaining, 0.0) if deadline_remaining is not None else None
            ),
        )
        try:
            decision = runtime.retry_decision_evaluator.evaluate(
                policy=policy.retry,
                context=context,
            )
        except Exception:  # noqa: BLE001
            decision = None
        if not isinstance(decision, RetryDecision) or not isinstance(
            decision.status, RetryDecisionStatus
        ):
            return RetryDecision(
                status=RetryDecisionStatus.UNKNOWN,
                reason_codes=("RETRY_DECISION_EVALUATOR_UNKNOWN",),
            )
        return decision

    async def _mark_reserved_unknown(
        self,
        record: IdempotencyRecord | None,
    ) -> None:
        runtime = self._reliability_runtime
        if runtime is None or record is None:
            return
        try:
            await runtime.idempotency_store.mark_unknown(record.key)
        except Exception:  # noqa: BLE001
            return

    def _override_last_attempt_as_unknown(
        self,
        *,
        logical_tool_call_id: str,
        error_code: str,
    ) -> M5ToolResult:
        entry = self._journal_entry(logical_tool_call_id)
        if entry is None or not entry.attempts:
            raise ToolInvocationBoundaryError(
                "TOOL_ATTEMPT_JOURNAL_MISMATCH",
                "cannot override a missing physical Tool attempt",
            )
        last = entry.attempts[-1]
        result = self._generated_result(
            tool_call_id=logical_tool_call_id,
            tool_id=entry.tool_id,
            status=ToolExecutionStatus.UNKNOWN,
            error_code=error_code,
            reason_codes=(error_code,),
            attempt=last.physical_attempt,
        )
        updated_attempt = replace(
            last,
            result=result,
            raw_result=last.raw_result or last.result,
        )
        updated_entry = replace(
            entry,
            result=result,
            raw_result=last.raw_result or last.result,
            attempts=(*entry.attempts[:-1], updated_attempt),
        )
        for index, current in enumerate(self._journal):
            if current.tool_call_id == logical_tool_call_id:
                self._journal[index] = updated_entry
                break
        return result

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

        # 基线单次物理尝试同样先收窄 Tool 定义与实现，避免 union 方法调用。
        tool_implementation = resolved.implementation_ref
        if (
            resolved.kind is not CapabilityKind.TOOL
            or not isinstance(resolved.definition, ToolDefinition)
            or not isinstance(tool_implementation, ToolImplementation)
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

        await self._authorize_recovery_side_effect()

        (
            concurrency_admission,
            inflight_handle,
            admission_reasons,
        ) = await self._begin_physical_tool_operation(
            resolved=resolved,
            logical_tool_call_id=logical_tool_call_id,
            physical_attempt=physical_attempt,
        )
        if admission_reasons:
            error_code = (
                "RESOURCE_LOCK_BUSY"
                if concurrency_admission is not None
                and concurrency_admission.status is ToolConcurrencyAdmissionStatus.BUSY
                else admission_reasons[0]
            )
            result = self._generated_result(
                tool_call_id=logical_tool_call_id,
                tool_id=tool_id,
                status=ToolExecutionStatus.UNKNOWN,
                error_code=error_code,
                reason_codes=admission_reasons,
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

        try:
            raw_result = await tool_implementation.invoke(
                request,
                self._execution_context,
            )
        except Exception:  # noqa: BLE001
            completion_ok = await self._complete_physical_tool_operation(
                concurrency_admission=concurrency_admission,
                inflight_handle=inflight_handle,
            )
            error_code = (
                "TOOL_EXECUTION_EXCEPTION"
                if completion_ok
                else "INFLIGHT_TOOL_COMPLETION_UNKNOWN"
            )
            result = self._generated_result(
                tool_call_id=logical_tool_call_id,
                tool_id=tool_id,
                status=ToolExecutionStatus.UNKNOWN,
                error_code=error_code,
                reason_codes=(error_code,),
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

        completion_ok = await self._complete_physical_tool_operation(
            concurrency_admission=concurrency_admission,
            inflight_handle=inflight_handle,
        )
        raw_identity_valid = (
            isinstance(raw_result, M5ToolResult)
            and isinstance(raw_result.status, ToolExecutionStatus)
            and raw_result.tool_call_id == logical_tool_call_id
            and raw_result.tool_id == tool_id
            and raw_result.attempt == physical_attempt
        )
        if not completion_ok:
            error_code = "INFLIGHT_TOOL_COMPLETION_UNKNOWN"
            result = self._generated_result(
                tool_call_id=logical_tool_call_id,
                tool_id=tool_id,
                status=ToolExecutionStatus.UNKNOWN,
                error_code=error_code,
                reason_codes=(error_code,),
                attempt=physical_attempt,
            )
            return self._append_journal_attempt(
                resolved=resolved,
                result=result,
                raw_result=raw_result if raw_identity_valid else None,
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

    async def _begin_physical_tool_operation(
        self,
        *,
        resolved: ResolvedCapability,
        logical_tool_call_id: str,
        physical_attempt: int,
    ) -> tuple[
        ToolConcurrencyAdmissionDecision | None,
        InFlightOperationHandle | None,
        tuple[str, ...],
    ]:
        concurrency = self._tool_concurrency_runtime
        if concurrency is not None:
            parent_handle_id = self._inflight_parent_handle_id
            definition = resolved.definition
            if parent_handle_id is None or not isinstance(definition, ToolDefinition):
                reason = "TOOL_CONCURRENCY_AUTHORITY_MISSING"
                self._record_fault(reason)
                return None, None, (reason,)
            try:
                admission = await concurrency.admit(
                    tool_definition=definition,
                    tool_id=resolved.capability_id,
                    tool_version=resolved.version,
                    execution_context=self._execution_context,
                    step_execution_id=self._step_execution_id,
                    parent_handle_id=parent_handle_id,
                    logical_tool_call_id=logical_tool_call_id,
                    physical_attempt=physical_attempt,
                )
            except Exception:  # noqa: BLE001
                admission = None
            if admission is None:
                reason = "TOOL_CONCURRENCY_ADMISSION_UNKNOWN"
                self._record_fault(reason)
                return None, None, (reason,)
            if admission.status is ToolConcurrencyAdmissionStatus.ADMITTED:
                return admission, admission.handle, ()
            reasons = admission.reason_codes or ("TOOL_CONCURRENCY_ADMISSION_UNKNOWN",)
            for reason in reasons:
                self._record_fault(reason)
            return admission, admission.handle, reasons

        try:
            handle = await self._begin_tool_inflight(
                resolved=resolved,
                logical_tool_call_id=logical_tool_call_id,
                physical_attempt=physical_attempt,
            )
        except ToolInvocationBoundaryError as exc:
            return None, None, (exc.reason_code,)
        return None, handle, ()

    async def _complete_physical_tool_operation(
        self,
        *,
        concurrency_admission: ToolConcurrencyAdmissionDecision | None,
        inflight_handle: InFlightOperationHandle | None,
    ) -> bool:
        if concurrency_admission is not None:
            concurrency = self._tool_concurrency_runtime
            if concurrency is None:
                self._record_fault("TOOL_CONCURRENCY_RUNTIME_MISSING")
                return False
            try:
                decision = await concurrency.complete_after_operation(
                    concurrency_admission,
                    completed_at=self._inflight_now(),
                )
            except Exception:  # noqa: BLE001
                decision = None
            if (
                decision is not None
                and decision.status is ToolConcurrencyCompletionStatus.COMPLETED
            ):
                return True
            reasons = (
                decision.reason_codes
                if decision is not None
                else ("TOOL_CONCURRENCY_COMPLETION_UNKNOWN",)
            )
            for reason in reasons:
                self._record_fault(reason)
            return False
        return await self._complete_tool_inflight(inflight_handle)

    async def _begin_tool_inflight(
        self,
        *,
        resolved: ResolvedCapability,
        logical_tool_call_id: str,
        physical_attempt: int,
    ) -> InFlightOperationHandle | None:
        registry = self._inflight_registry
        if registry is None:
            return None

        factory = self._inflight_identifier_factory
        parent_handle_id = self._inflight_parent_handle_id
        if factory is None or parent_handle_id is None:
            self._record_fault("INFLIGHT_TOOL_AUTHORITY_MISSING")
            raise ToolInvocationBoundaryError(
                "INFLIGHT_TOOL_AUTHORITY_MISSING",
                "Tool in-flight authority is incomplete",
            )

        started_at = self._inflight_now()
        try:
            handle_id = factory.new_tool_handle_id(
                execution_id=self._execution_context.execution_id,
                step_execution_id=self._step_execution_id,
                parent_handle_id=parent_handle_id,
                tool_call_id=logical_tool_call_id,
                physical_attempt=physical_attempt,
            )
        except Exception as exc:
            self._record_fault("INFLIGHT_TOOL_HANDLE_ID_UNKNOWN")
            raise ToolInvocationBoundaryError(
                "INFLIGHT_TOOL_HANDLE_ID_UNKNOWN",
                "Tool in-flight handle id factory failed",
            ) from exc
        if not isinstance(handle_id, str) or not handle_id.strip():
            self._record_fault("INFLIGHT_TOOL_HANDLE_ID_UNKNOWN")
            raise ToolInvocationBoundaryError(
                "INFLIGHT_TOOL_HANDLE_ID_UNKNOWN",
                "Tool in-flight handle id factory returned invalid id",
            )

        handle = InFlightOperationHandle(
            operation_handle_id=handle_id,
            execution_id=self._execution_context.execution_id,
            step_execution_id=self._step_execution_id,
            parent_handle_id=parent_handle_id,
            kind=InFlightOperationKind.TOOL,
            capability_id=resolved.capability_id,
            capability_version=resolved.version,
            tool_call_id=logical_tool_call_id,
            started_at=started_at,
        )
        try:
            registered = await registry.register(handle)
        except Exception as exc:
            self._record_fault("INFLIGHT_TOOL_REGISTRATION_UNKNOWN")
            raise ToolInvocationBoundaryError(
                "INFLIGHT_TOOL_REGISTRATION_UNKNOWN",
                "Tool in-flight registry failed",
            ) from exc
        if registered is not True:
            self._record_fault("INFLIGHT_TOOL_REGISTRATION_CONFLICT")
            raise ToolInvocationBoundaryError(
                "INFLIGHT_TOOL_REGISTRATION_CONFLICT",
                "Tool in-flight handle could not be uniquely registered",
            )
        return handle

    async def _complete_tool_inflight(
        self,
        handle: InFlightOperationHandle | None,
    ) -> bool:
        if handle is None:
            return True
        registry = self._inflight_registry
        if registry is None:
            self._record_fault("INFLIGHT_TOOL_AUTHORITY_MISSING")
            return False
        try:
            completed = await registry.complete(
                handle.operation_handle_id,
                completed_at=self._inflight_now(),
            )
        except Exception:  # noqa: BLE001
            completed = False
        if completed is not True:
            self._record_fault("INFLIGHT_TOOL_COMPLETION_UNKNOWN")
            return False
        return True

    def _inflight_now(self) -> datetime:
        try:
            value = self._inflight_clock()
        except Exception as exc:
            self._record_fault("INFLIGHT_CLOCK_UNKNOWN")
            raise ToolInvocationBoundaryError(
                "INFLIGHT_CLOCK_UNKNOWN",
                "in-flight clock failed",
            ) from exc
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            self._record_fault("INFLIGHT_CLOCK_UNKNOWN")
            raise ToolInvocationBoundaryError(
                "INFLIGHT_CLOCK_UNKNOWN",
                "in-flight clock must return timezone-aware datetime",
            )
        return value

    async def _authorize_recovery_side_effect(self) -> None:
        guard = self._side_effect_admission_guard
        if guard is None:
            return
        try:
            decision = await guard.authorize(
                execution_id=self._execution_context.execution_id,
            )
        except Exception as exc:  # noqa: BLE001
            self._record_fault("RECOVERY_SIDE_EFFECT_EPOCH_VALIDATION_UNKNOWN")
            raise ToolInvocationBoundaryError(
                "RECOVERY_SIDE_EFFECT_EPOCH_VALIDATION_UNKNOWN",
                "recovery side-effect admission guard failed",
            ) from exc
        if decision.status is RecoverySideEffectAdmissionStatus.ALLOWED:
            return
        reason = (
            "RECOVERY_SIDE_EFFECT_EPOCH_STALE"
            if decision.status is RecoverySideEffectAdmissionStatus.STALE
            else "RECOVERY_SIDE_EFFECT_EPOCH_VALIDATION_UNKNOWN"
        )
        self._record_fault(reason)
        raise ToolInvocationBoundaryError(
            reason,
            "stale or unknown recovery epoch cannot admit physical Tool attempt",
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
        reliability_runtime: ToolReliabilityRuntime | None = None,
        inflight_registry: InFlightOperationRegistry | None = None,
        inflight_identifier_factory: InFlightOperationIdentifierFactory | None = None,
        inflight_clock: Callable[[], datetime] | None = None,
        execution_concurrency_runtime: ExecutionConcurrencyRuntime | None = None,
        tool_concurrency_runtime: ToolConcurrencyRuntime | None = None,
    ) -> None:
        self._permission_context_provider = permission_context_provider
        self._permission_evaluator = permission_evaluator
        self._input_validator = input_validator
        self._output_validator = output_validator
        self._identifier_factory = identifier_factory
        self._reliability_runtime = reliability_runtime
        self._execution_concurrency_runtime = execution_concurrency_runtime
        self._tool_concurrency_runtime = tool_concurrency_runtime
        if tool_concurrency_runtime is not None:
            if (
                inflight_registry is not None
                and inflight_registry is not tool_concurrency_runtime.inflight_registry
            ):
                raise ValueError(
                    "Tool concurrency runtime must share owner in-flight registry"
                )
            if (
                inflight_identifier_factory is not None
                and inflight_identifier_factory
                is not tool_concurrency_runtime.inflight_identifier_factory
            ):
                raise ValueError(
                    "Tool concurrency runtime must share owner identifier factory"
                )
            inflight_registry = tool_concurrency_runtime.inflight_registry
            inflight_identifier_factory = (
                tool_concurrency_runtime.inflight_identifier_factory
            )
        if (inflight_registry is None) != (inflight_identifier_factory is None):
            raise ValueError(
                "owner in-flight tracking requires registry and identifier factory together"
            )
        self._inflight_registry = inflight_registry
        self._inflight_identifier_factory = inflight_identifier_factory
        self._inflight_clock = inflight_clock or (lambda: datetime.now(UTC))

    async def execute(
        self,
        *,
        approved_plan: ApprovedActionPlan,
        step: ActionStep,
        step_snapshot: StepLifecycleSnapshot,
        resolved: ResolvedStepCapabilities,
        execution_context: ExecutionContext,
        attempt_number: int = 1,
        prior_attempt_journal: tuple[ToolInvocationJournalEntry, ...] = (),
        owner_timeout_seconds: float | None = None,
        owner_timeout_runner: AsyncTimeoutRunner | None = None,
        side_effect_admission_guard: RecoverySideEffectAdmissionGuard | None = None,
    ) -> StepCapabilityExecutionOutcome:
        if attempt_number < 1:
            return self._outcome(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                status=CapabilityExecutionStatus.UNKNOWN,
                reason_codes=("STEP_ATTEMPT_NUMBER_INVALID",),
            )
        if (owner_timeout_seconds is None) != (owner_timeout_runner is None):
            return self._outcome(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                status=CapabilityExecutionStatus.UNKNOWN,
                reason_codes=("OWNER_TIMEOUT_CONFIGURATION_INVALID",),
            )
        if owner_timeout_seconds is not None and owner_timeout_seconds <= 0:
            return self._outcome(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                status=CapabilityExecutionStatus.UNKNOWN,
                reason_codes=("OWNER_TIMEOUT_CONFIGURATION_INVALID",),
            )

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

        admission_error = await self._owner_side_effect_admission_error(
            execution_context=execution_context,
            guard=side_effect_admission_guard,
        )
        if admission_error is not None:
            return self._outcome(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                status=CapabilityExecutionStatus.UNKNOWN,
                reason_codes=(admission_error,),
            )

        if self._execution_concurrency_runtime is not None:
            try:
                admission = await self._execution_concurrency_runtime.admit(
                    execution_context
                )
            except Exception:  # noqa: BLE001
                admission = None
            if admission is None:
                return self._outcome(
                    step=step,
                    step_snapshot=step_snapshot,
                    resolved=resolved,
                    status=CapabilityExecutionStatus.UNKNOWN,
                    reason_codes=("SESSION_EXECUTION_ADMISSION_UNKNOWN",),
                )
            if admission.status is ExecutionConcurrencyAdmissionStatus.BUSY:
                return self._outcome(
                    step=step,
                    step_snapshot=step_snapshot,
                    resolved=resolved,
                    status=CapabilityExecutionStatus.BLOCKED,
                    reason_codes=("SESSION_EXECUTION_LOCK_BUSY",),
                )
            if admission.status is not ExecutionConcurrencyAdmissionStatus.ADMITTED:
                return self._outcome(
                    step=step,
                    step_snapshot=step_snapshot,
                    resolved=resolved,
                    status=CapabilityExecutionStatus.UNKNOWN,
                    reason_codes=admission.reason_codes,
                )

        owner_handle, owner_error = await self._begin_owner_inflight(
            resolved=resolved,
            step_snapshot=step_snapshot,
            execution_context=execution_context,
        )
        if owner_error is not None:
            return self._outcome(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                status=CapabilityExecutionStatus.UNKNOWN,
                reason_codes=(owner_error,),
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
                step_id=step.step_id,
                step_attempt_number=attempt_number,
                prior_attempt_journal=prior_attempt_journal,
                reliability_runtime=self._reliability_runtime,
                inflight_registry=(
                    self._inflight_registry if owner_handle is not None else None
                ),
                inflight_identifier_factory=(
                    self._inflight_identifier_factory
                    if owner_handle is not None
                    else None
                ),
                inflight_parent_handle_id=(
                    owner_handle.operation_handle_id
                    if owner_handle is not None
                    else None
                ),
                inflight_clock=self._inflight_clock,
                tool_concurrency_runtime=self._tool_concurrency_runtime,
                side_effect_admission_guard=side_effect_admission_guard,
            )
        except (TypeError, ValueError):
            completion_ok = await self._complete_owner_inflight(owner_handle)
            reason = (
                "TOOL_GATEWAY_CONSTRUCTION_FAILED"
                if completion_ok
                else "INFLIGHT_OWNER_COMPLETION_UNKNOWN"
            )
            return self._outcome(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                status=CapabilityExecutionStatus.UNKNOWN,
                reason_codes=(reason,),
            )

        if resolved.execution_owner is CapabilityExecutionOwner.SKILL:
            outcome = await self._execute_skill(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                execution_context=execution_context,
                tool_invoker=tool_invoker,
                owner_timeout_seconds=owner_timeout_seconds,
                owner_timeout_runner=owner_timeout_runner,
            )
        else:
            outcome = await self._execute_workflow(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                execution_context=execution_context,
                tool_invoker=tool_invoker,
                owner_timeout_seconds=owner_timeout_seconds,
                owner_timeout_runner=owner_timeout_runner,
            )

        if self._owner_may_still_be_inflight(outcome):
            return outcome
        if not await self._complete_owner_inflight(owner_handle):
            return replace(
                outcome,
                status=CapabilityExecutionStatus.UNKNOWN,
                reason_codes=("INFLIGHT_OWNER_COMPLETION_UNKNOWN",),
            )
        return outcome

    async def resume_workflow_from_checkpoint(
        self,
        *,
        approved_plan: ApprovedActionPlan,
        step: ActionStep,
        step_snapshot: StepLifecycleSnapshot,
        resolved: ResolvedStepCapabilities,
        execution_context: ExecutionContext,
        resume_request: WorkflowResumeRequest,
        attempt_number: int = 1,
        prior_attempt_journal: tuple[ToolInvocationJournalEntry, ...] = (),
        side_effect_admission_guard: RecoverySideEffectAdmissionGuard | None = None,
    ) -> StepCapabilityExecutionOutcome:
        """Resume the exact approved Workflow checkpoint through existing M5 gates."""

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
        workflow = resolved.workflow
        implementation = None if workflow is None else workflow.implementation_ref
        if (
            resolved.execution_owner is not CapabilityExecutionOwner.WORKFLOW
            or workflow is None
            or workflow.kind is not CapabilityKind.WORKFLOW
            or not isinstance(implementation, WorkflowRecoveryImplementation)
        ):
            return self._outcome(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                status=CapabilityExecutionStatus.BLOCKED,
                reason_codes=("WORKFLOW_RECOVERY_IMPLEMENTATION_INVALID",),
            )
        if (
            resume_request.execution_id != execution_context.execution_id
            or resume_request.step_execution_id != step_snapshot.step_execution_id
            or resume_request.workflow_id != workflow.capability_id
            or resume_request.workflow_version != workflow.version
        ):
            return self._outcome(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                status=CapabilityExecutionStatus.BLOCKED,
                reason_codes=("WORKFLOW_RESUME_AUTHORITY_MISMATCH",),
            )
        if attempt_number < 1:
            return self._outcome(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                status=CapabilityExecutionStatus.UNKNOWN,
                reason_codes=("STEP_ATTEMPT_NUMBER_INVALID",),
            )

        admission_error = await self._owner_side_effect_admission_error(
            execution_context=execution_context,
            guard=side_effect_admission_guard,
        )
        if admission_error is not None:
            return self._outcome(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                status=CapabilityExecutionStatus.UNKNOWN,
                reason_codes=(admission_error,),
            )

        if self._execution_concurrency_runtime is not None:
            try:
                admission = await self._execution_concurrency_runtime.admit(
                    execution_context
                )
            except Exception:  # noqa: BLE001
                admission = None
            if admission is None:
                return self._outcome(
                    step=step,
                    step_snapshot=step_snapshot,
                    resolved=resolved,
                    status=CapabilityExecutionStatus.UNKNOWN,
                    reason_codes=("SESSION_EXECUTION_ADMISSION_UNKNOWN",),
                )
            if admission.status is ExecutionConcurrencyAdmissionStatus.BUSY:
                return self._outcome(
                    step=step,
                    step_snapshot=step_snapshot,
                    resolved=resolved,
                    status=CapabilityExecutionStatus.BLOCKED,
                    reason_codes=("SESSION_EXECUTION_LOCK_BUSY",),
                )
            if admission.status is not ExecutionConcurrencyAdmissionStatus.ADMITTED:
                return self._outcome(
                    step=step,
                    step_snapshot=step_snapshot,
                    resolved=resolved,
                    status=CapabilityExecutionStatus.UNKNOWN,
                    reason_codes=admission.reason_codes,
                )

        owner_handle, owner_error = await self._begin_owner_inflight(
            resolved=resolved,
            step_snapshot=step_snapshot,
            execution_context=execution_context,
            workflow_instance_id=resume_request.workflow_instance_id,
        )
        if owner_error is not None:
            return self._outcome(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                status=CapabilityExecutionStatus.UNKNOWN,
                reason_codes=(owner_error,),
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
                step_id=step.step_id,
                step_attempt_number=attempt_number,
                prior_attempt_journal=prior_attempt_journal,
                reliability_runtime=self._reliability_runtime,
                inflight_registry=(
                    self._inflight_registry if owner_handle is not None else None
                ),
                inflight_identifier_factory=(
                    self._inflight_identifier_factory
                    if owner_handle is not None
                    else None
                ),
                inflight_parent_handle_id=(
                    owner_handle.operation_handle_id
                    if owner_handle is not None
                    else None
                ),
                inflight_clock=self._inflight_clock,
                tool_concurrency_runtime=self._tool_concurrency_runtime,
                side_effect_admission_guard=side_effect_admission_guard,
            )
        except (TypeError, ValueError):
            await self._complete_owner_inflight(owner_handle)
            return self._outcome(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                status=CapabilityExecutionStatus.UNKNOWN,
                reason_codes=("TOOL_GATEWAY_CONSTRUCTION_FAILED",),
            )

        try:
            result = await implementation.resume_from_checkpoint(
                resume_request,
                execution_context,
                tool_invoker,
            )
        except Exception:  # noqa: BLE001
            reason_codes = self._exception_reasons(
                tool_invoker,
                default="WORKFLOW_RECOVERY_EXECUTION_EXCEPTION",
            )
            outcome = self._outcome(
                step=step,
                step_snapshot=step_snapshot,
                resolved=resolved,
                status=self._fault_status(tool_invoker),
                reason_codes=reason_codes,
                tool_results=self._journal_results(tool_invoker),
                tool_journal=tool_invoker.entries(),
            )
        else:
            journal_results = self._journal_results(tool_invoker)
            if (
                not isinstance(result, M5WorkflowResult)
                or not isinstance(result.status, WorkflowExecutionStatus)
                or result.workflow_id != resume_request.workflow_id
                or result.workflow_instance_id != resume_request.workflow_instance_id
            ):
                outcome = self._outcome(
                    step=step,
                    step_snapshot=step_snapshot,
                    resolved=resolved,
                    status=CapabilityExecutionStatus.UNKNOWN,
                    reason_codes=("WORKFLOW_RECOVERY_RESULT_INVALID",),
                    tool_results=journal_results,
                    tool_journal=tool_invoker.entries(),
                )
            else:
                boundary = self._boundary_outcome(
                    step=step,
                    step_snapshot=step_snapshot,
                    resolved=resolved,
                    tool_invoker=tool_invoker,
                    tool_results=journal_results,
                    workflow_result=result,
                )
                if boundary is not None:
                    outcome = boundary
                elif result.tool_results and result.tool_results != journal_results:
                    outcome = self._outcome(
                        step=step,
                        step_snapshot=step_snapshot,
                        resolved=resolved,
                        status=CapabilityExecutionStatus.UNKNOWN,
                        reason_codes=("CAPABILITY_RESULT_TOOL_TRACE_MISMATCH",),
                        workflow_result=result,
                        tool_results=journal_results,
                        tool_journal=tool_invoker.entries(),
                    )
                else:
                    normalized = replace(result, tool_results=journal_results)
                    status = (
                        CapabilityExecutionStatus.WAITING
                        if normalized.status is WorkflowExecutionStatus.WAITING
                        else CapabilityExecutionStatus.EXECUTED
                    )
                    outcome = self._outcome(
                        step=step,
                        step_snapshot=step_snapshot,
                        resolved=resolved,
                        status=status,
                        reason_codes=(
                            "WORKFLOW_RECOVERY_WAITING"
                            if status is CapabilityExecutionStatus.WAITING
                            else "WORKFLOW_RESUMED"
                        ,),
                        workflow_result=normalized,
                        tool_results=journal_results,
                        tool_journal=tool_invoker.entries(),
                    )

        if self._owner_may_still_be_inflight(outcome):
            return outcome
        if not await self._complete_owner_inflight(owner_handle):
            return replace(
                outcome,
                status=CapabilityExecutionStatus.UNKNOWN,
                reason_codes=("INFLIGHT_OWNER_COMPLETION_UNKNOWN",),
            )
        return outcome

    @staticmethod
    def _owner_may_still_be_inflight(
        outcome: StepCapabilityExecutionOutcome,
    ) -> bool:
        if outcome.skill_result is not None and (
            outcome.skill_result.status is SkillExecutionStatus.TIMEOUT
        ):
            return True
        if outcome.workflow_result is not None and outcome.workflow_result.status in {
            WorkflowExecutionStatus.CREATED,
            WorkflowExecutionStatus.RUNNING,
            WorkflowExecutionStatus.WAITING,
            WorkflowExecutionStatus.TIMEOUT,
        }:
            return True
        return bool(
            set(outcome.reason_codes)
            & {
                "SKILL_TIMEOUT_RUNNER_INVALID_RESULT",
                "SKILL_TIMEOUT_BOUNDARY_UNKNOWN",
                "WORKFLOW_TIMEOUT_RUNNER_INVALID_RESULT",
                "WORKFLOW_TIMEOUT_BOUNDARY_UNKNOWN",
            }
        )

    @staticmethod
    async def _owner_side_effect_admission_error(
        *,
        execution_context: ExecutionContext,
        guard: RecoverySideEffectAdmissionGuard | None,
    ) -> str | None:
        if guard is None:
            return None
        try:
            decision = await guard.authorize(
                execution_id=execution_context.execution_id,
            )
        except Exception:  # noqa: BLE001
            return "RECOVERY_SIDE_EFFECT_EPOCH_VALIDATION_UNKNOWN"
        if decision.status is RecoverySideEffectAdmissionStatus.ALLOWED:
            return None
        if decision.status is RecoverySideEffectAdmissionStatus.STALE:
            return "RECOVERY_SIDE_EFFECT_EPOCH_STALE"
        return "RECOVERY_SIDE_EFFECT_EPOCH_VALIDATION_UNKNOWN"

    async def _begin_owner_inflight(
        self,
        *,
        resolved: ResolvedStepCapabilities,
        step_snapshot: StepLifecycleSnapshot,
        execution_context: ExecutionContext,
        workflow_instance_id: str | None = None,
    ) -> tuple[InFlightOperationHandle | None, str | None]:
        registry = self._inflight_registry
        factory = self._inflight_identifier_factory
        if registry is None and factory is None:
            return None, None
        if registry is None or factory is None:
            return None, "INFLIGHT_OWNER_AUTHORITY_MISSING"

        capability: ResolvedCapability | None
        kind: InFlightOperationKind
        if resolved.execution_owner is CapabilityExecutionOwner.SKILL:
            capability = resolved.skill
            kind = InFlightOperationKind.SKILL
        elif resolved.execution_owner is CapabilityExecutionOwner.WORKFLOW:
            capability = resolved.workflow
            kind = InFlightOperationKind.WORKFLOW
        else:
            return None, "INFLIGHT_OWNER_KIND_INVALID"

        if capability is None:
            return None, "INFLIGHT_OWNER_BINDING_INVALID"

        started_at = self._owner_inflight_now()
        if started_at is None:
            return None, "INFLIGHT_CLOCK_UNKNOWN"
        try:
            handle_id = factory.new_owner_handle_id(
                execution_id=execution_context.execution_id,
                step_execution_id=step_snapshot.step_execution_id,
                kind=kind,
                capability_id=capability.capability_id,
            )
        except Exception:  # noqa: BLE001
            return None, "INFLIGHT_OWNER_HANDLE_ID_UNKNOWN"
        if not isinstance(handle_id, str) or not handle_id.strip():
            return None, "INFLIGHT_OWNER_HANDLE_ID_UNKNOWN"

        handle = InFlightOperationHandle(
            operation_handle_id=handle_id,
            execution_id=execution_context.execution_id,
            step_execution_id=step_snapshot.step_execution_id,
            kind=kind,
            capability_id=capability.capability_id,
            capability_version=capability.version,
            started_at=started_at,
            workflow_instance_id=(
                workflow_instance_id
                if kind is InFlightOperationKind.WORKFLOW
                else None
            ),
        )
        try:
            registered = await registry.register(handle)
        except Exception:  # noqa: BLE001
            registered = False
        if registered is not True:
            return None, "INFLIGHT_OWNER_REGISTRATION_UNKNOWN"
        return handle, None

    async def _complete_owner_inflight(
        self,
        handle: InFlightOperationHandle | None,
    ) -> bool:
        if handle is None:
            return True
        registry = self._inflight_registry
        if registry is None:
            return False
        completed_at = self._owner_inflight_now()
        if completed_at is None:
            return False
        try:
            return (
                await registry.complete(
                    handle.operation_handle_id,
                    completed_at=completed_at,
                )
                is True
            )
        except Exception:  # noqa: BLE001
            return False

    def _owner_inflight_now(self) -> datetime | None:
        try:
            value = self._inflight_clock()
        except Exception:  # noqa: BLE001
            return None
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            return None
        return value

    async def _execute_skill(
        self,
        *,
        step: ActionStep,
        step_snapshot: StepLifecycleSnapshot,
        resolved: ResolvedStepCapabilities,
        execution_context: ExecutionContext,
        tool_invoker: CoreApprovedToolInvoker,
        owner_timeout_seconds: float | None,
        owner_timeout_runner: AsyncTimeoutRunner | None,
    ) -> StepCapabilityExecutionOutcome:
        skill = resolved.skill
        skill_implementation = None if skill is None else skill.implementation_ref
        if (
            skill is None
            or skill.kind is not CapabilityKind.SKILL
            or not isinstance(skill_implementation, SkillImplementation)
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
            if owner_timeout_seconds is None:
                result = await skill_implementation.execute(
                    request,
                    execution_context,
                    tool_invoker,
                )
            else:
                if owner_timeout_runner is None:
                    raise RuntimeError("owner timeout runner is missing")
                timeout_result = await owner_timeout_runner.run(
                    timeout_seconds=owner_timeout_seconds,
                    operation=lambda: skill_implementation.execute(
                        request,
                        execution_context,
                        tool_invoker,
                    ),
                )
                if not isinstance(timeout_result, TimeoutRunResult) or not isinstance(
                    timeout_result.status, TimeoutRunStatus
                ):
                    return self._outcome(
                        step=step,
                        step_snapshot=step_snapshot,
                        resolved=resolved,
                        status=CapabilityExecutionStatus.UNKNOWN,
                        reason_codes=("SKILL_TIMEOUT_RUNNER_INVALID_RESULT",),
                        tool_results=self._journal_results(tool_invoker),
                        tool_journal=tool_invoker.entries(),
                    )
                if timeout_result.status is TimeoutRunStatus.TIMED_OUT:
                    journal_results = self._journal_results(tool_invoker)
                    result = M5SkillResult(
                        skill_id=skill.capability_id,
                        status=SkillExecutionStatus.TIMEOUT,
                        tool_results=journal_results,
                        error="SKILL_TIMEOUT",
                    )
                elif timeout_result.status is TimeoutRunStatus.UNKNOWN:
                    return self._outcome(
                        step=step,
                        step_snapshot=step_snapshot,
                        resolved=resolved,
                        status=CapabilityExecutionStatus.UNKNOWN,
                        reason_codes=("SKILL_TIMEOUT_BOUNDARY_UNKNOWN",),
                        tool_results=self._journal_results(tool_invoker),
                        tool_journal=tool_invoker.entries(),
                    )
                else:
                    # COMPLETED 的 value 仍可能不是 Skill 结果，必须先收窄再赋值。
                    completed_skill_result = timeout_result.value
                    if not isinstance(completed_skill_result, M5SkillResult):
                        return self._outcome(
                            step=step,
                            step_snapshot=step_snapshot,
                            resolved=resolved,
                            status=CapabilityExecutionStatus.UNKNOWN,
                            reason_codes=("SKILL_RESULT_INVALID",),
                            tool_results=self._journal_results(tool_invoker),
                            tool_journal=tool_invoker.entries(),
                        )
                    result = completed_skill_result
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
        owner_timeout_seconds: float | None,
        owner_timeout_runner: AsyncTimeoutRunner | None,
    ) -> StepCapabilityExecutionOutcome:
        workflow = resolved.workflow
        workflow_implementation = (
            None if workflow is None else workflow.implementation_ref
        )
        if (
            workflow is None
            or workflow.kind is not CapabilityKind.WORKFLOW
            or not isinstance(workflow_implementation, WorkflowImplementation)
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
            if owner_timeout_seconds is None:
                result = await workflow_implementation.start(
                    request,
                    execution_context,
                    tool_invoker,
                )
            else:
                if owner_timeout_runner is None:
                    raise RuntimeError("owner timeout runner is missing")
                timeout_result = await owner_timeout_runner.run(
                    timeout_seconds=owner_timeout_seconds,
                    operation=lambda: workflow_implementation.start(
                        request,
                        execution_context,
                        tool_invoker,
                    ),
                )
                if not isinstance(timeout_result, TimeoutRunResult) or not isinstance(
                    timeout_result.status, TimeoutRunStatus
                ):
                    return self._outcome(
                        step=step,
                        step_snapshot=step_snapshot,
                        resolved=resolved,
                        status=CapabilityExecutionStatus.UNKNOWN,
                        reason_codes=("WORKFLOW_TIMEOUT_RUNNER_INVALID_RESULT",),
                        tool_results=self._journal_results(tool_invoker),
                        tool_journal=tool_invoker.entries(),
                    )
                if timeout_result.status is TimeoutRunStatus.TIMED_OUT:
                    result = M5WorkflowResult(
                        workflow_instance_id=workflow_instance_id,
                        workflow_id=workflow.capability_id,
                        status=WorkflowExecutionStatus.TIMEOUT,
                        tool_results=self._journal_results(tool_invoker),
                        error="WORKFLOW_START_TIMEOUT",
                    )
                elif timeout_result.status is TimeoutRunStatus.UNKNOWN:
                    return self._outcome(
                        step=step,
                        step_snapshot=step_snapshot,
                        resolved=resolved,
                        status=CapabilityExecutionStatus.UNKNOWN,
                        reason_codes=("WORKFLOW_TIMEOUT_BOUNDARY_UNKNOWN",),
                        tool_results=self._journal_results(tool_invoker),
                        tool_journal=tool_invoker.entries(),
                    )
                else:
                    # COMPLETED 的 value 仍可能不是 Workflow 结果，必须先收窄再赋值。
                    completed_workflow_result = timeout_result.value
                    if not isinstance(completed_workflow_result, M5WorkflowResult):
                        return self._outcome(
                            step=step,
                            step_snapshot=step_snapshot,
                            resolved=resolved,
                            status=CapabilityExecutionStatus.UNKNOWN,
                            reason_codes=("WORKFLOW_RESULT_INVALID",),
                            tool_results=self._journal_results(tool_invoker),
                            tool_journal=tool_invoker.entries(),
                        )
                    result = completed_workflow_result
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
