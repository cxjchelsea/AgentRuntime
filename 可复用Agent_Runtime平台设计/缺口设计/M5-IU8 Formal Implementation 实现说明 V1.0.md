# M5-IU8 Formal Implementation 实现说明 V1.0

> Scope：M5 Execution Framework Step 10 — Concurrency / Resource Lock。
> Baseline：M5-IU8 Implementation Readiness Re-Review = PASSED；Implementation Readiness = READY @ 611f2fb29e7526b64e12e5a2e388ecf1fa793a27。

## 1. 本轮正式实现

正式接入：

~~~text
ExecutionConcurrencyRuntime
- session execution admission
- same-session BUSY / UNKNOWN fail-closed
- authoritative terminal execution session-release hook

ToolConcurrencyRuntime
- exact IU7 Tool operation identity
- runtime resource projection
- canonical lock-set acquire
- exact operation-resource binding
- normal completion release
- IU7 CONFIRMED_STOPPED release

CoreApprovedToolInvoker
- baseline physical Tool path
- IU6 reliability / retry physical Tool path
- shared physical admission/completion boundary

ExecutionControlCoordinator
- CONFIRMED_STOPPED Tool resource cleanup
- control terminal session release observer

ExecutionLifecycleService
- normal terminal execution observer
~~~

## 2. Session execution admission

正式 external owner 执行前：

~~~text
ExecutionContext
↓
ExecutionConcurrencyRuntime.admit
↓
SessionExecutionLockCoordinator.acquire
~~~

结果：

~~~text
ADMITTED -> 可继续真实 external execution
BUSY -> BLOCKED / SESSION_EXECUTION_LOCK_BUSY -> Skill / Workflow 不执行
UNKNOWN -> UNKNOWN -> 不执行真实 side effect
~~~

BUSY 不触发 CANCEL / PREEMPT，也不重新计算 M2 priority。CapabilityExecutionOwner.NONE 不占 session execution lock，因为该路径没有 external capability side effect。

## 3. Session lease 终态释放

普通执行终态：

~~~text
ExecutionLifecycleService.finish_execution
↓
先完成 authoritative lifecycle transition
↓
持久化 ExecutionRecord
↓
ExecutionTerminalObserver
↓
ExecutionConcurrencyRuntime.on_terminal_execution
↓
SessionExecutionLockCoordinator.release_if_terminal
~~~

控制终态通过 ExecutionControlLifecycleService.terminalize 后，由 ExecutionControlCoordinator 调用 terminal observer 完成 session release。

Observer 异常不会反向撤销已持久化的 terminal lifecycle，因此 lifecycle truth != session-release side authority。release uncertainty 只保留 lock，不伪造 execution 未终态。

## 4. 统一 physical Tool admission boundary

baseline 与 IU6 reliability 路径统一通过：

~~~text
_begin_physical_tool_operation()
_complete_physical_tool_operation()
~~~

正式 admission：

~~~text
exact resolved Tool
↓
input validation
↓
current execution permission
↓
IU6 reliability/idempotency preflight（如启用）
↓
ToolConcurrencyRuntime.admit
↓
exact IU7 operation_handle_id
↓
ToolResourceLockProjector
↓
ResourceLockSetCoordinator
↓
exact ResourceLockOwner
owner_id = Tool operation_handle_id
↓
IU7 Tool in-flight registration
↓
OperationResourceLeaseBinding
↓
physical Tool invoke
~~~

任何 BUSY / UNKNOWN / projection/acquire/register/binding failure 均禁止 physical invoke。

## 5. Baseline physical Tool path

CoreApprovedToolInvoker.execute_physical_attempt() 已接入统一 concurrency boundary。resource BUSY 时 Tool 不调用；real Tool completion 后完成 exact IU7 Tool handle 并释放 exact resource leases；completion/release uncertainty 会降级为 UNKNOWN。

## 6. IU6 reliability / retry path

_execute_reliable_tool_attempt() 已使用同一个 admission/completion boundary。每个 physical_attempt 都拥有独立 exact Tool operation_handle_id、ResourceLockOwner、lock-set acquisition 与 OperationResourceLeaseBinding。

新增行为门禁直接验证：

~~~text
attempt 1 -> real FAILED -> exact resource release
attempt 2 -> reacquire -> real SUCCESS -> exact resource release
~~~

两次 attempt 完成后无 active Tool handle、无 active resource lease、无 stale operation-resource binding。

~~~text
FI-M5-IU8-REQ-001
RELIABLE_TOOL_PATH_MUST_SHARE_EXACT_INFLIGHT_RESOURCE_BOUNDARY
= CLOSED
~~~

## 7. Timeout / UNKNOWN

IU6 timeout runner 只证明等待边界，不证明底层 Tool 停止。因此 TIMED_OUT / timeout UNKNOWN 不调用 physical completion cleanup：exact Tool handle、OperationResourceLeaseBinding 与 resource lease 均保持 active/held。

这延续 IU7 不变量：executor returned != underlying operation stopped。没有 finally-release。

## 8. CANCEL / PREEMPT + CONFIRMED_STOPPED

IU7 生成 HierarchicalInterruptSummary 后，IU8 只消费 exact Tool 的 CONFIRMED_STOPPED：先 complete/remove exact IU7 Tool handle，再 locate exact OperationResourceLeaseBinding，再 release exact resource leases。

ALREADY_COMPLETED / NOT_CANCELLABLE / UNKNOWN / AMBIGUOUS 仍不授权 speculative release。

## 9. Post-acquire admission failure

如果 lock set 已 acquire，但 Tool handle registration / operation-resource binding 失败且 physical invoke 尚未开始，则结果为 UNKNOWN、physical invoke 被禁止、retained lease evidence 保留。

Formal Implementation 不盲目释放整个 successful lease set，因为其中可能包含 exact ALREADY_ACQUIRED replay lease。crash/stale reclaim 仍由 IU9 负责。

## 10. Exact Tool identity re-validation

ToolConcurrencyRuntime.admit() 再次验证 ToolDefinition.tool_id/version 与 exact tool_id/version。一旦不匹配：UNKNOWN / TOOL_CONCURRENCY_DEFINITION_IDENTITY_MISMATCH，且不获取锁、不注册 Tool handle、不进行 physical invoke。

## 11. Independent Implementation Review findings

### F-M5-IU8-FI-001 TERMINAL_OBSERVER_FAILURE_COULD_ESCAPE_AFTER_LIFECYCLE_COMMIT

已修复：terminal observer failure 在 authoritative persistence 之后被隔离；session lock 保持 fail-closed，lifecycle truth 不回滚。状态：CLOSED。

### F-M5-IU8-FI-002 CONTROL_TERMINAL_OBSERVER_FAILURE_COULD_ESCAPE

已修复：控制终态同样隔离 terminal observer failure。状态：CLOSED。

### F-M5-IU8-FI-003 TOOL_CONCURRENCY_DEFINITION_IDENTITY_NOT_REVALIDATED

已修复：正式 concurrency boundary 增加 exact ToolDefinition id/version re-validation。状态：CLOSED。

### FI-M5-IU8-REQ-001 RELIABLE_TOOL_PATH_MUST_SHARE_EXACT_INFLIGHT_RESOURCE_BOUNDARY

baseline + reliability path 已统一，并增加真实 retry 两 attempt 行为门禁。状态：CLOSED。

## 12. Explicit non-goals

~~~text
parallel Step scheduler
priority recomputation
automatic PREEMPT on BUSY
lock stealing
lease expiry
stale lock reclaim
durable lease persistence
cross-process fencing
Checkpoint / Crash Recovery
Workflow resume
Execution aggregation
M6
Runtime new-cycle start after PREEMPT
~~~

对应后续：durable locking / checkpoint / recovery / resume -> M5-IU9；Execution aggregation -> M5-IU10；M6 -> after M5 closure。

## 13. Formal behavior tests

正式测试 tests/test_m5_iu8_formal_implementation.py 覆盖 same-session BUSY、normal terminal session release、baseline Tool lock、reliability timeout retention、retry 多 physical attempt、CONFIRMED_STOPPED cleanup、normal/control observer failure isolation、ToolDefinition identity mismatch 等场景。

## 14. Verified closure candidate

~~~text
exact code head = ef8b926f5fe7e3fe82914ded7c897148b022aad1
GitHub Actions run = 35809954815

pytest = PASSED
754 passed, 1 existing warning

mypy = PASSED
Success: no issues found in 195 source files

ruff check = PASSED
All checks passed!

ruff format --check = PASSED
195 files already formatted
~~~

The warning is the existing Pydantic deprecation warning and is unrelated to IU8.

## 15. Current status

~~~text
M5-IU8 IMPLEMENTATION READINESS RE-REVIEW = PASSED
M5-IU8 IMPLEMENTATION READINESS = READY

M5-IU8 FORMAL IMPLEMENTATION = CODE COMPLETE
M5-IU8 INDEPENDENT IMPLEMENTATION REVIEW = PASSED
M5-IU8 VERIFICATION = PASSED
M5-IU8 = PASSED

F-M5-IU8-FI-001 = CLOSED
F-M5-IU8-FI-002 = CLOSED
F-M5-IU8-FI-003 = CLOSED
FI-M5-IU8-REQ-001 = CLOSED

NEW BLOCKER = NONE
M5 = IN PROGRESS

NEXT REQUIRED =
M5-IU9
Step 11 — Persistence / Checkpoint / Recovery
~~~

This does not close M5 as a whole.