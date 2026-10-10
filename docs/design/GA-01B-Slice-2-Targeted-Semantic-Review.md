# PR #95｜GA-01B Slice 2 针对性语义审查与合并裁决

> 审查对象：`0aee13e243bcc5b8f933eb549f9abff12e4f6409`，base main `f3db0ebf18a44f173b669bb1829f9899fda3c585`。  
> 审查方法：按源码调用链、自动化测试及 CI 证据做**作者侧针对性 review**；非第三方独立审查。  
> 裁决：**AUTHORIZE_SANDBOX_ONLY_MERGE**；真实 LLM、生产 Tool 和 M6 B3 均未授权。

## 1. 模型权威边界

- `StructuredStrategyTransportAdapter` 只传输 M4 `StrategyModelRequest` 的白名单数据，并返回无执行权限的结构化选择；没有 Tool/DB/通知调用入口。
- `HybridStrategySelector` 在调用模型前检查合法 Strategy/Action 候选集，保留确定性规则优先和非 AGENT_PLANNED 拒绝机制。
- `StrategyModelOutputValidator` 拒绝额外字段、未注册 Strategy、非法 Action、重复 Action 等；模型调用失败抛错，不自行授权执行。
- `DefaultM4Planner` 的策略选择仍进入 `SelectedActionResolver`、PlanValidator 和 PolicyRechecker，审查未发现绕过既有 G01 Admission / M4 审批的新生产分支。
- **保留风险 R-01**：目前模型输出校验以“Strategy 合法且 Action 合法”为主，并未一般性验证两者具备业务语义一致性；该判断属于 Domain Compatibility / Evaluation，不是本切片现有自动测试能证明的结论。不得用“合法”替代“语义正确”。

## 2. Observation 来源与信任

- `ModelDrivenSandboxTurn.model_observation_projection` 位于 `tests/`，只接受同一 `run_id`、`domain_fingerprint` 且带 `execution_id` 的 `ObservedFact`，受上游 Coordinator correlation 与 Mock Evidence Verifier 约束。
- 模型看到的是受控 `InteractionContext.last_agent_action`，不是原始 Tool 文本。该投影在此阶段专属沙箱。
- **保留风险 R-02**：正式 Runtime 尚无含签名/来源版本/证据强度的 typed Observation Projection；测试对 `last.facts[-1]` 的语义解释由固定 Mock 定义，**不能**允许生产 Tool 输出直接塞入该字段并授予完成权威。

## 3. 计划审批与执行

- 测试 `test_ga01_slice2_m4.py` 使用真实 DefaultM4Planner、RuntimePlanValidatorAdapter、RuntimePolicyRecheckerAdapter；两组不同模型选择分别得到 Action A / Action B 的 ApprovedActionPlan。
- `test_ga01_slice2_loop.py` 真实运行 AgentRunCoordinator：第一轮 A → Mock Observation → 第二轮 B → Mock Observation → 第三轮证据支持 FINISH。
- 原 `AgentRunCoordinator` 对 ApprovedActionPlan 的类型、请求关联、Scope/Domain、相同 Plan 复用、预算/超时/取消等阻断逻辑保留。
- **保留风险 R-03**：此测试模型的选择由确定性 FakeTransport 实现，尚未证明真实 LLM 推理能力、提示注入鲁棒性或真实 Tool 回执的业务真实性。

## 4. 失败边界与回归

- 不支持的模型输出 / 未注册策略或动作 → 阻断；传输失败 → `StrategyModelExecutionError`，不退化为执行授权。
- 单独的模型返回内容不能触发 FINISH，完成只能由现有沙箱 Observation 支持。
- M6 G1/G2 仍是 DENY_ONLY，无正向 ValidatedResult / M7 / M8 / 业务副作用提交。
- GitHub Actions 精确 `0aee13e243bcc5b8f933eb549f9abff12e4f6409`：[run #38014787997](https://github.com/cxjchelsea/AgentRuntime/actions/runs/38014787997) **SUCCESS**：93 targeted passed；1179 full passed（1 warning）；mypy 245 files、ruff lint、ruff format 全绿。

## 5. 合并准则与后续

**可合并**当前受限 Scope；审核时必须重新核对 PR #95 exact HEAD、main exact HEAD、文件差异、CI 和 mergeability。合并后在新 main exact HEAD 以 GitHub Actions 再跑相同五项门禁。

后续 GA-01C 才实现真实 Provider + 无副作用 sandbox；正式 Observation provenance、真实 Tool Authorization 和 Domain Action/Strategy Compatibility 不属于此 PR。任何失败或证据变化都要先修复，不能用本审查覆盖缺失的验证。
