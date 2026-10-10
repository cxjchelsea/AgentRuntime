# PR #91｜GA-01A G01/G02/G03 针对性详细设计复审 V1.0

> **审查版本**：PR #91 原始 HEAD `9d38375772664e23c37c8bb189606676e001217a`；main 基线 `53cdda379979be836262df1bf6f9382c7ba89897`。  
> **审查范围**：G01 M2 Admission、G02 跨迭代关联、G03 Sandbox/NoGrant 隔离。  
> **方式**：仓库现有源码与既有测试静态逐项对照；不是外部审查者的独立审查，也未执行测试。  
> **结论：DESIGN_CONDITIONS_RESOLVED；IMPLEMENTATION_EVIDENCE_OPEN。** 三项的**设计决策**已确定；需要通过首个实现切片的测试证明，不把“设计收口”冒充代码完成或 GA-01B 整体 Ready。

## 1. G01 — M2 增强 Admission：设计决策 CLOSED

### 1.1 原源码真实能力

`runtime/orchestration/m2_runtime.py` 中：
- `_evaluate_integrated_policy`：`PrioritySubjectResolver.resolve(input,context,understanding,deep_safety)` → `RuntimeConstraintEvaluator.evaluate(...,current_priority_subject,incoming_priority_subject)` → `RuntimeConstraint.policy_decision`。
- `_assert_runtime_constraint_allows_flow`：先验证约束数量=1、`request_id` 对齐、`constraint.policy_decision == decision`；随后依严格顺序：
  1. blocked/!allowed：如果 `forced_workflow` 非空，抛 `AlternatePathRequiredError`；否则 `RuntimeControlBlockedError(POLICY_BLOCKED)`；
  2. `incoming_disposition != PROCESS_NOW`：抛 `RuntimeControlBlockedError(INCOMING_...)`；
  3. `requires_interruption` 且有正在运行的 subject：抛 `PreemptionEffectRequiredError`，不自动执行抢占副作用。
- `runtime/constraint_management/engine.py::RuntimeConstraintEvaluator` 已按 Runtime State → Priority → Preemption → Policy 求值；没有做真实中断/恢复副作用。
- 现有 `tests/test_m2_runtime_integration_gate.py` 已声明针对 forced workflow、blocked、DEFER、preemption、cross-turn plan correlation 的测试；**本轮只检查了测试源码，没有重跑**。

### 1.2 唯一采用的复用方案

**不让新 Agent Core 直接调用 M2 的 protected methods，也不复制一套判断逻辑。**

首个 GA-01B PR 内做 **最小 M2 公共组件提取**：
- 推荐位置：`runtime/orchestration/m2_admission.py`，定义 `M2AdmissionEvaluator`（命名为候选）及 `assert_admission_allows_flow(constraint,request_id,policy)`；
- 将以上唯一的现有判断逻辑**原样迁出** `M2RuntimeOrchestrator`，使原 `run()` 和新 `AgentRuntimeStepAdapter` **都调用同一实现**；
- `M2RuntimeOrchestrator` 原 protected helper 可短暂保持薄代理以最小化对既有测试的影响；不得留下两套相互分叉的实质逻辑；
- `M2AdmissionEvaluator` 输入为 `RuntimeInput`、`RuntimeContext`、`UnderstandingState`、`SafetyResult(DEEP)`、现有 `PrioritySubjectResolver` 与 `RuntimeConstraintEvaluator`。输出为原有 `RuntimeConstraint` 与 `PolicyDecision`，非新 Canonical 合同；
- 在 `PolicyDecision` 出口做 gate；若 forced workflow / DEFER / preemption，则停止 GA-01 普通 Loop，**不暗中派生其他 Workflow**。

**设计检查点**：提取前后测试用例的异常类型、reason、阶段边界和 M5 调用次数不变；不涉及修改 M2 的安全优先级配置。

### 1.3 G01 可验收 Test

`G01-1` 原增强 M2 正常路径与 Agent 新 Adapter 同获同一 `PolicyDecision`；`G01-2` forced workflow 仍在 PLAN 前阻断；`G01-3` blocked 优先于 disposition；`G01-4` DEFER 拒绝；`G01-5` required preemption 必须抛异常且状态无副作用；`G01-6` `constraint.request_id` 或 `policy_decision` 错配拒绝。精确比对已有 G2 用例，绝不能仅断言“都返回错误”。

## 2. G02 — Request/Plan/Execution/Observation：设计决策 CLOSED

### 2.1 源码证明的约束

- `RuntimeInput` 已包含 `request_id`、`trace_id`、`session_id`、`subject_id`、`identity_scope`、`source` 和 `trigger_type`。
- `UnderstandingState.metadata.request_id` 与 Deep `SafetyResult.request_id` 必须一致（`RuntimeConstraintEvaluator._validate_turn_continuity`）。
- `ActionPlanDraft.request_id` 从 Understanding metadata 生成（`DefaultM4Planner.plan`）；M2 在 PLAN/PLAN_VALIDATE/POLICY_RECHECK 必须严格检查 request_id。
- `ExecutionResult.request_id` / `plan_id` / `identity_scope` 关联到 Approved Plan；`runtime/validation/slice_a.py::admit_validation_input` 还要求 session/context、scope 和 plan/step/tool IDs 关联。
- `RuntimeContext.domain_extensions` 只有 `domain_id`，当前 Canonical Schema 没有业务包版本指纹字段；该值必须保留在 AgentRun 内部绑定信封，不能偷偷塞入 Canonical Contract 未经审查。

### 2.2 精确身份与标识所有权

```text
AgentRun ID (new, only Agent Core)
  original_request_id / original_trace_id / subject / identity_scope
  session / tenant / domain_id + exact version + binding fingerprint
    |
    +-- Iteration 0: request_id = original RuntimeInput.request_id
    |               turn trace = original or derived trace_id
    |               approved_plan_id = M4 generated plan_id
    |               execution_id = M5 generated execution_id
    |
    +-- Iteration N>=1: unique internal request_id = run_id + iteration ordinal
                    parent_original_request_id preserved in AgentRun Envelope
                    source = SYSTEM, trigger_type = SYSTEM_EVENT
                    user text NOT replaced by ToolResult text
                    context = original goal + immutable verified sandbox observation
                    approved_plan_id / execution_id unique to this request
```

**为什么内部迭代要使用新 request_id**：避免把两轮 `ActionPlanDraft/ApprovedActionPlan/ExecutionResult` 归到同一个物理请求，并为每轮日志、幂等与权限 scope 提供明确标识。**注意**：`source=SYSTEM` / `SYSTEM_EVENT` 是符合现有枚举的*设计方案*，**并不证明现有 InputProcessor/ContextBuilder/M3 会正确对待内部迭代**；必须通过两个真实 Provider 的 Integration Test 验证。遇到拒绝时应 STOP，不得悄悄将第二轮改回 USER_TEXT。

**固定字段**：每轮 `subject_id`、`identity_scope`、`session_id`、`tenant_id`、`domain_id/version/fingerprint` 与 Run Binding 一致；`trace_id` 各轮唯一并与父 run 建立索引；`plan_id` 唯一且 `plan.request_id == current_iteration.request_id`；`execution.plan_id == approved.plan_id`、`execution.request_id == current_iteration.request_id`。

- 不允许复制旧轮的 `ValidatedResult` 或 `ExecutionResult` 让其假装属于当前 iteration；历史证据由不可变 `PreviousObservationRef` 引用，只能读不能重新确认执行。
- Context Projection 中的 Observation 附来源轮次、执行/批准计划、绑定指纹、scope，**仅**作为数据，不改变当前计划审批权威。
- 一旦跨 iteration 的身份、scope、绑定版本或请求关联不一致：`BLOCK`，不得降级为部分成功。
- 系统时间、预算、Trace 等加入 Agent 自有内部 envelope，不得扩写冻结 Runtime Canonical 字段。
- `RuntimeControlState` 不因 Loop 内部 iteration 改成新领域状态。

### 2.3 G02 Test

`G02-1` Iteration 0 与 N 唯一 request/trace，父链接保留；`G02-2` Understanding/Safety/Plan/Execution request 对齐；`G02-3` session/identity/tenant/domain 任何一个变化均 BLOCK；`G02-4` previous observation 只作为外部上下文证据，不能当本轮动作；`G02-5` 重复批准计划 ID、重复 Tool call ID、跨轮错配均拒绝；`G02-6` 内部 `SYSTEM_EVENT` 输入由 Context/M3 真实接受，并能因两种 Observation 做不同决策；`G02-7` 内部事件不冒充用户主动发起的新业务任务。

## 3. G03 — Sandbox / M6 Truth Boundary：设计决策 CLOSED

### 3.1 不允许混淆的两个世界

| 运行路径 | 可信来源与可做什么 | 禁止做什么 |
|---|---|---|
| G1/G2 `DENY_ONLY_GATED` | `M6NoGrantTurnHandle` 做结构化准入，生成 NoGrant `ValidatedResult` 和 `BLOCK_BEFORE_M7_M8` | 不能做正向 Claim、M7 回复、M8 状态/记忆写入、不能使 GA Loop 自动 FINISH 成真实业务成功 |
| GA-01B 测试 Sandbox | 固定 MockAction/MockExecution + `SandboxObservation`；只可给独立测试 `ContinuationPolicy` 作为事实 | 不能对外生成真实 `ValidatedResult`、`RuntimeResponse`、`UpdateResult`；不能获得真实 Tool/网络/DB/通知凭据 |

### 3.2 唯一装配设计

- `agent_core/` 提供与权限无关的 `AgentRunCoordinator`、`LoopBudget`、`ContinuationPolicy`、只读 `SandboxObservation` 兼容的**内部抽象**；不实现生产 Grant。
- 只有 `tests/ga01/`（或测试包）定义 `SandboxRunComposition`、`SandboxEvidenceVerifier` 和纯内存 `MockExecutionEngine`；**生产代码不 import `tests`**。
- 在正式安装/运行入口中没有加载沙箱实例的注册表、别名、工厂、模式开关；缺少生产 AuthorizedObservationProvider 时一律 fail-closed。不要用 `if is_test`、`LEGACY_TEST_COMPAT`、`DEBUG=true` 作为切换真值授权的依据。
- `MockExecutionEngine` 虽返回既有 `ExecutionResult` 格式以测试 M4→M5 接口，但其结果仅由 `SandboxEvidenceVerifier` 转成 `SandboxObservation`；Mock 不调用 `CoreApprovedToolInvoker.execute_physical_attempt` 或任何真实 Tool Adapter，且没有真实 side-effect 凭据。
- 对 `runtime/orchestration/runtime.py` 和 `m2_runtime.py` 的 Gated 路径**不做代码改动**，继续验证 `M6DownstreamBlocked` 且 M7/M8 函数 0 调用。
- `SandboxRunOutcome` 的状态文本为 `SANDBOX_TASK_COMPLETED`，不可转换成正式 `RuntimeResponse`；即使 Schema 相似，依赖注入仍禁止跨界调用。
- **Import Test**：递归静态检查 `runtime/`、`agent_core/` 不引用 `tests.ga01`、Sandbox factory / verifier，不存在导出 sandbox->production bridge。
- **Dependency Test**：生产 Composition 不提供 Sandbox verifier；在生产工厂内强塞 Mock 类型必须拒绝；无法加载生产验证权威时不得 fallback。
- **Side-effect Test**：测试执行器仅内存 Fixture；所有网络/数据库/通知调用路径为 0；故障和重试不得触发实际 SideEffect。
- **NoGrant Regression**：G1/G2 请求不能因 Agent Loop 外围的存在而取得 response/update/claim rights。

### 3.3 G03 Test

`G03-1` G1/G2 `DENY_ONLY_GATED` 始终拒绝，M7/M8/业务副作用零调用；`G03-2` mock 成功但 NoGrant 强制封锁；`G03-3` production composition 注入 Mock verifier 强制拒绝；`G03-4` import/dependency 没有 sandbox-to-production 路径；`G03-5` Sandbox outcome 不是 `ValidatedResult`、`RuntimeResponse` 或 `UpdateResult`，不能向外发布正向事实；`G03-6` 通过或失败工具均无外部 I/O，Unknown 不视为成功。

## 4. 设计上的交叉冲突检查

| 冲突点 | 裁决 |
|---|---|
| G01 G2 一轮与 G02 多轮事件 | 所有新内部事件仍走同一个 M2 公共 admission；不得因 `source=SYSTEM` 略过 Priority/Preemption |
| G02 历史观察与 G03 Sandbox 事实 | 沙箱历史证据只在测试同一 `RunBinding` 下可投影，不能变成生产事实 |
| G01 Plan gate 与 G03 Mock Executor | `MockExecutionEngine.execute(ApprovedActionPlan,RuntimeContext)` 也必须校验 approved、request/plan/identity + 固定白名单 |
| 任务级 FINISH 与 M6 NoGrant | Sandbox FINISH 只在 test runner 内成立；G1/G2 没有获得 `FINISH = production success` 的能力 |
| 任务级 WAIT 与 M5 Recovery | GA-01 不调度后台恢复，不复用工具失败来触发重新调用 |
| 旧版 `ReplanEntryRequest` 只允许 RESULT_VALIDATE | Sandbox 循环不把模拟观察伪称正式 `RESULT_VALIDATE`，正式 M4 Replan 留待真实验证授权后 |

## 5. 精确结论：设计已收口 vs 代码未验证

| Gate | 设计决策 | 本次结果 | 后续证据归属 |
|---|---|---|---|
| **G01** | M2 唯一共享 admission 逻辑及阻断顺序 | **DESIGN_CLOSED** | GA-01B Slice 0 提取公共 Helper + G2 parity tests |
| **G02** | per-iteration internal request + parent Run Envelope + strict correlation | **DESIGN_CLOSED_CONDITIONAL** | GA-01B Slice 0 internal SYSTEM_EVENT/M3 Context Integration + mismatch tests |
| **G03** | test-only physical isolation + distinct Observation type + production fail-closed | **DESIGN_CLOSED** | GA-01B Slice 0 import/DI/security tests + gated G1/G2 regressions |

**G02 条件说明**：新增 SYSTEM_EVENT 是设计选择，不保证当前 Context/Understanding/Policy 接受；相关真实运行测试若不能通过，必须重新修订输入接线设计，而不是绕过 M2。

```text
PR#91 TARGETED DESIGN REVIEW = DESIGN PASS WITH IMPLEMENTATION PROOFS OPEN
G01 = DESIGN_CLOSED / TEST_NOT_RUN
G02 = DESIGN_CLOSED_CONDITIONAL / INTEGRATION_NOT_RUN
G03 = DESIGN_CLOSED / SECURITY_TEST_NOT_RUN

GA-01B SLICE-0 (TEST AND MINIMAL ADAPTER) = ELIGIBLE FOR DEVELOPMENT
GA-01B FULL LOOP = NOT YET VERIFIED
GA-01B PRODUCTION TOOL / M6 POSITIVE GRANT = NOT AUTHORIZED
MAIN MERGE = NOT AUTOMATIC
```

## 6. GA-01B 的最小下一个交付单元：Slice 0（明确，避免继续建文档）

**唯一交付目标**：一次完整 M2 enhanced admission 与一个内部迭代身份/观察映射在隔离环境中通过真实单测/集成测试；不实现全套 Loop。

- 提取 `runtime/orchestration/m2_admission.py` 的共享组件，让 G2 和 GA Step Adapter 均通过同一 gate。
- 冻结候选 `AgentRunEnvelope/IterationRef`，模拟 `SYSTEM_EVENT` 输入，验证 M3/M4 的 request 对齐、Domain fingerprint 不变。
- 测试包中构造 `SandboxEvidenceVerifier` / mock Executor，并用静态导入、依赖注入、安全拒绝测试证明与生产路径隔离。
- 重跑精确 G2/M6 回归及四项门禁；新增 `agent_core/` 后将 mypy/ruff 扩展覆盖新目录。
- 切片完成才进入 GA-01B 正式 Observe→Decide→Act→Finish 多轮循环。

**本次审查严格不包含代码修改，不把上面提到的测试写成已通过。**

## 7. 审查局限

源码来源为 main 的精确提交 `53cdda379979be836262df1bf6f9382c7ba89897`，审查设计 PR HEAD 为 `9d38375772664e23c37c8bb189606676e001217a`。本次对 M2、contracts、M6 admission、既有 G2/G1 测试进行静态核验；未下载仓库到可运行环境，也未执行测试，没有独立审查者参与。所有“DESIGN_CLOSED”仅指责任、接口、错误优先级和实现位置确定，而非运行证据证明。
