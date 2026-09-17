# 可复用 Agent Runtime 平台  
# M6 Result Validation 三项核心子设计冻结版 V1.0

> **Phase 0 Fix**  
> 文中 `ActionPlan` 指上游 `ApprovedActionPlan`。播放等内容例子为 Domain Example。

> **平台化转换说明**  
> 本文已从单一业务 Agent 设计转换为 **可复用 Agent Runtime 平台**设计。除明确标记为 `Core` 的对象、接口、不变量和生命周期外，任何具体业务 Intent、Entity、Workflow、Skill、Tool、知识域、状态字段、规则、提示词或示例均视为 **Domain Package 示例**，不得硬编码进 Runtime Core。新项目应通过 Registry / Adapter / Plugin / Config 注入领域差异。
> 
> 平台固定边界：`Runtime Core` 尽量稳定；`Domain Extension` 插件化；`Business Package` 配置化；`Application` 负责产品装配。

---

# 0. 冻结说明

本文件正式冻结 M6 的三项核心设计：

```text
M6-A ValidatedResult Schema

M6-B Evidence + Claim Policy

M6-C Goal Validation + UNKNOWN / Conflict Rules
```

冻结后的正式链路：

```text
ExecutionResult
        ↓
M6 Result Validation
        ↓
ValidatedResult
        ↓
M7 Response Generation
```

其中职责固定为：

```text
M5
记录实际执行了什么

M6
判断这些结果意味着什么

M7
把经过验证的事实说给用户
```

---

# 一、冻结层级

本规范分为三类：

```text
Frozen Core
不可破坏的核心数据结构、状态和规则

Extensible Registry
允许增加 Goal、Tool、Claim、Evidence 规则

Runtime Configuration
允许调整时效、严格程度、规则参数
```

后续新增业务：

```text
视频通话
家庭留言
新型提醒
新Tool
```

不得重新设计 M6 主架构。

---

# 第一部分  
# M6-A ValidatedResult Schema 冻结规范

## 1. ValidatedResult 定位

`ValidatedResult` 是 M6 唯一正式输出。

它回答：

```text
业务目标有没有完成？

现在真正知道哪些事实？

哪些事实还不知道？

是否存在冲突？

哪些内容可以告诉用户？

哪些内容不能告诉用户？

后续是否还需要继续处理？
```

它不是：

```text
Execution Trace
最终自然语言回复
Runtime State本身
Memory最终写入结果
新的ActionPlan
```

---

# 2. Frozen Core 主结构

正式冻结：

```text
ValidatedResult

metadata

validation_status

goal_validation

business_status

verified_facts

unverified_facts

conflicting_facts

claim_policy

followup

state_recommendation

validation_errors

quality
```

后续允许在子对象内增加字段，但不得删除这些核心区域。

---

# 3. metadata

冻结：

```text
metadata

validation_id

execution_id
plan_id
request_id
session_id

validator_version
rule_version
schema_version

created_at
```

---

# 4. validation_status

正式冻结为：

```text
VALIDATED

PARTIALLY_VALIDATED

NOT_VALIDATED

CONFLICTED

UNKNOWN
```

---

# 5. VALIDATED

定义：

```text
关键业务判断所需证据充分，
不存在影响结论的未解决冲突。
```

不代表所有字段都有值。

---

# 6. PARTIALLY_VALIDATED

定义：

```text
部分事实已经确认，
但仍有部分重要事实未知。
```

例如：

```text
求助事件已经创建
但通知是否送达未知
```

---

# 7. NOT_VALIDATED

定义：

```text
现有证据不足以完成关键结果验证。
```

这与：

```text
业务失败
```

不同。

---

# 8. CONFLICTED

定义：

```text
存在互相矛盾的关键证据，
且目前无法可靠解决。
```

---

# 9. UNKNOWN

定义：

```text
当前真实状态无法确定。
```

UNKNOWN 是正式结果，不是错误兜底字符串。

---

# 10. goal_validation

冻结结构：

```text
goal_validation[]
```

每个 Goal：

```text
GoalValidation

goal_id

goal_type

status

evidence_ids[]

missing_evidence[]

conflict_ids[]

reason_codes[]
```

---

# 11. Goal Status

冻结：

```text
COMPLETED

PARTIALLY_COMPLETED

NOT_COMPLETED

WAITING

UNKNOWN
```

---

# 12. COMPLETED

定义：

```text
Goal要求的完成条件
已经由足够证据满足。
```

---

# 13. PARTIALLY_COMPLETED

例如：

```text
搜索内容成功
但播放没有启动
```

若该 Goal 内允许定义部分完成，可使用。

---

# 14. NOT_COMPLETED

定义：

```text
存在充分证据表明目标没有完成。
```

注意：

```text
证据不足
不能判 NOT_COMPLETED
```

应判 UNKNOWN。

---

# 15. WAITING

适用于：

```text
Workflow仍在合法等待外部事件或用户输入。
```

例如：

```text
通知已发出
等待回执
```

---

# 16. business_status

冻结：

```text
BusinessStatus

status

business_code

summary_code

completed

partial
```

---

# 17. Business Status 核心枚举

冻结：

```text
SUCCESS

PARTIAL_SUCCESS

FAILED

WAITING

UNKNOWN
```

---

# 18. Business SUCCESS 与 Validation VALIDATED 区别

例如：

```text
validation_status = VALIDATED

business_status = FAILED
```

完全合法。

含义：

```text
我们非常确定业务失败了。
```

---

# 19. verified_facts

冻结为：

```text
verified_facts[]
```

结构：

```text
VerifiedFact

fact_id

fact_type

value

certainty

evidence_ids[]

source_scope

observed_at

valid_until
```

---

# 20. certainty

冻结：

```text
CONFIRMED

STRONGLY_SUPPORTED
```

只有这两类可以进入 `verified_facts`。

禁止将：

```text
LIMITED
UNKNOWN
```

混入 VerifiedFact。

---

# 21. unverified_facts

冻结：

```text
unverified_facts[]
```

结构：

```text
UnverifiedFact

fact_type

candidate_value

reason_code

missing_evidence[]

risk_if_claimed
```

---

# 22. conflicting_facts

冻结：

```text
conflicting_facts[]
```

结构：

```text
FactConflict

conflict_id

fact_type

evidence_a
value_a

evidence_b
value_b

resolution_status

selected_value
```

---

# 23. resolution_status

冻结：

```text
RESOLVED

UNRESOLVED
```

若：

```text
UNRESOLVED
```

则该事实不得进入 verified_facts。

---

# 24. claim_policy

冻结：

```text
ClaimPolicy

allowed_claims[]

forbidden_claims[]

conditional_claims[]

required_qualifiers[]

certainty_level
```

这是 M7 的强制事实边界。

---

# 25. followup

冻结：

```text
FollowupRequirement

required

type

target

reason_codes[]

urgency
```

---

# 26. Followup Type

冻结：

```text
NONE

STATUS_CHECK_REQUIRED

RETRY_REQUIRED

USER_CONFIRMATION_REQUIRED

SYSTEM_REPLAN_REQUIRED

WORKFLOW_CONTINUATION
```

---

# 27. state_recommendation

冻结：

```text
StateRecommendation

recommended_business_state

reason_codes[]

evidence_ids[]
```

注意：

```text
recommendation
!=
state mutation
```

---

# 28. validation_errors

冻结：

```text
ValidationError

error_code

target

recoverable

message

timestamp
```

---

# 29. quality

冻结：

```text
quality

schema_valid

evidence_sufficient

claim_policy_valid

conflict_free

degraded

warnings[]
```

---

# 30. ValidatedResult 禁止字段

禁止：

```text
final_response_text

new_action_plan

direct_tool_call

direct_state_update

direct_memory_write
```

---

# 31. 最小合法示例

执行：

```text
PlayTool SUCCESS
PlaybackState PLAYING
```

输出：

```text
validation_status =
VALIDATED

goal_validation:
START_PLAYBACK = COMPLETED

business_status =
SUCCESS

verified_facts:
playback_status = PLAYING

allowed_claims:
PLAYBACK_STARTED

forbidden_claims:
NONE
```

---

# 第二部分  
# M6-B Evidence + Claim Policy 冻结规范

# 32. 核心原则

正式冻结：

```text
Evidence
→ Fact
→ Claim
```

三层必须分离。

---

# 33. 第一层：Evidence

Evidence 表示：

> 系统实际观察到的原始证明材料。

例如：

```text
Tool Result
数据库状态
设备状态
第三方回执
Workflow状态
```

---

# 34. 第二层：Fact

Fact 表示：

> 根据 Evidence 可以确认的业务事实。

---

# 35. 第三层：Claim

Claim 表示：

> 在当前场景下，允许向用户表达的事实语义。

因此：

```text
Evidence
!=
Fact
!=
Claim
```

---

# 36. EvidenceModel

正式冻结：

```text
ValidationEvidence

evidence_id

source_type
source_id

field
value

observed_at

trust_level

freshness_status

scope
```

---

# 37. source_type

冻结核心集合：

```text
TOOL_RESULT

DEVICE_STATE

DATABASE_STATE

EXTERNAL_CALLBACK

WORKFLOW_STATE

SYSTEM_STATE
```

允许扩展。

---

# 38. trust_level

冻结：

```text
AUTHORITATIVE

DIRECT

SECONDARY

INFERRED
```

---

# 39. AUTHORITATIVE

表示：

```text
对于当前事实，
该来源属于正式权威状态源。
```

例如：

```text
数据库最终事务状态
外部系统正式Delivered回执
```

---

# 40. DIRECT

例如：

```text
播放器直接报告当前PLAYING
```

---

# 41. SECONDARY

例如：

```text
Skill根据多个ToolResult整理出的状态
```

可作为辅助证据。

---

# 42. INFERRED

表示：

```text
系统推测
```

不得单独用于高确定性 Claim。

---

# 43. freshness_status

冻结：

```text
FRESH

STALE

UNKNOWN
```

---

# 44. Evidence Freshness 原则

动态事实必须考虑时间。

例如：

```text
播放状态
网络状态
通知状态
```

旧 Evidence 不能无限有效。

---

# 45. Evidence Trust Priority

默认建议：

```text
AUTHORITATIVE
>
DIRECT
>
SECONDARY
>
INFERRED
```

但具体业务可以注册自己的权威源。

---

# 46. Evidence 不允许来自 Planner 预期

以下不得作为 Evidence：

```text
ActionPlan希望播放

Planner判断通知应该成功

LLM认为用户已经收到结果
```

---

# 47. Fact Formation

Fact 只有满足：

```text
ValidationRule
```

才可以生成。

不是：

```text
看到SUCCESS就自动生成事实
```

---

# 48. Tool Success Semantics 冻结

每个 ToolDefinition 必须明确：

```text
success_semantics
```

说明：

```text
ToolResult.status = SUCCESS
```

具体证明到什么程度。

---

# 49. 示例：Notification Tool

如果：

```text
SUCCESS
=
服务器接受请求
```

则只能生成：

```text
notification_request_accepted
```

不能生成：

```text
notification_delivered
```

---

# 50. ClaimPolicy 设计原则

正式固定：

```text
Verified Fact
并不自动等于
可以原样告诉用户
```

还需要经过：

```text
Claim Policy
```

---

# 51. ClaimDefinition

建议：

```text
ClaimDefinition

claim_id

required_facts[]

required_certainty

forbidden_conditions[]

required_qualifiers[]

user_facing_level
```

---

# 52. Claim Level

建议冻结为：

```text
INTERNAL_ONLY

USER_SAFE

USER_SAFE_WITH_QUALIFIER
```

---

# 53. INTERNAL_ONLY

例如：

```text
HTTP_502
retry_attempt = 2
```

系统内部需要知道。

用户不需要知道。

---

# 54. USER_SAFE

例如：

```text
播放已经开始
```

前提证据充分。

---

# 55. USER_SAFE_WITH_QUALIFIER

例如：

```text
通知请求已经提交，
但是否送达还无法确认
```

必须带不确定性限定。

---

# 56. required_qualifiers

冻结核心语义：

```text
CURRENTLY

SYSTEM_REPORTS

NOT_CONFIRMED

PARTIAL

TEMPORARY

SOURCE_LIMITED
```

M7 将它转换成自然语言。

---

# 57. Claim Ladder 冻结原则

对于具有多级状态的业务，必须定义：

```text
Claim Ladder
```

每一级有明确 Evidence Requirement。

---

# 58. Notification Claim Ladder

冻结概念层级：

```text
N1 REQUEST_CREATED

N2 REQUEST_ACCEPTED / SENT

N3 DELIVERED

N4 ACKNOWLEDGED

N5 PROCESSING
```

具体 Tool 若不支持后续级别，就不得验证后续 Claim。

---

# 59. 严格禁止跨级

如果 Evidence 只到：

```text
N2
```

则不得声称：

```text
N3
N4
N5
```

---

# 60. Help Event Claim Ladder

建议：

```text
H1 help_event_created

H2 notification_requested

H3 notification_delivered

H4 staff_acknowledged

H5 staff_processing
```

---

# 61. Playback Claim Ladder

建议：

```text
P1 content_found

P2 play_command_accepted

P3 playback_state_playing

P4 audio_output_confirmed
```

如果设备只能验证到 P3：

```text
最多声明 P3。
```

---

# 62. Reminder Claim Ladder

例如：

```text
R1 update_request_created

R2 database_update_success

R3 reminder_state_confirmed
```

---

# 63. Memory Claim Ladder

例如：

```text
M1 memory_write_requested

M2 storage_write_success

M3 memory_readback_confirmed
```

---

# 64. Weather / News 与动作类 Claim 不同

外部信息查询主要验证：

```text
来源
字段
时间
结构
```

而不是动作送达链。

---

# 65. Claim Forbidden Rules

无 Evidence 时禁止：

```text
“已经”
“确定”
“一定”
“对方已经收到”
“工作人员正在赶来”
```

对应语义 Claim。

具体自然语言由 M7 控制。

---

# 66. Safety Claim Policy

对于安全相关业务：

```text
默认采用更高 Claim Evidence 门槛。
```

特别是：

```text
求助
身体不适
高风险情绪
用药相关
```

---

# 67. Medical Boundary

Claim Policy 必须保留：

```text
不将执行结果扩展成医学诊断

不因一般信息返回自行生成用药结论
```

---

# 68. Claim Policy Registry

冻结：

```text
ClaimPolicyRegistry
```

支持：

```text
register

lookup

version

enable

disable
```

---

# 69. Evidence Registry

建议：

```text
EvidenceSourceRegistry
```

定义：

```text
source authority
freshness policy
supported facts
```

---

# 70. Evidence Rejection

M6 必须能够明确拒绝 Evidence。

原因冻结核心集合：

```text
STALE

UNTRUSTED

WRONG_SCOPE

WRONG_SESSION

WRONG_EXECUTION

SCHEMA_INVALID

CONFLICTED
```

---

# 71. 不同用户 Evidence 隔离

Evidence 必须绑定至少：

```text
session / elder / execution scope
```

禁止跨用户引用。

---

# 72. ClaimPolicy 输出是语义，不是句子

正确：

```text
allowed_claim:
NOTIFICATION_REQUEST_ACCEPTED
```

错误：

```text
allowed_claim:
“我已经帮您通知工作人员了。”
```

因为具体表达属于 M7。

---

# 第三部分  
# M6-C Goal Validation + UNKNOWN / Conflict 冻结规范

# 73. Goal Validation 核心原则

正式固定：

```text
目标完成状态
必须依据 Goal Completion Condition
+
Evidence
判断。
```

不得依据：

```text
Tool有没有报错
Planner预期
模型主观判断
```

---

# 74. GoalValidationRule

冻结结构：

```text
GoalValidationRule

rule_id

goal_type

required_evidence[]

optional_evidence[]

completion_conditions[]

partial_conditions[]

failure_conditions[]

waiting_conditions[]

unknown_conditions[]

conflict_rules[]

claim_rule_ids[]
```

---

# 75. Goal Completion

只有：

```text
completion_conditions
```

满足时才能：

```text
COMPLETED
```

---

# 76. Failure 条件

只有存在：

```text
充分反向证据
```

才能：

```text
NOT_COMPLETED
```

---

# 77. Missing Evidence 不等于 Failure

正式冻结：

```text
Missing Evidence
→ UNKNOWN / NOT_VALIDATED
```

不是：

```text
FAILED
```

---

# 78. WAITING 与 UNKNOWN 分离

## WAITING

系统知道：

```text
流程正在合法等待下一事件。
```

例如：

```text
等待callback
```

## UNKNOWN

系统不知道：

```text
当前业务到底发生到了什么状态。
```

---

# 79. TIMEOUT 与 UNKNOWN

Timeout 的解释取决于 Tool Contract。

若 Timeout 表示：

```text
请求状态未知
```

则：

```text
Goal = UNKNOWN
```

而不是：

```text
NOT_COMPLETED
```

---

# 80. Failure 与 UNKNOWN 的核心区别

```text
FAILED / NOT_COMPLETED
=
知道没有完成

UNKNOWN
=
不知道有没有完成
```

这一原则冻结。

---

# 81. UNKNOWN 触发条件

至少包括：

```text
关键Evidence缺失

外部状态无法查询

Tool Timeout且语义不明确

Evidence冲突无法解决

Tool Success语义不足

Validator关键数据缺失
```

---

# 82. UNKNOWN 禁止自动重判

M6 不允许：

```text
UNKNOWN
↓
模型猜测
↓
SUCCESS / FAILED
```

---

# 83. UNKNOWN 的后续出口

只有三种主要处理：

```text
保留UNKNOWN并如实表达

请求进一步状态检查

触发新的Runtime Replan
```

---

# 84. Conflict 核心模型

当多个 Evidence 针对同一事实出现：

```text
不同值
```

进入：

```text
Conflict Resolver
```

---

# 85. ConflictResolver 输入

```text
fact_type

evidence_set

trust_level

freshness

authority

scope
```

---

# 86. 默认冲突优先级

冻结原则：

```text
同Scope
同时间窗口下：

AUTHORITATIVE
>
DIRECT
>
SECONDARY
>
INFERRED
```

---

# 87. Freshness 可以覆盖旧权威证据

例如：

```text
数据库10分钟前显示PLAYING
```

当前设备直接状态：

```text
STOPPED
```

当前状态判断应优先：

```text
更新、更直接的状态证据
```

因此不能只按 trust_level 排序。

---

# 88. Conflict Resolution 需要同时考虑

```text
Authority

Directness

Freshness

Scope

Semantic Meaning
```

---

# 89. 可解决冲突

例如：

```text
旧状态 PLAYING
当前状态 STOPPED
```

由于时间明确不同：

```text
选择当前 STOPPED
```

并不是真正逻辑矛盾。

---

# 90. 不可解决冲突

例如同时：

```text
External Callback:
DELIVERED

Notification Database:
FAILED
```

且来源都权威、时间一致。

则：

```text
resolution_status =
UNRESOLVED
```

---

# 91. Unresolved Conflict 后果

必须：

```text
fact = UNKNOWN

validation_status = CONFLICTED
```

或：

```text
PARTIALLY_VALIDATED
```

取决于是否影响核心业务。

禁止挑一个结果“看起来更合理”。

---

# 92. Primary Goal 规则

Primary Goal 未达到：

```text
COMPLETED
```

整体 BusinessStatus 一般不得：

```text
SUCCESS
```

---

# 93. PARTIAL_SUCCESS

例如：

Primary Goal：

```text
PLAY_CONTENT
```

失败。

Secondary Goal：

```text
ACKNOWLEDGE
```

成功。

整体可：

```text
PARTIAL_SUCCESS
```

但不是 SUCCESS。

---

# 94. Workflow WAITING

如果 Primary Goal 本身是：

```text
启动HelpWorkflow
```

且 Workflow：

```text
RUNNING / WAITING
```

需要根据 Goal 定义判断。

如果 Goal 是：

```text
START_HELP_PROCESS
```

可能已经 COMPLETED。

如果 Goal 是：

```text
NOTIFY_STAFF
```

则可能仍 WAITING。

因此：

```text
Goal语义必须明确
```

---

# 95. Goal 粒度冻结原则

Goal 不能模糊定义：

```text
HANDLE_HELP
```

应尽量定义：

```text
CREATE_HELP_EVENT

REQUEST_STAFF_NOTIFICATION

WAIT_FOR_NOTIFICATION_STATUS
```

或建立父子 Goal。

否则 M6 无法准确验证。

---

# 96. Parent / Child Goal

允许：

```text
Goal
├── Child Goal A
├── Child Goal B
└── Child Goal C
```

整体状态根据：

```text
GoalValidationRule
```

聚合。

---

# 97. Goal Validation Registry

正式冻结：

```text
GoalValidationRegistry
```

所有可执行 Goal 必须注册验证规则。

---

# 98. 未注册 Goal

如果 M5 执行了新 Goal，但 M6 无规则：

```text
MISSING_VALIDATION_RULE
```

结果：

```text
NOT_VALIDATED / UNKNOWN
```

不得自动按 ToolStatus 推导。

---

# 99. Tool Interpreter 缺失

同理：

```text
MISSING_TOOL_INTERPRETER
```

对应 Tool 的输出不得直接升级为 VerifiedFact。

---

# 100. Validation Mode

冻结：

```text
FAST

STANDARD

STRICT
```

---

# 101. FAST

适用于：

```text
低风险
本地
结果直接
```

例如：

```text
本地音量状态
```

---

# 102. STANDARD

适用于：

```text
普通播放
天气
新闻
普通提醒
```

---

# 103. STRICT

适用于：

```text
求助

高风险身体不适

高风险情绪

关键通知

敏感Memory状态
```

---

# 104. Validation Mode 来源

主要来自：

```text
Policy / Goal Definition
```

M6 不自行把某业务降级为 FAST。

---

# 105. UNKNOWN / Conflict 的 Claim 规则

当：

```text
Goal = UNKNOWN
```

则禁止：

```text
SUCCESS_CLAIM
FAILURE_CLAIM
```

除非某个子事实可以独立确认。

---

# 106. 示例：通知 Timeout

已知：

```text
notification_request_created = true
```

未知：

```text
notification_delivered
```

则允许：

```text
请求已经创建
```

禁止：

```text
已送达
送达失败
```

---

# 107. 示例：部分验证

```text
HelpEvent created = CONFIRMED

Notification delivered = UNKNOWN
```

则：

```text
validation_status =
PARTIALLY_VALIDATED
```

而不是全部 UNKNOWN。

---

# 108. M6 错误状态与 Business Status 分离

例如：

```text
ValidationError:
STALE_EVIDENCE
```

不必意味着：

```text
Business FAILED
```

可能只是：

```text
UNKNOWN
```

---

# 109. Validation Error 核心集合冻结

```text
INVALID_EXECUTION_RESULT

MISSING_EVIDENCE

STALE_EVIDENCE

CONFLICTING_EVIDENCE

MISSING_TOOL_INTERPRETER

MISSING_VALIDATION_RULE

UNSUPPORTED_CLAIM

CLAIM_POLICY_VIOLATION

VALIDATION_TIMEOUT

VALIDATION_INTERNAL_ERROR
```

---

# 第四部分  
# 三项冻结设计的运行关系

# 110. 正式运行链

冻结为：

```text
ExecutionResult
        ↓
Schema Check
        ↓
Evidence Collection
        ↓
Evidence Trust / Freshness
        ↓
Tool Result Interpretation
        ↓
Goal Validation
        ↓
Conflict Resolution
        ↓
Fact Classification
        ↓
Business Status
        ↓
Claim Policy
        ↓
Followup Requirement
        ↓
ValidatedResult
```

---

# 111. Validation 顺序不能颠倒

尤其不能：

```text
Tool SUCCESS
↓
先生成用户Claim
↓
再找Evidence
```

必须：

```text
Evidence first
```

---

# 112. M5 → M6 正式接口冻结

M6 接收：

```text
ExecutionResult
ActionPlan
Policy Snapshot
必要 Runtime Evidence
```

不得直接让 LLM：

```text
根据用户原话猜执行是否成功。
```

---

# 113. M6 → M7 正式接口冻结

M7 只需要重点读取：

```text
business_status

verified_facts

allowed_claims

forbidden_claims

required_qualifiers

followup
```

M7 不需要重新解析：

```text
ToolResult
HTTP Code
外部API原始结构
```

---

# 114. M6 → M8 正式接口冻结

M8 使用：

```text
GoalValidation
VerifiedFacts
StateRecommendation
```

进行状态更新。

不得直接用：

```text
Tool SUCCESS
```

更新全局 State。

---

# 115. Frozen Core 总结

从 V1.0 开始，以下正式视为 M6 Frozen Core：

```text
ValidatedResult 主结构

ValidationStatus 五类

GoalStatus 五类

BusinessStatus 五类

Verified / Unverified / Conflict 三类Fact

Evidence模型

Trust Level

Freshness

Tool Success Semantics

GoalValidationRegistry

ClaimPolicy

Claim Ladder

Allowed / Forbidden Claim

UNKNOWN正式状态

WAITING与UNKNOWN分离

Missing Evidence != Failure

Tool Success != Business Success

Conflict Resolver

Evidence-first原则
```

---

# 116. 允许扩展内容

后续可以增加：

```text
Goal Validation Rule

Tool Interpreter

Evidence Source

ClaimDefinition

Claim Ladder

Fact Type

Validation Error

Validation Mode配置
```

但必须：

```text
Registry注册

向后兼容

增加Eval Case
```

---

# 117. 不允许破坏的边界

禁止后续变成：

```text
Tool SUCCESS
→ 直接告诉用户成功

Timeout
→ 默认失败

没有Evidence
→ LLM猜一个结果

出现冲突
→ 随机取一个

Planner预期
→ 当成事实

M6自己重试Tool

M7自行绕过forbidden_claims
```

---

# 第五部分  
# 三项冻结 Gate

# 118. Gate M6-F01

`ValidatedResult` 主结构稳定。

---

# 119. Gate M6-F02

正式支持：

```text
UNKNOWN
```

---

# 120. Gate M6-F03

正式支持：

```text
WAITING
```

且与 UNKNOWN 分离。

---

# 121. Gate M6-F04

每个 VerifiedFact 都存在 Evidence。

---

# 122. Gate M6-F05

Evidence 具备：

```text
source
trust
freshness
scope
```

---

# 123. Gate M6-F06

每个 Tool 明确：

```text
success_semantics
```

---

# 124. Gate M6-F07

Tool SUCCESS 不自动生成 Business SUCCESS。

---

# 125. Gate M6-F08

所有执行 Goal 都必须有 ValidationRule。

---

# 126. Gate M6-F09

未注册 Goal 默认：

```text
NOT_VALIDATED / UNKNOWN
```

---

# 127. Gate M6-F10

Missing Evidence 不得判失败。

---

# 128. Gate M6-F11

Unresolved Conflict 不得进入 VerifiedFact。

---

# 129. Gate M6-F12

ClaimPolicy 至少支持：

```text
allowed
forbidden
conditional
qualifier
```

---

# 130. Gate M6-F13

安全相关 Claim 不得超过真实 Evidence 等级。

---

# 131. Gate M6-F14

M7 不需要重新解释 ToolResult。

---

# 132. Gate M6-F15

M8 不直接使用未经验证的 ToolResult 修改状态。

---

# 133. Gate M6-F16

UNKNOWN 案例具有自动化回归测试。

---

# 134. Gate M6-F17

Conflict 案例具有自动化回归测试。

---

# 135. Gate M6-F18

False Success 具有独立测试指标。

---

# 第六部分  
# 冻结后的系统状态

完成这三项冻结以后，系统的数据主链已经稳定为：

```text
M3
UnderstandingState
        ↓
M4
Approved ActionPlan
        ↓
M5
ExecutionResult
        ↓
M6
ValidatedResult
```

这四个核心数据对象分别代表：

```text
UnderstandingState
=
系统如何理解用户

ActionPlan
=
系统决定做什么

ExecutionResult
=
系统实际做了什么

ValidatedResult
=
系统真正知道发生了什么
```

---

# 136. 四层真值边界

现在可以正式建立：

```text
User Meaning
!=
Agent Decision
!=
Execution Result
!=
Verified Reality
```

进一步：

```text
Verified Reality
!=
Final Natural Language
```

因为还需要 M7。

---

# 137. M6 冻结后的核心原则

整个 M6 最终可以压缩成四条不可改变的规则：

```text
一、没有证据，不生成事实。

二、缺少证据，不等于失败。

三、证据冲突，不假装确定。

四、系统只能声明自己真正验证过的内容。
```

---

# 138. 与 M7 的正式交接

M6 冻结后，M7 不再承担：

```text
事实判断
Tool结果解释
业务成功判断
```

M7 接下来只需要解决：

```text
如何把：

ActionPlan中的沟通目标

+
ValidatedResult中的可信事实

+
UnderstandingState中的用户状态

+
RuntimeContext中的交互背景

转成：

自然、适老、简短、
有陪伴感但不夸大事实的回复。
```

因此下一阶段可以正式固定为：

```text
M7
Response Planning & Generation

=
不重新判断真相，
只负责把真相说好。
```

至此，M6 Core Design 正式冻结。