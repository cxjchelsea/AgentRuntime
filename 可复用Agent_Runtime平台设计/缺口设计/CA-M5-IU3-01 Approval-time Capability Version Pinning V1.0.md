# CA-M5-IU3-01 Approval-time Capability Version Pinning V1.0

> 目标：关闭 `B-M5-IU3-001 APPROVAL_TO_EXECUTION_CAPABILITY_VERSION_NOT_PINNED`。
> 本 Amendment 只固定 planning/approval 时已经选择的 capability version；不实现 M5-IU3 runtime resolution。

## 1. 修改范围

### M4 CapabilityBinding

新增：

```text
skill_version
workflow_version
```

规划器在确定 Skill / Workflow 后，直接从当时通过校验的 Registry Definition 固化 version。

BindingRule 可以只返回 capability ID；Core 会在验证该 binding 合法后，以当前唯一合法 Registry Definition 补齐 version。

如果 BindingRule 显式给出 version，则该 version 必须和当前选择的 Registry Definition 完全一致，否则 fail closed。

### M4 ToolCallPlan

新增：

```text
tool_version
```

ToolPlanner 在生成 ToolCallPlan 时固化实际 ToolDefinition.version。

### ActionPlanDraft projection

`ActionPlanDraftAssembler` 现在写入：

```text
capability_plan.bindings[].skill_version
capability_plan.bindings[].workflow_version
tool_plan.tool_calls[].tool_version
```

### M4 Draft Validation

Draft Validator 现在要求：

```text
skill_id 存在 -> skill_version 必须存在
workflow_id 存在 -> workflow_version 必须存在
tool_id 存在 -> tool_version 必须存在
```

并做 exact：

```text
id + pinned_version
```

校验。Pinned version unavailable / disabled / drift 时直接拒绝 Draft。

## 2. 不修改项

本 Amendment 不修改：

```text
ActionStep Canonical Contract
ApprovedActionPlan top-level fields
PolicyDecision
ExecutionEngine
ExecutionResult
RuntimeOrchestrator
Skill / Workflow / Tool Protocol
```

M2 Policy 仍按 capability ID 授权；version 是 execution identity，不是新的 Policy authority。

## 3. Approval Preservation

现有 `PlanApprovalCoordinator` 会检查 ApprovedActionPlan 除 approval metadata 外必须与 validated Draft 保持语义一致。

因此 version pin 进入 Draft 后会被原样保留到 ApprovedActionPlan。

新增测试显式确认：

```text
ApprovedActionPlan.capability_plan == Draft.capability_plan
ApprovedActionPlan.tool_plan == Draft.tool_plan
```

且 pinned version 仍存在。

## 4. Regression Coverage

新增/增强测试覆盖：

```text
CapabilityPlanner 自动 pin skill_version
forced workflow 自动 pin workflow_version
ToolPlanner 自动 pin tool_version
BindingRule 显式错误 skill_version -> reject
Draft skill version drift -> reject
Draft workflow version drift -> reject
Draft tool version drift -> reject
Draft missing version pin -> reject
ApprovedActionPlan 保留 pinned versions
```

## 5. Blocker 状态

代码层修复已完成：

```text
B-M5-IU3-001 = FIX_IMPLEMENTED
```

但正式关闭仍要求：

```text
pytest
mypy
ruff check
ruff format --check
+ Independent Amendment Review
```

在这些 gate 完成前：

```text
B-M5-IU3-001 = NOT_YET_CLOSED
M5-IU3 IMPLEMENTATION READINESS = PENDING_AMENDMENT_VERIFICATION
```