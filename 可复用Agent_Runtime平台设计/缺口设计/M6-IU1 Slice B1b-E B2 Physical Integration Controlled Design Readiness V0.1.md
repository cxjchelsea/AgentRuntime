# M6-IU1 Slice B1b-E / B2 Physical Integration — Controlled Design & Readiness V0.1

**日期**：2026-10-09。**性质**：设计与就绪审查，非代码实施授权。**生产基线**：main 8cc64eec2a471d4c8e8de1a9545bb92d9afb7ba4。B1a/B0/Slice A/B1b-P 已合并；B1b-E/B2 尚未实施；B3、D-M6-IU1-01 仍阻塞。

## 1. 当前真实接线

- runtime/orchestration/runtime.py 中 run 从第 133 行开始；RESULT_VALIDATE 在 231–239，RESPONSE_PLAN 从 241、UPDATE 从 270 开始，成功终态在 285。
- runtime/orchestration/m2_runtime.py 中 run 从第 60 行开始；RESULT_VALIDATE 在 183–191，RESPONSE_PLAN 从 193、UPDATE 从 222 开始，成功终态在 237。
- 这两条主链仍然在 RESULT_VALIDATE 调用 ResultValidator.validate(execution, context, approved)，没有接线 B1a/B1b-P。
- runtime/orchestration/runtime.py 的 _run_stage 在阶段内异常时调用 _fail_stage，_fail_stage 负责错误 Trace 收口；**阶段之间抛错不自动调用 _fail_stage**。
- _close_turn 目前重复调用会再次写 Trace 和 TURN_END，缺少 exactly-once 防护；asyncio.CancelledError 不属于 except Exception 所能可靠捕获的普通异常。
- B0 NoGrantTurnSlot.take_once 最多一次，close 可重复调用但不能取代外层 finally；B1a 和 B1b-P 都没有可信来源证明。

## 2. B2 可信 RuntimeInput 捕获

生产 Orchestrator 必须在同一轮入口从已校验的 RuntimeInput 捕获 request_id、session_id、identity_scope、trace_id，形成私有不可变、turn-local OriginSnapshot。Snapshot 表示“由此运行入口捕获”，并不证明外部身份经过认证或有 M2 Positive Grant。原始输入必须先做 exact-type/Canonical 校验，不能由下游 ExecutionResult、ApprovedActionPlan、RuntimeContext 反推期望 request/session/scope。InputProcessor.process 返回结果需再次与入口 Snapshot 比对，发生变动 fail-closed。

B2-B01 待精化：冻结入口类型校验、processed_input 可变更字段范围、Snapshot 创建时点、失败时 Trace 是否已打开。

## 3. B2 受控 Facade 和双主链接线

候选选项 A：单轮 M6NoGrantFacade，接收冻结 OriginSnapshot，管理 B0 Slot、B1a Controller 和 B1b-P，并向宿主返回结构性 UNKNOWN/UNKNOWN ValidatedResult + immutable BLOCK decision。两条 run 的 RESULT_VALIDATE 保持同名调用点与顺序不变，内部以受控 facade 取代对普通 ResultValidator 的生产调用；公共三参数 ResultValidator ABI 不得修改。

候选选项 B：现有 ResultValidator adapter 携带 side-channel per-turn 绑定。此选项有跨并发轮串扰风险，目前不建议；只有独立论证上下文与退出释放后才可考虑。**推荐 A，但目前属于设计选择，不是冻结实施权限。**

Gated 生产模式缺少 facade、OriginSnapshot、B0 Slot、B1a/B1b-P 任一依赖必须 fail-closed，不能落回旧 Validator。原有 M0/M2 测试和兼容模式只能在明示的非受保护模式保留，不能宣称已被 B2 防护。B2-B02 尚需 exact constructor/DI、双 run 精确 diff、是否变更原有测试 stub 的方案。

## 4. B1b-E 阻断语义

在 RESULT_VALIDATE 结束之后、**创建/调用任何 ResponsePlanner.plan coroutine 之前**核验 B1b-P decision。NoGrant 和其他无正向授权输入均不能进入 M7 ResponsePlanner/ResponseGenerator/ResponseValidator 或 M8 StateMemoryUpdater；只以内部 typed NO_GRANT_DOWNSTREAM_BLOCKED 终止。不得生成伪造成功的 RuntimeResponse/UpdateResult，不得自动提供未审查的安全中性回复。即使 M5 已执行成功也不构成业务成功验证；M5 既有副作用不被本保护机制撤销。

严格表：
| 情形 | Gated 结果 |
|---|---|
| B1a UNKNOWN + B1b-P BLOCK | 终止，M7/M8 零调用 |
| B1b-P typed error / 缺失 decision | fail-closed，M7/M8 零调用 |
| Slice A 拒绝、B1a 身份不匹配 | fail-closed，M7/M8 零调用 |
| 传统 VALIDATED/SUCCESS 结果 | 无 B3 正向权限，不得以此 ALLOW |
| 缺 facade 且存在 legacy validator | 不允许静默回退 |

B1b-E 必须物理接入 B2 才能对上述入口保证零调用；纯 B1b-P 的测试通过不等于生产保护已生效。

## 5. 终态与取消安全

Orchestrator owner 必须提供共享的 finish_turn_once(turn_context, status, reason)，对已终态 Trace 不再修改 finished_at、不重复 TURN_END。两条 run 使用同一收口机制：正常阻断写 ERROR 和 NO_GRANT_DOWNSTREAM_BLOCKED，不返回成功的 RuntimeTurnOutcome。已有 _run_stage/_fail_stage 可能先完成错误终态，新终态化必须幂等避免双 close。不能只在两次 _run_stage 之间直接 raise。

完整 run 生命周期必须用 try/finally 管理 B0 Slot、Snapshot 和每轮 Controller；异常与 asyncio.CancelledError 都必须关闭 Slot，且 cleanup 不能掩盖原始异常。TraceStatus 是否支持 CANCELLED 要先精确审查；若没有，不能创造公开枚举值，应采用合法终态与明确取消原因。并发验证应使用每个 turn_context 真实 Trace，不能依赖共享 last_trace 的最新值作为唯一依据。

B2-B03 待精化：exact helper 差分、异常优先级、取消 Trace、日志失败恢复、单次终态测试。

## 6. 部署可用性边界

因为 B3 正向 issuer 未实现，严格 gated deny-only 模式将无法产生普通成功回复，属于**明确的可用性限制**，不能暗中恢复 permissive legacy 路径。正式生产切换策略与安全中性回复交付必须另行审批。B2-B04 待明确模式切换、配置缺失行为和旧 runner 隔离合同。

## 7. 候选文件（非授权）

新增候选 runtime/validation/m6_no_grant_facade.py、runtime/orchestration/m6_terminalization.py、tests/test_m6_iu1_b2_dual_runtime.py；受控修改 runtime/orchestration/runtime.py 和 runtime/orchestration/m2_runtime.py。仍不得修改 runtime/contracts、runtime/interfaces、已合入 Slice A/B0/B1a/B1b-P 或 M2/M4/M5/M7/M8 的生产实现。如需要扩大文件范围必须重新走 Controlled Amendment。

## 8. 未来实施验证矩阵

| ID | Oracle |
|---|---|
| E01 | 普通 Orchestrator NoGrant：全部 M7/M8 接口零调用 |
| E02 | M2 Orchestrator NoGrant：相同零调用；M2 原有策略顺序不改变 |
| E03 | RuntimeInput 与 processed_input 不一致：拒绝，不能从下游推导来源 |
| E04 | 伪造 context/approved/plan/execution 身份字段：fail-closed |
| E05 | facade 或 B1b-P 决策缺失：不回退旧 Validator |
| E06 | _run_stage 中失败：单次 TURN_END，保留原异常 |
| E07 | 阶段间 BLOCK：Trace ERROR、单次 TURN_END |
| E08 | M5/M6 中取消：Slot 关闭，无 SUCCESS 假象 |
| E09 | 并发两轮：无跨轮 Slot、Controller、Origin、Trace 串扰 |
| E10 | Slot take_once 二次调用或关闭后访问：不获得正向授权 |
| E11 | 伪造 Positive Grant / legacy VALIDATED：绝不自动 ALLOW |
| E12 | 保持 15 个调用点、公共 ABI 与既有回归 |
| E13 | 实施精确 HEAD 四项门禁 + 独立实施审查 |
| E14 | 合并后的 main 精确 HEAD 四项门禁 |

## 9. Readiness 裁决

B2-B01、B2-B02、B2-B03、B2-B04 均为 **OPEN DESIGN BLOCKER**；E01–E14 尚未执行。B1b-E 的保护位置已明确，但只能在 B2 接线后兑现，当前不能独立实施。

```text
B1b-E/B2 PHYSICAL INTEGRATION DESIGN = SUBMITTED_V0.1
B1b-E BARRIER PLACEMENT = DESIGN_SPECIFIED
B1b-E IMPLEMENTATION READINESS = NOT_READY / B2_DEPENDENT
B2 IMPLEMENTATION READINESS = NOT_READY / B2-B01..04 OPEN
B2 IMPLEMENTATION AUTHORIZATION = NOT_GRANTED
B1b-E IMPLEMENTATION AUTHORIZATION = NOT_GRANTED
B3 POSITIVE GRANT = BLOCKED
D-M6-IU1-01 = OPEN
NEXT = B2-01..04 Exact-Diff Targeted Physical Design Remediation + Independent Design Review
```
