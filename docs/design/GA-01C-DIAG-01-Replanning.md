# GA-01C EVAL-02-DIAG-01｜Observation → Replanning 定向诊断与整改

> 基线 PR #98 失败事实：Qwen2.5 3B 的 12 次完整任务只有 5 次 FINISH、10/26 动作位置正确；模型已收到观察但反复采集。此次不修改 M2/M4 核心、不授权真实 Tool。

## 三组对照与冻结参数

| 组别 | 输入给模型的 Observation | M4 约束 | 意图 |
|---|---|---|---|
| A_TEXT | 现有经过 sandbox projector 的自然语言描述 | 原合法候选集 | 复现实测失败基线 |
| B_TYPED | 从同样的 **已验证 Mock 事实**投影为 JSON 结构：evidence_state、evidence_fact、executed_actions、outstanding_condition、provenance | 原合法候选集 | 分离上下文表达影响 |
| C_TYPED_ELIGIBILITY | 与 B 完全相同的 JSON | M4 注入 Domain `StrategyEligibilityRule`，仅在已验证来源证明数据可用、且存在已观察到的执行动作时排除重复采集策略 | 分离动态候选约束贡献 |

这里的 JSON **是 test-only 的证据状态投影**，并非新生产事实；其“待验证”状态是由 Mock Tool 事实 `SOURCE_AVAILABLE` 推导出来的。没有证据时不能排除采集，不对 Tool UNKNOWN 或无可信观察做推理。C 不覆写模型选出的动作、不从两种候选直接插入正确答案，合法动作仍经过原 M4 Planner/Validator/Policy Rechecker 批准，且模型能够见到合法候选集变化。

所有组：同一 `qwen2.5:3b`、同样六个合成任务（laboratory、finance、inventory）、两次重复、预算（4 iterations / 3 executions / 55s decision / 5s execution）、相同动作语义与 prompt、相同确定性 temperature=0。预注册阈值仍是完整完成 ≥10/12，动作序列位置匹配率 ≥90%，不能把 NO_PROGRESS 或异常算成功。

## 观测与安全

- 每个模型调用前由 `SandboxObservationProjector` 校验 Run/Domain/Execution 来源；未受信任文本不产生 typed snapshot。
- `ProvenanceBoundCollectEligibility` 仅注入现有 M4 Eligibility 接口，不重新生成批准计划；只有 `AVAILABLE_UNVERIFIED` 且已观察的 `SOURCE_AVAILABLE/SOURCE_ALREADY_AVAILABLE` 才可限制 collect。不能单靠模型自行声明。
- 定向负测验证：原始自然语言不能开启重复治理、无证据不能限制候选，已验证事实才触发；既有 NO_PROGRESS、未授权完成和跨 Run 负测保留。
- 三组都记录每个 case/repeat 的动作序列、完成状态、模型接收的观察计数、M4 资格限制次数及总体完成率/动作正确率。失败需保留。

## 评测证据

代码与真实 Ollama GitHub Actions 执行后填写精确 HEAD、CI 链接及逐组数值。本阶段尚未宣称 C 改进已验证。三个任务家族仍是模拟业务，不是三个独立生产 Domain Package。

## 实际验证结果｜最终代码 HEAD（2026-10-10）

**冻结代码 HEAD**：`8e7df23dd8bae4a37d2b8c7d462767683bfd5b7c`。  
**真实 GitHub Actions**：[Run #38019587887](https://github.com/cxjchelsea/AgentRuntime/actions/runs/38019587887)。

- **常规门禁：PASS**。targeted `110 passed / 1 skipped`；全量 `1204 passed / 5 skipped / 1 warning`；mypy `255 source files`、Ruff lint、Ruff format 均 PASS。
- **模型接入基线**：Ollama Qwen2.5 3B 真模型 Smoke PASS，原有单任务 Agent Loop PASS，EVAL-01 六道单步选择 PASS。
- **DIAG-01 严格验收：FAIL**。三组真实对照全部执行完毕，C 的完成率达标但动作序列正确率没有达到预注册的 90%，因此 CI 保持失败，不放宽原始门槛。

| 方案 | 完成率 | 动作正确率 | BLOCK | 未分类错误 | M4 资格排除次数 |
|---|---|---|---|---|---|
| A_TEXT | **4/12（33.3%）** | **10/26（38.5%）** | 8 | 0 | 0 |
| B_TYPED | **4/12（33.3%）** | **10/23（43.5%）** | 5 | 3（StrategyModelOutputError） | 0 |
| C_TYPED_ELIGIBILITY | **12/12（100%）** | **16/20（80.0%）** | 0 | 0 | 8 |

**交叉检验**：在最初未做投影资格证明强化的 [Run #38019020166](https://github.com/cxjchelsea/AgentRuntime/actions/runs/38019020166) 中，三组统计分别也是 4/12、4/12、12/12，C 动作正确率同为 80%。最新 HEAD 加入了 `accept_verified_projection`，使只有经过 `SandboxObservationProjector` 校验并在同一测试 Step 对象显式确认的事实才能触发 M4 eligibility 拒绝，任意 Context 中伪造的 JSON 标记不再单独构成排除权威。**该机制仅适用于测试沙箱；不是生产级加密证明或跨服务事实权限。**

### 为什么 C 不是“模型突然更会规划”

C 在取得真实的 `SOURCE_AVAILABLE` 观察后，用 **M4 Domain StrategyEligibilityRule** 拒绝不再适用的重复采集 Strategy。只剩一个合法 Strategy 时，已有 `HybridStrategySelector` 使用 `SINGLE_LEGAL` 确定性选择，**第二轮不需要调用 LLM**。日志中的 `verified_observations=0` 统计的是“进入模型请求的后续观察次数”，而不是没有经过 Sandbox Projector / M4 事实校验。

因此 C 的 12/12 FINISH 说明：在这六个模拟任务中，**可信证据支持的 Domain 资格约束 + 既有 Runtime 执行链**能显著提高任务完成率；**并不说明自由模型决策能力提高**。这是有益的架构证据，但不能借此声称通用自主 Agent 已通过 Eval。

### 仍未解决的错误选择

`inventory-existing-reversed` 两次运行均先选择了不必要的采集，再借助资格约束转向核验，路径 `DOMAIN_ACTION_B → DOMAIN_ACTION_A`，而预期是 `DOMAIN_ACTION_A` 直接核验；造成 4 次位置不匹配，C 的 16/20=80%。

当前规则只依据本 Run **已执行并验证的采集结果**抑制重复动作。对于任务开始前就已存在的资料，**没有以经过证明的初始业务状态进入 M4**。如果把用户文本的“已经有数据”或测试夹具 `case.source_available` 直接当成权威，会掩盖本来应该解决的信任边界；不能在本次预注册试验失败后偷偷加进正确答案。

### B 方案失败的原因与边界

将 JSON 结构化状态直接塞进现有 `InteractionContext.last_agent_action` 的**单一字符串字段**后，发生 3 次 `StrategyModelOutputError`，模型输出被 M4 合法性校验拒绝，没有绕过授权，也没有假冒成功。结构化信息不自动等于可信且模型能稳定解析；应该设计新的 typed `PlanningObservationContext`，将 `evidence_state / previous_actions / pending_validation` 显式建模并通过受控 Schema 投影到模型请求，而非塞入原本只用于近期口播动作的字段。

### 下一步分离为两个正式阻塞项

1. **DIAG-02 / Initial Evidence Admission**：在任务开始时从**可信 State / Domain Evidence Provider**读取已有源数据的状态，并验证 Run/Subject/Scope/Domain/版本/有效期；仅在有证据的情况下将“重复采集不适用”纳入 M4 Eligibility。不得按任务标准答案直接封禁动作，缺少证据时保持未知和必要采集可用。
2. **DIAG-03 / Typed Planning Observation Contract**：重新定义模型输入中的工具观察、完成程度、剩余待证事实，以及反提示注入边界；使用相同任务集比较，区分模型独立正确决策率与 Eligibility 强制缩窄后的成功率。加入初始证据缺失、过期、矛盾、UNKNOWN、跨 Run 伪造和确认重新采集确有必要的场景，防止“永远不重复”错误。

**正式裁决**：`DIAG-01 IMPLEMENTED / STANDARD CI PASSED / LIVE A-B-C COMPLETED / C COMPLETION IMPROVED / OVERALL ACCEPTANCE FAILED`。PR #99 保持 Draft，不合并到 main，不能以 100% 完成率覆盖 80% 动作正确率的问题。
