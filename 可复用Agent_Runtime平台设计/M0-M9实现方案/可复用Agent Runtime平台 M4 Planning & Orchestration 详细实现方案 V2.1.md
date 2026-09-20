# 可复用 Agent Runtime 平台  
# M4 Planning & Orchestration 详细实现方案 V2.1

> **Phase 0 Fix**  
> 禁止使用歧义名称 `ActionPlan`。M4 输出 `ActionPlanDraft`，校验通过后成为 `ApprovedActionPlan`。M5 只消费后者。  
> Action / Strategy 业务值必须来自 Domain Registry。Core Control Actions / Strategies 见 Canonical Registry §4.20 / §4.21。

> **平台化转换说明**  
> 本文已从单一业务 Agent 设计转换为 **可复用 Agent Runtime 平台**设计。除明确标记为 `Core` 的对象、接口、不变量和生命周期外，任何具体业务 Intent、Entity、Workflow、Skill、Tool、知识域、状态字段、规则、提示词或示例均视为 **Domain Package 示例**，不得硬编码进 Runtime Core。新项目应通过 Registry / Adapter / Plugin / Config 注入领域差异。
> 
> 平台固定边界：`Runtime Core` 尽量稳定；`Domain Extension` 插件化；`Business Package` 配置化；`Application` 负责产品装配。

> 本版本基于 M4 V2.0 更新。  
> V2.0 中的 Goal Resolution、Planning Mode、Action Space、Strategy Library、Memory Usage Decision、Capability Selection、Tool Planning、Active Planning、Clarification Planning、Fast / Agent Planning、Plan Validator、Policy Re-check、Eval、Gate、交付物等内容全部保留。
>
> V2.1 重点补强：
>
> ```text
> Knowledge Need Decision
> Knowledge Domain Routing
> Retrieval Query Construction
> Retrieval Planning
> Evidence Requirement Planning
> RAG 与 M4/M5/M6/M7 的边界
> Knowledge Retrieval Skill Contract
> Knowledge-aware ActionPlan
> Retrieve → Validate → Replan 支持
> ```
>
> 并明确：
>
> ```text
> M4 负责：
> 要不要查知识
> 查什么
> 查哪个知识域
> 用什么检索方式
> 需要什么证据
>
> M5 负责：
> 真正执行检索
>
> Knowledge Infrastructure 负责：
> Document / Chunk / Index / Hybrid Search / Rerank
>
> M6 负责：
> 验证检索证据是否真的可以作为事实
>
> M7 负责：
> 基于验证后的事实进行表达
> ```

---


## 平台扩展补充：Planner 不拥有业务 Action Space

M4 Core 固定 Planning Mode、Goal Resolution、候选动作评估、Knowledge Planning、Plan Validation 与 Policy Re-check。具体 `Action`、`Strategy`、`KnowledgeDomain`、`Capability` 均应来自 Domain Registry；Core Planner 不硬编码某个产品的 Action Space。

# 01. 阶段定位

M4 是 Agent Runtime 的：

```text
Decision & Planning Layer
```

M3 解决：

```text
用户现在是什么意思？
```

M4 解决：

```text
基于当前理解、上下文和规则，

系统下一步最合适做什么？

为了完成这件事，
是否需要获取外部知识？

如果需要，
需要查什么知识？
去哪个知识域查？
需要什么证据？
```

因此 V2.1 的 M4 正式升级为：

```text
Behavior Planning
+
Knowledge Planning
+
Capability Planning
```

可以概括为：

> M3 负责“懂人”，M4 负责“决定下一步做什么，以及完成这一步需要哪些知识和能力”。

---

# 02. 阶段目标与八种智能映射

## 2.1 总体目标

M4 最终完成：

```text
Goal Resolution

+

Planning Mode Routing

+

Strategy Selection

+

Action Candidate Generation

+

Knowledge Need Decision

+

Knowledge Domain Routing

+

Retrieval Query Construction

+

Retrieval Planning

+

Evidence Requirement Planning

+

Memory Usage Decision

+

Clarification Planning

+

Active Interaction Planning

+

Capability Selection

+

Tool Planning

+

Action Sequencing

+

Fallback Planning

+

Response Strategy

+

Plan Validation

+

Policy Re-check
```

最终生成：

```text
Approved ActionPlan
```

---

## 2.2 与八种智能的映射

M4 直接承担：

```text
6. 对话策略智能
7. 主动性智能
```

并大量使用：

```text
2. 上下文智能
3. 关系连续性智能
4. 情绪理解智能
5. 目标与隐含需求推断智能
8. 自我约束智能
```

| 智能能力 | M4职责 |
|---|---|
| 语义理解智能 | 消费 M3，不重复实现 |
| 上下文智能 | 用 Context 影响 Strategy / Retrieval |
| 关系连续性智能 | 决定是否使用 Memory |
| 情绪理解智能 | 调整 Strategy，不重新判断 |
| 目标与隐含需求 | Goal Resolution核心输入 |
| 对话策略智能 | M4核心 |
| 主动性智能 | 主动行为决策 |
| 自我约束智能 | 受 M2 约束，并经 Policy Re-check |

---

# 03. 职责边界

## 3.1 M4 负责

M4 负责：

```text
当前主要目标是什么

当前使用哪种 Planning Mode

当前应采用什么 Strategy

下一步允许做哪些 Action

哪些 Action 更合适

是否需要知识支持

需要哪个 Knowledge Domain

检索 Query 怎么构造

是否需要 Query Rewrite

检索模式是什么

需要什么 Metadata Filter

需要多少候选

是否需要 Rerank

要求什么 Evidence Level

是否使用 Memory

是否需要 Clarification

是否值得主动

选择 Skill / Workflow / Tool

Action 顺序

Fallback

Stop Condition
```

---

## 3.2 M4 不负责

M4 不负责：

```text
真正执行检索

真正访问向量库

真正执行 BM25

真正执行 Reranker

真正读取外部 API

重新判断检索结果真假

生成最终答案文本

直接修改 State

直接写 Memory
```

---

## 3.3 RAG 的正式边界

必须固定：

```text
M4
负责 Retrieval Planning

M5
负责 Retrieval Execution

Knowledge Infrastructure
负责 Index / Search / Rerank

M6
负责 Evidence Validation

M7
负责 Answer Generation
```

---

## 3.4 LLM 在 M4 的边界

LLM 可以：

```text
在合法 Strategy 中做软选择

辅助 Query Rewrite

辅助 Knowledge Domain判断

辅助多候选 Strategy比较
```

LLM 不可以：

```text
创造未注册 Action

绕过 Policy

决定 Safety Workflow

直接调用 Tool

自由改变业务 State

把模型知识当 RAG Evidence
```

---

# 04. 前置依赖与外部依赖

## 4.1 M0 依赖

需要：

```text
Planner Interface

ActionPlan Schema

Registry

Trace

Error / Fallback
```

---

## 4.2 M1 依赖

读取：

```text
RuntimeContext

current_state

current_business

recent_turns

current_topic

active_task

recent_agent_actions

recent_suggestions

recent_rejections

retrieved_memories

time_context

tool_context

interaction_context
```

---

## 4.3 M2 依赖

必须读取：

```text
PolicyDecision

allowed_actions

forbidden_actions

forced_action

forced_workflow

allowed_skills

allowed_tools

interrupt_required

confirmation_required

response_constraints
```

---

## 4.4 M3 依赖

读取：

```text
UnderstandingState

intents

goal

topic

entities

emotion

need

interaction

risk

uncertainty

references

candidate_actions
```

---

## 4.5 Knowledge Infrastructure 依赖

M4 不直接查询知识库，但需要知道：

```text
available_knowledge_domains

domain_capabilities

supported_retrieval_modes

supported_filters

source_policies

freshness_capabilities
```

---

# 05. 输入

建议统一：

```text
PlanningInput

understanding_state

runtime_context

policy_decision

available_capabilities

knowledge_capability_context

recent_action_history

planning_metadata
```

---

# 06. 输出

唯一正式输出：

```text
ActionPlan
```

其中 V2.1 新增：

```text
knowledge_requirement

retrieval_plan

evidence_requirement
```

---

# 07. 核心数据结构

## 7.1 ActionPlan

建议：

```text
ActionPlan

plan_id

schema_version

planning_mode

primary_goal

secondary_goals[]

strategy

steps[]

knowledge_requirement

retrieval_plan

evidence_requirement

memory_usage

capability_selection

tool_plan

confirmation

response_strategy

state_intent

stop_condition

fallback_plan

policy_snapshot

reasoning_summary

quality

metadata
```

---

## 7.2 PlanningMode

继续保留：

```text
FORCED

DETERMINISTIC

AGENT_PLANNED

DEGRADED
```

---

## 7.3 PlanningGoal

```text
PlanningGoal

primary_goal

secondary_goals[]

goal_source

goal_priority

completion_condition
```

---

## 7.4 ActionStep

```text
ActionStep

step_id

action

target

skill

workflow

tool

parameters

depends_on

optional

completion_condition
```

---

# 7.5 KnowledgeRequirement

V2.1 新增核心结构：

```text
KnowledgeRequirement

required

reason

domain

knowledge_type

query_target

source_constraints[]

freshness_requirement

evidence_level

population

scenario

safety_level
```

---

## 7.5.1 required

```text
true / false
```

---

## 7.5.2 domain

例如：

```text
COMPANION

CONTENT

EMOTION

HEALTH

COGNITIVE

REMINDER

WEATHER

NEWS

GENERAL
```

---

## 7.5.3 knowledge_type

例如：

```text
FACTUAL

EXPLANATORY

PROCEDURAL

HEALTH_GUIDANCE

BIOGRAPHICAL

CULTURAL

CURRENT_INFO

CONTENT_METADATA

SAFETY_REFERENCE
```

---

# 7.6 RetrievalQuery

```text
RetrievalQuery

original_query

normalized_query

query_variants[]

entities[]

topics[]

temporal_constraints

population

domain

scenario
```

---

# 7.7 RetrievalPlan

```text
RetrievalPlan

required

domain

query

query_variants[]

retrieval_mode

filters

source_policy

vector_top_k

sparse_top_k

merge_policy

rerank_enabled

rerank_top_n

freshness_requirement

minimum_evidence

fallback_policy
```

---

## 7.7.1 RetrievalMode

建议：

```text
VECTOR

KEYWORD

HYBRID

STRUCTURED_LOOKUP

EXTERNAL_API

NONE
```

---

# 7.8 MetadataFilter

建议支持：

```text
domain

category

scenario

population

content_type

status

source_type

source_trust

safety_level

language

valid_from

valid_to

version
```

---

# 7.9 EvidenceRequirement

```text
EvidenceRequirement

required

minimum_count

minimum_trust

freshness_required

source_diversity_required

conflict_check_required

citation_required
```

---

# 7.10 MemoryUsageDecision

保留：

```text
use_memory

memory_ids[]

usage_mode

reason

risk
```

---

# 7.11 CapabilitySelection

```text
selected_skill

selected_workflow

selected_tools[]

selection_reason
```

---

# 7.12 ToolPlan

```text
tool_calls[]

parallelizable

timeout_policy

required_success
```

---

# 7.13 ResponseStrategy

保留：

```text
communicative_goal

tone

length

question_mode

memory_reference_mode

content_order
```

---

# 08. 数据来源、存储与生命周期

## 8.1 ActionPlan 生命周期

默认：

```text
Turn-Level
```

继续采用：

```text
Receding Horizon Planning
```

---

## 8.2 RetrievalPlan 生命周期

通常：

```text
Current Plan
```

只对当前知识需求有效。

用户换话题后：

```text
不自动复用旧 RetrievalPlan
```

---

## 8.3 KnowledgeRequirement 生命周期

如果当前 Goal 未完成且需要：

```text
Retrieve → Validate → Replan
```

KnowledgeRequirement 可以随：

```text
新的 Runtime Cycle
```

重新计算。

---

## 8.4 Query 不长期持久化为用户 Memory

检索 Query 属于：

```text
Execution / Planning Trace
```

不是长期用户事实。

---

# 09. 内部组件

M4 V2.1 建议正式包含：

```text
PlanningOrchestrator

PlanningRouter

GoalResolver

ForcedPlanner

DeterministicPlanner

AgentStrategyPlanner

DegradedPlanner

StrategySelector

ActionCandidateBuilder

KnowledgeNeedResolver

KnowledgeDomainRouter

RetrievalQueryBuilder

RetrievalPlanner

EvidenceRequirementPlanner

MemoryUsageDecider

CapabilitySelector

ToolPlanner

SequencePlanner

Clarification / Active Eligibility Projection
（由 ActionCandidateProvider / CandidateEligibilityRule / StrategyEligibilityRule / StrategySelectionRule 实现，不设独立 Planner）

FallbackPlanner

ResponseStrategyBuilder

PlanValidator

PolicyRechecker

ActionRegistry

StrategyRegistry
```

---

# 10. 运行时实现主流程

新版正式主流程：

```text
UnderstandingState
+
RuntimeContext
+
PolicyDecision
+
CapabilityRegistry
+
KnowledgeCapabilityContext
        ↓
① Forced Action / Workflow Check
        ↓
② Planning Mode Routing
        ↓
③ Goal Resolution
        ↓
④ Candidate Action Generation
        ↓
⑤ Strategy Selection
        ↓
⑥ Knowledge Need Decision
        ↓
   Need Knowledge?
      ↙       ↘
    No         Yes
     ↓          ↓
              ⑦ Knowledge Domain Routing
                  ↓
              ⑧ Retrieval Query Construction
                  ↓
              ⑨ Retrieval Planning
                  ↓
              ⑩ Evidence Requirement Planning
                  ↓
⑪ Memory Usage Decision
        ↓
⑫ Clarification / Active Eligibility Projection
        ↓
⑬ Capability Selection
        ↓
⑭ Tool Planning
        ↓
⑮ Action Sequence Planning
        ↓
⑯ Fallback Planning
        ↓
⑰ Response Strategy Build
        ↓
⑱ ActionPlan Draft
        ↓
⑲ Plan Validation
        ↓
⑳ Policy Re-check
        ↓
Approved ActionPlan
        ↓
M5
```

---

# 10.1 核心伪代码

```python
async def plan(
    understanding_state,
    runtime_context,
    policy_decision,
    capability_registry,
    knowledge_capability_context
):

    # 1. Forced
    if policy_decision.forced_workflow:
        draft = forced_planner.build(
            policy_decision,
            runtime_context
        )
        return validate_and_approve(
            draft,
            policy_decision
        )

    # 2. Route
    planning_mode = planning_router.route(
        understanding_state,
        runtime_context,
        policy_decision
    )

    # 3. Goal
    goals = goal_resolver.resolve(
        understanding_state,
        runtime_context,
        policy_decision
    )

    # 4. Candidates
    candidates = action_candidate_builder.build(
        goals,
        understanding_state,
        runtime_context,
        policy_decision
    )

    # 5. Strategy
    strategy = strategy_selector.select(
        candidates,
        understanding_state,
        runtime_context,
        policy_decision
    )

    # 6. Knowledge need
    knowledge_requirement = knowledge_need_resolver.resolve(
        goals,
        strategy,
        understanding_state,
        runtime_context
    )

    retrieval_plan = None
    evidence_requirement = None

    if knowledge_requirement.required:

        # 7. Domain
        knowledge_domain = knowledge_domain_router.route(
            knowledge_requirement,
            understanding_state,
            knowledge_capability_context
        )

        # 8. Query
        retrieval_query = retrieval_query_builder.build(
            understanding_state,
            runtime_context,
            knowledge_requirement,
            knowledge_domain
        )

        # 9. Retrieval plan
        retrieval_plan = retrieval_planner.build(
            knowledge_requirement,
            retrieval_query,
            knowledge_domain,
            knowledge_capability_context
        )

        # 10. Evidence
        evidence_requirement = evidence_requirement_planner.build(
            knowledge_requirement,
            retrieval_plan
        )

    # 11. Memory
    memory_decision = memory_usage_decider.decide(
        understanding_state,
        runtime_context,
        strategy
    )

    # 12. Clarification / active
    clarification = clarification_planner.plan(
        understanding_state,
        runtime_context,
        strategy
    )

    active_decision = active_interaction_planner.plan(
        runtime_context,
        policy_decision,
        understanding_state
    )

    # 13. Capability
    capability = capability_selector.select(
        strategy,
        candidates,
        retrieval_plan,
        capability_registry,
        policy_decision
    )

    # 14. Tool
    tool_plan = tool_planner.plan(
        capability,
        candidates,
        retrieval_plan,
        runtime_context
    )

    # 15. Sequence
    steps = sequence_planner.build(
        strategy,
        candidates,
        retrieval_plan,
        capability,
        clarification,
        tool_plan
    )

    # 16. Fallback
    fallback = fallback_planner.build(
        steps,
        capability,
        retrieval_plan,
        tool_plan
    )

    # 17. Response strategy
    response_strategy = response_strategy_builder.build(
        understanding_state,
        strategy,
        steps,
        runtime_context
    )

    # 18. Draft
    draft = action_plan_builder.build(
        planning_mode=planning_mode,
        goals=goals,
        strategy=strategy,
        steps=steps,
        knowledge_requirement=knowledge_requirement,
        retrieval_plan=retrieval_plan,
        evidence_requirement=evidence_requirement,
        memory_usage=memory_decision,
        capability=capability,
        tool_plan=tool_plan,
        fallback=fallback,
        response_strategy=response_strategy
    )

    # 19 + 20
    return validate_and_approve(
        draft,
        policy_decision
    )
```

---

# 11. 各步骤详细实现

## Step 1：Forced Action / Workflow

保留原规则。

如果 M2：

```text
forced_workflow = HelpWorkflow
```

M4：

```text
planning_mode = FORCED

strategy = SAFETY_OVERRIDE

step = ENTER_HELP_WORKFLOW
```

不进入 Agent Planner。

---

# Step 2：Planning Mode Routing

继续：

```text
FORCED

DETERMINISTIC

AGENT_PLANNED

DEGRADED
```

---

## 11.2.1 Deterministic

适用于：

```text
STOP

PAUSE

NEXT

VOLUME

REMINDER_RESPONSE

明确内容播放

简单天气查询
```

---

## 11.2.2 Agent Planned

适用于：

```text
支持型交互

隐含需求

多策略选择

Memory使用

主动行为

复杂知识需求
```

---

# Step 3：Goal Resolution

优先级继续：

```text
Safety Forced Goal
>
Active Critical Task
>
Explicit User Goal
>
Required Task Continuation
>
Strong Implicit Need
>
Agent Opportunity
```

---

# Step 4：Candidate Action Generation

仍然从固定 Action Space 中生成合法候选。

不能让 LLM创造任意动作。

---

# Step 5：Strategy Selection

LLM 主要发挥价值的位置之一。

在：

```text
多个合法策略都可行
```

时选择更适合当前用户的行为。

---

# Step 6：Knowledge Need Decision

V2.1 新增核心步骤。

系统必须先回答：

> 当前 Action 是否真的需要外部知识支持？

---

## 11.6.1 不需要知识

例如：

> “今天没人和我说话。”

M3：

```text
EXPRESS_EMOTION
```

M4：

```text
KnowledgeRequirement.required = false
```

直接进行交互策略。

---

## 11.6.2 需要知识

用户：

> “越剧是怎么来的？”

M4：

```text
required = true

domain = CONTENT / CULTURE

knowledge_type = EXPLANATORY
```

---

## 11.6.3 Health 场景

用户：

> “高血压平时该注意什么？”

M4：

```text
required = true

domain = HEALTH

knowledge_type = HEALTH_GUIDANCE

source_constraints:
APPROVED_HEALTH_KNOWLEDGE

evidence_level = HIGH
```

---

## 11.6.4 Knowledge Need 判断原则

通常以下情况需要：

```text
事实型查询

解释型查询

健康知识

文化知识

实时信息

需要依据知识继续执行任务
```

以下通常不需要：

```text
纯情绪回应

简单控制命令

普通陪伴

用户明确拒绝

结束会话
```

---

# Step 7：Knowledge Domain Routing

根据：

```text
Intent
Topic
Goal
Entities
Scenario
```

路由到：

```text
COMPANION

CONTENT

EMOTION

HEALTH

COGNITIVE

REMINDER

WEATHER

NEWS
```

---

## 11.7.1 Domain Package 中的业务能力目录项的用途

必须固定：

```text
Domain Package 中的业务能力目录项
≠
357 个 Intent
```

它们更适合作为：

```text
Knowledge Taxonomy

Metadata Taxonomy

Scenario Routing Taxonomy
```

例如：

```text
领域交互
→ 家庭话题
→ 子女工作忙
```

可以映射：

```text
domain = COMPANION

category = FAMILY

scenario = CHILDREN_BUSY
```

这可直接用于：

```text
Metadata Filter
```

---

# Step 8：Retrieval Query Construction

绝对不应简单：

```text
user_text
→ vector_search()
```

M4 应生成结构化：

```text
RetrievalQuery
```

---

## 11.8.1 示例

用户：

> “我最近晚上老睡不着，有没有什么办法？”

生成：

```text
original_query:
我最近晚上老睡不着，有没有什么办法

normalized_query:
目标用户失眠 日常改善方法

entities:
失眠

domain:
HEALTH

knowledge_type:
HEALTH_GUIDANCE

population:
elderly
```

---

## 11.8.2 Query Rewrite

LLM 可以用于：

```text
Query Rewrite
```

但必须限制：

```text
不能改变原目标

不能新增疾病诊断

不能生成业务事实
```

---

## 11.8.3 Query Variants

复杂查询可以生成少量：

```text
query_variants[]
```

例如：

```text
目标用户失眠改善

目标用户睡眠困难非药物建议

目标用户夜间难入睡日常管理
```

第一版建议：

```text
1～3个
```

不要无限扩展。

---

# Step 9：Retrieval Planning

M4 生成：

```text
RetrievalPlan
```

但不执行。

---

## 11.9.1 Retrieval Mode 选择

### STRUCTURED_LOOKUP

适合：

```text
明确ID

药品条目

内容资源

固定FAQ
```

---

### KEYWORD

适合：

```text
人名

药名

作品名

精确术语

专有名词
```

---

### VECTOR

适合：

```text
语义相似

开放描述
```

---

### HYBRID

推荐作为通用 RAG 默认：

```text
Dense
+
Sparse
```

---

### EXTERNAL_API

例如：

```text
天气

新闻
```

不应查询静态向量库当实时答案。

---

# Step 10：Evidence Requirement Planning

M4 不能只说：

```text
查点资料
```

而应该说明：

```text
这次知识回答需要多强的 Evidence？
```

例如普通文化：

```text
minimum_trust = MEDIUM
```

Health：

```text
minimum_trust = HIGH

approved_source_only = true

conflict_check_required = true
```

---

# Step 11：Memory Usage Decision

完整保留 V2.0。

Memory 只决定：

```text
该不该用

怎么用
```

不与 Knowledge RAG 混为一谈。

---

## 11.11.1 Memory != Knowledge

必须明确：

```text
Memory
=
关于这个用户的个人上下文

Knowledge
=
关于世界 / 内容 /业务的外部知识
```

例如：

```text
“用户喜欢越剧”
→ Memory

“越剧起源于哪里”
→ Knowledge
```

二者可以同时参与 Planning。

---

# Step 12：Clarification / Active Eligibility Projection

根据 M4 Closure Fix Pack Amendment V1.0，本步骤不再实现独立的 ClarificationPlanner / ActiveInteractionPlanner。

正式责任模型：

```text
M3 uncertainty / needs_clarification
+
RuntimeContext
+
PolicyDecision
+
Domain injected candidate / eligibility / strategy rules
        ↓
进入既有合法 Action / Strategy 空间
```

Clarification / Active Interaction 必须被表达为 registered Action / Strategy，不建立第二套“下一步做什么”的决策器。

如果 Query 本身缺关键条件：

```text
无法安全检索
```

可以先 Clarify。

例如：

> “这个药能不能吃？”

但当前没有：

```text
药名
```

则：

```text
CLARIFY
```

而不是直接做模糊健康检索。

---

# Step 13：Capability Selection

新增支持：

```text
KnowledgeRetrievalSkill
```

例如：

```text
Action:
RETRIEVE_KNOWLEDGE

Skill:
KnowledgeRetrievalSkill

Execution:
M5
```

---

# Step 14：Tool Planning

KnowledgeSkill 可能依赖：

```text
VectorSearchTool

KeywordSearchTool

StructuredLookupTool

RerankTool

ExternalApiTool
```

但 M4 不直接调用。

---

# Step 15：Action Sequence Planning

知识类问题可以形成：

```text
1. RETRIEVE_KNOWLEDGE

2. ANSWER_WITH_EVIDENCE
```

注意第二步：

```text
不能在 M5 直接生成用户答案
```

其真实含义是：

```text
检索结果进入 M6
→ M7表达
```

---

# Step 16：Fallback Planning

知识检索失败时，例如：

```text
No Result

Insufficient Evidence

Knowledge Service unavailable
```

Fallback 可以：

```text
CLARIFY

REPORT_INSUFFICIENT_KNOWLEDGE

REPLAN

USE_APPROVED_FALLBACK
```

不能：

```text
让 LLM 用预训练知识补齐高风险事实
```

---

# Step 17：Response Strategy

保留原设计。

知识问答可能：

```text
communicative_goal =
INFORM
```

Health：

```text
tone =
clear / cautious

length =
short-to-medium
```

---

# Step 18：ActionPlan Draft

现在 Plan 内会明确包含：

```text
knowledge_requirement

retrieval_plan

evidence_requirement
```

---

# Step 19：Plan Validation

新增检查：

```text
Knowledge Domain 是否存在

Retrieval Mode 是否支持

Filter 是否合法

Query 是否为空

Evidence Requirement 是否可满足

实时知识是否错误使用静态库

Health Query 是否要求 approved source

Knowledge Skill 是否已注册
```

---

# Step 20：Policy Re-check

仍经 M2。

例如：

```text
health query
```

即使 Planner 想查：

```text
unsafe source
```

也必须阻止。

---

# 12. 分支、路由与决策规则

## 12.1 Action Space

继续保留原 Action Space，并新增：

```text
RETRIEVE_KNOWLEDGE

ANSWER_WITH_EVIDENCE

WAIT_FOR_KNOWLEDGE

REQUEST_RETRIEVAL_REPLAN
```

其中：

```text
ANSWER_WITH_EVIDENCE
```

是逻辑目标，不是 M4 自己生成文本。

---

# 12.2 Strategy Library

继续：

```text
DIRECT_FULFILLMENT

ACKNOWLEDGE_THEN_FULFILL

ACKNOWLEDGE_THEN_EXPLORE

LISTENING_FIRST

CLARIFY_THEN_ACT

QUIET_PRESENCE

INFORMATION_THEN_FOLLOWUP

MEMORY_SUPPORTED_CONTINUATION

TASK_CONTINUATION

SAFETY_OVERRIDE

GENTLE_TOPIC_SHIFT

CLOSE_CONVERSATION
```

新增知识型：

```text
RETRIEVE_THEN_ANSWER

RETRIEVE_THEN_CLARIFY

RETRIEVE_THEN_REPLAN
```

---

# 12.3 Retrieve Then Answer

普通问答：

```text
KnowledgeNeed
→ Retrieve
→ Validate
→ Answer
```

不需要再次 Planning。

---

# 12.4 Retrieve Then Replan

当知识结果可能影响下一步行为：

```text
Retrieve
↓
M5
↓
M6
↓
New Runtime Event
↓
M4 Replan
```

---

## 12.4.1 典型情况

用户：

> “这种情况严重吗？”

如果检索结果会影响：

```text
是否继续问诊流程
是否需要安全处置
```

则：

```text
RETRIEVE_THEN_REPLAN
```

但高风险最终仍回：

```text
M2 Safety Rule
```

不是由 RAG 自己决定。

---

# 12.5 Knowledge Source Routing

必须区分：

```text
静态知识库

结构化数据库

实时API

用户Memory
```

不能统一塞进向量检索。

---

## 静态知识库

适合：

```text
文化

陪伴知识

健康审核内容

内容背景
```

---

## 结构化数据库

适合：

```text
内容资源

Reminder

药品条目

人物条目

内部业务表
```

---

## 实时 API

适合：

```text
Weather

News
```

---

## Memory

适合：

```text
用户偏好

关系

个人事实

近期状态
```

---

# 12.6 RAG 检索模式

第一版推荐：

```text
Hybrid Search
```

即：

```text
Dense Vector Search
+
Sparse / BM25 Search
```

然后：

```text
Merge
→ Deduplicate
→ Rerank
```

---

# 12.7 为什么不用纯向量

因为：

```text
人名

药名

作品名

地点

精确标题

专有术语
```

Keyword Search 往往更可靠。

而：

```text
开放表达

模糊需求

语义相似问题
```

Vector Search 更有优势。

---

# 12.8 Rerank

M4 决定：

```text
rerank_enabled = true/false
```

真正执行在 M5 / Knowledge Service。

Rerank 可综合：

```text
Semantic Relevance

Keyword Match

Metadata Match

Source Trust

Freshness

Population Match

Scenario Match
```

---

# 12.9 Health Knowledge Rule

Health Domain 默认：

```text
approved_source_only = true

minimum_evidence = HIGH

conflict_check_required = true
```

且：

```text
RAG Result
不能直接成为医学诊断
```

---

# 12.10 Weather / News

必须：

```text
EXTERNAL_API
```

优先。

不能：

```text
Vector Knowledge Base
```

作为当前实时事实来源。

---

# 13. 与 Knowledge / RAG Infrastructure 的正式接口

这是 V2.1 新增的重要部分。

M4 不负责知识库建设，但必须明确依赖接口。

---

## 13.1 KnowledgeDocument

知识基础对象建议：

```text
KnowledgeDocument

document_id

domain

title

content

source

source_type

author

published_at

updated_at

version

status

valid_from

valid_to

audience

safety_level

tags
```

---

## 13.2 KnowledgeChunk

建议：

```text
KnowledgeChunk

chunk_id

document_id

domain

category

scenario

section

content

summary

entities[]

topics[]

population[]

risk_level

source

source_trust

version

valid_from

valid_to

embedding_version
```

---

## 13.3 Chunk 原则

不建议只按：

```text
固定500字
```

切分。

优先：

```text
语义结构

标题层级

业务单元

FAQ单元

规则单元
```

---

## 13.4 Taxonomy

Domain Package 中的业务能力目录项适合作为：

```text
domain

category

scenario

subtopic
```

Metadata 层使用。

---

## 13.5 Index

Knowledge Infrastructure 至少支持：

```text
Vector Index

Keyword / BM25 Index

Metadata Index

Structured Key Index
```

---

# 14. 与前后 M 的接口

## M0 → M4

```text
Planner Interface
ActionPlan Schema
Registry
Trace
```

---

## M1 → M4

```text
RuntimeContext
```

---

## M2 → M4

```text
PolicyDecision
```

---

## M3 → M4

```text
UnderstandingState
```

---

## M4 → M5

输出：

```text
Approved ActionPlan
```

其中可能包含：

```text
RetrievalPlan
```

---

## M5 → Knowledge Service

执行：

```text
KnowledgeRetrievalSkill
```

内部真正完成：

```text
Query Normalization
Metadata Filter
Dense Search
Sparse Search
Candidate Merge
Deduplicate
Rerank
Evidence Selection
```

---

## M5 → M6

输出：

```text
RetrievalResult
```

作为 ExecutionResult 一部分。

---

## M6 → M7

输出：

```text
Verified Knowledge Facts

Allowed Claims

Forbidden Claims
```

---

# 15. 异常、超时与降级

新增知识规划异常：

```text
KNOWLEDGE_DOMAIN_NOT_FOUND

KNOWLEDGE_CAPABILITY_UNAVAILABLE

INVALID_RETRIEVAL_QUERY

UNSUPPORTED_RETRIEVAL_MODE

INVALID_METADATA_FILTER

EVIDENCE_REQUIREMENT_UNSATISFIABLE
```

---

## Knowledge 不可用

不能默认：

```text
LLM自由回答高风险事实
```

可以：

```text
REPORT_INSUFFICIENT_KNOWLEDGE

CLARIFY

DEGRADED ANSWER
```

仅限 Policy 允许范围。

---

# 16. 配置项与可变项

新增：

```text
knowledge_domain_registry

knowledge_type_registry

retrieval_mode_rules

default_top_k

default_rerank_top_n

metadata_filter_rules

evidence_requirement_rules

query_rewrite_rules

source_policy_rules

health_knowledge_policy

freshness_rules
```

原 M4 配置继续保留：

```text
strategy_preferences

strategy_registry

action_registry

intrusiveness_weights

repetition_limits

memory_usage_rules

active_interaction_thresholds

clarification_rules

planning_router_rules

planner_model

prompt_version

schema_version

planning_timeout

max_plan_steps
```

---

# 17. 非功能约束

## 17.1 LLM 不应该成为全部 Planning 的唯一路径

继续固定：

```text
FORCED
→ 不用 LLM

DETERMINISTIC
→ 不用 LLM

AGENT_PLANNED
→ LLM 可参与

DEGRADED
→ 无 LLM 也能运行
```

---

## 17.2 Query Rewrite 不得改变用户目标

必须可追踪：

```text
original_query

normalized_query
```

---

## 17.3 Retrieval Plan 必须可解释

至少回答：

```text
为什么要查？

查哪个 Domain？

为什么用 Hybrid？

用了哪些 Filter？

需要什么 Evidence？
```

---

## 17.4 Knowledge 与 Memory 必须物理/逻辑分层

不能把：

```text
用户偏好
```

和：

```text
世界知识
```

存同一种无约束向量空间后混检。

---

## 17.5 Health RAG 必须高约束

应：

```text
source-controlled

versioned

auditable

evidence-aware
```

---

# 18. Trace / Logging / Observability

新增记录：

```text
knowledge_required

knowledge_reason

selected_domain

retrieval_query

query_variants

retrieval_mode

metadata_filters

source_policy

top_k

rerank_config

evidence_requirement

knowledge_capability_selected
```

原 Planning Trace 继续保留：

```text
planning_mode

primary_goal

candidate_actions

selected_strategy

rejected_actions

memory_decision

active_decision

clarification_decision

capability_selection

tool_plan

steps

fallback_plan

validator_result

policy_recheck_result
```

---

# 19. 版本、兼容与变更影响

新增版本字段：

```text
knowledge_taxonomy_version

retrieval_policy_version

query_rewrite_version

knowledge_domain_version

evidence_requirement_version
```

---

## Breaking Change

以下需要回归：

```text
Knowledge Domain语义变化

RetrievalMode变化

Metadata字段删除

EvidenceLevel语义改变

RetrievalPlan Schema改变
```

---

# 20. 测试 / Eval

除原 Planning Eval 外，增加 RAG Planning Eval。

---

## 20.1 Knowledge Need Accuracy

判断：

```text
该查时查

不该查时不查
```

---

## 20.2 Domain Routing Accuracy

例如：

```text
越剧起源
→ CONTENT / CULTURE

高血压生活管理
→ HEALTH

明天天气
→ WEATHER
```

---

## 20.3 Query Rewrite Accuracy

要求：

```text
不改变原意

能提高检索表达质量

不增加未经用户表达的诊断
```

---

## 20.4 Retrieval Mode Accuracy

测试：

```text
人名
→ KEYWORD / HYBRID

开放解释
→ HYBRID

天气
→ EXTERNAL_API
```

---

## 20.5 Metadata Filter Accuracy

检查：

```text
population

domain

scenario

approved status

validity
```

是否正确。

---

## 20.6 Evidence Requirement Accuracy

Health：

```text
High
```

普通文化：

```text
Standard
```

---

## 20.7 Unnecessary Retrieval Rate

不能用户每说一句都 RAG。

---

## 20.8 Missing Retrieval Rate

需要知识时却直接让 LLM 回答，也是错误。

---

## 20.9 核心新增指标

```text
Knowledge Need Accuracy

Knowledge Domain Accuracy

Retrieval Query Quality

Retrieval Mode Accuracy

Metadata Filter Accuracy

Evidence Requirement Accuracy

Unnecessary Retrieval Rate

Missing Retrieval Rate
```

---

# 21. Gate

保留原 M4 Gate，并新增以下 Gate。

## Gate M4-25

Knowledge Need Decision 正式存在。

---

## Gate M4-26

Planner 能区分：

```text
无需知识

静态知识

结构化查询

实时API

用户Memory
```

---

## Gate M4-27

Knowledge Domain Routing 正式存在。

---

## Gate M4-28

RetrievalQuery 与用户原始输入分离。

---

## Gate M4-29

Query Rewrite 可追踪且不得改变用户目标。

---

## Gate M4-30

RetrievalPlan 正式进入 ActionPlan。

---

## Gate M4-31

Metadata Filter 正式进入 RetrievalPlan。

---

## Gate M4-32

Hybrid Retrieval 可作为通用默认模式。

---

## Gate M4-33

Health Knowledge 可以强制：

```text
approved_source_only
```

---

## Gate M4-34

Weather / News 不允许默认走静态 RAG 获取当前事实。

---

## Gate M4-35

EvidenceRequirement 正式存在。

---

## Gate M4-36

M4 不直接执行 Retriever。

---

## Gate M4-37

M4 不直接读取 Vector DB。

---

## Gate M4-38

检索失败不能自动退化为 LLM 自由补事实。

---

## Gate M4-39

Gate 分类修订为：

```text
CROSS_STAGE_DEFERRED
```

目标路径仍为：

```text
Retrieve
→ Validate
→ Replan
```

但该路径跨越 M5/K0、M6 与新一轮 M4，不能由 M4 Implementation Closure 单独证明。

M4 Closure 要求仅为：

```text
ReplanEntryRequest 已定义
M4 不直接执行 Retrieve / Validate
```

因此本 Gate 在 M4 Implementation Closure 中标记：

```text
NOT_APPLICABLE_FOR_M4_IMPLEMENTATION_CLOSURE
DEFERRED_UNTIL_M5_M6
```

真正 E2E 在 M5 + M6 完成后验证。

---

## Gate M4-40

Domain Package 中的业务能力目录项作为 Knowledge Taxonomy / Metadata 使用，而不是 Intent 爆炸。

---

# 22. 交付物

新版 M4 最终至少形成：

```text
M4-01 Planning总体架构

M4-02 Runtime Planning主流程

M4-03 ActionPlan Schema

M4-04 Action Space规范

M4-05 Strategy Taxonomy

M4-06 Goal Resolution规范

M4-07 Planning Router

M4-08 Forced Planner设计

M4-09 Deterministic Planner设计

M4-10 Agent Strategy Planner设计

M4-11 Degraded Planner设计

M4-12 Knowledge Need Decision规范

M4-13 Knowledge Domain Routing规范

M4-14 KnowledgeRequirement Schema

M4-15 RetrievalQuery Schema

M4-16 Query Rewrite规范

M4-17 RetrievalPlan Schema

M4-18 Metadata Filter规范

M4-19 Retrieval Mode规范

M4-20 EvidenceRequirement规范

M4-21 Memory Usage Decision规范

M4-22 Active Interaction Eligibility规范

M4-23 Capability Selection规范

M4-24 Tool Planning规范

M4-25 Clarification Eligibility规范

M4-26 Sequence Planning规范

M4-27 Fallback Planning规范

M4-28 Plan Validator

M4-29 Policy Re-check规范

M4-30 M4 Prompt规范

M4-31 Action / Strategy Registry规范

M4-32 Knowledge Domain Registry

M4-33 Retrieval Policy Registry

M4-34 M4 Eval Dataset

M4-35 M4 Metrics

M4-36 M4 Trace规范

M4-37 M4自动化测试

M4-38 M4 Gate验证报告
```

---

# 附录 A：M4 + RAG 一图说明

```text
用户输入
   ↓
M3 Understanding
   ↓
M4 Goal / Strategy
   ↓
Knowledge Need?
   │
   ├─ No
   │   ↓
   │  Normal Action Planning
   │
   └─ Yes
       ↓
   Knowledge Domain
       ↓
   Query Rewrite
       ↓
   RetrievalPlan
       ↓
   EvidenceRequirement
       ↓
   ActionPlan
       ↓
M5 KnowledgeRetrievalSkill
       ↓
Knowledge Infrastructure
       ↓
Hybrid Search
       ↓
Rerank
       ↓
RetrievalResult
       ↓
M6 Evidence Validation
       ↓
Verified Knowledge
       ↓
M7 Response
```

---

# 附录 B：Knowledge Infrastructure 建议接口

M4 不实现，但正式依赖：

```text
Knowledge Service

├── Document Repository
├── Chunk Store
├── Vector Index
├── BM25 / Sparse Index
├── Metadata Index
├── Structured Lookup
├── Retriever
├── Reranker
└── Evidence Pack Builder
```

---

# 附录 C：知识库基本结构

## KnowledgeDocument

```text
document_id
domain
title
content
source
source_type
author
published_at
updated_at
version
status
valid_from
valid_to
audience
safety_level
tags
```

## KnowledgeChunk

```text
chunk_id
document_id
domain
category
scenario
section
content
summary
entities[]
topics[]
population[]
risk_level
source
source_trust
version
valid_from
valid_to
embedding_version
```

---

# 附录 D：Chunk 原则

第一版建议：

```text
结构优先
>
固定长度优先
```

即：

```text
按标题

按段落

按语义主题

按FAQ

按业务规则单元
```

切分。

必要时再辅以：

```text
最大token长度
```

---

# 附录 E：典型场景

## E.1 越剧知识

用户：

> “越剧是怎么来的？”

M3：

```text
QUERY_INFORMATION

topic = YUE_OPERA
```

M4：

```text
KnowledgeNeed = REQUIRED

domain = CONTENT

knowledge_type = EXPLANATORY

RetrievalMode = HYBRID

query =
越剧 起源 发展历史
```

---

## E.2 高血压知识

用户：

> “高血压平时应该注意什么？”

M4：

```text
domain = HEALTH

knowledge_type = HEALTH_GUIDANCE

source_policy =
APPROVED_ONLY

evidence_level = HIGH

population = elderly

retrieval_mode = HYBRID
```

---

## E.3 天气

用户：

> “明天冷不冷？”

M4：

```text
domain = WEATHER

retrieval_mode = EXTERNAL_API
```

不能：

```text
vector_search("明天天气")
```

---

## E.4 支持型交互

用户：

> “今天真没意思。”

M4：

```text
KnowledgeNeed = false

strategy =
ACKNOWLEDGE_THEN_EXPLORE
```

不要无意义 RAG。

---

# 附录 F：M4 最终设计原则

最终固定：

```text
一、
M4 不是把所有决策交给 LLM。

二、
强规则由 M2 决定。

三、
明确任务优先走确定性 Planner。

四、
LLM 主要参与多种合法策略之间的软选择。

五、
知识需求必须显式判断。

六、
RAG 不是“用户问题直接丢向量库”。

七、
M4 负责 Retrieval Planning，
不负责 Retrieval Execution。

八、
Memory 和 Knowledge 必须分离。

九、
实时信息不能假装来自静态知识库。

十、
RAG Result 不是事实，
仍必须经过 M6 Validation。

十一、
Domain Package 中的业务能力目录项应主要用于 Knowledge Taxonomy / Metadata，
而不是扩张 Intent Space。

十二、
需要知识时：
先计划检索，
再执行，
再验证，
最后表达。
```

最终可以把新版 M4 压缩成：

```text
M3：
用户到底是什么意思？

M4：
下一步最合适做什么？

如果需要知识：
我需要知道什么？
去哪里查？
怎么查？
需要什么级别的证据？

M5：
真正查、真正做。

M6：
查到的东西到底能不能作为事实？

M7：
把允许表达的事实说出来。
```