# CA-M5-IU7-03 Control Lifecycle Terminalization Boundary V1.0

> Baseline: CA-M5-IU7-02 = PASSED @ 92db46ab6028aeeaf3fda24d6923c7ccb293cd28
> Scope: close B-M5-IU7-004 CONTROL_LIFECYCLE_TERMINALIZATION_INCOMPLETE.
> This amendment owns control-specific lifecycle mutation only.

## 1. Purpose

CA-01 established exact terminal control identity and latch authority.

CA-02 established exact in-flight observation, interrupt authority, uncertainty handling, and typed ExecutionControlApplication.

CA-03 closes the remaining lifecycle gap:

~~~text
LatchedExecutionControl
+
ExecutionControlApplication = READY_TO_TERMINALIZE
+
authoritative PreparedExecution
        ↓
ExecutionControlLifecycleTransitioner
        ↓
affected unfinished Steps -> CANCELLED / PREEMPTED
        ↓
Execution -> CANCELLED / PREEMPTED
        ↓
persist exact lifecycle observation
~~~

The central invariant remains:

~~~text
control signal
!= interrupt confirmation
!= lifecycle mutation
~~~

CA-03 may mutate lifecycle only after CA-01/02 authority is already present.

## 2. Why finish_step is not widened

Existing ExecutionLifecycleManager.finish_step is intentionally:

~~~text
RUNNING -> terminal
~~~

CANCEL/PREEMPT may also stop Steps that are still PENDING.

A PENDING Step never started. Routing it through finish_step would falsely represent it as normal execution completion.

Therefore CA-03 adds a separate control-specific boundary and leaves the ordinary lifecycle path unchanged.

## 3. New authority

Added:

~~~text
ExecutionControlLifecycleError

ExecutionControlLifecycleTransitioner
- terminalize(PreparedExecution, LatchedExecutionControl, ExecutionControlApplication, at)
  -> PreparedExecution

ExecutionControlLifecycleService
- terminalize(...)
  -> PreparedExecution
  -> persist ExecutionRecord when mutation occurs
~~~

The transitioner is pure. The service is the persistence boundary.

## 4. Exact authority requirements

Lifecycle mutation requires all of:

~~~text
1. exact latched CANCEL/PREEMPT
2. application.signal == latched_control.signal
3. signal.target_execution_id == PreparedExecution.execution_id
4. application.disposition == READY_TO_TERMINALIZE
5. affected_step_ids != ()
6. terminalization time is Core-local timezone-aware
7. terminalization time does not precede latch/latest lifecycle evidence
~~~

Any mismatch fails closed.

## 5. CANCEL/PREEMPT mapping

~~~text
CANCEL:
  affected RUNNING/PENDING Step -> CANCELLED
  Execution -> ExecutionPlanStatus.CANCELLED

PREEMPT:
  affected RUNNING/PENDING Step -> PREEMPTED
  Execution -> ExecutionPlanStatus.PREEMPTED
~~~

CA-03 does not compare CANCEL vs PREEMPT priority.

## 6. Already-terminal Step preservation

A Step already in SUCCESS/FAILED/SKIPPED/CANCELLED/TIMEOUT/PREEMPTED is immutable to a new control terminalization.

CA-03 preserves the original Step snapshot, including status, output, error, tool_call_ids, retry_count, started_at, and finished_at.

If a stale application still lists an already-terminal Step as affected, CA-03 fails closed. This prevents retrospective rewriting of real execution truth.

## 7. RUNNING Step rule

A RUNNING Step may be control-terminalized only if:

~~~text
step_id == application.running_step_id
preserve_running_step_result == false
application.interrupt_summary.status == ORDERED
interrupt_summary.step_execution_id matches the Step
owner interrupt outcome == CONFIRMED_STOPPED
owner outcome identity matches the root owner handle
~~~

Therefore interrupt requested, ALREADY_COMPLETED, NOT_CANCELLABLE, and UNKNOWN are not sufficient.

## 8. PENDING Step rule

A PENDING Step listed in affected_step_ids is mapped directly to the control terminal state.

It keeps started_at = None and receives finished_at = terminalization time. This records that the Step was terminalized by execution control before it started rather than falsely claiming it executed.

## 9. Side-effect / result preservation

Control terminalization never clears already observed fields. For a confirmed-stopped RUNNING Step, CA-03 changes only lifecycle fields required for control terminalization.

Existing output, error, tool_call_ids, retry_count, and started_at remain intact. Cancellation/preemption is not rollback.

## 10. Full-execution closure rule

After applying every affected_step_id exactly once, all Steps must be terminal.

If any PENDING/RUNNING Step remains outside the authorized affected set, CA-03 fails closed.

Only then may the ExecutionRecord become CANCELLED or PREEMPTED.

## 11. Late control

If CA-02 produced ALREADY_TERMINAL with affected_step_ids = (), CA-03 returns the current PreparedExecution unchanged.

It does not write CANCELLED/PREEMPTED onto already completed work. The original execution result remains for IU10 aggregation.

## 12. Exact live replay

Within the same live control authority, repeating the same already-applied transition is an idempotent no-op when the Execution already has the matching control status, all affected Steps already have the matching control status, and all Steps are terminal.

This is live-runtime idempotency only. Durable replay/recovery across process failure remains IU9.

## 13. Persistence boundary

ExecutionControlLifecycleService persists the resulting ExecutionRecord only when the pure transition actually mutated lifecycle.

Legitimate late-control and exact-live-replay no-ops do not create a new lifecycle observation.

## 14. Explicit exclusions

CA-03 does not implement:

~~~text
control watching/latching
in-flight registry
interrupt adapters
ResourceLock acquire/release/steal
durable control latch
crash recovery
checkpoint/resume
execution aggregation policy
canonical cancellation evidence projection
M6 validation
Runtime PREEMPT handoff execution/new cycle
~~~

Those remain IU8 / IU9 / IU10 / M6 / Runtime responsibilities.

## 15. Blocker mapping

CA-03 is designed to close:

~~~text
B-M5-IU7-004
CONTROL_LIFECYCLE_TERMINALIZATION_INCOMPLETE
~~~

After review and four green gates, B-M5-IU7-004 may be marked CLOSED.

At that point all original IU7 readiness blockers are closed and an IU7 Implementation Readiness Re-Review becomes the next required governance step.

## 16. Verification scenarios

~~~text
1. affected RUNNING + PENDING + CANCEL -> both CANCELLED; execution CANCELLED
2. affected RUNNING + PENDING + PREEMPT -> both PREEMPTED; execution PREEMPTED
3. pre-existing terminal Step remains unchanged
4. PENDING control terminalization keeps started_at=None
5. RUNNING requires owner CONFIRMED_STOPPED
6. WAITING/UNKNOWN/CONFLICT cannot mutate lifecycle
7. exact latched signal must match application signal
8. stale application cannot rewrite real terminal Step
9. unaffected nonterminal Step prevents execution terminalization
10. late ALREADY_TERMINAL control is no-op
11. terminalization time cannot precede latch/evidence
12. exact live replay is idempotent
13. terminal execution cannot be rewritten by another control
14. service persists real mutation but not late-control no-op
~~~

## 17. Current status

~~~text
CA-M5-IU7-03 = CODE COMPLETE
CA-M5-IU7-03 TARGETED AMENDMENT REVIEW = PENDING
CA-M5-IU7-03 VERIFICATION = PENDING

B-M5-IU7-004 = FIX_IMPLEMENTED_PENDING_REVIEW_AND_GATES

M5-IU7 IMPLEMENTATION READINESS = NOT_READY
M5 = IN PROGRESS
~~~