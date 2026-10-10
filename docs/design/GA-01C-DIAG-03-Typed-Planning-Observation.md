# GA-01C DIAG-03｜Typed Planning Observation Contract

## 目标与实施选择

DIAG-01 中将 JSON 直接塞入 `InteractionContext.last_agent_action` 导致真实 Qwen3B 结构化输出失败；DIAG-02 已验证初始状态经过可信准入可使完整任务正确动作序列达到 18/18。本单元新增**可选的 M4 只读模型规划上下文** `PlanningObservationContext`，不改变 M2 权限、M4 的候选集合/PolicyRecheck、M5 执行、M6 Truth Boundary。

## 契约

`PlanningObservationContext`（`runtime/planning/strategy_selection.py`）包含：
- `schema_version=1`
- `evidence_state`：UNKNOWN / AVAILABLE_UNVERIFIED / UNAVAILABLE / VERIFIED。为 Core 通用证据阶段，不是领域 Intent 或动作枚举。
- `evidence_refs`：已准入初始状态的证据引用及已核验 Mock 执行 ID
- `executed_action_ids`：实际完成观察并校验关联的动作，不包含尚未执行的计划
- `pending_conditions`：仍需满足的领域条件 ID，仅为提示，非执行授权
- `source_scope`：NONE / INITIAL_STATE / EXECUTION / INITIAL_AND_EXECUTION

冻结边界是模型只读投影，不携带真实数据/密钥/Tool 原文和授权。只允许非空、有长度和条数上限的结构化 ID，非法版本和状态拒绝。Core 不硬编码采集、核验或领域名。

## 模型请求最小接线

`StrategyModelRequest` 增加默认 `None` 的 `planning_observation`，`StrategyModelRequestBuilder` 支持注入只读的 projection provider；`StructuredStrategyTransportAdapter` 将该对象作为结构化 JSON 独立字段发送。历史请求默认不受影响。

新测试可设置 `include_legacy_agent_action=False`：模型只看新的 `planning_observation`，不再收到旧 `last_agent_action` 字段。注意为了不扩大本 PR 范围，DIAG-01 的**测试专用 M4 eligibility rule** 暂时还要消费经过 projector 比对的旧 snapshot；这不代表所有内部状态消费都完成 typed 迁移。后续应将规则本身迁移为 typed evidence authority，而不是字符串再解析。

## 信任边界

测试专用投影器从 DIAG-02 的 `AcceptedInitialEvidence` 和已经由 `SandboxObservationProjector` 校验过的 `ObservedFact` 派生。不存在初始证据时传 UNKNOWN，不从用户声称“有数据”直接推导 AVAILABLE。未授权/跨 Run/Domain/伪造事实不得进入新字段。

`PlanningObservationContext` **不是** M6 Positive Grant，也没有独立凭据证明能力：只能由可信调用方构造，外部原始 JSON 不能凭字段名自行获得权威。测试及未来生产 Composition Root 仍必须正确封闭证据提供者。模型输出仍需经过 M4 合法候选、PlanValidator、Policy Rechecker。

## 验证

- 旧 Slice 0–2、GA-01C pytest、mypy、ruff 全量回归；
- Typed Context 版本、合法值、字段上限、UNKNOWN 与隔离保护负测；
- 实际 Qwen2.5:3b，原六个合成任务 × 两次重复，保持 DIAG-02 预算、动作含义和验收门槛（完成 ≥10/12、位置动作正确率 ≥90%）；
- 验证进入模型的 payload 含 `planning_observation` 而不含 `last_agent_action`；收集实际请求条数和完成结果。单合法候选决策可能不需要 LLM 调用，不能把这些步骤当成真实模型决策。

## 尚未涵盖

生产 Domain State Store、分布式跨进程权限、真实工具执行、生产 M6 授权、多模型/多领域长期泛化。此 PR 是 frozen Slice-2 M4 合同的**向后兼容可选扩展**，需针对性审查后才可合并；不将测试里的通过率宣称为通用自主 Agent 成熟度。
