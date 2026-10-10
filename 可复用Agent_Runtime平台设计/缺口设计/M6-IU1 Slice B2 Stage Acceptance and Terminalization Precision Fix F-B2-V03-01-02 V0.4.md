# M6-IU1 Slice B2 — F-B2-V03-01/02 Stage-Acceptance & Terminalization Precision Fix V0.4

2026-10-09。**仅受控设计，非代码实施授权**。前置 V0.1–V0.3；设计父 HEAD 3d2efec4f91773cbb27d362d83eacd810ac75065；源代码基线 main@8cc64eec2a471d4c8e8de1a9545bb92d9afb7ba4。B1b-E/B2 尚未接入；D-M6-IU1-01 OPEN、B3 BLOCKED。

## F-B2-V03-01 — Stage 成功后才承认阻断决策

### 已核对源代码事实

当前 runtime/orchestration/runtime.py 的 _run_stage 在第 350–359 行 await + 类型 / invariant 校验，在第 376–390 行记录 SUCCESS、STAGE_END，至第 391 行才 return。因此由 adapter 预写的 decision_box **不是**已成功 stage 的授权证据。M2 继承相同的 _run_stage。原 RESULT_VALIDATE stage（runtime.py 231–239；m2_runtime.py 183–191）、返回的 ValidatedResult 类型与 15-stage 主链不可改。

### 冻结时序

1. 每次 run 自建局部、初始为空的 `decision_box: list[NoGrantDownstreamDecision]`；无实例属性、全局缓存、跨请求共享或 ContextVar；一个 Handle 仅一次 validate。
2. 仅在 DENY_ONLY_GATED 模式，RESULT_VALIDATE 的 awaited 私有桥接函数调用 Handle.validate，完成 B0/B1a/B1b-P 后将 decision 追加到本轮 box，再返回 **Canonical ValidatedResult**。
3. _run_stage 内部完成 await、输出类型验证、invariant 检查、成功 StageTrace 和 STAGE_END，且实际返回 ValidatedResult 后，才进入 **本轮门禁接受步骤**；任何早于该步的 decision_box 都不可使用、不可触发 allow/ResponsePlanner。
4. 接受步骤重新核对 `len(decision_box)==1`、exact decision 类型、disposition 为 BLOCK_BEFORE_M7_M8、六个 may_* 全 False、allowed_user_response == NONE、canonical result 三个关联 ID 与 origin/result/context 一致，以及 decision 三个诊断 ID 与 validated_result 一致。不要求它是一个外部真实性证明。缺失、污染、重复、错误类型、对象变化 => typed fail-closed；不进入 M7。
5. 完成接受步骤后，**在求值 `self.response_planner.plan(...)` 参数和创建 coroutine 之前**调用 private block_or_terminate；当前 NoGrant-only 没有任何成功分支；只能 ERROR + NO_GRANT_DOWNSTREAM_BLOCKED、raise typed block。
6. 如果桥接函数已预写 box 而 _run_stage 的类型/invariant/STAGE_END 失败，必须沿该失败终态收口并在 finally 清理，**不消费 box、不做第二次 validation、不产生成功**。不得允许一次 ResultValidation 错误被后续 decision 覆盖。
7. 既有 Legacy 测试路径保持独立，只有 `LEGACY_TEST_COMPAT` 才使用原三参 ResultValidator；生产组合根需具备明确显式 `DENY_ONLY_GATED` 断言和校验测试。无法声明“默认 legacy 但生产自动安全”；缺少/错误 factory 或模式必须 fail-closed。

**适配器示意（非可合并代码）**：

```python
decision_box: list[NoGrantDownstreamDecision] = []  # strictly run-local
validated_result = await self._run_stage(
    turn_context,
    "RESULT_VALIDATE",
    _validated_canonical_for_stage(handle, execution, context, approved, decision_box),
    ValidatedResult,
    input_contract_type="ExecutionResult",
)
# This line is only reachable AFTER _run_stage returned successfully.
decision = accept_stage_proven_no_grant_decision(
    decision_box, validated_result, origin_snapshot
)
block_or_terminate(decision)  # raises before even creating response_planner coroutine
```

**测试要求**：V4-A01 延迟/抛异常的 stage 不得让预写 box 生效；V4-A02 假造 status / malformed decision / 重复 box / ID mismatch 全 BLOCK；V4-A03 生产入口 legacy 默认或遗漏 factory 拒绝；V4-A04 两条 run 零 M7/M8、stage 顺序不新增第 16 stage。

## F-B2-V03-02 — Trace 错误先于日志，失败不覆盖主异常

### 已核对源代码事实

`_open_turn` 在建立 Trace 后调用 TURN_START 日志（runtime.py 292–304）；`_close_turn` 在设置 status/finished_at 后立即发 TURN_END（306–321）；`_run_stage` 阶段错误先 `_fail_stage`（360–374），`_fail_stage` 先关闭 turn，再写 STAGE_ERROR（393–417）。`_run_stage` 成功路径中的 STAGE_END 日志也可能抛同步异常且位于其 try/except 外（383–391）。TraceStatus 仅 RUNNING / SUCCESS / ERROR，绝无 CANCELLED。

### 冻结原子性规则

**first primary fault wins**，终态更改与日志发送解耦。私有 `finish_turn_once` 先同步完成内存 Trace 终态赋值，然后尝试发送一条 TURN_END，不能因 logger 抛错而再次终态化。

- `Trace RUNNING + finished_at is None`：可一次性同步设置 ERROR 或 SUCCESS、finished_at、首个 reason，然后发送 TURN_END；返回 true。**同一 turn 的并发安全**需要证明只有 run owner 串行执行终态入口，若允许并发调用则需同轮锁；不可仅凭 Python 赋值声称线程安全。
- `status in {ERROR,SUCCESS} + finished_at exists`：已关闭，不变更任何字段、不重复 TURN_END；返回 false。
- 半终态（RUNNING + finished_at 非空，或终态 + finished_at None）：**INCONSISTENT_TERMINAL_STATE**，保留已有证据，拒绝成功；不得强行补写一个 SUCCESS，也不得发第二个 TURN_END；是否将半终态原样上报及如何以内部异常表示需要与 API 错误语义一致，测试固定。
- `TURN_END` emit 失败：Trace 已关闭；记录只含 error_code/turn_id 的观测退化；不再 retry TURN_END（否则破坏“最多一次 attempt”），不允许返回表面成功。若已有 primary exception，则原样抛出 primary（日志错误附诊断而不覆盖）。
- `STAGE_ERROR` emit 失败：先设置 Stage ERROR、Trace ERROR 和原始异常的 trace_context，再做 best-effort 发日志；不能让日志异常覆盖原始 StageExecutionError / ContractValidationError。
- `STAGE_END` emit 失败：不能允许 _run_stage 返回正常结果而 Trace 仍 RUNNING；由外层捕获，按 `STAGE_LOG_FAILURE` fail closed，设置 ERROR。若业务阶段已有错误则保留业务错误优先。
- `TURN_START` emit 失败：TraceContext 已创建但 _open_turn 未返回，不能依靠运行者刚拿到的 turn_context；设计应在创建后、发日志之前将局部 turn_context 交还可收口的所有者，或者使用不会抛出的 safe logging wrapper，失败当作 `TURN_START_LOG_FAILURE` 并终结 Trace ERROR。不可宣称无 Trace 已创建。
- `handle.close()` 在 primary exception / cancellation 后失败：保留 primary/cancel，记录 cleanup_error，不做 M7/M8；close 为唯一异常则将尚未完成的 turn 终结 ERROR，并向上抛 typed `M6_CLEANUP_FAILURE`；不能继续成功返回。
- `asyncio.CancelledError` 在任一 awaited stage（尤其 M5/M6）出现时，外层显式捕获：finish_turn_once(ERROR, TURN_CANCELLED)，原样 re-raise；不借助 `except Exception`，finally 清理 handle。不能伪造 TraceStatus.CANCELLED。
- 外层 `except BaseException` 只用于可靠收口并 **裸 raise** 原异常，严禁转化 KeyboardInterrupt/SystemExit 为普通业务错误。异常发生在开启 turn 前则不制造虚假的 Trace。

### 精确顺序和日志行为

```text
stage failure
  -> StageEvent ERROR + original error code
  -> preserve original orchestration_error.trace_context
  -> finish_turn_once(ERROR, code): Trace state committed -> one TURN_END attempt
  -> one STAGE_ERROR attempt (both best-effort when primary exists)
  -> finally: close handle, do not mask primary
  -> raise original stage error
stage success but STAGE_END log failure
  -> outer guard marks Trace ERROR (not SUCCESS)
  -> finally closes slot
  -> raise typed logging failure
between-stage NoGrant block
  -> finish_turn_once(ERROR, NO_GRANT_DOWNSTREAM_BLOCKED)
  -> finally: close handle
  -> raise internal typed block
async cancellation
  -> finish_turn_once(ERROR, TURN_CANCELLED)
  -> finally: close handle
  -> re-raise same CancelledError
```

**关键顺序风险**：如果运行成功却在首次 TURN_END logging 时失败，不能先返回 `RuntimeTurnOutcome`。这意味着旧 `_close_turn` 的调用者需要识别终态日志失败并 fail closed；不得将它静默吞掉当成功。要验证 `_run_stage` 的 log_hook 不会在异常保护外导致未终结 Trace。

**验证矩阵增量**：V4-T01 单次 stage error + 双日志抛错，保留原异常与单次结束；T02 STAGE_END logger throw，最终 ERROR 无成功返回；T03 TURN_START logger throw，已创建 Trace 结束；T04 TURN_END throw 与 cleanup throw，主异常优先；T05 取消阶段和 interstage 均 Slot close；T06 半终态守卫；T07 重复 close 不覆写首个 reason/finished_at；T08 两条 Orchestrator 同一用例；T09 并发不同 turn 独立 Trace。

## Exact-diff 修订范围

仍以 V0.3 的五文件为 **候选唯一范围**：新增 `runtime/validation/m6_no_grant_facade.py`、`runtime/orchestration/m6_terminalization.py`、`tests/test_m6_iu1_b2_dual_runtime.py`；修改 `runtime/orchestration/runtime.py`、`runtime/orchestration/m2_runtime.py`。所有新错误类别、safe logger adapter、私有 stage acceptance helper 须落在这五个文件内。若需要第六文件或修改 public Canonical/接口，停止并重新审查，禁止暗中扩展授权。

## 裁决与下一 Gate

```text
F-B2-V03-01 = PRECISION_DESIGN_SUBMITTED / INDEPENDENT_REVIEW_PENDING
F-B2-V03-02 = PRECISION_DESIGN_SUBMITTED / INDEPENDENT_REVIEW_PENDING
R-B2-05/06 = AMENDED_V0.4 / NOT_YET_RE-FROZEN
R-B2-07 FIVE-FILE BOUNDARY = UNCHANGED
B1b-E / B2 IMPLEMENTATION READINESS = NOT_READY
B1b-E / B2 IMPLEMENTATION AUTHORIZATION = NOT_GRANTED
B3 POSITIVE GRANT = BLOCKED
D-M6-IU1-01 = OPEN
NEXT = V0.4 Independent Precision Re-Review and Implementation Readiness Re-Evaluation
```
