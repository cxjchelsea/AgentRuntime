# M5-IU1 Targeted Fix V1.0

> 适用范围：M5-IU1 Independent Review 发现的两个阻塞项。
> 本修复不改 Canonical Contract、不改 ExecutionEngine、不进入 Scheduler / Capability / Tool / Permission / Retry / Cancel / M6。

## 1. 阻塞项

```text
B-M5-IU1-001
ExecutionContext.step_state duplicates lifecycle truth

B-M5-IU1-002
Lifecycle transitions are not persisted to ExecutionStateStore
```

## 2. TF-M5-IU1-01：单一 Lifecycle Truth

`ExecutionContext.step_state` 不再保存 `PENDING / RUNNING / SUCCESS / FAILED` 等动态执行状态。

现在它只保留静态 Plan/Capability 投影：

```text
step_id ->
  action
  skill_id
  workflow_id
```

动态 Step 生命周期的唯一权威来源冻结为：

```text
PreparedExecution.steps
+
ExecutionRecord.step_results
```

因此后续执行组件不得把 `ExecutionContext.step_state` 当作当前执行状态。

```text
B-M5-IU1-001 = FIX_IMPLEMENTED
```

## 3. TF-M5-IU1-02：Lifecycle Persistence Boundary

`ExecutionLifecycleManager` 保持纯函数式状态转换职责，不直接依赖 Store。

新增：

```text
ExecutionLifecycleService
```

正式运行时 mutation path：

```text
PreparedExecution
↓
ExecutionLifecycleManager transition
↓
ExecutionLifecycleService
↓
ExecutionStateStore.save(latest ExecutionRecord)
↓
updated PreparedExecution
```

Service 覆盖：

```text
start_execution
start_step
finish_step
finish_execution
```

因此每个 authoritative lifecycle transition 都会同步持久化最新 `ExecutionRecord`。

`InMemoryExecutionStateStore.save` 同时拒绝 `updated_at` 倒退，避免旧 observation 覆盖新状态。

```text
B-M5-IU1-002 = FIX_IMPLEMENTED
```

## 4. 文档残留修复

原实现说明链路中的：

```text
ExecutionStateStore.save
```

已经修订为：

```text
ExecutionCreationStore.create（原子创建）
```

并明确初始化创建与后续 lifecycle persistence 是两个不同职责：

```text
create = 首次原子创建
save   = 后续最新 observation 持久化
```

因此：

```text
TD-M5-IU1-01 = CLOSED
```

## 5. Verification Gate

必须验证：

```text
1. ExecutionContext.step_state 不含动态 status
2. PreparedExecution.steps / ExecutionRecord.step_results 状态一致
3. start_execution 后 Store = RUNNING
4. start_step 后 Store current_step/status 已更新
5. finish_step 后 Store Step 终态已更新
6. finish_execution 后 Store = terminal
7. stale ExecutionRecord 不得覆盖较新的 observation
8. 不新增 Skill / Workflow / Tool / M6 调用
```

并运行：

```text
python -m pytest tests -q
python -m mypy runtime tests
python -m ruff check runtime tests
python -m ruff format --check runtime tests
```

四项全绿并完成 Targeted Re-Review 后，才允许：

```text
M5-IU1 = PASSED
```