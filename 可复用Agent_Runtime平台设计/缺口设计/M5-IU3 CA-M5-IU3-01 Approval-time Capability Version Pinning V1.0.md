# M5-IU3 CA-M5-IU3-01 Approval-time Capability Version Pinning V1.0

> 目标：关闭 `B-M5-IU3-001 APPROVAL_TO_EXECUTION_CAPABILITY_VERSION_NOT_PINNED`。
> 本 Amendment 只固定 M4 planning/approval 时的 capability version identity，不实现 M5-IU3 Capability Resolution。

## 1. Amendment 范围

本次修改：

```text
CapabilityBinding
+ skill_version
+ workflow_version

ToolCallPlan
+ tool_version

ActionPlanDraft.capability_plan.bindings[]
+ skill_version
+ workflow_version

ActionPlanDraft.tool_plan.tool_calls[]
+ tool_version
```

不修改：

```text
Canonical ActionStep
ApprovedActionPlan top-level fields
PolicyDecision
ExecutionEngine
ExecutionResult
RuntimeOrchestrator
```

## 2. Planning-time Pinning

`CapabilityPlanner` 在确认一个 Skill / Workflow 是当前唯一合法 enabled 定义时，同时固定其 `Definition.version`。

对于注入的 `CapabilityBindingRule`：

```text
未填写 version
→ Planner 用被验证 Registry Definition.version 归一化并固定

填写 version 且与被验证 Registry Definition.version 一致
→ 接受

填写 version 但不一致
→ CapabilityPlanningError
```

`ToolPlanner` 对每个已选择 Tool 同样固定 `ToolDefinition.version`。

因此 Planning output 不再只有 capability ID。

## 3. Draft Projection

`ActionPlanDraftAssembler` 将 pinned version 写入已有 opaque subplan：

```text
capability_plan.bindings[].skill_version
capability_plan.bindings[].workflow_version
tool_plan.tool_calls[].tool_version
```

不向 `ActionStep` 新增 version 字段。

## 4. Draft Validation

`PlanValidator` 现在要求：

```text
skill_id != None
→ skill_version 必须存在且非空
→ skill_version 必须等于当前被验证 SkillDefinition.version

workflow_id != None
→ workflow_version 必须存在且非空
→ workflow_version 必须等于当前被验证 WorkflowDefinition.version

tool_id
→ tool_version 必须存在且非空
→ tool_version 必须等于当前被验证 ToolDefinition.version
```

同时禁止：

```text
skill_id=None + skill_version!=None
workflow_id=None + workflow_version!=None
```

Version mismatch 一律 fail closed，不允许 Validator 自动修复。

## 5. Approval Preservation

`PlanApprovalCoordinator` 的既有完整性约束会继续保证：

```text
ApprovedActionPlan planning semantics
=
validated ActionPlanDraft planning semantics
```

因此 capability/tool version fields 会原样进入 ApprovedActionPlan。

M2 PolicyDecision 不新增 version 字段；Policy authorization 仍按 capability ID。

## 6. Tests

本 Amendment 增补/调整测试以证明：

```text
1. CapabilityPlanner 输出 skill_version
2. forced workflow 输出 workflow_version
3. injected binding 被归一化到 Registry version
4. injected wrong version fail closed
5. ToolPlanner 输出 tool_version
6. Draft projection 保存 version
7. Draft Validator 拒绝 missing skill_version
8. Draft Validator 拒绝 skill version drift
9. Draft Validator 拒绝 Tool version drift
10. Approval 原样保存 skill/workflow/tool version
```

## 7. Blocker 状态

代码/测试 amendment 完成后：

```text
B-M5-IU3-001 = FIX_IMPLEMENTED
```

但在四项门禁与 Controlled Amendment Re-Review 完成前，不直接写：

```text
B-M5-IU3-001 = CLOSED
M5-IU3 IMPLEMENTATION READINESS = READY
```

## 8. Required Gates

```text
python -m pytest tests -q
python -m mypy runtime tests
python -m ruff check runtime tests
python -m ruff format --check runtime tests
```

四项全绿后进入：

```text
CA-M5-IU3-01 Targeted Independent Re-Review
```