# M5-IU5 Result Collection 实现说明 V1.0

> 基线：M5-IU5 DESIGN COMPLETE / INDEPENDENT DESIGN REVIEW PASSED / READINESS READY。
> 实现分支：m5-iu5-result-collection。
> 本轮只实现 Result Collection + Step Attempt Observation，不进入 Reliability / Persistence / Finalization / Aggregation / M6。

## 1. 实现链路

~~~text
RUNNING StepLifecycleSnapshot
+
StepCapabilityExecutionOutcome
        ↓
StepResultCollector
        ↓
结构 / 身份 / 时间一致性检查
        ↓
owner result classification
        ↓
Core Tool journal preservation
        ↓
raw business output / capability event collection
        ↓
StepAttemptObservation
~~~

核心原则：

~~~text
Collect facts != Finalize Step
Attempt observation != terminal Step lifecycle
Execution observation != Business Truth
~~~

## 2. 新增内部对象

~~~text
StepAttemptStatus
StepAttemptObservation
StepResultCollectionError
StepResultCollector
~~~

新增代码：

~~~text
runtime/execution/result_collection.py
tests/test_m5_iu5_result_collection.py
~~~

这些对象属于 M5 internal，不修改 Canonical Contract。

## 3. 状态分类

StepAttemptStatus 冻结为：

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

Skill 精确映射 SkillExecutionStatus；Workflow 精确映射 WorkflowExecutionStatus，其中 WAITING 保持 WAITING，CREATED/RUNNING 保持 IN_PROGRESS。

特别保持：

~~~text
BLOCKED != FAILED
UNKNOWN != FAILED
NO_EXTERNAL_EXECUTION != SUCCESS
PARTIAL_SUCCESS 不被压成 SUCCESS/FAILED
~~~

## 4. 结构错误与 UNKNOWN 分离

以下属于 Core collection fault：

~~~text
snapshot 非 RUNNING
RUNNING snapshot.started_at 缺失
step_id / step_execution_id 不一致
attempt_number < 1
observed_at 早于 started_at
时间对象不可比较
~~~

统一抛 StepResultCollectionError，不生成 UNKNOWN observation，不改 lifecycle。

## 5. Tool truth

唯一 Tool truth 继续是 IU4 Core journal。

Collector 再次要求：

~~~text
outcome.tool_results
==
tuple(entry.result for entry in outcome.tool_journal)
~~~

不重查 Registry、不重调 Tool、不重做 Permission / Validation。

若出现 EXECUTED + final Tool UNKNOWN，则第二道闩把 attempt 降为 UNKNOWN，并追加 TOOL_UNKNOWN_NOT_PROPAGATED。

Tool FAILED / TIMEOUT / REJECTED 等非 UNKNOWN 事实不会由 Collector 单独覆盖 owner status，只通过 evidence flags 保留。

## 6. Evidence preservation

StepAttemptObservation 保留：

~~~text
skill_result / workflow_result
tool_results / tool_journal
business_outputs
capability_events
reason_codes
has_non_success_tool_observation
has_unknown_tool_observation
has_untrusted_success_observation
~~~

IU4 reason_codes 的原顺序和重复项不改变；Collector 只追加尚不存在的新 reason。

## 7. Lifecycle boundary

Collector 不调用 ExecutionLifecycleService.finish_step。

因此 collect 后原 RUNNING Step 仍保持 RUNNING，finished_at 不被写入。

这为后续 Retry / WAITING / Workflow persistence / Finalization 保留空间。

## 8. 明确未实现

~~~text
Retry / Timeout enforcement / Idempotency
Resource Lock
Cancellation / Preemption
Workflow resume / Checkpoint / Crash Recovery
Attempt history persistence
Step terminal finalization
Plan stop/fallback interpretation
Execution Aggregation
Canonical ExecutionResult
M6 / M7 / M8
~~~

## 9. 测试覆盖

行为测试覆盖 Skill / Workflow 全状态映射、BLOCKED/UNKNOWN/NO_EXTERNAL_EXECUTION、Tool UNKNOWN 第二道闩、Tool FAILED + Skill SUCCESS、raw SUCCESS + final UNKNOWN evidence、owner/result inconsistency、身份/时间错误、reason 保留、evidence flag invariant，以及 Collector 不修改 RUNNING lifecycle。

## 10. 当前状态

~~~text
M5-IU5 IMPLEMENTATION = CODE COMPLETE
M5-IU5 INDEPENDENT IMPLEMENTATION REVIEW = PASSED
NEW BLOCKER = NONE

M5-IU5 VERIFICATION = PENDING FOUR LOCAL GATES
M5-IU5 = NOT YET PASSED
M5 = IN PROGRESS
~~~