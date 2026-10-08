# M5-IU2 Targeted Fix V1.0

> 适用范围：M5-IU2 Independent Review 发现的 1 个阻塞项与 1 个非阻塞语义债。
> 本修复不改 Canonical Contract，不改 ExecutionEngine，不进入 Capability Resolution、Tool / Skill / Workflow Execution、Permission Enforcement、M6。

## 1. Review 发现

阻塞项：

```text
B-M5-IU2-001
UNKNOWN SAFETY LOCK MAY BE SILENTLY ALLOWED
```

非阻塞项：

```text
TD-M5-IU2-01
StepScheduleStatus.COMPLETE
!=
ExecutionPlanStatus.SUCCESS
```

## 2. TF-M5-IU2-01：Safety Lock 三态收口

原实现的 `RuntimeExecutionSnapshot.safety_lock` 类型本来就是：

```text
bool | None
```

即：

```text
true
false
unknown
```

但原 `RuntimeExecutionChecker` 只处理 `true`，导致 `None` 可能继续通过 Policy / State check 并最终得到 `ALLOWED`。

现在正式冻结：

```text
safety_lock = true
+ restricted_actions 命中当前 action
→ BLOCKED

safety_lock = true
+ restricted_actions 不可得
→ UNKNOWN

safety_lock = false
→ 继续后续检查

safety_lock = None
→ UNKNOWN
reason = SAFETY_LOCK_STATE_UNKNOWN
```

因此：

```text
Unknown Safety
!=
No Safety Lock
!=
Allowed
```

```text
B-M5-IU2-001 = FIX_IMPLEMENTED
```

## 3. TF-M5-IU2-02：Scheduler COMPLETE 语义澄清

`StepScheduleStatus.COMPLETE` 只表示：

```text
当前没有剩余 PENDING Step
调度工作结束
```

它不表示：

```text
Execution 成功
Business 成功
M6 已验证
```

正式冻结：

```text
StepScheduleStatus.COMPLETE
!=
ExecutionPlanStatus.SUCCESS
```

最终：

```text
SUCCESS
PARTIAL_SUCCESS
FAILED
```

必须由后续 Execution Aggregator 根据所有 Step 结果决定。

因此：

```text
TD-M5-IU2-01 = CLOSED_AS_DOCUMENTED_SEMANTIC
```

## 4. Regression Gate

必须验证：

```text
1. safety_lock=None -> UNKNOWN
2. safety_lock=False 仍可继续后续检查
3. safety_lock=True + restricted action -> BLOCKED
4. safety_lock=True + restricted_actions unknown -> UNKNOWN
5. UNKNOWN 不得升级为 ALLOWED
6. Scheduler COMPLETE 不被定义为 Execution success
7. 不新增 Capability Resolver / Tool / Skill / Workflow / M6 调用
```

并运行：

```text
python -m pytest tests -q
python -m mypy runtime tests
python -m ruff check runtime tests
python -m ruff format --check runtime tests
```

四项全绿并完成 Targeted Independent Re-Review 后，才允许：

```text
M5-IU2 = PASSED
```
