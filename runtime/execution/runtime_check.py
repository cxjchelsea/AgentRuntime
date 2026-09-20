"""M5-IU2 runtime execution checks.

This module decides whether an already-approved step may still enter execution now.
It does not re-plan, substitute capabilities, mutate Runtime state, or execute
cancellation/preemption side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from runtime.contracts.enums import RuntimeControlState
from runtime.contracts.execution import ExecutionContext
from runtime.contracts.planning import ActionStep
from runtime.execution.control import (
    ExecutionControlSignalSource,
    ExecutionControlSignalType,
)


class RuntimeExecutionCheckStatus(str, Enum):
    ALLOWED = "ALLOWED"
    BLOCKED = "BLOCKED"
    CANCEL_REQUIRED = "CANCEL_REQUIRED"
    PREEMPT_REQUIRED = "PREEMPT_REQUIRED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class RuntimeExecutionSnapshot:
    """Current Runtime facts required by the M5 pre-step check."""

    session_id: str
    identity_scope: str
    current_state: RuntimeControlState
    session_active: bool | None
    safety_lock: bool | None = None
    restricted_actions: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if not self.session_id.strip() or not self.identity_scope.strip():
            raise ValueError("session_id and identity_scope must not be blank")
        if self.restricted_actions is not None and any(
            not action.strip() for action in self.restricted_actions
        ):
            raise ValueError("restricted_actions must not contain blank values")


class RuntimeExecutionSnapshotProvider(Protocol):
    async def get_snapshot(
        self,
        execution_context: ExecutionContext,
    ) -> RuntimeExecutionSnapshot:
        """Project current Runtime facts without mutating Runtime state."""


class PolicySnapshotValidityStatus(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class PolicySnapshotValidityDecision:
    status: PolicySnapshotValidityStatus
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.reason_codes:
            raise ValueError("reason_codes must not be empty")
        if any(not reason.strip() for reason in self.reason_codes):
            raise ValueError("reason_codes must not contain blank values")


class PolicySnapshotValidityEvaluator(Protocol):
    async def evaluate(
        self,
        *,
        execution_context: ExecutionContext,
        snapshot: RuntimeExecutionSnapshot,
    ) -> PolicySnapshotValidityDecision:
        """Validate the frozen policy snapshot; must not recompute M2 policy."""


class StateEligibilityStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class StateEligibilityDecision:
    status: StateEligibilityStatus
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.reason_codes:
            raise ValueError("reason_codes must not be empty")
        if any(not reason.strip() for reason in self.reason_codes):
            raise ValueError("reason_codes must not contain blank values")


class ExecutionStateEligibilityEvaluator(Protocol):
    async def evaluate(
        self,
        *,
        step: ActionStep,
        execution_context: ExecutionContext,
        snapshot: RuntimeExecutionSnapshot,
    ) -> StateEligibilityDecision:
        """Check current Runtime-state eligibility without changing the plan."""


@dataclass(frozen=True, slots=True)
class RuntimeExecutionCheckDecision:
    status: RuntimeExecutionCheckStatus
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.reason_codes:
            raise ValueError("reason_codes must not be empty")
        if any(not reason.strip() for reason in self.reason_codes):
            raise ValueError("reason_codes must not contain blank values")


class RuntimeExecutionChecker:
    """Fail-closed M5 pre-step checker.

    Precedence:
    resolved Runtime/M2 control signal
    > identity/session continuity
    > session validity
    > safety restriction
    > frozen policy validity
    > Runtime-state eligibility
    """

    def __init__(
        self,
        *,
        snapshot_provider: RuntimeExecutionSnapshotProvider,
        control_signal_source: ExecutionControlSignalSource,
        policy_validity_evaluator: PolicySnapshotValidityEvaluator,
        state_eligibility_evaluator: ExecutionStateEligibilityEvaluator,
    ) -> None:
        self._snapshot_provider = snapshot_provider
        self._control_signal_source = control_signal_source
        self._policy_validity_evaluator = policy_validity_evaluator
        self._state_eligibility_evaluator = state_eligibility_evaluator

    async def check(
        self,
        *,
        step: ActionStep,
        execution_context: ExecutionContext,
    ) -> RuntimeExecutionCheckDecision:
        signal = await self._control_signal_source.get_signal(
            execution_context.execution_id
        )
        if signal.signal_type is ExecutionControlSignalType.CANCEL:
            return RuntimeExecutionCheckDecision(
                status=RuntimeExecutionCheckStatus.CANCEL_REQUIRED,
                reason_codes=(signal.reason_code or "CANCEL_REQUIRED",),
            )
        if signal.signal_type is ExecutionControlSignalType.PREEMPT:
            return RuntimeExecutionCheckDecision(
                status=RuntimeExecutionCheckStatus.PREEMPT_REQUIRED,
                reason_codes=(signal.reason_code or "PREEMPT_REQUIRED",),
            )

        snapshot = await self._snapshot_provider.get_snapshot(execution_context)

        if snapshot.identity_scope != execution_context.identity_scope:
            return RuntimeExecutionCheckDecision(
                status=RuntimeExecutionCheckStatus.BLOCKED,
                reason_codes=("IDENTITY_SCOPE_MISMATCH",),
            )
        if snapshot.session_id != execution_context.session_id:
            return RuntimeExecutionCheckDecision(
                status=RuntimeExecutionCheckStatus.BLOCKED,
                reason_codes=("SESSION_ID_MISMATCH",),
            )

        if snapshot.session_active is False:
            return RuntimeExecutionCheckDecision(
                status=RuntimeExecutionCheckStatus.BLOCKED,
                reason_codes=("SESSION_INACTIVE",),
            )
        if snapshot.session_active is None:
            return RuntimeExecutionCheckDecision(
                status=RuntimeExecutionCheckStatus.UNKNOWN,
                reason_codes=("SESSION_VALIDITY_UNKNOWN",),
            )

        if snapshot.safety_lock is None:
            return RuntimeExecutionCheckDecision(
                status=RuntimeExecutionCheckStatus.UNKNOWN,
                reason_codes=("SAFETY_LOCK_STATE_UNKNOWN",),
            )
        if snapshot.safety_lock is True:
            if snapshot.restricted_actions is None:
                return RuntimeExecutionCheckDecision(
                    status=RuntimeExecutionCheckStatus.UNKNOWN,
                    reason_codes=("SAFETY_RESTRICTIONS_UNKNOWN",),
                )
            if step.action in snapshot.restricted_actions:
                return RuntimeExecutionCheckDecision(
                    status=RuntimeExecutionCheckStatus.BLOCKED,
                    reason_codes=("ACTION_RESTRICTED_BY_SAFETY_LOCK",),
                )

        policy_decision = await self._policy_validity_evaluator.evaluate(
            execution_context=execution_context,
            snapshot=snapshot,
        )
        if policy_decision.status is PolicySnapshotValidityStatus.INVALID:
            return RuntimeExecutionCheckDecision(
                status=RuntimeExecutionCheckStatus.BLOCKED,
                reason_codes=policy_decision.reason_codes,
            )
        if policy_decision.status is PolicySnapshotValidityStatus.UNKNOWN:
            return RuntimeExecutionCheckDecision(
                status=RuntimeExecutionCheckStatus.UNKNOWN,
                reason_codes=policy_decision.reason_codes,
            )

        state_decision = await self._state_eligibility_evaluator.evaluate(
            step=step,
            execution_context=execution_context,
            snapshot=snapshot,
        )
        if state_decision.status is StateEligibilityStatus.INELIGIBLE:
            return RuntimeExecutionCheckDecision(
                status=RuntimeExecutionCheckStatus.BLOCKED,
                reason_codes=state_decision.reason_codes,
            )
        if state_decision.status is StateEligibilityStatus.UNKNOWN:
            return RuntimeExecutionCheckDecision(
                status=RuntimeExecutionCheckStatus.UNKNOWN,
                reason_codes=state_decision.reason_codes,
            )

        return RuntimeExecutionCheckDecision(
            status=RuntimeExecutionCheckStatus.ALLOWED,
            reason_codes=("RUNTIME_EXECUTION_ALLOWED",),
        )
