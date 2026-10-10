# GA-01B Slice 1｜Minimal Agent Loop 实现与 CI 验证

> **对应代码精确 HEAD**：`b17b472aba62cc3a267e407cf2fa71587d55efca`（PR #93，基于 PR #92 分支）。  
> **运行证据**：[GitHub Actions Run #38012708696](https://github.com/cxjchelsea/AgentRuntime/actions/runs/38012708696)，Python 3.11，SUCCESS。  
> **状态**：`SLICE1_SANDBOX_E2E_VERIFIED`；不是完整通用 Agent 或生产环境验证。

## 本次代码

- `agent_core/runner.py`：新增 `AgentRunCoordinator`、`LoopBudget`、`Decision`、`ObservedFact`、`RunOutcome`。限制每个任务的迭代轮数、执行次数和无进展重复，关联 `run_id/request_id/plan_id/domain_fingerprint`；返回 `FINISH/WAIT/BLOCK`，不触碰 M7/M8。
- `tests/test_ga01_slice1.py`：在独立的 `SandboxTurn` 中装配真实 `DefaultInputProcessor`、`DefaultContextBuilder`、SafetyGuard、G01 共享 M2 Admission、既有 UnderstandingEngine/Planner 接口、PlanValidator、真实 PolicyRechecker 与 MockExecutionEngine。
- `tests/ga01/sandbox.py`：给 Mock Evidence Verifier 增加测试受控的观察事实输入，继续做 M6 结构关联校验，且仅输出 `SandboxObservation`，不产生 `ValidatedResult` 或任何真实正向执行授权。

## 实际运行验证

| 证据 | CI 结果 |
|---|---|
| 定向 M2/G1/G2/GA01 Slice 0 + Slice 1 | **80 passed** |
| 全仓 `python -m pytest tests -q` | **1166 passed, 1 warning** |
| `python -m mypy runtime agent_core tests` | **Success，241 files** |
| `python -m ruff check runtime agent_core tests` | **All checks passed** |
| `python -m ruff format --check runtime agent_core tests` | **241 files already formatted** |

### E2E 证明

1. 同一任务下第一次决策生成 Draft，经过 Validator、PolicyRechecker 批准，再进入无副作用 Mock Executor；返回模拟观察。
2. 第二轮处理 `SYSTEM_EVENT`，将上一轮观察作为 ToolContext 数据输入并再次运行理解与 M2 Policy；仅在经 Mock 验证的事实包含 `GOAL_SATISFIED` 时 FINISH。
3. 相同原始任务、不同观察（未满足目标）不 Finish；进入下一轮已批准计划执行，最终受迭代/进展限制阻断。
4. 执行预算耗尽后不执行第二次 Mock；身份错配在首次工具调用前被拒绝。

## 边界和未覆盖点

- Agent Loop 控制已实现，但**真实模型驱动的多轮策略选择尚未接入**：测试中的 M3/M4 组件是符合现有接口的 deterministic fixture，完成谓词也是测试确定性的判断器。
- Mock Tool 是内存测试，`SandboxObservation` 只是经测试夹具验证的观察；不能成为生产 M6 `ValidatedResult` 或正向业务声明。
- 还未接入 Domain Package Loader、真实 K0/RAG、长期 Memory、M5 完整生产执行/恢复、生产 Composition Root、M6 B3 正向授权。
- 当前测试的 Finish 必须引用本任务已有观察事实；后续需要提高对误完成、串轮、未知状态、并发/取消、时间预算及用户等待的负向覆盖。
- **PR #91/#92/#93 都未合并 main**；顺序为先设计 #91，再 Slice0 #92，最后 Slice1 #93。不能以堆叠 PR 的通过替代 merge-target 精确差异/CI 验证。

## 后续工作

建议先对 Slice 1 做针对性代码 Review（是否重复 Runtime Authority、Loop Completion 是否可信、预算和异常是否 fail-closed），然后严格按顺序合并 PR #91 → #92 → #93，并在最终 main 复验；再开始 Slice 2（可配置完成谓词、动态策略选择与真实 Model Adapter 的隔离 E2E），不急于扩展生产 Runtime。
