# CA-M5-IU9-02 Durable Reliability + Control/InFlight Evidence V1.0

> Base：CA-M5-IU9-01 PASSED @ `b4e14e72bf84e9d8c6bc6b5f1084d3338eb40f0f`
> Scope：关闭 B-M5-IU9-002 与 B-M5-IU9-003。

## 1. 目标

CA-02 只解决两类 crash truth：

~~~text
IU6 reliability / replay evidence survives restart
IU7 terminal control + in-flight evidence survives restart
~~~

不进入 ResourceLock reclaim/fencing、Workflow resume、RecoveryDisposition orchestration、IU10 或 M6。

## 2. Durable reliability evidence

新增：

~~~text
StepAttemptCursorRecord
ToolOccurrenceCursorRecord
DurableReliabilityEvidenceStore
DurableStepAttemptSequenceAuthority
DurableToolOperationOccurrenceAuthority
DurableToolJournalEvidence
ToolJournalWriteStatus / Decision
~~~

冻结规则：

~~~text
Step attempt 1 必须先建立 durable baseline
无 durable baseline -> 不能直接 claim retry
next attempt 只能 exact current + 1
stale recovery epoch -> 不能推进 attempt

Tool occurrence exact key =
execution_id + step_execution_id + step_attempt_number
+ tool_id + tool_version + operation_fingerprint

Tool journal key =
execution_id + step_execution_id + step_attempt_number

journal append 使用 expected_current_length
exact last-entry replay -> ALREADY_CURRENT
stale length / tool_call_id rebind -> CONFLICT
~~~

Tool journal 直接复用现有 `ToolInvocationJournalEntry`，不创建第二套 Tool correlation identity。

## 3. Idempotency boundary

CA-02 不宣称现有 `InMemoryIdempotencyCoordinator` crash-durable。

已有以下抽象继续作为 authoritative contract：

~~~text
IdempotencyStore
IdempotencyCompletionAuthority
IdempotencyResultResolver
~~~

生产 Formal Implementation 必须提供 durable adapter，并继续遵守：

~~~text
COMPLETED -> recover result, never blind invoke
FAILED -> only exact provenance + IU6 replay authority
RESERVED -> unresolved / possibly in flight
UNKNOWN -> fail closed
~~~

B-M5-IU9-002 的原始缺口明确是 Step attempt / Tool occurrence / local Tool journal 的 live-only 状态；CA-02 不把 reference in-memory idempotency store 升格为生产实现。

## 4. Durable terminal control

新增：

~~~text
DurableTerminalControlStore
DurableExecutionControlLatch
DurableControlReadStatus
DurableControlReadDecision
~~~

保持 IU7 原语义：

~~~text
first exact CANCEL/PREEMPT -> LATCHED
exact immutable replay -> ALREADY_LATCHED
different terminal signal -> CONFLICT
stale recovery epoch -> UNKNOWN / fail closed
~~~

Recovery read 使用：

~~~text
NONE
LATCHED
UNKNOWN
~~~

`UNKNOWN` 不允许降级成 `None / no control`。IU7 optional `get_latched()` adapter 在 durable read UNKNOWN 时抛出错误，避免恢复流程误认为没有 terminal barrier。

## 5. Durable in-flight evidence

新增：

~~~text
InFlightEvidenceState
DurableInFlightOperationObservation
DurableInFlightEvidenceStore
DurableInFlightOperationRegistry
InFlightRecoveryTransitionStatus
InFlightRecoveryTransitionDecision
~~~

状态：

~~~text
ACTIVE_AT_CHECKPOINT
COMPLETED
CONFIRMED_STOPPED
ORPHANED_UNCONFIRMED
UNKNOWN
~~~

重启规则：

~~~text
ACTIVE_AT_CHECKPOINT
-> ORPHANED_UNCONFIRMED

process lost
!= operation stopped
!= operation completed
~~~

已持久化 `COMPLETED` 不会被降级为 orphaned。

CA-02 不自动生成 `CONFIRMED_STOPPED`；该强事实只能来自后续 external operation reconciliation authority。

## 6. In-flight live view 与 recovery truth

`DurableInFlightOperationRegistry.active_chain()` 仅暴露当前 `ACTIVE_AT_CHECKPOINT`，用于兼容 IU7 live registry。

恢复流程不得用 `active_chain()==()` 推断“无 unresolved operation”。CA-M5-IU9-04 必须直接读取 durable observation / recovery transition decision。

## 7. Recovery epoch fencing

所有 CA-02 reference mutation 都要求 current recovery claim。

生产 durable adapter 必须保证：

~~~text
recovery fence validation
+ evidence mutation
在同一个 durable transaction / CAS boundary 内成立
~~~

不能只在调用前单独检查一次 epoch。

## 8. Targeted Review findings

### F-M5-IU9-CA02-001 DURABLE_CONTROL_READ_UNKNOWN_COLLAPSED_TO_NONE

初版 durable control read 返回 `LatchedExecutionControl | None`，无法区分：

~~~text
确实没有 latch
vs
durable store read unknown / failed
~~~

修复为 typed `DurableControlReadDecision`：

~~~text
NONE / LATCHED / UNKNOWN
~~~

且 adapter 遇到 UNKNOWN fail closed。

~~~text
F-M5-IU9-CA02-001 = CLOSED
~~~

### F-M5-IU9-CA02-002 ORPHAN_TRANSITION_FENCE_UNCERTAINTY_COLLAPSED

初版 stale/non-current epoch 执行 orphan transition 时返回空 tuple，可能被上层误读为“没有孤儿 operation”。

修复为：

~~~text
TRANSITIONED
NO_ACTIVE
CONFLICT
UNKNOWN
~~~

stale recovery epoch 明确返回 `CONFLICT`，不再伪装为空成功。

~~~text
F-M5-IU9-CA02-002 = CLOSED
~~~

### F-M5-IU9-CA02-003 STEP_ATTEMPT_BASELINE_NOT_MANDATORY

初版 retry claim 在 durable cursor 缺失时可隐式把 current 当作 attempt 1。

这会允许未持久化 attempt-1 identity 的执行直接进入 retry。

修复：

~~~text
Step owner start前先 ensure durable attempt-1 baseline

baseline missing
-> CONFLICT
-> STEP_ATTEMPT_DURABLE_BASELINE_MISSING
~~~

~~~text
F-M5-IU9-CA02-003 = CLOSED
~~~

## 9. Verification scenarios

已覆盖：

~~~text
Step attempt cursor survives adapter recreation
retry number continues 1 -> 2 -> 3
missing attempt-1 baseline blocks retry
stale epoch cannot advance Step retry

Tool occurrence survives restart
exact step attempt / tool version / fingerprint scoping
stale epoch cannot advance occurrence

Tool journal append monotonic
exact append replay idempotent
journal survives adapter recreation
stale length / stale epoch rejected

terminal control latch survives restart
exact signal replay idempotent
different terminal signal conflict
stale worker cannot add terminal latch
UNKNOWN durable read never becomes no-control

active owner / Tool evidence survives adapter recreation
active-at-crash -> ORPHANED_UNCONFIRMED
completed evidence stays COMPLETED
stale recovery epoch orphan transition -> CONFLICT
NO_ACTIVE is explicit
stale worker cannot mark completion
operation handle cannot be rebound
~~~

## 10. Blocker mapping

~~~text
B-M5-IU9-002 RELIABILITY_REPLAY_EVIDENCE_NOT_CRASH_DURABLE
= CLOSED

B-M5-IU9-003 CONTROL_AND_INFLIGHT_STATE_NOT_CRASH_DURABLE
= CLOSED
~~~

仍开放：

~~~text
B-M5-IU9-005 RESOURCE_LOCK_CRASH_RECLAIM_AND_FENCING_MISSING
B-M5-IU9-006 WORKFLOW_CHECKPOINT_RESUME_AUTHORITY_INCOMPLETE
B-M5-IU9-007 RECOVERY_DECISION_ORCHESTRATOR_MISSING
~~~

## 11. Closure candidate verification

~~~text
exact head =
bcbe65ef3acb4fe696407a902e38e189399d2c61

GitHub Actions run =
35815369409

pytest = PASSED
783 passed, 1 existing warning

mypy = PASSED
Success: no issues found in 199 source files

ruff check = PASSED
All checks passed!

ruff format --check = PASSED
199 files already formatted
~~~

warning 为已有 Pydantic deprecation，与 CA-02 无关。

## 12. Current status

~~~text
CA-M5-IU9-02 = CODE COMPLETE
CA-M5-IU9-02 TARGETED AMENDMENT REVIEW = PASSED
CA-M5-IU9-02 VERIFICATION = PASSED
CA-M5-IU9-02 = PASSED

F-M5-IU9-CA02-001 = CLOSED
F-M5-IU9-CA02-002 = CLOSED
F-M5-IU9-CA02-003 = CLOSED

B-M5-IU9-001 = CLOSED
B-M5-IU9-002 = CLOSED
B-M5-IU9-003 = CLOSED
B-M5-IU9-004 = CLOSED

B-M5-IU9-005 = OPEN
B-M5-IU9-006 = OPEN
B-M5-IU9-007 = OPEN

M5-IU9 IMPLEMENTATION READINESS = NOT_READY
NEW BLOCKER = NONE

M5 = IN PROGRESS

NEXT REQUIRED =
CA-M5-IU9-03
Durable Resource Lock Recovery + Fencing
~~~
