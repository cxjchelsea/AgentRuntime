# 可复用 Agent Runtime 平台总体设计 V1.0

> **Phase 0 Fix**  
> 首批 Core Contract 以 `缺口设计/可复用Agent Runtime平台 Agent Runtime Core Contract Canonical Registry V1.0.md` 为唯一正式来源。  
> 本文与 Canonical Registry 冲突的名称、字段、枚举立即失效。

## 1. 文档定位

本文件定义一个可被多个 Agent 产品复用的基础平台。平台不以某一具体业务为中心，而以稳定的 Runtime、可插拔 Domain Extension 和可配置 Business Package 为中心。

核心目标：

```text
同一套 Runtime Core
+
不同 Domain Package
=
不同 Agent 产品
```

新项目原则上不重新开发 Context、Policy、Planner、Execution、Validation、Response、Memory、Knowledge、Trace、Eval 等公共能力，而是注入领域 Workflow、Rules、Capabilities、Knowledge、Prompts、Tools、Schemas、State 和 Evaluation Cases。

## 2. 四层总体架构

```text
┌──────────────────────────────────────────────────────────┐
│ L4 Application                                          │
│ 产品入口 / UI / API / Device Adapter / Deployment       │
├──────────────────────────────────────────────────────────┤
│ L3 Business Package                                     │
│ 具体产品能力目录 / 内容 / 配置 / Prompt / Eval Dataset  │
├──────────────────────────────────────────────────────────┤
│ L2 Domain Extension                                     │
│ Domain Workflow / Rules / Capabilities / Domain State   │
│ Domain Schema / Tool Adapter / Knowledge Domain          │
├──────────────────────────────────────────────────────────┤
│ L1 Agent Runtime Core                                   │
│ M0-M8 / K0 / Registry / Trace / Eval Harness            │
└──────────────────────────────────────────────────────────┘
```

### 2.1 Runtime Core

尽量稳定，只处理跨领域共同问题：

```text
Runtime Event
Context
Safety / Policy
Understanding
Planning
Execution
Validation
Response
State / Memory
Knowledge Infrastructure
Registry
Trace
Evaluation Harness
```

### 2.2 Domain Extension

描述“某一类 Agent 领域特有但可复用的机制”，例如医疗、教育、客服、企业助手等。

Domain Extension 可以注册：

```text
Domain Workflow Engine
Domain Rule Set
Domain State
Domain Capability
Domain Schema
Domain Knowledge Policy
Domain Tool Adapter
Domain Evaluation Rules
```

### 2.3 Business Package

描述某一个具体产品的业务资产：

```text
业务能力目录
场景配置
Prompt
内容库
知识数据
工具配置
Workflow 配置
规则参数
Feature Flag
Eval Dataset
```

### 2.4 Application

负责产品装配，不改变 Runtime Core 语义：

```text
Web / App / Robot / API
Authentication
Tenant
Environment
Deployment
UI / TTS / ASR / Device
```

## 3. Runtime 主链

所有 Domain 默认复用同一主链：

```text
① Input Normalize
↓
② Safety Guard
↓
③ Context Builder
↓
④ Intent / Goal Understanding
↓
⑤ Policy & State Engine
↓
⑥ Agent Planner / Orchestrator
↓
⑦ Business Execution
↓
⑧ Result Validation
↓
⑨ Response Planner / Generator
↓
⑩ State / Memory Update
```

工程模块映射：

```text
M0 Runtime Skeleton
M1 Input & Context
M2 Safety / State / Policy
M3 Understanding
M4 Planning & Orchestration
M5 Execution Framework
M6 Result Validation
M7 Response Planning & Generation
M8 State & Memory Update
M9 Domain Package & Business Capability Integration
K0 Knowledge & RAG Infrastructure
```

## 4. Core 与 Domain 的硬边界

Runtime Core 只定义：

```text
接口
生命周期
状态语义
执行模型
Truth Boundary
优先级机制
Registry机制
Trace机制
Evaluation机制
```

Runtime Core 不应硬编码：

```text
具体疾病
具体课程
具体工单
具体内容分类
具体商品
具体领域 Intent
具体领域 Workflow
具体领域 Prompt
具体领域安全规则
```

这些由 Domain Package 注入。

## 5. Domain Package 标准结构

```text
domains/<domain_name>/
├── domain.yaml
├── schemas/
├── intents/
├── rules/
├── policies/
├── workflows/
├── capabilities/
├── skills/
├── tools/
├── knowledge/
├── prompts/
├── state/
├── config/
└── evals/
```

`domain.yaml` 至少声明：

```yaml
domain:
  name: example_domain
  version: 1.0.0

runtime:
  understanding: enabled
  planning: enabled
  memory: enabled
  knowledge: enabled

registries:
  intents: intents/
  workflows: workflows/
  capabilities: capabilities/
  tools: tools/
  prompts: prompts/
  schemas: schemas/

state:
  schema: state/domain_state.yaml

evaluation:
  dataset: evals/
```

## 6. Runtime State 与 Domain State

固定分离：

```text
RuntimeState（Core Control）
├── session
├── current_state            → RuntimeControlState
├── active_task_id
├── active_workflow_id
├── interaction_mode
├── interrupt_state
├── pending_question
└── runtime_flags

DomainState
└── 由 Domain Extension 定义，经 RuntimeContext.domain_extensions 挂载
```

Core `RuntimeControlState` 仅允许：`STARTING` / `IDLE` / `LISTENING` / `PROCESSING` / `RESPONDING` / `WAITING_USER` / `WAITING_EXTERNAL` / `INTERRUPTED` / `ENDED` / `FAILED`。  
内容播放、情绪安抚、求助、不适采集等业务阶段属于 DomainState，不是 Core 状态。

Domain 不允许随意向 RuntimeState 增加业务字段。

Core Identity 仅使用 `subject_id` + `identity_scope`。禁止 `elder_id` 等产品角色字段进入 Core。

## 7. Core Schema 与 Domain Schema

Core Schema 固定（名称以 Canonical Registry 为准）：

```text
RuntimeInput
SafetyResult                  # phase=EARLY 进入主链；phase=DEEP 为 M2 内部
RuntimeContext
UnderstandingState
PolicyDecision
ActionPlanDraft               # M4 内部，不进入 M5
ApprovedActionPlan            # M5 唯一合法规划输入
ExecutionResult
ValidatedResult
ResponsePlan                  # M7 内部
RuntimeResponse
UpdateResult                  # M8 主链终点
StateUpdate                   # UpdateResult 内部
MemoryUpdate                  # UpdateResult 内部
```

禁止再使用歧义名称 `ActionPlan`。禁止把 `StateUpdate` / `MemoryUpdate` 当作主链终点。

Domain Schema Registry 扩展：

```text
DomainEntity
DomainFinding
DomainTask
DomainResult
DomainState
DomainEvidence
```

Domain Schema 必须通过 Core Contract 中定义的 extension / payload / typed reference 接入，不允许绕开主链建立第二套 Runtime。

## 8. Rules / Policy 插件模型

Runtime 提供统一规则接口：

```text
PolicyRule
- rule_id
- priority
- scope
- condition
- effect
- version
```

Domain Package 只提供规则实例和领域解释。

强制优先级原则：

```text
Safety
>
Domain Hard Policy
>
Runtime State Constraint
>
Planner Preference
```

## 9. Workflow 插件模型

某些 Agent 没有强业务流程；某些 Agent 有明确 Domain Workflow。

平台必须同时支持：

```text
Runtime-only Agent
Runtime + Domain Workflow Agent
```

Domain Workflow 负责“业务阶段如何推进”，Runtime 负责“每一轮如何理解、计划、执行、验证和更新”。两者不得混为一层。

## 10. Capability 插件模型

Capability 是稳定语义接口，技术实现可替换：

```text
Capability Contract
        ↓
Implementation V1
Implementation V2
Implementation V3
```

例如 KnowledgeRetrievalCapability 可依次实现为：

```text
Vector RAG
→ Hybrid RAG
→ GraphRAG
→ Agentic Retrieval
```

只要 Capability Contract 不变，上层 Runtime 和 Domain Workflow 不需要因技术升级而重写。

## 11. Prompt 插件模型

Prompt 不写死在代码中，统一通过 Prompt Registry 加载：

```text
Runtime Base Prompt
+
Domain Prompt
+
Task Prompt
+
Runtime Constraints
```

至少支持：

```text
prompt_id
version
domain
stage
model_constraints
schema_contract
```

## 12. Knowledge 插件模型

统一使用 K0 Knowledge Infrastructure。

Domain Package 负责：

```text
Knowledge Domain
Source Policy
Taxonomy
Documents
Metadata Rules
Evidence Requirement
```

K0 负责：

```text
Ingestion
Chunk
Index
Retrieval
Rerank
Evidence Pack
Version / Validity
```

## 13. Tool / Adapter 插件模型

Core Tool Runtime 负责：

```text
Timeout
Retry
Idempotency
Cancellation
Side-effect Trace
ExecutionResult
```

Domain Tool Adapter 负责具体外部系统协议。

## 14. Evaluation 插件模型

平台提供统一 Eval Harness，Domain 提供 Dataset 和领域判定标准。

```text
Core Eval
├── Understanding
├── Planning
├── Execution
├── Validation
├── Response
├── Memory
└── E2E

Domain Eval
├── Domain Rule Cases
├── Workflow Cases
├── Capability Cases
├── Safety Cases
└── Domain Truth Cases
```

## 15. 新 Agent 项目创建流程

```text
1. 创建 Domain Package
2. 定义 Domain State / Schema
3. 注册 Intent / Entity / Need
4. 注册 Rules / Policy
5. 定义 Domain Workflow（如需要）
6. 注册 Capability / Skill / Tool
7. 接入 Knowledge / Prompt
8. 提供 Eval Dataset
9. 通过 Core Contract Validation
10. 做第一个 Vertical Slice
11. E2E Gate
12. 渐进扩展业务能力
```

## 16. 技术升级原则

新增技术时必须先分类：

```text
A. Runtime Core 通用能力？
B. Domain Extension 新能力？
C. 现有 Capability 的新 Implementation？
D. 纯配置 / Prompt / Knowledge 变化？
```

默认优先认为新技术属于 C，而不是修改 Runtime 主链。

## 17. 禁止模式

禁止：

```text
每个项目复制一套 Runtime
每个 Skill 自建一套 RAG
业务 Intent 硬编码进 Core
Domain State 直接污染 RuntimeState
Prompt 散落代码
ToolResult 直接成为用户事实
Capability 内建立隐藏 Runtime
LLM 绕过 Policy 直接调用外部系统
```

## 18. 平台成功判定

至少用两个明显不同的真实 Domain 验证：

```text
Domain A 接入
↓
Runtime Core 不需业务化修改

Domain B 接入
↓
主要通过 Domain Package / Capability Adapter 完成
```

如果每新增一个 Domain 都必须修改 M1～M8 的核心语义，则平台抽象仍不充分。

## 19. 最终原则

```text
Runtime 固定
Domain 机制插件化
Capability 接口稳定
技术实现可替换
Rule / Prompt / Knowledge 配置化
Schema 可扩展但有 Contract
Evaluation 随 Domain 一起交付
```
