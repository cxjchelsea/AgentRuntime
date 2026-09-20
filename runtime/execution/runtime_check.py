"""M5-IU2 runtime execution checks.

This module re-checks live execution eligibility immediately before a planned step may
run. It does not modify the approved plan, select another capability, or make M2
priority/safety decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from runtime.contracts import ApprovedActionPlan
from runtime.contracts.planning import ActionStep
from runtime.execution.control import (
    ExecutionControlSignalSource,
    ExecutionControlSignalType,
)
from runtime.execution.foundation import PreparedExecution, StepLifecycleSnapshot
from runtime.execution.models import StepExecutionStatus


class RuntimeExecutionCheckStatus(str, Enum):
    ALLOWED = "ALLOWED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"
    PREEMPTED = "PREEMPTED"


@dataclass(frozen=True, slots=True)
class RuntimeExecutionFacts:
    """Already-resolved live execution facts supplied by Runtime/Domain adapters."""

    session_active: bool | None
    state_allows_step: bool | None
    policy_snapshot_valid: bool | None
    safety_allows_step: bool | None
    current_state: str | None = None
    blocking_reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.current_state is not None and not self.current_state.strip():
            raise ValueError("current_state must not be blank")
        if any(
            not reason.strip() for reason in self.blocking_reason_codes
        ):
            raise ValueError(
                "blocking_reason_codes must not contain blank values"
            )


@dataclass(frozen=True, slots=True)
class RuntimeExecutionCheckDecision:
    status: RuntimeExecutionCheckStatus
    reason_codes: tuple[str, ...]
    control_source: str | None = None

    def __post_init__(self) -> None:
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        if self.control_source is not None and not self.control_source.strip():
            raise ValueError("control_source must not be blank")


class RuntimeExecutionFactsProvider(Protocol):
    async def build(
        self,
        approved_plan: ApprovedActionPlan,
        prepared: PreparedExecution,
        step: ActionStep,
    ) -> RuntimeExecutionFacts:
        """Resolve live session/state/policy/safety facts for the approved step."""


class RuntimeExecutionChecker:
    """Fail-closed execution eligibility check before one approved step."""

    def __init__(
        self,
        *,
        facts_provider: RuntimeExecutionFactsProvider,
        control_signal_source: ExecutionControlSignalSource,
    ) -> None:
        self._facts_provider = facts_provider
        self._control_signal_source = control_signal_source

    async def check(
        self,
        approved_plan: ApprovedActionPlan,
        prepared: PreparedExecution,
        step: ActionStep,
    ) -> RuntimeExecutionCheckDecision:
        snapshot = self._validate_identity_and_step(
            approved_plan,
            prepared,
            step,
        )

        signal = await self._control_signal_source.get_signal(
            prepared.execution_record.execution_id
        )
        if signal.signal_type is ExecutionControlSignalType.CANCEL:
            return RuntimeExecutionCheckDecision(
                status=RuntimeExecutionCheckStatus.CANCELLED,
                reason_codes=(signal.reason_code or "CANCELLED",),
                control_source=signal.source,
            )
        if signal.signal_type is ExecutionControlSignalType.PREEMPT:
            return RuntimeExecutionCheckDecision(
                status=RuntimeExecutionCheckStatus.PREEMPTED,
                reason_codes=(signal.reason_code or "PREEMPTED",),
                control_source=signal.source,
            )

        facts = await self._facts_provider.build(
            approved_plan,
            prepared,
            step,
        )
        reason_codes = list(facts.blocking_reason_codes)
        checks = (
            ("SESSION", facts.session_active),
            ("STATE", facts.state_allows_step),
            ("POLICY_SNAPSHOT", facts.policy_snapshot_valid),
            ("SAFETY", facts.safety_allows_step),
        )
        for label, value in checks:
            if value is False:
                reason_codes.append(f"{label}_BLOCKED")
            elif value is None:
                reason_codes.append(f"{label}_UNKNOWN")

        if reason_codes:
            return RuntimeExecutionCheckDecision(
                status=RuntimeExecutionCheckStatus.BLOCKED,
                reason_codes=tuple(dict.fromkeys(reason_codes)),
            )

        # snapshot is intentionally referenced after fact resolution: a caller cannot
        # use this checker for a non-PENDING step and still get ALLOWED.
        if snapshot.status is not StepExecutionStatus.PENDING:
            raise ValueError("runtime execution check requires PENDING step")

        return RuntimeExecutionCheckDecision(
            status=RuntimeExecutionCheckStatus.ALLOWED,
            reason_codes=("RUNTIME_EXECUTION_ALLOWED",),
        )

    @staticmethod
    def _validate_identity_and_step(
        approved_plan: ApprovedActionPlan,
        prepared: PreparedExecution,
        step: ActionStep,
    ) -> StepLifecycleSnapshot:
        if approved_plan.plan_id != prepared.execution_record.plan_id:
            raise ValueError("approved plan_id does not match prepared execution")
        if approved_plan.request_id != prepared.execution_record.request_id:
            raise ValueError("approved request_id does not match prepared execution")
        if (
            prepared.execution_context.execution_id
            != prepared.execution_record.execution_id
        ):
            raise ValueError("execution identity drift detected")
        if prepared.execution_record.status != "RUNNING":
            raise ValueError("runtime execution check requires RUNNING execution")

        matches = [item for item in prepared.steps if item.step_id == step.step_id]
        if len(matches) != 1:
            raise ValueError("step must resolve to exactly one prepared snapshot")
        snapshot = matches[0]
        if snapshot.action != step.action:
            raise ValueError("approved step action drift detected")
        if snapshot.status is not StepExecutionStatus.PENDING:
            raise ValueError("runtime execution check requires PENDING step")
        return snapshot
