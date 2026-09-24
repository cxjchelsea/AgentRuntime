# CA-M5-IU10-03 Canonical ExecutionResult Projection + Cardinality V1.0

> Parent：M5-IU10 — Step 12 Execution Aggregation
>
> Base：CA-M5-IU10-02 Verification Closure @ dc0c3400d6dfd61a1935e8a194f2d450a08248dd

# 1. Amendment goal

本 Controlled Amendment 负责关闭 M5-IU10 最后四个设计 blocker：

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

CA-03 不重新决定 Step/Plan 成败，不重新执行能力，也不进入 M6。
它只消费 CA-01 / CA-02 / IU7 / IU9 已经形成的 authoritative execution facts，
把它们确定性投影为 Canonical ExecutionResult。

# 2. Authority chain

正式链路冻结为：

~~~text
ApprovedActionPlan
+
PreparedExecution terminal lifecycle
+
CA-02 StepAggregationEvidence
+
IU7/IU9 durable control provenance
        ↓
project_ca01_evidence_inputs(...)
        ↓
ExecutionAggregationAuthority.evaluate(...)
        ↓
READY_NATURAL / READY_EXISTING_TERMINAL
        ↓
ExecutionAggregator
        ↓
[READY_NATURAL only]
ExecutionLifecycleService.finish_execution(...)
        ↓
CA-01 re-evaluation
        ↓
READY_EXISTING_TERMINAL
        ↓
CanonicalExecutionResultProjector
        ↓
Canonical ExecutionResult
~~~

禁止 CA-03：

~~~text
自行重算 plan_status
自行把 PENDING 当 SKIPPED
自行解释 PARTIAL_SUCCESS
自行查 Registry 最新版本
重新 invoke Tool / Skill / Workflow
retry / resume / replan
进入 M6/M7/M8
~~~

# 3. Canonical contract cardinality amendment

现有 Canonical ExecutionResult 只有：

~~~text
workflow_result: dict | None
~~~

但 ApprovedActionPlan 合法允许多个 Workflow-owned Step。

因此增加 backward-compatible additive field：

~~~text
EXECUTION_RESULT_SCHEMA_VERSION = 1.1.0

ExecutionResult
+ workflow_results: list[dict] | None
~~~

保留 legacy：

~~~text
workflow_result: dict | None
~~~

冻结兼容规则：

~~~text
0 Workflow result
-> workflow_result = None
-> workflow_results = []

1 Workflow result
-> workflow_result = exact sole item
-> workflow_results = [same item]

>1 Workflow results
-> workflow_result = None
-> workflow_results = all exact items in ApprovedPlan Step order
~~~

不允许 first-wins / last-wins。

# 4. Why ExecutionResult schema becomes 1.1.0

这是 additive Canonical contract amendment，而不是全局 Canonical Registry 重写。

沿用 M4 Planning Contract 已有做法：

~~~text
global SCHEMA_VERSION remains 1.0.0
ExecutionResult default schema_version = 1.1.0
~~~

旧字段未删除，已有消费者仍可继续读取 workflow_result。

# 5. Formal projector

新增：

~~~text
CanonicalExecutionResultProjector
~~~

IU1 的 ExecutionResultProjector 保留为 skeleton/backward compatibility，不把它偷偷改造成第二套 aggregation authority。

正式 CA-03 path 必须使用 evidence-aware projector。

Projector 只接受：

~~~text
ExecutionAggregationEligibilityStatus.READY_EXISTING_TERMINAL
~~~

且必须有 exact ExecutionAggregationDecision。

~~~text
READY_NATURAL
~~~

只能由 ExecutionAggregator 消费，用于先调用既有
ExecutionLifecycleService.finish_execution(...) 提交终态；
提交后重新执行 CA-02 + CA-01，只有得到 READY_EXISTING_TERMINAL
才能进入 Canonical projector。这样不会在 durable terminal commit 之前发布结果。

# 6. Projector independent fail-closed checks

即使调用方传入一个 READY decision，Projector 仍独立检查：

~~~text
execution_id
plan_id
request_id
terminal plan status
execution timing
ApprovedPlan Step order
unique Step ids
CA-02 evidence readiness == READY
~~~

任何不一致都 fail closed。

Projector 不信任调用方手工构造的“READY”作为跳过 CA-02 evidence 校验的方式。

# 7. Step results

~~~text
step_results
-> ApprovedActionPlan.steps exact order
~~~

字段只来自 terminal StepLifecycleSnapshot：

~~~text
step_execution_id
step_id
action
status
skill_id
workflow_id
tool_call_ids
output
error
retry_count
started_at
finished_at
~~~

不从业务输出反推 Step status。

# 8. Skill results

每个 ATTEMPT_FINALIZED Skill-owner Step：

~~~text
evidence.skill_result
-> skill_results
~~~

顺序：

~~~text
ApprovedPlan owner Step order
~~~

CA-02 已负责验证：

~~~text
Step skill identity
owner id/version
owner result identity
Tool result equality
~~~

CA-03 不重复创造第二套 owner authority。

# 9. Workflow results

每个 ATTEMPT_FINALIZED Workflow-owner Step：

~~~text
evidence.workflow_result
-> workflow_results
~~~

顺序固定为 ApprovedPlan owner Step order。

每个 result 保留 workflow_instance_id，因此同一 workflow_id 多次实例化也不会因 ID 相同而被折叠。

# 10. Tool results

来源唯一为：

~~~text
CA-02 frozen Tool journal
~~~

顺序：

~~~text
ApprovedPlan Step order
-> evidence.tool_journal logical order
~~~

去重键：

~~~text
tool_call_id
~~~

规则：

~~~text
first exact logical call -> append one result
same tool_call_id + exact same frozen journal -> deterministic replay duplicate, dedupe
same tool_call_id + different frozen journal -> CONFLICT / fail closed
~~~

禁止按 tool_id 去重。

# 11. Business outputs

只复制：

~~~text
StepAggregationEvidence.business_outputs
~~~

顺序：

~~~text
ApprovedPlan Step order
-> source order
~~~

禁止：

~~~text
Tool.data -> business output inference
action name -> business output inference
Workflow COMPLETED -> business success inference
~~~

# 12. Execution events

当前 capability_events 未冻结“每条事件必须有 timestamp”。

因此 CA-03 正式冻结：

~~~text
execution_events
-> ApprovedPlan Step order
-> each Step evidence original source order
~~~

已有 event 内部 timestamp 原样保留；没有 timestamp 时不生成、不补齐、不猜测。

这比原草案“强制 timestamp sort”更符合当前合同真值边界。

# 13. State observations

当前没有可作为正式 state observation source 的 M5 authority。

因此：

~~~text
state_observations = []
~~~

禁止从：

~~~text
Tool data
business output
Action name
Workflow result
~~~

推导状态事实。

# 14. Errors

只允许从已有 execution facts 投影：

~~~text
Step.error
SkillResult.error
WorkflowResult.error
ToolResult.error_code / error_message
~~~

CA-03 可以增加 Core source 标签用于 provenance：

~~~text
STEP
SKILL
WORKFLOW
TOOL
~~~

但不得发明：

~~~text
recoverable=true/false
retryable=true/false
business error class
medical severity
~~~

# 15. Timing

Execution timing 必须有：

~~~text
started_at
finished_at
finished_at >= started_at
timezone-aware
~~~

并确定性生成：

~~~text
total_duration_ms
step_durations[]
tool_durations[]
~~~

对没有完整 start/finish 的合法 SKIPPED/control Step：

~~~text
duration_ms = None
~~~

不伪造零时长。

Tool result 只有在 start/finish 都真实存在时计算 duration。

# 16. Control provenance

CANCELLED / PREEMPTED Canonical result 必须同时具备：

~~~text
DurableControlReadDecision.status = LATCHED
exact LatchedExecutionControl
AggregationControlApplicabilityStatus = APPLIES
same exact latch
signal.target_execution_id == execution_id
signal_type matches terminal plan status
~~~

否则：

~~~text
EXECUTION_RESULT_CONTROL_PROVENANCE_MISSING
or
EXECUTION_RESULT_CONTROL_PROVENANCE_MISMATCH
~~~

cancellation payload 保存：

~~~text
signal_type
signal_id
reason_code
source
target_execution_id
requested_at = issued_at
observed_at
latched_at
cancelled
preempted
~~~

冻结：

~~~text
CANCELLED -> cancelled=true, preempted=false
PREEMPTED -> cancelled=false, preempted=true
~~~

PREEMPT 不伪装成 CANCEL。

Natural TIMEOUT / FAILED / SUCCESS / PARTIAL_SUCCESS：

~~~text
cancellation = None
~~~

允许存在 LATE_NOOP control，但它不能覆盖已经成立的自然 terminal result。

# 16.1 Control-path durable Tool join

CA-02 对 CONTROL_TERMINALIZED 只保存 Step 侧最小 terminal evidence，
不会使用 retry_count + 1 猜 final attempt，也不会伪造 Tool journal。

因此 CA-03 增加：

~~~text
ControlTerminalToolJournalStore
ControlTerminalToolEvidenceReader
DurableControlTerminalToolEvidenceReader
~~~

`CanonicalExecutionResultProjector` 自身持有 reader 依赖并执行 durable join。
调用方不能向 projector 直接注入一个 hand-constructed journal mapping 来绕过 durable provenance。

读取链：

~~~text
execution_id + step_execution_id
        ↓
Durable StepAttemptCursorRecord.current_attempt
        ↓
load_tool_journal(
    execution_id,
    step_execution_id,
    current_attempt,
)
        ↓
exact durable Tool journal
~~~

冻结：

~~~text
current_attempt comes from durable cursor
!= retry_count + 1 inference
~~~

如果 CONTROL_TERMINALIZED Step 已持有 tool_call_ids：

~~~text
durable journal tool_call_ids
must exactly equal
StepAggregationEvidence.tool_call_ids
~~~

同时每个 durable journal Tool 必须再次绑定 frozen ApprovedActionPlan：

~~~text
ApprovedStepCapabilityProjector
-> exact approved tool_id/version

durable journal tool_id/version
must match
approved tool_id/version
~~~

durable evidence 只证明“发生过什么”，不能自行证明“被批准过什么”。

否则：

~~~text
EXECUTION_RESULT_CONTROL_TOOL_EVIDENCE_READER_MISSING
or
EXECUTION_RESULT_CONTROL_TOOL_JOURNAL_MISMATCH
or
EXECUTION_RESULT_CONTROL_APPROVED_CAPABILITY_UNKNOWN
or
EXECUTION_RESULT_CONTROL_TOOL_NOT_APPROVED
~~~

即使 Step 没有 tool_call_ids，也不能因为 reader 缺失就默认“没有 Tool”。

正式语义：

~~~text
CONTROL_TERMINALIZED
-> durable Tool evidence reader REQUIRED
-> cursor=None 可证明 no durable Step attempt
-> exact journal=() 可证明 no Tool journal
~~~

reader 缺失本身不是 absence evidence。

如果 reader 返回额外 Tool journal，也会因 exact identity mismatch 被拒绝。

control-path Tool result 仍然只是 execution observation；
CANCELLED / UNKNOWN 等状态不会被升级成 SUCCESS。

# 17. Quality boundary

quality 是 M5 execution aggregation quality，不是 M6 business truth。

V1 只输出：

~~~text
aggregation_evidence_ready = true
degraded
aggregation_reason_codes
~~~

禁止：

~~~text
business_truth_valid
medical_truth_valid
claims_valid
response_valid
~~~

# 18. Natural lifecycle commit

CA-03 不建立第二套 execution terminal mutation。

当 CA-01 返回：

~~~text
READY_NATURAL
~~~

ExecutionAggregator 必须：

~~~text
ExecutionLifecycleService.finish_execution(...)
~~~

然后重新读取当前 PreparedExecution，并再次执行：

~~~text
CA-02 evidence projection
+
CA-01 aggregation evaluation
~~~

只有结果成为：

~~~text
READY_EXISTING_TERMINAL
~~~

才允许输出 Canonical ExecutionResult。

# 19. Existing terminal replay

crash window：

~~~text
CA-01 natural status decided
-> finish_execution persisted
-> process crashes before caller receives ExecutionResult
~~~

恢复后 durable terminal lifecycle + CA-02 evidence 应重算出同一 decision。

CA-01 已冻结：

~~~text
computed plan_status == persisted terminal status
-> READY_EXISTING_TERMINAL

mismatch
-> BLOCKED_UNKNOWN
~~~

CA-03 projector 只消费 READY_EXISTING_TERMINAL。

因此 same authoritative input：

~~~text
-> same Canonical ExecutionResult
~~~

不会二次 finish_execution。

# 20. Deterministic ordering

正式冻结：

~~~text
step_results
-> ApprovedPlan Step order

skill_results
-> ApprovedPlan Skill-owner Step order

workflow_results
-> ApprovedPlan Workflow-owner Step order

tool_results
-> ApprovedPlan Step order + frozen Tool journal order

business_outputs
-> ApprovedPlan Step order + evidence source order

execution_events
-> ApprovedPlan Step order + evidence source order

errors
-> ApprovedPlan Step order + fixed source projection order

timing arrays
-> ApprovedPlan Step order / Tool source order
~~~

禁止线程完成顺序、dict 偶然顺序、Registry 顺序成为输出 authority。

# 21. Boundary with CA-01 / CA-02

CA-01 owns：

~~~text
aggregation eligibility
required/optional semantics
plan_status
control precedence
terminal replay status consistency
~~~

CA-02 owns：

~~~text
terminal Step evidence exactness
owner/version truth
Tool journal truth
scheduler skip provenance
recovery-safe evidence
~~~

CA-03 owns：

~~~text
Canonical field projection
multi-Workflow cardinality
control provenance projection
deterministic collection ordering
natural terminal lifecycle integration
Canonical result replay
~~~

# 22. Files

~~~text
runtime/contracts/execution.py
runtime/contracts/__init__.py
runtime/execution/aggregation_result.py
runtime/execution/__init__.py
tests/test_canonical_contracts.py
tests/test_m5_iu10_ca03_canonical_result_projection.py
~~~

# 23. Targeted behavioral gates

~~~text
1. ExecutionResult schema_version = 1.1.0
2. workflow_results additive field exists
3. zero Workflow -> legacy None + plural []
4. one Workflow -> legacy exact + plural exact one
5. multiple Workflow -> legacy None + plural lossless list
6. Workflow order follows ApprovedPlan
7. natural aggregation uses existing lifecycle service
8. natural terminal commit is re-evaluated before projection
9. terminal replay does not mutate lifecycle again
10. terminal replay emits identical Canonical result
11. partial-success/degraded survives projection
12. Skill result comes from CA-02 evidence
13. Tool result comes from frozen journal
14. business outputs come from evidence only
15. capability events come from evidence only
16. state_observations is empty without authority
17. CANCEL projects exact durable signal provenance
18. PREEMPT remains PREEMPT, not CANCEL
19. control terminal result without exact provenance is rejected
20. control Tool journal uses durable current-attempt cursor
21. control Tool join never derives attempt from retry_count
22. control Step Tool IDs must exactly match durable journal
23. control Tool id/version must match frozen ApprovedPlan
24. control no-Tool path still requires durable absence proof
25. missing durable control Tool reader/projection fails closed
26. non-ready aggregation cannot be projected
27. Formal Projector accepts READY_EXISTING_TERMINAL only
28. Projector independently requires CA-02 READY evidence
29. Projector validates execution/plan/status provenance
30. Projector validates ApprovedPlan Step order
31. duplicate logical Tool exact replay is deterministic
32. conflicting duplicate tool_call_id fails closed
33. no Registry lookup
34. no capability invoke
35. no retry / resume / replan
36. no M6/M7/M8 dependency
37. Canonical ExecutionResult validates successfully
~~~

# 24. Blocker impact

Implementation target：

~~~text
B-M5-IU10-003
WORKFLOW_RESULT_CARDINALITY_CONTRACT_MISMATCH
= FIX_IMPLEMENTED_PENDING_REVIEW_AND_GATES

B-M5-IU10-004
CONTROL_TERMINATION_PROVENANCE_NOT_BOUND_TO_RESULT
= FIX_IMPLEMENTED_PENDING_REVIEW_AND_GATES

B-M5-IU10-005
SKELETON_EXECUTION_RESULT_PROJECTOR_INCOMPLETE
= FIX_IMPLEMENTED_PENDING_REVIEW_AND_GATES

B-M5-IU10-006
AGGREGATION_REPLAY_DETERMINISM_NOT_FROZEN
= FIX_IMPLEMENTED_PENDING_REVIEW_AND_GATES
~~~

Already closed：

~~~text
B-M5-IU10-001 = CLOSED
B-M5-IU10-002 = CLOSED
B-M5-IU10-007 = CLOSED
B-M5-IU10-008 = CLOSED
~~~

# 25. Non-goals

~~~text
change CA-01 plan-status matrix
change CA-02 evidence authority
execute Tool / Skill / Workflow
retry / resume / replan
Registry latest lookup
M6 validation
business truth inference
M7 response generation
M8 state/memory commit
production storage adapter selection
~~~

# 26. Current status

~~~text
CA-M5-IU10-03 = CODE COMPLETE
CA-M5-IU10-03 INDEPENDENT REVIEW = PASSED
CA-M5-IU10-03 VERIFICATION = PENDING

B-M5-IU10-003 = FIX_IMPLEMENTED_PENDING_GATES
B-M5-IU10-004 = FIX_IMPLEMENTED_PENDING_GATES
B-M5-IU10-005 = FIX_IMPLEMENTED_PENDING_GATES
B-M5-IU10-006 = FIX_IMPLEMENTED_PENDING_GATES

M5-IU10 IMPLEMENTATION READINESS = NOT_READY
FORMAL IMPLEMENTATION = NOT AUTHORIZED
M5 = IN PROGRESS
~~~

下一步必须是：

~~~text
CA-M5-IU10-03 Independent Review
-> targeted fixes if findings exist
-> four verification gates
-> CA-M5-IU10-03 Verification Closure
-> cumulative M5-IU10 Implementation Readiness Re-Review
~~~


# 27. Independent Review Closure

Reviewed semantic HEAD：

~~~text
bfc88622a8b64ba2d7a0ac7a48450c04cd658e6b
~~~

Base：

~~~text
CA-M5-IU10-02 = PASSED
dc0c3400d6dfd61a1935e8a194f2d450a08248dd
~~~

Independent Review findings：

~~~text
F-M5-IU10-CA03-001
PROJECTOR_COULD_PUBLISH_FROM_READY_NATURAL_BEFORE_DURABLE_TERMINAL_COMMIT
= CLOSED

F-M5-IU10-CA03-002
CONTROL_PATH_TOOL_JOURNAL_NOT_JOINED_FROM_DURABLE_CURRENT_ATTEMPT
= CLOSED

F-M5-IU10-CA03-003
DURABLE_TOOL_EVIDENCE_COULD_SELF_AUTHORIZE_WITHOUT_APPROVED_PLAN
= CLOSED

F-M5-IU10-CA03-004
CONTROL_NO_TOOL_PATH_COULD_DEFAULT_FROM_MISSING_READER
= CLOSED

F-M5-IU10-CA03-005
PROJECTOR_COULD_ACCEPT_HAND_CONSTRUCTED_CONTROL_TOOL_MAPPING
= CLOSED

F-M5-IU10-CA03-006
M0_CLOSURE_SCHEMA_VERSION_GATE_STALE
= CLOSED

F-M5-IU10-CA03-007
FROZEN_EXECUTION_CONTRACT_DOCUMENTATION_DRIFT
= CLOSED

F-M5-IU10-CA03-008
EVENT_TIMESTAMP_ORDER_WOULD_INVENT_UNFROZEN_TIME
= CLOSED
~~~

Review confirms：

~~~text
Canonical multi-Workflow projection is lossless
legacy workflow_result remains single-item compatibility only
Formal Projector accepts READY_EXISTING_TERMINAL only
natural terminalization reuses ExecutionLifecycleService
terminal replay does not re-terminalize execution
control result binds exact durable control latch
control Tool truth joins through durable current-attempt cursor
control Tool id/version rebinds to frozen ApprovedActionPlan
no-Tool control path requires durable absence proof
callers cannot inject hand-constructed control Tool journals
Tool replay is deterministic by logical tool_call_id
conflicting duplicate Tool evidence fails closed
state_observations are not inferred without authority
M5 quality does not claim M6 business truth
no Registry lookup / capability invoke / retry / resume / replan
no M6 / M7 / M8 authority leak
~~~

Independent Review decision：

~~~text
CA-M5-IU10-03 = CODE COMPLETE
CA-M5-IU10-03 INDEPENDENT REVIEW = PASSED
CA-M5-IU10-03 VERIFICATION = PENDING

B-M5-IU10-003 = FIX_IMPLEMENTED_PENDING_GATES
B-M5-IU10-004 = FIX_IMPLEMENTED_PENDING_GATES
B-M5-IU10-005 = FIX_IMPLEMENTED_PENDING_GATES
B-M5-IU10-006 = FIX_IMPLEMENTED_PENDING_GATES

NEW CA-03 SEMANTIC BLOCKER = NONE

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

四项门禁全部通过之前：

~~~text
CA-M5-IU10-03 != PASSED
B-M5-IU10-003..006 != CLOSED
M5-IU10 != READY
FORMAL IMPLEMENTATION != AUTHORIZED
~~~
