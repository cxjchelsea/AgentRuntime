# 可复用 Agent Runtime 平台  
# M4 Planning & Orchestration 四项关键子设计冻结版 V1.0

> **Phase 0 Fix**  
> 规划对象正式名为 `ActionPlanDraft` / `ApprovedActionPlan`。  
> 文中单独出现的 `ActionPlan` 一律按语境解释为二者之一，不得再作为类型名。  
> PLAY_CONTENT / LISTENING_FIRST / QUIET_PRESENCE 等为 Domain Example。

> **平台化转换说明**  
> 本文已从单一业务 Agent 设计转换为 **可复用 Agent Runtime 平台**设计。除明确标记为 `Core` 的对象、接口、不变量和生命周期外，任何具体业务 Intent、Entity、Workflow、Skill、Tool、知识域、状态字段、规则、提示词或示例均视为 **Domain Package 示例**，不得硬编码进 Runtime Core。新项目应通过 Registry / Adapter / Plugin / Config 注入领域差异。
> 
> 平台固定边界：`Runtime Core` 尽量稳定；`Domain Extension` 插件化；`Business Package` 配置化；`Application` 负责产品装配。

---

# 0. 冻结说明

本文件冻结 M4 的四项核心子设计：

```text
M4-02 ActionPlan Schema
M4-03/04 Action Space + Strategy Taxonomy
M4-09 Agent Planner Hybrid Pipeline
M4-19/20 M4 Eval Dataset & Metrics
```

冻结后应满足：

```text
M3
UnderstandingState
        ↓
M4
ActionPlan
        ↓
M5
Execution
```

三阶段之间的数据契约稳定。

本次冻结内容分为：

```text
A. Frozen Core
不得破坏的核心结构

B. Extensible Registry
允许新增枚举、Action、Strategy、Capability

C. Runtime Configuration
允许业务调整的参数、阈值和启停项
```

禁止以后因为新增一个普通业务场景而重新设计整个 Planner。

---

# 第一部分  
# M4-02 ActionPlan Schema 冻结规范

## 1. ActionPlan 定位

`ActionPlan` 是 M4 唯一正式输出。

它表达：

> 基于当前理解、上下文、Policy 和可用能力，系统当前准备采取什么行为。

它不是：

```text
自然语言回复
Tool真实结果
Runtime State
Memory写入结果
```

因此固定关系：

```text
UnderstandingState
        ↓
M4
        ↓
ActionPlan
        ↓
M5
ExecutionResult
```

---

# 2. Frozen Core 总结构

正式冻结为：

```text
ActionPlan

metadata

planning_mode

goals

strategy

steps

memory_usage

capability_plan

tool_plan

confirmation_plan

response_strategy

state_intent

stop_conditions

fallback_plan

policy_snapshot

trace

quality
```

后续允许在子对象内部向后兼容扩展字段，但不得删除核心对象。

---

# 3. metadata

冻结：

```text
metadata

plan_id
request_id
session_id

schema_version
planner_version
prompt_version

created_at
```

其中必须存在：

```text
plan_id
schema_version
```

---

# 4. planning_mode

正式冻结为：

```text
FORCED
DETERMINISTIC
AGENT_PLANNED
DEGRADED
```

不得使用自由字符串替代。

---

## 4.1 FORCED

来源：

```text
Safety
Hard Policy
Forced Workflow
```

例如：

```text
HelpWorkflow
```

Planner 不具有选择权。

---

## 4.2 DETERMINISTIC

用户目标明确，可通过规则直接得到计划。

例如：

```text
暂停
停止
继续播放
提醒确认
明确查询天气
```

---

## 4.3 AGENT_PLANNED

需要结合：

```text
Emotion
Need
Context
Interaction State
Memory
Recent Agent Behavior
```

选择自然策略。

---

## 4.4 DEGRADED

当：

```text
Planner失败
模型不可用
Context不足
```

采用有限、安全的兜底计划。

---

# 5. goals

冻结：

```text
goals

primary_goal
secondary_goals[]
goal_source
goal_priority
completion_condition
```

---

## 5.1 goal_source

冻结枚举：

```text
FORCED_POLICY
ACTIVE_TASK
EXPLICIT_USER_GOAL
IMPLICIT_NEED
SYSTEM_EVENT
AGENT_OPPORTUNITY
```

---

# 6. strategy

结构冻结：

```text
strategy

strategy_id
reason
confidence
```

`strategy_id` 必须来自 Strategy Registry。

不能直接写：

```text
“先安慰一下再问问”
```

---

# 7. steps

冻结：

```text
steps[]
```

每个 Step：

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

# 8. ActionStep 约束

一个 Step 只能表达：

> 一个明确业务行为。

禁止：

```text
action =
“先安慰用户，然后播放音乐，如果不喜欢再换一个”
```

必须拆成多个 Step。

---

# 9. depends_on

用于表达：

```text
Step 2
必须等待 Step 1
```

但第一版不鼓励复杂 DAG。

主要支持：

```text
顺序执行
简单条件依赖
```

---

# 10. memory_usage

冻结：

```text
memory_usage

decision

memory_ids[]

usage_mode

reason
```

---

## 10.1 decision

冻结：

```text
USE
DO_NOT_USE
NOT_REQUIRED
UNAVAILABLE
```

---

## 10.2 usage_mode

冻结：

```text
SILENT_CONTEXT
REFERENCE_EXPLICITLY
PERSONALIZE_ACTION
```

---

# 11. capability_plan

冻结：

```text
capability_plan

selected_skill

selected_workflow

required_capabilities[]
```

规则：

```text
普通能力
→ Skill

确定性流程
→ Workflow
```

---

# 12. tool_plan

冻结：

```text
tool_plan

required

tool_calls[]

execution_mode
```

---

## 12.1 ToolCallPlan

```text
ToolCallPlan

tool_id

parameters

required

timeout_policy

result_dependency
```

---

## 12.2 execution_mode

第一版冻结：

```text
SEQUENTIAL
PARALLEL_ALLOWED
```

M4 只表达计划。

实际执行并发由 M5 决定。

---

# 13. confirmation_plan

冻结：

```text
confirmation_plan

required

confirmation_type

target

timeout_behavior
```

注意：

M2 已定义的 Hard Confirmation 不得被 M4 修改。

---

# 14. response_strategy

冻结：

```text
response_strategy

communicative_goal

tone

length

question_mode

memory_reference_mode

content_order

constraints[]
```

---

# 15. communicative_goal

第一版冻结核心枚举：

```text
ACKNOWLEDGE
EMPATHIZE
INFORM
CLARIFY
INVITE
CONFIRM
REPORT_RESULT
CLOSE
NONE
```

可扩展，但不能直接存最终文案。

---

# 16. question_mode

冻结：

```text
NONE
DIRECT
GENTLE_OPTIONAL
REQUIRED
```

---

# 17. state_intent

冻结：

```text
state_intent

desired_business_state
reason
```

这里只表达：

```text
Planner希望进入哪个业务状态
```

真正 State Transition 仍须经过 State Engine。

---

# 18. stop_conditions

冻结为数组：

```text
stop_conditions[]
```

核心条件：

```text
USER_REJECTS

GOAL_COMPLETED

TASK_COMPLETED

TOOL_SUCCESS

TOOL_FAILURE

TIMEOUT

HIGHER_PRIORITY_EVENT

SAFETY_OVERRIDE

CONVERSATION_END
```

---

# 19. fallback_plan

冻结：

```text
fallback_plan

trigger_conditions[]

fallback_strategy

fallback_steps[]
```

必须保证：

```text
核心Tool失败
不等于
Runtime直接崩溃
```

---

# 20. policy_snapshot

冻结：

```text
policy_snapshot

policy_decision_id

allowed_actions

forbidden_actions

forced_workflow

reason_codes[]
```

用于后续审计：

> Planner 当时到底受到了什么约束？

---

# 21. trace

冻结：

```text
trace

candidate_actions[]

rejected_actions[]

selected_reason
```

---

# 22. rejected_actions

结构：

```text
RejectedAction

action

reason_code
```

例如：

```text
OFFER_CONTENT

reason =
RECENT_USER_REJECTION
```

---

# 23. quality

冻结：

```text
quality

schema_valid

policy_valid

capability_valid

confidence

degraded

warnings[]
```

---

# 24. ActionPlan 禁止字段

明确禁止在 ActionPlan 内出现：

```text
final_response_text

tool_execution_result

notification_success

memory_written

current_state_override

clinical_diagnosis
```

这些属于其他阶段。

---

# 25. ActionPlan 最小合法示例

用户：

> “暂停一下。”

```json
{
  "planning_mode": "DETERMINISTIC",

  "goals": {
    "primary_goal": "PAUSE_CURRENT_PLAYBACK",
    "goal_source": "EXPLICIT_USER_GOAL"
  },

  "strategy": {
    "strategy_id": "DIRECT_FULFILLMENT"
  },

  "steps": [
    {
      "step_id": "1",
      "action": "CONTROL_PLAYBACK",
      "parameters": {
        "operation": "PAUSE"
      },
      "skill_id": "ContentSkill"
    }
  ],

  "memory_usage": {
    "decision": "NOT_REQUIRED"
  },

  "tool_plan": {
    "required": true
  },

  "response_strategy": {
    "communicative_goal": "REPORT_RESULT",
    "length": "SHORT"
  }
}
```

---

# 第二部分  
# M4-03/04 Action Space + Strategy Taxonomy 冻结规范

# 26. 设计原则

正式冻结：

```text
Action
=
原子行为

Strategy
=
一个或多个 Action 的组织方式
```

不能混为一个层级。

---

# 27. Action Space 顶层分类

冻结五类：

```text
A. Conversation Action
B. Task Action
C. Capability Action
D. Control Action
E. Safety Action
```

---

# 28. Conversation Action 冻结核心集

```text
ACKNOWLEDGE

EMPATHIC_ACKNOWLEDGE

REFLECT

ANSWER

EXPLORE

CLARIFY

LISTEN

WAIT

SILENT_COMPANION

REASSURE_WITHIN_FACTS

SUMMARIZE

CHANGE_TOPIC

END
```

---

# 29. 各核心 Conversation Action 含义

## ACKNOWLEDGE

确认收到用户表达。

不要求情绪性回应。

---

## EMPATHIC_ACKNOWLEDGE

对明确情绪进行回应。

不得用于无证据情绪推断。

---

## REFLECT

将用户核心表达进行适度反映。

不增加新事实。

---

## ANSWER

回答明确问题。

---

## EXPLORE

邀请用户继续当前话题。

---

## CLARIFY

澄清阻塞下一步执行的关键不确定点。

---

## LISTEN

减少干预，让用户继续表达。

---

## WAIT

不主动产生新交互。

---

## SILENT_COMPANION

进入低打扰陪伴状态。

---

## REASSURE_WITHIN_FACTS

仅提供事实允许范围内的安定回应。

不得承诺未知结果。

---

## SUMMARIZE

总结当前已确认内容。

---

## CHANGE_TOPIC

切换话题。

必须具有合理原因。

---

## END

自然结束当前交互。

---

# 30. Task Action 冻结核心集

```text
CONTINUE_TASK

ASK_REQUIRED_FIELD

CONFIRM_ACTION

COMPLETE_TASK

CANCEL_TASK

DEFER_TASK
```

---

# 31. Capability Action 冻结核心集

```text
OFFER_CONTENT

PLAY_CONTENT

CONTROL_PLAYBACK

START_COGNITIVE_ACTIVITY

QUERY_INFORMATION

USE_MEMORY

CALL_TOOL
```

后续新增业务可以扩展 Capability Action。

---

# 32. Control Action 冻结核心集

```text
STOP_CURRENT_ACTIVITY

RESUME_ACTIVITY

REPEAT

CHANGE_TARGET
```

---

# 33. Safety Action 冻结核心集

```text
ENTER_SAFETY_WORKFLOW

ESCALATE_FOR_SAFETY_REVIEW
```

但一般由 M2 强制产生。

---

# 34. ActionDefinition 冻结结构

所有 Action Registry 项必须具有：

```text
action_id

category

description

intrusiveness_level

requires_confirmation

required_capability

allowed_planning_modes

enabled
```

---

# 35. intrusiveness_level

冻结四级：

```text
VERY_LOW
LOW
MEDIUM
HIGH
```

例如：

```text
WAIT
→ VERY_LOW

ACKNOWLEDGE
→ LOW

EXPLORE
→ MEDIUM

主动提敏感Memory
→ HIGH
```

---

# 36. Strategy 顶层定义

Strategy 不是自由文本。

必须来自：

```text
StrategyRegistry
```

---

# 37. 第一版冻结 Strategy

```text
DIRECT_FULFILLMENT

ACKNOWLEDGE_THEN_FULFILL

ACKNOWLEDGE_THEN_EXPLORE

LISTENING_FIRST

CLARIFY_THEN_ACT

QUIET_PRESENCE

INFORMATION_THEN_FOLLOWUP

MEMORY_SUPPORTED_CONTINUATION

TASK_CONTINUATION

SAFETY_OVERRIDE

GENTLE_TOPIC_SHIFT

CLOSE_CONVERSATION
```

---

# 38. DIRECT_FULFILLMENT

适用：

```text
显式目标清晰
无需额外理解
无需额外确认
```

例如：

```text
暂停
继续播放
查天气
```

---

# 39. ACKNOWLEDGE_THEN_FULFILL

适用：

```text
用户有明确任务
+
同时存在值得回应的情绪/表达
```

---

# 40. ACKNOWLEDGE_THEN_EXPLORE

适用：

```text
用户愿意继续交流
+
存在陪伴/倾听需求
```

避免成为所有情绪场景默认策略。

---

# 41. LISTENING_FIRST

适用：

```text
LISTENING Need
```

或近期：

```text
Agent建议/追问过多
```

---

# 42. CLARIFY_THEN_ACT

仅适用：

```text
下一步行为被关键歧义阻塞
```

---

# 43. QUIET_PRESENCE

适用：

```text
need_for_silence = high
```

或用户明确提出安静陪伴。

---

# 44. INFORMATION_THEN_FOLLOWUP

适用：

```text
Information Request
```

回答后可以：

```text
轻度追加
```

但必须依据用户接受度。

---

# 45. MEMORY_SUPPORTED_CONTINUATION

仅当：

```text
Memory相关
+
可信
+
自然
+
当前未冲突
```

使用。

---

# 46. TASK_CONTINUATION

适用：

```text
Active Task 尚未完成
```

例如：

```text
身体不适采集
```

---

# 47. SAFETY_OVERRIDE

严格对应：

```text
M2 Forced Safety Policy
```

不得由普通 Agent Planner 主观选择。

---

# 48. GENTLE_TOPIC_SHIFT

仅用于：

```text
当前话题不宜继续
或用户出现明显疲劳
或需要从重复低价值话题轻度转移
```

不得用于回避用户正常负面情绪。

---

# 49. CLOSE_CONVERSATION

适用：

```text
用户明确结束
交互自然结束
用户疲劳明显
```

---

# 50. StrategyDefinition 冻结结构

```text
strategy_id

description

preferred_goals[]

preferred_needs[]

compatible_emotions[]

required_conditions[]

avoid_conditions[]

default_actions[]

intrusiveness_level

enabled
```

---

# 51. Strategy 不应直接绑定 Emotion

禁止：

```text
LONELINESS
=
ACKNOWLEDGE_THEN_EXPLORE
```

而应：

```text
Emotion
+
Need
+
InteractionState
+
Goal
+
RecentBehavior
```

共同决定。

---

# 52. 冻结的 Need-first 原则

情感场景决策固定采用：

```text
Need-first
+
Goal-first
```

Emotion 作为调节因素。

不采用：

```text
Emotion → Fixed Action
```

---

# 53. 策略约束示例

如果：

```text
willingness_to_talk = NO
```

降低：

```text
EXPLORE
CLARIFY
```

提高：

```text
ACKNOWLEDGE
WAIT
SILENT_COMPANION
END
```

---

# 54. 用户拒绝约束

如果：

```text
recent_rejection =
OFFER_CONTENT
```

则近期：

```text
OFFER_CONTENT
```

应显著降权。

---

# 55. Strategy 扩展规则

未来允许新增：

```text
StrategyDefinition
```

但新增 Strategy 必须满足：

```text
1. 使用既有 Action
或同步注册新 Action

2. 有明确适用条件

3. 有 avoid_conditions

4. 有 Eval Cases

5. 不绕开 M2
```

---

# 第三部分  
# M4-09 Agent Planner Hybrid Pipeline 冻结规范

# 56. 总体架构

正式冻结：

```text
PlanningInput
        ↓
① Policy Forced Check
        ↓
② Planning Router
        ↓
③ Goal Resolver
        ↓
④ Candidate Action Builder
        ↓
⑤ Strategy Selector
        ↓
⑥ Memory Usage Decider
        ↓
⑦ Capability Selector
        ↓
⑧ Sequence Builder
        ↓
⑨ Fallback Builder
        ↓
⑩ Plan Validator
        ↓
⑪ Policy Re-check
        ↓
Approved ActionPlan
```

---

# 57. Step 1 Policy Forced Check

如果存在：

```text
forced_action
forced_workflow
```

直接：

```text
FORCED_PATH
```

不得调用普通 Planner 覆盖。

---

# 58. Step 2 Planning Router

冻结四路：

```text
FORCED_PATH

DETERMINISTIC_PATH

AGENT_PATH

DEGRADED_PATH
```

---

# 59. FORCED_PATH 条件

```text
M2 Forced Workflow
Hard Safety Action
Hard Business Policy
```

---

# 60. DETERMINISTIC_PATH 条件

满足：

```text
Goal明确

低歧义

无需情感策略选择

Action映射唯一或高度稳定
```

例如：

```text
暂停
继续
停止
简单查询
明确提醒回应
```

---

# 61. AGENT_PATH 条件

包括：

```text
支持型交互

隐含需求

多意图

关系话题

主动交互

Memory使用

用户对Agent不满

复杂策略选择
```

---

# 62. DEGRADED_PATH

以下情况进入：

```text
Planner不可用

LLM失败

Context不足但仍可安全回应

Schema连续失败
```

---

# 63. Step 3 Goal Resolver

冻结优先级：

```text
Forced Policy Goal
>
Critical Active Task
>
Explicit User Goal
>
Required Task Continuation
>
Strong Implicit Need
>
Agent Opportunity
```

---

# 64. Step 4 Candidate Action Builder

候选来源：

```text
M3 candidate_actions

Goal-compatible actions

Strategy Registry

Current Task

Available Capabilities
```

然后过滤：

```text
Policy forbidden actions

Unavailable capability

State-incompatible actions
```

---

# 65. CandidateAction 冻结结构

```text
action

goal_fit

need_fit

context_fit

policy_allowed

intrusiveness

repetition_penalty

confidence
```

---

# 66. Step 5 Strategy Selector

第一版 Hybrid：

```text
Rule Strategy Selector
+
LLM Strategy Planner
```

---

# 67. Rule Strategy Selector

优先处理：

```text
DIRECT_FULFILLMENT

TASK_CONTINUATION

QUIET_PRESENCE

CLARIFY_THEN_ACT

SAFETY_OVERRIDE
```

这些场景规则性较强。

---

# 68. LLM Strategy Planner

主要处理：

```text
ACKNOWLEDGE_THEN_EXPLORE

LISTENING_FIRST

MEMORY_SUPPORTED_CONTINUATION

GENTLE_TOPIC_SHIFT

复杂多意图排序
```

---

# 69. LLM Planner 输入冻结

只允许输入：

```text
UnderstandingState Summary

Relevant RuntimeContext

PolicyDecision

Candidate Actions

Available Capabilities

Recent Agent Behavior
```

不得让 Planner重新读取完整对话并重新做 M3 理解。

---

# 70. LLM Planner 核心任务

Prompt 必须固定：

```text
你负责选择行为，不负责理解用户。

不得重新修改 UnderstandingState。

不得生成最终回复。

只能从允许的 Action / Strategy 中选择。

不得调用未注册 Capability。

不得假设 Tool 执行成功。

允许 WAIT / END / SILENT_COMPANION。
```

---

# 71. Step 6 Memory Usage Decider

独立于 Strategy Planner。

输入：

```text
Relevant Memory

UnderstandingState

Current Goal

Current Emotion

InteractionState

Recent Memory Usage
```

输出：

```text
MemoryUsageDecision
```

---

# 72. Memory 使用判定冻结因子

至少：

```text
relevance

confidence

freshness

status

sensitivity

current_conflict

recent_usage

naturalness
```

---

# 73. Memory 使用 Hard Block

满足任一：

```text
deprecated

explicit current conflict

wrong user

low confidence

privacy forbidden
```

必须：

```text
DO_NOT_USE
```

---

# 74. Step 7 Capability Selector

输入：

```text
Action
+
CapabilityRegistry
```

输出：

```text
Skill
Workflow
Tool requirement
```

Planner 不硬编码：

```text
if PLAY_CONTENT then ...
```

到 Runtime Core。

---

# 75. Step 8 Sequence Builder

冻结原则：

```text
短视距规划
```

普通对话建议：

```text
1～2 个主要 Action
```

确定性任务例外。

---

# 76. Receding Horizon 冻结原则

正式采用：

```text
理解一轮
→
计划少量动作
→
执行
→
重新理解
→
重新规划
```

不采用长链自主规划。

---

# 77. Step 9 Fallback Builder

每个包含：

```text
Tool
Skill
External Capability
```

的 Plan 必须考虑失败。

---

# 78. Fallback 示例

```text
PLAY_CONTENT失败
→
REPORT_FAILURE
→
可选 OFFER_ALTERNATIVE
```

而不是：

```text
假装已经播放
```

---

# 79. Step 10 Plan Validator

冻结检查项：

```text
Action Registered

Strategy Registered

Policy Allowed

State Compatible

Capability Available

Tool Available

Memory Valid

Sequence Legal

No Direct State Mutation

No Tool Result Fabrication

No Response Text
```

---

# 80. Step 11 Policy Re-check

任何：

```text
AGENT_PLANNED ActionPlan
```

都必须再次进入：

```text
Policy Re-check
```

才可以交给 M5。

---

# 81. Plan Validation Failure

如果只是：

```text
轻度计划错误
```

可尝试一次：

```text
Replan
```

如果仍失败：

```text
DEGRADED_PATH
```

不要无限重试 Planner。

---

# 82. Hybrid Pipeline 降级

正式冻结：

```text
LLM Planner失败
→ Rule Strategy

Memory服务失败
→ memory_usage = UNAVAILABLE

Capability缺失
→ 不执行该Action

Policy失败
→ 高风险动作Fail Closed

Plan Schema失败
→ Replan一次
→ DEGRADED
```

---

# 83. DEGRADED Planner

第一版建议只允许有限动作：

```text
ACKNOWLEDGE

CLARIFY

ANSWER_BASIC

REPORT_FAILURE

END
```

不得：

```text
复杂主动行为
敏感 Memory
高风险 Tool
```

---

# 84. Planner 可观测性冻结

每轮必须记录：

```text
planning_path

goal_resolution

candidate_actions

selected_strategy

memory_decision

capability_decision

rejected_actions

validation_result

policy_recheck_result
```

---

# 85. Planner 版本化

必须记录：

```text
planner_version

strategy_registry_version

action_registry_version

prompt_version
```

---

# 第四部分  
# M4-19/20 Eval Dataset & Metrics 冻结规范

# 86. 评估目标

M4 评估的是：

```text
系统选的行为是否合适
```

而不是：

```text
最终说得漂不漂亮
```

因此评估时优先直接比较：

```text
ActionPlan
```

---

# 87. EvalCase 冻结结构

```text
PlanningEvalCase

case_id

category

understanding_state

runtime_context

policy_decision

available_capabilities

expected

allowed_variants

forbidden

difficulty

tags
```

---

# 88. expected

可包含：

```text
expected_mode

expected_primary_goal

expected_strategy

expected_actions

expected_action_order

expected_memory_usage

expected_tool_usage

expected_active_decision
```

---

# 89. forbidden

必须支持：

```text
forbidden_actions

forbidden_tools

forbidden_memory_usage

forbidden_strategy
```

这对情感陪护非常重要。

因为很多时候：

```text
“什么不该做”
```

比唯一正确动作更容易定义。

---

# 90. Eval 一级分类冻结

第一版至少：

```text
DIRECT_TASK

MULTI_INTENT

EMOTIONAL_SUPPORT

LISTENING

QUIET_PRESENCE

CLARIFICATION

MEMORY_USE

MEMORY_NON_USE

TOOL_USE

TOOL_NON_USE

TASK_CONTINUATION

AGENT_FRUSTRATION

ACTIVE_INTERACTION

SAFETY_OVERRIDE

CONVERSATION_CLOSING

POLICY_CONSTRAINT
```

---

# 91. DIRECT_TASK

例如：

> “暂停。”

期望：

```text
DIRECT_FULFILLMENT
CONTROL_PLAYBACK
```

禁止：

```text
EXPLORE
```

---

# 92. EMOTIONAL_SUPPORT

例如：

> “最近没人和我说话。”

可能允许：

```text
ACKNOWLEDGE_THEN_EXPLORE

LISTENING_FIRST
```

但禁止：

```text
DIRECT_OFFER_CONTENT
```

如果 Context 无支持。

---

# 93. LISTENING

例如用户连续表达一段情绪。

期望：

```text
LISTENING_FIRST
```

避免：

```text
继续提建议
```

---

# 94. QUIET_PRESENCE

用户：

> “让我静一会儿。”

期望：

```text
QUIET_PRESENCE
```

禁止：

```text
EXPLORE
```

---

# 95. MEMORY_USE

例如：

> “还是以前常听的吧。”

Context 存在稳定音乐偏好。

期望：

```text
PERSONALIZE_ACTION
```

---

# 96. MEMORY_NON_USE

例如旧偏好与当前表达冲突。

期望：

```text
DO_NOT_USE
```

这是必须单独建立的大类。

---

# 97. TOOL_NON_USE

例如：

> “今天屋里挺冷清的。”

禁止：

```text
Weather Tool
```

用于控制工具误调用。

---

# 98. AGENT_FRUSTRATION

例如：

> “你怎么又问？”

期望：

```text
减少问题
```

禁止继续：

```text
EXPLORE
```

---

# 99. ACTIVE_INTERACTION

评估：

```text
该不该主动
```

而不仅是主动后怎么说。

---

# 100. SAFETY_OVERRIDE

必须确认：

```text
M2 forced workflow
```

100% 覆盖普通 Planner。

---

# 101. Difficulty 冻结

```text
EASY
MEDIUM
HARD
ADVERSARIAL
```

---

# 102. 第一版核心指标

冻结如下：

```text
Primary Goal Accuracy

Strategy Accuracy

Primary Action Accuracy

Action Order Accuracy

Policy Violation Rate

Unnecessary Clarification Rate

Missed Clarification Rate

Over-questioning Rate

Over-suggestion Rate

Unnecessary Tool Call Rate

Memory Misuse Rate

Memory Missed-use Rate

Active Interaction Precision

Safety Override Accuracy

Plan Schema Validity Rate
```

---

# 103. Policy Violation Rate

目标：

```text
0 或接近 0
```

任何 Policy Violation 都应作为高优先级缺陷处理。

---

# 104. Over-questioning Rate

定义：

```text
本来无需继续追问
却选择 EXPLORE / CLARIFY
的比例
```

这是情感陪护自然度的关键指标。

---

# 105. Over-suggestion Rate

定义：

```text
用户主要需要表达/倾听，
Planner却主动给方案或推荐内容
的比例
```

---

# 106. Unnecessary Tool Call Rate

定义：

```text
当前目标并不需要外部事实或动作，
但 Planner 调用了 Tool
```

---

# 107. Memory Misuse Rate

包括：

```text
无关Memory

过期Memory

与当前表达冲突Memory

过度明确提Memory

敏感Memory不当使用
```

---

# 108. Active Interaction Precision

冻结为主动性最重要指标之一。

因为主动交互优先：

```text
Precision > Recall
```

原则：

```text
宁可少一次主动
不要明显打扰用户
```

---

# 109. Safety Override Accuracy

所有 Forced Safety Case 必须：

```text
100%进入正确安全路径
```

此指标不能与普通策略指标平均抵消。

---

# 110. Plan Schema Validity Rate

Planner 输出必须持续符合：

```text
ActionPlan Schema
```

目标应接近：

```text
100%
```

---

# 111. Evaluation Gate

冻结四类 Gate：

```text
Policy Gate

Behavior Gate

Memory/Tool Gate

Active/Safety Gate
```

---

# 112. Policy Gate

必须：

```text
Policy Violation Rate
达到上线阈值
```

未通过不得进入后续真实执行验证。

---

# 113. Behavior Gate

重点：

```text
Goal
Strategy
Action
Over-questioning
Over-suggestion
```

---

# 114. Memory/Tool Gate

重点：

```text
Memory Misuse

Unnecessary Tool

Missed Tool
```

---

# 115. Active/Safety Gate

主动性和 Safety 必须独立通过。

不能因为其他指标高就忽略。

---

# 116. Golden Set

正式保留：

```text
M4 Golden Planning Set
```

建议第一阶段：

```text
150～300 条
```

但更重要的是：

```text
高质量
真实边界
困难样例
```

---

# 117. 每次必须回归的改动

以下变化必须跑 Golden Set：

```text
Planner模型变化

Planner Prompt变化

Action Registry变化

Strategy Registry变化

Memory策略变化

主动性策略变化

M3 Schema变化

Policy规则变化
```

---

# 118. Error Bucket 冻结

```text
WRONG_PRIMARY_GOAL

WRONG_STRATEGY

WRONG_ACTION

WRONG_ACTION_ORDER

OVER_QUESTIONING

OVER_SUGGESTION

UNNECESSARY_CLARIFICATION

MISSED_CLARIFICATION

MEMORY_MISUSE

MEMORY_MISSED_USE

UNNECESSARY_TOOL

MISSED_TOOL

POLICY_VIOLATION

ACTIVE_INTRUSION

SAFETY_OVERRIDE_FAILURE

PREMATURE_END

FAIL_TO_END

PLAN_SCHEMA_ERROR
```

---

# 119. Error Attribution

发现错误后必须继续定位属于：

```text
M3 Understanding Error

M4 Goal Resolution Error

Strategy Error

Memory Decision Error

Capability Error

Policy Error

Prompt Error

Model Error
```

避免所有失败都归结为：

> Planner 不够聪明。

---

# 120. 四个子设计之间的冻结关系

最终固定关系：

```text
Action Space
定义：
系统可以做什么

↓

Strategy Taxonomy
定义：
这些 Action 如何组合才自然

↓

Hybrid Planner Pipeline
定义：
当前应该选择哪套 Strategy 和 Action

↓

ActionPlan Schema
定义：
最终计划怎样传给 M5

↓

Eval Dataset
定义：
如何判断 Planner 是否选对
```

---

# 121. 与 M3 的接口正式冻结

M4 不再自行重新构建用户理解。

正式依赖：

```text
UnderstandingState
```

其中重点字段：

```text
intent

goal

emotion

needs

interaction

risk

uncertainty

reference

topic
```

如果 M4 发现 Understanding 不足，应输出：

```text
CLARIFY
```

或进入降级。

而不是自己重新解释原始文本。

---

# 122. 与 M5 的接口正式冻结

M5 只接受：

```text
Approved ActionPlan
```

不得直接以：

```text
UnderstandingState
```

作为执行依据。

即：

```text
M3
不能直接调用 Tool

M4
不能直接执行 Tool

M5
不能重新决定 Planner Goal
```

---

# 123. 与 M2 的接口正式冻结

M4 输入：

```text
PolicyDecision
```

M4 输出后：

```text
ActionPlan
→ Policy Re-check
```

因此形成双重约束：

```text
M2
先限制可选空间

M4
在可选空间中决策

M2
最后再次验证
```

---

# 124. Frozen Core 总结

以下内容从 V1.0 开始视为 Frozen Core：

```text
PlanningMode 四类

ActionPlan 主结构

Action / Strategy 两层结构

Need-first / Goal-first 原则

Forced / Deterministic / Agent / Degraded 四路径

MemoryUsageDecision 独立存在

CapabilityRegistry 解耦

短视距 / Receding Horizon Planning

PlanValidator

Policy Re-check

独立 M4 Eval
```

---

# 125. 允许扩展的内容

以下允许持续扩展：

```text
新增 Action

新增 Strategy

新增 Skill

新增 Tool

新增 Capability

新增 Need 映射

新增 Eval Case

新增 Planner Model
```

但必须保持：

```text
向后兼容
+
Registry注册
+
评估覆盖
```

---

# 126. 不允许破坏的边界

禁止后续变成：

```text
一个超大 Planner Prompt
同时：

重新理解用户
做Safety
查Memory
调用Tool
生成最终回复
更新State
写Memory
```

这会破坏当前已经建立的 Runtime 分层。

必须继续保持：

```text
M3
懂人

↓

M4
决定做什么

↓

M5
真正执行

↓

M6
确认发生了什么

↓

M7
决定怎么说

↓

M8
决定留下什么
```

---

# 127. 四项子设计冻结完成标准

满足以下条件后视为 M4 Core Design Frozen：

```text
1. M4输入和输出Schema固定

2. Action Space固定核心集合

3. Strategy固定核心集合

4. PlanningMode固定

5. Planner Hybrid Pipeline固定

6. Memory决策位置固定

7. Capability选择位置固定

8. Policy双重校验固定

9. M4 Eval结构固定

10. M5无需重新理解Planner输出
```

---

# 128. 冻结后的项目状态

完成本次冻结后：

```text
M3
已经有稳定的 UnderstandingState

M4
已经有稳定的 ActionPlan

M3 → M4
理解接口稳定

M4 → M5
执行接口稳定
```

至此，核心智能链已经正式完成：

```text
M1
我知道当前发生了什么

↓

M2
我知道哪些事情不能乱做

↓

M3
我知道用户现在是什么意思

↓

M4
我知道此刻最合适做什么
```

下一阶段 M5 的任务因此非常明确：

```text
不是继续思考，

而是把已经批准的 ActionPlan
可靠地执行成真实系统动作。
```