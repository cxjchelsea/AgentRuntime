# 可复用 Agent Runtime 平台  
# M5 Execution Framework 详细实现方案 V2.0

> **Phase 0 Fix**  
> M5 只能消费 `ApprovedActionPlan`，不得接受 `ActionPlanDraft` 或歧义 `ActionPlan`。  
> `ExecutionResult` 使用 `plan_status` + `step_results[]` / `skill_results[]` / `tool_results[]`。M5 内部结果先使用 typed internal contracts，再投影到现有 Canonical `ExecutionResult`，本 Fix Pack 不修改主链 Contract。  
> `elder_id` 已从 ExecutionContext 删除，改 `identity_scope`。

> **平台化转换说明**  
> 本文已从单一业务 Agent 设计转换为 **可复用 Agent Runtime 平台**设计。除明确标记为 `Core` 的对象、接口、不变量和生命周期外，任何具体业务 Intent、Entity、Workflow、Skill、Tool、知识域、状态字段、规则、提示词或示例均视为 **Domain Package 示例**，不得硬编码进 Runtime Core。新项目应通过 Registry / Adapter / Plugin / Config 注入领域差异。
> 
> 平台固定边界：`Runtime Core` 尽量稳定；`Domain Extension` 插件化；`Business Package` 配置化；`Application` 负责产品装配。

> 本版本为 M5 V1.0 的结构化重整版。  
> 保留原方案中 Execution Orchestrator、Step Scheduler、Skill / Workflow / Tool、Timeout、Retry、Idempotency、Cancellation、Preemption、Concurrency、Execution State Store、Checkpoint、Crash Recovery、Execution Event、Error Taxonomy、Fallback、Permission、Ongoing Activity、Notification Execution、Metrics、Tracing、PoC、测试、Gate、交付物等全部内容，并统一纳入 M0～M9 的 22 项实现方案模板。
>
> 本版本重点补强：统一执行主流程、数据生命周期、跨 M 接口、执行权限边界、版本兼容与变更影响。

---


## 平台扩展补充：Execution Core 与 Domain Adapter

M5 Core 只提供 Skill / Workflow / Tool 执行协议、超时、重试、幂等、取消、并发和 Side Effect 管理。具体 Skill、Workflow、Tool Adapter 均由 Domain Package 注册。

## Readiness Contract Fix Pack

在进入 M5-IU1 前，以下内部执行合同已冻结为 M5 Core readiness baseline：

```text
Internal Result Contracts
Tool / Skill / Workflow Implementation Protocols
ExecutionControlSignalSource
ExecutionStateStore / WorkflowCheckpointStore
IdempotencyStore / ResourceLockProvider
Workflow / Tool optional execution metadata
```

这些对象用于 M5 内部执行可靠性，不改变冻结的主链：

```text
ApprovedActionPlan
→ ExecutionEngine
→ ExecutionResult
```

Registry 的 `implementation_ref` 在执行前必须满足对应 Protocol；解析失败、版本歧义或实现类型不匹配时必须 fail closed，不允许自行替换 Capability。

---

## Readiness Supplement

在 Readiness Re-Review 后补充冻结：

```text
ExecutionPermissionContext / Provider / Evaluator
PermissionDecision(ALLOWED / DENIED / UNKNOWN)

ApprovedWorkflowAuthority
project_workflow_authority(...)
```

前者补齐 Tool 执行前权限判定合同；后者明确 Workflow authority 来自已经批准的 `ApprovedActionPlan` 以及现有 `forced_workflow` 约束，不新增不存在的 `allowed_workflows / forbidden_workflows` Policy 字段。

---

# 01. 阶段定位

M5 是整个 Agent Runtime 的执行层。

前面几个阶段分别解决：

```text
M1
当前发生了什么？

M2
哪些事情允许做？

M3
用户是什么意思？

M4
下一步应该做什么？
```

M5 解决：

```text
已经决定要做什么以后，

如何把这个计划可靠地执行成真实系统动作？
```

因此：

```text
M4
Approved ActionPlan

↓

M5
Execution Framework

↓

ExecutionResult

↓

M6
Result Validation
```

M5 的目标不是继续：

```text
思考
规划
解释用户
```

而是：

```text
准确执行

可靠执行

可追踪执行

可失败执行

可取消执行

可抢占执行

可恢复执行

可防重复副作用执行
```

可以概括为：

> M4 决定“应该做什么”，M5 负责“按照批准后的计划真正做出来”。

---

# 02. 阶段目标与八种智能映射

## 2.1 M5 总体目标

M5 最终需要建立：

```text
Execution Orchestrator

+

Step Scheduler

+

Capability Resolution

+

Skill Execution

+

Workflow Execution

+

Tool Execution

+

Timeout

+

Retry

+

Idempotency

+

Cancellation

+

Preemption

+

Concurrency Control

+

Checkpoint

+

Recovery

+

Result Collection

+

Execution Trace
```

并最终输出：

```text
ExecutionResult
```

---

## 2.2 与八种智能的关系

M5 本身不是主要智能理解层。

它主要承载：

```text
对话策略智能的执行保障

主动性智能的行为落地

自我约束智能的执行边界
```

映射如下：

| 智能能力 | M5职责 |
|---|---|
| 语义理解智能 | 不负责 |
| 上下文智能 | 使用必要 ExecutionContext |
| 关系连续性智能 | 可执行 Memory 相关能力，但不决定是否使用 |
| 情绪理解智能 | 不负责 |
| 目标与隐含需求推断智能 | 不负责 |
| 对话策略智能 | 将 M4 ActionPlan 执行出来 |
| 主动性智能 | 执行已经批准的主动行为 |
| 自我约束智能 | 不执行未授权 Action / Tool / Workflow |

因此：

```text
M5
不是“智能决策层”

而是：

“智能决策的可靠执行层”
```

---

# 03. 职责边界

## 3.1 M5 负责

M5 负责：

```text
加载 Approved ActionPlan

创建 ExecutionContext

调度 ActionStep

解析 Capability

执行 Skill

启动 / 推进 Workflow

执行 Tool

校验 Tool 输入输出结构

处理 Timeout

执行允许的 Retry

处理 Idempotency

处理 Cancellation

落实 Preemption

处理资源锁

收集 Tool / Skill / Workflow 结果

生成 Execution Events

保存关键执行状态

保存 Workflow Checkpoint

执行恢复

输出 ExecutionResult
```

---

## 3.2 M5 不负责

M5 不负责：

```text
重新理解用户

重新选择 Intent

重新判断 Emotion

重新判断 Implicit Need

重新选择 Strategy

重新决定 Primary Goal

修改 Policy

自行替换 Capability

生成最终用户回复

判断执行结果能否对用户声称成功

直接写长期 Memory

直接修改 Runtime State
```

核心原则：

```text
M5
只能执行计划

不能重新规划计划
```

---

## 3.3 执行中条件变化的边界

执行过程中可能发生：

```text
用户突然求助

高优先级提醒到来

用户说停止

Tool异常

网络断开

系统关机
```

M5 不允许：

```text
自行修改 ActionPlan
```

正确机制：

```text
Runtime Event

↓

M2 Priority / Preemption

↓

取消 / 抢占当前 Execution

↓

进入新的 Runtime Cycle
```

---

# 04. 前置依赖与外部依赖

## 4.1 M0 依赖

M5 依赖 M0 提供：

```text
Execution Engine Interface

ExecutionResult 基础 Schema

Skill Registry

Workflow Registry

Tool Registry

Runtime Event

Error / Fallback

Trace
```

---

## 4.2 M1 依赖

M5 不直接使用完整 RuntimeContext，而是从中提取必要执行信息：

```text
session_id

identity_scope

device_id

current_state

tool_context

environment_context

active_task
```

并构造：

```text
ExecutionContext
```

---

## 4.3 M2 依赖

M5 必须继承：

```text
PolicyDecision / Policy Snapshot

Allowed / Forbidden Tools

Allowed / Forbidden Skills

forced_workflow（如存在）

Safety Lock

Preemption Decision

Required Confirmation
```

当前冻结的 PolicyDecision **不存在** generic `allowed_workflows / forbidden_workflows`。Workflow 执行权限不得由 M5 自行发明该字段，而应来自：

```text
ApprovedActionPlan 中已经批准的 workflow_id
+
policy_snapshot.forced_workflow（如存在）
+
WorkflowRegistry enabled/version
+
Runtime execution eligibility
+
Execution Permission
```

因此，Workflow authority 是已批准计划的执行投影，不是新的 M5 Policy。

---

## 4.4 M4 依赖

M5 唯一正式业务输入：

```text
Approved ActionPlan
```

注意必须已经通过：

```text
PlanValidator

+

M2 Policy Re-check
```

未经批准的 Plan 不得执行。

---

## 4.5 外部执行依赖

M5 可能连接：

```text
Playback Service

Notification Service

Weather API

News API

Scheduler

Storage

Memory Service

Device Service

Network Service
```

但所有外部能力必须通过：

```text
Tool
```

统一封装。

---

# 05. 输入

M5 唯一正式输入：

```text
Approved ActionPlan
```

重点读取：

```text
planning_mode

steps

capability_selection

tool_plan

confirmation

stop_condition

fallback_plan

policy_snapshot
```

M5 不需要重新读取 M3 的完整理解过程。

---

# 06. 输出

M5 唯一正式输出：

```text
ExecutionResult
```

它描述：

```text
执行了什么

哪些 Step 完成

调用了哪些 Skill / Workflow / Tool

每个 Tool 返回什么

是否超时

是否失败

是否取消

是否被抢占

发生了哪些错误
```

但：

```text
ExecutionResult
!=
Validated Business Truth
```

M6 才负责后续验证。

---

# 07. 核心数据结构

# 7.1 ExecutionContext

建议：

```text
ExecutionContext

execution_id

plan_id

request_id

session_id

identity_scope

device_id

current_state

policy_snapshot

step_state

tool_context

deadline

cancellation_token

trace_context
```

它是 M5 专用上下文。

不建议把整个 RuntimeContext 原样交给执行层。

---

# 7.2 Execution 标识链

完整追踪关系：

```text
request_id

↓

plan_id

↓

execution_id

↓

step_execution_id

↓

tool_call_id
```

每一级都必须可追踪。

---

# 7.3 ExecutionResult

正式建议：

```text
ExecutionResult

schema_version

metadata

plan_status

step_results[]

skill_results[]

workflow_result

tool_results[]

business_outputs

state_observations

errors[]

timing

cancellation

quality
```

---

# 7.4 metadata

```text
execution_id

plan_id

request_id

started_at

finished_at

executor_version
```

---

# 7.5 PlanStatus

建议冻结：

```text
SUCCESS

PARTIAL_SUCCESS

FAILED

CANCELLED

TIMEOUT

PREEMPTED
```

特别注意：

```text
SUCCESS
```

只表示：

```text
M5执行层完成
```

不代表：

```text
M6已经确认业务事实成功
```

---

# 7.6 StepExecutionResult

```text
StepExecutionResult

step_id

action

status

started_at

finished_at

skill_id

workflow_id

tool_calls[]

output

error

retry_count
```

---

# 7.7 StepStatus

```text
PENDING

RUNNING

SUCCESS

FAILED

SKIPPED

CANCELLED

TIMEOUT

PREEMPTED
```

---

# 7.8 ToolResult

所有 Tool 返回统一结构：

```text
ToolResult

tool_call_id

tool_id

status

data

error_code

error_message

started_at

finished_at

attempt

metadata
```

---

# 7.9 ToolStatus

Readiness Fix Pack 后冻结为：

```text
SUCCESS

FAILED

TIMEOUT

CANCELLED

UNAVAILABLE

REJECTED

UNKNOWN
```

其中 `UNKNOWN` 表示外部副作用可能已经发生，但当前无法确认结果；不得静默改写成 FAILED。

---

# 7.10 SkillResult

```text
SkillResult

skill_id

status

business_outputs[]

tool_results[]

events[]

error

metadata
```

---

# 7.11 WorkflowInstance

```text
WorkflowInstance

workflow_instance_id

workflow_id

status

current_step

created_at

updated_at

completed_steps

pending_step

important_outputs
```

---

# 7.12 WorkflowStatus

```text
CREATED

RUNNING

WAITING

COMPLETED

FAILED

CANCELLED

TIMEOUT
```

---

# 7.13 BusinessResult

用于表达：

```text
业务执行层观察到的结果
```

例如：

```text
ContentSkill:

content_id

playback_session_id

playback_started
```

但其中事实仍要进入 M6 验证。

---

# 7.14 ExecutionRecord

关键执行持久化结构：

```text
ExecutionRecord

execution_id

plan_id

status

current_step

step_results

created_at

updated_at
```

---

# 7.15 ExecutionEvent

建议：

```text
ExecutionEvent

event_id

execution_id

event_type

step_id

tool_call_id

timestamp

payload
```

event_type：

```text
EXECUTION_STARTED

STEP_STARTED

STEP_COMPLETED

STEP_FAILED

TOOL_STARTED

TOOL_COMPLETED

TOOL_FAILED

EXECUTION_CANCELLED

EXECUTION_PREEMPTED

EXECUTION_COMPLETED
```

---

# 7.16 ActivityInstance

对于持续活动：

```text
ActivityInstance

activity_id

activity_type

status

started_at

resource_id

owner_session
```

---

# 7.17 ActivityStatus

```text
ACTIVE

PAUSED

COMPLETED

CANCELLED

FAILED
```

---

# 7.18 ExecutionError

```text
ExecutionError

error_code

stage

step_id

tool_id

recoverable

retryable

message

cause

timestamp
```

---

# 7.19 ToolDefinition

建议：

```text
ToolDefinition

tool_id

description

input_schema

output_schema

timeout_policy

retry_policy

idempotency_mode

side_effect_level

required_permissions[]

resource_locks[]

enabled

version
```

---

# 7.20 SkillDefinition

```text
SkillDefinition

skill_id

version

supported_actions[]

required_tools[]

allowed_states[]

timeout

enabled
```

---

# 7.21 WorkflowDefinition

```text
WorkflowDefinition

workflow_id

version

supported_events[]

checkpoint_enabled

allowed_states[]

timeout_policy

resume_policy

enabled
```

---

# 08. 数据来源、存储与生命周期

# 8.1 Execution 生命周期

每个 Plan 执行时创建：

```text
execution_id
```

生命周期：

```text
CREATED

↓

RUNNING

↓

SUCCESS / PARTIAL_SUCCESS / FAILED

或

CANCELLED / TIMEOUT / PREEMPTED
```

---

# 8.2 Step 生命周期

```text
PENDING

↓

RUNNING

↓

SUCCESS / FAILED / SKIPPED /
CANCELLED / TIMEOUT / PREEMPTED
```

---

# 8.3 Tool Call 生命周期

每个真实 Tool Call 必须独立记录：

```text
tool_call_id

attempt

start

finish

status
```

重试不能覆盖第一次调用记录。

---

# 8.4 Workflow 生命周期

Workflow 可能跨多个 Runtime Cycle。

例如：

```text
HelpWorkflow
```

可能：

```text
当前 Cycle
→ 创建事件
→ 发通知

下一 Cycle
→ Tool Callback

下一 Cycle
→ 更新结果
```

因此 Workflow 状态不能只保存在单个函数调用中。

---

# 8.5 Checkpoint 生命周期

关键 Workflow 每推进一步：

```text
更新 Checkpoint
```

至少保存：

```text
workflow_instance_id

current_step

completed_steps

pending_step

important_outputs
```

---

# 8.6 哪些执行必须持久化

优先：

```text
Safety Workflow

Reminder

Notification

跨轮任务

长时间 Tool 调用
```

普通：

```text
ACKNOWLEDGE
```

不一定需要强持久化。

---

# 8.7 Ongoing Activity 生命周期

Execution 和 Activity 必须区分。

例如：

```text
Execution:
启动播放

Activity:
播放持续中
```

Execution 完成后：

```text
Playback Activity
```

仍可继续存在。

---

# 8.8 Trace 生命周期

一次 Execution 应至少保存：

```text
Plan
→ Step
→ Skill / Workflow
→ Tool
→ Result
```

调试信息保留策略遵循隐私和日志配置。

---

# 09. 内部组件

建议 M5 包含：

```text
ExecutionOrchestrator

PlanLoader

RuntimeExecutionChecker

StepScheduler

CapabilityResolver

SkillExecutor

WorkflowExecutor

ToolExecutor

ToolInputValidator

ToolOutputValidator

ResultCollector

ExecutionAggregator

RetryManager

TimeoutManager

IdempotencyManager

CancellationManager

PreemptionHandler

ConcurrencyManager

ResourceLockManager

ExecutionStateStore

WorkflowCheckpointManager

RecoveryManager

ExecutionEventPublisher

ExecutionTracer

MetricsCollector
```

---

# 10. 运行时实现主流程

M5 正式运行时主流程：

```text
Approved ActionPlan
        ↓
① Plan Load & Validate Approval
        ↓
② Create ExecutionContext
        ↓
③ Runtime Execution Check
        ↓
④ Step Scheduling
        ↓
⑤ Capability Resolution
        ↓
⑥ Execute Skill / Workflow / Tool
        ↓
⑦ Collect Step / Tool Result
        ↓
⑧ Timeout / Retry / Idempotency
        ↓
⑨ Cancellation / Preemption Check
        ↓
⑩ Persist Execution / Checkpoint
        ↓
⑪ Aggregate ExecutionResult
        ↓
M6 Result Validation
```

---

## 10.1 核心伪代码

```python
async def execute(
    approved_plan,
    runtime_context
):

    execution = create_execution(
        approved_plan,
        runtime_context
    )

    await execution_store.save(execution)

    publish(EXECUTION_STARTED)

    for step in step_scheduler.resolve(
        approved_plan.steps
    ):

        cancellation_manager.raise_if_cancelled(
            execution
        )

        preemption_handler.raise_if_preempted(
            execution
        )

        runtime_execution_checker.validate(
            step,
            execution
        )

        step_result = await execute_step(
            step,
            execution
        )

        await execution_store.save_step_result(
            step_result
        )

        if should_retry(step_result):
            step_result = await retry_manager.retry(
                step,
                execution
            )

        if should_stop_plan(
            step_result,
            approved_plan
        ):
            break

    result = execution_aggregator.aggregate(
        execution
    )

    publish(EXECUTION_COMPLETED)

    return result
```

---

# 11. 各步骤详细实现

# Step 1：Plan Load & Approval Check

M5 只接受：

```text
Approved ActionPlan
```

必须确认：

```text
plan_id存在

policy_snapshot存在

approval状态有效

schema_version兼容
```

未经批准：

```text
INVALID_PLAN
```

立即终止。

---

# Step 2：Create ExecutionContext

生成：

```text
execution_id
```

并绑定：

```text
request_id

plan_id

session_id

identity_scope

device_id

policy_snapshot

deadline

cancellation_token
```

---

# Step 3：Runtime Execution Check

执行每个 Step 前检查：

```text
当前 State 是否仍允许

Policy Snapshot 是否仍有效

Safety 是否仍允许该 Step

Session 是否仍有效

Cancellation / Preemption 是否已触发
```

M5-IU2 只负责 Runtime 层的实时执行资格检查。Capability 是否注册、enabled、版本兼容、Skill / Workflow 当前状态适配以及 Tool Permission，统一留给后续 Capability Resolution / Permission Enforcement，避免 Runtime Check 与 Capability Resolver 重复维护同一套能力真值。

注意：

如果发现环境变化：

```text
不要自行修改 Plan
```

而是：

```text
终止 / PREEMPT
→ 返回 Runtime
```

---

# Step 4：Step Scheduler

负责：

```text
Step 顺序

Step 依赖

Optional / Required

简单条件

是否可并行
```

第一版支持：

```text
顺序执行

+

简单条件执行
```

不做复杂 DAG。

---

## 11.4.1 Sequential Execution

例如：

```text
ACKNOWLEDGE

↓

PLAY_CONTENT
```

保证 Step 1 完成后再 Step 2。

---

## 11.4.2 Optional Step

如果：

```text
optional = true
```

失败后：

```text
不一定终止整个 Plan
```

---

## 11.4.3 Required Step

若：

```text
optional = false
```

且失败，则根据：

```text
on_failure
```

执行：

```text
STOP_PLAN

RUN_FALLBACK

CONTINUE_IF_SAFE
```

---

## 11.4.4 Step Dependency

例如：

```text
PLAY_CONTENT
depends_on:
CONTENT_SEARCH
```

如果搜索失败：

```text
PLAY_CONTENT
→ SKIPPED
```

---

## 11.4.5 简单条件执行

M5 Core 不硬编码领域条件名，也不复用 `completion_condition` 作为执行前置条件。

第一版通过注入的：

```text
StepEligibilityEvaluator
```

对“当前已批准 Step 是否可运行 / 等待 / 跳过”进行简单条件投影：

```text
ALLOW
WAIT
SKIP
```

Evaluator 只能约束当前 approved Step，不能改序、不能生成新 Step、不能替换 Capability。

复杂业务条件仍放在：

```text
Skill / Workflow
```

内部。

---

# Step 5：Capability Resolution

根据 ActionStep 找：

```text
Skill

Workflow

Tool
```

通过：

```text
SkillRegistry

WorkflowRegistry

ToolRegistry
```

---

## 11.5.1 Capability Resolution 校验

需要确认：

```text
存在

enabled

版本兼容

当前 State 可用

权限允许
```

---

## 11.5.2 Capability 不存在

例如：

```text
skill_id = VideoCallSkill
```

但 Registry 无此 Skill。

返回：

```text
CAPABILITY_NOT_FOUND
```

M5 不允许：

```text
自行换另一个 Skill
```

因为换 Skill 属于重新规划。

---

# Step 6：Skill / Workflow / Tool Execution

根据 ActionStep 类型进入对应 Executor。

---

## 11.6.1 Skill

Skill 是：

```text
业务能力执行单元
```

典型：

```text
ContentSkill

WeatherSkill

NewsSkill

CognitiveSkill

CompanionSkill
```

接口建议：

```python
class Skill:

    async def execute(
        self,
        action,
        parameters,
        execution_context
    ) -> SkillResult:
        ...
```

---

## 11.6.2 Skill 可以做什么

Skill 可以：

```text
调用注册 Tool

做参数转换

做资源查询

做资源选择

做有限业务执行
```

---

## 11.6.3 Skill 不允许做什么

禁止：

```text
重新理解 Emotion

重新选择 Strategy

更改 Primary Goal

绕过 Policy

调用未注册 Tool

伪造 Tool 成功

生成最终业务事实
```

---

## 11.6.4 ContentSkill 示例

```text
PLAY_CONTENT

↓

根据 category / preference
搜索资源

↓

选择具体资源

↓

PlayTool
```

---

## 11.6.5 WeatherSkill 示例

```text
QUERY_INFORMATION

domain = WEATHER

↓

参数解析

↓

WeatherTool

↓

原始结果
```

M5 不生成天气自然语言回答。

---

## 11.6.6 CompanionSkill 特殊性

对于：

```text
ACKNOWLEDGE

LISTEN

REFLECT
```

可能不需要外部 Tool。

此时 Skill 可以返回：

```text
response requirement
```

例如：

```text
communicative_action =
ACKNOWLEDGE
```

真正文案仍由 M7 生成。

---

## 11.6.7 Workflow

Workflow 用于：

```text
步骤固定

强约束

跨轮

需要状态跟踪
```

例如：

```text
HelpWorkflow

DiscomfortWorkflow

ReminderWorkflow

HighRiskEmotionWorkflow
```

基础接口：

```python
class Workflow:

    async def start(...)
    async def handle_event(...)
    async def cancel(...)
    async def resume(...)
    async def status(...)
```

---

## 11.6.8 Workflow 不要求一次调用完成

例如：

```text
创建求助事件

↓

发送通知

↓

WAITING

↓

等待 Tool Callback

↓

继续 Workflow
```

因此 Workflow 必须是有状态实例。

---

## 11.6.9 Tool

Tool 是：

```text
最小真实执行能力
```

例如：

```text
play_content

pause_content

stop_content

set_volume

query_weather

query_news

send_notification

create_event

read_reminder

update_reminder
```

Tool 的职责只有：

```text
接收参数

执行动作

返回真实结果
```

---

# Step 7：Tool Input / Output Validation

执行前：

```text
validate input_schema
```

例如缺：

```text
content_id
```

则：

```text
INVALID_PARAMETER
```

不调用 Tool。

---

## 11.7.1 Tool Output Validation

Tool 返回后：

```text
validate output_schema
```

结构异常：

```text
TOOL_INVALID_OUTPUT
```

不得直接当 SUCCESS。

---

# Step 8：Timeout / Retry / Idempotency

这是 M5 的可靠性核心。

---

## 11.8.1 Tool Timeout

每个 Tool 独立 timeout。

例如：

```text
WeatherTool

NotifyTool

PlayTool
```

可以不同。

---

## 11.8.2 三层 Timeout

M5 至少支持：

```text
Tool Timeout

Step Timeout

Execution / Plan Timeout
```

Workflow 另外还有：

```text
Workflow Timeout
```

---

## 11.8.3 Timeout 语义

必须区分：

```text
TIMEOUT
!=
FAILED
!=
SUCCESS
```

特别是通知：

```text
TIMEOUT
```

只能说明：

> 当前无法确认结果。

---

## 11.8.4 Retry

不是所有错误都能重试。

Retry 依赖：

```text
idempotent

side_effect_level

error_type
```

---

## 11.8.5 RetryPolicy

```text
RetryPolicy

enabled

max_attempts

retry_on[]

backoff

jitter
```

---

## 11.8.6 可重试错误

例如：

```text
temporary_network_error

service_unavailable

transient_timeout
```

---

## 11.8.7 不应自动重试

例如：

```text
INVALID_ARGUMENT

PERMISSION_DENIED

BUSINESS_REJECTED
```

以及：

```text
可能重复产生高副作用的操作
```

---

## 11.8.8 Idempotency

关键 Side Effect 必须支持：

```text
idempotency_key
```

例如：

```text
send_notification
```

若网络抖动后重试，不能重复通知。

---

## 11.8.9 Idempotency Key

建议：

```text
request_id
+
plan_id
+
step_id
+
business_action
```

---

## 11.8.10 Tool 幂等分类

### Naturally Idempotent

例如：

```text
query_weather
```

### Key-based Idempotent

例如：

```text
create_help_event
```

### Non-idempotent

必须谨慎执行和重试。

---

# Step 9：Cancellation / Preemption

每个 ExecutionContext 必须有：

```text
cancellation_token
```

---

## 11.9.1 Cancellation 来源

```text
USER_STOP

SESSION_END

SYSTEM_SHUTDOWN

TIMEOUT

SAFETY_OVERRIDE
```

---

## 11.9.2 Preemption 来源

由 M2 决定：

```text
HIGH_PRIORITY_PREEMPTION
```

例如：

```text
播放
↓
求助
```

---

## 11.9.3 Cancellation 行为

执行：

```text
停止未开始 Step

尝试取消可取消 Tool

Cleanup

保存已完成 Step

返回 CANCELLED
```

---

## 11.9.4 Preemption 行为

执行：

```text
停止 / 取消当前 Execution

记录 PREEMPTED

释放资源

回 Runtime

启动高优先级新 Runtime Cycle
```

---

## 11.9.5 已完成副作用不能撤回

例如：

```text
通知已经发出
```

之后用户取消。

不能修改成：

```text
未发送
```

只能停止后续步骤。

---

# Step 10：Concurrency / Resource Lock

系统可能同时存在：

```text
Playback

Reminder

Tool Callback

User Input
```

必须控制并发。

---

## 11.10.1 Session Execution Lock

建议至少：

```text
session_execution_lock
```

避免同一用户同时执行两个互相冲突的 Plan。

---

## 11.10.2 Resource Lock

例如：

```text
playback_lock

notification_lock

microphone_lock

speaker_lock
```

---

## 11.10.3 Playback 竞争

不能：

```text
PlayTool A

+

PlayTool B
```

同时控制播放器。

---

## 11.10.4 可并行查询

只读 Tool 可根据：

```text
tool_plan.execution_mode
```

决定是否并发。

---

# Step 11：Persistence / Checkpoint / Recovery

关键 Execution 不能只存在内存。

---

## 11.11.1 Execution State Store

保存：

```text
execution_id

plan_id

status

current_step

step_results

timestamps
```

---

## 11.11.2 Workflow Checkpoint

关键 Workflow 每步保存：

```text
workflow_instance_id

current_step

completed_steps

pending_step

important_outputs
```

---

## 11.11.3 Crash Recovery

程序重启后：

```text
加载 RUNNING / WAITING Execution

↓

判断是否安全恢复

↓

resume

或

FAILED / UNKNOWN
```

---

## 11.11.4 不允许盲目重放

例如重启前：

```text
send_notification
```

已经实际发出，但本地没拿到返回。

恢复后不能：

```text
直接再发一次
```

应检查：

```text
idempotency key

external status

workflow state
```

若仍无法确认：

```text
UNKNOWN
```

交给后续验证。

---

# Step 12：Execution Aggregation

所有 Step 完成、失败或中断后：

```text
ExecutionAggregator
```

根据：

```text
required step

optional step

tool result

workflow result

cancellation

preemption
```

生成：

```text
ExecutionResult
```

---

# 12. 分支、路由与决策规则

# 12.1 Skill / Workflow / Tool 区别

```text
Tool
=
最小真实动作

Skill
=
业务能力执行单元

Workflow
=
确定性、多步骤、可跨轮流程
```

---

# 12.2 Skill 与 Workflow 边界

Skill 更适合：

```text
Content

Weather

News

Companion

Cognitive
```

Workflow 更适合：

```text
Help

Discomfort

Reminder

HighRiskEmotion
```

---

# 12.3 Fast Execution Path

简单动作可以：

```text
ActionPlan
→ Tool
→ ExecutionResult
```

例如：

```text
PAUSE

STOP

VOLUME
```

但仍必须执行：

```text
Plan approved

Permission check

Tool registered

Trace

Timeout
```

不能绕过基础框架。

---

# 12.4 Long-running Execution

某些动作不是“一次函数调用就结束”。

例如：

```text
播放

领域任务交互

安静陪伴
```

应区分：

```text
Execution Start

和

Ongoing Activity
```

---

## 12.4.1 播放示例

M5：

```text
启动播放成功
```

Execution 可结束。

但：

```text
Playback Activity = ACTIVE
```

继续存在。

---

# 12.5 Tool Permission

```text
Tool存在
!=
当前有权限调用
```

同时：

```text
Planning Authorization
!=
Execution Permission
```

M2/M4 决定 Tool 是否可以进入 ApprovedActionPlan；M5 在真正调用前还必须检查当前执行主体、绑定、设备、环境、角色、Workflow State 等执行权限事实。

权限来源：

```text
PolicyDecision / Approved Plan

User Binding

Device Capability

Environment

Role

Workflow State
```

Readiness Supplement 冻结以下内部合同：

```text
ExecutionPermissionContext
ExecutionPermissionContextProvider
PermissionDecision
PermissionDecisionStatus
ExecutionPermissionEvaluator
```

PermissionDecisionStatus：

```text
ALLOWED
DENIED
UNKNOWN
```

其中 `UNKNOWN` 不得当作 ALLOWED，也不得触发 Capability substitution 或 Replan。具体执行行为由后续 M5-IU fail-closed 规则实现。

---

## 12.5.1 未绑定用户示例

当前需求已经规定：

```text
UNBOUND
```

不能写入未定义个人档案。

所以：

```text
memory_write_tool
```

应：

```text
REJECTED
```

而不是正常执行。

---

# 12.6 Tool Side Effect Level

建议：

```text
NONE

LOW

MEDIUM

HIGH
```

例如：

```text
query_weather
= NONE

play_content
= LOW

update_reminder
= MEDIUM

send_notification
= HIGH
```

Side Effect 决定：

```text
Retry

Confirmation

Idempotency

Recovery
```

策略。

---

# 12.7 Notification Execution

通知属于高风险 Side Effect。

推荐：

```text
create event_id

↓

create idempotency_key

↓

NotifyTool

↓

save ToolResult

↓

wait real result / callback

↓

M6 Validation
```

---

## 12.7.1 通知状态语义

应尽可能区分：

```text
REQUEST_ACCEPTED

SENT

DELIVERED

FAILED

TIMEOUT

UNKNOWN
```

实际接口能证明到哪一层，就只能对外使用哪一层。

不能：

```text
请求被服务端接受
```

就声称：

```text
工作人员已经收到
```

---

# 12.8 Tool Truth

必须保持：

```text
ToolResult
=
Tool真实返回
```

M5 不得：

```text
把 TIMEOUT 改成 SUCCESS

把 FAILED 改成 SUCCESS

根据常识猜执行结果
```

---

# 12.9 Fallback

M5 只能执行：

```text
ActionPlan.fallback_plan
```

不能：

```text
临时想一个新 Strategy
```

如果没有 Fallback：

```text
返回失败
```

---

## 12.9.1 Fallback 仍受 Policy 约束

即使是 fallback：

```text
也必须合法
```

必要时重新 Policy Check。

---

# 12.10 State Observation

M5 可以输出：

```text
playback_started = true
```

这属于：

```text
state_observation
```

但不能直接：

```text
current_state = S06
```

真正 State 更新属于 M8 + State Engine。

---

# 13. 与前后 M 的接口

# 13.1 M0 → M5

提供：

```text
Execution Engine Interface

ExecutionResult Schema

Registry

Trace

Error Framework
```

---

# 13.2 M1 → M5

提供执行必要 Context：

```text
session

identity

device

current state

tool context

environment context
```

M5 再构建 ExecutionContext。

---

# 13.3 M2 → M5

提供：

```text
Policy Snapshot

Allowed Capability

Permission

Preemption Decision

Safety Lock
```

---

# 13.4 M4 → M5

正式输入：

```text
Approved ActionPlan
```

---

# 13.5 M5 → M6

正式输出：

```text
ExecutionResult
```

M6 负责判断：

```text
这些结果说明真实世界发生了什么？
```

---

# 13.6 M5 → M7

M5 不直接把结果给 M7 当事实。

正确链路：

```text
M5
ExecutionResult

↓

M6
ValidatedResult

↓

M7
Response
```

---

# 13.7 M5 → M8

M5 可以输出：

```text
Execution Events

state_observations

business_result

tool_result
```

M8 决定：

```text
State Update

Task Update

Memory Update
```

---

# 14. 与业务模块的映射

# 14.1 领域交互

主要执行：

```text
CompanionSkill

ConversationalActionSkill
```

通常无外部 Tool 或只有轻量能力调用。

---

# 14.2 内容播放

主要：

```text
ContentSkill

SearchContentTool

PlayTool

PauseTool

StopTool

VolumeTool
```

并需要：

```text
playback_lock

ActivityInstance
```

---

# 14.3 情绪安抚

普通情绪：

```text
EmotionSkill

CompanionSkill

可选 ContentSkill
```

M5 只执行 M4 已批准动作。

---

# 14.4 安全与领域事件

主要：

```text
HelpWorkflow

DiscomfortWorkflow

HighRiskEmotionWorkflow

CreateEventTool

NotifyTool
```

这是 M5 对可靠性要求最高的一类业务。

---

# 14.5 领域提醒

主要：

```text
ReminderWorkflow

ReadReminderTool

UpdateReminderTool

Scheduler Tool

NotifyTool
```

---

# 14.6 领域任务交互

主要：

```text
CognitiveSkill

题库访问 Tool

ActivityInstance
```

---

# 14.7 长期记忆

M5 可以执行：

```text
MemoryReadTool

MemoryWriteTool
```

但：

```text
是否使用 Memory
```

由 M4 决定，

```text
是否长期写入
```

由 M8 决定。

---

# 14.8 新闻天气

主要：

```text
WeatherSkill

NewsSkill

WeatherTool

NewsTool
```

---

# 15. 异常、超时与降级

# 15.1 Capability 不存在

返回：

```text
CAPABILITY_NOT_FOUND
```

不得自动换 Capability。

---

# 15.2 Capability Disabled

返回：

```text
CAPABILITY_DISABLED
```

---

# 15.3 Tool Unavailable

返回：

```text
TOOL_UNAVAILABLE
```

若 Plan 有 fallback：

```text
执行 fallback
```

否则返回失败。

---

# 15.4 Tool Timeout

返回：

```text
TIMEOUT
```

不能伪造成功。

---

# 15.5 Permission Denied

返回：

```text
PERMISSION_DENIED
```

不重试。

---

# 15.6 Resource Busy

例如播放器锁占用：

```text
RESOURCE_BUSY
```

按照 Tool / Plan 规则：

```text
等待

失败

或 fallback
```

不得无限阻塞。

---

# 15.7 Workflow Error

返回：

```text
WORKFLOW_ERROR
```

必要时保留 Checkpoint 以便恢复。

---

# 15.8 Checkpoint Error

```text
CHECKPOINT_ERROR
```

对安全 Workflow 不能静默忽略。

---

# 15.9 Unknown Execution Error

兜底：

```text
UNKNOWN_EXECUTION_ERROR
```

必须记录 Trace。

---

# 15.10 recoverable 与 retryable

两者必须分开。

例如：

```text
Temporary Network Error

recoverable = true
retryable = true
```

而：

```text
Permission Denied

recoverable = false
retryable = false
```

---

# 16. 配置项与可变项

建议：

```yaml
execution:
  default_timeout:
  max_plan_steps:

retry:
  default_max_attempts:
  backoff:
  jitter:

workflow:
  checkpoint_enabled:

concurrency:
  session_lock:

tracing:
  enabled:

recovery:
  enabled:
```

---

## 16.1 Tool 级配置

例如：

```yaml
tools:

  notification:
    timeout:
    retry:
    idempotency:
    side_effect_level: HIGH

  weather:
    timeout:
    retry:
    side_effect_level: NONE

  playback:
    timeout:
    resource_lock: playback
    side_effect_level: LOW
```

---

## 16.2 Workflow 级配置

包括：

```text
workflow_timeout

checkpoint_enabled

resume_policy

allowed_retry
```

---

# 17. 非功能约束

# 17.1 可靠性优先

M5 的首要目标：

```text
真实执行
>
聪明执行
```

Executor 不应发挥。

---

# 17.2 异步执行

M5 应以：

```text
async execution
```

为主。

因为：

```text
Tool

网络请求

播放

通知

Workflow等待
```

都可能异步。

---

# 17.3 幂等性

关键 Side Effect 必须从第一版就支持基础幂等。

特别：

```text
通知

创建事件

提醒状态修改
```

---

# 17.4 可取消性

任何普通执行必须尽可能：

```text
可取消
```

满足用户随时停止。

---

# 17.5 可抢占性

高优先级事件必须可以：

```text
PREEMPT
```

低优先级执行。

---

# 17.6 一致性

以下必须保证：

```text
Execution Status

Step Status

Workflow State

Checkpoint

Side Effect Record
```

尽量一致。

---

# 17.7 资源控制

不能出现：

```text
多个播放实例抢播放器

多个通知请求重复发送

多个 Session 串执行
```

---

# 17.8 Recovery

安全与关键 Workflow：

```text
必须考虑进程重启恢复
```

普通低价值 Action 可以不做复杂恢复。

---

# 17.9 第一版复杂度控制

第一版不要做：

```text
分布式 Workflow Cluster

复杂 Saga

大规模 Worker

复杂 DAG

跨节点 Execution Migration
```

但必须从第一版保留：

```text
Timeout

Cancellation

Idempotency

Trace

Checkpoint Interface

Plan / Step / Tool IDs
```

---

# 18. Trace / Logging / Observability

M5 至少记录：

```text
request_id

plan_id

execution_id

step_id

skill_id

workflow_id

tool_call_id

status

start_time

end_time

retry_count

timeout

error

cancellation

preemption

checkpoint
```

---

## 18.1 Trace 示例

```text
Request R001

Plan P001

Execution E001

Step 1
ACKNOWLEDGE
SUCCESS

Step 2
PLAY_CONTENT

Skill:
ContentSkill

Tool:
SearchContentTool
SUCCESS

Tool:
PlayTool
SUCCESS

Execution:
SUCCESS
```

---

## 18.2 Metrics

至少建立：

```text
Execution Success Rate

Step Success Rate

Tool Success Rate

Tool Timeout Rate

Retry Rate

Cancellation Rate

Preemption Rate

Execution Latency

Tool Latency

Workflow Completion Rate

Duplicate Side Effect Rate
```

---

## 18.3 Duplicate Side Effect Rate

例如：

```text
一个 help_event
产生两次通知
```

属于高严重度问题。

目标：

```text
接近 0
```

---

## 18.4 Trace 与隐私

不得为了调试无限记录：

```text
完整语音

完整敏感健康信息

全部用户对话
```

仍遵循：

```text
最小必要原则
```

---

# 19. 版本、兼容与变更影响

# 19.1 ExecutionResult Schema Version

必须：

```text
ExecutionResult.schema_version
```

---

# 19.2 Executor Version

记录：

```text
executor_version
```

便于回溯执行行为。

---

# 19.3 Tool Version

每个 Tool：

```text
tool_id
version
```

---

# 19.4 Skill / Workflow Version

ActionPlan 可记录：

```text
required_capability_version
```

防止：

```text
Planner按照V2参数规划

Executor仍执行V1接口
```

---

# 19.5 可配置变化

一般无需改 M5 Core：

```text
Tool Timeout

Retry次数

某Tool是否启用

Workflow Timeout

Resource Lock配置

Checkpoint开关
```

---

# 19.6 新增 Tool

通常：

```text
新增 ToolDefinition

注册 Tool

实现 Tool Executor Adapter
```

无需改主执行链。

---

# 19.7 新增 Skill / Workflow

通过 Registry 注册即可。

---

# 19.8 Breaking Change

以下属于可能破坏兼容：

```text
修改 ToolResult 状态语义

修改 StepStatus

修改 ExecutionResult 必填字段

改变 Workflow Checkpoint 格式

改变 Idempotency 语义

改变 Tool Input / Output Schema
```

需版本升级和回归。

---

# 20. 测试 / Eval

# 20.1 基础执行

覆盖：

```text
单 Step 成功

多 Step 成功

Optional Step失败

Required Step失败
```

---

# 20.2 Registry

覆盖：

```text
Skill存在

Skill不存在

Tool禁用

Workflow版本不兼容
```

---

# 20.3 Timeout

覆盖：

```text
Tool Timeout

Step Timeout

Execution Timeout

Workflow Timeout
```

---

# 20.4 Retry

验证：

```text
可重试错误正确重试

不可重试错误不重试

重试次数正确

Backoff生效
```

---

# 20.5 Idempotency

重点：

```text
通知

创建事件

提醒修改
```

重复执行不得产生重复 Side Effect。

---

# 20.6 Cancellation

覆盖：

```text
执行前取消

Tool运行中取消

Step之间取消

Workflow等待中取消
```

---

# 20.7 Preemption

覆盖：

```text
播放被求助抢占

普通提醒被高风险抢占

领域任务交互被求助抢占
```

---

# 20.8 Recovery

覆盖：

```text
Executor崩溃

Workflow恢复

未完成 Tool Call

Checkpoint损坏
```

---

# 20.9 Concurrency

覆盖：

```text
同一 Session 两个 Plan

播放器资源竞争

通知重复调用

Resource Lock
```

---

# 20.10 Tool Truth

确保：

```text
Tool FAILED
```

不会变成：

```text
Execution Tool Result SUCCESS
```

---

# 20.11 Plan Execution Accuracy

检查：

> 是否严格按照 ActionPlan 执行。

例如：

```text
ACKNOWLEDGE
→ PLAY_CONTENT
```

不能实际执行：

```text
PLAY_CONTENT
→ ACKNOWLEDGE
```

---

# 20.12 Tool Invocation Accuracy

检查：

```text
调用是否正确

Tool是否正确

参数是否正确

顺序是否正确

不该调用时是否避免调用
```

---

# 20.13 Retry Correctness

```text
该重试的重试

不该重试的不重试
```

---

# 20.14 Cancellation Correctness

确保取消后：

```text
后续 Step 不执行

可取消 Tool停止

已完成 Side Effect 不伪造撤销
```

---

# 20.15 Recovery Accuracy

关键 Workflow 恢复后：

```text
不重复关键 Side Effect
```

---

# 20.16 核心指标

建议：

```text
Plan Execution Accuracy

Step Completion Accuracy

Tool Invocation Accuracy

Execution Success Rate

Timeout Handling Accuracy

Retry Correctness

Cancellation Correctness

Preemption Correctness

Idempotency Accuracy

Recovery Accuracy

Execution Schema Validity
```

---

# 21. Gate

## Gate M5-01

M5 只接受：

```text
Approved ActionPlan
```

---

## Gate M5-02

M5 统一输出：

```text
ExecutionResult
```

---

## Gate M5-03

所有 Step 具有独立状态。

---

## Gate M5-04

Skill / Workflow / Tool 职责明确分离。

---

## Gate M5-05

所有 Tool 输入和输出均经过 Schema Validation。

---

## Gate M5-06

Tool Timeout 正确返回：

```text
TIMEOUT
```

---

## Gate M5-07

M5 不伪造 Tool Success。

---

## Gate M5-08

Retry 只发生在允许重试的错误。

---

## Gate M5-09

关键 Side Effect 已存在基础 Idempotency。

---

## Gate M5-10

同一个 Help Event 不会因重试重复创建。

---

## Gate M5-11

Execution 支持 Cancellation。

---

## Gate M5-12

高优先级事件可以触发：

```text
PREEMPTED
```

---

## Gate M5-13

执行过程中高优先级事件到来时：

```text
M5 不自行 Replan
```

而是回 Runtime。

---

## Gate M5-14

Capability 不存在时不得擅自替换其他 Capability。

---

## Gate M5-15

M5 不生成最终用户话术。

---

## Gate M5-16

M5 不直接修改 Runtime State。

---

## Gate M5-17

M5 不直接写长期 Memory。

---

## Gate M5-18

关键 Workflow 支持 Checkpoint。

---

## Gate M5-19

系统恢复后不会盲目重放可能已经产生副作用的 Tool。

---

## Gate M5-20

一次 Execution 可以完整追踪：

```text
Plan
→ Step
→ Skill / Workflow
→ Tool
→ Result
```

---

## Gate M5-21

不同 Session Execution 不串用。

---

## Gate M5-22

资源竞争具备基础 Lock 机制。

---

## Gate M5-23

Execution 与 Ongoing Activity 已明确区分。

---

## Gate M5-24

Tool Permission 在执行前正式校验。

---

## Gate M5-25

ToolResult 的 SUCCESS / FAILED / TIMEOUT / UNKNOWN 等语义不会被 M5 自行改写。

---

# 22. 交付物

M5 最终至少形成：

```text
M5-01 Execution Framework总体架构

M5-02 Runtime Execution主流程

M5-03 ExecutionResult Schema

M5-04 ExecutionContext Schema

M5-05 Step Scheduler设计

M5-06 Skill执行规范

M5-07 Workflow执行规范

M5-08 Tool执行规范

M5-09 Skill / Workflow / Tool Registry规范

M5-10 Capability Resolver规范

M5-11 Tool Input / Output Validation规范

M5-12 Timeout规范

M5-13 Retry规范

M5-14 Idempotency规范

M5-15 Cancellation规范

M5-16 Preemption执行规范

M5-17 Concurrency / Resource Lock规范

M5-18 Execution State Store

M5-19 Workflow Checkpoint规范

M5-20 Crash Recovery规范

M5-21 Ongoing Activity规范

M5-22 Notification Execution规范

M5-23 Execution Event规范

M5-24 Execution Error Taxonomy

M5-25 Execution Trace规范

M5-26 M5 Metrics

M5-27 M5测试集

M5-28 M5 Gate验证报告
```

---

# 附录 A：推荐代码结构

```text
execution/

├── orchestrator.py
├── models.py
├── schemas.py
├── errors.py
│
├── scheduler/
│   ├── step_scheduler.py
│   └── dependency.py
│
├── capabilities/
│   ├── resolver.py
│   └── registry_adapter.py
│
├── skills/
│   ├── executor.py
│   └── base.py
│
├── workflows/
│   ├── executor.py
│   ├── manager.py
│   ├── checkpoint.py
│   └── base.py
│
├── tools/
│   ├── executor.py
│   ├── validator.py
│   ├── registry.py
│   └── base.py
│
├── retry/
│   ├── policy.py
│   └── manager.py
│
├── timeout/
│   └── manager.py
│
├── idempotency/
│   ├── manager.py
│   └── store.py
│
├── cancellation/
│   └── manager.py
│
├── concurrency/
│   ├── lock_manager.py
│   └── resource_lock.py
│
├── activities/
│   └── manager.py
│
├── recovery/
│   └── manager.py
│
└── tracing/
    └── execution_trace.py
```

---

# 附录 B：业务 Skill 目录建议

```text
skills/

├── companion/
├── content/
├── emotion/
├── cognitive/
├── weather/
└── news/
```

---

# 附录 C：业务 Workflow 目录

```text
workflows/

├── help/
├── discomfort/
├── reminder/
└── high_risk_emotion/
```

---

# 附录 D：Tool 目录

```text
tools/

├── playback/
├── notification/
├── weather/
├── news/
├── scheduler/
├── memory/
└── storage/
```

---

# 附录 E：第一版实现范围

第一版优先实现：

```text
ExecutionOrchestrator

StepScheduler

CapabilityResolver

SkillRegistry

WorkflowRegistry

ToolRegistry

ToolExecutor

Input / Output Validation

Timeout

Basic Retry

Cancellation

Basic Idempotency

ExecutionResult

Execution Trace
```

同时从第一版保留接口：

```text
Checkpoint

Recovery

Resource Lock

Ongoing Activity
```

---

# 附录 F：第一版不要过度实现

暂不需要：

```text
复杂分布式 Workflow

自动补偿事务平台

复杂 DAG Scheduler

跨机 Execution Migration

大规模 Worker Cluster

高级 Saga Engine
```

---

# 附录 G：第一版不能推迟的能力

必须第一版就具备：

```text
Tool真实结果

Timeout

Cancellation

Idempotency基础

Trace

Workflow Checkpoint接口

Plan ID

Execution ID

Step ID

Tool Call ID
```

这些能力越晚补，后续改造成本越高。

---

# 附录 H：典型 PoC

## H.1 播放成功

ActionPlan：

```text
PLAY_CONTENT
category = 评书
```

M5：

```text
ContentSkill

↓

SearchContentTool

↓

PlayTool
```

输出：

```text
ExecutionResult

plan_status =
SUCCESS

tool_results:
search = SUCCESS
play = SUCCESS
```

M6 再验证真实播放状态。

---

## H.2 播放失败

Search：

```text
SUCCESS
```

Play：

```text
FAILED
```

M5：

```text
ExecutionResult =
FAILED / PARTIAL_SUCCESS
```

不得生成：

```text
播放成功
```

---

## H.3 天气查询超时

ActionPlan：

```text
QUERY_INFORMATION

domain = WEATHER
```

WeatherTool：

```text
TIMEOUT
```

则：

```text
ExecutionResult.plan_status =
TIMEOUT
```

M5 不生成模型自造天气。

---

## H.4 求助通知幂等

同一个：

```text
help_event_id
```

由于网络抖动触发两次请求。

通过：

```text
idempotency_key
```

保证：

```text
不会创建两个求助事件
不会重复发送不必要通知
```

---

## H.5 求助抢占播放

当前：

```text
Playback Activity = ACTIVE
```

发生：

```text
Help Event
```

M2：

```text
PREEMPT
```

M5：

```text
停止 Playback Activity

↓

记录 PREEMPTED

↓

启动 HelpWorkflow
```

---

## H.6 用户取消播放

用户：

> “算了，不放了。”

当前：

```text
ContentSkill 正在搜索
```

M2/M4 形成 Stop Plan。

M5：

```text
cancel previous execution

↓

CANCELLED
```

尚未进入 PlayTool 时：

```text
不再执行 PlayTool
```

---

## H.7 Tool 不存在

ActionPlan：

```text
VideoCallTool
```

Registry 不存在。

返回：

```text
CAPABILITY_NOT_FOUND
```

不得自动换其他 Tool。

---

## H.8 网络断开

WeatherTool：

```text
network failure
```

如果 RetryPolicy 允许：

```text
有限重试
```

仍失败：

```text
FAILED
```

不得无限重试。

---

## H.9 进程崩溃恢复

HelpWorkflow：

```text
事件已创建

通知请求可能已发送

等待结果中
```

程序重启。

加载：

```text
Checkpoint
+
Idempotency Record
```

不得重新创建新的求助事件。

---

## H.10 两次播放竞争

Plan A：

```text
Play A
```

Plan B：

```text
Play B
```

通过：

```text
playback_lock
```

保证：

```text
播放器状态一致
```

不能同时启动两个独立播放流。

---

# 附录 I：M5 与 M6 的最终边界

这是 M5 最重要的交接原则。

M5 回答：

```text
调用了什么？

Tool 返回什么？

执行有没有失败？

执行有没有超时？
```

M6 回答：

```text
这些返回意味着什么？

哪些事实已经被确认？

哪些事实还未知？

哪些内容允许告诉用户？

哪些内容绝对不能说？
```

例如：

```text
NotifyTool.status =
TIMEOUT
```

M5 只能忠实返回。

M6 再判断：

```text
无法确认通知成功
```

M7 最终据此表达。

所以：

```text
Tool Success
!=
Business Truth

Execution Success
!=
Business Truth

Business Truth
!=
Allowed User Claim
```

---

# 附录 J：M0～M5 当前完整链路

```text
M0
Runtime Skeleton

↓

M1
Input & Context

↓

M2
Safety / State / Policy

↓

M3
Understanding

↓

M4
Planning & Orchestration

↓

M5
Execution Framework
```

形成：

```text
感知上下文

→ 约束

→ 理解

→ 决策

→ 执行
```

---

# 附录 K：M5 完成后的系统能力

M5 完成以后，系统已经能够：

```text
接收正式批准的 ActionPlan

知道每一步由谁执行

知道什么时候调用 Skill

什么时候进入 Workflow

什么时候调用 Tool

严格按顺序执行

处理 Timeout

有限 Retry

防止重复副作用

接受 Cancellation

落实 Preemption

控制资源竞争

保存关键 Workflow 进度

系统重启后恢复关键任务

完整记录真实执行结果
```

---

# 附录 L：M5 最终设计原则

M5 的核心思想：

```text
Planner 可以聪明，

Executor 必须可靠。
```

执行层追求的不是：

```text
灵活发挥
```

而是：

```text
严格执行

真实返回

失败可见

副作用可控

任务可取消

高优先级可抢占

关键流程可恢复

全过程可追踪
```

最终：

```text
M4
告诉系统：

“应该做什么。”

M5
保证系统：

“只做被批准的事情，
并把真正发生的结果如实带回来。”
```