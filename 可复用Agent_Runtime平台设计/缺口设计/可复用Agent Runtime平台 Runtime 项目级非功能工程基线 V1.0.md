# 可复用 Agent Runtime 平台
# Runtime 项目级非功能工程基线 V1.0

> **Phase 0 Fix**  
> 身份隔离键为 `identity_scope`，禁止 `elder_id`。数据契约以 Canonical Registry V1.0 为准。

> **平台化转换说明**  
> 本文已从单一业务 Agent 设计转换为 **可复用 Agent Runtime 平台**设计。除明确标记为 `Core` 的对象、接口、不变量和生命周期外，任何具体业务 Intent、Entity、Workflow、Skill、Tool、知识域、状态字段、规则、提示词或示例均视为 **Domain Package 示例**，不得硬编码进 Runtime Core。新项目应通过 Registry / Adapter / Plugin / Config 注入领域差异。
> 
> 平台固定边界：`Runtime Core` 尽量稳定；`Domain Extension` 插件化；`Business Package` 配置化；`Application` 负责产品装配。

---

# 0. 文档定位

本文件定义整个 Agent Runtime 的：

```text
Non-Functional Engineering Baseline
项目级非功能工程基线
```

它解决的不是：

```text
机器人会不会播放
会不会聊天
会不会提醒
```

而是：

```text
系统是否足够快

是否可靠

是否可恢复

是否安全

是否保护隐私

是否可观测

是否可配置

是否可版本化

是否可以被维护

是否具备上线条件
```

---

# 1. 适用范围

适用于：

```text
M0～M9 Runtime Core

Skill

Workflow

Tool

External API

Database

Memory Store

Scheduler

Notification

Playback

LLM Provider

Deployment

Monitoring
```

---

# 第一部分
# 性能基线

# 2. 性能原则

Agent 系统不要求所有步骤：

```text
越快越好
```

而要求：

```text
低风险场景响应足够自然

高风险路径优先低延迟

外部依赖有明确Timeout

任何阶段不能无限等待
```

---

# 3. 延迟预算分层

建议建立：

```text
End-to-End Latency Budget
```

而不是只看 LLM 延迟。

至少监控：

```text
Input Normalize

PreSafetyGuard

Context Build

Understanding

Policy

Planning

Execution

Validation

Response Generation

TTS
```

---

# 4. Safety Fast Path

高风险显式信号：

```text
不得等待完整深度理解流程
```

目标：

```text
PreSafetyGuard优先快速完成。
```

---

# 5. 外部 Tool 必须有 Timeout

任何：

```text
HTTP API

Database

Notification

Playback

Memory

Scheduler
```

调用必须具有：

```text
timeout_policy
```

禁止无限等待。

---

# 6. LLM Timeout

M3 / M4 / M7 必须：

```text
设置调用Timeout

存在降级路径
```

---

# 7. 性能指标

至少：

```text
P50

P95

P99

Timeout Rate
```

针对：

```text
Runtime总延迟

LLM延迟

Tool延迟

Validation延迟

TTS首包延迟
```

---

# 8. 流式策略

如果未来采用 Streaming：

必须明确：

```text
哪些内容可以提前流式

哪些内容必须等M6验证后再说
```

特别：

```text
Tool结果
Safety结果
外部业务状态
```

禁止在验证前提前流出确定性结果。

---

# 第二部分
# 可靠性基线

# 9. 所有外部依赖允许失败

必须默认：

```text
网络可能断

Tool可能Timeout

DB可能不可用

LLM可能失败

API可能限流

Memory可能不可用
```

架构不能建立在：

```text
“依赖永远成功”
```

的假设上。

---

# 10. Retry 基线

Retry 必须显式配置：

```text
max_attempts

retryable_errors

backoff

jitter
```

---

# 11. Side Effect Retry

有副作用操作必须先考虑：

```text
Idempotency
```

再考虑：

```text
Retry
```

---

# 12. Circuit Breaker

对于反复失败的外部依赖，建议支持：

```text
CLOSED

OPEN

HALF_OPEN
```

避免：

```text
持续调用故障服务
拖垮整个Runtime。
```

---

# 13. Graceful Degradation

允许：

```text
天气不可用
→ 说明暂时无法查询

Memory不可用
→ 暂时不用个性化

LLM Planner失败
→ deterministic fallback
```

但不能：

```text
依赖不可用
→ 伪造结果
```

---

# 14. Critical vs Non-critical Dependency

必须分类：

```text
CRITICAL

IMPORTANT

OPTIONAL
```

例如：

```text
Safety State Store
= CRITICAL

Memory Personalization
= OPTIONAL / IMPORTANT
```

具体按部署确定。

---

# 第三部分
# Crash Recovery 与一致性

# 15. 关键 Workflow 必须可恢复

至少：

```text
Help

Reminder

High-risk Workflow
```

需要：

```text
Checkpoint
```

---

# 16. Crash 后禁止盲目Replay

必须：

```text
检查Checkpoint

检查Idempotency Record

检查外部真实状态
```

再决定：

```text
resume
retry
unknown
manual recovery
```

---

# 17. Commit 分层

沿用 M8：

```text
Critical Runtime Commit

Conversation Commit

Memory Commit
```

---

# 18. 部分提交是合法状态

系统必须能够表达：

```text
PARTIAL_SUCCESS
```

而不是假设：

```text
要么全成功
要么全失败。
```

---

# 19. Critical State Store

至少保证：

```text
Active Safety Workflow

Critical Task

Safety Lock

Pending External Action

Idempotency Key
```

在进程崩溃后可恢复。

---

# 第四部分
# 幂等基线

# 20. 必须幂等的典型操作

至少：

```text
Create Help Event

Send Critical Notification

Reminder Update

Critical Event Creation

Memory Write Candidate

Conversation Turn Commit
```

---

# 21. Idempotency Key

至少绑定：

```text
request_id
plan_id
step_id
business_action
```

具体按 Tool 确定。

---

# 22. Idempotency状态

建议：

```text
NEW

RUNNING

SUCCESS

FAILED

UNKNOWN
```

---

# 23. UNKNOWN不能自动重做副作用

如果：

```text
上一操作结果UNKNOWN
```

优先：

```text
query external state
```

而不是：

```text
直接再执行一次。
```

---

# 第五部分
# 权限与Tool安全

# 24. Tool最小权限原则

每个 Tool 必须声明：

```text
required_permissions
```

只能获得：

```text
完成当前动作所需的最小权限。
```

---

# 25. Planner不能授予权限

权限来源：

```text
系统配置
角色
Policy
```

不是：

```text
LLM Plan。
```

---

# 26. Tool Allowlist

M5 只能执行：

```text
Registry中存在
+
enabled
+
当前Policy允许
```

的 Tool。

---

# 27. 参数校验

所有 Tool 调用必须：

```text
Schema Validate
```

禁止直接执行模型自由文本参数。

---

# 28. 高风险Tool二次约束

例如：

```text
通知

外部联络

敏感数据写入
```

建议额外检查：

```text
Permission

Policy

Idempotency

User / Event Scope
```

---

# 第六部分
# Secrets 与凭证

# 29. Secret禁止进入代码

禁止：

```text
API Key硬编码

密码写Prompt

Token写日志
```

---

# 30. Secret Store

生产环境应使用：

```text
环境变量
或
Secret Management System
```

---

# 31. Secret Rotation

重要凭证应支持：

```text
轮换
```

且不要求重新改代码。

---

# 第七部分
# 隐私与数据最小化

# 32. 最小必要原则

只采集：

```text
实现当前业务必要的数据。
```

不因为：

```text
未来可能有用
```

就无限保存。

---

# 33. Audio

默认：

```text
不长期保存完整原始音频。
```

如确有需要：

必须单独定义：

```text
用途

保存期限

访问权限

删除机制
```

---

# 34. Conversation

完整对话日志应区分：

```text
Runtime必要数据

Debug数据

产品数据

长期Memory
```

不能全部混为一体。

---

# 35. Memory 数据治理

Long-Term Memory 必须支持：

```text
user_scope

source

status

created_at

updated_at

expires_at

sensitivity
```

---

# 36. 用户删除与业务失效分开

```text
DEPRECATED
!=
DELETED
```

用户明确要求删除时：

必须走：

```text
真实数据删除流程。
```

---

# 37. Wrong-user Isolation

属于：

```text
Critical Privacy Requirement
```

目标：

```text
Wrong-user Context Rate = 0

Wrong-user Memory Rate = 0
```

---

# 第八部分
# 日志基线

# 38. 日志分类

建议：

```text
SYSTEM LOG

TRACE LOG

AUDIT LOG

SECURITY LOG
```

---

# 39. 普通日志禁止记录

默认避免：

```text
完整用户原话

完整健康信息

完整Memory内容

Secret

Token

身份证明信息
```

---

# 40. Trace 使用ID关联

优先记录：

```text
request_id
plan_id
tool_call_id
```

而不是把所有原始内容写日志。

---

# 41. 必须记录的重要事件

至少：

```text
Safety Workflow进入

Safety Lock变化

Tool Side Effect

Critical Notification

State Transition

Memory Write / Update / Deprecate

Policy Block

Validation Conflict

Crash Recovery
```

---

# 第九部分
# 可观测性

# 42. Trace

必须支持完整链：

```text
trace_id
↓
request_id
↓
plan_id
↓
execution_id
↓
tool_call_id
↓
validation_id
↓
response_id
↓
update_id
```

---

# 43. Metrics

至少建立四类：

```text
Runtime Metrics

LLM Metrics

Tool Metrics

Business Metrics
```

---

# 44. Runtime Metrics

例如：

```text
request count

E2E latency

error rate

degraded rate

unknown rate
```

---

# 45. LLM Metrics

例如：

```text
latency

timeout

token usage

schema failure

regeneration rate
```

---

# 46. Tool Metrics

例如：

```text
success rate

timeout rate

retry rate

idempotency hit rate

unavailable rate
```

---

# 47. Business Metrics

例如：

```text
playback success

reminder completion

notification status distribution

workflow completion

active greeting acceptance
```

---

# 48. Safety Metrics

必须独立：

```text
Safety Trigger Count

Forced Workflow Count

False Success

Policy Violation

Duplicate Critical Side Effect

Safety Recovery Failure
```

---

# 49. Memory Metrics

至少：

```text
write count

update count

deprecation count

temporary override count

wrong-user violation

memory service unavailable rate
```

---

# 第十部分
# 告警基线

# 50. 必须告警的情况

例如：

```text
Safety Store unavailable

Critical Notification failure spike

Wrong-user violation

State transition error spike

Crash recovery failure

Validation false-success detection

Tool timeout spike
```

---

# 51. 告警不能只基于单个日志字符串

优先：

```text
结构化Event
+
Metric Threshold
```

---

# 第十一部分
# 配置管理

# 52. 配置必须与代码分离

例如：

```text
Quiet Hours

Daily Active Limit

Reminder Retry Delay

Tool Timeout

Retry Count

Memory TTL

Feature Flag
```

应配置化。

---

# 53. 不能配置化的内容

以下属于架构硬约束：

```text
Truth Boundary

Safety Authority

M3不能调用Tool

M7不能提升事实确定性

Wrong-user禁止

Safety Lock不能由LLM释放
```

不能通过配置关闭。

---

# 54. Config Version

生产运行时应记录：

```text
config_version
```

便于回溯行为变化。

---

# 第十二部分
# Feature Flag

# 55. 新能力建议通过Feature Flag上线

例如：

```text
new_memory_strategy

new_planner

new_weather_provider
```

---

# 56. Feature Flag不能绕过Safety

禁止：

```text
experimental_mode
→ 跳过Safety Guard
```

---

# 57. Flag必须可回滚

生产问题出现时：

```text
可以快速关闭新能力
```

而不必整体回滚 Runtime。

---

# 第十三部分
# 版本管理

# 58. 必须版本化

至少：

```text
Schema

Prompt

Model

Policy

Validation Rule

Skill

Workflow

Tool

Business Capability

Configuration
```

---

# 59. 运行Trace必须记录关键版本

这样才能回答：

```text
为什么昨天同一句话
和今天行为不同？
```

---

# 60. Breaking Change

遵循 Core Schema Registry。

发生：

```text
Schema Major Change
```

必须：

```text
Migration

Compatibility Test

E2E Regression
```

---

# 第十四部分
# 模型与Prompt治理

# 61. Prompt不是临时代码字符串

生产 Prompt 必须：

```text
版本化

可评估

可回滚
```

---

# 62. 模型更换不能直接上线

模型升级必须重新运行：

```text
Stage Eval

Critical E2E

Safety E2E
```

---

# 63. Prompt修改同样需要回归

尤其：

```text
M3

M4

M7
```

---

# 64. LLM输出必须Schema Validate

不能：

```text
模型输出什么
Runtime就直接接受什么。
```

---

# 第十五部分
# Deployment 基线

# 65. 环境隔离

至少：

```text
DEV

TEST

STAGING

PROD
```

---

# 66. 不同环境的数据隔离

禁止：

```text
测试环境访问生产用户Memory
```

---

# 67. Safety Notification测试

测试环境必须：

```text
使用测试接收端
```

防止误通知真实领域服务人员。

---

# 第十六部分
# 数据库与存储

# 68. 存储至少区分

```text
Runtime State Store

Task / Workflow Store

Conversation Store

Memory Store

Audit / Trace Store
```

逻辑上要分清职责，即使第一版物理上共用数据库。

---

# 69. 数据库写入必须处理

```text
Timeout

Conflict

Duplicate

Partial Failure
```

---

# 70. Critical State需要可靠持久化

例如：

```text
HelpWorkflow

Safety Lock

Critical Reminder

Idempotency
```

不能只放内存。

---

# 第十七部分
# 时间与Scheduler

# 71. 时间统一

内部建议统一：

```text
标准时间表示
+
明确timezone
```

---

# 72. Reminder不能只靠进程sleep

应使用：

```text
Scheduler / Durable Timer
```

否则：

```text
进程重启
→ Reminder丢失
```

---

# 73. Timeout必须可恢复

Workflow Timeout 不应只存在当前进程内存。

---

# 第十八部分
# External API基线

# 74. 外部API必须Adapter化

例如：

```text
WeatherProvider

NewsProvider

NotificationProvider
```

Skill不直接绑定特定厂商。

---

# 75. Adapter统一处理

```text
Authentication

Timeout

Retry

Rate Limit

Error Mapping

Schema Normalization
```

---

# 76. API返回必须经过Tool Contract

禁止：

```text
第三方JSON
直接传给Planner或M7。
```

---

# 第十九部分
# 降级基线

# 77. 降级必须预定义

不能：

```text
运行时报错后
让LLM临时想办法。
```

---

# 78. 典型降级

```text
Memory不可用
→ No personalization

Weather不可用
→ 如实说明无法查询

Planner不可用
→ Deterministic fallback

Response LLM不可用
→ Safe template

Tool不可用
→ Failure / Unknown
```

---

# 第二十部分
# 安全上线基线

# 79. 正式用户测试前必须通过

至少：

```text
Safety E2E

Idempotency

Critical Notification

Wrong-user Isolation

Crash Recovery

UNKNOWN Preservation

Forbidden Claim
```

---

# 80. 真实用户试用 != 测试基础架构

不能把：

```text
生产试用
```

当作：

```text
发现基础Safety Bug的主要手段。
```

---

# 第二十一部分
# 工程质量基线

# 81. 每个模块至少需要

```text
Type / Schema Check

Unit Test

Error Handling

Logging

Trace

Config

Documentation
```

---

# 82. 禁止Silent Failure

异常必须：

```text
返回正式Error

记录Trace

必要时进入Degraded
```

不能：

```text
catch Exception:
    pass
```

---

# 83. 禁止Business Logic散落

例如：

```text
提醒3分钟规则
```

不能同时存在于：

```text
Prompt

Skill

Scheduler

Frontend
```

多个位置各写一份。

必须有唯一 Rule Owner。

---

# 第二十二部分
# SLO建议框架

具体数值可以在真实部署和性能测试后确定。

第一版先定义指标，不强行写死不成熟数字。

至少建立：

```text
Availability

E2E Latency

Critical Workflow Success

Critical Duplicate Side Effect

Wrong-user Isolation

False Success

Claim Violation
```

---

# 84. Safety类SLO优先级

建议：

```text
正确性
>
延迟
```

普通陪伴则可以平衡：

```text
自然度
+
延迟
+
成本
```

---

# 第二十三部分
# 成本与资源

# 85. LLM调用应可观测

至少：

```text
tokens

requests

model

cost
```

---

# 86. 不应每一步都调用LLM

遵循现有架构：

```text
Rule / Deterministic
能解决的
不强制LLM。
```

---

# 87. Context应控制大小

避免：

```text
全部历史
+
全部Memory
+
全部业务文档
```

每轮全部输入模型。

---

# 第二十四部分
# 非功能Gate

## NFR-01

所有外部调用有Timeout。

## NFR-02

所有Critical Side Effect有Idempotency策略。

## NFR-03

关键Workflow可Crash Recovery。

## NFR-04

Memory / Context严格User Scope隔离。

## NFR-05

所有Tool受Permission与Registry控制。

## NFR-06

Secrets不进入代码和普通日志。

## NFR-07

完整Runtime Trace可建立。

## NFR-08

关键Schema / Prompt / Policy / Tool均有版本。

## NFR-09

关键配置与代码分离。

## NFR-10

LLM失败存在明确降级。

## NFR-11

Memory失败不破坏Critical Runtime State。

## NFR-12

真实用户试用前Safety E2E通过。

## NFR-13

外部API通过Adapter接入。

## NFR-14

Reminder / Timeout使用Durable Scheduler机制。

## NFR-15

生产敏感日志遵循最小必要原则。

## NFR-16

Feature Flag不能绕过Safety。

## NFR-17

不存在无限Retry。

## NFR-18

不存在无限等待。

## NFR-19

不存在Silent Critical Failure。

## NFR-20

任何Release能力均有可观测状态。

---

# 第二十五部分
# Release Readiness Checklist

每次 Release 前至少确认：

```text
□ E2E Gate通过

□ Safety Gate通过

□ 外部依赖状态确认

□ Tool Timeout配置

□ Retry / Idempotency确认

□ Critical Workflow Recovery验证

□ User Scope隔离验证

□ Secrets配置完成

□ 日志脱敏确认

□ Metrics可用

□ Alert可用

□ Schema版本确认

□ Prompt / Model版本确认

□ Policy / Rule版本确认

□ Feature Flag确认

□ Migration完成

□ Rollback方案存在
```

---

# 第二十六部分
# 最终工程原则

正式固定：

```text
一、所有外部依赖都可能失败。

二、所有关键副作用都必须防重复。

三、所有关键Workflow都必须考虑崩溃恢复。

四、所有个人状态都必须严格隔离用户。

五、所有真实行为都必须可追踪。

六、所有关键行为规则都必须可版本化。

七、LLM不可用时系统仍需安全降级。

八、性能优化不能突破Truth和Safety边界。

九、日志与可观测性不能以泄露隐私为代价。

十、功能完成不等于工程上可发布。
```

至此：

```text
Runtime 项目级非功能工程基线 V1.0
=
FROZEN
```