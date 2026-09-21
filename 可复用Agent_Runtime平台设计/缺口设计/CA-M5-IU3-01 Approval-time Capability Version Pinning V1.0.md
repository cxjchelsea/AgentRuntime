# CA-M5-IU3-01 Approval-time Capability Version Pinning V1.0

> 目的：关闭 M5-IU3 Readiness blocker `B-M5-IU3-001`。
> 范围：只固定 M4 planning/approval 到 M5 execution 的 capability version identity；不实现 IU3 runtime resolver。

## 1. Blocker

```text
B-M5-IU3-001
APPROVAL_TO_EXECUTION_CAPABILITY_VERSION_NOT_PINNED
```

原链路只保存 Skill/Workflow/Tool ID，无法证明执行时实现版本与规划/批准时一致。

## 2. Controlled Amendment

### CapabilityBinding

新增：

```text
skill_version
workflow_version
```

`CapabilityPlanner` 在规划时从实际选中的唯一 enabled Registry Definition 固化 version。注入 BindingRule 可以只给 ID，Core 会将当前已验证 Definition.version 固化；若规则显式给出的 version 与当前选中 Definition 不一致则 fail closed。

### ToolCallPlan

新增：

```text
tool_version
```

`ToolPlanner` 在生成 approved tool-plan 前固定实际 ToolDefinition.version。

### Draft projection

`ActionPlanDraftAssembler` 将 version identity 写入：

```text
capability_plan.bindings[].skill_version
capability_plan.bindings[].workflow_version
tool_plan.tool_calls[].tool_version
```

### Draft validation

`PlanValidator` 不再只验证 capability ID 存在，而是要求 capability 存在时必须有 non-blank pinned version，并调用 Registry exact `get(id, version)` 校验：

```text
exact key exists
RegistryRecord.enabled
Definition.enabled
```

ID 存在但 pinned version 不存在时必须拒绝，不能重新选择其他版本。

### Approval preservation

`PlanApprovalCoordinator` 原有完整语义一致性检查已经保证 capability_plan/tool_plan 从 validated Draft 原样保留到 ApprovedActionPlan；新增回归测试明确锁住 version fields。

## 3. Frozen boundaries

本 Amendment 未修改：

```text
ActionStep Canonical fields
ApprovedActionPlan top-level schema
PolicyDecision
ExecutionEngine
ExecutionResult
RuntimeOrchestrator
M2 authorization semantics
```

M2 继续按 capability ID 授权；version 是 planning/execution identity，不是新的 policy dimension。

## 4. Regression coverage

新增/加强测试证明：

```text
CapabilityPlanner 自动固定 skill version
forced workflow 自动固定 workflow version
ToolPlanner 自动固定 tool version
BindingRule version drift 被拒绝
Assembler 把 version 写入 opaque subplan
Validator 拒绝 skill id/version drift
Validator 拒绝 tool id/version drift
ApprovedActionPlan 原样保留 version fields
```

## 5. Current status

```text
B-M5-IU3-001 = FIX_IMPLEMENTED
CA-M5-IU3-01 = CODE COMPLETE
```

最终关闭 blocker 仍需四项本地门禁和 Targeted Amendment Review。

## 6. Required gates

```text
python -m pytest tests -q
python -m mypy runtime tests
python -m ruff check runtime tests
python -m ruff format --check runtime tests
```

全部通过后才允许：

```text
B-M5-IU3-001 = CLOSED
M5-IU3 IMPLEMENTATION READINESS = READY
```