"""M5-IU3 CA1 capability-version pinning boundary gates."""

from __future__ import annotations

import inspect

from runtime.contracts import ApprovedActionPlan, PolicyDecision, RuntimeContext
from runtime.contracts.execution import ExecutionResult
from runtime.contracts.planning import ActionStep
from runtime.interfaces.execution import ExecutionEngine


def test_ca1_keeps_capability_versions_out_of_canonical_action_step() -> None:
    fields = set(ActionStep.model_fields)
    assert "skill_version" not in fields
    assert "workflow_version" not in fields
    assert "tool_version" not in fields


def test_ca1_does_not_expand_policy_authority_with_version_fields() -> None:
    fields = set(PolicyDecision.model_fields)
    assert "skill_version" not in fields
    assert "workflow_version" not in fields
    assert "tool_version" not in fields
    assert "allowed_skill_versions" not in fields
    assert "allowed_tool_versions" not in fields


def test_ca1_does_not_add_top_level_version_fields_to_approved_plan() -> None:
    fields = set(ApprovedActionPlan.model_fields)
    assert "skill_version" not in fields
    assert "workflow_version" not in fields
    assert "tool_version" not in fields


def test_ca1_keeps_frozen_execution_engine_signature() -> None:
    signature = inspect.signature(ExecutionEngine.execute)
    assert list(signature.parameters) == [
        "self",
        "approved_action_plan",
        "runtime_context",
    ]
    assert signature.parameters["approved_action_plan"].annotation is ApprovedActionPlan
    assert signature.parameters["runtime_context"].annotation is RuntimeContext
    assert signature.return_annotation is ExecutionResult