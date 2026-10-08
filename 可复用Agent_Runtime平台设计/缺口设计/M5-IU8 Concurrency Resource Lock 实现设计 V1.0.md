# M5-IU8 Concurrency / Resource Lock 实现设计 V1.0

> Mapping：M5-IU8 = M5 V2.0 Step 10。
> Baseline：M5-IU1～IU7 = PASSED。
> Goal：在不重新规划、不引入新的业务优先级、不提前进入 IU9 Recovery 的前提下，为跨 execution / Tool physical attempt 提供可审计、fail-closed 的并发互斥与资源占用边界。

## 1. IU8 正式目标

M5-IU8 解决：

~~~text
多个 execution / operation 可能同时存在
        ↓
哪些 execution 可以同时运行
        ↓
哪些真实资源不能被同时占用
        ↓
谁拥有锁
        ↓
何时真正获得锁
        ↓
何时可以安全释放锁
        ↓
冲突 / 不确定时如何 fail closed
~~~

正式链路：

~~~text
Execution / Physical Tool Attempt
        ↓
resolve lock requirements
        ↓
resolve concrete runtime lock identities
        ↓
deterministic lock-set acquisition
        ↓
all acquired ?
   ├─ no  -> BUSY / UNKNOWN / rollback acquired subset
   └─ yes -> physical operation may start
        ↓
operation reaches authoritative terminal boundary
        ↓
release exact leases
~~~

核心不变量：

~~~text
declared resource lock != concrete runtime lock identity
acquire requested != lock acquired
function returned != underlying operation stopped
timeout observed != resource safe to release
release requested != release confirmed
lock conflict != permission denied
lock conflict != preemption decision
resource lock != durable recovery
~~~

## 2. Existing baseline

仓库已有两个 seed contracts：

~~~text
ToolDefinition.resource_locks: list[str] | None

ResourceLockProvider
- acquire(resource_id, owner_id) -> bool
- release(resource_id, owner_id) -> None
~~~

它们证明 Resource Lock 已经属于 M5 边界，但不足以直接进入 Formal Implementation。

原因：

~~~text
bool acquire 无法区分：
- acquired
- exact replay
- busy
- provider unknown

release(None) 无法证明：
- 谁释放了哪一次 acquisition
- 是否重复释放
- 是否 wrong-owner
- release 是否真实成功
~~~

因此现有 ResourceLockProvider 只能视为 readiness seed，不是 IU8 最终 authority contract。

## 3. IU8 不负责什么

IU8 不做：

~~~text
重新计算 M2 priority
决定 CANCEL / PREEMPT
修改 ApprovedActionPlan
根据业务语义猜测资源
自动重放 Tool
Checkpoint
Crash Recovery
Workflow resume
Execution aggregation
M6 validation
启动新的 Runtime cycle
~~~

资源冲突只回答：

~~~text
当前 operation 是否获得了执行所需的互斥资源
~~~

它不回答谁更重要、谁应该被抢占、应该如何重新规划。

## 4. Session Execution Lock

M5 V2.0 要求至少存在 session_execution_lock。

IU8 第一版冻结为保守模型：

~~~text
同一个 session_id
同一时刻最多一个 active execution 持有 session execution lease
~~~

owner = execution_id。

第二个 execution 如果无法获取 session lock：

~~~text
BUSY
-> 当前 execution 不得开始真实 Step side effect
-> 不自行 PREEMPT 旧 execution
-> 交回 Runtime / 上层决定
~~~

跨 session 是否可以并发，由具体 resource locks 决定。

## 5. Tool Resource Lock 声明

Tool Registry 已存在：

~~~text
ToolDefinition.resource_locks
~~~

IU8 将其中字符串正式解释为 resource lock reference，而不是直接解释成最终 runtime lock key。

例如 speaker / playback / notification_channel 只表示 Tool 需要某类资源。

Core 不得自行硬编码：

~~~text
speaker:<device_id>
playback:<user_id>
~~~

## 6. Runtime Resource Identity Resolution

新增建议合同：

~~~text
ResourceLockRequirement
- resource_ref
- tool_id
- tool_version

ResolvedResourceLock
- lock_key
- resource_ref
- provenance

ResourceLockRequirementResolver
~~~

输入：

~~~text
ToolDefinition.resource_locks
ExecutionContext
Tool invocation identity
~~~

输出 exact concrete lock keys。

规则：

~~~text
same real resource -> same lock_key
different real resource -> different lock_key
~~~

lock_key 对 Core 是 opaque identity。

具体如何由 device / session / identity / tenant / external resource id 生成 lock key，由注入式 resolver / Domain Adapter 负责。Core 不解析领域字符串 DSL。

## 7. Lock Owner Identity

资源锁 owner 必须绑定到一次真实 operation，而不是模糊的 Tool 名称。

Tool lock owner 至少需要：

~~~text
execution_id
step_execution_id
tool_call_id
physical_attempt
~~~

建议冻结：

~~~text
ResourceLockOwner
- owner_id
- execution_id
- step_execution_id
- tool_call_id?
- physical_attempt?
~~~

其中 session_execution_lock owner = execution_id；physical Tool resource owner = exact physical attempt identity。

禁止 owner_id = tool_id / skill_id。

## 8. Typed Acquire Authority

新增：

~~~text
ResourceLockAcquireStatus
- ACQUIRED
- ALREADY_ACQUIRED
- BUSY
- UNKNOWN

ResourceLockLease
- lock_key
- owner_id
- acquisition_id
- acquired_at

ResourceLockAcquireRequest
- lock_key
- owner_id
- acquisition_id
- requested_at

ResourceLockAcquireDecision
- status
- reason_codes
- lease?
~~~

ACQUIRED 表示 exact acquisition 已获得锁。

ALREADY_ACQUIRED 仅允许 same acquisition_id + same owner_id + same lock_key 的 exact replay。

BUSY 表示锁已被其他 acquisition 占用，受保护 operation 不得执行。

UNKNOWN 表示无法证明锁是否拿到，必须 fail closed，不执行 physical side effect。

## 9. No Silent Stealing

IU8 第一版正式冻结：

~~~text
no silent lock stealing
~~~

即使旧 owner 看起来超时或 execution 看起来卡住，也不能直接覆盖锁，因为：

~~~text
timeout observed != old operation stopped
~~~

租约过期、fencing token、进程崩溃后的 reclaim 需要 durable time / persistence / recovery authority，属于 IU9。

## 10. Deterministic Multi-Lock Acquisition

一个 Tool 可以声明多个 resource_locks。

不同顺序获取可能死锁，因此第一版冻结：

~~~text
1. resolve all concrete lock keys
2. 去重
3. 按 canonical lock_key 全序排序
4. 按相同顺序 acquire
~~~

新增建议 ResourceLockSetCoordinator。

只有所有锁全部获得后，physical Tool attempt 才允许开始。

## 11. Partial Acquire Rollback

例如：

~~~text
acquire A = ACQUIRED
acquire B = BUSY
~~~

必须 release A，然后 physical Tool 不执行。

rollback 顺序为 reverse acquisition order。

如果 rollback release 本身返回 UNKNOWN：

~~~text
whole lock-set result = UNKNOWN
~~~

不能假装只是 BUSY，因为 Core 已无法证明 A 是否释放。

## 12. Typed Release Authority

新增：

~~~text
ResourceLockReleaseStatus
- RELEASED
- ALREADY_RELEASED
- NOT_OWNER
- UNKNOWN

ResourceLockReleaseDecision
- status
- reason_codes
- lease
~~~

release 必须消费 exact ResourceLockLease，而不是只传 resource_id + owner_id。

wrong acquisition / wrong owner 不得 silent success。

## 13. Physical Operation Lifetime Binding

这是 IU8 最关键的不变量之一。

Resource lock 生命周期绑定 physical operation lifetime，而不是 Python await expression lifetime。

### definitive normal completion

Tool invoke 已真实返回/抛出并确定 coroutine 已结束 -> lock may release。

### IU7 CONFIRMED_STOPPED

interrupt authority 已确认 operation 停止 -> lock may release。

### TIMEOUT / UNKNOWN

如果 timeout runner 只能说明等待超时，而不能证明底层 Tool 已停止：

~~~text
DO NOT RELEASE
~~~

锁必须保留为 active/uncertain。

这和 IU7 的：

~~~text
executor returned != underlying operation stopped
~~~

完全一致。

## 14. Lock Release after CANCEL / PREEMPT

IU7 负责 control signal / interrupt authority / CONFIRMED_STOPPED。

IU8 负责被确认停止的 operation 对应资源 lease 的释放。

因此：

~~~text
CANCEL/PREEMPT signal != release authority
interrupt requested != release authority
CONFIRMED_STOPPED -> release can be authorized
~~~

ALREADY_COMPLETED 必须先有真实 completion observation，再释放。

NOT_CANCELLABLE / UNKNOWN -> lock remains held。

## 15. Session Lock Lifetime

session execution lock 生命周期：

~~~text
Execution enters active execution boundary
        ↓
acquire session lease
        ↓
execute Steps
        ↓
Execution reaches authoritative terminal boundary
        ↓
release session lease
~~~

不能因为某一个 Step 完成就释放。

如果 execution 状态未知或 crash，不自动猜测 release；durable recovery 属于 IU9。

## 16. Read-only / Parallel Work

M5 V2.0 提到只读 Tool 可根据 tool_plan.execution_mode 决定是否并发，但当前 ApprovedActionPlan.tool_plan 仍是 dict[str, Any] | None，当前 Step Scheduler 也保持顺序执行。

因此冻结：

~~~text
IU8 controls safety under concurrency
IU8 does not introduce a new parallel scheduler
~~~

现有并发来源可以包括 different Runtime cycles / sessions / executions / callbacks。

没有资源锁要求的 read-only Tool，IU8 不额外增加 resource serialization。

是否主动 parallelize 同一 plan 的 Steps，必须等待已有明确调度 authority，不由 IU8 猜测。

## 17. Resource Lock 与 Permission / Idempotency 顺序

推荐 physical Tool gate 顺序：

~~~text
exact Tool resolution
↓
input validation
↓
execution permission
↓
IU6 idempotency / replay preflight
↓
resolve concrete resource lock set
↓
acquire all locks
↓
register / observe physical in-flight operation
↓
Tool.invoke
↓
result / timeout / interrupt observation
↓
release only at authoritative operation terminal boundary
~~~

permission denied / input invalid / idempotency completed replay 都不应无意义占用真实资源锁。

## 18. Lock Conflict Outcome

IU8 不把锁冲突自动映射为 FAILED / CANCELLED / PREEMPTED。

建议内部 typed outcome：

~~~text
ConcurrencyDisposition
- ACQUIRED
- BUSY
- UNKNOWN
~~~

BUSY 只表示当前执行没有获得资源执行权。

后续是否等待、终止、回 Runtime，属于 M5 orchestration / Formal Implementation 决策；IU8 不根据锁冲突自行重排 ApprovedActionPlan。

## 19. IU8 与 IU7 的关系

IU7 已完成 live operation identity / interrupt authority / control terminalization。

IU8 必须复用而不是建立第二套 operation truth。

正式关系：

~~~text
IU7 InFlightOperation
        ↕
IU8 ResourceLockLease
~~~

二者必须绑定同一次 physical operation provenance。

禁止：

~~~text
Tool 已被 IU7 视为仍 active
但 IU8 已释放其 exclusive resource
~~~

## 20. IU8 与 IU9 的边界

IU8 可以实现：

~~~text
live in-memory locking
typed acquire/release authority
session execution lock
resource lock set ordering
operation-bound lock lifetime
~~~

IU9 才负责：

~~~text
durable lock state
process restart
crash recovery
persisted lease
stale lock reclamation
fencing token across processes
lease expiry based recovery
~~~

IU8 不用定时自动解锁掩盖 crash-recovery 缺口。

## 21. Planned tests

至少覆盖：

~~~text
1. exact acquire -> ACQUIRED
2. exact acquire replay -> ALREADY_ACQUIRED
3. same lock different owner -> BUSY
4. provider uncertainty -> UNKNOWN / no physical Tool call
5. resource_ref resolves to exact runtime lock_key
6. unresolved resource_ref -> UNKNOWN / fail closed
7. multiple locks always canonical order
8. partial acquire BUSY -> reverse rollback
9. rollback UNKNOWN -> whole outcome UNKNOWN
10. release exact lease -> RELEASED
11. wrong owner / wrong acquisition cannot release
12. no silent stealing
13. same session second execution -> BUSY
14. different session executions may coexist absent shared resource conflict
15. two playback operations resolving same lock -> only one executes
16. no resource_locks -> no ResourceLock serialization
17. input invalid / permission denied -> no lock acquire
18. idempotency completed replay -> no physical resource acquire
19. physical Tool normal completion -> release
20. Tool exception after coroutine ended -> release
21. unconfirmed timeout -> DO NOT RELEASE
22. IU7 CONFIRMED_STOPPED -> release allowed
23. IU7 UNKNOWN / NOT_CANCELLABLE -> lock retained
24. lock conflict does not recompute priority
25. lock conflict does not rewrite ApprovedActionPlan
26. no IU9 recovery / checkpoint entered
27. no IU10 aggregation / M6 entered
~~~

## 22. Controlled Amendment plan

### CA-M5-IU8-01 Lock Identity + Typed Acquire/Release Authority

冻结 ResourceLockOwner / AcquireRequest / Lease / typed acquire/release decisions / exact replay / no silent stealing。

目标 blocker：B-M5-IU8-001。

### CA-M5-IU8-02 Runtime Resource Projection + Multi-Lock Set

冻结 ResourceLockRequirement / ResolvedResourceLock / RequirementResolver / ResourceLockSetCoordinator / canonical acquisition order / partial rollback / rollback uncertainty。

目标 blocker：

~~~text
B-M5-IU8-002
B-M5-IU8-003
~~~

### CA-M5-IU8-03 Session Lock + Operation-Bound Release

冻结 SessionExecutionLock、physical-operation lock ownership、definitive completion / CONFIRMED_STOPPED release authority、timeout/UNKNOWN lock retention、IU7 in-flight identity linkage。

目标 blocker：

~~~text
B-M5-IU8-004
B-M5-IU8-005
~~~

## 23. Frozen non-goals

~~~text
priority recomputation              -> M2/Runtime
new parallel scheduler              -> not introduced by IU8
durable lease persistence           -> IU9
crash recovery                      -> IU9
stale lock reclaim/fencing          -> IU9
Workflow resume                     -> IU9
ExecutionResult aggregation         -> IU10
M6                                  -> after M5 closure
Runtime new-cycle start             -> Runtime
~~~

## 24. Design conclusion

~~~text
M5-IU8 IMPLEMENTATION DESIGN = COMPLETE
M5-IU8 INDEPENDENT DESIGN REVIEW = PENDING
M5-IU8 IMPLEMENTATION READINESS = PENDING REVIEW
M5 = IN PROGRESS
~~~
