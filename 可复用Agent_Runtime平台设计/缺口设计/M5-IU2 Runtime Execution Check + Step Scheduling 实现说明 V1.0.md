# M5-IU2 Runtime Execution Check + Step Scheduling 实现说明 V1.0

> 适用范围：M5 Execution Framework 的第二个 Implementation Unit。
> 本 IU 只负责“执行前实时资格检查 + 第一版顺序调度”，不做 Capability Resolution，不调用 Skill / Workflow / Tool，不进入 Retry / Timeout / Permission Enforcement / M6。

## 1. IU2 目标

M5-IU2 解决两个问题：

```text
1. 当前已经批准的 Step，现在是否仍允许开始执行
2. 在顺序执行 baseline 下，下一个 Step 应该 READY / WAIT / SKIP / COMPLETE
```

正式链路：

```text
PreparedExecution + ApprovedActionPlan
        ↓
SequentialStepScheduler
        ↓
READY step
        ↓
RuntimeExecutionChecker
        ↓
ALLOWED / BLOCKED / CANCELLED / PREEMPTED
        ↓
后续 IU 才进入 Capability Resolution / Execution
```

## 2. Runtime Execution Check

新增：

```text
RuntimeExecutionFacts
RuntimeExecutionFactsProvider
RuntimeExecutionCheckStatus
RuntimeExecutionCheckDecision
RuntimeExecutionChecker
```

### 2.1 RuntimeExecutionFacts

Core 不直接解释 Domain 状态，而是要求注入层先把实时事实投影为：

```text
session_active
state_allows_step
policy_snapshot_valid
safety_allows_step
current_state
blocking_reason_codes
```

任何 required fact 为 `False` 或 `None` 时均 fail closed。

### 2.2 Control Signal

RuntimeExecutionChecker 先读取已冻结的：

```text
ExecutionControlSignalSource
```

并遵循：

```text
CANCEL  -> CANCELLED
PREEMPT -> PREEMPTED
NONE    -> 继续 Runtime facts 检查
```

M5 不自行计算 priority，也不决定新的 Safety / Preemption Policy。

### 2.3 不属于 IU2 Runtime Check 的内容

以下能力检查延后到 Capability Resolution / Permission Enforcement：

```text
Skill / Workflow / Tool 是否注册
enabled
版本兼容
Capability allowed_states
Tool required_permissions
implementation_ref 类型
```

因此：

```text
Runtime execution eligibility
!=
Capability resolution
```

## 3. Sequential Step Scheduler

新增：

```text
StepScheduleAction
StepScheduleDecision
SequentialStepScheduler
```

第一版只支持 ApprovedPlan 原顺序，不允许重新排序。

输出：

```text
READY
WAIT
SKIP
COMPLETE
```

### 3.1 Dependency

规则：

```text
dependency = PENDING / RUNNING
→ WAIT

dependency != SUCCESS
→ SKIP

all dependencies = SUCCESS
→ 当前 Step 可继续 eligibility 判断
```

Scheduler 不修改 Plan，也不执行 fallback。

### 3.2 Simple Condition Hook

新增：

```text
StepEligibilityStatus
StepEligibilityDecision
StepEligibilityEvaluator
```

用于注入简单执行前条件：

```text
ALLOW
WAIT
SKIP
```

Core 不硬编码业务条件名，也不把 `completion_condition` 偷换成 execution precondition。

Evaluator 只能约束当前 Approved Step，不能：

```text
改序
新增 Step
替换 Action
替换 Capability
```

## 4. Failure Directive

新增：

```text
StepFailureDirective
StepFailureDecision
FailureDirectiveResolver
ContinueIfSafeEvaluator
```

支持当前 M5 V2.0 已定义的：

```text
STOP_PLAN
RUN_FALLBACK
CONTINUE_IF_SAFE
```

默认规则：

```text
optional=true + 无 on_failure
→ CONTINUE

required + 无 on_failure
→ STOP_PLAN

CANCELLED / PREEMPTED
→ STOP_PLAN

CONTINUE_IF_SAFE 无 evaluator
→ STOP_PLAN
```

`RUN_FALLBACK` 只输出 directive，不在 IU2 真正执行 fallback。

FailureDirectiveResolver 必须确认：

```text
传入 status
==
PreparedExecution 中该 Step 的 authoritative terminal status
```

避免调用方伪造失败状态。

## 5. SKIP Lifecycle

IU2 扩展 IU1 lifecycle：

```text
PENDING
→ SKIPPED
```

新增：

```text
ExecutionLifecycleManager.skip_step
ExecutionLifecycleService.skip_step
```

SKIP 通过 LifecycleService 持久化，仍遵守 IU1 的单一状态真值与持久化边界。

## 6. 仍然不属于 IU2 的能力

```text
Capability Resolution
Skill Executor
Workflow Executor
Tool Executor
Tool Schema Validation
Execution Permission Enforcement
Retry
Timeout
Idempotency behavior
Cancellation Handler
Preemption Handler
Fallback execution
Execution Aggregation
M6 Result Validation
```

## 7. IU2 Gate

通过条件：

```text
1. RuntimeExecutionChecker 只检查已批准 Step 的实时资格
2. CANCEL / PREEMPT 只消费 Runtime/M2 已解析信号
3. 任一关键 Runtime fact 为 UNKNOWN 时 fail closed
4. Scheduler 严格保持 ApprovedPlan 顺序
5. Dependency 未完成时 WAIT
6. Dependency 非 SUCCESS 时 SKIP
7. 简单条件只能通过 injected StepEligibilityEvaluator
8. Failure directive 不修改 Plan
9. CANCELLED / PREEMPTED 不允许继续执行
10. SKIP transition 被持久化
11. IU2 不解析/调用 Capability
12. IU2 不进入 M6 / K0 / Response / Update
```

## 8. Verification

合并前运行：

```text
python -m pytest tests -q
python -m mypy runtime tests
python -m ruff check runtime tests
python -m ruff format --check runtime tests
```

四项全绿并通过 Independent Review 后，才允许：

```text
M5-IU2 = PASSED
```

不等于：

```text
Capability 已解析
Tool 已真实调用
Retry / Timeout 已完成
M5 = CLOSED
Production Ready
```
