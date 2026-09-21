"""M5-IU6 CA-01 reliability policy, timeout, retry, and replay contracts.

This module freezes authority boundaries only. It does not execute retries, sleep,
invoke capabilities, mutate lifecycle state, persist idempotency records, or
interpret Domain policy strings inside Core.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Generic, Protocol, TypeVar

from runtime.execution.models import ToolExecutionStatus


class ReliabilityCapabilityKind(str, Enum):
    SKILL = "SKILL"
    WORKFLOW = "WORKFLOW"
    TOOL = "TOOL"


class RetryTriggerStatus(str, Enum):
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    UNAVAILABLE = "UNAVAILABLE"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"


class IdempotencyMode(str, Enum):
    NATURAL = "NATURAL"
    KEY_BASED = "KEY_BASED"
    NON_IDEMPOTENT = "NON_IDEMPOTENT"


class SideEffectClass(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass(frozen=True, slots=True)
class ResolvedTimeoutPolicy:
    timeout_seconds: float | None

    def __post_init__(self) -> None:
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive when present")


@dataclass(frozen=True, slots=True)
class ResolvedRetryPolicy:
    enabled: bool
    max_attempts: int
    retry_on_statuses: tuple[RetryTriggerStatus, ...] = ()
    retry_on_error_codes: tuple[str, ...] = ()
    backoff_seconds: float = 0.0
    backoff_multiplier: float = 1.0
    max_backoff_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts is total attempts and must be >= 1")
        if not self.enabled and self.max_attempts != 1:
            raise ValueError("disabled retry policy must have max_attempts == 1")
        if any(not code.strip() for code in self.retry_on_error_codes):
            raise ValueError("retry_on_error_codes must contain non-blank values")
        if self.backoff_seconds < 0:
            raise ValueError("backoff_seconds must be >= 0")
        if self.backoff_multiplier < 1:
            raise ValueError("backoff_multiplier must be >= 1")
        if (
            self.max_backoff_seconds is not None
            and self.max_backoff_seconds < self.backoff_seconds
        ):
            raise ValueError("max_backoff_seconds must be >= initial backoff_seconds")


@dataclass(frozen=True, slots=True)
class ResolvedIdempotencyPolicy:
    mode: IdempotencyMode


@dataclass(frozen=True, slots=True)
class ResolvedReliabilityPolicy:
    """Typed reliability policy deterministically bound to one exact capability."""

    capability_kind: ReliabilityCapabilityKind
    capability_id: str
    capability_version: str
    policy_identity: str
    timeout: ResolvedTimeoutPolicy
    retry: ResolvedRetryPolicy
    idempotency: ResolvedIdempotencyPolicy
    side_effect_class: SideEffectClass

    def __post_init__(self) -> None:
        values = (
            self.capability_id,
            self.capability_version,
            self.policy_identity,
        )
        if any(not value.strip() for value in values):
            raise ValueError(
                "capability id/version and policy_identity must not be blank"
            )


class ReliabilityPolicyResolver(Protocol):
    def resolve(
        self,
        *,
        capability_kind: ReliabilityCapabilityKind,
        capability_id: str,
        capability_version: str,
        timeout_policy_ref: str | None,
        retry_policy_ref: str | None,
        idempotency_policy_ref: str | None,
        side_effect_level_ref: str | None,
    ) -> ResolvedReliabilityPolicy:
        """Resolve opaque refs into a deterministic typed policy.

        For the same exact capability version and refs, the resolver must not
        silently bind a mutable latest policy. policy_identity identifies the
        immutable resolved policy version/hash/token.
        """


class ReplaySafetyStatus(str, Enum):
    SAFE = "SAFE"
    UNSAFE = "UNSAFE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ReplaySafetyContext:
    """Facts available to CA-01 without inventing CA-02 attempt correlation."""

    idempotency_mode: IdempotencyMode
    side_effect_class: SideEffectClass
    invocation_started: bool
    current_status: ToolExecutionStatus
    has_unknown_side_effect: bool = False
    has_untrusted_success: bool = False
    idempotency_state_unknown: bool = False


@dataclass(frozen=True, slots=True)
class ReplaySafetyDecision:
    status: ReplaySafetyStatus
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")


class ReplaySafetyEvaluator(Protocol):
    def evaluate(self, context: ReplaySafetyContext) -> ReplaySafetyDecision:
        """Evaluate replay safety; UNKNOWN must never be treated as SAFE."""


class RetryDecisionStatus(str, Enum):
    RETRY = "RETRY"
    STOP = "STOP"
    WAIT = "WAIT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class RetryDecision:
    status: RetryDecisionStatus
    reason_codes: tuple[str, ...]
    next_attempt: int | None = None
    backoff_seconds: float | None = None

    def __post_init__(self) -> None:
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        if self.status is RetryDecisionStatus.RETRY:
            if self.next_attempt is None or self.next_attempt < 2:
                raise ValueError("RETRY requires next_attempt >= 2")
            if self.backoff_seconds is None or self.backoff_seconds < 0:
                raise ValueError("RETRY requires non-negative backoff_seconds")
        elif self.next_attempt is not None or self.backoff_seconds is not None:
            raise ValueError(
                "non-RETRY decision must not carry next_attempt/backoff_seconds"
            )


@dataclass(frozen=True, slots=True)
class RetryDecisionContext:
    current_attempt: int
    result_status: RetryTriggerStatus
    error_code: str | None
    replay_safety: ReplaySafetyDecision
    deadline_remaining_seconds: float | None

    def __post_init__(self) -> None:
        if self.current_attempt < 1:
            raise ValueError("current_attempt must be >= 1")
        if (
            self.deadline_remaining_seconds is not None
            and self.deadline_remaining_seconds < 0
        ):
            raise ValueError("deadline_remaining_seconds must be >= 0 when present")


class RetryDecisionEvaluator(Protocol):
    def evaluate(
        self,
        *,
        policy: ResolvedRetryPolicy,
        context: RetryDecisionContext,
    ) -> RetryDecision:
        """Decide RETRY only when policy, budget, and replay safety allow it."""


class ExecutionClock(Protocol):
    def now(self) -> datetime:
        """Return current execution time from an injected authoritative clock."""


class RetrySleeper(Protocol):
    async def sleep(self, seconds: float) -> None:
        """Sleep/backoff without hard-coding wall-clock behavior."""


class BackoffCalculator(Protocol):
    def calculate(
        self,
        *,
        policy: ResolvedRetryPolicy,
        next_attempt: int,
    ) -> float:
        """Return backoff for the requested total-attempt number."""


T = TypeVar("T")


class TimeoutRunStatus(str, Enum):
    COMPLETED = "COMPLETED"
    TIMED_OUT = "TIMED_OUT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class TimeoutRunResult(Generic[T]):
    status: TimeoutRunStatus
    value: T | None = None
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        if self.status is not TimeoutRunStatus.COMPLETED and self.value is not None:
            raise ValueError("non-COMPLETED timeout result must not carry value")


class AsyncTimeoutRunner(Protocol):
    async def run(
        self,
        *,
        timeout_seconds: float,
        operation: Callable[[], Awaitable[Any]],
    ) -> TimeoutRunResult[Any]:
        """Run one operation under an injected timeout boundary.

        The runner reports timeout/uncertainty only. It does not decide retry,
        idempotency, lifecycle finalization, or capability substitution.
        """
