# CA-M5-IU9-04 Workflow Checkpoint + Recovery Decision / Resume V1.0

> Base: CA-M5-IU9-03 PASSED @ 7320785ddfb5b980e3d18b7da91dd12c14e7082e  
> Target blockers: B-M5-IU9-006 / B-M5-IU9-007

## 1. 目标

CA-04 只关闭：

~~~text
B-M5-IU9-006 WORKFLOW_CHECKPOINT_RESUME_AUTHORITY_INCOMPLETE
B-M5-IU9-007 RECOVERY_DECISION_ORCHESTRATOR_MISSING
~~~

不进入 IU10 ExecutionResult aggregation、M6、replanning、priority recomputation 或 PREEMPT 后新 Runtime cycle。

## 2. WAITING durable-commit rule

冻结：

~~~text
Workflow result = WAITING
        ↓
current recovery epoch validation
        ↓
Domain / Workflow adapter durably persists opaque state
        ↓
Core CAS-commits exact WorkflowRecoveryCheckpoint
        ↓
only now WAITING is resumable
~~~

普通 WAITING observation 本身不构成 resume authority。

## 3. WorkflowRecoveryCheckpoint

新增 exact durable provenance：

~~~text
execution_id
step_id
step_execution_id
workflow_instance_id
workflow_id
workflow_version
checkpoint_id
generation
state_reference
resume_token
state_schema_version
committed_at
writer_recovery_epoch
writer_recovery_owner_id
~~~

Core 只保存 opaque state reference / resume token，不把业务 Workflow state schema 塞进 Core。

## 4. Checkpoint CAS / fencing

规则：

- generation 单调递增。
- checkpoint_id immutable。
- exact replay -> ALREADY_COMMITTED。
- same checkpoint_id different payload -> CONFLICT。
- provenance drift -> CONFLICT。
- stale recovery epoch cannot commit。
- stale epoch 在调用 Domain checkpoint adapter 前就被拒绝。

## 5. WorkflowResumeRequest

resume 不再复用普通 start request 的语义，新增 exact resume envelope：

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
checkpoint_schema_version
event?
inputs
~~~

Resume 必须保持：

~~~text
same workflow_instance_id
same workflow_id
same approved workflow_version
exact committed checkpoint generation
~~~

不允许 latest-version fallback / capability substitution / new instance restart。

## 6. Workflow resume gate

WorkflowResumeCoordinator 在调用实现前验证：

- current recovery epoch。
- checkpoint execution/step provenance。
- IU3 exact resolved Workflow owner。
- WorkflowDefinition.checkpoint_enabled = true。
- resume_policy 明确存在。
- exact workflow id/version。
- current ExecutionContext execution identity。

resume 返回 WAITING 时，只得到一次新的 WAITING observation；仍必须再次 durable checkpoint commit 后才能再次恢复。

## 7. Skill crash recovery

CA-04 不发明 Skill mid-frame resume。

新增 IU6SkillRecoveryReplayAuthority adapter：

~~~text
durable recovery evidence
→ StepReplaySafetyRequest
→ existing IU6 StepReplaySafetyEvaluator
→ SAFE only
→ existing StepAttemptSequenceAuthority.claim_next
→ RETRY_STEP
~~~

UNSAFE -> WAIT_RECONCILIATION。  
UNKNOWN / missing evidence -> UNKNOWN_BLOCKED。

## 8. RecoveryDisposition

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

它们是恢复授权，不是 ExecutionResult。

## 9. RecoveryCoordinator ordering

严格顺序：

~~~text
1. validate current recovery epoch
2. authoritative terminal lifecycle
3. durable terminal control latch
4. ACTIVE_AT_CHECKPOINT -> ORPHANED_UNCONFIRMED
5. external operation reconciliation
6. ResourceLock / operation-resource reconciliation
7. exact Workflow checkpoint
8. Skill replay safety
9. existing SequentialStepScheduler re-entry
~~~

禁止 Workflow resume / Skill retry / Scheduler re-entry 越过 control 或 unresolved external operation。

## 10. External operation rule

crash-time nonterminal operation 必须由 exact OperationRecoveryProbe 给出强证据：

~~~text
COMPLETED_CONFIRMED
STOPPED_CONFIRMED
NOT_FOUND_WITH_PROOF
~~~

否则 WAIT_RECONCILIATION。

如果 CA-03 provider fencing 成功并已 durable commit / reclaim，则可作为旧 provider operation 无法继续提交副作用的安全边界。

## 11. Resource rule

存在 active operation-resource binding 时不得进入 resume/retry/scheduler。

Tool resource 继续复用 CA-03 ToolResourceRecoveryCoordinator；CA-04 不增加 TTL/PID/heartbeat lock stealing。

## 12. Targeted verification scenarios

本轮测试覆盖：

- WAITING without durable checkpoint is not resumable。
- stale recovery epoch cannot checkpoint，且不会调用 Domain state adapter。
- exact checkpoint generation/provenance commit。
- resume keeps same instance + exact version + exact checkpoint material。
- latched CANCEL outranks Workflow resume。
- exact durable Workflow checkpoint authorizes RESUME_WORKFLOW。
- no running Step + pending work only re-enters existing Scheduler。

Formal verification 仍需四项门禁：

~~~text
python -m pytest tests -q
python -m mypy runtime tests
python -m ruff check runtime tests
python -m ruff format --check runtime tests
~~~

## 13. Blocker mapping

实现目标：

~~~text
B-M5-IU9-006 -> FIX IMPLEMENTED, targeted review required
B-M5-IU9-007 -> FIX IMPLEMENTED, targeted review required
~~~

只有 Targeted Amendment Review + four gates 全绿后才能写 CLOSED / PASSED。

## 14. Frozen non-goals

~~~text
ExecutionResult aggregation -> IU10
M6 validation -> after M5 closure
replanning -> M2/M4/Runtime
priority recomputation -> M2/Runtime
PREEMPT new-cycle start -> Runtime
business Workflow state schema -> Domain / Workflow adapter
blind TTL lock stealing -> forbidden
distributed global transaction -> not claimed
~~~

## 15. Current status

~~~text
CA-M5-IU9-04 = CODE COMPLETE
CA-M5-IU9-04 TARGETED AMENDMENT REVIEW = PENDING
CA-M5-IU9-04 VERIFICATION = PENDING

B-M5-IU9-001..005 = CLOSED
B-M5-IU9-006 = FIX_IMPLEMENTED_PENDING_REVIEW
B-M5-IU9-007 = FIX_IMPLEMENTED_PENDING_REVIEW

M5-IU9 IMPLEMENTATION READINESS = NOT_READY
NEXT REQUIRED = CA-M5-IU9-04 Targeted Amendment Review + Verification
M5 = IN PROGRESS
~~~
