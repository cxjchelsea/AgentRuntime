# CA-M5-IU9-04 Workflow Checkpoint + Recovery Decision / Resume V1.0

> Base：CA-M5-IU9-03 PASSED @ 7320785ddfb5b980e3d18b7da91dd12c14e7082e
> Target blockers：
> - B-M5-IU9-006 WORKFLOW_CHECKPOINT_RESUME_AUTHORITY_INCOMPLETE
> - B-M5-IU9-007 RECOVERY_DECISION_ORCHESTRATOR_MISSING

## 1. 目标

本 CA 只补齐 IU9 最后两个 readiness blocker：

~~~text
exact durable Workflow checkpoint authority
+ exact Workflow resume request
+ whole-recovery typed disposition
+ fail-closed recovery ordering
~~~

不进入 IU10 ExecutionResult aggregation、M6、重新规划、Capability substitution 或 PREEMPT 后新 Runtime cycle。

## 2. Workflow durable checkpoint

新增：

~~~text
WorkflowRecoveryCheckpointStatus
WorkflowRecoveryCheckpoint
WorkflowCheckpointWriteStatus
WorkflowCheckpointWriteDecision
WorkflowRecoveryCheckpointStore
InMemoryWorkflowRecoveryCheckpointStore
~~~

Checkpoint 必须绑定：

~~~text
checkpoint_id
generation
execution_id
step_execution_id
workflow_instance_id
workflow_id
workflow_version
state_reference
resume_token
committed_at
writer_recovery_epoch
~~~

Domain/Workflow 内部状态继续由 adapter 保存；Core 只保存 opaque state_reference / resume_token。

## 3. WAITING durable-commit rule

冻结：

~~~text
Workflow returned WAITING
!= resumable Workflow

resumable Workflow
= exact WAITING checkpoint
+ durable commit
+ current recovery epoch
+ exact execution / step / instance / id / version provenance
~~~

没有 durable checkpoint 时：

~~~text
WAIT_RECONCILIATION
~~~

不得生成新 workflow_instance_id，不得重新 start()。

## 4. Exact Workflow resume

新增：

~~~text
WorkflowResumeRequest
WorkflowRecoveryImplementation
WorkflowVersionAuthority
~~~

WorkflowResumeRequest 必须保留 exact：

~~~text
execution_id
step_execution_id
workflow_instance_id
workflow_id
workflow_version
checkpoint_id
checkpoint_generation
state_reference
resume_token
~~~

WorkflowVersionAuthority 只允许返回 ApprovedPlan 已冻结的 exact Workflow version，不允许 latest-version fallback。

Checkpoint version 与 approved version 不一致：

~~~text
UNKNOWN_BLOCKED
~~~

## 5. Skill crash recovery

新增恢复侧投影接口：

~~~text
StepRecoveryReplayStatus
StepRecoveryReplayDecision
StepRecoveryReplayEvaluator
~~~

它不重写 IU6 规则，只消费 IU6 whole-Step replay safety 的恢复投影：

~~~text
SAFE    -> RETRY_STEP
UNSAFE  -> WAIT_RECONCILIATION
UNKNOWN -> UNKNOWN_BLOCKED
~~~

不新增 Skill mid-frame resume。

## 6. RecoveryDisposition

冻结：

~~~text
TERMINAL_NO_ACTION
APPLY_LATCHED_CONTROL
RESUME_SCHEDULING
RESUME_WORKFLOW
RETRY_STEP
WAIT_RECONCILIATION
UNKNOWN_BLOCKED
~~~

这些只是 recovery authority，不是 ExecutionResult，也不是 M6 truth。

## 7. RecoveryCoordinator 顺序

严格：

~~~text
1. validate current RecoveryClaim / epoch
2. load exact source recovery snapshot
3. authoritative terminal lifecycle
4. durable terminal control latch
5. crash-active in-flight -> orphan transition
6. unresolved in-flight -> WAIT_RECONCILIATION
7. unresolved active resource binding -> WAIT_RECONCILIATION
8. exact running Workflow + durable checkpoint + exact approved version -> RESUME_WORKFLOW
9. running Skill + IU6 replay SAFE -> RETRY_STEP
10. no running Step -> RESUME_SCHEDULING
11. inconsistency / unknown -> UNKNOWN_BLOCKED
~~~

因此：

~~~text
terminal lifecycle > control > side-effect reconciliation > Workflow resume / Skill retry / scheduler
~~~

Checkpoint 不得覆盖更强 durable side evidence。

## 8. Recovery does not bypass existing runtime boundaries

RESUME_WORKFLOW 只授权进入 exact checkpoint resume path。

真实 resumed Workflow 的后续 Tool 调用仍必须经过既有：

~~~text
Permission
-> IU6 reliability / idempotency
-> IU7 in-flight/control
-> IU8 resource locking
~~~

CA-04 不提供任何 bypass。

RETRY_STEP 同样只授权回到 IU6 existing Step replay path。

RESUME_SCHEDULING 只允许回到 existing SequentialStepScheduler，不重排、不跳 Step、不改 ApprovedPlan。

## 9. Fail-closed rules

~~~text
stale recovery epoch                  -> UNKNOWN_BLOCKED
snapshot generation drift             -> UNKNOWN_BLOCKED
control store unknown                 -> UNKNOWN_BLOCKED
multiple RUNNING steps                -> UNKNOWN_BLOCKED
workflow checkpoint lookup unknown    -> UNKNOWN_BLOCKED
workflow exact checkpoint absent      -> WAIT_RECONCILIATION
workflow approved version unknown     -> UNKNOWN_BLOCKED
workflow version mismatch             -> UNKNOWN_BLOCKED
orphan external operation unresolved  -> WAIT_RECONCILIATION
active resource binding remains       -> WAIT_RECONCILIATION
Skill replay UNSAFE                   -> WAIT_RECONCILIATION
Skill replay UNKNOWN                  -> UNKNOWN_BLOCKED
~~~

## 10. Verification scenarios

新增 tests/test_m5_iu9_ca04_workflow_recovery.py，至少覆盖：

~~~text
checkpoint current recovery epoch commit
exact checkpoint replay idempotency
resume request exact instance/version identity
terminal lifecycle wins before resume
durable terminal control wins before resume
WAITING Workflow without durable checkpoint never resumes
exact checkpoint + approved version -> RESUME_WORKFLOW
checkpoint version mismatch -> UNKNOWN_BLOCKED
running Skill consumes injected IU6 replay safety
no RUNNING Step -> RESUME_SCHEDULING
~~~

## 11. Blocker mapping

实现目标：

~~~text
B-M5-IU9-006 -> CLOSED_PENDING_GATES
B-M5-IU9-007 -> CLOSED_PENDING_GATES
~~~

只有 Targeted Review 与四项门禁全部通过后才能改为 CLOSED。

## 12. Frozen non-goals

~~~text
ExecutionResult aggregation          -> IU10
M6 result validation                 -> after M5
replanning / capability substitution -> forbidden in Recovery
business Workflow state schema       -> Domain/adapter
blind TTL lock stealing              -> forbidden
distributed exactly-once             -> not claimed
PREEMPT next Runtime cycle           -> Runtime
~~~

## 13. Current status

~~~text
CA-M5-IU9-04 = CODE COMPLETE
CA-M5-IU9-04 TARGETED AMENDMENT REVIEW = PENDING
CA-M5-IU9-04 VERIFICATION = PENDING

B-M5-IU9-006 = CLOSED_PENDING_GATES
B-M5-IU9-007 = CLOSED_PENDING_GATES

M5-IU9 IMPLEMENTATION READINESS = NOT_READY
NEXT REQUIRED = CA-M5-IU9-04 Targeted Amendment Review + Verification
M5 = IN PROGRESS
~~~
