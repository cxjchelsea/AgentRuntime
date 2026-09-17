"""M0-IU4：Runtime Orchestrator Skeleton E2E 校验。

验证 10 节点主链、15 个实现调用点顺序、Error Boundary。
不验证真实业务智能。
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest

from runtime.contracts import (
    ActionPlanDraft,
    ApprovedActionPlan,
    CoreControlIntent,
    ExecutionResult,
    PlanApprovalStatus,
    ResponsePlan,
    RuntimeResponse,
    UpdateResult,
    ValidatedResult,
)
from runtime.interfaces.input import InputProcessor
from runtime.orchestration.logging import RuntimeLogHook
from runtime.registries import SkillRegistry
from tests.orchestration_stubs import (
    CallRecorder,
    ExplodingPlanner,
    StubContextBuilder,
    StubExecutionEngine,
    StubInputProcessor,
    StubPlanner,
    StubPlanValidator,
    StubPolicyEngine,
    StubPolicyRechecker,
    StubResponseGenerator,
    StubResponsePlanner,
    StubResponseValidator,
    StubResultValidator,
    StubSafetyGuard,
    StubStateMemoryUpdater,
    StubUnderstandingEngine,
    build_runtime_input,
)

EXPECTED_CALL_ORDER = [
    "INPUT",
    "SAFETY_EARLY",
    "CONTEXT",
    "UNDERSTANDING",
    "SAFETY_DEEP",
    "POLICY",
    "PLAN",
    "PLAN_VALIDATE",
    "POLICY_RECHECK",
    "EXECUTE",
    "RESULT_VALIDATE",
    "RESPONSE_PLAN",
    "RESPONSE_GENERATE",
    "RESPONSE_VALIDATE",
    "UPDATE",
]


class _StubBundle:
    """一组带同一 CallRecorder 的 Stub 依赖。"""

    def __init__(self) -> None:
        self.call_recorder = CallRecorder()
        self.input_processor = StubInputProcessor(self.call_recorder)
        self.safety_guard = StubSafetyGuard(self.call_recorder)
        self.context_builder = StubContextBuilder(self.call_recorder)
        self.understanding_engine = StubUnderstandingEngine(self.call_recorder)
        self.policy_engine = StubPolicyEngine(self.call_recorder)
        self.planner = StubPlanner(self.call_recorder)
        self.plan_validator = StubPlanValidator(self.call_recorder)
        self.policy_rechecker = StubPolicyRechecker(self.call_recorder)
        self.execution_engine = StubExecutionEngine(self.call_recorder)
        self.result_validator = StubResultValidator(self.call_recorder)
        self.response_planner = StubResponsePlanner(self.call_recorder)
        self.response_generator = StubResponseGenerator(self.call_recorder)
        self.response_validator = StubResponseValidator(self.call_recorder)
        self.state_memory_updater = StubStateMemoryUpdater(self.call_recorder)


def _build_orchestrator(
    stub_bundle: _StubBundle,
    *,
    skill_registry: SkillRegistry | None = None,
    log_hook: RuntimeLogHook | None = None,
):
    """按 Stub 依赖构造 Orchestrator。"""
    from runtime.orchestration import RuntimeOrchestrator

    return RuntimeOrchestrator(
        input_processor=stub_bundle.input_processor,
        safety_guard=stub_bundle.safety_guard,
        context_builder=stub_bundle.context_builder,
        understanding_engine=stub_bundle.understanding_engine,
        policy_engine=stub_bundle.policy_engine,
        planner=stub_bundle.planner,
        plan_validator=stub_bundle.plan_validator,
        policy_rechecker=stub_bundle.policy_rechecker,
        execution_engine=stub_bundle.execution_engine,
        result_validator=stub_bundle.result_validator,
        response_planner=stub_bundle.response_planner,
        response_generator=stub_bundle.response_generator,
        response_validator=stub_bundle.response_validator,
        state_memory_updater=stub_bundle.state_memory_updater,
        skill_registry=skill_registry,
        log_hook=log_hook,
    )


def test_full_chain_returns_response_and_update() -> None:
    """一个 RuntimeInput 可以跑完整链，最终返回 RuntimeResponse + UpdateResult。"""

    async def scenario() -> None:
        stub_bundle = _StubBundle()
        orchestrator = _build_orchestrator(stub_bundle)
        turn_outcome = await orchestrator.run(build_runtime_input())
        runtime_response, update_result = turn_outcome
        assert isinstance(runtime_response, RuntimeResponse)
        assert isinstance(update_result, UpdateResult)
        assert turn_outcome.runtime_response is runtime_response
        assert turn_outcome.update_result is update_result

    asyncio.run(scenario())


def test_fifteen_call_points_in_architecture_order() -> None:
    """15 个实现调用点顺序完全正确，对应架构 10 节点。"""

    async def scenario() -> None:
        stub_bundle = _StubBundle()
        orchestrator = _build_orchestrator(stub_bundle)
        await orchestrator.run(build_runtime_input())
        assert stub_bundle.call_recorder.entries == EXPECTED_CALL_ORDER
        assert stub_bundle.call_recorder.entries.index("SAFETY_EARLY") < (
            stub_bundle.call_recorder.entries.index("CONTEXT")
        )
        assert stub_bundle.call_recorder.entries.index("UNDERSTANDING") < (
            stub_bundle.call_recorder.entries.index("SAFETY_DEEP")
        )
        assert stub_bundle.call_recorder.entries.index("RESPONSE_VALIDATE") < (
            stub_bundle.call_recorder.entries.index("UPDATE")
        )

    asyncio.run(scenario())


def test_planner_and_validator_stay_on_draft() -> None:
    """Planner 输出 Draft；PlanValidator 后仍是 Draft。"""

    async def scenario() -> None:
        stub_bundle = _StubBundle()
        orchestrator = _build_orchestrator(stub_bundle)
        await orchestrator.run(build_runtime_input())
        assert isinstance(stub_bundle.planner.last_output, ActionPlanDraft)
        assert (
            stub_bundle.planner.last_output.approval_status is PlanApprovalStatus.DRAFT
        )
        assert isinstance(stub_bundle.plan_validator.last_output, ActionPlanDraft)
        assert (
            stub_bundle.plan_validator.last_output.approval_status
            is PlanApprovalStatus.DRAFT
        )

    asyncio.run(scenario())


def test_recheck_outputs_approved_and_execution_only_receives_approved() -> None:
    """PolicyRechecker 输出 Approved；ExecutionEngine 只收到 Approved，Draft 不进入。"""

    async def scenario() -> None:
        stub_bundle = _StubBundle()
        orchestrator = _build_orchestrator(stub_bundle)
        await orchestrator.run(build_runtime_input())
        assert isinstance(stub_bundle.policy_rechecker.last_output, ApprovedActionPlan)
        assert (
            stub_bundle.policy_rechecker.last_output.approval_status
            is PlanApprovalStatus.APPROVED
        )
        assert isinstance(
            stub_bundle.execution_engine.received_plan, ApprovedActionPlan
        )
        assert not isinstance(
            stub_bundle.execution_engine.received_plan, ActionPlanDraft
        )

    asyncio.run(scenario())


def test_execution_result_enters_result_validator() -> None:
    """ExecutionResult 必须进入 ResultValidator。"""

    async def scenario() -> None:
        stub_bundle = _StubBundle()
        orchestrator = _build_orchestrator(stub_bundle)
        await orchestrator.run(build_runtime_input())
        assert isinstance(
            stub_bundle.result_validator.received_execution_result, ExecutionResult
        )

    asyncio.run(scenario())


def test_response_pipeline_contracts() -> None:
    """ResponsePlanner 收 ValidatedResult；Generator 只收 ResponsePlan；Validator 被调用。"""

    async def scenario() -> None:
        stub_bundle = _StubBundle()
        orchestrator = _build_orchestrator(stub_bundle)
        await orchestrator.run(build_runtime_input())
        assert isinstance(
            stub_bundle.response_planner.received_validated_result, ValidatedResult
        )
        assert isinstance(
            stub_bundle.response_generator.received_response_plan, ResponsePlan
        )
        assert stub_bundle.response_validator.called is True

    asyncio.run(scenario())


def test_run_is_async() -> None:
    """Orchestrator.run 必须是 async。"""
    from runtime.orchestration import RuntimeOrchestrator

    assert inspect.iscoroutinefunction(RuntimeOrchestrator.run)


def test_stage_exception_is_not_disguised_as_success() -> None:
    """任一 stage 抛异常时 Runtime 不伪造成功。"""
    from runtime.orchestration.errors import StageExecutionError

    async def scenario() -> None:
        stub_bundle = _StubBundle()
        stub_bundle.planner = ExplodingPlanner(stub_bundle.call_recorder)
        orchestrator = _build_orchestrator(stub_bundle)
        with pytest.raises(StageExecutionError) as captured:
            await orchestrator.run(build_runtime_input())
        assert captured.value.stage_name == "PLAN"
        assert "UPDATE" not in stub_bundle.call_recorder.entries

    asyncio.run(scenario())


def test_missing_dependency_fails_explicitly() -> None:
    """缺失依赖时初始化明确失败。"""
    from runtime.orchestration.errors import DependencyMissingError

    stub_bundle = _StubBundle()
    with pytest.raises(DependencyMissingError):
        from runtime.orchestration import RuntimeOrchestrator

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


def test_registry_can_be_injected_without_driving_the_chain() -> None:
    """IU3 Registry 可注入、可访问，但不替代 Orchestrator，不干扰主链。"""

    async def scenario() -> None:
        stub_bundle = _StubBundle()
        skill_registry = SkillRegistry()
        orchestrator = _build_orchestrator(stub_bundle, skill_registry=skill_registry)
        await orchestrator.run(build_runtime_input())
        assert orchestrator.skill_registry is skill_registry
        assert stub_bundle.call_recorder.entries == EXPECTED_CALL_ORDER
        assert skill_registry.list() == []

    asyncio.run(scenario())


def test_domain_values_do_not_enter_runtime_core() -> None:
    """Domain Example 值不得进入 Orchestrator 或测试 Stub 主路径。"""
    forbidden_values = {"PLAY_CONTENT", "DISCOMFORT", "CLINICAL_DIAGNOSIS"}
    orchestration_root = Path("runtime/orchestration")
    stub_source = Path("tests/orchestration_stubs.py").read_text(encoding="utf-8")
    for source_path in orchestration_root.glob("*.py"):
        source_text = source_path.read_text(encoding="utf-8")
        assert forbidden_values.isdisjoint(set(source_text.split()))
    assert forbidden_values.isdisjoint(set(stub_source.split()))
    assert CoreControlIntent.UNKNOWN.value == "UNKNOWN"


def test_orchestrator_does_not_new_concrete_modules() -> None:
    """Orchestrator 不得直接实例化具体 M1-M8 实现。"""
    orchestrator_source = Path("runtime/orchestration/runtime.py").read_text(
        encoding="utf-8"
    )
    assert "StubInputProcessor" not in orchestrator_source
    assert "InputProcessor()" not in orchestrator_source


def test_dependencies_are_interface_types() -> None:
    """注入对象必须实现 IU2 Interface。"""
    stub_bundle = _StubBundle()
    orchestrator = _build_orchestrator(stub_bundle)
    assert isinstance(orchestrator.input_processor, InputProcessor)
