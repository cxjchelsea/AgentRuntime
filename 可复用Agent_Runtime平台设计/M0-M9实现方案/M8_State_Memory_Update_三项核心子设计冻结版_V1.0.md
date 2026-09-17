# 可复用 Agent Runtime 平台
# M8 State & Memory Update 三项核心子设计冻结版 V1.0

> **Phase 0 Fix**  
> 主链终点为 `UpdateResult`。隔离键为 `identity_scope`，禁止 `elder_id`。  
> 文中单独出现的 `ActionPlan` 指上游 `ApprovedActionPlan`。


> **平台化转换说明**  
> 本文已从单一业务 Agent 设计转换为 **可复用 Agent Runtime 平台**设计。除明确标记为 `Core` 的对象、接口、不变量和生命周期外，任何具体业务 Intent、Entity、Workflow、Skill、Tool、知识域、状态字段、规则、提示词或示例均视为 **Domain Package 示例**，不得硬编码进 Runtime Core。新项目应通过 Registry / Adapter / Plugin / Config 注入领域差异。
> 
> 平台固定边界：`Runtime Core` 尽量稳定；`Domain Extension` 插件化；`Business Package` 配置化；`Application` 负责产品装配。

---

# 0. 冻结说明

本文件正式冻结 M8 的三项核心设计：

```text
M8-A UpdateResult + State / Task / Conversation Update Schema

M8-B MemoryRecord + Memory Lifecycle

M8-C Memory Write / Conflict / Temporary Override Rules
```

冻结后的正式链路：

```text
UnderstandingState
+
Approved ActionPlan
+
ExecutionResult
+
ValidatedResult
+
RuntimeResponse
        ↓
M8 State & Memory Update
        ↓
UpdateResult
        ↓
下一轮 M1 RuntimeContext
```

M8 的职责固定为：

```text
把这一轮真正发生过的事情，
沉淀成下一轮真正可用的状态。
```

其中必须保持：

```text
计划发生的
!=
实际发生的
!=
已验证的
!=
应该长期记住的
```

---

# 第一部分
# M8-A UpdateResult + State / Task / Conversation Update Schema 冻结规范

## 1. UpdateResult 定位

`UpdateResult` 是 M8 唯一正式输出。

它表示：

```text
这一轮结束后，
哪些 Runtime State 已更新，
哪些 Task 已推进，
哪些 Conversation Context 已变化，
哪些 Interaction / Session 信息已更新，
哪些 Memory 已写入、更新、忽略或失效，
以及这些 Commit 是否成功。
```

它不是：

```text
新的用户理解
新的 ActionPlan
新的 Tool Result
新的自然语言回复
```

---

## 2. UpdateResult Frozen Core

正式冻结：

```text
UpdateResult

metadata

state_update

task_update

conversation_update

interaction_update

session_update

event_update

memory_update

commit_result

quality
```

后续允许在各子对象内部扩展字段，但不得删除这些核心区域。

---

## 3. metadata

冻结：

```text
metadata

update_id

request_id
session_id
turn_id

schema_version
updater_version
policy_version

created_at
```

---

## 4. StateUpdate

正式冻结：

```text
StateUpdate

previous_state

proposed_state

committed_state

transition_event

transition_reason_codes[]

transition_status

evidence_ids[]
```

---

## 5. transition_status

冻结：

```text
NOT_REQUIRED

PROPOSED

COMMITTED

REJECTED

DEFERRED
```

---

## 6. State 更新硬边界

正式冻结：

```text
M8 不直接绕过 State Engine 改状态。
```

必须：

```text
State Recommendation
→ StateEngine.validate_transition()
→ StateEngine.commit_transition()
```

---

## 7. State Truth Source

State 更新优先依据：

```text
ValidatedResult
+
Workflow Truth
+
State Policy
```

而不是：

```text
ActionPlan Expected Result
ToolResult SUCCESS
LLM 推断
```

---

## 8. State Priority

建议固定：

```text
Validated Reality / Workflow Truth
>
State Transition Policy
>
ActionPlan state_intent
```

---

## 9. UNKNOWN 不得提交成功状态

如果 M6：

```text
business_status = UNKNOWN
```

则 M8 不得：

```text
commit target success state
```

例如：

```text
playback UNKNOWN
≠
S06 播放中
```

---

## 10. Resume Policy

M8 必须遵守：

```text
resume_policy
```

不能自行恢复旧业务。

已确定：

```text
播放被求助中断
→ 求助结束后
不自动恢复播放
```

此类规则属于 Frozen Boundary。

---

## 11. TaskUpdate

正式冻结：

```text
TaskUpdate

task_id

task_type

previous_stage

next_stage

status

field_updates[]

pending_field

timeout_update

completion_reason
```

---

## 12. TaskStatus

冻结：

```text
ACTIVE

WAITING_USER

WAITING_EXTERNAL

COMPLETED

CANCELLED

FAILED

EXPIRED
```

---

## 13. TaskFieldUpdate

冻结：

```text
TaskFieldUpdate

field_name

old_value

new_value

source

confidence

confirmation_status
```

---

## 14. confirmation_status

冻结：

```text
CONFIRMED

UNCONFIRMED

REJECTED

SUPERSEDED
```

---

## 15. Task 字段提交原则

确定性 Workflow 的关键字段默认只使用：

```text
CONFIRMED
```

不能因为：

```text
M3 推断了一个低置信度值
```

就直接推进关键流程。

---

## 16. Pending Field

如果 RuntimeResponse 实际提出了某个 Task Question：

```text
task.pending_field
```

必须更新。

如果最终回复没有问出原计划问题：

```text
不得建立 pending_field
```

---

## 17. ConversationUpdate

正式冻结：

```text
ConversationUpdate

new_turn

current_topic

topic_history_updates[]

pending_question

pending_reference

recent_entities[]

conversation_stage

rolling_summary_update
```

---

## 18. ConversationTurn

冻结：

```text
ConversationTurn

turn_id

user_input

assistant_response

topic

intent_summary

emotion_summary

actions_taken[]

claims_used[]

question_metadata

timestamp
```

---

## 19. Conversation Truth Principle

Conversation History 记录：

```text
实际用户输入
+
实际 RuntimeResponse
```

而不是：

```text
ActionPlan 预期回复
ResponsePlan 草稿
```

---

## 20. PendingQuestion

正式冻结：

```text
PendingQuestion

question_id

question_type

target

asked_at

required

expires_at

source_task_id

status
```

---

## 21. PendingQuestionStatus

冻结：

```text
ACTIVE

ANSWERED

CANCELLED

EXPIRED

SUPERSEDED
```

---

## 22. PendingQuestion 来源

正式固定：

```text
RuntimeResponse.question
```

是唯一主要来源。

如果 M4 原计划提问，但 M7 最终没问：

```text
不得创建 PendingQuestion
```

---

## 23. PendingReference

建议冻结为：

```text
PendingReference

reference_id

reference_type

target

source_turn_id

salience

expires_at
```

用于下一轮：

```text
“她”
“那个”
“刚才那个”
```

等指代解析。

---

## 24. Topic Lifecycle

正式冻结：

```text
current_topic

topic_history
```

新 Topic 进入 current_topic 时：

```text
旧 topic
→ topic_history
```

---

## 25. Topic 不是 Long-Term Memory

例如：

```text
本轮正在聊女儿
```

默认只属于：

```text
Conversation / Session Context
```

不能直接进入长期 Memory。

---

## 26. InteractionUpdate

正式冻结：

```text
InteractionUpdate

last_agent_action

recent_agent_actions[]

recent_questions[]

recent_suggestions[]

recent_rejections[]

active_interaction_count

last_active_interaction_at

quiet_until

engagement_updates[]
```

---

## 27. InteractionUpdate 的作用

主要供下一轮 M4 判断：

```text
是不是已经问太多？

是不是刚建议过？

是不是刚被拒绝？

现在应不应该继续主动？

用户是不是要求安静？
```

---

## 28. Rejection 粒度

正式冻结：

```text
一次拒绝
!=
长期偏好
```

一次：

```text
“不用了”
```

只应首先记录为：

```text
recent_rejection
```

除非用户明确表达长期规则或形成重复稳定模式。

---

## 29. Quiet Until

如果进入安静陪伴：

```text
quiet_until
```

必须实际写入 Interaction Context。

下一轮 M1/M2/M4 可读取。

---

## 30. Active Interaction Count

只有：

```text
主动交互实际输出给用户
```

才计数。

以下都不得计数：

```text
M4 想主动但被 M2 阻止
M7 最终未输出
主动 Plan 被高优先级事件抢占
```

---

## 31. SessionUpdate

冻结：

```text
SessionUpdate

last_active_at

turn_index

current_topic

session_summary

session_status

session_end_reason
```

---

## 32. Session Summary

正式采用：

```text
Rolling Summary
```

而不是无限追加全部历史。

应保留：

```text
当前话题
重要近期事实
Active Task
未解决问题
近期拒绝 / 临时偏好
重要人物引用
```

---

## 33. Summary Trust

Session Summary 只能视为：

```text
SECONDARY CONTEXT
```

不能覆盖：

```text
当前用户明确表达
真实 System State
已确认 Task Fact
```

---

## 34. EventUpdate

冻结：

```text
EventUpdate

event_id

event_type

previous_status

new_status

reason_codes[]

evidence_ids[]
```

---

## 35. Event Truth Principle

Event 状态只能依据：

```text
ValidatedResult
```

例如：

```text
notification delivery UNKNOWN
```

不能写：

```text
event = staff_notified_confirmed
```

---

## 36. CommitResult

正式冻结：

```text
CommitResult

state_commit

task_commit

conversation_commit

interaction_commit

session_commit

event_commit

memory_commit

overall_status

errors[]
```

---

## 37. overall_status

冻结：

```text
SUCCESS

PARTIAL_SUCCESS

FAILED
```

---

## 38. Commit 分层

正式冻结三层：

```text
Critical Runtime Commit

Conversation Commit

Memory Commit
```

---

## 39. Critical Runtime Commit

包括：

```text
Runtime State

Active Task

Safety / Workflow critical state

Pending Question

Critical Event status
```

这部分优先保证一致性。

---

## 40. Conversation Commit

包括：

```text
Conversation Turn

Topic

Interaction Metadata

Session Summary
```

---

## 41. Memory Commit

允许独立失败。

例如：

```text
State / Task / Conversation 成功
Memory Write 失败
```

整体：

```text
PARTIAL_SUCCESS
```

不得因此回滚已经真实完成的关键安全业务。

---

## 42. Commit Idempotency

每次 M8 更新必须有：

```text
update_id
```

并支持：

```text
request_id + update_type
```

级别的幂等。

---

## 43. Conversation Idempotency

同一个：

```text
turn_id
```

不能重复写入。

---

## 44. UpdateResult 禁止包含

```text
新的用户理解

新的业务计划

新的 Tool 调用

新的最终回复
```

---

# 第二部分
# M8-B MemoryRecord + Memory Lifecycle 冻结规范

## 45. Memory Architecture

正式冻结四层：

```text
Turn Context

Session Context

Recent Context

Long-Term Memory
```

---

## 46. Turn Context

生命周期：

```text
当前 Turn
```

适合：

```text
临时模型推断
当前候选解释
一次性中间结构
```

默认不长期持久化。

---

## 47. Session Context

生命周期：

```text
当前会话
```

适合：

```text
当前 Topic

当前 Interaction Preference

当前情绪背景

当前临时目标
```

---

## 48. Recent Context

生命周期：

```text
数小时 ～ 数天
```

适合：

```text
近期事件

临时偏好

近期人物动态

短期情绪背景

最近拒绝
```

必须支持 TTL。

---

## 49. Long-Term Memory

只保存：

```text
稳定

重要

未来持续有价值

具有足够证据
```

的信息。

---

## 50. MemoryRecord Frozen Core

正式冻结：

```text
MemoryRecord

memory_id

user_scope

memory_type

content

structured_value

source

created_at
updated_at
last_confirmed_at

confidence

importance

status

scope

expires_at

last_used_at

usage_count

sensitivity

evidence_refs[]
```

---

## 51. user_scope

必须明确绑定：

```text
subject_id / identity_scope
```

这是强制字段。

禁止：

```text
没有 user_scope 的个人长期 Memory
```

---

## 52. MemoryType 核心集合

冻结：

```text
PREFERENCE

AVOIDANCE_PREFERENCE

RELATIONSHIP

PERSONAL_FACT

ROUTINE

IMPORTANT_EVENT

INTERACTION_PREFERENCE

LONG_TERM_INTEREST
```

允许扩展。

---

## 53. MemoryStatus

正式冻结：

```text
STABLE

TEMPORARY

EMERGING

UNCERTAIN

DEPRECATED
```

---

## 54. STABLE

表示：

```text
长期有效性较高，
证据充分，
可以参与稳定个性化。
```

---

## 55. TEMPORARY

表示：

```text
明确但只在一定时间范围内有效。
```

必须优先考虑：

```text
expires_at
```

---

## 56. EMERGING

表示：

```text
已经出现一定稳定趋势，
但仍不足以认定为长期稳定事实。
```

---

## 57. UNCERTAIN

表示：

```text
证据有限、
来源不确定、
解释存在歧义。
```

默认不得用于高影响个性化。

---

## 58. DEPRECATED

表示：

```text
旧 Memory 已明确失效、
被修正或不再适用。
```

---

## 59. status ≠ physical deletion

正式冻结：

```text
Memory失效
优先使用 DEPRECATED
而不是直接物理删除。
```

原因：

```text
审计
变化追踪
错误恢复
```

用户明确要求删除的数据另按隐私流程处理。

---

## 60. scope

建议冻结：

```text
SESSION

RECENT

LONG_TERM
```

Turn Context 通常不进入正式 Memory Store。

---

## 61. Memory Source

至少区分：

```text
USER_EXPLICIT

USER_CONFIRMED

REPEATED_BEHAVIOR

TASK_CONFIRMED

SYSTEM_OBSERVED

MODEL_INFERRED
```

---

## 62. Source Priority

正式建议：

```text
USER_EXPLICIT / USER_CONFIRMED
>
TASK_CONFIRMED
>
REPEATED_BEHAVIOR
>
SYSTEM_OBSERVED
>
MODEL_INFERRED
```

---

## 63. MODEL_INFERRED 默认限制

正式冻结：

```text
MODEL_INFERRED
不得直接创建 STABLE Long-Term Memory。
```

---

## 64. Memory Confidence

允许记录 confidence。

但：

```text
confidence
不能单独决定 Memory Status。
```

仍需考虑：

```text
source
stability
explicitness
conflict
scope
```

---

## 65. importance

用于：

```text
检索排序
Retention
Context选择
```

不是 Truth 指标。

---

## 66. sensitivity

建议：

```text
LOW

MEDIUM

HIGH
```

用于限制：

```text
检索
显式提及
长期保存
```

---

## 67. expires_at

必须支持：

```text
TEMPORARY
RECENT
```

类型 Memory 的过期。

---

## 68. last_confirmed_at

正式保留。

用于判断：

```text
多久没有重新确认
```

为未来：

```text
Memory Decay
Preference Drift
```

提供基础。

---

## 69. last_used_at / usage_count

只有 Memory：

```text
真正被 Planner / Response 使用
```

才更新。

仅检索出来：

```text
不得算使用。
```

---

## 70. Memory Lifecycle

正式冻结：

```text
Candidate
↓
UNCERTAIN / TEMPORARY / EMERGING
↓
STABLE

或

任一有效状态
↓
DEPRECATED
```

---

## 71. Promotion

允许：

```text
UNCERTAIN
→ EMERGING

EMERGING
→ STABLE
```

---

## 72. Promotion Signals

至少包括：

```text
explicit confirmation

repeated consistent statements

repeated consistent behavior

confirmed stable relationship fact
```

---

## 73. Promotion 不是 LLM 自由决定

正式冻结：

```text
Memory Status Promotion
必须由 Lifecycle Rule 决定。
```

---

## 74. 第一版 Promotion Policy

建议：

```text
显式长期表达
或
多次高一致性证据
```

才进入 STABLE。

---

## 75. Memory Decay

允许未来根据：

```text
last_confirmed_at

age

usage

conflict history
```

降低 Memory 当前有效性。

但第一版可以只实现：

```text
TTL + Explicit Deprecation
```

---

## 76. Recent Context Expiry

到：

```text
expires_at
```

后默认：

```text
从当前有效检索范围移出
```

可保留历史记录。

---

## 77. Long-Term Memory 也可以失效

正式冻结：

```text
Long-Term
!=
Forever Valid
```

必须支持：

```text
update
deprecation
replacement
```

---

## 78. 不允许默认长期保存的内容

正式禁止：

```text
长期心理标签

人格推断

“用户很孤独”

“用户依赖机器人”

未经确认的疾病判断

未经确认的家庭关系解释
```

---

## 79. 情绪的默认层级

情绪信息默认：

```text
Turn / Session / Recent
```

不自动：

```text
Long-Term
```

---

## 80. 关系 Memory

例如用户明确：

```text
“我女儿叫小敏。”
```

可以形成：

```text
RELATIONSHIP
```

但必须保留：

```text
source
evidence
user_scope
```

---

# 第三部分
# M8-C Memory Write / Conflict / Temporary Override 冻结规范

## 81. 核心原则

正式冻结：

```text
Memory Candidate
!=
Memory Write
```

任何候选必须先经过：

```text
Memory Write Decision
```

---

## 82. MemoryWriteDecision Frozen Core

```text
MemoryWriteDecision

candidate_id

decision

target_scope

memory_type

initial_status

reason_codes[]

merge_target

conflict_action
```

---

## 83. decision

冻结：

```text
WRITE

UPDATE_EXISTING

MERGE

KEEP_RECENT_ONLY

IGNORE

DEPRECATE_EXISTING
```

---

## 84. Memory Write 判断因子

必须至少考虑：

```text
explicitness

source

stability

future_value

confidence

sensitivity

duplication

conflict

scope

user_correction
```

---

## 85. 写入优先原则

建议固定：

```text
用户明确表达
>
用户确认
>
重复稳定模式
>
一次行为
>
模型推断
```

---

## 86. 单次行为规则

正式冻结：

```text
一次行为
不得自动形成 STABLE Preference。
```

例如：

```text
一次选择越剧
```

最多：

```text
Recent Context
或
EMERGING Candidate
```

---

## 87. 单次拒绝规则

正式冻结：

```text
一次拒绝
不得自动形成长期 Avoidance Preference。
```

例如：

```text
“今天不想听京剧。”
```

应优先：

```text
TEMPORARY / RECENT override
```

---

## 88. 明确长期表达

例如：

```text
“以后别给我放京剧了。”
```

可以进入：

```text
Long-Term Memory Write Decision
```

但仍需经过冲突处理。

---

## 89. Memory Conflict Types

正式冻结：

```text
DIRECT_CONTRADICTION

TEMPORARY_OVERRIDE

PREFERENCE_DRIFT

VALUE_UPDATE

DUPLICATE

AMBIGUOUS_CONFLICT
```

---

## 90. DIRECT_CONTRADICTION

例如：

旧：

```text
daughter_name = 小玲
```

新：

```text
“不是小玲，是小敏。”
```

且属于明确修正。

规则：

```text
旧值 → DEPRECATED

新值 → 根据来源进入适当状态
```

---

## 91. TEMPORARY_OVERRIDE

旧：

```text
STABLE:
喜欢京剧
```

新：

```text
“这几天不想听京剧。”
```

正式规则：

```text
旧 STABLE 保留

新增 TEMPORARY:
avoid_beijing_opera

当前检索中 Temporary Override 优先
```

---

## 92. Temporary Override 不等于 Preference Drift

短期：

```text
“这几天不想……”
```

只形成：

```text
TEMPORARY_OVERRIDE
```

长期连续变化才进入：

```text
PREFERENCE_DRIFT
```

---

## 93. PREFERENCE_DRIFT

例如：

```text
旧长期偏好 = 京剧

数周持续明确选择其他类型
并多次明确表示不再喜欢京剧
```

允许：

```text
旧 STABLE
→ confidence下降 / DEPRECATED

新 Emerging
→ STABLE
```

---

## 94. VALUE_UPDATE

适用于可变化的事实。

例如：

```text
常用称呼
生活习惯
某些联系方式
```

新明确值替代旧值。

---

## 95. DUPLICATE

同内容重复出现：

```text
不创建新Memory
```

而可以：

```text
更新 confirmation

更新 last_confirmed_at

增加 evidence
```

---

## 96. AMBIGUOUS_CONFLICT

如果无法判断：

```text
用户是在暂时变化
还是长期变化
```

规则：

```text
不得直接覆盖 STABLE Memory
```

可以：

```text
新候选 = UNCERTAIN / RECENT
```

---

## 97. Conflict Priority

正式冻结：

```text
Current Explicit Correction
>
Current Explicit Temporary Preference
>
Recent Confirmed Pattern
>
Stable Long-Term Memory
>
Old Historical Memory
>
Model Inference
```

---

## 98. Current Explicit Correction

优先级最高。

例如：

```text
“我刚才说错了。”
```

应立刻影响当前有效 Context。

---

## 99. 但修正的影响范围需要匹配

例如：

```text
“今天不是小玲来，是小敏来。”
```

不能自动推断：

```text
daughter_name changed
```

必须区分：

```text
事件角色
vs
长期关系事实
```

---

## 100. Write Scope Decision

正式规则：

```text
Session only
Recent only
Long-term
```

必须显式选择。

不能默认全部 Long-Term。

---

## 101. KEEP_RECENT_ONLY

这是重要 Decision。

适用于：

```text
近期重要
但长期价值不足
```

例如：

```text
“女儿明天来看我。”
```

应：

```text
KEEP_RECENT_ONLY
+
expires_at
```

---

## 102. IGNORE

适用于：

```text
无长期价值

低置信度推断

重复噪声

不必要敏感信息

无明确 user scope
```

---

## 103. Long-Term Write Precision Principle

正式冻结：

```text
Memory Write Precision
>
Memory Write Recall
```

即：

```text
宁可暂时没记住，
不要长期记错。
```

---

## 104. 推断性 Memory

如果 M3：

```text
possible loneliness
```

M8 默认：

```text
IGNORE for Long-Term
```

可以留：

```text
Session / Recent emotional context
```

---

## 105. Interaction Preference

例如用户多次表示：

```text
“不喜欢机器人总问问题。”
```

可以形成：

```text
INTERACTION_PREFERENCE
```

但最好经过：

```text
明确表达
或
重复稳定证据
```

---

## 106. Memory Explicit Correction

用户可以修正 Memory。

必须支持：

```text
old memory
→ DEPRECATED

new memory
→ create/update
```

并保留：

```text
evidence trail
```

---

## 107. Memory Usage Reaction

如果 M7 显式引用某 Memory 后用户说：

```text
“别老提这个。”
```

应更新：

```text
Interaction Preference
```

而不是自动删除事实 Memory。

例如：

```text
事实仍然是真的
但 explicit_reference preference = negative
```

---

## 108. Wrong-user Hard Rule

任何：

```text
candidate.user_scope
!=
current user scope
```

必须：

```text
REJECT / ERROR
```

不能自动修复到当前用户。

---

## 109. Unbound Mode

如果：

```text
identity_status = UNBOUND
```

默认：

```text
不写个人 Long-Term Memory
```

除非未来有明确产品规则。

---

## 110. Sensitive Memory

高 sensitivity 内容：

```text
默认提高写入门槛
```

第一版建议：

```text
只有显式、必要、受允许
```

才写入。

---

## 111. Memory Conflict Resolver 输出

建议：

```text
MemoryConflictResolution

conflict_type

existing_memory_id

candidate_id

selected_current_value

existing_status_update

candidate_status

temporary_override

reason_codes[]
```

---

## 112. Temporary Override Schema

建议冻结：

```text
TemporaryOverride

override_id

target_memory_id

override_value

source

created_at

expires_at

priority

status
```

---

## 113. Temporary OverrideStatus

冻结：

```text
ACTIVE

EXPIRED

CANCELLED

SUPERSEDED
```

---

## 114. Temporary Override Retrieval Rule

M1 检索当前有效 Memory 时：

```text
ACTIVE Temporary Override
>
Stable Long-Term Memory
```

但长期 Memory 本体仍然存在。

---

## 115. Temporary Override 到期

到期后：

```text
Override = EXPIRED
```

原 STABLE Memory 可重新成为当前默认。

除非期间发生：

```text
Preference Drift
```

---

## 116. Memory Write Idempotency

同一个：

```text
candidate_id
```

重复处理不能生成两个 MemoryRecord。

---

## 117. Merge 规则

若 candidate 与现有 Memory 本质相同：

```text
MERGE
```

而不是新增。

可更新：

```text
evidence_refs

last_confirmed_at

confidence

updated_at
```

---

## 118. Memory Deprecation Rule

DEPRECATED 后：

```text
默认不参与当前个性化
```

但可用于：

```text
历史变化审计
```

---

## 119. Memory Delete 与 Deprecation 分离

正式冻结：

```text
DEPRECATED
!=
DELETED
```

业务失效使用：

```text
DEPRECATED
```

隐私删除属于独立数据治理流程。

---

# 第四部分
# 三项冻结设计之间的关系

## 120. 正式关系

```text
ValidatedResult
+
RuntimeResponse
        ↓
Update Schema
        ↓
State / Task / Conversation Update
        ↓
Memory Candidate Processing
        ↓
Memory Write / Conflict / Override Rules
        ↓
Memory Lifecycle
        ↓
Commit
        ↓
UpdateResult
        ↓
下一轮 M1 RuntimeContext
```

---

## 121. Runtime Truth 与 Memory Truth 分离

正式冻结：

```text
当前 Runtime Fact
!=
Long-Term Memory
```

例如：

```text
今天不想听京剧
```

可以是真实的当前事实，

但不是：

```text
长期不喜欢京剧
```

---

## 122. Context 与 Memory 分离

正式冻结：

```text
Context
用于当前/近期理解

Memory
用于跨会话稳定连续性
```

不是所有 Context 都应该升级为 Memory。

---

## 123. Update 优先级

建议：

```text
Critical Runtime Truth
>
Task Continuity
>
Conversation Continuity
>
Interaction Continuity
>
Long-Term Memory
```

因此 Memory 写失败不能破坏关键安全状态。

---

## 124. M8→M1 闭环

下一轮 M1 读取：

```text
State Store

Task Store

Conversation Store

Interaction Store

Recent Context

Memory Store
```

从而重新构建：

```text
RuntimeContext_t+1
```

---

# 第五部分
# Frozen Core 总结

从 V1.0 开始，以下正式冻结：

```text
UpdateResult 主结构

StateUpdate

TaskUpdate

ConversationUpdate

InteractionUpdate

SessionUpdate

EventUpdate

CommitResult

PendingQuestion

PendingReference

Task Confirmed / Unconfirmed 区分

Turn / Session / Recent / Long-Term 四层结构

MemoryRecord 主结构

MemoryType 核心集合

MemoryStatus 五类

user_scope 强制绑定

expires_at

last_confirmed_at

Memory Candidate != Memory Write

MemoryWriteDecision

Temporary Override

Preference Drift

Explicit Correction Priority

Memory Conflict Priority

Long-Term Precision > Recall

State 依据 ValidatedResult 更新

RuntimeResponse 决定实际 Conversation Update

Critical Runtime Commit 与 Memory Commit 分层

Update Idempotency
```

---

# 第六部分
# 允许扩展内容

未来允许新增：

```text
MemoryType

Memory Lifecycle Rule

Conflict Type

Interaction State字段

Task Type

Event Type

Summary字段

Memory Ranking策略

Memory Decay策略
```

但必须：

```text
向后兼容

保持 user scope

遵守 Truth Boundary

新增 Eval Case
```

---

# 第七部分
# 不允许破坏的边界

以后禁止出现：

```text
ToolResult SUCCESS
→ 直接修改 Runtime State

ActionPlan 中计划提问
→ 即使最终没问也创建 PendingQuestion

一次拒绝
→ 长期不喜欢

一次选择
→ 稳定兴趣

模型推断孤独
→ 长期“用户孤独”

Current Temporary Preference
→ 直接删除旧 Stable Memory

Memory Candidate
→ 不经规则直接永久保存

Memory写失败
→ 重放关键安全Tool

不同用户的Memory混用

Summary覆盖明确用户事实

LLM自行释放Safety Lock
```

---

# 第八部分
# 冻结 Gate

## Gate M8-F01

UpdateResult 主结构固定。

## Gate M8-F02

StateUpdate 必须经过 State Engine。

## Gate M8-F03

M6 UNKNOWN 不得提交成功业务 State。

## Gate M8-F04

Task Field 区分 CONFIRMED / UNCONFIRMED。

## Gate M8-F05

PendingQuestion 只来自实际 RuntimeResponse。

## Gate M8-F06

Conversation History 保存实际输出而不是计划输出。

## Gate M8-F07

Turn / Session / Recent / Long-Term 四层边界存在。

## Gate M8-F08

MemoryRecord 必须具有 user_scope。

## Gate M8-F09

Memory Status 支持：

```text
STABLE
TEMPORARY
EMERGING
UNCERTAIN
DEPRECATED
```

## Gate M8-F10

MODEL_INFERRED 不得直接创建 STABLE Long-Term Memory。

## Gate M8-F11

单次行为不得自动成为稳定偏好。

## Gate M8-F12

单次拒绝不得自动成为长期 Avoidance Preference。

## Gate M8-F13

明确用户修正优先于旧 Memory。

## Gate M8-F14

Temporary Override 不会直接删除 Stable Memory。

## Gate M8-F15

Temporary Override 支持 expires_at。

## Gate M8-F16

Preference Drift 与 Temporary Override 分离。

## Gate M8-F17

Wrong-user Memory Rate 必须为 0。

## Gate M8-F18

Unbound Mode 默认不写个人 Long-Term Memory。

## Gate M8-F19

Memory Write 支持 Idempotency。

## Gate M8-F20

Critical Runtime Commit 与 Memory Commit 分层。

## Gate M8-F21

Memory Commit 失败不会重放关键安全副作用。

## Gate M8-F22

主动次数只统计真正发生的主动交互。

## Gate M8-F23

Quiet Until 能进入下一轮 RuntimeContext。

## Gate M8-F24

所有 Memory Write / Ignore / Update / Deprecate 均可 Trace。

---

# 第九部分
# 冻结后的核心数据链

至此 Runtime 的核心对象正式稳定为：

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

↓

M7
RuntimeResponse

↓

M8
UpdateResult
```

分别表示：

```text
UnderstandingState
=
系统如何理解用户

ActionPlan
=
系统决定做什么

ExecutionResult
=
系统实际执行了什么

ValidatedResult
=
系统真正确认发生了什么

RuntimeResponse
=
系统最终实际说了什么

UpdateResult
=
这一轮结束后系统真正留下了什么
```

---

# 第十部分
# M8 冻结后的最终原则

正式固定为：

```text
一、只有经过验证的事实才能成为 Runtime 事实状态。

二、实际发生的回复和行为优先于原计划。

三、当前 Context 与长期 Memory 必须分层。

四、一次行为或一次拒绝不能定义长期偏好。

五、用户明确修正优先于历史 Memory。

六、Temporary Override 不等于永久 Preference Change。

七、模型推断不能自动升级为长期事实。

八、个人 Memory 必须严格绑定 user scope。

九、Memory 写入追求 Precision 优先于 Recall。

十、关键业务状态更新失败与 Memory 写失败必须分开处理。
```

---

# 结论

完成本冻结文件后，M0～M8 的 Runtime Core 可以正式视为架构冻结：

```text
M1 读取上一轮留下的状态
↓
M2 约束本轮安全和状态
↓
M3 理解
↓
M4 决策
↓
M5 执行
↓
M6 验证
↓
M7 表达
↓
M8 更新
↓
下一轮 M1
```

最终形成：

```text
Context_t
→ Understanding_t
→ Planning_t
→ Execution_t
→ Validation_t
→ Response_t
→ Update_t
→ Context_t+1
```

即完整的连续 Agent Runtime Loop。

至此，M8 Core Design 正式冻结。
