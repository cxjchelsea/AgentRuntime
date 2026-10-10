# GA-01C｜Real Model Adapter + Live Sandbox E2E

> 基线 main：`661b95d2ba06d0db7e7c39ebe635efe901d770b3`。GA-01C 是真实 Provider 调用**能力实现**与**独立的 Live 运行证明**两件事；不能把 CI 中无网络的 Fake HTTP 测试当成真实模型成功。

## 交付范围

1. `agent_core/chat_transport.py`：兼容标准 Chat Completions 的 HTTPS JSON transport。模型和 endpoint 由明确配置提供；不在代码中保存凭据；远程仅允许 HTTPS，loopback 支持 HTTP 以兼容本地大模型。
2. 延续 `StructuredStrategyTransportAdapter` 与 M4 的 `HybridStrategySelector / DefaultM4Planner / PlanValidator / PolicyRechecker`，模型只可返回已注册、已筛选的 Strategy/Action；无自主 Tool 权威。
3. `tests/ga01/projector.py`：**仅沙箱** typed Observation 白名单映射，校验 Run / Domain binding / Plan / Execution ID 和注册事实；不得将任意 Tool 文本等同验证事实。当前只是沙箱 provenance，不等价生产 M6 Truth Boundary。
4. `tests/test_ga01c_transport.py`：注入假 HTTPS sender 测试真实 HTTP 请求体形状、响应解析、非法模型输出、网络异常、URL/凭据约束（**不会请求外网**）。
5. `tests/test_ga01c_live.py`：同一 `AgentRunCoordinator` / 真实 M4 Planner 测试装配，将 Fake Strategy Model 替换为真实模型 HTTP Transport；受控事实经 projector 投入下一轮 Context，工具仍为纯内存 Mock。

## 真实模型的运行条件

只对明确愿意消耗模型 API 额度的环境启用：

```bash
export GA01C_LIVE_OPT_IN=1
export GA01C_LLM_URL="https://YOUR_PROVIDER/v1/chat/completions"
export GA01C_LLM_MODEL="YOUR_MODEL"
export GA01C_LLM_API_KEY="YOUR_SECRET"
python -m pytest tests/test_ga01c_live.py -q -rs
```

不要在 issue、日志、聊天或仓库提交中粘贴真实密钥；Windows PowerShell 使用 `$env:GA01C_LLM_API_KEY = ...` 等环境变量。此类 endpoint 必须由用户在可信模型服务中自行确认。GitHub Actions 可通过 Secret `GA01C_LLM_API_KEY` 和 Variables `GA01C_LLM_URL`、`GA01C_LLM_MODEL` 配置；没配时 live case 显式 skip，**不是 PASS**。

## 安全边界

- HTTP 返回内容按不可信 JSON 处理，`StrategyModelOutputValidator` 才判定合法 Strategy 和候选 Action；请求中仅传 M4 allow-list，不包含原始隐私 Context、Token 或 ToolResult。
- 网络失败、timeout、非结构化 JSON 均 fail-closed；无自动重试/无生产外部 Tool；模型调用本身属于网络交互，不是零网络 IO。
- 模型的 completion 并非真实业务完成权威；`FINISH` 仍须 Mock Evidence 与受控任务目标匹配，不能直接用模型的“done”作为事实。
- 沙箱 Projector 位于 `tests/`，并不意味着生产可信 Observation Projection 已实现。生产环境仍缺 M6 B3 正向验证、真实身份域隔离、完整权限及审计绑定。
- 本版的 system prompt 为沙箱的 A→B 演示限定。它不是未来任意 Domain 的通用 Agent Prompt；上线前需版本化 Prompt、领域结构化约束以及 Prompt Injection 测试。

## 验收标准（分级，不混淆）

- **A：Adapter + Contract VERIFIED**：假 HTTP sender 的解析/错误/安全测试和全部原有 pytest/mypy/ruff 通过。
- **B：Live Provider VERIFIED**：单独的 `test_live_provider_drives_two_approved_mock_actions` 在可信模型凭据下真实发起两次模型推理并运行成功；需贴精确 HEAD、模型名称（非密钥）、CI/本地证据、费用和成功/失败统计。未运行时写 `LIVE_NOT_ATTESTED`。
- **C：Production Agent READY**：还需要 M6 Positive Grant、正式 Observation Truth Projection、Tool 权限、Domain Package 等，不属于 GA-01C。

正式代码审查后如仅 A 通过，可以合并可选 Provider 适配器，但不能把 GA-01C 宣称已经实现了真实 LLM E2E 验证。
