"""M5-IU6 runtime reliability orchestration dependencies.

This module composes already-frozen authorities. It does not define Domain retry
policy, perform capability discovery, or own canonical execution aggregation.
"""

from __future__ import annotations

from dataclasses import dataclass

from runtime.execution.reliability import (
    AsyncTimeoutRunner,
    ExecutionClock,
    ReliabilityPolicyResolver,
    ReplaySafetyEvaluator,
    RetryDecisionEvaluator,
    RetrySleeper,
)
from runtime.execution.reliability_boundary import (
    IdempotencyKeyFactory,
    IdempotencyPreflightEvaluator,
    ToolOperationCorrelator,
    ToolOperationFingerprintFactory,
    ToolOperationOccurrenceAuthority,
)
from runtime.execution.stores import (
    IdempotencyCompletionAuthority,
    IdempotencyResultResolver,
    IdempotencyStore,
)


@dataclass(frozen=True, slots=True)
class ToolReliabilityRuntime:
    """Injected authorities required for one reliable logical Tool invocation."""

    policy_resolver: ReliabilityPolicyResolver
    clock: ExecutionClock
    timeout_runner: AsyncTimeoutRunner
    replay_safety_evaluator: ReplaySafetyEvaluator
    retry_decision_evaluator: RetryDecisionEvaluator
    retry_sleeper: RetrySleeper
    fingerprint_factory: ToolOperationFingerprintFactory
    occurrence_authority: ToolOperationOccurrenceAuthority
    correlator: ToolOperationCorrelator
    idempotency_key_factory: IdempotencyKeyFactory
    idempotency_store: IdempotencyStore
    idempotency_preflight_evaluator: IdempotencyPreflightEvaluator
    idempotency_completion_authority: IdempotencyCompletionAuthority
    idempotency_result_resolver: IdempotencyResultResolver
