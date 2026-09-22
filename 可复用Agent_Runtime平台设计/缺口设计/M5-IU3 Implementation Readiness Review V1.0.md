# M5-IU3 Implementation Readiness Review V1.0

> Review baseline: `m5-iu2-targeted-fix@7f61908b`
> 前置：M5-IU1 = PASSED；M5-IU2 = PASSED。

## 1. Review 结论

```text
M5-IU3 IMPLEMENTATION DESIGN = COMPLETE
M5-IU3 IMPLEMENTATION READINESS = NOT_READY
BLOCKER COUNT = 1

B-M5-IU3-001
= APPROVAL_TO_EXECUTION_CAPABILITY_VERSION_NOT_PINNED
```

除该 blocker 外，现有 M5 Readiness Contract 已足以进入 IU3。

## 2. 已具备前置

```text
R-M5-IU3-01 Approved Plan authority = READY
R-M5-IU3-02 Skill/Workflow/Tool Registry infrastructure = READY
R-M5-IU3-03 Implementation Protocols = READY_FOR_IU3_AMENDMENT
R-M5-IU3-04 Execution Permission Contract = READY
R-M5-IU3-05 Workflow Authority = READY
R-M5-IU3-06 Runtime State infrastructure = READY
R-M5-IU3-07 Approved Tool projection = READY_BY_DESIGN
```

已有关键对象包括 ApprovedActionPlan、ActionStep refs、capability_plan/tool_plan、Skill/Workflow/Tool Registry、RegistryKey(id+version+namespace)、Implementation Protocol、ExecutionPermission*、ApprovedWorkflowAuthority、RuntimeExecutionSnapshot/StateEligibility。

## 3. B-M5-IU3-001

### 3.1 问题

M4 当前会检查同一 capability ID 只能有一个 enabled version，但最终 ApprovedPlan 不保存这个 version。

```text
M4: DOMAIN_SKILL@1.0.0 enabled
→ plan records DOMAIN_SKILL
→ registry changes
→ DOMAIN_SKILL@2.0.0 becomes only enabled
→ M5 resolve_skill("DOMAIN_SKILL") may bind 2.0.0
```

即 ApprovedActionPlan 不变，但 executable implementation 改变。

### 3.2 为什么现在升级为 blocker

此前 `TD-M5-02` 在 IU1/IU2 尚未真实绑定 capability，因此可暂缓。IU3 正是正式绑定 execution implementation 的阶段；继续 ID-only resolver 将无法证明 M5 Step 5 的 version compatibility，并破坏 Approved Plan immutability、execution determinism、trace reproducibility。

```text
TD-M5-02 -> B-M5-IU3-001
```

## 4. Required Controlled Amendment

下一步必须先完成：

```text
CA-M5-IU3-01
Approval-time Capability Version Pinning
```

最小修改范围：

```text
M4 CapabilityBinding
+ skill_version
+ workflow_version

M4 ToolCallPlan
+ tool_version

M4 Planner
→ 固化实际 Registry Definition.version

ActionPlanDraft.capability_plan.bindings[]
→ 写入 skill_version/workflow_version

ActionPlanDraft.tool_plan.tool_calls[]
→ 写入 tool_version

M4 PlanValidator
→ 校验 id + version exact Registry record + enabled
```

M2 PolicyDecision 不改字段；Policy 仍按 capability ID 授权。Canonical ActionStep、ApprovedActionPlan 顶层字段、ExecutionEngine、ExecutionResult 均不修改。

## 5. Amendment 后 IU3 Gate

必须证明：

```text
1. 每个 skill binding 带 exact version
2. 每个 workflow binding 带 exact version
3. 每个 tool call 带 exact version
4. Draft Validator 拒绝 id/version drift
5. ApprovedActionPlan 完整保留 version fields
6. M2 PolicyDecision 不扩字段
7. ActionStep 不新增 capability version 字段
8. 既有 M4/M5 测试保持绿色
9. Core 不硬编码 Domain capability/version
```

并通过 pytest / mypy / ruff check / ruff format --check。

## 6. 非阻塞项

### TD-M5-IU3-01 Registry namespace 未进入 ApprovedPlan

RegistryKey 支持 namespace，但 ApprovedPlan 仅使用 ID/version。跨 namespace 同 ID 时继续 fail closed，不猜 namespace。`NON_BLOCKING`。

### TD-M5-IU3-02 runtime_checkable Protocol 不是完整签名证明

沿用 TD-M5-01；runtime_checkable 负责 structural runtime check，mypy + 后续 executor result validation 补足。`NON_BLOCKING`。

### TD-M5-IU3-03 Tool-specific allowed_states 未冻结

ToolDefinition 当前无 allowed_states。直接 Tool Step 的通用状态合法性继续由 IU2 ExecutionStateEligibilityEvaluator 负责；IU3 只额外消费 Skill/Workflow 已冻结 allowed_states。`NON_BLOCKING`。

## 7. 最终状态

```text
M4 = CLOSED
M5 IMPLEMENTATION READINESS = READY
M5-IU1 = PASSED
M5-IU2 = PASSED

M5-IU3 IMPLEMENTATION DESIGN = COMPLETE
M5-IU3 IMPLEMENTATION READINESS = NOT_READY_PENDING_CA_REVIEW

B-M5-IU3-001 = FIX_IMPLEMENTED

CA-M5-IU3-01 = CODE_TEST_DOC COMPLETE
LOCAL FOUR GATES = PENDING
TARGETED INDEPENDENT RE-REVIEW = PENDING

NEXT REQUIRED:
CA-M5-IU3-01 Local Gates
→ Targeted Independent Re-Review

M5 = IN PROGRESS
```

在 B-M5-IU3-001 关闭前：

```text
M5-IU3 production implementation = NOT ALLOWED TO START
```