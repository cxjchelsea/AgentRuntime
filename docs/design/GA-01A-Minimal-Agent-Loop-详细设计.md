# GA-01A｜Minimal General Agent Loop 详细设计 V0.1

> **类别**：实施前的设计文件，非代码实现，不替代冻结 Canonical Contract。  
> **唯一代码基线**：main `53cdda379979be836262df1bf6f9382c7ba89897`（PR #90 合并后）。  
> **状态**：TARGETED_DESIGN_COMPLETE / IMPLEMENTATION_READINESS=CONDITIONAL（待针对性审查与测试落地）。  
> **目标**：为 GA-01B 提供能够直接编码、不会重写 M3/M4/M5、不会绕过 M6 NoGrant 的接线和最小接口设计。
> 关联：[总体架构 V2.1](../01-总体架构.md)、[总体实施方案 V1.0](../05-总体实施方案.md)、[当前开发状态](../03-开发现状.md)。

## 1. 设计前的源码事实与边界

| 文件/实体 | 实际签名与行为 | 对 GA-01A 的后果 |
|---|---|---|
| `runtime/orchestration/runtime.py::RuntimeOrchestrator.run(input)` | `LEGACY_TEST_COMPAT` 调 `_run_pipeline`；G1 NoGrant 调 gated pipeline；单轮走到 Response 和 UPDATE | **不得**通过在 Agent Loop 中重复 `run()` 实现内部循环；会产生过早回复/提交；LEGACY 不能授予生产正向验证 |
| `runtime/orchestration/m2_runtime.py::M2RuntimeOrchestrator.run(input)` | 自己实现完整 M2 POLICY/PLAN/EXECUTE/VALIDATE/RESPONSE/UPDATE；额外 `RuntimeConstraintEvaluator` 与 `PrioritySubjectResolver`；拒绝/需中断明确拦截 | **必须**复用其增强的 M2 admission 语义，不可仅调用简单 `PolicyEngine.evaluate` 来假装等价 |
| `runtime/interfaces/input.py::InputProcessor.process(RuntimeInput)` | 返回 `RuntimeInput` | 第一次正规入口处理输入，迭代不可将工具文本伪装成用户消息 |
| `runtime/interfaces/safety.py` | `evaluate_early(input)`、`evaluate_deep(input, context, understanding, early)` | 每次有新的计划/授权前确保最新合法 Safety/Policy；新增 Observation 不可跳过必要安全检查 |
| `runtime/interfaces/understanding.py` | `understand(input, context)->UnderstandingState` | 调用既有 M3；工具输出只作为经过验证的 Context/Observation 投影 |
| `runtime/planning/runtime_integration.py` | `DefaultM4Planner.plan(context, understanding, policy)->ActionPlanDraft` | 主规划实现，不造平行 Planner |
| `runtime/interfaces/planning.py` | `PlanValidator.validate(draft)->ActionPlanDraft`、`PolicyRechecker.recheck(draft,policy)->ApprovedActionPlan` | 准入通道不可跳过；批准必须使用对应本轮 PolicyDecision |
| `runtime/interfaces/execution.py` | `ExecutionEngine.execute(approved,context)->ExecutionResult` | 工具/技能执行仍由 Runtime；GA 层不直接绑定 ToolImplementation |
| `runtime/interfaces/validation.py` | `ResultValidator.validate(execution,context,approved)->ValidatedResult` | **此接口的存在不等于 M6 正向授权可用** |
| `runtime/validation/no_grant_downstream_policy.py` | NoGrant `BLOCK_BEFORE_M7_M8`，禁止响应、状态提交及正向 claims | 任何 G1/G2 gated 路径都不得偷渡 validated success 或继续做正向业务响应 |
| `runtime/planning/replan.py::ReplanEntryRequest` | `trigger_stage` 只能为 `RESULT_VALIDATE` | 只能在得到**经授权验证事实**后触发正规 Replan；离线 mock 的循环需保持测试专属类型 |
| `runtime/orchestration/trace.py` | Turn/StageTrace internal-only | 新 Run/Iteration trace 为外层关联索引，不修改 Canonical StageTrace |
| `runtime/contracts/planning.py` | Draft vs Approved 强类型；M4 不允许零 action 默默当 noop | `FINISH/WAIT` 不生成假的空 ActionPlan；交由外层控制策略，经证据校验 |
| `runtime/contracts/execution.py` | `ExecutionResult` 是物理执行观察 | 不能由其直接宣布已完成业务目标 |
| `runtime/contracts/validation.py` | `ValidatedResult` 为结构化验证输出 | 只有**合法验证权威**产出的结果才可进入正式事实链 |

上述是从代码读取后得到的设计事实；此处未声称运行验证。

## 2. 采用的方案与明确否决项

### 2.1 选择：Task-level Coordinator + Reuse Stage Interfaces + Explicit Gate Adapter

```text
Application/CLI [GA test entrypoint]
  |
  v
AgentRunCoordinator (new, GA-01B)
  ├── Fixed DomainBinding (test fixture only for GA-01)
  ├── AgentBudget/RunState (in-memory, internal)
  ├── RuntimeStepAdapter
  │     ├── M1 Input/Context + M2 early Safety
  │     ├── M3 Understanding + M2 deep Safety
  │     ├── M2EnhancedAdmissionAdapter [priority + constraint + policy]
  │     ├── M4 DefaultPlanner + Draft Validate + Policy Recheck
  │     └── M5 Execution [in test: non-side-effect fixed runner]
  ├── ObservationAuthority
  │     ├── Test-only verifier for isolated FakeTool
  │     └── Production path: deny-only until M6 positive grant exists
  └── ContinuationPolicy → CONTINUE / WAIT / FINISH / BLOCK
           └── next iteration reads immutable observation
```

#### 未选择方案 A：反复调用整个 `RuntimeOrchestrator.run()`

原因：调用链没有公开的“Execute + ValidatedObservation 后暂停”能力，直接循环会在每次迭代生成 M7 Response、M8 Update。并且 `M2RuntimeOrchestrator.run()` 与基类有不同强化 admission，不存在直接可重复利用的公共“半程 run”接口。

#### 未选择方案 B：复制新的 Planning/Tool Runtime

原因：将制造第二套 Authority，破坏现有 Version Pinning、Idempotency、Permission、M4 Gate 等不变量。

#### 未选择方案 C：修改现有 G1/G2 NoGrant 模式为可 GRANT

原因：此修改属于尚未获授权的 M6 B3 正向验证设计，不在 GA-01A 范围；既有 NoGrant 合同明确没有此权限。

### 2.2 重要边界：GA-01 的真实“Agent”与测试真实性

GA-01B 能证明：多轮控制器、已有 Planner 的合法动作链、受控 Mock Tool 的事实驱动再次决策、预算与终止策略。**不能证明**：真实外部工具生产执行、M6 正向业务验证、真实长期状态写入。因此输出标签必须是 `SANDBOX_TASK_COMPLETED`（模拟环境目标已满足），绝不使用 `PRODUCTION_BUSINESS_SUCCEEDED`。

## 3. Call Graph 设计（B-01）

### 3.1 RuntimeStepAdapter 的一轮只调用一次

```text
AgentRunCoordinator.run(AgentRunRequest)
  assert sandbox fixture boundary / Domain version pinned
  [FIRST ITERATION]
  processed_input = InputProcessor.process(raw RuntimeInput)
  early = SafetyGuard.evaluate_early(processed_input)
  context = ContextBuilder.build(processed_input, early)
  understanding = UnderstandingEngine.understand(processed_input, context)
  deep = SafetyGuard.evaluate_deep(processed_input,context,understanding,early)
  policy = M2EnhancedAdmissionAdapter.evaluate( ... )  # exact M2 semantics
  enforce allowed / incoming disposition / preemption barriers
  draft = DefaultM4Planner.plan(context,understanding,policy)
  checked_draft = PlanValidator.validate(draft)
  approved = PolicyRechecker.recheck(checked_draft,policy)
  assert identity/request/plan consistency and approved.status == APPROVED
  execution = SandboxExecutionEngine.execute(approved,context) [single call]
  observed = SandboxEvidenceVerifier.verify(execution,approved,context)
  do NOT call Response/Update in intermediate iteration
  continuation = ContinuationPolicy.evaluate(run_state,observed,goal,budget)
  [NEXT ITERATION]
  context = SafeObservationContextProvider.project(immutable observed, original goal ...)
  re-evaluate policy, new understanding/plan as needed
  ... (no tool call unless newly approved)
  [FINISH]
  construct sandbox-only TaskOutcome (not M7/M8 authorized RuntimeResponse)
```

**区别：目标级消息在首次 admission 标准化一次；后续不是伪造新的用户输入**。迭代必须沿用固定的主体、session、identity_scope、domain/版本，并保有 original request 的父关联。M3 `understand` 的接口要求 `RuntimeInput`；GA-01B 必须利用显式 Context 投影保存原用户任务和新观察，而不是把 ToolResult 的文本写成新用户消息。可以为每次内部 evaluation 生成有父子关联的 request ID，**但不能静默修改原请求身份**；M2/M4/M5 的 `request_id`、`plan_id` 校验要保留。最终具体 ID 方案在实现前的接口/fixture 测试中确定。

### 3.2 重新使用 M2 增强 admission，不是复制运行语义

`M2RuntimeOrchestrator._evaluate_integrated_policy(...)` 调用 `PrioritySubjectResolver.resolve` → `RuntimeConstraintEvaluator.evaluate`，随后 `_assert_runtime_constraint_allows_flow` 拦截 `POLICY_BLOCKED`、非 `PROCESS_NOW`、需要 preemption 等情况。

**GA-01B 不得调用这些受保护方法来绕过 class gate，也不得复制一份“简化 POLICY”**。新 `M2EnhancedAdmissionAdapter` 应依赖**现有公开** `PrioritySubjectResolver`、`RuntimeConstraintEvaluator`，将其输出带上 `RuntimeConstraint`，并在 adapter 中调用其稳定可复用的合规判定。该判定若目前只存在于 `M2RuntimeOrchestrator` 内部，GA-01B 需先做最小公共提取（保证 G2 原测试语义不变）、或编写复用精确状态/结果的公用 helper。不得改变优先级、拦截条件或凭空执行 preemption。

`PolicyEngine.evaluate` 的简单路径只适合历史简单 Orchestrator 的对比测试，不能当成生产 M2 增强 admission 的替代品。

### 3.3 Loop 中每轮是否运行 M3？

初版建议每轮重新评估理解/策略，但每轮的模型决策只可由已有合法候选集合产生；Observation 在 context 中作为**带来源的事实**出现。可在 GA-01B 接口设计中实现 `UnderstandingSnapshot` 复用、只对事实变化部分再推理的优化，但不得省掉安全及合法性重验。首次最小任务必须证明**第二次策略选择实际使用第一轮的工具观察**，否则只是硬编码两轮脚本。

### 3.4 Finish 与 WAIT 不生成假 action

M4 `SelectedActionResolver` 明确拒绝 zero-action strategy 隐式 noop。Agent Loop 的 `FINISH`、`WAIT` 属任务控制决策，需由 `ContinuationPolicy` 根据可信证据判定：
- FINISH：SandboxEvidenceVerifier 提供满足目标条件的可信测试事实；模型单独声称成功不够。
- CONTINUE：目标未达成且有新事实/合法可执行下一步。
- WAIT：等待人工或外部事件，**不主动执行另一步**。
- BLOCK：NoGrant / POLICY blocked / unknown side-effect / illegal candidate / budget reached。
- 对不需要 Tool 的正常回答/澄清，留待 GA-01C/GA-04 明确响应授权链，不造空工具计划。

## 4. 内部候选合同（非 Canonical，不改 `runtime/contracts`）

以下均为 `agent_core/` 下的**internal-only 设计类型**，字段可在 GA-01B 细化，不做冻结 Schema 变更：

```python
@dataclass(frozen=True)
class AgentRunRequest:
    runtime_input: RuntimeInput
    domain_binding_id: str
    domain_binding_version: str
    budget: "AgentBudget"
    # ONLY private sandbox composition in GA-01B

@dataclass(frozen=True)
class AgentBudget:
    max_iterations: int
    max_approved_executions: int
    max_total_seconds: float
    max_no_progress: int
    # optional model/token budget in GA-01C

@dataclass(frozen=True)
class IterationEvidence:
    run_id: str
    iteration_id: str
    request_id: str
    plan_id: str
    execution_id: str
    identity_scope: str
    domain_binding_fingerprint: str
    provenance: str  # "SANDBOX_VERIFIED" only in GA-01
    observed_facts: tuple["SafeFact", ...]
    uncertainty_codes: tuple[str, ...]

class ContinueKind(Enum):
    CONTINUE = "CONTINUE"
    WAIT = "WAIT"
    FINISH = "FINISH"
    BLOCK = "BLOCK"

@dataclass(frozen=True)
class AgentRunOutcome:
    run_id: str
    kind: ContinueKind
    # sandbox-specific outcome label, NOT RuntimeResponse
    reason_codes: tuple[str, ...]
    iteration_count: int
    approved_execution_count: int
```

**待审决定**：正式模式未来可能使用 `ValidatedResult`→事实投影，但 `SANDBOX_VERIFIED` 与 `PRODUCTION_VALIDATED` 不能共享可无条件互转的枚举类型。建议使用 Python 不同类型和严格 dependency boundary；不要靠一个布尔 `is_test` 决定权限。

### 4.1 一轮状态机

```text
NEW -> ADMITTED -> DECIDING -> APPROVED -> EXECUTING
    -> OBSERVED -> {DECIDING | WAITING | FINISHED | BLOCKED}
FAILED/BLOCKED/WAITING/FINISHED = terminal in GA-01; no automatic background retries.
```

状态迁移由 Task-level Coordinator 管理；不改变 `RuntimeControlState`，也不拦截 M5 内部 Step 状态机。

### 4.2 Identity/Version/Correlation

一个 Run 固定：`subject_id`、`identity_scope`、`tenant_id`、`session_id`、`domain_id`、`domain_version`、`binding_fingerprint`。每次 Agent Iteration 的 `approved.plan_id` 对应同轮 `execution.plan_id`，`approved.request_id` 对应同轮上下文；跨轮重复结果必须带来源而不能冒充当前轮的物理调用。冻结已执行 Tool/Workflow 的版本，不可随迭代静默换实现。

## 5. B-02：M6 Deny-Only 的严格测试隔离设计

### 5.1 严禁的做法

- 对 `M6NoGrantTurnHandle.validate` 或 `NoGrantDownstreamDecision` 注入 `GRANT`。
- 在 `DENY_ONLY_GATED` 抛 `M6DownstreamBlocked` 后继续调用 `response_planner`、`response_generator`、`state_memory_updater`。
- 将 `LEGACY_TEST_COMPAT` 设为默认生产模式或把其 `ResultValidator` 输出包装成生产授权。
- 把 FakeTool 模拟的 `ExecutionResult` 偷换成用户真实业务已达成的 `ValidatedResult`。
- 用字符串 `"sandbox"` 或环境变量就解除 Tool 副作用检查。

### 5.2 选择：独立 Sandbox Run Composition + Test-Only Evidence

```text
tests/ (或独立的 dev-only example，非生产发布入口)
  ├── DeterministicFakeModel / TestStrategyModel
  ├── ExplicitActionRegistry / FixedDomainBinding
  ├── LocalMockExecutor (NO network/files/DB/business notifications)
  ├── SandboxEvidenceVerifier (local, typed)
  └── SandboxAgentRunDriver
          -> real M3/M4 plan approval contracts
          -> mock M5-shaped ExecutionEngine
          -> strictly local observation; never M6 grant
```

1. **依赖隔离**：`SandboxAgentRunDriver` 只能从 `tests/` 的明确类型装配；GA-01 生产模块不得依赖或导入 sandbox verifier/driver。运行环境不提供实际 Tool credentials、网络/DB Adapter；mock 仅操作内存 fixture。
2. **类型隔离**：`SandboxEvidenceVerifier` 产生 `SandboxObservation`，不是 `ValidatedResult`，不包含 `may_commit`、`grant`、`approved_claims`。生产正式事实适配器接口暂时 `NotAuthorized`，而不是落入 sandbox fallback。
3. **状态隔离**：Sandbox Outcome 不走 M7/M8，不更新真实 Runtime/Domain State 或长期记忆；可写独立内存测试记录。
4. **负向隔离**：原有 G1/G2 NoGrant tests 继续断言不得调用 Response/Update；即使恶意注入 Fake VerifiedResult，Gated Run 也必须被拒绝。
5. **行为隔离**：不提供自动注入真实 `ToolImplementation` 入口；MockExecutor 应检查 `ApprovedActionPlan`、白名单 Action/Tool、scope 和最多次数；未知/缺失事实 fail-closed。
6. **可验证证据**：测试日志记录每个 MockTool 调用、ApprovedPlan、SandboxObservation 来源和两轮策略决策；只能表述 `sandbox task completed`。

### 5.3 后续生产对接的位置

未来只有在 M6 B3 具备合法正向验证授权及应用 Composition Root 完成后，才设计 `AuthorizedObservationAdapter(ValidatedResult)`。其 source 验证必须包含真实 ValidationAuthority、plan/execution/request/scope correlation 及 claim policy；GA-01A **没有授予**这条路径。

**关键裁决**：GA-01B 可通过 Sandbox E2E 证明控制流，但应将“生产 M6 正向适配”明确保持未实现。若有人要求“直接接真实 Tool 并真实回复用户”，当前结果应是 BLOCKED 而不是调用 legacy 分支。

## 6. 真实实现拆分（GA-01B 顺序）

| 编码顺序 | 产物/建议路径 | 职责 | 与现有资产连接 | 最低单测 |
|---|---|---|---|---|
| 1 | `agent_core/contracts.py` | Run/Budget/Iteration/Outcome internal types | 只引用 Canonical，不复制定义 | identity & budget |
| 2 | `agent_core/continuation.py` | 确定性控制策略 | 消费 SandboxObservation | finish/continue/wait/block/no-progress |
| 3 | `agent_core/observation.py` | 明确 provenance、correlation，测试观察接口 | Sandbox verifier 只在 tests 实现 | mismatched identity/plan、unknown |
| 4 | `agent_core/runtime_adapter.py` | 串接 M1–M4–M5 现有接口，公共 M2 admission | Context/Safety/M3/M4/M5 | reject draft、blocked policy、no double call |
| 5 | `agent_core/runner.py` | 多轮任务 Loop 和预算/trace linkage | `runtime_adapter`、`continuation` | 2 rounds、cancel、timeout |
| 6 | `tests/agent_core/` 或 `tests/test_ga01_*.py` | isolated fixtures + E2E | 复用 M4/M5 测试夹具与 fake adapters | 2 rounds + one mock Tool |

建议目录仅为候选，若现有项目包结构要求不同按最低侵入调整。**不要**同时建设新的 `agent_core/planner.py`、`agent_core/tool_executor.py`、`agent_core/state_store.py`。

### 6.1 为什么 GA-01B 不应一次写完所有服务

首先实现两个强制保护的薄 Slice：
- Slice A：固定合法批准链（M4）+ SandboxObservation + 完成终止，不产生真实副作用。
- Slice B：增加第二轮决策；证明不同观察会带来不同策略/动作，且所有新动作重新批准。

Slice A 无效则无需先开发 Prompt/K0/Memory；避免再次“先做完整底座再找用户任务”。

## 7. 测试用例表（GA-01B 的正式设计要求）

| Case | 构造 | 必须断言 |
|---|---|---|
| T01 可执行闭环 | FakeModel 先建议合法查询；MockTool 返回任务事实；策略观察后 Finish | >=2 决策，恰好 1 个执行调用，任务 `SANDBOX_TASK_COMPLETED` |
| T02 观察敏感 | 同目标，不同 MockTool fact | 第二轮策略/继续决定不同；不能按固定轮数硬编码 Finish |
| T03 非法 Action | 模型提议未注册 Tool/Action | M4 Validator/Policy Gate 拒绝；Mock Tool 0 次 |
| T04 policy blocked | M2 Policy denied / forced workflow / wrong disposition | Agent 不进入 M5；不伪造自动 preemption |
| T05 Draft only | 给 M5 未批准的 Draft | 类型/入场拒绝，0 次工具 |
| T06 Scope mismatch | request/session/identity/domain fingerprint 不匹配 | block，不能复制上一轮观察 |
| T07 UNKNOWN/WAITING | 模拟 Tool 结果不确定或仍等待 | 不 Finish，不自动 Retry、不得声明成功 |
| T08 no-progress/budget | 连续相同动作/超过迭代或工具限制 | deterministic BLOCK/WAIT，不能无限循环 |
| T09 double invocation | 注入失败、取消、重入 | 同个已批准任务最多 1 次规定的物理模拟调用，恢复不静默重放 |
| T10 G1/G2 regressions | gated `RuntimeOrchestrator`、`M2RuntimeOrchestrator` | NoGrant 后没有 M7/M8/正向 Claim |
| T11 original Runtime regressions | 现有 `tests/test_runtime_orchestrator.py`、M2/M3/M4/M5/M6 suites | 全部持续通过 |
| T12 trace lifecycle | CancelledError 或日志失败 | 无残留未终结的 iteration；StageTrace 已知风险单列，不谎称已修 |
| T13 production path unavailable | 不提供 B3 权威/生产 adapter | 必须拒绝真实 Tool/Response/Memory 写入 |
| T14 Domain swapped mid-run | 改 binding 版本/权限/ToolRef | 立即 block、无新执行 |

### 7.1 可运行命令和 Gate

计划 GA-01B 完成后在一致 HEAD 执行：

```bash
python -m pytest tests -q
python -m mypy runtime tests
python -m ruff check runtime tests
python -m ruff format --check runtime tests
```

**注意**：新增 `agent_core/` 后，门禁必须升级为 `python -m mypy runtime agent_core tests`、`ruff check/format --check runtime agent_core tests`，否则新代码未被类型与格式检查覆盖。需要同步调整 CI 入口/项目配置；不允许只报告老目录通过。

## 8. 未冻结的五项设计细节与严格入口

| ID | 未冻结项 | 推荐决定 | 实现前必须提交的证据 |
|---|---|---|---|
| A-01 | M2 增强 admission 的可复用公共入口 | 最小提取公共 helper，优先维持 G2 行为 | before/after G2 negative fixtures 一致 |
| A-02 | Iteration request/turn ID 映射 | parent `run_id` + per-iteration IDs，保留 `RuntimeInput` 身份 | approved/execution/request/trace correlation tests |
| A-03 | SandboxObservation 与 Product Observation 的边界 | 独立类型 + 硬依赖禁止 | imports/static test；NoGrant regressions |
| A-04 | Continue FINISH 的任务真值 | 领域可配置且由 fixture 验证的 completion predicate | 相同轮数不同事实不 Finish |
| A-05 | M5 实体 Executor 的替换点 | GA-01 测试专用 `ExecutionEngine`，GA-04 再接真实 M5 | Mock 只能按 `ApprovedActionPlan`，无其他 Tool 直调 |

A-01/A-02 涉及精确实现适配，当前文档给出原则和建议但**尚未经过运行性独立验证**。GA-01B 不应在未验证 request/identity correlation 或重构 G2 流程回归之前宣称 READY。

## 9. GA-01A 决策与验收说明

**已解决到设计级别**：
- B-01：选择明确的共享 Stage Interface + Task-Level Controller 架构；确定不循环原 `run()`。
- B-02：选择独立 Sandbox Test-only 实现，生产 Grant 保持未授权；不修改 NoGrant。

**仍需作为 GA-01B 开工条件**：
- A-01/A-02 最小实现级边界设计在 targeted review 后确认。
- T01/T02/T04/T06/T10/T13 的 fixture 必须能模拟并证明既有 G2/M6 真实拒绝。
- 不新增 Canonical Contract 改动、第二套 M5 Tool invoker、Production Positive Grant。

最终状态：

```text
GA-01A DETAILED DESIGN = DRAFT COMPLETE
GA-01A SOURCE CONSISTENCY = TARGETED REVIEW PERFORMED
GA-01A INDEPENDENT DESIGN REVIEW = NOT PERFORMED
GA-01B IMPLEMENTATION = CONDITIONAL / NOT YET AUTHORIZED
M6 POSITIVE GRANT = NOT AUTHORIZED
PR#90 MASTER ARCHITECTURE = MERGED INTO MAIN
```

此文件只能由单独 PR 合并后成为设计依据；GA-01B 编码仍需目标门槛核对，不需要为普通小修改增加新审查循环。
