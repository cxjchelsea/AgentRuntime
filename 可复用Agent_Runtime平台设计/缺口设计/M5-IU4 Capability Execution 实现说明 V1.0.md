# M5-IU4 Capability Execution 实现说明 V1.0

> 基线：`CA-M5-IU4-01 = PASSED`，`M5-IU4 IMPLEMENTATION READINESS = READY`。
> 实现分支：`m5-iu4-capability-execution`。
> 本轮只实现 frozen first-version execution scope，不进入 Reliability / Recovery / Aggregation / M6。

## 1. 正式执行链

```text
ApprovedActionPlan
+ exact Approved ActionStep
+ RUNNING StepLifecycleSnapshot
+ ExecutionContext
+ IU3 ResolvedStepCapabilities
        ↓
StepCapabilityExecutor
        ↓
frozen execution_owner
        ↓
Skill.execute
or fresh Workflow.start
        ↓
CoreApprovedToolInvoker
        ↓
Approved Tool authority check
        ↓
Tool Input Validation
        ↓
invoke-time Permission re-check
        ↓
exact IU3-resolved Tool implementation
        ↓
Tool Output Validation
        ↓
Core Tool Journal
        ↓
StepCapabilityExecutionOutcome
```

## 2. 新增内部实现

新增：

```text
runtime/execution/capability_execution.py
```

冻结内部对象：

```text
CapabilityExecutionStatus
StepCapabilityExecutionOutcome
ToolInvocationBoundaryError
CoreApprovedToolInvoker
StepCapabilityExecutor
```

这些对象不是 Canonical main-chain contract。

## 3. Execution Owner

IU4 不重新推导 owner，只消费 IU3 已解析出的：

```text
CapabilityExecutionOwner.SKILL
CapabilityExecutionOwner.WORKFLOW
CapabilityExecutionOwner.NONE
```

规则：

```text
SKILL
→ 只调用 exact resolved SkillImplementation.execute

WORKFLOW
→ 只调用 exact resolved WorkflowImplementation.start

NONE
→ NO_EXTERNAL_EXECUTION
```

本轮不调用：

```text
Workflow.resume
direct Tool fast path
```

## 4. Approved Tool Gateway

`CoreApprovedToolInvoker` 构造时只接收：

```text
IU3 ResolvedStepCapabilities.tools
```

真实调用期间：

```text
不得 Registry lookup
不得选择新 Tool
不得 fallback 到其他 version
不得从 Skill/Workflow Definition 扩张 Tool set
```

请求未批准 Tool 时：

```text
TOOL_NOT_APPROVED_FOR_STEP
→ Core boundary latch
→ 后续 Tool 调用全部 fail closed
→ Step outcome = BLOCKED
```

因此 Domain 即使捕获异常，也不能在 authority violation 后继续产生 Tool side effect。

## 5. Input Validation

每个 approved Tool call 首先执行：

```text
ToolInputValidator
```

结果：

```text
VALID
→ 继续

INVALID
→ REJECTED / INVALID_PARAMETER
→ 不调用 Permission Provider
→ 不调用真实 Tool

UNKNOWN / validator failure / invalid validator result
→ UNKNOWN / TOOL_INPUT_VALIDATION_UNKNOWN
→ 不调用真实 Tool
```

## 6. Invoke-time Permission

只有 Input VALID 才进入当前权限事实检查。

```text
required_permissions absent
→ ALLOWED without provider lookup

required_permissions present
→ ExecutionPermissionContextProvider
→ ExecutionPermissionEvaluator
```

规则：

```text
ALLOWED → invoke
DENIED  → REJECTED / PERMISSION_DENIED
UNKNOWN → UNKNOWN / TOOL_PERMISSION_UNKNOWN

provider/evaluator exception
→ UNKNOWN
```

Permission 每次 Tool invoke 都重新检查，不复用 IU3 resolution-time permission observation。

## 7. Tool Invocation

真实调用只使用 IU3 resolved：

```text
ResolvedCapability.definition
ResolvedCapability.implementation_ref
ResolvedCapability.version
```

构造：

```text
ToolInvocationRequest
attempt = 1
idempotency_key = None
```

Domain 不能控制：

```text
attempt
idempotency_key
retry
timeout
lock
```

真实 Tool exception：

```text
UNKNOWN / TOOL_EXECUTION_EXCEPTION
```

返回值必须满足：

```text
M5ToolResult
tool_call_id == Core generated id
tool_id == approved tool_id
attempt == 1
status is ToolExecutionStatus
```

否则 fail closed。

## 8. Output Validation

Tool 非 SUCCESS：

```text
不进入 output validation
不得被升级
保留原始非成功 observation
```

Tool SUCCESS：

```text
VALID
→ 保留 SUCCESS

INVALID
→ final UNKNOWN / TOOL_INVALID_OUTPUT

UNKNOWN / validator failure
→ final UNKNOWN / TOOL_OUTPUT_VALIDATION_UNKNOWN
```

当 SUCCESS output 无法验证时，Core journal 保留：

```text
raw_result = 原始 SUCCESS observation
result = UNKNOWN final observation
```

因此不会把可能已经发生的 side effect 简化成普通 FAILED。

## 9. Core Tool Journal

`StepCapabilityExecutionOutcome` 同时携带：

```text
tool_results
tool_journal
```

并强制：

```text
tool_results
==
tuple(entry.result for entry in tool_journal)
```

Journal 保存：

```text
tool_call_id
tool_id
approved tool_version
permission_status
input_validation_status
output_validation_status
raw_result
final result
```

Domain 的 `M5SkillResult.tool_results` / `M5WorkflowResult.tool_results`：

```text
empty
→ Core 用 journal 归一化

non-empty
→ 必须与 Core journal 完全一致
→ 不一致则 UNKNOWN / CAPABILITY_RESULT_TOOL_TRACE_MISMATCH
```

Domain 不能伪造第二套 Tool truth。

## 10. Skill Execution

输入参数：

```text
SkillExecutionRequest.parameters
= ActionStep.parameters or {}
```

异常：

```text
Skill exception
→ UNKNOWN / SKILL_EXECUTION_EXCEPTION
→ 已存在 Core Tool journal 不丢失
```

结果必须：

```text
M5SkillResult
result.skill_id == exact resolved skill_id
status is SkillExecutionStatus
```

否则：

```text
UNKNOWN / SKILL_RESULT_INVALID
```

## 11. Workflow Execution

本轮只允许：

```text
fresh Workflow.start
```

`workflow_instance_id` 只能来自注入的：

```text
CapabilityInvocationIdentifierFactory
```

不得调用 `resume`。

结果必须：

```text
M5WorkflowResult
workflow_id == exact resolved workflow_id
workflow_instance_id == Core generated id
status is WorkflowExecutionStatus
```

`WAITING` 保持：

```text
CapabilityExecutionStatus.WAITING
```

不提升成成功。

## 12. Authority / Lifecycle Gate

真实 owner invocation 前还检查：

```text
ActionStep 必须是 ApprovedActionPlan 中 exact Step
ExecutionContext.plan_id/request_id 必须匹配 ApprovedPlan
StepLifecycleSnapshot 必须匹配 step_id/action
StepLifecycleSnapshot.status 必须是 RUNNING
ResolvedStepCapabilities.step_id 必须匹配
resolved owner 与 Step skill/workflow identity 必须一致
ApprovedPlan capability_plan.bindings[].execution_owner 必须匹配 resolved owner
Approved owner capability ID + version 必须匹配 IU3 resolved owner identity
```

IU4 不自行修改 lifecycle；只消费 RUNNING snapshot。

## 13. 明确不属于本轮

```text
optional Tool invocation
direct Tool fast path
Workflow resume
Callback routing
Checkpoint
Crash Recovery
Retry
Timeout enforcement
Idempotency
Resource Lock
Cancellation side-effect handling
Preemption side-effect handling
Execution Aggregation
Canonical ExecutionResult completion
M6
Response
State / Memory Update
```

## 14. 回归覆盖

新增：

```text
tests/test_m5_iu4_capability_execution.py
```

覆盖：

```text
Skill owner exact execution
fresh Workflow START
Workflow WAITING
forced-workflow 保留 non-owner skill_id 时仍只执行 Workflow owner
forged resolved owner 不能覆盖 Approved execution_owner
Workflow Tool Gateway
unapproved Tool blocked
authority violation latch
input INVALID
input validator failure
invoke-time permission per call
permission DENIED
permission UNKNOWN
Tool adapter exception
output INVALID + raw observation preservation
non-success Tool never upgraded
Domain fabricated tool_results rejected
Skill exception after Tool preserves journal
wrong Workflow instance rejected
NONE owner
mutated Approved Step rejected
non-RUNNING snapshot rejected
ExecutionContext cross-plan rejected
Tool invocation id failure
attempt=1 / idempotency_key=None
```

## 15. 当前状态

```text
M5-IU4 IMPLEMENTATION = CODE COMPLETE
M5-IU4 INDEPENDENT IMPLEMENTATION REVIEW = PENDING
M5-IU4 VERIFICATION = PENDING FOUR LOCAL GATES
M5-IU4 = NOT YET PASSED

M5 = IN PROGRESS
```
