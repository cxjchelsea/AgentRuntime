"""M2 Closure Audit：验证 Safety / State / Priority / Policy 控制机制闭环。

这些 Gate 只证明 M2 的控制决策与 Runtime Gate 已闭合，不把尚未实现的
cancel / checkpoint / resume / queue persistence / forced workflow execution
伪装成已实现。
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import is_dataclass
from pathlib import Path

import runtime.contracts as contracts_module
from runtime.constraint_management import RuntimeConstraint, RuntimeConstraintEvaluator
from runtime.interfaces import PolicyEngine, PolicyRechecker, SafetyGuard
from runtime.orchestration import M2RuntimeOrchestrator, RuntimeOrchestrator
from runtime.orchestration.m2_control import PrioritySubjectResolver
from runtime.policy_enforcement import DefaultPolicyRechecker
from runtime.policy_management import DefaultPolicyEngine
from runtime.priority_management import PreemptionEngine, PriorityEngine
from runtime.safety import DefaultSafetyGuard
from runtime.state_management import RuntimeStateEngine

M2_PACKAGE_ROOTS = (
    Path("runtime/safety"),
    Path("runtime/state_management"),
    Path("runtime/priority_management"),
    Path("runtime/policy_management"),
    Path("runtime/constraint_management"),
    Path("runtime/policy_enforcement"),
    Path("runtime/orchestration"),
)

FORBIDDEN_DOMAIN_VALUES = {
    "PLAY_CONTENT",
    "DISCOMFORT",
    "QUIET_COMPANION",
    "CLINICAL_DIAGNOSIS",
    "MEDICAL_REMINDER",
    "ELDER",
    "PATIENT",
}

FORBIDDEN_EFFECT_CALLS = {
    "cancel",
    "checkpoint",
    "resume",
    "enqueue",
    "dequeue",
    "transition",
    "initialize",
}


def test_m2_real_implementations_keep_frozen_interfaces() -> None:
    assert issubclass(DefaultSafetyGuard, SafetyGuard)
    assert issubclass(DefaultPolicyEngine, PolicyEngine)
    assert issubclass(DefaultPolicyRechecker, PolicyRechecker)
    assert inspect.iscoroutinefunction(DefaultSafetyGuard.evaluate_early)
    assert inspect.iscoroutinefunction(DefaultSafetyGuard.evaluate_deep)
    assert inspect.iscoroutinefunction(DefaultPolicyEngine.evaluate)
    assert inspect.iscoroutinefunction(DefaultPolicyRechecker.recheck)


def test_m2_internal_decisions_did_not_expand_canonical_contract_surface() -> None:
    assert is_dataclass(RuntimeConstraint)
    assert "RuntimeConstraint" not in contracts_module.__all__
    assert "PriorityDecision" not in contracts_module.__all__
    assert "PreemptionDecision" not in contracts_module.__all__
    assert "StateTransitionDecision" not in contracts_module.__all__


def test_m2_integrated_runtime_is_explicit_subclass_of_frozen_runtime() -> None:
    assert issubclass(M2RuntimeOrchestrator, RuntimeOrchestrator)
    assert M2RuntimeOrchestrator is not RuntimeOrchestrator


def test_priority_subject_resolution_remains_injected_boundary() -> None:
    assert inspect.isabstract(PrioritySubjectResolver)
    signature = inspect.signature(PrioritySubjectResolver.resolve)
    assert tuple(signature.parameters) == (
        "self",
        "runtime_input",
        "runtime_context",
        "understanding_state",
        "safety_result",
    )


def test_m2_core_packages_do_not_hardcode_real_domain_values() -> None:
    source_text = "\n".join(
        source_file.read_text(encoding="utf-8")
        for package_root in M2_PACKAGE_ROOTS
        for source_file in package_root.glob("*.py")
    )
    for forbidden_value in FORBIDDEN_DOMAIN_VALUES:
        assert forbidden_value not in source_text


def test_m2_runtime_packages_have_no_notimplementederror_regression() -> None:
    for package_root in M2_PACKAGE_ROOTS:
        for source_file in package_root.glob("*.py"):
            assert "NotImplementedError" not in source_file.read_text(encoding="utf-8")


def test_m2_control_gate_does_not_execute_deferred_side_effects() -> None:
    source_file = Path("runtime/orchestration/m2_runtime.py")
    tree = ast.parse(source_file.read_text(encoding="utf-8"))
    called_names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute):
            called_names.add(node.func.attr)
        elif isinstance(node.func, ast.Name):
            called_names.add(node.func.id)
    assert not (called_names & FORBIDDEN_EFFECT_CALLS)


def test_m2_mechanisms_are_present_without_claiming_effect_execution() -> None:
    assert RuntimeStateEngine is not None
    assert PriorityEngine is not None
    assert PreemptionEngine is not None
    assert RuntimeConstraintEvaluator is not None
    assert DefaultPolicyRechecker is not None


def test_m2_orchestrator_keeps_turn_continuity_checks_at_plan_boundaries() -> None:
    source = Path("runtime/orchestration/m2_runtime.py").read_text(encoding="utf-8")
    assert '"PLAN"' in source
    assert '"PLAN_VALIDATE"' in source
    assert '"POLICY_RECHECK"' in source
    assert "_assert_plan_request_id" in source
    assert "RuntimeConstraint.request_id must match current RuntimeInput" in source


def test_m2_closure_does_not_claim_deferred_effect_components() -> None:
    orchestration_exports = set(__import__("runtime.orchestration", fromlist=["*"]).__all__)
    assert "TaskCanceller" not in orchestration_exports
    assert "CheckpointExecutor" not in orchestration_exports
    assert "ResumeExecutor" not in orchestration_exports
    assert "EventQueue" not in orchestration_exports
    assert "ForcedWorkflowExecutor" not in orchestration_exports
