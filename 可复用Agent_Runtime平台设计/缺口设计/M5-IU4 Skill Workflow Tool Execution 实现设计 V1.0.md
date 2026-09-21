# M5-IU4 Skill / Workflow / Tool Execution 实现设计 V1.0

> 基线：M5-IU3 = PASSED，verified head `1018d707`。
> 本文件设计 M5 Step 6 的 Capability Execution。不得重做 Capability Resolution，不得进入 Retry / Timeout / Idempotency / Resource Lock / Cancellation / Preemption / Checkpoint / Recovery / Aggregation / M6。
> 本 IU 的核心问题不是“能不能 await implementation”，而是“谁拥有这一步执行权，以及所有真实 Tool 调用如何始终留在 Core 门禁之内”。

## 1. IU4 目标

正式链路：

```text
ApprovedActionPlan
+ READY ActionStep
+ ExecutionContext
+ StepLifecycleSnapshot(step_execution_id)
+ IU3 ResolvedStepCapabilities
        ↓
Execution Owner Projection
        ↓
Skill Executor
or Workflow Executor
        ↓
Core-controlled Approved Tool Invocation Gateway
        ↓
exact IU3 Resolved Tool implementation
        ↓
M5 internal Skill / Workflow / Tool Result
        ↓
后续 Result Collection / Reliability / Persistence / Aggregation
```

IU4 不允许重新：

```text
查 Registry 选版本
发现新 Capability
替换 Skill / Workflow / Tool
重新规划
重新计算 M2 Policy
生成最终回复
把执行观察提升为业务真相
```

## 2. 为什么不能直接实现三个 Executor

当前合同存在三个结构性事实：

### 2.1 同一个 Binding 可以同时有 Skill + Workflow

M4 当前在 `forced_workflow` 场景会保留原 Skill，同时增加 Workflow：

```text
CapabilityBinding
  skill_id = ...
  workflow_id = forced_workflow
```

因此：

```text
skill != None
workflow != None
```

是合法 ApprovedPlan 形态。

如果 M5 自行决定：

```text
先 execute Skill
再 start Workflow
```

可能重复执行业务；

如果自行决定：

```text
只执行 Workflow
```

又是在 M5 发明 Planning 语义。

所以执行 owner 必须在批准前明确冻结，不能由 IU4 猜。

### 2.2 Skill / Workflow 当前无法被强制使用 Approved Tool Set

当前：

```python
SkillImplementation.execute(request, execution_context)
WorkflowImplementation.start(request, execution_context)
```

没有接收：

```text
IU3 ResolvedStepCapabilities.tools
Approved Tool Invocation Gateway
```

因此 Domain implementation 如果自己持有 ToolRegistry / Tool Adapter，就可以绕过：

```text
Approved tool authority
exact approved version
current execution permission
Tool input/output validation
后续 idempotency / lock / cancellation
```

这会形成第二套 Tool execution truth。

### 2.3 Tool 调用前后必须经过 Validation Boundary

M5 冻结设计要求：

```text
input validation
→ Tool invoke
→ output validation
```

当前仓库没有 M5 Tool Input / Output Validator contract。

因此不能为了完成 Step 6 而先允许裸 `ToolImplementation.invoke(...)`，再等后续 IU 补验证。

## 3. Execution Owner Contract

IU4 需要在 Approved capability binding 中消费明确 owner。

建议受控扩展现有 opaque：

```text
capability_plan.bindings[].execution_owner
```

第一版只允许：

```text
SKILL
WORKFLOW
NONE
```

不加入 Canonical ActionStep。

### 3.1 Owner 冻结规则

规划阶段：

```text
只有 skill_id
→ owner = SKILL

forced_workflow 存在
→ owner = WORKFLOW

只有 workflow_id
→ owner = WORKFLOW

skill_id + workflow_id 来自 Domain BindingRule
→ BindingRule 必须明确 owner
→ 缺失则 fail closed

skill_id == None
workflow_id == None
→ owner = NONE
```

IU4 只执行 owner，不根据字段组合重新推导 owner。

### 3.2 为什么暂不加入 DIRECT_TOOL

当前 M4 ToolPlan 的 Tool 来源是：

```text
selected Skill.required_tools
selected Skill.optional_tools
```

SequencePlanner 的 `tool_requirement` 也只来自 Skill required tools。

因此当前正式 M4 并不能生成：

```text
skill_id = None
workflow_id = None
direct approved tool owner = TOOL
```

M5 设计中的 Fast Tool Path 仍是目标能力，但当前规划合同尚不可表达。

IU4 第一版不伪造该路径，登记技术债：

```text
TD-M5-IU4-01 DIRECT_TOOL_FAST_PATH_NOT_REPRESENTABLE
```

## 4. Workflow Tool Authority 必须可表达

当前 ToolPlanner 只从：

```text
SkillDefinition.required_tools
SkillDefinition.optional_tools
```

生成 ToolPlan，并只保留：

```text
required_by_skills
```

但 Workflow 是正式执行 owner，且真实 Workflow 通常必须调用 Tool。

当前 `WorkflowDefinition` 没有：

```text
required_tools
optional_tools
```

因此以下合法形态目前无法安全表达：

```text
execution_owner = WORKFLOW
workflow_id = HELP_WORKFLOW
required approved tools = CREATE_EVENT + NOTIFY
```

不得用“Workflow implementation 自己知道要调什么 Tool”补洞。

建议受控扩展：

```text
WorkflowDefinition.required_tools
WorkflowDefinition.optional_tools

ToolCallPlan.required_by_workflows
tool_plan.tool_calls[].required_by_workflows
```

ToolPlanner 必须根据 execution_owner 生成 authority：

```text
owner = SKILL
→ 只生成该 Skill 的 Tool provenance

owner = WORKFLOW
→ 只生成该 Workflow 的 Tool provenance

owner = NONE
→ 不生成 owner Tool authority
```

IU3 Approved Tool Projection 必须同步识别：

```text
required_by_skills
required_by_workflows
```

且仍禁止从执行时 Registry metadata 扩张 Approved Tool Set。

## 5. Core-controlled Tool Invocation Gateway

正式原则：

```text
Domain Skill / Workflow
不得直接拥有 ToolRegistry truth
不得直接选择 Tool implementation
不得按 tool_id 重新 resolve
```

建议新增内部协议：

```python
class ApprovedToolInvoker(Protocol):
    async def invoke(
        self,
        *,
        tool_id: str,
        input_payload: dict[str, Any],
    ) -> M5ToolResult:
        ...
```

Gateway 在构造时已经绑定：

```text
execution_context
step_id
step_execution_id
IU3 ResolvedStepCapabilities.tools
permission provider/evaluator
input/output validators
tool_call_id factory
```

### 5.1 Gateway Authority

调用 `tool_id` 必须已经存在于当前 Step 的 IU3 resolved Tool set。

否则：

```text
TOOL_NOT_APPROVED_FOR_STEP
```

不得：

```text
查 Registry
找同名新版本
查 SkillDefinition.required_tools 扩张集合
调用任意 Domain Tool
```

### 5.2 Gateway 使用 exact implementation

Gateway 直接使用 IU3：

```text
ResolvedCapability.definition
ResolvedCapability.implementation_ref
ResolvedCapability.version
```

不再 Registry lookup。

因此：

```text
IU3 exact resolution
→ IU4 exact invocation
```

之间不存在第二次版本选择。

## 6. Skill / Workflow Protocol Amendment

为保证 Tool 调用不脱离 Core，当前 Protocol 需要受控修改。

建议：

```python
SkillImplementation.execute(
    request,
    execution_context,
    tool_invoker,
) -> M5SkillResult

WorkflowImplementation.start(
    request,
    execution_context,
    tool_invoker,
) -> M5WorkflowResult

WorkflowImplementation.resume(
    request,
    execution_context,
    tool_invoker,
) -> M5WorkflowResult
```

其中 `tool_invoker` 只能看到当前 Step 已批准/已解析的 Tool。

### 6.1 Tool-free Skill / Workflow

即使没有 Tool，也传入一个：

```text
EmptyApprovedToolInvoker
```

任何 Tool 调用都会 fail closed。

这样 Domain implementation 不需要两套函数签名。

## 7. Tool Permission TOCTOU

IU3 已在 Capability Resolution 时检查 execution permission。

但真正 Tool invoke 可能发生在 Skill / Workflow 执行过程中。

因此 Gateway 在每次真实 Tool 调用前必须重新消费：

```text
ExecutionPermissionContextProvider
ExecutionPermissionEvaluator
```

这不是重新规划，也不是第二套 Tool authority。

它只回答：

```text
这个已经批准并已经 exact-resolved 的 Tool，
在真正调用这一刻，权限事实是否仍允许？
```

规则：

```text
ALLOWED -> 可进入 input validation
DENIED  -> REJECTED / PERMISSION_DENIED
UNKNOWN -> UNKNOWN / TOOL_PERMISSION_UNKNOWN
provider/evaluator failure -> UNKNOWN
```

## 8. Tool Input / Output Validation Boundary

建议新增：

```text
ToolPayloadValidationStatus
ToolPayloadValidationDecision
ToolInputValidator
ToolOutputValidator
```

状态至少：

```text
VALID
INVALID
UNKNOWN
```

### 8.1 Input

调用前：

```text
VALID   -> invoke
INVALID -> 不调用 Tool，返回 REJECTED / INVALID_PARAMETER
UNKNOWN -> 不调用 Tool，返回 UNKNOWN
```

### 8.2 Output

Tool 返回后：

```text
VALID   -> 保留 Tool 原始 status/data
INVALID -> TOOL_INVALID_OUTPUT
UNKNOWN -> UNKNOWN
```

不得让 LLM 猜 schema。

### 8.3 Schema reference

第一版 Validator 只消费 ToolDefinition 已有：

```text
input_schema
output_schema
```

具体 schema_reference / SchemaRegistry / JSON Schema engine 由注入 Validator 解析。

Core 不把业务 schema 写死。

## 9. Invocation Identifier Contract

当前：

```text
ToolInvocationRequest 要求 tool_call_id
WorkflowExecutionRequest 要求 workflow_instance_id
```

但 `ExecutionIdentifierFactory` 目前只生成：

```text
execution_id
step_execution_id
```

IU4 需要新增内部 factory：

```text
CapabilityInvocationIdentifierFactory

new_tool_call_id(step_execution_id, tool_id)
new_workflow_instance_id(step_execution_id, workflow_id)
```

ID 策略继续注入，Core 不硬编码 UUID。

## 10. Skill Executor

输入：

```text
ActionStep
step_execution_id
Resolved Skill
Resolved Tools
ExecutionContext
ApprovedToolInvoker
```

构造：

```text
SkillExecutionRequest
```

必须使用：

```text
step.parameters or {}
```

作为 Skill request parameters。

Skill Executor 不自行构造额外业务参数。

输出必须：

```text
isinstance(M5SkillResult)
result.skill_id == resolved skill_id
```

否则 fail closed：

```text
SKILL_RESULT_INVALID
```

## 11. Workflow Executor

IU4 第一版只处理：

```text
fresh START
```

不处理 Recovery / Callback resume。

原因：

```text
resume authority
checkpoint selection
callback correlation
```

属于后续 Persistence / Checkpoint / Recovery 单元。

IU4 为 fresh workflow 创建 `workflow_instance_id`，构造 `WorkflowExecutionRequest`，调用 exact resolved `start`。

若 Workflow 返回 WAITING，只记录真实 WAITING，不把它当失败或成功。

```text
WAITING != COMPLETED
```

Resume 保留现有 Protocol，但本 IU 不授权调用。

登记：

```text
TD-M5-IU4-02 WORKFLOW_RESUME_DEFERRED_TO_RECOVERY_UNIT
```

## 12. Optional Tool 边界

继承：

```text
TD-M5-IU3-04 OPTIONAL_TOOL_STEP_PROVENANCE_NOT_FROZEN
```

IU4 第一版：

```text
只向 Tool Gateway 暴露 IU3 已明确投影到当前 Step 的 Tool
```

因此不会猜 optional Tool 归属。

这意味着：

```text
optional Tool invocation
= 暂不支持
```

但不会导致未授权 Tool 被执行。

在未来真正启用 optional Tool 前，该 TD 必须关闭。

## 13. IU4 内部结果

IU4 不直接生成 Canonical ExecutionResult。

建议内部：

```text
CapabilityExecutionStatus
  EXECUTED
  WAITING
  NO_EXTERNAL_EXECUTION
  BLOCKED
  UNKNOWN

StepCapabilityExecutionOutcome
  step_id
  step_execution_id
  owner
  owner_capability_id?
  owner_capability_version?
  skill_result?
  workflow_result?
  tool_results[]
  reason_codes[]
```

其中：

```text
NO_EXTERNAL_EXECUTION
!= Step SUCCESS

EXECUTED
!= M6 verified success
```

真正 Step lifecycle mutation 仍由 ExecutionLifecycleService / 后续 orchestration 完成。

## 14. 明确不属于 IU4

```text
Retry
Timeout policy enforcement
Idempotency
Resource Lock
Cancellation side-effect handler
Preemption side-effect handler
Workflow resume / callback routing
Checkpoint
Crash Recovery
Execution Aggregator
Canonical ExecutionResult completion
M6
Response
State/Memory Update
```

## 15. Planned Gate

至少覆盖：

```text
1. M5 不重新推导 execution owner
2. skill+workflow 时只执行 approved owner
3. Domain Skill/Workflow 只能通过 ApprovedToolInvoker 调 Tool
4. 未批准 Tool 调用 fail closed
5. Gateway 不重新 Registry lookup
6. exact IU3 implementation 被调用
7. Tool Permission 每次 invoke 前重检
8. DENIED / UNKNOWN 不调用 Tool
9. input INVALID / UNKNOWN 不调用 Tool
10. output INVALID 不伪造 SUCCESS
11. provider/evaluator/validator failure fail closed
12. Skill result id 必须匹配
13. Workflow START 生成唯一 instance id
14. Workflow WAITING 保持 WAITING
15. no external execution 不等于 Step success
16. Workflow owner 只能使用 Approved workflow Tool provenance
17. optional Tool 不猜归属
18. executed owner version 必须保留到 internal outcome
19. IU4 不进入 Retry/Idempotency/Lock/M6
```

## 16. 设计结论

```text
M5-IU4 IMPLEMENTATION DESIGN = COMPLETE
```

但当前现有合同还不能安全直接实现，必须以配套 Readiness Review 的 blocker 为准。
