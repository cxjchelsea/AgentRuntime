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

WorkflowResumeCoordinator 在签发 resume authorization 前验证：

- current recovery epoch。
- checkpoint execution/step provenance。
- IU3 exact resolved Workflow owner。
- WorkflowDefinition.checkpoint_enabled = true。
- resume_policy 明确存在。
- exact workflow id/version。
- current ExecutionContext execution identity。

CA-04 不直接调用 resume。Formal Implementation 经既有 StepCapabilityExecutor 执行后，如 resume 返回 WAITING，只得到新的 WAITING observation；仍必须再次 durable checkpoint commit 后才能再次恢复。

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
- authorization keeps same instance + exact version + exact checkpoint material，且 CA-04 不直接调用 provider。
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


## 13. Targeted Amendment Review findings

本轮独立审查发现并修复三项恢复一致性问题：

### F-M5-IU9-CA04-001 CHECKPOINT_EXACT_REPLAY_COULD_REPEAT_DOMAIN_PERSISTENCE

初版在 Core CAS 检测 exact replay 前先调用 Domain checkpoint adapter。若重复提交同一 checkpoint，会重复执行 Domain 持久化。

修复：

~~~text
Core read_latest preflight
-> exact checkpoint replay returns ALREADY_COMMITTED
-> Domain adapter is not called again
~~~

同时冻结 crash window：若崩溃发生在 Domain state 已持久化、Core checkpoint 尚未 CAS commit 之间，adapter 必须以 exact `checkpoint_id + generation + workflow instance/version` 实现幂等；只能返回同一 durable material 或 fail closed。

~~~text
F-M5-IU9-CA04-001 = CLOSED_BY_IMPLEMENTATION
~~~

### F-M5-IU9-CA04-002 RESUME_COULD_USE_NON_LATEST_CHECKPOINT

初版 WorkflowResumeCoordinator 只验证传入 checkpoint 的结构/provenance，没有重新读取 durable store 证明它仍是当前 latest checkpoint。

修复：

~~~text
read_latest(execution_id, step_execution_id)
-> exact equality with requested checkpoint
-> only then resume eligibility continues
~~~

旧 generation / 非 latest checkpoint -> UNKNOWN，不调用 Workflow implementation。

~~~text
F-M5-IU9-CA04-002 = CLOSED_BY_IMPLEMENTATION
~~~

### F-M5-IU9-CA04-003 RECOVERY_EPOCH_TOCTOU_BEFORE_RESUME_AUTHORIZATION

初版只在 resume 流程入口校验 recovery epoch。checkpoint read / capability validation 期间可能发生新的 recovery takeover，导致 stale owner 仍获得 resume authority。

修复为 authorization 返回前二次 epoch gate：

~~~text
initial current-epoch check
-> latest checkpoint + exact version validation
-> build exact WorkflowResumeRequest
-> validate current epoch AGAIN
-> only CURRENT may receive AUTHORIZED
~~~

Formal Implementation 在真正外部调用前仍必须再次校验 current recovery claim；CA-04 的 authorization 不能替代 side-effect admission gate。

~~~text
F-M5-IU9-CA04-003 = CLOSED_BY_IMPLEMENTATION
~~~

### F-M5-IU9-CA04-004 RESUME_BYPASSED_EXISTING_EXECUTION_BOUNDARY

初版 WorkflowResumeCoordinator 直接调用 WorkflowImplementation.resume()，形成了独立于 StepCapabilityExecutor 的第二条执行路径，可能绕过：

~~~text
owner in-flight registration
CoreApprovedToolInvoker
IU7 interrupt/control tracking
IU8 session/resource concurrency boundary
existing permission/tool validation path
~~~

这与 IU9 已冻结的“recovery re-enters existing IU6/IU7/IU8 boundaries”冲突。

修复：

~~~text
RecoveryCoordinator
-> RESUME_WORKFLOW decision
-> WorkflowResumeCoordinator.authorize()
-> exact WorkflowResumeRequest + recovery claim authority only
-> NO provider invocation inside CA-04
-> M5-IU9 Formal Implementation must re-enter existing StepCapabilityExecutor boundary
~~~

同时冻结 WorkflowImplementation.resume exact replay 合同：同一 checkpoint_id / generation / resume_token 的重放必须幂等或可外部对账，不能把 crash 后的盲重放当成安全。

~~~text
F-M5-IU9-CA04-004 = CLOSED_BY_ARCHITECTURE_CORRECTION
~~~

## 14. Blocker mapping

实现目标：

~~~text
B-M5-IU9-006 -> FIX IMPLEMENTED, targeted review required
B-M5-IU9-007 -> FIX IMPLEMENTED, targeted review required
~~~

只有 Targeted Amendment Review + four gates 全绿后才能写 CLOSED / PASSED。

## 15. Frozen non-goals

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

## 16. Current status

~~~text
CA-M5-IU9-04 = CODE COMPLETE
CA-M5-IU9-04 TARGETED AMENDMENT REVIEW = IN_PROGRESS
CA-M5-IU9-04 VERIFICATION = PENDING

B-M5-IU9-001..005 = CLOSED
B-M5-IU9-006 = FIX_IMPLEMENTED_PENDING_REVIEW
B-M5-IU9-007 = FIX_IMPLEMENTED_PENDING_REVIEW

M5-IU9 IMPLEMENTATION READINESS = NOT_READY
NEXT REQUIRED = CA-M5-IU9-04 Targeted Amendment Review + Verification
M5 = IN PROGRESS
~~~
