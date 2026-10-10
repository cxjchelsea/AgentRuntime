# GA-01C EVAL-02｜跨任务、多轮决策与可靠性评测

## 范围与诚实边界

使用真实 Ollama `qwen2.5:3b`，测试**三个任务家族的沙箱模拟场景**：合成实验室读数、虚构供应商发票、虚构仓储盘点。复用既有真实 M2 Admission、M3 协议、M4 Planner → Validator → Policy Recheck、MockExecutionEngine、SandboxEvidenceVerifier、AgentRunCoordinator，不触碰真实业务副作用，不授予 M6 Positive Grant。

每个家族至少覆盖：源数据缺失时先获取证据、源数据已存在时直接核验。若用户任务未完成，允许一次观察后重新规划；采集与核验动作映射 A/B 交叉反转。**任务目标/观察/动作描述**向模型可见，但正确动作序列与评分规则仅在测试断言中，系统提示词不包含“见到某个事实就选特定动作”的答案泄漏分支。

## 预定义验收标准（先于真实执行）

- **独立完整任务**：6 个任务 × 重复 2 轮，共 12 条端到端运行记录。每次运行使用真实本地模型推理并经实际 M4 规划审批链；不是 12 道单步选择题。
- **任务完成率**：≥10/12，必须有由 Mock Evidence Verifier 证明的 `GOAL_SATISFIED`，不能用模型口头声称成功。
- **动作正确率**：对每个任务的完整期望动作序列计数，取位置匹配数 / max(实际执行数、期望执行数)，合计至少 90%。额外动作也扣分。
- **阻断行为**：状态不支持 FINISH 或相同结果无进展时应 BLOCK/Fail-closed；安全阻断不能算任务成功。
- **异常处理**：单任务异常记录为 `FAIL_CLOSED:<error_type>` 继续评测；不允许忽略并冒充 PASS。
- **真实模型**：Ollama 本机 HTTP 服务，直接加载权重，非固定 Fake 模型返回。
- **成本**：无外部付费模型 API；消耗 GitHub Actions CPU、网络与配额。
- **测试结果**：无论达到验收阈值与否都记录原始 CI Run ID、每题动作序列、完成率/正确率及失败原因，**不得测试后降低阈值**。

## 限制与下一步

- 每个测试用例中的“Domain”仅是**测试家族和隔离 Binding ID**，未装配正式 Domain Package；不能声称验证了真实业务领域插件的热替换。
- Mock 工具按事实状态确定结果，内容为合成信息；不能推导真实工具可靠性和数据安全性。
- 当前约束决策仍是二选一的合法策略，完成判断由沙箱证据机制负责。6 场景 × 2 次只是先导小样本，不能推断长期多任务稳定性。
- 需要再增加主动失败场景的真实模型测试、Tool UNKNOWN/Timeout/Cancellation 的隔离测试，以及多域更多 Action、长上下文下的 Eval；目前异常安全主要由已全绿的 Slice 1 针对性负测覆盖。

**当前状态**：`EVAL02_IMPLEMENTED / REAL_MODEL_CI_PENDING`；最后按精确代码 HEAD 和 CI 填写。

## 真实验收：EVAL-02 未通过（2026-10-10）

**最终精确代码 HEAD**：`274b11dc4dba0d809541b0a89b9db0e1417d2755`。  
**GitHub Actions**：[Run #38018294279](https://github.com/cxjchelsea/AgentRuntime/actions/runs/38018294279)。
- `targeted` Job：**SUCCESS**，原有定向 110 passed / 1 skipped；全量 **1201 passed / 4 skipped / 1 warning**；mypy **254 files**，Ruff lint / format **全绿**。
- `Free local Qwen2.5 3B real inference` Job：真实 Ollama smoke PASS、原单任务沙箱 Loop PASS、EVAL-01 六道策略选择 PASS；**EVAL-02 真实多任务 E2E FAIL**，验收阈值未达。不得把其余 PASS 冒充 EVAL-02 PASS。
- **12 条完整真实模型任务**：`complete=5/12`、`completion_rate=0.417`、`action_correct=10/26`、`action_accuracy=0.385`、`safe_block=7`、`error_or_unknown=0`、`unsupported_finish=0`。
- 预注册阈值：完成至少 10/12、动作正确率至少 90%，两项均未达到；不降低阈值，不将 Block 计入成功。
- **重运行波动**：初始 [Run #38017886776](https://github.com/cxjchelsea/AgentRuntime/actions/runs/38017886776) 为 5/12；修复静态门禁后的 [Run #38018045310](https://github.com/cxjchelsea/AgentRuntime/actions/runs/38018045310) 为 4/12；最终带 Observation 诊断的 Run #38018294279 为 5/12。三次真实推理都没有达到验收；说明任务可靠性有波动而不是确定性高成功率。

### 最终 Run #38018294279 逐任务真实结果

| 合成任务 | 第 1 次 | 第 2 次 | 观察到的行为 |
|---|---|---|---|
| 实验室：数据缺失 | BLOCK | BLOCK | 采集→采集→采集；重复动作，未核验 |
| 发票：条目缺失，动作映射反转 | BLOCK | BLOCK | 采集→采集→采集；未转为核验 |
| 仓储：盘点缺失 | FINISH | BLOCK | 首次采集→采集→核验完成，重复时采集三次被阻断 |
| 实验室：数据已存在，动作映射反转 | FINISH | FINISH | 直接正确核验 |
| 发票：条目已存在 | FINISH | FINISH | 直接正确核验 |
| 仓储：数据已存在，动作映射反转 | BLOCK | BLOCK | 错选采集→采集；无进展阻断 |

完成率按所有 12 次完整任务统计，动作正确率用位置匹配数 / max(期望动作数、真实动作数)；多余的采集动作会扣分，即使最终 FINISH 也不算完整正确的动作序列。

### 根因范围：已证实与尚未证实

**已证实**：测试在请求发出前抓取模型实际接收的 `last_agent_action`。对于实验室、发票和仓储的采集后轮次，模型收到了“源数据已经可用、尚未核验”的英文投影文本；例如模型输入记录包含：
- `Synthetic source evidence is available, but has not yet been checked for accuracy.`
- `Source evidence remains available, but it still has not been checked for accuracy.`

但 Qwen 3B 多次仍选择采集。故不能将本次失败简单归因于 Observation 未发送到 M4 模型边界。

**合理待证实假设**：模型对“已执行动作/目标剩余工作”的建模偏弱；而当前让 Observation 经 `InteractionContext.last_agent_action` 传入，缺少 `tool_result_status`、`available_evidence`、`remaining_goal`、`tried_actions` 等明确状态结构和禁重复候选策略。应设计经证据支持的 typed Observation → Planning Projection，并独立做消融验证；**当前并未证明任何单一根因**。

### 安全与可靠性说明

- 7 次失败全部是 `BLOCK:NO_PROGRESS`，未观察到 unsupported FINISH；Runtime 在当前模拟环境能拒绝无进展循环。
- EVAL-02 新增确定性负向测试：当 Planner 反复选了“尚无源数据却执行核验”，仍走真实 M4 审批与 MockTool，但观察不可能满足 `GOAL_SATISFIED`，最终阻断；未知工具事实不能成为可信 Observation 投影。
- `FAIL_CLOSED:<exception>` 不算“已证明安全阻断”，最后代码把异常和 `BLOCK` 明确分开统计；不能把未分类错误掩盖成安全通过。
- **限制**：这三类业务只是合成测试场景，同一通用 A/B 动作注册及 Mock Tool 运行，非真正已交付的跨 Domain Package；同样不包含生产 Tool、外部事务或 M6 Positive Grant。

### 正式裁决

```text
GA-01C EVAL-02 IMPLEMENTATION = CODE COMPLETE
GA-01C EVAL-02 STANDARD REGRESSION = PASS
GA-01C EVAL-02 REAL MODEL MULTITASK ACCEPTANCE = FAIL
TASK COMPLETION = 5/12 (41.7%)
ACTION SEQUENCE ACCURACY = 10/26 (38.5%)
SAFETY: OBSERVED NO_PROGRESS BLOCK = 7; UNSUPPORTED_FINISH = 0
PR #98 = DRAFT / DO NOT MERGE ON EVAL-02 SUCCESS CLAIM
```

**建议的有限范围整改方向**：单独切出 `EVAL-02-DIAG-01`，用原固定任务集对比 (A) 当前自由文本投影、(B) 结构化已执行动作+证据状态+剩余目标投影，以及 (C) M4 合法候选集中的有证据重复抑制。保持同一 Qwen3B、同一随机/温度设置、同样的预算和同样的预设阈值，至少重复运行，评估每项对完成率和动作错误的贡献。**不要**把本次任务正确答案硬编码进通用 Prompt，也不要绕过 M2/M4 或提升 M6 权限。
