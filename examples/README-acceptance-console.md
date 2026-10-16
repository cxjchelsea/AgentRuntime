# 本地人工验收 Web 控制台（GA-21 复用）

此控制台是 **Linux / WSL2 本机实验性入口**，不是生产级服务，也不是医疗业务系统。服务仅绑定 `127.0.0.1`，浏览器只访问同一设备，HTTP API 需要从页面生成的临时 token。仅使用合成业务数据和只读工具。不应提交、输入任何真实患者或敏感个人数据。

## 环境

Ubuntu/WSL2、Python 3.11+、可访问的 OpenAI-compatible 模型服务（默认 Ollama `qwen2.5:3b`）。`GA01C_LLM_URL`、`GA01C_LLM_MODEL`、`GA01C_LLM_API_KEY` 由服务器环境读取，不下发到浏览器。

```bash
cd /path/to/AgentRuntime
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
python -m tests.ga20_fixture_prepare --output-dir /tmp/ga20-business-fixtures
python -m examples.acceptance_console \
  --inventory-config /tmp/ga20-business-fixtures/inventory.json \
  --learning-config /tmp/ga20-business-fixtures/learning.json
```

在同机浏览器打开 `http://127.0.0.1:8765/`。WSL2 终端执行时 Windows 浏览器通常也可以访问，取决于 WSL 网络配置。模型需在启动前运行并能从 Ubuntu 访问，例如 `curl http://127.0.0.1:11434/api/tags`。

建议手动依次验证：
1. 库存领域发送“请查询库存”，观察真实结果及工具执行数量。
2. “刚才结果”应复用已有证据且不执行工具；“再查一次”应重新查询。
3. 切到学习领域发送“请查询学习进度”，验证不同 Domain Package 和工具结果。
4. 回到库存领域验证界面会话隔离，点击重置只清除当前领域会话；“取消”后需重置方可继续。
5. 医疗领域不展示可用入口：真实慢病、心理健康、疾病预测业务包尚未整合到 GA-21 应用；已有医疗测试只是合成安全/知识/规则的自动化验证，不可声称临床决策能力。

此入口只暴露 GA-21 已验证的 `kind`、`tool_executions`、`revalidated_steps`、`reused_evidence` 元数据，不将其称为完整执行 Trace。它不实现权限管理、身份登录、持久记忆、医疗授权、公开网络部署或生产 Host 保障。可运行领域始终是 `inventory` 和 `learning`；更换领域不代表动态加载了医疗领域。不要以此替代 PR #148 的生产级 Host 隔离后续整改。
