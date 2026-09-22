# CA-M5-IU6-02 Tool Attempt + Idempotency + Finalization Boundary V1.0

> Purpose：关闭 B-M5-IU6-002 / 003 / 004 / 005 / 006。
> Baseline：CA-M5-IU6-01 = PASSED。
> 本 Amendment 只冻结多 physical Tool attempt、幂等 provenance/recovery/lifecycle、跨 Step replay correlation、Step attempt sequence、Step reliability/finalization authority；不实现真正 Retry loop、finish_step 调用、Workflow resume、Aggregation 或 M6。

## 1. Blocker mapping

~~~text
B-M5-IU6-002 IU4_TOOL_INVOCATION_IS_SINGLE_ATTEMPT_ONLY
→ logical Tool call / physical Tool attempt + attempt journal

B-M5-IU6-003 IDEMPOTENCY_PROVENANCE_AND_RESULT_RECOVERY_INCOMPLETE
→ IdempotencyRecord provenance + FAILED + reopen + completed recovery + preflight

B-M5-IU6-004 STEP_ATTEMPT_SEQUENCE_AUTHORITY_MISSING
→ StepAttemptSequenceAuthority

B-M5-IU6-005 STEP_FINALIZATION_AUTHORITY_NOT_FROZEN
→ StepReliabilityDecision + StepFinalizationDecision/Evaluator

B-M5-IU6-006 STEP_REPLAY_TOOL_OPERATION_CORRELATION_MISSING
→ operation fingerprint + occurrence authority + ToolOperationCorrelator
~~~

## 2. Logical Tool call / physical attempt

新增：

~~~text
ToolAttemptObservation
PhysicalToolAttemptExecutor
ToolInvocationJournalEntry.attempts[]
~~~

同一个 logical Tool call：

~~~text
logical_tool_call_id = stable
tool_id/version = stable
operation_key = stable
operation_fingerprint = stable
idempotency_key = stable
physical_attempt = 1,2,3...
~~~

CoreApprovedToolInvoker.execute_physical_attempt 只执行一个 physical attempt，不决定是否 retry。

Domain-facing invoke 仍保持 IU4 单 attempt baseline，不自动重试。

## 3. Tool journal truth

ToolInvocationJournalEntry 现在表达一个 logical invocation，并包含所有 physical attempts。

冻结：

~~~text
attempts 必须从 1 连续递增
每 attempt logical_tool_call_id/tool/version 必须一致
operation_key/fingerprint/idempotency_key 必须稳定
journal.result = 最后一个 physical attempt 的 final result
journal.raw_result = 最后一个 physical attempt 的 raw result
~~~

Domain tool_results 仍只对应 logical Tool call 的 final result；physical attempts 不升级成多个业务 Tool call。

## 4. Idempotency provenance

IdempotencyRecord 新增/冻结：

~~~text
step_execution_id
tool_id
tool_version
operation_key
operation_fingerprint
status
tool_call_id?
result_reference?
~~~

COMPLETED 必须同时具备 tool_call_id + result_reference。

非 COMPLETED 不得携带 result_reference。

## 5. Idempotency lifecycle

IdempotencyStatus：

~~~text
RESERVED
COMPLETED
FAILED
UNKNOWN
~~~

IdempotencyStore：

~~~text
get
reserve
mark_completed
mark_failed
reopen_failed
mark_unknown
~~~

mark_failed 只表示“可信确认未产生 side effect 的最终失败”。

reopen_failed 必须原子地对 exact matching provenance 执行 FAILED → RESERVED；provenance 不一致或不是 FAILED 时返回 false。

UNKNOWN 永远不能被 reopen 成新调用。

## 6. Completed result recovery

唯一恢复 authority：

~~~text
IdempotencyResultResolver.resolve_completed(record)
~~~

规则：

~~~text
COMPLETED → 不重新 invoke Tool，恢复可信 M5ToolResult
RESERVED → 视为 in-flight/concurrent，不重新 invoke
UNKNOWN → fail closed，不重新 invoke
FAILED → 只有通过 reopen_failed 后才允许后续 attempt
~~~

真正恢复前仍必须经过当前 Permission / deadline admission；idempotency cache 不能成为权限旁路。

## 7. Idempotency preflight

新增：

~~~text
IdempotencyPreflightStatus
- RESERVE_NEW
- RECOVER_COMPLETED
- WAIT_IN_FLIGHT
- REOPEN_FAILED
- FAIL_UNKNOWN
- REJECT_PROVENANCE

IdempotencyPreflightDecision
IdempotencyPreflightEvaluator
~~~

Preflight 只允许在 Input Validation + current Permission + deadline admission 之后使用。

UNKNOWN 不得变成 RESERVE_NEW / REOPEN_FAILED。

provenance mismatch 必须 REJECT_PROVENANCE。

## 8. Cross-Step Tool operation correlation

ToolOperationFingerprintFactory 负责 stable normalized fingerprint。

由于同一 Skill attempt 内可能合法调用两次完全相同的 Tool+payload，不能只按 fingerprint 去重。

新增 Core-owned：

~~~text
ToolOperationOccurrenceAuthority
ToolOperationOccurrenceDecision
~~~

对同一 tool/version/fingerprint，在单次 Step attempt 内原子分配 occurrence 1,2,3...。

ToolOperationCorrelator 使用：

~~~text
step_execution_id
step_attempt_number
tool_id/version
operation_fingerprint
operation_occurrence
prior_attempt_journal
~~~

将本 attempt 的 occurrence N 对齐到 prior attempt 的 occurrence N。

序列漂移、歧义、无法证明一致时必须 UNKNOWN，不能猜测 correlation。

因此：

~~~text
两个相同 Tool+payload 调用
→ occurrence 1 / occurrence 2
→ 两个不同 operation_key

下一次 Step replay
→ occurrence 1 对齐旧 occurrence 1
→ occurrence 2 对齐旧 occurrence 2
~~~

## 9. Idempotency key

IdempotencyKeyFactory 输入：

~~~text
execution_id
step_execution_id
ToolOperationCorrelationKey
tool_id/version
operation_fingerprint
~~~

同一 correlated operation 的 retry 必须复用同一 key。

## 10. Step attempt sequence

新增：

~~~text
StepAttemptSequenceAuthority
StepAttemptSequenceDecision
~~~

claim_next 必须原子保证：

~~~text
next_attempt = expected_current_attempt + 1
~~~

CONFLICT / UNKNOWN 不得 invent next_attempt/claim token。

Domain 不拥有 attempt numbering。

## 11. Step reliability authority

StepReliabilityDisposition：

~~~text
RETRY
KEEP_RUNNING
WAIT_RECOVERY
FINALIZE
ABORT_UNKNOWN
~~~

StepReliabilityEvaluator 只做 disposition 决策，不修改 lifecycle。

RETRY 必须明确 next_attempt。

## 12. Step finalization authority

StepFinalizationDisposition：

~~~text
FINALIZE
KEEP_RUNNING
WAIT_RECOVERY
UNKNOWN
~~~

IU6 第一版允许 FINALIZE 的 terminal status 只有：

~~~text
SUCCESS
FAILED
TIMEOUT
~~~

以下仍不属于 IU6：

~~~text
CANCELLED
PREEMPTED
~~~

它们继续由 Step 9 Cancellation/Preemption control authority 处理。

StepFinalizationEvaluator 不解释 ActionStep.on_failure / fallback_plan / stop_conditions。

## 13. Explicit non-goals

本 Amendment 不实现：

~~~text
actual Retry loop
Retry policy execution coordinator
AsyncTimeoutRunner wiring
ExecutionLifecycleService.finish_step 调用
Workflow start auto-retry
Workflow resume / recovery
durable Step attempt persistence
Resource Lock
Cancellation / Preemption handler
Plan stop/fallback
Aggregation
M6
~~~

## 14. Blocker closure conditions

只有以下条件全部满足后，B-002～B-006 才可 CLOSED：

~~~text
1. logical/physical Tool attempt contract 完整
2. journal physical attempts identity/fingerprint/key 全部稳定
3. Idempotency provenance + COMPLETED recovery + FAILED reopen + UNKNOWN fail-closed 完整
4. Step attempt sequence 有 Core authority
5. Step finalization 有显式 evaluator，不再猜测 UNKNOWN/BLOCKED/PARTIAL_SUCCESS/NO_EXTERNAL_EXECUTION
6. cross-Step Tool correlation 能区分 identical duplicate calls
7. sequence drift/ambiguous correlation → UNKNOWN
8. IU6 不越权 terminalize CANCELLED/PREEMPTED
9. targeted amendment review = PASSED
10. four local gates = GREEN
~~~

## 15. Current status

~~~text
CA-M5-IU6-02 = CODE COMPLETE
CA-M5-IU6-02 TARGETED AMENDMENT REVIEW = PENDING
CA-M5-IU6-02 VERIFICATION = PENDING FOUR LOCAL GATES

B-M5-IU6-002 = FIX_IMPLEMENTED_PENDING_REVIEW_AND_GATES
B-M5-IU6-003 = FIX_IMPLEMENTED_PENDING_REVIEW_AND_GATES
B-M5-IU6-004 = FIX_IMPLEMENTED_PENDING_REVIEW_AND_GATES
B-M5-IU6-005 = FIX_IMPLEMENTED_PENDING_REVIEW_AND_GATES
B-M5-IU6-006 = FIX_IMPLEMENTED_PENDING_REVIEW_AND_GATES

M5-IU6 IMPLEMENTATION READINESS = NOT_READY
M5 = IN PROGRESS
~~~