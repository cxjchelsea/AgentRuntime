"""M5-IU9 Formal Implementation behavioral gates."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

from runtime.contracts.enums import RuntimeControlState
from runtime.contracts.execution import ExecutionContext
from runtime.execution.capability_execution import (
    CapabilityExecutionStatus,
    StepCapabilityExecutor,
)
from runtime.execution.capability_resolution import CapabilityExecutionOwner
from runtime.execution.models import (
    M5WorkflowResult,
    StepExecutionStatus,
    WorkflowExecutionStatus,
)
from runtime.execution.recovery import (
    CurrentRecoveryEpochSideEffectAdmissionGuard,
    ExecutionRecoveryClaim,
    InMemoryRecoveryClaimAuthority,
    RecoveryClaimRequest,
    RecoveryClaimStatus,
    RecoverySideEffectAdmissionDecision,
    RecoverySideEffectAdmissionStatus,
)
from runtime.execution.recovery_evidence import (
    DurableStepAttemptSequenceAuthority,
    InMemoryDurableRecoveryEvidenceStore,
)
from runtime.execution.recovery_runtime import ApprovedPlanWorkflowVersionAuthority
from runtime.execution.reliability import (
    IdempotencyMode,
    ReliabilityCapabilityKind,
    ReplaySafetyDecision,
    ReplaySafetyStatus,
    ResolvedIdempotencyPolicy,
    ResolvedReliabilityPolicy,
    ResolvedRetryPolicy,
    ResolvedTimeoutPolicy,
    RetryDecision,
    RetryDecisionStatus,
    SideEffectClass,
)
from runtime.execution.reliability_boundary import (
    StepFinalizationDecision,
    StepFinalizationDisposition,
    StepReliabilityDecision,
    StepReliabilityDisposition,
)
from runtime.execution.reliability_coordinator import StepReliabilityCoordinator
from runtime.execution.reliability_runtime import StepReliabilityRuntime
from runtime.execution.result_collection import StepResultCollector
from runtime.execution.recovery_workflow import (
    WorkflowResumeRequest,
)
from tests.test_m5_iu4_capability_execution import (
    CountingIdentifierFactory,
    RecordingSkill,
    RecordingTool,
    StaticPermissionEvaluator,
    StaticPermissionProvider,
    StaticValidator,
    _approved_step,
    _skill_resolved,
    _snapshot,
    _tool,
    _workflow_resolved,
)

NOW = datetime(2026, 9, 23, 9, 0, tzinfo=UTC)


async def _claim(
    authority: InMemoryRecoveryClaimAuthority,
    *,
    claim_id: str,
    execution_id: str = "execution-iu4",
    owner: str,
    expected_epoch: int,
    source_generation: int = 1,
    at: datetime,
) -> ExecutionRecoveryClaim:
    decision = await authority.claim(
        RecoveryClaimRequest(
            claim_id=claim_id,
            execution_id=execution_id,
            recovery_owner_id=owner,
            expected_current_epoch=expected_epoch,
            source_snapshot_generation=source_generation,
            requested_at=at,
        )
    )
    assert decision.status is RecoveryClaimStatus.CLAIMED
    assert decision.claim is not None
    return decision.claim


def _context() -> ExecutionContext:
    return ExecutionContext(
        execution_id="execution-iu4",
        plan_id="plan-001",
        request_id="request-001",
        session_id="session-001",
        identity_scope="scope-001",
        policy_snapshot={"allowed": True},
        current_state=RuntimeControlState.PROCESSING,
    )


def _executor() -> StepCapabilityExecutor:
    return StepCapabilityExecutor(
        permission_context_provider=StaticPermissionProvider(),
        permission_evaluator=StaticPermissionEvaluator(),
        input_validator=StaticValidator(),
        output_validator=StaticValidator(),
        identifier_factory=CountingIdentifierFactory(),
    )


class SequencedAdmissionGuard:
    """Allow owner admission, then reject the first nested physical Tool admission."""

    def __init__(self) -> None:
        self.calls = 0

    async def authorize(
        self,
        *,
        execution_id: str,
    ) -> RecoverySideEffectAdmissionDecision:
        assert execution_id == "execution-iu4"
        self.calls += 1
        if self.calls == 1:
            return RecoverySideEffectAdmissionDecision(
                status=RecoverySideEffectAdmissionStatus.ALLOWED,
                reason_codes=("OWNER_EPOCH_CURRENT",),
            )
        return RecoverySideEffectAdmissionDecision(
            status=RecoverySideEffectAdmissionStatus.STALE,
            reason_codes=("TOOL_EPOCH_STALE",),
        )


class RecoveryWorkflow:
    def __init__(self) -> None:
        self.resume_calls = 0
        self.requests: list[WorkflowResumeRequest] = []

    async def resume_from_checkpoint(
        self,
        request: WorkflowResumeRequest,
        execution_context: ExecutionContext,
        tool_invoker: Any,
    ) -> M5WorkflowResult:
        del execution_context, tool_invoker
        self.resume_calls += 1
        self.requests.append(request)
        return M5WorkflowResult(
            workflow_instance_id=request.workflow_instance_id,
            workflow_id=request.workflow_id,
            status=WorkflowExecutionStatus.COMPLETED,
        )


def test_current_epoch_guard_turns_stale_after_newer_recovery_claim() -> None:
    async def scenario() -> None:
        authority = InMemoryRecoveryClaimAuthority()
        first = await _claim(
            authority,
            claim_id="claim-1",
            owner="worker-a",
            expected_epoch=0,
            at=NOW,
        )
        guard = CurrentRecoveryEpochSideEffectAdmissionGuard(
            claim_authority=authority,
            recovery_claim=first,
        )
        allowed = await guard.authorize(execution_id="execution-iu4")
        assert allowed.status is RecoverySideEffectAdmissionStatus.ALLOWED

        newer = await _claim(
            authority,
            claim_id="claim-2",
            owner="worker-b",
            expected_epoch=1,
            at=NOW + timedelta(seconds=1),
        )
        assert newer.recovery_epoch == 2

        stale = await guard.authorize(execution_id="execution-iu4")
        assert stale.status is RecoverySideEffectAdmissionStatus.STALE

    asyncio.run(scenario())


def test_stale_recovery_epoch_blocks_skill_before_owner_side_effect() -> None:
    async def scenario() -> None:
        authority = InMemoryRecoveryClaimAuthority()
        old = await _claim(
            authority,
            claim_id="claim-1",
            owner="worker-a",
            expected_epoch=0,
            at=NOW,
        )
        await _claim(
            authority,
            claim_id="claim-2",
            owner="worker-b",
            expected_epoch=1,
            at=NOW + timedelta(seconds=1),
        )
        guard = CurrentRecoveryEpochSideEffectAdmissionGuard(
            claim_authority=authority,
            recovery_claim=old,
        )

        plan, step = _approved_step(owner=CapabilityExecutionOwner.SKILL)
        skill = RecordingSkill()
        outcome = await _executor().execute(
            approved_plan=plan,
            step=step,
            step_snapshot=_snapshot(step),
            resolved=_skill_resolved(skill),
            execution_context=_context(),
            side_effect_admission_guard=guard,
        )

        assert outcome.status is CapabilityExecutionStatus.UNKNOWN
        assert outcome.reason_codes == ("RECOVERY_SIDE_EFFECT_EPOCH_STALE",)
        assert skill.calls == 0

    asyncio.run(scenario())


def test_nested_tool_revalidates_epoch_after_owner_admission() -> None:
    async def scenario() -> None:
        plan, step = _approved_step(owner=CapabilityExecutionOwner.SKILL)
        tool = RecordingTool()
        skill = RecordingSkill(tool_ids=("DOMAIN_TOOL",))
        guard = SequencedAdmissionGuard()

        outcome = await _executor().execute(
            approved_plan=plan,
            step=step,
            step_snapshot=_snapshot(step),
            resolved=_skill_resolved(skill, tools=(_tool(tool),)),
            execution_context=_context(),
            side_effect_admission_guard=guard,
        )

        assert guard.calls == 2
        assert skill.calls == 1
        assert tool.calls == 0
        assert outcome.status is CapabilityExecutionStatus.UNKNOWN
        assert "RECOVERY_SIDE_EFFECT_EPOCH_STALE" in outcome.reason_codes

    asyncio.run(scenario())


def test_workflow_resume_uses_exact_instance_version_and_current_epoch() -> None:
    async def scenario() -> None:
        authority = InMemoryRecoveryClaimAuthority()
        claim = await _claim(
            authority,
            claim_id="claim-1",
            owner="worker-a",
            expected_epoch=0,
            at=NOW,
        )
        guard = CurrentRecoveryEpochSideEffectAdmissionGuard(
            claim_authority=authority,
            recovery_claim=claim,
        )

        plan, step = _approved_step(owner=CapabilityExecutionOwner.WORKFLOW)
        workflow = RecoveryWorkflow()
        request = WorkflowResumeRequest(
            execution_id="execution-iu4",
            step_execution_id="step-execution-001",
            workflow_instance_id="wf-instance-existing",
            workflow_id="DOMAIN_WORKFLOW",
            workflow_version="4.5.6",
            checkpoint_id="cp-1",
            checkpoint_generation=2,
            state_reference="state://wf/1",
            resume_token="resume-token",
        )

        outcome = await _executor().resume_workflow_from_checkpoint(
            approved_plan=plan,
            step=step,
            step_snapshot=_snapshot(step),
            resolved=_workflow_resolved(workflow),
            execution_context=_context(),
            resume_request=request,
            side_effect_admission_guard=guard,
        )

        assert outcome.status is CapabilityExecutionStatus.EXECUTED
        assert workflow.resume_calls == 1
        assert workflow.requests == [request]
        assert outcome.owner_capability_version == "4.5.6"

    asyncio.run(scenario())


def test_workflow_resume_rejects_checkpoint_version_drift_before_invoke() -> None:
    async def scenario() -> None:
        authority = InMemoryRecoveryClaimAuthority()
        claim = await _claim(
            authority,
            claim_id="claim-1",
            owner="worker-a",
            expected_epoch=0,
            at=NOW,
        )
        guard = CurrentRecoveryEpochSideEffectAdmissionGuard(
            claim_authority=authority,
            recovery_claim=claim,
        )
        plan, step = _approved_step(owner=CapabilityExecutionOwner.WORKFLOW)
        workflow = RecoveryWorkflow()
        drifted = WorkflowResumeRequest(
            execution_id="execution-iu4",
            step_execution_id="step-execution-001",
            workflow_instance_id="wf-instance-existing",
            workflow_id="DOMAIN_WORKFLOW",
            workflow_version="999.0.0",
            checkpoint_id="cp-1",
            checkpoint_generation=2,
            state_reference="state://wf/1",
            resume_token="resume-token",
        )

        outcome = await _executor().resume_workflow_from_checkpoint(
            approved_plan=plan,
            step=step,
            step_snapshot=_snapshot(step),
            resolved=_workflow_resolved(workflow),
            execution_context=_context(),
            resume_request=drifted,
            side_effect_admission_guard=guard,
        )

        assert outcome.status is CapabilityExecutionStatus.BLOCKED
        assert outcome.reason_codes == ("WORKFLOW_RESUME_AUTHORITY_MISMATCH",)
        assert workflow.resume_calls == 0

    asyncio.run(scenario())


def test_approved_workflow_version_authority_reads_frozen_plan_not_checkpoint_claim() -> None:
    plan, step = _approved_step(owner=CapabilityExecutionOwner.WORKFLOW)
    lifecycle = _snapshot(step)
    snapshot = cast(
        Any,
        SimpleNamespace(
            execution_id="execution-iu4",
            execution_record=SimpleNamespace(
                plan_id=plan.plan_id,
                request_id=plan.request_id,
            ),
            steps=(lifecycle,),
        ),
    )
    authority = ApprovedPlanWorkflowVersionAuthority(
        approved_plan=plan,
        snapshot=snapshot,
    )

    expected = asyncio.run(
        authority.expected_version(
            execution_id="execution-iu4",
            step_execution_id=lifecycle.step_execution_id,
            workflow_id="DOMAIN_WORKFLOW",
        )
    )

    assert expected == "4.5.6"



class StaticClock:
    def now(self) -> datetime:
        return NOW + timedelta(seconds=10)


class NoopTimeoutRunner:
    async def run(self, **kwargs: Any) -> Any:
        raise AssertionError("timeout runner must not be used when timeout is disabled")


class NoopSleeper:
    async def sleep(self, seconds: float) -> None:
        del seconds


class SkillPolicyResolver:
    def resolve(self, **kwargs: Any) -> ResolvedReliabilityPolicy:
        return ResolvedReliabilityPolicy(
            capability_kind=ReliabilityCapabilityKind.SKILL,
            capability_id="DOMAIN_SKILL",
            capability_version="3.2.1",
            policy_identity="skill-policy@formal-recovery",
            timeout=ResolvedTimeoutPolicy(timeout_seconds=None),
            retry=ResolvedRetryPolicy(
                enabled=True,
                max_attempts=3,
                retry_on_statuses=(),
                backoff_seconds=0.0,
            ),
            idempotency=ResolvedIdempotencyPolicy(mode=IdempotencyMode.NATURAL),
            side_effect_class=SideEffectClass.NONE,
        )


class UnusedReplayEvaluator:
    async def evaluate(self, request: Any) -> ReplaySafetyDecision:
        del request
        return ReplaySafetyDecision(
            status=ReplaySafetyStatus.SAFE,
            reason_codes=("SAFE",),
        )


class UnusedRetryEvaluator:
    def evaluate(self, **kwargs: Any) -> RetryDecision:
        return RetryDecision(
            status=RetryDecisionStatus.STOP,
            reason_codes=("NO_FURTHER_RETRY",),
        )


class SimpleStepReliabilityEvaluator:
    def evaluate(self, **kwargs: Any) -> StepReliabilityDecision:
        observation = kwargs["observation"]
        assert observation.status.value == "SUCCESS"
        return StepReliabilityDecision(
            disposition=StepReliabilityDisposition.FINALIZE,
            reason_codes=("RECOVERED_ATTEMPT_SUCCESS",),
        )


class SimpleStepFinalizationEvaluator:
    def evaluate(self, **kwargs: Any) -> StepFinalizationDecision:
        return StepFinalizationDecision(
            disposition=StepFinalizationDisposition.FINALIZE,
            reason_codes=("FINALIZE_RECOVERED_SUCCESS",),
            terminal_status=StepExecutionStatus.SUCCESS,
        )


def test_recovered_skill_retry_claims_next_attempt_through_iu6_authority() -> None:
    async def scenario() -> None:
        authority = InMemoryRecoveryClaimAuthority()
        claim = await _claim(
            authority,
            claim_id="claim-1",
            owner="worker-a",
            expected_epoch=0,
            at=NOW,
        )
        evidence = InMemoryDurableRecoveryEvidenceStore(claim_authority=authority)
        sequence = DurableStepAttemptSequenceAuthority(
            store=evidence,
            execution_id="execution-iu4",
            recovery_claim=claim,
            clock=lambda: NOW + timedelta(seconds=2),
        )
        baseline = await sequence.ensure_baseline(
            step_execution_id="step-execution-001"
        )
        assert baseline.status.value in {"RECORDED", "ALREADY_CURRENT"}

        plan, step = _approved_step(owner=CapabilityExecutionOwner.SKILL)
        skill = RecordingSkill()
        runtime = StepReliabilityRuntime(
            policy_resolver=SkillPolicyResolver(),
            clock=StaticClock(),
            timeout_runner=NoopTimeoutRunner(),
            retry_decision_evaluator=UnusedRetryEvaluator(),
            retry_sleeper=NoopSleeper(),
            replay_safety_evaluator=UnusedReplayEvaluator(),
            attempt_sequence_authority=sequence,
            step_reliability_evaluator=SimpleStepReliabilityEvaluator(),
            step_finalization_evaluator=SimpleStepFinalizationEvaluator(),
        )
        coordinator = StepReliabilityCoordinator(
            step_executor=_executor(),
            result_collector=StepResultCollector(),
            runtime=runtime,
        )
        guard = CurrentRecoveryEpochSideEffectAdmissionGuard(
            claim_authority=authority,
            recovery_claim=claim,
        )

        result = await coordinator.run_recovered_retry(
            approved_plan=plan,
            step=step,
            step_snapshot=replace(_snapshot(step), started_at=NOW),
            resolved=_skill_resolved(skill),
            execution_context=_context(),
            expected_current_attempt=1,
            prior_attempt_journal=(),
            side_effect_admission_guard=guard,
        )

        assert skill.calls == 1
        assert result.prior_attempt_number == 1
        assert result.attempts[0].attempt_number == 2
        assert await sequence.current_attempt("step-execution-001") == 2

    asyncio.run(scenario())
