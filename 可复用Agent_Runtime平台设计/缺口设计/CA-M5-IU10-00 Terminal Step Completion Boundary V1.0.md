# CA-M5-IU10-00 Terminal Step Completion Boundary V1.0

> Parent：M5-IU10 — Step 12 Execution Aggregation
>
> Base：M5-IU10 design/readiness @ d575e90975a10d2cbd97f491f22bfc2ba93971da

# 1. Amendment goal

关闭 IU10 聚合前的两个 Step lifecycle 前置缺口：

~~~text
B-M5-IU10-007
PENDING_STEP_TERMINALIZATION_AUTHORITY_MISSING

B-M5-IU10-008
PARTIAL_SUCCESS_STEP_FINALIZATION_AUTHORITY_MISSING
~~~

CA-00 不实现 ExecutionAggregator，不决定 plan_status，不生成 Canonical ExecutionResult。

# 2. Frozen boundary A — Scheduler-authorized PENDING -> SKIPPED

新增：

~~~text
TerminalStepCompletionCoordinator
TerminalStepCompletionDecision
TerminalStepCompletionStatus
StepScheduler
~~~

Coordinator 必须内部读取当前 Scheduler decision，不接受外部裸 decision 作为 mutation token。

允许 terminalize 的 Scheduler decision 仅有：

~~~text
SKIP
-> exact decision.step_id
-> PENDING -> SKIPPED

BLOCKED
+ exact reason:
  REQUIRED_PREVIOUS_STEP_NOT_SUCCESSFUL
+ exact decision.step_id
-> PENDING -> SKIPPED
~~~

第二种允许连续调用，一次只关闭一个当前 candidate：

~~~text
required Step 1 FAILED
Step 2 PENDING
Step 3 PENDING

call 1
-> Scheduler BLOCKED Step 2
-> Step 2 SKIPPED

call 2
-> Scheduler BLOCKED Step 3
-> Step 3 SKIPPED

call 3
-> Scheduler COMPLETE
~~~

禁止：

~~~text
WAITING -> mutation
UNKNOWN -> mutation
generic BLOCKED -> mutation
SEQUENTIAL_ORDER_VIOLATION -> mutation
EXECUTION_NOT_RUNNING -> mutation
MULTIPLE_RUNNING_STEPS -> mutation
READY -> mutation
~~~

Aggregator 后续不得自行把 PENDING 解释成 SKIPPED。

# 3. Lifecycle mutation remains owned by existing lifecycle service

新增：

~~~text
PendingStepSkipAuthorityKind
PendingStepSkipAuthority
ExecutionLifecycleManager.skip_pending_step(...)
ExecutionLifecycleService.skip_pending_step(...)
~~~

Coordinator 根据当前 Scheduler decision 生成 typed authority，生命周期层只接受该 authority，而不是裸 step_id/reason_codes。

authority 必须精确绑定：

~~~text
execution_id
plan_id
step_execution_id
step_id
kind
reason_codes
~~~

约束：

~~~text
execution must be RUNNING
target Step must be exact PENDING
target started_at must be None
no other Step may be RUNNING
reason_codes must be non-empty/non-blank
at must not precede latest execution observation
~~~

mutation：

~~~text
PENDING
-> SKIPPED

started_at remains None
finished_at = authoritative terminalization time
terminal_reason_codes = exact scheduler reason_codes
~~~

仍通过现有 ExecutionStateStore persistence boundary。

没有第二套 lifecycle store / mutation engine。

# 4. Frozen boundary B — PARTIAL_SUCCESS terminal mapping

当前事实链：

~~~text
M5SkillResult.PARTIAL_SUCCESS
-> StepAttemptStatus.PARTIAL_SUCCESS
~~~

IU6 reliability 可在 retry 不再授权后给出：

~~~text
StepReliabilityDisposition.FINALIZE
~~~

CA-00 冻结：

~~~text
StepAttemptStatus.PARTIAL_SUCCESS
+ StepReliabilityDisposition.FINALIZE
->
StepFinalizationDecision:
  disposition = FINALIZE
  terminal_status = StepExecutionStatus.SUCCESS
  degraded = true
~~~

reason：

~~~text
STEP_PARTIAL_SUCCESS_FINALIZATION_AUTHORIZED
~~~

解释：

~~~text
StepExecutionStatus.SUCCESS
= owner Step execution reached a completed lifecycle state

degraded = true
= owner result was PARTIAL_SUCCESS and must remain visible to IU10
~~~

这不表示：

~~~text
business success
validated success
all outputs succeeded
plan SUCCESS
~~~

CA-01 / CA-02 必须消费 degraded / rich owner evidence，不能只看 Step SUCCESS 就丢失 partial semantics。

# 5. StepFinalizationDecision amendment

新增：

~~~text
degraded: bool = False
~~~

约束：

~~~text
degraded = true
->
disposition must be FINALIZE
terminal_status must be SUCCESS
~~~

禁止：

~~~text
FAILED + degraded
TIMEOUT + degraded
UNKNOWN + degraded
RETRY + degraded
~~~

不新增：

~~~text
StepExecutionStatus.PARTIAL_SUCCESS
~~~

因此不破坏已冻结 Step lifecycle enum。

# 6. Terminal reason preservation

StepLifecycleSnapshot 新增：

~~~text
terminal_reason_codes: tuple[str, ...] = ()
~~~

用途：

~~~text
Scheduler SKIP reason
required-upstream-failure remainder reason
later terminal evidence correlation
~~~

该字段是 execution fact，不是 business interpretation。

同步进入：

~~~text
ExecutionRecord.step_results
ExecutionRecoverySnapshot exact typed-step comparison
control lifecycle step payload projection
~~~

# 7. Recovery backward compatibility

CA-00 对 IU9 recovery payload 的新增字段是 additive。

旧 persisted step payload：

~~~text
no terminal_reason_codes key
~~~

解释为：

~~~text
terminal_reason_codes = []
~~~

新 snapshot 显式写出：

~~~text
terminal_reason_codes
~~~

因此：

~~~text
legacy empty reason
==
new empty reason
~~~

不 bump：

~~~text
RECOVERY_SNAPSHOT_SCHEMA_VERSION
~~~

原因是该字段有严格无歧义的 backward-compatible empty default。

不同 non-empty reason 仍参与 exact comparison，不能被归一化掉。

# 8. Truth / authority boundaries

必须保持：

~~~text
Scheduler SKIP decision
!= Aggregator decision

SKIPPED
!= FAILED

PARTIAL_SUCCESS owner result
!= business success

Step lifecycle SUCCESS
with degraded=true
!= plan SUCCESS

generic BLOCKED
!= permission to skip

WAITING / UNKNOWN
!= terminalization authority
~~~

# 9. Files

~~~text
runtime/execution/foundation.py
runtime/execution/step_completion.py
runtime/execution/reliability_boundary.py
runtime/execution/reliability_defaults.py
runtime/execution/recovery.py
runtime/execution/control_lifecycle.py
runtime/execution/__init__.py

tests/test_m5_iu10_ca00_terminal_step_completion.py
tests/test_m5_iu6_formal_implementation.py
~~~

# 10. Behavioral gates

覆盖：

~~~text
1. dependency SKIP -> exact PENDING Step SKIPPED
2. scheduler reason persists in lifecycle + ExecutionRecord
3. condition NOT_SATISFIED -> SKIPPED without capability invoke
4. required failure closes later pending Steps one at a time
5. repeated closure eventually reaches Scheduler COMPLETE
6. WAITING cannot terminalize
7. UNKNOWN cannot terminalize
8. unrelated BLOCKED cannot terminalize
9. PARTIAL_SUCCESS -> FINALIZE / SUCCESS / degraded=true
10. degraded cannot pair with FAILED/non-final disposition
11. StepExecutionStatus enum remains unchanged
12. legacy recovery payload without terminal_reason_codes remains readable
13. forged step_execution_id skip authority is rejected
14. skip authority kind cannot impersonate required-failure provenance
15. PARTIAL_SUCCESS remains non-terminal while IU6 still requests RETRY
~~~

# 11. Findings

~~~text
F-M5-IU10-CA00-001
RECOVERY_STEP_PAYLOAD_ADDITIVE_FIELD_COULD_BREAK_LEGACY_SNAPSHOT_EXACTNESS
= CLOSED

F-M5-IU10-CA00-002
PENDING_SKIP_MUTATION_SURFACE_NOT_AUTHORITY_SEALED
= CLOSED
~~~

Fix 1：

~~~text
legacy missing terminal_reason_codes
-> normalize to []
before exact typed-step comparison
~~~

Fix 2：

~~~text
current Scheduler decision
-> TerminalStepCompletionCoordinator
-> exact PendingStepSkipAuthority
-> lifecycle mutation
~~~

并要求：

~~~text
SCHEDULER_SKIP
!= REQUIRED_PREVIOUS_STEP_NOT_SUCCESSFUL provenance
~~~

# 12. Blocker impact

Implementation intent：

~~~text
B-M5-IU10-007 = FIX_IMPLEMENTED_PENDING_REVIEW_AND_GATES
B-M5-IU10-008 = FIX_IMPLEMENTED_PENDING_REVIEW_AND_GATES
~~~

不影响：

~~~text
B-M5-IU10-001 = OPEN
B-M5-IU10-002 = OPEN
B-M5-IU10-003 = OPEN
B-M5-IU10-004 = OPEN
B-M5-IU10-005 = OPEN
B-M5-IU10-006 = OPEN
~~~

# 13. Non-goals

CA-00 不做：

~~~text
plan_status aggregation
ExecutionResult projection
crash-safe rich Skill/Workflow/Tool aggregation evidence
multi-Workflow schema amendment
cancellation projection
M6 validation
capability invocation
retry/resume
Registry lookup
~~~

# 14. Current status

~~~text
CA-M5-IU10-00 = CODE COMPLETE
CA-M5-IU10-00 INDEPENDENT REVIEW = PENDING
CA-M5-IU10-00 VERIFICATION = PENDING

M5-IU10 IMPLEMENTATION READINESS = NOT_READY
FORMAL IMPLEMENTATION = NOT AUTHORIZED
M5 = IN PROGRESS
~~~
