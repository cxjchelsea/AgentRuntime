# 可复用 Agent Runtime 平台
# Agent Runtime Core Contract Canonical Registry V1.0

> **Phase 0 Fix 正式冻结文件**  
> 本文是首批 Core Contract 的**唯一正式来源**。  
> 自本文冻结起，任何阶段文档、Schema Registry 旧表、Frozen 子设计中与本文冲突的名称、字段、枚举、Owner 定义**立即失效**，不得再作为实现依据。  
> 本文不重新设计 Runtime 架构，不修改 10 节点主链，不修改 Truth Boundary，不修改 M0–M8 职责边界。

> **文档优先级（本轮已执行对齐）**  
> Runtime Invariants > 本文（首批 Contract 唯一来源）> Core Schema Registry（其余对象）> Frozen 子设计 > 阶段详细实现方案。

> **平台化原则**  
> Runtime Core 不得硬编码任何具体 Domain（陪护 / 医疗 / 教育 / 客服等）的身份、Intent、Action、Need、Strategy、业务状态。  
> 历史业务值一律降为 `Domain Example`，不得描述为 Frozen Core。

---

# 0. 本轮裁决摘要

## 0.1 名称裁决

| 旧称 / 歧义称 | 正式 canonical_name | 裁决 |
|---|---|---|
| ActionPlan | 禁止单独使用 | 必须写 `ActionPlanDraft` 或 `ApprovedActionPlan` |
| ActionPlan Draft | ActionPlanDraft | 去掉空格，作为 M4 内部对象 |
| Approved ActionPlan | ApprovedActionPlan | M5 唯一合法规划输入 |
| StateUpdate（作为链终点） | 失效 | 链终点仅为 `UpdateResult` |
| MemoryUpdate（作为链终点） | 失效 | 仅为 `UpdateResult.memory_update` |
| SafetyResult / EarlySafetyResult / DeepSafetyResult | SafetyResult 为唯一 Schema | 用 `phase` 区分；主链节点②使用 Early 实例 |
| elder_id | 从 Core 删除 | 改用 `subject_id` + `identity_scope` |
| user_scope | identity_scope | 与 elder_id 不再并列 |
| raw_asr_result | raw_text | 原始输入文本，模态无关 |
| PolicyDecision.reason | reason_codes[] | 禁止标量 reason |
| interrupt_required | interrupt_current_task | 统一布尔字段名 |
| ExecutionResult.status | plan_status | 执行计划状态 |
| facts_to_include / facts_to_avoid | claim_plan | 与 M6 ClaimPolicy 对齐 |
| UnderstandingState 扁平结构 | 失效 | 唯一采用嵌套结构 |
| RuntimeContext.business_context | domain_extensions | 可选领域挂载，不是 Core 业务对象 |

## 0.2 三类值边界（P0-B-003）

```text
Core Structural Types
= 跨领域对象结构、字段、关系

Core Control Enums
= Runtime 自身控制所必需的封闭枚举

Domain Registered Values
= 由 Domain Package 注册的业务值，禁止写入 Core 枚举表
```

---

# 1. 10 节点主链（不修改）

```text
RuntimeInput
 → ① Input Processor                 (M1)
 → ② Early Safety Guard              (M2)  → SafetyResult(phase=EARLY)
 → ③ Context Builder                 (M1)  → RuntimeContext
 → ④ Understanding Engine            (M3)  → UnderstandingState
 → ⑤ Policy / State Engine           (M2)  → PolicyDecision
 → ⑥ Planner / Orchestrator          (M4)  → ApprovedActionPlan
 → ⑦ Execution Engine                (M5)  → ExecutionResult
 → ⑧ Result Validator                (M6)  → ValidatedResult
 → ⑨ Response Engine                 (M7)  → ResponsePlan → RuntimeResponse
 → ⑩ State / Memory Update           (M8)  → UpdateResult
 → 下一轮 RuntimeContext
```

内部中间对象（不作为主链节点）：

```text
ActionPlanDraft
SafetyResult(phase=DEEP)
StateUpdate
MemoryUpdate
ExecutionContext
```

---

# 2. Core Identity / Domain Identity（P0-B-002）

## 2.1 硬边界

```text
Core Identity
!=
Domain Identity
```

Runtime Core 只认识通用主体与隔离范围。  
具体 `elder` / `patient` / `student` / `customer` 只能出现在 Domain Identity Extension，不得进入 Core 必填字段。

新增 Domain 不得修改本节字段语义。

## 2.2 CoreIdentity

canonical_name: `CoreIdentity`  
owner: M1  
producer: Input Normalizer  
consumer: M1–M8 / Memory / Trace  
lifecycle: Turn + Persistent Scope  
schema_version: `1.0.0`  
主链对象: 否（嵌入 RuntimeInput / RuntimeContext / ExecutionContext / MemoryRecord）  
内部中间对象: 否

```text
CoreIdentity

subject_id            required    本轮服务对象，领域中立
identity_scope        required    状态 / Memory / Trace 隔离键；默认等于 subject_id
actor_id              optional    触发者；缺省视为与 subject_id 相同
source                required    见 InputSource
device_id             optional    设备标识，不蕴含用户角色
tenant_id             optional    多租户隔离
```

禁止字段：

```text
elder_id
patient_id
student_id
customer_id
user_scope
```

## 2.3 DomainIdentityExtension

canonical_name: `DomainIdentityExtension`  
owner: M9  
producer: Domain Package  
consumer: Domain Rule / DomainState / Domain Eval  
lifecycle: Domain Release  
schema_version: `1.0.0`  
主链对象: 否

```text
DomainIdentityExtension

domain_id             required
subject_type          required    Domain 注册值，例如 elder / patient / student
domain_subject_ref    optional    Domain 业务侧编号
claims                optional    Domain Schema 扩展
```

只能通过 `RuntimeContext.domain_extensions.identity` 或等价 typed extension 挂载。  
不得提升为 Core 一等字段。

## 2.4 隔离不变量

```text
MemoryRecord.identity_scope
StateCommit.identity_scope
ExecutionContext.identity_scope
=
当前 RuntimeInput.identity_scope
```

禁止跨 `identity_scope` 读取或写入。

---

# 3. Core Structural Types

Core 冻结以下结构，不冻结其业务取值：

```text
IntentResult
IntentDefinition
Entity
NeedResult
NeedDefinition
ActionDefinition
StrategyDefinition
DomainStateDefinition
DomainSchemaReference
SafetyRuleReference
```

### 3.1 IntentResult

```text
IntentResult

intent_id             required    来自 IntentRegistry；Core Control 或 Domain 注册
confidence            required
source                required    EXPLICIT | INFERRED | RULE
evidence_ids[]        optional
```

### 3.2 IntentDefinition（Registry 项，非 Turn Contract）

```text
IntentDefinition

intent_id
version
scope                 CORE_CONTROL | DOMAIN
domain_id             optional    scope=DOMAIN 时必填
positive_examples[]
negative_examples[]
conflicts[]
```

### 3.3 DomainStateDefinition

```text
DomainStateDefinition

state_schema_id
domain_id
version
fields[]
allowed_transitions[]
```

Domain 业务阶段（播放中 / 求助中 / 不适采集等）只能出现在 DomainState，不能进入 Core RuntimeControlState。

---

# 4. Core Control Enums

以下枚举属于 Runtime 控制面，允许作为 Frozen Core。

## 4.1 InputSource

```text
USER
SYSTEM
SCHEDULER
TOOL
WORKFLOW
DEVICE
EXTERNAL
```

## 4.2 InputTriggerType

```text
USER_VOICE
USER_TEXT
USER_OTHER
SYSTEM_EVENT
SCHEDULER_EVENT
TOOL_CALLBACK
WORKFLOW_CALLBACK
TIMEOUT
NETWORK_EVENT
DEVICE_EVENT
```

失效：`voice` / `user_input` / `reminder` / `REMINDER_DUE` / `ACTIVE_GREETING` 作为 Core 枚举。  
后两者若出现，只能作为 Domain 对 `SCHEDULER_EVENT` / `SYSTEM_EVENT` 的 payload 细分，且必须标记 Domain Example。

## 4.3 IdentityStatus

```text
BOUND
UNBOUND
UNKNOWN
```

## 4.4 RuntimeControlState

```text
STARTING
IDLE
LISTENING
PROCESSING
RESPONDING
WAITING_USER
WAITING_EXTERNAL
INTERRUPTED
ENDED
FAILED
```

失效：`S00`–`S11`、`S90` 以及“内容播放中 / 情绪安抚中 / 求助处理中 / 不适采集中 / 提醒中”作为 Core 状态。

## 4.5 SafetyPhase

```text
EARLY
DEEP
```

## 4.6 SafetyRiskLevel

```text
NONE
LOW
MEDIUM
HIGH
CRITICAL
```

## 4.7 ValidationMode

```text
FAST
STANDARD
STRICT
```

## 4.8 PlanningMode

```text
FORCED
DETERMINISTIC
AGENT_PLANNED
DEGRADED
```

## 4.9 PlanApprovalStatus

```text
DRAFT
APPROVED
REJECTED
```

## 4.10 ExecutionPlanStatus

```text
SUCCESS
PARTIAL_SUCCESS
FAILED
TIMEOUT
CANCELLED
PREEMPTED
```

## 4.11 ValidationStatus

```text
VALIDATED
PARTIALLY_VALIDATED
NOT_VALIDATED
CONFLICTED
UNKNOWN
```

## 4.12 BusinessStatus

```text
SUCCESS
PARTIAL_SUCCESS
FAILED
WAITING
UNKNOWN
```

说明：`BusinessStatus` 是验证层对“业务目标是否达成”的通用判定，不是某个 Domain 的业务目录。

## 4.13 MemoryStatus

```text
STABLE
TEMPORARY
EMERGING
UNCERTAIN
DEPRECATED
```

## 4.14 TransitionStatus

```text
NOT_REQUIRED
PROPOSED
COMMITTED
REJECTED
DEFERRED
```

## 4.15 TaskStatus

```text
ACTIVE
WAITING_USER
WAITING_EXTERNAL
COMPLETED
CANCELLED
FAILED
EXPIRED
```

## 4.16 Core Control Intents

仅保留 Runtime 控制意图：

```text
UNKNOWN
STOP
CANCEL
HELP
```

`HELP` 只表示“用户请求运行时协助 / 升级”，不绑定任何求助 Workflow。具体求助流程由 Domain 注册。

## 4.17 SpeechAct

```text
REQUEST
QUESTION
STATEMENT
ANSWER
CONFIRMATION
REJECTION
CORRECTION
COMPLAINT
EMOTIONAL_EXPRESSION
GREETING
FAREWELL
COMMAND
UNCERTAIN
```

## 4.18 GenerationPath

```text
TEMPLATE
LLM
HYBRID
SILENT
```

## 4.19 ResponseType

```text
NORMAL
SHORT_ACK
RESULT_REPORT
CLARIFICATION
TASK_PROMPT
SAFETY_MESSAGE
CLOSING
SILENCE
SYSTEM_ERROR
```

## 4.20 Core Control Actions

Planner 可直接使用的跨领域控制动作：

```text
ACKNOWLEDGE
ANSWER
CLARIFY
WAIT
END
CONTINUE_TASK
ASK_REQUIRED_FIELD
CONFIRM_ACTION
COMPLETE_TASK
CANCEL_TASK
DEFER_TASK
CALL_TOOL
USE_MEMORY
ENTER_SAFETY_WORKFLOW
STOP_CURRENT_ACTIVITY
```

## 4.21 Core Control Strategies

```text
DIRECT_FULFILLMENT
CLARIFY_THEN_ACT
TASK_CONTINUATION
SAFETY_OVERRIDE
DEGRADED_FALLBACK
WAIT
END
```

---

# 5. Domain Registered Values

下列值**禁止**再被描述为 Frozen Core。它们属于 Domain Package 注册项，示例仅供理解机制。

## 5.1 Domain Intent Examples（禁止进 Core）

```text
PLAY_CONTENT
CONTROL_PLAYBACK
REMINDER_RESPONSE
QUIET_COMPANION
DISCOMFORT
COGNITIVE_INTERACTION
CHAT
EXPRESS_EMOTION
SHARE_EXPERIENCE
RECALL_EXPERIENCE
QUERY_INFORMATION
MEMORY_QUERY
MEMORY_SAVE_REQUEST
MEMORY_UPDATE_REQUEST
MEMORY_DELETE_REQUEST
ACTIVE_RESPONSE
```

## 5.2 Domain Action / Strategy Examples（禁止进 Core）

```text
PLAY_CONTENT
OFFER_CONTENT
CONTROL_PLAYBACK
START_COGNITIVE_ACTIVITY
SILENT_COMPANION
EMPATHIC_ACKNOWLEDGE
LISTENING_FIRST
QUIET_PRESENCE
ACKNOWLEDGE_THEN_EXPLORE
GENTLE_TOPIC_SHIFT
MEMORY_SUPPORTED_CONTINUATION
```

## 5.3 Domain Need Examples（禁止进 Core）

```text
COMPANIONSHIP
LISTENING
EMOTIONAL_ACKNOWLEDGEMENT
QUIET_PRESENCE
HUMAN_HELP
ENTERTAINMENT
REMEMBERING
ORIENTATION
```

## 5.4 DomainState Examples（禁止进 Core RuntimeControlState）

```text
内容播放中
情绪安抚中
求助处理中
不适采集中
提醒中
领域任务交互中
S06 / S07 / S08 / S09 / S10 / S11
```

## 5.5 Domain Identity Examples（禁止进 Core 一等字段）

```text
elder_id
patient_id
student_id
customer_id
```

---

# 6. 首批 Core Contract 总表

schema_version 除非另注，均为 `1.0.0`。

| canonical_name | Owner | Producer | Consumer | Lifecycle | 主链 | 内部中间对象 |
|---|---|---|---|---|---|---|
| RuntimeInput | M1 | Input Normalizer | M2 Early Safety / M3 / Trace | Turn | 是 | 否 |
| SafetyResult | M2 | Safety Guard | M1 Context / M3 / M2 Deep / Trace | Turn | 是（仅 EARLY） | DEEP 为内部 |
| RuntimeContext | M1 | Context Builder | M2 / M3 / M4 / M7 | Turn | 是 | 否 |
| UnderstandingState | M3 | Understanding Orchestrator | M2 Post-Policy / M4 / M8 | Turn | 是 | 否 |
| PolicyDecision | M2 | Policy / State / Safety Engine | M4 / M5 | Turn / Event | 是 | 否 |
| ActionPlanDraft | M4 | Planner | Plan Validator / M2 Re-check | Turn | 否 | 是 |
| ApprovedActionPlan | M4 | Plan Validator + Policy Re-check | M5 | Turn | 是 | 否 |
| ExecutionResult | M5 | Execution Framework | M6 | Execution / Trace | 是 | 否 |
| ValidatedResult | M6 | Result Validator | M7 / M8 | Turn / Trace | 是 | 否 |
| ResponsePlan | M7 | Response Planner | Response Generator | Turn | 否 | 是 |
| RuntimeResponse | M7 | Response Generator + Validator | User / M8 | Turn | 是 | 否 |
| StateUpdate | M8 | State Updater | UpdateResult 内部 | Turn | 否 | 是 |
| MemoryUpdate | M8 | Memory Updater | UpdateResult 内部 | Turn | 否 | 是 |
| UpdateResult | M8 | State & Memory Updater | Next M1 / Trace | Turn / Trace | 是 | 否 |

M5 **只能**消费 `ApprovedActionPlan`。  
M8 主链终点 **只能**是 `UpdateResult`。

---

# 7. RuntimeInput

- canonical_name: `RuntimeInput`
- owner: M1
- producer: Input Normalizer
- consumer: M2 Early Safety Guard, M3 Understanding, Trace
- lifecycle: Turn
- schema_version: `1.0.0`
- 主链对象: 是
- 内部中间对象: 否

## 7.1 required

```text
schema_version
request_id
trace_id
session_id
subject_id
identity_scope
source
trigger_type
timestamp
```

## 7.2 optional

```text
actor_id
device_id
tenant_id
input_type
text
raw_text
input_payload
confidence
segments
metadata
```

## 7.3 enum / type references

```text
source          → InputSource
trigger_type    → InputTriggerType
```

## 7.4 禁止字段

```text
elder_id
raw_asr_result
```

`text` 是标准化后的可见文本；`raw_text` 是标准化前原文。二者都不是用户意图。

---

# 8. SafetyResult

- canonical_name: `SafetyResult`
- owner: M2
- producer: Safety Guard
- consumer: 见 phase
- lifecycle: Turn
- schema_version: `1.0.0`
- 主链对象: `phase=EARLY` 时是；`phase=DEEP` 时否
- 内部中间对象: `phase=DEEP` 时是

`EarlySafetyResult` 与 `DeepSafetyResult` **不是独立 Schema**，只是同一 `SafetyResult` 的 phase 别名。

```text
EarlySafetyResult  = SafetyResult where phase = EARLY     # 节点②，进入主链
DeepSafetyResult   = SafetyResult where phase = DEEP      # M2 内部，供 Policy 聚合
```

## 8.1 required

```text
schema_version
safety_result_id
request_id
phase
risk_detected
risk_level
interrupt_current_task
allowed_to_continue_normal_flow
safety_lock_required
reason_codes[]
created_at
```

## 8.2 optional

```text
risk_types[]
matched_rules[]
evidence
confidence
force_workflow
requires_immediate_action
restricted_actions[]
```

## 8.3 enum / type references

```text
phase       → SafetyPhase
risk_level  → SafetyRiskLevel
```

`risk_types[]` / `matched_rules[]` 引用 Safety Rule Registry，不在 Core 冻结具体业务风险名。

---

# 9. RuntimeContext

- canonical_name: `RuntimeContext`
- owner: M1
- producer: Context Builder
- consumer: M2, M3, M4, M7
- lifecycle: Turn
- schema_version: `1.0.0`
- 主链对象: 是
- 内部中间对象: 否

## 9.1 required

```text
schema_version
identity_context
session_context
runtime_state_context
```

## 9.2 optional

```text
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

`relationship_context` 不再作为 Core 必选子上下文。若 Domain 需要关系信息，放入 `domain_extensions`。

## 9.3 identity_context required

```text
subject_id
identity_scope
identity_status
```

optional: `actor_id`, `device_id`, `tenant_id`, `language_preference`

禁止: `elder_id`, `preferred_addressing` 作为 Core 必填。后者若出现必须在 Domain Extension。

## 9.4 runtime_state_context required

```text
current_state          → RuntimeControlState
previous_state         → RuntimeControlState | null
interruptible
entered_at
```

optional:

```text
active_task_id
active_workflow_id
interaction_mode
pending_question_id
runtime_flags[]
```

禁止: `current_business` 作为 Core 字段。业务阶段放入 `domain_extensions.domain_state`。

## 9.5 domain_extensions

```text
domain_extensions

domain_id
identity              → DomainIdentityExtension
domain_state          → DomainState payload（符合已注册 DomainStateDefinition）
extra                 optional
```

这是 DomainState 在 Core Context 上的唯一挂载点。

---

# 10. UnderstandingState

- canonical_name: `UnderstandingState`
- owner: M3
- producer: Understanding Orchestrator
- consumer: M2 PostUnderstandingPolicy, M4 Planner, M8 Memory Candidate Processor
- lifecycle: Turn
- schema_version: `1.0.0`
- 主链对象: 是
- 内部中间对象: 否

唯一正式结构为**嵌套结构**。M0 扁平字段（`explicit_intents` / `emotion_intensity` / `ambiguity`）失效。

## 10.1 required

```text
schema_version
metadata
intents[]
uncertainty
quality
```

`intents[]` 在 M0 Stub 中至少包含 `{intent_id: UNKNOWN}`。

## 10.2 optional

```text
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

## 10.3 metadata required

```text
understanding_id
request_id
schema_version
timestamp
processing_path          FAST_PATH | DEEP_PATH | HYBRID_PATH | DEGRADED_PATH
```

optional: `model_version`, `prompt_version`

## 10.4 intents

每个元素为 `IntentResult`。  
`intent_id` 必须存在于 Intent Registry（Core Control 或当前 Domain）。

禁止把 Domain Intent 例子写成 Core 枚举表。

---

# 11. PolicyDecision

- canonical_name: `PolicyDecision`
- owner: M2
- producer: Policy / State / Safety Engine
- consumer: M4, M5
- lifecycle: Turn / Event
- schema_version: `1.0.0`
- 主链对象: 是
- 内部中间对象: 否

## 11.1 required

```text
schema_version
policy_decision_id
allowed
blocked
priority
interrupt_current_task
validation_mode
reason_codes[]
created_at
```

## 11.2 optional

```text
forced_workflow
forced_action
allowed_actions[]
forbidden_actions[]
allowed_skills[]
forbidden_skills[]
allowed_tools[]
forbidden_tools[]
confirmation_required
response_constraints
policy_flags[]
```

## 11.3 统一规则

```text
reason                 失效，改 reason_codes[]
interrupt_required     失效，改 interrupt_current_task
forbidden_skills       保留为 optional，与 allowed_skills 成对
```

`allowed=false` 时 `blocked=true`，二者不得同时为 true 的相反组合缺失。

---

# 12. ActionPlanDraft

- canonical_name: `ActionPlanDraft`
- owner: M4
- producer: Planner
- consumer: Plan Validator, M2 Policy Re-check
- lifecycle: Turn
- schema_version: `1.0.0`
- 主链对象: 否
- 内部中间对象: 是

## 12.1 required

```text
schema_version
plan_id
request_id
approval_status          必须 = DRAFT
planning_mode
goals[]
steps[]
quality
```

## 12.2 optional

```text
strategy
memory_usage
capability_plan
tool_plan
confirmation_plan
response_strategy
state_intent
stop_conditions[]
fallback_plan
trace
```

M5 **不得**消费本对象。

---

# 13. ApprovedActionPlan

- canonical_name: `ApprovedActionPlan`
- owner: M4
- producer: Plan Validator + M2 Policy Re-check
- consumer: M5
- lifecycle: Turn
- schema_version: `1.0.0`
- 主链对象: 是
- 内部中间对象: 否

M2 只做校验与否决，不重新定义规划语义。主 Owner 唯一为 M4。

## 13.1 required

```text
schema_version
plan_id
request_id
approval_status          必须 = APPROVED
planning_mode
goals[]
steps[]
policy_snapshot
quality
```

## 13.2 optional

与 ActionPlanDraft 的 optional 相同，另可含 `approved_at`。

## 13.3 禁止

```text
使用名称 ActionPlan
把 Draft 直接交给 M5
Planner 发明未注册 Action / Skill / Workflow / Tool
```

`steps[].action` 只能是 Core Control Action 或 Domain 已注册 Action。

---

# 14. ExecutionResult

- canonical_name: `ExecutionResult`
- owner: M5
- producer: Execution Framework
- consumer: M6
- lifecycle: Execution / Trace
- schema_version: `1.0.0`
- 主链对象: 是
- 内部中间对象: 否

## 14.1 required

```text
schema_version
execution_id
plan_id
request_id
identity_scope
plan_status
step_results[]
timing
```

## 14.2 optional

```text
skill_results[]
workflow_result
tool_results[]
business_outputs[]
execution_events[]
state_observations[]
errors[]
cancellation
quality
```

## 14.3 层次

```text
ExecutionResult.plan_status
        ↓
step_results[]
        ↓
skill_results[] / workflow_result
        ↓
tool_results[]
```

## 14.4 失效字段

```text
status                  改 plan_status
executed_skill          改 skill_results[]
executed_workflow       改 workflow_result
business_result         改 business_outputs[]
elder_id                改 identity_scope
```

`plan_status` ≠ `BusinessStatus`。执行成功不等于业务成功。

---

# 15. ValidatedResult

- canonical_name: `ValidatedResult`
- owner: M6
- producer: Result Validator
- consumer: M7, M8
- lifecycle: Turn / Trace
- schema_version: `1.0.0`
- 主链对象: 是
- 内部中间对象: 否

## 15.1 required

```text
schema_version
validation_id
execution_id
request_id
validation_status
business_status
claim_policy
```

## 15.2 optional

```text
goal_validation
verified_facts[]
unverified_facts[]
conflicting_facts[]
followup
state_recommendation
validation_errors[]
quality
```

`claim_policy` 至少包含 `allowed_claims[]` 与 `forbidden_claims[]`。

---

# 16. ResponsePlan

- canonical_name: `ResponsePlan`
- owner: M7
- producer: Response Planner
- consumer: Response Generator
- lifecycle: Turn
- schema_version: `1.0.0`
- 主链对象: 否
- 内部中间对象: 是

主链⑨的对外输出是 `RuntimeResponse`。`ResponsePlan` 是 M7 内部计划。

## 16.1 required

```text
schema_version
response_plan_id
request_id
response_requirement
claim_plan
```

## 16.2 optional

```text
communicative_goals[]
content_plan
tone_profile
length_policy
question_plan
memory_expression
safety_constraints
tts_constraints
generation_path
```

## 16.3 claim_plan required 语义

```text
must_include_claims[]     必须表达且不得提高确定性
optional_claims[]
forbidden_claims[]        任何生成路径不得出现
required_qualifiers[]
```

## 16.4 失效字段

```text
facts_to_include    → claim_plan.must_include_claims
facts_to_avoid      → claim_plan.forbidden_claims
content_constraints → content_plan / safety_constraints
```

M4 的 `response_strategy` ≠ 本对象。前者是沟通策略意图，后者是可执行表达计划。

---

# 17. RuntimeResponse

- canonical_name: `RuntimeResponse`
- owner: M7
- producer: Response Generator + Response Validator
- consumer: User / Application, M8
- lifecycle: Turn
- schema_version: `1.0.0`
- 主链对象: 是
- 内部中间对象: 否

## 17.1 required

```text
schema_version
response_id
request_id
response_type
payload
response_validation_status
```

## 17.2 optional

```text
tts_payload
question
trace
```

`payload` 不得包含 `forbidden_claims`。  
本对象不能自动成为 Long-Term Memory。

---

# 18. StateUpdate

- canonical_name: `StateUpdate`
- owner: M8
- producer: State Updater
- consumer: UpdateResult 聚合器
- lifecycle: Turn
- schema_version: `1.0.0`
- 主链对象: 否
- 内部中间对象: 是

## 18.1 required

```text
schema_version
previous_state           RuntimeControlState | null
proposed_state           RuntimeControlState
transition_status
```

## 18.2 optional

```text
committed_state
transition_event
transition_reason_codes[]
evidence_ids[]
domain_state_update      DomainState mutation，必须符合已注册 Schema
```

禁止把 Domain 业务状态写入 `proposed_state` / `committed_state`。

---

# 19. MemoryUpdate

- canonical_name: `MemoryUpdate`
- owner: M8
- producer: Memory Updater
- consumer: UpdateResult 聚合器
- lifecycle: Turn
- schema_version: `1.0.0`
- 主链对象: 否
- 内部中间对象: 是

## 19.1 required

```text
schema_version
identity_scope
```

## 19.2 optional

```text
candidates[]
writes[]
updates[]
deletes[]
ignored[]
reason_codes[]
```

M0 Stub 允许 `writes=[]`。  
LLM 不得单独决定 WRITE / STABLE / DELETE。

---

# 20. UpdateResult

- canonical_name: `UpdateResult`
- owner: M8
- producer: State & Memory Updater
- consumer: Next M1 Context Builder, Trace
- lifecycle: Turn / Trace
- schema_version: `1.0.0`
- 主链对象: 是（节点⑩终点）
- 内部中间对象: 否

## 20.1 required

```text
schema_version
update_id
request_id
identity_scope
state_update             StateUpdate
commit_result
```

## 20.2 optional

```text
task_update
conversation_update
interaction_update
session_update
event_update
memory_update            MemoryUpdate
quality
```

`commit_result` 必须区分 ATOMIC / PARTIAL / REJECTED。部分提交是合法状态。

---

# 21. ExecutionContext（支撑对象，非本轮主链节点）

- canonical_name: `ExecutionContext`
- owner: M5
- producer: Execution Orchestrator
- consumer: M5 internal
- lifecycle: Execution
- schema_version: `1.0.0`
- 主链对象: 否
- 内部中间对象: 是

required:

```text
schema_version
execution_id
plan_id
request_id
session_id
identity_scope
policy_snapshot
```

optional: `device_id`, `current_state`, `step_state`, `tool_context`, `deadline`, `cancellation_token`, `trace_context`

禁止: `elder_id`

---

# 22. Deprecated / Replaced

| 失效项 | 替换为 | 生效范围 |
|---|---|---|
| ActionPlan（单独使用） | ActionPlanDraft 或 ApprovedActionPlan | 全部文档 |
| ActionPlan Draft（带空格） | ActionPlanDraft | 全部文档 |
| StateUpdate 作为主链终点 | UpdateResult | 总体设计 / M0 |
| MemoryUpdate 作为主链终点 | UpdateResult.memory_update | 总体设计 / M0 |
| EarlySafetyResult 独立 Schema | SafetyResult.phase=EARLY | M2 / M3 |
| DeepSafetyResult 独立 Schema | SafetyResult.phase=DEEP | M2 |
| elder_id | subject_id + identity_scope | Core 全部 |
| user_scope | identity_scope | Core 全部 |
| raw_asr_result | raw_text | RuntimeInput |
| source=voice / user_input 等小写集 | InputSource / InputTriggerType | M1 |
| REMINDER_DUE / ACTIVE_GREETING 作为 Core trigger | SCHEDULER_EVENT / SYSTEM_EVENT | Core Enum |
| UnderstandingState 扁平字段 | 嵌套结构 | M0 |
| PolicyDecision.reason | reason_codes[] | M0 |
| interrupt_required | interrupt_current_task | M2 |
| ExecutionResult.status | plan_status | M0 |
| executed_skill / executed_workflow / business_result | skill_results / workflow_result / business_outputs | M0 |
| facts_to_include / facts_to_avoid | claim_plan | M0 / M7 |
| RuntimeContext.business_context | domain_extensions | M0 |
| current_business（Core 状态字段） | domain_extensions.domain_state | M1 / M2 |
| preferred_addressing 作为 Core 必填 | DomainIdentityExtension | IdentityContext |
| S00–S11 / S90 作为 Core 状态机 | RuntimeControlState + DomainState | M2 |
| PLAY_CONTENT 等 Domain Intent / Action / Need / Strategy | Domain Registry | Schema Registry / M3 / M4 |
| COMPANIONSHIP / QUIET_PRESENCE / HUMAN_HELP / LISTENING_FIRST | Domain Registry | Schema Registry / M3 / M4 |

---

# 23. 实现约束（给 M0，不在本轮写代码）

```text
1. 代码中的类型名必须与 canonical_name 完全一致。
2. 不得定义名为 ActionPlan 的类型。
3. 不得定义名为 elder_id 的 Core 字段。
4. 不得把 Domain Example 写成 Core Enum class。
5. M0 允许 Stub，但 Stub 也必须使用本文字段名。
6. 每个对象必须带 schema_version = 1.0.0。
7. Breaking Change 必须提升 Major Version，并先改本文。
```

---

# 24. Phase 0 Fix Gate

```text
G3  首批 Contract 名称 / 字段 / 枚举唯一     PASS（以本文为准）
G4  Owner / Producer / Consumer 唯一一致     PASS
G10 RuntimeState 枚举已去领域化              PASS
G11 Core 无产品专属硬编码                    PASS
G12 文档冲突以本文为唯一胜出定义             PASS（同步完成后）
G14 ARCHITECTURE_BASELINE_FROZEN             PASS
```

---

# 25. 最终原则

```text
一个核心概念只有一个 canonical_name。
一个主链节点只有一个正式输出对象。
一个身份字段不得携带 Domain 角色语义。
一个 Core Enum 不得包含 Domain 业务值。
Example 永远不是 Frozen Core。
```
