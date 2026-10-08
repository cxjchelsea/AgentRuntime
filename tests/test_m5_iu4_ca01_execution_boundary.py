"""CA-M5-IU4-01 controlled execution-boundary gates."""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from runtime.contracts.planning import ActionStep, ApprovedActionPlan
from runtime.execution import (
    ApprovedToolInvoker,
    CapabilityExecutionOwner,
    CapabilityInvocationIdentifierFactory,
    M5ToolResult,
    ToolExecutionStatus,
    ToolInputValidator,
    ToolInvocationJournalEntry,
    ToolOutputValidator,
    ToolPayloadValidationDecision,
    ToolPayloadValidationStatus,
)
from runtime.registries import ToolDefinition


class StaticIdentifierFactory:
    def new_tool_call_id(
        self,
        *,
        step_execution_id: str,
        tool_id: str,
    ) -> str:
        return f"{step_execution_id}:{tool_id}:call"

    def new_workflow_instance_id(
        self,
        *,
        step_execution_id: str,
        workflow_id: str,
    ) -> str:
        return f"{step_execution_id}:{workflow_id}:workflow"


class StaticInputValidator:
    def validate(
        self,
        tool_definition: ToolDefinition,
        input_payload: dict[str, Any],
    ) -> ToolPayloadValidationDecision:
        del tool_definition, input_payload
        return ToolPayloadValidationDecision(
            status=ToolPayloadValidationStatus.VALID,
            reason_codes=("INPUT_VALID",),
        )


class StaticOutputValidator:
    def validate(
        self,
        tool_definition: ToolDefinition,
        tool_result: M5ToolResult,
    ) -> ToolPayloadValidationDecision:
        del tool_definition, tool_result
        return ToolPayloadValidationDecision(
            status=ToolPayloadValidationStatus.VALID,
            reason_codes=("OUTPUT_VALID",),
        )


class NeverInvokeToolGateway:
    async def invoke(
        self,
        *,
        tool_id: str,
        input_payload: dict[str, Any],
    ) -> M5ToolResult:
        del tool_id, input_payload
        raise AssertionError("CA contract test must not invoke a real Tool")


def test_validation_decision_requires_reason_code() -> None:
    with pytest.raises(ValueError, match="reason_codes"):
        ToolPayloadValidationDecision(
            status=ToolPayloadValidationStatus.UNKNOWN,
            reason_codes=(),
        )


def test_invocation_contracts_are_dependency_injectable() -> None:
    identifier_factory: CapabilityInvocationIdentifierFactory = (
        StaticIdentifierFactory()
    )
    input_validator: ToolInputValidator = StaticInputValidator()
    output_validator: ToolOutputValidator = StaticOutputValidator()
    tool_invoker: ApprovedToolInvoker = NeverInvokeToolGateway()

    assert (
        identifier_factory.new_tool_call_id(
            step_execution_id="step-execution-001",
            tool_id="DOMAIN_TOOL",
        )
        == "step-execution-001:DOMAIN_TOOL:call"
    )
    assert input_validator is not None
    assert output_validator is not None
    assert tool_invoker is not None


def test_tool_journal_binds_exact_tool_identity_to_result() -> None:
    result = M5ToolResult(
        tool_call_id="tool-call-001",
        tool_id="DOMAIN_TOOL",
        status=ToolExecutionStatus.SUCCESS,
    )

    entry = ToolInvocationJournalEntry(
        tool_call_id="tool-call-001",
        tool_id="DOMAIN_TOOL",
        tool_version="1.0.0",
        result=result,
    )

    assert entry.tool_version == "1.0.0"
    assert entry.result is result


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("tool_call_id", "other-call"),
        ("tool_id", "OTHER_TOOL"),
    ],
)
def test_tool_journal_rejects_result_identity_drift(
    field_name: str,
    value: str,
) -> None:
    result = M5ToolResult(
        tool_call_id=value if field_name == "tool_call_id" else "tool-call-001",
        tool_id=value if field_name == "tool_id" else "DOMAIN_TOOL",
        status=ToolExecutionStatus.SUCCESS,
    )

    with pytest.raises(ValueError, match="must match"):
        ToolInvocationJournalEntry(
            tool_call_id="tool-call-001",
            tool_id="DOMAIN_TOOL",
            tool_version="1.0.0",
            result=result,
        )


def test_execution_owner_is_internal_not_canonical_action_step() -> None:
    assert "execution_owner" not in ActionStep.model_fields
    assert "execution_owner" not in ApprovedActionPlan.model_fields
    assert tuple(owner.value for owner in CapabilityExecutionOwner) == (
        "SKILL",
        "WORKFLOW",
        "NONE",
    )


def test_invocation_factory_contract_does_not_embed_uuid_policy() -> None:
    source = inspect.getsource(CapabilityInvocationIdentifierFactory)

    assert "uuid" not in source.lower()
    assert "random" not in source.lower()
