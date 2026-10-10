# GA-01B Slice 2｜Model-Driven Agent Decision Loop — 实施与验证记录

> **合并基线**：main `f3db0ebf18a44f173b669bb1829f9899fda3c585`。  
> **已验证代码 HEAD**：`c43688e35f7e483cf517855b64d86a44692072e8`。  
> **真实 CI**：[GitHub Actions #38014679739](https://github.com/cxjchelsea/AgentRuntime/actions/runs/38014679739)，Python 3.11，SUCCESS。  
> **阶段结论**：`SLICE2_STRUCTURED_MODEL_PROTOCOL_SANDBOX_E2E_VERIFIED`。不是外部真实 LLM 或生产 Agent Ready。

## 1. 实际代码

| 文件 | 产物 | 验证 |
|---|---|---|
| `agent_core/model_adapter.py` | Provider-neutral `StructuredStrategyTransportAdapter`；仅允许 M4 `StrategyModelRequest` 白名单字段进入模型传输，错误 fail closed | 真实 M4 selector 使用该 adapter |
| `tests/test_ga01_slice2.py` | 模型输出合法性、非法策略/Tool、transport 失败、Rule 优先级、观察差异影响选择 | targeted 通过 |
| `tests/test_ga01_slice2_m4.py` | 两种模型选择分别进入**真实** `DefaultM4Planner` → `RuntimePlanValidatorAdapter` → `RuntimePolicyRecheckerAdapter`；不同策略产生不同 Approved ActionPlan.steps | targeted 通过 |
| `tests/test_ga01_slice2_loop.py` | `AgentRunCoordinator` 三轮沙箱 E2E；第一轮 Action A，模拟观察要求核验，第二轮 Action B，第三轮 Finish | targeted 通过 |
| `tests/test_ga01_slice1.py` | 将已经存在的测试沙箱上下文装配扩展为可选的 `model_observation_projection`，原测试行为保持默认不变；使用接口型 Planner/Validator/Rechecker 注入 | 全量回归通过 |
| CI Workflow | 加入 Slice2 的全部测试文件 | GitHub Actions 验证 |

## 2. 真实 E2E 步骤

```text
Original Goal / AgentRun
    |
    v
M1 Input + Context / M3 Understanding / M2 enhanced admission
    |
    v
M4 HybridStrategySelector
    |-- legal strategy/action candidates (registry + policy first)
    |-- StructuredStrategyTransportAdapter
    |-- deterministic fake model chooses STRATEGY_A / ACTION_A
    v
DefaultM4Planner -> PlanValidator -> PolicyRechecker
    |
    v
MockExecutionEngine -> SandboxEvidenceVerifier
    |
    v
Observation: MOCK_FOUND_NEEDS_VERIFICATION
    |
    v
New SYSTEM_EVENT iteration -> Context projection -> re-run M3/M2/M4
    |
    v
Same fake model now chooses STRATEGY_B / ACTION_B
    |
    v
New approved plan -> MockExecutionEngine
    |
    v
SandboxObservation: GOAL_SATISFIED
    |
    v
Third iteration -> deterministic evidence-backed FINISH
```

**正反行为证据**：
- 首次无观察：模型获得策略/Action 白名单并选择 A；第二轮投影来自本 Run 的沙箱观察，模型选择 B；两个动作均经真实 M4 规划与批准；
- 模型虚构策略、工具或试图输出 `grant` 均由 M4 validator 拒绝，不能生成合法批准计划；
- 模型传输错误不降级为绕过 Policy 的工具权限；确定性规则命中时不会调用模型；
- `AgentRunCoordinator` 的已有 identity / budget / plan approval / replay / timeout / cancellation 负测持续全绿；
- 通过测试执行器的 Mock Observation 只形成沙箱证据，不能伪装成 M6 Production ValidatedResult。

## 3. GitHub Actions 真实结果

| 门禁 | 结果 |
|---|---|
| 定向 G01/G02/G03、Slice0/Slice1/Slice2 | **93 passed** |
| 全仓 pytest | **1179 passed, 1 warning** |
| mypy `runtime agent_core tests` | **Success: 245 source files** |
| ruff check | **All checks passed** |
| ruff format --check | **245 files already formatted** |

## 4. 清晰划分：已实现 vs 未实现

**已实现/证明**：既有 M4 **结构化模型协议**通过可注入模型传输接口参与实际多轮 Agent Loop；模型根据经过沙箱投影的 Observation 改变下一步合法 Action，两个不同 Action 实际经历 Plan / Validate / Policy Recheck / Mock Execution / Evidence Verification。

**未实现/不得宣称**：
1. 没有真实公网/本地 LLM provider 的请求与生成测试。当前 Deterministic Fake Transport 是**模型协议和控制流模拟**，不是实际大模型推理能力。真实调用需提供凭据、额度和安全测试环境，并验证 provider 结构化输出、成本/超时/并发；
2. `InteractionContext.last_agent_action` 的观察投影只在 `tests/` 构建，依赖同一沙箱 Run 的可信 Observation。正式生产应新增经验证的 typed Observation Projection Contract，不能接收原始 Tool 文本直接填入；
3. 未实现/授权 M6 B3 Positive Grant、M7/M8 正向下游、真实 Tool/Skill physical execution、Domain Package Loader、K0 实际服务、长期记忆和生产 Composition Root；
4. `AgentRunCoordinator` 的预算当前主要覆盖迭代/执行数量和每阶段超时，不等于完整持久化的生产 Agent 任务管理/恢复；
5. 当前只有一个测试 Domain，没有通过更换第二个 Domain 的 E2E 泛化验收。

## 5. 下一步建议

- 对 PR #95 做一次 focused semantic review：验证 Fake Model 与真实 LLM 的边界、Observation 投影的 provenance、不同模型输出与真实 M4 ApprovedPlan 的一致性、异常 fail-closed，随后以精确 HEAD / CI 合并。
- 下一阶段 GA-01C：接入一个真实结构化 LLM Provider，仍用无副作用沙箱工具，验证不同观察导致的独立模型决策；并设计生产可信 Observation Projection，而不是在 Core 引入第二套 Planner 或 Tool Runtime。
