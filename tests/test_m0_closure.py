"""M0-IU6：Skeleton E2E Gate 与 M0 Closure 独立检查。

只验证已落地 Skeleton，不新增 Runtime 能力，不进入 M1。
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
from pathlib import Path
from typing import get_type_hints

import pytest

from runtime.contracts import (
    SCHEMA_VERSION,
    ActionPlanDraft,
    ApprovedActionPlan,
    CoreControlAction,
    CoreControlIntent,
    CoreControlStrategy,
    ExecutionResult,
    PolicyDecision,
    ResponsePlan,
    RuntimeControlState,
    RuntimeResponse,
    UnderstandingState,
    UpdateResult,
    ValidatedResult,
)
from runtime.contracts.planning import PLANNING_SCHEMA_VERSION
from runtime.interfaces import (
    ContextBuilder,
    ExecutionEngine,
    InputProcessor,
    Planner,
    PlanValidator,
    PolicyEngine,
    PolicyRechecker,
    ResponseGenerator,
    ResponsePlanner,
    ResponseValidator,
    ResultValidator,
    SafetyGuard,
    StateMemoryUpdater,
    UnderstandingEngine,
)
from runtime.orchestration.errors import (
    ContractValidationError,
    DependencyMissingError,
    OrchestrationInvariantError,
    StageExecutionError,
)
from runtime.orchestration.logging import RecordingLogHook
from runtime.registries import (
    CapabilityRegistry,
    DomainManifest,
    DomainRegistry,
    DuplicateRegistrationError,
    PolicyRegistry,
    PromptRegistry,
    SchemaRegistry,
    SkillDefinition,
    SkillRegistry,
    ToolDefinition,
    ToolRegistry,
    WorkflowRegistry,
)
from tests.orchestration_stubs import (
    ExplodingExecutionEngine,
    WrongPhaseSafetyGuard,
    WrongTypePlanner,
    build_action_plan_draft,
    build_approved_action_plan,
    build_execution_result,
    build_policy_decision,
    build_response_plan,
    build_runtime_context,
    build_runtime_input,
    build_runtime_response,
    build_safety_result,
    build_understanding_state,
    build_update_result,
    build_validated_result,
)
from tests.test_runtime_orchestrator import (
    EXPECTED_CALL_ORDER,
    _build_orchestrator,
    _StubBundle,
)

SENSITIVE_TEXT = "M0_CLOSURE_SECRET_TEXT"
SENSITIVE_TOKEN = "M0_CLOSURE_SECRET_TOKEN"
FORBIDDEN_DOMAIN_VALUES = {
    "PLAY_CONTENT",
    "DISCOMFORT",
    "QUIET_COMPANION",
    "CLINICAL_DIAGNOSIS",
}
DEPRECATED_CORE_NAMES = {
    "EarlySafetyResult",
    "DeepSafetyResult",
    "elder_id",
    "user_scope",
    "raw_asr_result",
    "facts_to_include",
    "facts_to_avoid",
}
CORE_INTERFACE_TYPES = [
    InputProcessor,
    SafetyGuard,
    ContextBuilder,
    UnderstandingEngine,
    PolicyEngine,
    Planner,
    PlanValidator,
    PolicyRechecker,
    ExecutionEngine,
    ResultValidator,
    ResponsePlanner,
    ResponseGenerator,
    ResponseValidator,
    StateMemoryUpdater,
]
REGISTRY_TYPES = [
    SkillRegistry,
    WorkflowRegistry,
    ToolRegistry,
    PolicyRegistry,
    PromptRegistry,
    DomainRegistry,
    SchemaRegistry,
    CapabilityRegistry,
]


def test_case_01_happy_path() -> None:
    """CASE-01：完整 15 点主链成功，返回 RuntimeResponse + UpdateResult。"""

    async def scenario() -> None:
        stub_bundle = _StubBundle()
        orchestrator = _build_orchestrator(stub_bundle)
        turn_outcome = await orchestrator.run(build_runtime_input())
        runtime_response, update_result = turn_outcome
        assert isinstance(runtime_response, RuntimeResponse)
        assert isinstance(update_result, UpdateResult)
        assert stub_bundle.call_recorder.entries == EXPECTED_CALL_ORDER
        assert turn_outcome.trace.status == "SUCCESS"
        assert [event.stage_name for event in turn_outcome.trace.stage_events] == (
            EXPECTED_CALL_ORDER
        )

    asyncio.run(scenario())


def test_case_02_stage_failure_on_execute() -> None:
    """CASE-02：EXECUTE 失败后后续不再执行，不伪造终点结果。"""

    async def scenario() -> None:
        stub_bundle = _StubBundle()
        stub_bundle.execution_engine = ExplodingExecutionEngine(
            stub_bundle.call_recorder
        )
        orchestrator = _build_orchestrator(stub_bundle)
        with pytest.raises(StageExecutionError) as captured:
            await orchestrator.run(build_runtime_input())
        assert captured.value.stage_name == "EXECUTE"
        assert not isinstance(captured.value, RuntimeResponse)
        assert not isinstance(captured.value, UpdateResult)
        assert captured.value.trace_context is not None
        assert captured.value.trace_context.status == "ERROR"
        assert captured.value.trace_context.stage_events[-1].stage_name == "EXECUTE"
        assert "RESULT_VALIDATE" not in stub_bundle.call_recorder.entries
        assert "UPDATE" not in stub_bundle.call_recorder.entries

    asyncio.run(scenario())


def test_case_03_contract_violation() -> None:
    """CASE-03：错误 Contract 类型 fail fast。"""

    async def scenario() -> None:
        stub_bundle = _StubBundle()
        stub_bundle.planner = WrongTypePlanner(stub_bundle.call_recorder)
        orchestrator = _build_orchestrator(stub_bundle)
        with pytest.raises(ContractValidationError) as captured:
            await orchestrator.run(build_runtime_input())
        assert captured.value.stage_name == "PLAN"
        assert captured.value.trace_context is not None
        assert captured.value.trace_context.stage_events[-1].stage_name == "PLAN"
        assert "POLICY_RECHECK" not in stub_bundle.call_recorder.entries

    asyncio.run(scenario())


def test_case_04_invariant_violation() -> None:
    """CASE-04：Safety phase 不匹配触发 OrchestrationInvariantError。"""

    async def scenario() -> None:
        stub_bundle = _StubBundle()
        stub_bundle.safety_guard = WrongPhaseSafetyGuard(stub_bundle.call_recorder)
        orchestrator = _build_orchestrator(stub_bundle)
        with pytest.raises(OrchestrationInvariantError) as captured:
            await orchestrator.run(build_runtime_input())
        assert captured.value.stage_name == "SAFETY_EARLY"
        assert "CONTEXT" not in stub_bundle.call_recorder.entries

    asyncio.run(scenario())


def test_case_05_missing_dependency() -> None:
    """CASE-05：缺失必需 Interface 不进入主链。"""
    from runtime.orchestration import RuntimeOrchestrator

    stub_bundle = _StubBundle()
    with pytest.raises(DependencyMissingError):
        RuntimeOrchestrator(
            input_processor=stub_bundle.input_processor,
            safety_guard=stub_bundle.safety_guard,
            context_builder=stub_bundle.context_builder,
            understanding_engine=stub_bundle.understanding_engine,
            policy_engine=stub_bundle.policy_engine,
            planner=None,  # type: ignore[arg-type]
            plan_validator=stub_bundle.plan_validator,
            policy_rechecker=stub_bundle.policy_rechecker,
            execution_engine=stub_bundle.execution_engine,
            result_validator=stub_bundle.result_validator,
            response_planner=stub_bundle.response_planner,
            response_generator=stub_bundle.response_generator,
            response_validator=stub_bundle.response_validator,
            state_memory_updater=stub_bundle.state_memory_updater,
        )
    assert stub_bundle.call_recorder.entries == []


def test_case_06_identity_continuity() -> None:
    """CASE-06：同 session 两轮 trace/turn 可区分，且不互相污染。"""

    async def scenario() -> None:
        first_bundle = _StubBundle()
        second_bundle = _StubBundle()
        first_orchestrator = _build_orchestrator(first_bundle)
        second_orchestrator = _build_orchestrator(second_bundle)
        first_outcome = await first_orchestrator.run(
            build_runtime_input(
                request_id="request-a",
                trace_id="trace-a",
                session_id="session-shared",
            )
        )
        second_outcome = await second_orchestrator.run(
            build_runtime_input(
                request_id="request-b",
                trace_id="trace-b",
                session_id="session-shared",
            )
        )
        assert first_outcome.trace.session_id == "session-shared"
        assert second_outcome.trace.session_id == "session-shared"
        assert first_outcome.trace.trace_id != second_outcome.trace.trace_id
        assert first_outcome.trace.turn_id != second_outcome.trace.turn_id
        assert first_outcome.trace.request_id == "request-a"
        assert second_outcome.trace.request_id == "request-b"
        first_stage_ids = {event.trace_id for event in first_outcome.trace.stage_events}
        second_stage_ids = {
            event.trace_id for event in second_outcome.trace.stage_events
        }
        assert first_stage_ids == {"trace-a"}
        assert second_stage_ids == {"trace-b"}

    asyncio.run(scenario())


def test_case_07_registry_isolation() -> None:
    """CASE-07：可注册测试 Domain/Skill/Tool，但不驱动主链，不进入 Core Enum。"""

    async def scenario() -> None:
        skill_registry = SkillRegistry()
        tool_registry = ToolRegistry()
        domain_registry = DomainRegistry()
        skill_registry.register(SkillDefinition(skill_id="TEST_SKILL", version="1.0.0"))
        tool_registry.register(ToolDefinition(tool_id="TEST_TOOL", version="1.0.0"))
        domain_registry.register(
            DomainManifest(
                domain_id="TEST_DOMAIN",
                name="test_domain",
                version="1.0.0",
                registered_skills=["TEST_SKILL"],
                registered_tools=["TEST_TOOL"],
            )
        )
        stub_bundle = _StubBundle()
        orchestrator = _build_orchestrator(stub_bundle, skill_registry=skill_registry)
        await orchestrator.run(build_runtime_input())
        assert stub_bundle.call_recorder.entries == EXPECTED_CALL_ORDER
        assert skill_registry.exists("TEST_SKILL", "1.0.0")
        assert tool_registry.exists("TEST_TOOL", "1.0.0")
        assert domain_registry.exists("TEST_DOMAIN", "1.0.0")
        core_enum_values = {
            enum_member.value
            for enum_type in (
                CoreControlIntent,
                CoreControlAction,
                CoreControlStrategy,
                RuntimeControlState,
            )
            for enum_member in enum_type
        }
        assert "TEST_SKILL" not in core_enum_values
        assert "TEST_DOMAIN" not in core_enum_values
        assert FORBIDDEN_DOMAIN_VALUES.isdisjoint(core_enum_values)

    asyncio.run(scenario())


def test_case_08_privacy_and_exception_wrapping() -> None:
    """CASE-08：日志、Trace、包装异常默认不泄露敏感 payload。"""

    async def scenario() -> None:
        stub_bundle = _StubBundle()
        stub_bundle.execution_engine = ExplodingExecutionEngine(
            stub_bundle.call_recorder
        )
        log_hook = RecordingLogHook()
        orchestrator = _build_orchestrator(stub_bundle, log_hook=log_hook)
        sensitive_input = build_runtime_input(
            text=SENSITIVE_TEXT,
            input_payload={"token": SENSITIVE_TOKEN},
        )
        with pytest.raises(StageExecutionError) as captured:
            await orchestrator.run(sensitive_input)
        wrapper_text = str(captured.value)
        assert SENSITIVE_TEXT not in wrapper_text
        assert SENSITIVE_TOKEN not in wrapper_text
        assert captured.value.trace_context is not None
        serialized_events = json.dumps(
            [
                {
                    "stage_name": event.stage_name,
                    "status": event.status,
                    "error_type": event.error_type,
                    "error_message": event.error_message,
                    "output_contract_type": event.output_contract_type,
                }
                for event in captured.value.trace_context.stage_events
            ],
            default=str,
        )
        assert SENSITIVE_TEXT not in serialized_events
        assert SENSITIVE_TOKEN not in serialized_events
        serialized_logs = json.dumps(log_hook.records, default=str)
        assert SENSITIVE_TEXT not in serialized_logs
        assert SENSITIVE_TOKEN not in serialized_logs

    asyncio.run(scenario())


def test_fourteen_contracts_round_trip_and_unique_names() -> None:
    """14 个 Canonical Contract 名称唯一，schema_version 正确，可往返序列化。"""
    from runtime.contracts import SafetyPhase

    update_result = build_update_result()
    assert update_result.memory_update is not None
    contract_instances = [
        build_runtime_input(),
        build_runtime_context(),
        build_safety_result(SafetyPhase.EARLY),
        build_understanding_state(),
        build_policy_decision(),
        build_action_plan_draft(),
        build_approved_action_plan(),
        build_execution_result(),
        build_validated_result(),
        build_response_plan(),
        build_runtime_response(),
        update_result.state_update,
        update_result.memory_update,
        update_result,
    ]
    contract_type_names = [type(instance).__name__ for instance in contract_instances]
    assert len(contract_type_names) == 14
    assert len(set(contract_type_names)) == 14
    for contract_instance in contract_instances:
        # M4-CA1：仅 Planning Contract 默认 1.1.0，其余仍对齐全局 1.0.0
        expected_schema_version = (
            PLANNING_SCHEMA_VERSION
            if isinstance(contract_instance, ActionPlanDraft | ApprovedActionPlan)
            else SCHEMA_VERSION
        )
        assert contract_instance.schema_version == expected_schema_version
        restored = type(contract_instance).model_validate(
            contract_instance.model_dump(mode="json")
        )
        assert type(restored) is type(contract_instance)


def test_interfaces_are_async_and_contract_aligned() -> None:
    """14 个 Interface 全部存在且为 async，编排器只依赖 Interface。"""
    assert len(CORE_INTERFACE_TYPES) == 14
    for interface_type in CORE_INTERFACE_TYPES:
        public_methods = [
            method_object
            for method_name, method_object in inspect.getmembers(
                interface_type, predicate=inspect.isfunction
            )
            if not method_name.startswith("_")
        ]
        assert public_methods
        assert all(inspect.iscoroutinefunction(method) for method in public_methods)

    from runtime.orchestration import RuntimeOrchestrator

    constructor_hints = get_type_hints(RuntimeOrchestrator.__init__)
    for interface_type in CORE_INTERFACE_TYPES:
        assert interface_type in constructor_hints.values(), interface_type.__name__


def test_registries_have_required_operations_and_duplicate_protection() -> None:
    """Registry 具备 register/get/exists/list，并拒绝静默覆盖。"""
    required_operations = {"register", "get", "exists", "list"}
    for registry_type in REGISTRY_TYPES:
        public_methods = {
            method_name
            for method_name, _method in inspect.getmembers(
                registry_type, inspect.isfunction
            )
            if not method_name.startswith("_")
        }
        assert required_operations.issubset(public_methods)
        assert {"execute", "call", "invoke", "evaluate"}.isdisjoint(public_methods)

    skill_registry = SkillRegistry()
    skill_registry.register(SkillDefinition(skill_id="TEST_SKILL", version="1.0.0"))
    assert skill_registry.exists("TEST_SKILL", "1.0.0")
    assert len(skill_registry.list()) == 1
    with pytest.raises(DuplicateRegistrationError):
        skill_registry.register(SkillDefinition(skill_id="TEST_SKILL", version="1.0.0"))


def test_hygiene_no_stub_leakage_or_blocking_todo() -> None:
    """runtime/ 无测试 Stub、无阻塞 TODO、无非 abstract 的 NotImplementedError。"""
    runtime_root = Path("runtime")
    for python_file in runtime_root.rglob("*.py"):
        source_text = python_file.read_text(encoding="utf-8")
        module_tree = ast.parse(source_text)
        for syntax_node in ast.walk(module_tree):
            if isinstance(syntax_node, ast.ClassDef):
                assert not syntax_node.name.startswith("Stub")
                assert syntax_node.name != "ActionPlan"
                assert syntax_node.name not in {"EarlySafetyResult", "DeepSafetyResult"}
        if "TODO" in source_text or "FIXME" in source_text:
            relative_path = python_file.as_posix()
            assert relative_path.startswith("runtime/interfaces/"), relative_path
        if "NotImplementedError" in source_text:
            assert python_file.parent.name == "interfaces"


def test_deprecated_and_domain_tokens_not_reintroduced_in_runtime() -> None:
    """Deprecated Core 名称与真实 Domain 值不得作为代码标识符重新出现。"""
    runtime_root = Path("runtime")
    for python_file in runtime_root.rglob("*.py"):
        module_tree = ast.parse(python_file.read_text(encoding="utf-8"))
        identifier_names = (
            {
                syntax_node.id
                for syntax_node in ast.walk(module_tree)
                if isinstance(syntax_node, ast.Name)
            }
            | {
                syntax_node.attr
                for syntax_node in ast.walk(module_tree)
                if isinstance(syntax_node, ast.Attribute)
            }
            | {
                syntax_node.name
                for syntax_node in ast.walk(module_tree)
                if isinstance(
                    syntax_node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
                )
            }
        )
        assert DEPRECATED_CORE_NAMES.isdisjoint(identifier_names)
        assert FORBIDDEN_DOMAIN_VALUES.isdisjoint(identifier_names)


def test_orchestrator_boundary_invariants() -> None:
    """关键边界：Draft≠Approved，Execution 只收 Approved，Response 不直接吃 ExecutionResult。"""
    assert ActionPlanDraft is not ApprovedActionPlan
    execute_parameter = inspect.signature(ExecutionEngine.execute).parameters[
        "approved_action_plan"
    ]
    assert execute_parameter.annotation is ApprovedActionPlan
    generate_parameter = inspect.signature(ResponseGenerator.generate).parameters[
        "response_plan"
    ]
    assert generate_parameter.annotation is ResponsePlan
    assert generate_parameter.annotation is not ExecutionResult
    update_return = inspect.signature(StateMemoryUpdater.update).return_annotation
    assert update_return is UpdateResult
    validate_return = inspect.signature(ResultValidator.validate).return_annotation
    assert validate_return is ValidatedResult
    planner_return = inspect.signature(Planner.plan).return_annotation
    assert planner_return is ActionPlanDraft
    rechecker_return = inspect.signature(PolicyRechecker.recheck).return_annotation
    assert rechecker_return is ApprovedActionPlan
    understand_return = inspect.signature(
        UnderstandingEngine.understand
    ).return_annotation
    assert understand_return is UnderstandingState
    understand_return_types = {UnderstandingState}
    assert PolicyDecision not in understand_return_types
    assert ApprovedActionPlan not in understand_return_types
