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

## 真实执行与安全结果（2026-10-10）

**最终验证代码 HEAD** `cdfbfa4eeee7a247c2cd12c382ba10019bf3ac02`。GitHub Actions **[Run #38021400487](https://github.com/cxjchelsea/AgentRuntime/actions/runs/38021400487)** 两项 Jobs SUCCESS：

- 旧版定向回归：`110 passed / 1 skipped`；
- 全量：`1225 passed / 7 skipped / 1 warning`；
- mypy：`260 source files`，无问题；Ruff lint 和 format：PASS；
- 真正的本地 Ollama `qwen2.5:3b` CPU 推理，旧 Live Smoke + Loop + EVAL-01 全部 PASS；
- **DIAG-03 Typed Planning E2E：12/12 FINISH，18/18 动作序列完全匹配，0 模型/运行异常**；六种合成任务各 2 次重复，与 DIAG-02 保持相同预算与预注册门槛。
- 6 次起始已有证据的运行：因 DIAG-02 initial evidence admission + M4 `SINGLE_LEGAL`，`typed_model_requests=0`，不计入真实模型选择；
- 6 次起始无证据的运行：每次发起 1 次真正的结构化模型选择；执行后已验证事实缩窄合法策略，后续无需模型再次作策略选择。新模型请求包含 `planning_observation`，且不包含旧的 `last_agent_action` 字段。

### 失败证据（必须保留）

先前代码 HEAD `7f862b18af841d5d5b4ef26227dfe502342eeff3` 的 [Run #38021224276](https://github.com/cxjchelsea/AgentRuntime/actions/runs/38021224276) 中，真实 Qwen3B 在第三个任务输出 `strategy_id: 1`（非字符串）。M4 `StrategyModelOutputValidator` 正确拒绝并使 Live Job 失败，未授权执行。后续提交**没有修改系统提示词、模型、合法性验证或评分阈值**，只改了评测为逐任务记录异常、完成剩余任务并准确报告错误。最终新模型运行未复现该非法输出。两次实验体现小模型输出随运行波动，单次 12/12 不能作为长期稳定性的统计结论。

### 交付边界与遗留问题

```text
DIAG-03 OPTIONAL TYPED CONTRACT = IMPLEMENTED
DIAG-03 LEGACY M4 COMPATIBILITY = VERIFIED
DIAG-03 LIVE QWEN3B SANDBOX E2E = 12/12 VERIFIED ON EXACT CODE HEAD
MODEL INDEPENDENT MULTISTEP REPLANNING = NOT ESTABLISHED
PRODUCTION M6 POSITIVE GRANT = NOT AUTHORIZED
PRODUCTION TRUSTED CONTEXT LOADER = NOT IMPLEMENTED
```

**审查前不得合并。** 需明确审查：（1）投影回调是否可受到不可信输入或跨 Run 共享状态污染；（2）冻结 M4 `StrategyModelRequest` 的可选字段是否破坏外部消费者；（3）`include_legacy_agent_action=False` 与旧版本 prompt 的兼容性；（4）现有 DIAG-01 测试 Eligibility 还解析内部旧 snapshot——模型通道迁移不等于所有规划消费者都迁移。还需要过期、反复读取、冲突状态和重新采集确有必要场景验证后才可考虑生产接线。


## 最新精确 PR HEAD 的复现记录（同一代码）

PR HEAD `5013e70d5cd62e589c12040c82b17261ee881879` 对比先前通过的 `cdfbfa4eeee7a247c2cd12c382ba10019bf3ac02` **仅增加本文档内容，没有修改代码**。

GitHub Actions [Run #38021659409](https://github.com/cxjchelsea/AgentRuntime/actions/runs/38021659409)：
- 常规 Job **SUCCESS**（pytest/mypy/Ruff 通过）；
- 实际 Qwen2.5:3b 模型 Job **FAIL**：`11/12` 任务完成，`16/18 = 88.9%` 动作匹配，1 次 `StrategyModelOutputError`；具体出现在 `inventory-missing` 第一次执行时，模型未给出满足冻结 M4 输出契约的 Strategy，系统拒绝执行。
- 因预注册验收条件为 **≥10/12 完成、≥90% 动作匹配、0 非预期错误**，此精确 HEAD **未通过真实模型整体验收**。不能用 earlier PASS 覆盖 latest FAIL，也不能用 Model Validator 放宽规则实现假通过。

此两次 CI 的代码等价、实际模型表现不同，提示 3B 对所选 typed input 的结构化策略生成具有波动。应将模型返回的结构合法性失败计入长期可靠性指标；实现增加可诊断的受控错误分类、固定模型版本/权重摘要、重复种子和多次独立运行，而不是只选一次绿灯。当前系统对非法输出的阻断是安全预期，不能算完成成功。

**综合状态**：`TYPED_M4_CONTRACT_IMPLEMENTED / STANDARD_CI_PASS / LIVE_PROOF_EXISTS / LATEST_LIVE_ACCEPTANCE_FAIL / PRODUCTION_INTEGRATION_NOT_AUTHORIZED`。PR #101 保持 Draft，待针对性信任边界 review 和重复测试稳定性证据。
