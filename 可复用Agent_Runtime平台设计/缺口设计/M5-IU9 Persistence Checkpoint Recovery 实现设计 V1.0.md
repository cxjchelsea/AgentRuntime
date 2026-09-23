# M5-IU9 Persistence / Checkpoint / Recovery 实现设计 V1.0

> Mapping：M5-IU9 = M5 V2.0 Step 11。
> Baseline：M5-IU1～IU8 = PASSED。
> Goal：让 M5 在进程崩溃、Runtime 重启、Workflow WAITING、Tool/Skill 超时或控制信号已经锁存但尚未完成终态提交时，能够基于 durable evidence 恢复，而不是依赖进程内对象或猜测真实世界状态。

## 1. IU9 正式目标

M5-IU9 解决：

~~~text
process / worker crash
        ↓
live in-memory truth lost
        ↓
load durable execution facts
        ↓
reconcile stronger side authorities
        ↓
classify recovery state
        ↓
resume / retry / terminalize / wait reconciliation / fail closed
~~~

核心不变量：

~~~text
process restarted != prior operation stopped
checkpoint exists != checkpoint is newest truth
ExecutionRecord persisted != PreparedExecution recoverable
Tool timeout != Tool safe to replay
lock owner process gone != resource safe to reclaim
workflow WAITING != workflow resumable
resume requested != resume authorized
recovery != replanning
recovery != aggregation
~~~

## 2. Existing baseline

当前已有：

~~~text
ExecutionStateStore
WorkflowCheckpointStore seed protocol
IdempotencyStore / IdempotencyCompletionAuthority
ExecutionRecord
WorkflowCheckpoint
IU6 Tool operation correlation / idempotency / Step retry
IU7 control latch / in-flight operation identity
IU8 resource lease / session lock / operation-resource binding
WorkflowImplementation.resume() protocol
~~~

但目前关键实现仍是 live-only：

~~~text
InMemoryExecutionStateStore
InMemoryStepAttemptSequenceAuthority
InMemoryToolOperationOccurrenceAuthority
InMemoryIdempotencyCoordinator reference implementation
InMemoryExecutionControlLatch
InMemoryInFlightOperationRegistry
InMemoryResourceLockAuthority
InMemoryOperationResourceLeaseRegistry
ExecutionConcurrencyRuntime._leases
~~~

这些对象在进程重启后全部丢失，因此 IU8 通过不代表 crash-safe。

## 3. Crash model

IU9 第一版明确考虑以下 crash windows：

~~~text
A. lifecycle persisted, recovery checkpoint not yet advanced
B. control latched, control lifecycle not yet terminalized
C. Tool lock acquired, Tool handle/binding not fully registered
D. Tool invoke started, result not observed
E. Tool side effect succeeded, idempotency completion not committed
F. Step attempt finished, retry sequence / journal not persisted
G. Workflow returned WAITING, checkpoint not durably committed
H. session/resource lease still active when process disappears
I. old process is partitioned / delayed and new process starts recovery
~~~

IU9 不允许通过“worker 不在了”推断 operation stopped。

## 4. Recovery truth hierarchy

恢复时不同事实的优先级必须冻结：

~~~text
1. authoritative terminal lifecycle already persisted
2. durable terminal control latch for a nonterminal execution
3. authoritative idempotency completion / external operation reconciliation
4. durable resource-lock / operation-resource ownership evidence
5. durable in-flight / workflow / reliability evidence
6. latest valid recovery checkpoint
~~~

较弱 checkpoint 不能覆盖较新的 authoritative side evidence。

例如：

~~~text
checkpoint says RUNNING
but ExecutionRecord says CANCELLED with later revision
-> terminal lifecycle wins
~~~

以及：

~~~text
checkpoint has no active Tool
but durable lock + operation binding still exists
-> cannot assume resource free
~~~

## 5. Durable Execution Recovery Snapshot

当前 ExecutionRecord 不足以重建 PreparedExecution，因为它没有完整保存：

~~~text
ExecutionContext.session_id
device_id
policy_snapshot
current_state
tool_context
deadline
cancellation_token
trace_context
PreparedExecution.started_at / finished_at
typed StepLifecycleSnapshot reconstruction contract
recovery generation / revision
~~~

IU9 需要新增 Core-owned versioned recovery snapshot，建议：

~~~text
ExecutionRecoverySnapshot
- schema_version
- checkpoint_id
- generation
- execution_id
- captured_at
- execution_context snapshot
- execution_record snapshot
- typed step lifecycle snapshots
- execution_started_at
- execution_finished_at
- active_step_id?
- recovery references / revisions
~~~

该 snapshot 用于重建 Core execution state，不替代 ResourceLock / Idempotency 等独立 authority。

## 6. Snapshot monotonicity / CAS

不能继续使用无 revision 的：

~~~text
save(record)
~~~

作为 recovery writer authority。

IU9 必须冻结：

~~~text
generation strictly increases
expected_revision / compare-and-set
stale writer rejected
checkpoint identity immutable
same generation different payload -> CONFLICT / UNKNOWN
~~~

恢复过程不能让旧进程在新 recovery runtime 已接管后覆盖较新状态。

## 7. Recovery Claim / Epoch

仅靠 session lock 不足以防止两个进程同时恢复同一个 execution，因为 same execution 的 exact lease replay 本身可能成功。

因此 IU9 需要 execution-level recovery ownership：

~~~text
ExecutionRecoveryClaim
- execution_id
- recovery_epoch
- recovery_owner_id
- claimed_at
- source_checkpoint_generation
~~~

规则：

~~~text
only current recovery epoch may mutate recovered execution state
stale epoch writes -> reject
claim conflict -> WAIT / UNKNOWN
recovery epoch does not prove external Tool stopped
~~~

Recovery Claim 解决 Core stale-writer 问题，不替代 physical resource fencing。

## 8. Reliability evidence must survive restart

IU6 现在有两个关键 live-only sequence authorities：

~~~text
InMemoryStepAttemptSequenceAuthority
InMemoryToolOperationOccurrenceAuthority
~~~

以及 CoreApprovedToolInvoker 内存 Tool journal。

如果 crash 后这些从 1 重新开始，可能发生：

~~~text
Step attempt number reused
Tool occurrence reused / diverged
logical operation correlation lost
idempotency key cannot be safely correlated
unsafe duplicate side effect
~~~

IU9 需要 durable：

~~~text
Step attempt cursor
Tool operation occurrence cursor
Tool invocation journal / operation correlation evidence
retry claim token / attempt provenance
~~~

这些事实必须与 exact step_execution_id / tool version / operation fingerprint 绑定。

## 9. Idempotency recovery

IdempotencyStore 本身已有正确方向，但 IU9 冻结恢复语义：

~~~text
COMPLETED -> recover trusted result, never re-invoke
FAILED -> may reopen only under exact provenance + IU6 replay authority
RESERVED -> operation may still be in flight; do not replay blindly
UNKNOWN -> fail closed / reconciliation required
~~~

如果 external side effect 已成功但 crash 发生在 Idempotency completion commit 之前：

~~~text
RESERVED / UNKNOWN
!= safe retry
~~~

必须进入 operation reconciliation / WAIT_RECOVERY。

## 10. Durable terminal control latch

当前 InMemoryExecutionControlLatch 是 live-only。

危险窗口：

~~~text
CANCEL/PREEMPT already latched
↓
process crash
↓
restart forgets latch
↓
execution continues side effect
~~~

因此 IU9 需要 durable control latch store，保持 IU7 原语义：

~~~text
first exact terminal signal -> LATCHED
exact replay -> ALREADY_LATCHED
different terminal signal for same execution -> CONFLICT
UNKNOWN never becomes no-control
~~~

恢复顺序中，nonterminal execution 的 durable terminal control barrier 必须先于 Scheduler / retry / Workflow resume。

## 11. Durable in-flight evidence

当前 InMemoryInFlightOperationRegistry 在 crash 后丢失。

IU9 不能简单把 crash 前 ACTIVE handle 重新注册为 live ACTIVE，因为：

~~~text
process lost != underlying external operation status known
~~~

建议 durable operation observation 至少区分：

~~~text
ACTIVE_AT_CHECKPOINT
COMPLETED
CONFIRMED_STOPPED
ORPHANED_UNCONFIRMED
UNKNOWN
~~~

restart 后 crash 前的 ACTIVE operation 默认进入：

~~~text
ORPHANED_UNCONFIRMED
~~~

直到 injected external reconciliation authority 给出可信结果。

## 12. External Operation Reconciliation

IU9 需要 injected recovery adapter / probe，而不是 Core 猜测。

建议：

~~~text
OperationRecoveryProbe
input:
- exact operation handle / provider identity
- execution / step / tool provenance

output:
- RUNNING_CONFIRMED
- COMPLETED_CONFIRMED
- STOPPED_CONFIRMED
- NOT_FOUND_WITH_PROOF
- UNKNOWN
~~~

其中 NOT_FOUND 只有 provider 能证明“该 operation identity 从未执行或已明确不存在且不会继续”时才可作为强证据；普通 404 / lookup failed 不能自动等价 STOPPED。

没有 probe 或 probe UNKNOWN -> WAIT_RECONCILIATION。

## 13. Durable ResourceLock authority

IU8 的 InMemoryResourceLockAuthority 不具备 crash durability。

IU9 需要 durable：

~~~text
active lease
released acquisition history
acquisition identity index
session execution lease
operation-resource binding
lock revision / fence
~~~

重启后必须能回答：

~~~text
who owns this resource
which exact acquisition owns it
whether it has been released
which Tool operation the lease belongs to
whether current recovery epoch may mutate it
~~~

## 14. Safe stale-lock reclaim

IU9 明确禁止：

~~~text
process heartbeat expired -> immediately free lock
TTL expired -> immediately free lock
worker PID gone -> immediately free lock
~~~

Tool resource lock 只有以下情况可 reclaim：

~~~text
1. exact operation COMPLETED_CONFIRMED
2. exact operation STOPPED_CONFIRMED
3. provider-level fencing makes prior operation unable to commit side effect
~~~

否则：

~~~text
retain lock
WAIT_RECONCILIATION
~~~

Session execution lock 可在同 execution recovery 下 exact reattach；新的 competing execution 仍 BUSY。

## 15. Fencing semantics

Recovery epoch 只能防 Core stale writer，不能自动阻止旧 external provider operation。

因此 resource fencing 分两层：

~~~text
Core persistence fence
-> reject stale runtime writes / releases

Provider fence (optional capability)
-> adapter propagates opaque fencing token to provider
-> older token cannot commit
~~~

如果 provider 不支持 fencing，则 stale Tool lock 不得仅凭 epoch/TTL 回收。

## 16. Workflow checkpoint authority

现有 WorkflowCheckpoint 字段不足以证明 exact resume authority，缺少：

~~~text
execution_id
step_execution_id
workflow_version
checkpoint_id / generation
durable state reference / resume token
checkpoint status
schema/version provenance
~~~

IU9 建议新增 exact WorkflowRecoveryCheckpoint。

Domain Workflow 内部状态可以由 Domain/adapter 保存，Core 只持有 opaque state_reference / resume_token 和完整 provenance，不把领域状态结构塞进 Core。

## 17. WAITING workflow commit rule

Workflow 返回 WAITING 不能直接等于可恢复。

必须满足：

~~~text
Workflow returns WAITING
↓
durable exact checkpoint committed
↓
Core records checkpoint reference
↓
then WAITING is recoverable
~~~

如果 WAITING 已返回但 checkpoint durable commit 不确定：

~~~text
WAIT_RECOVERY / UNKNOWN
~~~

不能生成新的 workflow_instance_id 重新 start。

## 18. Workflow resume boundary

现有 WorkflowImplementation.resume() 只有 WorkflowExecutionRequest，不足以证明 exact checkpoint。

IU9 需要显式 resume request：

~~~text
WorkflowResumeRequest
- execution_id
- step_execution_id
- workflow_instance_id
- workflow_id
- workflow_version
- checkpoint_id
- checkpoint_generation
- state_reference / resume_token
- event?
~~~

Core 必须先重新解析 exact approved Workflow version，并验证 checkpoint provenance，然后才可调用 resume。

Resume 不允许 capability substitution / latest-version fallback。

## 19. Skill recovery

Skill 没有通用 resume contract。

因此 crash 时 RUNNING Skill 的第一版规则：

~~~text
unresolved external operation exists
-> WAIT_RECONCILIATION

all external operations reconciled
+ IU6 whole-Step replay safety = SAFE
+ durable Step attempt sequence grants next attempt
-> RETRY_STEP

replay safety UNKNOWN / UNSAFE
-> WAIT_RECOVERY / UNKNOWN
~~~

IU9 不发明 Skill mid-frame continuation。

## 20. Tool recovery

Recovery 不直接 resume 一个 Tool coroutine。

规则：

~~~text
COMPLETED idempotency evidence -> recover result
CONFIRMED completed/stopped external operation -> reconcile exact state
unresolved active Tool -> WAIT_RECONCILIATION
new physical Tool attempt -> only through normal IU6 + IU8 boundaries
~~~

因此不存在 recovery bypass permission / idempotency / ResourceLock。

## 21. Recovery decision model

建议冻结 typed disposition：

~~~text
TERMINAL_NO_ACTION
APPLY_LATCHED_CONTROL
RESUME_SCHEDULING
RESUME_WORKFLOW
RETRY_STEP
WAIT_RECONCILIATION
UNKNOWN_BLOCKED
~~~

这些 disposition 只是恢复授权，不是 ExecutionResult 聚合。

## 22. Recovery order

恢复流程严格按：

~~~text
1. acquire ExecutionRecoveryClaim / new recovery epoch
2. load latest recovery snapshot + authoritative durable side stores
3. validate identity / schema / generation / revisions
4. if lifecycle already terminal -> TERMINAL_NO_ACTION
5. if durable terminal control latch exists -> APPLY_LATCHED_CONTROL
6. reconcile orphaned in-flight operations + resource bindings
7. unresolved operation / lock -> WAIT_RECONCILIATION
8. exact WAITING Workflow checkpoint -> RESUME_WORKFLOW
9. RUNNING Skill with safe replay evidence -> RETRY_STEP
10. no running Step and valid pending work -> RESUME_SCHEDULING
11. any inconsistency -> UNKNOWN_BLOCKED
~~~

禁止把第 8～10 步提前到 control / operation reconciliation 前。

## 23. Recovery and scheduler

IU9 不重新设计 Scheduler。

RESUME_SCHEDULING 只表示：

~~~text
existing ApprovedActionPlan + reconstructed PreparedExecution
may return to existing SequentialStepScheduler
~~~

不修改计划、不跳 Step、不重新排序。

## 24. Recovery and control

durable CANCEL/PREEMPT barrier 的优先级不是 IU9 自己算出来的，而是沿用 IU7 已经接受的 terminal control authority。

恢复只保证：

~~~text
accepted terminal control cannot disappear after restart
~~~

PREEMPT recovery 仍不在 M5 内启动新的 Runtime cycle。

## 25. Checkpoint write points

至少在以下边界推进 recovery checkpoint / revision：

~~~text
execution initialized
execution started
step started
Step attempt identity claimed
Tool operation correlation/journal changed
control latched
Workflow durable WAITING checkpoint committed
step terminalized
execution terminalized
recovery decision committed
~~~

ResourceLock / Idempotency 等独立 authority 仍使用自己的 durable commit，不要求用单数据库事务伪造跨系统原子性。

## 26. Cross-store consistency

由于 checkpoint、lock、idempotency、external provider 可能不在同一事务域，IU9 不宣称分布式全局原子事务。

采用：

~~~text
monotonic revision
immutable identities
exact provenance
side-authority reconciliation
fail-closed uncertainty
~~~

恢复 snapshot 是 recovery anchor，不是覆盖所有 authority 的万能快照。

## 27. Planned tests

至少覆盖：

~~~text
1. exact recovery snapshot can reconstruct PreparedExecution
2. stale snapshot generation rejected
3. stale recovery epoch cannot mutate current execution
4. terminal Execution survives restart as terminal
5. latched CANCEL survives restart and blocks resume
6. active-at-crash Tool becomes ORPHANED_UNCONFIRMED
7. orphaned Tool without probe -> WAIT_RECONCILIATION
8. COMPLETED idempotency result is recovered without Tool invoke
9. RESERVED / UNKNOWN idempotency never blind-retries
10. Step attempt sequence survives restart
11. Tool operation occurrence sequence survives restart
12. prior Tool journal survives restart and correlates retry
13. durable session lock exact execution reattach
14. competing session execution remains BUSY during recovery
15. stale Tool lock not reclaimed by TTL alone
16. STOPPED_CONFIRMED permits exact resource reclaim
17. COMPLETED_CONFIRMED permits exact resource reconciliation
18. stale recovery fence cannot release newer lease
19. WAITING Workflow without durable checkpoint is not resumable
20. exact durable Workflow checkpoint resumes same instance/version
21. checkpoint identity mismatch -> UNKNOWN_BLOCKED
22. running Skill replay only when IU6 replay safety SAFE
23. recovery never creates new ApprovedActionPlan
24. recovery never bypasses Permission / Idempotency / ResourceLock
25. no IU10 aggregation / M6 entered
~~~

## 28. Controlled Amendment plan

### CA-M5-IU9-01 Durable Execution Snapshot + Recovery Claim

冻结：

~~~text
ExecutionRecoverySnapshot
RecoverySnapshotStore
generation / revision / CAS
ExecutionRecoveryClaim
recovery_epoch / stale writer rejection
PreparedExecution reconstruction boundary
~~~

目标 blocker：

~~~text
B-M5-IU9-001
B-M5-IU9-004
~~~

### CA-M5-IU9-02 Durable Reliability + Control/InFlight Evidence

冻结：

~~~text
durable Step attempt cursor
durable Tool occurrence cursor
durable Tool journal evidence
durable terminal control latch
durable in-flight operation observation
crash -> ORPHANED_UNCONFIRMED
~~~

目标 blocker：

~~~text
B-M5-IU9-002
B-M5-IU9-003
~~~

### CA-M5-IU9-03 Durable Resource Lock Recovery + Fencing

冻结：

~~~text
durable ResourceLock authority
durable operation-resource binding
recovery fence validation
safe stale-lock reclaim
provider fencing capability boundary
UNKNOWN -> retain
~~~

目标 blocker：B-M5-IU9-005。

### CA-M5-IU9-04 Workflow Checkpoint + Recovery Decision / Resume

冻结：

~~~text
WorkflowRecoveryCheckpoint
WAITING durable-commit rule
WorkflowResumeRequest
RecoveryDisposition
RecoveryCoordinator
recovery ordering
Skill retry / Workflow resume / Scheduler re-entry
~~~

目标 blocker：

~~~text
B-M5-IU9-006
B-M5-IU9-007
~~~

## 29. Frozen non-goals

~~~text
replanning / priority recomputation       -> M2/Runtime
automatic new cycle after PREEMPT         -> Runtime
business-specific workflow state schema   -> Domain / Workflow adapter
blind TTL lock stealing                   -> forbidden
distributed global transaction            -> not claimed
ExecutionResult aggregation               -> IU10
M6 validation                             -> after M5 closure
cross-service exactly-once guarantee      -> not claimed without provider support
~~~

## 30. Design conclusion

~~~text
M5-IU9 IMPLEMENTATION DESIGN = COMPLETE
M5-IU9 INDEPENDENT DESIGN REVIEW = PENDING
M5-IU9 IMPLEMENTATION READINESS = PENDING REVIEW
M5 = IN PROGRESS
~~~