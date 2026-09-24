# M5-IU10 Implementation Readiness Re-Review V1.0

> Review target：M5-IU10 — Step 12 Execution Aggregation。
>
> Baseline chain：
>
> - M5-IU9 = PASSED
> - CA-M5-IU10-00 = PASSED
> - CA-M5-IU10-01 = PASSED
> - CA-M5-IU10-02 = PASSED
> - CA-M5-IU10-03 = PASSED
>
> Latest verified code HEAD：
>
> ~~~text
> 289abb07c9a1d1fd08abf0ef66717b54433aad4a
> ~~~
>
> Latest verification：
>
> ~~~text
> pytest = 936 passed
> mypy = 215 source files, no issues
> ruff check = passed
> ruff format --check = 215 files formatted
> ~~~
>
> 本 Re-Review 只判断是否已经具备安全进入 M5-IU10 Formal Implementation 的全部 authority / contract。
> 不因为原始 blocker 数量归零而自动判 READY。

# 1. Final readiness decision

~~~text
M5-IU10 IMPLEMENTATION DESIGN = COMPLETE
M5-IU10 INDEPENDENT DESIGN REVIEW = PASSED

CA-M5-IU10-00 = PASSED
CA-M5-IU10-01 = PASSED
CA-M5-IU10-02 = PASSED
CA-M5-IU10-03 = PASSED

B-M5-IU10-001 = CLOSED
B-M5-IU10-002 = CLOSED
B-M5-IU10-003 = CLOSED
B-M5-IU10-004 = CLOSED
B-M5-IU10-005 = CLOSED
B-M5-IU10-006 = CLOSED
B-M5-IU10-007 = CLOSED
B-M5-IU10-008 = CLOSED

M5-IU10 IMPLEMENTATION READINESS RE-REVIEW = BLOCKED
M5-IU10 IMPLEMENTATION READINESS = NOT_READY

NEW BLOCKER =
B-M5-IU10-009
DURABLE_CONTROL_APPLICABILITY_AUTHORITY_MISSING

BLOCKERS = 1

FORMAL IMPLEMENTATION = NOT AUTHORIZED
M5 = IN PROGRESS
~~~

下一步：

~~~text
CA-M5-IU10-04
Durable Control Applicability Authority
~~~

# 2. Why original blocker closure is not enough

原始 8 个 blocker 已全部关闭，这一点成立。

但 CA-M5-IU10-01 明确冻结了一个后续依赖：

~~~text
AggregationControlApplicabilityDecision
~~~

并明确要求：

~~~text
Formal Implementation 不得手工构造
NONE / APPLIES / LATE_NOOP / UNKNOWN
来绕过真实 control provenance。
~~~

CA-01 同时明确：

~~~text
CA-01 不根据时间戳或 Step 状态自行推断 applicability。
后续 CA-03 必须提供 durable / authoritative applicability provenance。
~~~

Re-Review 检查当前代码后发现：

~~~text
AggregationControlApplicabilityDecision
= contract exists

ExecutionAggregationAuthority
= consumes it

ExecutionAggregator.aggregate(...)
= receives it from caller

authoritative producer
= MISSING

durable applicability evidence
= MISSING
~~~

因此 Formal Implementation 当前仍缺一个必须先冻结的 authority，而不是只缺 wiring。

# 3. CA-M5-IU10-00 cumulative result

CA-00 已冻结并验证：

~~~text
Scheduler-authorized PENDING -> SKIPPED
required-upstream-failure remainder terminalization
WAITING / UNKNOWN 不得被误终态化
Running Step finalization through existing lifecycle service
Skill PARTIAL_SUCCESS
-> Step SUCCESS lifecycle
-> degraded=true rich evidence
exact terminal reason persistence
recovery-safe additive terminal fields
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

CA-01 已冻结并验证：

~~~text
READY_NATURAL
READY_EXISTING_TERMINAL
WAITING
BLOCKED_UNKNOWN

required / optional plan-status authority
SKIPPED disposition authority
degraded -> PARTIAL_SUCCESS
natural terminal status precedence
existing-terminal exact replay
control precedence
late-control LATE_NOOP semantic
lifecycle/persisted fact alignment
~~~

Closed：

~~~text
B-M5-IU10-001
PLAN_STATUS_AND_AGGREGATION_ELIGIBILITY_NOT_FROZEN
~~~

但 CA-01 有一个显式 seam：

~~~text
AggregationControlApplicabilityDecision
~~~

该 seam 不是 CA-01 自己的职责，因此当时不构成 CA-01 failure；
它必须在 IU10 后续 cumulative chain 中得到 authoritative producer。

# 5. CA-M5-IU10-02 cumulative result

CA-02 已冻结并验证：

~~~text
typed StepAggregationEvidence
atomic terminal Step + evidence persistence
Skill / Workflow owner truth
Tool journal truth
scheduler SKIP provenance
minimal control-terminal Step evidence
IU9 recovery serialization
legacy missing-evidence fail-closed compatibility
project_ca01_evidence_inputs(...)
~~~

因此 CA-01 所需：

~~~text
AggregationEvidenceReadinessDecision
StepSkipAggregationDecision
~~~

已经有正式 producer。

Closed：

~~~text
B-M5-IU10-002
CRASH_SAFE_RICH_AGGREGATION_EVIDENCE_MISSING
~~~

Result：PASS。

# 6. CA-M5-IU10-03 cumulative result

CA-03 已冻结并验证：

~~~text
ExecutionResult schema 1.1.0 additive amendment
workflow_results[] lossless multi-Workflow projection
legacy workflow_result compatibility
CanonicalExecutionResultProjector
ExecutionAggregator
natural terminal commit through ExecutionLifecycleService
terminal replay
deterministic Step / Skill / Workflow / Tool ordering
durable current-attempt Tool journal join
ApprovedPlan Tool id/version revalidation
CANCEL / PREEMPT exact result provenance
M5-only quality projection
~~~

Closed：

~~~text
B-M5-IU10-003
B-M5-IU10-004
B-M5-IU10-005
B-M5-IU10-006
~~~

Result：PASS for CA-03's frozen scope。

# 7. New blocker found by cumulative Re-Review

## B-M5-IU10-009 DURABLE_CONTROL_APPLICABILITY_AUTHORITY_MISSING

Current contract：

~~~text
AggregationControlApplicabilityStatus
- NONE
- APPLIES
- LATE_NOOP
- UNKNOWN

AggregationControlApplicabilityDecision
- status
- reason_codes
- exact latched_control?
~~~

Current consumption：

~~~text
ExecutionAggregator.aggregate(
    ...,
    control: DurableControlReadDecision,
    control_applicability: AggregationControlApplicabilityDecision,
)
~~~

Current tests also directly construct：

~~~text
AggregationControlApplicabilityDecision(...)
~~~

No runtime component currently owns:

~~~text
DurableControlReadDecision
+
IU7 control application/lifecycle evidence
+
crash/recovery evidence
↓
AggregationControlApplicabilityDecision
~~~

This violates the CA-01 frozen rule that Formal Implementation must not hand-construct applicability.

# 8. Why this is a readiness blocker, not Formal Implementation wiring

If only ordinary wiring were missing, the required authority would already exist and Formal Implementation would merely connect it.

这里不是这种情况。

For one latched control：

~~~text
durable latch exists
~~~

cannot distinguish by itself：

~~~text
A. control should still APPLY
B. control was a proven late no-op
~~~

特别是 crash window：

~~~text
last Step terminalized
↓
CANCEL/PREEMPT latched
↓
IU7 evaluates ALREADY_TERMINAL
↓
no Step lifecycle mutation
↓
process crashes
↓
restart
~~~

Restart 后当前 durable truth 只有：

~~~text
latched control
+
terminal Step facts
~~~

如果没有 durable applicability provenance，系统不能证明：

~~~text
LATE_NOOP
~~~

而 CA-01 又明确禁止：

~~~text
只根据 timestamp / current Step state 自行猜 LATE_NOOP
~~~

如果 Formal Implementation 直接：

~~~text
AggregationControlApplicabilityDecision(
    status=LATE_NOOP,
    ...
)
~~~

就是绕过 authority。

因此这是 contract/authority 缺失，不是单纯 wiring。

# 9. Existing IU7 truth is useful but insufficient by itself

IU7 已经存在：

~~~text
ExecutionControlApplication
ExecutionControlDisposition.ALREADY_TERMINAL
ExecutionControlDisposition.READY_TO_TERMINALIZE
ExecutionControlRuntimeResult
ExecutionControlLifecycleTransitioner
~~~

其中：

~~~text
ALREADY_TERMINAL
~~~

可以作为 late-control no-op 的 live authority。

但当前缺少：

~~~text
将该 authority 变成 crash-safe aggregation provenance
~~~

也没有正式 projector：

~~~text
IU7 durable/live control truth
↓
AggregationControlApplicabilityDecision
~~~

因此不应在 IU10 Formal Implementation 中临时发明转换规则。

# 10. Required CA-M5-IU10-04

建议新增：

~~~text
CA-M5-IU10-04
Durable Control Applicability Authority
~~~

最小目标只关闭：

~~~text
B-M5-IU10-009
~~~

不得扩展为新的 Control Runtime。

至少需要冻结：

~~~text
1. applicability producer ownership
2. exact latch identity binding
3. APPLIES provenance
4. LATE_NOOP provenance
5. NONE provenance
6. UNKNOWN / conflict behavior
7. crash-safe persistence / recovery read
8. exact replay semantics
9. stale writer / mismatched execution rejection
10. formal adapter to AggregationControlApplicabilityDecision
~~~

# 11. Required authority rule

CA-04 必须保证：

~~~text
NONE
-> only from authoritative durable control NONE

APPLIES
-> only from exact current latched control
   plus authoritative control-application / terminalization provenance

LATE_NOOP
-> only from exact current latched control
   plus authoritative proof that IU7 classified the control as
   ALREADY_TERMINAL / late no-op

UNKNOWN
-> missing / ambiguous / conflicting / stale provenance
~~~

禁止：

~~~text
latched control exists -> blindly APPLIES
all Steps terminal -> blindly LATE_NOOP
latched_at > max(step.finished_at) -> automatically LATE_NOOP
caller boolean -> applicability
caller hand-built decision -> aggregation authority
~~~

# 12. Crash-safe requirement

The key missing property is not merely a helper function.

The following must survive restart：

~~~text
exact execution_id
exact signal identity
exact applicability outcome
provenance / revision
writer recovery epoch or equivalent stale-writer protection
~~~

A restart must be able to reproduce the same applicability decision or fail UNKNOWN.

No silent fallback.

# 13. Other readiness seams reviewed

The following are implementation wiring requirements, not new blockers.

## 13.1 Terminal Step completion wiring

Formal Implementation still needs to connect：

~~~text
SequentialStepScheduler
↓
TerminalStepCompletionCoordinator
~~~

for SKIP / required-upstream remainder closure.

Authority already frozen：YES。

Result：not a readiness blocker。

## 13.2 Running Step finalization wiring

Formal Implementation needs to connect：

~~~text
IU6 StepReliabilityRunResult / recovered result
↓
RunningStepCompletionCoordinator
↓
ExecutionLifecycleService.finish_step
~~~

Authority already frozen：YES。

Result：not a readiness blocker。

## 13.3 Evidence projection wiring

Formal Implementation needs：

~~~text
project_ca01_evidence_inputs(...)
~~~

This authoritative producer already exists.

Result：not a readiness blocker。

## 13.4 Durable control read wiring

IU9 already provides：

~~~text
DurableTerminalControlStore.read_latched(...)
-> DurableControlReadDecision
~~~

Result：not a readiness blocker。

## 13.5 Control-path Tool journal wiring

CA-03 provides：

~~~text
DurableControlTerminalToolEvidenceReader
↓
StepAttemptCursorRecord.current_attempt
↓
exact durable Tool journal
~~~

Result：not a readiness blocker。

## 13.6 Canonical projection wiring

CA-03 provides：

~~~text
CanonicalExecutionResultProjector
ExecutionAggregator
~~~

Result：not a readiness blocker。

# 14. Canonical contract review

Current Canonical amendment：

~~~text
ExecutionResult schema_version = 1.1.0
workflow_results[] added
workflow_result retained
~~~

Compatibility：

~~~text
0 Workflow
-> workflow_result=None
-> workflow_results=[]

1 Workflow
-> both represent exact same item

>1 Workflow
-> workflow_result=None
-> workflow_results=lossless ordered list
~~~

Canonical Registry and Schema Registry are aligned.

Result：PASS。

# 15. Replay / recovery review

Current chain already preserves：

~~~text
terminal Step evidence
exact final owner result
Tool logical journal
control terminal Step evidence
durable control latch
current Step attempt cursor
existing execution terminal lifecycle
~~~

Natural terminal replay：

~~~text
computed status == persisted status
-> READY_EXISTING_TERMINAL
-> deterministic Canonical result
~~~

Control-terminal Tool journal replay is also bound to exact current attempt.

Only control applicability itself lacks crash-safe authority.

Result：

~~~text
PASS except B-M5-IU10-009
~~~

# 16. Boundary review

Current CA chain still does not enter：

~~~text
M6 result/business validation
M7 response generation
M8 state/memory mutation
new planning
capability substitution
Registry latest-version selection
business truth inference
medical truth inference
~~~

Result：PASS。

# 17. Verification baseline

Latest CA-03 verified code：

~~~text
289abb07c9a1d1fd08abf0ef66717b54433aad4a
~~~

Verification：

~~~text
python -m pytest tests -q
-> 936 passed

python -m mypy runtime tests
-> Success: no issues found in 215 source files

python -m ruff check runtime tests
-> All checks passed

python -m ruff format --check runtime tests
-> 215 files already formatted
~~~

The later CA-03 closure commit is documentation-only relative to the verified code.

Result：PASS。

# 18. Formal Implementation scope after CA-04

After B-M5-IU10-009 is closed and Re-Review passes, Formal Implementation may wire：

~~~text
scheduler
-> TerminalStepCompletionCoordinator

IU6 finalization
-> RunningStepCompletionCoordinator

durable control store
-> DurableControlReadDecision

durable control applicability authority
-> AggregationControlApplicabilityDecision

CA-02 evidence
-> project_ca01_evidence_inputs

all terminal / exact control authority
-> ExecutionAggregationAuthority

READY_NATURAL
-> ExecutionLifecycleService.finish_execution
-> re-evaluate

READY_EXISTING_TERMINAL
-> CanonicalExecutionResultProjector

-> ExecutionResult
-> M6 boundary only
~~~

Formal Implementation must not use the IU1 skeleton `ExecutionResultProjector` as the IU10 result authority.

# 19. Final decision

~~~text
M5-IU10 IMPLEMENTATION READINESS RE-REVIEW = BLOCKED
M5-IU10 IMPLEMENTATION READINESS = NOT_READY

ORIGINAL BLOCKERS = 0
NEW BLOCKERS = 1

B-M5-IU10-009
DURABLE_CONTROL_APPLICABILITY_AUTHORITY_MISSING
= OPEN

FORMAL IMPLEMENTATION = NOT AUTHORIZED

NEXT REQUIRED =
CA-M5-IU10-04
Durable Control Applicability Authority

M5 = IN PROGRESS
~~~

The four completed amendments remain PASSED; this Re-Review does not reopen CA-00..03.

It only records that their cumulative composition still lacks one authority required by CA-01's own frozen boundary.
