# GA-01C DIAG-02 — 可信初始证据准入与 M4 适用性

## 目标与位置

回应 DIAG-01 经实际模型验证的遗留问题：已经存在的仓储数据，模型仍先选择不必要的采集。**不可**直接凭原始用户请求包含“已存在”、也不可凭评测中预存的 `expected_actions` 推导可跳过采集的事实。

本切片创建测试沙箱独立 `SyntheticInitialEvidenceProvider`，在首轮 M4 前，通过 `admit_initial_evidence` 读取并检查有版本的源数据证据；经验证的 `AcceptedInitialEvidence` 仅作为 M4 `StrategyEligibilityRule` 的否定条件。并未授予模型 Tool 执行权限、修改 Policy，或提前宣告任务完成。

## 类型合同

`InitialEvidenceRecord` 必须具备 evidence_id、run/session/subject、tenant/scope、domain/version/fingerprint、record_revision、observed_at、expires_at、status、source_kind；`AcceptedInitialEvidence` 是只读准入回执。

- Run、Subject、Session、Scope、Tenant、Domain、Version、Fingerprint 有任何不符 → 异常拒绝；
- 时间无时区、过期、未来采集、版本非法、来源不是隔离测试 State Store → 异常拒绝；
- Provider 无记录 / 状态 MISSING、UNKNOWN、CONTRADICTORY → 不允许据此排除采集；
- 只有已准入的 AVAILABLE_UNVERIFIED 证据，可以阻断冗余采集 Strategy；**验证动作仍必须执行并取得 GOAL_SATISFIED 回执**。
- 相同任务的“数据缺失”情形，Provider 返回无记录，不向模型注入未来期望动作；由现有 M4+Observation 决定并利用 DIAG-01 的执行后证据限制。

## 真实 E2E 验收

继续在 Qwen2.5 3B、六个合成任务×两次重复、同 LoopBudget 和温度条件下验证；保持原验收要求：**完成至少 10/12，动作序列正确率至少 90%**。同时负测跨 Run/Scope/Subject/Tenant/Domain/版本/有效期及 UNKNOWN，不得为提高得分降低合同严谨度。

## 重要边界

当前 Provider 是 test-only、由隔离模拟状态库播种，数据设置与测试场景的独立业务状态一致，但**还不是真实业务可信数据服务**。该实验只能验证如何接入初始证据的设计路径，不证明生产 Domain State Store 或 M6 Truth Boundary 已实现，也不证明 LLM 自身独立重规划能力增强。

后续 DIAG-03 将状态从 `last_agent_action` 迁移到正式的 Typed Planning Observation/Initial Context，不把测试 Snapshot 当成生产合同。
