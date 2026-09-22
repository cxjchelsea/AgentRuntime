# CA-M5-IU7-01 Control Signal Identity + Watch/Latch V1.0

> Purpose：关闭 M5-IU7 Readiness blocker B-M5-IU7-001 / B-M5-IU7-002。
> Baseline：M5-IU7 Design Review = PASSED；Implementation Readiness = NOT_READY。
> Scope：只冻结可审计 control signal、live watcher、terminal-control latch；不实现 interrupt、in-flight operation registry、lifecycle terminalization、Resource Lock、Recovery、Aggregation 或 M6。

## 1. Blockers

~~~text
B-M5-IU7-001 CONTROL_SIGNAL_ENVELOPE_NOT_AUDITABLE
B-M5-IU7-002 INFLIGHT_CONTROL_WATCH_AND_LATCH_MISSING
~~~

## 2. ExecutionControlSignal authority envelope

原合同：

~~~text
signal_type
reason_code
source
~~~

扩展为 terminal signal authority：

~~~text
signal_type
reason_code
source
signal_id
target_execution_id
issued_at
~~~

对于 CANCEL / PREEMPT：

~~~text
reason_code     = required, non-blank
source          = required, non-blank
signal_id       = required, non-blank
target_execution_id = required, non-blank
issued_at       = required, timezone-aware
~~~

对于 NONE：

~~~text
reason_code = None
signal_id = None
target_execution_id = None
issued_at = None
~~~

`source` 可以作为 NONE observation source metadata，但若存在必须 non-blank。

## 3. Target authority

正式不变量：

~~~text
CANCEL/PREEMPT.signal.target_execution_id
== current ExecutionContext.execution_id
~~~

现有 IU2 `RuntimeExecutionChecker` 已增加 fail-closed target check：

~~~text
mismatch
-> RuntimeExecutionCheckStatus.UNKNOWN
-> CONTROL_SIGNAL_TARGET_MISMATCH
~~~

它仍然只消费上游 control fact，不比较 priority、不重算 Policy。

## 4. Time authority split

`issued_at` 是上游 audit evidence，不是 M5 跨时钟域排序的唯一 authority。

新增：

~~~text
ObservedExecutionControl
- signal
- observed_at

LatchedExecutionControl
- signal
- observed_at
- latched_at
~~~

`observed_at / latched_at` 必须由 Core 本地 time authority 产生，并且 timezone-aware。

只要求：

~~~text
latched_at >= observed_at
~~~

不要求：

~~~text
observed_at >= issued_at
~~~

因为上游与 Core 可能处于不同 clock domain。

## 5. ExecutionControlWatcher

冻结协议：

~~~text
wait_for_terminal_signal(
  execution_id,
  cancellation_token
)
-> ObservedExecutionControl
~~~

语义：

~~~text
只观察已经由 Runtime/M2 resolved 的 CANCEL/PREEMPT
poll / subscription cadence 由 implementation 决定
cancellation_token 只是 opaque correlation data
不得把 cancellation_token string 当成 set()/cancel() primitive
不得计算 priority / Policy / timeout
~~~

Watcher 本身不 interrupt Tool/Skill/Workflow。

## 6. ExecutionControlLatch

新增：

~~~text
ExecutionControlLatchStatus
- LATCHED
- ALREADY_LATCHED
- CONFLICT
- UNKNOWN

ExecutionControlLatchDecision
- status
- reason_codes
- latched_control?

ExecutionControlLatch
- latch(observed, latched_at)
- get_latched(execution_id)
~~~

正式语义：

### LATCHED

~~~text
execution 尚无 terminal control
+ incoming signal exact/valid
-> 原子建立 barrier
~~~

### ALREADY_LATCHED

~~~text
exact same immutable signal replay
-> idempotent
-> 返回既有 LatchedExecutionControl
~~~

### CONFLICT

~~~text
同 execution 已 latch 一个 terminal signal
+ 后续 terminal signal identity/payload 不同
-> 不比较 CANCEL/PREEMPT priority
-> 不替换既有 barrier
-> 返回 CONFLICT + existing latched_control
~~~

### UNKNOWN

~~~text
无法确认 latch state / atomic outcome
-> 不得声称已经 latch
-> latched_control = None
~~~

## 7. Barrier persistence semantics

一旦 control 被成功 latch：

~~~text
后续 source 返回 NONE
!= control disappeared
~~~

Formal IU7 coordinator 必须先检查 latch，再决定是否允许继续调度。

Durable latch / crash recovery 仍属于 IU9；本 CA 只冻结 live authority。

## 8. Explicit non-goals

本 CA 不实现：

~~~text
InFlightOperationHandle / Registry
ExecutionInterruptController
Tool / Skill / Workflow interruption
ExecutionControlApplication
CANCELLED/PREEMPTED lifecycle mutation
Resource Lock
Checkpoint / Recovery
Execution Aggregation
M6
PREEMPT Runtime-cycle handoff execution
~~~

## 9. Contract gates

必须验证：

~~~text
1. NONE 不携带 terminal identity
2. CANCEL/PREEMPT 缺任一 authority field -> reject
3. issued_at 必须 timezone-aware
4. ObservedExecutionControl 只接受 CANCEL/PREEMPT
5. observed_at / latched_at 必须 timezone-aware
6. latched_at < observed_at -> reject
7. LATCHED / ALREADY_LATCHED 必须携带 latched_control
8. CONFLICT 必须保留 existing latched_control
9. UNKNOWN 不得伪造 latched_control
10. IU2 wrong-target signal -> UNKNOWN / fail closed
11. RuntimeExecutionChecker 仍不比较 priority
12. 无 interrupt/lifecycle/Registry/ResourceLock/M6 authority 泄漏
~~~

## 10. Blocker closure rule

B-M5-IU7-001 / 002 只有以下全部满足才能 CLOSED：

~~~text
CA-M5-IU7-01 Targeted Amendment Review = PASSED
four local gates = GREEN
contract semantics unchanged after gate repair
~~~

## 11. Current status

~~~text
CA-M5-IU7-01 = CODE COMPLETE
CA-M5-IU7-01 TARGETED AMENDMENT REVIEW = PASSED
CA-M5-IU7-01 VERIFICATION = PENDING FOUR LOCAL GATES

B-M5-IU7-001 = FIX_IMPLEMENTED_PENDING_GATES
B-M5-IU7-002 = FIX_IMPLEMENTED_PENDING_GATES

B-M5-IU7-003 = OPEN
B-M5-IU7-004 = OPEN
B-M5-IU7-005 = OPEN

M5-IU7 IMPLEMENTATION READINESS = NOT_READY
M5 = IN PROGRESS
~~~