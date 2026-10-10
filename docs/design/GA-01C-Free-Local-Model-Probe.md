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
