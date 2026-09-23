# CA-M5-IU9-01 Durable Execution Snapshot + Recovery Claim V1.0

> Base: M5-IU9 Design/Readiness @ c299da62741e39172af142228199548f70e0b576
> Scope: close B-M5-IU9-001 and B-M5-IU9-004 only.
> This amendment freezes recovery state and recovery-writer authority. It does not yet persist IU6 reliability evidence, IU7 control/in-flight state, IU8 locks, or Workflow checkpoints.

## 1. Purpose

CA-01 establishes the minimum Core authority required to answer two questions after restart:

~~~text
1. What exact M5 execution state can be reconstructed?
2. Which runtime generation is currently allowed to mutate it or start a new side effect?
~~~

Without both, persistence is only data storage, not safe recovery.

## 2. Recovery-safe ExecutionContext projection

Added:

~~~text
RecoverySafeExecutionContext
~~~

It persists Core recovery identity and policy context:

~~~text
execution_id
plan_id
request_id
session_id
identity_scope
policy_snapshot
device_id
current_state
step_state
deadline
cancellation_token
trace_context
optional opaque tool_context_reference
~~~

Raw `ExecutionContext.tool_context` is intentionally absent.

Reason:

~~~text
tool_context may contain:
- ephemeral credentials
- connection handles
- process-local objects
- runtime-only authorization state
~~~

Restore always produces:

~~~text
ExecutionContext.tool_context = None
~~~

Any later Tool side effect must reacquire current Permission / Tool Context authority.

## 3. ExecutionRecoverySnapshot

Added versioned snapshot:

~~~text
ExecutionRecoverySnapshot
- schema_version
- checkpoint_id
- generation
- execution_id
- captured_at
- RecoverySafeExecutionContext
- ExecutionRecord
- typed StepLifecycleSnapshot tuple
- execution_started_at
- execution_finished_at
- writer_recovery_epoch
- writer_recovery_owner_id
~~~

Snapshot validates:

~~~text
context / record execution identity
plan / request / identity provenance
aware record timestamps
captured_at >= latest ExecutionRecord.updated_at
unique step_id / step_execution_id
typed steps exactly equal ExecutionRecord.step_results
current_step exactly matches RUNNING step
terminal timing does not move backward
~~~

`restore_prepared_execution()` reconstructs `PreparedExecution` without restoring stale Tool authorization.

## 4. Snapshot generation and CAS

Added:

~~~text
ExecutionRecoverySnapshotStore
InMemoryExecutionRecoverySnapshotStore
RecoverySnapshotWriteStatus
RecoverySnapshotWriteDecision
~~~

Reference CAS rules:

~~~text
no snapshot + expected_generation=0 + generation=1
-> CREATED

exact current snapshot replay
-> ALREADY_CURRENT

existing generation N
+ expected_generation=N
+ candidate generation=N+1
-> UPDATED

stale expected generation
-> CONFLICT

generation jump / time regression
-> CONFLICT
~~~

No stale snapshot overwrites a newer one.

The in-memory store is a contract/reference mechanism only; it is not a production crash-durable adapter claim.

## 5. Recovery claim identity

Added:

~~~text
RecoveryClaimRequest
ExecutionRecoveryClaim
RecoveryClaimStatus / Decision
RecoveryClaimAuthority
InMemoryRecoveryClaimAuthority
~~~

Request carries:

~~~text
claim_id
execution_id
recovery_owner_id
expected_current_epoch
source_snapshot_generation
requested_at
~~~

Accepted claim carries an authority-assigned strictly increasing:

~~~text
recovery_epoch
~~~

## 6. Claim CAS semantics

Rules:

~~~text
initial current_epoch = 0
expected 0 -> recovery_epoch 1

current epoch N
new claim with expected N
-> recovery_epoch N+1

wrong expected epoch
-> CONFLICT / UNKNOWN

same claim_id + exact request + still current
-> ALREADY_CLAIMED

same claim_id reused with changed payload
-> UNKNOWN

old claim exact replay after a takeover
-> CONFLICT
not ALREADY_CLAIMED
~~~

This prevents a stale runtime from reviving an old ownership token via retry.

## 7. Claim must be based on latest snapshot

Added:

~~~text
RecoveryClaimCoordinator
~~~

Before claiming a new epoch it loads the latest snapshot and requires:

~~~text
request.source_snapshot_generation
==
latest snapshot generation
~~~

A claim based on stale snapshot generation cannot become current recovery owner.

## 8. Recovery epoch guard

Added:

~~~text
RecoveryEpochValidationStatus
RecoveryEpochValidationDecision
RecoveryClaimAuthority.validate_current()
~~~

Statuses:

~~~text
CURRENT
STALE
UNKNOWN
~~~

This guard is intentionally reusable by later Formal Implementation at both:

~~~text
state mutation boundary
external side-effect admission boundary
~~~

Therefore:

~~~text
stale recovery epoch
-> cannot save new recovery state
-> must not start new Skill / Workflow / physical Tool side effect
~~~

CA-01 freezes the guard contract. Wiring it into all actual side-effect paths belongs to M5-IU9 Formal Implementation after readiness becomes READY.

## 9. Snapshot mutation requires current claim

Added:

~~~text
ExecutionRecoverySnapshotCoordinator
~~~

Before CAS write it verifies:

~~~text
snapshot.execution_id == claim.execution_id
snapshot.writer_recovery_epoch == claim.recovery_epoch
snapshot.writer_recovery_owner_id == claim.recovery_owner_id
claim == current claim
~~~

Then and only then may snapshot CAS execute.

Old owner after takeover:

~~~text
validate_current -> STALE
save snapshot -> CONFLICT / RECOVERY_SNAPSHOT_STALE_WRITER
~~~

## 10. Why recovery epoch is not ResourceLock fencing

CA-01 explicitly freezes:

~~~text
recovery_epoch
!=
proof that an old external Tool operation cannot still commit
~~~

The epoch protects Core writer / side-effect admission authority.

Physical resource reclaim and provider fencing remain CA-M5-IU9-03.

Therefore CA-01 does not release any stale ResourceLock.

## 11. Reconstructed truth boundary

Recovered `PreparedExecution` is Core execution state only.

It does not assert:

~~~text
Tool operation stopped
ResourceLock free
CANCEL/PREEMPT absent
Workflow resumable
Idempotency safe to replay
~~~

Those stronger side authorities are reconciled by later IU9 amendments.

## 12. Verification scenarios

Covered at minimum:

~~~text
1. snapshot excludes raw tool_context
2. restored ExecutionContext has tool_context=None
3. recovery-safe policy/trace/deadline survive capture/restore
4. capture deep-copies mutable recovery context
5. typed Step / ExecutionRecord mismatch rejected
6. generation 1 create
7. exact snapshot replay idempotent
8. generation N -> N+1 update
9. stale generation cannot overwrite
10. initial claim -> epoch 1
11. current exact claim replay -> ALREADY_CLAIMED
12. takeover -> epoch increments
13. takeover fences old claim as STALE
14. stale owner cannot write recovery snapshot
15. competing takeovers from same epoch -> only one wins
16. stale source snapshot generation cannot claim
17. claim_id payload reuse conflict -> UNKNOWN
18. old claim replay after takeover -> CONFLICT
19. forged snapshot writer claim fails closed
20. terminal PreparedExecution restores terminal timing exactly
~~~

## 13. Blocker mapping

Designed to close:

~~~text
B-M5-IU9-001
EXECUTION_RECOVERY_SNAPSHOT_INCOMPLETE

B-M5-IU9-004
RECOVERY_WRITER_CAS_AND_EPOCH_MISSING
~~~

Still open after CA-01:

~~~text
B-M5-IU9-002 RELIABILITY_REPLAY_EVIDENCE_NOT_CRASH_DURABLE
B-M5-IU9-003 CONTROL_AND_INFLIGHT_STATE_NOT_CRASH_DURABLE
B-M5-IU9-005 RESOURCE_LOCK_CRASH_RECLAIM_AND_FENCING_MISSING
B-M5-IU9-006 WORKFLOW_CHECKPOINT_RESUME_AUTHORITY_INCOMPLETE
B-M5-IU9-007 RECOVERY_DECISION_ORCHESTRATOR_MISSING
~~~

## 14. Explicit exclusions

CA-01 does not implement:

~~~text
durable Step retry / occurrence journal
durable control latch
durable in-flight registry
external operation probe
durable ResourceLock / stale reclaim / provider fencing
Workflow durable checkpoint / resume
RecoveryDisposition orchestration
Execution aggregation
M6
~~~

## 15. Current status

~~~text
CA-M5-IU9-01 = CODE COMPLETE
CA-M5-IU9-01 TARGETED AMENDMENT REVIEW = PENDING
CA-M5-IU9-01 VERIFICATION = PENDING

B-M5-IU9-001 = FIX_IMPLEMENTED_PENDING_REVIEW_AND_GATES
B-M5-IU9-004 = FIX_IMPLEMENTED_PENDING_REVIEW_AND_GATES

M5-IU9 IMPLEMENTATION READINESS = NOT_READY
M5 = IN PROGRESS
~~~