"""CA-M5-IU10-01 aggregation eligibility and plan-status authority gates."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Mapping

from runtime.contracts.enums import ExecutionPlanStatus
from runtime.execution.aggregation_authority import (
    AggregationEvidenceReadinessDecision,
    AggregationEvidenceReadinessStatus,
    ExecutionAggregationAuthority,
    ExecutionAggregationEligibilityStatus,
    StepSkipAggregationDisposition,
)
from runtime.execution.control import (
    ExecutionControlSignal,
    ExecutionControlSignalType,
    LatchedExecutionControl,
)
from runtime.execution.foundation import (
    CallableExecutionIdentifierFactory,
    ExecutionContextBuilder,
    ExecutionFoundation,
    ExecutionRecordFactory,
    InMemoryExecutionStateStore,
    PreparedExecution,
    StepLifecycleSnapshot,
)
from runtime.execution.models import StepExecutionStatus
from runtime.execution.recovery_evidence import (
    DurableControlReadDecision,
    DurableControlReadStatus,
)
from tests.orchestration_stubs import (
    build_approved_action_plan,
    build_runtime_context,
)

NOW = datetime(2026, 9, 24, 10, 0, tzinfo=UTC)


def _plan(*, optional: tuple[bool | None, ...]):
    base = build_approved_action_plan()
    source = base.steps[0]
    return base.model_copy(
        update={
            "steps": [
                source.model_copy(
                    update={
                        "step_id": f"step-{index + 1:03d}",
                        "action": f"ACTION_{index + 1}",
                        "optional": flag,
                    }
                )
                for index, flag in enumerate(optional)
            ]
        }
    )


async def _prepared(plan) -> PreparedExecution:
    ids = CallableExecutionIdentifierFactory(
        execution_id_factory=lambda: "execution-iu10-ca01",
        step_execution_id_factory=lambda step_id: f"exec:{step_id}",
    )
    foundation = ExecutionFoundation(
        plan_validator=__import__(
            "runtime.execution.foundation",
            fromlist=["ApprovedPlanExecutionValidator"],
        ).ApprovedPlanExecutionValidator(),
        context_builder=ExecutionContextBuilder(identifier_factory=ids),
        record_factory=ExecutionRecordFactory(
            identifier_factory=ids,
            clock=lambda: NOW,
        ),
        execution_store=InMemoryExecutionStateStore(),
    )
    created = await foundation.initialize(plan, build_runtime_context())
    return replace(
        created,
        started_at=NOW,
        execution_record=replace(
            created.execution_record,
            status="RUNNING",
            updated_at=NOW,
        ),
    )


def _with_steps(
    prepared: PreparedExecution,
    *states: tuple[StepExecutionStatus, bool, tuple[str, ...]],
    execution_status: str = "RUNNING",
) -> PreparedExecution:
    steps: list[StepLifecycleSnapshot] = []
    for current, spec in zip(prepared.steps, states, strict=True):
        status, degraded, reasons = spec
        steps.append(
            replace(
                current,
                status=status,
                degraded=degraded,
                terminal_reason_codes=reasons,
                finished_at=NOW if status not in {
                    StepExecutionStatus.PENDING,
                    StepExecutionStatus.RUNNING,
                } else None,
            )
        )
    payload = tuple(
        {
            "step_execution_id": step.step_execution_id,
            "step_id": step.step_id,
            "action": step.action,
            "status": step.status.value,
            "skill_id": step.skill_id,
            "workflow_id": step.workflow_id,
            "tool_call_ids": list(step.tool_call_ids),
            "output": step.output,
            "error": step.error,
            "retry_count": step.retry_count,
            "terminal_reason_codes": list(step.terminal_reason_codes),
            "degraded": step.degraded,
            "started_at": step.started_at,
            "finished_at": step.finished_at,
        }
        for step in steps
    )
    return replace(
        prepared,
        steps=tuple(steps),
        finished_at=NOW if execution_status not in {"RUNNING", "CREATED"} else None,
        execution_record=replace(
            prepared.execution_record,
            status=execution_status,
            current_step=None,
            step_results=payload,
            updated_at=NOW,
        ),
    )


def _evidence(
    status: AggregationEvidenceReadinessStatus = AggregationEvidenceReadinessStatus.READY,
) -> AggregationEvidenceReadinessDecision:
    return AggregationEvidenceReadinessDecision(
        status=status,
        reason_codes=(f"EVIDENCE_{status.value}",),
    )


def _no_control() -> DurableControlReadDecision:
    return DurableControlReadDecision(
        status=DurableControlReadStatus.NONE,
        reason_codes=("NO_CONTROL",),
    )


def _unknown_control() -> DurableControlReadDecision:
    return DurableControlReadDecision(
        status=DurableControlReadStatus.UNKNOWN,
        reason_codes=("CONTROL_UNKNOWN",),
    )


def _latched(signal_type: ExecutionControlSignalType) -> DurableControlReadDecision:
    signal = ExecutionControlSignal(
        signal_type=signal_type,
        reason_code="CONTROL_REASON",
        source="runtime",
        signal_id="signal-001",
        target_execution_id="execution-iu10-ca01",
        issued_at=NOW,
    )
    latch = LatchedExecutionControl(
        signal=signal,
        observed_at=NOW,
        latched_at=NOW,
    )
    return DurableControlReadDecision(
        status=DurableControlReadStatus.LATCHED,
        reason_codes=("CONTROL_LATCHED",),
        latched_control=latch,
    )


async def _evaluate(
    plan,
    prepared,
    *,
    control: DurableControlReadDecision | None = None,
    evidence: AggregationEvidenceReadinessDecision | None = None,
    skips: Mapping[str, StepSkipAggregationDisposition] | None = None,
):
    return ExecutionAggregationAuthority().evaluate(
        approved_plan=plan,
        prepared=prepared,
        control=control or _no_control(),
        evidence_readiness=evidence or _evidence(),
        skip_dispositions=skips or {},
    )


def test_pending_or_running_step_waits_instead_of_failing() -> None:
    import asyncio

    async def scenario() -> None:
        plan = _plan(optional=(False,))
        prepared = await _prepared(plan)
        pending = await _evaluate(plan, prepared)
        assert pending.status is ExecutionAggregationEligibilityStatus.WAITING

        running = _with_steps(
            prepared,
            (StepExecutionStatus.RUNNING, False, ()),
        )
        decision = await _evaluate(plan, running)
        assert decision.status is ExecutionAggregationEligibilityStatus.WAITING
        assert decision.aggregation_decision is None

    asyncio.run(scenario())


def test_unknown_control_blocks_before_natural_aggregation() -> None:
    import asyncio

    async def scenario() -> None:
        plan = _plan(optional=(False,))
        prepared = _with_steps(
            await _prepared(plan),
            (StepExecutionStatus.SUCCESS, False, ("DONE",)),
        )
        decision = await _evaluate(plan, prepared, control=_unknown_control())
        assert decision.status is ExecutionAggregationEligibilityStatus.BLOCKED_UNKNOWN
        assert decision.reason_codes == ("AGGREGATION_CONTROL_STATE_UNKNOWN",)

    asyncio.run(scenario())


def test_latched_control_requires_iu7_terminalization_before_aggregation() -> None:
    import asyncio

    async def scenario() -> None:
        plan = _plan(optional=(False,))
        prepared = _with_steps(
            await _prepared(plan),
            (StepExecutionStatus.SUCCESS, False, ("DONE",)),
        )
        decision = await _evaluate(
            plan,
            prepared,
            control=_latched(ExecutionControlSignalType.CANCEL),
        )
        assert decision.status is ExecutionAggregationEligibilityStatus.BLOCKED_UNKNOWN
        assert decision.reason_codes == (
            "AGGREGATION_CONTROL_TERMINALIZATION_REQUIRED",
        )

    asyncio.run(scenario())


def test_control_terminal_replay_preserves_cancel_and_preempt() -> None:
    import asyncio

    async def scenario() -> None:
        for signal_type, expected, step_status in (
            (
                ExecutionControlSignalType.CANCEL,
                ExecutionPlanStatus.CANCELLED,
                StepExecutionStatus.CANCELLED,
            ),
            (
                ExecutionControlSignalType.PREEMPT,
                ExecutionPlanStatus.PREEMPTED,
                StepExecutionStatus.PREEMPTED,
            ),
        ):
            plan = _plan(optional=(False,))
            prepared = _with_steps(
                await _prepared(plan),
                (step_status, False, ("CONTROL",)),
                execution_status=expected.value,
            )
            decision = await _evaluate(
                plan,
                prepared,
                control=_latched(signal_type),
            )
            assert (
                decision.status
                is ExecutionAggregationEligibilityStatus.READY_EXISTING_TERMINAL
            )
            assert decision.existing_plan_status is expected
            assert decision.aggregation_decision is not None
            assert decision.aggregation_decision.plan_status is expected

    asyncio.run(scenario())


def test_cancelled_execution_without_control_provenance_is_blocked() -> None:
    import asyncio

    async def scenario() -> None:
        plan = _plan(optional=(False,))
        prepared = _with_steps(
            await _prepared(plan),
            (StepExecutionStatus.CANCELLED, False, ("CONTROL",)),
            execution_status="CANCELLED",
        )
        decision = await _evaluate(plan, prepared)
        assert decision.status is ExecutionAggregationEligibilityStatus.BLOCKED_UNKNOWN
        assert decision.reason_codes == (
            "AGGREGATION_CONTROL_PROVENANCE_MISSING",
        )

    asyncio.run(scenario())


def test_required_success_and_optional_success_is_success() -> None:
    import asyncio

    async def scenario() -> None:
        plan = _plan(optional=(False, True))
        prepared = _with_steps(
            await _prepared(plan),
            (StepExecutionStatus.SUCCESS, False, ("DONE",)),
            (StepExecutionStatus.SUCCESS, False, ("DONE",)),
        )
        decision = await _evaluate(plan, prepared)
        assert decision.status is ExecutionAggregationEligibilityStatus.READY_NATURAL
        assert decision.aggregation_decision is not None
        assert decision.aggregation_decision.plan_status is ExecutionPlanStatus.SUCCESS

    asyncio.run(scenario())


def test_required_timeout_precedes_required_failure() -> None:
    import asyncio

    async def scenario() -> None:
        plan = _plan(optional=(False, False))
        prepared = _with_steps(
            await _prepared(plan),
            (StepExecutionStatus.FAILED, False, ("FAILED",)),
            (StepExecutionStatus.TIMEOUT, False, ("TIMEOUT",)),
        )
        decision = await _evaluate(plan, prepared)
        assert decision.aggregation_decision is not None
        assert decision.aggregation_decision.plan_status is ExecutionPlanStatus.TIMEOUT

    asyncio.run(scenario())


def test_required_unsatisfied_is_failed() -> None:
    import asyncio

    async def scenario() -> None:
        plan = _plan(optional=(False, True))
        prepared = _with_steps(
            await _prepared(plan),
            (StepExecutionStatus.FAILED, False, ("FAILED",)),
            (StepExecutionStatus.SUCCESS, False, ("DONE",)),
        )
        decision = await _evaluate(plan, prepared)
        assert decision.aggregation_decision is not None
        assert decision.aggregation_decision.plan_status is ExecutionPlanStatus.FAILED

    asyncio.run(scenario())


def test_required_degraded_is_partial_success() -> None:
    import asyncio

    async def scenario() -> None:
        plan = _plan(optional=(False,))
        prepared = _with_steps(
            await _prepared(plan),
            (
                StepExecutionStatus.SUCCESS,
                True,
                ("STEP_PARTIAL_SUCCESS_FINALIZATION_AUTHORIZED",),
            ),
        )
        decision = await _evaluate(plan, prepared)
        assert decision.aggregation_decision is not None
        assert (
            decision.aggregation_decision.plan_status
            is ExecutionPlanStatus.PARTIAL_SUCCESS
        )

    asyncio.run(scenario())


def test_optional_failure_after_required_success_is_partial_success() -> None:
    import asyncio

    async def scenario() -> None:
        plan = _plan(optional=(False, True))
        prepared = _with_steps(
            await _prepared(plan),
            (StepExecutionStatus.SUCCESS, False, ("DONE",)),
            (StepExecutionStatus.FAILED, False, ("FAILED",)),
        )
        decision = await _evaluate(plan, prepared)
        assert decision.aggregation_decision is not None
        assert (
            decision.aggregation_decision.plan_status
            is ExecutionPlanStatus.PARTIAL_SUCCESS
        )

    asyncio.run(scenario())


def test_required_not_applicable_skip_does_not_fail_plan() -> None:
    import asyncio

    async def scenario() -> None:
        plan = _plan(optional=(False, False))
        prepared = _with_steps(
            await _prepared(plan),
            (StepExecutionStatus.SKIPPED, False, ("CONDITION_FALSE",)),
            (StepExecutionStatus.SUCCESS, False, ("DONE",)),
        )
        decision = await _evaluate(
            plan,
            prepared,
            skips={"step-001": StepSkipAggregationDisposition.NOT_APPLICABLE},
        )
        assert decision.aggregation_decision is not None
        assert decision.aggregation_decision.plan_status is ExecutionPlanStatus.SUCCESS

    asyncio.run(scenario())


def test_required_unsatisfied_skip_fails_plan() -> None:
    import asyncio

    async def scenario() -> None:
        plan = _plan(optional=(False,))
        prepared = _with_steps(
            await _prepared(plan),
            (
                StepExecutionStatus.SKIPPED,
                False,
                ("DEPENDENCY_NOT_SUCCESSFUL",),
            ),
        )
        decision = await _evaluate(
            plan,
            prepared,
            skips={"step-001": StepSkipAggregationDisposition.UNSATISFIED},
        )
        assert decision.aggregation_decision is not None
        assert decision.aggregation_decision.plan_status is ExecutionPlanStatus.FAILED

    asyncio.run(scenario())


def test_skipped_step_without_provenance_is_blocked_unknown() -> None:
    import asyncio

    async def scenario() -> None:
        plan = _plan(optional=(False,))
        prepared = _with_steps(
            await _prepared(plan),
            (StepExecutionStatus.SKIPPED, False, ("SOME_REASON",)),
        )
        decision = await _evaluate(plan, prepared)
        assert decision.status is ExecutionAggregationEligibilityStatus.BLOCKED_UNKNOWN
        assert decision.reason_codes == ("AGGREGATION_STEP_EFFECT_UNKNOWN",)

    asyncio.run(scenario())


def test_missing_or_unknown_rich_evidence_blocks_terminal_aggregation() -> None:
    import asyncio

    async def scenario() -> None:
        plan = _plan(optional=(False,))
        prepared = _with_steps(
            await _prepared(plan),
            (StepExecutionStatus.SUCCESS, False, ("DONE",)),
        )
        missing = await _evaluate(
            plan,
            prepared,
            evidence=_evidence(AggregationEvidenceReadinessStatus.MISSING),
        )
        assert missing.reason_codes == ("AGGREGATION_EVIDENCE_MISSING",)

        unknown = await _evaluate(
            plan,
            prepared,
            evidence=_evidence(AggregationEvidenceReadinessStatus.UNKNOWN),
        )
        assert unknown.reason_codes == ("AGGREGATION_EVIDENCE_UNKNOWN",)

    asyncio.run(scenario())


def test_existing_terminal_replay_requires_exact_natural_status_match() -> None:
    import asyncio

    async def scenario() -> None:
        plan = _plan(optional=(False, True))
        base = await _prepared(plan)
        partial = _with_steps(
            base,
            (StepExecutionStatus.SUCCESS, False, ("DONE",)),
            (StepExecutionStatus.FAILED, False, ("FAILED",)),
            execution_status="PARTIAL_SUCCESS",
        )
        accepted = await _evaluate(plan, partial)
        assert (
            accepted.status
            is ExecutionAggregationEligibilityStatus.READY_EXISTING_TERMINAL
        )

        mismatched = replace(
            partial,
            execution_record=replace(
                partial.execution_record,
                status="SUCCESS",
            ),
        )
        blocked = await _evaluate(plan, mismatched)
        assert blocked.status is ExecutionAggregationEligibilityStatus.BLOCKED_UNKNOWN
        assert blocked.reason_codes == (
            "AGGREGATION_EXISTING_TERMINAL_STATUS_MISMATCH",
        )

    asyncio.run(scenario())


def test_all_optional_without_progress_resolves_failed_or_timeout() -> None:
    import asyncio

    async def scenario() -> None:
        failed_plan = _plan(optional=(True, True))
        failed = _with_steps(
            await _prepared(failed_plan),
            (StepExecutionStatus.FAILED, False, ("FAILED",)),
            (StepExecutionStatus.SKIPPED, False, ("CONDITION_FALSE",)),
        )
        failed_decision = await _evaluate(
            failed_plan,
            failed,
            skips={"step-002": StepSkipAggregationDisposition.NOT_APPLICABLE},
        )
        assert failed_decision.aggregation_decision is not None
        assert failed_decision.aggregation_decision.plan_status is ExecutionPlanStatus.FAILED

        timeout_plan = _plan(optional=(True,))
        timed_out = _with_steps(
            await _prepared(timeout_plan),
            (StepExecutionStatus.TIMEOUT, False, ("TIMEOUT",)),
        )
        timeout_decision = await _evaluate(timeout_plan, timed_out)
        assert timeout_decision.aggregation_decision is not None
        assert timeout_decision.aggregation_decision.plan_status is ExecutionPlanStatus.TIMEOUT

    asyncio.run(scenario())


def test_all_not_applicable_steps_is_execution_success() -> None:
    import asyncio

    async def scenario() -> None:
        plan = _plan(optional=(False, True))
        prepared = _with_steps(
            await _prepared(plan),
            (StepExecutionStatus.SKIPPED, False, ("CONDITION_FALSE",)),
            (StepExecutionStatus.SKIPPED, False, ("CONDITION_FALSE",)),
        )
        decision = await _evaluate(
            plan,
            prepared,
            skips={
                "step-001": StepSkipAggregationDisposition.NOT_APPLICABLE,
                "step-002": StepSkipAggregationDisposition.NOT_APPLICABLE,
            },
        )
        assert decision.aggregation_decision is not None
        assert decision.aggregation_decision.plan_status is ExecutionPlanStatus.SUCCESS

    asyncio.run(scenario())
