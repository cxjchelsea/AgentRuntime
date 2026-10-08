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
ExecutionCreationStore.create（原子创建）
        ↓
PreparedExecution
        ↓
ExecutionLifecycleManager（纯状态转换）
        ↓
ExecutionLifecycleService（统一持久化）
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
ExecutionLifecycleService
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
step_state（静态 Plan/Capability 投影，不承载动态生命周期状态）
tool_context
deadline
cancellation_token
trace_context
```

当前 `deadline` 与 `trace_context` 都只允许通过显式 resolver 注入；IU1 不默认把 `RuntimeContext.task_context.timeout_at` 或 M4 trace 当作执行层事实。ToolContext 只以其 Canonical 子上下文投影；Conversation / Memory 等完整上下文不进入 ExecutionContext。

`ExecutionContext.step_state` 在 IU1 中只保存静态 Step 元数据（action / skill_id / workflow_id），**不保存 PENDING/RUNNING/SUCCESS 等动态状态**。动态执行状态的唯一权威来源是：

```text
PreparedExecution.steps
+
ExecutionRecord.step_results
```

后续组件不得把 `ExecutionContext.step_state` 当作生命周期真值，避免同一个 Step 状态被多处独立维护。

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

`ExecutionCreationStore.create(...)` 必须提供原子创建语义。Execution ID 已存在时不得覆盖已有执行，即使两个初始化请求并发到达，也只能有一个创建成功。IU1 将 `cancellation_token` 绑定为当前 `execution_id`，后续 Cancellation / Preemption Handler 以该执行身份关联动态控制信号。

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

`ExecutionLifecycleManager` 仅负责纯状态转换；所有真正改变 Execution / Step 生命周期的运行时调用必须经过 `ExecutionLifecycleService`。该 Service 在每次 transition 后把新的 `ExecutionRecord` 写入 `ExecutionStateStore`，保证进程内 PreparedExecution 与持久化 observation 一致。

生命周期必须满足时间单调性：Execution 不能在 `created_at` 之前开始；Step 不能在 Execution `started_at` 之前开始，也不能在自身 `started_at` 之前结束。`ExecutionResult.timing.started_at` 使用真实 Execution start time，而不是 record creation time。

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
4. Execution 初始化时原子持久化 CREATED + PENDING steps
5. execution_id 不允许覆盖/并发重复创建/跨 identity_scope 重绑定
6. Step 生命周期转换 deterministic + fail closed
7. 动态 Step 状态只存在于 PreparedExecution / ExecutionRecord，ExecutionContext.step_state 不重复维护状态
8. 所有 Lifecycle transition 通过 ExecutionLifecycleService 持久化最新 ExecutionRecord
9. IU1 sequential baseline 同时最多一个 RUNNING Step
10. 非终态 Execution 不能投影 ExecutionResult
11. ExecutionResult 不伪造业务事实
12. IU1 不调用 Skill / Workflow / Tool / M6 / K0 / Response / Update
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