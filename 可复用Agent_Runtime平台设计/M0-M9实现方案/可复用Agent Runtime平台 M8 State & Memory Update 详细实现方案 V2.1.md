# 可复用 Agent Runtime 平台  
# M8 State & Memory Update 详细实现方案 V2.1

> **Phase 0 Fix**  
> M8 主链终点只能是 `UpdateResult`。`StateUpdate` / `MemoryUpdate` 是其内部结果，不是链终点。  
> Core 状态只允许 `RuntimeControlState`。Domain 业务阶段经 `domain_state_update` 写入。  
> `elder_id` 已从 Core 删除，隔离键为 `identity_scope`。

> **平台化转换说明**  
> 本文已从单一业务 Agent 设计转换为 **可复用 Agent Runtime 平台**设计。除明确标记为 `Core` 的对象、接口、不变量和生命周期外，任何具体业务 Intent、Entity、Workflow、Skill、Tool、知识域、状态字段、规则、提示词或示例均视为 **Domain Package 示例**，不得硬编码进 Runtime Core。新项目应通过 Registry / Adapter / Plugin / Config 注入领域差异。
> 
> 平台固定边界：`Runtime Core` 尽量稳定；`Domain Extension` 插件化；`Business Package` 配置化；`Application` 负责产品装配。

> 本版本基于 M8 V2.0 更新。  
> V2.0 中的 State Commit、Task Update、Conversation Update、PendingQuestion、Interaction Update、Session Update、Turn / Session / Recent / Long-Term 四层数据架构、MemoryRecord、Memory Status、Conflict、Temporary Override、Promotion / Deprecation、TTL、Usage Feedback、ProactivityState、Context Compaction、Atomic / Partial Commit、Event Update、Idempotency、Recovery、Eval、Gate、交付物等内容全部保留。
>
> V2.1 重点补强：
>
> **Memory 不再被描述为“LLM 判断是否记住”，而正式拆分为：**
>
> ```text
> Candidate Extraction
> → Normalization
> → Validation
> → Write Policy
> → Conflict Resolution
> → Scope Decision
> → Lifecycle Decision
> → TTL
> → Commit
> → Usage Feedback
> → Promotion / Deprecation
> ```
>
> 并明确：
>
> ```text
> LLM = Memory 的语义入口
> Memory Policy = Memory 的准入治理者
> Conflict Resolver = 新旧 Memory 关系治理者
> Lifecycle Manager = Memory 生命周期治理者
> Store = 最终持久化执行者
> ```
>
> **LLM 无权单独决定 WRITE / STABLE / COVER / DELETE。**

---


## 平台扩展补充：Runtime State / Domain State 分离

M8 必须把 `RuntimeState` 与 `DomainState` 分开治理。Domain 可以拥有自己的阶段、任务、业务实体状态，但只能通过注册的 Domain State Schema 和 StateMutation Contract 更新，不能向 Core RuntimeState 任意添加字段。

# 01. 阶段定位

M8 是一次 Runtime Cycle 的收尾阶段。

前面已经完成：

```text
M3
UnderstandingState

M4
Approved ActionPlan

M5
ExecutionResult

M6
ValidatedResult

M7
RuntimeResponse
```

M8 解决：

```text
这一轮结束以后，

系统状态应该变成什么？

当前 Task 推进到了哪里？

刚刚真正问出去的问题是否需要成为 pending_question？

当前话题和人物指代如何延续？

哪些交互行为会影响下一轮策略？

哪些信息只保留当前 Turn？

哪些信息保留当前 Session？

哪些信息进入 Recent Context？

哪些信息真正有资格进入 Long-Term Memory？

新信息和旧 Memory 冲突时怎么办？

临时变化是否应该覆盖长期偏好？

长期 Memory 什么时候应该晋升、降级、失效？

这一轮哪些 Commit 必须强一致，
哪些失败可以允许 Partial Success？
```

因此：

```text
M8
=
State Commit
+
Task Commit
+
Context Commit
+
Interaction Commit
+
Memory Governance
+
Memory Commit
```

M8 的核心不是：

```text
“让机器人记住更多”
```

而是：

> **让系统只保留应该保留的东西，并以正确时间尺度、正确可信状态、正确用户作用域继续生效。**

---

# 02. 阶段目标与八种智能映射

## 2.1 M8 总体目标

M8 最终需要完成：

```text
State Transition Resolution

+

Task Progress Update

+

Conversation Context Update

+

Pending Question Update

+

Topic / Reference Update

+

Interaction State Update

+

Proactivity State Update

+

Session Update

+

Context Compaction

+

Memory Candidate Processing

+

Memory Governance Pipeline

+

Memory Conflict Resolution

+

Memory Scope / Lifecycle Management

+

Memory Promotion / Deprecation

+

Memory TTL / Expiry

+

Memory Usage Feedback

+

Event Update

+

Commit Coordination

+

Idempotency

+

Recovery
```

并统一输出：

```text
UpdateResult
```

---

## 2.2 与八种智能的关系

M8 是以下能力的核心实现层：

```text
3. 关系连续性智能

7. 主动性智能
```

同时构成：

```text
2. 上下文智能
```

跨轮持续性的基础。

| 智能能力 | M8职责 |
|---|---|
| 语义理解智能 | 不重新理解，消费 M3 结果 |
| 上下文智能 | 更新下一轮 M1 可读取 Context |
| 关系连续性智能 | M8 核心 |
| 情绪理解智能 | 保存必要短期情绪背景，不自动长期心理画像 |
| 目标与隐含需求推断智能 | 只保存必要交互状态，不持久化推断本身 |
| 对话策略智能 | 记录实际 Agent 行为与用户反应 |
| 主动性智能 | 维护 cooldown、主动次数、近期拒绝 |
| 自我约束智能 | 控制 Memory 准入、状态提交与事实边界 |

因此：

```text
M1
=
下一轮读取什么

M8
=
这一轮留下什么
```

而 Memory 部分进一步固定：

```text
M3
=
发现“可能值得记的东西”

M8
=
决定“有没有资格记、记在哪里、记多久、以什么状态记”
```

---

# 03. 职责边界

## 3.1 M8 负责

M8 负责：

```text
State Transition Proposal

State Commit

Task Update

Conversation Turn Commit

Pending Question生命周期

Pending Reference / Person Salience更新

Topic Update

Interaction History更新

Proactivity State更新

Session Summary更新

Context Compaction

Memory Candidate Validation

Memory Write Policy

Memory Scope Decision

Memory Conflict Resolution

Memory Lifecycle Decision

Memory Promotion / Deprecation

Memory TTL / Expiry

Memory Usage Feedback

Event Lifecycle Update

Commit Coordination

Partial Commit处理

Update Idempotency

Update Recovery

Update Trace
```

---

## 3.2 M8 不负责

M8 不负责：

```text
重新理解用户

重新分类 Intent

重新判断 Emotion

重新选择 Strategy

重新规划 Action

重新执行 Tool

重新验证业务事实

生成用户回复

让 LLM 自由决定记忆是否长期有效

让 LLM 自由覆盖旧 Memory

让 LLM 自由将 Memory 标记为 STABLE

绕过 State Engine 修改状态
```

---

## 3.3 M8 与 M6 的硬边界

必须固定：

```text
ExecutionResult
不能直接成为
Runtime Business State
```

正确链路：

```text
ExecutionResult
↓
M6
ValidatedResult
↓
M8
State / Task / Event Update
```

---

## 3.4 M8 与 M7 的硬边界

下一轮 Conversation Context 应基于：

```text
系统实际说了什么
```

而不是：

```text
M4原本计划说什么
```

因此：

```text
RuntimeResponse
>
ResponsePlan
```

例如：

```text
M4：
CLARIFY_REFERENCE

M7最终：
SYSTEM_ERROR
```

则：

```text
M8：
不得建立原计划中的 pending_question
```

---

## 3.5 LLM 与 Memory Governance 的硬边界

这是 V2.1 新增的核心规则。

### LLM 可以做

```text
发现候选 Memory

将自然语言标准化为结构化 Candidate

辅助 Session Summary

辅助语义归一
```

### LLM 不可以做

```text
决定 WRITE

决定 IGNORE

决定 Long-Term

决定 STABLE

决定覆盖哪条旧 Memory

决定 TTL

决定 DEPRECATED

决定用户永久偏好

决定心理画像
```

固定原则：

```text
LLM Output
=
Candidate / Semantic Suggestion

NOT
=
Memory Truth
```

---

# 04. 前置依赖与外部依赖

## 4.1 M0 依赖

M8 依赖：

```text
StateUpdate Schema

MemoryUpdate Schema

StateUpdater Interface

MemoryUpdater Interface

Runtime Trace

Error Framework

Store Interface

Schema Version
```

---

## 4.2 M1 依赖

M8 读取：

```text
Previous RuntimeContext

SessionContext

ConversationContext

TaskContext

InteractionContext

MemoryContext

SafetyContext
```

用于计算 Delta。

---

## 4.3 M2 依赖

State 更新必须服从：

```text
State Machine

Transition Rule

Safety Lock

Resume Policy

Policy Decision

Workflow State
```

---

## 4.4 M3 依赖

M3 可提供：

```text
memory_candidates

explicit facts

entities

topic

emotion

interaction state

uncertainty

confidence

evidence
```

其中：

```text
memory_candidates
```

仅是候选。

---

## 4.5 M4 依赖

M8 可以读取：

```text
ActionPlan

state_intent

task_intent

memory_usage

strategy

planned question
```

但不将计划当成已发生事实。

---

## 4.6 M5 依赖

可以读取：

```text
Execution Events

Workflow Instance

Activity Instance

State Observations
```

但业务事实仍以 M6 为准。

---

## 4.7 M6 依赖

关键事实来源：

```text
ValidatedResult

Goal Validation

Verified Facts

Business Status

State Recommendation

Follow-up

Conflicts
```

---

## 4.8 M7 依赖

使用：

```text
RuntimeResponse

Question Metadata

Claims Used

Memory References Used

Actual Response Type
```

更新 Conversation / Interaction。

---

## 4.9 存储依赖

可能依赖：

```text
State Store

Task Store

Conversation Store

Session Store

Recent Context Store

Memory Store

Event Store

Workflow Store
```

---

# 05. 输入

正式定义：

```text
UpdateInput
```

结构：

```text
UpdateInput

previous_runtime_context

understanding_state

action_plan

execution_result

validated_result

runtime_response

policy_context

workflow_context
```

---

# 06. 输出

统一输出：

```text
UpdateResult
```

包括：

```text
state_update

task_update

conversation_update

interaction_update

session_update

event_update

memory_update

commit_result

metadata
```

---

# 07. 核心数据结构

## 7.1 StateUpdate

```text
StateUpdate

previous_state

proposed_state

committed_state

transition_event

transition_reason

transition_status

evidence_ids[]
```

---

## 7.2 TransitionStatus

```text
NOT_REQUIRED

PROPOSED

COMMITTED

REJECTED

DEFERRED
```

---

## 7.3 TaskUpdate

```text
TaskUpdate

task_id

task_type

previous_stage

next_stage

status

field_updates

pending_field

timeout_update

completion_reason
```

---

## 7.4 TaskStatus

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

## 7.5 TaskFieldValue

```text
TaskFieldValue

field_name

value

source

confidence

status

evidence_refs[]
```

---

## 7.6 TaskFieldStatus

```text
CONFIRMED

UNCONFIRMED

REJECTED

SUPERSEDED
```

---

## 7.7 ConversationUpdate

```text
ConversationUpdate

new_turn

current_topic

topic_history_updates

pending_question

pending_reference

recent_entities

conversation_stage

rolling_summary_update
```

---

## 7.8 ConversationTurn

```text
ConversationTurn

turn_id

user_input

assistant_response

topic

intent_summary

emotion_summary

actions_taken

claims_used

question_metadata

timestamp
```

---

## 7.9 PendingQuestion

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

## 7.10 PendingQuestionStatus

```text
ACTIVE

ANSWERED

CANCELLED

EXPIRED

SUPERSEDED
```

---

## 7.11 InteractionUpdate

```text
InteractionUpdate

last_agent_action

recent_agent_actions

recent_questions

recent_suggestions

recent_rejections

active_interaction_count

quiet_until

engagement_history

user_reaction_updates
```

---

## 7.12 SessionUpdate

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

## 7.13 ProactivityState

```text
ProactivityState

last_active_interaction_at

active_interaction_count_today

last_active_topic

recent_active_results[]

recent_active_rejections

quiet_until
```

---

# 7.14 MemoryCandidate

V2.1 正式定义 Candidate，不再把它和 MemoryRecord 混在一起。

```text
MemoryCandidate

candidate_id

candidate_type

raw_content

normalized_value

source

source_turn_id

source_evidence[]

explicitness

confidence

temporal_hint

scope_hint

stability_hint

sensitivity

created_at
```

---

## 7.14.1 source

建议：

```text
USER_EXPLICIT

USER_BEHAVIOR

TASK_CONFIRMED

SYSTEM_CONFIRMED

MODEL_INFERRED

SUMMARY_DERIVED
```

---

## 7.14.2 explicitness

```text
EXPLICIT

STRONG_IMPLICIT

WEAK_INFERRED
```

---

## 7.14.3 stability_hint

只是提示：

```text
TEMPORARY_HINT

POSSIBLY_STABLE

UNKNOWN
```

**不能直接成为最终 MemoryStatus。**

---

# 7.15 MemoryCandidateValidationResult

```text
MemoryCandidateValidationResult

candidate_id

schema_valid

user_scope_valid

source_valid

evidence_valid

sensitivity_allowed

eligible

rejection_reasons[]
```

---

# 7.16 MemoryWriteDecision

```text
MemoryWriteDecision

candidate_id

decision

target_scope

memory_type

initial_status

ttl_policy

reason_codes[]

merge_target
```

decision：

```text
WRITE

UPDATE_EXISTING

MERGE

KEEP_RECENT_ONLY

IGNORE

DEPRECATE_EXISTING
```

---

# 7.17 MemoryScope

正式冻结：

```text
TURN

SESSION

RECENT

LONG_TERM
```

---

# 7.18 MemoryRecord

```text
MemoryRecord

memory_id

schema_version

identity_scope

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

policy_version
```

---

# 7.19 MemoryStatus

保留原设计：

```text
STABLE

TEMPORARY

EMERGING

UNCERTAIN

DEPRECATED
```

注意：

```text
MemoryStatus
!=
MemoryScope
```

例如可以存在：

```text
scope = LONG_TERM
status = EMERGING
```

表示：

> 已进入长期 Memory Store，但仍未达到稳定事实级别。

---

# 7.20 MemoryType

第一版建议：

```text
PREFERENCE

RELATIONSHIP

PERSONAL_FACT

ROUTINE

IMPORTANT_EVENT

INTERACTION_PREFERENCE

LONG_TERM_INTEREST

AVOIDANCE_PREFERENCE
```

---

# 7.21 MemoryConflict

```text
MemoryConflict

conflict_id

type

existing_memory_id

candidate_id

existing_value

candidate_value

resolution

reason
```

---

## 7.21.1 MemoryConflictType

```text
DIRECT_CONTRADICTION

TEMPORARY_OVERRIDE

PREFERENCE_DRIFT

VALUE_UPDATE

DUPLICATE

AMBIGUOUS_CONFLICT
```

---

# 7.22 MemoryLifecycleDecision

V2.1 新增：

```text
MemoryLifecycleDecision

memory_id

previous_status

next_status

promotion_reason

deprecation_reason

expires_at

rule_id
```

---

# 7.23 MemoryUsageFeedback

```text
MemoryUsageFeedback

memory_id

retrieved

selected_by_planner

actually_expressed

used_for_personalization

user_reaction

timestamp
```

---

# 7.24 EventUpdate

```text
EventUpdate

event_id

previous_status

new_status

reason

evidence_ids[]
```

---

# 7.25 CommitResult

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

# 7.26 CommitOverallStatus

```text
SUCCESS

PARTIAL_SUCCESS

FAILED
```

---

# 7.27 UpdateResult

```text
UpdateResult

update_id

schema_version

state_update

task_update

conversation_update

interaction_update

session_update

event_update

memory_update

commit_result

trace
```

---

# 08. 数据来源、存储与生命周期

## 8.1 四层数据架构

正式采用：

```text
Turn Context

Session Context

Recent Context

Long-Term Memory
```

---

## 8.2 Turn Context

生命周期：

```text
当前一轮
```

例如：

```text
当前模型推断

当前 Candidate

当前 ActionPlan
```

通常不持久化。

---

## 8.3 Session Context

生命周期：

```text
当前会话
```

例如：

```text
current_topic

pending_question

active_task

当前情绪背景

会话中的临时偏好
```

---

## 8.4 Recent Context

生命周期：

```text
数小时～数天
```

例如：

```text
女儿说明天来看望

最近几天不想听戏曲

昨天聊过身体不舒服
```

---

## 8.5 Long-Term Memory

只保存：

```text
稳定

重要

未来持续有价值

来源清晰

通过 Memory Policy
```

的信息。

---

## 8.6 Scope 和 Status 分开

这是 V2.1 必须明确的设计。

例如：

```text
scope = RECENT
status = TEMPORARY
```

或者：

```text
scope = LONG_TERM
status = EMERGING
```

不能把：

```text
RECENT
```

和：

```text
TEMPORARY
```

视为同一个概念。

---

## 8.7 Long-Term 不代表永久有效

Long-Term Memory 仍必须有：

```text
updated_at

last_confirmed_at

confidence

status

expires_at（如适用）
```

---

# 09. 内部组件

M8 建议包含：

```text
StateMemoryUpdateOrchestrator

UpdateEligibilityChecker

StateTransitionResolver

StateCommitter

TaskUpdater

ConversationUpdater

PendingQuestionManager

TopicManager

ReferenceSalienceManager

InteractionUpdater

ProactivityStateUpdater

SessionUpdater

SessionSummarizer

ContextCompactor

MemoryCandidateProcessor

MemoryNormalizer

MemoryCandidateValidator

MemoryWritePolicy

MemoryScopeResolver

MemoryConflictResolver

MemoryLifecycleManager

MemoryPromotionManager

MemoryDeprecationManager

MemoryExpiryManager

MemoryUsageFeedbackUpdater

EventUpdater

CommitCoordinator

IdempotencyManager

RecoveryManager

UpdateTracer
```

---

# 10. M8 总体运行时主流程

```text
Previous RuntimeContext
+
UnderstandingState
+
ActionPlan
+
ExecutionResult
+
ValidatedResult
+
RuntimeResponse
        ↓
① Update Eligibility Check
        ↓
② Resolve State Transition
        ↓
③ Resolve Task Update
        ↓
④ Build Conversation Update
        ↓
⑤ Update Pending Question / Reference / Topic
        ↓
⑥ Build Interaction / Proactivity Update
        ↓
⑦ Build Session Update / Compaction
        ↓
⑧ Run Memory Governance Pipeline
        ↓
⑨ Build Event Update
        ↓
⑩ Prepare Commit Plan
        ↓
⑪ Commit Critical Runtime State
        ↓
⑫ Commit Conversation / Interaction
        ↓
⑬ Commit Memory
        ↓
⑭ Aggregate CommitResult
        ↓
⑮ Produce UpdateResult
        ↓
下一轮 M1
```

---

# 10A. Memory 独立运行时主流程

这是 V2.1 新增的核心。

Memory 正式采用：

```text
Memory Candidate
        ↓
① Candidate Extraction
        ↓
② Candidate Normalization
        ↓
③ Candidate Validation
        ↓
④ Write Policy Decision
        ↓
⑤ Existing Memory Lookup
        ↓
⑥ Conflict Detection
        ↓
⑦ Scope Decision
        ↓
⑧ Lifecycle Decision
        ↓
⑨ TTL / Expiry Decision
        ↓
⑩ Build Memory Mutation
        ↓
⑪ Commit
        ↓
⑫ Usage Feedback
        ↓
⑬ Future Promotion / Deprecation
```

---

## 10A.1 各组件权限

```text
M3 / LLM
→ Candidate Extraction

LLM / Normalizer
→ Candidate Normalization

Validator
→ Candidate Validation

MemoryWritePolicy
→ WRITE / IGNORE / RECENT / UPDATE

ConflictResolver
→ 新旧关系

ScopeResolver
→ Turn / Session / Recent / Long-Term

LifecycleManager
→ TEMPORARY / EMERGING / STABLE / UNCERTAIN / DEPRECATED

ExpiryManager
→ TTL

Store
→ Commit
```

绝对禁止：

```text
LLM
→ “我觉得值得记”
→ 直接 Memory Store
```

---

# 11. 各步骤详细实现

## Step 1：Update Eligibility

不是所有字段每轮都更新。

例如：

> “谢谢。”

可能只需要：

```text
Conversation Turn

last_active_at

turn_index
```

因此采用：

```text
Delta Update
```

---

## Step 2：State Transition

状态提交必须经过：

```text
StateEngine.validate_transition()

StateEngine.commit_transition()
```

依据：

```text
Validated Result
+
Transition Rule
+
Safety Lock
+
Resume Policy
```

---

### M6 UNKNOWN

如果：

```text
Playback State = UNKNOWN
```

M8 不得进入：

```text
S06
```

---

### Workflow WAITING

HelpWorkflow：

```text
WAITING
```

则：

```text
保持 S08
```

---

## Step 3：Task Update

Task 跨轮存在。

字段必须区分：

```text
CONFIRMED

UNCONFIRMED
```

LLM 低置信推断：

```text
不得直接成为 CONFIRMED Task Field
```

---

## Step 4：Conversation Update

记录：

```text
实际 user input

实际 RuntimeResponse

必要结构化元数据
```

不永久塞入完整模型推理。

---

## Step 5：Pending Question / Reference / Topic

以：

```text
M7 实际输出
```

为准。

计划问了但实际没问：

```text
不建立 Pending Question
```

旧问题被新问题替代：

```text
旧 = SUPERSEDED

新 = ACTIVE
```

---

## Step 6：Interaction / Proactivity Update

记录：

```text
Recent Agent Actions

Recent Questions

Recent Suggestions

Recent Rejections

Quiet Until

Active Count
```

只有真正发生的主动行为：

```text
active_interaction_count += 1
```

---

## Step 7：Session / Compaction

采用：

```text
Recent Turns
+
Rolling Summary
+
Structured Active State
```

Summary 不是权威事实源。

---

# Step 8：Memory Candidate Extraction

Candidate 一般由 M3 输出。

例如：

> “我最喜欢越剧。”

M3：

```text
MemoryCandidate

candidate_type = PREFERENCE

normalized_value = YUE_OPERA

source = USER_EXPLICIT

explicitness = EXPLICIT
```

注意：

```text
Candidate
!=
Memory
```

---

# Step 9：Memory Normalization

这一步允许 LLM 参与。

例如：

> “我平时还是最爱听越剧。”

可以标准化为：

```text
memory_type = PREFERENCE

domain = CONTENT

value = YUE_OPERA
```

但 Normalizer 只做：

```text
语义结构化
```

不做：

```text
WRITE Decision

Scope Decision

Status Decision
```

---

# Step 10：Candidate Validation

正式校验：

```text
Schema Valid?

identity_scope 正确?

Source Valid?

Evidence存在?

Sensitive Data允许?

Candidate是否属于可保存类型?
```

例如：

```text
MODEL_INFERRED:
“用户长期孤独”
```

第一版：

```text
eligible = false
```

---

# Step 11：Memory Write Policy

这是决定“要不要记”的真正核心。

输入：

```text
Candidate

Explicitness

Source

Stability Hint

Future Value

Sensitivity

Existing Memory

Recent Pattern
```

输出：

```text
WRITE

UPDATE_EXISTING

MERGE

KEEP_RECENT_ONLY

IGNORE

DEPRECATE_EXISTING
```

---

## 11.11.1 示例：稳定偏好

用户：

> “我最喜欢越剧。”

可能：

```text
decision = WRITE

scope = LONG_TERM

status = EMERGING
```

而不是让 LLM决定。

---

## 11.11.2 示例：临时偏好

用户：

> “今天不想听京剧。”

规则识别：

```text
temporal_hint = today
```

决策：

```text
KEEP_RECENT_ONLY

scope = RECENT

status = TEMPORARY
```

---

## 11.11.3 示例：普通事件

用户：

> “我女儿今天加班。”

可：

```text
KEEP_RECENT_ONLY
```

不进入长期 Memory。

---

## 11.11.4 示例：弱推断

M3：

```text
possible_loneliness
```

决策：

```text
IGNORE
```

不写长期 Memory。

---

# Step 12：Existing Memory Lookup

只查询：

```text
同 identity_scope

同 memory_type / domain

可能相关 key
```

用于判断：

```text
Duplicate

Conflict

Update

Override
```

---

# Step 13：Memory Conflict Detection

不交给 LLM自由决定。

通过结构化 Conflict Rules。

---

## 13.1 DIRECT_CONTRADICTION

旧：

```text
daughter_name = 小玲
```

新：

> “不是小玲，是小敏。”

结果：

```text
DIRECT_CONTRADICTION
```

---

## 13.2 TEMPORARY_OVERRIDE

旧：

```text
喜欢京剧
STABLE
```

新：

> “这几天不想听京剧。”

结果：

```text
TEMPORARY_OVERRIDE
```

---

## 13.3 PREFERENCE_DRIFT

旧长期喜欢 A。

近阶段反复明确选择 B / 拒绝 A。

结果：

```text
PREFERENCE_DRIFT
```

不是一次变化就立即覆盖。

---

## 13.4 DUPLICATE

同一事实重复表达：

```text
MERGE / update last_confirmed_at
```

无需新增重复 Memory。

---

# Step 14：Memory Scope Decision

正式决定：

```text
TURN

SESSION

RECENT

LONG_TERM
```

---

## 14.1 Scope 规则示例

```text
一次临时情绪
→ SESSION / RECENT

今天发生的事件
→ RECENT

明确稳定家庭关系
→ LONG_TERM

明确长期偏好
→ LONG_TERM

一次行为选择
→ RECENT

模型推断
→ 通常不进入 LONG_TERM
```

---

# Step 15：Lifecycle Decision

Scope 确定后，再决定 Status。

```text
TEMPORARY

UNCERTAIN

EMERGING

STABLE

DEPRECATED
```

---

## 15.1 STABLE 不由 LLM直接产生

STABLE 来源必须满足明确 Policy，例如：

```text
用户明确长期陈述
+
高可信
+
规则允许
```

或：

```text
EMERGING
+
多次一致确认
+
Promotion Rule
```

---

## 15.2 UNCERTAIN

用于：

```text
候选具有价值

但证据不足
```

避免：

```text
要么记成真
要么完全丢掉
```

---

## 15.3 EMERGING

用于：

```text
正在形成的偏好 / 模式
```

---

# Step 16：TTL / Expiry Decision

不同 Scope / Type 配置不同 TTL。

例如：

```text
“女儿明天来”
→ expires after event window

“这几天不想听京剧”
→ short TTL

“喜欢越剧”
→ no short TTL but still reviewable

“当前有点孤独”
→ short/session TTL
```

---

# Step 17：Build Memory Mutation

真正生成：

```text
Create Memory

Update Memory

Merge Memory

Deprecate Memory

Add Temporary Override
```

到这里才接近 Store。

---

# Step 18：Memory Commit

Memory Commit 必须：

```text
identity_scope scoped

idempotent

schema validated

policy_version recorded
```

---

# Step 19：Memory Usage Feedback

区分：

```text
Retrieved

Selected

Actually Used

Explicitly Expressed
```

只有真正用到：

```text
usage_count += 1
```

---

## 19.1 用户负面反应

例如：

> “别老提这个。”

记录：

```text
interaction preference:
avoid_explicit_memory_reference
```

不是：

```text
删除原 Memory Fact
```

---

# Step 20：Promotion / Deprecation

在未来轮次根据规则更新生命周期。

---

## 20.1 Promotion

例如：

```text
UNCERTAIN
→ EMERGING

EMERGING
→ STABLE
```

信号：

```text
Explicit Confirmation

Repeated Consistent Statement

Repeated Stable Behavior
```

---

## 20.2 Deprecation

例如：

```text
STABLE
→ DEPRECATED
```

依据：

```text
Explicit Correction

Confirmed Preference Drift

Fact Update
```

---

# Step 21：Event Update

Help / Reminder / Workflow Event 必须依据：

```text
M6 Validated Truth
```

更新。

UNKNOWN：

```text
不能写成 DELIVERED
```

---

# Step 22：Commit Coordination

分为：

```text
Critical Runtime Commit

Conversation / Interaction Commit

Memory Commit
```

---

## 22.1 Critical Commit

优先：

```text
State

Safety Lock

Active Task

Workflow State

Pending Question

Critical Event
```

---

## 22.2 Conversation Commit

包括：

```text
Turn

Topic

Recent Action

Recent Question

Recent Rejection

Summary
```

---

## 22.3 Memory Commit

独立执行。

Memory 失败：

```text
不能回滚已经完成的 Help Notification
```

---

# 12. 分支、路由与决策规则

## 12.1 Verified Truth > Execution Result

```text
M6 ValidatedResult
>
M5 ExecutionResult
```

---

## 12.2 Actual > Planned

```text
M7 RuntimeResponse
>
M4 Response Plan
```

---

## 12.3 Explicit > Inferred

```text
User Explicit
>
Model Inferred
```

---

## 12.4 Current Correction > Old Memory

当前明确修正优先。

---

## 12.5 Temporary Override != Long-term Reversal

```text
“今天不想听京剧”
```

不能自动：

```text
DEPRECATED:
喜欢京剧
```

---

## 12.6 Single Behavior != Stable Preference

一次选越剧：

```text
不能直接 STABLE
```

---

## 12.7 Single Emotion != Long-term Trait

一次孤独：

```text
不能形成长期“孤独用户”标签
```

---

## 12.8 Memory Precision > Recall

正式原则：

```text
Memory Write Precision
>
Memory Recall
```

---

## 12.9 Wrong-user Memory = Zero Tolerance

每个 Memory：

```text
必须绑定 identity_scope
```

---

## 12.10 Safety Lock Release

必须依据：

```text
Deterministic Workflow
+
Validated Completion
```

---

## 12.11 LLM Decision Boundary

正式固定：

```text
LLM 可抽取 / 标准化 / 摘要

LLM 不可决定：
WRITE
SCOPE
STATUS
TTL
CONFLICT RESOLUTION
PROMOTION
DEPRECATION
```

---

# 13. 与前后 M 的接口

## M1 → M8

```text
Previous RuntimeContext
```

---

## M2 → M8

```text
State Machine

Resume Policy

Safety Lock

Workflow Rule
```

---

## M3 → M8

```text
MemoryCandidate

Explicit Fact

Topic

Entity
```

---

## M4 → M8

```text
Memory Usage Decision

Strategy

State Intent
```

---

## M5 → M8

```text
Execution Event

Activity

Workflow
```

---

## M6 → M8

```text
Validated Truth
```

是事实状态提交的最高依据。

---

## M7 → M8

```text
Actual RuntimeResponse
```

是 Conversation Update 的最高依据。

---

## M8 → M1

提交后的：

```text
State Store

Session Store

Task Store

Conversation Store

Recent Context Store

Memory Store
```

成为下一轮 M1 数据来源。

---

# 14. 与业务模块的映射

## 领域交互

重点：

```text
Topic
Recent Interaction
Relationship Reference
Recent Rejection
Session Summary
```

---

## 内容播放

重点：

```text
Playback State
Recent Content Choice
Temporary Preference
```

单次播放不自动长期化。

---

## 情绪安抚

重点：

```text
Session Emotional Context
Need for Silence
Recent Topic
```

不保存心理诊断。

---

## 安全与领域服务

重点：

```text
Safety Lock
Workflow State
Critical Event
Task State
```

---

## 领域提醒

重点：

```text
Reminder Task
Pending Question
Retry State
Escalation Event
```

---

## 领域任务交互

重点：

```text
Activity Progress
Current Question
Task Stage
```

---

## 长期记忆

M8 为核心实现：

```text
Candidate
→ Policy
→ Conflict
→ Scope
→ Lifecycle
→ Commit
```

---

## 新闻天气

一般只进入：

```text
Current Topic
Recent Query Context
```

不长期保存每次查询结果。

---

# 15. 异常、超时与降级

保留以下错误：

```text
INVALID_UPDATE_INPUT

ILLEGAL_STATE_TRANSITION

STATE_COMMIT_FAILED

TASK_UPDATE_FAILED

CONVERSATION_COMMIT_FAILED

SESSION_UPDATE_FAILED

MEMORY_CANDIDATE_INVALID

MEMORY_POLICY_FAILED

MEMORY_WRITE_FAILED

MEMORY_CONFLICT_UNRESOLVED

MEMORY_SCHEMA_INVALID

WRONG_USER_SCOPE

CHECKPOINT_UPDATE_FAILED

PARTIAL_COMMIT

UNKNOWN_UPDATE_ERROR
```

---

## Memory Candidate Invalid

```text
→ IGNORE
+
Trace
```

---

## Memory Policy unavailable

不得：

```text
默认 WRITE
```

而应：

```text
KEEP_RECENT_ONLY / IGNORE
```

采用保守策略。

---

## Conflict unresolved

```text
不得覆盖旧 Memory
```

可：

```text
UNCERTAIN
或
KEEP_RECENT_ONLY
```

---

# 16. 配置项与可变项

建议：

```text
recent_context_ttl

memory_scope_rules

memory_write_rules

memory_ttl_rules

memory_promotion_rules

memory_deprecation_rules

memory_conflict_rules

memory_write_thresholds

summary_threshold

quiet_cooldown

active_interaction_daily_limit

pending_question_ttl

commit_retry_policy

idempotency_policy
```

---

# 17. 非功能约束

## 17.1 Memory Precision

第一优先：

```text
少记错
```

而不是：

```text
多记
```

---

## 17.2 Deterministic Governance

Memory Governance 尽量：

```text
Rule / Policy Driven
```

而不是：

```text
LLM Judgment Driven
```

---

## 17.3 State Consistency

关键：

```text
State
Safety Lock
Task
Workflow
Pending Question
```

必须一致。

---

## 17.4 Idempotency

重复 Update 不得：

```text
重复写 Turn
重复写 Memory
重复推进 Task
```

---

## 17.5 Privacy / Scope

所有 Memory 强绑定：

```text
identity_scope
```

---

## 17.6 Growth Control

通过：

```text
TTL
Compaction
Deprecation
Merge
Dedup
```

避免 Memory 无限增长。

---

# 18. Trace / Logging / Observability

除原有 Update Trace 外，Memory 需要独立 Trace：

```text
candidate_id

raw_candidate

normalized_candidate

candidate_validation

write_policy_decision

existing_memory_matches

conflict_type

scope_decision

lifecycle_decision

ttl_decision

mutation

commit_result

promotion_event

deprecation_event

usage_feedback
```

这样能够回答：

```text
为什么记了？

为什么没记？

为什么只是 Recent？

为什么不是 Stable？

为什么旧 Memory 被废弃？
```

---

# 19. 版本、兼容与变更影响

必须版本化：

```text
UpdateResult Schema

MemoryRecord Schema

Memory Write Policy

Memory Conflict Rules

Memory Lifecycle Rules

Memory Normalizer Prompt（如使用LLM）

Summary Prompt
```

---

# 20. 测试 / Eval

除原指标外，V2.1 增加：

```text
Candidate Extraction Recall

Candidate Validation Precision

Write Policy Accuracy

Scope Decision Accuracy

Lifecycle Decision Accuracy

Temporary Override Accuracy

Stable Preference False-positive Rate

Conflict Classification Accuracy

Promotion Accuracy

Deprecation Accuracy
```

---

## 核心优先指标

### Memory Write Precision

长期写入尤其重要。

### Long-term Over-memory Rate

本应 Recent，却长期保存。

### Stable False-positive Rate

本应 Temporary / Emerging，却被标记 STABLE。

### Wrong-user Memory Rate

目标：

```text
0
```

---

# 21. Gate

在原 M8 Gate 基础上新增：

## Gate M8-26

Memory Candidate 与 MemoryRecord 正式分离。

---

## Gate M8-27

LLM 输出不能直接进入 Memory Store。

---

## Gate M8-28

MemoryWritePolicy 正式决定：

```text
WRITE / UPDATE / MERGE /
KEEP_RECENT_ONLY / IGNORE / DEPRECATE
```

---

## Gate M8-29

Memory Scope 正式区分：

```text
TURN / SESSION / RECENT / LONG_TERM
```

---

## Gate M8-30

Memory Scope 与 Memory Status 分离。

---

## Gate M8-31

STABLE 状态不能由 LLM 自由产生。

---

## Gate M8-32

Temporary Override 不覆盖 Stable Memory。

---

## Gate M8-33

Single Behavior 不可直接生成 Stable Preference。

---

## Gate M8-34

Single Emotion 不可形成长期人格 / 心理标签。

---

## Gate M8-35

Memory Conflict Resolver 有确定性优先级。

---

## Gate M8-36

Promotion / Deprecation 由 Lifecycle Rules 控制。

---

## Gate M8-37

Memory Governance 全链可 Trace。

---

# 22. 交付物

M8 最终至少形成：

```text
M8-01 State & Memory Update总体架构

M8-02 Runtime Update主流程

M8-03 UpdateInput Schema

M8-04 UpdateResult Schema

M8-05 StateUpdate Schema

M8-06 State Transition Commit规范

M8-07 TaskUpdate规范

M8-08 Task Field Confirmation规范

M8-09 ConversationUpdate规范

M8-10 ConversationTurn Schema

M8-11 PendingQuestion规范

M8-12 Topic / Reference Lifecycle规范

M8-13 InteractionUpdate规范

M8-14 ProactivityState规范

M8-15 SessionUpdate规范

M8-16 Context Compaction规范

M8-17 Memory Architecture

M8-18 Memory Runtime Pipeline

M8-19 MemoryCandidate Schema

M8-20 MemoryCandidate Validation规范

M8-21 Memory Normalization规范

M8-22 MemoryWritePolicy规范

M8-23 Memory Scope规范

M8-24 MemoryRecord Schema

M8-25 Memory Type Taxonomy

M8-26 Memory Status Lifecycle

M8-27 Memory Conflict Resolution

M8-28 Temporary Override规范

M8-29 Preference Drift规范

M8-30 Memory Promotion规范

M8-31 Memory Deprecation规范

M8-32 Memory TTL / Expiry规范

M8-33 Memory Usage Feedback规范

M8-34 EventUpdate规范

M8-35 Commit Coordinator规范

M8-36 Update Idempotency规范

M8-37 Update Recovery规范

M8-38 Update Error Taxonomy

M8-39 M8 Eval Dataset

M8-40 M8 Metrics

M8-41 M8 Trace规范

M8-42 M8自动化测试

M8-43 M8 Gate验证报告
```

---

# 附录 A：Memory Pipeline 一图说明

```text
用户表达
   ↓
M3
发现潜在 Memory Candidate
   ↓
┌────────────────────────┐
│ Candidate Extraction   │ ← LLM可参与
└───────────┬────────────┘
            ↓
┌────────────────────────┐
│ Normalization          │ ← LLM可参与
└───────────┬────────────┘
            ↓
┌────────────────────────┐
│ Candidate Validation   │ ← 确定性
└───────────┬────────────┘
            ↓
┌────────────────────────┐
│ Memory Write Policy    │ ← 核心治理
└───────────┬────────────┘
            ↓
┌────────────────────────┐
│ Conflict Resolution    │ ← 规则
└───────────┬────────────┘
            ↓
┌────────────────────────┐
│ Scope Decision         │
│ Turn/Session/Recent/LT │
└───────────┬────────────┘
            ↓
┌────────────────────────┐
│ Lifecycle Decision     │
│ TEMP/EMERGING/STABLE...│
└───────────┬────────────┘
            ↓
┌────────────────────────┐
│ TTL / Expiry           │
└───────────┬────────────┘
            ↓
┌────────────────────────┐
│ Commit                 │
└───────────┬────────────┘
            ↓
Memory Store
            ↓
Usage Feedback
            ↓
Promotion / Deprecation
```

---

# 附录 B：三个典型案例

## B.1 “我最喜欢越剧”

```text
Candidate:
PREFERENCE / YUE_OPERA

Source:
USER_EXPLICIT

Write Policy:
WRITE

Scope:
LONG_TERM

Initial Status:
EMERGING

后续反复确认：
→ STABLE
```

---

## B.2 “今天不想听京剧”

```text
Candidate:
AVOID_BEIJING_OPERA

Temporal:
TODAY

Write Policy:
KEEP_RECENT_ONLY

Scope:
RECENT

Status:
TEMPORARY

Existing:
LIKE_BEIJING_OPERA / STABLE

Conflict:
TEMPORARY_OVERRIDE

Result:
保留 Stable
+
增加 Temporary Override
```

---

## B.3 “他们今天都忙，也没人和我说话”

M3：

```text
possible_loneliness
implicit_need = companionship
```

Memory Policy：

```text
MODEL_INFERRED psychological state

→ IGNORE for Long-Term
```

可以仅进入：

```text
Session Emotional Context
```

而不是：

```text
Long-Term:
User is lonely
```

---

# 附录 C：Memory 的最终权限模型

| 操作 | LLM | Rule/Policy |
|---|---:|---:|
| 发现候选 | ✓ | ✓ |
| 标准化文本 | ✓ | ✓ |
| 判断是否写入 | ✗ | ✓ |
| 判断 Scope | ✗ | ✓ |
| 判断 TEMPORARY / STABLE | ✗ | ✓ |
| 冲突分类 | 辅助可选 | ✓ 最终 |
| 覆盖旧 Memory | ✗ | ✓ |
| DEPRECATED | ✗ | ✓ |
| TTL | ✗ | ✓ |
| Promotion | ✗ | ✓ |
| Summary | ✓ | ✓校验 |

---

# 附录 D：M8 最终设计原则

最终固定：

```text
一、
LLM 是 Memory 的语义入口，
不是 Memory 的治理者。

二、
Candidate 不等于 Memory。

三、
一次行为不等于稳定偏好。

四、
一次情绪不等于长期人格。

五、
当前临时变化不等于长期偏好反转。

六、
Scope 和 Status 必须分离。

七、
长期 Memory 必须可修正、可降级、可过期。

八、
Memory 宁可少写，也不要长期写错。

九、
所有 Memory 决策必须可追踪到 Policy / Rule。

十、
下一轮 Agent 使用的不是“模型记得什么”，
而是“治理系统允许继续生效的 Memory”。
```

最终可以把 M8 Memory 概括为：

```text
LLM
负责“看懂什么可能值得记”

Memory Policy
负责“有没有资格记”

Conflict Resolver
负责“新旧记忆是什么关系”

Lifecycle Manager
负责“它现在处于什么状态”

Memory Store
负责“真正保存”
```

这才是整个长期陪护 Agent 的记忆治理核心。