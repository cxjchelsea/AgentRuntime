"""GA-01B Slice 0: admission and per-iteration provenance, no Agent loop yet."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from typing import cast

import pytest

from agent_core.iteration import (
    AgentRunBinding,
    IterationCorrelationError,
    IterationRef,
)
from runtime.constraint_management import RuntimeConstraint
from runtime.contracts import InputSource, InputTriggerType, RuntimeInput
from runtime.input_processing import DefaultInputProcessor
from runtime.orchestration import OrchestrationInvariantError
from runtime.orchestration.m2_admission import assert_admission_allows_flow
from tests.orchestration_stubs import (
    build_policy_decision,
    build_runtime_input,
)


def binding_input() -> tuple[AgentRunBinding, RuntimeInput]:
    raw = build_runtime_input(request_id="r-original", trace_id="t-original")
    binding = AgentRunBinding.from_input(
        raw,
        run_id="ga-run-1",
        domain_id="test-domain",
        domain_version="1.0.0",
        binding_fingerprint="pinned-fixture",
    )
    return binding, raw


def test_g02_new_iteration_is_system_event_not_tool_or_user_text() -> None:
    binding, original = binding_input()
    first = binding.iteration_input(original, ordinal=0)
    second = binding.iteration_input(original, ordinal=1)
    third = binding.iteration_input(original, ordinal=2)
    assert first.request_id == "r-original"
    assert second.request_id != first.request_id != third.request_id
    assert second.trace_id != first.trace_id
    assert second.source is InputSource.SYSTEM
    assert second.trigger_type is InputTriggerType.SYSTEM_EVENT
    assert second.text is None and second.raw_text is None
    assert second.input_payload is not None
    assert second.input_payload["parent_request_id"] == first.request_id
    assert second.input_payload["run_id"] == binding.run_id

    async def check() -> None:
        normalized = await DefaultInputProcessor().process(second)
        assert normalized.request_id == second.request_id
        assert normalized.trigger_type is InputTriggerType.SYSTEM_EVENT

    asyncio.run(check())
    actual = IterationRef.from_input(binding, second, ordinal=1)
    assert actual.domain_fingerprint == binding.binding_fingerprint
    assert actual.request_id == second.request_id


@pytest.mark.parametrize(
    "bad_field", ["subject_id", "identity_scope", "session_id", "tenant_id"]
)
def test_g02_mismatched_scope_rejected(bad_field: str) -> None:
    binding, original = binding_input()
    corrupt = original.model_copy(update={bad_field: "wrong"})
    with pytest.raises(IterationCorrelationError):
        binding.iteration_input(corrupt, ordinal=1)


def test_g02_cross_iteration_replay_and_negative_ordinal_rejected() -> None:
    binding, original = binding_input()
    second = binding.iteration_input(original, ordinal=1)
    with pytest.raises(IterationCorrelationError):
        IterationRef.from_input(binding, second, ordinal=2)
    with pytest.raises(IterationCorrelationError):
        binding.iteration_input(original, ordinal=-1)


def test_g01_shared_policy_gate_rejects_request_mismatch() -> None:
    # This test intentionally uses a structurally mocked constraint so that
    # correlation is rejected before priority/disposition resolution.
    class Constraint:
        request_id = "other-request"
        policy_decision = build_policy_decision()

    with pytest.raises(OrchestrationInvariantError):
        assert_admission_allows_flow(
            constraint=cast(RuntimeConstraint, Constraint()),
            request_id="current-request",
            policy_decision=Constraint.policy_decision,
        )


def test_g03_prod_modules_do_not_import_tests_or_sandbox_factory() -> None:
    # Static dependency invariant: a production class cannot import a test verifier.
    for package in ("runtime", "agent_core"):
        for path in Path(package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    assert not node.module.startswith("tests"), str(path)
                    assert "sandbox" not in node.module.lower(), str(path)
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert not alias.name.startswith("tests"), str(path)
                        assert "sandbox" not in alias.name.lower(), str(path)
