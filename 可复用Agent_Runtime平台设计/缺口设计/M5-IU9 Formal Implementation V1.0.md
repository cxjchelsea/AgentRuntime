# M5-IU9 Formal Implementation V1.0

> Base：CA-M5-IU9-06 PASSED @ db5ffe69b2448cc03c38314bc5eb4ccfc7c2c642
> Formal branch：m5-iu9-formal-implementation
> PR：#72

## 1. 实现目标

本实现不重新设计 Recovery，而是把 CA-M5-IU9-01～06 冻结的合同接入现有 M5 执行边界。

核心原则：

~~~text
Recovery decision != parallel execution engine

Recovery authority
-> re-enter existing M5 boundaries
~~~

不进入 IU10 / M6，不重规划，不重新选择 Capability。

## 2. Formal Runtime

新增：

~~~text
runtime/execution/recovery_runtime.py

M5RecoveryRuntime
M5RecoveryRuntimeOutcome
M5RecoveryRuntimeStatus
ApprovedPlanWorkflowVersionAuthority
RecoveryExecutionBindings
RecoveryExecutionBindingsFactory
RecoveryControlRuntimeFactory
~~~

`M5RecoveryRuntime` 只负责恢复编排，不拥有 Tool / Skill / Workflow 的第二套执行语义。

## 3. 总恢复链

~~~text
exact ExecutionRecoveryClaim
-> exact source RecoverySnapshot
-> RecoveryCoordinator

TERMINAL_NO_ACTION
-> no action

APPLY_LATCHED_CONTROL
-> existing IU7 ExecutionControlCoordinator

WAIT_RECONCILIATION
-> ToolResourceRecoveryCoordinator
-> RecoveryCoordinator re-evaluate

RESUME_WORKFLOW
-> exact ApprovedPlan capability resolution
-> existing StepCapabilityExecutor
-> WorkflowRecoveryImplementation.resume_from_checkpoint

RETRY_STEP
-> exact ApprovedPlan capability resolution
-> existing StepReliabilityCoordinator.run_recovered_retry

RESUME_SCHEDULING
-> existing SequentialStepScheduler
~~~

## 4. FI-M5-IU9-REQ-001

### Workflow approved version authority

实现：

~~~text
ApprovedPlanWorkflowVersionAuthority
~~~

来源严格为：

~~~text
ApprovedActionPlan
-> exact ActionStep
-> ApprovedStepCapabilityProjector
-> ApprovedCapabilityReference.workflow.version
~~~

Checkpoint 中的 workflow_version 只作为待核对证据，不作为自己的审批来源。

禁止：

~~~text
checkpoint self-claim
Registry latest fallback
capability substitution
~~~

## 5. FI-M5-IU9-REQ-002

### Authority-sealed Tool reconciliation

Formal Runtime 不直接构造并提交 provider terminal truth。

仅调用：

~~~text
ToolResourceRecoveryCoordinator.recover(...)
~~~

该路径继续使用 CA-05：

~~~text
OperationRecoveryProbe / ProviderFenceEvidence
-> validated typed reconciliation
-> durable in-flight terminal evidence
-> exact ResourceLock reclaim
~~~

## 6. FI-M5-IU9-REQ-003

### Reconciliation before resume

`RecoveryCoordinator` 仍保持冻结顺序。

`M5RecoveryRuntime` 只有在得到 WAIT_RECONCILIATION 时才尝试一次 Tool reconciliation，然后重新调用同一个 RecoveryCoordinator。

只有第二次 decision 已经成为：

~~~text
RESUME_WORKFLOW
RETRY_STEP
RESUME_SCHEDULING
~~~

才继续运行。

未收口 Tool / ResourceLock 仍保持 WAIT。

## 7. FI-M5-IU9-REQ-004

### Current recovery epoch before side effect

新增：

~~~text
RecoverySideEffectAdmissionGuard
CurrentRecoveryEpochSideEffectAdmissionGuard
~~~

真实副作用入口：

~~~text
Skill owner execute
Workflow resume
physical Tool attempt
~~~

均在执行前重新调用：

~~~text
RecoveryClaimAuthority.validate_current(exact claim)
~~~

旧 worker 在新 claim 出现后返回 STALE/UNKNOWN，不能继续产生新副作用。

nested Tool 会在 owner admission 之后再次独立校验，不把 owner 时刻的 CURRENT 状态缓存为 Tool authority。

## 8. FI-M5-IU9-REQ-005

### Durable / CAS adapter boundary

Formal Runtime 没有 InMemory fallback。

注入依赖仍为冻结协议：

~~~text
ExecutionRecoverySnapshotStore
DurableTerminalControlStore
DurableInFlightEvidenceStore
DurableReliabilityEvidenceStore
DurableOperationResourceBindingStore
WorkflowRecoveryCheckpointStore
RecoveryClaimAuthority
~~~

仓库中的 InMemory 实现仅保留 reference / test 用途。

生产 adapter 必须保持 CA01～CA06 冻结的：

~~~text
recovery epoch fencing
CAS
monotonic revision
exact identity
durable tombstone
fail-closed uncertainty
~~~

## 9. FI-M5-IU9-REQ-006

### Re-enter IU6 / IU7 / IU8

Skill：

~~~text
RETRY_STEP
-> StepReliabilityCoordinator.run_recovered_retry
-> existing StepAttemptSequenceAuthority
-> existing replay / retry / finalization evaluators
~~~

Recovery 第一次 whole-Step replay 使用 CA-04 已给出的 RETRY_STEP authority；后续 retry 仍由 IU6 policy/replay/retry evaluator 决定。

Workflow：

~~~text
RESUME_WORKFLOW
-> StepCapabilityExecutor.resume_workflow_from_checkpoint
-> exact same workflow instance/version
-> CoreApprovedToolInvoker
~~~

Workflow 后续 Tool：

~~~text
Permission
-> IU6 reliability/idempotency
-> IU7 in-flight/control
-> IU8 ResourceLock
-> physical invoke
~~~

Control：

~~~text
durable latched CANCEL/PREEMPT
-> RecoveryControlRuntimeFactory(exact claim)
-> existing ExecutionControlCoordinator
~~~

Scheduler：

~~~text
RESUME_SCHEDULING
-> existing SequentialStepScheduler
~~~

## 10. Workflow resume boundary

`StepCapabilityExecutor.resume_workflow_from_checkpoint()` 额外验证：

~~~text
execution_id
step_execution_id
workflow_id
workflow_version
workflow_instance_id/result identity
~~~

不生成新 workflow instance，不调用 fresh start()。

## 11. Skill recovered retry boundary

`StepReliabilityCoordinator.run_recovered_retry()`：

~~~text
current durable attempt = N
-> StepAttemptSequenceAuthority.claim_next(expected=N)
-> attempt N+1
-> existing IU5 collection
-> existing IU6 reliability decision
-> subsequent retry only through existing IU6 policy
~~~

不允许 Formal Runtime 手工计算并直接执行 N+1。

## 12. Formal behavioral gates

新增：

~~~text
tests/test_m5_iu9_formal_implementation.py
~~~

当前覆盖：

~~~text
current epoch -> stale after newer claim
stale worker blocked before Skill owner invoke
nested Tool independently revalidates epoch
exact Workflow instance/version resume
Workflow version drift blocked before invoke
Workflow approved version from frozen ApprovedActionPlan
recovered Skill claims attempt N+1 through IU6 authority
~~~

CA01～CA06 原有测试继续覆盖 snapshot / evidence / lock / checkpoint / reconciliation / owner supersession。

## 13. Non-goals

~~~text
ExecutionResult aggregation       -> IU10
M6 validation                    -> later
replanning                       -> forbidden
capability substitution          -> forbidden
Registry latest fallback         -> forbidden
Skill mid-frame resume           -> forbidden
PREEMPT automatic new cycle      -> Runtime
cross-service exactly-once       -> not claimed
~~~

## 14. Current status

~~~text
M5-IU9 FORMAL IMPLEMENTATION = CODE COMPLETE
M5-IU9 FORMAL IMPLEMENTATION REVIEW = PASSED
M5-IU9 FORMAL IMPLEMENTATION VERIFICATION = PASSED

M5-IU9 = IN PROGRESS
M5 = IN PROGRESS
~~~

下一步：

~~~text
Formal Implementation Independent Review = PASSED
-> four gates = PASSED
-> Formal Implementation Verification Closure = PASSED
-> M5-IU9 Closure Evaluation
~~~

## 15. Verification Closure

绑定对象：

~~~text
PR #72
HEAD = 09856eef967f4ccda1f7223681eb6eaa62c1c99a
base review head = 25183dfea4d4540d5ceb1be7b661334b113add15
~~~

相对 base review head 的唯一新增提交：

~~~text
09856eef967f4ccda1f7223681eb6eaa62c1c99a
M5-IU9: satisfy formal implementation gates
~~~

该 delta 经 exact patch 复核：

~~~text
tests/test_m5_iu9_formal_implementation.py
- frozen Workflow plan 补显式空 tool_plan
- import / format

runtime/execution/__init__.py
- import / __all__ 排序

runtime/execution/capability_execution.py
- noqa / format

runtime/execution/recovery.py
- 去除过时 quoted annotation

runtime/execution/recovery_runtime.py
- import / format

runtime/execution/reliability_coordinator.py
- format only
~~~

未改变：

~~~text
RecoveryCoordinator frozen ordering
terminal lifecycle > control > reconciliation > resume/retry/scheduler
Tool reconciliation authority
Workflow exact resume identity/version
Skill recovered retry IU6 re-entry
current recovery epoch side-effect guard
IU7 control authority
IU8 ResourceLock authority
SequentialStepScheduler authority
~~~

四项门禁：

~~~text
python -m pytest tests -q
= 841 passed

python -m mypy runtime tests
= Success, 207 files

python -m ruff check runtime tests
= PASSED

python -m ruff format --check runtime tests
= PASSED
~~~

Closure：

~~~text
M5-IU9 FORMAL IMPLEMENTATION = CODE COMPLETE
M5-IU9 FORMAL IMPLEMENTATION REVIEW = PASSED
M5-IU9 FORMAL IMPLEMENTATION VERIFICATION = PASSED

FORMAL IMPLEMENTATION VERIFICATION CLOSURE = PASSED

M5-IU9 = IN PROGRESS
M5 = IN PROGRESS
~~~

本 Closure 不等于：

~~~text
M5-IU9 FORMAL IMPLEMENTATION = PASSED
M5-IU9 = PASSED
M5-IU9 = CLOSED
M5 = PASSED
~~~

下一步必须是：

~~~text
M5-IU9 Closure Evaluation
~~~

在该 Closure Evaluation 完成之前，不进入 M5-IU10。
