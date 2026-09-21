# M5-IU5 Implementation Readiness Review V1.0

> Review target：M5-IU5 Result Collection + Step Attempt Observation。
> Baseline：M5-IU4 = PASSED。
> 本 Review 判断“是否已经具备安全实现 IU5 的合同条件”，不实现 ResultCollector 代码。

## 1. Readiness 结论

~~~text
M5-IU5 IMPLEMENTATION DESIGN = COMPLETE
M5-IU5 IMPLEMENTATION READINESS = READY

BLOCKERS = 0
NEW PRODUCTION CODE = ALLOWED WITHIN FROZEN IU5 SCOPE
~~~

IU5 可以完全建立在现有 IU1 / IU4 internal contracts 之上，通过新增 M5 internal typed observation 完成，不需要修改 Canonical Contract、StepExecutionStatus、ExecutionEngine 或 RuntimeOrchestrator。

## 2. 前置依赖核对

### 2.1 M5-IU1

已存在：

~~~text
StepLifecycleSnapshot
PreparedExecution
ExecutionLifecycleService
StepExecutionStatus
~~~

IU5 只消费 RUNNING snapshot，不调用 finish_step。

结论：READY。

### 2.2 M5-IU4

已存在并验证：

~~~text
StepCapabilityExecutionOutcome
CapabilityExecutionStatus
M5SkillResult
M5WorkflowResult
M5ToolResult
ToolInvocationJournalEntry
Core Tool journal truth boundary
~~~

IU5 所需原始执行观察已经具备。

结论：READY。

### 2.3 Canonical ExecutionResult

IU5 不生成 Canonical ExecutionResult，因此当前 Canonical 中缺少 WAITING / UNKNOWN Step terminal status 不构成 blocker。

## 3. WAITING / IN_PROGRESS

当前 StepExecutionStatus 没有 WAITING / IN_PROGRESS。

如果 IU5 直接终态化 Step，会形成 blocker。

本设计通过新增：

~~~text
StepAttemptStatus.WAITING
StepAttemptStatus.IN_PROGRESS
~~~

表达非终态 observation，同时保持 StepLifecycleSnapshot.status = RUNNING。

因此无需修改 StepExecutionStatus 或 Canonical StepExecutionResult。

## 4. PARTIAL_SUCCESS

SkillExecutionStatus 已存在 PARTIAL_SUCCESS，但 StepExecutionStatus 没有对应值。

IU5 保留：

~~~text
StepAttemptStatus.PARTIAL_SUCCESS
~~~

不提前决定 Step terminal disposition，也不提前决定 ExecutionPlanStatus.PARTIAL_SUCCESS。

结论：NO BLOCKER。

## 5. UNKNOWN

ToolExecutionStatus / CapabilityExecutionStatus 已支持 UNKNOWN。

IU5 冻结：

~~~text
UNKNOWN stays UNKNOWN
Tool UNKNOWN cannot be hidden by owner SUCCESS
~~~

不需要修改现有 enum。

## 6. Retry 前 lifecycle 终态

ExecutionLifecycleService.finish_step 只允许 terminal StepExecutionStatus。

如果 IU5 调用它，则 FAILED / TIMEOUT 会在 Reliability 之前终态化，属于架构错误。

IU5 设计明确禁止：

~~~text
ExecutionLifecycleService.finish_step
~~~

因此一次 attempt observation 可以存在于 Step 仍 RUNNING 的状态下。

后续 Reliability / Finalization 再决定是否终态。

## 7. attempt identity

当前没有单独的 StepAttempt contract。

IU5 新增内部：

~~~text
attempt_number >= 1
~~~

由 Core caller 提供。

不需要修改 SkillExecutionRequest / WorkflowExecutionRequest / ToolInvocationRequest / Canonical StepExecutionResult。

后续 Retry 单元可以递增 attempt_number。

IU5 只负责单次 collect 时验证 attempt_number >= 1。跨 observation 的单调递增 / 唯一性需要 attempt history 或 Reliability orchestration 才能判断，属于后续单元，不阻塞纯 Result Collection。

## 8. Tool Journal sufficiency

现有 ToolInvocationJournalEntry 已保存：

~~~text
tool_call_id
tool_id
tool_version
permission_status
input_validation_status
output_validation_status
raw_result
final result
~~~

足够 IU5：

~~~text
收集 final Tool truth
保留 raw observation
识别 UNKNOWN
识别 raw SUCCESS -> final UNKNOWN
~~~

IU5 不负责根据 ToolDefinition.side_effect_level / idempotency_mode 判断 replay safety；这些 metadata 由后续 Reliability IU 消费。

结论：READY FOR IU5。

## 9. Tool non-success 与 owner success

可能出现：

~~~text
Tool FAILED / TIMEOUT
+
Skill SUCCESS
~~~

IU5 不应擅自把 owner SUCCESS 改成 FAILED，因为 ResultCollector 不拥有 Skill / Workflow 的业务执行语义。

当前设计只：

~~~text
保留 owner status
保留全部 Tool truth
标记 has_non_success_tool_observation
~~~

后续 Reliability / M6 再处理其语义。

结论：NO BLOCKER。

## 10. Raw business output

Skill business_outputs 与 Workflow important_outputs 已有 typed source。

IU5 只做 raw collection，不验证、不解释，不需要新增 Domain schema。

## 11. Event 边界

Skill events 目前是 Domain-returned dict。

IU5 不把它们升级为 Core ExecutionEventRecord，只记录为：

~~~text
capability_events
~~~

所以不需要先冻结 Event Publisher / Event ID Factory。

## 12. Persistence 边界

IU5 不写：

~~~text
ExecutionStateStore
WorkflowCheckpointStore
IdempotencyStore
~~~

因此当前尚未实现 durable attempt history / checkpoint 不阻塞 Result Collection 本身。

## 13. Aggregation 边界

当前 ExecutionResultProjector 仍只投影 IU1 lifecycle snapshots，没有 rich Skill / Workflow / Tool aggregation。

IU5 不修改它。

后续 Aggregation 单元必须消费：

~~~text
StepAttemptObservation history
+
finalized Step lifecycle
~~~

再投影 Canonical ExecutionResult。

这不是 IU5 blocker。

## 14. Downstream requirements / retained debt

### TD-M5-IU5-01 STEP_FINALIZATION_POLICY_DEFERRED

~~~text
StepAttemptObservation
→ 何时成为 terminal StepExecutionStatus
~~~

由后续 Reliability / Control / Finalization 负责。

### TD-M5-IU5-02 WORKFLOW_WAITING_DURABILITY_DEFERRED

~~~text
Workflow WAITING / IN_PROGRESS
~~~

在 IU5 只收集事实；Checkpoint / resume / callback correlation 仍未实现。

### TD-M5-IU5-03 REPLAY_SAFETY_POLICY_DEFERRED

IU5 只暴露 side-effect evidence，不根据它自行决定 Retry / Idempotency。

后续 Reliability IU 必须结合：

~~~text
ToolDefinition.retry_policy
ToolDefinition.idempotency_mode
side-effect metadata
attempt observation
idempotency store
~~~

决定是否允许 replay。

### TD-M5-IU5-04 ATTEMPT_SEQUENCE_AUTHORITY_DEFERRED

IU5 只接收单次 attempt_number，不能独立证明同一 step_execution_id 下的跨次单调递增 / 不重复。

该 authority 必须由后续 Reliability / Persistence 中维护 attempt history 的组件拥有。

这不阻塞 IU5，因为 IU5 不执行 Retry，也不保存 attempt history。

### 继承既有非阻塞债

~~~text
TD-M5-IU3-01 REGISTRY_NAMESPACE_NOT_PINNED
TD-M5-IU3-04 OPTIONAL_TOOL_STEP_PROVENANCE_NOT_FROZEN
TD-M5-IU4-01 DIRECT_TOOL_FAST_PATH_NOT_REPRESENTABLE
TD-M5-IU4-02 WORKFLOW_RESUME_DEFERRED_TO_RECOVERY_UNIT
~~~

它们不阻塞 IU5，因为 IU5 不解析新 capability、不执行 optional/direct Tool、不恢复 Workflow。

## 15. Canonical / Frozen Contract 影响

IU5 不需要修改：

~~~text
ActionStep
ApprovedActionPlan
PolicyDecision
ExecutionEngine
ExecutionResult top-level contract
StepExecutionStatus
ExecutionPlanStatus
RuntimeOrchestrator
M6 contracts
~~~

只允许新增：

~~~text
M5 internal StepAttemptStatus
M5 internal StepAttemptObservation
M5 internal StepResultCollector
必要的 IU5 internal error
tests
docs
~~~

## 16. 实现授权范围

允许：

~~~text
纯 Result Collection
status classification
tool journal preservation
raw business output collection
capability event collection
side-effect evidence flags
identity/time consistency checks
~~~

禁止：

~~~text
真实 Tool / Skill / Workflow 再调用
Registry lookup
Retry
Timeout enforcement
Idempotency
Cancellation / Preemption
Lifecycle finish_step
Checkpoint / Recovery
Store persistence
Plan stop/fallback
Execution Aggregation
Canonical ExecutionResult
M6
~~~

## 17. Readiness Gate

正式实现必须证明：

~~~text
1. 新对象属于 M5 internal，不污染 Canonical
2. RUNNING snapshot 必须有 started_at；identity/time 结构错误与 UNKNOWN execution fact 分离
3. WAITING / IN_PROGRESS / PARTIAL_SUCCESS / UNKNOWN 均可无损表达
4. ResultCollector 不拥有 lifecycle mutation
5. ResultCollector 不拥有 Retry / Idempotency 决策
6. Tool journal 仍是唯一 Tool truth
7. raw business outputs 不被提升成 business truth
8. IU4 reason codes 不被覆盖
9. 不进入 Registry / Tool invoke / Store / M6
~~~

## 18. Current Formal Status

~~~text
M4 = CLOSED

M5-IU1 = PASSED
M5-IU2 = PASSED
M5-IU3 = PASSED
M5-IU4 = PASSED

M5-IU5 IMPLEMENTATION DESIGN = COMPLETE
M5-IU5 INDEPENDENT DESIGN REVIEW = PASSED
M5-IU5 IMPLEMENTATION READINESS = READY

BLOCKERS = 0
NEW BLOCKER = NONE

NEXT REQUIRED:
M5-IU5 formal implementation

M5 = IN PROGRESS
~~~
