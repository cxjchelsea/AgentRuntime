# GA-01C-EVAL-01｜不泄漏正确答案的真实模型策略评测

## 目标

检验 Qwen2.5 3B 的下一步选择是否由目标、观察与工具语义决定，而不仅仅复现旧版显式 A→B 指令。当前属于隔离的真实模型策略选择评测，**不是**完整多任务 Agent Loop 的可靠性证明。

## 设计

- 六个任务上下文：测量数据缺失、已有数据需要核验、现成报告审计、缺少原始数据，以及两个 A/B 动作语义互换的反偏置用例。
- 提示词只声明两个允许动作的含义、对应策略关系和输出格式，不写“出现某个状态应选择某个动作”或测试期望值。
- 用户目标和经过测试构造的观察通过现有 `StrategyModelRequest` allow-list 投入，模型结果走真实 `HybridStrategySelector` 和合法候选校验。
- 模型权重由 Ollama 免费下载，GitHub Actions 的本机 HTTP 服务运行，无付费密钥。
- 六个用例每个只调用一次模型；逐项记录选择、真实期望和是否通过，并打印 `NO_LEAK_SCORE`。
- 初期验收阈值：至少 5/6，且两个互换语义用例必须全对。失败也记录原始 CI 结果，不改期望答案。
- **重要局限**：动作库仍是两个测试动作，领域 Registry 是固定的，检验的是 M4 结构化模型选择，不涵盖真实生产 Tool、Model-driven Multi-domain Workflow、多轮长期记忆或真实事实核验。
- 模型提示词是任务规划的通用说明，但包含本评测工具的能力定义，不是盲测未知工具。单次 6 例样本不足以证明可靠性；后续至少增加 3 种任务领域、不同措辞与重复采样统计。

## 证据状态

进入真实 CI 后根据精确 HEAD、Run ID、每个 case 的输出与安全门禁填写。当前不预先声称 PASS。

## 真实运行证据（2026-10-10）

- **精确代码 HEAD**：`94bf89f9eef3f3cb5826b39db6c89afc1fdaf111`
- **GitHub Actions Run**：[38017394400](https://github.com/cxjchelsea/AgentRuntime/actions/runs/38017394400)，`Free local Qwen2.5 3B real inference` 与 `targeted` 两个 Jobs 均 **SUCCESS**
- **真实权重加载**：Ollama `qwen2.5:3b`，本地 loopback HTTP Chat Completions；无注入伪造 Sender，无付费 API Key
- **真实 3B 策略推理 6/6 正确**，`NO_LEAK_SCORE=6/6`，用时 25.45 秒
- 原 GA-01C 真实模型基础 Smoke 和原有沙箱 Agent Loop E2E 均 **1 passed**，分别耗时 5.87 秒、5.47 秒
- 常规回归：定向 **110 passed / 1 skipped**；全量 **1198 passed / 3 skipped / 1 warning**；mypy **253 source files**，Ruff lint 和 format 全绿
- 常规 pytest 的 skipped 是未为普通 Job 提供本地模型/云模型的显式 Live 测试；**真实 Qwen3B EVAL 在独立 Job 实际运行并通过，不属于 skipped**。

| 场景 | 选择 | 期望 | 结果 |
|---|---|---|---|
| `missing-sample` | `DOMAIN_ACTION_A`（采集） | A | PASS |
| `measurements-collected` | `DOMAIN_ACTION_B`（核验） | B | PASS |
| `audit-existing-report` | `DOMAIN_ACTION_B`（核验） | B | PASS |
| `data-not-collected` | `DOMAIN_ACTION_A`（采集） | A | PASS |
| `swapped-audit` | `DOMAIN_ACTION_A`（**此时映射为核验**） | A | PASS |
| `swapped-collect` | `DOMAIN_ACTION_B`（**此时映射为采集**） | B | PASS |

**严格结论**：`GA-01C EVAL-01 = SIX_CASE_LIVE_MODEL_SELECTION_PASSED`；`MODEL_AUTONOMOUS_PLANNING_GENERALIZATION = NOT_ESTABLISHED`。

特别说明：
- 模型知道每个 Action 的功能描述及 Strategy/Action 的一一映射，这是正常能力声明；没有给出每道题的标准答案，也没有原沙箱默认 Prompt 中“看到 X 选 B”的条件分支。
- 这是 6 个独立的**单次策略选择**试题，不等于 6 个独立的端到端多步任务；原单场景多轮 Agent Loop E2E 另有证明，不能将两者相加冒充 6 个多步任务。
- 没有任务跨领域泛化、重复采样方差、长上下文/冲突观察、提示注入鲁棒性和真实工具执行证据，仍不授权生产。
- 后续应评审将系统级 `system_instruction` 扩展给外部业务装配是否安全；当前 PR 只为测试提供显式注入，并保持生产默认 Prompt 不变。

## 代码状态

本证据属于堆叠 PR #97（base PR #96 的分支），**未合并 main**；保留主线 main 的 M6 deny-only、M7/M8 禁止 side-effect 边界。应先针对性审查 PR #96 生产 HTTP Adapter / 本地评测依赖安全与 PR #97 模型上下文信任边界，再决定合并。
