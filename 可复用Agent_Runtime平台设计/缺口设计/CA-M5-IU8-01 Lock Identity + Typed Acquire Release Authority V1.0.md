# CA-M5-IU8-01 Lock Identity + Typed Acquire/Release Authority V1.0

> Baseline: M5-IU8 Design/Readiness @ 3f4ce540cc2819dcfd71d133bae264b51e5a8aa7
> Scope: close B-M5-IU8-001 RESOURCE_LOCK_AUTHORITY_NOT_AUDITABLE.
> This amendment does not resolve runtime resource refs, coordinate multi-lock sets, bind session execution locks, or implement IU9 recovery.

## 1. Purpose

Existing seed contract:

~~~text
ResourceLockProvider.acquire(resource_id, owner_id) -> bool
ResourceLockProvider.release(resource_id, owner_id) -> None
~~~

cannot distinguish exact replay, busy, provider uncertainty, wrong-owner release, or release replay.

CA-01 freezes an auditable typed authority:

~~~text
ResourceLockOwner
ResourceLockAcquireRequest
ResourceLockLease
ResourceLockAcquireStatus / Decision
ResourceLockReleaseStatus / Decision
ResourceLockAuthority
InMemoryResourceLockAuthority
~~~

## 2. Owner identity

Tool resource-lock owner identity is bound to physical-operation provenance:

~~~text
owner_id
execution_id
step_execution_id
tool_call_id
physical_attempt
~~~

If tool_call_id is present, physical_attempt must also be present, and vice versa.
A Tool owner also requires step_execution_id.

Session-level owner identity is intentionally allowed to omit Tool fields; session lock semantics belong CA-M5-IU8-03.

## 3. Acquire identity

Every acquisition has immutable:

~~~text
lock_key
owner
acquisition_id
requested_at
~~~

A successful acquisition returns a lease:

~~~text
lock_key
owner
acquisition_id
acquired_at
~~~

All times are timezone-aware.

## 4. Acquire outcomes

~~~text
ACQUIRED
ALREADY_ACQUIRED
BUSY
UNKNOWN
~~~

ALREADY_ACQUIRED is allowed only for exact replay:

~~~text
same acquisition_id
same lock_key
same ResourceLockOwner
same active lease
~~~

Important:

~~~text
same owner_id
+
different acquisition_id
=
BUSY
not replay
~~~

This prevents one logical owner from accidentally hiding multiple physical operations.

UNKNOWN is used when acquisition identity conflicts or exact replay is no longer provably active. UNKNOWN never exposes a lease.

## 5. No silent stealing

Active lock ownership is never replaced by:

~~~text
same Tool
same execution
same owner_id
timeout
new acquisition request
~~~

Only exact lease release removes an active lock.

There is no stale-lock timeout, lease expiry, reclaim, or fencing in CA-01. Those remain IU9.

## 6. Release authority

Release consumes the exact ResourceLockLease.

Outcomes:

~~~text
RELEASED
ALREADY_RELEASED
NOT_OWNER
UNKNOWN
~~~

Current in-memory authority produces RELEASED / ALREADY_RELEASED / NOT_OWNER directly.
The UNKNOWN enum remains part of the frozen provider-facing authority contract for later non-memory providers where release state cannot be established.

Release rules:

~~~text
exact lease -> RELEASED
exact release replay -> ALREADY_RELEASED
wrong acquisition -> NOT_OWNER
wrong owner -> NOT_OWNER
active lease mismatch -> NOT_OWNER
~~~

Release before acquired_at is invalid.

## 7. Re-acquire after release

After an exact lease is released:

~~~text
same acquisition_id replay
-> UNKNOWN
~~~

because that acquisition is no longer active and must not be resurrected.

A new acquisition_id may acquire the now-free lock. This keeps acquisition identity single-use.

## 8. Legacy provider boundary

Existing runtime.execution.stores.ResourceLockProvider is retained only for backward compatibility/readiness history.

It is explicitly not the IU8 formal authority because bool/None cannot satisfy auditability.

IU8 formal wiring must use:

~~~text
runtime.execution.resource_lock.ResourceLockAuthority
~~~

## 9. Explicit exclusions

CA-01 does not implement:

~~~text
ToolDefinition.resource_locks -> concrete lock_key projection
resource-ref resolver
multi-lock ordering
partial-acquire rollback
session execution lock
physical-operation lifetime wiring
IU7 CONFIRMED_STOPPED release wiring
timeout/UNKNOWN retention wiring
durable lock persistence
lease expiry
stale reclaim
fencing
checkpoint/recovery
aggregation
M6
~~~

## 10. Verification scenarios

Covered:

~~~text
1. first exact acquire -> ACQUIRED + lease
2. exact active replay -> ALREADY_ACQUIRED
3. same owner / different acquisition -> BUSY
4. different owner cannot steal
5. acquisition_id cannot be rebound
6. exact release -> RELEASED
7. exact release replay -> ALREADY_RELEASED
8. wrong acquisition cannot release
9. wrong owner cannot release
10. released acquisition cannot be resurrected
11. new acquisition may acquire after release
12. Tool owner provenance must be structurally complete
13. naive datetime rejected
14. release time cannot precede acquire
15. typed decisions reject invalid enum/lease shapes
~~~

## 11. Blocker mapping

Designed to close:

~~~text
B-M5-IU8-001
RESOURCE_LOCK_AUTHORITY_NOT_AUDITABLE
~~~

Does not close:

~~~text
B-M5-IU8-002
B-M5-IU8-003
B-M5-IU8-004
B-M5-IU8-005
~~~

## 12. Current status

~~~text
CA-M5-IU8-01 = CODE COMPLETE
CA-M5-IU8-01 TARGETED AMENDMENT REVIEW = PASSED
CA-M5-IU8-01 VERIFICATION = PASSED
CA-M5-IU8-01 = PASSED

B-M5-IU8-001 = CLOSED

M5-IU8 IMPLEMENTATION READINESS = NOT_READY
B-M5-IU8-002 = OPEN
B-M5-IU8-003 = OPEN
B-M5-IU8-004 = OPEN
B-M5-IU8-005 = OPEN

NEXT REQUIRED =
CA-M5-IU8-02
Runtime Resource Projection + Multi-Lock Set

M5 = IN PROGRESS
~~~
