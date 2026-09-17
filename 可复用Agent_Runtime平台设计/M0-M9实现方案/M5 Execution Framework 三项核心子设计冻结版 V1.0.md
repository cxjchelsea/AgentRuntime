# 可复用 Agent Runtime 平台  
# M5 Execution Framework 三项核心子设计冻结版 V1.0

> **Phase 0 Fix**  
> M5 只接受 `ApprovedActionPlan`。`ExecutionResult.status` 作为正式字段名已失效，统一为 `plan_status`。

> **平台化转换说明**  
> 本文已从单一业务 Agent 设计转换为 **可复用 Agent Runtime 平台**设计。除明确标记为 `Core` 的对象、接口、不变量和生命周期外，任何具体业务 Intent、Entity、Workflow、Skill、Tool、知识域、状态字段、规则、提示词或示例均视为 **Domain Package 示例**，不得硬编码进 Runtime Core。新项目应通过 Registry / Adapter / Plugin / Config 注入领域差异。
> 
> 平台固定边界：`Runtime Core` 尽量稳定；`Domain Extension` 插件化；`Business Package` 配置化；`Application` 负责产品装配。

---

# 0. 冻结说明

本文件冻结 M5 的三项核心子设计：

```text
M5-A ExecutionResult Schema

M5-B Skill / Workflow / Tool Contract

M5-C Retry / Idempotency / Cancellation Reliability Contract
```

冻结后的正式执行链为：

```text
Approved ActionPlan
        ↓
M5 Execution Framework
        ↓
ExecutionResult
        ↓
M6 Result Validation
```

其中必须保持：

```text
M4
决定做什么

M5
执行计划并如实记录实际执行结果

M6
判断这些结果意味着什么
```

本次冻结内容分为：

```text
Frozen Core
核心结构和职责边界，不允许破坏

Extensible Registry
允许后续新增 Skill / Workflow / Tool

Runtime Config
允许调整超时、重试次数等参数
```

---

# 第一部分  
# ExecutionResult Schema 冻结规范

## 1. ExecutionResult 定位

`ExecutionResult` 是 M5 唯一正式输出。

它回答：

> 已批准的 ActionPlan 实际执行到了哪里，每个步骤调用了什么能力，真实返回了什么结果，执行过程中发生了什么错误、超时、取消或抢占。

它不能回答：

```text
“业务最终是否成功”
“哪些事实可以告诉用户”
“应该如何回复用户”
```

这些属于 M6 和 M7。

---

# 2. Frozen Core 主结构

正式冻结：

```text
ExecutionResult

metadata

plan_status

step_results

skill_results

workflow_result

tool_results

business_outputs

execution_events

state_observations

errors

timing

cancellation

quality
```

后续允许增加子字段，但不得删除这些核心对象。

---

# 3. metadata

冻结为：

```text
metadata

execution_id
plan_id
request_id
session_id

executor_version

started_at
finished_at
```

必须保证：

```text
request_id
→ plan_id
→ execution_id
```

可完整关联。

---

# 4. plan_status

冻结枚举：

```text
SUCCESS

PARTIAL_SUCCESS

FAILED

TIMEOUT

CANCELLED

PREEMPTED
```

---

## 4.1 SUCCESS 的定义

仅表示：

```text
M5要求执行的必要步骤均完成，
且没有执行层错误导致计划失败。
```

不代表：

```text
Business Truth = Success
```

---

## 4.2 PARTIAL_SUCCESS

表示：

```text
部分步骤成功，
部分步骤失败或被跳过，
但整个执行没有完全失败。
```

---

## 4.3 FAILED

表示：

```text
关键执行步骤失败，
导致 ActionPlan 无法完成。
```

---

## 4.4 TIMEOUT

表示：

```text
Plan 或关键 Step 超过允许时间。
```

不得自动解释为：

```text
FAILED
```

更不得解释为：

```text
SUCCESS
```

---

## 4.5 CANCELLED

表示：

```text
执行被显式取消。
```

例如：

```text
用户取消
Session结束
系统关闭
```

---

## 4.6 PREEMPTED

表示：

```text
因为更高优先级事件，
当前执行被抢占。
```

必须与普通取消区分。

---

# 5. step_results

冻结为：

```text
step_results[]
```

每项为：

```text
StepExecutionResult

step_execution_id

step_id
action

status

skill_id
workflow_id

tool_call_ids[]

output

error

retry_count

started_at
finished_at
```

---

# 6. Step Status

冻结：

```text
PENDING

RUNNING

SUCCESS

FAILED

SKIPPED

TIMEOUT

CANCELLED

PREEMPTED
```

---

# 7. SKIPPED 的定义

例如：

```text
Step 2 depends_on Step 1

Step 1 failed

Step 2未执行
```

则：

```text
Step 2 = SKIPPED
```

不能记录为 FAILED，因为它根本没有执行。

---

# 8. skill_results

冻结：

```text
skill_results[]
```

结构：

```text
SkillExecutionResult

skill_id
skill_version

status

action

business_output

tool_call_ids[]

error

started_at
finished_at
```

---

# 9. workflow_result

若本次执行进入 Workflow，则：

```text
WorkflowExecutionResult

workflow_id
workflow_instance_id

status

current_step

completed_steps[]

pending_step

checkpoint_id

outputs

error
```

否则：

```text
workflow_result = null
```

---

# 10. Workflow Status

冻结：

```text
CREATED

RUNNING

WAITING

COMPLETED

FAILED

TIMEOUT

CANCELLED
```

---

# 11. WAITING

必须支持：

```text
Workflow 当前没有失败，
而是在等待外部事件。
```

例如：

```text
等待通知回执
等待用户确认
等待Tool callback
```

这类状态不能误判成：

```text
SUCCESS
或
FAILED
```

---

# 12. tool_results

冻结：

```text
tool_results[]
```

每项：

```text
ToolResult

tool_call_id
tool_id
tool_version

status

input_summary

data

error_code
error_message

attempt

idempotency_key

started_at
finished_at

metadata
```

---

# 13. Tool Status 冻结

```text
SUCCESS

FAILED

TIMEOUT

CANCELLED

UNAVAILABLE

REJECTED
```

---

# 14. REJECTED

表示：

```text
Tool本身存在，
但本次调用未被允许。
```

例如：

```text
权限不足

未绑定用户禁止写Memory

Policy禁止
```

---

# 15. UNAVAILABLE

表示：

```text
能力当前不可用
```

例如：

```text
Tool服务下线

设备能力不存在

网络导致服务不可达
```

---

# 16. business_outputs

冻结：

```text
business_outputs[]
```

用于记录 Skill / Workflow 产生的业务级输出。

例如：

```text
content_id
playback_session_id
help_event_id
notification_request_id
weather_payload
reminder_update_id
```

但它们仍然只是：

```text
M5执行过程中产生的业务输出
```

是否可以视为最终事实，由 M6 判断。

---

# 17. execution_events

冻结：

```text
execution_events[]
```

核心事件：

```text
EXECUTION_STARTED

STEP_STARTED
STEP_COMPLETED
STEP_FAILED

SKILL_STARTED
SKILL_COMPLETED
SKILL_FAILED

WORKFLOW_STARTED
WORKFLOW_WAITING
WORKFLOW_COMPLETED
WORKFLOW_FAILED

TOOL_STARTED
TOOL_COMPLETED
TOOL_FAILED

EXECUTION_CANCELLED
EXECUTION_PREEMPTED
EXECUTION_COMPLETED
```

---

# 18. state_observations

冻结：

```text
state_observations[]
```

只允许记录：

```text
M5观察到的事实
```

例如：

```text
playback_started = true

notification_request_created = true

workflow_waiting_callback = true
```

不允许直接：

```text
current_state = S06
```

Runtime State 仍由 State Engine 管理。

---

# 19. errors

冻结：

```text
errors[]
```

结构：

```text
ExecutionError

error_code

stage

step_id
skill_id
workflow_id
tool_id

recoverable
retryable

message

cause

timestamp
```

---

# 20. Error Code 核心集合冻结

```text
INVALID_PLAN

INVALID_PARAMETER

CAPABILITY_NOT_FOUND

CAPABILITY_DISABLED

TOOL_NOT_FOUND

TOOL_UNAVAILABLE

TOOL_TIMEOUT

TOOL_FAILED

TOOL_INVALID_OUTPUT

PERMISSION_DENIED

RESOURCE_BUSY

WORKFLOW_ERROR

CHECKPOINT_ERROR

EXECUTION_TIMEOUT

EXECUTION_CANCELLED

EXECUTION_PREEMPTED

UNKNOWN_EXECUTION_ERROR
```

允许后续扩展。

---

# 21. timing

冻结：

```text
timing

total_duration_ms

step_durations

tool_durations
```

主要用于：

```text
性能
超时
可观测性
```

---

# 22. cancellation

冻结：

```text
cancellation

cancelled

reason

requested_at

source
```

`source`：

```text
USER
POLICY
PREEMPTION
SYSTEM
TIMEOUT
```

---

# 23. quality

冻结：

```text
quality

schema_valid

plan_followed

tool_outputs_valid

degraded

warnings[]
```

---

# 24. ExecutionResult 禁止字段

禁止出现：

```text
final_user_response

verified_business_success

allowed_user_claims

memory_update

direct_runtime_state
```

这些属于后续阶段。

---

# 25. ExecutionResult 核心冻结原则

正式固定：

```text
M5只记录：

做了什么
调用了什么
真实返回了什么
有没有失败
有没有超时
有没有取消
有没有抢占
```

不得扩展成：

```text
解释真实世界
```

---

# 第二部分  
# Skill / Workflow / Tool Contract 冻结规范

# 26. 总体模型

正式固定：

```text
Action
↓
Skill / Workflow
↓
Tool
```

其中：

```text
Action
= 想做什么

Skill
= 如何完成一种普通业务能力

Workflow
= 如何按固定流程推进一个受约束任务

Tool
= 执行一个最小真实动作
```

---

# 27. Tool Contract

Tool 是真实世界和外部系统动作的最小单元。

正式冻结：

```text
Tool

execute(input, execution_context)
→ ToolResult
```

---

# 28. ToolDefinition

冻结：

```text
ToolDefinition

tool_id
version

description

input_schema
output_schema

timeout_policy
retry_policy

idempotency_mode

side_effect_level

required_permissions[]

resource_requirements[]

enabled
```

---

# 29. Tool 输入要求

所有 Tool 调用必须经过：

```text
Input Schema Validation
```

禁止：

```text
参数缺失仍执行
字段类型错误仍执行
```

---

# 30. Tool 输出要求

所有 Tool Result 必须经过：

```text
Output Schema Validation
```

如果第三方 API 返回异常格式：

```text
TOOL_INVALID_OUTPUT
```

而不是尝试让 LLM 猜测结果。

---

# 31. Tool Side Effect Level

冻结：

```text
NONE

LOW

MEDIUM

HIGH
```

示例：

```text
query_weather
→ NONE

query_news
→ NONE

play_content
→ LOW

update_reminder
→ MEDIUM

create_help_event
→ HIGH

send_notification
→ HIGH
```

---

# 32. Tool 不允许承担的职责

禁止：

```text
解释用户意图

判断情绪

选择业务策略

选择是否应该调用自己

自行生成最终用户回复

自行更新 Runtime State
```

---

# 33. Skill Contract

正式冻结：

```text
Skill

execute(
    action,
    parameters,
    execution_context
)
→ SkillResult
```

---

# 34. SkillDefinition

冻结：

```text
SkillDefinition

skill_id
version

supported_actions[]

required_tools[]

optional_tools[]

allowed_states[]

timeout_policy

enabled
```

---

# 35. Skill 可以做什么

允许：

```text
业务参数转换

业务资源选择

调用多个注册Tool

组合普通业务执行逻辑

整理business_output
```

---

# 36. Skill 不允许做什么

禁止：

```text
重新解析M3

重新选择Strategy

改变M4 Primary Goal

绕过Policy

调用未注册Tool

伪造Tool结果

生成最终自然语言回复
```

---

# 37. SkillResult

冻结：

```text
SkillResult

skill_id
version

status

business_output

tool_results[]

events[]

error
```

---

# 38. Skill Status

冻结：

```text
SUCCESS

PARTIAL_SUCCESS

FAILED

TIMEOUT

CANCELLED
```

---

# 39. Workflow Contract

正式冻结：

```text
Workflow

start(...)
handle_event(...)
resume(...)
cancel(...)
status(...)
```

Workflow 可以跨：

```text
多个 Runtime Cycle
```

这是和 Skill 的核心区别。

---

# 40. WorkflowDefinition

冻结：

```text
WorkflowDefinition

workflow_id
version

supported_events[]

initial_step

steps[]

checkpoint_enabled

timeout_policy

allowed_states[]

enabled
```

---

# 41. WorkflowInstance

冻结：

```text
WorkflowInstance

workflow_instance_id

workflow_id
workflow_version

status

current_step

completed_steps[]

pending_step

context

created_at
updated_at
```

---

# 42. Workflow Checkpoint

冻结：

```text
WorkflowCheckpoint

checkpoint_id

workflow_instance_id

current_step

completed_steps[]

pending_step

critical_outputs

created_at
```

---

# 43. 必须支持 Checkpoint 的 Workflow

优先包括：

```text
HelpWorkflow

HighRiskEmotionWorkflow

DiscomfortWorkflow

ReminderWorkflow
```

尤其是：

```text
存在通知
跨轮确认
等待外部回调
```

的流程。

---

# 44. Workflow 不允许做什么

同样禁止：

```text
重做M3理解

重做M4自由策略规划

绕开State Machine

绕开Policy

伪造外部执行成功
```

---

# 45. Skill 与 Workflow 的选择冻结原则

```text
如果目标是完成一种普通能力
→ Skill

如果目标需要固定步骤、
中间状态、
跨轮推进、
强制约束
→ Workflow
```

---

# 46. 业务示例冻结

普通陪伴：

```text
CompanionSkill
```

内容：

```text
ContentSkill
```

领域任务交互：

```text
CognitiveSkill
```

天气：

```text
WeatherSkill
```

新闻：

```text
NewsSkill
```

求助：

```text
HelpWorkflow
```

不适采集：

```text
DiscomfortWorkflow
```

高风险情绪：

```text
HighRiskEmotionWorkflow
```

提醒：

```text
ReminderWorkflow
```

---

# 47. Registry Contract

正式冻结三类 Registry：

```text
SkillRegistry

WorkflowRegistry

ToolRegistry
```

都至少支持：

```text
register

lookup

enable

disable

version
```

---

# 48. Capability Resolver 冻结规则

M5 只能：

```text
根据 ActionPlan 指定的 capability
查询 Registry
```

如果不存在：

```text
CAPABILITY_NOT_FOUND
```

禁止：

```text
M5自行寻找替代Capability
```

因为那属于重新规划。

---

# 49. Version Compatibility

必须保留：

```text
version
```

接口。

后续至少允许：

```text
Planner要求某Capability版本
```

与：

```text
Executor实际版本
```

进行兼容检查。

---

# 50. Permission Contract

每次 Tool 执行前必须经过：

```text
Tool Permission Check
```

权限来源可包括：

```text
PolicyDecision

identity binding

device capability

workflow state

privacy rules
```

---

# 51. 未绑定用户示例

如果：

```text
identity_status = UNBOUND
```

而 Tool 是：

```text
write_personal_memory
```

则：

```text
ToolResult.status = REJECTED
```

不得自动创建未知用户档案。

---

# 52. Skill / Workflow / Tool Frozen Boundary

正式固定：

```text
Skill不能重新规划

Workflow不能绕过Policy

Tool不能决定自己是否应该被调用
```

整个执行层都只服务于：

```text
Approved ActionPlan
```

---

# 第三部分  
# Retry / Idempotency / Cancellation 可靠性冻结规范

# 53. 总体目标

本规范解决三个执行层核心问题：

```text
失败了能不能再试？

再试会不会做重复动作？

用户或高优先级事件来了能不能及时停？
```

即：

```text
Retry
+
Idempotency
+
Cancellation
```

---

# 54. Retry 核心原则

正式固定：

```text
不是所有失败都可以重试
```

Retry 必须同时考虑：

```text
Error Type

Tool Idempotency

Side Effect Level

Attempt Count
```

---

# 55. RetryPolicy

冻结：

```text
RetryPolicy

enabled

max_attempts

retryable_errors[]

backoff_strategy

base_delay

max_delay

jitter
```

---

# 56. Retryable Error

第一版典型：

```text
TEMPORARY_NETWORK_ERROR

SERVICE_UNAVAILABLE

TRANSIENT_TIMEOUT

RATE_LIMITED
```

是否真正启用根据具体 Tool 配置。

---

# 57. Non-Retryable Error

典型：

```text
INVALID_ARGUMENT

PERMISSION_DENIED

BUSINESS_REJECTED

CAPABILITY_NOT_FOUND

INVALID_OUTPUT_SCHEMA
```

默认不得自动重试。

---

# 58. Side Effect 与 Retry

如果：

```text
side_effect_level = HIGH
```

默认：

```text
不得仅凭Timeout直接无脑重试
```

必须先确认：

```text
Tool支持Idempotency
```

或：

```text
能查询前一次调用状态
```

---

# 59. Idempotency 核心原则

正式固定：

```text
同一个业务动作即使重复触发执行，
也不能产生重复关键副作用。
```

---

# 60. Idempotency Key

冻结生成组成：

```text
request_id
+
plan_id
+
step_id
+
business_action
```

必要时加入：

```text
workflow_instance_id
```

---

# 61. IdempotencyMode

冻结：

```text
NATURAL

KEY_BASED

NON_IDEMPOTENT
```

---

# 62. NATURAL

例如：

```text
query_weather
```

重复调用不会造成业务副作用。

---

# 63. KEY_BASED

例如：

```text
create_help_event

send_notification

update_reminder
```

必须使用：

```text
idempotency_key
```

保证重复调用只对应一次逻辑动作。

---

# 64. NON_IDEMPOTENT

若 Tool 无法保证幂等：

```text
默认禁止自动重试高副作用调用
```

除非具有其他业务补偿或状态确认机制。

---

# 65. Idempotency Store

建议冻结：

```text
IdempotencyRecord

idempotency_key

tool_id

status

result_reference

created_at
updated_at
```

---

# 66. 重复调用处理

如果发现：

```text
同一个 idempotency_key
已经 SUCCESS
```

则：

```text
直接返回原结果
```

不要再次执行真实副作用。

---

# 67. Pending 调用处理

如果：

```text
同一个key
状态 = RUNNING / UNKNOWN
```

不得立即重复执行。

应：

```text
等待
查询状态
或返回UNKNOWN
```

---

# 68. Notification 特殊冻结规则

通知必须区分：

```text
REQUEST_ACCEPTED

SENT

DELIVERED

FAILED

TIMEOUT

UNKNOWN
```

如果实际接口只支持部分状态：

```text
只允许记录接口真实支持的状态
```

不得推导：

```text
REQUEST_ACCEPTED
=
DELIVERED
```

---

# 69. Cancellation 核心原则

正式固定：

```text
所有可持续Execution
必须具备取消入口。
```

---

# 70. CancellationToken

冻结：

```text
CancellationToken

execution_id

cancel_requested

reason

source

requested_at
```

---

# 71. Cancellation Source

冻结：

```text
USER

POLICY

PREEMPTION

SYSTEM

TIMEOUT
```

---

# 72. Cancel 检查点

M5 至少在以下位置检查：

```text
Step开始前

Tool调用前

Tool调用后

Retry前

进入下一Step前
```

长时间 Tool 若支持取消，应将 Token 向下传递。

---

# 73. Cancellation 的执行行为

正式固定：

```text
停止尚未执行Step

取消支持取消的Tool

执行必要Cleanup

保留已完成结果

记录Cancellation

生成ExecutionResult
```

---

# 74. 已完成副作用不可回滚假装不存在

例如：

```text
通知已经发送
```

用户随后：

> “算了。”

则只能：

```text
停止后续动作
```

不能把历史结果改成：

```text
通知未发送
```

---

# 75. Preemption

Preemption 来源于 M2。

冻结：

```text
PREEMPTION
=
Higher Priority Runtime Event
```

例如：

```text
播放
↓
用户求助
↓
M2判定抢占
↓
M5停止当前执行
↓
ExecutionResult = PREEMPTED
```

---

# 76. Preemption 不等于 Failure

必须保持：

```text
PREEMPTED
!=
FAILED
```

因为原计划可能没有执行错误，只是被高优先级事件终止。

---

# 77. Cancellation 与 Workflow

跨轮 Workflow 被取消时必须保存：

```text
cancelled state

completed steps

side effects already performed
```

不得简单删除 Workflow 记录。

---

# 78. Crash Recovery 与 Idempotency

系统恢复后：

```text
如果某高副作用Tool状态未知
```

必须先：

```text
查询IdempotencyRecord
或
查询外部系统状态
```

不能直接重放。

---

# 79. UNKNOWN 是合法状态

这是本规范的重要冻结原则。

当系统无法确认：

```text
通知到底有没有送达
外部动作到底有没有完成
```

应保留：

```text
UNKNOWN
```

而不是为了“给用户确定答复”强行转换为成功或失败。

---

# 80. Timeout 与 Retry 的冻结关系

```text
Timeout
↓
判断Tool类型
↓
判断Idempotency
↓
判断RetryPolicy
↓
允许才Retry
```

禁止：

```text
Timeout
→ 一律Retry
```

---

# 81. Retry 最大次数

具体：

```text
max_attempts
```

属于 Runtime Config。

但冻结：

```text
Retry必须存在硬上限
```

禁止无限重试。

---

# 82. Backoff

支持：

```text
FIXED

EXPONENTIAL
```

后续可扩展。

---

# 83. Retry Trace

每次尝试必须记录：

```text
attempt

error

delay

started_at
finished_at
```

最终 ExecutionResult 应能还原：

```text
一共调用了几次
为什么重试
```

---

# 84. Duplicate Side Effect 防护 Gate

以下业务必须专门测试：

```text
Help Event 创建

工作人员通知

提醒状态更新

用户关键记录写入
```

要求：

```text
重复执行相同Plan
不得产生重复关键副作用
```

---

# 85. Reliability Error 分类

建议：

```text
RETRY_EXHAUSTED

IDEMPOTENCY_CONFLICT

DUPLICATE_REQUEST

CANCELLATION_FAILED

PREEMPTION_FAILED

UNKNOWN_EXTERNAL_STATE

RECOVERY_STATE_CONFLICT
```

---

# 第四部分  
# 三项冻结设计之间的关系

# 86. 总体关系

正式固定：

```text
Skill / Workflow / Tool Contract
定义：

执行能力是什么
以及怎样执行

↓

Retry / Idempotency / Cancellation
定义：

执行过程中怎样保证可靠

↓

ExecutionResult Schema
定义：

最后怎样把真实执行过程交给M6
```

---

# 87. M4 → M5 边界

M5 只能接受：

```text
Approved ActionPlan
```

不得以：

```text
用户原始文本
UnderstandingState
```

作为重新决策依据。

---

# 88. M5 → M6 边界

M6 只能以：

```text
ExecutionResult
+
相关真实系统状态
```

进行验证。

不得假定：

```text
Planner想成功
=
执行成功
```

---

# 89. 冻结后的执行主链

正式固定为：

```text
Approved ActionPlan
        ↓
Execution Orchestrator
        ↓
Step Scheduler
        ↓
Capability Resolver
        ↓
Skill / Workflow
        ↓
Tool
        ↓
Retry / Timeout / Idempotency / Cancellation
        ↓
真实 ToolResult
        ↓
ExecutionResult
        ↓
M6 Result Validation
```

---

# 90. Frozen Core 总结

从 V1.0 起，以下视为 M5 Frozen Core：

```text
ExecutionResult 主结构

PlanStatus 六类

StepStatus 八类

ToolStatus 六类

Skill / Workflow / Tool 三层执行模型

Registry机制

Workflow Instance / Checkpoint

Tool Input / Output Schema Validation

Side Effect Level

RetryPolicy

IdempotencyMode

IdempotencyKey

CancellationToken

PREEMPTED独立状态

UNKNOWN真实状态

M5不得重新规划

M5不得直接更新Runtime State

M5不得生成最终回复
```

---

# 91. 允许扩展内容

未来允许新增：

```text
Skill

Workflow

Tool

Tool Error Code

Business Output

Execution Event

Retry策略实现

Registry条目
```

但必须：

```text
向后兼容
+
满足Contract
+
新增测试
```

---

# 92. 不允许破坏的内容

禁止以后变成：

```text
Tool内部自己判断用户意图

Skill发现Planner不合理后自行换策略

Workflow绕过Policy

Tool Timeout后直接当成功

M5直接告诉用户“成功了”

系统崩溃后无脑重复发送通知
```

---

# 93. 冻结完成 Gate

以下全部满足后视为 M5 Core Frozen：

```text
1. ExecutionResult Schema固定

2. Skill Contract固定

3. Workflow Contract固定

4. Tool Contract固定

5. Tool状态枚举固定

6. Side Effect概念固定

7. Retry决策边界固定

8. Idempotency机制位置固定

9. Cancellation机制位置固定

10. Preemption状态固定

11. Workflow Checkpoint位置固定

12. M5→M6接口固定

13. UNKNOWN外部状态被正式支持

14. M5不能重新规划被正式固定
```

---

# 94. 冻结后的项目状态

到这里：

```text
M3
理解用户
↓
UnderstandingState

M4
选择行为
↓
Approved ActionPlan

M5
可靠执行
↓
ExecutionResult
```

三个核心接口已经稳定：

```text
UnderstandingState
→
ActionPlan
→
ExecutionResult
```

这意味着后续：

```text
模型可以换

Prompt可以优化

Skill可以增加

Tool可以增加

业务模块可以增加
```

但整个 Runtime 主骨架无需重构。

---

# 95. 下一阶段的正式问题

M6 接下来不再关心：

```text
“为什么选择这个行为？”
```

也不重新执行 Tool。

它只回答：

```text
根据 M5 返回的 ExecutionResult，

到底有哪些事实已经被真实确认？

哪些仍然未知？

业务目标到底完成了没有？

哪些内容可以告诉用户？

哪些内容绝对不能说？
```

因此：

```text
M5
=
执行真实世界

M6
=
建立真实世界的可信解释
```

至此，M5 核心设计正式冻结。