# M5-IU4 Implementation Readiness Review V1.0

> Review target: M5-IU4 Skill / Workflow / Tool Execution
> Baseline: M5-IU3 = PASSED @ `1018d707`
> Scope: 只判断是否可以开始 IU4 production implementation，不实现 Executor。

## 1. Readiness 结论

```text
M5-IU4 IMPLEMENTATION DESIGN = COMPLETE
M5-IU4 IMPLEMENTATION READINESS = NOT_READY

BLOCKERS = 5
NEW PRODUCTION CODE = NOT AUTHORIZED
```

原因不是 Capability Resolution 缺失；IU3 已经完成 exact resolution。

真正缺的是：

```text
谁拥有 Step 的执行权
+
Domain Skill / Workflow 如何被强制留在 Approved Tool authority 内
+
真实 Tool invoke 前后的 Validation Gate
+
Tool / Workflow invocation identity
+
Workflow owner 的 Approved Tool authority
```

## 2. B-M5-IU4-001 — Capability Execution Owner Not Frozen

### 2.1 事实

当前 M4 可以生成：

```text
skill_id != None
workflow_id != None
```

尤其：

```text
forced_workflow
```

会保留已选 Skill，再附加 Workflow。

### 2.2 风险

IU4 如果自行决定：

```text
Skill then Workflow
```

可能双执行。

如果自行决定：

```text
Workflow wins
```

则 M5 在发明 M4 未冻结的执行语义。

### 2.3 Blocker

```text
B-M5-IU4-001
= CAPABILITY_EXECUTION_OWNER_NOT_FROZEN
```

### 2.4 Required fix

通过 opaque capability_plan 受控扩展：

```text
capability_plan.bindings[].execution_owner
```

第一版：

```text
SKILL
WORKFLOW
NONE
```

Execution owner 必须在 Approval 前冻结，IU4 只能消费。

## 3. B-M5-IU4-002 — Core-controlled Tool Invocation Boundary Missing

### 3.1 事实

当前：

```python
SkillImplementation.execute(request, execution_context)
WorkflowImplementation.start(request, execution_context)
```

无法接收：

```text
IU3 resolved approved tools
Core Tool Gateway
```

### 3.2 风险

Domain Skill / Workflow 可以通过自己持有的 adapter / registry：

```text
调用未批准 Tool
调用当前新版本 Tool
绕过 Permission
绕过 schema validation
绕过未来 idempotency / lock / cancellation
```

这会破坏：

```text
ApprovedActionPlan
→ IU3 exact resolution
→ IU4 exact execution
```

的单一 authority 链。

### 3.3 Blocker

```text
B-M5-IU4-002
= CORE_CONTROLLED_TOOL_INVOCATION_BOUNDARY_MISSING
```

### 3.4 Required fix

新增：

```text
ApprovedToolInvoker
```

并受控修改 Skill / Workflow Implementation Protocol，使 Domain implementation 的 Tool 调用只能经过该 Gateway。

## 4. B-M5-IU4-003 — Tool Validation Boundary Missing

### 4.1 事实

冻结设计要求：

```text
Tool Input Validation
→ Tool invoke
→ Tool Output Validation
```

当前仓库没有：

```text
ToolInputValidator
ToolOutputValidator
ToolPayloadValidationDecision
```

### 4.2 风险

若 IU4 现在直接调用：

```python
ToolImplementation.invoke(...)
```

则会先产生真实副作用，再等待后续 IU 补 validation。

这不允许。

### 4.3 Blocker

```text
B-M5-IU4-003
= TOOL_INVOCATION_VALIDATION_CONTRACT_MISSING
```

### 4.4 Required fix

在真实 Tool invocation 被授权前，先冻结并实现可注入的 Input / Output Validation contract。

## 5. B-M5-IU4-004 — Invocation Identifier Factory Missing

### 5.1 事实

当前 internal request 要求：

```text
ToolInvocationRequest.tool_call_id
WorkflowExecutionRequest.workflow_instance_id
```

但现有 `ExecutionIdentifierFactory` 只提供：

```text
execution_id
step_execution_id
```

### 5.2 风险

Executor 若临时：

```text
uuid4()
字符串拼接
计数器
```

会把 ID policy 偷进 Core，且不利于 deterministic test / trace / recovery。

### 5.3 Blocker

```text
B-M5-IU4-004
= CAPABILITY_INVOCATION_IDENTIFIER_FACTORY_MISSING
```

### 5.4 Required fix

新增内部注入 factory：

```text
new_tool_call_id(...)
new_workflow_instance_id(...)
```

不修改 Canonical main-chain contract。

## 6. B-M5-IU4-005 — Workflow Tool Authority Not Representable

### 6.1 事实

当前 ToolPlanner 只从：

```text
SkillDefinition.required_tools
SkillDefinition.optional_tools
```

生成 ToolPlan，并只记录：

```text
required_by_skills
```

当前 WorkflowDefinition 没有：

```text
required_tools
optional_tools
```

### 6.2 风险

当：

```text
execution_owner = WORKFLOW
```

时，Workflow 要调用通知、事件、提醒等 Tool，却没有正式 Approved Tool provenance。

如果让 Workflow implementation 自己拿 Tool Adapter：

```text
Approved Tool authority
exact version
permission
validation
future reliability gates
```

都会被绕过。

### 6.3 Blocker

```text
B-M5-IU4-005
= WORKFLOW_TOOL_AUTHORITY_NOT_REPRESENTABLE
```

### 6.4 Required fix

受控扩展：

```text
WorkflowDefinition.required_tools
WorkflowDefinition.optional_tools

ToolCallPlan.required_by_workflows
tool_plan.tool_calls[].required_by_workflows
```

ToolPlanner 必须按照 execution_owner 生成 owner-specific Tool authority。

IU3 Tool Projection 需同步消费 workflow provenance；不得执行时再从 WorkflowDefinition 扩张 Tool 集合。

## 7. Existing Technical Debt Assessment

### 7.1 TD-M5-IU3-01 Registry Namespace Not Pinned

当前 exact resolver 默认 namespace=None。

该问题仍 fail closed，不会执行错版本。

IU4 不重新 Registry lookup，因此本 IU 不扩大该风险。

状态：

```text
TD-M5-IU3-01 = OPEN / NON_BLOCKING_FOR_IU4
```

### 7.2 TD-M5-IU3-04 Optional Tool Step Provenance

当前 selected optional Tool：

```text
required_by_skills = ()
```

没有 step provenance。

IU3 不猜归属。

IU4 第一版也不得暴露给 owner Tool Gateway。

所以：

```text
optional Tool invocation = OUT_OF_SCOPE
```

状态：

```text
TD-M5-IU3-04 = OPEN
NON_BLOCKING only because IU4 explicitly disables optional Tool invocation
MUST CLOSE before optional Tool execution is authorized
```

### 7.3 TD-M5-IU4-01 Direct Tool Fast Path

当前 M4 不能正式生成 direct Tool execution owner。

状态：

```text
TD-M5-IU4-01 = OPEN / NON_BLOCKING
```

IU4 第一版不实现 direct Tool fast path。

### 7.4 TD-M5-IU4-02 Workflow Resume

IU4 第一版只授权 fresh Workflow START。

Resume / callback / checkpoint correlation 进入后续 Persistence / Recovery unit。

状态：

```text
TD-M5-IU4-02 = OPEN / NON_BLOCKING
```

## 8. Proposed Controlled Amendment

建议合并为一次最小受控修正：

```text
CA-M5-IU4-01
Execution Ownership + Core-controlled Invocation Boundary
```

修改范围只允许：

```text
M4 internal CapabilityBinding / opaque capability_plan
M5 internal execution protocols
M5 internal validation / invocation protocols
M5 internal invocation identifier protocols
WorkflowDefinition Tool dependency metadata
M4 ToolPlanner provenance
IU3 approved Tool projection
tests
design docs
```

禁止修改：

```text
Canonical ActionStep
ApprovedActionPlan top-level fields
PolicyDecision
ExecutionEngine signature
ExecutionResult canonical shape
RuntimeOrchestrator
M6
```

## 9. CA-M5-IU4-01 Required Deliverables

至少冻结：

```text
CapabilityExecutionOwner
capability_plan.bindings[].execution_owner

ApprovedToolInvoker

ToolPayloadValidationStatus
ToolPayloadValidationDecision
ToolInputValidator
ToolOutputValidator

CapabilityInvocationIdentifierFactory

WorkflowDefinition.required_tools / optional_tools
ToolCallPlan.required_by_workflows
approved tool_plan workflow provenance

SkillImplementation(..., tool_invoker)
WorkflowImplementation.start(..., tool_invoker)
WorkflowImplementation.resume(..., tool_invoker)
```

并补 Gate：

```text
1. both Skill+Workflow without owner cannot reach execution
2. forced_workflow owner is preserved through Approval
3. IU4 never derives owner from current Registry
4. Skill/Workflow cannot access unapproved Tool through Core gateway
5. Tool input INVALID/UNKNOWN prevents invoke
6. Tool output invalid cannot remain SUCCESS
7. permission UNKNOWN remains UNKNOWN
8. tool_call_id / workflow_instance_id come only from injected factory
9. Canonical contracts unchanged
10. Workflow owner Tool set comes only from approved workflow provenance
11. IU3 projection never expands Workflow tools at execution time
12. no Retry/Idempotency/Lock/M6
```

## 10. Current Formal Status

```text
M4 = CLOSED

M5-IU1 = PASSED
M5-IU2 = PASSED
M5-IU3 = PASSED

M5-IU4 IMPLEMENTATION DESIGN = COMPLETE

B-M5-IU4-001 = OPEN
B-M5-IU4-002 = OPEN
B-M5-IU4-003 = OPEN
B-M5-IU4-004 = OPEN
B-M5-IU4-005 = OPEN

M5-IU4 IMPLEMENTATION READINESS = NOT_READY

NEXT REQUIRED:
CA-M5-IU4-01
Execution Ownership + Core-controlled Invocation Boundary

M5 = IN PROGRESS
```

## 11. Authorization

在上述 5 个 blocker 关闭前：

```text
不得开始真正 Skill / Workflow / Tool production invocation implementation
```

允许做：

```text
CA-M5-IU4-01 controlled amendment
targeted amendment review
four local gates
readiness re-review
```
