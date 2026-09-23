# CA-M5-IU8-03 Session Lock + Operation-Bound Release V1.0

> Baseline: CA-M5-IU8-02 = PASSED @ 1ff03a4b39e89ccc675b969e1543d1edce1b2839
> Scope: close B-M5-IU8-004 and B-M5-IU8-005.
> This amendment remains live/in-memory. Durable lease persistence, stale reclaim, fencing, crash recovery, and restart semantics remain IU9.

## 1. Purpose

CA-01 established typed lock authority.

CA-02 established:

~~~text
resource_ref -> concrete lock_key
canonical multi-lock acquisition
partial-acquire rollback
~~~

CA-03 closes the final IU8 readiness gaps:

~~~text
A. same-session execution mutual exclusion

B. exact Tool resource lease lifetime
   must follow real physical operation lifetime
~~~

Core invariants:

~~~text
session lock BUSY != PREEMPT
session lock BUSY != priority recomputation

executor returned != underlying operation stopped
timeout observed != resource safe to release
interrupt requested != resource safe to release

normal physical completion -> release may be authorized
Tool CONFIRMED_STOPPED -> release may be authorized

ALREADY_COMPLETED interrupt outcome
!= actual completion observation

NOT_CANCELLABLE / UNKNOWN
-> retain resource lease
~~~

## 2. Session execution lock

Added:

~~~text
SessionExecutionLockIdentityFactory
Sha256SessionExecutionLockIdentityFactory

SessionExecutionLease

SessionExecutionAcquireStatus / Decision
SessionExecutionReleaseStatus / Decision

SessionExecutionLockCoordinator
~~~

The Core session lock key is deterministically derived from the generic Core session_id.

No Domain/business semantics are used.

The default implementation namespaces the identity:

~~~text
session-execution:sha256:<digest(session_id)>
~~~

The acquisition identity is deterministically bound to:

~~~text
session_id
+
execution_id
~~~

The ResourceLockOwner for a session lock is:

~~~text
owner_id = execution_id
execution_id = execution_id
no step_execution_id
no tool_call_id
no physical_attempt
~~~

## 3. Session mutual exclusion semantics

For one session:

~~~text
execution-1 acquire
-> ACQUIRED

execution-1 exact replay
-> ALREADY_ACQUIRED

execution-2 acquire while execution-1 holds
-> BUSY
~~~

BUSY does not trigger:

~~~text
CANCEL
PREEMPT
priority comparison
M2 recomputation
ApprovedActionPlan rewrite
~~~

The caller/Runtime may decide what to do later.

IU8 only proves that the second execution does not own the session execution resource.

Different session_id values map to different session lock identities.

## 4. Session lock release authority

A session lease can be released only when the current PreparedExecution is authoritatively terminal.

Required:

~~~text
ExecutionRecord.status is one of:
SUCCESS
PARTIAL_SUCCESS
FAILED
CANCELLED
TIMEOUT
PREEMPTED

PreparedExecution.finished_at is present

all Step statuses are terminal
~~~

If execution remains RUNNING or any Step remains PENDING/RUNNING:

~~~text
RETAINED
EXECUTION_NOT_AUTHORITATIVELY_TERMINAL
~~~

Release time must not precede:

~~~text
PreparedExecution.finished_at
ExecutionRecord.updated_at
session lease acquired_at
~~~

## 5. Exact session lease identity

Release does not trust wrapper fields alone.

Before release, CA-03 recomputes expected:

~~~text
session lock_key
session acquisition_id
~~~

from:

~~~text
prepared.execution_context.session_id
prepared.execution_context.execution_id
~~~

and verifies:

~~~text
execution context id
execution record id
session lease execution_id
session lease session_id
ResourceLockOwner.execution_id
ResourceLockOwner.owner_id
expected lock_key
expected acquisition_id
~~~

Any mismatch:

~~~text
UNKNOWN
no ResourceLockAuthority.release call
~~~

This prevents an unrelated ordinary resource lease from being wrapped as a session lease.

## 6. Operation-bound resource lease

Added:

~~~text
OperationResourceLeaseBinding
OperationResourceLeaseRegistry
InMemoryOperationResourceLeaseRegistry

OperationResourceReleaseStatus / Decision
OperationResourceReleaseCoordinator
~~~

One binding links:

~~~text
exact IU7 InFlightOperationHandle(kind=TOOL)
+
exact ResourceLockOwner
+
exact ResourceLockLease set
~~~

Binding invariants:

~~~text
handle execution_id == owner execution_id
handle step_execution_id == owner step_execution_id
handle tool_call_id == owner tool_call_id
owner has physical_attempt
every lease.owner == exact owner
lock_key unique
acquisition_id unique
lease acquired_at <= Tool operation started_at
~~~

Therefore ResourceLock truth and IU7 InFlightOperation truth refer to the same physical Tool operation boundary.

## 7. Live operation-resource registry

The binding registry is live only:

~~~text
operation_handle_id -> exact OperationResourceLeaseBinding
~~~

Rules:

~~~text
exact register replay -> idempotent false
same operation_handle_id + different binding -> rejected
release authority requires the exact binding to remain active
full confirmed release -> remove exact binding
partial/uncertain release -> keep binding for safe retry
~~~

This is not a durable store.

Process restart / reconstruction remains IU9.

## 8. Normal completion release

Formal release method:

~~~text
release_after_completion(
    exact binding,
    exact completed_handle,
    completed_at
)
~~~

Release authority requires:

~~~text
completed_handle == binding.handle
completed_at timezone-aware
completed_at >= Tool handle started_at
completed_at >= every lease acquired_at
exact binding still active
~~~

Only then are exact leases released.

This path is intended for:

~~~text
Tool coroutine / adapter has truly completed
or
has truly raised and the physical operation is known ended
~~~

It is not for:

~~~text
wait timeout
caller gave up waiting
owner timeout without Tool stop proof
~~~

## 9. IU7 interrupt release

CA-03 consumes the already-frozen IU7 HierarchicalInterruptSummary.

For an exact bound Tool handle:

~~~text
summary must match execution_id + step_execution_id
summary.status must be ORDERED
summary must contain exactly the bound Tool handle + its matching outcome
~~~

Then:

### CONFIRMED_STOPPED

~~~text
Tool outcome = CONFIRMED_STOPPED
-> exact Tool leases may be released
~~~

This uses the Tool outcome itself.

The parent Skill/Workflow outcome does not substitute for missing Tool stop evidence.

### ALREADY_COMPLETED

~~~text
Tool outcome = ALREADY_COMPLETED
-> RETAINED
-> ALREADY_COMPLETED_AWAITING_REAL_COMPLETION
~~~

Reason:

~~~text
interrupt controller reports operation was already complete
!=
Core has observed the actual completion boundary required to close the resource lifetime
~~~

The normal completion path must reconcile it.

### NOT_CANCELLABLE

~~~text
RETAINED
NOT_CANCELLABLE_RESOURCE_RETAINED
~~~

### UNKNOWN

~~~text
RETAINED
INTERRUPT_UNKNOWN_RESOURCE_RETAINED
~~~

### AMBIGUOUS / malformed / missing Tool outcome

~~~text
UNKNOWN
retained_leases = exact binding leases
~~~

No release is attempted.

## 10. Multi-lease release

For one Tool operation holding multiple resource leases, release is performed in reverse lease order.

Per-lease release accepts only:

~~~text
RELEASED
ALREADY_RELEASED
~~~

as confirmed free.

If any lease returns:

~~~text
NOT_OWNER
UNKNOWN
malformed evidence
exception
~~~

the operation resource result becomes:

~~~text
UNKNOWN
~~~

and exact unreleased leases remain in retained_leases.

Leases already confirmed released remain in released_leases.

The live operation binding remains registered so a safe idempotent retry can occur.

## 11. Why no finally-release

CA-03 explicitly forbids this pattern as the IU8 authority model:

~~~text
try:
    await physical_tool()
finally:
    release(resource_lock)
~~~

because a timeout runner or cancellation wrapper can return control while the underlying operation is still alive.

The correct authority is:

~~~text
normal real completion
OR
exact Tool CONFIRMED_STOPPED
~~~

not Python lexical scope exit.

## 12. Relation to IU7

IU7 owns:

~~~text
InFlightOperationHandle
InFlightOperationRegistry
InterruptOutcome
HierarchicalInterruptSummary
CONFIRMED_STOPPED
ALREADY_COMPLETED
NOT_CANCELLABLE
UNKNOWN
~~~

IU8 CA-03 reuses those contracts.

It does not create a second interrupt truth.

Formal relation:

~~~text
IU7 Tool InFlightOperationHandle
        ↕ exact identity
IU8 OperationResourceLeaseBinding
        ↕
ResourceLockLease
~~~

A Tool that IU7 still considers possibly active cannot have its resource lease released by timeout/UNKNOWN shortcuts.

## 13. Relation to execution lifecycle

Session lock release consumes PreparedExecution as lifecycle truth.

It does not mutate lifecycle.

CA-03 does not:

~~~text
finish Step
finish Execution
terminalize CANCEL/PREEMPT
aggregate ExecutionResult
~~~

It only decides whether the existing terminal lifecycle state is sufficient to release the session lock.

## 14. Explicit exclusions

CA-03 does not implement:

~~~text
full Tool invocation wiring
full session-lock runtime wiring
new parallel scheduler
priority recomputation
automatic PREEMPT on BUSY
lease expiry
stale-lock reclaim
fencing token
durable lease persistence
restart reconstruction
Checkpoint
Crash Recovery
Workflow resume
Execution aggregation
M6
Runtime new-cycle start
~~~

The first two are Formal Implementation wiring after IU8 readiness becomes READY.

Durable recovery remains IU9.

## 15. Verification scenarios

Covered at minimum:

~~~text
1. same session second execution -> BUSY
2. same execution exact session acquire replay -> ALREADY_ACQUIRED
3. different sessions can hold session locks concurrently
4. RUNNING execution retains session lease
5. terminal execution + all terminal Steps releases session lease
6. terminal execution status + nonterminal Step does not release
7. release cannot precede latest execution observation
8. forged session lock_key cannot release
9. Tool binding requires exact execution/step/tool provenance
10. Tool lease must exist before operation starts
11. operation binding cannot be rebound
12. normal exact Tool completion releases resources
13. completion identity mismatch retains resources
14. Tool CONFIRMED_STOPPED releases resources
15. ALREADY_COMPLETED retains until real completion observation
16. NOT_CANCELLABLE retains
17. UNKNOWN retains
18. ambiguous interrupt summary cannot release
19. partial release uncertainty preserves retained leases + active binding
20. release requires exact active operation-resource binding
~~~

## 16. Blocker mapping

Designed to close:

~~~text
B-M5-IU8-004
LOCK_RELEASE_AUTHORITY_NOT_OPERATION_BOUND

B-M5-IU8-005
SESSION_EXECUTION_LOCK_AUTHORITY_MISSING
~~~

After closure of these two blockers, all original IU8 readiness blockers are closed.

That still does not automatically mean:

~~~text
M5-IU8 = PASSED
~~~

The next governance step must be:

~~~text
M5-IU8 Implementation Readiness Re-Review
~~~

Only a READY decision authorizes IU8 Formal Implementation wiring.

## 17. Current status

~~~text
CA-M5-IU8-03 = CODE COMPLETE
CA-M5-IU8-03 TARGETED AMENDMENT REVIEW = PENDING
CA-M5-IU8-03 VERIFICATION = PENDING

B-M5-IU8-004 = FIX_IMPLEMENTED_PENDING_REVIEW_AND_GATES
B-M5-IU8-005 = FIX_IMPLEMENTED_PENDING_REVIEW_AND_GATES

M5-IU8 IMPLEMENTATION READINESS = NOT_READY
M5 = IN PROGRESS
~~~
