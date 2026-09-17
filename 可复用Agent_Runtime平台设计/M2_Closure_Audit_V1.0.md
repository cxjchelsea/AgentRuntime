# M2 Closure Audit V1.0

## 1. 审计结论口径

本文件审计的是 **M2 Safety / State / Priority / Preemption / Policy 控制机制是否闭环**。

M2 CLOSED 的定义固定为：

```text
Safety Detection
+ Runtime State Facts / Transition Mechanism
+ Priority Evaluation
+ Preemption Decision
+ Policy Aggregation
+ Runtime Control Gate
+ Planner Output Policy Re-check
+ fail-closed boundaries
```

M2 CLOSED **不等于**：

```text
真实 task cancel 已实现
真实 checkpoint / resume 已实现
EventQueue 已实现
RuntimeState 已自动切换 INTERRUPTED
forced SafetyWorkflow 已真实执行
Domain priority mapping 已提供
业务闭环已完成
Production Ready
```

上述内容没有冻结执行 Contract，当前必须保持 `DEFERRED_BY_ARCHITECTURE`，不得发明假实现。

---

## 2. M2 单元状态

| 单元 | 内容 | Closure 输入状态 |
|---|---|---|
| M2-IU1 | Safety Guard | PASSED |
| M2-IU2 | Runtime State / Transition Engine | PASSED |
| M2-IU3 | Priority / Preemption Engine | PASSED |
| M2-IU4 | Policy Engine | PASSED |
| M2-IU5 | RuntimeConstraint Integration | PASSED |
| M2-IU6 | Plan Re-check / Policy Enforcement | PASSED |
| M2-IU7 | Runtime Integration + E2E Gate | PASSED，待 Closure 总门禁确认 |

---

## 3. Closure Invariants

### M2-G01 Safety > ordinary Agent flow

当 Safety / Policy 明确禁止普通流程时，普通 Planner 不得继续。

判定：**PASS by implementation + IU7 E2E**。

### M2-G02 Policy blocked > PROCESS_NOW

`incoming_disposition=PROCESS_NOW` 不是绕过 Policy 的通行证。

判定：**PASS**。

### M2-G03 DEFER / QUEUE / DROP must not enter ordinary Planner

非 `PROCESS_NOW` disposition 必须在 Planner 前终止普通 Agent path。

判定：**PASS by shared control branch**。DEFER 有显式 E2E；QUEUE / DROP 使用同一确定性分支。

### M2-G04 Preemption decision != preemption effect

`interrupt=True` 不能被解释为 task 已取消、状态已迁移、checkpoint 已完成或 resume 已安排。

判定：**PASS**。需要真实副作用时以 `PREEMPTION_EFFECT_REQUIRED` fail closed。

### M2-G05 forced workflow required != workflow completed

forced workflow 只产生 alternate-path required 控制信号，不声称 workflow 已执行。

判定：**PASS**。

### M2-G06 Planner cannot self-approve

M5 只能接 `ApprovedActionPlan`；Draft 必须经过 Plan Validation + Policy Re-check。

判定：**PASS**。

### M2-G07 Plan Policy Re-check fail closed

blocked / not allowed / forbidden action-skill-tool / forced requirement violation 不得产生 `ApprovedActionPlan`。

判定：**PASS**。

### M2-G08 Turn continuity

M2 integrated path 必须确保：

```text
RuntimeConstraint.request_id
ActionPlanDraft.request_id @ PLAN
ActionPlanDraft.request_id @ PLAN_VALIDATE
ApprovedActionPlan.request_id @ POLICY_RECHECK
```

均与当前 `RuntimeInput.request_id` 一致。

判定：**PASS**。

### M2-G09 Priority remains Domain-injected

Core 不得根据业务文本、intent、Safety label 或领域名称自行发明 priority kind / numeric priority。

判定：**PASS**。由 `PrioritySubjectResolver` 注入。

### M2-G10 RuntimeState and DomainState remain separated

M2 Core State Engine 只管理 `RuntimeControlState`；Domain workflow state 不进入 Core state definition。

判定：**PASS**。

### M2-G11 RuntimeConstraint remains internal

`RuntimeConstraint` / `PriorityDecision` / `PreemptionDecision` / `StateTransitionDecision` 不得升级为 Canonical Contract。

判定：**PASS**。

### M2-G12 No hidden Priority/Preemption coupling into frozen PolicyEngine

冻结的 `PolicyEngine.evaluate(RuntimeContext, UnderstandingState, SafetyResult)` 不得通过 global cache / singleton / hidden mutable state 偷传 IU3 结果。

判定：**PASS**。

### M2-G13 Core/Domain boundary

M2 Runtime packages 不得硬编码 companion / medical 等真实 Domain intent/action/state/priority values。

判定：**PASS，Closure test 持续扫描**。

### M2-G14 M0 hygiene regression

M2 新增 runtime 实现不得在非 Interface 实现路径重新引入 `NotImplementedError` 等已被 M0 Closure 禁止的卫生回归。

判定：**PASS，Closure test 持续扫描**。

### M2-G15 Deferred effects are not fabricated

IU7 不得直接执行尚未冻结的 cancel/checkpoint/resume/enqueue/state-transition side effects。

判定：**PASS，Closure test 对 integrated runtime 调用面做 AST Gate**。

### M2-G16 Frozen 15-call skeleton remains recognizable

M2 integrated path 不新增 Canonical top-level stage；正常成功路径仍保持原 15 个 call points。

判定：**PASS by IU7 E2E**。

---

## 4. 非阻塞架构债务

### TD-M2-01 双 Runtime `run()` 维护分叉

当前：

```text
RuntimeOrchestrator = M0/M1 frozen regression baseline
M2RuntimeOrchestrator = M2 integrated runtime path
```

`M2RuntimeOrchestrator.run()` 复制了原 15 段 pipeline 并增加 M2 gate，因此存在维护分叉。

裁决：**NON_BLOCKING_TECH_DEBT**。

理由：

1. M0/M1 已 CLOSED，IU7 不应为集成 M2 直接重写其已冻结实现；
2. M2 integrated path 顶层阶段和 Canonical Contract 未产生第二套业务语义；
3. 当前差异是显式“加门”，而不是另建业务链；
4. 在后续 Runtime facade / orchestration convergence 阶段应消除复制，但不应为消除代码重复而重开 M0/M1。

后续要求：任何修改基础 15-stage pipeline 时，必须同时验证 M0 baseline 与 M2 integrated path，直到完成统一 facade/convergence。

### TD-M2-02 concurrent initialize idempotence

IU2 已知：并发双 initialize 在 absent scope 下，loser 可能收到 `StateRevisionConflictError`。

裁决：**NON_BLOCKING_TECH_DEBT**。安全性不受损，不会 silent overwrite；后续并发治理阶段处理。

### TD-M2-03 opaque plan dictionaries

`tool_plan` / `capability_plan` / `state_intent` 等仍是 `dict[str, Any]`，IU6 不进行猜测式 Policy 校验。

裁决：**DEFERRED_BY_ARCHITECTURE**。M4 正式实现前应冻结相应子 Schema。

---

## 5. 明确 Deferred，而非 M2 Blocker

以下能力均不得作为“M2 已实现”对外宣称，但不阻塞 M2 控制机制 Closure：

| Deferred Capability | 原因 | 后续归属 |
|---|---|---|
| real task cancellation | 无冻结 effect contract | M5 / orchestration effects |
| checkpoint / resume executor | 无冻结 effect contract | M5 / runtime execution |
| persistent EventQueue | 尚无 Queue contract | execution / scheduler infra |
| auto transition to INTERRUPTED | target/event mapping 尚未冻结 | state + orchestration integration |
| forced SafetyWorkflow execution | Workflow 执行属于 capability/execution | M4/M5 |
| concrete Domain priority mapping | 属于 Domain Package | Domain Extension / M9 |
| semantic validation of opaque plan dicts | 子 Schema 未冻结 | M4 design/implementation |

---

## 6. Closure Gate

只有同时满足以下条件才能正式宣布：

```text
M2 = CLOSED
NEXT_ALLOWED = M3 Understanding Implementation
```

条件：

1. `tests/test_m2_closure.py` 全部通过；
2. 全量 pytest 通过；
3. mypy 通过；
4. ruff check 通过；
5. ruff format --check 通过；
6. M0 / M1 Closure 回归保持绿色；
7. Closure 审查未发现新的 scope violation / fabricated effect / Domain hardcode。

在上述门禁完成前：

```text
M2 = READY_FOR_CLOSURE_REVIEW
```

而不是 CLOSED。
