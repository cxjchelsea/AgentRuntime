# 可复用 Agent Runtime 平台  
# Runtime 运行不变量与架构约束 V1.0

> **Phase 0 Fix**  
> 主链对象名称以 Canonical Registry 为准：`ApprovedActionPlan`、`UpdateResult`、`SafetyResult(phase=EARLY)`。  
> 禁止歧义 `ActionPlan`。禁止 `elder_id` 作为 Core 身份字段。  
> Core 状态只允许 `RuntimeControlState`。

> **平台化转换说明**  
> 本文已从单一业务 Agent 设计转换为 **可复用 Agent Runtime 平台**设计。除明确标记为 `Core` 的对象、接口、不变量和生命周期外，任何具体业务 Intent、Entity、Workflow、Skill、Tool、知识域、状态字段、规则、提示词或示例均视为 **Domain Package 示例**，不得硬编码进 Runtime Core。新项目应通过 Registry / Adapter / Plugin / Config 注入领域差异。
> 
> 平台固定边界：`Runtime Core` 尽量稳定；`Domain Extension` 插件化；`Business Package` 配置化；`Application` 负责产品装配。

---

# 0. 文档定位

本文件定义整个可复用 Agent Runtime 平台 Agent Runtime 的：

```text
运行不变量
架构硬约束
跨模块禁止事项
Truth Boundary
Safety Boundary
Memory Boundary
执行边界
```

本文件不是某一个阶段的实现方案。

它是：

```text
M0～M9
所有阶段必须共同遵守的最高层约束。
```

其目的不是说明：

> “每个模块具体怎么实现。”

而是固定：

> “无论以后采用什么模型、框架、Prompt、数据库、Tool、Skill 或 Workflow，这些原则都不能被破坏。”

---

# 1. 适用范围

本文件适用于：

```text
产品设计

软件架构

AI代码生成

人工编码

Cursor / Copilot开发

代码重构

Code Review

自动化测试

E2E测试

版本升级

Skill接入

Tool接入

Workflow接入

模型替换

Prompt优化
```

---

# 2. 最高级原则

整个系统必须始终遵守：

```text
模型输出
!=
运行时状态
!=
工具结果
!=
业务事实
!=
用户可见事实
```

进一步：

```text
用户输入
!=
用户真实意图

用户真实意图
!=
系统决策

系统决策
!=
系统执行结果

系统执行结果
!=
真实业务结果

真实业务结果
!=
最终用户表达

最终用户表达
!=
长期记忆
```

任何实现都不得压平这些层级。

---

# 第一部分
# 全局架构不变量

# 3. Runtime 主链不可绕过

正式主链固定为：

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
下一轮 RuntimeContext
```

M2 在 Understanding 之后再次聚合 Policy，输出 `PolicyDecision`。禁止使用歧义名称 `ActionPlan`。

任何模块不得直接跨越多个 Truth Boundary。

---

# 4. 禁止短路路径

明确禁止：

```text
M3 → Tool

M3 → Runtime State

M3 → Long-Term Memory

M4 → Tool

M4 → RuntimeResponse

M5 → Business Truth

M5 → 用户成功声明

M6 → Tool调用

M6 → State直接修改

M7 → ToolResult自由解释

M7 → Memory直接写入

M8 → 重新理解用户

M8 → 重新规划

M8 → 重新执行业务Tool
```

---

# 5. 模块职责唯一性

每个阶段必须有明确职责。

```text
M1
负责输入标准化和上下文构建

M2
负责安全、状态、优先级、抢占、Policy

M3
负责理解

M4
负责规划

M5
负责执行

M6
负责验证

M7
负责表达

M8
负责状态、上下文和Memory提交

M9
负责业务能力接入
```

禁止同一职责在多个模块重复实现。

---

# 6. 不允许隐藏第二套 Runtime

例如：

```text
某个Skill内部
又重新调用LLM：

理解用户
判断风险
重新规划
调用Tool
生成回复
```

这种实现等于：

```text
在Runtime里面
又偷偷建立第二套Runtime。
```

正式禁止。

---

# 第二部分
# 输入与上下文不变量

# 7. RuntimeInput 不是用户意图

必须保持：

```text
RuntimeInput.text
=
标准化输入文本
```

不能直接作为：

```text
Intent
Goal
Emotion
Risk
```

这些必须由后续阶段明确产生。

---

# 8. 原始输入与标准化输入分离

如果存在：

```text
raw_text
normalized_text
```

必须保留来源关系。

不得：

```text
标准化后覆盖原始输入，
导致无法审计。
```

---

# 9. Context 不得伪造

ContextBuilder 只能加载：

```text
真实存在的数据

已提交的状态

合法Memory

真实Task

真实Tool状态
```

如果数据源不可用：

```text
missing_context
或
UNAVAILABLE
```

不得：

```text
自动生成一个合理默认事实。
```

---

# 10. Memory unavailable != no memory

正式固定：

```text
Memory Service不可用
!=
该用户没有Memory
```

必须区分：

```text
UNAVAILABLE
NO_RESULT
```

---

# 11. 当前显式信息优先

上下文冲突优先级：

```text
当前用户明确表达
>
当前真实业务状态
>
近期已确认信息
>
稳定Long-Term Memory
>
旧历史信息
>
模型推断
```

---

# 第三部分
# Safety 与 Policy 不变量

# 12. Safety Authority 不属于 Planner

正式固定：

```text
M2
是安全与Policy最终权威。
```

M3 可以提供：

```text
RiskSignal
```

M4 可以提供：

```text
候选行为
```

但：

```text
最终安全处理决定
属于M2。
```

---

# 13. 高风险不得进入普通自由规划

如果：

```text
PreSafetyGuard
或
PostUnderstandingSafetyPolicy
```

判定：

```text
forced_workflow
```

则：

```text
普通Planner不得覆盖。
```

---

# 14. Planner 不得取消 Forced Workflow

正式禁止：

```text
forced_workflow = HelpWorkflow

Planner:
“我觉得先安慰用户比较自然。”
```

这种覆盖。

必须：

```text
Safety Override
```

优先执行。

---

# 15. Safety Lock 不能由 LLM 释放

正式固定：

```text
Safety Lock Release
只能由：

确定性Workflow
Policy Rule
State Rule
```

执行。

禁止：

```text
LLM判断“看起来已经没事了”
→ release lock
```

---

# 16. 高风险不能因为模型失败而降级成普通聊天

如果：

```text
Risk Model / Understanding Model不可用
```

仍需依据：

```text
规则
显式关键词
当前Safety Context
已有事件
```

进行保守处理。

不能：

```text
模型失败
→ 当作没有风险
```

---

# 17. Priority != Preemption

正式固定：

```text
更高优先级
!=
一定立即中断
```

Priority 负责排序。

Preemption 负责决定：

```text
INTERRUPT

DEFER

QUEUE

DROP
```

两者不得混为一套 if/else。

---

# 第四部分
# Understanding 不变量

# 18. M3 只负责理解

M3 输出：

```text
UnderstandingState
```

不能：

```text
调用Tool

改变State

写Memory

生成最终用户回复

决定最终Safety动作
```

---

# 19. Emotion != Risk

正式固定：

```text
情绪识别
!=
安全风险判断
```

例如：

```text
sadness
```

不等于：

```text
high_risk
```

---

# 20. Emotion != Diagnosis

不得从：

```text
孤独
低落
焦虑表达
```

直接推导：

```text
抑郁症
焦虑症
精神疾病
```

除非未来业务明确引入专业临床评估体系。

---

# 21. Need 不能被当作显式事实

例如 M3 推断：

```text
implicit_need = LISTENING
```

不能在后续写成：

```text
“用户明确要求倾听。”
```

必须保留：

```text
explicit
vs
inferred
```

---

# 22. 模型推断必须可降级为 UNKNOWN

任何高不确定信息都必须允许：

```text
UNKNOWN

UNCERTAIN

UNRESOLVED
```

禁止强制填值。

---

# 23. 指代无法解析时不得猜

例如：

> “帮我联系她。”

如果没有可靠指代目标：

```text
Reference.status = UNRESOLVED / AMBIGUOUS
```

M4 应考虑 Clarify。

不能直接选择：

```text
女儿
```

---

# 24. Understanding Evidence 不是 Business Evidence

正式区分：

```text
M3 Evidence
=
为什么这样理解用户

M6 Evidence
=
为什么认定现实事实成立
```

两者不得混用。

---

# 第五部分
# Planning 不变量

# 25. M4 不能重新理解用户

M4 输入已经包含：

```text
UnderstandingState
```

不能重新：

```text
读完整原始对话
然后产生另一套Intent / Emotion / Goal
```

如发现不足：

```text
CLARIFY
```

或：

```text
DEGRADED
```

---

# 26. Planner 不能发明 Capability

任何：

```text
Skill
Workflow
Tool
Action
```

必须来自 Registry。

禁止：

```text
Planner自由输出一个不存在的tool_name。
```

---

# 27. Planner 不得假设 Tool 成功

ActionPlan 中可以写：

```text
CALL_TOOL
```

不能写：

```text
Tool一定成功
```

---

# 28. Planner 不得把未来结果写成当前事实

禁止：

```text
“通知后工作人员会收到”
```

作为 Planner Truth。

Plan 只能表达：

```text
要做什么
```

不能表达：

```text
已经发生什么
```

---

# 29. Planner 短视距原则

普通 Agent Planning 默认：

```text
短视距
+
Receding Horizon
```

即：

```text
计划少量动作
→ 执行
→ 再理解
→ 再规划
```

禁止普通陪伴任务一开始生成长链自主计划。

---

# 30. Deterministic Workflow 除外

固定 Workflow：

```text
Help
Reminder
Discomfort
HighRiskEmotion
```

可以有明确多步骤。

但：

```text
Workflow步骤
不是Planner自由推理链。
```

---

# 31. WAIT / END / SILENCE 是合法行为

系统不应强迫 Agent：

```text
每轮必须说话

每轮必须追问

每轮必须推荐
```

以下行为合法：

```text
WAIT

END

SILENT_COMPANION
```

---

# 32. Need-first / Goal-first

情感陪伴场景必须保持：

```text
Goal
+
Need
+
Interaction State
```

优先。

禁止简单：

```text
Emotion → 固定Action
```

---

# 第六部分
# Execution 不变量

# 33. M5 只接受 ApprovedActionPlan

禁止：

```text
Draft Plan
直接进入Executor。
```

必须经过：

```text
Schema Validation
Capability Validation
Policy Re-check
```

---

# 34. Executor 不重新规划

M5 不能：

```text
觉得Plan不好
→ 自己换Skill

Tool不存在
→ 自己找另一个Tool

某一步失败
→ 自己重新决定业务Goal
```

若计划无法继续：

```text
按Fallback执行
或
返回Failure / Followup
```

---

# 35. Skill 不能成为第二个 Planner

Skill 可以：

```text
业务参数转换
资源选择
调用Tool
有限业务逻辑
```

不能：

```text
重新理解用户
选择新的Strategy
改变Primary Goal
```

---

# 36. Workflow 不得绕开 Policy

即使 Workflow 是确定性的：

```text
也必须受 State / Permission / Policy 约束。
```

---

# 37. Tool 不能决定自己是否应该被调用

Tool 只能：

```text
接受明确参数
执行动作
返回真实结果
```

不能：

```text
判断用户到底想不想做这个动作
```

---

# 38. Tool Result 必须真实

禁止：

```text
Tool FAILED
→ Skill改成SUCCESS

Tool TIMEOUT
→ Executor假定SUCCESS
```

---

# 39. Timeout != Failure != Success

正式固定：

```text
TIMEOUT
```

必须作为独立状态。

因为：

```text
Timeout
通常意味着“无法确认”
```

而不是必然：

```text
失败
```

---

# 40. UNKNOWN External State 合法

例如：

```text
通知调用超时
```

无法确认：

```text
到底发送成功还是失败
```

必须保留：

```text
UNKNOWN
```

禁止强制二值化。

---

# 41. Retry 必须受限制

正式禁止：

```text
所有失败自动Retry
```

Retry 必须同时检查：

```text
Error Type

Idempotency

Side Effect Level

Max Attempts
```

---

# 42. Retry 必须有硬上限

禁止：

```text
无限重试。
```

---

# 43. 高副作用 Tool 不得无脑重试

例如：

```text
send_notification
create_help_event
update_reminder
```

必须优先保证：

```text
Idempotency
```

---

# 44. 关键 Side Effect 必须支持 Idempotency

包括至少：

```text
求助事件创建

工作人员通知

提醒状态修改

关键个人记录
```

---

# 45. 已完成副作用不能假装撤销

例如：

```text
通知已经发送
```

之后：

```text
用户取消
```

只能停止：

```text
后续步骤
```

不能把历史改成：

```text
没发送
```

---

# 46. PREEMPTED != FAILED

如果业务因为：

```text
更高优先级事件
```

被终止：

```text
PREEMPTED
```

必须单独记录。

---

# 第七部分
# Validation 不变量

# 47. Execution Success != Business Success

这是 M6 最核心不变量。

正式固定：

```text
M5 SUCCESS
不能自动生成
M6 SUCCESS
```

---

# 48. Evidence First

所有 VerifiedFact 必须：

```text
有Evidence。
```

正式固定：

```text
No Evidence
=
No Verified Fact
```

---

# 49. Missing Evidence != Failure

如果缺少证据：

```text
UNKNOWN
或
NOT_VALIDATED
```

而不是：

```text
FAILED
```

---

# 50. Failure 必须有反向证据

只有明确证明：

```text
目标没有完成
```

才能：

```text
NOT_COMPLETED / FAILED
```

---

# 51. UNKNOWN 是正式状态

正式支持：

```text
UNKNOWN
```

且：

```text
UNKNOWN
不得被后续模块偷偷升级为SUCCESS。
```

---

# 52. WAITING != UNKNOWN

```text
WAITING
=
知道流程正在合法等待

UNKNOWN
=
不知道当前真实状态
```

必须严格分离。

---

# 53. 冲突证据不得静默忽略

出现：

```text
Evidence A != Evidence B
```

必须：

```text
Conflict Detection
```

不能：

```text
挑一个“更方便”的值。
```

---

# 54. 未解决冲突不得生成 VerifiedFact

如果：

```text
resolution_status = UNRESOLVED
```

最终：

```text
Fact = UNKNOWN
```

---

# 55. Planner 预期不是 Evidence

正式禁止：

```text
ActionPlan中的completion_condition
```

被拿来证明：

```text
现实已经完成。
```

---

# 56. Tool SUCCESS 的语义必须显式定义

每个 Tool 必须具有：

```text
success_semantics
```

说明：

```text
SUCCESS
到底证明到哪一级。
```

---

# 57. 不允许跨 Claim Level

例如通知：

```text
请求已接受
```

不能升级为：

```text
已送达
已确认
正在处理
```

---

# 第八部分
# Response 不变量

# 58. M7 不重新判断事实

正式固定：

```text
M7只消费ValidatedResult。
```

不得：

```text
读取ToolResult后自由推理。
```

---

# 59. Truth Monotonicity

正式固定：

```text
最终回复确定性
<=
ValidatedResult确定性
```

---

# 60. UNKNOWN 不得被语言柔化成“应该成功”

禁止：

```text
“应该已经通知到了。”

“应该没问题。”

“大概已经处理好了。”
```

如果 M6 是：

```text
UNKNOWN
```

---

# 61. Forbidden Claim 必须强制拦截

所有生成路径：

```text
Template
LLM
Hybrid
Fallback
```

都必须遵守：

```text
forbidden_claims
```

---

# 62. Required Qualifier 不能消失

例如：

```text
NOT_CONFIRMED
```

M7 必须保留该不确定语义。

---

# 63. M7 不能新增未来承诺

禁止：

```text
“我马上再帮您联系一次。”
```

除非真实 ActionPlan 中有对应动作。

---

# 64. 第三方未来行为不得虚构

禁止：

```text
“工作人员马上来。”

“家属很快就到了。”
```

除非有明确真实 Evidence。

---

# 65. Empathy != Fact Validation

系统可以：

```text
回应感受
```

不能：

```text
替用户证明未经验证的外部事实。
```

---

# 66. Emotion UNKNOWN 时不得强行共情标签

M3 如果：

```text
emotion = UNKNOWN
```

M7 不得：

```text
“您一定很难过。”
```

---

# 67. SILENCE 是合法输出

正式固定：

```text
SILENCE
```

可以作为 RuntimeResponse。

---

# 68. END 后不得重新打开对话

如果 Planner：

```text
END
```

M7 不得最后问：

```text
“您还想聊点什么吗？”
```

---

# 69. 普通一轮最多一个主要问题

默认：

```text
max_questions = 1
```

特殊 Workflow 除外，但仍遵循：

```text
一轮一问。
```

---

# 第九部分
# State Update 不变量

# 70. State Commit 必须来自验证事实

正式链：

```text
ExecutionResult
↓
ValidatedResult
↓
State Recommendation
↓
State Engine
↓
State Commit
```

禁止：

```text
ToolResult
→ State Commit
```

---

# 71. ActionPlan StateIntent != State

Planner 可以：

```text
希望进入 S06
```

但只有真实播放验证后：

```text
才能进入S06。
```

---

# 72. M6 UNKNOWN 不得进入Success State

正式固定。

---

# 73. State Transition 必须合法

不得：

```text
任何模块直接修改 current_state
```

必须经过：

```text
StateEngine.validate_transition()
```

---

# 74. Safety State 优先于普通业务状态

当存在：

```text
Safety Lock
```

普通 Task / Playback 不得覆盖安全状态。

---

# 75. Resume 只能依据 Resume Policy

禁止：

```text
中断结束
→ 自动恢复所有旧业务
```

例如：

```text
播放被求助打断
```

明确：

```text
不自动恢复。
```

---

# 第十部分
# Memory 不变量

# 76. MemoryCandidate != MemoryRecord

正式固定：

```text
候选
不能自动持久化。
```

---

# 77. 一次表达 != 长期记忆

例如：

```text
“今天不想听京剧。”
```

不能自动写成：

```text
长期不喜欢京剧。
```

---

# 78. 一次行为 != 稳定偏好

一次点击 / 一次播放 / 一次选择：

```text
不能直接创建STABLE Preference。
```

---

# 79. 一次拒绝 != 长期禁用

一次：

```text
“不用了。”
```

只能优先影响：

```text
Recent Context
```

---

# 80. MODEL_INFERRED 不得直接进入 STABLE Memory

正式固定。

---

# 81. 情绪默认不进入长期人格档案

例如：

```text
今天孤独
```

默认：

```text
Session / Recent
```

不能：

```text
Long-Term:
用户是孤独的人
```

---

# 82. 用户明确修正优先

例如：

```text
“我刚才说错了。”
```

当前明确修正优先于历史 Memory。

---

# 83. Temporary Override != Stable Preference Change

例如：

```text
“这几天不想听京剧。”
```

应：

```text
Temporary Override
```

而不是直接：

```text
Deprecated stable preference
```

---

# 84. Preference Drift 必须有持续证据

长期偏好变化需要：

```text
明确长期表达
或
持续稳定证据
```

---

# 85. Wrong-user Memory Rate 必须为 0

任何 Memory：

```text
必须带user_scope。
```

跨用户污染属于：

```text
严重架构缺陷。
```

---

# 86. Unbound Mode 默认不能写个人长期Memory

如果：

```text
identity_status = UNBOUND
```

默认：

```text
禁止个人Long-Term Memory Write
```

除非以后有明确产品规则。

---

# 87. Memory unavailable 不得伪造

如果 Memory Service 失败：

```text
不得让LLM“模拟记得”用户。
```

---

# 88. Memory Explicit Reference 需要授权

只有：

```text
M4 usage_mode = REFERENCE_EXPLICITLY
```

M7 才可显式：

```text
“您之前说过……”
```

---

# 89. Memory 写入追求 Precision > Recall

正式固定：

```text
宁可暂时少记，
不要长期记错。
```

---

# 第十一部分
# Conversation 与 Task 不变量

# 90. PendingQuestion 只记录实际问出的内容

如果：

```text
M4计划问
```

但 M7 最终没有问：

```text
不能创建 PendingQuestion。
```

---

# 91. Conversation History 保存实际输出

不能保存：

```text
Response Draft
```

作为实际对话。

必须保存：

```text
RuntimeResponse
```

---

# 92. Task关键字段区分 CONFIRMED / UNCONFIRMED

模型推断字段：

```text
不得默认作为Workflow确定字段。
```

---

# 93. Task推进依赖已确认输入

关键安全 / 确定性 Workflow：

```text
优先使用CONFIRMED Field
```

---

# 94. Topic != Long-Term Memory

当前聊什么：

```text
默认属于Context
```

不是永久 Memory。

---

# 95. Rolling Summary 是 Secondary Source

Summary 不能覆盖：

```text
当前用户明确表达

已确认业务状态

正式Memory事实
```

---

# 第十二部分
# 主动性不变量

# 96. M2 决定“能不能主动”

M4 决定：

```text
值不值得主动。
```

两者必须分开。

---

# 97. Planner不能绕过主动性Policy

例如：

```text
quiet_period
daily limit
busy state
```

M4不能因为：

```text
“这个话题很合适”
```

而主动。

---

# 98. 实际主动发生后才计数

只有：

```text
RuntimeResponse真的输出
```

才更新：

```text
active_interaction_count
```

---

# 99. 一次拒绝只影响近期主动性

除非用户明确表达：

```text
长期不希望某类主动交互。
```

---

# 100. 安静陪伴 Cooldown 必须真正生效

写入：

```text
quiet_until
```

后，后续主动策略必须读取。

---

# 第十三部分
# 业务能力接入不变量

# 101. M9 不能修改 Runtime Core

新增业务原则上：

```text
新增Capability
Skill
Workflow
Tool
Content
Config
ValidationRule
ResponseRule
```

而不是：

```text
修改M3-M8职责。
```

---

# 102. 357 类业务内容 != 357 个Intent

正式固定。

---

# 103. 新内容优先数据化

例如：

```text
新增昆曲
```

优先：

```text
Content Taxonomy
```

不是：

```text
新Agent
新Intent
新Planner
```

---

# 104. 高约束任务优先 Workflow

例如：

```text
求助
不适采集
提醒
```

不应由自由 Agent Planner 控制内部步骤。

---

# 105. 真实副作用必须经过 Tool

任何：

```text
通知
播放
写数据库
调API
创建事件
```

不能仅靠模型文本宣称完成。

---

# 106. Capability Exists != Implemented

正式固定：

```text
DEFINED
!=
IMPLEMENTED
!=
WIRED
!=
VERIFIED
!=
E2E_PASSED
!=
RELEASE_READY
```

---

# 第十四部分
# 工程与可观测性不变量

# 107. 全链必须可追踪

至少：

```text
trace_id
request_id
session_id
plan_id
execution_id
tool_call_id
validation_id
response_id
update_id
```

---

# 108. 关键对象必须版本化

至少：

```text
Schema

Prompt

Model

Policy

Rule

Skill

Workflow

Tool
```

---

# 109. 生产行为不能依赖不可追踪Prompt

所有关键 Prompt 必须：

```text
有version
可回滚
可关联Eval
```

---

# 110. Trace 不等于保存所有敏感原始数据

正式固定：

```text
可追踪
!=
无限记录
```

遵守：

```text
最小必要原则。
```

---

# 111. 默认不保存完整音频

若无明确需求：

```text
不持久化全量用户音频。
```

---

# 112. 敏感数据不得写普通 Debug Log

例如：

```text
健康信息
个人关系细节
完整对话
Memory原文
```

应按数据治理规则处理。

---

# 第十五部分
# 降级不变量

# 113. LLM失败不得使Safety失效

正式固定。

---

# 114. M3失败

可以：

```text
Rule / Context Fast Path
+
UNKNOWN
```

不能：

```text
随便猜Intent。
```

---

# 115. M4失败

可以：

```text
Deterministic / Degraded Planner
```

禁止：

```text
自由调用Tool。
```

---

# 116. M5失败

必须：

```text
真实返回失败 / Timeout / Unknown
```

不能假装成功。

---

# 117. M6失败

必须：

```text
NOT_VALIDATED / UNKNOWN
```

不能：

```text
默认Business Success。
```

---

# 118. M7失败

允许：

```text
Safe Template Fallback
```

但：

```text
不得突破Claim Boundary。
```

---

# 119. M8 Memory失败

不能：

```text
导致关键安全副作用重放。
```

---

# 第十六部分
# 架构禁止模式

以下实现模式正式列为：

```text
Architecture Anti-Patterns
```

---

# 120. 超大万能 Prompt

禁止：

```text
一次Prompt同时：

理解用户
判断风险
查Memory
规划
调用Tool
判断结果
生成回复
更新Memory
```

---

# 121. LLM直接控制状态机

禁止：

```text
model_output.next_state
→ 直接State Commit
```

---

# 122. LLM直接生成Tool名称

禁止：

```text
自由文本Tool Name
```

必须来自 Registry。

---

# 123. Tool调用结果直接拼进用户回复

禁止：

```text
ToolResult
→ LLM自由回答
```

必须：

```text
ToolResult
→ M6
→ ClaimPolicy
→ M7
```

---

# 124. 所有历史全部塞Prompt

禁止：

```text
无限Conversation History
+
全部Memory
```

直接输入每轮。

必须使用：

```text
Context Selection
+
Summary
+
Relevant Memory Retrieval
```

---

# 125. 所有用户信息自动记忆

正式禁止。

---

# 126. 所有情绪自动安慰

正式禁止。

需要：

```text
Need
Goal
Interaction State
```

共同决策。

---

# 127. 所有不确定性都追问

正式禁止。

只问：

```text
阻塞下一步的重要不确定点。
```

---

# 128. 所有Tool失败都自动Retry

正式禁止。

---

# 129. 所有高优先级事件都立即打断

正式禁止。

需经过：

```text
Preemption Policy
```

---

# 130. 所有主动机会都执行

正式禁止。

主动性：

```text
Precision > Recall
```

---

# 第十七部分
# 运行不变量总表

以下可作为开发和 Code Review 的最高级检查清单。

| 编号 | 不变量 |
|---|---|
| INV-001 | 模型输出 != Runtime State |
| INV-002 | Tool Result != Business Truth |
| INV-003 | Execution Success != Business Success |
| INV-004 | Missing Evidence != Failure |
| INV-005 | Timeout != Success |
| INV-006 | UNKNOWN 不得被升级成 Success |
| INV-007 | WAITING != UNKNOWN |
| INV-008 | Planner 不得覆盖 forced_workflow |
| INV-009 | Safety Lock 不得由 LLM 释放 |
| INV-010 | M3 不得调用 Tool |
| INV-011 | M4 不得执行 Tool |
| INV-012 | M5 不得重新规划 |
| INV-013 | M6 不得重新执行 Tool |
| INV-014 | M7 不得重新判断业务事实 |
| INV-015 | M8 不得重新理解或规划 |
| INV-016 | Forbidden Claim 不得输出 |
| INV-017 | Response Certainty <= Validated Certainty |
| INV-018 | MemoryCandidate != MemoryRecord |
| INV-019 | 一次行为 != Stable Preference |
| INV-020 | 一次拒绝 != 长期偏好 |
| INV-021 | MODEL_INFERRED 不得直接成为 Stable Memory |
| INV-022 | Wrong-user Memory 必须为 0 |
| INV-023 | PendingQuestion 只来自实际提问 |
| INV-024 | State Commit 必须经过 State Engine |
| INV-025 | Critical Side Effect 必须考虑 Idempotency |
| INV-026 | PREEMPTED != FAILED |
| INV-027 | Capability 不存在时 Executor 不得自行替换 |
| INV-028 | Tool SUCCESS 必须有明确 success_semantics |
| INV-029 | 用户可见事实必须可追溯到 VerifiedFact |
| INV-030 | 新业务原则上不得修改 Runtime Core |

---

# 第十八部分
# AI / Cursor 编码使用规则

以后给 AI 编码时，建议每次提示词都明确加入：

```text
你必须遵守《Runtime运行不变量与架构约束》。

如果当前任务与该规范冲突：

不得通过绕过规范完成需求。

必须指出冲突，
并选择符合规范的实现方式。
```

---

# 131. AI 不得因为“实现更简单”破坏边界

例如：

```text
为了少写一个M6
直接让M5返回最终回复
```

禁止。

---

# 132. AI 不得因为“测试都过了”宣称违反层级的实现正确

测试通过只能证明：

```text
当前测试覆盖的行为通过。
```

不能覆盖：

```text
Architecture Invariant。
```

---

# 133. Code Review 必须同时检查

```text
Functional Correctness

Contract Compliance

Invariant Compliance
```

不能只看：

```text
功能能不能跑。
```

---

# 第十九部分
# Gate

## Gate INV-01

不存在跨层直接调用。

## Gate INV-02

所有真实副作用经过 Tool。

## Gate INV-03

所有 Tool Result 经 M6 后再进入用户事实。

## Gate INV-04

所有 State Commit 经 State Engine。

## Gate INV-05

所有 Long-Term Memory Write 经 Memory Policy。

## Gate INV-06

所有高风险强制路径无法被普通 Planner 覆盖。

## Gate INV-07

UNKNOWN 在所有下游保持 UNKNOWN 语义。

## Gate INV-08

Forbidden Claim 无法通过任何 Response Path。

## Gate INV-09

Critical Side Effect 重试具备 Idempotency。

## Gate INV-10

Wrong-user Context / Memory 不会进入当前会话。

## Gate INV-11

M8 只提交真实发生和已验证的数据。

## Gate INV-12

所有业务模块通过 M9 接入，不建立独立旁路 Runtime。

---

# 第二十部分
# 本文档与其他设计文件的优先级

正式建议采用以下优先级：

```text
第一优先级：
Runtime Invariants & Architectural Constraints

第二优先级：
Agent Runtime Core Contract Canonical Registry V1.0
（首批 Core Contract 唯一正式来源）

第三优先级：
Core Schema Registry（其余对象）

第四优先级：
M0～M9 Frozen Core设计

第五优先级：
各阶段详细实现方案

第六优先级：
具体Skill / Workflow / Tool实现
```

如果发生冲突：

```text
高优先级文件优先。
```

---

# 结论

本文件最终固定的是：

```text
这个Agent可以不断增加能力，

可以换模型，

可以换Prompt，

可以换数据库，

可以换框架，

可以增加Skill，

可以增加Workflow，

可以增加Tool，

可以增加业务模块，

但是：

理解、决策、执行、事实、表达、状态、记忆
这几个边界不能被重新混在一起。
```

最终架构原则可以压缩为：

```text
模型负责推理，
Runtime负责约束。

Planner负责决定，
Executor负责执行。

Tool负责真实动作，
Validator负责确认事实。

Response负责表达，
Updater负责沉淀。

Safety不让系统乱做，
Validation不让系统乱说，
Memory Policy不让系统乱记。
```

至此：

```text
Runtime 运行不变量与架构约束 V1.0
=
FROZEN
```