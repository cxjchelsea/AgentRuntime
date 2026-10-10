# GA-01A｜Targeted Design Self-Review V0.1

> 审查对象：[GA-01A 详细设计](GA-01A-Minimal-Agent-Loop-详细设计.md)。基线 main `53cdda379979be836262df1bf6f9382c7ba89897`。  
> **性质：同一执行者的源码一致性和安全边界复查，非第三方独立审查。** 未运行代码或测试。  
> **结论：READY_FOR_TARGETED_INDEPENDENT_REVIEW；NOT READY FOR GA-01B CODING。**

## 逐项核查

| 检查 | 结论 | 源码/证据 |
|---|---|---|
| 不循环完整 RuntimeOrchestrator.run | PASS DESIGN | `runtime/orchestration/runtime.py` 的 `_run_pipeline` 一直走到 M7/M8 |
| 不绕过 M2 增强 Policy | NEEDS EXACT HELPER REVIEW | `runtime/orchestration/m2_runtime.py` 的 Priority/Constraint/Policy 和入场检查不可简化 |
| 仅批准的计划进入 M5 | PASS DESIGN | `runtime/interfaces/planning.py`、`contracts/planning.py`、`interfaces/execution.py` |
| 模型无自主 Tool 权限 | PASS DESIGN | M3/M4 StructuredModel 只返回理解/合法 strategy |
| 执行结果不直接当真实业务事实 | PASS DESIGN | `contracts/execution.py` vs `contracts/validation.py` |
| NoGrant 不被绕过 | PASS DESIGN WITH TEST DEPENDENCY | `runtime/validation/no_grant_downstream_policy.py`，需 T10/T13 负测 |
| Sandbox 不得生产装配 | NEEDS STATIC TEST | 不导出测试 Verifier；需要构建时与导入负测 |
| 第二轮确实观察第一轮事实 | NEEDS E2E | 需 T01/T02 数据对比 |
| 无第二套 Scheduler/State Owner | PASS DESIGN | 新 Agent Core 只控制任务级迭代 |
| request/plan/execution correlation | NEEDS FIXTURE TEST | A-02 尚未冻结 |
| 可确认代码门禁 | NOT RUN | 仅文档阶段；不冒称 |
| 独立人员审查 | NOT PERFORMED | 本文只是一轮 self review |

## 最重要的落地纠偏

1. 不能把 `AgentRunCoordinator` 简写成不停地调用原 `RuntimeOrchestrator.run()`；必须组合现有 Stage Interfaces，而且 M2 的增强 admission 需要完全复用。
2. 不接受沙箱 Verifier 把模拟结果签发成正式 `ValidatedResult`；否则不满足 M6 的 Truth Boundary。
3. 不接受“Agent 先调一次假 Tool，第二轮硬编码 FINISH”的测试；完成必须由观察事实驱动。
4. 刻意不在 GA-01B 提前做 Prompt/RAG/Memory 的全功能实现，优先交付可运行真实控制流。
5. 避免新增无必要 Canonical Schema 和冗余 Runtime Authority。

## 实施前需要解决

- **G01**：提取或复用 M2 增强 admission 的最小公共判定位置，证明 G2 没有行为漂移。
- **G02**：明确并测试迭代 request_id / context / plan_id / execution_id / scope 的追踪方式。
- **G03**：证明 test-only Sandbox 不能进入生产依赖注入和实际副作用执行路径。

若 G01–G03 的方案和负测均清晰，GA-01B 可进入第一小切片实施；不需继续扩展 Runtime 范围。
