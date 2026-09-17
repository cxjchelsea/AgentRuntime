# 可复用 Agent Runtime 平台八种智能与 M0–M9 实现映射规范 V1.0

> **Phase 0 Fix**  
> 首批 Core Contract 以 Canonical Registry V1.0 为准。  
> “8 大业务模块”是历史产品表述，不是 Core 固定业务目录。M9 接入的是任意 Domain Package。

## 1. 文档目的


> **平台化转换说明**  
> 本文已从单一业务 Agent 设计转换为 **可复用 Agent Runtime 平台**设计。除明确标记为 `Core` 的对象、接口、不变量和生命周期外，任何具体业务 Intent、Entity、Workflow、Skill、Tool、知识域、状态字段、规则、提示词或示例均视为 **Domain Package 示例**，不得硬编码进 Runtime Core。新项目应通过 Registry / Adapter / Plugin / Config 注入领域差异。
> 
> 平台固定边界：`Runtime Core` 尽量稳定；`Domain Extension` 插件化；`Business Package` 配置化；`Application` 负责产品装配。

本规范用于建立《八种智能能力规范》与后续 M0～M9 软件实现之间的正式映射关系。

本规范解决两个问题：

```text
八种智能
到底由哪些软件阶段实现？

每个 M
除了完成软件职责之外，
具体为哪些“智能表现”提供支撑？
```

整体关系为：

```text
八种智能能力规范
        ↓
八种智能 × M0～M9 映射
        ↓
M0～M9 详细实现方案
        ↓
8 大业务模块接入
        ↓
具体业务内容与场景
```

其中：

```text
八种智能
= Agent 能力目标

M0～M9
= 软件工程实现路径

8 大业务模块
= 智能能力落地的业务域
```

八种智能本身不直接对应八个软件模块。

---

# 2. M0～M9 定义

本项目后续统一采用以下阶段划分：

| 阶段 | 名称 | 核心职责 |
|---|---|---|
| M0 | Runtime Skeleton | 建立 Agent Runtime 总骨架与统一数据契约 |
| M1 | Input & Context | 建立输入标准化、会话上下文和运行上下文 |
| M2 | Safety / State / Policy | 建立安全、状态机、优先级、抢占与确定性约束 |
| M3 | Understanding | 理解用户当前表达、情绪、目标与隐含需要 |
| M4 | Planning & Orchestration | 根据理解结果决定下一步行为与能力编排 |
| M5 | Execution Framework | 统一执行 Skill / Workflow / Tool |
| M6 | Result Validation | 校验 Tool 真实结果、业务事实与安全边界 |
| M7 | Response Generation | 根据已确定行为和真实结果生成自然回复 |
| M8 | State & Memory Update | 更新状态、会话、事件及长期记忆 |
| M9 | Domain Package & Business Capability Integration | 接入任意 Domain Package，不修改 Runtime Core |

---

# 3. 八种智能与 M0～M9 总映射

| 智能能力 | 核心阶段 | 重要支撑阶段 | 最终业务落地 |
|---|---|---|---|
| 1. 语义理解智能 | M3 | M1 | M9 |
| 2. 上下文智能 | M1、M3 | M4、M8 | M9 |
| 3. 关系连续性智能 | M8 | M1、M3、M4 | M9 |
| 4. 情绪理解智能 | M3 | M1、M2 | M9 |
| 5. 目标与隐含需求推断智能 | M3 | M1、M4 | M9 |
| 6. 对话策略智能 | M4 | M2、M3、M6、M7 | M9 |
| 7. 主动性智能 | M4、M8 | M1、M2 | M9 |
| 8. 自我约束智能 | M2、M6 | M3、M4、M5、M7、M8 | M9 |

需要特别注意：

```text
没有任何一种智能
是只靠单一 M 就能完整实现的。
```

M3 和 M4 是核心智能决策节点，但必须依赖 M1、M2、M6、M8 等基础能力。

---

# 4. M0 —— Runtime Skeleton

## 4.1 M0 的职责

M0 不直接实现某一种智能，而是为八种智能建立统一运行框架。

核心任务：

```text
建立一次用户交互的完整 Runtime 链路

Input
→ Safety
→ Context
→ Understanding
→ Policy
→ Planning
→ Execution
→ Validation
→ Response
→ Update
```

---

## 4.2 M0 对八种智能的意义

M0 主要解决：

> 后续八种智能产生的信息，如何在整个 Agent Runtime 中流动？

如果没有 M0，容易出现：

```text
情绪理解一套数据
Memory 一套数据
Planner 一套数据
业务模块又一套数据
```

最终无法形成统一 Agent。

---

## 4.3 M0 必须预定义的核心数据对象

建议至少包括：

```text
RuntimeInput
RuntimeContext
UnderstandingState
PolicyDecision
ActionPlan
ExecutionResult
ValidatedResult
ResponsePlan
StateUpdate
MemoryUpdate
```

这些对象具体字段后续在对应 M 中展开。

---

## 4.4 对智能目标的映射

M0 对全部八种智能均属于：

```text
基础承载
```

但不负责具体智能判断。

---

# 5. M1 —— Input & Context

## 5.1 主要承载智能

核心：

```text
上下文智能
```

重要支撑：

```text
语义理解智能
关系连续性智能
情绪理解智能
目标推断智能
主动性智能
```

---

## 5.2 M1 的核心任务

M1 要解决的问题是：

> 系统在理解当前一句话之前，到底知道哪些背景？

---

## 5.3 应形成统一 RuntimeContext

至少包括：

```text
用户身份
设备身份
当前时间

session_id
当前 Runtime State
当前业务状态

最近对话历史
当前话题
当前任务
待回答问题

近期事件
当前提醒
正在执行的 Tool

相关长期记忆
近期关系信息

当前安全状态
最近主动行为
最近被拒绝记录
```

---

## 5.4 与八种智能关系

### 对语义理解

提供：

```text
“那个”
“还是之前的”
“她”
“再来一个”
```

等表达的解析背景。

### 对上下文智能

M1 是主要数据基础。

### 对关系连续性

负责将相关 Memory 注入当前 Context。

### 对情绪理解

提供前文，避免只看单句话判断情绪。

### 对目标推断

提供：

```text
用户前面在聊什么
刚刚发生什么
当前任务是什么
```

### 对主动性

提供：

```text
最近是否主动过
用户是否刚拒绝
当前是否安静陪伴
```

---

## 5.5 M1 不负责

M1 不直接判断：

```text
用户到底是什么情绪
用户真正想做什么
系统下一步应该做什么
```

它只负责：

> 给后续智能提供正确上下文。

---

# 6. M2 —— Safety / State / Policy

## 6.1 主要承载智能

核心：

```text
自我约束智能
```

重要支撑：

```text
情绪理解
对话策略
主动性
```

---

## 6.2 M2 的核心任务

M2 要回答：

```text
现在是什么状态？
什么行为是允许的？
什么行为必须禁止？
谁可以抢占谁？
哪些情况必须进入安全流程？
```

---

## 6.3 M2 主要组成

建议包括：

```text
State Machine
Priority Engine
Preemption Engine
Safety Rules
Business Policy
Permission Rules
Timeout Policy
Interrupt Policy
```

---

## 6.4 对八种智能关系

### 自我约束智能

M2 是核心实现阶段之一。

例如：

```text
高风险事件
→ 不允许普通 Planner 继续自由决策
```

```text
求助处理中
→ 禁止播放请求抢占
```

### 情绪理解

M3 可以判断情绪，但：

```text
普通情绪
还是
高风险事件
```

最终必须受到 Safety Policy 约束。

### 对话策略

M4 可以产生候选动作，但 M2 决定：

```text
这个动作是否允许
```

### 主动性

主动问候必须受到：

```text
安静时间
频率限制
当前业务状态
用户拒绝状态
```

约束。

---

# 7. M3 —— Understanding

## 7.1 主要承载智能

M3 是八种智能体系中的第一个核心智能阶段。

直接承担：

```text
语义理解智能
情绪理解智能
目标与隐含需求推断智能
```

同时大量使用：

```text
上下文智能
关系连续性智能
```

---

## 7.2 M3 核心问题

M3 必须回答：

> 这个用户现在到底表达了什么，以及当前处于什么用户状态？

---

## 7.3 M3 最终不应只输出 Intent

不建议：

```text
intent = chat
```

而应形成统一：

```text
UnderstandingState
```

---

## 7.4 UnderstandingState 建议至少包含

```text
explicit_intents

entities
references
topic

emotion
emotion_intensity
emotion_cause

explicit_goal
implicit_need

risk_signal

uncertainty
ambiguity

needs_clarification

conversation_stage

candidate_actions
```

---

## 7.5 对八种智能的具体映射

### 语义理解智能

M3 完成：

```text
意图
实体
多意图
修正
否定
指代
省略
```

理解。

### 上下文智能

M3 负责：

```text
利用 M1 Context
解释当前输入
```

### 关系连续性

M3 要判断：

```text
当前表达
是否与某条历史记忆相关
```

但不直接决定是否使用该记忆回复用户。

### 情绪理解

M3 建立：

```text
emotion
cause
intensity
interaction_need
```

等状态。

### 目标与隐含需求推断

M3 区分：

```text
用户说了什么
和
用户实际上可能想获得什么
```

---

# 8. M4 —— Planning & Orchestration

## 8.1 主要承载智能

M4 是第二个核心智能阶段。

直接承担：

```text
对话策略智能
主动性智能
```

同时使用：

```text
上下文智能
关系连续性智能
目标推断智能
自我约束智能
```

---

## 8.2 M4 核心问题

M4 回答：

> 我已经理解这个用户现在的状态了，下一步最合适做什么？

---

## 8.3 输入

M4 主要接收：

```text
UnderstandingState
RuntimeContext
Memory
Policy
Current State
Recent Agent Actions
```

---

## 8.4 输出

统一：

```text
ActionPlan
```

建议包括：

```text
primary_action
secondary_actions

selected_skill
selected_workflow

tool_calls

whether_to_ask
whether_to_use_memory
whether_to_wait
whether_to_end

response_strategy

stop_condition

fallback
```

---

## 8.5 推荐 Action Space

例如：

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

---

## 8.6 对八种智能的关系

### 对话策略智能

这是 M4 的核心。

### 主动性智能

M4 决定：

```text
要不要主动
主动什么
以什么方式主动
```

### 关系连续性

M4 决定：

```text
某条记忆现在该不该用
```

### 自我约束

所有 ActionPlan 必须经过 M2 Policy。

---

# 9. M5 —— Execution Framework

## 9.1 主要作用

M5 不主要产生“智能判断”。

它负责：

> 把 M4 的决定转化为真实业务执行。

---

## 9.2 对智能的意义

如果 M3/M4 是：

```text
想明白
```

M5 就是：

```text
真正做出来
```

---

## 9.3 统一执行对象

建议包括：

```text
Skill
Workflow
Tool
Service
```

---

## 9.4 示例

M4：

```text
PLAY_CONTENT
```

M5：

```text
ContentSkill
→ ContentSearchTool
→ PlayTool
```

---

## 9.5 对八种智能的支撑

主要支撑：

```text
对话策略智能
主动性智能
自我约束智能
```

因为好的决策必须能够被正确执行。

---

# 10. M6 —— Result Validation

## 10.1 主要承载智能

核心：

```text
自我约束智能
```

---

## 10.2 核心问题

M6 回答：

> 系统真正执行出了什么结果？这个结果是否允许被表达给用户？

---

## 10.3 必须处理的真实性问题

例如：

```text
通知是否真的成功
内容是否真的开始播放
Weather Tool 是否真的获得数据
Memory 是否真的找到对应内容
提醒是否真的更新
```

---

## 10.4 典型规则

```text
Tool 返回 fail
→ 禁止 Response 生成 success 语义
```

```text
Memory 未找到
→ 禁止模型虚构“我记得……”
```

---

## 10.5 输出

建议形成：

```text
ValidatedResult

business_status
verified_facts
unverified_facts
allowed_claims
forbidden_claims
fallback_required
```

---

# 11. M7 —— Response Generation

## 11.1 主要作用

M7 负责：

> 已经知道该做什么、实际结果是什么以后，如何自然地说出来。

---

## 11.2 与八种智能关系

M7 本身不是独立的第九种“表达智能”。

它是八种智能最终对用户可感知的出口。

主要体现：

```text
语义理解结果
情绪理解结果
关系连续性
对话策略
自我约束
```

---

## 11.3 输入

应主要来自：

```text
ActionPlan
ValidatedResult
UnderstandingState
RuntimeContext
Response Policy
```

而不是重新让 LLM 自由决定业务行为。

---

## 11.4 重要原则

M7 负责：

```text
怎么说
```

不重新决定：

```text
做什么
```

---

# 12. M8 —— State & Memory Update

## 12.1 主要承载智能

核心：

```text
关系连续性智能
```

重要支撑：

```text
上下文智能
主动性智能
```

---

## 12.2 M8 核心问题

一次交互结束以后：

```text
什么只是这一轮临时状态？
什么需要带到下一轮？
什么应该进入长期记忆？
什么旧信息需要更新？
```

---

## 12.3 更新范围

包括：

```text
Runtime State
Session Context
Current Topic
Pending Task
Recent Events

Short-term Memory
Long-term Memory
Preference
Relationship Information
```

---

## 12.4 关系连续性核心

不能：

```text
每次对话都写长期 Memory
```

而应先经过：

```text
memory candidate
→ relevance
→ confidence
→ importance
→ policy
→ write / update / ignore
```

---

## 12.5 主动性支持

M8 还需要保存：

```text
最近主动问候时间
最近主动主题
最近拒绝次数
近期重要事项
适合后续跟进的话题
```

供下一次主动规划使用。

---

# 13. M9 —— Domain Package & Business Capability Integration

## 13.1 M9 的定位

M9 不是重新设计 Agent 智能。

而是：

> 将已经建立好的八种智能和 Runtime 能力应用到具体业务模块。

---

## 13.2 8 大模块

```text
领域交互模块
内容播放模块
情绪安抚模块
安全与领域事件模块
领域提醒模块
领域任务交互模块
长期记忆模块
新闻天气模块
```

---

# 14. 八种智能在 8 大业务中的体现

## 14.1 领域交互

重点使用：

```text
语义理解
上下文
关系连续性
情绪理解
隐含需求
对话策略
主动性
```

这是八种智能表现最综合的业务模块之一。

---

## 14.2 内容播放

重点使用：

```text
语义理解
上下文
关系连续性
目标推断
```

例如理解：

> “放点我以前喜欢听的。”

---

## 14.3 情绪安抚

重点使用：

```text
情绪理解
隐含需求
上下文
关系连续性
对话策略
自我约束
```

---

## 14.4 安全与领域事件

重点使用：

```text
语义理解
风险理解
自我约束
```

但核心执行由确定性 Workflow 控制。

---

## 14.5 领域提醒

重点使用：

```text
上下文智能
主动性智能
自我约束智能
```

---

## 14.6 领域任务交互

重点使用：

```text
语义理解
上下文
对话策略
关系连续性
```

---

## 14.7 长期记忆

重点使用：

```text
关系连续性
上下文智能
自我约束
```

---

## 14.8 新闻天气

重点使用：

```text
语义理解
上下文
目标推断
自我约束
```

其中真实新闻和天气事实必须来自 Tool。

---

# 15. 跨 M 智能链路

八种智能最终不是分散工作的，而应该形成以下完整链路：

```text
M1
建立当前世界和用户上下文
        ↓
M3
理解用户
        ↓
形成 UnderstandingState
        ↓
M2
施加安全和业务约束
        ↓
M4
制定 ActionPlan
        ↓
M5
执行 Skill / Workflow / Tool
        ↓
M6
验证真实结果
        ↓
M7
自然表达
        ↓
M8
更新状态和记忆
        ↓
下一次 M1
```

最终形成循环：

```text
理解用户
↓
采取行为
↓
观察结果
↓
持续更新对用户的认识
↓
下一轮理解得更好
```

---

# 16. 各 M 的智能责任边界

为了防止后续实现职责混乱，需要固定以下边界。

## M1

负责：

```text
我现在知道哪些上下文？
```

不负责：

```text
这些上下文说明用户想干什么？
```

---

## M2

负责：

```text
什么允许做、什么不能做？
```

不负责：

```text
普通情况下最自然的下一步是什么？
```

---

## M3

负责：

```text
用户现在是什么意思？
用户当前可能需要什么？
```

不负责：

```text
最终选择哪个动作。
```

---

## M4

负责：

```text
下一步做什么？
```

不负责：

```text
Tool 实际是否执行成功。
```

---

## M5

负责：

```text
按照计划执行。
```

不负责：

```text
修改 Planner 的业务意图。
```

---

## M6

负责：

```text
实际发生了什么？
哪些事实可以对用户说？
```

---

## M7

负责：

```text
如何自然地表达。
```

不负责：

```text
重新决定业务行为。
```

---

## M8

负责：

```text
哪些状态和信息应该被保留下来？
```

不负责：

```text
重新解释用户本轮含义。
```

---

# 17. 后续每个 M 的详细设计要求

从本规范开始，后续每一份 M 详细方案至少必须包含：

```text
1. 本阶段软件目标

2. 本阶段承载的八种智能目标

3. 输入

4. 输出

5. 核心数据结构

6. 内部组件

7. 决策逻辑

8. 与前后 M 的接口

9. 与 8 大业务模块的关系

10. 配置项与可变项

11. 异常与降级

12. 测试与评估方案

13. 本阶段完成标准
```

---

# 18. 最终统一关系

本项目后续整体设计统一理解为：

```text
第一层
八种智能能力

回答：
机器人应该聪明在哪里？

↓

第二层
M0～M9 Runtime 实现

回答：
这些智能具体怎么被软件实现？

↓

第三层
8 大业务模块

回答：
这些智能在哪些产品能力里发挥作用？

↓

第四层
具体业务内容

回答：
真正提供给用户的是什么内容和服务？
```

最终不允许出现：

```text
八种智能各自变成八套独立代码系统
```

也不允许：

```text
M0～M9 只完成传统软件架构，
却没有承载智能能力目标
```

正确目标是：

```text
八种智能
作为能力约束

+

M0～M9
作为统一 Agent Runtime 实现

+

8 大模块
作为业务能力插件

+

内容配置
作为持续变化的产品资产
```

共同形成完整桌面式情感陪护 Agent。