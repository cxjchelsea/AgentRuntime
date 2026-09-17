"""M0-IU3：Registry 基础设施最小校验。

只验证注册、查询、隔离与错误模型。
不得在测试中调用真实业务执行。
"""

from __future__ import annotations

import inspect

import pytest

from runtime.registries import (
    BaseRegistry,
    CapabilityRegistry,
    DomainManifest,
    DomainRegistry,
    DuplicateRegistrationError,
    InvalidRegistryItemError,
    PolicyDefinition,
    PolicyRegistry,
    PromptDefinition,
    PromptLayer,
    PromptRegistry,
    RegistryItemNotFoundError,
    SchemaDefinition,
    SchemaRegistry,
    SchemaScope,
    SkillDefinition,
    SkillRegistry,
    ToolDefinition,
    ToolRegistry,
    WorkflowDefinition,
    WorkflowRegistry,
)
from runtime.registries.capability import CapabilityDefinition


def _skill_definition(
    skill_id: str = "TEST_SKILL", version: str = "1.0.0"
) -> SkillDefinition:
    return SkillDefinition(skill_id=skill_id, version=version, enabled=True)


def _workflow_definition(
    workflow_id: str = "TEST_WORKFLOW", version: str = "1.0.0"
) -> WorkflowDefinition:
    return WorkflowDefinition(workflow_id=workflow_id, version=version, enabled=True)


def _tool_definition(
    tool_id: str = "TEST_TOOL", version: str = "1.0.0"
) -> ToolDefinition:
    return ToolDefinition(tool_id=tool_id, version=version, enabled=True)


def _policy_definition(
    rule_id: str = "TEST_POLICY", version: str = "1.0.0"
) -> PolicyDefinition:
    return PolicyDefinition(
        rule_id=rule_id, version=version, priority=10, scope="runtime"
    )


def _prompt_definition(
    prompt_id: str = "TEST_PROMPT",
    version: str = "1.0.0",
    layer: PromptLayer = PromptLayer.RUNTIME_BASE,
) -> PromptDefinition:
    return PromptDefinition(prompt_id=prompt_id, version=version, layer=layer)


def _domain_manifest(
    domain_id: str = "TEST_DOMAIN", version: str = "1.0.0"
) -> DomainManifest:
    return DomainManifest(
        domain_id=domain_id,
        name="test_domain",
        version=version,
        enabled=True,
        registered_intents=["TEST_INTENT"],
        registered_skills=["TEST_SKILL"],
        registered_tools=["TEST_TOOL"],
    )


def _schema_definition(
    schema_id: str,
    version: str = "1.0.0",
    scope: SchemaScope = SchemaScope.DOMAIN,
) -> SchemaDefinition:
    return SchemaDefinition(schema_id=schema_id, version=version, scope=scope)


def test_register_get_exists_list() -> None:
    """合法对象可以注册、查询、列举。"""
    skill_registry = SkillRegistry()
    skill_definition = _skill_definition()
    skill_registry.register(skill_definition)

    assert skill_registry.exists("TEST_SKILL", "1.0.0") is True
    stored_record = skill_registry.get("TEST_SKILL", "1.0.0")
    assert stored_record.definition.skill_id == "TEST_SKILL"
    listed_records = skill_registry.list()
    assert len(listed_records) == 1


def test_duplicate_identifier_and_version_is_rejected() -> None:
    """同一 identifier + version 不得静默覆盖。"""
    skill_registry = SkillRegistry()
    skill_registry.register(_skill_definition())
    with pytest.raises(DuplicateRegistrationError):
        skill_registry.register(_skill_definition())
    assert skill_registry.get("TEST_SKILL", "1.0.0").definition.enabled is True


def test_get_missing_item_raises_not_found() -> None:
    """未注册对象必须抛出明确 NotFound。"""
    tool_registry = ToolRegistry()
    with pytest.raises(RegistryItemNotFoundError):
        tool_registry.get("MISSING_TOOL", "1.0.0")


def test_invalid_identifier_is_rejected() -> None:
    """空标识符属于无效注册项。"""
    skill_registry = SkillRegistry()
    with pytest.raises(InvalidRegistryItemError):
        skill_registry.register(_skill_definition(skill_id=""))


def test_multiple_versions_can_be_listed() -> None:
    """同一 identifier 的不同 version 可精确获取并列出。"""
    skill_registry = SkillRegistry()
    skill_registry.register(_skill_definition(version="1.0.0"))
    skill_registry.register(_skill_definition(version="1.1.0"))
    assert skill_registry.get("TEST_SKILL", "1.0.0").definition.version == "1.0.0"
    assert skill_registry.get("TEST_SKILL", "1.1.0").definition.version == "1.1.0"
    listed_versions = {record.definition.version for record in skill_registry.list()}
    assert listed_versions == {"1.0.0", "1.1.0"}


def test_skill_workflow_tool_policy_prompt_do_not_execute() -> None:
    """Registry 不提供执行 / 调用 / 评估方法。"""
    forbidden_method_names = {
        "execute",
        "call",
        "invoke",
        "evaluate",
        "render",
        "generate",
        "run",
    }
    registry_types = [
        SkillRegistry,
        WorkflowRegistry,
        ToolRegistry,
        PolicyRegistry,
        PromptRegistry,
        DomainRegistry,
        SchemaRegistry,
        CapabilityRegistry,
    ]
    for registry_type in registry_types:
        public_methods = {
            method_name
            for method_name, _method in inspect.getmembers(
                registry_type, inspect.isfunction
            )
            if not method_name.startswith("_")
        }
        assert forbidden_method_names.isdisjoint(public_methods), registry_type.__name__


def test_implementation_reference_is_stored_but_not_called() -> None:
    """可以绑定 implementation reference，但 Registry 不得调用它。"""

    class ProbeImplementation:
        def __init__(self) -> None:
            self.called = False

        def execute(self) -> None:
            self.called = True

    probe_implementation = ProbeImplementation()
    skill_registry = SkillRegistry()
    skill_registry.register(
        _skill_definition(),
        implementation_ref=probe_implementation,
    )
    stored_record = skill_registry.get("TEST_SKILL", "1.0.0")
    assert stored_record.implementation_ref is probe_implementation
    assert probe_implementation.called is False


def test_domain_registry_accepts_test_manifest() -> None:
    """DomainRegistry 可注册纯测试 DomainManifest。"""
    domain_registry = DomainRegistry()
    domain_manifest = _domain_manifest()
    domain_registry.register(domain_manifest)
    stored_record = domain_registry.get("TEST_DOMAIN", "1.0.0")
    assert stored_record.definition.domain_id == "TEST_DOMAIN"
    assert stored_record.definition.registered_intents == ["TEST_INTENT"]


def test_test_domain_has_no_real_business_semantics() -> None:
    """测试 Domain 不得使用真实 Domain Example 值。"""
    domain_manifest = _domain_manifest()
    forbidden_values = {"PLAY_CONTENT", "DISCOMFORT", "CLINICAL_DIAGNOSIS"}
    registered_intents = domain_manifest.registered_intents or []
    registered_skills = domain_manifest.registered_skills or []
    registered_values = set(registered_intents) | set(registered_skills)
    assert forbidden_values.isdisjoint(registered_values)


def test_schema_registry_separates_core_and_domain() -> None:
    """SchemaRegistry 能区分 Core / Domain Schema。"""
    schema_registry = SchemaRegistry()
    schema_registry.register(
        _schema_definition("core.runtime_input", scope=SchemaScope.CORE)
    )
    schema_registry.register(
        _schema_definition("domain.test_state", scope=SchemaScope.DOMAIN)
    )
    core_record = schema_registry.get("core.runtime_input", "1.0.0")
    domain_record = schema_registry.get("domain.test_state", "1.0.0")
    assert core_record.definition.scope is SchemaScope.CORE
    assert domain_record.definition.scope is SchemaScope.DOMAIN


def test_domain_registered_value_does_not_enter_core_enum() -> None:
    """Domain 注册值可以进入 Registry，但不进入 Core Enum。"""
    from runtime.contracts import CoreControlIntent, InputSource, RuntimeControlState

    skill_registry = SkillRegistry()
    skill_registry.register(_skill_definition(skill_id="TEST_CUSTOM_INTENT_SKILL"))
    core_enum_values = {
        enum_member.value
        for enum_type in (CoreControlIntent, InputSource, RuntimeControlState)
        for enum_member in enum_type
    }
    assert "TEST_CUSTOM_INTENT_SKILL" not in core_enum_values
    assert "PLAY_CONTENT" not in core_enum_values


def test_registries_do_not_share_state() -> None:
    """不同 Registry 实例互不污染，可供依赖注入。"""
    first_skill_registry = SkillRegistry()
    second_skill_registry = SkillRegistry()
    first_skill_registry.register(_skill_definition())
    assert first_skill_registry.exists("TEST_SKILL", "1.0.0") is True
    assert second_skill_registry.exists("TEST_SKILL", "1.0.0") is False

    tool_registry = ToolRegistry()
    assert tool_registry.exists("TEST_SKILL", "1.0.0") is False


def test_enable_disable_and_unregister() -> None:
    """M5 冻结的 enable / disable，以及显式 unregister。"""
    workflow_registry = WorkflowRegistry()
    workflow_registry.register(_workflow_definition())
    workflow_registry.disable("TEST_WORKFLOW", "1.0.0")
    assert workflow_registry.get("TEST_WORKFLOW", "1.0.0").enabled is False
    workflow_registry.enable("TEST_WORKFLOW", "1.0.0")
    assert workflow_registry.get("TEST_WORKFLOW", "1.0.0").enabled is True
    workflow_registry.unregister("TEST_WORKFLOW", "1.0.0")
    assert workflow_registry.exists("TEST_WORKFLOW", "1.0.0") is False


def test_policy_and_prompt_registration() -> None:
    """Policy / Prompt 只注册定义，不执行。"""
    policy_registry = PolicyRegistry()
    policy_registry.register(_policy_definition())
    prompt_registry = PromptRegistry()
    prompt_registry.register(_prompt_definition(layer=PromptLayer.CONSTRAINT))
    assert policy_registry.get("TEST_POLICY", "1.0.0").definition.priority == 10
    assert (
        prompt_registry.get("TEST_PROMPT", "1.0.0").definition.layer
        is PromptLayer.CONSTRAINT
    )


def test_base_registry_generic_register() -> None:
    """BaseRegistry 自身支持 register / get / exists / list。"""
    base_registry: BaseRegistry[str] = BaseRegistry()
    base_registry.register("TEST_ITEM", "1.0.0", "payload")
    assert base_registry.exists("TEST_ITEM", "1.0.0") is True
    assert base_registry.get("TEST_ITEM", "1.0.0").definition == "payload"
    assert len(base_registry.list()) == 1


def test_type_mismatch_and_empty_definition_are_rejected() -> None:
    """类型不匹配或空定义必须失败，不得静默接受。"""
    skill_registry = SkillRegistry()
    with pytest.raises(InvalidRegistryItemError):
        skill_registry._store("TEST_SKILL", "1.0.0", _tool_definition())  # type: ignore[arg-type]
    with pytest.raises(InvalidRegistryItemError):
        skill_registry._store("TEST_SKILL", "1.0.0", None)  # type: ignore[arg-type]


def test_capability_registry_registers_definition_only() -> None:
    """CapabilityRegistry 只登记能力目录项，不执行实现。"""
    capability_registry = CapabilityRegistry()
    capability_definition = CapabilityDefinition(
        capability_id="TEST_CAPABILITY",
        version="1.0.0",
        domain="TEST_DOMAIN",
        implementation_type="SKILL",
        skills=["TEST_SKILL"],
    )
    capability_registry.register(capability_definition)
    stored_record = capability_registry.get("TEST_CAPABILITY", "1.0.0")
    assert stored_record.definition.skills == ["TEST_SKILL"]
