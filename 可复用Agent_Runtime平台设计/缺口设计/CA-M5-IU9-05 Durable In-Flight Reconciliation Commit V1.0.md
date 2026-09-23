# CA-M5-IU9-05 Durable In-Flight Reconciliation Commit V1.0

> Base：CA-M5-IU9-04 PASSED @ d4bd57dd07f659813d8364ee177bdaa4ccbdb81b
> Target blocker：
> B-M5-IU9-008 RECOVERY_RECONCILIATION_NOT_COMMITTED_TO_DURABLE_INFLIGHT_TERMINAL_EVIDENCE

## 1. 目标

本 CA 只关闭一个跨 CA 集成缺口：

~~~text
crash-active operation
-> ORPHANED_UNCONFIRMED
-> authoritative provider reconciliation
-> durable terminal evidence
-> recovery may continue
~~~

它不修改 CA-M5-IU9-04 的 Recovery 决策顺序，不进入 M5-IU9 Formal Implementation，不进入 IU10 / M6，也不重新规划。

## 2. 新增 durable reconciliation contract

新增：

~~~text
InFlightReconciliationBasis
InFlightTerminalReconciliation
DurableInFlightEvidenceStore.commit_terminal_reconciliation(...)
~~~

允许的 basis / target state 映射固定为：

~~~text
OPERATION_COMPLETED_CONFIRMED
-> COMPLETED

OPERATION_STOPPED_CONFIRMED
-> CONFIRMED_STOPPED

OPERATION_NOT_FOUND_WITH_PROOF
-> CONFIRMED_STOPPED

PROVIDER_FENCE_ESTABLISHED
-> FENCED_OUT
~~~

不允许任意 caller 自由选择 terminal state。

## 3. FENCED_OUT 语义

新增：

~~~text
InFlightEvidenceState.FENCED_OUT
~~~

它表示：

~~~text
exact provider fence has been durably established
and
the old operation can no longer commit the protected side effect
~~~

它明确不表示：

~~~text
physical process/thread stopped
~~~

因此：

~~~text
FENCED_OUT
!= CONFIRMED_STOPPED
~~~

这样保持：

~~~text
recovery epoch != provider fencing
provider fencing != physical stop proof
~~~

## 4. Durable mutation rules

只有当前 durable observation 为：

~~~text
ORPHANED_UNCONFIRMED
~~~

时，恢复期 reconciliation 才允许提交为 terminal evidence。

提交必须同时满足：

~~~text
exact InFlightOperationHandle
exact operation_handle_id
exact execution provenance
current recovery epoch
reconciliation observed_at >= operation started_at
basis/state mapping valid
~~~

状态迁移：

~~~text
ORPHANED_UNCONFIRMED
-> COMPLETED
or
-> CONFIRMED_STOPPED
or
-> FENCED_OUT
~~~

禁止：

~~~text
ACTIVE_AT_CHECKPOINT -> recovery terminal reconciliation
UNKNOWN -> recovery terminal reconciliation
terminal -> different terminal rewrite
stale recovery epoch -> mutation
handle mismatch -> mutation
~~~

exact replay：

~~~text
same handle
+ same target state
+ same basis
+ same terminal timestamp
-> ALREADY_CURRENT
~~~

## 5. CA-03 Resource Recovery 接线

ToolResourceRecoveryCoordinator 在获得 strong recovery basis 后，必须先提交 durable in-flight terminal truth，再释放 ResourceLock。

顺序冻结：

~~~text
provider/probe strong evidence
-> commit durable in-flight terminal reconciliation
-> release exact resource leases
-> persist binding release tombstone
~~~

原因：

如果先释放资源、后写 durable in-flight evidence，第二次 Recovery 可能仍看到：

~~~text
ORPHANED_UNCONFIRMED
~~~

并永久 WAIT。

如果 durable terminal commit 成功但随后 lock release 失败：

~~~text
terminal in-flight evidence exists
+
active resource binding remains
-> CA-04 still WAIT_RECONCILIATION
~~~

因此仍然 fail-closed。

## 6. Strong evidence mapping

OperationRecoveryProbe：

~~~text
COMPLETED_CONFIRMED
-> durable COMPLETED

STOPPED_CONFIRMED
-> durable CONFIRMED_STOPPED

NOT_FOUND_WITH_PROOF
-> durable CONFIRMED_STOPPED

RUNNING_CONFIRMED
-> no terminal mutation

UNKNOWN
-> no terminal mutation
~~~

Provider fencing：

~~~text
ESTABLISHED
+ exact operation identity
+ exact current recovery epoch
+ durably persisted fence
-> durable FENCED_OUT

UNSUPPORTED / UNKNOWN
-> no terminal mutation
~~~

## 7. No-ResourceLock operation

B-M5-IU9-008 不能只修有 ResourceLock 的 Tool。

对于：

~~~text
orphaned Tool
+ no operation-resource binding
+ no active resource lease
~~~

ToolResourceRecoveryCoordinator 仍需允许通过 exact OperationRecoveryProbe 完成：

~~~text
strong provider evidence
-> durable terminal reconciliation
-> NO_RESOURCE_LOCKS
~~~

如果只能得到 RUNNING / UNKNOWN：

~~~text
durable state remains ORPHANED_UNCONFIRMED
-> recovery remains blocked
~~~

## 8. CA-04 compatibility

CA-04 unresolved set 保持：

~~~text
ACTIVE_AT_CHECKPOINT
ORPHANED_UNCONFIRMED
UNKNOWN
-> WAIT_RECONCILIATION
~~~

以下已是 recovery terminal truth：

~~~text
COMPLETED
CONFIRMED_STOPPED
FENCED_OUT
~~~

因此成功 reconciliation 后，CA-04 不再因同一个 operation 永久 WAIT。

Resource binding 若仍 active，则仍由：

~~~text
active resource binding
-> WAIT_RECONCILIATION
~~~

继续阻挡，直到资源安全回收完成。

## 9. Test scenarios

新增：

~~~text
tests/test_m5_iu9_ca05_inflight_reconciliation.py
~~~

至少覆盖：

~~~text
orphan -> completed durable reconciliation
exact reconciliation replay idempotency
stale recovery epoch cannot terminalize orphan
STOPPED_CONFIRMED -> durable CONFIRMED_STOPPED + resource reclaim
provider fence -> FENCED_OUT, not false CONFIRMED_STOPPED
unbound/no-lock orphan + strong probe -> durable terminal convergence
RUNNING_CONFIRMED does not upgrade orphan
~~~

## 10. Blocker mapping

目标：

~~~text
B-M5-IU9-008
RECOVERY_RECONCILIATION_NOT_COMMITTED_TO_DURABLE_INFLIGHT_TERMINAL_EVIDENCE
-> CLOSED_PENDING_GATES
~~~

只有：

~~~text
Targeted Amendment Review = PASSED
Verification = PASSED
~~~

后才能正式写 CLOSED。

## 11. Frozen non-goals

~~~text
M5-IU9 Formal Implementation wiring
Workflow approved-version source implementation
ExecutionResult aggregation
M6
replanning
capability substitution
generic provider adapter implementation
distributed transaction across evidence/lock/provider
~~~

本 CA 不宣称跨系统 exactly-once。

## 12. Current status

~~~text
CA-M5-IU9-05 = CODE COMPLETE
CA-M5-IU9-05 TARGETED AMENDMENT REVIEW = PENDING
CA-M5-IU9-05 VERIFICATION = PENDING

B-M5-IU9-008 = CLOSED_PENDING_GATES

M5-IU9 IMPLEMENTATION READINESS = NOT_READY
FORMAL IMPLEMENTATION = NOT AUTHORIZED

NEXT REQUIRED =
CA-M5-IU9-05 Targeted Amendment Review
-> Verification
-> M5-IU9 Implementation Readiness Re-Review
~~~
