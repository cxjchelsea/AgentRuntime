# M5 Readiness Contract Fix Pack V1.0

> 适用范围：M5 Execution Framework V2.0 的 Implementation Readiness 阻塞修复。
> 本文件只冻结 M5 内部执行合同与 Registry optional metadata，不修改 M4、M6、RuntimeOrchestrator 15-stage，也不改变主链 Canonical `ApprovedActionPlan → ExecutionResult`。

## 1. Readiness Review 阻塞项

第一轮 M5 Implementation Readiness Review 识别：

```text
B-M5-001 Execution internal result contracts 未冻结
B-M5-002 Workflow / Tool Registry metadata 不足
B-M5-003 Cancellation / Preemption dynamic signal interface 缺失
B-M5-004 Execution persistence / checkpoint / idempotency / lock protocols 缺失
B-M5-005 Skill / Workflow / Tool implementation protocols 未冻结
```

本 Fix Pack 只处理这五项，不开始真实 Tool / Skill / Workflow 执行。

## 2. CF-M5-01：Internal Result Contracts

新增 M5 内部 typed contracts：

```text
ToolInvocationRequest
M5ToolResult
SkillExecutionRequest
M5SkillResult
WorkflowExecutionRequest
M5WorkflowResult
ExecutionErrorRecord
ExecutionEventRecord
WorkflowCheckpoint
ExecutionRecord
ActivityInstance
```

并冻结执行状态：

```text
StepExecutionStatus
ToolExecutionStatus
SkillExecutionStatus
WorkflowExecutionStatus
ActivityStatus
```

`ToolExecutionStatus` 正式包含 `UNKNOWN`。它用于“外部副作用可能已经发生，但当前无法确认”的情况，不得被 M5 静默改写为 FAILED。

这些类型属于 M5 internal contracts。当前 Canonical `ExecutionResult` 保持不变，M5 后续将内部结果投影到其 `step_results / skill_results / workflow_result / tool_results / business_outputs / execution_events / errors`。

因此：

```text
B-M5-001 = FIX_IMPLEMENTED
```

## 3. CF-M5-02：Registry Metadata Amendment

对现有 Registry 做向后兼容 optional 字段扩展。

`WorkflowDefinition` 新增：

```text
supported_events
allowed_states
checkpoint_enabled
timeout_policy
resume_policy
```

`ToolDefinition` 新增：

```text
resource_locks
```

原有定义不填写新字段时仍然合法，因此该调整不改变已有注册项语义。

这些字段只描述执行 metadata，不执行 Workflow / Tool，也不把 Domain resource 名称硬编码进 Core。

因此：

```text
B-M5-002 = FIX_IMPLEMENTED
```

## 4. CF-M5-03：Cancellation / Preemption Signal Contract

新增：

```text
ExecutionControlSignalType
ExecutionControlSignal
ExecutionControlSignalSource
```

信号类型冻结为：

```text
NONE
CANCEL
PREEMPT
```

边界：M2 / Runtime 负责决定是否取消/抢占及其原因，M5 只读取已解析的控制信号并安全停止执行。M5 不根据 priority 自行做新的抢占决策。

冻结的 `ExecutionEngine.execute(ApprovedActionPlan, RuntimeContext)` 签名不修改；Concrete M5 Engine 后续通过依赖注入获得 `ExecutionControlSignalSource`。

因此：

```text
B-M5-003 = FIX_IMPLEMENTED
```

## 5. CF-M5-04：Persistence / Checkpoint / Idempotency / Lock Protocols

新增 Protocol：

```text
ExecutionStateStore
WorkflowCheckpointStore
IdempotencyStore
ResourceLockProvider
```

并新增：

```text
IdempotencyRecord
IdempotencyStatus
```

`IdempotencyStatus` 包含 `UNKNOWN`，用于保存“副作用可能已发生但无法确认”的恢复状态，防止 crash / timeout 后盲目重放。

本 Fix Pack 只冻结接口，不绑定 Redis / PostgreSQL。M5-IU 后续允许提供 InMemory 实现用于机制测试，再由部署层替换真实存储。

因此：

```text
B-M5-004 = FIX_IMPLEMENTED
```

## 6. CF-M5-05：Implementation Protocols

新增 runtime-checkable Protocol：

```text
ToolImplementation
SkillImplementation
WorkflowImplementation
```

并新增：

```text
ExecutionImplementationResolver
```

Resolver 从现有 `SkillRegistry / WorkflowRegistry / ToolRegistry` 读取 `implementation_ref`，并强制：

```text
存在且 enabled
同一 ID 只能解析出一个 enabled version
implementation_ref 满足对应 Protocol
```

任一失败都 fail closed；M5 不允许自行替换成别的 Skill / Workflow / Tool。

因此：

```text
B-M5-005 = FIX_IMPLEMENTED
```

## 7. 明确不改变的边界

本 Fix Pack 不修改：

```text
ApprovedActionPlan
ExecutionEngine frozen interface
ExecutionResult top-level Canonical Contract
RuntimeOrchestrator EXECUTE stage
M4 planning semantics
M6 truth validation boundary
```

也不实现：

```text
真实 Tool 调用
真实 Skill 执行
真实 Workflow 推进
Retry / Timeout engine
Cancellation handler
Checkpoint persistence implementation
Crash Recovery
Resource locking implementation
```

这些属于 M5-IU 实现。

## 8. 文档对齐

M5 V2.0 同步收口：

```text
business_result → business_outputs[]
ToolStatus 增加 UNKNOWN
ToolDefinition 使用 idempotency_mode / required_permissions / resource_locks
WorkflowDefinition 增加 checkpoint / timeout / resume metadata
```

以当前 Canonical Contract / Registry 名称为准。

## 9. Fix Pack Verification Gate

合并前必须运行：

```text
python -m pytest tests -q
python -m mypy runtime tests
python -m ruff check runtime tests
python -m ruff format --check runtime tests
```

并独立复核：

```text
1. Canonical ApprovedActionPlan / ExecutionResult 未被改写
2. optional Registry 字段保持向后兼容
3. UNKNOWN 不被当 FAILED
4. M5 control signal 不拥有 priority 决策权
5. store protocols 不绑定具体基础设施
6. implementation resolver 不做 capability substitution
7. Core 未硬编码业务 Skill / Tool / Workflow 值
```

全部满足后才允许：

```text
M5 IMPLEMENTATION READINESS = READY
M5-IU1 = ALLOWED TO START
```