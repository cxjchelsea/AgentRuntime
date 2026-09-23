# M5-IU9 Implementation Readiness Review V1.0

> Review target：M5-IU9 Persistence / Checkpoint / Recovery。
> Baseline：M5-IU1～IU8 = PASSED。
> 本 Review 只判断是否具备安全进入 IU9 Formal Implementation 的合同，不把已有 in-memory store 当成 crash-durable 实现。

## 1. Readiness conclusion

~~~text
M5-IU9 IMPLEMENTATION DESIGN = COMPLETE
M5-IU9 INDEPENDENT DESIGN REVIEW = PASSED
M5-IU9 IMPLEMENTATION READINESS = NOT_READY

BLOCKERS = 7
FORMAL IMPLEMENTATION = NOT AUTHORIZED
NEW BLOCKER = NONE
~~~

当前已经具备大量 live runtime truth，但进程重启后无法证明这些 truth 仍然存在或仍然最新。

## 2. B-M5-IU9-001 EXECUTION_RECOVERY_SNAPSHOT_INCOMPLETE

当前 ExecutionStateStore 只持久化 ExecutionRecord。

ExecutionRecord 无法完整重建 PreparedExecution / ExecutionContext，尤其缺少 session/device/policy/deadline/trace 以及 typed lifecycle reconstruction contract。

因此 crash 后即使 ExecutionRecord 仍在，也没有安全的 Core recovery envelope。

~~~text
B-M5-IU9-001 = OPEN
REQUIRES CA-M5-IU9-01
~~~

## 3. B-M5-IU9-002 RELIABILITY_REPLAY_EVIDENCE_NOT_CRASH_DURABLE

当前以下关键 authority 为内存态：

~~~text
InMemoryStepAttemptSequenceAuthority
InMemoryToolOperationOccurrenceAuthority
CoreApprovedToolInvoker local Tool journal
~~~

重启后可能重用 attempt / occurrence、丢失 operation correlation，从而破坏 IU6 replay/idempotency safety。

~~~text
B-M5-IU9-002 = OPEN
REQUIRES CA-M5-IU9-02
~~~

## 4. B-M5-IU9-003 CONTROL_AND_INFLIGHT_STATE_NOT_CRASH_DURABLE

当前：

~~~text
InMemoryExecutionControlLatch
InMemoryInFlightOperationRegistry
~~~

均是 live-only。

如果 CANCEL/PREEMPT 已锁存但 crash，restart 可能忘记 barrier；如果 Tool/Skill/Workflow 在 crash 时 active，restart 也无法知道 underlying operation 是否仍运行。

必须持久化 terminal control barrier 与 in-flight observation，并把 crash 前 active operation 恢复为 ORPHANED_UNCONFIRMED，而不是自动当作 completed/stopped。

~~~text
B-M5-IU9-003 = OPEN
REQUIRES CA-M5-IU9-02
~~~

## 5. B-M5-IU9-004 RECOVERY_WRITER_CAS_AND_EPOCH_MISSING

当前 ExecutionStateStore.save() 没有 revision / compare-and-set，same execution 的 session lease exact replay 也不能阻止两个进程同时恢复同一 execution。

缺少：

~~~text
Recovery generation
ExecutionRecoveryClaim
recovery_epoch
stale-writer rejection
~~~

没有这些机制，旧 worker / partitioned worker 可能覆盖新恢复进程的状态。

~~~text
B-M5-IU9-004 = OPEN
REQUIRES CA-M5-IU9-01
~~~

## 6. B-M5-IU9-005 RESOURCE_LOCK_CRASH_RECLAIM_AND_FENCING_MISSING

IU8 已明确把以下内容后置到 IU9：

~~~text
durable lease persistence
stale reclaim
cross-process fencing
crash recovery
~~~

当前 InMemoryResourceLockAuthority / InMemoryOperationResourceLeaseRegistry 在 restart 后丢失。

更重要的是：

~~~text
worker gone
!= external Tool stopped
~~~

因此不能用 TTL/PID/heartbeat 直接释放 stale lock。

需要 durable lock/binding + recovery fence + exact external-operation reconciliation；provider 不支持 fencing 且 operation 未证明 stopped/completed 时必须 retain。

~~~text
B-M5-IU9-005 = OPEN
REQUIRES CA-M5-IU9-03
~~~

## 7. B-M5-IU9-006 WORKFLOW_CHECKPOINT_RESUME_AUTHORITY_INCOMPLETE

已有 WorkflowCheckpoint / WorkflowCheckpointStore / WorkflowImplementation.resume() 只是 seed。

当前 WorkflowCheckpoint 缺少 execution_id、step_execution_id、workflow_version、checkpoint generation、opaque durable state reference 等 exact resume provenance。

WorkflowImplementation.resume() 也没有显式接收 exact checkpoint authority。

因此 WAITING 还不能等价于 crash-safe resumable。

~~~text
B-M5-IU9-006 = OPEN
REQUIRES CA-M5-IU9-04
~~~

## 8. B-M5-IU9-007 RECOVERY_DECISION_ORCHESTRATOR_MISSING

当前没有一个 Core authority 能在 restart 后按统一顺序判断：

~~~text
terminal?
latched control?
orphaned operation?
resource lock unresolved?
workflow resumable?
skill replay safe?
scheduler may resume?
~~~

如果各模块自行恢复，容易出现 Workflow resume 早于 CANCEL barrier、Skill retry 早于 Tool reconciliation、Scheduler 在 unresolved lock 时继续等问题。

需要 typed RecoveryDisposition + RecoveryCoordinator。

~~~text
B-M5-IU9-007 = OPEN
REQUIRES CA-M5-IU9-04
~~~

## 9. Existing contracts that are reusable

以下方向正确，不是 blocker：

~~~text
ExecutionRecord identity
ExecutionStateStore seed
WorkflowCheckpointStore seed
IdempotencyStore / CompletionAuthority
IU6 replay-safety evaluator
IU6 exact operation fingerprint/correlation
IU7 immutable terminal control signal identity
IU7 exact InFlightOperationHandle
IU8 exact ResourceLockLease / acquisition identity
IU8 exact OperationResourceLeaseBinding
IU8 session execution lease
WorkflowImplementation.resume() capability shape
~~~

IU9 应扩展这些 authority，不创建第二套 execution / Tool / lock identity。

## 10. Independent Design Review findings

独立复核重点：

~~~text
crash truth vs live truth
Core / Domain checkpoint boundary
IU6 replay/idempotency compatibility
IU7 control barrier persistence
IU8 lock lifetime / reclaim safety
stale writer fencing
IU10 aggregation boundary
~~~

### 10.1 Recovery 不把 crash 当 stopped

设计明确 active-at-crash -> ORPHANED_UNCONFIRMED，只有 exact external reconciliation 才能升级为 completed/stopped。

通过。

### 10.2 Checkpoint 不覆盖 stronger authority

Recovery snapshot 只是 anchor；terminal lifecycle、idempotency、lock/binding、provider reconciliation 等较强证据可以覆盖 stale checkpoint。

通过。

### 10.3 Workflow 领域状态不污染 Core

Core 保存 exact provenance + opaque state_reference/resume_token；Domain/adapter 保存领域 workflow state。

通过。

### 10.4 Recovery writer 与 resource fence 分层

Execution recovery epoch 解决 Core stale writer；provider fencing 仅在 adapter 支持时阻止旧 external operation。二者不混为一谈。

通过。

### 10.5 IU9 不提前做 IU10/M6

RecoveryDisposition 不生成 Canonical ExecutionResult，也不进行 M6 validation。

通过。

## 11. Independent Design Review Decision

~~~text
M5-IU9 IMPLEMENTATION DESIGN = COMPLETE
M5-IU9 INDEPENDENT DESIGN REVIEW = PASSED

DESIGN BLOCKER = NONE
NEW BLOCKER = NONE
~~~

Design review PASSED 只表示设计边界成立，不表示可以直接 Formal Implementation。

## 12. Controlled Amendment plan

### CA-M5-IU9-01 Durable Execution Snapshot + Recovery Claim

关闭：

~~~text
B-M5-IU9-001 EXECUTION_RECOVERY_SNAPSHOT_INCOMPLETE
B-M5-IU9-004 RECOVERY_WRITER_CAS_AND_EPOCH_MISSING
~~~

### CA-M5-IU9-02 Durable Reliability + Control/InFlight Evidence

关闭：

~~~text
B-M5-IU9-002 RELIABILITY_REPLAY_EVIDENCE_NOT_CRASH_DURABLE
B-M5-IU9-003 CONTROL_AND_INFLIGHT_STATE_NOT_CRASH_DURABLE
~~~

### CA-M5-IU9-03 Durable Resource Lock Recovery + Fencing

关闭：

~~~text
B-M5-IU9-005 RESOURCE_LOCK_CRASH_RECLAIM_AND_FENCING_MISSING
~~~

### CA-M5-IU9-04 Workflow Checkpoint + Recovery Decision / Resume

关闭：

~~~text
B-M5-IU9-006 WORKFLOW_CHECKPOINT_RESUME_AUTHORITY_INCOMPLETE
B-M5-IU9-007 RECOVERY_DECISION_ORCHESTRATOR_MISSING
~~~

## 13. Readiness Re-Review Gate

只有以下全部满足，才能写：

~~~text
M5-IU9 IMPLEMENTATION READINESS = READY
~~~

条件：

~~~text
1. CA-M5-IU9-01 Targeted Review = PASSED + four gates GREEN
2. CA-M5-IU9-02 Targeted Review = PASSED + four gates GREEN
3. CA-M5-IU9-03 Targeted Review = PASSED + four gates GREEN
4. CA-M5-IU9-04 Targeted Review = PASSED + four gates GREEN
5. B-M5-IU9-001～007 all CLOSED
6. stale recovery writer cannot overwrite newer state
7. latched terminal control survives restart
8. active-at-crash operation is never assumed stopped
9. retry / occurrence identity survives restart
10. RESERVED / UNKNOWN idempotency never blind-replays
11. stale Tool lock cannot be reclaimed by TTL alone
12. provider fence limitations remain explicit
13. WAITING Workflow is resumable only after durable exact checkpoint
14. Workflow resume uses same instance + exact approved version
15. recovery ordering applies control/reconciliation before resume/retry
16. existing Scheduler reused; no replanning
17. IU10/M6 not entered
~~~

## 14. Current Formal Status

~~~text
M5-IU1 = PASSED
M5-IU2 = PASSED
M5-IU3 = PASSED
M5-IU4 = PASSED
M5-IU5 = PASSED
M5-IU6 = PASSED
M5-IU7 = PASSED
M5-IU8 = PASSED

M5-IU9 IMPLEMENTATION DESIGN = COMPLETE
M5-IU9 INDEPENDENT DESIGN REVIEW = PASSED
M5-IU9 IMPLEMENTATION READINESS = NOT_READY

B-M5-IU9-001 = OPEN
B-M5-IU9-002 = OPEN
B-M5-IU9-003 = OPEN
B-M5-IU9-004 = OPEN
B-M5-IU9-005 = OPEN
B-M5-IU9-006 = OPEN
B-M5-IU9-007 = OPEN

NEW BLOCKER = NONE

NEXT REQUIRED =
CA-M5-IU9-01
Durable Execution Snapshot + Recovery Claim

M5 = IN PROGRESS
~~~