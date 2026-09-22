# M5-IU7 Cancellation / Preemption 实现设计 V1.0

> Mapping：M5-IU7 = M5 V2.0 Step 9。
> Baseline：M5-IU1～IU6 = PASSED。
> Goal：消费已经由 Runtime/M2 解析好的 CANCEL / PREEMPT authority，停止后续执行并在安全边界终止当前 execution；IU7 不比较 priority、不重算 Policy、不重新解释 IU6 timeout/retry。

## 1. IU7 正式目标

~~~text
Resolved Execution Control Signal
        ↓
Control Identity / Target Check
        ↓
Latch Execution Control Barrier
        ↓
Observe current Step / in-flight operation
        ↓
Request interrupt if possible
        ↓
Preserve already-observed side effects/results
        ↓
Wait / Fail closed / terminalize at safe boundary
        ↓
Control Lifecycle Transition
        ↓
CANCELLED / PREEMPTED Execution
        ↓
return control evidence / preemption handoff requirement
~~~

核心原则：

~~~text
Cancellation != rollback
Preemption != priority recomputation
Control signal != lifecycle mutation
Interrupt requested != interrupt confirmed
UNKNOWN interrupt != CANCELLED/PREEMPTED
Already completed side effect != reversible
PREEMPTED execution != start next Runtime cycle
~~~

## 2. Upstream authority

IU7 只消费已经解析好的：

~~~text
ExecutionControlSignalType.CANCEL
ExecutionControlSignalType.PREEMPT
~~~

来源可以包括：

~~~text
USER_STOP
SESSION_END
SYSTEM_SHUTDOWN
TIMEOUT
SAFETY_OVERRIDE
HIGH_PRIORITY_PREEMPTION
~~~

但这些 reason 只是上游控制事实。

IU7 禁止：

~~~text
比较 priority
重新运行 M2
重新计算 Safety
重新解释 timeout_policy
把 UNKNOWN signal 升格为 CANCEL/PREEMPT
~~~

## 3. Control signal envelope

当前 ExecutionControlSignal 只有：

~~~text
signal_type
reason_code
source
~~~

正式终止 execution 前需要可审计 envelope，建议冻结：

~~~text
ExecutionControlSignal
- signal_id
- target_execution_id
- signal_type
- reason_code
- source
- issued_at

LatchedExecutionControl
- signal
- observed_at
- latched_at
~~~

NONE 可以保持无 signal identity；CANCEL/PREEMPT 必须具备 immutable signal identity。

规则：

~~~text
signal.target_execution_id
== ExecutionContext.execution_id
~~~

否则 fail closed。

`issued_at` 主要用于上游审计，不作为跨时钟域的唯一排序依据。IU7 自己通过注入式 Core clock 记录 `observed_at / latched_at`；控制与本地 operation/lifecycle evidence 的先后判断优先使用同一 Core time source。M5 仍不利用这些时间重新决定控制优先级。

## 4. cancellation_token 的正式定位

现有：

~~~text
ExecutionContext.cancellation_token = execution_id
~~~

它目前只是 opaque correlation token，不是一个可以 set()/cancel() 的运行对象。

IU7 不得把这个 string 假装成 active cancellation primitive。

运行中 control 必须由独立注入式 watcher/controller 提供。

## 5. Execution Control Latch

一旦 execution 接受 CANCEL/PREEMPT：

~~~text
不得因为下一次 source 返回 NONE 就恢复执行
~~~

因此新增：

~~~text
ExecutionControlLatch
~~~

职责：

~~~text
latch exact control signal
return already-latched signal
detect conflicting later signal
prevent scheduler from starting new Step after control accepted
~~~

第一版冻结：

~~~text
first terminal control signal wins inside M5
same signal replay = idempotent
different later signal = CONFLICT / UNKNOWN
~~~

M5 不自行决定 CANCEL 与 PREEMPT 谁优先。

## 6. In-flight observation

当前 RuntimeExecutionChecker 只在 Step 开始前读取 control signal。

IU7 还必须覆盖：

~~~text
Tool 正在 await
Skill.execute 正在 await
Workflow.start 正在 await
~~~

因此新增 live control contract：

~~~text
ExecutionControlWatcher
~~~

建议：

~~~text
wait_for_terminal_signal(execution_id, cancellation_token)
-> exact CANCEL/PREEMPT signal
~~~

Core 不把 polling cadence 写死在 IU7 coordinator；poll/subscription 由 watcher implementation 负责。

## 7. In-flight operation identity

要取消当前运行操作，必须知道当前到底在执行什么。

新增：

~~~text
InFlightOperationKind
- TOOL
- SKILL
- WORKFLOW

InFlightOperationHandle
- operation_handle_id
- execution_id
- step_execution_id
- parent_handle_id?
- kind
- capability_id
- capability_version
- tool_call_id? / workflow_instance_id?
- started_at
~~~

并新增：

~~~text
InFlightOperationRegistry
~~~

职责：

~~~text
register active operation
read exact active operation chain
mark operation completed
never discover/substitute capabilities
~~~

同一个 Step 可能存在嵌套 in-flight 链：

~~~text
Skill.execute
  ↓
CoreApprovedToolInvoker
  ↓
Tool.invoke
~~~

因此 Registry 不能只返回“某一个 active handle”，而必须能返回同一 `step_execution_id` 的**唯一父子 active chain**。

正式要求：

~~~text
owner Skill/Workflow = parent
nested Tool = child/leaf
no cycles
no multiple active leaves for IU7 sequential baseline
~~~

Control interrupt 顺序冻结为：

~~~text
leaf Tool first
→ then parent owner task/operation
~~~

原因不是业务 priority，而是执行结构：只停止子 Tool 不足以保证父 Skill/Workflow 不继续执行。

durable registry/recovery 属于 IU9；IU7 第一版只要求 live authority。

## 8. Interrupt authority

新增：

~~~text
ExecutionInterruptController
~~~

输出：

~~~text
CONFIRMED_STOPPED
ALREADY_COMPLETED
NOT_CANCELLABLE
UNKNOWN
~~~

语义：

### CONFIRMED_STOPPED

~~~text
当前 in-flight operation 已确认停止
→ 可以进入 control terminalization
~~~

### ALREADY_COMPLETED

~~~text
operation 在 interrupt 生效前已完成
→ 保留真实 completion/result
→ 只停止后续 Step
~~~

但 `ALREADY_COMPLETED` **本身不等于 lifecycle 已经完成**。

只有当 owner 的真实 completion/result 已经通过现有 result/lifecycle authority 写回，当前 Step 不再是 RUNNING，IU7 才能继续 terminalize 剩余 PENDING Steps。

如果 interrupt controller 报 `ALREADY_COMPLETED`，但 lifecycle 仍是 RUNNING：

~~~text
→ WAITING_IN_FLIGHT
→ 等待真实 completion observation/lifecycle commit
→ 不得猜测 Step terminal status
~~~

### NOT_CANCELLABLE

~~~text
当前 operation 不能安全中断
→ 不得伪装成 CANCELLED/PREEMPTED
→ latch control barrier
→ 等待当前 operation 到达真实 terminal boundary
~~~

### UNKNOWN

~~~text
无法确认当前 operation 是否停止/是否产生 side effect
→ fail closed
→ 不得 terminalize running Step
~~~

## 9. Side-effect preservation

正式不变量：

~~~text
已经成功发生的 Tool side effect
不会因为后续 CANCEL/PREEMPT 被改写成“未发生”
~~~

例如：

~~~text
notification SUCCESS
↓
USER_STOP
↓
notification result remains SUCCESS
remaining work stops
execution may become CANCELLED
~~~

IU7 只控制未来动作和当前可安全中断的 in-flight operation。

## 10. Control application outcome

新增：

~~~text
ExecutionControlDisposition
- NO_CONTROL
- WAITING_IN_FLIGHT
- READY_TO_TERMINALIZE
- ALREADY_TERMINAL
- CONFLICT
- UNKNOWN

ExecutionControlApplication
- signal
- disposition
- reason_codes
- running_step_id?
- interrupt_outcome?
- preserve_running_step_result
- handoff_required
~~~

其中：

~~~text
PREEMPT + terminalized
→ handoff_required = true
~~~

但 IU7 **不启动**新的 Runtime cycle。

## 11. Lifecycle terminalization

现有 `ExecutionLifecycleService.finish_step` 只允许：

~~~text
RUNNING -> terminal
~~~

现有 `finish_execution` 又要求：

~~~text
所有 Step 已经 terminal
~~~

因此 CANCEL/PREEMPT 时剩余 PENDING Steps 当前无法合法收口。

IU7 需要新的纯 lifecycle boundary，例如：

~~~text
ExecutionControlLifecycleTransitioner
~~~

输入：

~~~text
PreparedExecution
latched control signal
safe control application outcome
terminalization time
~~~

输出一个完整新的 PreparedExecution。

规则：

### 已 terminal Step

~~~text
保持原 status/result/time
绝不重写
~~~

### RUNNING Step

只有整个 in-flight chain 已达到 control-safe boundary，且当前 owner interrupt = CONFIRMED_STOPPED 时：

~~~text
CANCEL -> CANCELLED
PREEMPT -> PREEMPTED
~~~

如果 operation 已 ALREADY_COMPLETED：

~~~text
先等待/确认真实 lifecycle completion 已提交
→ 保留实际 terminal result
→ 不使用 control 覆盖该 Step
~~~

如果 NOT_CANCELLABLE / UNKNOWN：

~~~text
不能终态化 execution
~~~

### PENDING Steps

在 control 已 latch 且当前 in-flight 已到安全边界后：

~~~text
CANCEL -> CANCELLED
PREEMPT -> PREEMPTED
~~~

它们表示“因 execution control 从未开始”，不是执行失败。

### Execution

所有 Step terminal 后：

~~~text
CANCEL -> ExecutionPlanStatus.CANCELLED
PREEMPT -> ExecutionPlanStatus.PREEMPTED
~~~

## 12. Lifecycle mutation authority

IU7 可以正式拥有 CANCELLED/PREEMPTED lifecycle mutation，但只能通过：

~~~text
Control signal exact authority
+ Control latch
+ in-flight interrupt evidence
+ Control Lifecycle Transitioner
~~~

不能直接：

~~~text
if CANCEL_REQUIRED:
    finish_step(CANCELLED)
~~~

尤其 `interrupt requested` 不等于 `interrupt confirmed`。

## 13. Interaction with IU6

IU6 已冻结：

~~~text
CANCELLED / PREEMPTED terminalization
不属于 Reliability finalization
~~~

IU7 接管这两个 control terminal status。

但 IU7 不能改变 IU6 已经观察到的：

~~~text
Tool journal
Idempotency state
StepAttemptObservation
retry evidence
~~~

如果 control 与 Tool side-effect uncertainty 同时存在：

~~~text
UNKNOWN side effect remains UNKNOWN
control cannot erase it
~~~

## 14. Interaction with IU8

IU7 不实现：

~~~text
session_execution_lock
playback_lock
notification_lock
microphone/speaker lock
lock stealing/recovery
~~~

operation-local interrupt cleanup 可以由 interrupt adapter 自己完成。

正式 ResourceLockProvider acquire/release policy 属于 M5-IU8。

技术债：

~~~text
TD-M5-IU7-01 RESOURCE_LOCK_RELEASE_DEFERRED_TO_IU8
~~~

## 15. Interaction with IU9

IU7 第一版 live control state 可以使用注入式 memory implementation。

以下继续留给 IU9：

~~~text
durable control latch
crash during cancellation
restart after PREEMPT
persisted in-flight registry
Workflow resume/recovery
~~~

技术债：

~~~text
TD-M5-IU7-02 DURABLE_CONTROL_RECOVERY_DEFERRED_TO_IU9
~~~

## 16. Interaction with Runtime

PREEMPT 后 IU7 只返回：

~~~text
execution = PREEMPTED
handoff_required = true
~~~

谁启动新的高优先级 Runtime Cycle 属于 Runtime orchestration，不属于 M5。

## 17. Planned tests

至少覆盖：

~~~text
1. NONE signal 不产生 lifecycle mutation
2. CANCEL/PREEMPT 必须带 immutable signal identity
3. wrong target execution -> fail closed
4. same signal replay idempotent
5. conflicting later signal -> CONFLICT/UNKNOWN
6. pre-step checker 不比较 priority
7. runtime watcher 可在 in-flight operation 期间产生 terminal signal
8. cancellation_token string 不被当成 mutable token
9. exact hierarchical in-flight operation chain only
10. nested Tool 必须 leaf-first interrupt，再停止 parent owner
11. CONFIRMED_STOPPED 才允许 control-terminalize running Step
12. ALREADY_COMPLETED 但 lifecycle 仍 RUNNING -> WAITING，不猜终态
13. ALREADY_COMPLETED + lifecycle 已提交 -> 保留真实 Step result
14. NOT_CANCELLABLE 保持 barrier + wait
15. UNKNOWN interrupt 不写 CANCELLED/PREEMPTED
16. terminal Step 永不被 control 重写
17. remaining PENDING Steps -> CANCELLED/PREEMPTED
18. completed Tool side effect 保持原 truth
19. CANCEL -> execution CANCELLED
20. PREEMPT -> execution PREEMPTED
21. PREEMPT 只返回 handoff_required，不启动 Runtime cycle
22. Resource Lock policy 不进入 IU7
23. Recovery/Checkpoint 不进入 IU7
24. Aggregation/M6 不进入 IU7
~~~

## 18. 设计结论

~~~text
M5-IU7 IMPLEMENTATION DESIGN = COMPLETE
~~~

是否可以直接实现，以 Implementation Readiness Review 为准。