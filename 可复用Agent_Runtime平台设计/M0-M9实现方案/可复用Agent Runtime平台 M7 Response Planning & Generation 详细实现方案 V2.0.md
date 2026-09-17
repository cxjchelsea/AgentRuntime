# 可复用 Agent Runtime 平台  
# M7 Response Planning & Generation 详细实现方案 V2.0

> **Phase 0 Fix**  
> `ResponsePlan` 必须使用 `claim_plan`，禁止 `facts_to_include` / `facts_to_avoid`。  
> `ResponsePlan` 是 M7 内部对象；主链对外输出是 `RuntimeResponse`。  
> 文中 `ActionPlan` 指上游 `ApprovedActionPlan`。

> **平台化转换说明**  
> 本文已从单一业务 Agent 设计转换为 **可复用 Agent Runtime 平台**设计。除明确标记为 `Core` 的对象、接口、不变量和生命周期外，任何具体业务 Intent、Entity、Workflow、Skill、Tool、知识域、状态字段、规则、提示词或示例均视为 **Domain Package 示例**，不得硬编码进 Runtime Core。新项目应通过 Registry / Adapter / Plugin / Config 注入领域差异。
> 
> 平台固定边界：`Runtime Core` 尽量稳定；`Domain Extension` 插件化；`Business Package` 配置化；`Application` 负责产品装配。

> 本版本为 M7 V1.0 的结构化重整版。  
> 保留原方案中 Response Requirement、Communication Goal、Claim Compiler、Truth Monotonicity、UNKNOWN / WAITING / PARTIAL_SUCCESS 表达、Content Structure、Tone / Style、Question Planner、Emotion Expression、Memory Expression、事实型查询表达、Error / Failure、Safety Response、Template + LLM Hybrid Generation、Response Validator、Promise Control、TTS Formatter、防重复机制、Response Policy、Eval、PoC、Gate、交付物等全部内容，并统一纳入 M0～M9 的 22 项实现方案模板。
>
> 本版本重点补强：运行时表达主流程、数据生命周期、跨 M 接口、表达约束的优先级、版本治理以及 Response Plan 与 RuntimeResponse 的正式边界。

---

# 01. 阶段定位

M7 是整个 Runtime 的最终表达层。

前面阶段已经完成：

```text
M3
理解用户
↓
UnderstandingState

M4
决定做什么
↓
ActionPlan

M5
真实执行
↓
ExecutionResult

M6
验证真实结果
↓
ValidatedResult
```

M7 解决：

```text
已经知道：

用户现在是什么状态，
系统决定采取什么交互策略，
真实业务结果是什么，
哪些事实可以说，
哪些事实不能说，

那么：

具体应该怎样对用户说？
```

因此 M7 的核心定位：

```text
Meaning
+
Decision
+
Truth
        ↓
Communication
```

M7 是：

> 将已经完成的理解、决策和事实验证，转化为自然、简短、适老、可朗读且不突破事实边界的最终用户表达。

---

# 02. 阶段目标与八种智能映射

## 2.1 M7 总体目标

M7 最终需要完成：

```text
Response Requirement 判断

+

Communication Goal解析

+

Claim Compilation

+

Content Structure Planning

+

Tone / Style Planning

+

Question Planning

+

Memory Expression Planning

+

Generation Route选择

+

Template / LLM / Hybrid生成

+

Response Validation

+

TTS Formatting

+

RuntimeResponse输出
```

---

## 2.2 与八种智能的关系

M7 不新增“第九种表达智能”。

它是前面八种智能的最终用户可感知出口。

| 智能能力 | M7作用 |
|---|---|
| 语义理解智能 | 使用 M3 结果，不重新理解 |
| 上下文智能 | 使用少量表达相关 Context |
| 关系连续性智能 | 控制 Memory 如何自然表达 |
| 情绪理解智能 | 调整语气，但不重新判断情绪 |
| 目标与隐含需求推断 | 使用已有 Need / Goal 调节表达 |
| 对话策略智能 | 把 M4 Strategy 转化为话语结构 |
| 主动性智能 | 执行已经批准的主动表达 |
| 自我约束智能 | 严格遵守 M6 Truth Boundary 和 M2 Safety Boundary |

因此：

```text
M7
不是重新变聪明，

而是把前面已经形成的智能
准确地表现出来。
```

---

# 03. 职责边界

## 3.1 M7 负责

M7 负责：

```text
决定是否需要回复

确定当前沟通目标

组织回复结构

选择语气

选择长度

决定如何问问题

决定如何表达 UNKNOWN

决定如何表达 WAITING

决定如何表达 PARTIAL_SUCCESS

决定 Memory 是否显式提及

根据 ClaimPolicy 准备可表达内容

把 Verified Result 转成自然语言

适配老年用户语言特征

生成 TTS 可直接使用的文本

验证最终回复没有越权
```

---

## 3.2 M7 不负责

M7 不负责：

```text
重新判断 Intent

重新判断 Emotion

重新推断 Need

重新决定 Strategy

重新规划 Action

重新调用 Tool

重新解释 Tool Result

重新判断 Business Success

重新判断 Safety

直接修改 Runtime State

直接写 Memory
```

必须固定：

```text
M7
不能重新做 M3～M6 的工作。
```

---

## 3.3 “说什么”和“怎么说”分离

M7 内部仍要拆成：

```text
Response Planning
+
Response Generation
```

不能：

```text
所有输入
→ LLM
→ 自由生成
```

正确流程：

```text
Validated Truth
+
Communication Goal
+
Response Constraints
        ↓
Response Plan
        ↓
Response Generation
        ↓
Response Validation
```

---

# 04. 前置依赖与外部依赖

## 4.1 M0 依赖

M7 依赖 M0 提供：

```text
ResponsePlan 基础 Schema

RuntimeResponse 基础 Schema

Response Engine Interface

Trace

Error / Fallback

Schema Version机制
```

---

## 4.2 M1 依赖

M7 只读取表达相关 Context：

```text
preferred_addressing

language_preference

current_topic

pending_question

conversation_stage

recent_agent_utterances

interaction_context

tts_constraints
```

不应把整个 RuntimeContext 再次交给生成模型自由理解。

---

## 4.3 M2 依赖

M7 必须继承：

```text
Safety Response Policy

Response Hard Rules

Medical Boundary

Privacy Boundary

Claim Strictness

Quiet / Silence Constraints
```

---

## 4.4 M3 依赖

M7 可以读取：

```text
emotion

emotion confidence

explicit / inferred status

implicit need

willingness_to_talk

need_for_silence

frustration_with_agent

conversation_fatigue

topic
```

但只用于：

```text
Tone
Style
Question intensity
```

不得重新推断。

---

## 4.5 M4 依赖

M7 必须读取：

```text
ActionPlan.response_strategy

Strategy

Actions

Question Intent

Memory Usage Mode

Stop Condition

Communication Goal
```

M4 已经决定：

```text
这一轮想做什么
```

M7 不能改。

---

## 4.6 M6 依赖

M7 的所有业务事实必须来自：

```text
ValidatedResult

business_status

verified_facts

allowed_claims

forbidden_claims

conditional_claims

required_qualifiers

followup
```

这是 M7 的 Truth Boundary。

---

## 4.7 外部依赖

可能包括：

```text
LLM Provider

Template Store

TTS Formatter

Pronunciation Dictionary
```

但这些均属于表达实现，不得改变业务事实。

---

# 05. 输入

建议正式定义：

```text
ResponseGenerationInput
```

结构：

```text
ResponseGenerationInput

understanding_state

action_plan

validated_result

runtime_context

response_policy
```

---

## 5.1 为什么仍需要 UnderstandingState

同一个事实：

```text
playback_failed
```

面对：

```text
普通播放用户
```

和：

```text
刚刚情绪低落的用户
```

可以使用不同 Tone。

但：

```text
Fact
```

本身不能变化。

所以：

```text
Truth
来自 M6

Tone
可参考 M3
```

---

## 5.2 为什么需要 ActionPlan

M4 已经决定：

```text
ACKNOWLEDGE

EXPLORE

LISTEN

CLARIFY

REPORT_RESULT

END
```

M7 不能重新选择。

它只需要知道：

```text
当前回复的交互目的
```

---

# 06. 输出

M7 最终正式输出：

```text
RuntimeResponse
```

其中可以是：

```text
自然语言回复
```

也可以合法为：

```text
SILENCE
```

即：

```text
text = null
tts_payload = null
```

---

# 07. 核心数据结构

# 7.1 ResponseRequirement

```text
ResponseRequirement

required

response_type

reason
```

---

# 7.2 ResponseType

建议冻结：

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

# 7.3 CommunicativeGoal

建议：

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

# 7.4 ResponseContentFacts

```text
ResponseContentFacts

must_include[]

may_include[]

must_not_include[]

qualifiers[]

certainty
```

---

# 7.5 ToneProfile

```text
ToneProfile

warmth

formality

directness

emotional_intensity

pace

complexity
```

---

# 7.6 QuestionPlan

```text
QuestionPlan

required

question_type

target

directness

optional

max_questions
```

---

# 7.7 QuestionType

```text
CLARIFICATION

OPEN_EXPLORATION

CLOSED_CONFIRMATION

REQUIRED_TASK_FIELD

OPTIONAL_INVITATION
```

---

# 7.8 ResponsePlan

正式建议：

```text
ResponsePlan

schema_version

response_required

response_type

communicative_goals[]

content_plan

claim_plan

tone_profile

length

question_plan

memory_expression

safety_constraints

tts_constraints

generation_path

metadata
```

---

# 7.9 ContentPlan

```text
ContentPlan

ordered_content_blocks[]
```

Block 类型：

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

# 7.10 ClaimPlan

```text
ClaimPlan

must_include_claims[]

optional_claims[]

forbidden_claims[]

qualifiers[]
```

---

# 7.11 MemoryExpressionPlan

```text
MemoryExpressionPlan

mode

memory_ids[]

explicit_reference_allowed
```

mode：

```text
NONE

SILENT_CONTEXT

PERSONALIZE_ACTION

REFERENCE_EXPLICITLY
```

---

# 7.12 SafetyConstraints

例如：

```text
no_diagnosis

no_unverified_reassurance

no_new_medication_advice

no_external_state_fabrication

no_unauthorized_promise
```

---

# 7.13 TTSConstraints

```text
TTSConstraints

max_sentence_length

max_sentences

pause_markers

pronunciation_hints

avoid_symbols
```

---

# 7.14 GenerationPath

```text
TEMPLATE_PATH

LLM_PATH

HYBRID_PATH

SILENT_PATH
```

---

# 7.15 TemplateDefinition

```text
TemplateDefinition

template_id

applicable_goal

required_claims[]

required_qualifiers[]

tone

variants[]

version
```

---

# 7.16 ResponseDraft

```text
ResponseDraft

text

sentences[]

claims_used[]

question_used

template_id

generation_metadata
```

---

# 7.17 RuntimeResponse

```text
RuntimeResponse

schema_version

response_id

request_id

session_id

response_type

text

tts_payload

claims_used[]

question

generation_path

validation_status

metadata
```

---

# 08. 数据来源、存储与生命周期

## 8.1 ResponsePlan 生命周期

ResponsePlan 属于：

```text
Turn-Level
```

只针对当前这一轮。

---

## 8.2 ResponseDraft 生命周期

属于内部临时对象。

如果 Validator 不通过：

```text
可以丢弃
```

不应进入 Session Context。

---

## 8.3 RuntimeResponse 生命周期

RuntimeResponse 作为：

```text
当前一轮最终输出
```

之后由 M8 根据：

```text
实际说了什么
```

更新：

```text
Conversation Context

recent_agent_actions

pending_question
```

---

## 8.4 claims_used 生命周期

建议随：

```text
RuntimeResponse Trace
```

保存。

用于后续审计：

> 这句话到底用了哪个 M6 Claim？

---

## 8.5 Question Metadata 生命周期

如果 M7 真正输出了问题：

```text
question metadata
```

需要交给 M8 建立：

```text
pending_question
```

直到：

```text
用户回答

超时

Task变化

问题被取消
```

---

## 8.6 Memory Reference 生命周期

本轮：

```text
REFERENCE_EXPLICITLY
```

只表示：

```text
本轮允许显式提 Memory
```

不代表未来每轮继续提。

---

## 8.7 Silence 生命周期

进入：

```text
SILENT_COMPANION
```

后，第一次可能：

```text
SHORT_ACK
```

之后：

```text
SILENCE
```

直到：

```text
用户新输入

Reminder

Safety Event

其他允许事件
```

---

# 09. 内部组件

建议 M7 包含：

```text
ResponseOrchestrator

ResponseRequirementChecker

CommunicationGoalResolver

ClaimCompiler

ContentStructurePlanner

TonePlanner

QuestionPlanner

MemoryExpressionPlanner

GenerationRouter

TemplateGenerator

LLMResponseGenerator

HybridGenerator

ResponseValidator

ClaimValidator

QualifierValidator

GoalDriftValidator

PromiseValidator

MemoryExpressionValidator

SafetyLanguageValidator

LengthValidator

QuestionCountValidator

TTSFormatter

ResponseFallbackManager
```

---

# 10. 运行时实现主流程

M7 正式 Runtime Algorithm：

```text
UnderstandingState
+
ActionPlan
+
ValidatedResult
+
Relevant RuntimeContext
+
ResponsePolicy
        ↓
① Response Requirement Check
        ↓
② Communication Goal Resolution
        ↓
③ Claim Compilation
        ↓
④ Content Structure Planning
        ↓
⑤ Tone / Style Planning
        ↓
⑥ Question Planning
        ↓
⑦ Memory Expression Planning
        ↓
⑧ Generation Path Routing
        ↓
⑨ Template / LLM / Hybrid Generation
        ↓
⑩ Response Draft
        ↓
⑪ Constraint / Claim / Promise Validation
        ↓
      PASS ?
      ↙   ↘
    Yes    No
     ↓      ↓
⑫ TTS   Controlled Regeneration
Format      ↓
     ↓   still fail?
     ↓      ↓
Runtime   Safe Template Fallback
Response
```

---

## 10.1 核心伪代码

```python
async def generate_response(
    understanding_state,
    action_plan,
    validated_result,
    runtime_context,
    response_policy
):

    requirement = response_requirement_checker.check(
        action_plan,
        validated_result,
        runtime_context
    )

    if not requirement.required:
        return build_silent_response(requirement)

    goals = communication_goal_resolver.resolve(
        action_plan,
        validated_result
    )

    content_facts = claim_compiler.compile(
        validated_result.claim_policy,
        goals
    )

    content_plan = content_structure_planner.plan(
        goals,
        content_facts,
        understanding_state,
        action_plan
    )

    tone = tone_planner.plan(
        understanding_state,
        action_plan,
        response_policy
    )

    question_plan = question_planner.plan(
        action_plan,
        understanding_state,
        runtime_context,
        response_policy
    )

    memory_plan = memory_expression_planner.plan(
        action_plan,
        runtime_context
    )

    response_plan = build_response_plan(
        requirement=requirement,
        goals=goals,
        content_plan=content_plan,
        claims=content_facts,
        tone=tone,
        question_plan=question_plan,
        memory_plan=memory_plan,
        response_policy=response_policy
    )

    path = generation_router.route(
        response_plan
    )

    draft = await response_generator.generate(
        response_plan,
        path
    )

    validation = response_validator.validate(
        draft,
        response_plan,
        validated_result
    )

    if not validation.valid:
        draft = await response_fallback_manager.recover(
            draft,
            response_plan,
            validation
        )

    final_validation = response_validator.validate(
        draft,
        response_plan,
        validated_result
    )

    if not final_validation.valid:
        draft = safe_template_generator.generate(
            response_plan
        )

    tts_payload = tts_formatter.format(
        draft.text,
        response_plan.tts_constraints
    )

    return build_runtime_response(
        draft,
        tts_payload,
        response_plan
    )
```

---

# 11. 各步骤详细实现

# Step 1：Response Requirement Check

并不是每个 Action 都需要回复。

例如：

```text
WAIT

SILENT_COMPANION
```

可能：

```text
response_required = false
```

所以 M7 第一件事是判断：

```text
这一轮到底需不需要说话？
```

---

## 11.1 SILENCE 是正式输出

例如：

```text
response_type = SILENCE

text = null
```

不能为了保证模型有输出而每次说：

> “好的，我不说话了。”

第一次进入安静陪伴可以简短确认。

之后应允许真正静默。

---

# Step 2：Communication Goal Resolution

根据：

```text
ActionPlan.response_strategy
+
ActionPlan.actions
+
ValidatedResult.business_status
```

得到当前表达目标。

M7 不能自行把：

```text
LISTENING_FIRST
```

改成：

```text
OFFER_CONTENT
```

---

# Step 3：Claim Compiler

这是 M7 最关键的事实保护组件。

输入：

```text
M6 ClaimPolicy
```

包括：

```text
allowed_claims

forbidden_claims

conditional_claims

required_qualifiers
```

输出：

```text
ResponseContentFacts
```

---

## 11.3.1 must_include

关键事实。

例如安全场景：

```text
当前通知状态不能确认
```

如果用户必须知道，则进入：

```text
must_include
```

---

## 11.3.2 may_include

例如：

```text
内容标题

天气更新时间
```

可以根据长度决定是否表达。

---

## 11.3.3 must_not_include

直接继承：

```text
forbidden_claims
```

---

## 11.3.4 Truth Monotonicity Principle

必须正式固定：

```text
Response certainty
<=
ValidatedResult certainty
```

即：

> M7 可以保持或降低确定性，但绝对不能提升确定性。

例如：

```text
M6:
未确认
```

不能在 M7 变成：

```text
已经
确定
肯定
```

---

# Step 4：Content Structure Planning

先决定：

```text
回复要包含哪些块
以及顺序
```

而不是马上写句子。

---

## 11.4.1 推荐通用顺序

一般：

```text
1. 当前交互回应

2. 核心事实

3. 必要限定

4. 下一步 / 问题
```

具体按场景裁剪。

---

## 11.4.2 信息优先级

建议：

```text
Safety Critical Facts
>
Goal Result
>
Required Qualifier
>
Required Question
>
Emotional Acknowledgement
>
Optional Personalization
>
Optional Small Talk
```

---

## 11.4.3 普通任务成功

通常只需要：

```text
结果确认
```

不必额外：

```text
复述请求

长情绪回应

额外建议

开放问题
```

---

## 11.4.4 情绪 + 任务

例如：

```text
简短 Acknowledge

↓

业务结果
```

---

## 11.4.5 情绪倾诉

如果 M4：

```text
ACKNOWLEDGE_THEN_EXPLORE
```

结构：

```text
情绪回应

↓

一个轻度邀请
```

---

## 11.4.6 Quiet Presence

结构：

```text
第一次：
简短确认

之后：
SILENCE
```

---

## 11.4.7 Safety

结构优先：

```text
明确

简短

操作导向
```

而不是长篇安慰。

---

# Step 5：Tone / Style Planning

Tone 结构化：

```text
warmth

formality

directness

emotional_intensity

pace

complexity
```

---

## 11.5.1 warmth

建议：

```text
LOW

MEDIUM

HIGH
```

普通陪伴默认：

```text
MEDIUM
```

安全场景不追求高煽情。

---

## 11.5.2 directness

```text
DIRECT

BALANCED

GENTLE
```

例如：

```text
Safety
→ DIRECT

普通支持型交互
→ GENTLE
```

---

## 11.5.3 complexity

默认用户端：

```text
SIMPLE
```

---

## 11.5.4 适老语言原则

固定：

```text
短句

单句信息量低

少专业术语

少复杂并列

避免长前置条件

重点信息靠前

一次一个问题

避免抽象表达

避免连续多个选择
```

---

# Step 6：Question Planning

M4 已经决定是否：

```text
EXPLORE

CLARIFY

ASK_REQUIRED_FIELD
```

M7 只负责：

```text
怎么问
```

---

## 11.6.1 max_questions

普通当前轮：

```text
1
```

除非固定 Workflow 有特殊设计。

---

## 11.6.2 Clarification

只问：

```text
真正阻塞下一步的信息
```

例如：

> “帮我联系她。”

只需要确认：

```text
“她”是谁
```

而不是扩展询问：

```text
为什么联系
什么时候认识
为什么现在联系
```

---

## 11.6.3 Open Exploration

应该：

```text
低压力

可不回答

紧贴当前话题
```

---

## 11.6.4 Required Task Field

如果 Workflow 必须采集：

```text
location

time

status
```

则：

```text
一次一项
```

---

## 11.6.5 用户不想说话

如果：

```text
willingness_to_talk = LOW
```

且 M4 没有 Hard Required Question：

```text
QuestionPlan.required = false
```

---

# Step 7：Memory Expression Planning

M4 已经决定：

```text
memory_usage_mode
```

M7 必须严格执行。

---

## SILENT_CONTEXT

Memory 只参与内部个性化。

不能说：

> “我记得……”

---

## PERSONALIZE_ACTION

例如基于偏好选越剧。

M7 可以：

> “给您放一段越剧。”

不需要暴露 Memory。

---

## REFERENCE_EXPLICITLY

只有这种模式才可以表达：

```text
“您之前提过……”
```

前提：

```text
该 Memory 已经真实存在且允许表达
```

---

## 11.7.1 防止“监视感”

即使 Memory 真实，也避免：

```text
精确复述大量历史

频繁说出保存时间

反复强调“我记得”
```

除非用户主动要求。

---

# Step 8：Generation Path Routing

建议：

```text
SILENT_PATH

TEMPLATE_PATH

LLM_PATH

HYBRID_PATH
```

---

## 11.8.1 Template Path

适合：

```text
Safety

Reminder

Required Confirmation

Tool Failure

UNKNOWN

System Error

短控制确认
```

---

## 11.8.2 LLM Path

适合：

```text
领域交互

情绪回应

开放探索

Topic Continuation
```

---

## 11.8.3 Hybrid Path

适合：

```text
固定事实
+
自然陪伴表达
```

例如：

```text
ACKNOWLEDGE
+
REPORT_PLAYBACK_FAILURE
```

---

# Step 9：Response Generation

Generator 输入只允许：

```text
ResponsePlan

Allowed Facts

Required Qualifiers

Relevant User State

Relevant Context

Forbidden Claims

Style Rules
```

---

## 11.9.1 不给原始 ToolResult

正式建议：

```text
M7 LLM
不直接读取原始 ToolResult
```

避免模型重新解释技术结果。

---

## 11.9.2 Prompt 核心要求

固定：

```text
你负责表达，不负责重新判断事实。

只能表达 Allowed Facts。

不得表达 Forbidden Claims。

不得提高事实确定性。

不得新增业务 Action。

不得自行承诺未来操作。

不得重新决定 Tool 调用。

不得进行医学诊断。

不得把推测写成事实。

语言需要适合目标用户语音交互。
```

---

# Step 10：Response Draft

Generator 生成：

```text
ResponseDraft
```

但 Draft 不是最终输出。

---

# Step 11：Response Validation

必须检查：

```text
Forbidden Claim

Unsupported Claim

Qualifier Missing

Response Goal Drift

New Action Introduction

Unauthorized Promise

Question Count

Length

Safety Language

Memory Misuse

Medical Boundary

TTS Compatibility
```

---

## 11.11.1 Unsupported Claim

例如生成：

> “工作人员马上就到。”

但 M6 没有：

```text
STAFF_ON_THE_WAY
```

则：

```text
reject
```

---

## 11.11.2 Required Qualifier Missing

M6：

```text
NOT_CONFIRMED
```

Draft：

> “通知已经成功。”

必须拒绝。

---

## 11.11.3 Goal Drift

M4：

```text
REPORT_RESULT
```

M7 却新增：

```text
OFFER_CONTENT
```

属于：

```text
RESPONSE_GOAL_DRIFT
```

---

## 11.11.4 Promise Control

必须单独检查未来动作承诺。

例如：

```text
“我马上再联系他们。”

“我会一直帮您盯着。”

“稍后我再来提醒您。”
```

如果 Runtime 没有对应：

```text
ActionPlan
Task
Scheduler
Workflow
```

必须禁止。

---

## 11.11.5 Question Count

普通轮：

```text
max_questions = 1
```

超出：

```text
reject / rewrite
```

---

## 11.11.6 Length Check

按照：

```text
VERY_SHORT

SHORT

MEDIUM

LONG
```

进行句数 / 长度限制。

---

# Step 12：Validation Failure Recovery

建议：

```text
Draft
↓
ResponseValidator Fail
↓
Controlled Regeneration once
↓
Validator
↓
仍失败
↓
Safe Template Fallback
```

禁止：

```text
无限重试
```

---

# Step 13：TTS Formatting

通过：

```text
TTSFormatter
```

完成：

```text
数字展开

单位读法

日期时间读法

英文缩写处理

停顿标记

复杂符号清理
```

---

## 11.13.1 TTS Formatter 不改语义

它只能修改：

```text
朗读形式
```

不能：

```text
新增信息

删掉关键限定

改变事实
```

---

# Step 14：RuntimeResponse Build

最终生成：

```text
RuntimeResponse
```

并记录：

```text
claims_used

question metadata

generation_path

validation_status
```

---

# 12. 分支、路由与决策规则

# 12.1 UNKNOWN 表达

如果：

```text
business_status = UNKNOWN
```

必须：

```text
REPORT_UNKNOWN
```

不能：

```text
猜成功

猜失败

说“应该没问题”
```

---

# 12.2 WAITING 表达

WAITING 和 UNKNOWN 分开。

```text
WAITING
```

表示：

```text
流程明确还在继续
```

可以表达：

```text
当前还在等待结果
```

而不是：

```text
不知道发生了什么
```

---

# 12.3 PARTIAL_SUCCESS 表达

必须表达：

```text
成功了什么

未完成 / 未确认什么
```

不能：

```text
“都处理好了”
```

---

# 12.4 情绪表达不能扩大判断

M3：

```text
possible loneliness
confidence = medium
```

M7 不得：

> “您一定非常孤独。”

---

# 12.5 Emotion UNKNOWN

如果：

```text
emotion = UNKNOWN
```

M7 不得凭空添加：

```text
孤独
失落
焦虑
害怕
```

---

# 12.6 Validate Emotion != Validate Interpretation

用户：

> “他们都不在乎我。”

M7 可以接住：

```text
被忽视、难受的感受
```

但不能确认：

```text
家人确实不在乎用户
```

必须固定：

```text
回应感受

不替用户证明未经验证的事实
```

---

# 12.7 Empathy 多样性

避免频繁：

```text
“我理解您的感受。”

“我能感受到您的心情。”
```

允许：

```text
Surface Variation
```

但：

```text
Semantic Fixed
```

即：

```text
措辞可以变

语义不能漂移
```

---

# 12.8 普通任务成功

尽量：

```text
短

明确
```

不自动加开放问题。

---

# 12.9 Tool Failure

如果：

```text
business_status = FAILED
```

必须清楚说明：

```text
未完成
```

不能说：

> “稍等一下，马上就好。”

除非 Runtime 确实已经建立后续任务。

---

# 12.10 System Error

内部：

```text
HTTP 500
```

M7 应转换成：

```text
用户能理解的失败语义
```

不需要暴露技术错误码。

---

# 12.11 Safety Response

Safety 建议固定：

```text
SHORT

DIRECT

CALM

NO_DECORATION

NO_UNVERIFIED_REASSURANCE
```

禁止：

```text
长篇安慰

复杂比喻

玩笑

过度情绪渲染

虚假保证

未经证实的“没事”
```

---

# 12.12 Safety Template 优先

以下内容优先使用审核 Template：

```text
求助确认

高风险提示

关键通知结果

通知 UNKNOWN

安全超时 / 失败
```

避免自由 LLM 漂移。

---

# 12.13 事实型查询

Weather / News 等：

```text
只能整理 M6 Verified Facts
```

不能使用模型训练知识补实时事实。

---

# 12.14 Weather

M6 只有：

```text
temperature = 12
```

M7 不能补：

```text
风很大

体感9度
```

除非也有证据。

---

# 12.15 News

只能整理：

```text
M6 verified news items
```

不能自行补新闻背景为当前事实。

---

# 12.16 Memory Truth

如果：

```text
Memory Service unavailable
```

禁止：

> “我记得您之前……”

---

# 12.17 END

如果 M4：

```text
END
```

M7 必须：

```text
简短结束

不追加新开放问题
```

否则会破坏结束动作。

---

# 12.18 LISTEN

M7 应：

```text
简短邀请

然后让用户继续
```

不能变成长建议。

---

# 12.19 CLARIFY

只问：

```text
clarification_target
```

不扩展其他问题。

---

# 12.20 SILENT_COMPANION

第一次：

```text
SHORT_ACK
```

之后：

```text
SILENCE
```

---

# 12.21 Response Policy 优先级

建议：

```text
M6 ClaimPolicy
>
M2 Safety Response Policy
>
Hard Response Policy
>
M4 Response Strategy
>
User Style Preference
>
Language Diversity Preference
```

---

# 12.22 个性化不能覆盖安全

即使用户偏好：

```text
幽默
轻松
```

Safety Response 也不能开玩笑。

---

# 12.23 防重复机制

读取：

```text
recent_agent_utterances
```

避免：

```text
重复开场

重复安慰

重复问题
```

但不能为了不重复：

```text
改变 Strategy
```

---

# 12.24 老年用户特殊表达规则

固定：

```text
避免代词过多

避免多重否定

时间表达清楚

数字单位适合朗读

问题一次一个

少使用抽象术语
```

例如不建议：

> “目前并不是不能确认没有发送。”

应该：

> 使用单层、直接表达。

---

# 13. 与前后 M 的接口

# 13.1 M0 → M7

提供：

```text
ResponsePlan Schema

RuntimeResponse Schema

Response Engine Interface

Trace
```

---

# 13.2 M1 → M7

提供少量表达 Context：

```text
preferred_addressing

language preference

recent agent utterances

conversation stage

tts context
```

---

# 13.3 M2 → M7

提供：

```text
Safety Response Constraints

Medical Boundary

Hard Response Policy
```

---

# 13.4 M3 → M7

提供：

```text
Emotion

Need

Interaction State

Topic
```

只用于表达调整。

---

# 13.5 M4 → M7

提供：

```text
Strategy

Action

Response Strategy

Memory Usage Mode

Question Intent
```

M7 不重新规划。

---

# 13.6 M6 → M7

最关键接口：

```text
ValidatedResult

Allowed Claims

Forbidden Claims

Required Qualifiers

Business Status

Followup
```

---

# 13.7 M7 → M8

M7 输出：

```text
RuntimeResponse

question metadata

claims_used

memory references used

response action metadata
```

M8 用于：

```text
建立 Pending Question

记录 Recent Agent Action

更新 Conversation Context

更新 Interaction Context
```

---

# 14. 与业务模块的映射

# 14.1 领域交互

重点：

```text
ACKNOWLEDGE

LISTEN

EXPLORE

REFLECT

END

SILENCE
```

适合：

```text
LLM_PATH / HYBRID_PATH
```

---

# 14.2 内容播放

重点：

```text
SHORT_ACK

RESULT_REPORT

FAILURE

UNKNOWN
```

多数：

```text
Template / Hybrid
```

---

# 14.3 情绪安抚

重点：

```text
Emotion Expression

Tone

Question Pressure

Silence

Memory Expression
```

---

# 14.4 安全与领域事件

优先：

```text
SAFETY_MESSAGE

Template

Strict Claim Validation

Direct Style
```

---

# 14.5 领域提醒

重点：

```text
TASK_PROMPT

CONFIRMATION

SHORT RESULT
```

通常适合受控 Template。

---

# 14.6 领域任务交互

重点：

```text
Question

Answer Feedback

Task Prompt

Closing
```

---

# 14.7 长期记忆

重点：

```text
MemoryExpressionPlan
```

严格服从 M4 Usage Mode。

---

# 14.8 新闻天气

重点：

```text
Verified Facts

Source-aware expression

Time-aware expression
```

不新增未验证事实。

---

# 15. 异常、超时与降级

# 15.1 LLM Generation Timeout

返回：

```text
GENERATION_TIMEOUT
```

进入：

```text
Safe Template Fallback
```

---

# 15.2 LLM Generation Failed

```text
GENERATION_FAILED
```

使用 Template。

---

# 15.3 Forbidden Claim Generated

```text
FORBIDDEN_CLAIM_GENERATED
```

Draft 丢弃。

---

# 15.4 Unsupported Claim

```text
UNSUPPORTED_CLAIM
```

不得进入最终回复。

---

# 15.5 Required Qualifier Missing

```text
REQUIRED_QUALIFIER_MISSING
```

进入 Controlled Regeneration / Template。

---

# 15.6 Goal Drift

```text
RESPONSE_GOAL_DRIFT
```

拒绝当前 Draft。

---

# 15.7 Unauthorized Promise

```text
UNAUTHORIZED_PROMISE
```

例如：

> “我等会儿再来提醒您。”

但系统无 Scheduler Task。

必须拒绝。

---

# 15.8 Memory Misuse

```text
MEMORY_MISUSE
```

例如：

```text
SILENT_CONTEXT
```

却生成：

> “我记得您之前……”

---

# 15.9 Question Limit

```text
QUESTION_LIMIT_EXCEEDED
```

---

# 15.10 Response Too Long

```text
RESPONSE_TOO_LONG
```

---

# 15.11 Medical Boundary

```text
MEDICAL_BOUNDARY_VIOLATION
```

---

# 15.12 TTS Error

```text
TTS_FORMAT_ERROR
```

必要时退化为：

```text
原始验证后文本
```

前提是不改变事实。

---

# 15.13 Response Validation Failed

如果最终仍失败：

```text
RESPONSE_VALIDATION_FAILED
```

进入最小安全 Template。

---

# 15.14 Error Taxonomy

建议至少：

```text
INVALID_RESPONSE_PLAN

FORBIDDEN_CLAIM_GENERATED

UNSUPPORTED_CLAIM

REQUIRED_QUALIFIER_MISSING

RESPONSE_GOAL_DRIFT

UNAUTHORIZED_PROMISE

MEMORY_MISUSE

QUESTION_LIMIT_EXCEEDED

RESPONSE_TOO_LONG

MEDICAL_BOUNDARY_VIOLATION

TTS_FORMAT_ERROR

GENERATION_TIMEOUT

GENERATION_FAILED

RESPONSE_VALIDATION_FAILED
```

---

# 16. 配置项与可变项

建议：

```text
response_type_rules

communication_goal_rules

default_tone

elder_friendly_rules

max_sentences

max_questions

length_rules

generation_router_rules

template_registry

safety_template_policy

memory_expression_policy

claim_strictness

response_validator_rules

tts_rules

prompt_version

schema_version
```

---

## 16.1 ResponsePolicy

建议：

```text
ResponsePolicy

elder_friendly

max_sentences

max_questions

default_length

medical_boundary

claim_strictness

memory_expression_policy

safety_template_policy
```

---

## 16.2 Template 配置

Template 应：

```text
变量化
版本化
可审查
```

不能把业务事实硬编码进模板。

---

# 17. 非功能约束

# 17.1 Truth > Naturalness

M7 的首要原则：

```text
真实性
>
自然度
```

不能为了表达顺滑提升事实确定性。

---

# 17.2 Response Latency

M7 需要纳入整机响应时延预算。

因此：

```text
短任务
优先 Template

复杂陪伴
才使用 LLM
```

---

# 17.3 适老可读性

重点控制：

```text
句长

句数

术语

代词

多重否定

数字

时间

问题数量
```

---

# 17.4 稳定性

LLM Draft 永远不能直接作为：

```text
RuntimeResponse
```

必须经过：

```text
ResponseValidator
```

---

# 17.5 No Promise Without Runtime State

任何未来承诺都必须有真实：

```text
Task

Workflow

Scheduler

ActionPlan
```

支撑。

---

# 17.6 Silence as First-class Output

系统必须允许：

```text
真正不说话
```

这对领域场景非常重要。

---

# 17.7 Generation Retry Limit

禁止无限重生成。

推荐：

```text
1次 controlled regeneration
+
Template fallback
```

---

# 17.8 隐私

LLM 只接收：

```text
当前表达所需 Memory

必要 Context
```

不应全量暴露历史。

---

# 18. Trace / Logging / Observability

至少记录：

```text
response_requirement

response_plan

generation_path

template_id

model_version

prompt_version

claims_available

claims_used

forbidden_claims

required_qualifiers

memory_expression_mode

question_plan

draft

validation_result

fallback_used

tts_result

final_response
```

---

## 18.1 claims_used

特别重要。

如果用户反馈：

> “机器人为什么说工作人员收到通知了？”

可以追踪：

```text
M6 是否允许该 Claim？

M7 是否越权？

Validator 是否失效？
```

---

## 18.2 Promise Trace

建议单独记录：

```text
future_promises_detected
```

用于发现未经授权承诺。

---

## 18.3 敏感日志

仍遵循：

```text
最小必要记录
```

不应长期保存所有完整用户对话仅为了调试。

---

# 19. 版本、兼容与变更影响

# 19.1 ResponsePlan Schema Version

必须：

```text
ResponsePlan.schema_version
```

---

# 19.2 RuntimeResponse Schema Version

必须：

```text
RuntimeResponse.schema_version
```

---

# 19.3 Prompt Version

LLM Response Prompt：

```text
prompt_version
```

写入 Trace。

---

# 19.4 Template Version

每个 Template：

```text
template_id

version
```

---

# 19.5 ResponsePolicy Version

适老规则、安全模板策略、问题限制等建议版本化。

---

# 19.6 可配置变化

一般无需改 M7 Core：

```text
调整句长

调整默认 Tone

新增 Template

新增普通表达 Variation

调整 TTS读法

调整 Question Limit
```

---

# 19.7 新增 Communicative Goal

通常：

```text
扩展 Goal Registry

扩展 Template / Prompt
```

无需重写 Pipeline。

---

# 19.8 Breaking Change

以下可能影响 M8 / Client / TTS：

```text
删除 RuntimeResponse 核心字段

修改 Question Metadata 语义

修改 Claims Used 契约

修改 ResponseType

改变 SILENCE 语义
```

必须升级版本。

---

# 20. 测试 / Eval

# 20.1 ResponseEvalCase

建议：

```text
ResponseEvalCase

understanding_state

action_plan

validated_result

runtime_context

expected_response_properties

required_semantics

forbidden_semantics

style_requirements
```

---

# 20.2 Eval 分类

至少：

```text
NORMAL_TASK_SUCCESS

NORMAL_TASK_FAILURE

UNKNOWN_RESULT

WAITING_RESULT

PARTIAL_SUCCESS

EMOTIONAL_ACKNOWLEDGEMENT

LISTENING

QUIET_PRESENCE

CLARIFICATION

SAFETY_MESSAGE

MEMORY_REFERENCE

MEMORY_NON_REFERENCE

CONVERSATION_CLOSE

SYSTEM_ERROR
```

---

# 20.3 核心指标

```text
Claim Accuracy

Forbidden Claim Violation Rate

Unsupported Claim Rate

Qualifier Preservation Rate

Response Goal Adherence

Question Count Accuracy

Length Compliance Rate

Memory Reference Accuracy

Safety Language Compliance

Medical Boundary Violation Rate

Unauthorized Promise Rate

TTS Readability

Response Schema Validity
```

---

## 20.3.1 Forbidden Claim Violation Rate

目标：

```text
0
```

尤其：

```text
Safety

Notification

Medical
```

场景。

---

## 20.3.2 Qualifier Preservation Rate

M6：

```text
UNKNOWN

NOT_CONFIRMED
```

M7 必须：

```text
100%保留不确定性语义
```

---

## 20.3.3 Response Goal Adherence

例如 M4：

```text
LISTEN
```

M7 不应生成：

```text
建议清单
```

---

## 20.3.4 Question Count Accuracy

```text
该问一个
→ 不能问三个
```

---

## 20.3.5 Memory Reference Accuracy

只有：

```text
REFERENCE_EXPLICITLY
```

才允许明显引用 Memory。

---

## 20.3.6 Unauthorized Promise Rate

目标：

```text
接近0
```

因为未经授权的语言承诺可能造成真实业务误导。

---

## 20.3.7 TTS Readability

评价：

```text
句长

停顿

数字

单位

缩写

复杂符号
```

---

# 20.4 人工评价

少量真实对话可人工评价：

```text
Naturalness

Warmth

Clarity

Respect

Intrusiveness

Elder Friendliness
```

但：

```text
自然度不能覆盖 Truth / Safety 指标
```

---

# 20.5 PoC 1：播放成功

M4：

```text
DIRECT_FULFILLMENT
```

M6：

```text
PLAYBACK_STARTED
```

M7：

```text
SHORT_ACK / RESULT_REPORT
```

不增加不必要问题。

---

# 20.6 PoC 2：播放失败

M6：

```text
FAILED
```

M7：

```text
明确说明没有成功播放
```

如果 M4 没有：

```text
OFFER_ALTERNATIVE
```

M7 不能主动问：

> “要不要换一首？”

---

# 20.7 PoC 3：通知 UNKNOWN

M6：

```text
request_created = CONFIRMED

delivery = UNKNOWN
```

M7 必须同时表达：

```text
确认部分
+
未知部分
```

---

# 20.8 PoC 4：隐含孤独

M3：

```text
possible_loneliness
```

M4：

```text
ACKNOWLEDGE_THEN_EXPLORE
```

M7：

```text
轻度回应
+
一个可选问题
```

不能：

> “您一定非常孤独。”

---

# 20.9 PoC 5：Emotion UNKNOWN

用户：

> “我女儿今天加班。”

M3：

```text
emotion = UNKNOWN
```

M7 不能：

> “您是不是很失落？”

除非 M4 明确有其他依据。

---

# 20.10 PoC 6：用户不想说话

M4：

```text
QUIET_PRESENCE
```

M7：

```text
第一次短确认

之后 SILENCE
```

---

# 20.11 PoC 7：Clarification

M4：

```text
CLARIFY_REFERENCE
```

M7：

```text
只问“她是谁”
```

---

# 20.12 PoC 8：Safety

M6：

```text
notification_delivery = UNKNOWN
```

M7：

```text
短

直接

保留 UNKNOWN
```

禁止：

> “放心，工作人员已经来了。”

---

# 20.13 PoC 9：Memory Silent Context

M4：

```text
PERSONALIZE_ACTION
```

M7：

```text
直接提供个性化结果
```

不说：

> “我记得您三个月前……”

---

# 20.14 PoC 10：Conversation Close

M4：

```text
END
```

M7：

```text
简短结束
```

不得再新增开放问题。

---

# 21. Gate

## Gate M7-01

正式输入至少包含：

```text
UnderstandingState

ActionPlan

ValidatedResult
```

---

## Gate M7-02

正式输出统一：

```text
RuntimeResponse
```

---

## Gate M7-03

M7 内部正式存在：

```text
ResponsePlan
```

---

## Gate M7-04

M7 不重新判断 Business Success。

---

## Gate M7-05

M7 不重新解释原始 ToolResult。

---

## Gate M7-06

业务事实声明必须来自：

```text
M6 Allowed Claims
```

---

## Gate M7-07

Forbidden Claims 无法被 Generator 绕过。

---

## Gate M7-08

Required Qualifiers 必须保留。

---

## Gate M7-09

UNKNOWN 不生成确定性成功 / 失败表达。

---

## Gate M7-10

WAITING 与 UNKNOWN 语义明确分离。

---

## Gate M7-11

M7 不新增 ActionPlan 中不存在的业务承诺。

---

## Gate M7-12

普通当前轮默认最多一个问题。

---

## Gate M7-13

M3 Emotion UNKNOWN 时，M7 不自行生成明确情绪判断。

---

## Gate M7-14

推断情绪不能在表达层升级成确定事实。

---

## Gate M7-15

Memory explicit reference 必须得到 M4 授权。

---

## Gate M7-16

SILENCE 是合法输出。

---

## Gate M7-17

Safety Response 优先 Template / Hybrid。

---

## Gate M7-18

所有 LLM Draft 必须经过 ResponseValidator。

---

## Gate M7-19

Validator 失败存在安全降级。

---

## Gate M7-20

最终输出符合基础适老表达约束。

---

## Gate M7-21

最终回复可以追踪：

```text
使用哪些 Claim

为什么问这个问题

采用什么 Communication Goal

走哪种 Generation Path
```

---

## Gate M7-22

Response Certainty 不得高于 M6 Certainty。

---

## Gate M7-23

未经 Runtime 支撑的未来承诺可以被 PromiseValidator 拦截。

---

## Gate M7-24

TTSFormatter 不改变语义和确定性。

---

# 22. 交付物

M7 最终至少形成：

```text
M7-01 Response Generation总体架构

M7-02 Runtime Response主流程

M7-03 ResponseGenerationInput Schema

M7-04 ResponsePlan Schema

M7-05 RuntimeResponse Schema

M7-06 Response Type规范

M7-07 Communication Goal规范

M7-08 Claim Compiler规范

M7-09 Content Structure规范

M7-10 Tone / Style规范

M7-11 Elder-friendly Language规范

M7-12 Question Planning规范

M7-13 Emotion Expression规范

M7-14 Memory Expression规范

M7-15 UNKNOWN / WAITING表达规范

M7-16 Safety Response规范

M7-17 Template规范

M7-18 LLM Response Prompt规范

M7-19 Generation Router

M7-20 Response Validator

M7-21 Promise Control规范

M7-22 TTS Formatter规范

M7-23 Response Policy规范

M7-24 Response Error Taxonomy

M7-25 Response Trace规范

M7-26 M7 Eval Dataset

M7-27 M7 Metrics

M7-28 M7自动化测试

M7-29 M7 Gate验证报告
```

---

# 附录 A：推荐代码结构

```text
response/

├── orchestrator.py
├── models.py
├── schemas.py
├── errors.py
│
├── requirement/
│   └── checker.py
│
├── planning/
│   ├── planner.py
│   ├── communication_goal.py
│   ├── content_structure.py
│   ├── style.py
│   ├── question.py
│   └── memory_expression.py
│
├── claims/
│   ├── compiler.py
│   └── validator.py
│
├── generation/
│   ├── router.py
│   ├── llm_generator.py
│   ├── template_generator.py
│   └── hybrid_generator.py
│
├── validation/
│   ├── validator.py
│   ├── claim_check.py
│   ├── qualifier_check.py
│   ├── goal_check.py
│   ├── promise_check.py
│   ├── memory_check.py
│   ├── question_check.py
│   └── safety_check.py
│
├── templates/
│   ├── safety/
│   ├── reminder/
│   ├── error/
│   ├── unknown/
│   └── control/
│
├── tts/
│   └── formatter.py
│
└── config/
```

---

# 附录 B：Template + LLM Hybrid 原则

推荐：

```text
受控事实
+
自然表达
```

而不是：

```text
所有事实和语言都交给 LLM
```

例如：

```text
Claim:
PLAYBACK_FAILED
```

是固定语义。

前置：

```text
ACKNOWLEDGE
```

可以自然生成。

---

# 附录 C：Safety Template 原则

关键安全表达优先来自：

```text
审核过的固定 Template
```

包括：

```text
求助确认

通知状态

失败

超时

UNKNOWN

高风险提示
```

---

# 附录 D：第一版实现范围

第一版建议优先实现：

```text
ResponseRequirement

CommunicationGoalResolver

ClaimCompiler

ContentStructurePlanner

Basic TonePlanner

QuestionPlanner

MemoryExpressionPlanner

TemplateGenerator

LLMGenerator

HybridGenerator

GenerationRouter

ResponseValidator

PromiseValidator

SafeTemplateFallback

TTSFormatter

RuntimeResponse
```

---

# 附录 E：第一版暂时不做

暂不优先：

```text
复杂人格化语言风格

长期语言风格学习

声音情绪控制

自动幽默

复杂修辞

多角色人格

强化学习Response优化
```

---

# 附录 F：第一版不能推迟

必须第一版具备：

```text
Forbidden Claim enforcement

Qualifier preservation

Truth Monotonicity

UNKNOWN表达

WAITING表达

Question limit

Length limit

Safety Template

Response Validation

Memory Reference Control

Unauthorized Promise Control

SILENCE

TTS Basic Formatting
```

---

# 附录 G：M0～M7 当前完整链路

```text
M0
Runtime Skeleton
        ↓
M1
Input & Context
        ↓
M2
Safety / State / Policy
        ↓
M3
Understanding
        ↓
M4
Planning & Orchestration
        ↓
M5
Execution Framework
        ↓
M6
Result Validation
        ↓
M7
Response Planning & Generation
```

一次完整用户请求现在可以：

```text
听到

↓

知道背景

↓

受规则约束

↓

理解

↓

决定

↓

真实执行

↓

验证事实

↓

正确表达
```

---

# 附录 H：M7 与 M8 的正式交接

M7 输出：

```text
RuntimeResponse

question metadata

claims_used

memory references used

response action metadata
```

M6 输出：

```text
ValidatedResult
```

M4 输出：

```text
ActionPlan
```

M8 将综合：

```text
这一轮发生了什么

真实结果是什么

系统实际说了什么
```

形成：

```text
StateUpdate

MemoryUpdate

ContextUpdate
```

因此：

```text
M7
=
这一轮怎么说

M8
=
这一轮结束以后，
系统应该留下什么
```

---

# 附录 I：M7 最终设计原则

最终固定以下原则：

```text
一、
M7只表达，
不重新决策。

二、
M7只能说M6允许说的事实。

三、
不确定性不能在语言生成中消失。

四、
自然和温暖不能以牺牲真实性为代价。

五、
语言承诺必须有真实Runtime动作支撑。

六、
SILENCE也是合法而重要的陪伴行为。

七、
好的陪伴回复不是说得更多，
而是在合适的时候说合适的话。
```

最终：

```text
M3
让系统懂人。

M4
让系统会陪。

M5
让系统真的去做。

M6
让系统知道自己做成了什么。

M7
让系统只把真正知道、
真正允许表达的事情，
以用户愿意接受的方式说出来。
```