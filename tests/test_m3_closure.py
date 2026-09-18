"""M3 Closure Audit: verify Understanding implementation closure without scope inflation.

These gates prove the reusable M3 Understanding mechanism is integrated and bounded.
They do not claim that a real model provider, Domain taxonomy/rules, clinical truth,
Planner, Tool execution, response generation, or memory persistence is implemented.
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import fields, is_dataclass
from pathlib import Path

import runtime.contracts as contracts_module
from runtime.contracts import UnderstandingState
from runtime.interfaces import UnderstandingEngine
from runtime.orchestration import M2RuntimeOrchestrator
from runtime.understanding import (
    CandidateAction,
    MemoryCandidate,
    ModelUnderstandingOutputValidator,
    RiskSignalSet,
    RuntimeUnderstandingEngine,
    StructuredUnderstandingModel,
    UnderstandingEvidence,
    UnderstandingPostprocessResult,
    UnderstandingStateAssembler,
)
from runtime.understanding import model_boundary

M3_PACKAGE_ROOT = Path("runtime/understanding")

FROZEN_UNDERSTANDING_FIELDS = {
    "schema_version",
    "metadata",
    "intents",
    "uncertainty",
    "quality",
    "semantic",
    "goal",
    "entities",
    "references",
    "topic",
    "emotion",
    "needs",
    "interaction",
    "risk",
    "evidence",
    "memory_candidates",
    "candidate_actions",
}

INTERNAL_ONLY_TYPES = {
    "CandidateAction",
    "MemoryCandidate",
    "RiskSignalSet",
    "UnderstandingEvidence",
    "UnderstandingPostprocessResult",
}

FORBIDDEN_DOWNSTREAM_IMPORT_PREFIXES = (
    "runtime.execution",
    "runtime.orchestration",
    "runtime.planning",
    "runtime.policy_enforcement",
    "runtime.policy_management",
    "runtime.response",
    "runtime.safety",
    "runtime.state_management",
    "runtime.update",
    "runtime.validation",
)

FORBIDDEN_EFFECT_CALLS = {
    "approve",
    "cancel",
    "commit",
    "enqueue",
    "execute",
    "persist",
    "resume",
    "save",
    "transition",
    "update",
    "write",
}

FORBIDDEN_DOMAIN_VALUES = {
    "PLAY_CONTENT",
    "DISCOMFORT",
    "QUIET_COMPANION",
    "CLINICAL_DIAGNOSIS",
    "MEDICAL_REMINDER",
    "ELDER",
    "PATIENT",
}

REQUIRED_FORBIDDEN_MODEL_KEYS = {
    "action_plan",
    "approved_action_plan",
    "policy_decision",
    "final_response",
    "response",
    "state_update",
    "memory_write",
    "tool_call",
    "workflow_call",
    "execution_result",
}


def _python_sources() -> list[Path]:
    return sorted(M3_PACKAGE_ROOT.glob("*.py"))


def test_m3_concrete_engine_keeps_frozen_understanding_interface() -> None:
    assert issubclass(RuntimeUnderstandingEngine, UnderstandingEngine)
    assert inspect.iscoroutinefunction(RuntimeUnderstandingEngine.understand)
    signature = inspect.signature(RuntimeUnderstandingEngine.understand)
    assert tuple(signature.parameters) == (
        "self",
        "runtime_input",
        "runtime_context",
    )
    assert signature.return_annotation in {
        "UnderstandingState",
        UnderstandingState,
    }


def test_m3_final_output_surface_is_still_frozen_understanding_state() -> None:
    assert set(UnderstandingState.model_fields) == FROZEN_UNDERSTANDING_FIELDS
    assert "primary_intent" not in UnderstandingState.model_fields
    assert "emotion_label" not in UnderstandingState.model_fields
    assert "risk_level" not in UnderstandingState.model_fields
    assert UnderstandingStateAssembler is not None


def test_m3_internal_types_did_not_become_canonical_contracts() -> None:
    for type_name in INTERNAL_ONLY_TYPES:
        assert type_name not in contracts_module.__all__

    assert is_dataclass(CandidateAction)
    assert is_dataclass(MemoryCandidate)
    assert is_dataclass(RiskSignalSet)
    assert is_dataclass(UnderstandingEvidence)
    assert is_dataclass(UnderstandingPostprocessResult)


def test_candidate_action_has_no_execution_approval_surface() -> None:
    names = {field.name for field in fields(CandidateAction)}
    assert names == {"action", "confidence", "target", "reason_code"}
    assert not (
        names
        & {
            "steps",
            "approval_status",
            "policy_snapshot",
            "tool_requirement",
            "tool_call",
            "workflow_call",
        }
    )


def test_memory_candidate_has_no_persistence_authority() -> None:
    names = {field.name for field in fields(MemoryCandidate)}
    assert not (
        names
        & {
            "commit_status",
            "persisted",
            "store",
            "write_status",
            "memory_record_id",
        }
    )


def test_model_boundary_is_understanding_only() -> None:
    assert inspect.isclass(ModelUnderstandingOutputValidator)
    assert inspect.isclass(StructuredUnderstandingModel)
    assert REQUIRED_FORBIDDEN_MODEL_KEYS <= model_boundary._FORBIDDEN_MODEL_KEYS
    assert "response" not in model_boundary._ALLOWED_OUTPUT_FIELDS
    assert "action_plan" not in model_boundary._ALLOWED_OUTPUT_FIELDS
    assert "tool_call" not in model_boundary._ALLOWED_OUTPUT_FIELDS
    assert "state_update" not in model_boundary._ALLOWED_OUTPUT_FIELDS


def test_model_context_boundary_does_not_expose_whole_runtime_context() -> None:
    selected_fields = {
        field.name for field in fields(model_boundary.SelectedModelContext)
    }
    assert selected_fields == {
        "session_id",
        "current_runtime_state",
        "active_task_id",
        "active_workflow_id",
        "pending_question",
        "current_topic",
        "recent_turns",
        "relevant_memories",
    }
    assert "domain_extensions" not in selected_fields
    assert "safety_context" not in selected_fields
    assert "tool_context" not in selected_fields
    assert "identity_context" not in selected_fields


def test_m3_runtime_package_does_not_import_downstream_authority_modules() -> None:
    violations: list[tuple[str, str]] = []
    for source_file in _python_sources():
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            module_name: str | None = None
            if isinstance(node, ast.ImportFrom):
                module_name = node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(FORBIDDEN_DOWNSTREAM_IMPORT_PREFIXES):
                        violations.append((str(source_file), alias.name))
            if module_name and module_name.startswith(
                FORBIDDEN_DOWNSTREAM_IMPORT_PREFIXES
            ):
                violations.append((str(source_file), module_name))

    assert violations == []


def test_m3_runtime_package_does_not_execute_downstream_side_effects() -> None:
    violations: list[tuple[str, str]] = []
    for source_file in _python_sources():
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called_name: str | None = None
            if isinstance(node.func, ast.Attribute):
                called_name = node.func.attr
            elif isinstance(node.func, ast.Name):
                called_name = node.func.id
            if called_name in FORBIDDEN_EFFECT_CALLS:
                violations.append((str(source_file), called_name))

    assert violations == []


def test_m3_core_package_does_not_hardcode_known_domain_values() -> None:
    source_text = "\n".join(
        source_file.read_text(encoding="utf-8") for source_file in _python_sources()
    )
    for forbidden_value in FORBIDDEN_DOMAIN_VALUES:
        assert forbidden_value not in source_text


def test_m3_production_package_has_no_notimplementederror_regression() -> None:
    for source_file in _python_sources():
        assert "NotImplementedError" not in source_file.read_text(encoding="utf-8")


def test_existing_m2_runtime_keeps_deep_safety_and_policy_authority_after_m3() -> None:
    source = inspect.getsource(M2RuntimeOrchestrator.run)
    understanding_index = source.index('"UNDERSTANDING"')
    deep_safety_index = source.index('"SAFETY_DEEP"')
    policy_index = source.index('"POLICY"')
    plan_index = source.index('"PLAN"')

    assert understanding_index < deep_safety_index < policy_index < plan_index
    assert "evaluate_deep" in source
    assert "_evaluate_integrated_policy" in source


def test_m3_closure_does_not_claim_real_provider_or_downstream_components() -> None:
    understanding_exports = set(
        __import__("runtime.understanding", fromlist=["*"]).__all__
    )
    assert "OpenAIUnderstandingModel" not in understanding_exports
    assert "AnthropicUnderstandingModel" not in understanding_exports
    assert "ToolExecutor" not in understanding_exports
    assert "MemoryStore" not in understanding_exports
    assert "ResponseGenerator" not in understanding_exports
    assert "SafetyDecisionEngine" not in understanding_exports
