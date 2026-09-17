# 可复用 Agent Runtime 平台
# M9 Domain Package & Business Capability Integration 详细实现方案 V2.0

> **Phase 0 Fix**  
> Domain 必须通过 Registry 注入 Intent / Action / Strategy / Need / DomainState / DomainIdentity。  
> 不得要求修改 Core Schema 以支持 `elder` / `patient` / `student` 等角色。  
> Domain Identity 只能挂在 `RuntimeContext.domain_extensions.identity`。

> M9 不再表示某个固定产品的业务模块接入，而是定义 **任意 Domain Package 如何装载到统一 Runtime Core**。M9 是平台从“通用 Runtime”进入“具体 Agent 产品”的唯一标准扩展层。

# 01. 阶段定位

M0～M8 定义通用 Runtime；K0 定义通用知识基础设施；M9 定义领域业务如何接入。

```text
Runtime Core
M0-M8 + K0
        ↓
M9 Domain Integration
        ↓
Domain Package
        ↓
Concrete Agent Application
```

M9 不是第九个智能层，不引入第二套 Runtime。

# 02. 核心目标

每个 Domain Package 必须把领域差异映射为标准扩展对象：

```text
Domain Manifest
Domain Schema
Domain Intent / Entity / Need
Domain Rules / Policy
Domain Workflow
Domain Capability
Skill
Tool Adapter
Knowledge Domain
Prompt Package
Domain State
Validation Rule
Response Policy
Memory Policy
Eval Dataset
```

# 03. Domain Package 目录规范

```text
domains/<domain>/
├── domain.yaml
├── schemas/
├── intents/
├── entities/
├── needs/
├── rules/
├── policies/
├── workflows/
├── capabilities/
├── skills/
├── tools/
├── knowledge/
├── prompts/
├── state/
├── validation/
├── response/
├── memory/
├── config/
└── evals/
```

# 04. Domain Manifest

```text
DomainManifest
- domain_id
- name
- version
- runtime_compatibility
- required_core_schemas
- registered_schemas[]
- registered_intents[]
- registered_workflows[]
- registered_capabilities[]
- registered_skills[]
- registered_tools[]
- knowledge_domains[]
- prompt_packages[]
- state_schema
- eval_packages[]
- feature_flags[]
```

加载 Domain 前必须做 Compatibility Validation。

# 05. 业务能力目录与 Runtime Intent 的关系

Domain Package 可以拥有任意规模的业务能力 Taxonomy，但：

```text
Business Capability Item
!=
Runtime Intent
!=
Skill
!=
Workflow
```

多个业务目录项可以复用同一个 Intent / Skill / Workflow，仅通过参数、知识、配置或内容变化实现。

# 06. Capability Classification

每个业务能力必须首先分类：

```text
CONTENT_ONLY
CONFIG_ONLY
DIALOGUE_ONLY
RULE_ONLY
SKILL
WORKFLOW
TOOL_BACKED_SKILL
EXTERNAL_API_SKILL
KNOWLEDGE_BACKED_SKILL
COMPOSITE_CAPABILITY
```

分类决定开发工作量和依赖。

# 07. Intent / Entity / Need 接入

M3 Core 只定义理解结果结构和 Registry 机制。Domain Package 注册实际领域语义。

```text
IntentDefinition
EntityDefinition
NeedDefinition
```

要求：

```text
有唯一ID
有版本
有适用Domain
有正反例
有冲突关系
有 Eval Cases
```

不得把完整业务目录机械转成大量 Intent。

# 08. Rules / Policy 接入

Domain Rule 通过统一 Policy Registry 加载。

```text
DomainRule
- rule_id
- priority
- scope
- trigger
- condition
- effect
- forced_action
- forbidden_actions
- version
```

强规则不能藏在 Prompt 中。

# 09. Domain Workflow 接入

只有确有业务阶段推进要求时才定义 Workflow。

```text
DomainWorkflow
- workflow_id
- states[]
- transitions[]
- entry_conditions
- exit_conditions
- interrupt_policy
- resume_policy
- checkpoint_policy
```

Runtime 每轮仍走 M1～M8；Workflow 只作为 M2/M4/M5 使用的领域状态机。

# 10. Capability 接入

```text
DomainCapability
- capability_id
- contract
- input_schema
- output_schema
- implementation
- required_tools[]
- required_knowledge[]
- policy_requirements[]
- validation_requirements[]
```

Capability Contract 与 Implementation 分离。

# 11. Skill 接入

Skill 是 M5 可直接执行的逻辑能力。

```text
SkillDefinition
- skill_id
- input_schema
- output_schema
- side_effect_level
- timeout_policy
- retry_policy
- idempotency_policy
```

# 12. Tool Adapter 接入

具体外部系统只能通过 Tool Adapter 进入 M5。

```text
ToolDefinition
- tool_id
- adapter
- auth_requirement
- timeout
- retry
- side_effect
- truth_semantics
```

Tool 成功不等于业务事实成立。

# 13. Knowledge Domain 接入

Domain 只提供知识资产和治理策略；索引、检索、Rerank、Evidence Pack 统一复用 K0。

```text
KnowledgeDomainConfig
- domain
- taxonomy
- source_policy
- metadata_schema
- ingestion_rules
- evidence_requirement
```

# 14. Prompt Package 接入

```text
PromptPackage
- prompt_id
- stage
- domain
- version
- base_template
- schema_contract
- forbidden_behavior
- eval_cases
```

Prompt 不得承担 Hard Policy、Workflow State Machine 或 Truth Validation。

# 15. Domain State 接入

```text
RuntimeState
!=
DomainState

Core Identity
!=
Domain Identity
```

Domain State 只能通过 `RuntimeContext.domain_extensions.domain_state` 挂载。  
Domain Identity 只能通过 `RuntimeContext.domain_extensions.identity` 挂载。  
不允许修改 Runtime Core Schema，也不允许把 `elder_id` 提升为一等 Core 字段。

# 16. Validation Rule 接入

Domain 可以提供额外 Validation Rule，但必须运行在 M6 统一框架内。

```text
DomainValidationRule
- rule_id
- target_result_type
- evidence_requirement
- validation_logic
- allowed_claims
- forbidden_claims
```

# 17. Response Policy 接入

Domain 可以定义术语、格式、语气、免责声明、表达边界，但 M7 仍遵守：

```text
Validated Truth
→ ResponsePlan
→ RuntimeResponse
```

Domain Prompt 不能扩大 M6 的 Allowed Claims。

# 18. Memory Policy 接入

Domain 可以定义哪些领域对象具有记忆资格，但最终写入仍由 M8 Memory Governance 决定。

```text
MemoryCandidate
→ Validation
→ Write Policy
→ Conflict
→ Scope
→ Lifecycle
→ Commit
```

# 19. Capability Registry

平台只有一个正式业务能力目录：

```text
BusinessCapabilityRegistry
```

至少记录：

```text
capability_id
business_taxonomy_ref
implementation_type
status
domain
intents[]
entities[]
needs[]
skills[]
workflows[]
tools[]
knowledge_dependencies[]
state_dependencies[]
policy_dependencies[]
validation_dependencies[]
eval_cases[]
```

# 20. Capability Status Model

统一状态：

```text
DEFINED
DESIGNED
IMPLEMENTED
WIRED
VERIFIED
E2E_PASSED
RELEASE_READY
```

必须坚持：

```text
CODE EXISTS
!= IMPLEMENTED
!= WIRED
!= VERIFIED
!= BUSINESS LOOP CLOSED
!= RELEASE READY
```

Domain 可在此基础上增加更严格治理状态。

# 21. 新业务能力接入标准流程

```text
1. 建立 Business Capability ID
2. 分类 Implementation Type
3. 确认 Domain Schema
4. 映射 Intent / Entity / Need
5. 确认 Rule / Policy
6. 判断是否需要 Workflow
7. 选择或新增 Capability / Skill
8. 绑定 Tool Adapter
9. 绑定 Knowledge / Prompt
10. 定义 Domain State 更新
11. 定义 M6 Validation
12. 定义 M7 Response Policy
13. 定义 M8 Memory Policy
14. 建立 Unit / Integration Test
15. 建立 E2E Case
16. 更新 Traceability Matrix
17. 通过 Gate
```

# 22. 依赖矩阵

每个 Capability 显式列出：

```text
Runtime Core
Domain Workflow
Rules
Knowledge
External API
Tool
Content Repository
Database
Model
Human Review
```

依赖状态至少：

```text
AVAILABLE
PLANNED
MISSING
NOT_REQUIRED
```

# 23. Domain Workflow 与 Runtime 的边界

```text
Domain Workflow：
业务阶段怎么走

Runtime：
每一轮怎么理解、决策、执行、验证、响应、更新
```

禁止把 Runtime 主链复制到 Workflow 内。

# 24. 新技术接入原则

新增技术优先判断是否只是现有 Capability 的新 Implementation。

```text
RAG → GraphRAG
Single-Agent → Multi-Agent
Rule + LLM → Model + Critic
Local Model → Cloud Model
```

若 Contract 不变，不修改业务 Workflow 和 Runtime Core。

# 25. Vertical Slice 实施策略

每个新 Domain 先做一个最小纵向闭环：

```text
Input
→ M1
→ M2
→ M3
→ M4
→ M5
→ M6
→ M7
→ M8
→ Next Turn
```

第一条 Slice 应选择低风险、依赖明确、结果可验证的能力；随后再验证 Hard Policy / Workflow / External Tool / Memory / Knowledge 等复杂路径。

# 26. M9 Gate

至少满足：

```text
M9-01 Domain Manifest 可被加载和校验
M9-02 Domain Schema 不污染 Core Schema
M9-03 Domain Intent 通过 Registry 注入
M9-04 Hard Rule 不藏在 Prompt
M9-05 Workflow 与 Runtime 主链分离
M9-06 Capability Contract 与 Implementation 分离
M9-07 Tool 仅通过 M5 执行
M9-08 Knowledge 统一使用 K0
M9-09 Domain Validation 运行在 M6
M9-10 Response 不扩大 Validated Claims
M9-11 Memory 写入仍受 M8 Governance
M9-12 Capability Status 可追踪
M9-13 Traceability 可回到 Requirement / Test
M9-14 至少一个 Vertical Slice E2E PASS
M9-15 新 Domain 接入不要求修改 M1-M8 核心语义
```

# 27. 交付物

```text
M9-01 Domain Package规范
M9-02 Domain Manifest Schema
M9-03 Domain Schema Extension规范
M9-04 Intent / Entity / Need Registry规范
M9-05 Domain Rule / Policy规范
M9-06 Domain Workflow规范
M9-07 Capability Contract规范
M9-08 Skill注册规范
M9-09 Tool Adapter规范
M9-10 Knowledge Domain接入规范
M9-11 Prompt Package规范
M9-12 Domain State规范
M9-13 Domain Validation规范
M9-14 Domain Response Policy规范
M9-15 Domain Memory Policy规范
M9-16 Business Capability Registry
M9-17 Capability Status规范
M9-18 Dependency Matrix
M9-19 Domain Integration E2E Dataset
M9-20 Domain Integration Gate报告
```

# 28. 最终原则

```text
Runtime Core 稳定
Domain Mechanism 插件化
Business Capability Registry 化
Knowledge / Prompt / Rule 配置化
Capability Implementation 可替换
Domain State 与 Runtime State 分离
Domain Eval 随 Domain Package 一起交付
```
