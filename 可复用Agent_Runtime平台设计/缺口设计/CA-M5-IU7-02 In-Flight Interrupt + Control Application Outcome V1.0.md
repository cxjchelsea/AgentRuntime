# CA-M5-IU7-02 In-Flight Interrupt + Control Application Outcome V1.0

> Baseline: CA-M5-IU7-01 = PASSED @ `6f9ec6ff2b5cd567d021d3f27369f714f3208c53`
> Scope: close the representability gaps behind B-M5-IU7-003 and B-M5-IU7-005.
> This amendment does not own lifecycle mutation; B-M5-IU7-004 remains for CA-M5-IU7-03.

## 1. Purpose

CA-01 established:

~~~text
resolved CANCEL/PREEMPT
-> auditable signal identity
-> live watch
-> latch barrier
~~~

CA-02 now freezes the missing middle authority:

~~~text
latched control
-> observe exact active operation hierarchy
-> leaf-first interrupt request
-> distinguish requested from confirmed
-> reconcile ALREADY_COMPLETED against real lifecycle
-> produce typed control-application outcome
-> authorize or deny entry to CA-03
~~~

The central invariant is:

~~~text
interrupt requested != interrupt confirmed
UNKNOWN interrupt != CANCELLED/PREEMPTED
~~~

## 2. In-flight operation identity

Added:

~~~text
InFlightOperationKind
- TOOL
- SKILL
- WORKFLOW

InFlightOperationHandle
- operation_handle_id
- execution_id
- step_execution_id
- parent_handle_id?
- kind
- capability_id
- capability_version
- started_at
- tool_call_id?
- workflow_instance_id?
~~~

Rules:

~~~text
owner Skill/Workflow = root
nested Tool = child
Tool requires explicit parent_handle_id
all handles are exact execution + step bound
operation_handle_id cannot be rebound
started_at uses timezone-aware Core-local time
~~~

Direct Tool fast-path remains outside the current executable owner model and is not invented by CA-02.

## 3. Live in-flight registry

Added:

~~~text
InFlightOperationRegistry
- register(handle)
- complete(operation_handle_id, completed_at)
- active_chain(execution_id, step_execution_id)

InMemoryInFlightOperationRegistry
~~~

The in-memory implementation is mechanism-only:

~~~text
live runtime authority = yes
durable crash recovery = no
persisted in-flight graph = no
~~~

Durability remains IU9.

Registry is not a Registry/capability resolver and cannot substitute Skill/Workflow/Tool versions.

## 4. Hierarchical graph rule

The coordinator validates one exact chain.

Allowed first-version structure:

~~~text
Skill / Workflow owner
        ↓
optional nested Tool chain
~~~

Required:

~~~text
exactly one root
exactly one active leaf
no missing parent
no duplicate handle
no cycle
all non-root active nodes are Tool
~~~

If multiple active leaves exist:

~~~text
AMBIGUOUS_INFLIGHT_GRAPH
-> fail closed
-> no interrupt request is sent
~~~

Parallel/multi-leaf control policy remains IU8.

## 5. Interrupt authority

Added:

~~~text
ExecutionInterruptController

InterruptOutcomeStatus
- CONFIRMED_STOPPED
- ALREADY_COMPLETED
- NOT_CANCELLABLE
- UNKNOWN

InterruptOutcome
~~~

The controller returns an observation stronger than a request.

It must not map:

~~~text
Python task.cancel()
coroutine cancellation request
socket close request
provider cancel request
~~~

directly to:

~~~text
CONFIRMED_STOPPED
~~~

unless the adapter can establish that the actual business operation is stopped.

## 6. Leaf-first interrupt coordinator

Added:

~~~text
InFlightInterruptCoordinator
HierarchicalInterruptStatus
HierarchicalInterruptSummary
~~~

Interrupt order is structural, not priority-based:

~~~text
leaf Tool
-> parent Tool if any
-> root Skill / Workflow owner
~~~

The coordinator never compares CANCEL vs PREEMPT priority and never recomputes M2 Policy.

Wrong-target terminal signals fail closed before any interrupt request.

## 7. Control application outcome

Added:

~~~text
ExecutionControlDisposition
- NO_CONTROL
- WAITING_IN_FLIGHT
- READY_TO_TERMINALIZE
- ALREADY_TERMINAL
- CONFLICT
- UNKNOWN

ExecutionControlApplication
- signal
- disposition
- reason_codes
- running_step_id?
- interrupt_summary?
- nonterminal_step_ids_at_latch
- affected_step_ids
- preserve_running_step_result
- handoff_required
~~~

Formal distinction:

~~~text
signal accepted
!= interrupt confirmed
!= lifecycle terminalized
~~~

CA-02 produces authority for CA-03; it does not mutate lifecycle.

## 8. affected_step_ids rule

At latch time CA-02 records all nonterminal Step ids.

A Step becomes affected only when control can be shown to have changed unfinished work.

Rules:

~~~text
PENDING Step behind accepted latch
-> affected because it is prevented from starting

RUNNING Step
-> affected only when owner interrupt = CONFIRMED_STOPPED

UNKNOWN / NOT_CANCELLABLE RUNNING Step
-> running Step is not claimed affected

ALREADY_COMPLETED owner
-> running Step is not claimed affected
-> real lifecycle completion must be preserved
~~~

Therefore:

~~~text
READY_TO_TERMINALIZE
requires affected_step_ids != ()
~~~

## 9. ALREADY_COMPLETED reconciliation

If the interrupt controller says:

~~~text
ALREADY_COMPLETED
~~~

but the authoritative Step lifecycle still says:

~~~text
RUNNING
~~~

CA-02 returns:

~~~text
WAITING_IN_FLIGHT
OWNER_COMPLETED_AWAITING_LIFECYCLE_COMMIT
~~~

It does not guess SUCCESS/FAILED/TIMEOUT/etc.

If refreshed lifecycle proves the running Step has already reached a real terminal status:

~~~text
preserve_running_step_result = true
~~~

and the real terminal status/output remains unchanged.

If no PENDING Step remains:

~~~text
ALREADY_TERMINAL
affected_step_ids = ()
no retrospective CANCELLED/PREEMPTED rewrite
~~~

If PENDING Steps remain:

~~~text
READY_TO_TERMINALIZE
affected_step_ids = only those PENDING Steps
~~~

The completed running Step is excluded from affected_step_ids.

## 10. NOT_CANCELLABLE / UNKNOWN

~~~text
NOT_CANCELLABLE
-> WAITING_IN_FLIGHT
-> latch barrier remains
-> do not claim running Step stopped

UNKNOWN
-> UNKNOWN
-> fail closed
-> do not claim running Step stopped
~~~

Both preserve existing running-result/side-effect evidence.

## 11. Side-effect preservation

CA-02 never mutates PreparedExecution.

Already observed outputs and IU6 Tool/idempotency evidence remain authoritative.

Example:

~~~text
Tool side effect SUCCESS
-> control arrives
-> owner ALREADY_COMPLETED
-> lifecycle commits SUCCESS
-> CA-02 preserves SUCCESS/output
-> only remaining PENDING work may be affected
~~~

Cancellation is not rollback.

## 12. PREEMPT handoff

~~~text
PREEMPT signal
-> handoff_required = true
~~~

This is independent of lifecycle rewrite.

Therefore even a late PREEMPT may yield:

~~~text
ALREADY_TERMINAL
affected_step_ids = ()
handoff_required = true
~~~

CA-02 does not start a new Runtime cycle.

## 13. Explicit exclusions

CA-02 does not implement:

~~~text
ExecutionLifecycleService.finish_step control mutation
PENDING -> CANCELLED/PREEMPTED mutation
ExecutionPlanStatus CANCELLED/PREEMPTED commit
ResourceLock policy
lock stealing/recovery
durable in-flight registry
Checkpoint/Crash Recovery
Workflow resume
Execution aggregation
Canonical ExecutionResult completion
M6
Runtime new-cycle start
~~~

Those remain:

~~~text
CA-M5-IU7-03 -> lifecycle terminalization
IU8 -> Resource Lock / concurrency
IU9 -> persistence / checkpoint / recovery
IU10 -> aggregation
M6 -> truth validation
Runtime -> PREEMPT next-cycle orchestration
~~~

## 14. Blocker mapping

CA-02 is designed to close:

~~~text
B-M5-IU7-003
INFLIGHT_OPERATION_INTERRUPT_AUTHORITY_MISSING

B-M5-IU7-005
CONTROL_APPLICATION_UNCERTAINTY_OUTCOME_MISSING
~~~

CA-02 does not close:

~~~text
B-M5-IU7-004
CONTROL_LIFECYCLE_TERMINALIZATION_INCOMPLETE
~~~

## 15. Verification gates

Required:

~~~text
python -m pytest tests -q
python -m mypy runtime tests
python -m ruff check runtime tests
python -m ruff format --check runtime tests
~~~

Do not mark CA-M5-IU7-02 PASSED until:

~~~text
Targeted Amendment Review = PASSED
four local gates = GREEN
no new blocker
~~~

## 16. Current status

~~~text
CA-M5-IU7-02 = CODE COMPLETE
CA-M5-IU7-02 TARGETED AMENDMENT REVIEW = PENDING
CA-M5-IU7-02 VERIFICATION = PENDING

B-M5-IU7-003 = FIX_IMPLEMENTED_PENDING_REVIEW_AND_GATES
B-M5-IU7-005 = FIX_IMPLEMENTED_PENDING_REVIEW_AND_GATES

B-M5-IU7-004 = OPEN

M5-IU7 IMPLEMENTATION READINESS = NOT_READY
M5 = IN PROGRESS
~~~
