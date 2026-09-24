# CA-M5-IU10-02 Crash-Safe Terminal Step Aggregation Evidence V1.0

> Parent：M5-IU10 — Step 12 Execution Aggregation
>
> Base：CA-M5-IU10-01 Verification Closure @ 9b0a84d0b475a2264b00c7386d875cf374ca7fa6

# 1. Amendment goal

关闭：

~~~text
B-M5-IU10-002
CRASH_SAFE_RICH_AGGREGATION_EVIDENCE_MISSING
~~~

CA-02 把聚合所需的 terminal Step evidence 变成 Core-owned、typed、recovery-safe、exact-identity，并与 Step terminal lifecycle 同一次持久化。

# 2. Atomic truth boundary

~~~text
terminal authority
↓
build StepAggregationEvidence
↓
Step lifecycle transition
↓
StepLifecycleSnapshot(status + evidence)
↓
same ExecutionRecord.step_results
↓
same ExecutionStateStore.save(...)
~~~

禁止第二次异步 evidence write；否则会重新出现 terminal Step 已提交但 evidence 丢失的 crash window。

# 3. Core schema

~~~text
AGGREGATION_EVIDENCE_SCHEMA_VERSION = m5-iu10-ca02-v1

StepAggregationTerminalizationKind
- ATTEMPT_FINALIZED
- SCHEDULER_SKIPPED
- CONTROL_TERMINALIZED

StepAggregationEvidenceReadStatus
- READY
- MISSING
- UNKNOWN
~~~

StepAggregationEvidence 保存：

~~~text
execution_id / step_execution_id / step_id
terminalization_kind
terminal_step_status
terminal_reason_codes
degraded
observed_at / terminalized_at

final_attempt_number?
final_attempt_status?
final_attempt_reason_codes

execution_owner?
owner_capability_id/version?
skill_result?
workflow_result?

tool_call_ids
tool_journal
business_outputs
capability_events

Tool truth flags
scheduler_skip_disposition?
~~~

# 4. Step lifecycle integration

StepLifecycleSnapshot 新增 aggregation_evidence。

该字段同步进入 ExecutionRecord.step_results 和 ExecutionRecoverySnapshot exact Step payload。

旧 payload 缺 aggregation_evidence 时按 None 归一化，保证旧 recovery snapshot 可读；但 terminal Step + evidence=None 只能得到 MISSING，不能被自动升级为 READY。

# 5. ATTEMPT_FINALIZED

来源：RunningStepCompletionCoordinator 消费 IU6 StepReliabilityRunResult / RecoveredStepReliabilityRunResult。

保存 final attempt、owner result、Tool journal、business outputs、capability events，并在调用既有 finish_step 时与 lifecycle 一起持久化。

冻结映射：

~~~text
Step SUCCESS + degraded=false <-> final attempt SUCCESS
Step SUCCESS + degraded=true  <-> final attempt PARTIAL_SUCCESS
Step FAILED                   <-> final attempt FAILED
Step TIMEOUT                  <-> final attempt TIMEOUT
~~~

WAITING / IN_PROGRESS / UNKNOWN 不得伪装为 terminal attempt。

# 6. Skill evidence

必须满足：

~~~text
Step.skill_id
== evidence.owner_capability_id
== skill_result.skill_id

execution_owner = SKILL
~~~

并校验 Skill status 与 Step lifecycle/degraded 的 exact 映射，以及 skill business_outputs/events 与 evidence 的一致性。

# 7. Workflow evidence

必须满足：

~~~text
Step.workflow_id
== evidence.owner_capability_id
== workflow_result.workflow_id

execution_owner = WORKFLOW
~~~

冻结：

~~~text
Step SUCCESS <-> Workflow COMPLETED
Step FAILED  <-> Workflow FAILED
Step TIMEOUT <-> Workflow TIMEOUT
~~~

Workflow WAITING / RUNNING / CREATED 不能成为 terminal aggregation evidence。

# 8. Ambiguous owner

如果 Step 同时具有 skill_id 与 workflow_id，CA-02 不自行选 owner：

~~~text
UNKNOWN
AGGREGATION_EVIDENCE_STEP_OWNER_AMBIGUOUS
~~~

# 9. Tool truth

ATTEMPT_FINALIZED 保存 exact Tool journal，并要求 tool_call_ids 等于 journal logical order。

Tool truth flags 不是可信输入；CA-02 从 frozen journal 重新计算 non-success / unknown / untrusted-success 并与字段核对。

如果 terminal evidence 中仍有 UNKNOWN Tool truth 或 raw SUCCESS -> sanitized UNKNOWN：

~~~text
UNKNOWN
AGGREGATION_EVIDENCE_TOOL_TRUTH_UNKNOWN
~~~

# 10. SCHEDULER_SKIPPED

TerminalStepCompletionCoordinator 创建 evidence 并与 PENDING -> SKIPPED lifecycle 同次保存。

冻结：

~~~text
DEPENDENCY_NOT_SUCCESSFUL
REQUIRED_PREVIOUS_STEP_NOT_SUCCESSFUL
-> UNSATISFIED

其他已经由 scheduler authority 合法给出的 SKIP
-> NOT_APPLICABLE
~~~

CA-02 输出 exact StepSkipAggregationDecision 给 CA-01，不重新运行 condition evaluator。

# 11. CONTROL_TERMINALIZED

CA-02 只保存 Step 侧最小 crash-safe terminal evidence：

~~~text
CANCELLED / PREEMPTED
exact ExecutionControlApplication.reason_codes
terminalized_at
existing lifecycle tool_call_ids
~~~

CA-02 不伪造 final attempt、Skill/Workflow result、Tool journal、business output 或 capability event。

原因是 control lifecycle 没有 authoritative final attempt cursor；不得用 retry_count + 1 猜 attempt。

IU9 durable Tool journal 虽已存在，但读取要求 exact execution_id + step_execution_id + step_attempt_number。control signal/applicability、cancellation projection 与 control-path Tool join 仍归 CA-03 / B-M5-IU10-004。

# 12. Exact typed ↔ persisted consistency

StepAggregationEvidenceAuthority 同时检查 typed Step 和 ExecutionRecord.step_results。

要求 exact：

~~~text
Step count / unique step_id
execution_id
step_execution_id
step_id
terminal status
terminal reason
degraded
terminalized_at
tool_call_ids
aggregation_evidence payload
~~~

任何漂移 -> UNKNOWN，不自动修复。

# 13. Recovery exactness

recovery.py 将 aggregation_evidence 加入 Step exact payload；legacy missing key -> None。

snapshot restore 后 typed StepAggregationEvidence 保留，因此 live terminal evidence 与 restart evidence 一致。

# 14. Strict serialized schema

from_payload 要求 exact key set，并拒绝：

~~~text
extra/missing keys
字符串强转
非 bool 的 bool 字段
非 mapping 的 payload collection
非 string mapping key
unsupported live Runtime object
~~~

允许的 recovery-safe value 仅为 Enum value、aware datetime、dataclass frozen mapping、string-key dict、list/tuple、primitive/None。

# 15. CA-01 authority seam

新增：

~~~text
StepAggregationEvidenceAuthority
project_ca01_evidence_inputs(prepared)
~~~

输出：

~~~text
AggregationEvidenceReadinessDecision
StepSkipAggregationDecision map
~~~

规则：

~~~text
all terminal evidence exact -> READY
terminal Step evidence absent -> MISSING
typed/persisted drift / owner mismatch / Tool UNKNOWN / ambiguous owner -> UNKNOWN
~~~

Formal Implementation 不得手工构造 READY 来绕过该 authority。

StepAggregationEvidenceAuthority 必须同时消费 frozen ApprovedActionPlan。

ATTEMPT_FINALIZED evidence 还必须验证：

~~~text
execution owner
owner capability id/version
Tool id/version
~~~

均来自 ApprovedStepCapabilityProjector 的 frozen capability/tool authority。

禁止：

~~~text
evidence self-claim version
Registry latest substitution
unapproved Tool version
~~~

# 16. Immutability and replay

CA-02 不建立第二套独立 mutable evidence store。evidence 属于 immutable terminal Step fact。

same recovery snapshot -> exact same evidence；不同 persisted payload -> UNKNOWN。

# 17. Files

~~~text
runtime/execution/aggregation_evidence.py
runtime/execution/foundation.py
runtime/execution/recovery.py
runtime/execution/step_completion.py
runtime/execution/control_lifecycle.py
runtime/execution/aggregation_authority.py
runtime/execution/__init__.py
tests/test_m5_iu10_ca02_aggregation_evidence.py
~~~

# 18. Behavioral gates

~~~text
1. attempt finalization atomically persists rich evidence
2. PARTIAL_SUCCESS preserves degraded + final attempt PARTIAL_SUCCESS
3. Skill owner/result survives persistence
4. Tool journal survives persistence
5. business outputs/events survive persistence
6. CA-01 readiness derives READY only from evidence authority
7. evidence survives IU9 snapshot roundtrip
8. condition SKIP -> NOT_APPLICABLE
9. dependency/remainder SKIP -> UNSATISFIED
10. terminal legacy Step without evidence -> MISSING
11. persisted evidence drift -> UNKNOWN
12. legacy payload without evidence remains recovery-readable
13. control terminalization attaches minimal evidence only
14. exact evidence payload roundtrip
15. live Runtime object rejected
16. Workflow COMPLETED evidence READY
17. Workflow WAITING cannot masquerade as terminal SUCCESS
18. UNKNOWN Tool truth -> UNKNOWN
19. recovered attempt number survives evidence
20. extra/coercive serialized fields rejected
21. forged Tool truth flags rejected
22. ambiguous Skill+Workflow owner -> UNKNOWN
23. owner version drift from ApprovedActionPlan -> UNKNOWN
24. Tool version drift from ApprovedActionPlan -> UNKNOWN
25. owner result Tool results must equal Core journal final results
26. frozen physical Tool attempts are revalidated
~~~

# 19. Independent Review findings accumulated during implementation

~~~text
F-M5-IU10-CA02-001 SECOND_EVIDENCE_WRITE_WOULD_REINTRODUCE_CRASH_WINDOW = CLOSED
F-M5-IU10-CA02-002 LEGACY_TERMINAL_STEP_COULD_BE_FALSELY_UPGRADED_TO_READY = CLOSED
F-M5-IU10-CA02-003 FINAL_ATTEMPT_STATUS_NOT_CRASH_PRESERVED = CLOSED
F-M5-IU10-CA02-004 TOOL_TRUTH_FLAGS_COULD_BE_FORGED = CLOSED
F-M5-IU10-CA02-005 STEP_OWNER_COULD_BE_AMBIGUOUS = CLOSED
F-M5-IU10-CA02-006 SERIALIZED_EVIDENCE_ALLOWED_COERCIVE_TYPES = CLOSED
F-M5-IU10-CA02-007 OWNER_RESULT_TOOL_RESULTS_COULD_DIVERGE_FROM_CORE_JOURNAL = CLOSED
F-M5-IU10-CA02-008 EXTENSIBLE_PAYLOADS_COULD_BYPASS_RECOVERY_SAFE_FREEZE = CLOSED
F-M5-IU10-CA02-009 FROZEN_PHYSICAL_TOOL_ATTEMPTS_NOT_REVALIDATED = CLOSED
F-M5-IU10-CA02-010 OWNER_AND_TOOL_VERSIONS_COULD_SELF_CLAIM_WITHOUT_APPROVED_PLAN = CLOSED
F-M5-IU10-CA02-011 CONTROL_PATH_LACKS_EXACT_FINAL_ATTEMPT_AUTHORITY = CLOSED_BY_BOUNDARY
~~~

# 20. Independent Review boundary on control evidence

Control-terminalized Step 的 evidence 是 crash-safe terminal fact，但不是完整 cancellation projector。

CA-02 不使用 retry_count + 1 猜 final attempt，也不从 durable Tool journal 随意选 attempt。

因此：

~~~text
CONTROL_TERMINALIZED evidence
+ IU9 durable control / Tool evidence
-> 后续 CA-03 authoritative join
~~~

该边界关闭的是 CA-02 的“不得发明”问题，不关闭 B-M5-IU10-004。

# 21. Blocker impact

~~~text
B-M5-IU10-002
CRASH_SAFE_RICH_AGGREGATION_EVIDENCE_MISSING
= CLOSED

B-M5-IU10-003 = OPEN
B-M5-IU10-004 = OPEN
B-M5-IU10-005 = OPEN
B-M5-IU10-006 = OPEN

B-M5-IU10-001 = CLOSED
B-M5-IU10-007 = CLOSED
B-M5-IU10-008 = CLOSED
~~~

# 22. Non-goals

~~~text
change CA-01 plan-status matrix
multi-Workflow Canonical amendment
ExecutionResult formal projector
cancellation/preemption result projection
control applicability persistence
natural execution terminal commit
M6 validation
business truth inference
replanning / retry / resume
Registry lookup
~~~

# 23. Current status

~~~text
CA-M5-IU10-02 = PASSED
CA-M5-IU10-02 INDEPENDENT REVIEW = PASSED
CA-M5-IU10-02 VERIFICATION = PASSED

B-M5-IU10-002 = CLOSED

M5-IU10 IMPLEMENTATION READINESS = NOT_READY
FORMAL IMPLEMENTATION = NOT AUTHORIZED
M5 = IN PROGRESS
~~~

# 24. Independent Review decision

Independent Review exact semantic target：

~~~text
PR #76
base = 9b0a84d0b475a2264b00c7386d875cf374ca7fa6
semantic head = d9df6a421380e8321cc9d404c375e75a250e63ec
~~~

累计复核：

~~~text
terminal lifecycle + evidence same-write atomicity
legacy missing evidence fail-closed
typed ↔ persisted exact evidence
IU9 recovery exactness
final attempt status/reasons
Skill/Workflow owner/result truth
Tool journal + physical-attempt truth
Tool truth flags recomputation
business outputs/events recovery-safe freeze
scheduler SKIP provenance
control minimal evidence boundary
ApprovedActionPlan owner/Tool ID+version authority
strict serialized schema
CA-01 READY/MISSING/UNKNOWN projection seam
~~~

Independent Review 已关闭：

~~~text
F-M5-IU10-CA02-001 SECOND_EVIDENCE_WRITE_WOULD_REINTRODUCE_CRASH_WINDOW
F-M5-IU10-CA02-002 LEGACY_TERMINAL_STEP_COULD_BE_FALSELY_UPGRADED_TO_READY
F-M5-IU10-CA02-003 FINAL_ATTEMPT_STATUS_NOT_CRASH_PRESERVED
F-M5-IU10-CA02-004 TOOL_TRUTH_FLAGS_COULD_BE_FORGED
F-M5-IU10-CA02-005 STEP_OWNER_COULD_BE_AMBIGUOUS
F-M5-IU10-CA02-006 SERIALIZED_EVIDENCE_ALLOWED_COERCIVE_TYPES
F-M5-IU10-CA02-007 OWNER_RESULT_TOOL_RESULTS_COULD_DIVERGE_FROM_CORE_JOURNAL
F-M5-IU10-CA02-008 EXTENSIBLE_PAYLOADS_COULD_BYPASS_RECOVERY_SAFE_FREEZE
F-M5-IU10-CA02-009 FROZEN_PHYSICAL_TOOL_ATTEMPTS_NOT_REVALIDATED
F-M5-IU10-CA02-010 OWNER_AND_TOOL_VERSIONS_COULD_SELF_CLAIM_WITHOUT_APPROVED_PLAN
F-M5-IU10-CA02-011 CONTROL_PATH_LACKS_EXACT_FINAL_ATTEMPT_AUTHORITY
~~~

其中 F-011 通过明确边界关闭：CA-02 不猜 control final attempt；CA-03 使用 IU9 durable control/Tool authority 做后续 join。

未发现新的 semantic blocker。

正式结论：

~~~text
CA-M5-IU10-02 = CODE COMPLETE
CA-M5-IU10-02 INDEPENDENT REVIEW = PASSED
CA-M5-IU10-02 VERIFICATION = PENDING

B-M5-IU10-002
CRASH_SAFE_RICH_AGGREGATION_EVIDENCE_MISSING
= FIX_IMPLEMENTED_PENDING_GATES

NEW SEMANTIC BLOCKER = NONE
~~~

其余 blocker：

~~~text
B-M5-IU10-001 = CLOSED
B-M5-IU10-002 = FIX_IMPLEMENTED_PENDING_GATES
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

四项门禁通过并完成 Verification Closure 前，不得写：

~~~text
CA-M5-IU10-02 = PASSED
B-M5-IU10-002 = CLOSED
~~~


# 25. Verification Closure

Verification target code HEAD：

~~~text
1679871786257f992fcaf3bca9403e0bd48d35ed
~~~

Independent Review semantic HEAD：

~~~text
d9df6a421380e8321cc9d404c375e75a250e63ec
~~~

Independent Review closure documentation HEAD：

~~~text
667192d7a0b137b1f3ab1a3a2ed760411095bb27
~~~

Independent Review 后仅做门禁兼容修复，不改变 CA-02 aggregation 语义：

~~~text
1. test_unknown_tool_truth_blocks_terminal_evidence_readiness
   - 不再伪造 has_unknown_tool_observation
   - 同步把 Tool journal result / physical attempt result 改为 UNKNOWN
   - 同步 owner result tool_results
   - 同步 has_non_success_tool_observation / has_unknown_tool_observation

2. StepAggregationEvidence.from_payload
   - 不再把字段级 ValueError 包装成泛化 payload 错误
   - strict type validation 保持不变
   - 字段错误仍可保留 exact field identity

3. _snapshot_to_record_payload
   - 显式使用 dict[str, object]，仅修正 mypy invariant 推断

4. fail-closed isinstance
   - 保持 ValueError 语义
   - 仅增加 noqa: TRY004

5. import / __all__ / formatting
   - 仅门禁兼容与格式对齐
~~~

四项最终门禁：

~~~text
python -m pytest tests -q
-> 922 passed

python -m mypy runtime tests
-> Success: no issues found in 213 source files

python -m ruff check runtime tests
-> All checks passed

python -m ruff format --check runtime tests
-> 213 files already formatted
~~~

Verification Closure decision：

~~~text
CA-M5-IU10-02 = PASSED
CA-M5-IU10-02 INDEPENDENT REVIEW = PASSED
CA-M5-IU10-02 VERIFICATION = PASSED

B-M5-IU10-002
CRASH_SAFE_RICH_AGGREGATION_EVIDENCE_MISSING
= CLOSED

NEW CA-02 BLOCKER = NONE

M5-IU10 IMPLEMENTATION READINESS = NOT_READY
FORMAL IMPLEMENTATION = NOT AUTHORIZED
M5 = IN PROGRESS
~~~

Remaining IU10 blockers：

~~~text
B-M5-IU10-001 = CLOSED
B-M5-IU10-002 = CLOSED
B-M5-IU10-003 = OPEN
B-M5-IU10-004 = OPEN
B-M5-IU10-005 = OPEN
B-M5-IU10-006 = OPEN
B-M5-IU10-007 = CLOSED
B-M5-IU10-008 = CLOSED
~~~

下一步：

~~~text
CA-M5-IU10-03
Canonical ExecutionResult Projection + Cardinality
~~~

CA-02 Verification Closure 只关闭 B-M5-IU10-002；不代表 M5-IU10 READY，不授权 Formal Implementation。
