# M6-IU1 Slice B2-01..04 Targeted Exact-Diff Physical Design Remediation V0.2

**2026-10-09 · Design-only**。生产基线 main@8cc64eec2a471d4c8e8de1a9545bb92d9afb7ba4，设计基线 PR #82 @ ba465935314806ab31a740aafc549da046c99711。B1b-P 已合并，但 B1b-E/B2 未接线。不得以本文件代替实施授权。

## A. 决定的物理方向

选择 **Option A：显式的每轮 M6NoGrantFacade + 两条 run 的本地 turn state**；拒绝全局 side-channel、可变单例 slot 与修改 ResultValidator 的 public 三参 ABI。生产受保护模式为 DENY_ONLY_GATED：所有没有 Profile Grant 的调用，执行到 M6 后以 typed block 结束，**不产生** RuntimeResponse/UpdateResult，也不执行 M7/M8。该模式是受控能力，不等于可用的正常对话服务。现有旧 runner 不可暗中回退或被称为 gated production。

## B2-B01 — RuntimeInput 来源冻结及一致性

**入口合同**：
- 在两条 run 最初时严格校验 RuntimeInput 对象、request_id、session_id、identity_scope、trace_id 为 exact、非空、无首尾空格；不接受从 ExecutionResult / Context 回填缺失值。
- 在 _open_turn 前建立只读 TurnOriginSnapshot(request_id, session_id, identity_scope, trace_id)。该对象只证明入口绑定，不证明外部身份或 M2 grant。
- 既有 input_processor.process 之后比较 processed_input 与入口的四个 ID；差异 => typed ORIGIN_CHANGED、fail closed，不继续后续 stage。
- M6 调用 Slice A 的 expected request/session 及 B1a ValidationOriginBinding 一律取入口 snapshot；identity_scope 复核 Context.identity_context、ExecutionResult，plan/request 由现有 Slice A 保证。
- InputProcessor 仍可改变正文等非身份属性，但不得更改上述四个身份/追踪键；未经身份认证的上游 RuntimeInput 即使格式通过也不升级为认证用户。
- 对入口非法数据，在 _open_turn 前拒绝，不制造不存在的 Trace；对已打开 turn 的 processed_input 错误，通过共同终态 owner 关闭 ERROR。

**建议精确接口**（private）：TurnOriginSnapshot.from_runtime_input(runtime_input) -> snapshot | raises M6OriginError; assert_processed_identity(snapshot, processed_input) -> None。DTO 仅携带以上 ID，不保存原始 payload。

## B2-B02 — Facade 接口、constructor 模式和 exact-run diff

**受保护组合根**负责显式构造每轮 Facade，不得隐式注入随运行变化的 ContextVar。建议独立内部 Protocol/port：

- M6NoGrantFacade.open_turn(origin: TurnOriginSnapshot) -> M6NoGrantTurnHandle；Handle 携带 B0 NoGrantTurnSlot、B1a Controller 和一次性生命周期。
- async handle.validate(execution, context, approved) -> M6NoGrantValidation(validated_result: ValidatedResult, downstream_decision: NoGrantDownstreamDecision)。
- validate 内部执行 Slice A admit → slot.take_once → B1a.project → B1b-P evaluate；所有关联键从 origin 取得；result UNKNOWN/UNKNOWN；必然 BLOCK；禁止产生 ALLOW。
- handle.close() 仅废止 slot/turn binding；不得写 Trace 或产生响应。重复 validate/take_once 应 fail closed；Handle 不能跨 turn/多次执行共享。

**严格生产注入选择**：新增显式配置枚举 M6IntegrationMode.LEGACY_TEST_COMPAT / DENY_ONLY_GATED（private）。新受保护生产入口必须明确选择 DENY_ONLY_GATED；缺少必需 Facade factory 直接报 DependencyMissingError，不能自动退回 LEGACY_TEST_COMPAT。LEGACY_TEST_COMPAT 为现有测试与旧路径保留的清晰标识，不等于对真实生产提供授权；必须经过单独部署选择。默认值、老构造器兼容和受保护部署开关在独立 re-review 前不视为冻结（B2-B02 余项）。

**两条 run 的一致性差分（精确锚点）**：

| 文件 | 原锚点 | 拟改（仅 gated mode） |
|---|---|---|
| runtime/orchestration/runtime.py | run 第 133 行、_open_turn 第 135 行 | 在 open 前严格冻结 Origin；创建 turn handle；最外层 try/finally |
| 同上 | INPUT 137–143 | INPUT 后 assert_processed_identity；身份错配走 owner ERROR |
| 同上 | RESULT_VALIDATE 231–239 | 保留 RESULT_VALIDATE 原 stage 与 ValidatedResult type；gated mode 以 await handle.validate 得到 ValidatedResult，并保存同轮私有 decision；legacy test compatibility 仍原三参数调用，但不能在 gated mode 使用 |
| 同上 | RESPONSE_PLAN 241 起 | 在构造 self.response_planner.plan(...) 的 coroutine **之前**调用 block_or_terminate(decision)，无条件阻断 gated NoGrant |
| 同上 | _close_turn 306–321、_fail_stage 393–409 | 共享 idempotent terminalization helper，防重复 TURN_END；error path 使用同一 owner |
| runtime/orchestration/m2_runtime.py | run 第 60/62 行 | 与上述同构 origin、handle、outer try/finally |
| 同上 | RESULT_VALIDATE 183–191 | 与上述同构 gated branch，不重算 M2 priority/policy |
| 同上 | RESPONSE_PLAN 193 起 | 同位置阻断，M7/M8 零调用 |
| 同上 | _close_turn(SUCCESS) 237 | only legacy-compatible success；gated deny-only 不可能到达 success |

注意 _run_stage 的 awaitable 参数要保持 await ValidatedResult 的语义；可由 handle.validate 返回 private wrapper，在本地保存决策后提供返回 Canonical 的 coroutine adapter，**不能**把 wrapper 作为新增 Canonical、改变公开 Stage 接口或把 gate 当新第 16 stage。该适配器的闭包取值、异常时 decision 缺失处理需实施前精确化。

## B2-B03 — Trace 单次终态、取消及资源释放

TraceStatus 仅 RUNNING / SUCCESS / ERROR，**没有 CANCELLED**。取消映射现有 ERROR + internal reason TURN_CANCELLED，再原样 re-raise asyncio.CancelledError；不得私造公共枚举。

共同内部 helper: finish_turn_once(turn_context, status: TraceStatus, reason_code: str | None) -> bool。以 finished_at is None 且 status RUNNING 作为唯一可关闭条件；首次设置 finished_at、status、错误 reason 并记录 TURN_END，之后再调用必然 no-op；不覆写先前错误或成功。当前 _close_turn 无幂等校验，需调整调用统一 helper。错误日志失败时不能生成 success 输出；日志是否 throw 的兼容策略要求实测。

两条 run 外层 lifecycle：
1. Origin 严格校验；_open_turn；创建 handle（若失败仍终结 Trace）。
2. try 包围 INPUT 至最终返回；_run_stage 内部错误先由 _fail_stage 收口，外层 except 只执行 finish_turn_once（幂等）；M6 阶段间 BLOCK 明确终结 ERROR 并抛 typed NO_GRANT_DOWNSTREAM_BLOCKED。
3. except asyncio.CancelledError: finish_turn_once(ERROR, TURN_CANCELLED); raise。
4. except BaseException: finish_turn_once(ERROR, reason) unless already finished; raise 原异常。
5. finally: handle.close（或未创建则 skip）；如 close 抛错，保留原始异常优先级，记录无敏感信息的 cleanup 错误；绝不调用 M7/M8。
6. 并发每轮使用局部 handle/trace；共享 last_trace 是观测 latest 状态，不能作为 per-turn 真值。

**仍需冻结**：原 _run_stage 对 Exception 与 ValidationError 的包装、同步 _emit_log 失败、_open_turn 失败、close 出错与原异常优先级的精确 Python 实现；这些是 B2-B03 对实施授权的剩余阻塞，不得因伪代码存在而认定已解除。

## B2-B04 — Gated 模式/正常业务可用性

严格 DENY_ONLY_GATED 模式没有 B3 正向授权，因此不会产出正常成功回复，也不会执行 M8 更新；不可作为无提示的默认生产切换。应用选择、配置来源、非受保护 legacy runner 的运行环境标签、灰度/回滚、运维可见性须另设 Deployment Decision；在此之前不允许将 LEGACY_TEST_COMPAT 当作生产可信验证。任何缺少 gate/handle/policy 的错误在受保护模式均 **FAIL_CLOSED**，绝不自动回退。

## E01–E14：证据与 exact files

将 E01–E14（两条 run 零 M7/M8 调用、输入改写、伪造来源、缺失依赖、单次终态、阶段间 Block、取消、并发隔离、B0 一次性、正向假凭据、15 stage regression、源码四门禁、合并后 main 门禁）作为独立实施验收；记录每一项 source SHA、trace 与调用计数，绝不能拿 B1b-P 的 1092 passed 替代物理链测试。

候选允许范围（**仅设计，不是实际授权**）：新增 runtime/validation/m6_no_grant_facade.py、runtime/orchestration/m6_terminalization.py、tests/test_m6_iu1_b2_dual_runtime.py；修改 runtime/orchestration/runtime.py 和 runtime/orchestration/m2_runtime.py。没有批准改动 runtime/contracts/**、runtime/interfaces/**、Slice A/B0/B1a/B1b-P，或 M2/M4/M5/M7/M8。

## 当前设计门禁

B2-B01：TARGETED_DESIGN_SPECIFIED，须验证输入校验与生命周期精确点。
B2-B02：PARTIAL，constructor 默认、适配器闭包和旧测试兼容未冻结。
B2-B03：PARTIAL，日志/cleanup 异常及 stage 包装优先级待 exact-code。
B2-B04：TARGETED_DESIGN_SPECIFIED，部署授权另行决策。
E01–E14：NOT_RUN。
**B1b-E/B2 实施就绪：NOT_READY；正式实施授权：NOT_GRANTED。**
