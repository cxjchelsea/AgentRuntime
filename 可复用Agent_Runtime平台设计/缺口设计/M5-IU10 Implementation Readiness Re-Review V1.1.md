# M5-IU10 Implementation Readiness Re-Review V1.1

> Review target：M5-IU10 — Step 12 Execution Aggregation。
>
> 本文件是 CA-M5-IU10-04 Verification Closure 之后的第二轮累计 Re-Review。
>
> V1.0 保留第一次 Re-Review 的历史结论：
>
> ~~~text
> BLOCKED
> B-M5-IU10-009 = OPEN
> ~~~
>
> 本 V1.1 只判断 CA-04 关闭 B-009 后，M5-IU10 是否已经具备进入 Formal Implementation 的完整 authority / contract。

# 1. Final readiness decision

~~~text
M5-IU10 IMPLEMENTATION DESIGN = COMPLETE
M5-IU10 INDEPENDENT DESIGN REVIEW = PASSED

CA-M5-IU10-00 = PASSED
CA-M5-IU10-01 = PASSED
CA-M5-IU10-02 = PASSED
CA-M5-IU10-03 = PASSED
CA-M5-IU10-04 = PASSED

B-M5-IU10-001 = CLOSED
B-M5-IU10-002 = CLOSED
B-M5-IU10-003 = CLOSED
B-M5-IU10-004 = CLOSED
B-M5-IU10-005 = CLOSED
B-M5-IU10-006 = CLOSED
B-M5-IU10-007 = CLOSED
B-M5-IU10-008 = CLOSED
B-M5-IU10-009 = CLOSED

M5-IU10 IMPLEMENTATION READINESS RE-REVIEW = PASSED
M5-IU10 IMPLEMENTATION READINESS = READY

BLOCKERS = 0
NEW BLOCKER = NONE

FORMAL IMPLEMENTATION = AUTHORIZED

M5 = IN PROGRESS
NEXT REQUIRED = M5-IU10 Formal Implementation
~~~

READY 只授权冻结范围内的 M5-IU10 Formal Implementation。

它不表示：

~~~text
M5-IU10 = PASSED
M5 = CLOSED
M6 = implemented
production storage adapters = complete
end-to-end Runtime = production ready
~~~

# 2. Evidence baseline

Latest CA-04 verified code HEAD：

~~~text
cf9dea1a702af3bbdbf050e89c81fec4b01a4b4e
~~~

Verification Closure HEAD：

~~~text
055b6931c37247a7e1e5ee676bfd25a31aac7b0c
~~~

Closure HEAD 相对 verified code HEAD 仅增加 Verification Closure 文档。

Latest verification：

~~~text
python -m pytest tests -q
-> 953 passed

python -m mypy runtime tests
-> Success: no issues found in 217 source files

python -m ruff check runtime tests
-> All checks passed

python -m ruff format --check runtime tests
-> 217 files already formatted
~~~

Result：PASS。

# 3. CA-M5-IU10-00 cumulative result

已冻结并验证：

~~~text
Scheduler-authorized PENDING -> SKIPPED
required-upstream-failure remainder closure
WAITING / UNKNOWN cannot terminalize PENDING
Running Step finalization uses existing lifecycle boundary
PARTIAL_SUCCESS owner observation
-> Step SUCCESS lifecycle
-> degraded = true
exact terminal reason persistence
aggregation evidence + terminal lifecycle atomic persistence
~~~

Closed：

~~~text
B-M5-IU10-007
PENDING_STEP_TERMINALIZATION_AUTHORITY_MISSING

B-M5-IU10-008
PARTIAL_SUCCESS_STEP_FINALIZATION_AUTHORITY_MISSING
~~~

Result：PASS。

# 4. CA-M5-IU10-01 cumulative result

已冻结并验证：

~~~text
READY_NATURAL
READY_EXISTING_TERMINAL
WAITING
BLOCKED_UNKNOWN

required / optional semantics
natural plan-status matrix
existing-terminal replay consistency
control precedence
APPLIES / LATE_NOOP consumption semantics
lifecycle/persisted fact alignment
~~~

Closed：

~~~text
B-M5-IU10-001
PLAN_STATUS_AND_AGGREGATION_ELIGIBILITY_NOT_FROZEN
~~~

Result：PASS。

# 5. CA-M5-IU10-02 cumulative result

已冻结并验证：

~~~text
typed StepAggregationEvidence
ATTEMPT_FINALIZED
SCHEDULER_SKIPPED
CONTROL_TERMINALIZED

exact Skill owner/result
exact Workflow owner/result
exact Tool journal truth
scheduler skip provenance
minimal control-terminal Step evidence
recovery serialization
legacy missing evidence -> MISSING / UNKNOWN
project_ca01_evidence_inputs(...)
~~~

Closed：

~~~text
B-M5-IU10-002
CRASH_SAFE_RICH_AGGREGATION_EVIDENCE_MISSING
~~~

Result：PASS。

# 6. CA-M5-IU10-03 cumulative result

已冻结并验证：

~~~text
ExecutionResult schema 1.1.0
workflow_results[] lossless multi-Workflow field
legacy workflow_result compatibility
CanonicalExecutionResultProjector
ExecutionAggregator
deterministic Step / Skill / Workflow / Tool ordering
natural terminal commit through ExecutionLifecycleService
existing-terminal deterministic replay
durable current-attempt Tool journal join
ApprovedPlan Tool id/version revalidation
exact CANCEL/PREEMPT result provenance
M5-only quality projection
~~~

Closed：

~~~text
B-M5-IU10-003
WORKFLOW_RESULT_CARDINALITY_CONTRACT_MISMATCH

B-M5-IU10-004
CONTROL_TERMINATION_PROVENANCE_NOT_BOUND_TO_RESULT

B-M5-IU10-005
SKELETON_EXECUTION_RESULT_PROJECTOR_INCOMPLETE

B-M5-IU10-006
AGGREGATION_REPLAY_DETERMINISM_NOT_FROZEN
~~~

Result：PASS。

# 7. CA-M5-IU10-04 cumulative result

第一次 Readiness Re-Review 唯一新 blocker：

~~~text
B-M5-IU10-009
DURABLE_CONTROL_APPLICABILITY_AUTHORITY_MISSING
~~~

CA-04 已补齐：

~~~text
DurableControlApplicabilityRecord
DurableControlApplicabilityStore
DurableControlApplicabilityRecorder
DurableAggregationControlAuthority
AggregationControlAuthoritySnapshot
~~~

冻结映射：

~~~text
READY_TO_TERMINALIZE
-> APPLIES

true late ALREADY_TERMINAL
-> LATE_NOOP

durable control NONE
+
no applicability record
-> NONE

missing / conflicting / stale / ambiguous evidence
-> UNKNOWN
~~~

并冻结：

~~~text
exact durable latch identity
immutable first applicability
recovery-epoch fencing
write-before-control-lifecycle
natural terminal commit re-resolves control authority
control-terminal replay does not rewrite APPLIES to LATE_NOOP
Formal ExecutionAggregator owns control resolution
caller cannot inject control / control_applicability
~~~

Closed：

~~~text
B-M5-IU10-009 = CLOSED
~~~

Result：PASS。

# 8. Readiness gate re-evaluation

## Gate 1 — Design complete

~~~text
M5-IU10 IMPLEMENTATION DESIGN = COMPLETE
~~~

Result：PASS。

## Gate 2 — Independent Design Review

~~~text
M5-IU10 INDEPENDENT DESIGN REVIEW = PASSED
~~~

Result：PASS。

## Gate 3 — Controlled Amendments

~~~text
CA-00 = PASSED
CA-01 = PASSED
CA-02 = PASSED
CA-03 = PASSED
CA-04 = PASSED
~~~

Result：PASS。

## Gate 4 — All known blockers

~~~text
B-M5-IU10-001..009 = CLOSED
~~~

Result：PASS。

## Gate 5 — Terminal Step authority

PENDING/SKIP/remainder closure 和 Running Step finalization 都已有唯一 authority。

Result：PASS。

## Gate 6 — Natural plan-status authority

Required/optional、TIMEOUT/FAILED/PARTIAL_SUCCESS/SUCCESS matrix 已冻结。

Result：PASS。

## Gate 7 — Existing terminal replay

Persisted terminal status 必须与重新计算的 exact aggregation status 一致。

Mismatch：

~~~text
BLOCKED_UNKNOWN
~~~

不会覆盖既有终态。

Result：PASS。

## Gate 8 — Rich evidence crash safety

Step terminal lifecycle 与 StepAggregationEvidence 同一 persistence boundary。

Result：PASS。

## Gate 9 — Skill / Workflow / Tool truth boundary

Formal aggregation 只消费冻结 evidence，不重新执行、不调用 Registry latest、不进行 capability substitution。

Result：PASS。

## Gate 10 — Workflow cardinality

~~~text
0 -> legacy None + plural []
1 -> legacy exact + plural exact one
>1 -> legacy None + plural lossless ordered list
~~~

Result：PASS。

## Gate 11 — Control terminal provenance

CANCELLED/PREEMPTED Canonical result 需要：

~~~text
exact durable latch
+
APPLIES
+
matching terminal lifecycle
+
exact durable Tool journal where applicable
~~~

Result：PASS。

## Gate 12 — Late-control provenance

LATE_NOOP 只来自 durable IU7 application provenance。

禁止 timestamp/current-Step inference。

Result：PASS。

## Gate 13 — Applicability crash safety

APPLIES/LATE_NOOP evidence：

~~~text
immutable
recovery-epoch fenced
exact latch bound
replay-safe
~~~

Result：PASS。

## Gate 14 — Natural terminal race

READY_NATURAL 后：

~~~text
finish_execution(...)
↓
re-resolve authoritative control snapshot
↓
re-project CA-02 evidence
↓
re-evaluate CA-01
~~~

旧 NONE snapshot 不可跨 terminal commit 复用。

Result：PASS。

## Gate 15 — Formal control ownership

正式 ExecutionAggregator API 已不接受：

~~~text
control
control_applicability
~~~

而是依赖：

~~~text
AggregationControlAuthority
~~~

Result：PASS。

## Gate 16 — Canonical projector boundary

Formal publication 必须经过：

~~~text
ExecutionAggregator
-> READY_EXISTING_TERMINAL
-> CanonicalExecutionResultProjector
~~~

IU1 skeleton ExecutionResultProjector 不能作为 IU10 authority。

Result：PASS。

## Gate 17 — IU8 session terminal boundary preserved

Natural terminalization 继续通过：

~~~text
ExecutionLifecycleService.finish_execution(...)
~~~

该 service 已保留：

~~~text
ExecutionTerminalObserver
~~~

因此 Formal IU10 不需要新 session-lock release authority。

Result：PASS。

## Gate 18 — IU9 recovery boundary preserved

IU10 不接管：

~~~text
RecoveryCoordinator
Workflow resume
Tool reconciliation
resource reclaim
recovery claim policy
~~~

只消费 durable truth。

Result：PASS。

## Gate 19 — M6 boundary preserved

IU10 不判断 business truth，不进入 Result Validation。

Result：PASS。

## Gate 20 — Verification baseline

~~~text
953 passed
mypy 217 files clean
ruff check passed
ruff format 217 files formatted
~~~

Result：PASS。

# 9. Actual runtime integration review

当前仓库已经有 IU10 所需的全部 authority/component，但还没有：

~~~text
tests/test_m5_iu10_formal_implementation.py
M5-IU10 Formal Implementation 实现说明
完整 execution-loop wiring
~~~

这是符合当前阶段的。

它表示：

~~~text
Formal Implementation 尚未完成
~~~

而不是：

~~~text
Readiness contract 尚未定义
~~~

以下剩余工作均可直接由已有冻结 authority 实现，不需要新增设计决策。

# 10. FI-M5-IU10-REQ-001 — Terminal Step completion wiring

Formal Implementation 必须把：

~~~text
SequentialStepScheduler
↓
StepScheduleDecision
↓
TerminalStepCompletionCoordinator
~~~

接入真实 execution loop。

特别是：

~~~text
SKIP
required previous Step not successful
~~~

必须先完成 exact PENDING Step terminalization，再允许聚合。

禁止 Aggregator 自己把 PENDING 改成 SKIPPED。

Status：

~~~text
FORMAL IMPLEMENTATION REQUIRED
NOT A READINESS BLOCKER
~~~

# 11. FI-M5-IU10-REQ-002 — Running Step finalization wiring

真实 owner completion：

~~~text
IU6 StepReliabilityRunResult
↓
RunningStepCompletionCoordinator
↓
ExecutionLifecycleService.finish_step
↓
StepAggregationEvidence
~~~

Skill PARTIAL_SUCCESS：

~~~text
Step lifecycle SUCCESS
+
degraded = true
~~~

Status：

~~~text
FORMAL IMPLEMENTATION REQUIRED
NOT A READINESS BLOCKER
~~~

# 12. FI-M5-IU10-REQ-003 — Durable control writer composition

任何使用 durable terminal control 的 Formal control path 必须同时注入：

~~~text
DurableExecutionControlLatch
DurableControlApplicabilityRecorder
~~~

两者必须绑定：

~~~text
same execution_id
same exact current ExecutionRecoveryClaim / epoch authority
same durable control truth domain
~~~

ExecutionControlCoordinator.control_applicability_recorder 的 optional surface 只用于旧机制/测试兼容。

Formal IU10 path 不得省略 recorder。

Status：

~~~text
FORMAL IMPLEMENTATION REQUIRED
NOT A READINESS BLOCKER
~~~

Reason：

~~~text
recovery claim / epoch semantics 已由 IU9 冻结
CA-04 recorder contract 已冻结
只剩 dependency composition
~~~

# 13. FI-M5-IU10-REQ-004 — Formal aggregation control authority

Formal Aggregator 必须使用：

~~~text
DurableAggregationControlAuthority(
    control_store,
    applicability_store,
)
~~~

禁止 Formal path 使用 test-only/static：

~~~text
StaticAggregationControlAuthority
hand-built AggregationControlAuthoritySnapshot
hand-built AggregationControlApplicabilityDecision
~~~

Status：

~~~text
FORMAL IMPLEMENTATION REQUIRED
NOT A READINESS BLOCKER
~~~

# 14. FI-M5-IU10-REQ-005 — Control-path durable Tool reader

CanonicalExecutionResultProjector Formal instance 必须注入：

~~~text
DurableControlTerminalToolEvidenceReader
~~~

并从：

~~~text
StepAttemptCursorRecord.current_attempt
↓
exact durable Tool journal
~~~

读取 control-terminal Tool truth。

禁止：

~~~text
retry_count + 1
caller-provided journal
Tool id-only dedupe
~~~

Status：

~~~text
FORMAL IMPLEMENTATION REQUIRED
NOT A READINESS BLOCKER
~~~

# 15. FI-M5-IU10-REQ-006 — Natural terminal commit boundary

Formal natural aggregation：

~~~text
READY_NATURAL
↓
ExecutionLifecycleService.finish_execution(...)
↓
terminal observer remains active
↓
re-resolve control authority
↓
CA-01 re-evaluate
↓
READY_EXISTING_TERMINAL
~~~

不得直接构造 terminal ExecutionRecord。

不得跳过 IU8 terminal observer/session-release boundary。

Status：

~~~text
FORMAL IMPLEMENTATION REQUIRED
NOT A READINESS BLOCKER
~~~

# 16. FI-M5-IU10-REQ-007 — Publication boundary

只有：

~~~text
READY_EXISTING_TERMINAL
~~~

可以发布 Canonical ExecutionResult。

以下：

~~~text
WAITING
BLOCKED_UNKNOWN
CONTROL_TERMINALIZATION_REQUIRED
evidence MISSING
control/applicability UNKNOWN
~~~

都不得发布“近似结果”。

Formal integration 可以返回/传播 fail-closed reason，但不能伪造 terminal result。

Status：

~~~text
FORMAL IMPLEMENTATION REQUIRED
NOT A READINESS BLOCKER
~~~

# 17. FI-M5-IU10-REQ-008 — Canonical projector choice

Formal IU10 必须使用：

~~~text
CanonicalExecutionResultProjector
~~~

不得使用 IU1：

~~~text
ExecutionResultProjector
~~~

作为最终 aggregation authority。

IU1 projector 仅保留 skeleton/backward-compatibility 用途。

Status：

~~~text
FORMAL IMPLEMENTATION REQUIRED
NOT A READINESS BLOCKER
~~~

# 18. FI-M5-IU10-REQ-009 — End-to-end aggregation loop

Formal Implementation 必须至少证明：

~~~text
scheduler terminal closure
+
running Step finalization
+
CA-02 evidence readiness
+
durable control/applicability resolve
+
CA-01 eligibility
+
natural terminal commit or existing terminal replay
+
CA-03 Canonical projection
=
one complete IU10 path
~~~

同时覆盖：

~~~text
natural SUCCESS
PARTIAL_SUCCESS
FAILED
TIMEOUT
CANCELLED
PREEMPTED
late-control LATE_NOOP
crash/replay existing terminal
UNKNOWN / WAITING fail closed
multi-Workflow
control-path Tool evidence
~~~

Status：

~~~text
FORMAL IMPLEMENTATION REQUIRED
NOT A READINESS BLOCKER
~~~

# 19. Production durability boundary

仓库中的 InMemory stores 继续只是 reference/test mechanism。

Formal IU10 不得把它们描述成 production crash durability。

Production adapters 必须继续遵守：

~~~text
durable transaction / CAS
recovery-epoch fencing
immutable control applicability
exact identity
monotonic revision
fail-closed read uncertainty
~~~

这属于既有 IU9/CA-04 adapter contract，不需要新增 IU10 readiness blocker。

# 20. Authorized Formal Implementation scope

本次 READY 授权修改现有 M5 execution runtime，仅用于接线：

~~~text
SequentialStepScheduler
TerminalStepCompletionCoordinator
RunningStepCompletionCoordinator
ExecutionControlCoordinator + DurableControlApplicabilityRecorder
DurableAggregationControlAuthority
ExecutionAggregationAuthority
project_ca01_evidence_inputs
ExecutionLifecycleService
DurableControlTerminalToolEvidenceReader
CanonicalExecutionResultProjector
ExecutionAggregator
~~~

以及新增：

~~~text
M5-IU10 formal integration coordinator / composition
formal implementation behavioral tests
formal implementation documentation
~~~

允许做必要的 dependency injection / adapter composition / orchestration wiring。

# 21. Explicitly unauthorized scope

Formal IU10 不得实现：

~~~text
new M2 policy decision
control priority recomputation
new scheduler semantics
new retry policy
new replay policy
new recovery disposition
new ResourceLock semantics
Workflow capability substitution
Registry latest-version fallback
M6 business validation
M7 response generation
M8 state/memory mutation
new Runtime cycle after PREEMPT
business truth inference
medical truth inference
~~~

# 22. Implementation Review failure conditions

即使 Readiness = READY，Formal Implementation 若出现以下任一项，Independent Implementation Review 必须 FAIL：

~~~text
1. Aggregator terminalizes PENDING Step itself
2. PARTIAL_SUCCESS degradation is lost
3. caller can inject control applicability
4. durable control exists but recorder omitted in Formal path
5. current control authority is not re-resolved after natural terminal commit
6. control-terminal Tool journal uses retry_count inference
7. Formal path uses IU1 skeleton projector
8. WAITING/BLOCKED_UNKNOWN publishes ExecutionResult
9. existing terminal status is overwritten on mismatch
10. Tool/Skill/Workflow result is reconstructed from guesses
11. multi-Workflow result becomes first-wins/last-wins
12. session terminal observer is bypassed
13. Registry latest is consulted during replay
14. M6 validation is invoked from IU10
~~~

# 23. Final decision

~~~text
M5-IU10 IMPLEMENTATION READINESS RE-REVIEW = PASSED
M5-IU10 IMPLEMENTATION READINESS = READY

BLOCKERS = 0
NEW BLOCKER = NONE

B-M5-IU10-001..009 = CLOSED

FI-M5-IU10-REQ-001..009
= FORMAL IMPLEMENTATION REQUIRED

FORMAL IMPLEMENTATION = AUTHORIZED

M5 = IN PROGRESS

NEXT REQUIRED =
M5-IU10 Formal Implementation
~~~

This READY decision authorizes implementation only.

It does not close M5-IU10.
