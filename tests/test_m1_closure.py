"""M1-IU3：M1 Closure 静态边界与回归 Gate。

这些检查只证明 M1 Input / Context 的实现边界已经闭合，不把尚无真实 Store、
Adapter 或 Domain 的能力伪装成已实现。
"""

from __future__ import annotations

import inspect
from pathlib import Path

import runtime.context_building as context_building_module
import runtime.input_processing as input_processing_module
from runtime.context_building import (
    ContextKind,
    CoreContextSelector,
    DefaultContextBuilder,
)
from runtime.contracts import InputTriggerType, RuntimeContext, RuntimeInput
from runtime.contracts.context import RuntimeStateContext
from runtime.input_processing import DefaultInputProcessor
from runtime.interfaces import ContextBuilder, InputProcessor

FORBIDDEN_DOMAIN_VALUES = {
    "PLAY_CONTENT",
    "DISCOMFORT",
    "QUIET_COMPANION",
    "CLINICAL_DIAGNOSIS",
}


def test_m1_real_implementations_keep_frozen_interfaces() -> None:
    assert issubclass(DefaultInputProcessor, InputProcessor)
    assert issubclass(DefaultContextBuilder, ContextBuilder)
    assert inspect.iscoroutinefunction(DefaultInputProcessor.process)
    assert inspect.iscoroutinefunction(DefaultContextBuilder.build)

    input_signature = inspect.signature(DefaultInputProcessor.process)
    context_signature = inspect.signature(DefaultContextBuilder.build)
    assert tuple(input_signature.parameters) == ("self", "runtime_input")
    assert tuple(context_signature.parameters) == (
        "self",
        "runtime_input",
        "safety_result",
    )


def test_m1_canonical_contract_surface_was_not_expanded() -> None:
    assert RuntimeInput.__name__ == "RuntimeInput"
    assert RuntimeContext.__name__ == "RuntimeContext"
    assert {
        "identity_context",
        "session_context",
        "runtime_state_context",
    }.issubset(RuntimeContext.model_fields)
    assert "relationship_context" not in RuntimeContext.model_fields
    assert "current_business" not in RuntimeContext.model_fields
    assert "current_business" not in RuntimeStateContext.model_fields


def test_default_selector_never_auto_loads_memory_or_domain_extensions() -> None:
    selector = CoreContextSelector()
    for trigger_type in InputTriggerType:
        runtime_input = RuntimeInput.model_construct(trigger_type=trigger_type)
        selected = selector.select(runtime_input)
        assert ContextKind.MEMORY not in selected
        assert ContextKind.DOMAIN_EXTENSIONS not in selected


def test_context_building_package_has_no_notimplementederror_regression() -> None:
    package_root = Path("runtime/context_building")
    for source_file in package_root.glob("*.py"):
        assert "NotImplementedError" not in source_file.read_text(encoding="utf-8")


def test_m1_runtime_packages_do_not_hardcode_real_domain_values() -> None:
    package_roots = [Path("runtime/input_processing"), Path("runtime/context_building")]
    source_text = "\n".join(
        source_file.read_text(encoding="utf-8")
        for package_root in package_roots
        for source_file in package_root.glob("*.py")
    )
    for forbidden_value in FORBIDDEN_DOMAIN_VALUES:
        assert forbidden_value not in source_text


def test_m1_closure_does_not_claim_store_backed_capabilities() -> None:
    """真实 Store/Adapter 生命周期能力未实现时，不应在 runtime M1 包中伪造类型。"""
    exported_names = set(dir(input_processing_module)) | set(
        dir(context_building_module)
    )
    assert "RawInputAdapter" not in exported_names
    assert "SessionStore" not in exported_names
    assert "ConversationStore" not in exported_names
    assert "MemoryStore" not in exported_names
