# General Agent System（通用 Agent 系统）

> **项目定位**：构建一套可运行、可扩展、可通过切换 Domain Package 服务不同业务的通用 Agent 系统。仓库名 AgentRuntime 是历史名称；**最终产品不只是 Runtime**。

## 从这里开始

建议按顺序读这四份文件（它们是当前维护的产品/工程导航，不替代源码与冻结契约）：

1. [系统总体架构](docs/01-总体架构.md)：最终产品、边界、一次任务如何运行。
2. [现有代码与架构映射](docs/02-代码资产映射.md)：代码在哪、可复用什么、缺什么。
3. [当前进度与阻塞](docs/03-开发现状.md)：已经完成什么、尚未证明什么。
4. [开发路线和验收](docs/04-开发路线.md)：下一步做什么、做到什么程度算完成。

[文档体系和历史证据说明](docs/README.md)

## 用一句话理解架构

```text
Application（产品入口、会话、Domain 选择）
         │
Domain Package（Prompt / 知识 / Tool / Workflow / 规则 / 状态策略）
         │
General Agent Core（Goal → Decide → Act → Observe → Replan / Finish）
         │
Agent Runtime（现有 M0–M6：权限、安全、执行、恢复、Trace 等）
```

这是**目标架构**，不是声称四层都已实现。现有 M3/M4 包含实际理解/策略选择实现，M5 包含较完整执行实现；Loop 与可执行 Domain Package 尚未通过跨领域 E2E 验证。

## 目前到底能做什么？

- 已实现并具备历史测试证据：固定主链 Orchestrator、M3 Understanding Engine、M4 Planner/合法候选策略、M5 Execution 相关能力、M6 有限 Deny-Only 保护。
- **未证明**：可反复观察-决策-行动的真实 Agent Loop；装载并切换两个可执行 Domain Package；完整真实模型+真实工具的生产任务闭环。
- **不能混淆**：模块 Closure ≠ 完整 Agent 可用；测试用无副作用 Mock ≠ 真实正向授权；接口/Manifest 存在 ≠ 动态加载实现。

## 下一步（唯一近期开发焦点）

**GA-01：最小通用 Agent Loop**。先以隔离、无外部副作用环境证明：模型决策 → 合法工具 → Observation → 再决策 → Finish。严格保留 M2/M4/M5/M6 授权边界；不得为了 Demo 绕过 Deny-Only。真实副作用执行必须经过独立正向授权设计。

## 代码及验证

- 核心实现在 `runtime/`，测试在 `tests/`。
- Python 配置在 [pyproject.toml](pyproject.toml)。
- 本次文档整理只基于基线 `01347c62083cdb30b8a149d37bb979b373ded9d3` 的源码审阅及历史证据；**没有重新运行测试**。以当前分支的 CI/本地实际输出为准。
- 旧 M0–M9 设计与 CA/IU/Closure 文档保留在 [历史设计资料](可复用Agent_Runtime平台设计/)，只供契约与审计追溯；请不要将旧实施顺序视为当前开发路线。

## 变更原则

1. 优先复用 M3/M4/M5，不重做第二套 Planner、Executor 或 State Store。
2. Core 不硬编码医疗、教育等领域枚举；领域差异由版本固定的 Domain Package 承载。
3. 安全、权限与外部副作用一律 fail-closed。
4. 每个交付单元有可运行测试，重要变更绑定精确 commit 和证据。
5. 生产代码与冻结契约的修改必须单独评审；本次仅整理文档。
