# 可复用 Agent Runtime 平台  
# M2 Safety / State / Policy 详细实现方案 V2.0

> **Phase 0 Fix**  
> 首批 Core Contract 以 Canonical Registry V1.0 为唯一正式来源。  
> `SafetyResult` 是唯一 Schema，用 `phase=EARLY|DEEP` 区分。  
> Core 状态机只允许 `RuntimeControlState`。S06–S11 等业务状态降为 Domain Example，进入 DomainState。  
> `PolicyDecision` 使用 `reason_codes[]` 与 `interrupt_current_task`。

> **平台化转换说明**  
> 本文已从单一业务 Agent 设计转换为 **可复用 Agent Runtime 平台**设计。除明确标记为 `Core` 的对象、接口、不变量和生命周期外，任何具体业务 Intent、Entity、Workflow、Skill、Tool、知识域、状态字段、规则、提示词或示例均视为 **Domain Package 示例**，不得硬编码进 Runtime Core。新项目应通过 Registry / Adapter / Plugin / Config 注入领域差异。
> 
> 平台固定边界：`Runtime Core` 尽量稳定；`Domain Extension` 插件化；`Business Package` 配置化；`Application` 负责产品装配。

> 本版本为 M2 V1.0 的结构化重整版。  
> 保留前序 M2 中已经确定的 Safety Guard、状态机、优先级、抢占、Policy、Safety Lock、Event Queue、Hard Rule / Soft Policy、Conflict Resolver、异常降级、PoC、Gate、交付物等全部内容，并按照统一 22 项实现方案模板重新组织。

---


## 平台扩展补充：Safety Core 与 Domain Safety

M2 Core 固定优先级、抢占、强制 Workflow、禁止动作、Policy Re-check 等机制；具体“什么条件属于高风险”由 Domain Rule Package 定义。医疗、金融、设备控制、普通内容 Agent 可以拥有完全不同的 Domain Safety Policy，但必须复用同一 M2 决策契约。

# 01. 阶段定位

M2 是整个 Agent Runtime 的：

```text
Safety / State / Policy
```

确定性控制层。

M1 解决：

```text
当前发生了什么？
```

M2 解决：

```text
当前系统处于什么状态？

当前事件允许做什么？

哪些事情必须做？

哪些事情绝对不能做？

哪个业务可以抢占哪个业务？

哪些场景必须进入确定性 Workflow，
不能交给 Agent Planner 自由判断？
```

因此 M2 可以概括为：

```text
Safety Guard
+
State Machine
+
Priority Engine
+
Preemption Engine
+
Policy Engine
```

M2 的核心不是：

```text
让机器人更有创造力
```

而是：

```text
让 Agent 的智能始终运行在可控边界之内
```

---

# 02. 阶段目标与八种智能映射

## 2.1 M2 总体目标

M2 最终需要建立：

```text
安全识别机制

+

状态机

+

运行时优先级

+

业务抢占机制

+

强制 Workflow 路由

+

行为允许 / 禁止规则

+

主动行为约束

+

超时与确认规则

+

Policy 冲突解决机制
```

---

## 2.2 与八种智能的关系

M2 核心承担：

```text
自我约束智能
```

同时支撑：

```text
情绪理解智能
对话策略智能
主动性智能
```

映射如下：

| 智能能力 | M2作用 |
|---|---|
| 语义理解智能 | 不直接实现 |
| 上下文智能 | 使用 M1 RuntimeContext 作为判断依据 |
| 关系连续性智能 | 提供隐私与数据边界 |
| 情绪理解智能 | 对高风险情绪与普通情绪施加不同处理边界 |
| 隐含需求推断智能 | 不直接实现 |
| 对话策略智能 | 限制 M4 可以选择的 Action Space |
| 主动性智能 | 控制主动问候、提醒等可执行条件 |
| 自我约束智能 | M2 核心实现阶段 |

因此：

```text
M2
=
“机器人知道什么事情不能乱做”
```

---

# 03. 职责边界

## 3.1 M2 负责

M2 必须负责：

```text
Early Safety Guard

Safety Re-evaluation

State Machine

State Transition

Priority Model

Priority Comparison

Preemption

Resume Policy

Safety Lock

Policy Engine

Policy Registry

Policy Conflict Resolver

Confirmation Policy

Timeout Policy

Active Interaction Policy

Reminder Policy

Privacy Hard Rules

Tool Truth Constraints
```

---

## 3.2 M2 不负责

M2 不负责：

```text
复杂语义理解

隐含情绪解释

隐含需求推断

普通情况下最自然的策略选择

具体 Tool 执行

Tool 结果真实性校验细节

最终回复生成

Memory 写入
```

这些分别属于：

```text
M3
M4
M5
M6
M7
M8
```

---

## 3.3 M2 与 M4 的边界

M2 回答：

```text
允许做什么？
禁止做什么？
是否必须走某个 Workflow？
```

M4 回答：

```text
在允许范围内，
下一步最适合做什么？
```

因此：

```text
Policy
>
Planner
```

不能：

```text
Planner 自己决定是否遵守 Policy
```

---

# 04. 前置依赖与外部依赖

## 4.1 前置阶段依赖

M2 依赖 M0 提供：

```text
Runtime Engine

SafetyResult Schema

PolicyDecision Schema

StateUpdate Schema

RuntimeEvent

Registry

Trace

Error / Fallback
```

M2 依赖 M1 提供：

```text
RuntimeContext

Current State Context

Task Context

Time Context

Tool Context

Safety Context

Interaction Context
```

---

## 4.2 需求规则依赖

当前用户端需求已经明确：

- S00～S11、S90 状态；
- 求助、高风险不适、高风险情绪为最高运行时优先级；
- 用药 / 复测提醒高于普通提醒；
- 普通提醒高于陪伴、播放、认知、主动问候；
- 求助过程中不能被普通播放、闲聊、领域任务交互或主动问候抢占；
- 通知结果必须来自真实接口；
- 高风险事件必须进入安全链路。

M2 必须把这些文字要求正式变成可执行规则。

---

## 4.3 外部依赖

M2 本身不应强依赖具体 LLM，但可能依赖：

```text
Rule Store

Safety Rule Registry

State Store

Task Store

Event Queue

Time Service

Policy Config

Notification Capability Metadata
```

Safety 的复杂语义信号可以来自 M3，但最终约束逻辑仍属于 M2。

---

# 05. 输入

M2 的主要输入包括：

```text
RuntimeInput

RuntimeContext

Early Safety Evidence

UnderstandingState

CurrentState

ActiveTask

RuntimeEvent
```

注意：

M2 会出现两次主要判断时点。

---

## 5.1 Early Safety 输入

在 M3 之前：

```text
RuntimeInput
+
有限 Context
```

用于识别明显高风险事件。

---

## 5.2 Deep Safety / Policy 输入

M3 之后：

```text
RuntimeContext
+
UnderstandingState
+
Early Safety Result
```

用于完成更完整的：

```text
Safety Re-evaluation
+
Policy Decision
```

---

# 06. 输出

M2 输出至少包括：

```text
SafetyResult

StateDecision

PriorityDecision

PreemptionDecision

PolicyDecision
```

这些共同构成：

```text
RuntimeConstraint
```

供 M4 / M5 / M8 使用。

---

# 07. 核心数据结构

# 7.1 SafetyResult

建议：

```text
SafetyResult

schema_version
safety_result_id
request_id
phase                         EARLY | DEEP
risk_detected
risk_level
interrupt_current_task
allowed_to_continue_normal_flow
safety_lock_required
reason_codes[]
created_at

risk_types[]
matched_rules[]
evidence
confidence
force_workflow
requires_immediate_action
restricted_actions[]
```

`EarlySafetyResult` / `DeepSafetyResult` 不是独立 Schema。

---

# 7.2 StateDefinition

建议：

```text
StateDefinition

state_id

name

allowed_inputs

allowed_transitions

interruptible

priority

entry_action

exit_action

timeout

timeout_action
```

---

# 7.3 StateTransition

```text
StateTransition

from_state

event

condition

to_state

action

priority

resume_policy
```

---

# 7.4 PriorityDecision

```text
PriorityDecision

incoming_priority

current_priority

higher_than_current

can_interrupt

should_defer

should_queue

should_drop

reason
```

---

# 7.5 PreemptionDecision

```text
PreemptionDecision

interrupt

current_business

incoming_event

on_interrupt

cleanup_policy

resume_policy

deferred_events

reason
```

---

# 7.6 PolicyDecision

建议：

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

forced_action
forced_workflow
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

`interrupt_required` / 标量 `reason` 已失效。

---

# 7.7 PolicyViolation

建议：

```text
PolicyViolation

violation_type

source

severity

blocked_action

reason_code

fallback
```

---

# 7.8 RuntimeConstraint

可以在 M2 内部聚合成：

```text
RuntimeConstraint

safety_result

state_decision

priority_decision

preemption_decision

policy_decision
```

---

# 08. 数据来源、存储与生命周期

## 8.1 State 生命周期

`current_state` 属于：

```text
Runtime Persistent State
```

不能只存在于 LLM Prompt。

至少需要持久保存：

```text
current_state

previous_state

entered_at

active_business

active_workflow
```

---

## 8.2 Safety Lock 生命周期

进入关键安全 Workflow 后：

```text
safety_lock = true
```

直到：

```text
SafetyWorkflow 正式结束
```

才能释放。

Safety Lock 不允许因为：

```text
普通会话超时
普通 STOP
LLM 回复结束
```

自动清除。

---

## 8.3 Priority 生命周期

优先级不是永久属性。

它取决于：

```text
当前 Event
当前 Active Task
当前 Business
```

例如：

```text
Medication Reminder
```

事件处理结束后，该高优先级上下文也应结束。

---

## 8.4 Pending Safety Event

安全相关事件需要持久化：

```text
event_id

event_type

created_at

status

notify_status

active_workflow
```

避免进程重启导致安全流程丢失。

---

## 8.5 Policy Decision 生命周期

通常：

```text
Turn-Level
```

只对当前 ActionPlan 有效。

新一轮输入需要重新计算。

---

# 09. 内部组件

建议 M2 包括：

```text
SafetyGuard

SafetyRuleEngine

SafetyReEvaluator

StateMachine

StateStore

PriorityEngine

PreemptionEngine

PolicyEngine

PolicyRegistry

PolicyConflictResolver

PolicyValidator

SafetyLockManager

EventQueue

TimeoutManager

ConfirmationManager
```

---

## 9.1 Policy 子模块

建议拆成：

```text
SafetyPolicy

StatePolicy

PriorityPolicy

InterruptionPolicy

ActiveInteractionPolicy

ReminderPolicy

PrivacyPolicy

ResponseTruthPolicy
```

---

# 10. 运行时实现主流程

M2 的真正 Runtime Algorithm 建议固定为双阶段结构。

```text
RuntimeInput
    ↓
① Early Safety Guard
    ↓
SafetyResult(preliminary)
    ↓
M1 Context
    ↓
M3 Understanding
    ↓
② Safety Re-evaluation
    ↓
③ State Validation
    ↓
④ Priority Evaluation
    ↓
⑤ Preemption Evaluation
    ↓
⑥ Policy Aggregation
    ↓
⑦ Policy Conflict Resolution
    ↓
⑧ Final PolicyDecision
    ↓
M4 Planner
    ↓
⑨ Planner Output Policy Check
    ↓
允许
→ M5 Execution

拒绝
→ Forced Workflow / Replan / Fallback
```

---

## 10.1 伪代码

```python
async def evaluate_runtime_policy(
    runtime_input,
    runtime_context,
    understanding_state
):
    early_safety = safety_guard.check_early(
        runtime_input,
        runtime_context
    )

    deep_safety = safety_re_evaluator.evaluate(
        runtime_input,
        runtime_context,
        understanding_state,
        early_safety
    )

    state_decision = state_machine.evaluate(
        runtime_context.runtime_state_context,
        runtime_input,
        deep_safety
    )

    priority_decision = priority_engine.evaluate(
        current_context=runtime_context,
        incoming_event=runtime_input,
        safety=deep_safety
    )

    preemption = preemption_engine.evaluate(
        runtime_context,
        priority_decision,
        deep_safety
    )

    matched_policies = policy_engine.evaluate_all(
        runtime_context,
        understanding_state,
        deep_safety,
        state_decision,
        priority_decision,
        preemption
    )

    final_policy = policy_conflict_resolver.resolve(
        matched_policies
    )

    return final_policy
```

---

## 10.2 Planner 之后二次检查

```python
def validate_action_plan(
    action_plan,
    policy_decision
):
    violations = policy_validator.validate(
        action_plan,
        policy_decision
    )

    if violations:
        return reject_or_replan(violations)

    return APPROVED
```

这确保：

```text
Planner 即使出错
也不能直接执行非法 Action
```

---

# 11. 各步骤详细实现

# Step 1：Early Safety Guard

目标：

```text
在进入复杂理解之前，
快速抓住明显紧急事件。
```

适合处理：

```text
明确求助

明显高风险不适

明显攻击 / 自伤表达

跌倒 / 受伤等直接描述

严重环境危险
```

当前业务目录中安全与领域事件已经覆盖求助、情绪安全、身体安全、用药摄入、意外环境以及安全处置机制等类别。

---

## 11.1 Early Safety 实现原则

建议：

```text
规则优先
+
快速文本信号
+
有限 Context
```

它的目标不是做完整心理分析，而是：

```text
宁可先拦住明显风险，
不要让高风险输入继续进入普通对话链。
```

---

# Step 2：Safety Re-evaluation

M3 完成以后，根据：

```text
UnderstandingState.risk_signal

emotion

goal

implicit_need

context
```

重新做深层 Safety 判断。

这样形成：

```text
Early Safety
+
Deep Risk Understanding
```

双重安全入口。

---

## 11.2 为什么必须二次 Safety

例如：

```text
“救命”
```

Early Safety 就可识别。

但：

```text
“活着这么累也没什么意思。”
```

可能需要 M3 结合上下文才能发现风险信号。

因此建议：

```text
Input
↓
Early Safety
↓
M3
↓
Safety Re-evaluation
```

---

# Step 3：State Validation

StateMachine 判断：

```text
当前状态是否合法？

当前 Event 在这个状态下是否允许？

是否需要状态迁移？
```

---

## 11.3 当前需求状态

Core 只允许 `RuntimeControlState`：

```text
STARTING
IDLE
LISTENING
PROCESSING
RESPONDING
WAITING_USER
WAITING_EXTERNAL
INTERRUPTED
ENDED
FAILED
```

下列历史状态**不是 Frozen Core**，必须进入 DomainState（Domain Example）：

```text
# Domain Example — 禁止写入 Core 状态机
S05 领域交互中
S06 内容播放中
S07 情绪安抚中
S08 求助处理中
S09 不适采集中
S10 提醒中
S11 领域任务交互中
```

历史 S00–S04 / S90 映射：

```text
S00 → STARTING
S01 → IDLE
S02 → LISTENING
S03 → PROCESSING
S04 → RESPONDING
S90 → FAILED
```



---

## 11.4 状态迁移必须统一

禁止业务代码：

```python
state = "HELP_IN_PROGRESS"  # Domain Example，禁止写入 Core
```

应该统一：

```python
state_machine.transition(event)
```

StateMachine 负责验证：

```text
from_state

event

condition

to_state
```

---

# Step 4：Priority Evaluation

当前需求固定运行时业务优先级：

```text
优先级 1
求助 / 高风险不适 / 高风险情绪

优先级 2
用药 / 复测提醒

优先级 3
其他提醒

优先级 4
陪伴 / 播放 / 认知 / 主动问候
```



软件内部可映射为：

```text
CRITICAL = 100

MEDICAL_REMINDER = 80

NORMAL_REMINDER = 60

NORMAL_INTERACTION = 20
```

数值本身配置化。

---

# Step 5：Preemption Evaluation

Priority 只回答：

```text
谁更重要？
```

Preemption 还需要回答：

```text
是否立即中断？

中断时做什么？

中断后是否恢复？
```

---

## 11.5 PreemptionRule

```text
PreemptionRule

current_business

incoming_event

interrupt

on_interrupt

cleanup_policy

resume_policy
```

---

## 11.6 Resume Policy

建议：

```text
NO_RESUME

OPTIONAL_RESUME

AUTO_RESUME

REPLAN
```

安全事件后普通业务默认：

```text
NO_RESUME
```

---

# Step 6：Policy Aggregation

不同 Policy 分别返回自己的判断。

例如：

```text
SafetyPolicy

StatePolicy

ActiveInteractionPolicy

ReminderPolicy

PrivacyPolicy
```

最终统一交给：

```text
PolicyConflictResolver
```

---

# Step 7：Policy Conflict Resolution

当多个 Policy 冲突时建议优先：

```text
Safety
>
Privacy
>
State
>
Priority / Preemption
>
Business Hard Rule
>
Interaction Soft Policy
```

---

# Step 8：生成 Final PolicyDecision

最终明确：

```text
允许什么

禁止什么

必须做什么

是否强制 Workflow

是否必须确认

哪些 Tool 可调用
```

---

# Step 9：ActionPlan 二次 Policy Check

M4 输出后：

```text
ActionPlan
↓
PolicyValidator
```

如果 Planner 生成：

```text
PLAY_CONTENT
```

但：

```text
safety_lock = true
```

则必须阻止。

---

# 12. 分支、路由与决策规则

# 12.1 普通路径

```text
无安全风险
+
State 允许
+
Policy 允许
↓
M4 Planner
```

---

# 12.2 Forced Workflow 路径

```text
risk_detected = true
+
forced_workflow != null
```

则：

```text
绕过普通自由 Planner

→ Deterministic Workflow
```

例如：

```text
HelpWorkflow

HighRiskEmotionWorkflow

EmergencyDiscomfortWorkflow
```

---

# 12.3 Safety Lock 路径

一旦进入：

```text
S08
或其他 Critical Workflow
```

建立：

```text
safety_lock = true
```

此期间禁止：

```text
普通播放

主动问候

领域任务交互

娱乐推荐
```

---

# 12.4 Event Queue

提醒、用户语音、Tool Callback 可能同时发生。

因此引入：

```text
EventQueue
```

事件至少包含：

```text
event_id

event_type

priority

timestamp

payload
```

---

## 12.4.1 同时事件示例

当前播放时同时出现：

```text
普通喝水提醒

+

用户说“救命”
```

不能简单按先来先处理。

应该：

```text
HELP = 100

NORMAL_REMINDER = 60

→ HELP先处理
```

普通提醒再根据 ReminderPolicy：

```text
defer

expire

re-evaluate
```

---

# 12.5 Hard Rule 与 Soft Policy

## Hard Rule

不可被 Planner 覆盖：

```text
通知失败不能说成功

高风险必须进入安全链

不同用户数据不能串

状态转移必须合法
```

---

## Soft Policy

主要影响 M4：

```text
回复尽量简短

减少连续追问

刚被拒绝后避免再次推荐
```

M2 以 Hard Rule 和确定性业务规则为主。

---

# 12.6 求助处理规则

当前需求规定：

```text
进入 S08

停止普通业务

询问一次是否叫人

肯定
→ 继续

否定
→ 取消

8秒无应答
→ 按肯定处理

确认后2秒内发起通知

单次通知等待10秒

结果只有 success / fail / timeout
```

这些属于确定性 Workflow / Policy，不交给 LLM。

---

# 12.7 身体不适规则

当前需求规定：

```text
普通不适
→ S09
→ 采集 1～5 项

高风险不适
→ 跳过普通采集
→ 进入安全通知链
```



M2 负责控制：

```text
普通
vs
强制升级
```

---

# 12.8 ReminderPolicy

当前需求已经固定：

普通提醒：

```text
首次未回应
→ 5分钟后再提醒一次
→ 仍无回应
→ 已过期
```

用药 / 复测：

```text
首次未回应
→ 3分钟后再提醒
→ 再次无回应
→ reminder_unanswered
→ 发起通知
```



这些不允许交给 M4 自由规划。

---

# 12.9 ActiveInteractionPolicy

当前需求明确：

```text
22:00–06:00
不主动问候

每日主动问候上限3次

播放中
提醒中
求助中
不适采集中
不主动问候

安静陪伴确认后10分钟
不主动追问
```



这些规则必须落到 Policy，而不是只写进 Prompt。

---

# 12.10 ConfirmationPolicy

用于统一：

```text
哪些动作必须确认

确认超时怎么办

无应答是否视为肯定

取消如何处理
```

例如：

```text
求助确认
8秒无应答
→ YES
```

属于固定软件规则。

---

# 12.11 TimeoutPolicy

建议统一管理：

```text
Listening timeout

ASR timeout

Help confirmation timeout

Discomfort question timeout

Discomfort total timeout

Reminder response timeout

Cognitive question timeout

Notification timeout
```

而不是散落在代码。

---

# 13. 与前后 M 的接口

# 13.1 M0 → M2

M0 提供：

```text
SafetyResult Schema

PolicyDecision Schema

StateUpdate Schema

RuntimeEvent

Registry
```

---

# 13.2 M1 → M2

M1 提供：

```text
RuntimeContext

current_state

active_task

time_context

tool_context

interaction_context

safety_context
```

---

# 13.3 M2 → M3

Early Safety Result 可以传给 M3：

```text
当前是否存在安全背景

当前是否已经锁定 Workflow
```

但 M3 仍负责完整理解。

---

# 13.4 M3 → M2

M3 返回：

```text
risk_signal

emotion

intent

uncertainty
```

如果：

```text
requires_safety_review = true
```

则回 M2：

```text
Safety Re-evaluation
```

这是重要的跨阶段回路。

---

# 13.5 M2 → M4

M4 必须接收：

```text
PolicyDecision
```

Planner 只能在：

```text
allowed_actions
allowed_skills
allowed_tools
```

范围内规划。

---

# 13.6 M2 → M5

M5 只接受：

```text
Policy Approved ActionPlan
```

没有通过 M2：

```text
不得执行敏感 Tool
```

---

# 13.7 M2 → M6

M6 使用：

```text
response_constraints

truth_policy

safety_flags
```

验证最终结果是否允许表达。

---

# 13.8 M8 → M2

M8 提交：

```text
StateUpdate Proposal
```

必须经过：

```text
StateMachine.validate
```

不能由 M8 随意修改状态。

---

# 14. 与业务模块的映射

# 14.1 领域交互

主要 Policy：

```text
ActiveInteractionPolicy

StatePolicy

InterruptionPolicy

QuietPeriodPolicy
```

---

# 14.2 内容播放

主要涉及：

```text
Playback State

STOP Policy

Preemption

ResumePolicy
```

---

# 14.3 情绪安抚

M2 负责区分：

```text
普通情绪
→ 普通 M4 策略

高风险情绪
→ Safety Workflow
```

---

# 14.4 安全与领域事件

这是 M2 的核心业务映射。

主要涉及：

```text
Safety Guard

Safety Lock

Forced Workflow

Priority 100

Notification Truth Hard Rule
```

当前总业务目录中的安全与领域事件模块覆盖求助、情绪安全、身体健康安全、用药与摄入安全、意外环境安全以及处置保障机制。

---

# 14.5 领域提醒

主要：

```text
ReminderPolicy

Priority

Retry

Escalation

Timeout
```

---

# 14.6 领域任务交互

主要：

```text
Interruptible = true

可被求助 / 不适 / 用药复测提醒抢占
```

---

# 14.7 长期记忆

主要涉及：

```text
PrivacyPolicy

Identity Isolation

Sensitive Memory Boundary
```

---

# 14.8 新闻天气

一般属于：

```text
NORMAL_INTERACTION
```

不能抢占安全事件或提醒。

---

# 15. 异常、超时与降级

# 15.1 Safety Model 失败

不能：

```text
默认 NO_RISK
```

应：

```text
规则层继续工作

model_status = unavailable
```

必要场景采取更保守策略。

---

# 15.2 Policy Engine 失败

对敏感场景采用：

```text
Fail Closed
```

例如：

```text
安全

通知

敏感状态修改

Memory敏感操作
```

默认不放行。

---

# 15.3 普通陪伴 Policy 失败

可以：

```text
固定兜底
+
回安全状态
```

而不是执行未知 Planner 行为。

---

# 15.4 State Store 失败

不能继续假设当前状态。

可以：

```text
进入 S90

或
安全降级状态
```

具体由可恢复性决定。

---

# 15.5 Priority Engine 失败

若存在 Safety Event：

```text
Safety Priority 默认最高
```

其他普通事件可以延期。

---

# 15.6 Preemption Engine 失败

对于安全事件：

```text
默认中断普通业务
```

即保守策略。

---

# 16. 配置项与可变项

建议配置：

```text
state_definitions

state_transitions

priority_mapping

preemption_rules

resume_rules

quiet_hours

active_interaction_limits

confirmation_timeouts

business_timeouts

reminder_retry_rules

policy_precedence

safety_rule_version
```

---

## 16.1 配置示例

```yaml
priorities:
  help: 100
  high_risk_discomfort: 100
  high_risk_emotion: 100
  medication_reminder: 80
  recheck_reminder: 80
  normal_reminder: 60
  companion: 20
  playback: 20
  cognitive: 20
```

---

## 16.2 主动交互配置

```yaml
active_interaction:
  quiet_hours:
    start: "22:00"
    end: "06:00"

  max_daily_greetings: 3

  quiet_companion_cooldown_minutes: 10
```

---

# 17. 非功能约束

# 17.1 安全优先

M2 必须优先保证：

```text
不能放过 Hard Safety Violation
```

而不是优先追求回复自然度。

---

# 17.2 决策延迟

Policy / State / Priority 判断应尽可能：

```text
本地
确定性
低延迟
```

不能让安全抢占依赖长时间 LLM 推理。

---

# 17.3 一致性

以下更新必须具备一致性保障：

```text
State

Safety Lock

Active Workflow

Reminder State

Notification State
```

---

# 17.4 可追踪

任何：

```text
block

force_workflow

interrupt

state_transition
```

都必须有：

```text
reason_code
```

---

# 17.5 隐私

M2 不应为了 Safety 之外的目的扩大个人数据读取范围。

尤其未绑定用户不得产生虚假身份归属。

---

# 18. Trace / Logging / Observability

每轮至少记录：

```text
EarlySafetyResult

DeepSafetyResult

CurrentState

IncomingEvent

MatchedPolicies

PriorityDecision

PreemptionDecision

PolicyConflicts

FinalPolicyDecision

StateTransition
```

---

## 18.1 Policy Reason Code

建议使用标准原因：

```text
FORCE_HELP_HIGH_RISK

BLOCK_PLAYBACK_SAFETY_LOCK

BLOCK_ACTIVE_GREETING_QUIET_HOURS

BLOCK_ACTION_INVALID_STATE

PREEMPT_PLAYBACK_MEDICATION_REMINDER

NO_RESUME_AFTER_SAFETY_EVENT
```

---

## 18.2 调试价值

例如：

> 为什么用户说“放首歌”却没有播放？

Trace：

```text
current_state = S08

safety_lock = true

reason =
BLOCK_PLAYBACK_SAFETY_LOCK
```

这样才能定位真正原因。

---

# 19. 版本、兼容与变更影响

# 19.1 State Machine Version

建议：

```text
state_machine_version
```

---

# 19.2 Policy Version

每次规则调整记录：

```text
policy_version
```

---

# 19.3 Safety Rule Version

尤其高风险规则必须：

```text
versioned
```

避免线上行为变化无法回溯。

---

# 19.4 可配置变更

以下变化通常无需改 Core：

```text
优先级数值

Quiet Hours

Timeout

Retry Interval

抢占关系

允许 Action 列表
```

---

# 19.5 Breaking Change

例如：

```text
删除状态

改变状态语义

改变高风险事件结果契约

改变 Safety Lock 生命周期

改变 notify_status 定义
```

可能影响 M4/M5/M6/M8，必须做完整回归。

---

# 20. 测试 / Eval

# 20.1 State Transition 测试

测试所有合法状态迁移。

---

# 20.2 Illegal Transition 测试

例如：

```text
S08
→
S06
```

未经合法结束事件必须被拒绝。

---

# 20.3 Priority 测试

验证：

```text
Critical
>
Medication Reminder
>
Normal Reminder
>
Normal Interaction
```

---

# 20.4 Preemption 测试

覆盖：

```text
是否中断

如何清理

是否恢复

是否入队
```

---

# 20.5 Safety 测试

覆盖：

```text
普通表达

明确风险

模糊风险

上下文风险

多风险组合

误报干扰样例
```

---

# 20.6 Policy Conflict 测试

例如：

```text
ActiveInteractionPolicy
允许主动

但
StatePolicy
禁止主动
```

应输出：

```text
BLOCK
```

---

# 20.7 Fail Closed 测试

Policy Engine / Safety Model 异常时：

```text
敏感动作不能被错误放行
```

---

# 20.8 Planner Violation 测试

故意让 M4 输出非法 Action：

```text
S08
+
PLAY_CONTENT
```

PolicyValidator 必须拦截。

---

# 20.9 Notification Truth 测试

确保：

```text
notify_status = fail / timeout
```

时：

```text
success claim forbidden
```

---

# 21. Gate

## Gate M2-01

需求中的全部状态已经正式编码。

---

## Gate M2-02

所有状态迁移必须经过 StateMachine。

---

## Gate M2-03

运行时优先级正式实现。

---

## Gate M2-04

当前需求中的抢占规则全部可以执行。

---

## Gate M2-05

高风险事件可以强制绕过普通 Planner。

---

## Gate M2-06

Planner 无法执行 Policy 禁止 Action。

---

## Gate M2-07

Safety Lock 可以阻止普通业务启动。

---

## Gate M2-08

主动问候限制不依赖 Prompt。

---

## Gate M2-09

Reminder Retry / Escalation 不依赖 LLM。

---

## Gate M2-10

通知真实性已经作为 Hard Rule 存在。

---

## Gate M2-11

Policy Conflict Resolver 正式存在。

---

## Gate M2-12

所有 PolicyDecision 都可以追踪 reason_code。

---

## Gate M2-13

Early Safety 和 Deep Safety 均存在。

---

## Gate M2-14

M3 RiskSignal 可以触发 Safety Re-evaluation。

---

## Gate M2-15

Planner 输出后存在二次 Policy Validation。

---

## Gate M2-16

State / Safety Lock / Active Workflow 可持久恢复。

---

## Gate M2-17

Policy Engine 异常时，敏感操作 Fail Closed。

---

# 22. 交付物

M2 最终至少形成：

```text
M2-01 Safety总体架构

M2-02 SafetyResult数据模型

M2-03 Early Safety Guard设计

M2-04 Deep Safety Re-evaluation设计

M2-05 State Machine设计

M2-06 State Definition表

M2-07 State Transition表

M2-08 Priority模型

M2-09 Preemption规则表

M2-10 Resume Policy规范

M2-11 Policy Engine设计

M2-12 Policy分类与Registry

M2-13 Policy Conflict Resolver

M2-14 Safety Lock机制

M2-15 Event Queue机制

M2-16 Confirmation / Timeout Policy

M2-17 Reminder Policy

M2-18 Active Interaction Policy

M2-19 Policy Trace / Reason Code规范

M2-20 M2自动化测试集

M2-21 M2 Gate验证报告
```

---

# 附录 A：Core RuntimeControlState

| State | 名称 |
|---|---|
| STARTING | 启动中 |
| IDLE | 空闲 |
| LISTENING | 聆听 |
| PROCESSING | 处理中 |
| RESPONDING | 回复中 |
| WAITING_USER | 等待用户 |
| WAITING_EXTERNAL | 等待外部 |
| INTERRUPTED | 已抢占 |
| ENDED | 已结束 |
| FAILED | 失败 |

业务阶段（播放 / 安抚 / 求助 / 不适采集 / 提醒等）属于 DomainState，见 Canonical Registry §5.4。  
上表取代原 S00–S11 / S90 Core 状态表。原表不再有效。

---

# 附录 B：当前运行时优先级

```text
Priority 1

求助
高风险身体不适
高风险情绪

↓

Priority 2

用药提醒
复测提醒

↓

Priority 3

其他提醒

↓

Priority 4

普通陪伴
播放
认知
主动问候
```



---

# 附录 C：当前抢占关系

## C.1 播放中遇到求助

```text
S06
+
HELP

→ 停止播放
→ S08
→ HelpWorkflow
→ NO_RESUME
```

---

## C.2 播放中遇到用药 / 复测提醒

```text
S06
+
MEDICATION / RECHECK REMINDER

→ 中断播放
→ S10
→ 提醒完成后不强制恢复
```

---

## C.3 求助处理中请求播放

```text
S08
+
PLAY_CONTENT

→ 不执行播放
→ 继续 HelpWorkflow
```

---

## C.4 不适采集中出现求助

```text
S09
+
HELP

→ 停止采集
→ S08
```

---

## C.5 普通提醒中出现求助

```text
S10
+
HELP

→ 中断提醒
→ S08
```

这些关系与现有需求第 9 章保持一致。

---

# 附录 D：典型 PolicyDecision

## D.1 普通陪伴状态请求播放

```text
current_state = S05

intent = PLAY_CONTENT
```

Policy：

```text
allowed = true

allowed_actions:
- PLAY_CONTENT

allowed_skills:
- ContentSkill
```

进入 M4 正常规划。

---

## D.2 求助处理中请求播放

```text
current_state = S08

safety_lock = true
```

Policy：

```text
allowed = false

forbidden_actions:
- PLAY_CONTENT

forced_action:
- CONTINUE_HELP_WORKFLOW

reason_code:
BLOCK_PLAYBACK_SAFETY_LOCK
```

---

# 附录 E：典型 PoC

## E.1 PoC 1：普通播放

```text
Current State:
S01

Understanding:
PLAY_CONTENT

Policy:
allowed

State:
S01 → S06
```

---

## E.2 PoC 2：播放中求助

用户：

> “救命。”

流程：

```text
S06
↓
Early Safety = Critical
↓
Preemption = true
↓
停止播放
↓
Safety Lock
↓
S08
↓
HelpWorkflow
```

结果：

```text
resume_policy = NO_RESUME
```

---

## E.3 PoC 3：求助中播放请求

```text
S08

safety_lock = true

用户：
“给我放首歌”
```

Policy：

```text
PLAY_CONTENT = forbidden
```

继续：

```text
HelpWorkflow
```

---

## E.4 PoC 4：安静时段主动问候

```text
23:00
S01
ACTIVE_GREETING
```

Policy：

```text
blocked

reason =
QUIET_HOURS
```

---

## E.5 PoC 5：提醒抢占播放

```text
S06
+
MEDICATION_REMINDER
```

Priority：

```text
80 > 20
```

结果：

```text
中断播放
→ S10
```

---

## E.6 PoC 6：普通提醒遇到求助

```text
S10
+
“快叫人来”
```

结果：

```text
普通提醒中断
→ S08
```

---

## E.7 PoC 7：高风险不适

Safety 判断：

```text
HIGH_RISK_DISCOMFORT
```

Policy：

```text
force_workflow = EmergencyDiscomfortWorkflow
```

不得继续普通：

```text
S09 第1～4项信息采集
```

而直接进入安全通知链。

---

# 附录 F：M2 完成后的系统状态

完成 M2 后，系统已经具备：

```text
知道当前是什么状态

知道哪些 Action 被允许

知道哪些 Action 被禁止

知道谁可以抢占谁

知道什么时候必须中断普通任务

知道什么时候不能自动恢复

知道哪些事件必须进入确定性 Workflow

知道什么时候禁止 Agent 自由决策

知道哪些系统事实不能由 LLM 编造
```

但此时：

```text
它还不真正理解人的复杂表达
```

这正是 M3 的任务。

---

# 附录 G：M0～M2 当前形成的基础

```text
M0
统一 Runtime 骨架

↓

M1
准备输入与 Context

↓

M2
建立 Safety / State / Policy

↓

M3
理解这个人此刻到底在表达什么

↓

M4
决定下一步最合适做什么
```

因此到 M2 完成后，M3 可以专注在：

```text
语义

情绪

隐含需要

指代

上下文融合

不确定性

风险信号
```

而不需要自己重新承担状态机、提醒优先级、抢占、通知真实性等确定性业务规则。