# 可复用 Agent Runtime 平台  
# M3 Understanding 详细实现方案 V2.0

> **Phase 0 Fix**  
> 首批 Core Contract 以 Canonical Registry V1.0 为唯一正式来源。  
> `UnderstandingState` 唯一采用嵌套结构。  
> Core Control Intents 仅 `UNKNOWN` / `STOP` / `CANCEL` / `HELP`。其余 Intent 必须由 Domain Registry 注册。

> **平台化转换说明**  
> 本文已从单一业务 Agent 设计转换为 **可复用 Agent Runtime 平台**设计。除明确标记为 `Core` 的对象、接口、不变量和生命周期外，任何具体业务 Intent、Entity、Workflow、Skill、Tool、知识域、状态字段、规则、提示词或示例均视为 **Domain Package 示例**，不得硬编码进 Runtime Core。新项目应通过 Registry / Adapter / Plugin / Config 注入领域差异。
> 
> 平台固定边界：`Runtime Core` 尽量稳定；`Domain Extension` 插件化；`Business Package` 配置化；`Application` 负责产品装配。

> 本版本为 M3 V1.0 的结构化重整版。  
> 保留前序 M3 中已确定的所有理解能力、数据结构、Rule + LLM 方案、Risk Pass、Conflict Resolver、Validator、Prompt、Eval、PoC、Gate、交付物等内容，并按照统一 22 项模板重新组织。  
> 本版本最重要的变化，是将 M3 正式固定为一条可执行的 Runtime Understanding Pipeline，而不是组件清单。

---


## 平台扩展补充：Core Intent 与 Domain Intent

M3 Core 不冻结具体业务 Intent 列表。Core 只冻结 `IntentResult`、多 Intent 关系、置信度、证据与 Registry Contract。任何 `PLAY_CONTENT`、`REMINDER_RESPONSE`、领域查询等具体 Intent 都应由 Domain Package 通过 `IntentRegistry` 注册。平台只可保留极少数跨领域 Runtime Control Intent（如 STOP / CANCEL / HELP 类）且同样需要版本化。

# 01. 阶段定位

M3 是 Runtime 第一个真正承担“理解智能”的核心阶段。

M0 解决：

```text
系统怎么运行
```

M1 解决：

```text
当前有哪些事实和上下文
```

M2 解决：

```text
当前有哪些硬规则和安全边界
```

M3 正式解决：

```text
用户这一刻到底在表达什么？

用户明确想做什么？

有没有多重意图？

这句话和前文有什么关系？

有没有省略、指代、修正、否定？

用户当前可能是什么情绪？

可能真正需要什么？

用户是否还愿意继续交流？

有没有风险信号？

哪些判断确定？

哪些只是推测？

哪些地方需要澄清？
```

因此 M3 的目标不是输出：

```text
intent = CHAT
```

而是构建：

```text
UnderstandingState
```

即：

> 当前这一轮对用户表达、目标、情绪、需要、交互状态、风险和不确定性的结构化理解。

---

# 02. 阶段目标与八种智能映射

## 2.1 M3 总体目标

M3 最终要完成：

```text
Literal Meaning
+
Contextual Meaning
+
Intent / Goal
+
Emotion
+
Implicit Need
+
Reference Resolution
+
Interaction State
+
Risk Signal
+
Uncertainty
+
Evidence
+
Candidate Actions
```

并统一生成：

```text
UnderstandingState
```

---

## 2.2 与八种智能的关系

M3 核心实现：

```text
语义理解智能

情绪理解智能

目标与隐含需求推断智能
```

大量依赖：

```text
上下文智能

关系连续性智能
```

并向：

```text
对话策略智能

主动性智能

自我约束智能
```

提供输入。

| 智能能力 | M3职责 |
|---|---|
| 语义理解智能 | 核心实现 |
| 上下文智能 | 使用 M1 RuntimeContext |
| 关系连续性智能 | 使用相关关系信息和 Memory |
| 情绪理解智能 | 核心实现 |
| 目标与隐含需求推断智能 | 核心实现 |
| 对话策略智能 | 只提供 Candidate Actions，不做最终决策 |
| 主动性智能 | 输出用户接受度、疲劳度等状态 |
| 自我约束智能 | 输出 RiskSignal、不确定性和 Evidence |

---

# 03. 职责边界

## 3.1 M3 负责

M3 负责：

```text
语义解析

Intent识别

Multi-intent识别

Speech Act识别

Entity提取

否定识别

修正识别

Reference Resolution

Context Fusion

Topic识别

Explicit Goal分析

Emotion分析

Implicit Need推断

InteractionState分析

RiskSignal识别

Uncertainty分析

Clarification判断

Evidence建立

Candidate Action生成
```

---

## 3.2 M3 不负责

M3 不负责：

```text
最终业务策略选择

最终 Action 选择

Tool 执行

状态修改

通知执行

Memory真正写入

最终自然语言回复
```

---

## 3.3 M3 与 M4 的硬边界

M3 回答：

```text
用户现在是什么意思？
用户可能需要什么？
```

M4 回答：

```text
基于这种理解，
下一步应该做什么？
```

因此：

```text
UnderstandingState
!=
ActionPlan
```

---

## 3.4 M3 与 M2 的硬边界

M3 可以输出：

```text
risk_signal = POSSIBLE_HIGH_RISK
```

但不能直接决定：

```text
send_notification()
```

最终 Safety 升级仍由 M2 决定。

---

# 04. 前置依赖与外部依赖

## 4.1 M0 依赖

M3 依赖 M0 提供：

```text
UnderstandingEngine Interface

UnderstandingState基础Schema

Runtime Engine

Trace

Error/Fallback

Schema Version机制
```

---

## 4.2 M1 依赖

M3 依赖 M1 提供：

```text
RuntimeInput

RuntimeContext

ConversationContext

TaskContext

PendingQuestion

PendingReference

RelationshipContext

MemoryContext

ToolContext

TimeContext
```

---

## 4.3 M2 依赖

M3 可能接收：

```text
EarlySafetyResult

SafetyContext

CurrentState

Policy背景
```

用于理解阶段约束。

---

## 4.4 内部依赖

M3 至少需要：

```text
IntentRegistry

EmotionRegistry

NeedRegistry

EntityRegistry

ContextSelector

DeterministicParser

ReferenceResolver

LLMProvider

RiskDetector

ConflictResolver

UnderstandingValidator

UncertaintyAnalyzer
```

---

# 05. 输入

M3 的标准输入建议定义为：

```text
UnderstandingInput

runtime_input

runtime_context

early_safety_result

policy_context
```

核心仍是：

```text
RuntimeInput
+
RuntimeContext
```

---

## 5.1 RuntimeInput 使用字段

至少使用：

```text
normalized_text

raw_text

asr_confidence

segments

timestamp

source

trigger_type
```

---

## 5.2 RuntimeContext 使用字段

根据当前输入按需选择：

```text
current_state

current_business

recent_turns

session_summary

current_topic

pending_question

pending_reference

active_task

recent_person_reference

relationship_context

relevant_memory

time_context

tool_context

interaction_context
```

---

# 06. 输出

M3 最终统一输出：

```text
UnderstandingState
```

如果发现 Safety 风险：

```text
UnderstandingState.risk.requires_safety_review = true
```

则控制流回到：

```text
M2 Safety Re-evaluation
```

否则进入：

```text
M4
```

---

# 07. 核心数据结构

# 7.1 UnderstandingState

建议统一结构：

```text
UnderstandingState

understanding_id

timestamp

schema_version

semantic

intents

goal

topic

reference

emotion

need

interaction

risk

uncertainty

evidence

memory_candidates

candidate_actions

overall_confidence

metadata
```

---

# 7.2 SemanticUnderstanding

```text
SemanticUnderstanding

normalized_meaning

speech_act

negation

confirmation

correction

comparison

temporal_expression

person_entities

content_entities

location_entities

health_entities

other_entities

multi_intent
```

---

# 7.3 IntentResult

```text
IntentResult

explicit_intents

sub_intents

intent_relations

confidence
```

---

# 7.4 GoalState

```text
GoalState

explicit_goal

goal_type

target

parameters

completion_criteria

confidence
```

---

# 7.5 TopicState

```text
TopicState

current_topic

topic_shift

topic_continuation

topic_reference

confidence
```

---

# 7.6 ReferenceResolution

```text
ReferenceResolution

reference_expression

reference_type

candidate_targets

resolved_target

confidence

source_context
```

---

# 7.7 EmotionState

```text
EmotionState

primary_emotion

secondary_emotions

valence

arousal

intensity

possible_cause

cause_confidence

duration_hint

expression_style

confidence
```

---

# 7.8 ImplicitNeedState

```text
ImplicitNeedState

implicit_needs

confidence

evidence

uncertainty
```

---

# 7.9 InteractionState

```text
InteractionState

engagement_level

willingness_to_talk

willingness_to_receive_suggestion

need_for_silence

frustration_with_agent

conversation_fatigue

acceptance_state
```

---

# 7.10 RiskSignal

```text
RiskSignal

signal_detected

signal_types

severity_hint

evidence

confidence

requires_safety_review
```

---

# 7.11 UncertaintyState

```text
UncertaintyState

overall_confidence

uncertain_fields

ambiguity_type

candidate_interpretations

needs_clarification

clarification_reason

safe_to_infer
```

---

# 7.12 EvidenceItem

```text
EvidenceItem

target_field

evidence_type

source

content

confidence
```

evidence_type 可以包括：

```text
CURRENT_INPUT

RECENT_TURN

SESSION_CONTEXT

TASK_CONTEXT

MEMORY

SYSTEM_STATE

MODEL_INFERENCE
```

---

# 7.13 MemoryCandidate

M3 不直接写 Memory，但可以产生候选：

```text
MemoryCandidate

type

content

source

confidence

importance_hint

evidence
```

例如：

```text
type = preference

content = 喜欢越剧

source = explicit_user_statement
```

真正写入仍由 M8 决定。

---

# 08. 数据来源、存储与生命周期

## 8.1 UnderstandingState 生命周期

UnderstandingState 默认属于：

```text
Turn-Level
```

即当前一轮理解结果。

不应直接成为长期用户事实。

---

## 8.2 Evidence 生命周期

Evidence 至少在：

```text
当前 Turn Trace
```

中保留。

敏感内容仍遵守最小必要原则。

---

## 8.3 Emotion 生命周期

EmotionState 只是：

```text
当前交互理解
```

不能自动升级成：

```text
长期心理画像
```

---

## 8.4 Implicit Need 生命周期

Implicit Need 同样只是：

```text
当前轮推断
```

不能自动永久保存。

---

## 8.5 MemoryCandidate 生命周期

MemoryCandidate 从 M3 输出后：

```text
→ M8审查

→ write / update / ignore
```

M3 不持久化。

---

## 8.6 RiskSignal 生命周期

RiskSignal 必须：

```text
立即进入 M2 Safety Re-evaluation
```

若 Safety 已建立事件，则后续以 Safety Event 状态为准。

---

## 8.7 Fact 与 Inference 分离

必须固定：

```text
User Fact
!=
Model Inference
```

例如用户说：

> “我女儿一个星期没来了。”

事实：

```text
daughter_not_visit_for_week
```

推断：

```text
possible_loneliness
```

二者必须存放在不同字段。

---

# 09. 内部组件

建议 M3 包含：

```text
UnderstandingOrchestrator

InputPrechecker

DeterministicParser

UnderstandingContextSelector

ReferenceResolver

ContextFusionEngine

UnderstandingRouter

LLMUnderstandingAnalyzer

IntentResolver

EmotionAnalyzer

NeedAnalyzer

InteractionAnalyzer

RiskDetector

UnderstandingMerger

ConflictResolver

UnderstandingValidator

GroundingValidator

UncertaintyAnalyzer

CandidateActionGenerator

UnderstandingStateBuilder
```

---

# 10. 运行时实现主流程

M3 正式 Runtime Algorithm：

```text
RuntimeInput + RuntimeContext
        ↓
① Input Precheck
        ↓
② Deterministic Parse
        ↓
③ Understanding Context Selection
        ↓
④ Reference / Pending Question Resolution
        ↓
⑤ Context Fusion
        ↓
⑥ Fast Path / Deep Path Routing
       ↙                 ↘
 Fast Path             Deep Path
   ↓                       ↓
规则理解结果          LLM结构化理解
       ↘                 ↙
        ↓
⑦ Result Merge
        ↓
⑧ Risk Signal Pass
        ↓
⑨ Conflict Resolution
        ↓
⑩ Schema / Grounding Validation
        ↓
⑪ Uncertainty & Clarification
        ↓
⑫ Candidate Action Generation
        ↓
⑬ UnderstandingState Build
        ↓
┌────────────────────────────┐
│ risk.requires_review=true  │
└────────────┬───────────────┘
             ↓
            M2

否则
↓
M4
```

---

## 10.1 伪代码

```python
async def understand(
    runtime_input: RuntimeInput,
    runtime_context: RuntimeContext,
    early_safety_result: SafetyResult | None = None,
) -> UnderstandingState:

    # 1. 输入质量与基础可理解性检查
    precheck = input_prechecker.check(
        runtime_input,
        runtime_context
    )

    # 2. 确定性解析
    deterministic = deterministic_parser.parse(
        runtime_input,
        runtime_context
    )

    # 3. 选择当前理解需要的上下文
    selected_context = context_selector.select(
        runtime_input,
        runtime_context,
        deterministic
    )

    # 4. 指代 / pending question 解析
    reference_result = reference_resolver.resolve(
        runtime_input,
        selected_context,
        deterministic
    )

    # 5. Context Fusion
    fused_context = context_fusion_engine.fuse(
        selected_context,
        reference_result,
        deterministic
    )

    # 6. Fast / Deep Route
    route = understanding_router.route(
        runtime_input,
        deterministic,
        reference_result,
        fused_context
    )

    if route == "FAST":
        model_result = None

        draft = fast_understanding_builder.build(
            deterministic,
            reference_result,
            fused_context
        )

    else:
        model_result = await llm_understanding_analyzer.analyze(
            runtime_input,
            fused_context,
            deterministic,
            reference_result
        )

        draft = understanding_merger.merge(
            deterministic,
            reference_result,
            model_result,
            fused_context
        )

    # 8. 风险信号复查
    risk_result = risk_detector.analyze(
        runtime_input,
        fused_context,
        draft,
        early_safety_result
    )

    # 9. 冲突解析
    resolved = conflict_resolver.resolve(
        deterministic,
        model_result,
        risk_result,
        draft
    )

    # 10. Schema + Grounding
    validated = understanding_validator.validate(
        resolved,
        runtime_input,
        fused_context
    )

    # 11. 不确定性 / 澄清
    uncertainty = uncertainty_analyzer.analyze(
        validated,
        fused_context,
        runtime_input
    )

    # 12. Candidate Action
    candidate_actions = candidate_action_generator.generate(
        validated,
        uncertainty,
        fused_context
    )

    # 13. 最终状态
    return understanding_state_builder.build(
        validated,
        risk_result,
        uncertainty,
        candidate_actions
    )
```

---

# 11. 各步骤详细实现

# Step 1：Input Precheck

先检查：

```text
输入是否为空

ASR置信度是否过低

是否存在异常输入格式

是否属于文本输入

是否已经被 Early Safety 锁定
```

如果输入质量严重不足：

```text
uncertainty =
LOW_ASR_CONFIDENCE
```

而不是强行深度理解。

---

# Step 2：Deterministic Parse

这一层解决：

> 可以用规则稳定解决的问题。

主要包括：

```text
明确 STOP

明确 YES / NO

Reminder Response

Playback Control

基础时间表达

基础数字

明显否定

明显修正

Pending Question回答

明显求助关键词
```

例如当前 Pending Question 是：

```text
medication_reminder_confirmation
```

用户：

> “刚吃过了。”

可以直接得到：

```text
intent =
REMINDER_RESPONSE

result =
COMPLETED
```

---

# Step 3：Understanding Context Selection

M3 不应把整个 RuntimeContext 发给 LLM。

通过：

```text
UnderstandingContextSelector
```

选择当前真正需要的数据。

例如用户：

> “换一个。”

重点加载：

```text
current_business

current_content

last_content

content_category

playback_status

recent_turns
```

而无需加载：

```text
所有家庭成员

所有人生经历

完整长期记忆
```

---

# Step 4：Reference / Pending Question Resolution

负责：

```text
他

她

他们

那个

刚才那个

昨天那个

之前那个

还是那个

再来一个

还是老样子
```

以及：

```text
Pending Question
```

---

## 11.4.1 Reference Resolution 优先级

推荐：

```text
Active Task
>
Pending Question
>
当前 Business Object
>
最近一轮显式对象
>
Current Topic
>
Recent Person Reference
>
Long-Term Relationship Memory
```

---

## 11.4.2 播放示例

第一轮：

> “给我听越剧。”

第二轮：

> “再来一个。”

解析：

```text
intent = PLAY_CONTENT

operation = NEXT

resolved_reference =
current_content_category:YUE_OPERA
```

---

## 11.4.3 Pending Question 示例

Agent：

> “现在要不要叫人帮忙？”

用户：

> “不用。”

解析：

```text
speech_act = REJECTION

intent =
HELP_CONFIRMATION_RESPONSE

value = NO
```

---

# Step 5：Context Fusion

将：

```text
当前输入

近期对话

当前任务

当前状态

Relationship

Memory

Tool State
```

按相关性组合。

同时输出：

```text
relevant_context

supporting_context

conflicting_context

ignored_context

context_dependencies
```

---

## 11.5.1 Context 冲突示例

长期 Memory：

```text
喜欢京剧
```

当前：

> “最近不太想听京剧。”

M3 应形成：

```text
historical_preference =
LIKE_BEIJING_OPERA

current_preference =
AVOID_BEIJING_OPERA

conflict = true
```

当前明确表达优先。

---

# Step 6：Fast Path / Deep Path Routing

这是第一版 M3 很重要的性能优化。

## Fast Path

适合：

```text
停止

音量

明确播放

Reminder确认

简单天气查询

下一首

再播一次
```

流程：

```text
规则
+
Context
→ UnderstandingState
```

不一定调用大模型。

---

## Deep Path

适合：

```text
情绪表达

隐含需求

复杂上下文

多意图

人物关系

模糊表达

讽刺 / 反问

互动疲劳

复杂指代
```

流程：

```text
Rule Result
+
Selected Context
+
LLM Structured Understanding
```

---

# Step 7：LLM Structured Understanding

LLM 的职责是：

```text
理解
```

不是：

```text
回复
```

输入建议：

```text
Current Input

Relevant Recent Turns

Current State

Current Topic

Active Task

Pending Question

Relevant Relationship / Memory

Deterministic Result
```

---

## 11.7.1 LLM 结构化输出

例如：

```json
{
  "speech_act": "EMOTIONAL_EXPRESSION",
  "intents": ["EXPRESS_EMOTION"],
  "topic": "family",
  "emotion": {
    "type": "possible_loneliness",
    "confidence": 0.72
  },
  "implicit_needs": [
    {
      "type": "COMPANIONSHIP",
      "confidence": 0.68
    }
  ],
  "interaction_state": {
    "willingness_to_talk": "medium"
  },
  "risk_signals": [],
  "uncertainty": {}
}
```

---

## 11.7.2 Prompt 原则

Prompt 必须明确：

```text
你不是回复用户。

你是理解组件。

必须区分：
事实
推断
情绪
需要
风险
不确定性。

不得做医学诊断。

不得伪造外部系统状态。

不得把推断写成事实。
```

---

# Step 8：Risk Signal Pass

M3 完成初步理解后再次看：

```text
当前输入

上下文

情绪

目标

Need

已有 Safety Result
```

是否存在：

```text
help_request_signal

self_harm_signal

harm_to_others_signal

high_risk_discomfort_signal

medication_risk_signal

fall_injury_signal

environmental_danger_signal

confusion_disorientation_signal
```

当前总业务目录中安全与领域服务模块本身覆盖这些方向。

---

## 11.8.1 RiskSignal 不直接执行

M3 只输出：

```text
requires_safety_review = true
```

M2 决定：

```text
是否强制进入 Safety Workflow
```

---

# Step 9：Conflict Resolution

可能同时存在：

```text
Rule Result

LLM Result

Context Result

Memory Result
```

必须统一冲突优先级。

建议：

```text
当前业务确定性规则
>
当前用户明确表达
>
确定性命令规则
>
LLM深层推断
>
历史Memory推断
```

---

## 11.9.1 Multi-intent 不等于冲突

例如：

```text
EXPRESS_EMOTION
+
PLAY_CONTENT
```

可以共存。

---

## 11.9.2 Intent Relation

建议：

```text
PARALLEL

SEQUENTIAL

CONFLICTING

DEPENDENT
```

例如：

> “别放京剧了，给我放评书。”

可以理解为：

```text
STOP_CURRENT
+
START_NEW_CONTENT
```

关系：

```text
SEQUENTIAL
```

---

# Step 10：Schema / Grounding Validation

模型输出不能直接相信。

Validator 检查：

```text
Intent 是否存在于 Registry

Emotion 是否属于定义空间

Need 是否合法

confidence 是否有效

Reference 是否有来源

是否生成不存在的人名

是否伪造 Tool 状态

是否把推断写成事实

是否输出非法字段
```

---

## 11.10.1 幻觉示例

LLM 输出：

```text
用户女儿叫王芳
```

但 RuntimeContext 中没有“王芳”。

处理：

```text
unsupported
→ 删除
或
标记为 ungrounded
```

---

# Step 11：Uncertainty / Clarification

M3 必须把：

```text
不知道
```

作为正式状态。

---

## 11.11.1 Uncertainty 类型

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

## 11.11.2 safe_to_infer

例如：

> “那后天呢？”

当前 Context 已明确：

```text
北京天气
```

可以：

```text
safe_to_infer = true
```

无需机械追问。

但：

> “帮我联系她。”

Context 中有：

```text
女儿
妹妹
护理员
```

则：

```text
safe_to_infer = false

needs_clarification = true
```

---

## 11.11.3 澄清原则

推荐：

```text
低风险
+
上下文充分
+
推断代价低
→ 可推断

安全相关
敏感操作
不可逆操作
多候选冲突
→ 澄清
```

---

# Step 12：Candidate Action Generation

M3 可以输出：

```text
ACKNOWLEDGE

ANSWER

EXPLORE

CLARIFY

LISTEN

WAIT

SILENT_COMPANION

RECALL_MEMORY

OFFER_CONTENT

PLAY_CONTENT

CALL_TOOL

CONTINUE_TASK

CHANGE_TOPIC

END

ESCALATE
```

但这里只是：

```text
candidate_actions
```

不是最终 ActionPlan。

---

# Step 13：UnderstandingState Build

把：

```text
semantic

intent

goal

topic

reference

emotion

need

interaction

risk

uncertainty

evidence

candidate_actions
```

统一封装成最终：

```text
UnderstandingState
```

---

# 12. 分支、路由与决策规则

# 12.1 Intent 设计

当前需求附录已经有本期基础意图：

```text
陪聊

播放

停止

音量

普通情绪

高风险情绪

求助

身体不适

提醒完成

提醒稍后

提醒取消

认知

无法识别
```



但后续扩展时，不应把 Domain Package 中的业务能力目录项全部变成 Intent。

---

## 12.1.1 推荐 Core + Domain 可扩展 Intent Space

```text
CHAT

EXPRESS_EMOTION

PLAY_CONTENT

CONTROL_PLAYBACK

STOP

HELP

DISCOMFORT

REMINDER_RESPONSE

COGNITIVE_INTERACTION

QUERY_INFORMATION

MEMORY_QUERY

MEMORY_COMMAND

ACTIVE_RESPONSE

UNKNOWN
```

---

## 12.1.2 Intent + Entity

例如：

```text
intent = PLAY_CONTENT

category = OPERA

subcategory = YUE_OPERA
```

而不是：

```text
PLAY_YUE_OPERA
```

---

# 12.2 Speech Act

建议支持：

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

这对领域场景非常重要。

---

# 12.3 否定

例如：

> “我不是想听歌。”

必须识别：

```text
negated_intent =
PLAY_CONTENT
```

不能只因为出现“听歌”就命中 PLAY_CONTENT。

---

# 12.4 修正

例如：

> “放京剧吧……算了，还是评书。”

解析：

```text
correction = true

superseded_target = 京剧

final_target = 评书
```

---

# 12.5 多意图

例如：

> “我有点头晕，顺便把音乐关了。”

输出：

```text
DISCOMFORT

STOP_PLAYBACK
```

M3 两个都识别。

谁优先由 M2/M4 决定。

---

# 12.6 Explicit Goal

Intent 与 Goal 分开。

例如：

```text
intent =
PLAY_CONTENT

goal =
START_PLAYBACK

target =
YUE_OPERA
```

---

# 12.7 Implicit Need

建议第一版 Need Space：

```text
COMPANIONSHIP

LISTENING

EMOTIONAL_ACKNOWLEDGEMENT

INFORMATION

ACTION_HELP

REASSURANCE

QUIET_PRESENCE

EXPRESSION

REMEMBERING

ENTERTAINMENT

ORIENTATION

HUMAN_HELP

UNKNOWN
```

隐含需求必须带：

```text
confidence

evidence
```

---

# 12.8 Emotion Taxonomy

基础层可以包括：

```text
positive

neutral

sad

anxious

fearful

angry

frustrated

lonely

ashamed

guilty

disappointed

grieving

uncertain
```

业务场景层可以映射当前情绪目录中的：

```text
想家与思念亲人

孤独与缺少陪伴

无聊与生活空虚

衰老失落

无意义感

不想交流
```

等场景。

---

# 12.9 Emotion != Risk

必须固定：

```text
Emotion
!=
Safety Risk
```

例如：

```text
sadness = high
```

不自动等于：

```text
high_risk_emotion
```

---

# 12.10 Emotion Cause

只允许：

```text
possible_cause
```

而不是：

```text
confirmed_cause
```

除非用户明确说明。

---

# 12.11 InteractionState

情感陪护必须理解：

```text
用户还想不想聊

用户是不是已经烦了

用户是否愿意接受建议

用户是否需要安静
```

例如：

> “别问了，我不想说。”

输出：

```text
willingness_to_talk = LOW

need_for_silence = HIGH

explicit_intent =
STOP_QUESTIONING
```

---

# 12.12 Agent Frustration

例如：

> “你怎么老问这个？”

输出：

```text
emotion =
frustration

frustration_target =
AGENT

interaction_issue =
REPETITIVE_QUESTIONING
```

而不是普通负面情绪。

---

# 12.13 Repetition

用户重复：

> “我女儿还没来。”

可以输出：

```text
repetition_detected = true

possible_importance = elevated
```

但不能自动推断：

```text
认知障碍
```

---

# 12.14 Topic Shift

例如：

前面聊女儿。

突然问：

> “今天冷不冷？”

输出：

```text
topic_shift = true

new_topic = WEATHER
```

旧话题进入 Topic History。

---

# 12.15 Silence

未来如果 RuntimeInput 是：

```text
long_silence
```

M3 应结合 Context 判断：

```text
expected_silence
```

而不是一律：

```text
ASR_FAILURE
```

---

# 13. 与前后 M 的接口

# 13.1 M0 → M3

提供：

```text
UnderstandingEngine Interface

UnderstandingState Schema

Trace

Error
```

---

# 13.2 M1 → M3

提供：

```text
RuntimeInput

RuntimeContext
```

这是 M3 最核心输入。

---

# 13.3 M2 → M3

提供：

```text
EarlySafetyResult

Current Safety Context

Current State
```

---

# 13.4 M3 → M2

如果：

```text
risk.requires_safety_review = true
```

则：

```text
UnderstandingState
→ M2 Safety Re-evaluation
```

---

# 13.5 M3 → M4

M3 输出：

```text
UnderstandingState
```

M4 根据：

```text
UnderstandingState

RuntimeContext

PolicyDecision
```

生成：

```text
ActionPlan
```

---

# 13.6 M3 → M8

M3 可输出：

```text
MemoryCandidate
```

M8 再决定：

```text
write

update

ignore
```

---

# 14. 与业务模块的映射

# 14.1 领域交互

重点：

```text
Speech Act

Topic

Emotion

Implicit Need

InteractionState

Reference
```

---

# 14.2 内容播放

重点：

```text
PLAY_CONTENT

CONTROL_PLAYBACK

Content Entity

Reference

Current Business Context
```

---

# 14.3 情绪安抚

重点：

```text
Emotion

Emotion Intensity

Possible Cause

Implicit Need

WillingnessToTalk

NeedForSilence

RiskSignal
```

---

# 14.4 安全与领域事件

重点：

```text
HELP

DISCOMFORT

RiskSignal

Health Entity

RequiresSafetyReview
```

---

# 14.5 领域提醒

重点：

```text
PendingQuestion

REMINDER_RESPONSE

Confirmation

Rejection

Task Context
```

---

# 14.6 领域任务交互

重点：

```text
COGNITIVE_INTERACTION

Answer

Skip

Stop

Current Task
```

---

# 14.7 长期记忆

重点：

```text
MEMORY_QUERY

MEMORY_COMMAND

MemoryCandidate

Reference to Memory
```

---

# 14.8 新闻天气

重点：

```text
QUERY_INFORMATION

domain

date

location

follow-up reference
```

例如：

> “那后天呢？”

通过前文继承：

```text
domain = WEATHER

city = previous_city

date = day_after_tomorrow
```

---

# 15. 异常、超时与降级

# 15.1 LLM 不可用

降级：

```text
Deterministic Parse

+

Context

→ partial UnderstandingState
```

并：

```text
uncertainty = HIGH
```

---

# 15.2 Reference Resolver 失败

输出：

```text
unresolved_reference
```

不要强猜。

---

# 15.3 Emotion Analyzer 失败

输出：

```text
emotion = UNKNOWN
```

不影响基础任务理解。

---

# 15.4 Need Inference 失败

输出：

```text
implicit_need = UNKNOWN
```

Explicit Goal 仍可继续。

---

# 15.5 Risk 模块失败

不能输出：

```text
NO_RISK
```

应：

```text
risk_status = UNAVAILABLE
```

并交 M2 保守处理。

---

# 15.6 Schema Validation 失败

模型结果：

```text
不得直接进入 M4
```

应：

```text
修复

重试

或降级为 partial understanding
```

---

# 16. 配置项与可变项

建议配置：

```text
intent_taxonomy

emotion_taxonomy

need_taxonomy

entity_taxonomy

context_selection_rules

confidence_thresholds

clarification_thresholds

fast_path_rules

deep_path_rules

risk_review_rules

model_config

prompt_version

schema_version
```

---

## 16.1 Taxonomy Registry

建立：

```text
IntentRegistry

EmotionRegistry

NeedRegistry

EntityRegistry
```

避免分类散落代码。

---

## 16.2 IntentDefinition

```text
id

name

description

parent

required_entities

optional_entities

examples

enabled
```

---

## 16.3 EmotionDefinition

```text
id

name

parent_category

description

typical_signals

business_mapping

enabled
```

---

## 16.4 NeedDefinition

```text
id

name

description

compatible_actions

conflicting_actions
```

注意 compatible_actions 只是供 M4 参考。

---

# 17. 非功能约束

# 17.1 性能

第一版不建议每轮多模型串行。

推荐：

```text
Fast Parse

+

1次主LLM Structured Understanding

+

必要时1次Risk Pass
```

---

# 17.2 Fast Path 优先

明显命令尽量：

```text
本地规则快速完成
```

例如：

```text
停止
音量
下一首
确认
取消
```

---

# 17.3 Deep Path 控制

只有真正需要：

```text
复杂情绪

关系语义

隐含需求

复杂多轮
```

才进入 Deep Path。

---

# 17.4 响应预算

M3 必须纳入整机：

```text
普通闲聊首包 ≤5秒
```

的总预算。

因此 M3 不应默认进行大量串行模型调用。

---

# 17.5 稳定性

LLM 输出必须：

```text
Structured Output

Schema Validation

Grounding Validation
```

后才能进入 M4。

---

# 17.6 隐私

LLM Context 只发送当前理解必要信息。

不要：

```text
每轮全量上传全部人生 Memory
```

---

# 18. Trace / Logging / Observability

每轮至少记录：

```text
selected_context

input_precheck

deterministic_parse

reference_result

context_fusion

route

llm_result

risk_result

conflict_resolution

validation_result

uncertainty

candidate_actions

final_understanding_state
```

---

## 18.1 Understanding Diff

建议记录：

```text
Rule Result

vs

LLM Result

vs

Final Result
```

例如：

```text
Rule:
STOP

LLM:
CHAT

Final:
STOP
```

方便发现模型与规则冲突。

---

## 18.2 Prompt Trace

至少记录：

```text
model_version

prompt_version

schema_version
```

方便 Prompt 回归。

---

# 19. 版本、兼容与变更影响

# 19.1 Prompt Version

每次 Understanding Prompt 修改：

```text
必须版本化
```

---

# 19.2 Schema Version

UnderstandingState：

```text
schema_version
```

必须存在。

---

# 19.3 可配置变化

例如新增：

```text
昆曲
```

一般只需要：

```text
Content Entity / Taxonomy
```

无需改 M3 Core。

---

# 19.4 新增普通情绪

例如：

```text
怀旧后的失落
```

可以：

```text
更新 EmotionRegistry
```

无需重写 Pipeline。

---

# 19.5 新增业务模块

例如：

```text
家庭留言
```

可能需要：

```text
新增 Intent / Entity
```

但：

```text
ReferenceResolver

EmotionAnalyzer

NeedAnalyzer

Uncertainty
```

仍复用。

---

# 19.6 Breaking Change

以下可能影响 M4 / M8：

```text
删除 UnderstandingState 核心字段

改变 RiskSignal 语义

改变 IntentRelation 定义

改变 MemoryCandidate 契约
```

必须升级 Schema Version。

---

# 20. 测试 / Eval

M3 不应只测 Intent Accuracy。

建议建立以下测试体系。

---

# 20.1 基础意图测试

```text
播放

停止

聊天

认知

天气

提醒回应
```

---

# 20.2 同义表达测试

例如 STOP：

```text
别放了

关了吧

够了

不用了

停一下
```

---

# 20.3 Multi-intent 测试

```text
情绪 + 播放

不适 + 停止

停止 + 新播放
```

---

# 20.4 Reference 测试

```text
他

她

那个

昨天那个

再来一个
```

---

# 20.5 省略测试

第一轮：

> “今天北京冷不冷？”

第二轮：

> “明天呢？”

---

# 20.6 修正测试

```text
不是A，是B

算了，换B

刚才说错了
```

---

# 20.7 Emotion 测试

覆盖：

```text
明显情绪

隐含情绪

混合情绪

无情绪

不确定情绪
```

---

# 20.8 Implicit Need 测试

覆盖：

```text
只想表达

想被倾听

想得到行动帮助

想安静

想获得信息

想找真人
```

---

# 20.9 Risk 测试

覆盖：

```text
明确风险

隐晦风险

上下文型风险

普通负面表达

误报干扰样例
```

---

# 20.10 Context Conflict 测试

例如：

```text
长期喜欢京剧

+

当前不想听京剧
```

---

# 20.11 老年语言特征测试

覆盖：

```text
重复

断续

长停顿

自我修正

口语省略

模糊词
```

---

# 20.12 Agent Interaction 测试

例如：

```text
用户嫌机器人烦

用户拒绝继续交流

连续拒绝建议

机器人重复提问
```

---

## 20.13 核心指标

建议：

```text
Intent Accuracy

Multi-intent Recall

Entity Accuracy

Reference Resolution Accuracy

Emotion Accuracy

Emotion Over-Inference Rate

Need Inference Accuracy

Need Over-Inference Rate

Risk Recall

Risk False Positive Rate

Clarification Precision

Clarification Recall

Context Utilization Accuracy

Schema Validity Rate
```

---

## 20.14 Over-Inference Rate

这是陪护 Agent 的关键指标。

必须专门统计：

```text
Emotion Over-Inference Rate

Need Over-Inference Rate

Memory Overuse Rate
```

防止：

```text
用户普通说一句话
→ 系统硬解释成孤独、焦虑、需要安慰
```

---

## 20.15 Risk Eval

高风险规则和语料必须单独审核。

当前需求已经明确：

```text
高风险情绪语料

高风险不适关键词
```

属于后续审核内容，而不是由开发自行随意补充。

---

# 21. Gate

## Gate M3-01

M3 不再只输出单一 Intent。

必须输出：

```text
UnderstandingState
```

---

## Gate M3-02

支持 Multi-intent。

---

## Gate M3-03

支持否定。

---

## Gate M3-04

支持修正。

---

## Gate M3-05

支持 Pending Question。

---

## Gate M3-06

支持基础 Reference Resolution。

---

## Gate M3-07

能够利用 M1 Context 完成省略理解。

---

## Gate M3-08

Emotion 与 Risk 分离。

---

## Gate M3-09

Implicit Need 必须带 confidence 和 Evidence。

---

## Gate M3-10

支持 UNKNOWN。

---

## Gate M3-11

支持 Uncertainty。

---

## Gate M3-12

支持 needs_clarification。

---

## Gate M3-13

M3 不调用 Tool。

---

## Gate M3-14

M3 不修改 State。

---

## Gate M3-15

M3 不直接写 Memory。

---

## Gate M3-16

M3 不生成最终用户回复。

---

## Gate M3-17

RiskSignal 可以触发 M2 Safety Re-evaluation。

---

## Gate M3-18

当前表达优先于旧 Memory。

---

## Gate M3-19

LLM 输出必须经过 Schema Validation。

---

## Gate M3-20

LLM 失败存在结构化降级。

---

## Gate M3-21

重要推断具有 Evidence。

---

## Gate M3-22

存在 Over-Inference 专项测试。

---

## Gate M3-23

Fast Path 与 Deep Path 都已实现。

---

## Gate M3-24

Reference / PendingQuestion Resolver 在 LLM 前执行。

---

## Gate M3-25

ConflictResolver 能处理 Rule / LLM / Context 冲突。

---

# 22. 交付物

M3 最终至少形成：

```text
M3-01 Understanding总体架构

M3-02 Runtime Understanding主流程

M3-03 UnderstandingState Schema

M3-04 Intent Taxonomy

M3-05 Entity Schema

M3-06 Speech Act规范

M3-07 Deterministic Parser规范

M3-08 Understanding Context Selector

M3-09 Reference Resolution规范

M3-10 Context Fusion规范

M3-11 Emotion Understanding规范

M3-12 Implicit Need规范

M3-13 Interaction State规范

M3-14 Risk Signal规范

M3-15 Uncertainty / Clarification规范

M3-16 Rule + LLM混合理解方案

M3-17 Fast / Deep Router

M3-18 Understanding Prompt规范

M3-19 Conflict Resolver

M3-20 Grounding / Schema Validator

M3-21 Confidence规范

M3-22 Candidate Action规范

M3-23 MemoryCandidate规范

M3-24 M3 Eval Dataset

M3-25 M3自动化测试

M3-26 M3 Trace规范

M3-27 M3 Gate验证报告
```

---

# 附录 A：第一版实现推荐

第一版不要做多个模型。

建议：

```text
规则解析
+
1次主LLM Structured Understanding
+
必要时1次Risk Pass
+
确定性后处理
```

真正工程流程：

```text
Fast Parse
↓
Context Selection
↓
Reference Resolution
↓
Route
↓
LLM（必要时）
↓
Merge
↓
Risk
↓
Validation
↓
UnderstandingState
```

---

# 附录 B：典型理解案例

## B.1 普通任务

用户：

> “给我放段评书。”

```text
intent =
PLAY_CONTENT

content_type =
STORYTELLING

goal =
START_PLAYBACK

risk =
NONE
```

---

## B.2 Context 依赖

前：

> “给我放越剧。”

后：

> “换一个。”

```text
intent =
CONTROL_PLAYBACK

operation =
NEXT

category =
YUE_OPERA
```

---

## B.3 隐含孤独

用户：

> “这两天他们都忙，也没什么人和我说话。”

```text
emotion =
possible_loneliness

implicit_need =
companionship / listening

confidence =
medium

risk =
normal
```

---

## B.4 不要过度理解

用户：

> “我女儿今天加班。”

无其他负面上下文：

```text
topic =
daughter_work

emotion =
UNKNOWN / neutral

implicit_need =
UNKNOWN
```

不能：

```text
loneliness = high
```

---

## B.5 不想交流

用户：

> “我不想说了。”

```text
intent =
STOP_CONVERSATION

willingness_to_talk =
LOW

need_for_silence =
HIGH / possible
```

如果前文已有风险：

```text
risk_context
不能因为 STOP 被清掉
```

---

## B.6 Multi-intent

用户：

> “我有点难受，把音乐停了吧。”

```text
intents =
DISCOMFORT
STOP_PLAYBACK

relation =
PARALLEL / SEQUENTIAL
```

---

## B.7 明确风险

用户：

> “快来人，我喘不过气。”

```text
intents =
HELP
DISCOMFORT

risk_signal =
HIGH

requires_safety_review =
true
```

---

## B.8 修正

用户：

> “明天……不是，后天我女儿来。”

```text
correction = true

superseded_time =
tomorrow

final_time =
day_after_tomorrow
```

---

## B.9 Agent Frustration

用户：

> “怎么又问，我刚才不是说了吗？”

```text
emotion =
frustration

frustration_target =
AGENT

interaction_issue =
REPETITIVE_QUESTIONING

willingness_for_questions =
LOW
```

---

## B.10 高风险情绪

用户：

> “活着也没什么意思。”

```text
risk_signal =
POSSIBLE_HIGH_RISK_EMOTION

requires_safety_review =
true
```

M3 不直接执行通知。

---

# 附录 C：推荐代码结构

```text
understanding/

├── orchestrator.py
├── models.py
├── schemas.py
├── validator.py
├── confidence.py
│
├── routing/
│   └── router.py
│
├── semantic/
│   ├── parser.py
│   ├── deterministic.py
│   └── llm_analyzer.py
│
├── intent/
│   ├── registry.py
│   └── resolver.py
│
├── reference/
│   ├── resolver.py
│   └── entity_linker.py
│
├── context/
│   ├── selector.py
│   └── fusion.py
│
├── emotion/
│   ├── analyzer.py
│   └── taxonomy.py
│
├── needs/
│   ├── analyzer.py
│   └── taxonomy.py
│
├── interaction/
│   └── analyzer.py
│
├── risk/
│   ├── detector.py
│   └── models.py
│
├── uncertainty/
│   └── analyzer.py
│
├── candidate_actions/
│   └── generator.py
│
└── prompts/
    └── understanding/
```

---

# 附录 D：M3 完成后的系统状态

完成 M3 后，系统从：

```text
“用户说了一句话”
```

升级为：

```text
知道用户表面说了什么

知道用户明确想做什么

知道有没有多个需求

知道有没有否定、修正、省略、指代

知道当前话题是什么

知道当前可能是什么情绪

知道这种情绪可能和什么有关

知道用户可能真正需要什么

知道用户愿不愿意继续聊

知道用户是否已经对机器人产生烦躁

知道有没有潜在风险

知道哪些判断确定

知道哪些只是推测

知道哪些地方应该澄清
```

这时系统才真正开始具备：

```text
“懂人”
```

的能力。

---

# 附录 E：M3 与 M4 的最终关系

可以把二者最终概括成：

```text
M3：
我理解到了什么？

M4：
基于这种理解，
我下一步怎么做？
```

例如 M3 输出：

```text
用户正在谈女儿

可能存在轻度孤独

当前更需要倾听

仍愿意继续交流

刚刚拒绝了音乐建议

风险正常
```

M4 才决定：

```text
ACKNOWLEDGE
→ LISTEN
→ 轻度 EXPLORE
```

而不是 M3 自己直接回复：

> “别难过，我陪你。”

因此：

```text
M3
=
Current User Interaction State

M4
=
Next Best Agent Behavior
```