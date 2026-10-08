# M5-IU2 Runtime Execution Check + Step Scheduling 实现说明 V1.0

> 适用范围：M5 Execution Framework 的第二个 Implementation Unit。
> 前置：M5-IU1 = PASSED。
> 本 IU 只实现“执行前 Runtime 合法性检查 + 第一版顺序 Step 调度”，不进入 Capability Resolution、真实 Skill / Workflow / Tool 执行、Permission Enforcement、Retry / Timeout Handler、Cancellation / Preemption Handler、M6。

## 1. IU2 目标

IU2 解决两个问题：

```text
1. 一个已经批准的 Step，在真正执行前，此刻还能不能继续执行？
2. 一个 ApprovedActionPlan 中，下一步应该轮到哪个 Step？
```

正式链路：

```text
PreparedExecution (RUNNING)
        ↓
SequentialStepScheduler
        ↓
StepScheduleDecision
        ↓
RuntimeExecutionChecker
        ↓
RuntimeExecutionCheckDecision
        ↓
后续 Capability Resolution（不在 IU2）
```

IU2 不修改 ApprovedPlan，不重新运行 M4 Planner，不重新计算 M2 Policy。

## 2. Runtime Execution Check

新增：

```text
runtime/execution/runtime_check.py
```

核心对象：

```text
RuntimeExecutionSnapshot
RuntimeExecutionSnapshotProvider

PolicySnapshotValidityDecision
PolicySnapshotValidityEvaluator

StateEligibilityDecision
ExecutionStateEligibilityEvaluator

RuntimeExecutionCheckDecision
RuntimeExecutionChecker
```

### 2.1 RuntimeExecutionSnapshot

Snapshot 只承载执行前必须重新确认的当前 Runtime 事实：

```text
session_id
identity_scope
current_state
session_active
safety_lock
restricted_actions
```

它不是新的 RuntimeContext，也不复制 Conversation / Memory / DomainState。

### 2.2 检查顺序

IU2 冻结优先级：

```text
已解析 Cancel / Preempt 信号
>
identity / session continuity
>
session validity
>
safety restriction
>
frozen policy snapshot validity
>
current Runtime state eligibility
```

输出状态：

```text
ALLOWED
BLOCKED
CANCEL_REQUIRED
PREEMPT_REQUIRED
UNKNOWN
```

其中：

```text
UNKNOWN != ALLOWED
```

任何无法确认的关键事实都不得静默放行。

### 2.3 Cancel / Preempt 边界

IU2 只消费：

```text
ExecutionControlSignalSource
```

给出的 Runtime / M2 已解析信号。

IU2 不比较 priority，不自行决定抢占，不执行真正 cancel / preempt side effect。

```text
CANCEL_REQUIRED / PREEMPT_REQUIRED
```

只表示后续 handler 必须处理。

### 2.4 Policy Snapshot Validity

`PolicySnapshotValidityEvaluator` 只验证：

```text
当前被冻结的 policy_snapshot 是否仍有效
```

禁止：

```text
重新计算 PolicyDecision
增加 / 删除 allowed action
修改 ApprovedActionPlan
重新选择 Capability
```

### 2.5 Safety Lock

若：

```text
safety_lock = true
```

且当前 Action 明确存在于：

```text
restricted_actions
```

则：

```text
BLOCKED
```

Safety Lock 采用显式三态语义：

```text
safety_lock = true
+ restricted_actions 命中当前 action
→ BLOCKED

safety_lock = true
+ restricted_actions 不可得
→ UNKNOWN

safety_lock = false
→ 继续后续检查

safety_lock = null / unknown
→ UNKNOWN
```

因此：

```text
UNKNOWN safety_lock
!=
false
!=
ALLOWED
```

不默认放行。

## 3. Step Scheduler

新增：

```text
runtime/execution/scheduler.py
```

核心对象：

```text
SequentialStepScheduler

StepScheduleDecision
StepScheduleStatus

StepConditionEvaluator
StepConditionDecision
NoopStepConditionEvaluator
```

### 3.1 Scheduler 前置状态

只有：

```text
ExecutionRecord.status = RUNNING
```

时 Scheduler 才允许给出 READY。

CREATED 或终态 Execution 不进入正常调度。

### 3.2 第一版顺序调度

IU2 严格保持 ApprovedActionPlan.steps 原顺序：

```text
Step 1
↓
Step 2
↓
Step 3
```

不重新排序，不优化，不并发，不构造 DAG。

输出状态：

```text
READY
WAITING
SKIP
BLOCKED
COMPLETE
UNKNOWN
```

Scheduler 只做决策，不直接调用 LifecycleManager，不修改 Step 状态。

特别说明：

```text
StepScheduleStatus.COMPLETE
!=
ExecutionPlanStatus.SUCCESS
```

`COMPLETE` 只表示“当前没有剩余 PENDING Step，调度工作结束”，不表示业务执行成功，也不表示整个 Execution 应当被标为 SUCCESS。最终 `SUCCESS / PARTIAL_SUCCESS / FAILED` 必须由后续 Execution Aggregator 根据全部 Step 结果决定。

### 3.3 dependency

如果 dependency：

```text
PENDING / RUNNING
```

则：

```text
WAITING
```

如果 dependency 终态但不是 SUCCESS：

```text
SKIP
```

真正把 Step 标成 SKIPPED 仍由后续 orchestration 通过 ExecutionLifecycleService 完成。

### 3.4 Optional / Required

如果前序 Step 失败，并且：

```text
optional = true
```

Scheduler 可以继续评估下一 Approved Step。

如果：

```text
optional != true
```

则第一版 fail closed：

```text
BLOCKED
reason = REQUIRED_PREVIOUS_STEP_NOT_SUCCESSFUL
```

IU2 不解释任意字符串 `on_failure`。

原因：

```text
ActionStep.on_failure 当前不是冻结 Core Enum
```

因此不能在 Core 中自行发明：

```text
STOP_PLAN
RUN_FALLBACK
CONTINUE_IF_SAFE
```

的具体运行语义。

后续如需支持，必须先冻结 FailureDisposition / Resolver Contract。

### 3.5 简单条件

当前 Canonical ActionStep 没有独立的：

```text
execution_condition
```

字段。

因此 IU2 **不把 completion_condition 偷换成执行条件**。

简单条件通过注入：

```text
StepConditionEvaluator
```

处理。

Core 只认识：

```text
SATISFIED
NOT_SATISFIED
WAITING
UNKNOWN
```

不硬编码 Domain 条件语法。

## 4. Capability Enabled 为什么不在 IU2

M5 V2.0 Step 3 文本中曾把：

```text
Capability 是否启用
```

列入 Runtime Execution Check。

但实际运行链中：

```text
Step 4 = Scheduling
Step 5 = Capability Resolution
```

Capability Registry 的：

```text
存在
enabled
version
implementation_ref
permission
```

必须由后续 Capability Resolution 统一检查。

IU2 不提前再做一套 Registry Lookup，避免：

```text
Runtime Check 一套 capability truth
Capability Resolver 又一套 capability truth
```

因此本 IU 将该项明确落到下一 IU。

## 5. 明确不属于 IU2

```text
Capability Resolution
Skill / Workflow / Tool invocation
ExecutionPermissionEvaluator 实际 enforcement
Tool schema validation
Timeout handling
Retry
Idempotency behavior
Cancellation handler
Preemption handler
Resource Lock
Checkpoint / Recovery
Execution aggregation
M6 Result Validation
Response / Update
```

## 6. IU2 Gate

通过条件：

```text
1. Cancel / Preempt 只消费已有 signal，不重新算 priority
2. identity/session drift fail closed
3. session validity unknown 不放行
4. safety_lock = None 时返回 UNKNOWN，不得静默放行
5. safety lock restriction 正确阻断
6. policy validity 只校验 snapshot，不重算 Policy
7. Runtime-state eligibility 可注入且 UNKNOWN 保留
8. Scheduler 只在 RUNNING execution 上调度
9. 严格保持 ApprovedPlan 原顺序
10. dependency pending/running -> WAITING
11. failed dependency -> SKIP
12. required previous failure -> BLOCKED
13. optional previous failure可以继续
14. 简单条件必须通过注入 evaluator，不解析 Domain 规则
15. Scheduler 不修改 lifecycle
16. StepScheduleStatus.COMPLETE 只表示调度结束，不表示 Execution success
17. IU2 不进入 Capability / Tool / M6
```

## 7. Verification

合并前运行：

```text
python -m pytest tests -q
python -m mypy runtime tests
python -m ruff check runtime tests
python -m ruff format --check runtime tests
```

四项全绿并完成 Independent Review 后，才允许：

```text
M5-IU2 = PASSED
```

不等于：

```text
M5 = CLOSED
Capability 已解析
Tool 已执行
业务执行成功
Production Ready
```
