# M5-IU3 Capability Resolution 实现设计 V1.0

> 基线：M5-IU2 = PASSED，PR #36 head `7f61908b`。
> 本文件只设计 M5-IU3 Capability Resolution，不实现 Skill / Workflow / Tool 调用，不进入 Retry / Timeout / Idempotency / Cancellation Handler / M6。

## 1. IU3 目标

```text
Scheduler 已经选中了一个 Approved Step，
这个 Step 已批准的 Skill / Workflow / Tool 引用，
此刻能否解析成唯一、当前可用、允许执行的具体实现？
```

正式链路：

```text
ApprovedActionPlan + READY ActionStep + ExecutionContext
        ↓
Approved Capability Projection
        ↓
Exact Registry Resolution
        ↓
Enabled / Version / Implementation Check
        ↓
Capability-specific State Eligibility
        ↓
Workflow Authority Check
        ↓
Tool Execution Permission Check
        ↓
ResolvedStepCapabilities
        ↓
后续 Executor（不在 IU3）
```

IU3 不重新规划、不选择新的 Capability、不修改 ApprovedActionPlan。

## 2. Authority Sources

IU3 的能力 authority 只允许来自已经批准的计划：

```text
ActionStep.skill_id
ActionStep.workflow_id
ApprovedActionPlan.capability_plan
ApprovedActionPlan.tool_plan
policy_snapshot.forced_workflow（如存在）
```

Registry 只负责验证已批准引用当前是否仍存在、enabled、版本是否匹配、implementation_ref 是否有效、当前状态和执行权限是否允许。

```text
Registry Discovery != Capability Selection
Registry Resolution != Replan
Missing Approved Capability != Search Similar Capability
Resolution Failure != Capability Substitution
```

## 3. Approved Tool Source

`ActionStep.tool_requirement` 不是完整 Tool 列表。M4 `SequencePlanner` 当前语义是：

```text
只有一个 required tool -> ActionStep.tool_requirement = tool_id
多个 required tools -> ActionStep.tool_requirement = None
```

完整已批准 Tool 集合在 `ApprovedActionPlan.tool_plan.tool_calls[]`。因此冻结：

```text
ApprovedActionPlan.tool_plan = approved Tool authority source
ActionStep.tool_requirement = 单 Tool 场景的一致性投影
```

对于当前 Step：

1. `skill_id` 若存在，读取 `tool_plan.tool_calls[].required_by_skills` 中包含该 skill_id 的 Tool；
2. `tool_requirement` 若存在，必须已经出现在 Approved tool_plan，否则 fail closed；
3. 不得从当前 SkillDefinition.required_tools 新增 Tool；
4. Registry metadata 只能校验 Approved Tool，不能扩张 Approved Tool Set。

```text
Current SkillDefinition.required_tools != new execution authority
```

## 4. Capability 类型

第一版支持：

```text
SKILL
WORKFLOW
TOOL
NO_EXTERNAL_CAPABILITY
```

没有外部能力引用时返回 `NO_EXTERNAL_CAPABILITY`，不是 Registry failure；也不代表 Step 已成功。

## 5. Version Safety

### 5.1 当前问题

现有 ApprovedPlan 只保存 capability ID。M4 规划时通过“同一 ID 只能有一个 enabled version”选出当时定义；现有 ExecutionImplementationResolver 又在执行时按 ID 找“当前唯一 enabled version”。

```text
Planning: SKILL_A@1.0 enabled
→ ApprovedPlan 只记录 SKILL_A
→ Registry changes
→ Execution: SKILL_A@2.0 becomes only enabled version
→ current resolver may execute 2.0
```

这就是既有 `TD-M5-02 Approval-to-Execution Capability Version Drift`。

### 5.2 IU3 正式要求

IU3 不接受执行时重新选择当前唯一版本。ApprovedPlan 必须携带规划/批准时版本：

```text
capability_plan.bindings[].skill_version
capability_plan.bindings[].workflow_version
tool_plan.tool_calls[].tool_version
```

不修改 Canonical ActionStep。M5-IU3 必须按 `id + approved_version` exact lookup。

若批准版本 missing / disabled / definition disabled / implementation_ref invalid，则 fail closed；禁止找最新版本、找另一 enabled version、自动升级或 fallback。

## 6. Version Pinning Controlled Amendment

为避免重开 Canonical ActionStep，使用现有 opaque subplan 做最小受控扩展。

```text
CapabilityBinding:
  action_id
  skill_id
  skill_version
  workflow_id
  workflow_version

ToolCallPlan:
  tool_id
  tool_version
  required
  required_by_skills
  ...
```

版本必须来自规划时真正通过 Registry 校验的 Definition。Policy Recheck 后 capability_plan/tool_plan 原样进入 ApprovedActionPlan；M2 Policy 仍按 ID 授权。

## 7. Exact Resolution Contract

IU3 实现建议新增内部类型：

```text
CapabilityKind
ApprovedCapabilityReference
ResolvedCapability
ResolvedStepCapabilities
CapabilityResolutionStatus
CapabilityResolutionDecision
```

建议状态：

```text
RESOLVED
NO_EXTERNAL_CAPABILITY
BLOCKED
UNKNOWN
```

`ResolvedCapability` 至少冻结 kind / capability_id / version / definition / implementation_ref / source。后续 Executor 必须消费 IU3 已冻结结果，禁止再次按 ID 查询 Registry 重新选择版本。

## 8. Registry Resolution

当前 ID-only API 只是 Readiness 临时能力。IU3 正式实现需要 exact version resolution：

```text
resolve_skill(skill_id, version)
resolve_workflow(workflow_id, version)
resolve_tool(tool_id, version)
```

或等价 exact-record API。必须同时确认 RegistryKey exact match、RegistryRecord.enabled、Definition.enabled、implementation_ref 存在且满足对应 Protocol。

## 9. Current State Eligibility

IU2 已负责 Step 级 Runtime State eligibility；IU3 只补 Capability metadata 自身限制：

```text
SkillDefinition.allowed_states
WorkflowDefinition.allowed_states
```

规则：allowed_states=None 表示无额外限制；非空且当前 state 命中则 eligible；不命中 BLOCKED；state 不可得则 UNKNOWN。

Tool 当前无 allowed_states；直接 Tool Step 的通用状态合法性继续由 IU2 ExecutionStateEligibilityEvaluator 负责。

## 10. Workflow Authority

Workflow 必须同时满足：已在 ApprovedActionPlan、project_workflow_authority 允许、forced_workflow（如有）一致、批准版本仍 enabled、allowed_states 当前允许。IU3 不创建新的 Workflow Policy。

## 11. Tool Permission

当前冻结 Permission Contract 只针对 Tool：ExecutionPermissionContextProvider + ExecutionPermissionEvaluator + ToolDefinition.required_permissions。

```text
ALLOWED -> 可进入后续 Executor
DENIED  -> BLOCKED
UNKNOWN -> UNKNOWN
```

`UNKNOWN != ALLOWED`。Skill / Workflow 当前无 generic required_permissions，IU3 不临时发明第二套权限模型。

## 12. No Capability Substitution

以下全部禁止：

```text
Approved skill missing -> choose another skill
Approved workflow missing -> choose another workflow
Approved tool missing -> choose another tool
Approved version disabled -> choose newest version
Permission denied -> choose another capability
State ineligible -> choose another capability
```

这些都属于重新规划，必须回 Runtime / M4。

## 13. Failure Semantics

建议 reason codes：

```text
CAPABILITY_VERSION_UNPINNED
CAPABILITY_NOT_FOUND
CAPABILITY_DISABLED
IMPLEMENTATION_REF_MISSING
IMPLEMENTATION_PROTOCOL_INVALID
CAPABILITY_STATE_INELIGIBLE
CAPABILITY_STATE_UNKNOWN
WORKFLOW_AUTHORITY_INVALID
TOOL_PERMISSION_DENIED
TOOL_PERMISSION_UNKNOWN
APPROVED_TOOL_PLAN_INCONSISTENT
```

## 14. IU3 明确不实现

```text
Skill execute / Workflow start-resume / Tool invoke
Tool schema validation
Timeout / Retry / Idempotency behavior
Resource Lock
Cancellation / Preemption side-effect handler
Checkpoint / Recovery
Execution aggregation
M6 / Response / State-Memory Update
```

## 15. Planned Test Gate

至少覆盖：只解析 Approved refs；exact id+version；批准版本 disabled 不替代；implementation_ref fail closed；Skill/Workflow state；forced workflow；Tool DENIED/UNKNOWN；多 required tools 从 approved tool_plan 投影；tool_requirement 与 tool_plan 一致；NO_EXTERNAL_CAPABILITY 不伪装成功；Resolver 不调用真实 capability、不修改 Plan、不进入下游阶段。

## 16. 当前设计结论

```text
M5-IU3 IMPLEMENTATION DESIGN = COMPLETE
```

能否开始代码实现，以配套 Readiness Review 为准。