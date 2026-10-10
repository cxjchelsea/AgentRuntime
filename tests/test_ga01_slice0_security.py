"""GA-01B Slice-0 G02/G03 executable proof: no production authority."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from agent_core.iteration import (
    AgentRunBinding,
    IterationCorrelationError,
    IterationRef,
)
from runtime.contracts import (
    DomainExtensions,
    ExecutionPlanStatus,
    RuntimeResponse,
    UpdateResult,
    ValidatedResult,
)
from tests.ga01.sandbox import (
    LocalMockExecutionEngine,
    SandboxObservation,
    verify_local_mock,
)
from tests.orchestration_stubs import (
    build_approved_action_plan,
    build_execution_result,
    build_policy_decision,
    build_runtime_context,
    build_runtime_input,
)


def _fixture():
    user_input = build_runtime_input()
    binding = AgentRunBinding.from_input(
        user_input,
        run_id="sandbox-provenance",
        domain_id="education-fixture",
        domain_version="v1",
        binding_fingerprint="manifest-hash-v1",
    )
    iteration = IterationRef.from_input(binding, user_input, ordinal=0)
    base_context = build_runtime_context()
    context = base_context.model_copy(
        update={"domain_extensions": DomainExtensions(domain_id="education-fixture")}
    )
    approved = build_approved_action_plan().model_copy(
        update={"policy_snapshot": build_policy_decision().model_dump(mode="json")}
    )
    execution = build_execution_result()
    return binding, iteration, context, approved, execution


def test_g03_sandbox_observation_stays_noncanonical_and_mock_runs_once() -> None:
    binding, iteration, context, approved, prepared = _fixture()

    async def scenario() -> None:
        engine = LocalMockExecutionEngine(prepared)
        execution = await engine.execute(approved, context)
        observation = verify_local_mock(
            binding=binding,
            iteration=iteration,
            context=context,
            approved=approved,
            execution=execution,
        )
        assert type(observation) is SandboxObservation
        assert not isinstance(observation, (ValidatedResult, RuntimeResponse, UpdateResult))
        assert observation.facts == ("MOCK_EXECUTION_OBSERVED",)
        assert engine.call_count == 1
        with pytest.raises(IterationCorrelationError, match="repeat"):
            await engine.execute(approved, context)
        assert engine.call_count == 2

    asyncio.run(scenario())


def test_g02_cross_plan_and_domain_forgery_rejected_before_sandbox_observation() -> None:
    binding, iteration, context, approved, execution = _fixture()
    fake_plan = execution.model_copy(update={"plan_id": "foreign-plan"})
    with pytest.raises(IterationCorrelationError):
        verify_local_mock(
            binding=binding,
            iteration=iteration,
            context=context,
            approved=approved,
            execution=fake_plan,
        )
    wrong_domain = context.model_copy(
        update={"domain_extensions": DomainExtensions(domain_id="other-domain")}
    )
    with pytest.raises(IterationCorrelationError):
        verify_local_mock(
            binding=binding,
            iteration=iteration,
            context=wrong_domain,
            approved=approved,
            execution=execution,
        )
    wrong_fingerprint = replace(iteration, domain_fingerprint="untrusted-binding")
    with pytest.raises(IterationCorrelationError):
        verify_local_mock(
            binding=binding,
            iteration=wrong_fingerprint,
            context=context,
            approved=approved,
            execution=execution,
        )


def test_g03_mock_cannot_relabel_failed_execution_as_authorized_business_success() -> None:
    binding, iteration, context, approved, execution = _fixture()
    unknown = execution.model_copy(update={"plan_status": ExecutionPlanStatus.FAILED})
    # UNKNOWN must not be packaged as an affirmative sandbox fact either.
    with pytest.raises(IterationCorrelationError, match="terminal"):
        verify_local_mock(
            binding=binding,
            iteration=iteration,
            context=context,
            approved=approved,
            execution=unknown,
        )
