# M5-IU7 Implementation Readiness Review V1.0

> Review target：M5-IU7 Cancellation / Preemption。
> Baseline：M5-IU1～IU6 = PASSED；M5 Remaining IU Mapping 已冻结。
> 本 Review 只判断是否具备安全进入 IU7 Formal Implementation 的合同，不实现运行时控制。

## 1. Readiness conclusion

~~~text
M5-IU7 IMPLEMENTATION DESIGN = COMPLETE
M5-IU7 IMPLEMENTATION READINESS = NOT_READY

BLOCKERS = 5
FORMAL IMPLEMENTATION = NOT AUTHORIZED
~~~

当前系统已经能够在 Step 开始前识别 `CANCEL_REQUIRED / PREEMPT_REQUIRED`，但还不能安全地把运行中的 execution 终止为 CANCELLED / PREEMPTED。

## 2. B-M5-IU7-001 CONTROL_SIGNAL_ENVELOPE_NOT_AUDITABLE

当前 `ExecutionControlSignal` 只有：

~~~text
signal_type
reason_code
source
~~~

缺少：

~~~text
signal_id
target_execution_id
issued_at
~~~

这意味着 IU7 无法可靠完成：

~~~text
控制事件去重
重复 signal 幂等应用
wrong-target rejection
signal 与 operation completion 的事实排序
控制审计 / trace 绑定
~~~

`ExecutionControlSignalSource.get_signal(execution_id)` 的调用参数不足以替代 signal 自身的 immutable authority identity。

结论：

~~~text
B-M5-IU7-001 = OPEN
REQUIRES CA-M5-IU7-01
~~~

## 3. B-M5-IU7-002 INFLIGHT_CONTROL_WATCH_AND_LATCH_MISSING

当前 `RuntimeExecutionChecker` 只在进入 Step 前调用：

~~~text
ExecutionControlSignalSource.get_signal(execution_id)
~~~

因此当前只能做到：

~~~text
“开始下一步之前发现取消/抢占”
~~~

做不到：

~~~text
Tool.invoke 正在 await 时收到 USER_STOP
Skill.execute 正在 await 时收到 PREEMPT
Workflow.start 正在 await 时收到 SAFETY_OVERRIDE
~~~

此外当前没有 control latch。

如果一次 CANCEL 已被接受，而下一次 source 暂时返回 NONE，系统理论上可能继续调度后续 Step。

需要冻结：

~~~text
ExecutionControlWatcher
ExecutionControlLatch
~~~

`ExecutionContext.cancellation_token` 当前只是 opaque string/correlation token，不能当成 active cancellation primitive。

结论：

~~~text
B-M5-IU7-002 = OPEN
REQUIRES CA-M5-IU7-01
~~~

## 4. B-M5-IU7-003 INFLIGHT_OPERATION_INTERRUPT_AUTHORITY_MISSING

当前 Tool / Skill / Workflow invocation 都是直接 await。

系统没有：

~~~text
active operation registry
exact hierarchical in-flight handle chain
interrupt authority
confirmed-stop outcome
~~~

并且当前 Skill/Workflow 内部调用 Tool 时会形成父子嵌套执行：

~~~text
Skill/Workflow owner
→ Core Tool gateway
→ Tool invocation
~~~

因此只记录一个 active handle 不足以保证 control 真正停止整个 owner execution。

现有 ToolImplementation / SkillImplementation / WorkflowImplementation 也没有统一 cancellation handle。

因此现在如果收到 control signal，无法区分：

~~~text
已经安全停止
其实已经完成
不可取消但仍在运行
状态未知 / side effect 可能已发生
~~~

不能把 Python task cancellation 或 coroutine cancellation 临时等同于业务 Tool 已停止。

需要冻结：

~~~text
InFlightOperationHandle(parent_handle_id)
InFlightOperationRegistry(active_chain)
ExecutionInterruptController
InterruptOutcome
leaf-first then parent interrupt ordering
multiple active leaves -> fail closed / deferred to IU8
~~~

结论：

~~~text
B-M5-IU7-003 = OPEN
REQUIRES CA-M5-IU7-02
~~~

## 5. B-M5-IU7-004 CONTROL_LIFECYCLE_TERMINALIZATION_INCOMPLETE

现有生命周期存在结构性缺口：

~~~text
ExecutionLifecycleService.finish_step
只允许 RUNNING -> terminal
~~~

但 CANCEL/PREEMPT 时通常还有多个：

~~~text
PENDING Step
~~~

同时：

~~~text
ExecutionLifecycleService.finish_execution
要求所有 Step 已 terminal
~~~

所以当前没有合法路径把：

~~~text
RUNNING/PENDING execution
→ fully terminal CANCELLED/PREEMPTED execution
~~~

直接逐个调用 `finish_step` 也不成立，因为 PENDING Step 从未开始。

需要新的 control-specific pure transition boundary，保证：

~~~text
terminal Step 原样保留
running Step 仅在 safe interrupt evidence 后终态
pending Step 记录为因 control 未开始
execution 最终映射 CANCELLED/PREEMPTED
~~~

结论：

~~~text
B-M5-IU7-004 = OPEN
REQUIRES CA-M5-IU7-03
~~~

## 6. B-M5-IU7-005 CONTROL_APPLICATION_UNCERTAINTY_OUTCOME_MISSING

当前没有 typed control application result。

如果中断返回：

~~~text
NOT_CANCELLABLE
UNKNOWN
ALREADY_COMPLETED
~~~

现有合同无法表达：

~~~text
现在应继续等待
是否可以 terminalize
running result 是否已经真正写回 lifecycle
running result 是否必须保留
PREEMPT 是否需要 Runtime handoff
control 是否真的影响了 unfinished work
late control 是否必须 no-op
控制冲突是否需要 fail closed
~~~

若直接在 coordinator 中用 bool/exception 分支，很容易出现：

~~~text
interrupt requested
→ 被错误解释成 CANCELLED
~~~

需要冻结：

~~~text
ExecutionControlDisposition
ExecutionControlApplication
~~~

明确：

~~~text
WAITING_IN_FLIGHT
READY_TO_TERMINALIZE
ALREADY_TERMINAL
CONFLICT
UNKNOWN
~~~

结论：

~~~text
B-M5-IU7-005 = OPEN
REQUIRES CA-M5-IU7-02
~~~

## 7. Existing contracts that are reusable

以下已有基础设施方向正确，不是 blocker：

~~~text
ExecutionControlSignalType.NONE/CANCEL/PREEMPT
ExecutionControlSignalSource
RuntimeExecutionCheckStatus.CANCEL_REQUIRED/PREEMPT_REQUIRED
RuntimeExecutionChecker precedence
ExecutionContext.cancellation_token correlation field
PreparedExecution / StepLifecycleSnapshot
StepExecutionStatus.CANCELLED/PREEMPTED
ExecutionPlanStatus.CANCELLED/PREEMPTED
ExecutionLifecycleService persistence boundary
IU6 Tool journal / StepAttemptObservation
~~~

问题不是“完全没有控制能力”，而是缺少从 **resolved signal → live interrupt → safe lifecycle terminalization** 的中间 authority。

## 8. Non-blocking deferred debts

### TD-M5-IU7-01 RESOURCE_LOCK_RELEASE_DEFERRED_TO_IU8

IU7 不提前实现：

~~~text
session/resource lock policy
resource lock stealing
lock ownership recovery
~~~

operation-local interrupt cleanup 可以由 adapter 完成；统一 ResourceLockProvider policy 属于 IU8。

### TD-M5-IU7-02 DURABLE_CONTROL_RECOVERY_DEFERRED_TO_IU9

IU7 第一版只冻结 live control。

以下正式后置：

~~~text
durable control latch
crash during cancellation/preemption
persisted in-flight registry
restart/recovery
~~~

属于 IU9。

## 9. Controlled Amendment plan

### CA-M5-IU7-01 Control Signal Identity + Watch/Latch

必须冻结：

~~~text
auditable ExecutionControlSignal envelope
signal_id / target execution / issued_at
ExecutionControlWatcher
ExecutionControlLatch
same-signal idempotency
conflicting-signal fail-closed
Core observed_at/latched_at time authority; upstream issued_at is audit-only
~~~

不得：

~~~text
compare priority
recompute Policy
recompute timeout
start Runtime cycle
~~~

### CA-M5-IU7-02 In-Flight Interrupt + Control Application Outcome

必须冻结：

~~~text
InFlightOperationKind
InFlightOperationHandle
InFlightOperationRegistry
ExecutionInterruptController
InterruptOutcome
hierarchical interrupt summary
ExecutionControlDisposition
ExecutionControlApplication
nonterminal_step_ids_at_latch / affected_step_ids
ALREADY_COMPLETED lifecycle reconciliation
late-control no-retroactive-rewrite rule
side-effect preservation semantics
preemption handoff_required semantics
~~~

要求：

~~~text
interrupt requested != interrupt confirmed
nested execution -> leaf Tool first, then parent owner
UNKNOWN interrupt != terminal lifecycle
NOT_CANCELLABLE -> barrier + wait
ALREADY_COMPLETED + Step still RUNNING -> WAITING_IN_FLIGHT
ALREADY_COMPLETED + lifecycle committed -> preserve actual result
all work already terminal -> ALREADY_TERMINAL / no lifecycle rewrite
no affected_step_ids -> no retrospective CANCELLED/PREEMPTED
~~~

### CA-M5-IU7-03 Control Lifecycle Terminalization Boundary

必须冻结：

~~~text
Control Lifecycle Transitioner
running Step control terminalization rule
pending Step control terminalization rule
terminal Step preservation
execution CANCELLED/PREEMPTED mapping
single persistence boundary / no partial rewrite
~~~

要求：

~~~text
already terminal results never rewritten
PENDING != FAILED
UNKNOWN interrupt cannot terminalize
control does not erase IU6 evidence
~~~

## 10. Frozen non-goals for IU7

即使 readiness 以后变成 READY，IU7 也不得进入：

~~~text
Resource Lock policy                    -> IU8
Checkpoint / Crash Recovery             -> IU9
Workflow resume                         -> IU9
canonical ExecutionResult aggregation   -> IU10
M6                                      -> after M5 closure
Runtime new-cycle start after PREEMPT   -> Runtime orchestration
~~~

## 11. Readiness Re-Review Gate

只有以下全部满足，才能写：

~~~text
M5-IU7 IMPLEMENTATION READINESS = READY
~~~

条件：

~~~text
1. CA-M5-IU7-01 Targeted Review = PASSED
2. CA-M5-IU7-01 four local gates = GREEN
3. CA-M5-IU7-02 Targeted Review = PASSED
4. CA-M5-IU7-02 four local gates = GREEN
5. CA-M5-IU7-03 Targeted Review = PASSED
6. CA-M5-IU7-03 four local gates = GREEN
7. B-M5-IU7-001～005 全部 CLOSED
8. M5 仍不比较 priority / 不重算 M2
9. interrupt requested 不能直接映射 terminal
10. nested Tool/owner chain 必须有确定 interrupt order
11. ALREADY_COMPLETED 不能绕过真实 lifecycle completion
12. completed side effects/results 不被 control 重写
13. late control 不得回写 CANCELLED/PREEMPTED
14. execution control status 必须有 affected_step_ids 证据
15. PREEMPT 不直接启动新 Runtime cycle
16. IU8/IU9/IU10/M6 边界未被突破
~~~

## 12. Current Formal Status

~~~text
M5-IU1 = PASSED
M5-IU2 = PASSED
M5-IU3 = PASSED
M5-IU4 = PASSED
M5-IU5 = PASSED
M5-IU6 = PASSED

M5 REMAINING IU MAPPING = FROZEN

M5-IU7 IMPLEMENTATION DESIGN = COMPLETE
M5-IU7 IMPLEMENTATION READINESS = NOT_READY

B-M5-IU7-001 = OPEN
B-M5-IU7-002 = OPEN
B-M5-IU7-003 = OPEN
B-M5-IU7-004 = OPEN
B-M5-IU7-005 = OPEN

NEXT REQUIRED = CA-M5-IU7-01
M5 = IN PROGRESS
~~~