# M5-IU8 Implementation Readiness Re-Review V1.0

> Review target: M5-IU8 Step 10 — Concurrency / Resource Lock.
> Baseline chain:
>
> - M5-IU8 Design/Readiness @ 3f4ce540cc2819dcfd71d133bae264b51e5a8aa7
> - CA-M5-IU8-01 = PASSED @ 85964f7c4649d9aad178b3df987ef156710267fe
> - CA-M5-IU8-02 = PASSED @ 1ff03a4b39e89ccc675b969e1543d1edce1b2839
> - CA-M5-IU8-03 = PASSED @ 653a2619cb9b444071dfdeb84cfe0740cc19d2a8
>
> This review decides only whether Formal Implementation wiring is now authorized.

## 1. Final readiness decision

~~~text
M5-IU8 IMPLEMENTATION DESIGN = COMPLETE
M5-IU8 INDEPENDENT DESIGN REVIEW = PASSED

CA-M5-IU8-01 = PASSED
CA-M5-IU8-02 = PASSED
CA-M5-IU8-03 = PASSED

B-M5-IU8-001 = CLOSED
B-M5-IU8-002 = CLOSED
B-M5-IU8-003 = CLOSED
B-M5-IU8-004 = CLOSED
B-M5-IU8-005 = CLOSED

M5-IU8 IMPLEMENTATION READINESS RE-REVIEW = PASSED
M5-IU8 IMPLEMENTATION READINESS = READY

BLOCKERS = 0
NEW BLOCKER = NONE

FORMAL IMPLEMENTATION = AUTHORIZED
~~~

READY authorizes only the frozen IU8 Formal Implementation scope.

It does not mean:

~~~text
M5-IU8 = PASSED
M5 = CLOSED
IU9 recovery = implemented
IU10 aggregation = implemented
M6 = implemented
~~~

## 2. Evidence reviewed

The re-review independently checked the cumulative CA chain rather than inferring READY only from blocker labels.

### CA-M5-IU8-01

Frozen and verified:

~~~text
typed ResourceLockOwner
typed acquire / release outcomes
immutable acquisition identity
exact active replay
wrong-owner / wrong-acquisition rejection
no silent lock stealing
single-use acquisition identity
~~~

Decision:

~~~text
B-M5-IU8-001 = CLOSED
~~~

### CA-M5-IU8-02

Frozen and verified:

~~~text
static resource_ref != concrete lock_key
injected runtime resolver
projection UNKNOWN -> no partial usable lock authority
canonical concrete lock-key ordering
concrete-key deduplication
whole-set fingerprint
partial-acquire reverse rollback
rollback uncertainty -> whole set UNKNOWN
ALREADY_ACQUIRED lease not treated as newly acquired rollback target
~~~

Decision:

~~~text
B-M5-IU8-002 = CLOSED
B-M5-IU8-003 = CLOSED
~~~

### CA-M5-IU8-03

Frozen and verified:

~~~text
same-session execution mutual exclusion
BUSY != PREEMPT / priority recomputation
session release only after authoritative terminal execution
exact session lease identity re-validation

exact IU7 Tool operation_handle_id
==
ResourceLockOwner.owner_id

normal real Tool completion may release
Tool CONFIRMED_STOPPED may release

ALREADY_COMPLETED -> retain until real completion
NOT_CANCELLABLE -> retain
UNKNOWN -> retain
ambiguous interrupt evidence -> no release

partial release uncertainty -> retained lease evidence
~~~

Decision:

~~~text
B-M5-IU8-004 = CLOSED
B-M5-IU8-005 = CLOSED
~~~

## 3. Readiness gate re-evaluation

The original IU8 Readiness Review required 16 conditions.

### Gate 1-6 — Controlled Amendments

~~~text
CA-01 Targeted Review = PASSED
CA-01 Verification = PASSED

CA-02 Targeted Review = PASSED
CA-02 Verification = PASSED

CA-03 Targeted Review = PASSED
CA-03 Verification = PASSED
~~~

Result: PASS.

### Gate 7 — Original blockers

~~~text
B-M5-IU8-001..005 = CLOSED
~~~

Result: PASS.

### Gate 8 — no silent lock stealing

CA-01 requires exact acquisition identity and never replaces another active lease.

Result: PASS.

### Gate 9 — acquire UNKNOWN means no physical side effect

CA-01/02 expose typed UNKNOWN and projection/acquisition cannot authorize physical execution without ACQUIRED/ALREADY_ACQUIRED lock-set authority.

Result: PASS.

### Gate 10 — partial lock-set acquisition cannot leak confirmed-free assumptions

CA-02 reverse-rolls newly acquired leases and escalates uncertain rollback to UNKNOWN with retained lease evidence.

Result: PASS.

### Gate 11 — timeout/UNKNOWN operation cannot release exclusive resource

CA-03 release authority requires real completion or exact Tool CONFIRMED_STOPPED.

Result: PASS.

### Gate 12 — IU7 operation truth and IU8 lease provenance stay consistent

CA-03 binds:

~~~text
ResourceLockOwner.owner_id
==
exact IU7 Tool operation_handle_id
~~~

and also validates execution / step / tool_call provenance.

Result: PASS.

### Gate 13 — session BUSY does not recompute priority

SessionExecutionLockCoordinator returns BUSY only.

No PREEMPT / CANCEL / priority path exists in CA-03.

Result: PASS.

### Gate 14 — no new parallel scheduler

No scheduler or execution graph parallelization was added.

Result: PASS.

### Gate 15 — IU9 durable recovery boundary preserved

Absent from IU8 implementation authority:

~~~text
durable lease persistence
lease expiry
stale reclaim
process restart reconstruction
fencing implementation
checkpoint / crash recovery
Workflow resume
~~~

Result: PASS.

### Gate 16 — IU10 / M6 boundary preserved

No Execution aggregation or M6 validation entered CA-01/02/03.

Result: PASS.

## 4. Integration-point review against the current runtime

Readiness was also checked against the actual M5 execution paths.

Current Core Tool execution has two physical paths:

~~~text
A. baseline path
CoreApprovedToolInvoker.execute_physical_attempt()

B. IU6 reliability path
CoreApprovedToolInvoker._execute_reliable_tool_attempt()
~~~

Current IU7 in-flight tracking is already wired in the baseline physical-attempt path.

The IU6 reliability path currently performs the physical invoke separately and therefore does not yet use the same nested Tool in-flight helper.

This is a real Formal Implementation requirement, but not a readiness-contract blocker.

Reason:

~~~text
the exact contracts needed to correct it now exist
~~~

Formal IU8 is specifically authorized to unify both physical Tool paths around the frozen exact operation / lock authorities.

If Formal Implementation leaves either path outside IU8 locking/in-flight provenance, the later Independent Implementation Review must fail.

## 5. Mandatory Formal Implementation wiring

READY is conditional on the following exact implementation scope.

### 5.1 Session admission

Before an execution performs the first real Step side effect:

~~~text
ExecutionContext.session_id
↓
SessionExecutionLockCoordinator.acquire
↓
ACQUIRED / exact ALREADY_ACQUIRED
    -> execution may proceed toward real Step side effects

BUSY
    -> no real Step side effect

UNKNOWN
    -> no real Step side effect
~~~

BUSY must not call PREEMPT or rerun M2.

### 5.2 Physical Tool admission order

For every real physical Tool attempt, including IU6 retry attempts:

~~~text
exact resolved Tool
↓
input validation
↓
current execution permission
↓
IU6 idempotency / replay preflight
↓
generate exact Tool operation_handle_id
↓
project resource_ref -> concrete lock_key
↓
acquire canonical lock set
↓
construct exact ResourceLockOwner(owner_id = operation_handle_id)
↓
construct Tool InFlightOperationHandle
↓
bind ResourceLockLease set to exact Tool handle
↓
register exact Tool in-flight handle
↓
Tool physical invoke may begin
~~~

Implementation may reorder handle construction details only if all frozen time and identity invariants remain true.

In particular:

~~~text
lease.acquired_at <= Tool handle.started_at
~~~

and no physical invoke may occur before lock and operation authority are established.

### 5.3 Baseline and reliability paths must converge

IU8 Formal Implementation must cover both:

~~~text
execute_physical_attempt()
_execute_reliable_tool_attempt()
~~~

including every retry physical_attempt.

This is mandatory because:

~~~text
IU6 retry attempt
is still a real physical Tool operation
is still subject to IU7 control
is still subject to IU8 resource exclusion
~~~

No reliability bypass is permitted.

## 6. Pre-operation admission failure rule

There is a narrow failure window after a complete lock-set acquisition but before Tool physical invoke:

~~~text
lock set acquired
↓
binding / in-flight registration fails
↓
Tool has not started
~~~

CA-02 successful lock-set output may include exact ALREADY_ACQUIRED replay leases together with newly acquired leases.

Therefore Formal Implementation must not blindly release the whole successful lease set during this failure window.

First-version frozen safe rule:

~~~text
physical invoke = FORBIDDEN
outcome = UNKNOWN / fail closed

if exact newly-acquired-only rollback provenance is unavailable:
    retain the lease set
    do not guess release
~~~

This may reduce liveness, but preserves safety.

Durable reclaim remains IU9.

Formal Implementation may perform a safe rollback only when it can prove the exact lease was newly acquired by the current admission attempt.

## 7. Normal completion ordering

When the Tool physical operation is definitively complete:

~~~text
real physical completion observed
↓
OperationResourceReleaseCoordinator.release_after_completion
↓
release exact leases
↓
complete/remove IU7 Tool in-flight handle
~~~

If release is UNKNOWN:

~~~text
operation truth may still become completed
resource binding / retained lease evidence remains
~~~

The implementation must not claim the physical Tool is still running merely because lock release is uncertain.

Operation truth and resource ownership truth are separate facts.

## 8. Timeout / UNKNOWN ordering

For timeout or uncertain underlying operation state:

~~~text
Tool timeout boundary observed
!= Tool stopped
~~~

Therefore:

~~~text
keep IU7 Tool in-flight handle active
keep IU8 operation-resource binding active
keep exact resource leases held
return TIMEOUT / UNKNOWN evidence as already defined
~~~

No finally-release.

## 9. CANCEL / PREEMPT ordering

When IU7 interrupt produces exact Tool:

~~~text
CONFIRMED_STOPPED
~~~

Formal IU8 may release that Tool's leases.

The implementation must also reconcile the IU7 in-flight handle so the system does not leave:

~~~text
IU7 says active
while
IU8 resource is already free
~~~

Safe first-version ordering:

~~~text
CONFIRMED_STOPPED observed
↓
complete/remove exact stopped Tool in-flight handle
↓
release exact resource leases
↓
retain binding evidence if release is uncertain
~~~

For:

~~~text
ALREADY_COMPLETED
NOT_CANCELLABLE
UNKNOWN
AMBIGUOUS
~~~

the CA-03 rules remain authoritative and no speculative release is allowed.

## 10. Session terminal release

After the full execution reaches authoritative terminal lifecycle:

~~~text
all Steps terminal
+
Execution terminal
+
finished_at present
↓
SessionExecutionLockCoordinator.release_if_terminal
~~~

A Step completion alone never releases the session execution lease.

Session release uncertainty does not retroactively rewrite execution lifecycle.

## 11. Existing current-code gap classification

The current reliability-path absence of nested Tool in-flight registration is classified as:

~~~text
FI-M5-IU8-REQ-001
RELIABLE_TOOL_PATH_MUST_SHARE_EXACT_INFLIGHT_RESOURCE_BOUNDARY
~~~

Status:

~~~text
FORMAL IMPLEMENTATION REQUIRED
NOT A READINESS BLOCKER
~~~

Reason:

- the missing behavior is the exact wiring that Formal Implementation is about to perform;
- all required identities and authorities are now frozen;
- no new Canonical or Domain contract is required.

If not fixed in Formal Implementation:

~~~text
M5-IU8 INDEPENDENT IMPLEMENTATION REVIEW = FAIL
~~~

## 12. Formal Implementation authorized scope

Authorized next implementation may modify the existing M5 execution runtime only as needed to wire:

~~~text
session lock admission/release
resource projection
canonical multi-lock acquisition
exact Tool operation-resource binding
baseline physical Tool path
IU6 reliability/retry physical Tool path
IU7 CONFIRMED_STOPPED resource cleanup
normal real-completion resource cleanup
fail-closed BUSY / UNKNOWN propagation
~~~

It must not implement:

~~~text
parallel Step scheduler
lock stealing
lease expiry
stale lock reclaim
durable lock persistence
fencing across process restart
checkpoint/crash recovery
Workflow resume
Execution aggregation
M6
Runtime priority recomputation
new Runtime cycle after PREEMPT
~~~

## 13. Verification baseline

Latest CA-03 exact-head verification:

~~~text
verified head =
653a2619cb9b444071dfdeb84cfe0740cc19d2a8

GitHub Actions run =
35804986233
~~~

Results:

~~~text
pytest = PASSED
745 passed, 1 existing warning

mypy = PASSED
Success: no issues found in 193 source files

ruff check = PASSED
All checks passed!

ruff format --check = PASSED
193 files already formatted
~~~

The warning is the existing Pydantic deprecation warning and is unrelated to IU8.

## 14. Final decision

~~~text
M5-IU8 IMPLEMENTATION READINESS RE-REVIEW = PASSED
M5-IU8 IMPLEMENTATION READINESS = READY

BLOCKERS = 0
NEW BLOCKER = NONE

FI-M5-IU8-REQ-001 = FORMAL IMPLEMENTATION REQUIRED

M5 = IN PROGRESS

NEXT REQUIRED =
M5-IU8 Formal Implementation
~~~

This READY decision authorizes implementation only. It does not close M5-IU8.
