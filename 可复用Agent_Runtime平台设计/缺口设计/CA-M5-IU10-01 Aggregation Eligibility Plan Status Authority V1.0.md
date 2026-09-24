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
StepSkipAggregationDisposition
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
~~~

禁止：

~~~text
caller hand-construct READY 为了绕过 rich evidence
missing evidence -> READY fallback
unknown evidence -> FAILED
~~~

# 5. Control precedence

直接消费 IU9 durable control read：DurableControlReadDecision。

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

## 5.3 Existing terminal control replay

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

SKIPPED 必须有额外 provenance：

~~~text
NOT_APPLICABLE -> NOT_APPLICABLE
UNSATISFIED    -> UNSATISFIED
UNKNOWN/missing -> BLOCKED_UNKNOWN
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
~~~

不一致：

~~~text
BLOCKED_UNKNOWN
~~~

# 16. Files

~~~text
runtime/execution/aggregation_authority.py
runtime/execution/__init__.py
tests/test_m5_iu10_ca01_aggregation_authority.py
~~~

# 17. Behavioral gates

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
~~~

# 18. Blocker impact

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

# 19. Formal Implementation dependency

CA-01 依赖后续 CA-02 提供 authoritative：

~~~text
AggregationEvidenceReadinessDecision
StepSkipAggregationDisposition
~~~

所以 CA-01 即使 PASSED，M5-IU10 仍不能 READY。

# 20. Non-goals

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

# 21. Current status

~~~text
CA-M5-IU10-01 = CODE COMPLETE
CA-M5-IU10-01 INDEPENDENT REVIEW = PENDING
CA-M5-IU10-01 VERIFICATION = PENDING

B-M5-IU10-001 = FIX_IMPLEMENTED_PENDING_REVIEW_AND_GATES

M5-IU10 IMPLEMENTATION READINESS = NOT_READY
FORMAL IMPLEMENTATION = NOT AUTHORIZED
M5 = IN PROGRESS
~~~
