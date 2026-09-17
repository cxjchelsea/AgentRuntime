# 可复用 Agent Runtime 平台  
# M3 Understanding 四项关键子设计 V1.0

> **Phase 0 Fix**  
> `UnderstandingState` 以 Canonical Registry 嵌套结构为准。  
> 本文 L2 Business Intent / 业务 Need / 业务 Action 列表全部降为 Domain Example，不是 Frozen Core。  
> Core Control Intents 仅 `UNKNOWN` / `STOP` / `CANCEL` / `HELP`。

> **平台化转换说明**  
> 本文已从单一业务 Agent 设计转换为 **可复用 Agent Runtime 平台**设计。除明确标记为 `Core` 的对象、接口、不变量和生命周期外，任何具体业务 Intent、Entity、Workflow、Skill、Tool、知识域、状态字段、规则、提示词或示例均视为 **Domain Package 示例**，不得硬编码进 Runtime Core。新项目应通过 Registry / Adapter / Plugin / Config 注入领域差异。
> 
> 平台固定边界：`Runtime Core` 尽量稳定；`Domain Extension` 插件化；`Business Package` 配置化；`Application` 负责产品装配。

---

# 第一部分：M3-02 UnderstandingState Schema 详细设计

## 1. 设计目标

`UnderstandingState` 是 M3 最重要的正式交付物。

其作用是把：

```text
用户当前输入
+
M1 RuntimeContext
+
M3 理解结果
```

转换为：

```text
一个结构稳定、可追踪、可验证、
能够直接供 M2 和 M4 使用的用户当前交互状态
```

后续必须保持：

```text
M3 → UnderstandingState → M4
```

这一接口稳定。

---

## 2. Schema 总体结构

建议第一版固定为：

```text
UnderstandingState

1. metadata
2. semantic
3. intents
4. goal
5. entities
6. references
7. topic
8. emotion
9. needs
10. interaction
11. risk
12. uncertainty
13. evidence
14. memory_candidates
15. candidate_actions
16. quality
```

---

## 3. metadata

```text
metadata

understanding_id
request_id
session_id
turn_id

schema_version
model_version
prompt_version

created_at
processing_path
```

`processing_path` 建议记录：

```text
FAST_PATH
DEEP_PATH
HYBRID_PATH
DEGRADED_PATH
```

这样后续能知道本轮到底用了什么理解路径。

---

# 4. semantic

描述当前话语的基础语义结构。

```text
semantic

raw_meaning
normalized_meaning

speech_act

negation
correction
repetition
hesitation

temporal_expressions

multi_clause
```

---

## 4.1 speech_act

建议固定枚举：

```text
GREETING
STATEMENT
QUESTION
REQUEST
COMMAND

ANSWER
CONFIRMATION
REJECTION
CORRECTION

COMPLAINT
EMOTIONAL_EXPRESSION

FAREWELL

UNKNOWN
```

它与 Intent 分离。

例如：

> “今天一个人都没来。”

可能：

```text
speech_act =
STATEMENT
+
EMOTIONAL_EXPRESSION
```

但不一定存在明确工具型 Intent。

---

# 5. intents

```text
intents

primary_intent

secondary_intents[]

intent_relations[]

confidence
```

不采用：

```text
intent = 单标签
```

---

## 5.1 IntentRelation

```text
IntentRelation

from_intent
to_intent

relation_type
```

枚举：

```text
PARALLEL
SEQUENTIAL
DEPENDENT
CONFLICTING
SUPERSEDED
```

例如：

> “别放京剧了，换成评书。”

可以解析为：

```text
STOP_CURRENT_CONTENT
→ SEQUENTIAL →
PLAY_CONTENT
```

---

# 6. goal

描述用户明确希望最终完成什么。

```text
goal

explicit_goal
goal_target
goal_parameters

goal_status
goal_confidence
```

状态：

```text
CLEAR
PARTIAL
UNCLEAR
NONE
```

例如：

> “给我放段越剧。”

```text
explicit_goal =
START_CONTENT_PLAYBACK

goal_target =
YUE_OPERA
```

---

# 7. entities

统一实体结构：

```text
entities[]

entity_type
value
normalized_value

source_span

confidence
status
```

`status`：

```text
EXPLICIT
INFERRED
RESOLVED
UNCERTAIN
NEGATED
SUPERSEDED
```

---

## 7.1 第一版 Entity 类型

建议包括：

```text
PERSON
RELATION

CONTENT
CONTENT_CATEGORY

TIME
DATE
DURATION

LOCATION

BODY_PART
SYMPTOM_DESCRIPTION

REMINDER_TYPE

ACTIVITY

WEATHER_DIMENSION

NEWS_CATEGORY

NUMBER

OTHER
```

---

# 8. references

```text
references[]

expression

reference_type

candidate_targets[]

resolved_target

confidence

resolution_source

status
```

状态：

```text
RESOLVED
AMBIGUOUS
UNRESOLVED
```

`resolution_source`：

```text
PENDING_QUESTION
ACTIVE_TASK
CURRENT_BUSINESS
RECENT_TURN
CURRENT_TOPIC
RELATIONSHIP_CONTEXT
MEMORY
```

---

# 9. topic

```text
topic

current_topic
topic_domain

topic_shift
previous_topic

continuation

confidence
```

例如：

```text
topic_domain = FAMILY
```

与：

```text
emotion = loneliness
```

必须保持分离。

---

# 10. emotion

建议：

```text
emotion

primary_emotion
secondary_emotions[]

valence
arousal

intensity

possible_causes[]

confidence

explicit_or_inferred
```

---

## 10.1 valence

```text
POSITIVE
NEUTRAL
NEGATIVE
MIXED
UNKNOWN
```

---

## 10.2 arousal

```text
LOW
MEDIUM
HIGH
UNKNOWN
```

---

## 10.3 intensity

```text
LOW
MEDIUM
HIGH
UNKNOWN
```

注意：

```text
emotion.intensity
!=
safety severity
```

---

# 11. needs

```text
needs[]

need_type
confidence

explicit_or_inferred

evidence_ids[]
```

建议支持多个并存 Need。

例如：

```text
COMPANIONSHIP
+
EMOTIONAL_ACKNOWLEDGEMENT
```

---

# 12. interaction

这一块是情感Agent 应用非常关键的新增结构。

```text
interaction

engagement_level

willingness_to_talk
willingness_to_answer_questions
willingness_to_receive_suggestions

need_for_silence

frustration_with_agent

conversation_fatigue

repetition_detected

interaction_preference
```

---

## 12.1 engagement_level

```text
HIGH
MEDIUM
LOW
DISENGAGED
UNKNOWN
```

---

## 12.2 willingness

统一：

```text
YES
LIKELY
UNCERTAIN
UNLIKELY
NO
```

---

# 13. risk

M3 风险只是 RiskSignal，不是最终 Safety Decision。

```text
risk

signals[]

severity_hint

requires_safety_review

confidence

evidence_ids[]
```

---

## 13.1 RiskSignal 类型

第一版结构预留：

```text
EXPLICIT_HELP

SELF_HARM
HARM_TO_OTHERS

HIGH_RISK_DISCOMFORT

MEDICATION_RISK

FALL_OR_INJURY

ENVIRONMENTAL_DANGER

CONFUSION_OR_DISORIENTATION

OTHER_SAFETY_SIGNAL
```

具体触发标准和医学、安全内容必须由后续经过审核的业务规则定义，M3 只提供结构。

---

# 14. uncertainty

```text
uncertainty

overall_level

uncertain_fields[]

ambiguity_types[]

candidate_interpretations[]

needs_clarification

clarification_target

safe_to_infer
```

---

## 14.1 ambiguity_types

```text
LOW_ASR_CONFIDENCE

AMBIGUOUS_REFERENCE

UNCLEAR_GOAL

MULTIPLE_INTERPRETATIONS

CONFLICTING_CONTEXT

UNKNOWN_ENTITY

UNCLEAR_CONFIRMATION

INSUFFICIENT_CONTEXT
```

---

# 15. evidence

这是 M3 可解释性的基础。

```text
evidence[]

evidence_id

source_type

source_ref

text_or_value

supports_field

strength
```

来源：

```text
CURRENT_INPUT
RECENT_TURN
SESSION_CONTEXT
TASK_CONTEXT
SYSTEM_STATE
MEMORY
RULE_MATCH
MODEL_INFERENCE
```

---

# 16. memory_candidates

M3 可以发现值得后续 M8 考虑的信息，但不能直接保存。

```text
memory_candidates[]

memory_type

content

confidence

source

explicit_user_statement

suggested_scope
```

`suggested_scope`：

```text
SESSION
RECENT
LONG_TERM_CANDIDATE
```

---

# 17. candidate_actions

只表示：

> 从理解角度看可能合适的下一步行为。

```text
candidate_actions[]

action

reason

confidence
```

例如：

```text
ACKNOWLEDGE
EXPLORE
LISTEN
SILENT_COMPANION
CLARIFY
ANSWER
CALL_TOOL
END
ESCALATE_REVIEW
```

最终由 M4 选择。

---

# 18. quality

```text
quality

overall_confidence

schema_valid

context_sufficient

degraded

warnings[]
```

---

# 19. Schema 示例一

用户：

> “今天他们都忙，也没人陪我说话。”

```json
{
  "semantic": {
    "speech_act": [
      "STATEMENT",
      "EMOTIONAL_EXPRESSION"
    ]
  },

  "intents": {
    "primary_intent": "EXPRESS_EMOTION"
  },

  "topic": {
    "current_topic": "social_connection"
  },

  "emotion": {
    "primary_emotion": "LONELINESS",
    "intensity": "MEDIUM",
    "confidence": 0.72,
    "explicit_or_inferred": "INFERRED"
  },

  "needs": [
    {
      "need_type": "COMPANIONSHIP",
      "confidence": 0.78,
      "explicit_or_inferred": "INFERRED"
    },
    {
      "need_type": "LISTENING",
      "confidence": 0.61,
      "explicit_or_inferred": "INFERRED"
    }
  ],

  "risk": {
    "signals": [],
    "requires_safety_review": false
  },

  "uncertainty": {
    "overall_level": "MEDIUM",
    "needs_clarification": false,
    "safe_to_infer": true
  },

  "candidate_actions": [
    {
      "action": "ACKNOWLEDGE"
    },
    {
      "action": "EXPLORE"
    },
    {
      "action": "LISTEN"
    }
  ]
}
```

---

# 20. Schema 示例二：不过度理解

用户：

> “我女儿今天加班。”

```text
topic =
daughter_work

emotion =
UNKNOWN

implicit_need =
UNKNOWN

risk =
none
```

不允许因为“女儿”和养老场景自动推断：

```text
loneliness
```

---

# 第二部分：M3-03/08/09 Intent / Emotion / Need Taxonomy 设计

# 21. Taxonomy 总体原则

三套分类必须满足：

```text
少而稳定
+
可扩展
+
层级化
+
与具体内容解耦
```

不能把业务总表里的 Domain Package 中的业务分类项全部转换成 Intent。领域目录更适合作为 Business / Knowledge Taxonomy，由 Domain Package 提供。

---

# 22. Intent Taxonomy

> 本节 L2 业务 Intent 为 **Domain Example**，不是 Frozen Core。Core 只保留 `UNKNOWN` / `STOP` / `CANCEL` / `HELP`。

建议分三层：

```text
L1 Interaction Intent

L2 Business Intent

L3 Parameters / Entities
```

---

# 23. L1 Interaction Intent

顶层稳定分类：

```text
SOCIAL_INTERACTION

INFORMATION_REQUEST

ACTION_REQUEST

CONTROL

SAFETY_REQUEST

TASK_RESPONSE

MEMORY_INTERACTION

UNKNOWN
```

---

# 24. L2 Business Intent 第一版

## Social Interaction

```text
CHAT
GREETING
FAREWELL

EXPRESS_EMOTION

QUIET_COMPANION

SHARE_EXPERIENCE
RECALL_EXPERIENCE
```

---

## Content

```text
PLAY_CONTENT

CONTROL_PLAYBACK
```

播放控制再用：

```text
operation =
PAUSE
RESUME
STOP
NEXT
REPEAT
VOLUME_UP
VOLUME_DOWN
```

---

## Safety / Care

```text
HELP

DISCOMFORT
```

风险等级不直接写成独立 Intent，而由 `risk` 处理。

---

## Reminder

```text
REMINDER_RESPONSE
```

参数：

```text
COMPLETED
LATER
CANCEL
UNCLEAR
```

---

## Cognitive

```text
COGNITIVE_INTERACTION
```

参数：

```text
RIDDLE
IDIOM
POETRY
CALCULATION
SONG_GUESS
...
```

---

## Information

```text
QUERY_INFORMATION
```

参数：

```text
WEATHER
NEWS
DATE
CALENDAR
SEASONAL_TERM
GENERAL
```

---

## Memory

```text
MEMORY_QUERY

MEMORY_SAVE_REQUEST

MEMORY_UPDATE_REQUEST

MEMORY_DELETE_REQUEST
```

---

## Control

```text
STOP_CURRENT_ACTIVITY

REPEAT

CHANGE_TOPIC
```

---

# 25. Intent 不应该包含

不建议：

```text
PLAY_BEIJING_OPERA

PLAY_YUE_OPERA

PLAY_HUANGMEI_OPERA
```

统一：

```text
PLAY_CONTENT

content.category = opera

content.subcategory = beijing_opera
```

这样未来新增昆曲时：

```text
新增 taxonomy 数据
```

即可。

---

# 26. Emotion Taxonomy

建议采用：

```text
基础情绪层
+
业务场景层
```

---

# 27. 基础情绪层

第一版：

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
```

---

# 28. 业务情绪场景层

用 `emotion_context` 或 `scenario_tag` 表达。

例如现有目录里的：

```text
想家与思念亲人

丧亲、离别与哀伤

家庭冲突

被忽视

社交退缩

衰老失落

能力下降

自我价值下降

死亡与未来担忧

生活无意义感

夜间情绪

环境陌生感
```



对应：

```text
primary_emotion
+
scenario_tag
```

例如：

```text
primary_emotion = LONELINESS

scenario_tag =
MISSING_FAMILY
```

---

# 29. 为什么不能直接用 29 个情绪目录做 Emotion

因为目录中混合了：

```text
情绪
原因
生活场景
关系状态
安全状态
```

例如：

```text
健康问题引起的情绪
```

不是一种基础 Emotion。

更合理：

```text
emotion = ANXIETY

cause/scenario =
HEALTH_CONCERN
```

---

# 30. Need Taxonomy

Need 是整个情感Agent 应用特别重要的中间层。

推荐第一版：

```text
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

# 31. Need 定义示例

## COMPANIONSHIP

含义：

```text
希望存在持续的社会互动或陪伴感。
```

不能仅因为用户独处就自动推断。

---

## LISTENING

```text
用户当前更需要表达，
而不是立即获得建议或解决方案。
```

---

## EMOTIONAL_ACKNOWLEDGEMENT

```text
用户需要自己的感受被看见和回应。
```

---

## QUIET_PRESENCE

```text
用户不希望继续说话，
但仍可能需要低打扰陪伴。
```

---

## REASSURANCE

```text
当前希望获得安定感或确认。
```

不等于提供虚假的：

> “肯定没事。”

---

## ACTION_HELP

表示：

```text
用户需要系统实际完成某个动作。
```

例如播放内容。

---

## HUMAN_HELP

表示：

```text
用户希望真人介入。
```

与普通陪伴需求必须明显区分。

---

# 32. Need 推断原则

必须遵守：

```text
显式需要
>
上下文充分的隐含需要
>
低置信度推测
```

禁止：

```text
任何负面情绪
→ COMPANIONSHIP
```

---

# 33. Intent / Emotion / Need 三者关系

必须分开：

```text
Intent
=
用户在做什么

Emotion
=
用户当前可能感受什么

Need
=
当前可能希望获得什么
```

例如：

> “今天真没意思，放点老歌吧。”

```text
Intent =
EXPRESS_EMOTION
+
PLAY_CONTENT

Emotion =
BOREDOM

Need =
ENTERTAINMENT
+
可能的 COMPANIONSHIP
```

---

# 34. Taxonomy 配置结构

建议所有 Taxonomy 外置。

例如：

```yaml
emotion:
  loneliness:
    parent: negative_social
    enabled: true

need:
  companionship:
    enabled: true
    compatible_actions:
      - acknowledge
      - listen
      - explore
```

但：

```text
compatible_actions
```

只用于 M4 参考。

---

# 第三部分：M3-13 Rule + LLM Hybrid Pipeline 详细设计

# 35. 总体目标

不是：

```text
所有输入 → LLM
```

而是：

```text
确定性问题
→ Rule / Resolver

真正需要理解的问题
→ LLM

最后
→ Validator / Resolver
```

推荐结构：

```text
RuntimeInput
+
RuntimeContext
        ↓
① Preprocessor
        ↓
② Fast Rule Parser
        ↓
③ Context Selector
        ↓
④ Reference Resolver
        ↓
⑤ Path Router
      /         \
 Fast Path     Deep Path
      \         /
        ↓
⑥ Result Merger
        ↓
⑦ Risk Review
        ↓
⑧ Conflict Resolver
        ↓
⑨ Schema Validator
        ↓
⑩ Confidence / Uncertainty
        ↓
UnderstandingState
```

---

# 36. Step 1 Preprocessor

负责：

```text
文本规范化

保留否定

保留修正

保留必要重复

时间表达初步解析

ASR segment 整理
```

不能过度清洗。

例如：

```text
“不是，我不是头疼，是头晕”
```

不能清洗成：

```text
“我头疼头晕”
```

否则语义被破坏。

---

# 37. Step 2 Fast Rule Parser

适合处理：

```text
停止

播放控制

提醒确认

明确 yes / no

固定时间表达

pending_question 回复

明显求助词

基础数字

明确 Tool 控制词
```

输出：

```text
RuleParseResult
```

---

# 38. RuleParseResult

```text
matched_rules

high_confidence_intents

entities

pending_question_resolution

safety_hits

confidence
```

---

# 39. Step 3 Context Selector

按当前输入选择：

```text
recent_turns

pending_question

active_task

current_business

current_topic

person_context

relevant_memory

tool_context
```

而不是发送全量历史。

---

# 40. Step 4 Reference Resolver

优先尝试确定性解析：

```text
Pending Question
>
Active Task
>
Current Business
>
Last Explicit Object
>
Current Topic
>
Relationship Context
>
Memory
```

如果解析成功：

```text
resolved_reference
```

直接作为 Deep Understanding 输入。

---

# 41. Step 5 Path Router

判断：

```text
FAST_PATH
还是
DEEP_PATH
```

---

# 42. Fast Path 条件

适合：

```text
高置信度停止

暂停/继续

音量控制

提醒明确回答

简单内容播放

简单事实查询

明确认知活动请求
```

例如：

> “暂停。”

无需为了“智能”调用大模型。

---

# 43. Deep Path 条件

出现以下任一情况：

```text
情绪表达

隐含需求

多意图

复杂修正

模糊目标

复杂指代

关系话题

用户对 Agent 不满

上下文冲突

需要情绪强度理解

可能存在隐含风险
```

则进入 Deep Path。

---

# 44. Deep Path LLM 输入

建议只给：

```text
CURRENT_INPUT

CURRENT_STATE

ACTIVE_TASK

PENDING_QUESTION

SELECTED_RECENT_TURNS

CURRENT_TOPIC

RELEVANT_RELATIONSHIP

RELEVANT_MEMORY

RULE_PARSE_RESULT
```

---

# 45. LLM 输出任务

只允许输出结构化：

```text
semantic

intents

goal

emotion

needs

interaction

references

risk_signals

uncertainty

evidence
```

明确禁止：

```text
最终回复

直接 Tool Call

State 修改

Memory 写入
```

---

# 46. Prompt 的核心约束

Prompt 必须强调：

```text
1. 当前任务是理解，不是回复。

2. 区分用户明确表达与模型推测。

3. 没有足够依据时返回 UNKNOWN。

4. 不进行医学、心理诊断。

5. 不因为养老场景自动推断孤独、认知障碍等。

6. 当前明确表达优先于历史偏好。

7. 高风险只标记 signal，不决定业务执行。

8. 不虚构 Context 中不存在的人物、事实或事件。
```

---

# 47. Step 6 Result Merger

合并：

```text
RuleResult
+
ReferenceResult
+
LLMResult
```

不能简单“模型覆盖规则”。

---

# 48. 合并优先级

建议：

```text
Hard Context Fact

>
Pending Task / Pending Question

>
高置信度显式 Rule

>
当前输入中的明确表达

>
LLM Contextual Inference

>
Memory-derived Inference
```

---

# 49. 示例

规则：

```text
用户当前回答 NO
```

Pending：

```text
HELP_CONFIRMATION
```

LLM 却识别：

```text
STOP_CONVERSATION
```

最终应优先：

```text
HELP_CONFIRMATION_RESPONSE = NO
```

---

# 50. Step 7 Risk Review

分两阶段：

```text
Early Safety
已经处理明显风险

Deep Risk Review
处理上下文型/隐含风险
```

M3 输出：

```text
RiskSignal
```

然后返回 M2：

```text
Safety Re-evaluation
```

---

# 51. Step 8 Conflict Resolver

处理：

```text
Rule vs LLM

Memory vs Current Input

多个 Intents

多候选 Reference

Emotion vs Context

Need vs Explicit Goal
```

---

# 52. 当前表达与 Memory 冲突

必须：

```text
当前明确表达保持当前有效状态
```

但不能直接删除长期 Memory。

例如：

```text
Memory:
喜欢京剧

Input:
“最近不想听京剧。”
```

Understanding：

```text
current_preference =
AVOID_BEIJING_OPERA

historical_preference =
LIKE_BEIJING_OPERA

conflict =
true
```

后续 M8 再判断是否修改记忆。

---

# 53. Step 9 Schema Validator

检查：

```text
枚举是否合法

必填字段

Evidence 是否存在

Entity 是否有来源

推断是否被错误标记为 Fact

Risk 结构是否正确

Confidence 范围

是否出现禁用字段
```

任何 LLM 输出都不得绕过 Validator。

---

# 54. Step 10 Confidence / Uncertainty

最终根据：

```text
ASR质量

Rule一致性

Context充分程度

LLM置信度

Reference确定性

多结果冲突
```

生成：

```text
overall_confidence

uncertain_fields

needs_clarification
```

---

# 55. 降级链

建议：

```text
正常：
Rule + LLM + Resolver

LLM失败：
Rule + Context + UNKNOWN

Context部分失败：
可用Context + uncertainty

Reference失败：
UNRESOLVED_REFERENCE

Emotion失败：
emotion = UNKNOWN

Need失败：
need = UNKNOWN

Risk组件失败：
risk_status = UNAVAILABLE
→ M2保守处理
```

---

# 56. Pipeline 可观测性

Trace 至少记录：

```text
selected_context

rule_hits

reference_resolution

path_selected

llm_result

risk_result

conflict_resolution

validation_result

final_understanding
```

---

# 57. 第一版实现建议

第一版无需做多个 Agent。

推荐：

```text
RuleParser

ContextSelector

ReferenceResolver

MainUnderstandingLLM

RiskReviewer

ResultMerger

UnderstandingValidator
```

七个组件就足够。

---

# 第四部分：M3-19 Eval Dataset & Evaluation 详细设计

# 58. 设计目标

M3 不能以：

> “我和它聊了几句，感觉挺聪明。”

作为验收方式。

必须建立固定：

```text
M3 Evaluation Dataset
```

用于：

```text
Prompt修改

模型替换

规则调整

Taxonomy修改

Context策略变化
```

后的回归测试。

---

# 59. Dataset 单条结构

建议：

```text
EvalCase

case_id

category

input

context

expected

allowed_variants

forbidden_outputs

risk_level

difficulty

tags
```

---

# 60. expected 内容

根据案例不同填写：

```text
intents

entities

references

emotion

needs

interaction

risk

uncertainty

clarification
```

不要求每个案例都评价全部字段。

---

# 61. 样例结构

```yaml
case_id: M3-CTX-001

category: reference

context:
  current_business: playback
  current_content_category: yue_opera

input:
  "再来一个"

expected:
  intent:
    - PLAY_CONTENT

  reference:
    category: yue_opera

  operation:
    next

forbidden_outputs:
  - ask_user_what_content
```

---

# 62. Dataset 一级分类

建议至少建立 14 大类。

---

## A. 基础 Intent

覆盖：

```text
chat
play
stop
help
discomfort
reminder
cognitive
weather
news
memory
```

---

## B. 同义表达

例如停止：

```text
停一下
别说了
不用了
够了
关了吧
```

---

## C. 多 Intent

例如：

```text
情绪 + 播放

不适 + 停止播放

求助 + 身体不适

停止当前内容 + 请求新内容
```

---

## D. Negation

例如：

```text
“我不是想听歌。”

“我没觉得害怕。”
```

---

## E. Correction

```text
“不是明天，是后天。”

“不是头疼，是头晕。”
```

---

## F. Reference

```text
他
她
他们
那个
这个
昨天那个
之前那个
再来一个
```

---

## G. Ellipsis

例如：

前：

> “明天北京天气怎么样？”

后：

> “后天呢？”

---

## H. Emotion

覆盖：

```text
明显情绪

隐含情绪

混合情绪

不确定情绪

无情绪控制组
```

---

## I. Need Inference

覆盖：

```text
LISTENING

COMPANIONSHIP

QUIET_PRESENCE

INFORMATION

ACTION_HELP

HUMAN_HELP

UNKNOWN
```

---

## J. Over-Inference Negative Set

这是必须单独建立的一组。

例如：

> “我女儿今天加班。”

期望：

```text
emotion = UNKNOWN / neutral
```

禁止：

```text
loneliness
abandonment
```

---

## K. Interaction State

例如：

```text
“你别老问了。”

“刚才不是说过了吗？”

“我想静静。”
```

---

## L. Risk

包括：

```text
明确高风险

含蓄风险

普通负面但非高风险

安全词误报干扰

上下文组合风险
```

---

## M. Elderly Speech Pattern

覆盖：

```text
重复

断续

口语

自我修正

停顿

模糊词

不完整表达
```

---

## N. Context Conflict

例如：

```text
Memory喜欢京剧
+
当前说不想听京剧
```

---

# 63. Difficulty

建议：

```text
EASY

MEDIUM

HARD

ADVERSARIAL
```

---

# 64. HARD 案例示例

前文：

> “女儿最近工作特别忙。”

数轮以后：

> “她也不容易，我就是有时候一个人闷得慌。”

需要同时理解：

```text
她 = daughter

emotion =
possible loneliness

need =
companionship/listening

attitude_toward_daughter =
understanding

risk =
normal
```

不能把它理解成：

```text
family conflict
```

---

# 65. 指标体系

## 65.1 Intent

```text
Intent Precision

Intent Recall

Multi-intent Recall

Intent Relation Accuracy
```

---

## 65.2 Entity

```text
Entity Precision

Entity Recall

Entity Normalization Accuracy
```

---

## 65.3 Reference

```text
Reference Resolution Accuracy

Ambiguous Reference Detection Accuracy
```

---

## 65.4 Emotion

```text
Emotion Accuracy

Emotion Macro-F1

Emotion Intensity Accuracy
```

但最重要的附加指标是：

```text
Emotion Over-Inference Rate
```

---

# 66. Emotion Over-Inference Rate

定义：

```text
本应 UNKNOWN / Neutral
却被错误推断为明确情绪
的比例
```

这是情感Agent 应用必须重点控制的指标。

---

# 67. Need 指标

```text
Need Precision

Need Recall

Need Over-Inference Rate
```

其中 Precision 应优先于盲目提高 Recall。

因为：

```text
猜错用户需要什么
```

很容易导致 M4 行为变得冒犯或机械。

---

# 68. Risk 指标

风险建议独立评估：

```text
Risk Recall

Risk Precision

Risk False Negative Rate

Risk False Positive Rate
```

安全场景更重视：

```text
Recall
```

但不能完全牺牲误报率。

---

# 69. Clarification 指标

建议：

```text
Clarification Precision
```

表示：

> 系统决定追问的时候，有多少真的应该追问。

以及：

```text
Clarification Recall
```

表示：

> 真正需要澄清的案例，有多少识别出来。

---

# 70. Context 指标

```text
Context Utilization Accuracy

Context Conflict Resolution Accuracy

Pending Question Resolution Accuracy

Context-independent Robustness
```

---

# 71. Schema 指标

```text
Schema Validity Rate

Unsupported Fact Rate

Hallucinated Entity Rate
```

---

# 72. Unsupported Fact Rate

如果模型输出：

```text
daughter_name = 王芳
```

而 Input / Context 从未出现：

```text
王芳
```

计为 unsupported fact。

这是 M3 非常重要的质量指标。

---

# 73. Composite Score

不建议简单把所有指标平均。

M3 可以划分四个 Gate：

```text
Semantic Gate

Context Gate

Emotional Understanding Gate

Safety Gate
```

每个 Gate 独立通过。

安全 Gate 不应被普通 Intent 高分抵消。

---

# 74. Regression Dataset

固定一部分案例：

```text
Golden Set
```

后续任何：

```text
模型升级
Prompt修改
规则修改
Taxonomy修改
```

都必须跑。

---

# 75. Golden Set 第一版规模建议

PoC 阶段先建立：

```text
150～300 条高质量案例
```

比一开始自动生成几千条低质量样例更有价值。

重点覆盖：

```text
真实难点
+
典型边界
+
业务高风险
```

随着开发再扩展。

---

# 76. 数据来源

建议未来逐步来自：

```text
需求人工设计

业务同事设计

真实匿名化对话

测试中发现的失败样例

模型回归失败样例
```

其中安全/医疗相关预期标签必须经过相应人员审核。

---

# 77. Error Bucket

每次评估失败不要只记录：

```text
wrong
```

应该归类：

```text
INTENT_ERROR

ENTITY_ERROR

REFERENCE_ERROR

CONTEXT_ERROR

EMOTION_ERROR

OVER_INFERENCE

NEED_ERROR

RISK_MISS

RISK_FALSE_POSITIVE

CLARIFICATION_ERROR

SCHEMA_ERROR

HALLUCINATION
```

---

# 78. Error-driven Improvement

后续优化流程应该是：

```text
Eval
↓
Error Bucket
↓
判断问题来源
↓
Rule / Prompt / Model / Context / Taxonomy
↓
只修改对应层
↓
Regression
```

而不是：

```text
感觉不好
↓
重新改一大段 Prompt
```

---

# 79. M3 四个子设计之间的最终关系

四个子设计不是并列孤立文件。

关系为：

```text
Taxonomy
定义：
“系统允许理解成什么”

↓

UnderstandingState Schema
定义：
“理解结果以什么结构存在”

↓

Rule + LLM Pipeline
定义：
“如何从输入得到这个结构”

↓

Eval Dataset
定义：
“如何判断这个理解到底对不对”
```

可以概括成：

```text
Vocabulary
↓
Representation
↓
Computation
↓
Evaluation
```

---

# 80. 四项子设计的推荐正式文件拆分

正式落盘建议拆成：

```text
M3-02_UnderstandingState_Schema.md

M3-03_Intent_Emotion_Need_Taxonomy.md

M3-13_Rule_LLM_Hybrid_Understanding_Pipeline.md

M3-19_Understanding_Eval_Dataset_and_Metrics.md
```

---

# 81. 四份文件完成 Gate

## Schema Gate

必须确认：

```text
M4 不需要重新解析 M3 自由文本。
```

M4 可以直接读取结构化 UnderstandingState。

---

## Taxonomy Gate

必须确认：

```text
新增普通内容或场景
不会要求新增一套 Runtime 逻辑。
```

---

## Pipeline Gate

必须确认：

```text
Rule、LLM、Context、Risk
职责清晰，
任何一个失败都有降级路径。
```

---

## Evaluation Gate

必须确认：

```text
M3 的好坏可以通过固定数据集衡量，
而不是依靠主观聊天体验。
```

---

# 82. M3 子设计完成后的状态

完成这四项以后，M3 就从：

```text
“我们需要让模型更懂用户”
```

变成：

```text
系统允许理解哪些东西

理解结果长什么样

如何得到理解结果

如何判断理解结果是否正确
```

也就是说：

```text
目标
→
数据结构
→
算法流程
→
评估体系
```

已经闭环。

此时才真正具备进入 M3 编码实现的条件。
## 平台扩展补充：Taxonomy 所有权

Intent / Entity / Need 的结构由 Core 冻结，具体 Taxonomy 的所有权属于 Domain Package。冻结文档中的具体业务枚举仅是 Schema 示例，不得被实现为所有项目共享的强制枚举。

