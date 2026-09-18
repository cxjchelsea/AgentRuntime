# 可复用 Agent Runtime 平台  
# Agent Runtime Core Schema Registry V1.0

> **Phase 0 Fix**  
> 首批 Core Contract 的唯一正式来源已切换为：  
> `可复用Agent Runtime平台 Agent Runtime Core Contract Canonical Registry V1.0.md`  
> 本文中与 Canonical Registry 冲突的名称、字段、枚举、Owner **立即失效**。  
> 本文继续作为其余支撑对象（TaskContext、MemoryRecord、RuntimeEvent 等）的登记册。

> **平台化转换说明**  
> 本文已从单一业务 Agent 设计转换为 **可复用 Agent Runtime 平台**设计。除明确标记为 `Core` 的对象、接口、不变量和生命周期外，任何具体业务 Intent、Entity、Workflow、Skill、Tool、知识域、状态字段、规则、提示词或示例均视为 **Domain Package 示例**，不得硬编码进 Runtime Core。新项目应通过 Registry / Adapter / Plugin / Config 注入领域差异。
> 
> 平台固定边界：`Runtime Core` 尽量稳定；`Domain Extension` 插件化；`Business Package` 配置化；`Application` 负责产品装配。

---

# 0. 文档定位

本文件是可复用 Agent Runtime 平台 Runtime 的：

```text
Global Data Contract Registry
```

即：

```text
全局数据契约总表
```

其作用是统一 M0–M9 中所有核心数据对象的：

```text
名称
职责
Owner
Producer
Consumer
核心字段
状态枚举
Truth Level
生命周期
版本
Frozen状态
```

从本文件冻结以后：

```text
各阶段详细设计
可以补充实现细节，

但不得自行修改核心 Schema 语义。
```

若后续确需修改核心 Contract：

```text
必须修改本 Registry
+
修改对应阶段规范
+
执行兼容性评审
+
执行回归测试
```

---


## 平台扩展补充：Schema Extension Contract

Core Schema Registry 只冻结跨领域对象。所有领域对象必须进入 `Domain Schema Registry`，并通过 typed extension / domain payload / reference 接入 Core Contract。新增 Domain 不应修改 Core Schema 的既有字段语义。

# 1. 全局核心链

整个 Agent Runtime 的数据主链正式固定为：

```text
Raw Input
    ↓
RuntimeInput
    ↓
SafetyResult(phase=EARLY)
    ↓
RuntimeContext
    ↓
UnderstandingState
    ↓
PolicyDecision
    ↓
ApprovedActionPlan
    ↓
ExecutionResult
    ↓
ValidatedResult
    ↓
ResponsePlan            # M7 内部
    ↓
RuntimeResponse
    ↓
UpdateResult
    ↓
下一轮 RuntimeContext
```

禁止使用歧义名称 `ActionPlan`。`ActionPlanDraft` 不进入主链。`StateUpdate` / `MemoryUpdate` 不是链终点。

其中：

```text
RuntimeInput
=
本轮进入系统的标准输入

RuntimeContext
=
系统当前已知背景

UnderstandingState
=
系统如何理解用户

PolicyDecision
=
当前允许做什么、禁止做什么

ApprovedActionPlan
=
本轮批准执行什么

ExecutionResult
=
实际执行了什么

ValidatedResult
=
系统真正确认发生了什么

ResponsePlan
=
准备怎么表达

RuntimeResponse
=
系统实际说了什么

UpdateResult
=
本轮真正留下了什么
```

---

# 2. 全局 Truth Boundary

所有数据对象必须遵守：

```text
Model Output
!= Runtime State
!= Tool Result
!= Business Truth
!= User-facing Claim
```

进一步：

```text
Understanding
!= Decision

Decision
!= Execution

Execution
!= Validation

Validation
!= Response

Response
!= Persistent State
```

---

# 3. Contract Owner 原则

每个核心对象必须存在唯一主要 Owner。

其他模块：

```text
可以读取
可以验证
可以消费
```

但不能：

```text
重新定义其语义。
```

---

# 4. 全局 Contract 总览

| Contract | Owner | Producer | Primary Consumer | 生命周期 | Frozen |
|---|---|---|---|---|---|
| RuntimeInput | M1 | Input Normalizer | M2 Early Safety / M3 / Trace | Turn | YES |
| SafetyResult | M2 | Safety Guard | M1 / M3 / M2 Deep / Trace | Turn | YES |
| RuntimeContext | M1 | Context Builder | M2 / M3 / M4 / M7 | Turn | YES |
| UnderstandingState | M3 | Understanding Orchestrator | M2 Post-Policy / M4 / M8 | Turn | YES |
| PolicyDecision | M2 | Policy / State / Safety Engine | M4 / M5 | Turn / Event | YES |
| ActionPlanDraft | M4 | Planner | Plan Validator / M2 Re-check | Turn | YES |
| ApprovedActionPlan | M4 | Plan Validator + Policy Re-check | M5 | Turn | YES |
| ExecutionContext | M5 | Execution Orchestrator | M5 internal | Execution | YES |
| ExecutionResult | M5 | Execution Framework | M6 | Execution | YES |
| ValidatedResult | M6 | Result Validator | M7 / M8 | Turn | YES |
| ResponsePlan | M7 | Response Planner | Response Generator | Turn | YES |
| RuntimeResponse | M7 | Response Generator + Validator | User / M8 | Turn | YES |
| StateUpdate | M8 | State Updater | UpdateResult 内部 | Turn | YES |
| MemoryUpdate | M8 | Memory Updater | UpdateResult 内部 | Turn | YES |
| UpdateResult | M8 | State & Memory Updater | Next M1 / Trace | Turn | YES |
| RuntimeEvent | M0/M2 | Runtime / External Sources | M2 / Workflow | Event | YES |
| TaskContext | M1/M8 | Task Store | M1 / M3 / M4 | Cross-turn | YES |
| PendingQuestion | M8 | RuntimeResponse Commit | M1 / M3 | Cross-turn | YES |
| MemoryRecord | M8 / Memory Service | Memory Lifecycle | M1 / M3 / M4 | Cross-session | YES |
| ToolResult | M5 | Tool Executor | M5 / M6 | Execution | YES |
| WorkflowInstance | M5 | Workflow Engine | M5 / M8 | Cross-turn | YES |
| BusinessCapabilityDefinition | M9 | Capability Registry | M3–M8 | Release | YES |

---

# 第一部分
# Input & Context Contracts

# 5. RuntimeInput

## Owner

```text
M1 Input & Context
```

## Producer

```text
Input Normalizer
```

## Consumers

```text
M2 PreSafetyGuard

M3 Understanding

Trace
```

---

## 5.1 Schema

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

`elder_id` 已从 Core 删除。身份以 Canonical Registry `CoreIdentity` 为准。

---

## 5.2 source

核心枚举：

```text
USER

SYSTEM

SCHEDULER

TOOL

WORKFLOW

DEVICE

EXTERNAL
```

---

## 5.3 trigger_type

核心枚举：

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

`REMINDER_DUE` / `ACTIVE_GREETING` 不是 Core 枚举。它们只可作为 Domain 对 `SCHEDULER_EVENT` / `SYSTEM_EVENT` 的 payload 细分（Domain Example）。

---

## 5.4 Truth Level

```text
Normalized Input Fact
```

注意：

```text
RuntimeInput.text
!=
用户真实意图
```

语义理解属于 M3。

---

## 5.5 生命周期

```text
Turn
```

---

# 6. RuntimeContext

## Owner

```text
M1
```

## Producer

```text
ContextBuilder
```

## Consumers

```text
M2
M3
M4
M7
```

---

## 6.1 Schema

```text
RuntimeContext

identity_context

session_context

runtime_state_context

conversation_context

task_context

time_context

relationship_context

memory_context

safety_context

tool_context

interaction_context

environment_context

missing_context[]
```

---

# 7. IdentityContext

```text
IdentityContext

subject_id
identity_scope
identity_status
actor_id
device_id
tenant_id
language_preference
```

`elder_id` / `preferred_name` / `preferred_addressing` / `room_id` 不是 Core 字段。若 Domain 需要，放入 `domain_extensions.identity`。

---

## 7.1 identity_status

```text
BOUND

UNBOUND

UNKNOWN
```

---

# 8. SessionContext

```text
SessionContext

session_id

started_at

last_active_at

turn_index

session_type

current_topic

session_summary

ended
```

---

# 9. RuntimeStateContext

```text
RuntimeStateContext

current_state          → RuntimeControlState
previous_state
active_task_id
active_workflow_id
interaction_mode
interruptible
pending_question_id
runtime_flags[]
entered_at
```

`current_business` 已从 Core 删除。业务阶段进入 `domain_extensions.domain_state`。

---

# 10. ConversationContext

```text
ConversationContext

recent_turns[]

current_topic

topic_history[]

pending_reference

pending_question

last_user_message

last_agent_action

conversation_stage
```

---

# 11. TaskContext

```text
TaskContext

task_id

task_type

active_task

task_stage

required_fields[]

collected_fields[]

next_required_field

timeout_at

status
```

---

# 12. TimeContext

```text
TimeContext

current_datetime

date

weekday

time_of_day

quiet_period

special_date

active_time_window
```

---

# 13. RelationshipContext

```text
RelationshipContext

preferred_addressing

important_people[]

current_relationship_topics[]

recent_person_mentions[]

interaction_preferences[]
```

---

# 14. MemoryContext

```text
MemoryContext

retrieved_memories[]

memory_query

retrieval_reason

memory_confidence

memory_status

service_status
```

---

## 14.1 service_status

建议：

```text
AVAILABLE

UNAVAILABLE

DEGRADED
```

必须区分：

```text
UNAVAILABLE
!=
NO_MEMORY
```

---

# 15. SafetyContext

```text
SafetyContext

current_risk_state

active_safety_event

recent_safety_event

safety_lock

restricted_actions[]
```

---

# 16. ToolContext

```text
ToolContext

active_tool_calls[]

recent_tool_results[]

playback_status

notification_status

network_status
```

---

# 17. InteractionContext

```text
InteractionContext

last_agent_action

last_response_strategy

recent_questions_count

recent_questions[]

recent_suggestions[]

recent_rejections[]

recent_active_interactions[]

silence_mode

quiet_until

user_interrupt_count
```

---

# 18. EnvironmentContext

```text
EnvironmentContext

network_status

audio_status

speaker_status

microphone_status

battery_status
```

---

# 第二部分
# Understanding Contracts

# 19. UnderstandingState

## Owner

```text
M3 Understanding
```

## Producer

```text
Understanding Orchestrator
```

## Consumers

```text
M2 PostUnderstandingPolicy
M4 Planner
M8 Memory Candidate Processor
```

---

## 19.1 Schema

```text
UnderstandingState

metadata

semantic

intents

goal

entities

references

topic

emotion

needs

interaction

risk

uncertainty

evidence

memory_candidates

candidate_actions

quality
```

---

# 20. Understanding metadata

```text
understanding_id

request_id

schema_version

model_version

prompt_version

processing_path

timestamp
```

---

## 20.1 processing_path

```text
FAST_PATH

DEEP_PATH

HYBRID_PATH

DEGRADED_PATH
```

---

# 21. SemanticUnderstanding

```text
semantic

speech_act

normalized_meaning

negation

confirmation

correction

entities[]
```

---

# 22. SpeechAct

核心枚举：

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

---

# 23. Intent Contract

Core 只冻结 `IntentResult` 结构与 **Core Control Intents**：

```text
UNKNOWN
STOP
CANCEL
HELP
```

下列历史值降为 **Domain Example**，必须由 Domain Package 注册，不再是 Frozen Core：

```text
# Domain Example — 不得写入 Core Enum
CHAT
GREETING
FAREWELL
EXPRESS_EMOTION
QUIET_COMPANION
SHARE_EXPERIENCE
RECALL_EXPERIENCE
PLAY_CONTENT
CONTROL_PLAYBACK
DISCOMFORT
REMINDER_RESPONSE
COGNITIVE_INTERACTION
QUERY_INFORMATION
MEMORY_QUERY
MEMORY_SAVE_REQUEST
MEMORY_UPDATE_REQUEST
MEMORY_DELETE_REQUEST
ACTIVE_RESPONSE
```

---

# 24. GoalUnderstanding

```text
goal

explicit_goal

implicit_need

goal_parameters

confidence

needs_clarification
```

---

# 25. Entity

```text
Entity

entity_type

value

normalized_value

status

confidence

source
```

---

## 25.1 Entity status

```text
EXPLICIT

INFERRED

RESOLVED

UNCERTAIN

NEGATED

SUPERSEDED
```

---

# 26. Reference

```text
Reference

reference_text

reference_type

resolved_target

status

source

confidence
```

---

## 26.1 Reference status

```text
RESOLVED

AMBIGUOUS

UNRESOLVED
```

---

# 27. EmotionState

```text
emotion

primary_emotion

secondary_emotions[]

intensity

possible_cause

confidence

explicit_or_inferred
```

---

# 28. Emotion Core Taxonomy

```text
JOY
CALM
INTEREST
SADNESS
LONELINESS
ANXIETY
FEAR
ANGER
IRRITATION
FRUSTRATION
DISAPPOINTMENT
HELPLESSNESS
GUILT
SHAME
GRIEF
EMPTINESS
BOREDOM
UNCERTAIN
UNKNOWN
```

---

# 29. Need Contract

```text
needs[]                 → NeedResult[]
```

Core 只冻结 `NeedResult` / `NeedDefinition` 结构。  
下列历史值是 **Domain Example**，不是 Frozen Core：

```text
# Domain Example
COMPANIONSHIP
LISTENING
EMOTIONAL_ACKNOWLEDGEMENT
EXPRESSION
REASSURANCE
QUIET_PRESENCE
INFORMATION
ACTION_HELP
ENTERTAINMENT
REMEMBERING
ORIENTATION
AUTONOMY
HUMAN_HELP
UNKNOWN
```

---

# 30. InteractionUnderstanding

```text
interaction

engagement

willingness_to_talk

willingness_for_suggestion

need_for_silence

frustration_with_agent

conversation_fatigue
```

---

# 31. RiskSignal

```text
risk

signals[]

confidence

requires_safety_review
```

注意：

```text
RiskSignal
!=
Safety Decision
```

最终 Authority 在 M2。

---

# 32. Uncertainty

```text
uncertainty

uncertain_fields[]

candidate_interpretations[]

needs_clarification

safe_to_infer
```

---

# 33. Uncertainty Type

核心：

```text
LOW_ASR_CONFIDENCE

AMBIGUOUS_REFERENCE

MULTIPLE_INTENTS

UNCLEAR_GOAL

UNCERTAIN_EMOTION

CONFLICTING_CONTEXT

MISSING_CONTEXT

UNCLEAR_CONFIRMATION

UNKNOWN_ENTITY
```

---

# 34. Understanding Evidence

```text
UnderstandingEvidence

evidence_type

source

reference

confidence
```

注意：

```text
这不是 M6 ValidationEvidence。
```

二者语义不同：

```text
M3 Evidence
=
为什么这样理解用户

M6 Evidence
=
为什么认定真实世界事实成立
```

---

# 35. MemoryCandidate

```text
MemoryCandidate

candidate_id

memory_type

content

structured_value

source

confidence

suggested_scope

sensitivity
```

注意：

```text
MemoryCandidate
!=
MemoryRecord
```

---

# 36. CandidateAction

```text
CandidateAction

action

target

confidence

reason_code
```

仅为：

```text
semantic affordance
```

不是最终 ApprovedActionPlan。

---

# 第三部分
# Policy & State Contracts

# 37. PolicyDecision

## Owner

```text
M2
```

## Producer

```text
Policy / State / Safety Engine
```

## Consumers

```text
M4
M5
```

---

## 37.1 Schema

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
response_constraints
policy_flags[]
```

`reason` 与 `interrupt_required` 已失效。

---

# 38. ValidationMode

```text
FAST

STANDARD

STRICT
```

---

# 39. forced_workflow

一旦存在：

```text
M4普通Planner不得覆盖。
```

---

# 40. SafetyLock

```text
SafetyLock

lock_id

owner

reason

acquired_at

expires_at

reentrant

release_condition

status
```

---

## 40.1 status

```text
ACTIVE

RELEASED

EXPIRED

RECOVERY_REQUIRED
```

---

# 40A. SafetyResult

首批正式 Schema 以 Canonical Registry 为准。`SafetyResult` 是唯一 Schema：

```text
SafetyResult

schema_version
safety_result_id
request_id
phase                      EARLY | DEEP
risk_detected
risk_level                 NONE | LOW | MEDIUM | HIGH | CRITICAL
interrupt_current_task
allowed_to_continue_normal_flow
safety_lock_required
reason_codes[]
created_at
```

```text
EarlySafetyResult = SafetyResult where phase = EARLY    # 主链节点②
DeepSafetyResult  = SafetyResult where phase = DEEP     # M2 内部
```

二者不是独立 Schema。

---

# 41. RuntimeEvent

## Owner

```text
M0 / M2 Runtime
```

---

## 41.1 Schema

```text
RuntimeEvent

event_id

event_type

source

generated_at

received_at

priority

payload

dedupe_key

status
```

---

# 42. RuntimeEvent status

```text
NEW

PROCESSING

HANDLED

DEFERRED

DROPPED

EXPIRED
```

---

# 第四部分
# Planning Contracts

# 43. ActionPlanDraft

## Owner

```text
M4
```

---

## 43.1 Draft 与 Approved 区别

```text
ActionPlanDraft
=
Planner 输出，尚未最终批准
approval_status = DRAFT
不得进入 M5

ApprovedActionPlan
=
Schema / Capability / Policy 校验通过后
允许进入 M5 的正式计划
approval_status = APPROVED
```

禁止再使用歧义名称 `ActionPlan`。

M4-CA1 后：

```text
ActionPlanDraft schema_version default = 1.1.0
ApprovedActionPlan schema_version default = 1.1.0
旧 1.0.0 payload = backward compatible input
```

M5 只接受：

```text
ApprovedActionPlan
```

---

# 44. ApprovedActionPlan

```text
ApprovedActionPlan

metadata

planning_mode

goals

strategy

steps[]

knowledge_requirement

retrieval_plan

evidence_requirement

memory_usage

capability_plan

tool_plan

confirmation_plan

response_strategy

state_intent

stop_conditions[]

fallback_plan

policy_snapshot

trace

quality
```

---

# 44.1 KnowledgeRequirement

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

除 `required` 外，本轮不新增业务值枚举；Domain / KnowledgeType / Population / Scenario / SafetyLevel 继续由 Domain Package / Config 注入。

---

# 44.2 RetrievalPlan

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

`RetrievalPlan` 是 M4 规划输出，不是执行结果。

---

# 44.3 EvidenceRequirement

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

正式边界：

```text
EvidenceRequirement != EvidenceItem
EvidenceRequirement != EvidencePack
EvidenceRequirement != VerifiedFact
```

---

# 44.4 RetrievalMode

```text
VECTOR
KEYWORD
HYBRID
STRUCTURED_LOOKUP
EXTERNAL_API
NONE
```

该枚举属于跨 Domain Knowledge Infrastructure control vocabulary。

---

# 45. planning_mode

```text
FORCED

DETERMINISTIC

AGENT_PLANNED

DEGRADED
```

---

# 46. PlanningGoal

```text
PlanningGoal

goal_id

goal_type

primary

goal_source

goal_priority

parameters

completion_condition
```

---

# 47. goal_source

```text
FORCED_POLICY

ACTIVE_TASK

EXPLICIT_USER_GOAL

IMPLICIT_NEED

SYSTEM_EVENT

AGENT_OPPORTUNITY
```

---

# 48. Strategy

```text
StrategySelection

strategy_id

reason_code

confidence
```

Core Control Strategies：

```text
DIRECT_FULFILLMENT
CLARIFY_THEN_ACT
TASK_CONTINUATION
SAFETY_OVERRIDE
DEGRADED_FALLBACK
WAIT
END
```

下列历史值是 **Domain Example**，必须由 Domain Strategy Registry 注册：

```text
# Domain Example
ACKNOWLEDGE_THEN_FULFILL
ACKNOWLEDGE_THEN_EXPLORE
LISTENING_FIRST
QUIET_PRESENCE
INFORMATION_THEN_FOLLOWUP
MEMORY_SUPPORTED_CONTINUATION
GENTLE_TOPIC_SHIFT
CLOSE_CONVERSATION
```

---

# 49. ActionStep

```text
ActionStep

step_id

action

target

parameters

skill_id

workflow_id

tool_requirement

depends_on[]

optional

completion_condition

on_failure
```

---

# 50. Action Space

Core Control Actions：

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

下列历史值是 **Domain Example**，必须由 Domain Action Registry 注册：

```text
# Domain Example
EMPATHIC_ACKNOWLEDGE
REFLECT
EXPLORE
LISTEN
SILENT_COMPANION
REASSURE_WITHIN_FACTS
SUMMARIZE
CHANGE_TOPIC
OFFER_CONTENT
PLAY_CONTENT
CONTROL_PLAYBACK
START_COGNITIVE_ACTIVITY
QUERY_INFORMATION
RESUME_ACTIVITY
REPEAT
CHANGE_TARGET
ESCALATE_FOR_SAFETY_REVIEW
```

---

# 51. MemoryUsageDecision

```text
MemoryUsageDecision

decision

memory_ids[]

usage_mode

reason_codes[]
```

---

## 51.1 decision

```text
USE

DO_NOT_USE

NOT_REQUIRED

UNAVAILABLE
```

---

## 51.2 usage_mode

```text
SILENT_CONTEXT

REFERENCE_EXPLICITLY

PERSONALIZE_ACTION
```

---

# 52. CapabilityPlan

```text
CapabilityPlan

selected_skill

selected_workflow

required_capabilities[]
```

---

# 53. ToolPlan

```text
ToolPlan

required

tool_calls[]

execution_mode
```

---

# 54. ToolCallPlan

```text
ToolCallPlan

tool_id

parameters

required

timeout_policy

result_dependency
```

---

# 55. ConfirmationPlan

```text
ConfirmationPlan

required

confirmation_type

target

timeout_behavior
```

---

# 56. M4 ResponseStrategy

注意：

```text
M4 ResponseStrategy
!=
M7 ResponsePlan
```

M4 只定义：

```text
沟通策略意图
```

结构：

```text
communicative_goal

tone

length

question_mode

memory_reference_mode

content_order
```

---

# 57. StateIntent

```text
StateIntent

desired_business_state

reason
```

注意：

```text
StateIntent
!=
State Commit
```

---

# 第五部分
# Execution Contracts

# 58. ExecutionContext

## Owner

```text
M5
```

---

## 58.1 Schema

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

---

# 59. ExecutionResult

```text
ExecutionResult

metadata

plan_status

step_results[]

skill_results[]

workflow_result

tool_results[]

business_outputs[]

execution_events[]

state_observations[]

errors[]

timing

cancellation

quality
```

---

# 60. PlanStatus

```text
SUCCESS

PARTIAL_SUCCESS

FAILED

TIMEOUT

CANCELLED

PREEMPTED
```

注意：

```text
Execution SUCCESS
!=
Business SUCCESS
```

---

# 61. StepExecutionResult

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

# 62. StepStatus

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

# 63. ToolResult

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

# 64. ToolStatus

```text
SUCCESS

FAILED

TIMEOUT

CANCELLED

UNAVAILABLE

REJECTED
```

---

# 65. ToolDefinition

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

success_semantics

enabled
```

---

# 66. IdempotencyMode

```text
NATURAL

KEY_BASED

NON_IDEMPOTENT
```

---

# 67. SideEffectLevel

```text
NONE

LOW

MEDIUM

HIGH
```

---

# 68. SkillDefinition

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

# 69. SkillResult

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

# 70. WorkflowDefinition

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

# 71. WorkflowInstance

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

# 72. WorkflowStatus

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

# 73. WorkflowCheckpoint

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

# 74. CancellationToken

```text
CancellationToken

execution_id

cancel_requested

reason

source

requested_at
```

---

# 75. Cancellation Source

```text
USER

POLICY

PREEMPTION

SYSTEM

TIMEOUT
```

---

# 第六部分
# Validation Contracts

# 76. ValidatedResult

## Owner

```text
M6
```

---

## 76.1 Schema

```text
ValidatedResult

metadata

validation_status

goal_validation[]

business_status

verified_facts[]

unverified_facts[]

conflicting_facts[]

claim_policy

followup

state_recommendation

validation_errors[]

quality
```

---

# 77. ValidationStatus

```text
VALIDATED

PARTIALLY_VALIDATED

NOT_VALIDATED

CONFLICTED

UNKNOWN
```

---

# 78. GoalValidation

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

# 79. GoalStatus

```text
COMPLETED

PARTIALLY_COMPLETED

NOT_COMPLETED

WAITING

UNKNOWN
```

---

# 80. BusinessStatus

```text
BusinessStatus

status

business_code

summary_code

completed

partial
```

---

## 80.1 status

```text
SUCCESS

PARTIAL_SUCCESS

FAILED

WAITING

UNKNOWN
```

---

# 81. ValidationEvidence

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

# 82. source_type

```text
TOOL_RESULT

DEVICE_STATE

DATABASE_STATE

EXTERNAL_CALLBACK

WORKFLOW_STATE

SYSTEM_STATE
```

---

# 83. trust_level

```text
AUTHORITATIVE

DIRECT

SECONDARY

INFERRED
```

---

# 84. freshness_status

```text
FRESH

STALE

UNKNOWN
```

---

# 85. VerifiedFact

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

## 85.1 certainty

```text
CONFIRMED

STRONGLY_SUPPORTED
```

---

# 86. UnverifiedFact

```text
UnverifiedFact

fact_type

candidate_value

reason_code

missing_evidence[]

risk_if_claimed
```

---

# 87. FactConflict

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

## 87.1 resolution_status

```text
RESOLVED

UNRESOLVED
```

---

# 88. ClaimPolicy

```text
ClaimPolicy

allowed_claims[]

forbidden_claims[]

conditional_claims[]

required_qualifiers[]

certainty_level
```

---

# 89. required_qualifiers

核心：

```text
CURRENTLY

SYSTEM_REPORTS

NOT_CONFIRMED

PARTIAL

TEMPORARY

SOURCE_LIMITED
```

---

# 90. FollowupRequirement

```text
FollowupRequirement

required

type

target

reason_codes[]

urgency
```

---

# 91. Followup Type

```text
NONE

STATUS_CHECK_REQUIRED

RETRY_REQUIRED

USER_CONFIRMATION_REQUIRED

SYSTEM_REPLAN_REQUIRED

WORKFLOW_CONTINUATION
```

---

# 92. StateRecommendation

```text
StateRecommendation

recommended_business_state

reason_codes[]

evidence_ids[]
```

注意：

```text
Recommendation
!=
Commit
```

---

# 第七部分
# Response Contracts

# 93. ResponsePlan

## Owner

```text
M7
```

---

## 93.1 Schema

```text
ResponsePlan

metadata

response_requirement

communicative_goals[]

content_plan

claim_plan

tone_profile

length_policy

question_plan

memory_expression

safety_constraints

tts_constraints

generation_path
```

---

# 94. ResponseRequirement

```text
ResponseRequirement

required

response_type

reason_codes[]
```

---

# 95. ResponseType

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

---

# 96. CommunicativeGoal

```text
ACKNOWLEDGE

EMPATHIZE

INFORM

REPORT_SUCCESS

REPORT_FAILURE

REPORT_UNKNOWN

REPORT_WAITING

CLARIFY

INVITE

CONFIRM

TASK_PROMPT

REASSURE_WITHIN_FACTS

CLOSE

NONE
```

---

# 97. ContentPlan

```text
ContentPlan

ordered_blocks[]
```

---

# 98. ContentBlock

```text
ACKNOWLEDGEMENT

EMOTION_RESPONSE

FACT

RESULT

QUALIFIER

QUESTION

NEXT_STEP

CLOSING
```

---

# 99. ClaimPlan

```text
ClaimPlan

must_include_claims[]

optional_claims[]

forbidden_claims[]

required_qualifiers[]
```

---

# 100. ToneProfile

```text
ToneProfile

warmth

directness

formality

emotional_intensity

complexity

pace
```

---

# 101. LengthPolicy

```text
LengthPolicy

level

max_sentences

max_characters
```

---

## 101.1 level

```text
VERY_SHORT

SHORT

MEDIUM

LONG
```

---

# 102. QuestionPlan

```text
QuestionPlan

required

question_type

target

question_mode

max_questions
```

---

# 103. question_type

```text
CLARIFICATION

OPEN_EXPLORATION

CLOSED_CONFIRMATION

REQUIRED_TASK_FIELD

OPTIONAL_INVITATION
```

---

# 104. question_mode

```text
NONE

DIRECT

GENTLE_OPTIONAL

REQUIRED
```

---

# 105. MemoryExpression

```text
MemoryExpression

mode

memory_ids[]

explicit_reference_allowed
```

---

## 105.1 mode

```text
NONE

SILENT_CONTEXT

PERSONALIZE_ACTION

REFERENCE_EXPLICITLY
```

---

# 106. SafetyConstraints

```text
SafetyConstraints

no_diagnosis

no_unverified_reassurance

no_new_medication_advice

no_external_state_fabrication

no_unauthorized_promise
```

---

# 107. GenerationPath

```text
TEMPLATE

LLM

HYBRID

SILENT
```

---

# 108. RuntimeResponse

```text
RuntimeResponse

metadata

response_type

text

tts_payload

claims_used[]

question

memory_references[]

generation_info

validation_status
```

---

# 109. RuntimeResponse validation_status

```text
VALID

FALLBACK_VALID

INVALID
```

只有：

```text
VALID
FALLBACK_VALID
```

允许输出。

---

# 110. ResponseQuestion

```text
ResponseQuestion

question_type

target

required
```

M8 以此建立 PendingQuestion。

---

# 111. TTSPayload

```text
TTSPayload

text

language

pause_markers[]

pronunciation_overrides[]
```

---

# 第八部分
# Update & Memory Contracts

# 112. UpdateResult

## Owner

```text
M8
```

---

## 112.1 Schema

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

---

# 113. StateUpdate

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

# 114. TransitionStatus

```text
NOT_REQUIRED

PROPOSED

COMMITTED

REJECTED

DEFERRED
```

---

# 115. TaskUpdate

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

# 116. TaskStatus

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

# 117. TaskFieldUpdate

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

# 118. confirmation_status

```text
CONFIRMED

UNCONFIRMED

REJECTED

SUPERSEDED
```

---

# 119. ConversationUpdate

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

# 120. PendingQuestion

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

# 121. PendingQuestionStatus

```text
ACTIVE

ANSWERED

CANCELLED

EXPIRED

SUPERSEDED
```

---

# 122. PendingReference

```text
PendingReference

reference_id

reference_type

target

source_turn_id

salience

expires_at
```

---

# 123. InteractionUpdate

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

# 124. SessionUpdate

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

# 125. EventUpdate

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

# 126. MemoryRecord

```text
MemoryRecord

memory_id

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
```

---

# 127. MemoryType

核心：

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

---

# 128. MemoryStatus

```text
STABLE

TEMPORARY

EMERGING

UNCERTAIN

DEPRECATED
```

---

# 129. MemoryScope

```text
SESSION

RECENT

LONG_TERM
```

---

# 130. MemorySource

```text
USER_EXPLICIT

USER_CONFIRMED

REPEATED_BEHAVIOR

TASK_CONFIRMED

SYSTEM_OBSERVED

MODEL_INFERRED
```

---

# 131. MemorySensitivity

```text
LOW

MEDIUM

HIGH
```

---

# 132. MemoryWriteDecision

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

# 133. Memory Write Decision

```text
WRITE

UPDATE_EXISTING

MERGE

KEEP_RECENT_ONLY

IGNORE

DEPRECATE_EXISTING
```

---

# 134. MemoryConflictResolution

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

# 135. ConflictType

```text
DIRECT_CONTRADICTION

TEMPORARY_OVERRIDE

PREFERENCE_DRIFT

VALUE_UPDATE

DUPLICATE

AMBIGUOUS_CONFLICT
```

---

# 136. TemporaryOverride

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

# 137. TemporaryOverrideStatus

```text
ACTIVE

EXPIRED

CANCELLED

SUPERSEDED
```

---

# 138. CommitResult

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

# 139. Commit overall_status

```text
SUCCESS

PARTIAL_SUCCESS

FAILED
```

---

# 第九部分
# M9 Business Integration Contracts

# 140. BusinessCapabilityDefinition

## Owner

```text
M9
```

---

## 140.1 Schema

```text
BusinessCapabilityDefinition

capability_id

module

name

supported_intents[]

supported_actions[]

entities[]

needs[]

skill_ids[]

workflow_ids[]

tool_ids[]

content_dependencies[]

api_dependencies[]

allowed_states[]

policy_ids[]

validation_rule_ids[]

response_rule_ids[]

memory_rules[]

enabled

version
```

---

# 141. CapabilityStatus

```text
DEFINED

DESIGNED

IMPLEMENTED

WIRED

VERIFIED

E2E_PASSED

RELEASE_READY
```

---

# 142. DependencyStatus

```text
AVAILABLE

STUB

PLANNED

NOT_FOUND

NOT_REQUIRED
```

---

# 143. ImplementationType

```text
CONTENT

CONFIG

PROMPT_RESOURCE

SKILL

WORKFLOW

TOOL

EXTERNAL_API

COMPOSITE
```

---

# 第十部分
# ID & Trace Contract

# 144. 全局 ID 链

必须支持：

```text
trace_id
↓
request_id
↓
understanding_id
↓
policy_decision_id
↓
plan_id
↓
execution_id
↓
step_execution_id
↓
tool_call_id
↓
validation_id
↓
response_plan_id
↓
response_id
↓
update_id
```

---

# 145. Session 与 Identity Scope

横向始终携带：

```text
session_id
subject_id
identity_scope
device_id
```

禁止跨 `identity_scope` 污染。`elder_id` / `user_scope` 已从 Core 删除。

---

# 146. ID 原则

所有关键对象 ID：

```text
唯一
不可复用
可追踪
```

---

# 第十一部分
# Version Contract

# 147. 必须版本化的对象

至少：

```text
Runtime Schema

Understanding Schema

ApprovedActionPlan Schema

ExecutionResult Schema

ValidatedResult Schema

ResponsePlan Schema

RuntimeResponse Schema

UpdateResult Schema

Memory Schema
```

---

# 148. 模型 / Prompt 版本

需要记录：

```text
model_version

prompt_version
```

主要涉及：

```text
M3
M4
M7
```

---

# 149. Rule / Policy 版本

需要记录：

```text
policy_version

rule_version

strategy_registry_version

action_registry_version

validation_rule_version
```

---

# 150. Capability 版本

```text
skill_version

workflow_version

tool_version

capability_version
```

---

# 第十二部分
# 生命周期总表

| Contract | 生命周期 |
|---|---|
| RuntimeInput | Turn |
| SafetyResult | Turn |
| RuntimeContext | Turn |
| UnderstandingState | Turn |
| PolicyDecision | Turn / Event |
| ActionPlanDraft | Turn |
| ApprovedActionPlan | Turn |
| ExecutionContext | Execution |
| ExecutionResult | Execution / Trace |
| ValidatedResult | Turn / Trace |
| ResponsePlan | Turn |
| RuntimeResponse | Turn / Conversation |
| UpdateResult | Turn / Trace |
| TaskContext | Cross-turn |
| PendingQuestion | Cross-turn |
| WorkflowInstance | Cross-turn |
| Recent Context | Hours / Days |
| MemoryRecord | Cross-session |
| BusinessCapabilityDefinition | Release / Version |

---

# 第十三部分
# Truth Level 总表

| Contract | Truth Level |
|---|---|
| RuntimeInput | Normalized Input |
| RuntimeContext | Known Context / System Fact |
| UnderstandingState | Semantic Interpretation |
| PolicyDecision | Runtime Constraint |
| ActionPlanDraft | Intended Action Draft |
| ApprovedActionPlan | Approved Intended Action |
| ExecutionResult | Execution Observation |
| ValidatedResult | Verified Business Truth |
| ResponsePlan | Communication Intention |
| RuntimeResponse | Actual User-facing Output |
| UpdateResult | Committed Runtime Change |
| MemoryRecord | Persisted User Context |

---

# 151. 最关键的 Truth 约束

```text
UnderstandingState
不能直接成为 Runtime State

ApprovedActionPlan
不能直接成为事实

ExecutionResult
不能直接成为 Business Truth

ValidatedResult
不能被 M7 提高确定性

RuntimeResponse
不能自动成为 Long-Term Memory

MemoryCandidate
不能自动成为 MemoryRecord
```

---

# 第十四部分
# Producer / Consumer 强边界

# 152. M1

可以产生：

```text
RuntimeInput
RuntimeContext
```

不能产生：

```text
UnderstandingState
```

---

# 153. M2

可以产生：

```text
PolicyDecision
SafetyLock
Preemption Decision
```

不能产生：

```text
ActionPlanDraft / ApprovedActionPlan
```

---

# 154. M3

只能产生：

```text
UnderstandingState
```

不能：

```text
调用 Tool
改 State
生成最终回复
```

---

# 155. M4

产生：

```text
ActionPlanDraft
ApprovedActionPlan
```

不能：

```text
执行 Tool
生成真实结果
```

---

# 156. M5

产生：

```text
ExecutionResult
ToolResult
```

不能：

```text
判断用户可见真相
重新规划
```

---

# 157. M6

产生：

```text
ValidatedResult
```

不能：

```text
调用 Tool
生成最终回复
```

---

# 158. M7

产生：

```text
ResponsePlan
RuntimeResponse
```

不能：

```text
重新解释 ToolResult
修改 State
写 Memory
```

---

# 159. M8

产生：

```text
UpdateResult
MemoryRecord变更
Context变更
State Commit
```

不能：

```text
重新理解
重新规划
重新执行业务Tool
```

---

# 160. M9

产生：

```text
Business Capability Definition
业务映射
Registry配置
```

不能：

```text
修改 M0–M8 核心职责边界
```

---

# 第十五部分
# 全局 Frozen Enum Registry

以下枚举从 V1.0 起视为 Frozen Core。

## PlanningMode

```text
FORCED
DETERMINISTIC
AGENT_PLANNED
DEGRADED
```

## ValidationStatus

```text
VALIDATED
PARTIALLY_VALIDATED
NOT_VALIDATED
CONFLICTED
UNKNOWN
```

## BusinessStatus

```text
SUCCESS
PARTIAL_SUCCESS
FAILED
WAITING
UNKNOWN
```

## GoalStatus

```text
COMPLETED
PARTIALLY_COMPLETED
NOT_COMPLETED
WAITING
UNKNOWN
```

## Execution PlanStatus

```text
SUCCESS
PARTIAL_SUCCESS
FAILED
TIMEOUT
CANCELLED
PREEMPTED
```

## MemoryStatus

```text
STABLE
TEMPORARY
EMERGING
UNCERTAIN
DEPRECATED
```

## GenerationPath

```text
TEMPLATE
LLM
HYBRID
SILENT
```

## ResponseValidationStatus

```text
VALID
FALLBACK_VALID
INVALID
```

---

# 第十六部分
# Contract Compatibility Rules

# 161. 向后兼容扩展

允许：

```text
新增 optional field

新增 Registry 条目

新增非破坏性枚举值
```

前提：

```text
旧 Consumer 不崩溃
```

---

# 162. Breaking Change

以下视为 Breaking Change：

```text
删除核心字段

修改字段原始语义

修改 enum 既有值语义

修改 Truth Level

修改 Producer / Consumer Owner

把 optional 变 required

改变 ID 关联逻辑
```

必须进行：

```text
Schema Major Version Upgrade
```

---

# 163. Schema Version

建议：

```text
MAJOR.MINOR
```

例如：

```text
1.0
1.1
2.0
```

---

# 第十七部分
# Runtime Core Contract Gates

## Gate SCHEMA-01

所有核心 Contract 均存在唯一 Owner。

## Gate SCHEMA-02

所有跨模块对象都有明确 Producer / Consumer。

## Gate SCHEMA-03

核心字段命名全项目唯一。

## Gate SCHEMA-04

同一概念不得在不同模块出现不同名字。

例如禁止：

```text
risk
risk_level
safety_risk
```

无规范地混用。

## Gate SCHEMA-05

同名字段不得存在不同语义。

## Gate SCHEMA-06

Execution SUCCESS 与 Business SUCCESS 必须区分。

## Gate SCHEMA-07

UNKNOWN 为正式状态。

## Gate SCHEMA-08

WAITING 与 UNKNOWN 区分。

## Gate SCHEMA-09

StateRecommendation 与 StateCommit 区分。

## Gate SCHEMA-10

MemoryCandidate 与 MemoryRecord 区分。

## Gate SCHEMA-11

ActionPlanDraft 与 ApprovedActionPlan 区分。禁止使用歧义名称 ActionPlan。

## Gate SCHEMA-12

M4 ResponseStrategy 与 M7 ResponsePlan 区分。

## Gate SCHEMA-13

Understanding Evidence 与 Validation Evidence 区分。

## Gate SCHEMA-14

每个 Tool 定义 success_semantics。

## Gate SCHEMA-15

每个长期 Memory 强制 identity_scope。

## Gate SCHEMA-16

所有主要 Contract 支持 schema_version。

## Gate SCHEMA-17

跨阶段对象可通过 ID 完整追踪。

## Gate SCHEMA-18

任何 Breaking Change 必须升级 Schema Major Version。

---

# 第十八部分
# 推荐代码中的 Schema 组织方式

建议建立统一：

```text
contracts/
```

而不是把所有公共数据模型分别散落到各模块内部。

推荐：

```text
contracts/

├── common/
│   ├── ids.py
│   ├── enums.py
│   ├── metadata.py
│   └── version.py
│
├── input/
│   ├── runtime_input.py
│   └── runtime_context.py
│
├── understanding/
│   └── understanding_state.py
│
├── policy/
│   └── policy_decision.py
│
├── planning/
│   └── action_plan.py
│
├── execution/
│   ├── execution_result.py
│   ├── tool_result.py
│   └── workflow.py
│
├── validation/
│   └── validated_result.py
│
├── response/
│   ├── response_plan.py
│   └── runtime_response.py
│
├── update/
│   └── update_result.py
│
├── memory/
│   └── memory_record.py
│
└── business/
    └── capability.py
```

---

# 164. Registry 与 Contract 分离

注意：

```text
contracts/
=
数据契约

registries/
=
运行时可扩展定义
```

例如：

```text
ActionDefinition
StrategyDefinition
SkillDefinition
ToolDefinition
GoalValidationRule
ClaimDefinition
BusinessCapabilityDefinition
```

更适合放：

```text
registries/
```

而不是与 Turn-level Contract 混在一起。

---

# 第十九部分
# 全局最重要的契约链

最终整个 Runtime 必须始终保持：

```text
RuntimeInput
↓
SafetyResult(phase=EARLY)
↓
RuntimeContext
↓
UnderstandingState
↓
PolicyDecision
↓
ApprovedActionPlan
↓
ExecutionResult
↓
ValidatedResult
↓
ResponsePlan
↓
RuntimeResponse
↓
UpdateResult
↓
RuntimeContext_next
```

任何模块都不得：

```text
跳过中间 Truth Boundary
```

例如禁止：

```text
M3
→ Tool

M4
→ RuntimeResponse

M5
→ “通知成功”

ToolResult
→ State Commit

ExecutionResult
→ M7自由生成

MemoryCandidate
→ Stable Memory
```

---

# 第二十部分
# 本 Registry 的最终原则

正式固定：

```text
一、一个核心概念只有一个正式 Schema。

二、一个核心 Schema 只有一个主要 Owner。

三、跨阶段只通过正式 Contract 交互。

四、模型推理、计划、执行、事实、表达、持久化必须分层。

五、下游不得提升上游数据的真实性等级。

六、所有关键对象必须可版本化、可追踪。

七、Contract 修改优先考虑兼容性，而不是局部方便。

八、本 Registry 是所有阶段数据定义的最终权威来源。
```

---

# 结论

至此，M0–M9 原本分散在不同阶段设计中的核心数据对象，已经收束为一套统一的数据契约体系。

正式形成：

```text
Input Contract
↓
Context Contract
↓
Understanding Contract
↓
Policy Contract
↓
Planning Contract
↓
Execution Contract
↓
Validation Contract
↓
Response Contract
↓
Update Contract
↓
Memory Contract
↓
Business Capability Contract
```

从实现阶段开始：

```text
阶段文档负责说明“怎么做”

本 Registry 负责说明“模块之间究竟传什么”
```

如果两者出现冲突：

```text
首批 Core Contract
优先以 Canonical Registry V1.0
作为跨模块接口基准。

其余对象仍以本 Registry 为准，
并回头修正阶段实现文档。
```

至此：

```text
Agent Runtime Core Schema Registry V1.0
=
FROZEN
```