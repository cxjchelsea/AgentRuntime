# CA-M5-IU10-01 Aggregation Eligibility + Plan Status Authority V1.0

> Parent：M5-IU10 — Step 12 Execution Aggregation
>
> Base：CA-M5-IU10-00 Verification Closure @ 1f34dba0f702116356e3aad487bd5f15c103128e

# 1. Amendment goal

关闭：

~~~text
B-M5-IU10-001
PLAN_STATUS_AND_AGGREGATION_ELIGIBILITY_NOT_FROZEN
~~~

CA-01 只冻结：

~~~text
什么时候可以进入 aggregation
自然 execution plan_status 怎么判
existing terminal replay 怎么校验
IU7 CANCEL/PREEMPT 如何保持优先级
SKIPPED / degraded 的 execution-layer 语义
~~~

CA-01 不实现：

~~~text
StepAggregationEvidence store
rich Skill / Workflow / Tool evidence persistence
ExecutionResult projector
multi-Workflow schema
cancellation projection
M6
~~~

# 2. Core contracts

新增：

~~~text
AggregationEvidenceReadinessStatus
AggregationEvidenceReadinessDecision
AggregationControlApplicabilityStatus
AggregationControlApplicabilityDecision
StepSkipAggregationDisposition
StepSkipAggregationDecision
StepAggregationEffect
ExecutionAggregationEligibilityStatus
ExecutionAggregationDecision
ExecutionAggregationEligibilityDecision
ExecutionAggregationAuthority
~~~

# 3. Aggregation eligibility states

冻结：

~~~text
READY_NATURAL
READY_EXISTING_TERMINAL
WAITING
BLOCKED_UNKNOWN
~~~

解释：

~~~text
READY_NATURAL
= execution 仍 RUNNING，但所有 Step 已形成可聚合终态，
  control/evidence 均清晰，可以授权 natural plan_status

READY_EXISTING_TERMINAL
= execution lifecycle 已终态，
  且重新计算出的 aggregation authority 与已持久化终态一致

WAITING
= execution 尚未具备 final aggregation 条件，
  但没有发现矛盾/未知真值

BLOCKED_UNKNOWN
= authority / evidence / lifecycle 存在未知、缺失或矛盾，
  不得压成 FAILED
~~~

# 4. Evidence readiness seam

CA-01 不实现 CA-02 的 evidence store，但冻结输入 seam：

~~~text
READY
MISSING
UNKNOWN
~~~

规则：

~~~text
READY
-> status authority 可继续

MISSING
-> BLOCKED_UNKNOWN / AGGREGATION_EVIDENCE_MISSING

UNKNOWN
-> BLOCKED_UNKNOWN / AGGREGATION_EVIDENCE_UNKNOWN
~~~

Formal Implementation 强制要求：

~~~text
AggregationEvidenceReadinessDecision.READY
必须由 CA-02 authoritative evidence layer 产生

并且必须绑定 exact execution_id。
~~~

禁止：

~~~text
caller hand-construct READY 为了绕过 rich evidence
missing evidence -> READY fallback
unknown evidence -> FAILED
~~~

# 5. Control precedence + applicability authority

IU9 durable control read 只回答：

~~~text
是否存在 durable latched CANCEL / PREEMPT
~~~

它不回答：

~~~text
这个 control 在 aggregation 时仍应覆盖自然完成，
还是已经被证明为 late no-op
~~~

因此 CA-01 新增：

~~~text
AggregationControlApplicabilityStatus

NONE
APPLIES
LATE_NOOP
UNKNOWN
~~~

以及 exact：

~~~text
AggregationControlApplicabilityDecision
- status
- reason_codes
- latched_control?
~~~

规则：

~~~text
NONE
-> durable control 必须 NONE

APPLIES
-> 必须携带并 exact 等于当前 DurableControlReadDecision.latched_control

LATE_NOOP
-> 必须携带并 exact 等于当前 DurableControlReadDecision.latched_control

同 signal type 但不同 signal_id / reason / source / timestamp
也不得复用 applicability。

UNKNOWN
-> BLOCKED_UNKNOWN
~~~

CA-01 不根据时间戳或 Step 状态自行推断 applicability。
后续 CA-03 必须提供 durable / authoritative applicability provenance。


## 5.1 UNKNOWN

~~~text
control.status = UNKNOWN
-> BLOCKED_UNKNOWN
~~~

## 5.2 LATCHED + execution 尚未 control-terminalize

~~~text
latched CANCEL/PREEMPT
+
execution not yet matching terminal lifecycle
->
BLOCKED_UNKNOWN
AGGREGATION_CONTROL_TERMINALIZATION_REQUIRED
~~~

IU10 不抢 IU7 mutation authority。

## 5.3 Late-control race

Independent Review 发现真实竞态：

~~~text
last Step terminalized
↓
execution lifecycle still RUNNING
↓
CANCEL/PREEMPT arrives
↓
IU7 sees no unfinished Step
-> ALREADY_TERMINAL / no Step mutation
↓
durable latch exists
but execution still RUNNING
~~~

如果把“durable latch exists”直接解释成“必须 control-terminalize”，会永久阻塞 natural aggregation。

冻结：

~~~text
LATE_NOOP
+ exact same latched control
+ all Steps terminal
+ no CANCELLED/PREEMPTED execution lifecycle
->
允许继续 natural aggregation
~~~

如果 LATE_NOOP 仍有 PENDING/RUNNING Step：

~~~text
BLOCKED_UNKNOWN
AGGREGATION_LATE_CONTROL_HAS_UNFINISHED_WORK
~~~

## 5.4 Existing terminal control replay

~~~text
CANCEL latch + execution CANCELLED
-> READY_EXISTING_TERMINAL / CANCELLED

PREEMPT latch + execution PREEMPTED
-> READY_EXISTING_TERMINAL / PREEMPTED
~~~

要求：

~~~text
exact target execution_id
all Steps terminal
no opposite control Step status
rich evidence READY
~~~

控制冲突：

~~~text
CANCEL latch + PREEMPTED execution
PREEMPT latch + CANCELLED execution
CANCEL execution containing PREEMPTED Step
PREEMPT execution containing CANCELLED Step
-> BLOCKED_UNKNOWN
~~~

已在 control 到来前完成的 SUCCESS / FAILED / SKIPPED / TIMEOUT Step 可以保留。

# 6. Control provenance missing

~~~text
execution = CANCELLED / PREEMPTED
+
durable control read = NONE
->
BLOCKED_UNKNOWN
AGGREGATION_CONTROL_PROVENANCE_MISSING
~~~

自然 RUNNING execution 中出现 CANCELLED / PREEMPTED Step 而无 durable control：

~~~text
BLOCKED_UNKNOWN
AGGREGATION_STEP_CONTROL_PROVENANCE_MISSING
~~~

# 7. Nonterminal states

~~~text
execution = CREATED
-> WAITING / AGGREGATION_EXECUTION_NOT_STARTED

execution = RUNNING
+ any Step PENDING/RUNNING
-> WAITING / AGGREGATION_STEPS_NOT_TERMINAL
~~~

execution 已 terminal 但仍有 PENDING / RUNNING Step：

~~~text
BLOCKED_UNKNOWN
AGGREGATION_TERMINAL_EXECUTION_HAS_NONTERMINAL_STEP
~~~

# 8. Required / Optional authority

唯一来源：

~~~text
ApprovedActionPlan.steps[].optional
~~~

冻结：

~~~text
optional is True -> OPTIONAL
optional is False / None -> REQUIRED
~~~

# 9. Step aggregation semantic effects

先归一化为：

~~~text
SATISFIED
DEGRADED
UNSATISFIED
TIMEOUT
NOT_APPLICABLE
~~~

直接映射：

~~~text
Step SUCCESS + degraded=false -> SATISFIED
Step SUCCESS + degraded=true  -> DEGRADED
Step FAILED                   -> UNSATISFIED
Step TIMEOUT                  -> TIMEOUT
~~~

SKIPPED 必须有额外 provenance。

不是裸 enum，而是 exact：

~~~text
StepSkipAggregationDecision
- execution_id
- step_execution_id
- step_id
- disposition
- reason_codes

CA-02 给出的 skip decision 必须与当前 lifecycle exact identity 一致。
~~~

映射：

~~~text
NOT_APPLICABLE -> NOT_APPLICABLE
UNSATISFIED    -> UNSATISFIED
UNKNOWN/missing/identity mismatch -> BLOCKED_UNKNOWN
~~~

# 10. Why SKIPPED is not equal to FAILED

当前 Scheduler 至少存在两类 SKIP：

~~~text
registered execution condition NOT_SATISFIED
-> 合法条件分支没有触发

dependency not successful
-> action 无法执行
~~~

因此：

~~~text
SKIPPED != FAILED
~~~

CA-02 后续必须用 terminal evidence 提供可证明的 skip disposition，CA-01 不从任意字符串猜业务含义。

# 11. Natural plan_status matrix

## 11.1 Required TIMEOUT

~~~text
any REQUIRED TIMEOUT
-> TIMEOUT
~~~

## 11.2 Required UNSATISFIED

若无 required TIMEOUT：

~~~text
any REQUIRED UNSATISFIED
-> FAILED
~~~

optional success 不得把 required failure 稀释成 PARTIAL_SUCCESS。

## 11.3 Required DEGRADED

若无 required TIMEOUT / UNSATISFIED：

~~~text
any REQUIRED DEGRADED
-> PARTIAL_SUCCESS
~~~

## 11.4 Required 全部满足或不适用

~~~text
all REQUIRED in SATISFIED / NOT_APPLICABLE
~~~

再看 optional。

optional 无 DEGRADED / UNSATISFIED / TIMEOUT：

~~~text
SUCCESS
~~~

全部 Step 都 NOT_APPLICABLE：

~~~text
SUCCESS
~~~

这里只表示 Approved Plan 按条件正常收口，不表示业务目标成功。

## 11.5 Optional degradation/failure/timeout

required 已满足/不适用，optional 有 DEGRADED / UNSATISFIED / TIMEOUT，且全 Plan 至少有 SATISFIED / DEGRADED：

~~~text
PARTIAL_SUCCESS
~~~

## 11.6 没有任何执行进展

如果没有任何 SATISFIED / DEGRADED：

~~~text
optional TIMEOUT exists -> TIMEOUT
otherwise optional UNSATISFIED -> FAILED
~~~

# 12. Example matrix

| Required | Optional | Result |
|---|---|---|
| SATISFIED | SATISFIED | SUCCESS |
| SATISFIED | UNSATISFIED | PARTIAL_SUCCESS |
| SATISFIED | TIMEOUT | PARTIAL_SUCCESS |
| DEGRADED | any non-control | PARTIAL_SUCCESS |
| UNSATISFIED | SATISFIED | FAILED |
| TIMEOUT | SATISFIED | TIMEOUT |
| NOT_APPLICABLE | SATISFIED | SUCCESS |
| NOT_APPLICABLE | UNSATISFIED only | FAILED |
| NOT_APPLICABLE | TIMEOUT only | TIMEOUT |
| all NOT_APPLICABLE | — | SUCCESS |

# 13. Existing terminal replay

~~~text
natural plan_status decided
-> finish_execution persisted
-> process crash before ExecutionResult returned
~~~

恢复后重新计算。

computed status == persisted execution status：

~~~text
READY_EXISTING_TERMINAL
AGGREGATION_EXISTING_TERMINAL_REPLAY_AUTHORIZED
~~~

不一致：

~~~text
BLOCKED_UNKNOWN
AGGREGATION_EXISTING_TERMINAL_STATUS_MISMATCH
~~~

不得覆盖旧 terminal lifecycle。

# 14. Natural lifecycle mutation boundary

CA-01 只产出 ExecutionAggregationDecision，不直接调用 finish_execution。

ExecutionAggregationDecision 必须绑定：

~~~text
execution_id
plan_id
plan_status
reason_codes
~~~

不得把一个 execution 的 aggregation decision 用到另一个 execution。

Formal wiring：

~~~text
ExecutionAggregationAuthority
-> READY_NATURAL + plan_status
-> existing ExecutionLifecycleService.finish_execution(...)
~~~

不得新增第二套 execution terminal mutation。

# 15. Alignment authority

必须验证：

~~~text
ApprovedActionPlan.plan_id/request_id
ExecutionContext.plan_id/request_id/execution_id
ExecutionRecord.plan_id/request_id/execution_id
Approved Step order
Prepared Step order
unique step_id
nonblank step_execution_id
exact ActionStep.action
exact skill_id / workflow_id
ExecutionContext.identity_scope == ExecutionRecord.identity_scope
ExecutionRecord.current_step == exact RUNNING Step or None
at most one RUNNING Step
~~~

不一致：

~~~text
BLOCKED_UNKNOWN
~~~

# 16. Lifecycle timing consistency

Eligibility 必须 fail-closed 校验基础 lifecycle envelope：

~~~text
RUNNING execution
-> started_at required
-> finished_at must be None

terminal execution
-> started_at / finished_at required
-> finished_at >= started_at

PENDING Step
-> no started_at / finished_at

RUNNING Step
-> started_at required
-> finished_at None

terminal Step
-> finished_at required
-> if started_at exists: finished_at >= started_at
~~~

这些是 M5 lifecycle facts，不属于 CA-02 rich evidence。

# 17. Files

~~~text
runtime/execution/aggregation_authority.py
runtime/execution/__init__.py
tests/test_m5_iu10_ca01_aggregation_authority.py
~~~

# 18. Behavioral gates

~~~text
1. PENDING -> WAITING
2. RUNNING -> WAITING
3. unknown control -> BLOCKED_UNKNOWN
4. latched control before IU7 terminalization -> BLOCKED_UNKNOWN
5. CANCEL replay preserves CANCELLED
6. PREEMPT replay preserves PREEMPTED
7. control terminal without provenance -> BLOCKED_UNKNOWN
8. contradictory control Step status -> BLOCKED_UNKNOWN
9. required + optional success -> SUCCESS
10. required timeout -> TIMEOUT
11. required failure -> FAILED
12. required degraded -> PARTIAL_SUCCESS
13. optional failure after required success -> PARTIAL_SUCCESS
14. required NOT_APPLICABLE skip -> not failure
15. required UNSATISFIED skip -> FAILED
16. skipped without provenance -> BLOCKED_UNKNOWN
17. missing rich evidence -> BLOCKED_UNKNOWN
18. unknown rich evidence -> BLOCKED_UNKNOWN
19. existing terminal exact replay -> READY_EXISTING_TERMINAL
20. existing terminal mismatch -> BLOCKED_UNKNOWN
21. all optional with no progress -> FAILED / TIMEOUT
22. all NOT_APPLICABLE -> SUCCESS
23. late no-op control after all Steps terminal -> natural aggregation
24. late no-op with unfinished work -> BLOCKED_UNKNOWN
25. control applicability must bind exact latched control
26. evidence readiness from other execution -> BLOCKED_UNKNOWN
27. skip decision from other step_execution_id -> BLOCKED_UNKNOWN
28. aggregation decision binds exact execution_id + plan_id
29. Step action/capability provenance drift -> BLOCKED_UNKNOWN
30. current_step pointer drift -> BLOCKED_UNKNOWN
31. terminal Step missing finished_at -> BLOCKED_UNKNOWN
32. existing terminal execution missing finished_at -> BLOCKED_UNKNOWN
33. executed SUCCESS/FAILED/TIMEOUT Step missing started_at -> BLOCKED_UNKNOWN
34. persisted Step fact drift -> BLOCKED_UNKNOWN
35. corrupted CREATED execution with terminal Step -> BLOCKED_UNKNOWN
~~~

# 19. Independent Review findings

~~~text
F-M5-IU10-CA01-001
ALL_STEPS_TERMINAL_LATCHED_CONTROL_COULD_DEADLOCK_AGGREGATION
= CLOSED

F-M5-IU10-CA01-002
CONTROL_APPLICABILITY_NOT_BOUND_TO_EXACT_LATCH
= CLOSED

F-M5-IU10-CA01-003
EVIDENCE_READINESS_NOT_BOUND_TO_EXECUTION
= CLOSED

F-M5-IU10-CA01-004
SKIP_DISPOSITION_NOT_BOUND_TO_EXACT_STEP_EXECUTION
= CLOSED

F-M5-IU10-CA01-005
AGGREGATION_DECISION_NOT_BOUND_TO_EXECUTION_PLAN
= CLOSED

F-M5-IU10-CA01-006
STEP_PROVENANCE_AND_CURRENT_STEP_ALIGNMENT_INCOMPLETE
= CLOSED

F-M5-IU10-CA01-007
AGGREGATION_ELIGIBILITY_DID_NOT_VALIDATE_LIFECYCLE_TIMING_ENVELOPE
= CLOSED

F-M5-IU10-CA01-008
PREPARED_STEP_AND_PERSISTED_EXECUTION_RECORD_COULD_DIVERGE
= CLOSED

F-M5-IU10-CA01-009
EXECUTED_TERMINAL_STEP_COULD_LACK_START_EVIDENCE
= CLOSED

F-M5-IU10-CA01-010
CORRUPTED_CREATED_EXECUTION_COULD_BE_MISCLASSIFIED_AS_WAITING
= CLOSED

F-M5-IU10-CA01-011
PERSISTED_STEP_ALIGNMENT_HELPER_DISPATCH_WAS_INVALID
= CLOSED
~~~

# 20. Blocker impact

~~~text
B-M5-IU10-001
PLAN_STATUS_AND_AGGREGATION_ELIGIBILITY_NOT_FROZEN
= FIX_IMPLEMENTED_PENDING_REVIEW_AND_GATES
~~~

其余：

~~~text
B-M5-IU10-002 = OPEN
B-M5-IU10-003 = OPEN
B-M5-IU10-004 = OPEN
B-M5-IU10-005 = OPEN
B-M5-IU10-006 = OPEN
B-M5-IU10-007 = CLOSED
B-M5-IU10-008 = CLOSED
~~~

# 21. Formal Implementation dependency

CA-01 依赖后续 CA-02 提供 authoritative：

~~~text
AggregationEvidenceReadinessDecision
StepSkipAggregationDecision
~~~

并依赖后续 CA-03 / B-004 control provenance 提供：

~~~text
AggregationControlApplicabilityDecision
~~~

Formal Implementation 不得手工构造 READY / LATE_NOOP / APPLIES 来绕过 evidence/control provenance。

所以 CA-01 即使 PASSED，M5-IU10 仍不能 READY。

# 22. Non-goals

~~~text
rich evidence persistence
StepAggregationEvidence
ExecutionResult projection
multi Workflow output
control provenance projection into ExecutionResult
quality/errors/events construction
M6 validation
response generation
state/memory mutation
~~~

# 23. Current status

~~~text
CA-M5-IU10-01 = PASSED
CA-M5-IU10-01 INDEPENDENT REVIEW = PASSED
CA-M5-IU10-01 VERIFICATION = PASSED

B-M5-IU10-001 = CLOSED

M5-IU10 IMPLEMENTATION READINESS = NOT_READY
FORMAL IMPLEMENTATION = NOT AUTHORIZED
M5 = IN PROGRESS
~~~


# 24. Independent Review decision（历史时点）

> 本节记录 Independent Review 完成时的历史状态；当前正式状态以第 25 节 Verification Closure 为准。

累计复核范围：

~~~text
aggregation eligibility
required / optional authority
SKIPPED semantic provenance
degraded semantics
natural plan_status precedence
existing terminal replay
IU7 control precedence
late-control no-op race
exact evidence / skip / control identities
execution / plan decision identity
lifecycle timing envelope
PreparedExecution vs persisted ExecutionRecord alignment
~~~

结论：

~~~text
CA-M5-IU10-01 = CODE COMPLETE
CA-M5-IU10-01 INDEPENDENT REVIEW = PASSED
CA-M5-IU10-01 VERIFICATION = PENDING

B-M5-IU10-001
PLAN_STATUS_AND_AGGREGATION_ELIGIBILITY_NOT_FROZEN
= FIX_IMPLEMENTED_PENDING_GATES

NEW SEMANTIC BLOCKER = NONE
~~~

CA-01 通过 Review 不等于 M5-IU10 READY。

仍然：

~~~text
B-M5-IU10-002 = OPEN
B-M5-IU10-003 = OPEN
B-M5-IU10-004 = OPEN
B-M5-IU10-005 = OPEN
B-M5-IU10-006 = OPEN

M5-IU10 IMPLEMENTATION READINESS = NOT_READY
FORMAL IMPLEMENTATION = NOT AUTHORIZED
~~~

四项门禁已通过并完成 Verification Closure：

~~~text
CA-M5-IU10-01 = PASSED
B-M5-IU10-001 = CLOSED
~~~


# 25. Verification Closure

Verification target code HEAD：

~~~text
47d8552232087285996fa85ac7c41e99947d57e0
~~~

相对 Independent Review closure HEAD：

~~~text
6d924410f741dcf2de6a75d892f4f48344fb3d94
~~~

仅有两项门禁兼容修改：

~~~text
1. aggregation_authority.py
   - typing.Mapping -> typing.ClassVar, Mapping
   - _TERMINAL_EXECUTION_STATUSES 标注为
     ClassVar[dict[str, ExecutionPlanStatus]]
   - 仅消除 RUF012
   - 不改变 aggregation status / eligibility / control / evidence 语义

2. test_m5_iu10_ca01_aggregation_authority.py
   - test_terminal_step_missing_finished_at_is_blocked
     同时清空 PreparedExecution Step 与 persisted step_results 的 finished_at
   - 保证该测试穿过 persisted-fact alignment，
     精确验证 AGGREGATION_TERMINAL_STEP_FINISH_MISSING
   - 不改变 production code 语义
~~~

isinstance fail-closed 校验继续使用 ValueError，并保留 noqa: TRY004。

无 authority 语义变化，无 status matrix 变化，无新 runtime wiring。

四项门禁：

~~~text
python -m pytest tests -q
-> 898 passed

python -m mypy runtime tests
-> Success: no issues found in 211 source files

python -m ruff check runtime tests
-> All checks passed

python -m ruff format --check runtime tests
-> 211 files already formatted
~~~

Verification 结论：

~~~text
CA-M5-IU10-01 = PASSED
CA-M5-IU10-01 INDEPENDENT REVIEW = PASSED
CA-M5-IU10-01 VERIFICATION = PASSED

B-M5-IU10-001
PLAN_STATUS_AND_AGGREGATION_ELIGIBILITY_NOT_FROZEN
= CLOSED

NEW VERIFICATION BLOCKER = NONE
~~~

该 Closure 只关闭 CA-01 / B-001。

仍然保持：

~~~text
B-M5-IU10-002 = OPEN
B-M5-IU10-003 = OPEN
B-M5-IU10-004 = OPEN
B-M5-IU10-005 = OPEN
B-M5-IU10-006 = OPEN

B-M5-IU10-007 = CLOSED
B-M5-IU10-008 = CLOSED

M5-IU10 IMPLEMENTATION READINESS = NOT_READY
FORMAL IMPLEMENTATION = NOT AUTHORIZED
M5 = IN PROGRESS
~~~

下一步允许进入：

~~~text
CA-M5-IU10-02
Crash-Safe Terminal Step Aggregation Evidence
~~~

CA-02 必须消费并实现 CA-01 已冻结的：

~~~text
AggregationEvidenceReadinessDecision
StepSkipAggregationDecision
~~~

不得重新定义 CA-01 的 plan_status matrix。
