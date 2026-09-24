# CA-M5-IU10-04 Durable Control Applicability Authority V1.0

> Parent：M5-IU10 — Step 12 Execution Aggregation
>
> Trigger：M5-IU10 Implementation Readiness Re-Review
>
> Target blocker：
>
> ~~~text
> B-M5-IU10-009
> DURABLE_CONTROL_APPLICABILITY_AUTHORITY_MISSING
> ~~~

# 1. Amendment goal

CA-01 已冻结：

~~~text
AggregationControlApplicabilityStatus

NONE
APPLIES
LATE_NOOP
UNKNOWN
~~~

但在 CA-00～03 完成后，Formal Aggregator 仍然需要调用方直接提供：

~~~text
AggregationControlApplicabilityDecision
~~~

CA-04 的唯一目标是建立：

~~~text
IU7 authoritative control application
+
IU9 durable control latch
+
IU9 recovery epoch
        ↓
crash-safe applicability evidence
        ↓
DurableAggregationControlAuthority
        ↓
AggregationControlAuthoritySnapshot
        ↓
ExecutionAggregator
~~~

# 2. Non-goals

CA-04 不负责：

~~~text
control priority
M2 policy recomputation
new CANCEL/PREEMPT decision
interrupt execution
control lifecycle semantics redesign
Execution plan_status matrix
Step aggregation evidence
Canonical result field projection
M6 validation
M7 response
M8 state/memory
~~~

CA-04 不创建第二套 control signal/latch。

# 3. Existing authority reused

现有 IU7 / IU9 authority：

~~~text
ExecutionControlSignal
ObservedExecutionControl
LatchedExecutionControl
ExecutionControlApplication
ExecutionControlDisposition
DurableTerminalControlStore
DurableControlReadDecision
ExecutionRecoveryClaim
RecoveryClaimAuthority
RecoveryEpochValidationStatus
~~~

CA-04 只持久化：

~~~text
这个 exact durable latch 在 aggregation 时属于
APPLIES 还是 LATE_NOOP
~~~

不复制 durable control latch 本身。

# 4. Durable applicability evidence

新增：

~~~text
ControlApplicabilityEvidenceStatus
APPLIES
LATE_NOOP
~~~

NONE 不单独写 record，因为它必须由 DurableTerminalControlStore 的 NONE 证明。
UNKNOWN 是 fail-closed 结果，也不作为确认事实持久化。

# 5. Durable record

新增：

~~~text
DurableControlApplicabilityRecord

execution_id
latched_control
status
source_disposition
source_reason_codes
source_nonterminal_step_ids_at_latch
source_affected_step_ids
source_running_step_id
source_preserve_running_step_result
revision
recorded_at
writer_recovery_epoch
~~~

冻结映射：

~~~text
APPLIES
<-> READY_TO_TERMINALIZE

LATE_NOOP
<-> ALREADY_TERMINAL
~~~

禁止其他映射。

# 6. No timestamp inference

禁止：

~~~text
latched_at > last_step.finished_at
-> LATE_NOOP

all Steps terminal
-> LATE_NOOP
~~~

因为 current lifecycle state 不等于 historical control applicability provenance。

同样的“当前全部 Step terminal”可能来自：

~~~text
A. control 已经真正 APPLIES 并完成 terminalization
B. control 到达时工作已经自然完成，因此 LATE_NOOP
~~~

必须使用 IU7 当时的 authoritative application disposition 区分。

# 7. Authoritative write source

只允许两个 final IU7 disposition 写 durable applicability：

~~~text
READY_TO_TERMINALIZE
-> APPLIES

ALREADY_TERMINAL
-> LATE_NOOP
~~~

以下不得写为确认 applicability：

~~~text
NO_CONTROL
WAITING_IN_FLIGHT
CONFLICT
UNKNOWN
~~~

# 8. Recovery fencing

写入必须携带 ExecutionRecoveryClaim，并验证：

~~~text
required_claim.execution_id == latch target execution_id
RecoveryClaimAuthority.validate_current(claim)
~~~

只有 CURRENT 可以写。

~~~text
STALE
-> CONFLICT

UNKNOWN
-> UNKNOWN
~~~

Production adapter 必须把 recovery-epoch validation 和 applicability mutation 放在同一个 durable transaction / CAS boundary。

参考 in-memory store 只用于 contract verification，不宣称进程 crash durability。

# 9. Immutable first applicability

同一 execution 的 applicability 是 first-immutable。

~~~text
first APPLIES / LATE_NOOP
-> RECORDED

exact semantic replay
-> ALREADY_CURRENT

same latch + different applicability
-> CONFLICT

different latch
-> CONFLICT
~~~

特别是：

~~~text
APPLIES
不能被后续 execution 已 terminal 时重新评估出的
ALREADY_TERMINAL 覆盖为 LATE_NOOP
~~~

# 10. Write-before-lifecycle ordering

ExecutionControlCoordinator 增加可注入：

~~~text
ControlApplicabilityRecorder
~~~

对于 READY_TO_TERMINALIZE / ALREADY_TERMINAL，冻结顺序：

~~~text
exact final IU7 application
↓
persist durable applicability
↓
RECORDED / ALREADY_CURRENT only
↓
ExecutionControlLifecycleService.terminalize(...)
~~~

applicability persistence failure 时 fail closed，不执行新的 lifecycle mutation。

# 11. Crash window

关键窗口：

~~~text
READY_TO_TERMINALIZE
↓
APPLIES durably recorded
↓
process crash
↓
control lifecycle mutation 尚未完成
~~~

恢复后：

~~~text
durable latch = exact signal
durable applicability = APPLIES
execution lifecycle still RUNNING
↓
Aggregation Authority
-> AGGREGATION_CONTROL_TERMINALIZATION_REQUIRED
~~~

不会错误进入 natural aggregation。

若 lifecycle 已经持久化 CANCELLED/PREEMPTED 后 crash，重启仍可由 APPLIES + exact terminal lifecycle 进入 READY_EXISTING_TERMINAL。

# 12. LATE_NOOP crash safety

IU7 已判 ALREADY_TERMINAL 时：

~~~text
persist LATE_NOOP
↓
lifecycle no-op
~~~

重启后 exact durable latch + exact durable LATE_NOOP 可以继续 natural / existing-terminal aggregation，不会因为 latch 存在永久卡死。

# 12.1 Control-terminal exact replay

`ALREADY_TERMINAL` 不能被机械地解释成新的 LATE_NOOP。

存在另一种合法来源：

~~~text
control previously APPLIES
↓
CANCEL/PREEMPT lifecycle already persisted
↓
same exact control is replayed
↓
IU7 current application = ALREADY_TERMINAL
~~~

如果此时重新写 LATE_NOOP，会伪造历史并与已持久化 APPLIES 冲突。

因此当：

~~~text
application = ALREADY_TERMINAL
+
current execution status = CANCELLED / PREEMPTED
~~~

CA-04 将其视为：

~~~text
control-terminal replay
~~~

不创建新的 LATE_NOOP evidence，不覆盖既有 APPLIES。

对于 pre-CA04 legacy execution 如果 APPLIES evidence 缺失，也不允许根据当前 control-terminal lifecycle 反向补写历史；aggregation 保持 UNKNOWN/fail closed。

# 13. Durable read authority

新增：

~~~text
DurableAggregationControlAuthority
~~~

同时读取：

~~~text
DurableTerminalControlStore
DurableControlApplicabilityStore
~~~

输出：

~~~text
AggregationControlAuthoritySnapshot
- control
- applicability
~~~

# 14. NONE mapping

只有：

~~~text
durable control = NONE
+
durable applicability evidence = NONE
~~~

才能输出 NONE。

如果 control NONE 但 applicability record 存在：

~~~text
UNKNOWN
AGGREGATION_CONTROL_APPLICABILITY_ORPHAN_EVIDENCE
~~~

# 15. LATCHED mapping

~~~text
control = LATCHED + applicability missing
-> UNKNOWN

control = LATCHED + applicability read unknown
-> UNKNOWN

control = LATCHED + record.latch != durable latch
-> UNKNOWN

control = LATCHED + exact APPLIES record
-> APPLIES

control = LATCHED + exact LATE_NOOP record
-> LATE_NOOP
~~~

禁止 latched -> 默认 APPLIES。

# 16. Formal Aggregator boundary amendment

CA-03 旧接口：

~~~text
ExecutionAggregator.aggregate(
    approved_plan,
    prepared,
    control,
    control_applicability,
    at,
)
~~~

CA-04 改为：

~~~text
ExecutionAggregator(
    ...
    control_authority: AggregationControlAuthority
)

aggregate(
    approved_plan,
    prepared,
    at,
)
~~~

Aggregator 内部调用：

~~~text
control_authority.resolve(execution_id)
↓
exact control snapshot
↓
CA-01 ExecutionAggregationAuthority
~~~

正式入口不再接收 caller 提供的 control / control_applicability。

# 17. Low-level projector boundary

CanonicalExecutionResultProjector 仍保留低层 projection seam，接收已经由 Aggregator / CA-01 授权的 control 与 applicability。

Formal Implementation 不得绕过 ExecutionAggregator 直接用 hand-built applicability 发布 Canonical result。

# 18. Durable provenance retained

record 保留：

~~~text
source_disposition
source_reason_codes
nonterminal Steps at latch
affected Steps
running Step identity
preserve-running-result flag
~~~

不复制：

~~~text
HierarchicalInterruptSummary
InterruptOutcome
provider-specific stop proof
~~~

这些仍属于 IU7/IU9 truth boundary。

# 19. Exact replay

相同 execution、latch、status、source disposition、source reason、source Step provenance 重复写：

~~~text
ALREADY_CURRENT
revision unchanged
original recorded_at unchanged
~~~

# 20. Files

~~~text
runtime/execution/control_applicability.py
runtime/execution/control_runtime.py
runtime/execution/aggregation_result.py
runtime/execution/__init__.py
tests/test_m5_iu10_ca03_canonical_result_projection.py
tests/test_m5_iu10_ca04_control_applicability.py
~~~

# 21. Behavioral gates

~~~text
1. durable control NONE + no applicability -> NONE
2. latched control + no applicability -> UNKNOWN
3. READY_TO_TERMINALIZE -> durable APPLIES
4. ALREADY_TERMINAL -> durable LATE_NOOP
5. APPLIES survives authority recreation
6. LATE_NOOP survives authority recreation
7. exact replay -> ALREADY_CURRENT
8. exact replay keeps revision
9. exact replay keeps original recorded_at
10. APPLIES cannot be overwritten by later LATE_NOOP
11. stale recovery epoch cannot write
12. non-final control application cannot write
13. orphan applicability without durable latch -> UNKNOWN
14. applicability must bind exact durable latch
15. IU7 source Step provenance retained
16. control runtime records before lifecycle mutation
17. Aggregator no longer accepts caller control
18. Aggregator no longer accepts caller control_applicability
19. no timestamp-based LATE_NOOP inference
20. control-terminal exact replay is not reclassified as LATE_NOOP
21. no M6/M7/M8 authority introduced
~~~

# 22. Blocker impact

~~~text
B-M5-IU10-009
DURABLE_CONTROL_APPLICABILITY_AUTHORITY_MISSING
= FIX_IMPLEMENTED_PENDING_REVIEW_AND_GATES
~~~

Original blockers remain：

~~~text
B-M5-IU10-001..008 = CLOSED
~~~

# 23. Current status

~~~text
CA-M5-IU10-04 = CODE COMPLETE
CA-M5-IU10-04 INDEPENDENT REVIEW = PASSED
CA-M5-IU10-04 VERIFICATION = PENDING

B-M5-IU10-009 = FIX_IMPLEMENTED_PENDING_GATES

M5-IU10 IMPLEMENTATION READINESS = NOT_READY
FORMAL IMPLEMENTATION = NOT AUTHORIZED
M5 = IN PROGRESS
~~~

Next required：

~~~text
CA-M5-IU10-04 Independent Review
-> targeted fixes if findings exist
-> four verification gates
-> CA-M5-IU10-04 Verification Closure
-> M5-IU10 Implementation Readiness Re-Review
~~~


# 24. Independent Review Closure

Independent Review 累计检查：

~~~text
durable applicability identity
IU7 source disposition mapping
recovery epoch fencing
immutable replay
control-latch exact binding
control-runtime write ordering
natural aggregation race
control-terminal replay
formal Aggregator authority seam
M6/M7/M8 boundary
~~~

Review findings：

~~~text
F-M5-IU10-CA04-001
NATURAL_TERMINAL_RECHECK_REUSED_STALE_CONTROL_SNAPSHOT
= CLOSED
~~~

原实现只在 aggregate() 开始时 resolve control authority。

竞态：

~~~text
initial durable control = NONE
↓
all Steps terminal
↓
READY_NATURAL
↓
natural finish_execution(...)
↓
期间 control 到达并形成 durable LATE_NOOP / APPLIES truth
↓
如果继续复用旧 NONE snapshot
-> terminal replay 绕过最新 control authority
~~~

修复：

~~~text
finish_execution(...)
↓
重新 DurableAggregationControlAuthority.resolve(...)
↓
重新 CA-02 evidence projection
↓
重新 CA-01 aggregation evaluation
~~~

并增加行为 gate：

~~~text
first resolve = NONE
second resolve = exact LATE_NOOP
resolve_count == 2
terminal replay remains deterministic
~~~

---

~~~text
F-M5-IU10-CA04-002
REFERENCE_STORE_RECOVERY_EPOCH_CHECK_NOT_AT_MUTATION_BOUNDARY
= CLOSED
~~~

原参考 store 先：

~~~text
await validate_current(claim)
~~~

再进入 applicability store lock。

两者之间理论上允许 recovery owner takeover。

修复为与 IU9 reference durable evidence store 一致：

~~~text
applicability store mutation lock
↓
InMemoryRecoveryClaimAuthority._validate_current_sync(claim)
↓
same critical section mutation
~~~

因此 reference implementation 也能证明 stale writer 不在 epoch 校验与写入之间穿透。

Production adapter 仍必须使用真实 durable transaction / CAS。

---

~~~text
F-M5-IU10-CA04-003
CONTROL_TERMINAL_REPLAY_COULD_BE_RECLASSIFIED_AS_LATE_NOOP
= CLOSED
~~~

同一个已经 APPLIES 的 CANCEL/PREEMPT，在 execution 已经持久化为：

~~~text
CANCELLED / PREEMPTED
~~~

后再次 replay，IU7 当前视角可以得到：

~~~text
ALREADY_TERMINAL
~~~

但这不代表历史上该 control 是 LATE_NOOP。

修复：

~~~text
application = ALREADY_TERMINAL
+
current execution = CANCELLED / PREEMPTED
-> control-terminal replay
-> do not create LATE_NOOP
-> preserve existing APPLIES history
~~~

对于没有 CA-04 applicability evidence 的 legacy control-terminal execution：

~~~text
do not backfill guessed history
-> aggregation remains UNKNOWN / fail closed
~~~

---

Review also confirms：

~~~text
NONE only comes from durable control absence
read uncertainty never collapses to NONE
latched control without applicability evidence -> UNKNOWN
APPLIES/LATE_NOOP bind exact immutable latch
non-final IU7 dispositions cannot become applicability truth
source Step provenance is retained
APPLIES cannot be overwritten by later LATE_NOOP
Formal ExecutionAggregator no longer accepts caller control
Formal ExecutionAggregator no longer accepts caller control_applicability
no timestamp-based LATE_NOOP inference
no Registry lookup / capability invoke / retry / resume / replan
no M6 / M7 / M8 authority
~~~

Independent Review decision：

~~~text
CA-M5-IU10-04 = CODE COMPLETE
CA-M5-IU10-04 INDEPENDENT REVIEW = PASSED
CA-M5-IU10-04 VERIFICATION = PENDING

B-M5-IU10-009
DURABLE_CONTROL_APPLICABILITY_AUTHORITY_MISSING
= FIX_IMPLEMENTED_PENDING_GATES

NEW CA-04 SEMANTIC BLOCKER = NONE

M5-IU10 IMPLEMENTATION READINESS = NOT_READY
FORMAL IMPLEMENTATION = NOT AUTHORIZED
M5 = IN PROGRESS
~~~

下一步只允许执行四项 Verification Gate：

~~~text
python -m pytest tests -q
python -m mypy runtime tests
python -m ruff check runtime tests
python -m ruff format --check runtime tests
~~~

四项全绿之前：

~~~text
CA-M5-IU10-04 != PASSED
B-M5-IU10-009 != CLOSED
M5-IU10 != READY
FORMAL IMPLEMENTATION != AUTHORIZED
~~~
