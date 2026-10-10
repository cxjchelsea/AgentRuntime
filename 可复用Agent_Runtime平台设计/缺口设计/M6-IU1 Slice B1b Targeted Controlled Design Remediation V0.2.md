# M6-IU1 Slice B1b — Targeted Controlled Design Remediation V0.2

**基线**：设计 PR #82 @ `b44ee6c626b20ad63b3ee9cd91ca7126b62de0bd`；生产 main @ `1c0f68bdb4fd188e32b9fb22aa5424117e1fa881`。**性质：仅受控设计整改，不是 implementation authorization。** 继承 B1b V0.1 `BLOCK_BEFORE_M7_M8` 默认阻断决策；本版逐项处理 B-B1b-01/02 和 R-B1b-03..05。B3/D-M6-IU1-01 仍阻塞。

## 1. B-B1b-01：精确来源交接与策略合同

### 1.1 分离来源证明和策略分类

**B1b-P 只作结构性防肯定判定，绝不颁发来源证明。** 真正的可信 RuntimeInput 捕获、B0 每轮消费与 B1a 调用事实，只能由将来经 B2 授权的 M6 facade / Orchestrator 生产接线持有和维护。不存在通过输入 `ValidatedResult`、公开 `validation_errors` 或提供某个字符串 token 就得到 ALLOW 的路径。

选用两个明确合同：

```text
NoGrantDownstreamContext (private immutable structural DTO):
  expected_request_id: nonblank str
  expected_execution_id: nonblank str
  expected_validation_id: nonblank str
  expected_identity_scope: nonblank str
  expected_session_id: nonblank str
  provenance_kind: NO_GRANT_INTERNAL | UNATTESTED_UNKNOWN
  structural_only: literal True

NoGrantDownstreamDecision (private immutable):
  disposition: BLOCK_BEFORE_M7_M8      # 唯一许可输出
  reason: NO_AUTHORIZED_VALIDATION_GRANT | AUTHORITY_UNATTESTED | INPUT_INVALID | CORRELATION_MISMATCH | CANONICAL_MISMATCH
  origin_classification: NO_GRANT_INTERNAL | UNATTESTED_UNKNOWN
  may_call_response_planner: false
  may_call_response_generator: false
  may_call_state_memory_updater: false
  may_emit_positive_claim: false
  may_commit_business_or_memory: false
  allowed_user_response: NONE
  request_id/execution_id/validation_id: correlation-only; not authority
```

**B1b-P callable** `evaluate_no_grant_downstream(*, validated: ValidatedResult, context: NoGrantDownstreamContext) -> NoGrantDownstreamDecision`。由 B1b-P 内部验证 exact types、所有字段非空且去首尾空格后不改变、两侧 request/execution/validation ID 完全匹配；`validated.validation_status is UNKNOWN`、`validated.business_status is UNKNOWN`、`verified_facts/goal_validation/state_recommendation` 均不包含肯定材料；必要时验证 claim policy 中无正向 claims。任何异常、缺失、篡改、来源不明、其他 status 均导致 **BLOCK**，不得返回 ALLOW。

输入 `context` 允许由独立测试直接构造；**此 DTO 不是证书，不证明私有调用源可信，且不能从其内容推断 B0 Slot 已消费。** `provenance_kind=NO_GRANT_INTERNAL` 的取值只是调用者传入的结构性分类，B1b-P 不得自行提升为经过认证的来源。未来 B2 才负责确保在同一 `run()` 的受控分支下创建，记录 B0 Slot take_once，投影 B1a 结果并绑定相同 request/execution/validation ID；对传入该接口的任意伪造上下文，B1b-P 仍唯一返回 BLOCK。

### 1.2 不可复用性边界

B1b-P 不提供 `issue_provenance`、`consume_once` 或运行时 replay lock，不维护可被误认为已认证来源的全局 registry；一轮一次的绑定与释放归属 B2 的 turn-local composition/finally。此时策略无论重复调用几次都返回阻断，不产生额外权利；因此在纯策略单元内不实现虚假“防重放证书”。

## 2. B-B1b-02：运行时阻断、错误 Trace 和收口顺序

在现有 `runtime/orchestration/runtime.py` 与 `runtime/orchestration/m2_runtime.py` 中，`_fail_stage` 仅由 `_run_stage` 执行失败分支触发；若直接在 `RESULT_VALIDATE` 后抛错，不会自动标记当前 Trace 的终态。B1b-P **不接触**运行时 Trace，只返回纯决策。

供 B2-E 精确设计冻结的执行序列：

1. 在当前 `run()` 建立 turn-local B0 Slot/controller/origin 资源，外层 `try/finally` 保证成功、普通异常与 `asyncio.CancelledError` 都关闭，`finally` 不把错误转成成功。
2. `RESULT_VALIDATE` 结束后立即对 `NoGrantDownstreamDecision` 做 M6 内部 gate 检查，检查发生在任何 `self.response_planner.plan(...)` 表达式求值之前。
3. 决策 BLOCK 时触发 **独立的 typed internal orchestration termination**（候选码 `NO_GRANT_DOWNSTREAM_BLOCKED`）；由 Orchestrator owner 在一个明确的错误闭环中将 Trace 标记 `ERROR`、附带 reason code、终止一次，禁止再进入 M7/M8；不得伪造 `RuntimeResponse`/`UpdateResult` 或 `TraceStatus.SUCCESS`。
4. 不能仅将 BLOCK 异常置于两次 `_run_stage` 中间而指望 `_fail_stage` 自动工作。B2 必须明确新增显式 terminalization helper 或包装为可追踪 M6 末端 gate（不得伪造额外顶层 stage）；需对重复 close、非 M6 异常、取消期间 Trace 写入失败逐项验证。
5. 在 `finally` 内关闭 B0 Slot、丢弃 per-turn 绑定/controller；清理失败不得覆盖原始 cause，也不允许把 UNKNOWN 记录成成功。Trace 异常关闭、取消和本轮资源释放的优先级及日志字段留在 B2 exact-diff 冻结。
6. 并发两轮不得共享 `NoGrantDownstreamContext`、B0 Slot、Controller ID set。B1b-P 作为纯函数可复用，但不得持有 turn-local authority。

**B-B1b-02 不宣称物理关闭完成。** 它只能在此确定强制要求；两条方法的实际 diff / cancellation semantics 是 B2 审查与实施门禁。

## 3. R-B1b-03：普通结果边界

定义完整决策空间为 `BLOCK` 或 `DEFER_TO_SEPARATE_AUTHORITY` 的体系架构，但 **B1b-P 自身唯一可返回 BLOCK**。普通 `VALIDATED`、`BusinessStatus.SUCCESS`、`allowed_claims` 非空，以及任意已通过传统验证的输入都 **不**由 B1b-P 返回 ALLOW，也不从 B1b-P 开启 legacy `ResultValidator` 回退。

当 B2 后续需要支持正常路径，必须另设已授权的 profile/grant authority 与显式策略分流、完整安全证据；当前 D-M6-IU1-01 OPEN，不可用 B1b 的 `NOT_NO_GRANT` 分支绕过。对 untagged UNKNOWN / status 不匹配的运行时输入，B1b-P 返回 BLOCK，宿主默认 fail-closed。回归测试只证明纯策略不会意外颁发 ALLOW，不宣称业务正常路径已恢复。

## 4. R-B1b-04：副作用与中性回复边界

B1b-E 的保护对象准确限定为此检查点**之后**触发的 `ResponsePlanner.plan`、`ResponseGenerator.generate`、`ResponseValidator.validate`、`StateMemoryUpdater.update` 及其经这些方法发起的后续动作。M5 在该保护点前已执行，无法由 B1b 撤销。其他未接线调用链、外部 telemetry/logging、网络/工具调用不能仅因 B1b-P 返回 BLOCK 而声称被阻止。

内部错误 Trace/必要的无敏感信息日志允许由 B2 owner 执行，但不得对外说“操作成功”。**SAFE_NEUTRAL_RESPONSE 仍是 DEFERRED / NOT_AUTHORIZED**；不能调用普通注入的 M7 Generator 伪装成已校验模板。B1b-P 不创建文本、TTS、通知、业务事件、持久化记录或 UpdateResult。

## 5. R-B1b-05：验证证据两层切分

### B1b-P 独立可实施纯单元 Oracle（待另行授权）
- P01 Valid B1a `UNKNOWN/UNKNOWN` + exact structural correlation → immutable `BLOCK_BEFORE_M7_M8`。
- P02 `allowed_claims=['success']`、伪造 `validation_errors` 或 `verified_facts` → typed no-authority BLOCK；无 ALLOW。
- P03 missing/invalid DTO、错 request/execution/validation、空白 identifier、scope/session → fail-closed BLOCK。
- P04 普通 VALIDATED / Business SUCCESS、unsupported status → BLOCK、无 legacy fallback/ALLOW。
- P05 重复调用同一个 DTO、伪造 `provenance_kind=NO_GRANT_INTERNAL` → 均只有 BLOCK；不声称验证来源。
- P06 结果和 context 不可变，NoGrant 模块不 import Orchestrator、M7/M8、Registry、Tools；没有 IO/副作用。
- P07 固定 `allowed_user_response=NONE`、全部 `may_*` 为 false；无 state writes、response 创建。
- P08 精确 HEAD pytest / mypy / ruff check / ruff format 全绿。

### B1b-E/B2 真实主链接入 Oracle（当前不授权）
- E01 双 `run()` 结果为 NoGrant 时，四个 M7 方法与 M8 Updater 均为 zero calls。
- E02 BLOCK 导致 Trace ERROR 且 exactly-once terminalization，不产生成功的 `RuntimeTurnOutcome`。
- E03 success/exception/cancellation/missing facade 全路径 B0 Slot close-once；cleanup 不覆盖原异常。
- E04 trusted RuntimeInput 捕获来源不由 downstream execution/context 派生；身份错配 fail-closed。
- E05 多轮并发隔离；旧 token 复用不授权；无 replay/positive claim。
- E06 既有 M0/M2 15 调用点顺序、不变量及旧 public ABI 不改变；受控迁移策略不可隐式 fallback。
- E07 B3 / 正常 Positive Grant 路径继续 BLOCKED，只有另行授权后才能独立验证。
- E08 合并后 main 精确 HEAD 四项门禁。

## 6. 修复追踪与待决

| Finding | 本版处理 | 仍需下一门禁 |
|---|---|---|
| B-B1b-01 | 冻结 DTO + 唯一 BLOCK 纯函数合同 + 真实性限制 | B1b-P targeted independent re-review |
| B-B1b-02 | 冻结 Trace ERROR + exactly-once + try/finally B2 义务 | B2 exact-method lifecycle design |
| R-B1b-03 | 所有非 NoGrant/positive 输入不得以 B1b-P 取得 ALLOW | B1b-P targeted independent re-review |
| R-B1b-04 | 精确列出 protected M7/M8 调用与保护时点 | B2 physical integration |
| R-B1b-05 | 纯策略 P01–08、主链 E01–08 分拆 | 后续分别取证 |

```text
B1b V0.2 TARGETED DESIGN REMEDIATION = SUBMITTED
B-B1b-01 = REMEDIATED_IN_DESIGN / RE-REVIEW_PENDING
B-B1b-02 = DESIGN_REQUIREMENT_SPECIFIED / B2_PHYSICAL_REVIEW_PENDING
R-B1b-03..05 = REMEDIATED_IN_DESIGN / RE-REVIEW_PENDING
B1b-P IMPLEMENTATION READINESS = NOT_GRANTED
B1b-E / B2 IMPLEMENTATION = NOT_AUTHORIZED
B3 POSITIVE GRANT = BLOCKED
D-M6-IU1-01 = OPEN
NEXT = B1b V0.2 Targeted Independent Design Re-Review
```
