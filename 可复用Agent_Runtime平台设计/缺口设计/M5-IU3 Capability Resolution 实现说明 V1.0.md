# M5-IU3 Capability Resolution 实现说明 V1.0

> 基线：`m5-iu3-ca01-version-pinning@0d6c557`
> 前置：M5-IU3 Implementation Readiness = READY；CA-M5-IU3-01 = PASSED。

## 1. 本轮实现范围

```text
ApprovedActionPlan
+ Approved ActionStep
+ ExecutionContext
+ current RuntimeControlState
        ↓
Approved Capability Projection
        ↓
exact id + approved_version Registry Resolution
        ↓
implementation_ref protocol check
        ↓
Skill / Workflow allowed_states
        ↓
Workflow Authority
        ↓
Tool Execution Permission
        ↓
ResolvedStepCapabilities
```

本轮没有进入 Capability 的真实执行。

## 2. 新增正式对象

新增 `runtime/execution/capability_resolution.py`，主要冻结：

```text
CapabilityKind
CapabilityReferenceSource
CapabilityResolutionStatus
ApprovedCapabilityReference
ApprovedStepCapabilityReferences
ResolvedCapability
ResolvedStepCapabilities
CapabilityResolutionDecision
ApprovedStepCapabilityProjector
StepCapabilityResolver
```

Resolution 四态：

```text
RESOLVED
NO_EXTERNAL_CAPABILITY
BLOCKED
UNKNOWN
```

`NO_EXTERNAL_CAPABILITY` 只表示当前 Step 不需要外部 Skill/Workflow/Tool，不等于执行成功。

## 3. Approved Authority Projection

Skill / Workflow authority 只来自 ActionStep 与 approved `capability_plan.bindings[]` 的一致交集。

Tool authority：

```text
ApprovedActionPlan.tool_plan.tool_calls[]
```

是完整批准来源；`ActionStep.tool_requirement` 仅用于单 Tool projection 一致性校验。

多 required tools 通过：

```text
tool_calls[].required_by_skills
```

投影到当前 Skill Step。

以下情况 fail closed：

```text
Step 不属于 ApprovedPlan
binding 与 Step skill/workflow 不一致
pinned version 缺失
tool_requirement 不在 approved tool_plan
同一 Tool 出现冲突 version
```

## 4. Exact Version Resolution

Readiness 阶段旧的 ID-only `ExecutionImplementationResolver` 已正式收紧为：

```text
resolve_skill(skill_id, approved_version)
resolve_workflow(workflow_id, approved_version)
resolve_tool(tool_id, approved_version)
```

内部只调用 Registry exact `get(id, version)`。

禁止：

```text
lookup current latest
lookup current unique enabled version
fallback to another version
substitute another capability
```

正式区分：

```text
CAPABILITY_NOT_FOUND
CAPABILITY_DISABLED
IMPLEMENTATION_REF_MISSING
IMPLEMENTATION_PROTOCOL_INVALID
```

## 5. State Gate

IU3 只消费 SkillDefinition / WorkflowDefinition 已冻结的 `allowed_states`。

```text
allowed_states absent/empty -> no extra restriction
state matched -> continue
state mismatch -> BLOCKED / CAPABILITY_STATE_INELIGIBLE
current state unavailable -> UNKNOWN / CAPABILITY_STATE_UNKNOWN
```

Tool 没有新增 allowed_states；通用 Step state safety 仍由 IU2 RuntimeExecutionChecker 管理。

## 6. Workflow Authority

复用既有 `project_workflow_authority(...)`：

```text
Approved workflow reference
+ policy_snapshot.forced_workflow
```

必须一致。

不新增 `allowed_workflows` / `forbidden_workflows` Policy 字段。

## 7. Tool Permission

复用：

```text
ExecutionPermissionContextProvider
ExecutionPermissionEvaluator
PermissionDecisionStatus
```

```text
ALLOWED -> continue
DENIED -> BLOCKED / TOOL_PERMISSION_DENIED
UNKNOWN -> UNKNOWN / TOOL_PERMISSION_UNKNOWN
```

Permission provider/evaluator 无法可靠给出事实时同样 fail closed 为 UNKNOWN。

## 8. Executor Boundary

`ResolvedStepCapabilities` 携带已经冻结的：

```text
capability_id
approved version
Registry definition
implementation_ref
authority source
```

后续 Executor 应直接消费该结果，不得再按 ID 查询 Registry 重新选版本。

## 9. 本轮明确未实现

```text
Skill.execute
Workflow.start/resume
Tool.invoke
Tool input/output schema validation
Retry / Timeout / Idempotency behavior
Resource Lock
Cancellation / Preemption side-effect handler
Checkpoint / Recovery
Execution Aggregator
M6 Result Validation
Response
State / Memory Update
```

## 10. 回归门禁

新增 `tests/test_m5_iu3_capability_resolution.py`，覆盖：

```text
exact approved version resolution
no capability substitution
disabled exact version
missing implementation_ref
wrong protocol
Skill / Workflow allowed_states
state UNKNOWN
forced workflow authority drift
Tool permission DENIED / UNKNOWN
multiple required tools
tool_requirement/tool_plan consistency
mutated step authority rejection
resolution does not invoke capability
NO_EXTERNAL_CAPABILITY != execution success
```

同时更新 M5 Readiness resolver 测试，使其正式使用 exact-version API。

## 11. 非阻塞技术债

```text
TD-M5-IU3-01 REGISTRY_NAMESPACE_NOT_PINNED
TD-M5-IU3-04 OPTIONAL_TOOL_STEP_PROVENANCE_NOT_FROZEN
```

其中 optional Tool 当前虽然已进入 approved tool_plan，但没有冻结其 step/skill provenance。IU3 不猜归属，因此不会产生错误执行；在后续真正 Skill/Tool Executor 允许 optional Tool invocation 前必须补齐。

## 12. 当前状态

```text
M5-IU3 IMPLEMENTATION = CODE COMPLETE
M5-IU3 INDEPENDENT IMPLEMENTATION REVIEW = PASSED
M5-IU3 VERIFICATION = PENDING FOUR LOCAL GATES
M5-IU3 = READY_TO_PASS_AFTER_FOUR_LOCAL_GATES

M5 = IN PROGRESS
```

只有四项本地门禁全部通过后，才能写 `M5-IU3 = PASSED`。