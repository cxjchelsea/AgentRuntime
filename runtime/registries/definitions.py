"""Registry 定义对象。

只描述可注册元数据，不包含执行逻辑。
字段来自 M4 / M5 / M9 / 总体设计已冻结项。
"""

from enum import Enum

from runtime.contracts.common import CanonicalModel
from runtime.contracts.enums import PlanningMode


class PromptLayer(str, Enum):
    """Prompt 分层，对应总体设计 Runtime Base / Domain / Task / Constraints。"""

    RUNTIME_BASE = "RUNTIME_BASE"
    DOMAIN = "DOMAIN"
    TASK = "TASK"
    CONSTRAINT = "CONSTRAINT"


class SchemaScope(str, Enum):
    """Schema 命名空间：Core 与 Domain 分离。"""

    CORE = "CORE"
    DOMAIN = "DOMAIN"


class IntrusivenessLevel(str, Enum):
    """M4 Action / Strategy 冻结的通用侵入性等级。"""

    VERY_LOW = "VERY_LOW"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ActionDefinition(CanonicalModel):
    """M4 Action Registry 项。

    Action 只定义“系统可以做什么”，不等于计划批准，也不包含执行逻辑。
    具体业务 action_id / category 由 Domain Registry 注入。
    """

    action_id: str
    version: str
    category: str
    description: str
    intrusiveness_level: IntrusivenessLevel
    requires_confirmation: bool
    required_capability: str | None
    allowed_planning_modes: list[PlanningMode]
    enabled: bool = True


class StrategyDefinition(CanonicalModel):
    """M4 Strategy Registry 项。

    Strategy 描述合法 Action 如何组合/选择，不重新做 M3 Understanding，也不绕过 M2。
    具体 strategy_id / goal / need / emotion 值由 Domain Package 注入。
    """

    strategy_id: str
    version: str
    description: str
    preferred_goals: list[str]
    preferred_needs: list[str]
    compatible_emotions: list[str]
    required_conditions: list[str]
    avoid_conditions: list[str]
    default_actions: list[str]
    intrusiveness_level: IntrusivenessLevel
    enabled: bool = True


class SkillDefinition(CanonicalModel):
    """Skill 定义。不执行 Skill。"""

    skill_id: str
    version: str
    enabled: bool = True
    supported_actions: list[str] | None = None
    required_tools: list[str] | None = None
    optional_tools: list[str] | None = None
    allowed_states: list[str] | None = None
    input_schema: str | None = None
    output_schema: str | None = None
    timeout_policy: str | None = None
    retry_policy: str | None = None
    idempotency_policy: str | None = None
    side_effect_level: str | None = None


class WorkflowDefinition(CanonicalModel):
    """Workflow 定义。不管理实例状态。"""

    workflow_id: str
    version: str
    enabled: bool = True
    states: list[str] | None = None
    entry_conditions: list[str] | None = None
    exit_conditions: list[str] | None = None


class ToolDefinition(CanonicalModel):
    """Tool 定义。不调用外部系统。"""

    tool_id: str
    version: str
    enabled: bool = True
    description: str | None = None
    input_schema: str | None = None
    output_schema: str | None = None
    timeout_policy: str | None = None
    retry_policy: str | None = None
    idempotency_mode: str | None = None
    side_effect_level: str | None = None
    required_permissions: list[str] | None = None


class PolicyDefinition(CanonicalModel):
    """Policy / Rule 定义。不在 Registry 内求值。"""

    rule_id: str
    version: str
    priority: int
    scope: str
    trigger: str | None = None
    effect: str | None = None
    enabled: bool = True


class PromptDefinition(CanonicalModel):
    """Prompt 资产定义。不调用模型。"""

    prompt_id: str
    version: str
    layer: PromptLayer
    domain: str | None = None
    stage: str | None = None
    model_constraints: str | None = None
    schema_contract: str | None = None


class DomainManifest(CanonicalModel):
    """Domain 清单。不加载或执行领域业务。"""

    domain_id: str
    name: str
    version: str
    enabled: bool = True
    runtime_compatibility: str | None = None
    required_core_schemas: list[str] | None = None
    registered_schemas: list[str] | None = None
    registered_intents: list[str] | None = None
    registered_workflows: list[str] | None = None
    registered_capabilities: list[str] | None = None
    registered_skills: list[str] | None = None
    registered_tools: list[str] | None = None
    knowledge_domains: list[str] | None = None
    prompt_packages: list[str] | None = None
    state_schema: str | None = None
    eval_packages: list[str] | None = None
    feature_flags: list[str] | None = None


class SchemaDefinition(CanonicalModel):
    """Schema 引用。Domain Schema 不得改写 Core Contract。"""

    schema_id: str
    version: str
    scope: SchemaScope
    namespace: str | None = None
    schema_reference: str | None = None


class CapabilityDefinition(CanonicalModel):
    """业务能力目录项。对应 M9 BusinessCapabilityRegistry。"""

    capability_id: str
    version: str
    domain: str | None = None
    implementation_type: str | None = None
    status: str | None = None
    business_taxonomy_ref: str | None = None
    intents: list[str] | None = None
    entities: list[str] | None = None
    needs: list[str] | None = None
    skills: list[str] | None = None
    workflows: list[str] | None = None
    tools: list[str] | None = None
    knowledge_dependencies: list[str] | None = None
    state_dependencies: list[str] | None = None
    policy_dependencies: list[str] | None = None
    validation_dependencies: list[str] | None = None
    eval_cases: list[str] | None = None
