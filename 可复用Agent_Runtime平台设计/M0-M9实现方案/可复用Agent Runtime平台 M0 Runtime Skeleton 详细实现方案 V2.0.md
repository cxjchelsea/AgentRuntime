# 可复用 Agent Runtime 平台  
# M0 Runtime Skeleton 详细实现方案 V2.0

> **Phase 0 Fix**  
> 首批 Core Contract 以 Canonical Registry V1.0 为唯一正式来源。  
> 本节及后文若出现歧义 `ActionPlan` / `elder_id` / 扁平 UnderstandingState / `StateUpdate` 作为链终点等旧定义，一律失效。  
> M0 标题中的“桌面式情感陪护”仅为历史产品语境，不是 Core 业务范围。

> **平台化转换说明**  
> 本文已从单一业务 Agent 设计转换为 **可复用 Agent Runtime 平台**设计。除明确标记为 `Core` 的对象、接口、不变量和生命周期外，任何具体业务 Intent、Entity、Workflow、Skill、Tool、知识域、状态字段、规则、提示词或示例均视为 **Domain Package 示例**，不得硬编码进 Runtime Core。新项目应通过 Registry / Adapter / Plugin / Config 注入领域差异。
> 
> 平台固定边界：`Runtime Core` 尽量稳定；`Domain Extension` 插件化；`Business Package` 配置化；`Application` 负责产品装配。

> 本版本为 M0 V1.0 的结构化重整版。  
> 保留前序方案中已经确定的 Runtime 主链、核心数据对象、Registry、Event、Trace、Error/Fallback、PoC、Gate、交付物等全部内容，并按照统一的 22 项详细实现方案模板重新组织。

---

# 01. 阶段定位

M0 是可复用 Agent Runtime 平台的 **Runtime 基础阶段**。

M0 不负责把机器人直接做“聪明”，而是负责搭建：

> 后续所有智能能力、业务模块、Workflow、Skill、Tool、Memory、Policy 能够共同运行的统一 Agent Runtime 骨架。

因此 M0 的目标不是：

```text
让机器人已经具备完整的智能理解和交互能力
```

而是：

```text
让以后所有“智能能力”
能够按照统一方式进入系统、
交换数据、
接受约束、
执行、
验证、
更新状态，
并形成完整闭环。
```

M0 完成以后，系统应该是：

```text
一个“还不聪明，
但运行架构完整”的 Agent Runtime。
```

---

# 02. 阶段目标与八种智能映射

## 2.1 M0 总体目标

M0 负责建立：

```text
输入
→ 安全
→ 上下文
→ 理解
→ 策略
→ 规划
→ 执行
→ 结果验证
→ 回复
→ 状态与记忆更新
```

这一完整 Runtime 管线。

即使 M0 阶段：

```text
Safety Guard = Stub

Context Builder = Stub

Understanding = Stub

Planner = Stub

Memory = Stub
```

也必须能够让一条测试请求完整经过：

```text
Input
→ Runtime
→ Output
```

---

## 2.2 与八种智能能力的关系

M0 不直接实现八种智能，但为八种智能提供统一软件承载。

| 八种智能 | M0 中的承载方式 |
|---|---|
| 语义理解智能 | 建立 UnderstandingState 数据接口 |
| 上下文智能 | 建立 RuntimeContext 数据接口 |
| 关系连续性智能 | 建立 Memory / Relationship 信息进入 Runtime 的接口 |
| 情绪理解智能 | 在 UnderstandingState 中预留情绪结构 |
| 目标与隐含需求推断 | 在 UnderstandingState 中预留 Goal / Need 结构 |
| 对话策略智能 | 建立 ActionPlanDraft / ApprovedActionPlan 标准对象 |
| 主动性智能 | 允许主动事件通过 RuntimeEvent / RuntimeInput 进入系统 |
| 自我约束智能 | 建立 Safety、PolicyDecision、ValidatedResult 等硬约束承载对象 |

因此：

```text
M0 = 八种智能的软件运行底座
```

而不是八种智能本身。

---

# 03. 职责边界

## 3.1 M0 负责

M0 必须负责：

```text
Runtime Engine

Runtime 10 节点骨架

核心数据对象

统一节点接口

Skill / Workflow / Tool 基础契约

Registry

Runtime Event

统一 Error

Fallback

Trace

Logging

Runtime 配置机制

最小闭环 PoC

基础测试与 Gate
```

---

## 3.2 M0 不负责

M0 明确不负责完整实现：

```text
高级 Prompt Engineering

复杂语义理解

情绪识别模型

隐含需求分析

复杂 Planner

完整 Safety Rule

完整状态机业务规则

提醒 Scheduler

长期 Memory 算法

完整业务模块

Domain Package 中的业务能力目录项

最终业务话术

最终内容资产
```

这些分别在 M1～M9 中逐步补齐。

---

## 3.3 Runtime Core 不得承担业务内容知识

Runtime Core 不应该知道：

```text
京剧是什么

越剧是什么

孤独具体有哪些场景

猜谜有什么题目

天气有哪些字段
```

Runtime 只处理：

```text
当前输入是什么

当前上下文是什么

当前理解结果是什么

哪些 Action 被允许

要调用哪个能力

真实执行结果是什么

最终应该如何更新状态
```

具体业务知识属于后续业务模块。

---

# 04. 前置依赖与外部依赖

## 4.1 前置资料依赖

M0 依赖以下已确定上位设计：

```text
八种智能能力规范

八种智能 × M0～M9 映射规范

当前用户端需求说明书

状态机定义

业务优先级定义

安全边界
```

当前需求已经定义用户端 S00～S11、S90 状态、运行时优先级、抢占规则以及“真实业务状态不得由 LLM 伪造”等约束，M0 必须为这些后续实现保留正式接口。

---

## 4.2 软件依赖

M0 本身尽量不绑定具体技术厂商，但至少需要概念上的：

```text
Python Runtime / Application Runtime

配置加载能力

结构化模型 / Schema 能力

日志系统

Trace 标识机制

异步执行能力

基础持久化接口
```

---

## 4.3 M0 不应提前绑定

M0 不应锁死：

```text
具体 LLM 厂商

具体向量数据库

具体 Memory 实现

具体天气 API

具体新闻 API

具体播放服务

具体通知服务
```

这些通过后续接口和 Registry 接入。

---

# 05. 输入

M0 定义系统统一入口：

```text
RuntimeInput
```

Runtime Input 不只来自用户语音。

可能来源包括：

```text
voice
scheduler
system
tool_callback
```

可能的 trigger_type 包括：

```text
user_input
reminder
active_greeting
tool_result
system_event
```

这样未来：

```text
用户说话

09:00 用药提醒

主动问候

通知接口回调

任务超时
```

都可以进入同一 Runtime。

---

# 06. 输出

M0 的统一执行结果建议封装为：

```text
RuntimeOutput
```

至少包含：

```text
response

state_update

memory_update

execution_status

trace_id

error
```

RuntimeOutput 对外不应暴露模型内部自由文本判断作为业务真实状态。

---

# 07. 核心数据结构

M0 固定整条链路中的核心数据对象：

```text
RuntimeInput
SafetyResult                  # phase=EARLY 进入主链
RuntimeContext
UnderstandingState            # 嵌套结构
PolicyDecision
ActionPlanDraft               # M4 内部
ApprovedActionPlan            # M5 唯一输入
ExecutionResult
ValidatedResult
ResponsePlan                  # M7 内部
RuntimeResponse
UpdateResult                  # 主链终点
StateUpdate                   # UpdateResult 内部
MemoryUpdate                  # UpdateResult 内部
```

禁止定义名为 `ActionPlan` 的类型。禁止 `elder_id` 进入 Core。

后续 M1～M8 可以扩展字段，但原则上不再推翻整套数据流。

---

## 7.1 RuntimeInput

建议字段：

```text
RuntimeInput

schema_version
request_id
trace_id
session_id

subject_id
identity_scope
actor_id
device_id
tenant_id

source
input_type
trigger_type

text
raw_text

timestamp

input_payload
confidence
metadata
```

`source` / `trigger_type` 使用 Canonical Registry 的 `InputSource` / `InputTriggerType`。禁止小写并行枚举。

---

## 7.2 RuntimeContext

M0 先建立容器：

```text
RuntimeContext

schema_version
identity_context
session_context
runtime_state_context
conversation_context
task_context
time_context
memory_context
safety_context
tool_context
interaction_context
environment_context
domain_extensions
missing_context[]
```

`business_context` 已失效，改 `domain_extensions`。

M1 再正式定义这些内容如何构建。

---

## 7.3 SafetyResult

预留：

```text
SafetyResult

schema_version
safety_result_id
request_id
phase                         EARLY | DEEP
risk_detected
risk_level
interrupt_current_task
allowed_to_continue_normal_flow
safety_lock_required
reason_codes[]
created_at
```

`EarlySafetyResult` / `DeepSafetyResult` 不是独立 Schema，只是 `phase` 别名。主链节点②使用 `phase=EARLY`。

具体 Safety 实现在 M2。

---

## 7.4 UnderstandingState

M0 预留：

```text
UnderstandingState

schema_version
metadata
intents[]
uncertainty
quality

semantic
goal
entities[]
references[]
topic
emotion
needs[]
interaction
risk
evidence
memory_candidates[]
candidate_actions[]
```

唯一采用嵌套结构。扁平字段（`explicit_intents` / `emotion_intensity` / `ambiguity`）已失效。

M0 阶段允许只返回：

```text
intents = [{intent_id: UNKNOWN}]
```

M3 再完整实现。

---

## 7.5 PolicyDecision

建议：

```text
PolicyDecision

schema_version
policy_decision_id
allowed
blocked
priority
interrupt_current_task
validation_mode
reason_codes[]
created_at

forced_workflow
forced_action
allowed_actions[]
forbidden_actions[]
allowed_skills[]
forbidden_skills[]
allowed_tools[]
forbidden_tools[]
confirmation_required
policy_flags[]
```

`reason` / `interrupt_required` 已失效。

M2 负责正式实现。

---

## 7.6 ActionPlanDraft / ApprovedActionPlan

禁止使用歧义名称 `ActionPlan`。

```text
ActionPlanDraft
approval_status = DRAFT
不得进入 M5

ApprovedActionPlan
approval_status = APPROVED
M5 唯一合法规划输入
```

建议公共字段：

```text
schema_version
plan_id
request_id
approval_status
planning_mode
goals[]
steps[]
quality

strategy
memory_usage
capability_plan
tool_plan
confirmation_plan
response_strategy
state_intent
stop_conditions[]
fallback_plan
policy_snapshot          # Approved 必填
```

---

## 7.7 ExecutionResult

表示真实执行过程结果：

```text
ExecutionResult

schema_version
execution_id
plan_id
request_id
identity_scope
plan_status
step_results[]
timing

skill_results[]
workflow_result
tool_results[]
business_outputs[]
errors[]
```

`plan_status`：

```text
SUCCESS
PARTIAL_SUCCESS
FAILED
TIMEOUT
CANCELLED
PREEMPTED
```

`status` / `executed_skill` / `business_result` 已失效。`plan_status` ≠ BusinessStatus。

---

## 7.8 ValidatedResult

ExecutionResult 与最终可表达事实必须分开。

```text
ValidatedResult

business_status

verified_facts

unverified_facts

allowed_claims

forbidden_claims

safety_flags

fallback_required

validation_errors
```

例如通知 Tool 返回 timeout：

```text
allowed_claims:
- 通知未成功

forbidden_claims:
- 已通知工作人员
- 工作人员正在赶来
```

---

## 7.9 ResponsePlan

```text
ResponsePlan

schema_version
response_plan_id
request_id
response_requirement
claim_plan

communicative_goals[]
content_plan
tone_profile
length_policy
question_plan
tts_constraints
generation_path
```

`facts_to_include` / `facts_to_avoid` 已失效，改 `claim_plan.must_include_claims` / `claim_plan.forbidden_claims`。  
ResponsePlan 是 M7 内部对象；主链对外输出是 RuntimeResponse。

---

## 7.10 StateUpdate / MemoryUpdate / UpdateResult

主链终点只能是 `UpdateResult`。`StateUpdate` 与 `MemoryUpdate` 是其内部结果。

```text
UpdateResult

schema_version
update_id
request_id
identity_scope
state_update
commit_result
memory_update
```

```text
StateUpdate

schema_version
previous_state            → RuntimeControlState
proposed_state            → RuntimeControlState
transition_status
domain_state_update       optional
```

禁止把 Domain 业务状态写入 `proposed_state`。

```text
MemoryUpdate

schema_version
identity_scope
candidates[]
writes[]
```

M0 Stub 允许 `writes=[]`。状态由 Runtime 管理，不能由 LLM 文本直接改变。

---

# 08. 数据来源、存储与生命周期

## 8.1 Turn 级对象

以下对象主要在一次 Runtime Request 中存在：

```text
RuntimeInput
SafetyResult
UnderstandingState
PolicyDecision
ActionPlanDraft
ApprovedActionPlan
ExecutionResult
ValidatedResult
ResponsePlan
RuntimeResponse
UpdateResult
```

原则上属于：

```text
Turn-Level Data
```

---

## 8.2 Session 级对象

例如：

```text
RuntimeContext.session_context

当前话题

当前任务

Pending Question

当前业务
```

后续由 M1 定义完整生命周期。

---

## 8.3 持久状态

至少为以下对象预留持久化接口：

```text
current_state

active_workflow

safety_lock

active_task

important_pending_event

必要 Session 信息
```

尤其避免系统重启后：

```text
# Domain Example：DomainState 丢失后被误判为 IDLE
WAITING_EXTERNAL / DomainState(in_progress)
→ 被误判为 IDLE
```

---

## 8.4 Memory 数据

长期 Memory 不在 M0 实现。

M0 只规定：

```text
Memory 通过标准接口进入 RuntimeContext

Runtime 通过 MemoryUpdate 输出候选更新
```

---

## 8.5 Trace 数据

每轮运行至少需要：

```text
request_id

session_id

trace_id
```

Tool 调用需要：

```text
execution_id

tool_call_id
```

---

# 09. 内部组件

M0 Runtime 至少由以下逻辑组件组成：

```text
Input Processor

Safety Guard

Context Builder

Understanding Engine

Policy / State Engine

Planner / Orchestrator

Execution Engine

Result Validator

Response Engine

State Updater

Memory Updater
```

横向基础能力：

```text
State Store

Session Store

Event Bus / Event Queue

Skill Registry

Workflow Registry

Tool Registry

Policy Registry

Config

Logging

Tracing

Error Handler
```

---

# 10. 运行时实现主流程

这是 M0 最核心的 Runtime Algorithm。

```text
RuntimeInput
      ↓
① Input Processor
      ↓
② Early Safety Guard
      ↓
③ Context Builder
      ↓
④ Understanding Engine
      ↓
⑤ Policy / State Engine
      ↓
⑥ Planner / Orchestrator
      ↓
⑦ Execution Engine
      ↓
⑧ Result Validator
      ↓
⑨ Response Engine
      ↓
⑩ State / Memory Update
      ↓
RuntimeOutput
```

---

## 10.1 Runtime 主控制器伪代码

```python
async def handle(runtime_input):

    normalized_input = input_processor.process(
        runtime_input
    )

    safety_result = safety_guard.check(
        normalized_input
    )

    context = context_builder.build(
        normalized_input,
        safety_result
    )

    understanding = understanding_engine.understand(
        normalized_input,
        context
    )

    policy = policy_engine.evaluate(
        context,
        understanding,
        safety_result
    )

    plan = planner.plan(
        context,
        understanding,
        policy
    )

    execution_result = await executor.execute(
        plan,
        context
    )

    validated_result = validator.validate(
        execution_result,
        plan,
        context
    )

    response_plan = response_engine.plan(
        understanding,
        plan,
        validated_result,
        context
    )

    response = await response_engine.generate(
        response_plan
    )

    state_update = state_updater.update(
        context,
        plan,
        validated_result
    )

    memory_update = memory_updater.update(
        context,
        understanding,
        validated_result
    )

    return RuntimeOutput(
        response=response,
        state_update=state_update,
        memory_update=memory_update
    )
```

---

# 11. 各步骤详细实现

## Step 1：Input Processor

接口：

```text
InputProcessor.process(input)
→ RuntimeInput
```

作用：

```text
统一入口
统一数据结构
生成 request_id / trace_id
```

M0 阶段可以只处理文本测试输入。

---

## Step 2：Safety Guard

接口：

```text
SafetyGuard.check(input, context?)
→ SafetyResult
```

M0：

```text
Stub
```

M2：

```text
正式 Safety Engine
```

---

## Step 3：Context Builder

接口：

```text
ContextBuilder.build(input, ...)
→ RuntimeContext
```

M0 可只返回最基础：

```text
session_id
current_state
```

M1 再补齐。

---

## Step 4：Understanding Engine

接口：

```text
UnderstandingEngine.understand(input, context)
→ UnderstandingState
```

M0 可使用：

```text
StubUnderstanding
```

例如：

```text
输入 “你好”
→ intent = TEST
```

M3 再替换成真实 Rule + LLM Understanding。

---

## Step 5：Policy Engine

接口：

```text
PolicyEngine.evaluate(
    context,
    understanding,
    safety
)
→ PolicyDecision
```

M0 默认：

```text
allowed = true
```

M2 再实现完整规则。

---

## Step 6：Planner

接口：

```text
Planner.plan(
    context,
    understanding,
    policy
)
→ ActionPlanDraft  # 经校验后成为 ApprovedActionPlan
```

M0 只需要输出测试动作。

---

## Step 7：Executor

接口：

```text
Executor.execute(plan, context)
→ ExecutionResult
```

必须通过：

```text
Skill Registry

Workflow Registry

Tool Registry
```

寻找能力。

---

## Step 8：Validator

接口：

```text
Validator.validate(result, ...)
→ ValidatedResult
```

M0 建立框架。

M6 再实现完整真实性校验。

---

## Step 9：Response Engine

接口：

```text
ResponseEngine.plan(...)
→ ResponsePlan

ResponseEngine.generate(...)
→ RuntimeResponse
```

M0 可以使用固定文本。

M7 再实现真正 Response Generation。

---

## Step 10：State / Memory Update

接口：

```text
StateUpdater.update(...)
→ StateUpdate

MemoryUpdater.update(...)
→ MemoryUpdate
```

M0 建立接口。

M8 再实现完整逻辑。

---

# 12. 分支、路由与决策规则

M0 不实现完整业务决策，但必须支持以下运行结构。

## 12.1 普通 Agent 路径

```text
Input
→ Safety
→ Context
→ Understanding
→ Policy
→ Planner
→ Skill / Tool
→ Validation
→ Response
→ Update
```

---

## 12.2 强制 Workflow 路径

M0 必须允许未来：

```text
Safety / Policy
→ forced_workflow
```

绕过普通 Planner 自由决策。

例如 M2 后续可以：

```text
高风险
→ HelpWorkflow
```

---

## 12.3 Tool Callback 路径

Tool 异步返回时应能够：

```text
Tool Callback
→ RuntimeEvent / RuntimeInput
→ Runtime
```

重新进入链路。

---

## 12.4 Scheduler 路径

提醒、主动问候等：

```text
Scheduler Event
→ RuntimeInput
→ Runtime
```

而不是绕开 Runtime 直接执行业务。

---

# 13. 与前后 M 的接口

## 13.1 M0 → M1

M0 提供：

```text
RuntimeInput

RuntimeContext 基础 Schema

ContextBuilder Interface
```

M1 负责把 RuntimeContext 做实。

---

## 13.2 M0 → M2

M0 提供：

```text
SafetyResult

PolicyDecision

StateUpdate

State Engine Interface
```

M2 负责：

```text
Safety
State
Priority
Preemption
Policy
```

---

## 13.3 M0 → M3

提供：

```text
UnderstandingEngine Interface

UnderstandingState Schema
```

---

## 13.4 M0 → M4

提供：

```text
Planner Interface

ActionPlan Schema
```

---

## 13.5 M0 → M5

提供：

```text
Executor

Skill / Workflow / Tool Interface

Registry
```

---

## 13.6 M0 → M6

提供：

```text
ExecutionResult

ValidatedResult

Validator Interface
```

---

## 13.7 M0 → M7

提供：

```text
ResponsePlan

RuntimeResponse
```

---

## 13.8 M0 → M8

提供：

```text
StateUpdate

MemoryUpdate
```

---

## 13.9 M0 → M9

提供：

```text
统一业务能力挂载机制
```

业务模块不得重新建立另一套 Runtime。

---

# 14. 与业务模块的映射

当前业务总体系包括：

```text
领域交互
内容播放
情绪安抚
安全与领域事件
领域提醒
领域任务交互
长期记忆
新闻天气
```



M0 不实现这些业务。

它只保证这些业务未来可以分别通过：

```text
Skill

Workflow

Tool

Service
```

接入。

例如：

```text
领域交互
→ CompanionSkill

内容播放
→ ContentSkill

情绪安抚
→ EmotionSkill

求助
→ HelpWorkflow

身体不适
→ DiscomfortWorkflow

提醒
→ ReminderWorkflow

天气
→ WeatherSkill + WeatherTool
```

---

# 15. 异常、超时与降级

## 15.1 统一错误体系

建议：

```text
INPUT_ERROR

CONTEXT_ERROR

UNDERSTANDING_ERROR

POLICY_ERROR

PLANNING_ERROR

EXECUTION_ERROR

TOOL_ERROR

VALIDATION_ERROR

RESPONSE_ERROR

STATE_ERROR

MEMORY_ERROR

TIMEOUT_ERROR
```

统一错误对象：

```text
RuntimeError

error_code

stage

severity

recoverable

message

cause

fallback
```

---

## 15.2 Understanding 失败

未来可以：

```text
LLM Understanding失败
→ Rule Based Understanding
```

---

## 15.3 Response 失败

```text
Response Generation失败
→ 固定兜底话术
```

---

## 15.4 网络 Tool 失败

例如：

```text
网络内容失败
→ 本地资源
```

---

## 15.5 Tool 执行失败

必须：

```text
返回真实失败
```

不能：

```text
Tool失败
→ Response说成功
```

---

## 15.6 安全场景

安全事件不能通过：

```text
“降级成普通闲聊”
```

绕过。

---

# 16. 配置项与可变项

M0 建立配置框架。

示例：

```yaml
runtime:
  timeout: 30

components:
  understanding: stub
  planner: stub

skills:
  echo:
    enabled: true

tracing:
  enabled: true
```

以后允许：

```text
understanding:
stub
→ llm_v1
→ hybrid_v2
```

而不修改 Runtime Engine。

---

## 16.1 应配置化的内容

包括：

```text
组件实现选择

Skill 开关

Workflow 开关

Tool 开关

Trace 开关

Runtime Timeout

模型版本入口

Schema 版本
```

---

# 17. 非功能约束

## 17.1 异步能力

Runtime 应以异步调用为基础。

因为未来：

```text
LLM

天气 API

新闻 API

通知 Tool

播放网络资源

TTS
```

都可能需要等待。

因此：

```text
Runtime Core
建议 async
```

---

## 17.2 一致性

以下关键数据更新必须保证一致：

```text
状态更新

安全事件

通知状态

关键任务状态
```

---

## 17.3 性能

M0 本身不得引入大量无必要网络调用。

后续各节点的性能预算应符合需求中已有的用户端响应时限，例如普通闲聊从用户说完到开始 TTS 播报要求 ≤5 秒。

---

## 17.4 隐私

日志与 Trace 必须支持：

```text
最小必要记录

敏感字段过滤

不默认保存完整录音
```

当前需求明确普通闲聊不默认保存完整录音、用户数据不得串用。

---

## 17.5 会话隔离

必须按：

```text
subject_id
session_id
device_id
```

隔离 Runtime 状态。

---

# 18. Trace / Logging / Observability

## 18.1 Runtime Trace

一次请求至少可以追踪：

```text
Input

Safety

Context

Understanding

Policy

ActionPlan

Execution

Validation

Response

StateUpdate
```

---

## 18.2 三类基础日志

### Runtime Log

记录：

```text
各 Runtime 阶段是否成功

耗时

状态变化
```

### Decision Trace

记录：

```text
UnderstandingState

PolicyDecision

ActionPlan
```

### Tool Trace

记录：

```text
调用哪个 Tool

输入摘要

返回状态

耗时

错误
```

---

## 18.3 Trace 标识

必须具备：

```text
request_id

session_id

trace_id
```

Tool：

```text
execution_id

tool_call_id
```

这样后续可以回答：

> 为什么机器人刚才这么回答？

---

# 19. 版本、兼容与变更影响

## 19.1 Schema Version

核心数据对象应支持：

```text
schema_version
```

包括：

```text
UnderstandingState

ActionPlan

ExecutionResult

ValidatedResult
```

---

## 19.2 可无代码调整

以下变化原则上只应改配置：

```text
切换 Stub / LLM implementation

Skill enable / disable

Trace 开关

Runtime timeout
```

---

## 19.3 新增业务能力

例如未来增加：

```text
家庭留言

视频通话

小游戏
```

原则上：

```text
新增 Skill / Workflow / Tool
+
Registry 注册
```

而不是修改 Runtime 主链。

---

## 19.4 Breaking Change

以下属于可能破坏兼容的变化：

```text
删除核心数据字段

改变节点调用顺序语义

改变 ActionPlan 必填契约

改变 ExecutionResult 状态语义
```

必须进行版本升级与回归验证。

---

# 20. 测试 / Eval

## 20.1 主链测试

确保：

```text
10 个 Runtime 节点全部可以被调用
```

---

## 20.2 节点异常测试

模拟：

```text
Understanding失败

Planner失败

Tool失败

Validator失败

Response失败
```

系统不能整体崩溃。

---

## 20.3 Registry 测试

验证：

```text
注册 Skill

调用 Skill

禁用 Skill

不存在 Skill

Workflow 注册

Tool 注册
```

---

## 20.4 Trace 测试

一次请求必须可以恢复：

```text
输入
→ 理解
→ 策略
→ 计划
→ 执行
→ 结果
→ 回复
```

---

## 20.5 状态隔离测试

不同：

```text
session_id
subject_id
device_id
```

不得串 Context 或状态。

---

## 20.6 真实状态保护测试

必须验证：

```text
Response 文本
不能直接修改业务状态
```

---

# 21. Gate

M0 完成必须满足以下 Gate。

## Gate M0-01

10 个 Runtime 节点接口全部存在。

---

## Gate M0-02

核心数据结构全部存在：

```text
RuntimeInput
RuntimeContext
SafetyResult
UnderstandingState
PolicyDecision
ActionPlanDraft
ApprovedActionPlan
ExecutionResult
ValidatedResult
ResponsePlan
RuntimeResponse
UpdateResult
```

---

## Gate M0-03

至少一个测试输入可完整经过：

```text
Input
→ Runtime
→ Output
```

---

## Gate M0-04

任意节点发生模拟异常：

```text
Runtime 不崩溃
```

并返回标准错误或 fallback。

---

## Gate M0-05

Skill / Workflow / Tool 存在统一基础接口和 Registry。

---

## Gate M0-06

每次运行具有：

```text
request_id
session_id
trace_id
```

---

## Gate M0-07

能够查看完整 Decision Trace。

---

## Gate M0-08

不同 Session 和用户 Context 不串用。

---

## Gate M0-09

业务真实状态不能由 Response 文本修改。

---

## Gate M0-10

Runtime Core 不得写死：

```text
8 大业务模块

Domain Package 中的业务分类项

具体内容名称

具体情绪类型
```

---

# 22. 交付物

M0 完成以后至少交付：

```text
M0-01 Runtime 总体结构说明

M0-02 Runtime 数据流说明

M0-03 Runtime 核心数据模型

M0-04 10 节点接口契约

M0-05 Skill / Workflow / Tool 基础接口规范

M0-06 Registry 设计

M0-07 Event 模型

M0-08 Error / Fallback 规范

M0-09 Trace / Logging 规范

M0-10 Runtime Skeleton 代码

M0-11 最小闭环测试

M0-12 M0 Gate 验证报告
```

---

# 附录 A：Registry 机制

## A.1 Skill Registry

```text
SkillRegistry

# Domain Example — 不得写入 Core
companion
content
emotion
cognitive
weather
news
```

支持：

```text
register
enable
disable
lookup
```

---

## A.2 Workflow Registry

例如（Domain Example，不是 Core Workflow 枚举）：

```text
# Domain Example
HelpWorkflow
DiscomfortWorkflow
HighRiskEmotionWorkflow
ReminderWorkflow
```

---

## A.3 Tool Registry

例如（Domain Example，不是 Core Tool 枚举）：

```text
# Domain Example
play_content
stop_content
send_notification
query_weather
query_news
retrieve_memory
save_memory
```

---

## A.4 Policy Registry

例如：

```text
priority_policy

interrupt_policy

quiet_time_policy

memory_policy

safety_policy
```

---

# 附录 B：Skill / Workflow / Tool 基础契约

## B.1 Skill

用于：

```text
具有一定策略性
可以内部调用多个 Tool
```

例如：

```text
ContentSkill
EmotionSkill
CompanionSkill
```

基础接口：

```python
class Skill:
    def can_handle(...)
    async def execute(...)
```

---

## B.2 Workflow

用于：

```text
确定性较高
步骤明确
不可随意跳跃
```

例如：

```text
HelpWorkflow
```

可能流程：

```text
确认
→ 创建事件
→ 通知
→ 等待结果
→ 回复
```

---

## B.3 Tool

只负责真实动作：

```text
播放

通知

查天气

查询数据库

写数据
```

Tool 不做业务决策。

---

# 附录 C：Runtime Event

系统不是单纯一问一答。

必须支持：

```text
用户语音

提醒到时

主动问候

Tool 回调

通知结果

网络恢复

任务超时
```

统一抽象：

```text
RuntimeEvent

event_id

event_type

source

timestamp

priority

payload
```

例如：

```text
event_type = USER_INPUT
```

或：

```text
event_type = REMINDER_DUE
```

所有 Event 最终进入统一 Runtime。

---

# 附录 D：推荐代码结构

```text
app/

├── runtime/
│   ├── engine.py
│   ├── models.py
│   ├── events.py
│   └── errors.py
│
├── input/
│   └── processor.py
│
├── context/
│   └── builder.py
│
├── safety/
│   └── guard.py
│
├── understanding/
│   └── engine.py
│
├── policy/
│   └── engine.py
│
├── planning/
│   └── planner.py
│
├── execution/
│   └── executor.py
│
├── validation/
│   └── validator.py
│
├── response/
│   └── engine.py
│
├── state/
│   └── updater.py
│
├── memory/
│   └── updater.py
│
├── skills/
│   ├── base.py
│   └── registry.py
│
├── workflows/
│   ├── base.py
│   └── registry.py
│
├── tools/
│   ├── base.py
│   └── registry.py
│
├── config/
│
├── infra/
│   ├── logging.py
│   └── tracing.py
│
└── tests/
```

该结构只是职责结构。

M0 不要求每个目录都已经完成真实业务实现。

---

# 附录 E：M0 最小 PoC

## E.1 PoC 1：EchoSkill

输入：

```text
你好
```

流程：

```text
RuntimeInput
↓
SafetyStub
↓
ContextStub
↓
UnderstandingStub

intent = TEST

↓
PolicyStub

allowed = true

↓
PlannerStub

Action = ECHO

↓
EchoSkill

↓
ExecutionResult

success

↓
Validator

valid

↓
Response

“你好。”

↓
StateUpdate
```

这一步验证的不是业务功能，而是：

```text
Runtime 主链能够完整执行。
```

---

## E.2 PoC 2：ContentSkill Stub

输入：

```text
给我放首歌
```

先不真正播放。

模拟：

```text
ExecutionResult

status = success

content = mock_song
```

验证：

```text
Understanding
→ Planning
→ Skill
→ Tool
→ Result
→ Response
```

链路。

真实 Content 模块在 M9 接入。

---

# 附录 F：M0 完成后的系统状态

M0 完成后系统已经能够：

```text
输入进入统一 Runtime

信息沿统一数据链流转

Understanding 有固定入口

Policy 有固定入口

Planner 有固定入口

Skill / Workflow / Tool 可以注册

Tool 可以返回真实结果

结果可以被验证

Response 可以生成

State / Memory 有标准更新接口

全过程可以 Trace
```

但此时不能宣称：

```text
已经实现完整智能陪护 Agent
```

---

# 附录 G：与下一阶段关系

M0 完成后进入：

```text
M1 Input & Context
```

M0 做的是：

```text
建立容器和管道
```

M1 做的是：

```text
开始向 RuntimeContext 中装入正确、有效、具有生命周期的信息
```

因此：

```text
M0
统一运行架构

↓

M1
建立上下文基础

↓

M2
建立安全与规则

↓

M3
建立真正的用户理解

↓

M4
开始智能决策
```

这构成后续完整 Agent Runtime 的基础。