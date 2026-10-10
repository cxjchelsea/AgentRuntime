# GA-01B Slice 2｜结构化模型驱动策略选择（受控阶段）

> 基线：main `f3db0ebf18a44f173b669bb1829f9899fda3c585`。正式生产工具和 M6 正向 Grant 未启用。

## 范围

- 复用 `StructuredStrategyModel` / `HybridStrategySelector`，新增 `StructuredStrategyTransportAdapter`，由外部注入异步结构化 JSON transport。
- 模型只能见到 `StrategyModelRequest` allow-list（合法策略、合法候选 Action、非敏感理解摘要与受控 `recent_agent_action`），不能直接看到原始 ToolResult 或持有执行权限。
- 在两种不同的沙箱观察投影下，对同一目标测试模型选择不同**合法**策略与 Action；非法输出、模型异常、规则优先于模型均需有负测。
- **重点限制**：本阶段用 Deterministic Fake Transport 测试已有 M4 结构化模型边界；不是外部真实 LLM 已调用，也不是整个 AgentRunCoordinator 的动态 M4→执行完整接线已经完成。它属于 Slice 2 的首个可验证切片，后续仍需整合真正由 Selector 输出的 ActionPlanDraft、批准和第二轮 Mock 执行。
- 当前 Runtime M4 请求的 `PlanningModelContext` 没有原始 Observation 字段。测试通过当前已允许的 `InteractionContext.last_agent_action` 做窄投影验证变化；**只允许测试装配**，不能将任意外部 Tool 文本伪装成 last_agent_action 作为生产做法。后续需要设计经校验的 typed Observation 投影。
- 缺少外部模型密钥和禁副作用运行环境，不能声称 OpenAI/其他 LLM live integration 已验证。

## 验收

CI 需运行 `tests/test_ga01_slice2.py` 及所有已有 G01–G03、Slice 1 的测试和四项门禁。Slice 2 若只完成本阶段，正式状态为 `MODEL_BOUNDARY_ADAPTER_VERIFIED`，不是 `SLICE2_FULL_AGENT_LOOP_COMPLETE`。
