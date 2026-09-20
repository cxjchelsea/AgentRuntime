# M5-IU1 Execution Foundation 实现说明 V1.0

> 适用范围：M5 Execution Framework 的第一个 Implementation Unit。
> 本 IU 只建立执行生命周期骨架，不调用真实 Skill / Workflow / Tool，不实现 Retry / Timeout / Permission Enforcement / Cancellation Handler / Checkpoint / Recovery，也不承担 M6 Truth Validation。

## 1. IU1 目标

M5-IU1 负责把已经批准的计划转换为一个可被执行框架后续阶段安全接管的执行实例。

正式链路：

```text
ApprovedActionPlan
        ↓
ApprovedPlanExecutionValidator
        ↓
ExecutionContextBuilder
        ↓
ExecutionRecordFactory
        ↓
ExecutionStateStore.save
        ↓
PreparedExecution
        ↓
ExecutionLifecycleManager
        ↓
ExecutionResultProjector（仅终态投影）
```

## 2. 本 IU 实现内容

新增 `runtime/execution/foundation.py`，包含：

```text
ApprovedPlanExecutionValidator
ExecutionIdentifierFactory
CallableExecutionIdentifierFactory
ExecutionContextBuilder
ExecutionRecordFactory
StepLifecycleSnapshot
PreparedExecution
ExecutionLifecycleManager
ExecutionResultProjector
ExecutionFoundation
InMemoryExecutionStateStore
```

## 3. Approved Plan Entry Check

M5 入口只接受 `ApprovedActionPlan` 语义。IU1 不重新运行 M4 Planner，也不重新执行 M2 Policy Re-check。

执行前检查：

```text
approval_status = APPROVED
plan_id / request_id 非空
schema_version 属于 M5 支持范围
policy_snapshot 非空
steps 非空
step_id 唯一
depends_on 只能引用此前已经出现的 approved step
```

任何失败都 fail closed，不进入执行实例创建。

## 4. ExecutionContext Builder

M5 不直接把完整 RuntimeContext 透传给执行层。

只投影：

```text
execution_id
plan_id
request_id
session_id
identity_scope
device_id
current_state
policy_snapshot
step_state
tool_context
deadline
cancellation_token
trace_context
```

当前 deadline 从 `RuntimeContext.task_context.timeout_at` 投影；ToolContext 只以其 Canonical 子上下文投影；Conversation / Memory 等完整上下文不进入 ExecutionContext。

## 5. Execution / Step ID Chain

IU1 冻结：

```text
request_id
→ plan_id
→ execution_id
→ step_execution_id
```

`ExecutionIdentifierFactory` 只定义 ID 生成能力，不在 Core 固定 UUID、Snowflake 等策略。

同一 Execution 内 `step_execution_id` 必须唯一。

## 6. ExecutionRecord

初始化时创建并持久化：

```text
ExecutionRecord
status = CREATED
current_step = null
所有 Step = PENDING
```

Execution ID 已存在时不得覆盖已有执行。

`InMemoryExecutionStateStore` 仅用于 IU1 机制测试，不代表生产持久化方案。

同一个 execution_id 不能重新绑定到其他 plan_id / request_id / identity_scope。

## 7. Step Lifecycle

IU1 冻结最小生命周期：

```text
PENDING
→ RUNNING
→ SUCCESS / FAILED / SKIPPED / CANCELLED / TIMEOUT / PREEMPTED
```

第一版仍按 M5 V2.0 的顺序执行 baseline：一个 Execution 同时只允许一个 RUNNING Step。

IU1 不负责 dependency scheduling；真正的依赖解析属于后续 StepScheduler IU。

生命周期必须满足时间单调性：Step 不能在 Execution 创建前开始，也不能在 started_at 之前结束。

## 8. ExecutionResult Projection

`ExecutionResultProjector` 只允许从终态 Execution 投影 Canonical `ExecutionResult`。

当前投影只承载执行观察：

```text
execution_id / plan_id / request_id
identity_scope
plan_status
step_results
timing
```

不会在 IU1 中伪造：

```text
skill_results
workflow_result
tool_results
business_outputs
state_observations
quality
```

因此：

```text
ExecutionPlanStatus.SUCCESS
!=
Business Truth Success
```

M6 仍是后续事实验证边界。

## 9. 明确不属于 IU1 的内容

```text
StepScheduler dependency resolution
Capability Resolution
Skill Executor
Workflow Executor
Tool Executor
Tool Input / Output Schema Validation
Execution Permission enforcement
Timeout
Retry
Idempotency behavior
Cancellation handling
Preemption handling
Resource Lock
Workflow Checkpoint
Crash Recovery
Ongoing Activity
Execution Event publisher
真实 Trace / Metrics
```

这些后续按 M5 Implementation Units 逐步实现。

## 10. IU1 Gate

本 IU 通过条件：

```text
1. 只接受 ApprovedActionPlan
2. ExecutionContext 只投影 M5 所需上下文
3. request → plan → execution → step execution ID 链成立
4. Execution 初始化时持久化 CREATED + PENDING steps
5. execution_id 不允许覆盖/跨 identity_scope 重绑定
6. Step 生命周期转换 deterministic + fail closed
7. IU1 sequential baseline 同时最多一个 RUNNING Step
8. 非终态 Execution 不能投影 ExecutionResult
9. ExecutionResult 不伪造业务事实
10. IU1 不调用 Skill / Workflow / Tool / M6 / K0 / Response / Update
```

## 11. Verification

合并前运行：

```text
python -m pytest tests -q
python -m mypy runtime tests
python -m ruff check runtime tests
python -m ruff format --check runtime tests
```

四项全绿且独立 Review 通过后，才允许标记：

```text
M5-IU1 = PASSED
```

不等于：

```text
M5 = CLOSED
Execution capability 已可用
Tool 已真实调用
业务执行成功
Production Ready
```