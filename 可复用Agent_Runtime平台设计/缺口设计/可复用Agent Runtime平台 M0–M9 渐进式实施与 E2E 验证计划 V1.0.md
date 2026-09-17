# 可复用 Agent Runtime 平台  
# M0–M9 渐进式实施与 E2E 验证计划 V1.0

> **Phase 0 Fix**  
> 首批 Core Contract 以 Canonical Registry V1.0 为唯一正式来源。  
> Phase 1 必须实现的对象见下文已对齐清单。文中单独出现的 `ActionPlan` 在实现时必须拆成 `ActionPlanDraft` / `ApprovedActionPlan`。  
> 提醒 / 求助 / 用药等第一条切片是 Domain Example，不是 Core 能力。

> **平台化转换说明**  
> 本文已从单一业务 Agent 设计转换为 **可复用 Agent Runtime 平台**设计。除明确标记为 `Core` 的对象、接口、不变量和生命周期外，任何具体业务 Intent、Entity、Workflow、Skill、Tool、知识域、状态字段、规则、提示词或示例均视为 **Domain Package 示例**，不得硬编码进 Runtime Core。新项目应通过 Registry / Adapter / Plugin / Config 注入领域差异。
> 
> 平台固定边界：`Runtime Core` 尽量稳定；`Domain Extension` 插件化；`Business Package` 配置化；`Application` 负责产品装配。

---

# 0. 文档定位

本文件定义：

```text
整个可复用 Agent Runtime 平台
从设计进入真实编码阶段后的实施顺序。
```

它解决的核心问题是：

```text
先写哪个模块？

哪些阶段应该一起实现？

什么时候应该联调？

第一条端到端链应该选什么？

什么时候可以接真实Tool？

什么时候可以进入高风险业务？

什么时候算一个Capability真正完成？
```

本文件不是：

```text
M0～M9 的再次设计
```

而是：

```text
把已冻结的设计
转换成真实工程实施路径。
```

---

# 1. 最高实施原则

正式固定：

```text
不要按 M0 → M8 全部实现完成后再统一联调。
```

推荐：

```text
M0 Runtime Skeleton
+
M1～M8最小实现
+
一个Business Vertical Slice
+
E2E
+
逐步扩展
```

---

# 2. 为什么不能纵向全部写完再联调

如果按：

```text
M0
↓
M1
↓
M2
↓
...
↓
M8
↓
最后联调
```

容易出现以下问题：

```text
M3 的 UnderstandingState
实际满足不了 M4

M4 的 ActionPlan
M5 根本执行不了

M5 的 ToolResult
M6 无法验证

M6 的 ClaimPolicy
M7 无法自然表达

M7 的 Question
M8 无法建立 PendingQuestion

M8 更新的 Context
下一轮 M1 又读不回来
```

这些问题：

```text
必须通过真实横向链路
才能尽早发现。
```

---

# 3. 正式开发模式

采用：

```text
Runtime Skeleton
+
Vertical Slice
+
Incremental Expansion
```

三个层次。

---

# 4. Runtime Skeleton

先建立：

```text
M0
```

提供：

```text
主循环

统一 Contract

Registry

State Engine Interface

Event Bus

Trace

Error Handling
```

但不要一开始把全部业务逻辑写完。

---

# 5. Vertical Slice

一个 Vertical Slice 必须完整经过：

```text
Input
↓
Context
↓
Policy
↓
Understanding
↓
Planning
↓
Execution
↓
Validation
↓
Response
↓
Update
↓
Next Context
```

也就是：

```text
M1 → M8
```

完整闭环。

---

# 6. Incremental Expansion

第一条闭环跑通后，再：

```text
增加一个能力

增加一个Failure Case

增加一个Priority Case

增加一个Cross-turn Case
```

逐步扩展。

---

# 第一阶段
# Phase 0：工程基线冻结

实施代码之前，先确认以下文件已经存在：

```text
Runtime总体链路

八种智能规范

八种智能 × M0～M9映射

M0～M9详细方案

Core Schema Registry

Runtime Invariants

各核心Frozen设计
```

---

# 7. Phase 0 Gate

必须确认：

```text
Schema不再随便改名
Owner明确
Truth Boundary明确
M3～M8核心Contract冻结
Runtime Invariant冻结
```

首批 Contract 已收入 Canonical Registry V1.0。

达到：

```text
ARCHITECTURE_BASELINE_FROZEN = true
M0_RUNTIME_SKELETON = ALLOWED
```

后才允许进入 M0 编码。本文件本身不启动实现。

---

# 第二阶段
# Phase 1：M0 最小 Runtime Skeleton

目标不是一次写完所有 M0。

只实现：

```text
Runtime入口

Request Lifecycle

RuntimeContext容器

Module Interface

Registry

Trace ID

Error Boundary

Async Main Loop
```

---

# 8. Phase 1 需要真正落地的 Contract

至少实现：

```text
RuntimeInput
SafetyResult
RuntimeContext
UnderstandingState
PolicyDecision
ActionPlanDraft
ApprovedActionPlan
ExecutionResult
ValidatedResult
ResponsePlan
RuntimeResponse
UpdateResult
```

字段与枚举以 Canonical Registry 为准。禁止 `elder_id`、禁止歧义 `ActionPlan` 类型。

第一版可以只有核心字段。

---

# 9. 所有阶段先实现 Interface

例如：

```text
UnderstandingEngine

PolicyEngine

Planner

ExecutionEngine

ResultValidator

ResponseEngine

StateMemoryUpdater
```

---

# 10. 第一版全部允许 Stub

例如：

```text
UnderstandingEngine
→ Echo / Rule Stub

Planner
→ Fixed Plan Stub

Executor
→ Fake Tool Stub
```

目标：

```text
先让数据走完整条链。
```

---

# 11. Phase 1 E2E

输入：

```text
“你好”
```

能够完整走：

```text
RuntimeInput
↓
RuntimeContext
↓
UnderstandingState Stub
↓
PolicyDecision
↓
ActionPlan
↓
ExecutionResult
↓
ValidatedResult
↓
RuntimeResponse
↓
UpdateResult
```

即使只是：

```text
“你好。”
```

也算第一条 Runtime E2E。

---

# 12. Phase 1 Gate

必须满足：

```text
所有阶段可被调用

所有Contract能序列化

Trace链完整

异常不会击穿Runtime

M8输出能被下一轮M1读取
```

达到：

```text
RUNTIME_SKELETON_PASSED
```

---

# 第三阶段
# Phase 2：第一条真实业务 Vertical Slice —— Content Playback

第一条正式业务建议：

```text
内容播放
```

原因：

```text
风险低

业务清晰

有真实副作用

可以验证M5/M6

可以验证State

可以验证M8
```

---

# 13. 第一条用例

用户：

```text
“给我放段评书。”
```

---

# 14. M1 最小实现

支持：

```text
current_state

session

recent_turns

basic tool state
```

---

# 15. M2 最小实现

只实现：

```text
允许/禁止

当前State合法性

最基本Priority
```

---

# 16. M3 最小实现

识别：

```text
intent = PLAY_CONTENT

entity:
content_category = 评书
```

先使用：

```text
规则
+
LLM
```

均可。

---

# 17. M4 最小实现

输出：

```text
strategy = DIRECT_FULFILLMENT

action = PLAY_CONTENT

skill = ContentSkill
```

---

# 18. M5 最小实现

实现：

```text
ContentSkill

SearchContentTool Stub / Real

PlayTool Stub / Real
```

---

# 19. M6 最小实现

验证：

```text
内容是否找到

播放命令是否成功

Playback状态
```

---

# 20. M7 最小实现

输出：

```text
成功
失败
UNKNOWN
```

三种基本结果。

---

# 21. M8 最小实现

成功：

```text
State → S06

Conversation append

current content updated
```

失败：

```text
不进入 S06
```

---

# 22. Phase 2 必测 Case

```text
CONTENT-001
播放成功

CONTENT-002
内容不存在

CONTENT-003
播放Tool失败

CONTENT-004
播放Timeout

CONTENT-005
M6 UNKNOWN
```

---

# 23. Phase 2 Gate

要求：

```text
M3正确理解

M4正确计划

M5真实执行

M6不把Tool Success直接当Business Success

M7不乱说成功

M8只根据ValidatedResult更新State
```

达到：

```text
FIRST_VERTICAL_SLICE_PASSED
```

---

# 第四阶段
# Phase 3：补 Content 的跨轮与控制能力

继续扩：

```text
“换一个”

“暂停”

“继续”

“停吧”

“声音小一点”
```

---

# 24. 这一阶段重点验证

不是 Content 本身，而是：

```text
Context

Reference

Task Continuity

Control Action

State
```

---

# 25. 重点测试

```text
上一轮正在播放评书

下一轮：
“换一个”
```

M1：

```text
current playback context
```

M3：

```text
CONTROL_PLAYBACK
```

M4：

```text
CHANGE_TARGET
```

M5：

```text
stop / next / play
```

M8：

```text
current content updated
```

---

# 26. Phase 3 Gate

必须证明：

```text
Runtime不是单轮Pipeline

Context_t
可以真正影响
Understanding_t+1
```

达到：

```text
CROSS_TURN_RUNTIME_PASSED
```

---

# 第五阶段
# Phase 4：Companion Vertical Slice

接入：

```text
普通聊天

倾听

轻度情绪表达

安静陪伴

对话结束
```

---

# 27. 重点不再是 Tool

而是验证：

```text
M3 Need

M4 Dialogue Strategy

M7 ResponsePlan

M8 Interaction State
```

---

# 28. 核心 Case

```text
COMP-001
普通闲聊

COMP-002
用户表达想念女儿

COMP-003
用户只想倾诉

COMP-004
用户说“不想说了”

COMP-005
用户说“让我静静”

COMP-006
END Conversation
```

---

# 29. 重点 Gate

确保：

```text
Emotion != Action

Need影响Strategy

SILENCE是合法Response

END不会继续问

一次最多一个主要问题

quiet_until真正写入
```

达到：

```text
COMPANION_LOOP_PASSED
```

---

# 第六阶段
# Phase 5：Reminder Workflow

此阶段第一次正式引入：

```text
跨轮确定性 Workflow
```

---

# 30. 实现内容

```text
ReminderWorkflow

Scheduler

Reminder Task

WAITING_USER

Timeout

Retry Event
```

---

# 31. 普通提醒链

```text
REMINDER_DUE
↓
M2
↓
ReminderWorkflow
↓
M7提醒
↓
M8 Task WAITING_USER
```

---

# 32. 用户回应

例如：

```text
“知道了。”
```

需要：

```text
PendingQuestion / Active Task
→ M3 TASK_RESPONSE
→ Workflow continuation
```

---

# 33. 无回应

普通提醒：

```text
5 min
→ retry
→ expired
```

---

# 34. 用药/复测提醒

实现：

```text
3 min
→ retry
→ reminder_unanswered
→ notification
```

---

# 35. 这一阶段重点验证

```text
Runtime Event

Workflow

Task State

Timeout

Cross-turn

Scheduler

M8 Task Update
```

---

# 36. Phase 5 Gate

达到：

```text
DETERMINISTIC_WORKFLOW_PASSED
```

---

# 第七阶段
# Phase 6：Safety / Help Vertical Slice

到这里才正式进入高风险。

原因：

```text
Runtime
Workflow
Tool
Validation
State
Idempotency
```

都已经被低风险业务验证过。

---

# 37. 首先实现 HelpWorkflow

Case：

```text
“帮我叫个人。”
```

---

# 38. 重点实现

```text
PreSafetyGuard

Forced Workflow

Help Event

Notification Tool

Idempotency

Safety Lock

Notification Claim Ladder

Workflow WAITING
```

---

# 39. 必测 Case

```text
HELP-001
普通求助

HELP-002
明确紧急求助

HELP-003
播放中求助

HELP-004
Notification Success

HELP-005
Notification Timeout

HELP-006
Notification UNKNOWN

HELP-007
重复请求

HELP-008
Crash Recovery
```

---

# 40. 关键验证

必须证明：

```text
Planner不能覆盖Safety

播放被正确PREEMPT

通知不重复

Timeout不被当Success

M7不说“工作人员已经来了”

Safety Lock不能由LLM释放
```

---

# 41. Phase 6 Gate

达到：

```text
SAFETY_RUNTIME_PASSED
```

---

# 第八阶段
# Phase 7：Discomfort Workflow

在 Help 基础上扩：

```text
身体不适采集
```

---

# 42. 先做普通路径

例如：

```text
“不舒服。”
```

进入：

```text
DiscomfortWorkflow
```

逐字段采集。

---

# 43. 重点验证

```text
Task field

CONFIRMED / UNCONFIRMED

一轮一问

PendingQuestion

Task progression
```

---

# 44. 再接高风险分流

如果：

```text
胸痛
呼吸困难
明确危险信号
```

必须：

```text
跳过普通完整采集
→ Safety Workflow
```

---

# 45. Phase 7 Gate

证明：

```text
普通Workflow
和
Safety Override
可以共存。
```

达到：

```text
CARE_WORKFLOW_PASSED
```

---

# 第九阶段
# Phase 8：Emotion Support

现在再扩：

```text
普通情绪支持

高风险情绪
```

---

# 46. 普通情绪先做

验证：

```text
Emotion
Need
InteractionState
Strategy
Response
```

---

# 47. 再做高风险

进入：

```text
HighRiskEmotionWorkflow
```

而不是普通聊天。

---

# 48. 核心测试

```text
EMO-001
普通低落

EMO-002
孤独表达

EMO-003
不想建议

EMO-004
只想听

EMO-005
含糊风险

EMO-006
明确高风险
```

---

# 第十阶段
# Phase 9：Cognitive Interaction

接入：

```text
CognitiveSkill

QuestionBank

CognitiveTask
```

重点测试：

```text
跨轮问答

任务推进

中途退出

被Safety抢占
```

---

# 第十一阶段
# Phase 10：Memory Capability

这里才开始正式增强长期关系连续性。

注意：

```text
M8 Memory基础结构
应该更早存在
```

但完整：

```text
Long-Term Memory业务能力
```

可以现在再接。

---

# 49. 先做 Explicit Memory

例如：

```text
“记住我喜欢越剧。”
```

---

# 50. 再做 Memory Query

例如：

```text
“我女儿叫什么？”
```

---

# 51. 再做 Memory Correction

例如：

```text
“我刚才说错了，是小敏。”
```

---

# 52. 再做 Temporary Override

例如：

```text
“这几天不听京剧。”
```

---

# 53. 最后做 Emerging / Preference Drift

不要第一版就上复杂自动人格建模。

---

# 54. Phase 10 Gate

必须证明：

```text
Wrong-user = 0

Explicit Correction有效

Temporary Override不会毁掉Stable Memory

MODEL_INFERRED不会变Stable
```

达到：

```text
MEMORY_CONTINUITY_PASSED
```

---

# 第十二阶段
# Phase 11：Weather / News

最后接：

```text
External API能力
```

---

# 55. 重点不只是查询

还要验证：

```text
API Adapter

Freshness

Source

Timeout

Tool Truth

M6 Fact Validation
```

---

# 56. 必测

```text
WEATHER-001
当前天气成功

WEATHER-002
API Timeout

WEATHER-003
Location missing

WEATHER-004
Stale result

NEWS-001
新闻成功

NEWS-002
缺source

NEWS-003
旧新闻
```

---

# 第十三阶段
# Phase 12：357能力映射与 M9 扩展

等三级目录正式确定后，再做：

```text
357 Capability Mapping Matrix
```

不是现在。

届时每项映射：

```text
业务能力
→ M9模块
→ Implementation Type
→ Skill / Workflow
→ Tool / API
→ Content
→ E2E
→ Status
```

---

# 第十四阶段
# 每个 Vertical Slice 的统一实施模板

以后新增任何能力，都按：

```text
1. Definition
2. Contract
3. Stub
4. Happy Path
5. Failure Path
6. UNKNOWN Path
7. Cross-turn Path
8. Priority / Preemption Path
9. State / Memory Update
10. E2E Gate
```

---

# 57. 每个能力至少测试五类

```text
正常

失败

Timeout / UNKNOWN

上下文连续

抢占 / Policy
```

---

# 第十五阶段
# E2E 测试总体系

最终建立：

```text
E2E Runtime Eval Set
```

---

# 58. E2E-01 Runtime Skeleton

```text
输入
→ 回复
→ Update
```

---

# 59. E2E-02 Content Playback

```text
播放成功
```

---

# 60. E2E-03 Cross-turn Control

```text
播放
→ 换一个
```

---

# 61. E2E-04 Companion

```text
聊天
→ 倾听
→ 不追问
```

---

# 62. E2E-05 Quiet Presence

```text
“让我静静”
→ short ack
→ silence
→ cooldown
```

---

# 63. E2E-06 Reminder

```text
trigger
→ prompt
→ user response
→ task complete
```

---

# 64. E2E-07 Reminder Timeout

```text
无回应
→ retry
→ expired / notify
```

---

# 65. E2E-08 Help

```text
help
→ forced workflow
→ event
→ notification
```

---

# 66. E2E-09 Safety Preemption

```text
playback
→ help
→ PREEMPTED
```

---

# 67. E2E-10 Notification UNKNOWN

确保：

```text
UNKNOWN
从M5
一直保持到M7
```

---

# 68. E2E-11 Discomfort

```text
采集
→ pending question
→ next turn
```

---

# 69. E2E-12 High-risk Discomfort

```text
risk
→ bypass ordinary collection
```

---

# 70. E2E-13 Emotion

```text
emotion
→ need
→ strategy
→ response
```

---

# 71. E2E-14 High-risk Emotion

```text
high risk
→ safety workflow
```

---

# 72. E2E-15 Memory Continuity

```text
explicit memory
→ new session
→ retrieval
```

---

# 73. E2E-16 Memory Correction

```text
old value
→ explicit correction
→ old deprecated
→ new effective
```

---

# 74. E2E-17 Temporary Override

```text
stable preference
+
temporary avoid
```

---

# 75. E2E-18 Wrong-user Isolation

两个用户：

```text
Memory
Context
Task
```

绝不串。

---

# 76. E2E-19 Crash Recovery

关键 Workflow：

```text
执行中崩溃
→ checkpoint
→ resume
→ no duplicate side effect
```

---

# 77. E2E-20 External API Timeout

天气/新闻：

```text
Timeout
→ UNKNOWN / failure semantics
→ no hallucinated answer
```

---

# 第十六阶段
# 开发完成状态模型

不要再使用：

```text
“做完了”
```

这种模糊状态。

统一：

```text
DEFINED

DESIGNED

STUBBED

IMPLEMENTED

WIRED

UNIT_VERIFIED

INTEGRATION_VERIFIED

E2E_PASSED

RELEASE_READY
```

---

# 78. STUBBED

说明：

```text
链路存在
但依赖还是假实现。
```

---

# 79. IMPLEMENTED

说明：

```text
代码存在。
```

但还不代表：

```text
Runtime真的调用它。
```

---

# 80. WIRED

说明：

```text
真正进入主链。
```

---

# 81. UNIT_VERIFIED

模块测试通过。

---

# 82. INTEGRATION_VERIFIED

相邻阶段接口通过。

---

# 83. E2E_PASSED

完整链路通过。

---

# 84. RELEASE_READY

必须再满足：

```text
业务依赖

安全

权限

日志

监控

配置

真实环境
```

条件。

---

# 第十七阶段
# 每阶段开发规则

# 85. 先Contract

实现前明确：

```text
Input Schema

Output Schema

Error

Status
```

---

# 86. 再Stub

先验证：

```text
链路能走。
```

---

# 87. 再真实实现

然后替换：

```text
Stub
→ Real Implementation
```

---

# 88. 再Failure

不要只测 Happy Path。

---

# 89. 再Cross-turn

因为 Agent 系统真正的问题往往出在下一轮。

---

# 90. 再E2E Gate

不通过：

```text
不扩下一个高复杂能力。
```

---

# 第十八阶段
# 推荐的真实实施顺序总表

| 顺序 | 目标 | 主要验证 |
|---|---|---|
| 0 | 架构基线 | Contract / Invariant |
| 1 | M0最小骨架 | Runtime可运行 |
| 2 | Content Happy Path | M1–M8完整闭环 |
| 3 | Content Cross-turn | Context连续 |
| 4 | Companion | Strategy / Response |
| 5 | Reminder | Workflow / Timeout |
| 6 | Help | Safety / Preemption / Idempotency |
| 7 | Discomfort | Task / Safety分流 |
| 8 | Emotion | Need / Safety Upgrade |
| 9 | Cognitive | Cross-turn Activity |
| 10 | Memory | Long-term Continuity |
| 11 | Weather/News | External API Truth |
| 12 | 正式Capability Mapping | 全业务覆盖 |

---

# 第十九阶段
# 不推荐的实施方式

正式禁止：

```text
把M3全部写完
再写M4全部
再写M5全部
……
最后一次性联调
```

---

# 91. 原因

这种方式容易产生：

```text
纸面模块都完整
但链路不成立
```

最终大量返工。

---

# 92. 也不建议先做所有Skill

因为：

```text
没有Runtime E2E验证，
Skill越多，
返工面越大。
```

---

# 93. 也不建议第一条就做Safety

不是因为 Safety 不重要。

而是因为：

```text
Safety非常依赖
State
Workflow
Tool
Idempotency
Validation
Recovery
```

基础还没验证时直接做，定位问题会很困难。

---

# 94. 但Safety必须在正式用户试用前完成

正式固定：

```text
PoC第一条可以不是Safety

真实用户测试前
Safety Gate必须通过
```

---

# 第二十阶段
# 每个阶段的停止条件

一个 Phase 完成，不是看：

```text
代码量
```

而是看：

```text
目标E2E是否通过。
```

---

# 95. 例如 Content Phase 完成标准

不是：

```text
ContentSkill写完了。
```

而是：

```text
PLAY_CONTENT
从输入一路走到State更新
并覆盖成功/失败/UNKNOWN
```

---

# 96. Help Phase 完成标准

不是：

```text
HelpWorkflow代码存在。
```

而是：

```text
正常求助
抢占
Timeout
UNKNOWN
幂等
Crash Recovery
全部通过。
```

---

# 第二十一阶段
# 开发反馈闭环

每条 Vertical Slice 完成后需要回填：

```text
发现的Contract问题

发现的Invariant问题

发现的Missing Field

发现的Tool限制

发现的Validation证据缺口

发现的业务依赖缺口
```

---

# 97. 可以改设计，但必须受控

实施阶段发现设计问题是正常的。

但修改必须：

```text
Issue
↓
判断是否Breaking
↓
修改Core Schema / Frozen Spec
↓
Version
↓
Regression
```

不能直接：

```text
代码里临时加字段
文档不更新
```

---

# 第二十二阶段
# 最终 Runtime 完成标准

整个 Runtime Core 真正完成，需要证明：

```text
普通对话可以闭环

跨轮可以连续

Tool可以真实执行

执行结果可以验证

UNKNOWN可以保留

回复不越Truth Boundary

State可以可靠更新

Task可以跨轮推进

Memory可以安全连续

高风险可以强制接管

关键副作用具有幂等

Crash可以恢复

业务能力可以通过M9插件式扩展
```

---

# 结论

真正实施时，不应该：

```text
先把 M0～M8 每一层分别“做完整”
然后最后再联调。
```

正确方式是：

```text
先搭骨架
↓
选最简单业务
↓
M1～M8纵向贯通
↓
跑成功 / 失败 / UNKNOWN
↓
确认下一轮Context
↓
再扩第二条能力
↓
逐渐增加Workflow
↓
最后进入Safety、Memory和外部API复杂能力
```

也就是：

```text
设计按 M0～M9 分层，

实现按 Vertical Slice 推进。
```

这是本项目正式推荐的工程实施方式。

至此：

```text
M0–M9 渐进式实施与 E2E 验证计划 V1.0
=
FROZEN
```