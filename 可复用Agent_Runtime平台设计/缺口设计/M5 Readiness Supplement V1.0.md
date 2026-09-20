# M5 Readiness Supplement V1.0

> 适用范围：M5 Readiness Re-Review 新发现的 B-M5-006 / B-M5-007。
> 本补充不开始 M5-IU1，不修改 Canonical `ApprovedActionPlan` / `ExecutionResult`，不修改冻结 `ExecutionEngine` 签名，也不重开 M2。

## 1. Supplement 目标

本次只解决：

```text
B-M5-006 Execution Permission Contract Missing
B-M5-007 Workflow Policy Semantics Mismatch
```

并登记两个非阻塞技术债：

```text
TD-M5-01 Runtime Protocol Check ≠ Full Signature Validation
TD-M5-02 Approval-to-Execution Capability Version Drift
```

## 2. RS-M5-01：Execution Permission Contract

### 2.1 边界

正式区分：

```text
Planning Authorization
!=
Execution Permission
```

M2/M4 决定某 Tool 是否可以进入 `ApprovedActionPlan`；M5 在真正调用前仍必须确认当前执行主体、绑定、设备、环境、角色、Workflow State 等实时执行权限事实。

### 2.2 新增内部合同

新增：

```text
PermissionDecisionStatus
ExecutionPermissionContext
PermissionDecision
ExecutionPermissionContextProvider
ExecutionPermissionEvaluator
```

`PermissionDecisionStatus` 冻结为：

```text
ALLOWED
DENIED
UNKNOWN
```

`UNKNOWN` 不得当作 ALLOWED；后续 M5-IU 必须 fail closed 或返回明确不可确认状态，不得因此替换 Capability 或 Replan。

### 2.3 ExecutionPermissionContext

Context 只承载当前已投影的执行权限事实：

```text
execution_id
identity_scope
granted_permissions
denied_permissions
evidence_refs
```

`granted_permissions` 与 `denied_permissions` 不能冲突。权限事实如何从绑定、设备、环境、角色、Domain 数据投影，由注入的 `ExecutionPermissionContextProvider` 负责；Core 不硬编码业务角色或权限名。

### 2.4 PermissionDecision

Decision 必须包含非空 `reason_codes`。`ALLOWED` 不能同时携带 `missing_permissions`。

`ExecutionPermissionEvaluator` 只判断 ToolDefinition.required_permissions 在当前执行权限上下文下的状态，不修改 ApprovedPlan，不替换 Tool，不拥有 Planning 权限。

因此：

```text
B-M5-006 = FIX_IMPLEMENTED
```

## 3. RS-M5-02：Workflow Policy Semantics Alignment

### 3.1 不新增 allowed_workflows / forbidden_workflows

当前冻结 `PolicyDecision` 不存在：

```text
allowed_workflows
forbidden_workflows
```

本 Supplement 不为了 M5 重开 M2，也不向 PolicyDecision 临时新增这两个字段。

### 3.2 Workflow Authority 正式来源

Workflow 执行权来自：

```text
ApprovedActionPlan 中已经批准的 workflow_id
+
policy_snapshot.forced_workflow（如存在）
+
WorkflowRegistry enabled/version
+
Runtime execution eligibility
+
Execution Permission
```

新增：

```text
ApprovedWorkflowAuthority
project_workflow_authority(...)
```

它只把已经批准的 Workflow 引用投影为 M5 执行 authority，不创建新的 Policy。

若 `policy_snapshot.forced_workflow` 存在，则 ApprovedPlan 必须仍包含该 Workflow，且不能同时携带其他 Workflow；否则 fail closed。

因此：

```text
B-M5-007 = FIX_IMPLEMENTED
```

## 4. 文档修正

M5 V2.0 的 M2 依赖已经修订为：

```text
PolicyDecision / Policy Snapshot
Allowed / Forbidden Tools
Allowed / Forbidden Skills
forced_workflow（如存在）
Safety Lock
Preemption Decision
Required Confirmation
```

删除不存在的 generic `Allowed Workflows` 依赖。

Tool Permission 章节同步冻结 Planning Authorization 与 Execution Permission 的区别，并引用上述 Permission Contract。

## 5. 非阻塞债

```text
TD-M5-01
runtime_checkable Protocol 只提供结构成员检查；
完整参数/返回类型仍依赖 mypy + 调用时结果类型校验。

TD-M5-02
ApprovedActionPlan 当前按 capability ID 授权，未冻结 ID+version；
ExecutionImplementationResolver 通过“同一 ID 仅一个 enabled version”暂时 fail closed。
```

这两项不阻塞 M5-IU1，但必须在 Capability Resolution / Tool Executor 实现时继续跟踪。

## 6. Supplement Verification Gate

合并前必须运行：

```text
python -m pytest tests -q
python -m mypy runtime tests
python -m ruff check runtime tests
python -m ruff format --check runtime tests
```

并确认：

```text
1. ExecutionPermissionEvaluator 不修改计划、不替换 Capability
2. PermissionContext 不硬编码业务角色/权限名
3. UNKNOWN 不等于 ALLOWED
4. PolicyDecision 未新增 allowed_workflows / forbidden_workflows
5. Workflow authority 只来自 ApprovedPlan + forced_workflow + runtime checks
6. ExecutionEngine frozen interface 未变化
```

满足后再进行 M5 Readiness Final Review。