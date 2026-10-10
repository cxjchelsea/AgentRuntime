# GA-01C 免费真实模型试验：Ollama + Qwen2.5 0.5B

这是无需购买 API Key 的免费真实推理验证方案：公开仓库的 GitHub Actions runner 运行 Ollama 容器、下载 `qwen2.5:0.5b`（约 398 MB）模型，调用 `http://127.0.0.1:11434/v1/chat/completions`。

- 模型：Ollama `qwen2.5:0.5b`，开源模型权重、本机 CPU 推理，而非 Fake Model。参考官方 Ollama <https://ollama.com/library/qwen2.5> 和 <https://github.com/ollama/ollama/blob/main/docs/api/openai-compatibility.mdx>。
- 不需要 API Key，不请求付费 DeepSeek 云模型。GitHub 托管 runner 的时间与流量受平台政策及配额限制；项目当前为 public repository。
- 执行位置：PR #96 上的 `free-local-model` 工作流；只在本 PR 分支变更时运行。下载和容器产生可观耗时，但没有模型 API 费用。
- 第一门：模型权重真实生成 JSON，并经 M4 结构化策略验证。
- 第二门：现有 `test_live_provider_drives_two_approved_mock_actions` 真实执行两轮模型选择、M4 校验/审批、沙箱工具和完成判断。
- 若第二门失败，要保留原因（不合法 JSON、Action 与上下文不一致、M4 审批未过、超时等）；不能将 Fake Sender 的通过结果伪称本门通过。
- **测试通过**也只证明在已知 A→B 的特定 sandbox prompt 下，一个小模型可以选合法动作；不等于通用 Agent 自主规划或生产可用。

Windows 上也可以使用 `ollama pull qwen2.5:0.5b`，设置 `GA01C_LLM_URL=http://127.0.0.1:11434/v1/chat/completions`、`GA01C_LLM_MODEL=qwen2.5:0.5b`、`GA01C_LIVE_OPT_IN=1` 运行单测；本地不需要 Key。

## 真实运行结果：第一轮 Qwen2.5 0.5B

GitHub Actions Run [#38016686123](https://github.com/cxjchelsea/AgentRuntime/actions/runs/38016686123)：Ollama 真实加载 0.5B，`Actual Qwen2.5 inference smoke` **PASS**，证明本地权重推理、结构化 JSON、M4 合法性校验真实运行；但 `Real model inside bounded Agent Loop` **FAIL**。实测第一轮选 A、第二轮仍选 A，产生相同观察 `MOCK_FOUND_NEEDS_VERIFICATION`，Coordinator 正确返回 `NO_PROGRESS` / `BLOCK`，没有假冒 FINISH。这属于模型动态决策能力不足，非安全放行失败。

下一轮尝试同样免费的 Qwen2.5 **1.5B**（约 986 MB），相同任务、相同 M4 合法性/审批及 Loop，严格保留模型失败证据。不将真实运行失败修改成伪造 PASS。

## 第二轮：Qwen2.5 1.5B

CI [#38016807140](https://github.com/cxjchelsea/AgentRuntime/actions/runs/38016807140)：真实 1.5B 权重下载/CPU 推理成功，结构化 JSON/M4 单轮测试通过，**完整多轮 E2E 仍失败**。同一 Run 中第二轮重复 Action A，两个 Observation 都是 `MOCK_FOUND_NEEDS_VERIFICATION`，AgentRunCoordinator 正确 `BLOCK / NO_PROGRESS`。没有授权放宽或假成功。第三轮上限试验选择 Qwen2.5 3B（约 1.9 GB），同任务、同安全规则；不再无限扩大模型规格。

## 第三轮：Qwen2.5 3B — 真实模型 E2E 成功

GitHub Actions [#38016938372](https://github.com/cxjchelsea/AgentRuntime/actions/runs/38016938372)，精确代码 HEAD `4098ab6c01f7dc5ea50bf2b869d780655fa11491`：

- `Actual Qwen2.5 inference smoke`：**1 passed，10.68s**，权重真实推理 + JSON + M4 合法性链；
- `Real model inside bounded Agent Loop`：**1 passed，8.84s**，真实 3B 模型参与两轮决策，第一轮 Query/Action A → Mock Observation `MOCK_FOUND_NEEDS_VERIFICATION` → 第二轮选择 Verify/Action B → Mock Evidence `GOAL_SATISFIED` → 第三轮 FINISH；
- 回归 `targeted`：**110 passed, 1 skipped**；全量：**1197 passed, 2 skipped, 1 warning**；mypy **252 files**、Ruff 检查和格式全部通过。
- 注：全量测试中两个 skipped 是 CI 中尚未开启的外部云 LLM 测试和需要本地 Ollama 单独 job 的真实探针；但 Ollama 独立 job 真实执行的两项均 PASSED。不能把 skip 解释成 3B 未执行。
- 该模型没有云模型 API 费用；CI Docker 下载镜像和权重占用免费公共仓库托管计算资源。
- **限度**：该 E2E 的 system prompt 仍显式描述了 A/B 的决策规则，因此证明结构化模型调用和观察驱动的行为条件在这个已知任务上可运行，不足以证明通用 Agent 的自主规划可靠性。
- 结论：`GA-01C FREE_LOCAL_QWEN2_5_3B LIVE_INFERENCE_VERIFIED / SANDBOX_E2E_VERIFIED / CLOUD_DEEPSEEK_NOT_ATTESTED / PRODUCTION_TOOL_NOT_AUTHORIZED`。

对照：

| 免费模型 | 真模型 JSON+M4 单轮 | 真模型多轮 E2E | 失败/成功原因 |
|---|---|---|---|
| Qwen2.5 0.5B | PASSED | FAILED | 第二轮重复 Action A，No Progress 拒绝 |
| Qwen2.5 1.5B | PASSED | FAILED | 第二轮重复 Action A，No Progress 拒绝 |
| Qwen2.5 3B | PASSED | **PASSED** | 第二轮根据观察改选 Action B，Mock 完成证据支持 FINISH |
