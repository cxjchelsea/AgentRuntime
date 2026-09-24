"""M5-IU6 Step-level reliability coordinator.

Coordinates already-frozen reliability authorities around the exact IU3-resolved
step owner. It never replans, substitutes capabilities, mutates step lifecycle,
aggregates ExecutionResult, or enters M6.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from runtime.contracts import ApprovedActionPlan
from runtime.contracts.execution import ExecutionContext
from runtime.contracts.planning import ActionStep
from runtime.execution.capability_execution import (
    CapabilityExecutionStatus,
    StepCapabilityExecutionOutcome,
    StepCapabilityExecutor,
)
from runtime.execution.capability_resolution import (
    CapabilityExecutionOwner,
    CapabilityKind,
    ResolvedCapability,
    ResolvedStepCapabilities,
)
from runtime.execution.foundation import StepLifecycleSnapshot
from runtime.execution.invocation import ToolInvocationJournalEntry
from runtime.execution.recovery import RecoverySideEffectAdmissionGuard
from runtime.execution.reliability import (
    ReliabilityCapabilityKind,
    ReplaySafetyDecision,
    ReplaySafetyStatus,
    ResolvedReliabilityPolicy,
    RetryDecision,
    RetryDecisionContext,
    RetryDecisionStatus,
    RetryTriggerStatus,
)
from runtime.execution.reliability_boundary import (
    StepAttemptSequenceDecision,
    StepAttemptSequenceStatus,
    StepFinalizationDecision,
    StepFinalizationDisposition,
    StepReliabilityDecision,
    StepReliabilityDisposition,
    StepReplaySafetyRequest,
)
from runtime.execution.reliability_runtime import StepReliabilityRuntime
from runtime.execution.result_collection import (
    StepAttemptObservation,
    StepAttemptStatus,
    StepResultCollectionError,
    StepResultCollector,
)
from runtime.registries.definitions import SkillDefinition, WorkflowDefinition


class StepReliabilityCoordinationError(RuntimeError):
    """Structural/integration failure while coordinating IU6 reliability."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        if not reason_code.strip():
            raise ValueError("reason_code must not be blank")
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class StepReliabilityRunResult:
    """IU6 internal result; not lifecycle mutation and not canonical ExecutionResult."""

    attempts: tuple[StepAttemptObservation, ...]
    reliability_decision: StepReliabilityDecision
    finalization_decision: StepFinalizationDecision
    owner_policy_identity: str | None = None

    def __post_init__(self) -> None:
        if not self.attempts:
            raise ValueError("Step reliability result requires at least one attempt")
        expected = 1
        for attempt in self.attempts:
            if attempt.attempt_number != expected:
                raise ValueError("Step reliability attempts must be contiguous from 1")
            expected += 1

    @property
    def final_observation(self) -> StepAttemptObservation:
        return self.attempts[-1]


@dataclass(frozen=True, slots=True)
class RecoveredStepReliabilityRunResult:
    """IU9 recovery segment executed through the existing IU6 authorities."""

    prior_attempt_number: int
    attempts: tuple[StepAttemptObservation, ...]
    reliability_decision: StepReliabilityDecision
    finalization_decision: StepFinalizationDecision
    owner_policy_identity: str | None = None

    def __post_init__(self) -> None:
        if self.prior_attempt_number < 1:
            raise ValueError("prior_attempt_number must be >= 1")
        if not self.attempts:
            raise ValueError("recovered reliability result requires attempts")
        expected = self.prior_attempt_number + 1
        for attempt in self.attempts:
            if attempt.attempt_number != expected:
                raise ValueError(
                    "recovered attempts must be contiguous after prior attempt"
                )
            expected += 1

    @property
    def final_observation(self) -> StepAttemptObservation:
        return self.attempts[-1]


class StepReliabilityCoordinator:
    """Execute/observe/retry one Step without owning lifecycle finalization."""

    def __init__(
        self,
        *,
        step_executor: StepCapabilityExecutor,
        result_collector: StepResultCollector,
        runtime: StepReliabilityRuntime,
    ) -> None:
        self._step_executor = step_executor
        self._result_collector = result_collector
        self._runtime = runtime

    async def run(
        self,
        *,
        approved_plan: ApprovedActionPlan,
        step: ActionStep,
        step_snapshot: StepLifecycleSnapshot,
        resolved: ResolvedStepCapabilities,
        execution_context: ExecutionContext,
    ) -> StepReliabilityRunResult:
        owner_policy, policy_error = self._resolve_owner_policy(resolved)
        attempts: list[StepAttemptObservation] = []
        attempt_number = 1
        prior_journal: tuple[ToolInvocationJournalEntry, ...] = ()

        while True:
            deadline_remaining, deadline_error = self._deadline_remaining(
                execution_context
            )
            if deadline_error is not None:
                outcome = self._unknown_outcome(
                    step=step,
                    step_snapshot=step_snapshot,
                    resolved=resolved,
                    reason_code=deadline_error,
                )
            elif deadline_remaining is not None and deadline_remaining <= 0:
                outcome = self._unknown_outcome(
                    step=step,
                    step_snapshot=step_snapshot,
                    resolved=resolved,
                    reason_code="EXECUTION_DEADLINE_EXPIRED",
                )
            elif policy_error is not None:
                outcome = self._unknown_outcome(
                    step=step,
                    step_snapshot=step_snapshot,
                    resolved=resolved,
                    reason_code=policy_error,
                )
            else:
                owner_timeout = self._effective_owner_timeout(
                    owner_policy=owner_policy,
                    deadline_remaining_seconds=deadline_remaining,
                )
                outcome = await self._step_executor.execute(
                    approved_plan=approved_plan,
                    step=step,
                    step_snapshot=step_snapshot,
                    resolved=resolved,
                    execution_context=execution_context,
                    attempt_number=attempt_number,
                    prior_attempt_journal=prior_journal,
                    owner_timeout_seconds=owner_timeout,
                    owner_timeout_runner=(
                        self._runtime.timeout_runner
                        if owner_timeout is not None
                        else None
                    ),
                )

            observed_at = self._clock_now()
            try:
                observation = self._result_collector.collect(
                    step_snapshot=step_snapshot,
                    outcome=outcome,
                    attempt_number=attempt_number,
                    observed_at=observed_at,
                )
            except StepResultCollectionError as exc:
                raise StepReliabilityCoordinationError(
                    exc.reason_code,
                    "IU5 result collection failed inside IU6 coordination",
                ) from exc
            attempts.append(observation)

            if attempt_number > 1 and not self._tool_operation_sequence_matches(
                prior_journal=prior_journal,
                current_journal=observation.tool_journal,
            ):
                reliability_decision = StepReliabilityDecision(
                    disposition=StepReliabilityDisposition.ABORT_UNKNOWN,
                    reason_codes=("STEP_REPLAY_TOOL_SEQUENCE_DRIFT",),
                )
                return self._finish(
                    attempts=attempts,
                    observation=observation,
                    reliability_decision=reliability_decision,
                    owner_policy=owner_policy,
                )

            replay_safety: ReplaySafetyDecision | None = None
            retry_decision: RetryDecision | None = None
            if (
                observation.execution_owner is CapabilityExecutionOwner.SKILL
                and owner_policy is not None
            ):
                trigger = self._step_retry_trigger(observation.status)
                if trigger is not None and owner_policy.retry.enabled:
                    replay_safety = await self._step_replay_safety(
                        observation=observation,
                        owner_policy=owner_policy,
                    )
                    retry_decision = self._step_retry_decision(
                        observation=observation,
                        owner_policy=owner_policy,
                        trigger=trigger,
                        replay_safety=replay_safety,
                        execution_context=execution_context,
                    )

            reliability_decision = self._step_reliability_decision(
                observation=observation,
                replay_safety=replay_safety,
                retry_decision=retry_decision,
            )

            if reliability_decision.disposition is not StepReliabilityDisposition.RETRY:
                return self._finish(
                    attempts=attempts,
                    observation=observation,
                    reliability_decision=reliability_decision,
                    owner_policy=owner_policy,
                )

            if (
                observation.execution_owner is not CapabilityExecutionOwner.SKILL
                or owner_policy is None
                or replay_safety is None
                or replay_safety.status is not ReplaySafetyStatus.SAFE
                or retry_decision is None
                or retry_decision.status is not RetryDecisionStatus.RETRY
                or retry_decision.next_attempt != attempt_number + 1
                or reliability_decision.next_attempt != attempt_number + 1
                or retry_decision.next_attempt > owner_policy.retry.max_attempts
            ):
                reliability_decision = StepReliabilityDecision(
                    disposition=StepReliabilityDisposition.ABORT_UNKNOWN,
                    reason_codes=("STEP_RETRY_AUTHORITY_INCONSISTENT",),
                )
                return self._finish(
                    attempts=attempts,
                    observation=observation,
                    reliability_decision=reliability_decision,
                    owner_policy=owner_policy,
                )

            try:
                if retry_decision.backoff_seconds:
                    await self._runtime.retry_sleeper.sleep(
                        retry_decision.backoff_seconds
                    )
            except Exception:  # noqa: BLE001
                reliability_decision = StepReliabilityDecision(
                    disposition=StepReliabilityDisposition.ABORT_UNKNOWN,
                    reason_codes=("STEP_RETRY_BACKOFF_FAILURE",),
                )
                return self._finish(
                    attempts=attempts,
                    observation=observation,
                    reliability_decision=reliability_decision,
                    owner_policy=owner_policy,
                )

            remaining_after_backoff, deadline_error = self._deadline_remaining(
                execution_context
            )
            if deadline_error is not None or (
                remaining_after_backoff is not None and remaining_after_backoff <= 0
            ):
                reliability_decision = StepReliabilityDecision(
                    disposition=StepReliabilityDisposition.ABORT_UNKNOWN,
                    reason_codes=(deadline_error or "STEP_RETRY_DEADLINE_EXPIRED",),
                )
                return self._finish(
                    attempts=attempts,
                    observation=observation,
                    reliability_decision=reliability_decision,
                    owner_policy=owner_policy,
                )

            sequence = await self._claim_next_attempt(
                step_execution_id=observation.step_execution_id,
                expected_current_attempt=attempt_number,
            )
            if (
                sequence.status is not StepAttemptSequenceStatus.CLAIMED
                or sequence.next_attempt != attempt_number + 1
                or sequence.next_attempt != retry_decision.next_attempt
            ):
                reliability_decision = StepReliabilityDecision(
                    disposition=StepReliabilityDisposition.ABORT_UNKNOWN,
                    reason_codes=("STEP_ATTEMPT_SEQUENCE_NOT_CLAIMED",),
                )
                return self._finish(
                    attempts=attempts,
                    observation=observation,
                    reliability_decision=reliability_decision,
                    owner_policy=owner_policy,
                )

            prior_journal = observation.tool_journal
            attempt_number = sequence.next_attempt

    async def run_recovered_retry(
        self,
        *,
        approved_plan: ApprovedActionPlan,
        step: ActionStep,
        step_snapshot: StepLifecycleSnapshot,
        resolved: ResolvedStepCapabilities,
        execution_context: ExecutionContext,
        expected_current_attempt: int,
        prior_attempt_journal: tuple[ToolInvocationJournalEntry, ...],
        side_effect_admission_guard: RecoverySideEffectAdmissionGuard,
    ) -> RecoveredStepReliabilityRunResult:
        """Continue one crash-recovered Skill through the existing IU6 authorities."""

        if resolved.execution_owner is not CapabilityExecutionOwner.SKILL:
            raise StepReliabilityCoordinationError(
                "RECOVERY_RETRY_REQUIRES_SKILL_OWNER",
                "recovered retry may execute only an exact Skill owner",
            )
        if expected_current_attempt < 1:
            raise StepReliabilityCoordinationError(
                "RECOVERY_RETRY_ATTEMPT_INVALID",
                "expected_current_attempt must be >= 1",
            )

        owner_policy, policy_error = self._resolve_owner_policy(resolved)
        if owner_policy is None or policy_error is not None:
            raise StepReliabilityCoordinationError(
                policy_error or "RECOVERY_SKILL_POLICY_UNKNOWN",
                "exact Skill reliability policy is required for recovery retry",
            )

        sequence = await self._claim_next_attempt(
            step_execution_id=step_snapshot.step_execution_id,
            expected_current_attempt=expected_current_attempt,
        )
        if (
            sequence.status is not StepAttemptSequenceStatus.CLAIMED
            or sequence.next_attempt != expected_current_attempt + 1
        ):
            raise StepReliabilityCoordinationError(
                "STEP_ATTEMPT_SEQUENCE_NOT_CLAIMED",
                "recovery retry could not claim the exact next Step attempt",
            )

        attempts: list[StepAttemptObservation] = []
        attempt_number = sequence.next_attempt
        prior_journal = prior_attempt_journal

        while True:
            deadline_remaining, deadline_error = self._deadline_remaining(
                execution_context
            )
            if deadline_error is not None:
                outcome = self._unknown_outcome(
                    step=step,
                    step_snapshot=step_snapshot,
                    resolved=resolved,
                    reason_code=deadline_error,
                )
            elif deadline_remaining is not None and deadline_remaining <= 0:
                outcome = self._unknown_outcome(
                    step=step,
                    step_snapshot=step_snapshot,
                    resolved=resolved,
                    reason_code="EXECUTION_DEADLINE_EXPIRED",
                )
            else:
                owner_timeout = self._effective_owner_timeout(
                    owner_policy=owner_policy,
                    deadline_remaining_seconds=deadline_remaining,
                )
                outcome = await self._step_executor.execute(
                    approved_plan=approved_plan,
                    step=step,
                    step_snapshot=step_snapshot,
                    resolved=resolved,
                    execution_context=execution_context,
                    attempt_number=attempt_number,
                    prior_attempt_journal=prior_journal,
                    owner_timeout_seconds=owner_timeout,
                    owner_timeout_runner=(
                        self._runtime.timeout_runner
                        if owner_timeout is not None
                        else None
                    ),
                    side_effect_admission_guard=side_effect_admission_guard,
                )

            observed_at = self._clock_now()
            try:
                observation = self._result_collector.collect(
                    step_snapshot=step_snapshot,
                    outcome=outcome,
                    attempt_number=attempt_number,
                    observed_at=observed_at,
                )
            except StepResultCollectionError as exc:
                raise StepReliabilityCoordinationError(
                    exc.reason_code,
                    "IU5 result collection failed during recovered IU6 retry",
                ) from exc
            attempts.append(observation)

            if not self._tool_operation_sequence_matches(
                prior_journal=prior_journal,
                current_journal=observation.tool_journal,
            ):
                decision = StepReliabilityDecision(
                    disposition=StepReliabilityDisposition.ABORT_UNKNOWN,
                    reason_codes=("STEP_REPLAY_TOOL_SEQUENCE_DRIFT",),
                )
                return self._finish_recovered(
                    prior_attempt_number=expected_current_attempt,
                    attempts=attempts,
                    observation=observation,
                    reliability_decision=decision,
                    owner_policy=owner_policy,
                )

            replay_safety: ReplaySafetyDecision | None = None
            retry_decision: RetryDecision | None = None
            trigger = self._step_retry_trigger(observation.status)
            if trigger is not None and owner_policy.retry.enabled:
                replay_safety = await self._step_replay_safety(
                    observation=observation,
                    owner_policy=owner_policy,
                )
                retry_decision = self._step_retry_decision(
                    observation=observation,
                    owner_policy=owner_policy,
                    trigger=trigger,
                    replay_safety=replay_safety,
                    execution_context=execution_context,
                )

            reliability_decision = self._step_reliability_decision(
                observation=observation,
                replay_safety=replay_safety,
                retry_decision=retry_decision,
            )
            if reliability_decision.disposition is not StepReliabilityDisposition.RETRY:
                return self._finish_recovered(
                    prior_attempt_number=expected_current_attempt,
                    attempts=attempts,
                    observation=observation,
                    reliability_decision=reliability_decision,
                    owner_policy=owner_policy,
                )

            if (
                replay_safety is None
                or replay_safety.status is not ReplaySafetyStatus.SAFE
                or retry_decision is None
                or retry_decision.status is not RetryDecisionStatus.RETRY
                or retry_decision.next_attempt != attempt_number + 1
                or reliability_decision.next_attempt != attempt_number + 1
                or retry_decision.next_attempt > owner_policy.retry.max_attempts
            ):
                inconsistent = StepReliabilityDecision(
                    disposition=StepReliabilityDisposition.ABORT_UNKNOWN,
                    reason_codes=("STEP_RETRY_AUTHORITY_INCONSISTENT",),
                )
                return self._finish_recovered(
                    prior_attempt_number=expected_current_attempt,
                    attempts=attempts,
                    observation=observation,
                    reliability_decision=inconsistent,
                    owner_policy=owner_policy,
                )

            try:
                if retry_decision.backoff_seconds:
                    await self._runtime.retry_sleeper.sleep(
                        retry_decision.backoff_seconds
                    )
            except Exception:  # noqa: BLE001
                failed = StepReliabilityDecision(
                    disposition=StepReliabilityDisposition.ABORT_UNKNOWN,
                    reason_codes=("STEP_RETRY_BACKOFF_FAILURE",),
                )
                return self._finish_recovered(
                    prior_attempt_number=expected_current_attempt,
                    attempts=attempts,
                    observation=observation,
                    reliability_decision=failed,
                    owner_policy=owner_policy,
                )

            remaining_after_backoff, deadline_error = self._deadline_remaining(
                execution_context
            )
            if deadline_error is not None or (
                remaining_after_backoff is not None and remaining_after_backoff <= 0
            ):
                expired = StepReliabilityDecision(
                    disposition=StepReliabilityDisposition.ABORT_UNKNOWN,
                    reason_codes=(deadline_error or "STEP_RETRY_DEADLINE_EXPIRED",),
                )
                return self._finish_recovered(
                    prior_attempt_number=expected_current_attempt,
                    attempts=attempts,
                    observation=observation,
                    reliability_decision=expired,
                    owner_policy=owner_policy,
                )

            sequence = await self._claim_next_attempt(
                step_execution_id=observation.step_execution_id,
                expected_current_attempt=attempt_number,
            )
            if (
                sequence.status is not StepAttemptSequenceStatus.CLAIMED
                or sequence.next_attempt != attempt_number + 1
                or sequence.next_attempt != retry_decision.next_attempt
            ):
                failed = StepReliabilityDecision(
                    disposition=StepReliabilityDisposition.ABORT_UNKNOWN,
                    reason_codes=("STEP_ATTEMPT_SEQUENCE_NOT_CLAIMED",),
                )
                return self._finish_recovered(
                    prior_attempt_number=expected_current_attempt,
                    attempts=attempts,
                    observation=observation,
                    reliability_decision=failed,
                    owner_policy=owner_policy,
                )

            prior_journal = observation.tool_journal
            attempt_number = sequence.next_attempt

    def _finish_recovered(
        self,
        *,
        prior_attempt_number: int,
        attempts: list[StepAttemptObservation],
        observation: StepAttemptObservation,
        reliability_decision: StepReliabilityDecision,
        owner_policy: ResolvedReliabilityPolicy,
    ) -> RecoveredStepReliabilityRunResult:
        try:
            finalization = self._runtime.step_finalization_evaluator.evaluate(
                observation=observation,
                reliability_decision=reliability_decision,
            )
        except Exception:  # noqa: BLE001
            finalization = None
        if not isinstance(finalization, StepFinalizationDecision) or not isinstance(
            finalization.disposition,
            StepFinalizationDisposition,
        ):
            finalization = StepFinalizationDecision(
                disposition=StepFinalizationDisposition.UNKNOWN,
                reason_codes=("STEP_FINALIZATION_EVALUATOR_UNKNOWN",),
            )
        elif (
            reliability_decision.disposition
            in {
                StepReliabilityDisposition.ABORT_UNKNOWN,
                StepReliabilityDisposition.WAIT_RECOVERY,
                StepReliabilityDisposition.KEEP_RUNNING,
            }
            and finalization.disposition is StepFinalizationDisposition.FINALIZE
        ):
            finalization = StepFinalizationDecision(
                disposition=StepFinalizationDisposition.UNKNOWN,
                reason_codes=("STEP_FINALIZATION_AUTHORITY_INCONSISTENT",),
            )
        return RecoveredStepReliabilityRunResult(
            prior_attempt_number=prior_attempt_number,
            attempts=tuple(attempts),
            reliability_decision=reliability_decision,
            finalization_decision=finalization,
            owner_policy_identity=owner_policy.policy_identity,
        )

    def _resolve_owner_policy(
        self,
        resolved: ResolvedStepCapabilities,
    ) -> tuple[ResolvedReliabilityPolicy | None, str | None]:
        owner: ResolvedCapability | None
        capability_kind: ReliabilityCapabilityKind
        timeout_ref: str | None
        retry_ref: str | None
        idempotency_ref: str | None
        side_effect_ref: str | None

        if resolved.execution_owner is CapabilityExecutionOwner.NONE:
            return None, None
        if resolved.execution_owner is CapabilityExecutionOwner.SKILL:
            owner = resolved.skill
            if (
                owner is None
                or owner.kind is not CapabilityKind.SKILL
                or not isinstance(owner.definition, SkillDefinition)
            ):
                return None, "STEP_RELIABILITY_SKILL_BINDING_INVALID"
            capability_kind = ReliabilityCapabilityKind.SKILL
            timeout_ref = owner.definition.timeout_policy
            retry_ref = owner.definition.retry_policy
            idempotency_ref = owner.definition.idempotency_policy
            side_effect_ref = owner.definition.side_effect_level
        else:
            owner = resolved.workflow
            if (
                owner is None
                or owner.kind is not CapabilityKind.WORKFLOW
                or not isinstance(owner.definition, WorkflowDefinition)
            ):
                return None, "STEP_RELIABILITY_WORKFLOW_BINDING_INVALID"
            capability_kind = ReliabilityCapabilityKind.WORKFLOW
            timeout_ref = owner.definition.timeout_policy
            retry_ref = None
            idempotency_ref = None
            side_effect_ref = None

        try:
            policy = self._runtime.policy_resolver.resolve(
                capability_kind=capability_kind,
                capability_id=owner.capability_id,
                capability_version=owner.version,
                timeout_policy_ref=timeout_ref,
                retry_policy_ref=retry_ref,
                idempotency_policy_ref=idempotency_ref,
                side_effect_level_ref=side_effect_ref,
            )
        except Exception:  # noqa: BLE001
            return None, "STEP_RELIABILITY_POLICY_RESOLUTION_FAILED"
        if (
            not isinstance(policy, ResolvedReliabilityPolicy)
            or policy.capability_kind is not capability_kind
            or policy.capability_id != owner.capability_id
            or policy.capability_version != owner.version
        ):
            return None, "STEP_RELIABILITY_POLICY_IDENTITY_MISMATCH"
        return policy, None

    async def _step_replay_safety(
        self,
        *,
        observation: StepAttemptObservation,
        owner_policy: ResolvedReliabilityPolicy,
    ) -> ReplaySafetyDecision:
        try:
            request = StepReplaySafetyRequest(
                observation=observation,
                owner_policy=owner_policy,
            )
            decision = await self._runtime.replay_safety_evaluator.evaluate(request)
        except Exception:  # noqa: BLE001
            decision = None
        if not isinstance(decision, ReplaySafetyDecision) or not isinstance(
            decision.status, ReplaySafetyStatus
        ):
            return ReplaySafetyDecision(
                status=ReplaySafetyStatus.UNKNOWN,
                reason_codes=("STEP_REPLAY_SAFETY_EVALUATOR_UNKNOWN",),
            )
        return decision

    def _step_retry_decision(
        self,
        *,
        observation: StepAttemptObservation,
        owner_policy: ResolvedReliabilityPolicy,
        trigger: RetryTriggerStatus,
        replay_safety: ReplaySafetyDecision,
        execution_context: ExecutionContext,
    ) -> RetryDecision:
        remaining, deadline_error = self._deadline_remaining(execution_context)
        if deadline_error is not None:
            return RetryDecision(
                status=RetryDecisionStatus.UNKNOWN,
                reason_codes=(deadline_error,),
            )
        context = RetryDecisionContext(
            current_attempt=observation.attempt_number,
            result_status=trigger,
            error_code=(
                observation.skill_result.error
                if observation.skill_result is not None
                else None
            ),
            replay_safety=replay_safety,
            deadline_remaining_seconds=(
                max(remaining, 0.0) if remaining is not None else None
            ),
        )
        try:
            decision = self._runtime.retry_decision_evaluator.evaluate(
                policy=owner_policy.retry,
                context=context,
            )
        except Exception:  # noqa: BLE001
            decision = None
        if not isinstance(decision, RetryDecision) or not isinstance(
            decision.status, RetryDecisionStatus
        ):
            return RetryDecision(
                status=RetryDecisionStatus.UNKNOWN,
                reason_codes=("STEP_RETRY_DECISION_EVALUATOR_UNKNOWN",),
            )
        return decision

    def _step_reliability_decision(
        self,
        *,
        observation: StepAttemptObservation,
        replay_safety: ReplaySafetyDecision | None,
        retry_decision: RetryDecision | None,
    ) -> StepReliabilityDecision:
        try:
            decision = self._runtime.step_reliability_evaluator.evaluate(
                observation=observation,
                replay_safety=replay_safety,
                retry_decision=retry_decision,
            )
        except Exception:  # noqa: BLE001
            decision = None
        if not isinstance(decision, StepReliabilityDecision) or not isinstance(
            decision.disposition, StepReliabilityDisposition
        ):
            return StepReliabilityDecision(
                disposition=StepReliabilityDisposition.ABORT_UNKNOWN,
                reason_codes=("STEP_RELIABILITY_EVALUATOR_UNKNOWN",),
            )
        return decision

    def _finish(
        self,
        *,
        attempts: list[StepAttemptObservation],
        observation: StepAttemptObservation,
        reliability_decision: StepReliabilityDecision,
        owner_policy: ResolvedReliabilityPolicy | None,
    ) -> StepReliabilityRunResult:
        try:
            finalization = self._runtime.step_finalization_evaluator.evaluate(
                observation=observation,
                reliability_decision=reliability_decision,
            )
        except Exception:  # noqa: BLE001
            finalization = None
        if not isinstance(finalization, StepFinalizationDecision) or not isinstance(
            finalization.disposition,
            StepFinalizationDisposition,
        ):
            finalization = StepFinalizationDecision(
                disposition=StepFinalizationDisposition.UNKNOWN,
                reason_codes=("STEP_FINALIZATION_EVALUATOR_UNKNOWN",),
            )
        elif (
            reliability_decision.disposition
            in {
                StepReliabilityDisposition.ABORT_UNKNOWN,
                StepReliabilityDisposition.WAIT_RECOVERY,
                StepReliabilityDisposition.KEEP_RUNNING,
            }
            and finalization.disposition is StepFinalizationDisposition.FINALIZE
        ):
            finalization = StepFinalizationDecision(
                disposition=StepFinalizationDisposition.UNKNOWN,
                reason_codes=("STEP_FINALIZATION_AUTHORITY_INCONSISTENT",),
            )
        return StepReliabilityRunResult(
            attempts=tuple(attempts),
            reliability_decision=reliability_decision,
            finalization_decision=finalization,
            owner_policy_identity=(
                owner_policy.policy_identity if owner_policy is not None else None
            ),
        )

    async def _claim_next_attempt(
        self,
        *,
        step_execution_id: str,
        expected_current_attempt: int,
    ) -> StepAttemptSequenceDecision:
        try:
            decision = await self._runtime.attempt_sequence_authority.claim_next(
                step_execution_id=step_execution_id,
                expected_current_attempt=expected_current_attempt,
            )
        except Exception:  # noqa: BLE001
            decision = None
        if not isinstance(decision, StepAttemptSequenceDecision) or not isinstance(
            decision.status, StepAttemptSequenceStatus
        ):
            return StepAttemptSequenceDecision(
                status=StepAttemptSequenceStatus.UNKNOWN,
                step_execution_id=step_execution_id,
                expected_current_attempt=expected_current_attempt,
                reason_codes=("STEP_ATTEMPT_SEQUENCE_UNKNOWN",),
            )
        return decision

    def _deadline_remaining(
        self,
        execution_context: ExecutionContext,
    ) -> tuple[float | None, str | None]:
        if execution_context.deadline is None:
            return None, None
        try:
            now = self._runtime.clock.now()
        except Exception:  # noqa: BLE001
            return None, "EXECUTION_CLOCK_UNKNOWN"
        try:
            return (execution_context.deadline - now).total_seconds(), None
        except (TypeError, ValueError):
            return None, "EXECUTION_DEADLINE_COMPARISON_UNKNOWN"

    def _clock_now(self) -> datetime:
        try:
            value = self._runtime.clock.now()
        except Exception as exc:
            raise StepReliabilityCoordinationError(
                "EXECUTION_CLOCK_UNKNOWN",
                "ExecutionClock failed during result collection",
            ) from exc
        return value

    @staticmethod
    def _effective_owner_timeout(
        *,
        owner_policy: ResolvedReliabilityPolicy | None,
        deadline_remaining_seconds: float | None,
    ) -> float | None:
        policy_timeout = (
            owner_policy.timeout.timeout_seconds if owner_policy is not None else None
        )
        values = [
            value
            for value in (policy_timeout, deadline_remaining_seconds)
            if value is not None and value > 0
        ]
        return min(values) if values else None

    @staticmethod
    def _step_retry_trigger(
        status: StepAttemptStatus,
    ) -> RetryTriggerStatus | None:
        mapping = {
            StepAttemptStatus.FAILED: RetryTriggerStatus.FAILED,
            StepAttemptStatus.TIMEOUT: RetryTriggerStatus.TIMEOUT,
            StepAttemptStatus.PARTIAL_SUCCESS: RetryTriggerStatus.PARTIAL_SUCCESS,
        }
        return mapping.get(status)

    @staticmethod
    def _tool_operation_sequence_matches(
        *,
        prior_journal: tuple[ToolInvocationJournalEntry, ...],
        current_journal: tuple[ToolInvocationJournalEntry, ...],
    ) -> bool:
        prior = tuple(
            (
                entry.tool_id,
                entry.tool_version,
                entry.operation_key,
                entry.operation_fingerprint,
            )
            for entry in prior_journal
        )
        current = tuple(
            (
                entry.tool_id,
                entry.tool_version,
                entry.operation_key,
                entry.operation_fingerprint,
            )
            for entry in current_journal
        )
        return prior == current

    @staticmethod
    def _unknown_outcome(
        *,
        step: ActionStep,
        step_snapshot: StepLifecycleSnapshot,
        resolved: ResolvedStepCapabilities,
        reason_code: str,
    ) -> StepCapabilityExecutionOutcome:
        owner: ResolvedCapability | None
        if resolved.execution_owner is CapabilityExecutionOwner.SKILL:
            owner = resolved.skill
        elif resolved.execution_owner is CapabilityExecutionOwner.WORKFLOW:
            owner = resolved.workflow
        else:
            owner = None
        return StepCapabilityExecutionOutcome(
            step_id=step.step_id,
            step_execution_id=step_snapshot.step_execution_id,
            status=CapabilityExecutionStatus.UNKNOWN,
            execution_owner=resolved.execution_owner,
            reason_codes=(reason_code,),
            owner_capability_id=(owner.capability_id if owner is not None else None),
            owner_capability_version=(owner.version if owner is not None else None),
        )
