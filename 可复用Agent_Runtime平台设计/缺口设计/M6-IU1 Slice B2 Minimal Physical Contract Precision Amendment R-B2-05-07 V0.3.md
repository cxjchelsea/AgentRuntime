# M6-IU1 Slice B2 — Minimal Physical Contract Precision Amendment R-B2-05..07 V0.3

**日期**：2026-10-09。**性质**：受控设计修订；不是实施授权。**设计父 HEAD**：PR #82 @ 2dca959f60d9f709762cee42b18675e10ca2a964。**生产代码基线**：main@8cc64eec2a471d4c8e8de1a9545bb92d9afb7ba4。继承 B2 V0.1/V0.2；Slice A/B0/B1a/B1b-P 已合并，B1b-E/B2 未接线；D-M6-IU1-01 仍 OPEN，B3 blocked。

## 1. R-B2-05 — 精确 Facade / RESULT_VALIDATE 合同

### 1.1 唯一候选 Option A：本轮显式 Handle，不使用 side channel

冻结私有接口（示意类型，非公开 Canonical）：

- `TurnOriginSnapshot.from_runtime_input(raw: RuntimeInput)`：严格 exact type + request/session/identity_scope/trace_id 四字段的 exact 非空字符串校验；必须在 `_open_turn` 之前生成。只说明 run 入口捕获，不是外部身份认证。
- `M6NoGrantFacadeFactory.open_turn(origin: TurnOriginSnapshot) -> M6NoGrantTurnHandle`：每轮新建一个 B0 Slot、B1a Controller 和处理状态；不返回全局共享句柄。
- `M6NoGrantTurnHandle.validate(execution: ExecutionResult, context: RuntimeContext, approved: ApprovedActionPlan) -> M6NoGrantValidation`：每轮最多调用一次；内部 Slice A `admit_validation_input`，B0 `take_once`，B1a `project` 和 B1b-P `evaluate_no_grant_downstream`；失败不自动回退旧 Validator。
- `M6NoGrantValidation` 为冻结内部对象：`validated: ValidatedResult`、`decision: NoGrantDownstreamDecision`、`turn_identity: TurnOriginSnapshot`。不得成为 Canonical 或进入 M7/M8。
- `handle.close()`：废止 Slot 和绑定，必须可以在 finally 调用，不进行任何业务写入。

### 1.2 保留 _run_stage 的 Canonical 返回合同

两个 run 继续以 **原有 RESULT_VALIDATE stage** 调用 _run_stage，`expected_type=ValidatedResult` 不变。不能直接把 `M6NoGrantValidation` 交给 _run_stage。

冻结私有单轮桥接函数：

```python
async def _validated_canonical_for_stage(
    handle: M6NoGrantTurnHandle,
    execution: ExecutionResult,
    context: RuntimeContext,
    approved: ApprovedActionPlan,
    decision_box: list[NoGrantDownstreamDecision],
) -> ValidatedResult:
    validated_bundle = await handle.validate(execution, context, approved)
    if decision_box:
        raise M6InternalInvariantError("MULTIPLE_DECISIONS")
    decision_box.append(validated_bundle.decision)
    return validated_bundle.validated
```

- `decision_box` **仅在该次 run 的栈内创建**，禁止实例属性、ContextVar、跨轮缓存或可被外部传入。
- `_run_stage` 校验 Canonical 后、进入 `RESPONSE_PLAN` 的任何 coroutine 创建前，必须满足 `len(decision_box)==1`，且 Decision 为 exact class、block disposition、correlation ID 与当前 `validated_result` 一致，否则直接走 fail-closed 阻断终态。
- 如果 `handle.validate` 返回错误或 `_run_stage` 类型校验失败，`decision_box` 不能绕过错误继续运行。
- 必须处理 decision_box 在 `_run_stage` 成功前已赋值而 stage 后续失败的情况：即使已有 Decision，也不允许进入 M7/M8。
- 如要避免 list，可改用纯局部 typed holder，但只能在独立设计复审证实等价后更改，不能用共享实例字段替代。

### 1.3 构造器与兼容模式冻结

**建议 Mode**：`LEGACY_TEST_COMPAT` 和 `DENY_ONLY_GATED` 两个私有枚举值。旧实例化 API 的默认行为暂保留 `LEGACY_TEST_COMPAT`，只为现有测试及历史未保护路径兼容；**不得将该默认解释为生产安全保护**。受保护入口必须显式传 `mode=DENY_ONLY_GATED` 与 `m6_no_grant_facade_factory`；缺 factory 在构造期 fail closed（`DependencyMissingError`），严禁 run 时退回旧 Validator。

现有 14 个构造依赖及 public `ResultValidator.validate` 三参数签名不改。M2RuntimeOrchestrator 以 `**runtime_dependencies` 转发 mode/factory，禁止单独维护第二套配置语义。若需强制生产默认安全，属于另一个 **Deployment Gate**，不可用这次修改偷偷改变所有旧 runner 行为。

**未完全消除的部署风险**：如果应用仍用旧默认构造，依然不受 B2 保护。此设计只能作为 gated 内部路径，不能在没有部署验收时称为生产已保护。

## 2. R-B2-06 — Trace / exception / cancellation 的确定性优先级

### 2.1 共用终态函数

当前 TraceStatus 仅 `RUNNING/SUCCESS/ERROR`，没有 CANCELLED。冻结 `finish_turn_once(turn_context, status: TraceStatus, reason_code: str | None) -> bool`：

- 只有 `trace.status is RUNNING` 且 `finished_at is None` 才可第一次关闭；设置 terminal status、finished_at 和可选内部 reason，并发出最多一次 TURN_END。
- 已经结束时返回 False，绝不覆写首个终态的 finished_at/status/reason，不再发 TURN_END。
- 如果 status 与 finished_at 出现相互矛盾的半终态，fail-closed 记录内部 invariant fault，**不得改成 SUCCESS**；实施前需测试半终态异常与日志注入。
- 由共同 Orchestrator helper 管理；`_fail_stage` 仍负责 stage 错误信息，但调用同一 helper 收口，避免双 TURN_END。

### 2.2 本轮优先级矩阵（first fault wins）

| 触发事件 | Trace 终态 | 向调用方的异常 | Slot/资源 |
|---|---|---|---|
| 原始 RuntimeInput 非法，在 open 前 | 无 Trace 创建 | typed `M6_ORIGIN_INVALID` | 未创建则无需 close |
| `_open_turn` 中同步日志失败 | 不允许声称已有成功 Trace；若 turn_context 已可得则尽力 ERROR | 原日志错误（不得伪成功） | 未创建 handle 则无需 close |
| Stage 内普通异常经 `_run_stage` | ERROR、最多一次 TURN_END | 保留原 `StageExecutionError` / `ContractValidationError` | finally 关闭 |
| 处理后身份错配（阶段间） | ERROR、最多一次 TURN_END | typed `ORIGIN_CHANGED` | finally 关闭 |
| M6 B1b-P BLOCK（阶段间） | ERROR、reason `NO_GRANT_DOWNSTREAM_BLOCKED` | typed internal block | finally 关闭 |
| `asyncio.CancelledError` | ERROR、reason `TURN_CANCELLED` | 原样 re-raise CancelledError | finally 关闭 |
| `handle.close()` 在已有主异常后失败 | 原首个终态不变 | **原主异常优先**，清理错误只做内部安全日志 | 不执行回退/业务动作 |
| `handle.close()` 是唯一失败 | ERROR（若此前尚未关闭），禁止成功返回 | typed cleanup failure | fail-closed |
| `_emit_log` 在终态期间失败 | 不产生成功回包；尽力使 Trace 已记录 ERROR | 原主异常优先，日志失败记录可观测损失 | finally 尽力关闭 |

**强制顺序**：捕获主异常 / 取消 → 调用 finish_turn_once（允许重复、不能改写首个终态）→ finally 尝试 close → 重抛主异常。必须显式捕获 `asyncio.CancelledError`，不可用裸 `except Exception` 当作取消保障；也不建议无差别 swallow `BaseException`，保留 Python 的 KeyboardInterrupt/SystemExit 行为与资源清理。

**剩余评审焦点**：现有同步 `_emit_log` 如何在 Trace 写入与 TURN_END 之间失败，需要明确是否“标记终态先于 emit”；建议先修改 Trace，再以非覆盖主异常的方式记录日志，不能报告日志已成功。不可因为清理中的 `log_hook` 又失败就无限重试/重复终态。

### 2.3 不变量

- ERROR 的执行事实不能被伪造为业务 FAIL/SUCCESS；`RuntimeTurnOutcome` 不得在 BLOCK 时返回。
- `NoGrantTurnSlot.close` 具幂等性，但每轮只创建一个 Slot；跨轮不得复用。
- `self.last_trace` 仅 latest-turn 观测，不适合并发 trace 唯一性；验收以每轮 `turn_context.trace` 为准。

## 3. R-B2-07 — 五文件 Exact-Diff Inventory 与 E01–E14 归属

**冻结候选文件恰好五个**，以下“候选”不是本轮写代码授权。

| 文件 | 类型 | 严格改动边界 |
|---|---|---|
| `runtime/validation/m6_no_grant_facade.py` | NEW | OriginSnapshot、factory/handle、B0/B1a/B1b-P 顺序、run-local bundle、typed errors |
| `runtime/orchestration/m6_terminalization.py` | NEW | 共用 finish_turn_once、半终态检验和错误原因、安全日志逻辑 |
| `runtime/orchestration/runtime.py` | MODIFY | 新私有 mode/factory 注入，入口 Snapshot、stage adapter、pre-M7 gate、finally、旧 M0 接口兼容 |
| `runtime/orchestration/m2_runtime.py` | MODIFY | 同构 Facade/gate/outer lifecycle，不触动原 M2 policy 与优先级 |
| `tests/test_m6_iu1_b2_dual_runtime.py` | NEW | 双 runtime E01–E14 验证与失败注入 |

**禁止**修改 `runtime/contracts/**`、`runtime/interfaces/**`、A/B0/B1a/B1b-P 的已合入代码，或 M2/M4/M5/M7/M8；若实现发现必改第六个文件，必须停止并走受控变更。

### 验收项 → 文件矩阵

| Oracle | Facade | Terminalization | Runtime | M2 Runtime | Tests |
|---|---|---|---|---|---|
| E01/E02 双主链 NoGrant 零 M7/M8 | ✓ |  | ✓ | ✓ | ✓ |
| E03/E04 来源改写及身份篡改 | ✓ | ✓ | ✓ | ✓ | ✓ |
| E05 缺依赖，无 legacy fallback | ✓ |  | ✓ | ✓ | ✓ |
| E06/E07 Stage 异常及阶段间 BLOCK 单次终态 |  | ✓ | ✓ | ✓ | ✓ |
| E08 CancelledError 清理 | ✓ | ✓ | ✓ | ✓ | ✓ |
| E09 并发轮隔离 | ✓ | ✓ | ✓ | ✓ | ✓ |
| E10 Slot 一次性与关闭 | ✓ |  | ✓ | ✓ | ✓ |
| E11 伪造正向授权与遗留结果 | ✓ |  | ✓ | ✓ | ✓ |
| E12 既有 15-stage 及 ABI 回归 |  |  | ✓ | ✓ | ✓ |
| E13/E14 源 SHA / main 合并后四门禁 |  |  |  |  | ✓ / CI logs |

### 状态

```text
B2 R-B2-05..07 MINIMAL PRECISION AMENDMENT = SUBMITTED_V0.3
R-B2-05 PRIVATE ADAPTER & COMPAT MODE = SPECIFIED / RE-REVIEW_PENDING
R-B2-06 TERMINALIZATION PRIORITY = SPECIFIED / RE-REVIEW_PENDING
R-B2-07 FIVE-FILE DIFF & E01..E14 TRACE = SPECIFIED / RE-REVIEW_PENDING
B1b-E / B2 IMPLEMENTATION READINESS = NOT_GRANTED
B1b-E / B2 FORMAL IMPLEMENTATION AUTHORIZATION = NOT_GRANTED
B3 POSITIVE GRANT = BLOCKED
D-M6-IU1-01 = OPEN
NEXT = M6-IU1 Slice B2 V0.3 Targeted Independent Physical Design Re-Review
```
