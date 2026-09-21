# M5-IU5 Result Collection + Step Attempt Observation 实现设计 V1.0

> 基线：M5-IU4 = PASSED，latest head 9efc61e39b7b308079895b5a9e065eb2ddaf28b6。
> 本 IU 对应 M5 主流程的“⑦ Collect Step / Tool Result”。
> M5 V2.0 详细章节原“Step 7：Tool Input / Output Validation”已经在 IU4 的 Core Tool Gateway 内完成；IU5 不重复 Validation。
> 本 IU 只收集和归一化“一次执行尝试的事实”，不进入 Retry / Timeout enforcement / Idempotency / Cancellation / Preemption / Checkpoint / Recovery / Plan Aggregation / M6。

## 1. IU5 目标

~~~text
RUNNING StepLifecycleSnapshot
+
StepCapabilityExecutionOutcome (IU4)
        ↓
Result Identity / Consistency Check
        ↓
Owner Result Classification
        ↓
Core Tool Journal Collection
        ↓
Raw Business Output / Capability Event Collection
        ↓
StepAttemptObservation
        ↓
后续 Reliability / Lifecycle Finalization / Persistence / Aggregation
~~~

核心原则：

~~~text
Collect facts != Finalize Step
Attempt observation != Step terminal lifecycle
Execution observation != Business Truth
~~~

IU5 不允许：

~~~text
UNKNOWN -> FAILED
WAITING -> SUCCESS
PARTIAL_SUCCESS -> 强制 SUCCESS/FAILED
NO_EXTERNAL_EXECUTION -> Step SUCCESS
Retry 前提前终态化 Step
根据单个 Tool failure 擅自重写 owner result
生成 Canonical ExecutionResult
进入 M6
~~~

## 2. 为什么不能直接写 StepExecutionStatus

当前 StepExecutionStatus 只有：

~~~text
PENDING
RUNNING
SUCCESS
FAILED
SKIPPED
CANCELLED
TIMEOUT
PREEMPTED
~~~

但 IU4 可以合法观察到：

~~~text
CapabilityExecutionStatus.WAITING
CapabilityExecutionStatus.UNKNOWN
CapabilityExecutionStatus.BLOCKED
CapabilityExecutionStatus.NO_EXTERNAL_EXECUTION

SkillExecutionStatus.PARTIAL_SUCCESS

WorkflowExecutionStatus.CREATED
WorkflowExecutionStatus.RUNNING
WorkflowExecutionStatus.WAITING
~~~

这些没有安全的一对一 terminal mapping。

同时，FAILED / TIMEOUT observation 在 Retry / Idempotency 尚未处理之前，也不能直接写成 StepExecutionStatus.FAILED / TIMEOUT，否则后续 Reliability 无法合法重试。

因此 IU5 必须新增内部 attempt observation 层。

## 3. StepAttemptStatus

冻结内部枚举：

~~~text
SUCCESS
PARTIAL_SUCCESS
FAILED
WAITING
IN_PROGRESS
CANCELLED
TIMEOUT
PREEMPTED
BLOCKED
UNKNOWN
NO_EXTERNAL_EXECUTION
~~~

这些状态只回答：

> 当前这一次 owner invocation / capability execution 观察到了什么？

它们不是 StepExecutionStatus、ExecutionPlanStatus、BusinessStatus 或 ValidationStatus。

特别冻结：

~~~text
SUCCESS != M6 business success
PARTIAL_SUCCESS != ExecutionPlanStatus.PARTIAL_SUCCESS
WAITING / IN_PROGRESS != FAILED
NO_EXTERNAL_EXECUTION != SUCCESS
UNKNOWN != FAILED
~~~

## 4. StepAttemptObservation

建议新增内部 typed result：

~~~text
StepAttemptObservation

step_id
step_execution_id
attempt_number
status
execution_owner

owner_capability_id?
owner_capability_version?

reason_codes[]

skill_result?
workflow_result?

tool_results[]
tool_journal[]

business_outputs[]
capability_events[]

has_non_success_tool_observation
has_unknown_tool_observation
has_untrusted_success_observation

observed_at
~~~

attempt_number 必须 >= 1，由 Core caller 提供，Domain implementation 无权决定。

第一轮：

~~~text
attempt_number = 1
~~~

后续 Retry IU 可以产生 2 / 3 / ...，因此前一次 observation 不会被覆盖。

Step attempt_number 与 ToolInvocationRequest.attempt 是不同层级的计数。

## 5. 输入一致性门禁

StepResultCollector 接收：

~~~text
StepLifecycleSnapshot
StepCapabilityExecutionOutcome
attempt_number
observed_at
~~~

至少校验：

~~~text
snapshot.status == RUNNING
outcome.step_id == snapshot.step_id
outcome.step_execution_id == snapshot.step_execution_id
attempt_number >= 1
observed_at >= snapshot.started_at
~~~

错配必须 fail closed；IU5 不重新读 ApprovedPlan、不重新解析 Capability，因为 IU4 已完成 Approved owner / ID / version 校验。

## 6. CapabilityExecutionStatus 顶层映射

优先消费 IU4 顶层状态：

| IU4 | IU5 |
|---|---|
| BLOCKED | BLOCKED |
| UNKNOWN | UNKNOWN |
| WAITING | WAITING |
| NO_EXTERNAL_EXECUTION | NO_EXTERNAL_EXECUTION |
| EXECUTED | 继续读取 owner result |

其中：

~~~text
BLOCKED != FAILED
UNKNOWN != FAILED
NO_EXTERNAL_EXECUTION != SUCCESS
~~~

WAITING 必须仍满足 Workflow owner + WorkflowExecutionStatus.WAITING。

## 7. Skill 分类

当 execution_owner = SKILL 且 IU4 = EXECUTED：

| SkillExecutionStatus | StepAttemptStatus |
|---|---|
| SUCCESS | SUCCESS |
| PARTIAL_SUCCESS | PARTIAL_SUCCESS |
| FAILED | FAILED |
| CANCELLED | CANCELLED |
| TIMEOUT | TIMEOUT |
| PREEMPTED | PREEMPTED |

owner/result 缺失或不一致：

~~~text
UNKNOWN
RESULT_COLLECTION_OWNER_RESULT_INCONSISTENT
~~~

## 8. Workflow 分类

| WorkflowExecutionStatus | StepAttemptStatus |
|---|---|
| COMPLETED | SUCCESS |
| FAILED | FAILED |
| CANCELLED | CANCELLED |
| TIMEOUT | TIMEOUT |
| PREEMPTED | PREEMPTED |
| WAITING | WAITING |
| RUNNING | IN_PROGRESS |
| CREATED | IN_PROGRESS |

WAITING / RUNNING / CREATED 全部是非终态事实。

IU5 不调用 Workflow.resume，也不保存 Checkpoint。

## 9. Tool Truth Collection

唯一 Tool truth 继续是：

~~~text
StepCapabilityExecutionOutcome.tool_journal
~~~

IU5 再次要求：

~~~text
outcome.tool_results
==
tuple(entry.result for entry in outcome.tool_journal)
~~~

不得重新相信 Domain tool_results，不得 Registry lookup，不得重新调用 Tool，不得重新做 Permission / Validation。

第一版不允许 ResultCollector 因单个 Tool FAILED / TIMEOUT / REJECTED / UNAVAILABLE 就擅自覆盖 owner 状态。原因是 owner execution unit 可能已经合法处理该 observation；IU5 只保留事实，后续 M6 才判断业务事实。

但 UNKNOWN 是特殊不变量：

~~~text
Tool final status = UNKNOWN
+
IU4 status = EXECUTED
~~~

说明 Core observation 链不一致，IU5 必须：

~~~text
StepAttemptStatus.UNKNOWN
TOOL_UNKNOWN_NOT_PROPAGATED
~~~

不得接受 owner SUCCESS。

## 10. Side-effect Evidence Flags

IU5 不做 Retry safety decision，只暴露事实。

has_non_success_tool_observation：

~~~text
任一 Tool status != SUCCESS
~~~

has_unknown_tool_observation：

~~~text
任一 Tool status = UNKNOWN
~~~

has_untrusted_success_observation：

~~~text
raw_result.status = SUCCESS
+
final result.status = UNKNOWN
~~~

表示“外部副作用/结果可能已成功发生，但返回证据不再可信”。

这不等于 retryable=false；真正的 Retry / Idempotency 决策属于后续 Reliability IU。

## 11. Business Outputs / Events

Skill：

~~~text
M5SkillResult.business_outputs
~~~

原样收集，不解释、不验证、不补全。

Workflow：

~~~text
M5WorkflowResult.important_outputs
~~~

只作为 raw observed output 保存，不升级成 business truth。

Skill 的 events 只收集为：

~~~text
capability_events
~~~

不得直接升级成 ExecutionEventRecord，因为 Core Execution Event 的 event_id / event_type / timestamp authority 属于后续 Event/Trace 机制。

## 12. Reason Codes

IU4 reason_codes 必须原样保留。

Collector 可追加：

~~~text
RESULT_COLLECTED
RESULT_COLLECTION_OWNER_RESULT_INCONSISTENT
TOOL_UNKNOWN_NOT_PROPAGATED
~~~

但不得删除或覆盖上游 reason。

## 13. 与 Step Lifecycle 的边界

IU5 不调用：

~~~text
ExecutionLifecycleService.finish_step(...)
~~~

因此：

~~~text
RUNNING Step
+
StepAttemptObservation
~~~

可以同时存在。

后续：

~~~text
StepAttemptObservation
        ↓
Reliability / Control / Workflow Persistence
        ↓
Finalization Decision
        ↓
ExecutionLifecycleService.finish_step(...)
~~~

只有确定“不再 Retry、不再 WAITING/RUNNING、不再恢复 Workflow”后，才允许终态化 Step。

## 14. 与 Reliability 的边界

IU5 只回答：

~~~text
这次尝试观察到了什么？
~~~

不回答：

~~~text
是否重试
还能重试几次
backoff
是否安全重放
timeout enforcement
idempotency reserve/complete/unknown
resource lock
~~~

后续 Reliability IU 再结合 ToolDefinition retry_policy / idempotency_mode、side-effect evidence、attempt_number 等信息决策。

## 15. 与 Persistence / Aggregation 的边界

IU5 不写：

~~~text
ExecutionStateStore
WorkflowCheckpointStore
IdempotencyStore
~~~

Workflow WAITING 只收集成 WAITING observation。

IU5 也不调用：

~~~text
ExecutionResultProjector
ExecutionAggregator
~~~

不直接生成 Canonical StepExecutionResult / ExecutionResult。

## 16. 第一版接口建议

~~~python
class StepResultCollector:
    def collect(
        self,
        *,
        step_snapshot: StepLifecycleSnapshot,
        outcome: StepCapabilityExecutionOutcome,
        attempt_number: int,
        observed_at: datetime,
    ) -> StepAttemptObservation:
        ...
~~~

Collector 必须是：

~~~text
无 Registry
无 Tool invoke
无 Store
无 Lifecycle mutation
无 Runtime State mutation
无 M6
~~~

## 17. Planned Gate

至少覆盖：

~~~text
1. Snapshot 必须 RUNNING
2. step_id / step_execution_id 必须一致
3. attempt_number >= 1
4. observed_at 不早于 step started_at
5. BLOCKED 保持 BLOCKED
6. UNKNOWN 保持 UNKNOWN
7. WAITING 保持 WAITING
8. NO_EXTERNAL_EXECUTION 不变成 SUCCESS
9. Skill SUCCESS -> SUCCESS
10. Skill PARTIAL_SUCCESS 保持 PARTIAL_SUCCESS
11. Skill FAILED/CANCELLED/TIMEOUT/PREEMPTED 精确分类
12. Workflow COMPLETED -> SUCCESS
13. Workflow WAITING -> WAITING
14. Workflow CREATED/RUNNING -> IN_PROGRESS
15. Workflow FAILED/CANCELLED/TIMEOUT/PREEMPTED 精确分类
16. Core tool journal 原样保留
17. Tool UNKNOWN 不得被 owner SUCCESS 覆盖
18. non-success Tool observation 不被删除
19. raw SUCCESS + final UNKNOWN 标记 untrusted-success evidence
20. business_outputs 原样保留
21. capability events 不升级成 Core execution events
22. IU5 不调用 Registry / Tool / Lifecycle / Store / M6
23. IU5 不做 Retry / Timeout enforcement / Idempotency
24. IU5 不生成 Canonical ExecutionResult
~~~

## 18. 明确不属于 IU5

~~~text
Retry decision
Timeout enforcement
Idempotency behavior
Resource Lock
Cancellation handling
Preemption handling
Workflow resume
Checkpoint persistence
Crash Recovery
Step terminal lifecycle mutation
Plan stop/fallback interpretation
Execution Aggregation
Canonical ExecutionResult completion
M6 Result Validation
M7 Response
M8 State/Memory
~~~

## 19. 设计结论

~~~text
M5-IU5 IMPLEMENTATION DESIGN = COMPLETE
~~~

本 IU 可以在不修改 Canonical Contract、不修改既有 StepExecutionStatus 的前提下实现。

Readiness 以配套《M5-IU5 Implementation Readiness Review V1.0》为准。
