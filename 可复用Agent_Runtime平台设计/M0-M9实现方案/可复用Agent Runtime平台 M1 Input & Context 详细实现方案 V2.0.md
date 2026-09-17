# 可复用 Agent Runtime 平台  
# M1 Input & Context 详细实现方案 V2.0

> **Phase 0 Fix**  
> 首批 Core Contract 以 Canonical Registry V1.0 为唯一正式来源。  
> `elder_id` 已从 Core 删除，改 `subject_id` + `identity_scope`。  
> `source` / `trigger_type` 必须使用 Canonical Registry 大写枚举。

> **平台化转换说明**  
> 本文已从单一业务 Agent 设计转换为 **可复用 Agent Runtime 平台**设计。除明确标记为 `Core` 的对象、接口、不变量和生命周期外，任何具体业务 Intent、Entity、Workflow、Skill、Tool、知识域、状态字段、规则、提示词或示例均视为 **Domain Package 示例**，不得硬编码进 Runtime Core。新项目应通过 Registry / Adapter / Plugin / Config 注入领域差异。
> 
> 平台固定边界：`Runtime Core` 尽量稳定；`Domain Extension` 插件化；`Business Package` 配置化；`Application` 负责产品装配。

> 本版本为 M1 V1.0 的结构化重整版。  
> 保留前序 M1 中已经确定的 RuntimeInput、RuntimeContext、Context 分类、生命周期、选择机制、冲突规则、Serializer、Context Budget、PoC、Gate、交付物等内容，并补齐运行时主流程、依赖、跨 M 接口、非功能约束和版本治理。

---

# 01. 阶段定位

M1 是：

```text
Input & Context
```

阶段。

它解决两个核心问题：

```text
第一：
这一轮进入系统的输入，到底是什么？

第二：
系统在理解这一轮输入之前，
应该知道哪些当前有效的背景信息？
```

M1 不负责：

```text
最终判断用户意图
最终判断用户情绪
最终推断隐含需求
最终决定下一步 Action
```

这些分别属于后续 M3 / M4。

M1 的核心责任是：

> 为后续理解和决策准备一份正确、足够、当前有效、结构化并且具有生命周期的 RuntimeContext。

因此 M1 可以概括成：

```text
M0：
建立容器和管道

M1：
把正确的信息装进容器
```

---

# 02. 阶段目标与八种智能映射

## 2.1 M1 总体目标

M1 最终要做到：

```text
输入统一

+

上下文构建

+

上下文筛选

+

上下文生命周期管理

+

当前事实 / 状态 / 任务 / 历史信息隔离

+

为 M3 提供可直接理解的 RuntimeContext
```

---

## 2.2 与八种智能的关系

M1 核心承担：

```text
上下文智能
```

并重点支撑：

```text
语义理解智能

关系连续性智能

情绪理解智能

目标与隐含需求推断智能

主动性智能
```

映射如下：

| 智能能力 | M1作用 |
|---|---|
| 语义理解智能 | 为指代、省略、多轮理解提供必要上下文 |
| 上下文智能 | M1核心 |
| 关系连续性智能 | 把相关关系信息、近期信息、Memory 注入当前上下文 |
| 情绪理解智能 | 提供近期话题、事件、用户表达连续性 |
| 隐含需求推断智能 | 提供当前场景和前文背景 |
| 对话策略智能 | 间接支撑，由 M4读取 Context |
| 主动性智能 | 提供近期主动行为、拒绝、安静时段等信息 |
| 自我约束智能 | 提供真实系统状态、Tool 状态、任务状态 |

---

# 03. 职责边界

## 3.1 M1 负责

M1 负责：

```text
原始输入标准化

RuntimeInput 构建

用户身份上下文

Session 上下文

Runtime State 上下文

Conversation Context

Task Context

Time Context

Relationship Context

Memory Context 接口

Safety Context

Tool Context

Interaction Context

Environment Context

Context Selector

Context 生命周期

Context 优先级

Context 冲突规则

Context Serializer

Context Budget
```

---

## 3.2 M1 不负责

M1 不应该做：

```text
情绪分类

最终意图分类

高风险最终判定

隐含需求推断

策略选择

业务路由

Tool 调用

长期 Memory 写入
```

例如用户说：

> “我今天不太想说话。”

M1 只负责保存：

```text
当前输入文本

最近对话

当前业务状态

是否刚刚问过问题

是否刚刚主动过

用户身份

当前时间
```

而不是直接判断：

```text
用户需要安静陪伴
```

这个推断属于 M3。

---

# 04. 前置依赖与外部依赖

## 4.1 前置阶段依赖

M1 依赖 M0 提供：

```text
Runtime Engine

RuntimeInput 基础 Schema

RuntimeContext 基础 Schema

request_id

session_id

trace_id

ContextBuilder Interface

基础 Store 接口

基础 Trace 能力
```

---

## 4.2 数据源依赖

Context Builder 未来可能依赖：

```text
Session Store

State Store

Task Store

Conversation Store

Recent Context Store

Memory Service

Tool State Store

Event Store

User Profile

Time Service

Device State
```

---

## 4.3 外部依赖原则

M1 不应要求：

```text
每一轮必须查询所有外部服务
```

而应该：

```text
按需构建 Context
```

避免：

```text
每轮全量 Memory 查询

每轮全量业务状态读取

每轮加载全部历史
```

---

# 05. 输入

M1 的输入不是只有语音文本。

统一入口是：

```text
RawInput
```

来源至少包括：

```text
USER_VOICE

REMINDER_DUE

ACTIVE_GREETING

SYSTEM_EVENT

TOOL_CALLBACK

TIMEOUT

NETWORK_EVENT
```

当前用户端需求本身就包含用户语音、定时提醒、主动问候、通知结果、网络异常等多种事件来源，因此输入必须统一。

---

# 06. 输出

M1 最终输出两类核心对象：

```text
RuntimeInput

RuntimeContext
```

其中：

```text
RuntimeInput
=
标准化后的当前输入

RuntimeContext
=
当前这一轮有效的运行背景
```

这些对象共同作为 M3 的主要输入。

---

# 07. 核心数据结构

# 7.1 RuntimeInput

建议：

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
trigger_type

text
raw_text

timestamp

input_payload
confidence
segments
metadata
```

---

## 7.1.1 source

例如：

```text
USER
SYSTEM
SCHEDULER
TOOL
WORKFLOW
DEVICE
EXTERNAL
```

禁止再使用 `voice` / `scheduler` 等小写并行枚举。

---

## 7.1.2 trigger_type

例如：

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

`reminder` / `active_greeting` 不是 Core trigger。它们只可作为 Domain 对 `SCHEDULER_EVENT` / `SYSTEM_EVENT` 的 payload 细分（Domain Example）。

---

# 7.2 RuntimeContext

M1 正式定义：

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
```

下面逐项展开。

---

# 7.3 IdentityContext

表示：

> 当前系统到底在和谁交互？

建议：

```text
IdentityContext

subject_id

identity_status

device_id

room_id

preferred_name

preferred_addressing

language_preference
```

identity_status：

```text
BOUND

UNBOUND

UNKNOWN
```

当前需求已经明确：

```text
未绑定用户
→ 不得写入未定义个人档案
→ 可进入公共模式
```

因此身份状态必须显式存在。

---

# 7.4 SessionContext

表示：

> 当前会话本身是什么状态？

建议：

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

# 7.5 RuntimeStateContext

表示：

> 当前系统处于什么业务运行状态？

建议：

```text
RuntimeStateContext

current_state

previous_state

current_business

current_priority

interruptible

entered_at
```

当前需求已经定义：

```text
S00～S11
S90
```

等用户端状态。

---

# 7.6 ConversationContext

这是后续自然对话能力的重要上下文。

建议：

```text
ConversationContext

recent_turns

current_topic

topic_history

pending_reference

pending_question

last_user_message

last_agent_action

conversation_stage
```

---

# 7.7 TaskContext

表示：

> 当前是否存在一个尚未完成的业务任务？

建议：

```text
TaskContext

active_task

task_type

task_id

task_stage

required_fields

collected_fields

next_required_field

timeout_at
```

例如身体不适采集：

```text
active_task = discomfort_collection

task_stage = 3

collected_fields:
  location = 胸口
  sensation = 闷

next_required_field =
onset_time
```

这比依靠聊天历史判断“问到哪了”可靠得多。

---

# 7.8 TimeContext

建议：

```text
TimeContext

current_datetime

time_of_day

weekday

date

quiet_period

special_date

active_time_window
```

time_of_day 可包括：

```text
morning

noon

afternoon

evening

night
```

当前需求已经存在：

```text
早安问候
午间问候
晚间问候
22:00–06:00 安静时段
```

因此时间必须成为 Context 的一等数据。

---

# 7.9 RelationshipContext

表示：

> 当前这一轮最相关的关系信息。

建议：

```text
RelationshipContext

preferred_addressing

important_people

current_relationship_topics

recent_person_mentions

interaction_preferences
```

注意：

```text
RelationshipContext
!=
整个长期 Memory
```

这里仅加载当前相关的关系数据。

---

# 7.10 MemoryContext

表示：

> 当前这一轮从长期 Memory 中召回的相关内容。

建议：

```text
MemoryContext

retrieved_memories

memory_query

retrieval_reason

memory_confidence

memory_status
```

M1 不负责决定最终：

```text
记什么

写什么

删什么
```

这些主要属于 M8。

M1 只定义：

```text
Memory 以什么结构进入当前 Context
```

---

# 7.11 SafetyContext

建议：

```text
SafetyContext

current_risk_state

active_safety_event

recent_safety_event

safety_lock

restricted_actions
```

M1 只提供：

```text
已有的 Safety 状态
```

不负责本轮最终风险判断。

最终风险决策属于 M2。

---

# 7.12 ToolContext

表示当前真实 Tool 状态。

建议：

```text
ToolContext

active_tool_calls

recent_tool_results

playback_status

notification_status

network_status
```

例如：

```text
playback_status = PLAYING
```

那么用户说：

> “停一下。”

M3 才有条件理解：

```text
停的是当前播放
```

---

# 7.13 InteractionContext

用于描述：

> 最近 Agent 与用户之间的交互节奏。

建议：

```text
InteractionContext

last_agent_action

last_response_strategy

recent_questions_count

recent_suggestions

recent_rejections

recent_active_interactions

silence_mode

user_interrupt_count
```

这部分非常重要。

它可以帮助后续避免：

```text
一直追问

一直推荐

刚被拒绝又推荐

一直主动讲话

反复问同一个问题
```

---

# 7.14 EnvironmentContext

根据设备能力预留：

```text
EnvironmentContext

network_status

audio_status

speaker_status

microphone_status

battery_status
```

当前需求已经存在：

```text
网络异常

麦克风不可用

扬声器异常

低电量
```

等软件异常行为，因此设备环境也应进入 RuntimeContext。

---

# 08. 数据来源、存储与生命周期

M1 最核心的设计之一就是：

```text
Context 生命周期
```

因为 Context 不能无限保存。

---

# 8.1 Context != 全部历史

必须固定：

```text
Context
!=
所有历史数据
```

Context 是：

> 当前这一轮理解和决策所需要的、仍然有效的信息。

因此不要：

```text
把最近100轮直接塞进 Prompt

把全部长期 Memory 都加载

把所有过去的话题一直保留为 current
```

---

# 8.2 Turn-Level Context

只在当前一轮有效。

例如：

```text
当前 RuntimeInput

当前 ASR confidence

当前 Tool Callback

当前模型输入
```

本轮结束后清理。

---

# 8.3 Session-Level Context

当前会话有效。

例如：

```text
current_topic

pending_question

recent_turns

active_task

pending_reference
```

会话结束后：

```text
清理
或
摘要化
```

---

# 8.4 Recent Context

跨会话短期存在。

例如：

```text
今天女儿准备来看望

今天已经主动问候过

刚刚拒绝听音乐

最近在连续听某部评书
```

这些通常需要：

```text
TTL
```

而不是永久 Memory。

---

# 8.5 Long-Term Context

真正长期保存的信息，例如：

```text
家乡

家庭成员

稳定兴趣

长期习惯

重要人生经历
```

由 M8 判断是否写入。

---

# 8.6 推荐 Context Store 分层

建议：

```text
Context Storage

├── Turn Store

├── Session Store

├── Recent Context Store

├── Task Store

└── Long-Term Memory Store
```

避免所有信息放进一张“大 Memory 表”。

---

# 8.7 生命周期事件

Context 可以因为以下原因失效：

```text
TTL 到期

显式结束

业务完成

状态切换

用户纠正

新事实覆盖

Memory更新
```

---

# 8.8 Pending Question 生命周期

例如 Agent：

> “现在要不要叫人帮忙？”

建立：

```text
pending_question =
HELP_CONFIRMATION
```

用户回答后必须：

```text
立即消费并清除
```

否则下一句话“不要了”可能被错误解释。

---

# 8.9 Topic 生命周期

当前话题：

```text
女儿来访
```

之后用户开始天气查询：

```text
current_topic
→ WEATHER
```

旧话题：

```text
进入 topic_history
```

而不是仍然占据 current_topic。

---

# 8.10 用户纠正

例如：

> “不是明天，是后天。”

应：

```text
旧临时事实失效

新事实成为当前有效值
```

不能保留：

```text
tomorrow
day_after_tomorrow
```

两个同等有效值。

---

# 09. 内部组件

推荐 M1 包含：

```text
InputAdapter

InputNormalizer

ContextBuilder

ContextSelector

ContextLifecycleManager

ContextConflictResolver

ContextSerializer

ContextBudgetManager
```

以及各种 Provider：

```text
IdentityProvider

SessionProvider

StateProvider

ConversationProvider

TaskProvider

TimeProvider

RelationshipProvider

MemoryProvider

SafetyProvider

ToolProvider

InteractionProvider

EnvironmentProvider
```

---

# 10. 运行时实现主流程

M1 真正运行时建议固定为：

```text
RawInput
   ↓
① Input Adapter
   ↓
② Input Normalize
   ↓
③ RuntimeInput 构造
   ↓
④ 确定 Context 构建需求
   ↓
⑤ Context Selector
   ↓
⑥ 各 Context Provider 拉取信息
   ↓
⑦ 生命周期 / Freshness 校验
   ↓
⑧ 冲突处理
   ↓
⑨ Context 聚合
   ↓
⑩ RuntimeContext
   ↓
⑪ Context Serializer
   ↓
面向 M3 的 Understanding Context View
```

---

## 10.1 伪代码

```python
async def build_context(
    raw_input,
    runtime_state
):
    runtime_input = input_normalizer.normalize(
        raw_input
    )

    context_plan = context_selector.select(
        runtime_input,
        runtime_state
    )

    loaded = {}

    for provider in context_plan.providers:
        loaded[provider.name] = await provider.load(
            runtime_input,
            runtime_state
        )

    fresh_context = lifecycle_manager.filter_expired(
        loaded
    )

    resolved_context = conflict_resolver.resolve(
        fresh_context,
        runtime_input
    )

    runtime_context = context_builder.merge(
        resolved_context
    )

    return runtime_input, runtime_context
```

M3 真正需要模型 Context 时，再：

```python
llm_context = context_serializer.serialize(
    runtime_context,
    target="understanding"
)
```

---

# 11. 各步骤详细实现

# Step 1：Input Adapter

不同数据源先适配：

```text
VoiceInput

SchedulerInput

SystemInput

ToolCallbackInput
```

全部转换到统一 RawInput 结构。

---

# Step 2：Input Normalize

负责：

```text
编码统一

文本清洗

基础标点恢复

ASR结果标准化

时间格式统一

来源统一

空输入检查

重复输入去重

事件格式统一
```

---

## 11.2.1 ASR 特殊处理

目标用户语音可能存在：

```text
停顿长

重复

断句错误

语速慢

表达含混

地方口音

自我修正
```

因此建议保留：

```text
raw_text

normalized_text

asr_confidence

segments
```

例如：

```text
raw_text:
“我……我想听那个……昨天那个”

normalized_text:
“我想听昨天那个”
```

但：

```text
raw_text
!=
长期保存
```

当前需求要求普通闲聊默认不保存完整录音，遵循最小必要原则。

---

# Step 3：RuntimeInput 构造

将标准化结果封装成：

```text
RuntimeInput
```

并绑定：

```text
request_id

trace_id

session_id

subject_id

device_id
```

---

# Step 4：确定 Context 构建需求

不是所有输入都需要相同 Context。

例如：

```text
USER_INPUT
```

通常需要：

```text
Session
State
Conversation
Time
Task
Tool
Interaction
```

提醒事件：

```text
REMINDER_DUE
```

重点需要：

```text
State
ReminderTask
Time
Safety
```

主动问候：

```text
ACTIVE_GREETING
```

重点需要：

```text
State
Time
InteractionHistory
RecentContext
```

---

# Step 5：Context Selector

引入：

```text
ContextSelector
```

负责：

> 当前这一轮到底应该加载哪些 Context。

初版可以规则化。

例如：

```text
USER_INPUT

→ Session
→ State
→ Conversation
→ Task
→ Time
→ Tool
```

如果输入明显涉及人物指代，再增加：

```text
Relationship
Memory
```

---

# Step 6：Context Provider 读取

各 Provider 分别读取。

例如：

```text
SessionProvider
→ SessionStore

StateProvider
→ StateStore

TaskProvider
→ TaskStore

TimeProvider
→ TimeService

MemoryProvider
→ MemoryService
```

Provider 不负责最终推断。

---

# Step 7：Freshness / 生命周期校验

每条动态信息建议至少带：

```text
created_at

updated_at

expires_at
```

必要时：

```text
source

confidence
```

例如：

```json
{
  "value": "今天女儿可能来",
  "source": "user_stated",
  "created_at": "...",
  "expires_at": "..."
}
```

过期信息不得继续作为当前事实。

---

# Step 8：Context 冲突处理

推荐优先级：

```text
当前明确表达
>
当前业务真实状态
>
近期确认信息
>
稳定长期 Memory
>
旧历史信息
>
模型推断
```

例如：

长期 Memory：

```text
喜欢京剧
```

用户当前说：

> “今天不想听京剧。”

当前意愿必须优先。

---

# Step 9：Context 聚合

ContextBuilder 将不同来源统一组织为：

```text
RuntimeContext
```

但不产生：

```text
emotion

implicit_need

final_intent
```

这些仍属于 M3。

---

# Step 10：RuntimeContext 输出

RuntimeContext 作为：

```text
结构化系统事实层
```

提供给后续 M2 / M3 / M4 使用。

---

# Step 11：Context Serializer

如果需要将 Context 输入 LLM，不应该直接：

```text
str(RuntimeContext)
```

而是：

```text
RuntimeContext
↓
ContextSerializer
↓
LLM Context View
```

例如：

```text
当前状态：
领域交互

当前话题：
女儿来访

最近三轮：
...

相关人物：
女儿

相关记忆：
...
```

只选择当前任务真正需要的内容。

---

# 12. 分支、路由与决策规则

# 12.1 Context 按需加载

例如用户问：

> “现在几点？”

一般无需：

```text
全部人生经历
家庭成员
所有兴趣偏好
```

只需要：

```text
TimeContext
CurrentState
Session
```

---

# 12.2 指代型输入

例如：

> “她今天怎么没来？”

需要额外：

```text
recent_person_mentions

relationship_context

recent_turns
```

---

# 12.3 播放控制

例如：

> “换一个。”

需要：

```text
current_business

playback_status

last_content

last_content_category
```

---

# 12.4 Pending Question 优先

如果存在：

```text
pending_question
```

必须优先加载。

例如：

> “不用。”

其含义高度依赖当前 Pending Question。

---

# 12.5 Active Task 优先

身体不适采集等流程中：

```text
active_task
```

优先级高于普通 Conversation Context。

---

# 12.6 Fact 与 Inference 分离

M1 必须把：

```text
事实

系统状态

用户明确陈述

长期 Memory

模型推测
```

区分开。

建议数据来源类型：

```text
FACT

USER_STATED

SYSTEM_STATE

MEMORY

INFERRED

UNKNOWN
```

M1 主要提供：

```text
FACT
USER_STATED
SYSTEM_STATE
MEMORY
```

`INFERRED` 主要由 M3 产生。

---

# 12.7 Context 冲突保留

某些情况下不直接覆盖，而是显式保留冲突。

例如：

```text
historical_preference =
LIKE_BEIJING_OPERA

current_preference =
AVOID_BEIJING_OPERA

conflict = true
```

让 M3/M4 看见：

```text
“长期喜欢”
和
“今天不想听”
```

是两个不同时间尺度的信息。

---

# 13. 与前后 M 的接口

# 13.1 M0 → M1

M0 提供：

```text
RuntimeInput Schema

RuntimeContext Schema

ContextBuilder Interface

Store Interface

Trace
```

---

# 13.2 M1 → M2

M1 向 M2 提供：

```text
current_state

active_task

time_context

tool_context

safety_context

interaction_context
```

供 Policy / Safety 判断。

---

# 13.3 M1 → M3

M1 是 M3 的核心前置。

提供：

```text
RuntimeInput
+
RuntimeContext
```

M3 再产生：

```text
UnderstandingState
```

因此固定：

```text
M1：
“现在有哪些事实和背景？”

M3：
“这些事实和背景说明用户现在是什么意思？”
```

---

# 13.4 M1 → M4

M4 也会使用：

```text
RuntimeContext
```

例如：

```text
最近是否拒绝过音乐

当前是否刚主动问候过

当前 Tool 是否正在执行

当前业务是什么
```

用于策略规划。

---

# 13.5 M8 → M1

M1 与 M8 是循环关系：

```text
M1
读取 Context / Memory

↓

M3 / M4
理解与行动

↓

M8
更新 Context / Memory

↓

下一轮 M1
重新读取
```

---

# 14. 与业务模块的映射

当前业务体系包含 8 大模块、68 个二级目录、Domain Package 中的业务能力目录项。

M1 不需要为 357 个条目逐一写上下文逻辑，而是提供通用 Context。

---

## 14.1 领域交互

重点使用：

```text
ConversationContext

RelationshipContext

MemoryContext

InteractionContext

TimeContext
```

---

## 14.2 内容播放

重点使用：

```text
ToolContext

ConversationContext

pending_reference

current_business

recent content
```

---

## 14.3 情绪安抚

重点使用：

```text
ConversationContext

RecentContext

RelationshipContext

InteractionContext
```

M1 不负责判断情绪，只提供相关背景。

---

## 14.4 安全与领域事件

重点使用：

```text
SafetyContext

TaskContext

RuntimeStateContext

ToolContext
```

---

## 14.5 领域提醒

重点使用：

```text
TaskContext

TimeContext

pending_question

InteractionContext
```

---

## 14.6 领域任务交互

重点使用：

```text
TaskContext

ConversationContext

current question

previous answer
```

---

## 14.7 长期记忆

重点使用：

```text
MemoryContext

RelationshipContext

RecentContext
```

---

## 14.8 新闻天气

重点使用：

```text
TimeContext

ConversationContext

pending_reference

recent query context
```

例如：

> “那后天呢？”

依赖前一轮城市和天气查询上下文。

---

# 15. 异常、超时与降级

# 15.1 Session Store 失败

可以：

```text
创建临时 Session
```

但必须：

```text
history_unavailable = true
```

不能伪造历史。

---

# 15.2 Memory Service 失败

必须区分：

```text
memory_context = unavailable
```

与：

```text
memory_context = empty
```

前者：

```text
服务不可用
```

后者：

```text
确实没有结果
```

语义完全不同。

---

# 15.3 Identity 未知

应：

```text
identity_status = UNBOUND
```

进入公共模式。

不得：

```text
猜测 subject_id
```

---

# 15.4 Context 部分失败

允许：

```text
partial context
```

但必须记录：

```text
missing_context
```

---

# 15.5 Tool State 读取失败

不能假设：

```text
playback_status = STOPPED
```

应：

```text
playback_status = UNKNOWN
```

---

# 15.6 Context 超时

对于低优先级 Provider 可以：

```text
跳过
```

并返回：

```text
missing_context
```

关键 State / Safety Context 则应采用更保守的 Runtime 行为。

---

# 16. 配置项与可变项

建议配置：

```text
recent_turn_limit

session_timeout

recent_context_ttl

topic_ttl

pending_question_ttl

context_provider_timeout

context_budget

summary_threshold

memory_retrieval_enabled

context_source_priority
```

---

## 16.1 recent_turns

例如：

```text
最近 5～10 轮
```

只是建议范围。

最终不应写死在业务代码中，而应配置并通过评估确定。

---

## 16.2 Context Selector

选择规则应可配置。

例如：

```yaml
context_routes:
  user_input:
    - session
    - state
    - conversation
    - task
    - time
    - interaction

  reminder_due:
    - state
    - task
    - time
    - safety

  active_greeting:
    - state
    - time
    - interaction
    - recent_context
```

---

# 17. 非功能约束

# 17.1 性能

Context Builder 不应成为系统主要延迟来源。

优先：

```text
本地 State
Session
Task
Conversation
```

快速读取。

长期 Memory：

```text
按需查询
```

避免每一轮都查询多个远程数据源。

---

# 17.2 Context Budget

需要建立：

```text
ContextBudget
```

尤其面向 LLM。

优先级建议：

```text
高优先级：
当前输入
当前任务
当前 State
Safety

中优先级：
最近对话
当前话题

低优先级：
长期 Memory
较旧摘要
```

Token 超限时：

```text
先丢低优先级信息
```

---

# 17.3 长会话管理

推荐：

```text
recent_turns
+
rolling_summary
```

例如：

```text
recent_turns:
最近若干轮原始对话

rolling_summary:
更早内容的结构化摘要
```

---

# 17.4 隐私

Context 读取必须遵守：

```text
最小必要
```

尤其：

```text
普通闲聊不默认保存完整录音

不同用户数据隔离

未绑定模式不写个人档案
```

与当前需求保持一致。

---

# 17.5 可用性

单个非关键 Context Provider 失败：

```text
不应让整轮对话完全失败
```

但必须显式表达：

```text
Context 缺失
```

---

# 18. Trace / Logging / Observability

每次 Context 构造建议至少记录：

```text
context_sources

requested_context

loaded_context

skipped_context

expired_context

missing_context

conflicting_context

final_context
```

---

## 18.1 关键调试价值

例如 M3 没理解：

> “她今天没来。”

Trace 可以发现：

```text
RelationshipContext
未加载
```

而不是直接认为：

```text
LLM能力不行
```

---

## 18.2 Context Source Trace

建议每个 Context Item 带：

```text
source

created_at

updated_at

expires_at

confidence

trace_reference
```

---

# 19. 版本、兼容与变更影响

## 19.1 RuntimeContext Schema Version

建议：

```text
RuntimeContext.schema_version
```

防止 M3/M4 与 Context 字段版本不一致。

---

## 19.2 可配置变化

以下通常不需要改 Core：

```text
recent_turns 数量

TTL

Context Provider timeout

Context Selector规则

Context Budget
```

---

## 19.3 新增 Context 类型

例如未来新增：

```text
LocationContext

CaregiverContext
```

原则上：

```text
新增 Context Provider
+
扩展 RuntimeContext
```

而不是重写 ContextBuilder。

---

## 19.4 Breaking Change

例如：

```text
删除 pending_question

改变 task_context 语义

改变 memory_context unavailable/empty 区分
```

都会影响 M3/M4，应升级 Schema Version。

---

# 20. 测试 / Eval

# 20.1 Input Normalize 测试

覆盖：

```text
语音输入

提醒事件

系统事件

Tool Callback

Timeout
```

全部可以转换为 RuntimeInput。

---

# 20.2 Context 完整性测试

验证各 Provider 是否正确填充。

---

# 20.3 生命周期测试

测试：

```text
Turn结束

Session结束

Task完成

TTL到期

状态切换

用户纠正
```

之后 Context 是否正确清理。

---

# 20.4 多会话隔离

不同：

```text
subject_id

session_id

device_id
```

不得串数据。

---

# 20.5 Pending Question 测试

不同业务的 pending_question 不能串用。

---

# 20.6 Reference 准备测试

验证 Context 是否能为：

```text
他

她

那个

之前那个

再来一个
```

提供必要信息。

---

# 20.7 Context 冲突测试

例如：

```text
长期：
喜欢京剧

当前：
今天不想听京剧
```

Context 应保留当前信息优先关系。

---

# 20.8 缺失数据测试

覆盖：

```text
Memory unavailable

Identity unknown

Session Store failed

Tool state unknown
```

全部应显式表示。

---

# 20.9 Context Selection 测试

简单问题不能加载大量无关 Context。

例如：

> “现在几点？”

不应自动加载整套人生记忆。

---

# 21. Gate

## Gate M1-01

所有主要输入来源可统一生成：

```text
RuntimeInput
```

---

## Gate M1-02

RuntimeContext 至少具备：

```text
Identity

Session

State

Conversation

Task

Time

Tool

Interaction
```

结构。

---

## Gate M1-03

Context 能区分：

```text
事实

用户陈述

系统状态

Memory

模型推断
```

---

## Gate M1-04

Turn / Session / Recent / Long-Term 四类生命周期边界明确。

---

## Gate M1-05

pending_question 能正确建立、消费和清理。

---

## Gate M1-06

业务切换后旧 Context 不继续作为当前主 Context。

---

## Gate M1-07

不同用户、不同 Session 数据不串用。

---

## Gate M1-08

Memory Service 失败不会被解释为：

```text
用户没有相关 Memory
```

---

## Gate M1-09

可以输出供 M3 使用的完整结构化 RuntimeContext。

---

## Gate M1-10

ContextBuilder 不包含：

```text
最终意图判断

最终情绪判断

最终 Action 决策
```

---

## Gate M1-11

Context Selector 已存在，不能每轮全量加载所有 Context。

---

## Gate M1-12

Context 具有 Freshness / TTL / Source 基础字段。

---

## Gate M1-13

当前明确表达能够压过旧历史和旧 Memory。

---

## Gate M1-14

ContextSerializer 与 RuntimeContext 数据结构分离。

---

## Gate M1-15

Context 缺失能够显式表达，而不是伪造默认值。

---

# 22. 交付物

M1 最终至少形成：

```text
M1-01 Input来源与统一输入规范

M1-02 RuntimeInput数据模型

M1-03 RuntimeContext总体模型

M1-04 Context分类规范

M1-05 Context生命周期规范

M1-06 Context优先级与冲突规则

M1-07 Context Builder实现

M1-08 Context Selector实现

M1-09 Context Serializer实现

M1-10 Session / Recent / Task Store

M1-11 Context Provider接口规范

M1-12 Context Freshness规范

M1-13 Context Budget规范

M1-14 M1测试集

M1-15 M1 Gate验证报告
```

---

# 附录 A：Pending Question 设计

`pending_question` 是多轮 Agent 中非常重要的结构。

例如 Agent：

> “现在要不要叫人帮忙？”

Context：

```text
pending_question:
  type = HELP_CONFIRMATION

  source_business = discomfort

  asked_at = ...
```

用户：

> “不用。”

M3 就可以理解为：

```text
HELP_CONFIRMATION_RESPONSE = NO
```

而不是普通 STOP。

回答处理完成后：

```text
pending_question
必须清除
```

---

# 附录 B：Pending Reference 设计

用于支持：

```text
那个

刚才那个

昨天那个

之前那个

再来一个
```

例如：

```text
pending_reference:
  type = CONTENT

  value = content_123
```

为 M3 Reference Resolver 提供候选对象。

---

# 附录 C：Topic Context

建议维护：

```text
current_topic

topic_stack

topic_history
```

例如：

```text
current_topic =
女儿来访

topic_stack:
- 今天生活
- 女儿来访
```

临时插入：

> “现在几点？”

回答后，M4 可以决定：

```text
是否恢复女儿来访话题
```

---

# 附录 D：Interaction Context 示例

如果：

```text
recent_suggestions:
- PLAY_MUSIC

recent_rejections:
- PLAY_MUSIC
```

那么 M4 后续应该能够利用这个 Context：

```text
避免马上再次建议音乐
```

这就是上下文智能直接改善陪伴自然感的例子。

---

# 附录 E：主动性 Context

主动性需要至少保存：

```text
last_active_greeting_at

active_greeting_count_today

last_active_topic

last_active_result

recent_rejection_count

quiet_until
```

例如安静陪伴后：

```text
quiet_until =
当前时间 + 10 分钟
```

对应现有需求中的低打扰规则。

---

# 附录 F：Recent Fact Store

仅靠：

```text
Session
+
Long-Term Memory
```

是不够的。

还需要：

```text
Recent Context Store
```

例如：

> “女儿明天来。”

这类信息：

```text
未必值得永久保存
```

但在第二天前：

```text
非常重要
```

因此建议：

```text
Session
↓
Recent Context
↓
Long-Term Memory
```

形成三个时间尺度。

---

# 附录 G：Context 与其他概念的边界

## G.1 Context 与 Memory

```text
Conversation Context
=
当前会话和任务

Recent Context
=
跨会话短期动态信息

Long-Term Memory
=
长期稳定信息
```

不能：

```text
聊天出现一次
→ 自动进入长期 Memory
```

---

## G.2 Context 与 State

State：

```text
系统现在处在哪个运行状态
```

Context：

```text
为了理解和决策，
当前还需要知道哪些背景
```

例如：

```text
S06 内容播放中
```

属于 State。

而：

```text
正在播放某段越剧
用户刚才说“换一个”
```

属于 Context。

---

## G.3 Context 与 Understanding

Context：

```text
用户说：
“他们今天都挺忙的”

当前话题：
孩子

关系：
有一位女儿
```

M3 才推断：

```text
possible_emotion =
loneliness

implicit_need =
companionship
```

M1 不提前做。

---

## G.4 Context 与 Planner

Context 可以提供：

```text
用户刚拒绝音乐
```

M4 才决定：

```text
本轮不再次 OFFER_CONTENT
```

---

# 附录 H：RuntimeContext 示例

```json
{
  "identity_context": {
    "subject_id": "E001",
    "identity_status": "BOUND",
    "preferred_addressing": "张奶奶"
  },

  "session_context": {
    "session_id": "S123",
    "turn_index": 6
  },

  "runtime_state_context": {
    "current_state": "S05",
    "current_business": "companion"
  },

  "conversation_context": {
    "current_topic": "family",
    "pending_question": null,
    "recent_person_reference": "daughter"
  },

  "task_context": {
    "active_task": null
  },

  "time_context": {
    "time_of_day": "evening",
    "quiet_period": false
  },

  "memory_context": {
    "retrieved_memories": [
      {
        "type": "family_relation",
        "content": "用户有一位女儿"
      }
    ]
  },

  "interaction_context": {
    "recent_suggestions": [
      "PLAY_MUSIC"
    ],
    "recent_rejections": [
      "PLAY_MUSIC"
    ]
  },

  "tool_context": {
    "playback_status": "STOPPED"
  }
}
```

---

# 附录 I：M1 PoC

## I.1 PoC 1：多轮省略

第一轮：

> “给我放京剧。”

第二轮：

> “换一个。”

第二轮 Context 应提供：

```text
当前业务 =
内容播放

当前类别 =
京剧

当前播放对象 =
X
```

使 M3 可以理解：

```text
换一个京剧内容
```

---

## I.2 PoC 2：Pending Question

Agent：

> “现在要不要叫人帮忙？”

用户：

> “不用。”

Context：

```text
pending_question =
help_confirmation
```

确保 M3 有明确语境。

---

## I.3 PoC 3：主动性

上午已经主动问候。

中午触发：

```text
ACTIVE_GREETING
```

Context 必须提供：

```text
today_active_count

last_active_time

last_result
```

供 M2/M4 判断。

---

## I.4 PoC 4：跨轮人物指代

用户：

> “我女儿最近工作忙。”

之后：

> “她这个星期都没来。”

Context 应保留：

```text
recent_person_reference =
daughter
```

---

## I.5 PoC 5：业务切换

原本：

```text
S06 播放
```

用户：

> “胸口有点难受。”

新的：

```text
active_business_context
→ discomfort
```

旧播放信息进入：

```text
previous_business_context
```

而不能继续成为当前主业务上下文。

---

# 附录 J：M1 完成后的系统状态

完成 M1 后，系统仍然不一定“聪明”。

但它已经不再是：

```text
只看到用户当前一句话
```

而是知道：

```text
现在是谁

现在是什么时间

当前处于哪个状态

正在做什么

前面聊过什么

刚刚问过什么

当前任务做到哪一步

当前 Tool 在做什么

最近 Agent 做过什么

用户刚刚拒绝过什么

有哪些近期信息

有哪些当前相关长期记忆

设备和网络是否正常
```

这一步为 M3 建立真正的理解智能提供了必要基础。

最终：

```text
M1
=
准备“事实与上下文”

M3
=
解释“这些事实意味着什么”
```