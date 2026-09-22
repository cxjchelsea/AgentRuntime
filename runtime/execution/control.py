"""M5 cancellation / preemption control-signal contracts.

Priority and safety decisions remain owned by M2/Runtime. M5 only observes already
resolved execution-control signals. CA-M5-IU7-01 freezes auditable signal identity,
Core-local observation time, live watcher, and terminal-control latch contracts only.
It does not interrupt capabilities or mutate execution lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol


class ExecutionControlSignalType(str, Enum):
    NONE = "NONE"
    CANCEL = "CANCEL"
    PREEMPT = "PREEMPT"


@dataclass(frozen=True, slots=True)
class ExecutionControlSignal:
    """Runtime/M2-resolved control authority for one execution.

    issued_at is upstream audit evidence. IU7 must not use it as the sole ordering
    authority against local execution events from another clock domain.
    """

    signal_type: ExecutionControlSignalType
    reason_code: str | None = None
    source: str | None = None
    signal_id: str | None = None
    target_execution_id: str | None = None
    issued_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.signal_type, ExecutionControlSignalType):
            raise ValueError("signal_type must be ExecutionControlSignalType")  # noqa: TRY004

        if self.signal_type is ExecutionControlSignalType.NONE:
            if self.reason_code is not None:
                raise ValueError("NONE signal cannot carry reason_code")
            if self.signal_id is not None:
                raise ValueError("NONE signal cannot carry signal_id")
            if self.target_execution_id is not None:
                raise ValueError("NONE signal cannot carry target_execution_id")
            if self.issued_at is not None:
                raise ValueError("NONE signal cannot carry issued_at")
            if self.source is not None and not self.source.strip():
                raise ValueError("source must not be blank")
            return

        required = (
            ("reason_code", self.reason_code),
            ("source", self.source),
            ("signal_id", self.signal_id),
            ("target_execution_id", self.target_execution_id),
        )
        for name, value in required:
            if value is None or not value.strip():
                raise ValueError(f"CANCEL/PREEMPT signal requires non-blank {name}")
        if self.issued_at is None:
            raise ValueError("CANCEL/PREEMPT signal requires issued_at")
        _require_aware_datetime(self.issued_at, "issued_at")


@dataclass(frozen=True, slots=True)
class ObservedExecutionControl:
    """One terminal signal observed by M5 using the Core-local time authority."""

    signal: ExecutionControlSignal
    observed_at: datetime

    def __post_init__(self) -> None:
        if self.signal.signal_type not in {
            ExecutionControlSignalType.CANCEL,
            ExecutionControlSignalType.PREEMPT,
        }:
            raise ValueError("observed execution control requires CANCEL/PREEMPT")
        _require_aware_datetime(self.observed_at, "observed_at")


@dataclass(frozen=True, slots=True)
class LatchedExecutionControl:
    """Terminal control barrier accepted by M5 for one execution."""

    signal: ExecutionControlSignal
    observed_at: datetime
    latched_at: datetime

    def __post_init__(self) -> None:
        if self.signal.signal_type not in {
            ExecutionControlSignalType.CANCEL,
            ExecutionControlSignalType.PREEMPT,
        }:
            raise ValueError("latched execution control requires CANCEL/PREEMPT")
        _require_aware_datetime(self.observed_at, "observed_at")
        _require_aware_datetime(self.latched_at, "latched_at")
        if self.latched_at < self.observed_at:
            raise ValueError("latched_at cannot be before observed_at")


class ExecutionControlLatchStatus(str, Enum):
    LATCHED = "LATCHED"
    ALREADY_LATCHED = "ALREADY_LATCHED"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ExecutionControlLatchDecision:
    status: ExecutionControlLatchStatus
    reason_codes: tuple[str, ...]
    latched_control: LatchedExecutionControl | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ExecutionControlLatchStatus):
            # 合同测试与 Targeted Review 都要求非法 status 以 ValueError fail-closed。
            raise ValueError("status must be ExecutionControlLatchStatus")  # noqa: TRY004
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")

        if self.status in {
            ExecutionControlLatchStatus.LATCHED,
            ExecutionControlLatchStatus.ALREADY_LATCHED,
        }:
            if self.latched_control is None:
                raise ValueError("LATCHED/ALREADY_LATCHED requires latched_control")
            return

        if self.status is ExecutionControlLatchStatus.UNKNOWN:
            if self.latched_control is not None:
                raise ValueError("UNKNOWN must not claim a latched control")
            return

        if (
            self.status is ExecutionControlLatchStatus.CONFLICT
            and self.latched_control is None
        ):
            raise ValueError("CONFLICT requires the existing latched_control")


class ExecutionControlSignalSource(Protocol):
    async def get_signal(self, execution_id: str) -> ExecutionControlSignal:
        """Return Runtime/M2-resolved execution control for one execution.

        CANCEL/PREEMPT results must target exactly execution_id. The caller must
        still validate the returned target and fail closed on mismatch.
        """


class ExecutionControlWatcher(Protocol):
    async def wait_for_terminal_signal(
        self,
        *,
        execution_id: str,
        cancellation_token: str | None,
    ) -> ObservedExecutionControl:
        """Observe a live CANCEL/PREEMPT signal while execution is in flight.

        Polling/subscription cadence is implementation-owned. cancellation_token is
        opaque correlation data; it is not a mutable cancellation primitive.
        """


class ExecutionControlLatch(Protocol):
    async def latch(
        self,
        *,
        observed: ObservedExecutionControl,
        latched_at: datetime,
    ) -> ExecutionControlLatchDecision:
        """Atomically latch one terminal control barrier.

        First exact terminal signal -> LATCHED.
        Exact replay of the same immutable signal -> ALREADY_LATCHED.
        Same execution with a different terminal signal/payload -> CONFLICT.
        Indeterminate storage/runtime state -> UNKNOWN.

        Implementations must compare immutable signal identity and payload exactly;
        M5 must not compare control priority or choose between competing signals.
        """

    async def get_latched(
        self,
        execution_id: str,
    ) -> LatchedExecutionControl | None:
        """Return the currently latched terminal control, if one is known."""



class InMemoryExecutionControlLatch:
    """Live-only IU7 latch; durable recovery remains M5-IU9."""

    def __init__(self) -> None:
        self._latched: dict[str, LatchedExecutionControl] = {}

    async def latch(
        self,
        *,
        observed: ObservedExecutionControl,
        latched_at: datetime,
    ) -> ExecutionControlLatchDecision:
        try:
            candidate = LatchedExecutionControl(
                signal=observed.signal,
                observed_at=observed.observed_at,
                latched_at=latched_at,
            )
        except (TypeError, ValueError):
            return ExecutionControlLatchDecision(
                status=ExecutionControlLatchStatus.UNKNOWN,
                reason_codes=("CONTROL_LATCH_INPUT_INVALID",),
            )

        execution_id = observed.signal.target_execution_id
        if execution_id is None or not execution_id.strip():
            return ExecutionControlLatchDecision(
                status=ExecutionControlLatchStatus.UNKNOWN,
                reason_codes=("CONTROL_LATCH_TARGET_UNKNOWN",),
            )

        existing = self._latched.get(execution_id)
        if existing is None:
            self._latched[execution_id] = candidate
            return ExecutionControlLatchDecision(
                status=ExecutionControlLatchStatus.LATCHED,
                reason_codes=("CONTROL_LATCHED",),
                latched_control=candidate,
            )

        if existing.signal == observed.signal:
            return ExecutionControlLatchDecision(
                status=ExecutionControlLatchStatus.ALREADY_LATCHED,
                reason_codes=("CONTROL_ALREADY_LATCHED",),
                latched_control=existing,
            )

        return ExecutionControlLatchDecision(
            status=ExecutionControlLatchStatus.CONFLICT,
            reason_codes=("CONTROL_LATCH_CONFLICT",),
            latched_control=existing,
        )

    async def get_latched(
        self,
        execution_id: str,
    ) -> LatchedExecutionControl | None:
        if not isinstance(execution_id, str) or not execution_id.strip():
            return None
        return self._latched.get(execution_id)

def _require_aware_datetime(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
