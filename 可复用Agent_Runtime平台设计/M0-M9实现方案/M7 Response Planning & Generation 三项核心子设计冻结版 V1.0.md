# 可复用 Agent Runtime 平台  
# M7 Response Planning & Generation 三项核心子设计冻结版 V1.0

> **Phase 0 Fix**  
> `ResponsePlan` 以 Canonical Registry `claim_plan` 为准。`facts_to_include` / `facts_to_avoid` 已失效。

> **平台化转换说明**  
> 本文已从单一业务 Agent 设计转换为 **可复用 Agent Runtime 平台**设计。除明确标记为 `Core` 的对象、接口、不变量和生命周期外，任何具体业务 Intent、Entity、Workflow、Skill、Tool、知识域、状态字段、规则、提示词或示例均视为 **Domain Package 示例**，不得硬编码进 Runtime Core。新项目应通过 Registry / Adapter / Plugin / Config 注入领域差异。
> 
> 平台固定边界：`Runtime Core` 尽量稳定；`Domain Extension` 插件化；`Business Package` 配置化；`Application` 负责产品装配。

---

# 0. 冻结说明

本文件正式冻结 M7 的三项核心设计：

```text
M7-A ResponsePlan + RuntimeResponse Schema

M7-B Claim-preserving Generation + Response Validator

M7-C Elder-friendly Response + Question / TTS Rules
```

正式链路：

```text
UnderstandingState
+
ActionPlan
+
ValidatedResult
+
RuntimeContext
        ↓
M7 Response Planning & Generation
        ↓
RuntimeResponse
        ↓
M8 State & Memory Update
```

职责固定为：

```text
M3
决定用户是什么意思

M4
决定系统要做什么

M6
决定哪些事实是真的、哪些可以说

M7
决定这些内容怎么说

M8
决定这一轮之后留下什么
```

---

# 第一部分  
# M7-A ResponsePlan + RuntimeResponse Schema 冻结规范

## 1. ResponsePlan 定位

`ResponsePlan` 是 M7 内部正式中间对象。

它回答：

```text
这一轮要不要回复？

主要沟通目标是什么？

需要表达哪些事实？

哪些事实不能说？

应该使用什么语气和长度？

要不要提问？

Memory能不能显式提起？

应该使用模板还是LLM？
```

它不是：

```text
最终自然语言文本
```

---

# 2. ResponsePlan Frozen Core

正式冻结：

```text
ResponsePlan

metadata

response_requirement

communicative_goals

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

# 3. metadata

冻结：

```text
response_plan_id

request_id
session_id

schema_version
planner_version
policy_version

created_at
```

---

# 4. response_requirement

冻结结构：

```text
ResponseRequirement

required

response_type

reason_codes[]
```

---

# 5. response_type

正式冻结：

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

# 6. SILENCE 是正式 Response Type

固定：

```text
response_type = SILENCE
```

意味着：

```text
系统当前明确选择不产生语言输出
```

这不是异常。

---

# 7. communicative_goals

冻结为：

```text
communicative_goals[]
```

核心枚举：

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

# 8. Communicative Goal 来源

必须来自：

```text
ActionPlan.response_strategy
```

M7 不得擅自增加新的业务目标。

---

# 9. content_plan

冻结：

```text
ContentPlan

ordered_blocks[]
```

---

# 10. ContentBlock 类型

正式冻结：

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

# 11. ordered_blocks 的意义

回复顺序先由结构确定。

例如：

```text
ACKNOWLEDGEMENT
→ RESULT
→ QUALIFIER
→ QUESTION
```

而不是让 LLM 自由决定所有内容顺序。

---

# 12. claim_plan

冻结：

```text
ClaimPlan

must_include_claims[]

optional_claims[]

forbidden_claims[]

required_qualifiers[]
```

必须直接承接：

```text
ValidatedResult.claim_policy
```

---

# 13. must_include_claims

表示：

```text
这轮必须明确表达的关键事实。
```

例如：

```text
NOTIFICATION_STATUS_UNKNOWN
```

若属于用户必须知道的状态，则不能被模型为了“自然”省略。

---

# 14. optional_claims

允许根据：

```text
长度
语境
用户状态
```

决定是否表达。

---

# 15. forbidden_claims

M7 全流程不可生成。

包括：

```text
LLM Draft
Template
Fallback
```

全部受约束。

---

# 16. required_qualifiers

正式承接 M6。

核心语义例如：

```text
CURRENTLY

NOT_CONFIRMED

PARTIAL

TEMPORARY

SYSTEM_REPORTS

SOURCE_LIMITED
```

---

# 17. tone_profile

冻结：

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

# 18. warmth

核心值：

```text
LOW
MEDIUM
HIGH
```

---

# 19. directness

冻结：

```text
DIRECT

BALANCED

GENTLE
```

---

# 20. complexity

冻结：

```text
SIMPLE

NORMAL
```

默认用户语音交互：

```text
SIMPLE
```

---

# 21. length_policy

冻结：

```text
LengthPolicy

level

max_sentences

max_characters
```

核心级别：

```text
VERY_SHORT

SHORT

MEDIUM

LONG
```

---

# 22. 默认长度原则

默认：

```text
SHORT
```

除非：

```text
用户明确要求详细说明
```

或者属于：

```text
内容型长回答
```

---

# 23. question_plan

冻结：

```text
QuestionPlan

required

question_type

target

question_mode

max_questions
```

---

# 24. question_type

冻结：

```text
CLARIFICATION

OPEN_EXPLORATION

CLOSED_CONFIRMATION

REQUIRED_TASK_FIELD

OPTIONAL_INVITATION
```

---

# 25. question_mode

冻结：

```text
NONE

DIRECT

GENTLE_OPTIONAL

REQUIRED
```

---

# 26. max_questions

普通单轮默认：

```text
1
```

属于 Frozen Core。

Workflow 特殊任务可以显式覆盖，但仍应一轮一题。

---

# 27. memory_expression

冻结：

```text
MemoryExpression

mode

memory_ids[]

explicit_reference_allowed
```

---

# 28. mode

与 M4 正式对齐：

```text
NONE

SILENT_CONTEXT

PERSONALIZE_ACTION

REFERENCE_EXPLICITLY
```

---

# 29. safety_constraints

冻结：

```text
SafetyConstraints

no_diagnosis

no_unverified_reassurance

no_new_medication_advice

no_external_state_fabrication

no_unauthorized_promise
```

---

# 30. tts_constraints

冻结：

```text
TTSConstraints

enabled

max_sentence_length

max_sentences

pause_policy

pronunciation_hints[]

avoid_symbols[]
```

---

# 31. generation_path

冻结四类：

```text
TEMPLATE

LLM

HYBRID

SILENT
```

---

# 32. RuntimeResponse 定位

`RuntimeResponse` 是 M7 唯一正式输出。

表示：

> 本轮真正准备交给用户 / TTS 的最终回复结果。

---

# 33. RuntimeResponse Frozen Core

正式冻结：

```text
RuntimeResponse

metadata

response_type

text

tts_payload

claims_used

question

memory_references

generation_info

validation_status
```

---

# 34. metadata

```text
response_id

response_plan_id

request_id
session_id

created_at
```

---

# 35. text

可以：

```text
string
```

也可以在：

```text
SILENCE
```

时：

```text
null
```

---

# 36. tts_payload

建议：

```text
TTSPayload

text

language

pause_markers

pronunciation_overrides[]
```

---

# 37. claims_used

冻结为：

```text
claims_used[]
```

记录：

```text
本次最终回复实际表达了哪些M6 Claim。
```

---

# 38. question

如果本轮包含问题：

```text
ResponseQuestion

question_type

target

required
```

没有问题则：

```text
null
```

---

# 39. memory_references

记录：

```text
最终文本是否显式引用了Memory
以及引用了哪些Memory。
```

---

# 40. generation_info

```text
generation_path

template_id

model_version

prompt_version
```

---

# 41. validation_status

冻结：

```text
VALID

FALLBACK_VALID

INVALID
```

只有前两者允许输出给用户。

---

# 42. RuntimeResponse 禁止携带

```text
Tool原始结果

新的ActionPlan

State Mutation

Memory Write Operation

未经验证的Fact
```

---

# 43. M7→M8 正式接口

M8 使用：

```text
RuntimeResponse.question

claims_used

memory_references

response_type
```

更新：

```text
pending_question

recent_agent_actions

conversation history

interaction history
```

---

# 第二部分  
# M7-B Claim-preserving Generation + Response Validator 冻结规范

# 44. 核心原则

正式冻结：

```text
M6决定Truth Boundary

M7只能在Truth Boundary内部表达
```

进一步：

```text
Natural Language
不能改变
Validated Truth
```

---

# 45. Truth Monotonicity

正式冻结：

```text
Response Certainty
<=
ValidatedResult Certainty
```

即：

```text
M7可以更谨慎

但不能更确定
```

---

# 46. 示例

M6：

```text
notification_delivery = UNKNOWN
```

允许：

```text
“目前还不能确认通知是否送达。”
```

禁止：

```text
“通知应该已经送到了。”
```

更禁止：

```text
“工作人员已经收到了。”
```

---

# 47. Claim-preserving Generation 主链

正式冻结：

```text
ValidatedResult
        ↓
Claim Compiler
        ↓
ResponsePlan.claim_plan
        ↓
Generator
        ↓
ResponseDraft
        ↓
ResponseValidator
        ↓
RuntimeResponse
```

---

# 48. Claim Compiler 职责

只把：

```text
M6 ClaimPolicy
```

转换成：

```text
M7表达约束
```

不能新增事实。

---

# 49. Claim Compiler 输出

冻结：

```text
CompiledClaims

must_include

may_include

must_not_include

qualifiers

certainty_ceiling
```

---

# 50. certainty_ceiling

表示：

```text
最终生成语言允许达到的最高确定性。
```

---

# 51. Generator 不读取原始 ToolResult

正式冻结：

```text
M7 Generator
不得直接消费原始 ToolResult。
```

正常事实路径只能读取：

```text
ValidatedResult
```

---

# 52. Generator 不得补充模型知识作为执行事实

例如天气 Tool 只返回：

```text
12℃
```

Generator 不能因为模型知道：

```text
12℃通常很冷
```

就自行增加：

```text
“外面风很大”
```

---

# 53. Template / LLM / Hybrid 共用同一 Claim Boundary

无论：

```text
Template
LLM
Hybrid
Fallback
```

全部必须经过：

```text
ClaimPlan
+
ResponseValidator
```

---

# 54. ResponseDraft 冻结结构

```text
ResponseDraft

text

semantic_units[]

claims_used[]

qualifiers_used[]

question_used

promises_detected[]

memory_references[]

generation_metadata
```

---

# 55. ResponseValidator Frozen Checks

正式冻结至少 10 类：

```text
1. Forbidden Claim Check

2. Unsupported Claim Check

3. Required Claim Check

4. Qualifier Preservation Check

5. Certainty Escalation Check

6. Response Goal Drift Check

7. Unauthorized Promise Check

8. Memory Reference Check

9. Safety / Medical Boundary Check

10. Question / Length / TTS Check
```

---

# 56. Forbidden Claim Check

如果任何语义与：

```text
forbidden_claims
```

匹配：

```text
Validation FAIL
```

---

# 57. 不能只靠关键词

例如 forbidden：

```text
STAFF_RECEIVED
```

生成：

> “那边应该已经看到消息了。”

虽然没有“收到”两个字，

语义仍然越界。

因此至少需要：

```text
结构化规则
+
语义检查
```

---

# 58. Unsupported Claim Check

任何新出现的外部事实必须能映射到：

```text
allowed_claims
```

否则：

```text
UNSUPPORTED_CLAIM
```

---

# 59. Required Claim Check

如果：

```text
must_include_claims
```

中的关键 Claim 被模型遗漏：

```text
Validation FAIL
```

例如通知状态 UNKNOWN 不得被省略。

---

# 60. Qualifier Preservation Check

M6：

```text
NOT_CONFIRMED
```

最终回复必须保留不确定语义。

---

# 61. Certainty Escalation Check

禁止：

```text
possible
→ definitely

unknown
→ probably success

request accepted
→ delivered
```

---

# 62. Response Goal Drift Check

M4：

```text
ACKNOWLEDGE
```

M7 却：

```text
推荐音乐
建议联系女儿
```

属于：

```text
GOAL_DRIFT
```

---

# 63. Unauthorized Promise Check

这是 Frozen Core。

禁止生成没有真实 Plan 支持的未来承诺。

例如：

```text
“我马上再帮您联系一次。”

“我会一直替您看着。”

“工作人员马上就来。”
```

除非有对应：

```text
ActionPlan
ValidatedResult / Runtime Task
```

支持。

---

# 64. PromiseDefinition

建议识别：

```text
未来系统动作

第三方未来动作

持续性监控承诺

确定性结果承诺
```

---

# 65. Memory Reference Check

如果：

```text
memory_expression.mode != REFERENCE_EXPLICITLY
```

不得生成：

```text
“我记得您以前说过……”
```

---

# 66. Safety / Medical Boundary Check

继续强制：

```text
no_diagnosis

no_self_medication

no_unverified_health_reassurance

no_external_state_fabrication
```

---

# 67. Validation 顺序

推荐冻结：

```text
Claim checks
↓
Promise / Safety
↓
Goal adherence
↓
Question / Length
↓
TTS
```

事实安全优先于语言风格。

---

# 68. Validator Failure Pipeline

正式冻结：

```text
Draft
↓
Validator FAIL
↓
Controlled Regeneration once
↓
Validator
↓
仍FAIL
↓
Safe Template Fallback
↓
Validator
↓
RuntimeResponse
```

---

# 69. 禁止无限重生成

最大自由重生成次数建议：

```text
1
```

可配置，但必须有硬上限。

---

# 70. Safe Template Fallback

至少准备：

```text
ACKNOWLEDGE_GENERIC

RESULT_SUCCESS

RESULT_FAILURE

RESULT_UNKNOWN

RESULT_WAITING

CLARIFY_GENERIC

SAFETY_STATUS

SYSTEM_ERROR

CLOSING
```

---

# 71. Fallback Template 也必须参数化

例如：

```text
RESULT_UNKNOWN
```

必须使用：

```text
verified / allowed claim
```

填充。

不能写死：

```text
“通知没有成功。”
```

---

# 72. Response Validator Error Codes

冻结核心集合：

```text
FORBIDDEN_CLAIM_GENERATED

UNSUPPORTED_CLAIM

REQUIRED_CLAIM_MISSING

REQUIRED_QUALIFIER_MISSING

CERTAINTY_ESCALATION

RESPONSE_GOAL_DRIFT

UNAUTHORIZED_PROMISE

MEMORY_REFERENCE_VIOLATION

MEDICAL_BOUNDARY_VIOLATION

QUESTION_LIMIT_EXCEEDED

RESPONSE_TOO_LONG

TTS_CONSTRAINT_VIOLATION
```

---

# 73. Claim Trace

最终必须支持：

```text
每个主要用户可见事实
→ 对应Claim
→ 对应VerifiedFact
→ 对应Evidence
```

即：

```text
Response Sentence
↓
Claim
↓
Fact
↓
Evidence
```

---

# 74. 事实链示例

用户回复语义：

```text
“播放已经开始。”
```

Trace：

```text
PLAYBACK_STARTED Claim
↓
playback_status = PLAYING Fact
↓
Playback Device State Evidence
```

---

# 75. Unsupported Naturalness 禁止

即使某句：

```text
很自然
很温暖
很像真人
```

只要越过事实边界：

```text
必须拒绝。
```

---

# 第三部分  
# M7-C 适老表达 + Question / TTS 冻结规范

# 76. 核心定位

这一规范解决：

```text
事实和策略都正确以后，
怎样让用户真正容易听懂和接受。
```

---

# 77. Elder-friendly Frozen Principles

正式冻结：

```text
短句

一轮一个中心

重点靠前

一次最多一个问题

少术语

少复杂从句

少代词歧义

少多重否定

语义直接

允许停顿

不给用户增加不必要认知负担
```

---

# 78. 单轮信息负荷

原则：

```text
必要信息
>
完整信息
```

不是：

```text
系统知道什么都一次说完。
```

---

# 79. Sentence Principle

默认：

```text
一句表达一个主要意思。
```

避免：

> “我已经尝试通知工作人员，但是目前还没有收到对方确认，所以您先别担心，我再看看情况，如果一会儿还没有回复的话我们再……”

这类超长句。

---

# 80. 重点信息前置

安全场景：

```text
先讲当前关键状态
```

再补限定。

不要先说长篇安慰再告诉结果。

---

# 81. 避免复杂术语

内部：

```text
notification callback timeout
```

用户侧：

```text
当前还没有收到确认结果
```

---

# 82. 避免暴露技术系统结构

默认不说：

```text
API
HTTP
数据库
Tool
Agent
Workflow
```

除非确有用户需求。

---

# 83. 避免模糊代词

重要业务对象尽量明确：

```text
工作人员

这段评书

今天的天气
```

而不是：

```text
他们
那个
这个
```

除非 Context 非常明确。

---

# 84. 避免多重否定

禁止类似：

```text
“目前并不是不能确认它没有成功。”
```

改为：

```text
“目前还不能确认是否成功。”
```

---

# 85. Emotion Expression Frozen Rules

正式冻结：

```text
回应有依据的感受

不扩大情绪

不进行心理诊断

不替用户确认未经验证的外部解释
```

---

# 86. Validate Emotion ≠ Validate Interpretation

用户：

> “他们就是不想管我。”

允许：

```text
回应用户感受到被忽视
```

禁止：

```text
确认家人真的不关心用户
```

---

# 87. Inferred Emotion

如果：

```text
Emotion = INFERRED
```

不得使用：

```text
“一定”
“就是”
“肯定”
```

描述用户情绪。

---

# 88. Emotion UNKNOWN

必须允许纯事实回应。

不能为了陪伴感硬加：

```text
“您一定很难过。”
```

---

# 89. Question Rules Frozen Core

普通回复：

```text
max_questions = 1
```

---

# 90. 一问一目标

一个问题只服务一个：

```text
clarification_target
或
exploration_target
```

---

# 91. Clarification Question

只问：

```text
阻塞下一步的最小必要信息。
```

---

# 92. Exploration Question

必须：

```text
和当前话题直接相关

低压力

可选择不回答
```

---

# 93. Required Question

Workflow 所需字段可以：

```text
DIRECT
```

但：

```text
一次一题
```

原则不变。

---

# 94. 用户不愿交流

如果：

```text
willingness_to_talk = NO
```

普通 Exploration：

```text
禁止。
```

---

# 95. 用户烦躁

如果：

```text
frustration_with_agent = true
```

降低：

```text
问题数量
回复长度
解释长度
```

---

# 96. Closing Rule

如果 M4：

```text
END
```

最终回复不得：

```text
再新增开放式问题
```

否则逻辑冲突。

---

# 97. Silence Rule

进入：

```text
SILENT_COMPANION
```

时：

第一次可以：

```text
SHORT_ACK
```

之后没有新事件：

```text
SILENCE
```

不能定时反复说：

> “我还在呢。”

除非主动策略另有计划。

---

# 98. Response Length Frozen Defaults

建议：

```text
VERY_SHORT
≈ 1句

SHORT
≈ 1～2句

MEDIUM
≈ 2～4句

LONG
仅显式需求使用
```

具体字符阈值可配置。

---

# 99. 默认

普通语音交互：

```text
SHORT
```

---

# 100. Safety

通常：

```text
VERY_SHORT / SHORT
```

优先清楚。

---

# 101. TTS Core Contract

M7 最终文本必须：

```text
可直接被TTS稳定朗读。
```

---

# 102. TTSFormatter Frozen Responsibilities

仅允许：

```text
数字朗读转换

日期时间朗读转换

单位朗读转换

缩写展开

必要停顿

符号清理

发音提示
```

---

# 103. TTSFormatter 禁止职责

禁止：

```text
改事实

添加解释

删Required Claim

改变Qualifier

重新组织业务意义
```

---

# 104. 数字表达

例如：

```text
12°C
```

转为适合 TTS 的：

```text
十二摄氏度
```

---

# 105. 时间

例如：

```text
15:30
```

按语言规范转：

```text
下午三点半
```

---

# 106. 日期

根据实际 Context 转换成自然朗读格式。

但：

```text
不得自行改变日期事实。
```

---

# 107. URL / ID / 技术编号

默认不直接朗读。

例如：

```text
help_event_id
```

属于内部信息。

除非用户确实需要。

---

# 108. Pause Policy

支持少量结构化停顿：

```text
SHORT_PAUSE

MEDIUM_PAUSE
```

用于：

```text
结果
+
限定语
```

之间提高理解度。

---

# 109. TTS 句子长度

应该有：

```text
max_sentence_length
```

具体数值属于配置。

超过则：

```text
重新断句
```

不能删业务信息。

---

# 110. 朗读前最终校验

TTS Formatter 后仍应做轻量：

```text
Semantic Preservation Check
```

确保：

```text
格式化前后Claim语义一致。
```

---

# 111. Elder-friendly Style 不得覆盖 Truth

例如为了安抚：

禁止把：

```text
“目前无法确认通知是否送达”
```

柔化成：

```text
“应该没问题，您放心。”
```

---

# 112. Elder-friendly Style 不得覆盖 Planner

例如 Planner 要：

```text
LISTEN
```

不能为了活跃气氛：

```text
推荐游戏。
```

---

# 113. 个性化 Style 的优先级

正式冻结：

```text
Truth Boundary
>
Safety
>
Planner Goal
>
Elder-friendly Rules
>
Personal Style Preference
```

---

# 第四部分  
# 三项冻结设计的整体关系

# 114. 正式关系

```text
ValidatedResult
        ↓
Claim-preserving Rules
        ↓
ResponsePlan
        ↓
Template / LLM / Hybrid
        ↓
ResponseDraft
        ↓
ResponseValidator
        ↓
TTSFormatter
        ↓
RuntimeResponse
```

---

# 115. 生成链不能逆向修改事实

禁止：

```text
Generator觉得某句话更自然
→ 修改Claim
```

---

# 116. ResponsePlan 与 RuntimeResponse 区别

```text
ResponsePlan
=
准备怎么表达

RuntimeResponse
=
最终实际表达了什么
```

M8 应使用：

```text
RuntimeResponse
```

更新真实 Conversation History。

不能只记录 ResponsePlan。

---

# 117. M6→M7 边界冻结

M7 正常情况下只消费：

```text
Verified Facts
Claim Policy
Business Status
```

不得自行提升 ExecutionResult 为 Truth。

---

# 118. M7→M8 边界冻结

M8 读取：

```text
实际输出文本

实际问题

实际使用Claim

实际显式引用Memory
```

更新状态。

---

# 119. Frozen Core 总结

从 V1.0 开始，以下正式冻结：

```text
ResponsePlan主结构

RuntimeResponse主结构

ResponseType九类

CommunicativeGoal核心枚举

ContentBlock结构

ClaimPlan

Truth Monotonicity

Forbidden Claim强校验

Qualifier Preservation

Unauthorized Promise Check

Response Goal Drift Check

Memory explicit-reference控制

Template / LLM / Hybrid / Silent四路径

ResponseValidator必须存在

单轮默认最多一个问题

适老短句原则

SILENCE正式输出

TTSFormatter独立存在

TTS不得改变语义
```

---

# 120. 允许扩展内容

未来允许增加：

```text
表达模板

Tone Profile值

ContentBlock

TTS pronunciation rules

ResponseType

语言风格偏好

新的Response Eval Case
```

但必须：

```text
不破坏Claim Boundary

不破坏Planner Boundary

通过ResponseValidator
```

---

# 121. 不允许破坏的边界

以后禁止出现：

```text
M7重新判断Tool成功

M7自由读取ToolResult猜结果

M7把UNKNOWN说成成功

M7自己承诺未来动作

M7自己新增业务建议

M7自行决定写Memory

为了温暖而制造假事实

为了自然而删除关键Qualifier

为了活跃对话而强行提问
```

---

# 第五部分  
# 冻结 Gate

## Gate M7-F01

`ResponsePlan` 主结构稳定。

---

## Gate M7-F02

`RuntimeResponse` 主结构稳定。

---

## Gate M7-F03

SILENCE 是合法 RuntimeResponse。

---

## Gate M7-F04

所有业务事实声明来自 M6 ClaimPolicy。

---

## Gate M7-F05

Forbidden Claim 无法通过任何生成路径输出。

---

## Gate M7-F06

Required Qualifier 不会在生成过程中丢失。

---

## Gate M7-F07

Response Certainty 不高于 M6 Certainty。

---

## Gate M7-F08

M7 不重新解析 ToolResult。

---

## Gate M7-F09

M7 不新增 Planner 未授权业务动作。

---

## Gate M7-F10

Future Promise 具有专门校验。

---

## Gate M7-F11

Memory explicit-reference 必须经过 M4 授权。

---

## Gate M7-F12

Emotion UNKNOWN 时允许不进行情绪解释。

---

## Gate M7-F13

推断情绪不会升级成确定事实。

---

## Gate M7-F14

普通单轮问题数默认 <= 1。

---

## Gate M7-F15

END Strategy 不产生新的开放式问题。

---

## Gate M7-F16

QUIET_PRESENCE 可以真正进入 SILENCE。

---

## Gate M7-F17

Safety 场景存在 Template / Hybrid 受控路径。

---

## Gate M7-F18

所有自由生成 Draft 都经过 ResponseValidator。

---

## Gate M7-F19

Validator Failure 有有限重生成和模板降级。

---

## Gate M7-F20

TTSFormatter 不改变 Claim 语义。

---

## Gate M7-F21

最终 RuntimeResponse 可以追踪到所使用的 Claim。

---

# 第六部分  
# 冻结后的主链

至此系统核心数据链正式稳定为：

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
```

五个对象分别表示：

```text
UnderstandingState
=
用户是什么意思

ActionPlan
=
系统准备做什么

ExecutionResult
=
系统实际执行了什么

ValidatedResult
=
系统真正知道发生了什么

RuntimeResponse
=
系统最终实际对用户表达了什么
```

---

# 122. M7 冻结后的最终原则

可以正式固定为：

```text
一、表达不能重新定义事实。

二、自然不能覆盖真实性。

三、温暖不能制造确定性。

四、问题不能超过用户当前愿意承担的交互负荷。

五、沉默是合法的陪伴行为。

六、最终说出去的话必须可以追溯到它的事实和策略来源。
```

至此 M7 Core Design 正式冻结。