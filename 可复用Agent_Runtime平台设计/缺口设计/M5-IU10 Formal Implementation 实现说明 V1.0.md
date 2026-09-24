# M5-IU10 Formal Implementation 实现说明 V1.0

> Base：
>
> ~~~text
> M5-IU10 IMPLEMENTATION READINESS RE-REVIEW = PASSED
> M5-IU10 IMPLEMENTATION READINESS = READY
> FORMAL IMPLEMENTATION = AUTHORIZED
> base = d283027eceb81130d2b165e8184585d299c045fc
> ~~~
>
> PR：#79
>
> Semantic review HEAD：
>
> ~~~text
> a62a1711831fea2502dc9bc3a0b2dfde7ce076f0
> ~~~

# 1. Formal Implementation target

本轮不再重新设计 IU10。

唯一目标是把已经冻结并验证的：

~~~text
CA-M5-IU10-00
CA-M5-IU10-01
CA-M5-IU10-02
CA-M5-IU10-03
CA-M5-IU10-04
~~~

接入正式 M5 execution runtime。

实现范围严格绑定：

~~~text
FI-M5-IU10-REQ-001..009
~~~

# 2. Formal aggregation runtime

新增：

~~~text
runtime/execution/aggregation_runtime.py
~~~

核心对象：

~~~text
M5ExecutionAggregationRuntime
M5ExecutionAggregationOutcome
M5ExecutionAggregationRuntimeStatus
~~~

正式状态：

~~~text
STEP_READY
WAITING
BLOCKED_UNKNOWN
AGGREGATED
~~~

该 runtime 不执行 Capability，也不创建第二套 scheduler / retry / recovery engine。

# 3. Terminal Step completion wiring

正式链：

~~~text
SequentialStepScheduler
↓
TerminalStepCompletionCoordinator
↓
PENDING Step exact terminalization
↓
re-enter scheduler
~~~

支持：

~~~text
scheduler SKIP
required previous Step not successful
~~~

WAITING / BLOCKED_UNKNOWN 不做 speculative terminalization。

Aggregator 不直接把 PENDING 改为 SKIPPED。

# 4. Running Step finalization wiring

正式链：

~~~text
StepReliabilityRunResult
or
RecoveredStepReliabilityRunResult
or
RecoveredWorkflowReliabilityRunResult
↓
RunningStepCompletionCoordinator
↓
ExecutionLifecycleService.finish_step
↓
StepAggregationEvidence
↓
M5ExecutionAggregationRuntime.advance
~~~

Skill PARTIAL_SUCCESS 继续保持：

~~~text
Step lifecycle = SUCCESS
degraded = true
~~~

# 5. Formal aggregation publication

Formal runtime 只在 scheduler 已 COMPLETE 或 execution 已 authoritative terminal 时进入：

~~~text
ExecutionAggregator
~~~

内部仍是：

~~~text
DurableAggregationControlAuthority
↓
ExecutionAggregationAuthority
↓
READY_NATURAL / READY_EXISTING_TERMINAL
~~~

如果 READY_NATURAL：

~~~text
ExecutionLifecycleService.finish_execution
↓
preserve ExecutionTerminalObserver
↓
re-resolve durable control authority
↓
re-project CA-02 evidence
↓
re-evaluate
↓
must become READY_EXISTING_TERMINAL
~~~

只有：

~~~text
READY_EXISTING_TERMINAL
~~~

才能：

~~~text
CanonicalExecutionResultProjector
↓
Canonical ExecutionResult
~~~

# 6. Durable control composition

新增：

~~~text
DurableControlRuntimeFactory
DurableRecoveryControlRuntimeFactory
~~~

同一个 exact ExecutionRecoveryClaim 同时绑定：

~~~text
DurableExecutionControlLatch
+
DurableControlApplicabilityRecorder
~~~

保证：

~~~text
terminal control latch
+
APPLIES/LATE_NOOP provenance
~~~

使用同一 recovery epoch authority。

# 7. Durable Tool journal write boundary

新增：

~~~text
ToolInvocationJournalPersistence
DurableToolJournalEvidence.persist(...)
~~~

CoreApprovedToolInvoker 在 logical Tool invocation 返回给 owner 前：

~~~text
exact logical Tool journal
↓
durable current-attempt journal
~~~

写入失败：

~~~text
TOOL_DURABLE_JOURNAL_WRITE_UNKNOWN
↓
ToolInvocationBoundaryError
↓
fail closed
~~~

不得把未持久化 Tool result 当成可安全聚合 evidence。

# 8. Live execution durable journal composition

Independent Implementation Review 发现 normal live execution 的 durable journal 写端原先只存在 optional seam。

已新增：

~~~text
LiveExecutionBindingsBuilder
DurableLiveExecutionBindings
DurableLiveExecutionBindingsFactory
~~~

Core 创建 exact：

~~~text
DurableToolJournalEvidence
~~~

并验证：

~~~text
StepCapabilityExecutor.tool_journal_persistence
is exact same journal
~~~

如果 caller 构造的 StepCapabilityExecutor 未绑定：

~~~text
ValueError
live StepCapabilityExecutor must use exact durable Tool journal
~~~

# 9. Claim-coherent live Tool + control composition

为避免：

~~~text
Tool journal uses recovery epoch N
Control latch/applicability uses recovery epoch M
~~~

新增：

~~~text
DurableM5ExecutionBindings
DurableM5ExecutionBindingsFactory
~~~

统一：

~~~text
one exact ExecutionRecoveryClaim
↓
DurableLiveExecutionBindingsFactory
+
DurableControlRuntimeFactory
~~~

Formal live path 不再依赖调用方分别拼装两个 claim。

# 10. Control-terminal Tool read boundary

Formal Canonical projector 固定使用：

~~~text
DurableControlTerminalToolEvidenceReader
~~~

读取：

~~~text
StepAttemptCursorRecord.current_attempt
↓
exact durable Tool journal
~~~

禁止：

~~~text
retry_count + 1
caller-provided Tool journal
Tool id-only identity
~~~

# 11. Recovered Workflow same-attempt finalization

恢复 Workflow checkpoint 不创建伪造的新 Step attempt。

新增：

~~~text
RecoveredWorkflowReliabilityRunResult
StepReliabilityCoordinator.finalize_recovered_workflow_outcome(...)
~~~

链路：

~~~text
exact current attempt N
↓
resume same Workflow instance/version
↓
IU5 StepResultCollector
↓
IU6 reliability decision
↓
IU6 finalization evaluator
↓
RecoveredWorkflowReliabilityRunResult(attempt N)
↓
RunningStepCompletionCoordinator
~~~

不会为了进入 IU10 人工 claim N+1。

# 12. Recovered Workflow current-attempt journal merge

checkpoint resume 前当前 attempt 已有 Tool journal 时：

~~~text
recovered current-attempt journal
+
resumed journal
↓
stable ordered merge by tool_call_id
~~~

exact duplicate：

~~~text
dedupe
~~~

same tool_call_id + different immutable journal：

~~~text
WORKFLOW_RECOVERY_TOOL_JOURNAL_CONFLICT
-> UNKNOWN
~~~

不会 first-wins / last-wins。

# 13. Recovered current-attempt Tool ID reservation

Independent Review 发现：

~~~text
F-M5-IU10-FI-001
RECOVERED_CURRENT_ATTEMPT_TOOL_CALL_ID_NOT_RESERVED_BEFORE_PHYSICAL_INVOKE
~~~

原风险：

~~~text
checkpoint resume
+
recovered current attempt already has tool-call-X
↓
new Tool gateway local issued-id set starts empty
↓
identifier factory returns tool-call-X again
↓
physical Tool could execute
↓
only durable persist detects duplicate
~~~

这是 side-effect-before-identity-conflict。

修复：

~~~text
recovered_current_attempt_journal.tool_call_id
↓
reserved_tool_call_ids
↓
CoreApprovedToolInvoker
~~~

以下入口都必须在 side effect 前拒绝 reserved id：

~~~text
_new_tool_call_id
_claim_reliable_attempt_identity
_append_logical_result_without_attempt
~~~

结果：

~~~text
TOOL_CALL_ID_COLLISION
physical Tool invoke = 0
~~~

Status：

~~~text
F-M5-IU10-FI-001 = CLOSED
~~~

# 14. Live durable journal writer gap

Independent Review 发现：

~~~text
F-M5-IU10-FI-002
LIVE_EXECUTION_DURABLE_TOOL_JOURNAL_WRITER_NOT_MANDATORILY_COMPOSED
~~~

原实现：

~~~text
Formal control-terminal projector
-> always reads durable Tool journal

Recovery execution
-> durable journal writer enforced

Normal live execution
-> journal persistence optional
~~~

存在：

~~~text
strict reader
+
missing live writer
~~~

风险。

通过 DurableLiveExecutionBindingsFactory 已关闭。

Status：

~~~text
F-M5-IU10-FI-002 = CLOSED
~~~

# 15. Recovery claim coherence gap

Independent Review 进一步发现：

~~~text
F-M5-IU10-FI-003
LIVE_TOOL_AND_CONTROL_DURABLE_AUTHORITIES_COULD_USE_DIFFERENT_RECOVERY_CLAIMS
~~~

虽然 live Tool writer 和 durable control factory 各自都要求 claim，但 caller 可分别调用。

修复：

~~~text
DurableM5ExecutionBindingsFactory.create(exact claim)
↓
live Tool journal bindings
+
control latch/applicability runtime
~~~

两侧由同一次 create 使用同一 claim。

Status：

~~~text
F-M5-IU10-FI-003 = CLOSED
~~~

# 16. Recovery Runtime compatibility

M5RecoveryRuntime 仍由既有 RecoveryCoordinator 决定：

~~~text
TERMINAL_NO_ACTION
APPLY_LATCHED_CONTROL
WAIT_RECONCILIATION
RESUME_WORKFLOW
RETRY_STEP
RESUME_SCHEDULING
~~~

Formal IU10 没有新增 recovery disposition。

Workflow resume 只有在原 Recovery decision 已授权后才执行。

WAITING Workflow 仍产生 WAIT_RECOVERY / non-final authority，不会被强制 terminalize。

# 17. Formal fail-closed behavior

以下均不得产生 ExecutionResult：

~~~text
execution non-RUNNING/non-terminal
scheduler WAITING
scheduler BLOCKED_UNKNOWN
running Step KEEP_RUNNING
running Step WAIT_RECOVERY
running Step completion UNKNOWN
aggregation eligibility WAITING
aggregation eligibility BLOCKED_UNKNOWN
control applicability UNKNOWN
evidence MISSING/UNKNOWN
terminal status mismatch
Tool durable journal mismatch
~~~

M5ExecutionAggregationRuntime 统一返回：

~~~text
WAITING
or
BLOCKED_UNKNOWN
~~~

且：

~~~text
aggregation_result = None
~~~

# 18. Existing terminal replay

Formal runtime 对已 terminal execution 直接进入 exact replay validation。

要求：

~~~text
existing terminal status
==
CA-01 recomputed authority
~~~

否则：

~~~text
BLOCKED_UNKNOWN
~~~

通过时 Canonical result 必须 deterministic。

# 19. Multi-Workflow

Formal path 使用 CA-03 Canonical projector，保持：

~~~text
0 Workflow
-> workflow_result=None
-> workflow_results=[]

1 Workflow
-> singular + plural same exact item

>1 Workflow
-> workflow_result=None
-> workflow_results lossless ordered list
~~~

# 20. IU8 terminal observer boundary

Natural finish 仍调用：

~~~text
ExecutionLifecycleService.finish_execution(...)
~~~

因此不会绕开：

~~~text
ExecutionTerminalObserver
↓
IU8 session execution lease release
~~~

observer failure 仍不反向改写 authoritative terminal lifecycle。

# 21. Formal implementation behavioral gates

新增/扩展：

~~~text
tests/test_m5_iu10_formal_implementation.py
~~~

覆盖至少：

~~~text
PARTIAL_SUCCESS finalization + aggregation
scheduler SKIP terminal closure
WAITING no publication
existing terminal deterministic replay
multi-Workflow lossless projection
CANCEL/PREEMPT durable provenance
late-control LATE_NOOP
natural terminal observer preservation
control-terminal current-attempt Tool journal
durable control factory exact claim binding
recovery bindings exact durable journal
live bindings exact durable journal
one-claim Tool/control composition
durable Tool write before return
durable Tool write failure fail closed
recovered Workflow same-attempt finalization
recovered Workflow journal merge/conflict
recovered current-attempt Tool ID collision before side effect
Formal runtime excludes skeleton projector/hand-built control
~~~

# 22. Boundary review

Formal Implementation 没有新增：

~~~text
M2 policy decision
priority recomputation
scheduler semantics
retry policy
replay policy
recovery disposition
ResourceLock semantics
Registry latest lookup
capability substitution
M6 validation
M7 response
M8 state/memory update
PREEMPT new Runtime cycle
business/medical truth inference
~~~

# 23. Independent Implementation Review decision

Review findings：

~~~text
F-M5-IU10-FI-001 = CLOSED
F-M5-IU10-FI-002 = CLOSED
F-M5-IU10-FI-003 = CLOSED
~~~

No additional semantic blocker found after targeted remediation.

Decision：

~~~text
M5-IU10 FORMAL IMPLEMENTATION = CODE COMPLETE
M5-IU10 INDEPENDENT IMPLEMENTATION REVIEW = PASSED
M5-IU10 VERIFICATION = PENDING

NEW IMPLEMENTATION BLOCKER = NONE

M5-IU10 = IN PROGRESS
M5 = IN PROGRESS
~~~

# 24. Required verification

在四项门禁实际全绿之前，不得写：

~~~text
M5-IU10 FORMAL IMPLEMENTATION = PASSED
M5-IU10 VERIFICATION = PASSED
M5-IU10 = PASSED
~~~

下一步必须执行：

~~~text
python -m pytest tests -q
python -m mypy runtime tests
python -m ruff check runtime tests
python -m ruff format --check runtime tests
~~~

通过后进入：

~~~text
M5-IU10 Formal Implementation Verification Closure
~~~
