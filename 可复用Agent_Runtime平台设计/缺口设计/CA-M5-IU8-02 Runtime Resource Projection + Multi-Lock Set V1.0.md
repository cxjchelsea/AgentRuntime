# CA-M5-IU8-02 Runtime Resource Projection + Multi-Lock Set V1.0

> Baseline: CA-M5-IU8-01 = PASSED @ 85964f7c4649d9aad178b3df987ef156710267fe
> Scope: close B-M5-IU8-002 and B-M5-IU8-003.
> This amendment does not own session execution locks, operation-lifetime release wiring, or IU9 durable recovery.

## 1. Purpose

CA-01 established typed lock identity and exact acquire/release authority.

CA-02 closes the next two gaps:

~~~text
ToolDefinition.resource_locks
        ↓
runtime ResourceLockRequirement
        ↓
injected ResourceLockRequirementResolver
        ↓
opaque concrete lock_key
        ↓
canonical lock-set acquisition
        ↓
all acquired
or
partial rollback
~~~

Core invariants:

~~~text
resource_ref != concrete lock_key
projection UNKNOWN -> no physical side effect
multi-lock acquire order is deterministic
partial acquire must rollback newly-acquired leases
rollback uncertainty -> whole lock-set UNKNOWN
replayed existing lease != rollback candidate
~~~

## 2. Runtime resource projection

Added:

~~~text
ResourceLockRequirement
ResolvedResourceLock
ResourceLockResolutionStatus / Decision
ResourceLockRequirementResolver
ResourceLockProjectionStatus / Decision
ToolResourceLockProjector
~~~

ToolDefinition.resource_locks remains static Registry metadata.

The Core does not parse business/device semantics from the ref.

Injected resolver input includes:

~~~text
resource requirement
ExecutionContext
tool_call_id
physical_attempt
~~~

Resolver output contains:

~~~text
resource_ref
opaque lock_key
provenance
~~~

The same real resource must resolve to the same lock_key.

Different real resources must not be collapsed by Core-generated rules.

## 3. Fail-closed projection

If any declared resource cannot be resolved:

~~~text
projection = UNKNOWN
resolved_locks = ()
~~~

Partial projection is never exposed as usable authority.

Resolver exception, malformed decision, or resource_ref identity mismatch also produces UNKNOWN.

A Tool declaring no resource locks resolves successfully to an empty lock set.

Duplicate static refs are deduplicated before resolver calls.

## 4. Concrete lock aliases

Different resource refs may resolve to the same concrete lock_key.

Example:

~~~text
ref A -> lock X
ref B -> lock X
~~~

The projection may preserve both resolved provenance records.

The lock-set coordinator canonicalizes by concrete lock_key and acquires X only once.

This prevents aliases for the same physical resource from creating self-deadlock.

## 5. Lock-set identity

Added:

~~~text
ResourceLockSetRequest
ResourceLockSetStatus
ResourceLockSetDecision
ResourceLockAcquisitionIdentifierFactory
Sha256ResourceLockAcquisitionIdentifierFactory
ResourceLockSetCoordinator
~~~

One lock set has:

~~~text
lock_set_id
owner
resolved_locks
requested_at
~~~

The coordinator canonicalizes the concrete set by:

~~~text
deduplicate lock_key
sort lock_key
~~~

Then computes a fingerprint over the entire canonical lock set.

Each per-lock acquisition_id is deterministically bound to:

~~~text
lock_set_id
+
whole lock-set fingerprint
+
lock_key
~~~

Therefore reusing the same lock_set_id with changed membership is not an exact replay.

## 6. Deterministic acquisition order

All runtime instances use the same total order:

~~~text
sorted concrete lock_key
~~~

Example:

~~~text
input:
z-lock
a-lock
m-lock

acquire:
a-lock
m-lock
z-lock
~~~

This is the minimum deadlock-avoidance rule for IU8 without introducing a new parallel scheduler.

## 7. Lock-set outcomes

~~~text
ACQUIRED
BUSY
UNKNOWN
~~~

### ACQUIRED

Every unique concrete lock is either:

~~~text
ACQUIRED
or exact ALREADY_ACQUIRED
~~~

and the decision exposes the complete lease set in canonical order.

Empty lock sets are valid ACQUIRED no-ops.

### BUSY

A lock is BUSY and every lease newly acquired during the current call has been confirmed released.

BUSY must not expose retained leases.

### UNKNOWN

Returned when:

~~~text
acquire authority is UNKNOWN
acquire authority returns malformed/mismatched evidence
acquisition id cannot be generated
rollback cannot be confirmed
exact replayed leases coexist with later set failure
~~~

UNKNOWN is fail-closed.

## 8. Partial acquisition rollback

For:

~~~text
A -> ACQUIRED
B -> ACQUIRED
C -> BUSY
~~~

rollback is:

~~~text
release B
release A
~~~

Only leases newly obtained as ACQUIRED during the current coordinator call are rollback candidates.

This is important:

~~~text
ALREADY_ACQUIRED
!= newly acquired by this call
~~~

A replayed lease may belong to a real operation already in progress and must never be released merely because a later lock in the current replay attempt fails.

## 9. Replayed lease + later failure

If:

~~~text
A -> ALREADY_ACQUIRED
B -> BUSY / UNKNOWN
~~~

the coordinator returns:

~~~text
UNKNOWN
retained_leases = (A,)
LOCK_SET_REPLAY_PARTIAL_STATE
~~~

It does not release A.

This preserves operation-lifetime truth for CA-M5-IU8-03.

## 10. Rollback uncertainty

If rollback release returns:

~~~text
UNKNOWN
NOT_OWNER
malformed decision
exception
identity mismatch
~~~

the whole lock-set outcome becomes:

~~~text
UNKNOWN
~~~

and the corresponding lease remains in retained_leases.

If rollback time cannot be established or would precede acquire time:

~~~text
UNKNOWN
retained_leases = all newly acquired leases
~~~

The Core must not pretend those resources are free.

## 11. Exact lock-set replay

Same:

~~~text
lock_set_id
same canonical concrete lock membership
same lock keys
~~~

produces the same acquisition ids.

CA-01 then returns ALREADY_ACQUIRED for active exact leases.

Changing membership changes the whole-set fingerprint and therefore changes acquisition identity, preventing false exact replay.

## 12. Explicit exclusions

CA-02 does not implement:

~~~text
session_execution_lock
Tool physical-call wiring
permission/idempotency/resource-lock gate wiring
normal-completion release
IU7 CONFIRMED_STOPPED release
timeout/UNKNOWN lock retention wiring
stale lock reclaim
lease expiry
fencing
durable lock persistence
checkpoint/recovery
parallel scheduler
aggregation
M6
~~~

These remain CA-M5-IU8-03 / IU9 / IU10 / Runtime boundaries.

## 13. Blocker mapping

CA-02 is designed to close:

~~~text
B-M5-IU8-002
RUNTIME_RESOURCE_IDENTITY_UNRESOLVED

B-M5-IU8-003
MULTI_LOCK_ORDER_AND_PARTIAL_ROLLBACK_MISSING
~~~

It does not close:

~~~text
B-M5-IU8-004
LOCK_RELEASE_AUTHORITY_NOT_OPERATION_BOUND

B-M5-IU8-005
SESSION_EXECUTION_LOCK_AUTHORITY_MISSING
~~~

## 14. Verification scenarios

Covered at minimum:

~~~text
runtime context is consumed by injected resolver
no-lock Tool is a successful empty projection
duplicate resource refs are deduplicated
unresolved resource -> UNKNOWN with no partial resolved locks
resolver exception -> UNKNOWN
canonical concrete lock ordering
duplicate concrete lock keys acquired once
partial BUSY -> reverse rollback
partial UNKNOWN -> reverse rollback
rollback UNKNOWN -> whole set UNKNOWN + retained lease
rollback NOT_OWNER -> whole set UNKNOWN + retained lease
invalid rollback clock -> retained lease
exact set replay -> deterministic acquisition ids
same set id with changed membership != exact replay
replayed existing lease is not rolled back on later failure
mismatched successful acquire evidence -> UNKNOWN
~~~

## 15. Current status

~~~text
CA-M5-IU8-02 = CODE COMPLETE
CA-M5-IU8-02 TARGETED AMENDMENT REVIEW = PASSED
CA-M5-IU8-02 VERIFICATION = PASSED
CA-M5-IU8-02 = PASSED

B-M5-IU8-002 = CLOSED
B-M5-IU8-003 = CLOSED

B-M5-IU8-004 = OPEN
B-M5-IU8-005 = OPEN

M5-IU8 IMPLEMENTATION READINESS = NOT_READY

NEXT REQUIRED =
CA-M5-IU8-03
Session Lock + Operation-Bound Release

M5 = IN PROGRESS
~~~
