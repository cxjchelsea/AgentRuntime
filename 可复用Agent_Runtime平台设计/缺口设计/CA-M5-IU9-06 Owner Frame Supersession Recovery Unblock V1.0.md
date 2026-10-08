# CA-M5-IU9-06 Owner Frame Supersession + Recovery Unblock V1.0

> Base：CA-M5-IU9-05 PASSED @ 5d5070aafd24bec79b5f85bb564331e758d9e0a7
> Target blocker：B-M5-IU9-FI-001 OWNER_INFLIGHT_CRASH_RECOVERY_DEADLOCK

## 1. 目标

本 CA 只解决 Formal Implementation 阶段发现的 owner in-flight 恢复死锁：

~~~text
Skill / Workflow owner frame
-> crash
-> ACTIVE_AT_CHECKPOINT
-> ORPHANED_UNCONFIRMED
-> CA-04 WAIT_RECONCILIATION
-> RETRY_STEP / RESUME_WORKFLOW 永远不可达
~~~

不改变 Tool external operation 的 reconciliation truth，不进入 IU10 / M6。

## 2. Core owner frame 与 external Tool 分离

~~~text
SKILL / WORKFLOW in-flight handle
= Core-owned local execution frame authority

TOOL in-flight handle
= external side-effect operation evidence
~~~

因此 recovery epoch takeover 不等于 provider fence、STOPPED proof 或 NOT_FOUND proof。

## 3. 新增 owner-frame state

~~~text
InFlightEvidenceState.OWNER_FRAME_SUPERSEDED
OwnerFrameSupersessionBasis.RECOVERY_EPOCH_TAKEOVER
~~~

其唯一语义：旧 Skill / Workflow 本地执行帧在新的 recovery epoch 下不再具有权威。
它不声明任何外部物理操作已经停止。

## 4. Typed provenance

OWNER_FRAME_SUPERSEDED 必须满足：

~~~text
handle.kind in {SKILL, WORKFLOW}
owner_supersession_basis = RECOVERY_EPOCH_TAKEOVER
reconciliation_basis = None
terminal_at >= handle.started_at
writer_recovery_epoch = current recovery epoch
~~~

其他 state 不得携带 owner_supersession_basis。

## 5. External reconciliation 保持 Tool-only

CA-05 的 InFlightTerminalReconciliation 现在明确只允许：

~~~text
handle.kind = TOOL
~~~

Skill / Workflow owner 禁止伪装成 provider reconciliation truth。

## 6. Exact owner supersession authority

新增：

~~~text
DurableInFlightEvidenceStore.supersede_orphaned_owner_frame(...)
~~~

必须绑定 exact：

~~~text
execution_id
step_execution_id
owner_kind
capability_id
recovered_at
current ExecutionRecoveryClaim
~~~

只允许：

~~~text
ORPHANED_UNCONFIRMED
-> OWNER_FRAME_SUPERSEDED
~~~

TOOL 显式禁止；stale epoch / unknown epoch / time regression 均 fail closed。

## 7. Exact running-step binding

RecoveryCoordinator 只从 snapshot 中唯一 RUNNING step 推导：

~~~text
step_execution_id
owner kind
capability_id
~~~

只 supersede 该 exact owner。其他 orphan owner 保持 unresolved，并继续阻塞恢复。

## 8. Recovery ordering

~~~text
terminal lifecycle
-> durable terminal control
-> crash ACTIVE -> ORPHANED_UNCONFIRMED
-> exact owner-frame supersession
-> unresolved in-flight check
-> active resource binding check
-> Workflow resume / Skill replay / Scheduler re-entry
~~~

## 9. Workflow recovery

~~~text
RUNNING Workflow
+ exact owner superseded
+ nested Tool all reconciled
+ durable WAITING checkpoint
+ exact approved version
-> RESUME_WORKFLOW
~~~

nested Tool 未收口时仍 WAIT_RECONCILIATION。

## 10. Skill recovery

~~~text
RUNNING Skill
+ exact owner superseded
+ nested Tool all reconciled
-> IU6 whole-Step replay

SAFE    -> RETRY_STEP
UNSAFE  -> WAIT_RECONCILIATION
UNKNOWN -> UNKNOWN_BLOCKED
~~~

不新增 Skill mid-frame resume。

## 11. Verification scenarios

新增 tests/test_m5_iu9_ca06_owner_frame_supersession.py，覆盖：

~~~text
Skill owner superseded, nested Tool remains orphan
Tool kind explicitly forbidden
exact replay idempotent
stale epoch rejected
Workflow owner reaches RESUME_WORKFLOW
Skill owner reaches RETRY_STEP
nested Tool orphan still blocks
external reconciliation rejects Skill owner
non-running orphan owner is not silently superseded
~~~

同时更新 CA-04 fake store 适配 exact supersession protocol。

## 12. Non-goals

~~~text
M5-IU9 Formal Implementation wiring
actual Workflow resume invocation
actual Skill replay execution
new provider reconciliation semantics
replanning
IU10 aggregation
M6
distributed exactly-once
~~~

## 13. Blocker mapping

~~~text
B-M5-IU9-FI-001
OWNER_INFLIGHT_CRASH_RECOVERY_DEADLOCK
= FIX_IMPLEMENTED_PENDING_GATES
~~~

只有 Targeted Review 与 Verification 均通过后才能正式关闭。

## 14. Current status

~~~text
CA-M5-IU9-06 = CODE COMPLETE
CA-M5-IU9-06 TARGETED AMENDMENT REVIEW = PENDING
CA-M5-IU9-06 VERIFICATION = PENDING

B-M5-IU9-FI-001 = FIX_IMPLEMENTED_PENDING_GATES

M5-IU9 IMPLEMENTATION READINESS = NOT_READY
M5-IU9 FORMAL IMPLEMENTATION = BLOCKED

NEXT REQUIRED =
CA-M5-IU9-06 Targeted Amendment Review
-> Verification
-> M5-IU9 Implementation Readiness Re-Review
-> resume Formal Implementation
~~~