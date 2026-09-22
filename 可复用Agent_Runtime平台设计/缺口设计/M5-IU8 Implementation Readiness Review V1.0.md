# M5-IU8 Implementation Readiness Review V1.0

> Review target：M5-IU8 Concurrency / Resource Lock。
> Baseline：M5-IU1～IU7 = PASSED；M5 Remaining IU Mapping 已冻结。
> 本 Review 只判断是否具备安全进入 IU8 Formal Implementation 的合同，不实现 Resource Lock runtime。

## 1. Readiness conclusion

~~~text
M5-IU8 IMPLEMENTATION DESIGN = COMPLETE
M5-IU8 INDEPENDENT DESIGN REVIEW = PASSED
M5-IU8 IMPLEMENTATION READINESS = NOT_READY

BLOCKERS = 5
FORMAL IMPLEMENTATION = NOT AUTHORIZED
NEW BLOCKER = NONE
~~~

当前仓库已有：

~~~text
ToolDefinition.resource_locks
ResourceLockProvider.acquire/release
IU7 live in-flight operation identity
IU7 interrupt / control lifecycle
IU6 idempotency / retry / timeout evidence
~~~

但这些基础还不能安全证明具体资源身份、exact acquisition owner、多锁完整获得、真实 operation 终止与 session concurrency authority。

## 2. B-M5-IU8-001 RESOURCE_LOCK_AUTHORITY_NOT_AUDITABLE

当前：

~~~text
ResourceLockProvider.acquire(...) -> bool
ResourceLockProvider.release(...) -> None
~~~

无法表达：

~~~text
ACQUIRED
ALREADY_ACQUIRED
BUSY
UNKNOWN

RELEASED
ALREADY_RELEASED
NOT_OWNER
UNKNOWN
~~~

也没有 immutable acquisition_id / lease / acquired_at / exact owner provenance。

因此无法安全完成 same-request replay、wrong-owner release rejection、wrong-acquisition rejection、release audit 和 provider uncertainty fail-closed。

结论：

~~~text
B-M5-IU8-001 = OPEN
REQUIRES CA-M5-IU8-01
~~~

## 3. B-M5-IU8-002 RUNTIME_RESOURCE_IDENTITY_UNRESOLVED

当前 ToolDefinition 已有：

~~~text
resource_locks: list[str] | None
~~~

但静态 Registry 字符串不足以直接代表具体 runtime resource。

例如 speaker / playback / microphone，如果 Core 直接把这些字符串作为 lock key，会造成所有设备共享同一 global lock；如果 Core 自行拼接 user/device 规则，又会污染 Core/Domain 边界。

当前缺少：

~~~text
ResourceLockRequirement
ResolvedResourceLock
ResourceLockRequirementResolver
~~~

把：

~~~text
static resource_ref
+
ExecutionContext / Tool invocation identity
~~~

投影为 opaque concrete runtime lock_key。

结论：

~~~text
B-M5-IU8-002 = OPEN
REQUIRES CA-M5-IU8-02
~~~

## 4. B-M5-IU8-003 MULTI_LOCK_ORDER_AND_PARTIAL_ROLLBACK_MISSING

一个 Tool 可以声明多个 resource_locks。

当前没有 canonical lock ordering、deduplication、all-or-none lock-set outcome、partial acquire rollback、rollback uncertainty。

因此可能出现：

~~~text
A: lock-1 -> lock-2
B: lock-2 -> lock-1
~~~

导致死锁。

也可能出现：

~~~text
lock-1 acquired
lock-2 busy
~~~

但 lock-1 被遗留。

需要冻结：

~~~text
ResourceLockSetCoordinator
canonical lock_key total order
reverse rollback
rollback UNKNOWN -> whole outcome UNKNOWN
~~~

结论：

~~~text
B-M5-IU8-003 = OPEN
REQUIRES CA-M5-IU8-02
~~~

## 5. B-M5-IU8-004 LOCK_RELEASE_AUTHORITY_NOT_OPERATION_BOUND

IU7 已经证明：

~~~text
executor returned
!=
underlying operation stopped
~~~

尤其 Tool timeout / Skill timeout / Workflow WAITING / interrupt requested 都不能直接证明真实 operation 已停止。

如果 IU8 使用：

~~~text
try:
    await tool.invoke()
finally:
    release(lock)
~~~

则 timeout / unknown 情况会提前放开资源，让第二个 operation 在第一个仍可能运行时进入真实副作用。

当前 ResourceLock 合同也没有和 IU7 InFlightOperation / exact physical attempt 建立 provenance 绑定。

需要冻结：

~~~text
physical-operation lock owner identity
definitive completion release authority
CONFIRMED_STOPPED release authority
TIMEOUT / UNKNOWN -> retain lock
NOT_CANCELLABLE -> retain lock
ALREADY_COMPLETED -> wait for real completion observation
~~~

结论：

~~~text
B-M5-IU8-004 = OPEN
REQUIRES CA-M5-IU8-03
~~~

## 6. B-M5-IU8-005 SESSION_EXECUTION_LOCK_AUTHORITY_MISSING

M5 V2.0 明确要求至少存在：

~~~text
session_execution_lock
~~~

当前代码没有正式 authority 在 execution active boundary 上 acquire session lock、hold for whole execution、并仅在 authoritative terminal boundary 后 release。

因此两个来自同一 session 的 execution 理论上仍可同时进入真实 Step 执行。

需要冻结：

~~~text
SessionExecutionLockCoordinator
session_id -> exact lock identity
execution_id -> owner
BUSY / UNKNOWN fail-closed outcome
terminal execution release boundary
~~~

并明确：

~~~text
lock BUSY != PREEMPT
~~~

IU8 不自行决定谁优先。

结论：

~~~text
B-M5-IU8-005 = OPEN
REQUIRES CA-M5-IU8-03
~~~

## 7. Existing contracts that are reusable

以下已有基础方向正确，不是 blocker：

~~~text
ToolDefinition.resource_locks
ResourceLockProvider seed protocol
ExecutionContext.session_id
ExecutionContext.execution_id
Step execution identity
logical tool_call_id
physical_attempt
IU6 exact retry/idempotency evidence
IU7 InFlightOperationHandle
IU7 InFlightOperationRegistry
IU7 CONFIRMED_STOPPED / ALREADY_COMPLETED / NOT_CANCELLABLE / UNKNOWN
IU7 control latch and lifecycle terminalization
~~~

IU8 不应创建第二套 operation identity。

## 8. Design review findings

独立复核重点：

~~~text
Core / Domain boundary
IU7 operation truth compatibility
IU6 retry / idempotency ordering
IU9 durable recovery boundary
IU10 aggregation boundary
M2 priority ownership
~~~

结果：

### 8.1 Resource identity 不硬编码领域

设计把 ToolDefinition.resource_locks 解释为 resource_ref，并通过 injected resolver 生成 concrete lock_key。

~~~text
Core does not hardcode speaker/playback/device rules
~~~

通过。

### 8.2 Lock conflict 不升级为 priority decision

~~~text
BUSY
!= PREEMPT
!= CANCEL
!= priority comparison
~~~

通过。

### 8.3 timeout 不错误释放锁

~~~text
timeout observed
!= underlying operation stopped
~~~

并与 IU7 owner-retention 规则一致。

通过。

### 8.4 Multi-lock deadlock 有明确治理

通过 canonical total order + reverse rollback 处理，不发明并发图调度。

通过。

### 8.5 Durable recovery 未提前进入

设计明确不做 lease expiry / stale lock reclaim / fencing across process restart / durable persisted lease。

这些继续属于 IU9。

通过。

## 9. Independent Design Review Decision

~~~text
M5-IU8 IMPLEMENTATION DESIGN = COMPLETE
M5-IU8 INDEPENDENT DESIGN REVIEW = PASSED

DESIGN BLOCKER = NONE
NEW BLOCKER = NONE
~~~

Design review PASSED 只表示设计边界合理，不代表当前代码已具备实现条件。

## 10. Controlled Amendment plan

### CA-M5-IU8-01 Lock Identity + Typed Acquire/Release Authority

关闭：

~~~text
B-M5-IU8-001
RESOURCE_LOCK_AUTHORITY_NOT_AUDITABLE
~~~

### CA-M5-IU8-02 Runtime Resource Projection + Multi-Lock Set

关闭：

~~~text
B-M5-IU8-002
RUNTIME_RESOURCE_IDENTITY_UNRESOLVED

B-M5-IU8-003
MULTI_LOCK_ORDER_AND_PARTIAL_ROLLBACK_MISSING
~~~

### CA-M5-IU8-03 Session Lock + Operation-Bound Release

关闭：

~~~text
B-M5-IU8-004
LOCK_RELEASE_AUTHORITY_NOT_OPERATION_BOUND

B-M5-IU8-005
SESSION_EXECUTION_LOCK_AUTHORITY_MISSING
~~~

## 11. Readiness Re-Review Gate

只有以下全部满足，才能写：

~~~text
M5-IU8 IMPLEMENTATION READINESS = READY
~~~

条件：

~~~text
1. CA-M5-IU8-01 Targeted Review = PASSED
2. CA-M5-IU8-01 four local gates = GREEN
3. CA-M5-IU8-02 Targeted Review = PASSED
4. CA-M5-IU8-02 four local gates = GREEN
5. CA-M5-IU8-03 Targeted Review = PASSED
6. CA-M5-IU8-03 four local gates = GREEN
7. B-M5-IU8-001～005 全部 CLOSED
8. no silent lock stealing
9. lock acquire UNKNOWN -> no physical side effect
10. partial lock-set acquire cannot leak confirmed-free assumptions
11. timeout/UNKNOWN operation cannot release exclusive resource
12. IU7 active operation and IU8 lease provenance remain consistent
13. session lock BUSY does not recompute priority
14. no new parallel scheduler invented
15. IU9 durable recovery boundary not entered
16. IU10/M6 boundary not entered
~~~

## 12. Current Formal Status

~~~text
M5-IU1 = PASSED
M5-IU2 = PASSED
M5-IU3 = PASSED
M5-IU4 = PASSED
M5-IU5 = PASSED
M5-IU6 = PASSED
M5-IU7 = PASSED

M5-IU8 IMPLEMENTATION DESIGN = COMPLETE
M5-IU8 INDEPENDENT DESIGN REVIEW = PASSED
M5-IU8 IMPLEMENTATION READINESS = NOT_READY

B-M5-IU8-001 = OPEN
B-M5-IU8-002 = OPEN
B-M5-IU8-003 = OPEN
B-M5-IU8-004 = OPEN
B-M5-IU8-005 = OPEN

NEW BLOCKER = NONE

NEXT REQUIRED =
CA-M5-IU8-01
Lock Identity + Typed Acquire/Release Authority

M5 = IN PROGRESS
~~~
