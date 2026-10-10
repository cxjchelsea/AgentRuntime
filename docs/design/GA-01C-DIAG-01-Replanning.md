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
