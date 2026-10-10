# GA-01C｜DeepSeek Flash Live Provider 验证方案与实际状态

## 1. 选型（2026-10-10）

- Provider：DeepSeek API
- Model：`deepseek-flash`（当前官方 DeepSeek V4.1 Flash API 名称）
- Endpoint：`https://api.deepseek.com/chat/completions`
- JSON：`response_format={"type":"json_object"}`，模型 system prompt 明确要求 JSON；后端 M4 对策略与动作独立验证、校验并批准
- 真实工具：禁止；只有 tests 中 Mock ExecutionEngine
- 来源：<https://api-docs.deepseek.com/zh-cn/>、<https://api-docs.deepseek.com/zh-cn/guides/json_mode/>。

本轮只使用 provider-specific 的假响应单测证明 HTTP 请求形状兼容，不把它算成真实推理。

## 2. 单独 Live Verification 配置

GitHub 仓库 Settings → Secrets and variables → Actions：

- **Secret**：`GA01C_LLM_API_KEY`（真实 DeepSeek API key，绝对不要提交代码或贴到聊天中）
- **Variable**：`GA01C_LIVE_OPT_IN`，值为 `1`，明确允许 CI 发起付费调用
- **可选 Variables**：`GA01C_LLM_URL`、`GA01C_LLM_MODEL`。如果不填写，CI 中明确回退到上方确定的 DeepSeek endpoint 和 `deepseek-flash`。

严格区分验证：

- `LIVE_NOT_ATTESTED`：key 未配置，或 live case skipped。
- `LIVE_FAILED`：确实发起请求但 401/403/404、模型输出不合法、超时、模型错误、完成失败；需逐项定位，不可自动重试或放宽 M4 权限。
- `LIVE_VERIFIED`：精确 HEAD 的 CI 中该用例**实际执行（非 skipped）并通过**；同时需要保留运行链接和实际模型名称。

设置完成后，可以在 GitHub Actions 的 *Agent Runtime Test Gates* 工作流选择当前 PR 分支并点击 Run workflow；或在同一分支产生明确的测试提交重新触发 PR CI。启用 LIVE 后，CI 后续运行可能发生费用；验证完成应将 opt-in Variable 关闭或改为 `0`。

## 3. 环境限制

当前连接没有写入 GitHub Actions Secrets/Variables 或 dispatch 工作流的授权操作；不能代替用户创建 API key，也不会通过硬编码密钥绕过限制。未获得 Live 成功日志前，GA-01C 的验收只能写为 `HTTP_ADAPTER_AND_LOOPBACK_E2E_VERIFIED / LIVE_NOT_ATTESTED`。

## 4. 关于“真实 Agent 动态决策”的证据边界

当前 Sandbox system prompt 显式指导条件分支 A→B；因此即便实际模型调用成功，也只能说明真实模型能够遵循受限提示词，选择两个合法动作并完成 Mock E2E，**不能宣称对未知任务具有通用 Agent 自主规划能力**。下一阶段必须使用不泄漏期望答案的任务集、不同领域任务与动作选择 Eval。
