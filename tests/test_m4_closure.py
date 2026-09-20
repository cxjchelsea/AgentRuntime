"""M4 closure structural gates.

These gates prove only the Runtime/Planning mechanism boundary. They do not claim
Domain business closure, production readiness, clinical validation, or real K0/M5
execution.
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import fields

import runtime.planning.runtime_integration as runtime_integration_module
from runtime.interfaces.planning import Planner, PlanValidator, PolicyRechecker
from runtime.planning import (
    DefaultM4Planner,
    RuntimePlanValidatorAdapter,
    RuntimePolicyRecheckerAdapter,
    ValidationReceipt,
)


def test_m4_runtime_components_implement_frozen_planning_interfaces() -> None:
    assert issubclass(DefaultM4Planner, Planner)
    assert issubclass(RuntimePlanValidatorAdapter, PlanValidator)
    assert issubclass(RuntimePolicyRecheckerAdapter, PolicyRechecker)


def test_m4_runtime_integration_adds_no_new_runtime_stage_or_execution_dependency() -> (
    None
):
    source = inspect.getsource(runtime_integration_module)
    tree = ast.parse(source)
    imported_modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module)

    forbidden_prefixes = (
        "runtime.interfaces.execution",
        "runtime.execution",
        "runtime.knowledge",
        "runtime.response",
        "runtime.update",
        "runtime.validation",
        "requests",
        "httpx",
    )
    assert not any(
        module.startswith(prefix)
        for module in imported_modules
        for prefix in forbidden_prefixes
    )


def test_m4_runtime_integration_does_not_construct_approved_plan_directly() -> None:
    source = inspect.getsource(runtime_integration_module)
    tree = ast.parse(source)

    direct_approved_constructors = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ApprovedActionPlan"
    ]

    assert direct_approved_constructors == []


def test_validation_receipt_contains_only_integrity_metadata() -> None:
    assert [field.name for field in fields(ValidationReceipt)] == [
        "plan_id",
        "request_id",
        "fingerprint",
        "validation_codes",
    ]


def test_m4_runtime_integration_hardcodes_no_business_knowledge_taxonomy() -> None:
    source = inspect.getsource(runtime_integration_module)

    for business_token in (
        "HEALTH",
        "WEATHER",
        "NEWS",
        "CONTENT",
        "MEDICAL",
    ):
        assert business_token not in source
