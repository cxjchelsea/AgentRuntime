# M5-IU10 Execution Aggregation 实现设计 V1.0

> Mapping：M5-IU10 = M5 V2.0 Step 12 — Execution Aggregation。
>
> Baseline：M5-IU1～IU9 = PASSED。
>
> Base commit：M5-IU9 Closure baseline ee7b29de0416cbf681df8de4cf9ae326c5185fb5。
>
> Goal：把已经获得 authoritative execution / step terminal facts 的 M5 执行，确定性地聚合为 Canonical ExecutionResult，同时保持 Tool / Skill / Workflow 原始执行真值，不越界进入 M6 Business Validation。

---

# 1. IU10 正式目标

Step 12 原始定义：

~~~text
all Steps complete / fail / interrupt
        ↓
ExecutionAggregator
        ↓
required vs optional semantics
Tool / Skill / Workflow facts
Cancellation / Preemption
        ↓
ExecutionResult
~~~

IU10 只回答：

~~~text
这个 ApprovedActionPlan 在执行层最终发生了什么？
~~~

IU10 不回答：

~~~text
业务目标是否真正达成
Tool 成功是否足以证明外部世界目标达成
哪些事实可以告诉用户
如何回复用户
应该如何更新长期状态/记忆
~~~

这些仍属于 M6 / M7 / M8。

# 2. 当前基础

当前已经具备：

~~~text
ApprovedActionPlan
ActionStep.optional
PreparedExecution
StepLifecycleSnapshot
ExecutionLifecycleService
ExecutionControlLifecycleService
StepAttemptObservation
ToolInvocationJournalEntry
M5SkillResult
M5WorkflowResult
M5ToolResult
Durable Tool journal / recovery evidence
Durable terminal control latch
ExecutionResult Canonical contract
ExecutionResultProjector skeleton
~~~

IU1 中的 ExecutionResultProjector 只是骨架，目前把：

~~~text
skill_results
workflow_result
tool_results
business_outputs
execution_events
state_observations
errors
cancellation
quality
~~~

全部投为 None。

因此它不能直接作为 IU10 Formal Aggregator。

# 3. Aggregation truth boundary

必须保持：

~~~text
ExecutionResult != ValidatedResult != Business Truth

Tool SUCCESS != business success
Skill SUCCESS != verified business success
Workflow COMPLETED != external-world success
PARTIAL_SUCCESS != M6 PARTIALLY_VALIDATED
FAILED != business failure interpretation
~~~

IU10 只能复制、归并、排序、结构化 M5 已经拥有的 authoritative execution facts。

禁止：

~~~text
根据常识把 UNKNOWN 改成 FAILED
根据 Tool SUCCESS 推断业务成功
根据 response wording 补结果
根据最新 Registry 重解释旧能力
重新执行 / 重试 / resume
重新规划
调用 M6
~~~

# 4. Aggregation 资格与执行终态分离

自然执行不能要求进入 Aggregator 前已经是 SUCCESS / FAILED，因为自然 plan_status 本来就应由 IU10 决定。

正确顺序：

~~~text
ApprovedActionPlan
+
all Step authoritative terminal lifecycle
+
required aggregation evidence
        ↓
ExecutionAggregationDecision
        ↓
natural plan_status
        ↓
existing ExecutionLifecycleService.finish_execution(...)
        ↓
authoritative terminal ExecutionRecord
        ↓
ExecutionResult projection
~~~

控制终态例外：

~~~text
CANCEL / PREEMPT
↓
IU7 control authority
↓
ExecutionControlLifecycleService
↓
execution already CANCELLED / PREEMPTED
↓
IU10 validates + preserves
~~~

IU10 不得覆盖 IU7 的终态。

# 5. 非终态恢复状态不能强行聚合

以下都不是新的 ExecutionPlanStatus：

~~~text
Workflow WAITING
Recovery WAIT_RECONCILIATION
Recovery UNKNOWN_BLOCKED
Step RUNNING
Step PENDING
unresolved Tool UNKNOWN
~~~

它们表示：

~~~text
ExecutionResult 尚不具备最终聚合资格
~~~

而不是：

~~~text
plan_status = FAILED
~~~

因此 V1 不新增 WAITING / UNKNOWN plan_status。

# 6. Aggregation Eligibility

建议新增：

~~~text
ExecutionAggregationEligibilityStatus

READY_NATURAL
READY_EXISTING_TERMINAL
WAITING
BLOCKED_UNKNOWN
~~~

以及：

~~~text
ExecutionAggregationEligibilityDecision
- status
- reason_codes
- existing_plan_status?
~~~

规则：

~~~text
PENDING / RUNNING Step
-> WAITING

durable terminal control exists
but IU7 lifecycle not yet terminal
-> BLOCKED_UNKNOWN / CONTROL_TERMINALIZATION_REQUIRED

execution RUNNING
+ all Steps terminal
+ no unresolved control barrier
+ aggregation evidence complete
-> READY_NATURAL

execution already terminal
+ evidence consistent
-> READY_EXISTING_TERMINAL
~~~

terminal status 与 evidence 不一致：

~~~text
BLOCKED_UNKNOWN
~~~

不得覆盖旧终态。

# 7. Required / Optional authority

唯一来源：

~~~text
ApprovedActionPlan.steps[].optional
~~~

冻结：

~~~text
optional is True
-> OPTIONAL

optional is False / None
-> REQUIRED
~~~

IU10 不读取 Domain 自定义标签猜 required/optional。

# 8. Natural plan_status 初步矩阵

最终由 CA-M5-IU10-01 冻结。

建议：

~~~text
any REQUIRED TIMEOUT
-> TIMEOUT

any REQUIRED FAILED / SKIPPED
and no required TIMEOUT
-> FAILED

REQUIRED CANCELLED / PREEMPTED
while execution still RUNNING
-> BLOCKED_UNKNOWN

all REQUIRED SUCCESS
+ all OPTIONAL SUCCESS
-> SUCCESS

all REQUIRED SUCCESS
+ at least one OPTIONAL FAILED / TIMEOUT / SKIPPED
+ at least one Step SUCCESS
-> PARTIAL_SUCCESS
~~~

如果计划没有 REQUIRED Step：

~~~text
all SUCCESS
-> SUCCESS

some SUCCESS + some FAILED/TIMEOUT/SKIPPED
-> PARTIAL_SUCCESS

no SUCCESS:
  any TIMEOUT -> TIMEOUT
  otherwise -> FAILED
~~~

IU7 已 authoritative terminalize 时：

~~~text
CANCELLED -> preserve CANCELLED
PREEMPTED -> preserve PREEMPTED
~~~

不得由 Step success/failure 覆盖。

# 9. UNKNOWN / WAITING evidence 与 terminal Step 不兼容

如果 Step lifecycle 已 terminal，但 final aggregation evidence 仍显示：

~~~text
StepAttemptStatus.UNKNOWN
Workflow WAITING
Workflow RUNNING
Tool UNKNOWN not reconciled
untrusted success
~~~

则：

~~~text
BLOCKED_UNKNOWN
~~~

IU10 不得为了输出 ExecutionResult 而丢弃矛盾证据。

# 10. 核心 blocker：缺少 crash-safe rich aggregation evidence

当前 StepLifecycleSnapshot 只保留：

~~~text
step id
action
status
skill/workflow id
tool_call_ids
output
error
retry_count
timestamps
~~~

但正式 ExecutionResult 还需要：

~~~text
exact Skill result
exact Workflow result
exact Tool journal/result
business outputs
capability events
final attempt provenance
terminal reason
validation observations
~~~

这些在 live path 中存在于：

~~~text
StepAttemptObservation
StepCapabilityExecutionOutcome
ToolInvocationJournalEntry
~~~

但没有与 Step terminalization 一起 crash-safe 保存。

危险窗口：

~~~text
final Skill/Workflow/Tool observation exists
↓
Step lifecycle terminal persisted
↓
process crashes before ExecutionResult
↓
IU9 sees terminal Step
↓
rich owner/business evidence no longer recoverable
~~~

因此：

~~~text
live aggregation succeeds
!= crash-replay aggregation deterministic
~~~

# 11. StepAggregationEvidence

建议 CA-M5-IU10-02 冻结：

~~~text
StepAggregationEvidence

schema_version
execution_id
step_execution_id
step_id

terminalization_kind
terminal_step_status
terminal_reason_codes[]

final_attempt_number?

execution_owner?
owner_capability_id?
owner_capability_version?

skill_result?
workflow_result?

tool_journal[]
business_outputs[]
capability_events[]

observed_at
~~~

terminalization_kind：

~~~text
ATTEMPT_FINALIZED
SCHEDULER_SKIPPED
CONTROL_TERMINALIZED
~~~

规则：

~~~text
one exact terminal Step
-> at most one immutable aggregation evidence record

same identity + same payload
-> ALREADY_CURRENT

same identity + different payload
-> CONFLICT / UNKNOWN
~~~

# 12. Aggregation evidence 与 Step lifecycle 原子边界

IU10 不能留下：

~~~text
Step terminal lifecycle committed
but aggregation evidence silently disappeared
~~~

优选方案：

~~~text
StepAggregationEvidence
作为 Step terminal observation 的 Core-owned recovery-safe projection
与 StepLifecycleSnapshot terminal payload 一起持久化
~~~

即扩展：

~~~text
StepLifecycleSnapshot
+ aggregation_evidence?
~~~

并同步进入：

~~~text
ExecutionRecord.step_results
ExecutionRecoverySnapshot
~~~

这样 IU9 restart 后仍可重建 deterministic aggregation evidence。

不得把 credential / process handle / live Runtime object 放入 evidence。

# 13. Scheduler SKIP evidence

Scheduler SKIP 没有 Skill/Workflow attempt。

必须形成：

~~~text
terminalization_kind = SCHEDULER_SKIPPED
terminal_reason_codes = exact StepScheduleDecision.reason_codes
~~~

不能只看到 Step status = SKIPPED 后再猜原因。

# 14. Control terminal evidence

CANCEL / PREEMPT 由 IU7 authority 决定。

控制终态必须绑定：

~~~text
terminalization_kind = CONTROL_TERMINALIZED
signal_type
signal_id
reason_code
source
observed_at
latched_at
~~~

聚合 cancellation/preemption 信息来自 durable exact control latch，而不是从 error 字符串反推。

# 15. Tool evidence

ToolResult 排序 / 去重必须来自 Core-owned Tool journal。

规则：

~~~text
plan Step order
-> final Step evidence order
-> Tool journal logical order
~~~

同一 tool_call_id：

~~~text
exact duplicate
-> one logical Tool result

different payload / provenance
-> CONFLICT / BLOCKED_UNKNOWN
~~~

不得按 tool_id 去重。

# 16. Skill result

每个 Skill owner Step 最终最多一个 final Skill result。

必须验证：

~~~text
step.skill_id
==
aggregation evidence owner_capability_id
==
M5SkillResult.skill_id
~~~

不一致：

~~~text
BLOCKED_UNKNOWN
~~~

skill_results 按 ApprovedPlan Step 顺序输出。

# 17. Workflow result cardinality blocker

当前 Canonical：

~~~text
workflow_result: dict | None
~~~

但 ApprovedActionPlan 允许多个 ActionStep，每个 Step 都可带 workflow_id，现有 validator 没有限制 one Workflow per execution。

因此合法计划可以：

~~~text
Workflow A
-> Workflow B
~~~

singular workflow_result 无法无损表达。

建议 CA-M5-IU10-03 做 backward-compatible amendment：

~~~text
ExecutionResult.workflow_results: list[dict] | None
~~~

同时保留旧字段 workflow_result：

~~~text
0 Workflow
-> workflow_result = None
-> workflow_results = []

1 Workflow
-> workflow_result = exact sole item
-> workflow_results = [same item]

>1 Workflow
-> workflow_result = None
-> workflow_results = all items in plan order
~~~

不删除旧字段。

# 18. Business outputs

只复制 M5 owner result / terminal evidence 中明确产生的 business outputs。

禁止：

~~~text
从 Tool data 猜 business output
从 action 名称生成 business output
从 Workflow COMPLETED 推断业务成功
~~~

# 19. execution_events

第一版只允许：

~~~text
A. authoritative lifecycle facts
B. capability_events already emitted by owner evidence
~~~

可根据确定性 timestamp 投影 lifecycle events。

禁止生成没有 source timestamp 的想象事件。

# 20. state_observations

V1 不从 Tool data / business output / action name 推导 state observation。

只有明确 source 才输出。

当前无正式 source：

~~~text
state_observations = []
~~~

# 21. errors

只从已有执行事实投影：

~~~text
Step.error
SkillResult.error
WorkflowResult.error
ToolResult.error_code / error_message
structural aggregation warnings/errors
~~~

如果 recoverable / retryable 没有 authoritative source：

~~~text
omit / null
~~~

不得猜 true/false。

# 22. timing

可确定性投影：

~~~text
started_at
finished_at
total_duration_ms
step_durations
tool_durations
~~~

时间缺失 / 倒退：

~~~text
BLOCKED_UNKNOWN
~~~

# 23. cancellation

仅当 authoritative IU7 control evidence 存在时输出。

至少：

~~~text
cancelled = true
signal_type
reason
source
signal_id
requested_at = signal.issued_at
observed_at
latched_at
~~~

PREEMPT 不重写成普通 CANCEL。

Natural TIMEOUT：

~~~text
plan_status = TIMEOUT
cancellation = None
~~~

除非另有真实 control evidence。

# 24. quality

quality 是 M5 execution-quality，不是 M6 truth-quality。

建议：

~~~text
schema_valid
plan_followed
tool_outputs_valid
degraded
warnings[]
~~~

不得包含 business_truth_valid / medical_truth_valid / response_claims_valid。

# 25. Natural lifecycle commit ownership

Aggregator 先产生：

~~~text
ExecutionAggregationDecision
- plan_status
- reason_codes
~~~

然后自然终态调用：

~~~text
ExecutionLifecycleService.finish_execution(...)
~~~

不得新写第二套 lifecycle mutation。

# 26. Existing terminal replay

支持 crash window：

~~~text
IU10 plan_status decided
↓
finish_execution persisted
↓
process crash before caller received ExecutionResult
~~~

恢复后：

~~~text
terminal lifecycle
+
durable StepAggregationEvidence
↓
recompute same decision
~~~

如果：

~~~text
computed status == persisted status
~~~

允许 deterministic result replay。

否则：

~~~text
BLOCKED_UNKNOWN
~~~

不得重写 terminal lifecycle。

# 27. Deterministic ordering

冻结：

~~~text
step_results -> ApprovedPlan Step order
skill_results -> owner Step order
workflow_results -> owner Step order
tool_results -> Step order + Tool journal logical order
business_outputs -> Step order + source order
errors -> Step order + source order
events -> timestamp + deterministic source tie-break
~~~

不得依赖线程完成顺序或 Registry/dict 偶然顺序。

# 28. Existing projector

现有 ExecutionResultProjector 属于 IU1 skeleton。

IU10 正式实现必须升级为 evidence-aware aggregation/projection，不能继续无条件输出大量 None。

最终兼容方式由 CA-M5-IU10-03 冻结。

# 29. Independent Design Review 新发现的前置闭环缺口

## 29.1 Scheduler decision 尚未形成 terminal Step lifecycle

现有 SequentialStepScheduler 可以返回：

~~~text
SKIP
BLOCKED / REQUIRED_PREVIOUS_STEP_NOT_SUCCESSFUL
~~~

但现有 ExecutionLifecycleManager 只允许：

~~~text
PENDING -> RUNNING
RUNNING -> terminal
~~~

没有：

~~~text
PENDING -> SKIPPED
~~~

的正式 authority。

因此会出现：

~~~text
required Step 1 = FAILED
Step 2 = PENDING
Scheduler = BLOCKED
Step 2 永远保持 PENDING
-> IU10 永远无法满足 all Steps terminal
~~~

这不能由 Aggregator 临时把 PENDING 当 SKIPPED。

## 29.2 Skill PARTIAL_SUCCESS 尚未形成 terminal Step lifecycle

当前：

~~~text
M5SkillResult.status = PARTIAL_SUCCESS
-> StepAttemptStatus.PARTIAL_SUCCESS
~~~

但 BasicStepFinalizationEvaluator 只映射：

~~~text
SUCCESS -> Step SUCCESS
FAILED -> Step FAILED
TIMEOUT -> Step TIMEOUT
~~~

PARTIAL_SUCCESS 当前返回：

~~~text
StepFinalizationDisposition.UNKNOWN
STEP_STATUS_REQUIRES_LATER_AUTHORITY
~~~

因此 partial Skill 也无法形成可聚合的 terminal Step。

初步建议由 CA-M5-IU10-00 冻结：

~~~text
PARTIAL_SUCCESS owner observation
-> Step lifecycle SUCCESS
-> aggregation evidence preserves PARTIAL_SUCCESS / degraded=true
~~~

这样不修改既有 StepExecutionStatus 枚举，同时 Plan Aggregator 可依据 rich evidence 产出 PARTIAL_SUCCESS。

该映射必须由 Controlled Amendment 正式评审后才能冻结。

# 30. Blockers

~~~text
B-M5-IU10-001
PLAN_STATUS_AND_AGGREGATION_ELIGIBILITY_NOT_FROZEN
= OPEN

B-M5-IU10-002
CRASH_SAFE_RICH_AGGREGATION_EVIDENCE_MISSING
= OPEN

B-M5-IU10-003
WORKFLOW_RESULT_CARDINALITY_CONTRACT_MISMATCH
= OPEN

B-M5-IU10-004
CONTROL_TERMINATION_PROVENANCE_NOT_BOUND_TO_RESULT
= OPEN

B-M5-IU10-005
SKELETON_EXECUTION_RESULT_PROJECTOR_INCOMPLETE
= OPEN

B-M5-IU10-006
AGGREGATION_REPLAY_DETERMINISM_NOT_FROZEN
= OPEN

B-M5-IU10-007
PENDING_STEP_TERMINALIZATION_AUTHORITY_MISSING
= OPEN

B-M5-IU10-008
PARTIAL_SUCCESS_STEP_FINALIZATION_AUTHORITY_MISSING
= OPEN
~~~

# 31. Controlled Amendment Plan

## CA-M5-IU10-00 Terminal Step Completion Boundary

冻结：

~~~text
scheduler SKIP -> exact PENDING Step terminalization authority
required-upstream-failure remainder handling
terminal reason preservation
no mutation for WAITING / UNKNOWN / unrelated BLOCKED
PARTIAL_SUCCESS owner observation terminal mapping
degradation evidence preservation
existing lifecycle/store mutation boundary reuse
~~~

必须保证：

~~~text
Aggregator never converts PENDING to SKIPPED by itself
Aggregator never converts PARTIAL_SUCCESS to SUCCESS/FAILED by itself
~~~

目标：

~~~text
B-M5-IU10-007
B-M5-IU10-008
~~~

## CA-M5-IU10-01 Aggregation Eligibility + Plan Status Authority

冻结：

~~~text
ExecutionAggregationEligibilityStatus
ExecutionAggregationEligibilityDecision
ExecutionAggregationDecision
required/optional authority
natural plan_status matrix
control precedence
existing terminal replay consistency
nonterminal WAIT/BLOCK behavior
~~~

目标：B-M5-IU10-001。

## CA-M5-IU10-02 Crash-Safe Terminal Step Aggregation Evidence

冻结：

~~~text
StepAggregationEvidence
terminalization_kind
final owner/result evidence
Tool journal projection
scheduler SKIP reason
control terminal reason
persistence / exact replay / conflict semantics
recovery-safe serialization
~~~

目标：

~~~text
B-M5-IU10-002
~~~

并支撑 B-M5-IU10-006。

## CA-M5-IU10-03 Canonical ExecutionResult Projection + Cardinality

冻结：

~~~text
multi-Workflow backward-compatible contract
ExecutionAggregator / formal projector
cancellation projection
quality projection
errors/events/timing projection
deterministic ordering
terminal replay
natural lifecycle commit integration
~~~

目标：

~~~text
B-M5-IU10-003
B-M5-IU10-004
B-M5-IU10-005
B-M5-IU10-006
~~~

# 32. Planned verification scenarios

至少覆盖：

~~~text
1. aggregation refuses PENDING / RUNNING Steps
2. terminal control barrier prevents natural aggregation
3. all required + optional success -> SUCCESS
4. required failure -> FAILED
5. required skipped -> FAILED
6. required timeout -> TIMEOUT
7. optional failed + required success -> PARTIAL_SUCCESS
8. optional skipped + required success -> PARTIAL_SUCCESS
9. no-required mixed success/non-success -> PARTIAL_SUCCESS
10. CANCEL preserves CANCELLED
11. PREEMPT preserves PREEMPTED
12. cancelled/preempted Step without control -> BLOCKED_UNKNOWN
13. terminal Step with UNKNOWN Tool evidence -> BLOCKED_UNKNOWN
14. terminal Step with Workflow WAITING -> BLOCKED_UNKNOWN
15. final Skill evidence survives reconstruction
16. final Workflow evidence survives reconstruction
17. final Tool journal survives reconstruction
18. scheduler SKIP reason survives reconstruction
19. control reason/source/id survives reconstruction
20. duplicate Tool exact replay dedupes only by tool_call_id
21. conflicting duplicate Tool evidence -> BLOCKED_UNKNOWN
22. multiple Workflow Steps are losslessly represented
23. business outputs only from explicit evidence
24. no synthetic state observation
25. errors do not invent recoverable/retryable
26. timing rejects missing/backward terminal timestamps
27. deterministic ordering independent of completion race
28. natural aggregation uses existing lifecycle service
29. existing terminal replay returns identical result
30. terminal status mismatch -> BLOCKED_UNKNOWN
31. no capability invoke / retry / resume during aggregation
32. no Registry lookup / capability substitution
33. no M6 invocation
34. no response generation
35. ExecutionResult validates Canonical schema
36. scheduler SKIP can terminalize exact PENDING Step without capability invoke
37. required upstream failure can deterministically close remaining unexecuted Steps
38. scheduler WAITING / UNKNOWN cannot terminalize PENDING Step
39. Skill PARTIAL_SUCCESS reaches terminal Step only through frozen completion authority
40. PARTIAL_SUCCESS degradation survives into plan aggregation
~~~

# 33. Readiness decision

~~~text
M5-IU10 IMPLEMENTATION DESIGN = COMPLETE
M5-IU10 INDEPENDENT DESIGN REVIEW = PASSED

M5-IU10 IMPLEMENTATION READINESS = NOT_READY

OPEN BLOCKERS =
B-M5-IU10-001
B-M5-IU10-002
B-M5-IU10-003
B-M5-IU10-004
B-M5-IU10-005
B-M5-IU10-006
B-M5-IU10-007
B-M5-IU10-008

FORMAL IMPLEMENTATION = NOT AUTHORIZED

M5 = IN PROGRESS
~~~

下一步：

~~~text
M5-IU10 Independent Design Review
-> CA-M5-IU10-00
Terminal Step Completion Boundary
-> CA-M5-IU10-01
Aggregation Eligibility + Plan Status Authority
~~~


# 34. Post-Readiness Amendment Record

> 本节为 CA-00～03 完成后的累计 Readiness Re-Review 修订记录。
> 第 30～33 节保留初始设计时点历史，不作为当前状态。

CA-M5-IU10-00～03 全部通过后，累计 Re-Review 发现：

~~~text
B-M5-IU10-009
DURABLE_CONTROL_APPLICABILITY_AUTHORITY_MISSING
~~~

根因：

~~~text
AggregationControlApplicabilityDecision 已存在
ExecutionAggregationAuthority 已消费

但 Formal Aggregator 仍可由 caller 直接提供：
control
control_applicability

且没有 crash-safe authoritative producer
区分：
APPLIES
vs
LATE_NOOP
~~~

因此追加：

~~~text
CA-M5-IU10-04
Durable Control Applicability Authority
~~~

CA-04 冻结：

~~~text
READY_TO_TERMINALIZE -> durable APPLIES
ALREADY_TERMINAL -> durable LATE_NOOP

exact durable latch binding
recovery-epoch fenced immutable evidence
write-before-control-lifecycle ordering
control-terminal replay does not rewrite APPLIES as LATE_NOOP
natural terminal commit后重新 resolve control authority
ExecutionAggregator internally resolves authoritative control snapshot
~~~

当前实施状态以 CA-M5-IU10-04 文档与最新 Readiness Re-Review 为准。
