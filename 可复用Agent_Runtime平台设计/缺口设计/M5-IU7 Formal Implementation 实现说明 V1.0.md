# M5-IU7 Formal Implementation 实现说明 V1.0

> Scope：M5 Execution Framework Step 9 — Cancellation / Preemption。
> Baseline：CA-M5-IU7-01/02/03 = PASSED；B-M5-IU7-001～005 = CLOSED；Implementation Readiness Re-Review = PASSED；Implementation Readiness = READY。

## 1. 本轮正式实现

~~~text
Live Control Runtime
- InMemoryExecutionControlLatch
- ExecutionControlCoordinator
- watcher -> latch -> interrupt -> application -> lifecycle wiring
- WAITING_IN_FLIGHT lifecycle reconciliation
- PREEMPT handoff_required projection only

Live In-Flight Observation
- InFlightOperationIdentifierFactory
- Skill / Workflow owner live handle registration
- nested physical Tool live handle registration
- exact parent-child binding
- Tool leaf completion before owner completion
- live registry cleanup uncertainty -> fail closed
~~~

## 2. 正式控制链路

~~~text
Runtime/M2 resolved CANCEL / PREEMPT
        ↓
ExecutionControlWatcher
        ↓
ObservedExecutionControl
        ↓
ExecutionControlLatch
        ↓
LatchedExecutionControl
        ↓
observe exact RUNNING Step / active operation chain
        ↓
InFlightInterruptCoordinator
        ↓
ExecutionControlApplicationEvaluator
        ↓
WAIT / UNKNOWN / CONFLICT
or
READY_TO_TERMINALIZE / ALREADY_TERMINAL
        ↓
ExecutionControlLifecycleService
        ↓
CANCELLED / PREEMPTED when authority is sufficient
~~~

M5-IU7 does not compare control priority and does not rerun M2.

## 3. In-flight owner / Tool wiring

When formal IU7 tracking is configured:

~~~text
StepCapabilityExecutor
  register Skill/Workflow owner
        ↓
CoreApprovedToolInvoker
  register nested physical Tool before Tool.invoke
        ↓
Tool finishes
  remove Tool leaf
        ↓
Skill/Workflow finishes
  remove owner root
~~~

During a Tool await, the registry can therefore expose:

~~~text
owner Skill/Workflow
  └── Tool leaf
~~~

and InFlightInterruptCoordinator keeps the frozen order:

~~~text
Tool leaf first
→ owner second
~~~

No parallel-leaf policy is introduced; ambiguous graphs remain fail closed and belong to IU8 concurrency governance.

## 4. Runtime coordinator rules

ExecutionControlCoordinator composes only frozen authorities.

It guarantees:

~~~text
wrong target -> UNKNOWN / no latch mutation
latch UNKNOWN -> no lifecycle mutation
latch CONFLICT -> no lifecycle mutation
WAITING_IN_FLIGHT -> no lifecycle mutation
READY_TO_TERMINALIZE -> control lifecycle service
ALREADY_TERMINAL -> verified no-op lifecycle path
~~~

Watcher failure raises a control-runtime error before lifecycle mutation.

## 5. ALREADY_COMPLETED reconciliation

If interrupt authority reports:

~~~text
ALREADY_COMPLETED
~~~

while the Step lifecycle is still RUNNING:

~~~text
WAITING_IN_FLIGHT
~~~

The coordinator exposes a separate reconcile path that consumes an authoritative later PreparedExecution.

Only after the real completion is present can pending work be control-terminalized.

Therefore:

~~~text
interrupt says completed
!=
Core guesses Step completion
~~~

## 6. Side-effect / result preservation

Formal wiring does not erase existing:

~~~text
Tool journal
idempotency state
Step output
Tool call ids
retry evidence
real terminal Step result
~~~

If live registry cleanup cannot be confirmed after a Tool returns, the execution observation is downgraded to UNKNOWN rather than silently claiming a clean boundary. A valid raw Tool result is retained when its identity is trustworthy.

Cancellation/preemption remains:

~~~text
control of unfinished work
!= rollback
~~~

## 7. PREEMPT boundary

PREEMPT can produce:

~~~text
execution = PREEMPTED
handoff_required = true
~~~

IU7 does not start the next Runtime cycle.

## 8. Compatibility

When no in-flight registry/factory is configured, existing IU4/IU6 capability execution behavior remains unchanged.

Formal IU7 tracking is opt-in through injected Core authorities and does not alter capability discovery, approval, Registry resolution, retry policy, or idempotency policy.

## 9. Explicit non-goals

~~~text
Resource Lock / concurrency policy             -> M5-IU8
durable control latch                          -> M5-IU9
persisted in-flight registry                   -> M5-IU9
crash recovery / checkpoint / Workflow resume  -> M5-IU9
ExecutionResult aggregation                    -> M5-IU10
M6 validation                                  -> after M5 closure
new Runtime cycle after PREEMPT                -> Runtime orchestration
~~~

## 10. Formal behavior tests

新增：

~~~text
tests/test_m5_iu7_formal_implementation.py
~~~

覆盖：

~~~text
1. live latch exact replay / conflict
2. CANCEL owner interrupt -> Step/Execution terminalization
3. PREEMPT pending-only -> PREEMPTED + handoff_required
4. wrong target -> fail closed before lifecycle mutation
5. ALREADY_COMPLETED -> WAIT then real lifecycle reconciliation
6. watcher failure -> no lifecycle mutation
7. actual Skill owner + nested Tool live chain is visible
8. nested interrupt order = Tool leaf -> Skill owner
9. completed owner/Tool handles are removed after normal completion
~~~

## 11. Current status

~~~text
M5-IU7 IMPLEMENTATION READINESS RE-REVIEW = PASSED
M5-IU7 IMPLEMENTATION READINESS = READY

M5-IU7 FORMAL IMPLEMENTATION = CODE COMPLETE
M5-IU7 INDEPENDENT IMPLEMENTATION REVIEW = PENDING
M5-IU7 VERIFICATION = PENDING

M5 = IN PROGRESS
~~~
