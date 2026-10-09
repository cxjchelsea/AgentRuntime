# M6-IU1 Slice B1b — Minimal Contract Precision Amendment R-B1b-06/07 V0.3

**性质**：仅修订 B1b-P 纯策略接口精度；不是 implementation authorization。**承接**：B1b V0.1、V0.2 和 V0.2 Targeted Independent Design Re-Review。**冻结实现基线**：`main@1c0f68bdb4fd188e32b9fb22aa5424117e1fa881`。**设计父 HEAD**：`03696830f8a8db6ae47aa2fe00c051a67ad1e7cc`。

## 0. 不变量

1. B1b-P 纯策略 **没有 ALLOW 返回分支**，对任何可构造的输入均不能授权调用 M7/M8、生成正向事实、文本或写入状态。
2. B1b-P **不能认证 origin**。输入即使声称 `NO_GRANT_INTERNAL`，也不代表经过验证的 B0 Slot、B1a 投影调用或可信 RuntimeInput。
3. 保留 B1b V0.2 两级证据：P01–P08 为纯策略测试；E01–E08 属于 B1b-E/B2，不可由纯策略测试替代。
4. 当前不引入 Domain 枚举、M7/M8 注入、公共 Canonical 修改、持久化记录、Grant Producer 或 Orchestrator 接线。

## 1. R-B1b-06：唯一错误契约、返回形态与优先级

### 1.1 明确选择

- **已正确构造的两份 exact-type 输入**：只返回不可变 `NoGrantDownstreamDecision`，`disposition=BLOCK_BEFORE_M7_M8`；输入之间即使冲突、包含正向业务宣称，也仍然是 BLOCK，不抛出可被消费者误当作“未触发保护”的异常。
- **对象类型错误、缺失、非法 DTO 构造**：抛出内部 `NoGrantDownstreamError`（typed fail-closed），**不返回决策**；调用者不得通过 `except` 路径回退到旧 Validator 或跳过保护。该异常不是 Canonical，也不能被当作成功或中性用户回复。
- DTO 构造时的字段级错误必须抛出同一类内部异常，保持可观测的 stable error code。纯策略的原始异常不得泄漏为 `AttributeError`、`KeyError` 或静默 `ALLOW`。

### 1.2 返回对象冻结结构

```text
NoGrantDownstreamDisposition = BLOCK_BEFORE_M7_M8
NoGrantOriginClassification = NO_GRANT_INTERNAL | UNATTESTED_UNKNOWN

NoGrantDownstreamReason:
  NO_AUTHORIZED_VALIDATION_GRANT
  AUTHORITY_UNATTESTED
  CORRELATION_MISMATCH
  CANONICAL_MISMATCH

NoGrantDownstreamErrorCode:
  INVALID_CONTEXT
  INVALID_VALIDATED_RESULT
  INVALID_CONTEXT_FIELD

NoGrantDownstreamDecision (frozen internal dataclass):
  disposition = BLOCK_BEFORE_M7_M8
  reason: NoGrantDownstreamReason
  origin_classification: NoGrantOriginClassification
  may_call_response_planner = False
  may_call_response_generator = False
  may_call_response_validator = False
  may_call_state_memory_updater = False
  may_emit_positive_claim = False
  may_commit_business_or_memory = False
  allowed_user_response = NONE
  request_id, execution_id, validation_id: str | None  # diagnostic-only, see 1.4
```

`NoGrantDownstreamDecision` 的所有控制布尔值和 disposition 只能具有以上固定值；不能接受调用者提供 `allow=True` 等参数，也不提供 `authorize()` 方法。

### 1.3 精确优先级（first match wins）

| 顺序 | 触发条件 | 输出 |
|---|---|---|
| 0 | `context` 非 exact `NoGrantDownstreamContext`（含 None），或 `validated` 非 `ValidatedResult`（含 None） | typed `NoGrantDownstreamError(INVALID_CONTEXT / INVALID_VALIDATED_RESULT)`；如两者都错，先 CONTEXT |
| 1 | context 已构造但字段被运行时强行篡改为非法（含 provenance 非枚举或 structural_only 非 `True`） | typed `NoGrantDownstreamError(INVALID_CONTEXT_FIELD)` |
| 2 | request/execution/validation 任一 ID 不一致 | BLOCK + `CORRELATION_MISMATCH` |
| 3 | status 不严格为 `UNKNOWN/UNKNOWN`，或出现任何 `verified_facts`、`goal_validation`、`state_recommendation`、`claim_policy.allowed_claims` 非空，或 `claim_policy.conditional_claims` 非空 | BLOCK + `CANONICAL_MISMATCH` |
| 4 | `context.provenance_kind=UNATTESTED_UNKNOWN` | BLOCK + `AUTHORITY_UNATTESTED` |
| 5 | `context.provenance_kind=NO_GRANT_INTERNAL`，其余检查通过 | BLOCK + `NO_AUTHORIZED_VALIDATION_GRANT` |

**所有条件均不能产生 ALLOW。** `validation_errors` 等公开文本字段不用于判定来源、授权或错误优先级。若 Canonical 经非法低级篡改使其嵌套结构无法安全检查，按 `CANONICAL_MISMATCH` 阻断；不得传播未处理异常或默许通过。生产接口输入严格类型；不做字符串强制转换。

### 1.4 诊断关联 ID 使用规则

- 仅在 context 与 validated 均为合法对象、三个 ID 均是严格非空且完全一致时，返回 `request_id/execution_id/validation_id`。
- 若存在字段篡改、correlation mismatch、对象不合法，三项关联 ID 统一为 `None`；不得将攻击者提供的 ID 写入“已验证关联”日志。
- 即使 ID 完全一致，这些值也仅用于 diagnostics，不是 origin/Grant proof；不得复制原始用户输入、Prompt、医学个人信息到 reason/trace。

## 2. R-B1b-07：不可变 Context 字段与能力边界

### 2.1 类型冻结

```text
NoGrantDownstreamContext (frozen=True, slots=True):
  expected_request_id: str
  expected_execution_id: str
  expected_validation_id: str
  expected_identity_scope: str
  expected_session_id: str
  provenance_kind: NoGrantOriginClassification
  structural_only: Literal[True] = True
```

`provenance_kind` 必须是 **精确 Enum 实例**，不接受任意同值字符串；`structural_only` 必须为 `True` 且不得接受整数 `1`。五个 ID 均要求 `type(x) is str`、非空、无前后空格且不能只含空白；不进行 `strip()` 修正或宽松 coercion。字段非法在 `__post_init__` 内返回 typed `INVALID_CONTEXT_FIELD`，不产生 context。

### 2.2 Source correlation 能力边界

`ValidatedResult` 的主键只有 `request_id`、`execution_id`、`validation_id` 等字段，不承载 session 或 identity scope。因此 B1b-P 只能对 Context 自己的 `expected_session_id`、`expected_identity_scope` 检查类型和非空格式，**不能**声称将它们与 `ValidatedResult` 进行相等验证。它们与 `RuntimeInput`、`RuntimeContext`、`ExecutionResult` 的真实对应以及单轮所有权验证仅由未来 B2 完成。

无论 context 标为 `NO_GRANT_INTERNAL` 还是 `UNATTESTED_UNKNOWN`，B1b-P 的 disposition 都是 BLOCK；后者 reason 为 `AUTHORITY_UNATTESTED`，不能被条件式“兼容成功路径”覆盖。

### 2.3 错误测试的精确预期

| Oracle | 测试 |
|---|---|
| P01 | 正常 NoGrant + 完整一致三 ID -> BLOCK、固定全部 may=false、diagnostic ID 可用 |
| P02 | forged claims/verified facts -> CANONICAL_MISMATCH；伪造 validation_errors 不改变授权 |
| P03 | missing object/错误类型 -> typed error；非法 context 构造 -> INVALID_CONTEXT_FIELD；错误 ID -> CORRELATION_MISMATCH 且无 diagnostic IDs |
| P04 | VALIDATED/SUCCESS -> CANONICAL_MISMATCH；绝无 ALLOW |
| P05 | 伪造来源 Enum / 重复调用 -> BLOCK；不能证实 provenance 或 Slot |
| P06 | DTO/decision immutable；无外部生产模块、I/O、Registry、Tool 引用 |
| P07 | 错误先后顺序组合测试；所有下游控制 False，allowed_user_response=NONE |
| P08 | Exact implementation HEAD 四项门禁通过，独立审查另行裁决 |

## 3. 本版设计取舍与追踪

- `R-B1b-06`：已选择“合法对象总是 BLOCK decision；非法对象 typed exception；context-first、correlation-first 的确定性错误优先级”；没有无授权时的继续执行路径。
- `R-B1b-07`：已冻结所有 DTO 类型/不变量及 Session/Scope 只能做 structural validation 的限制。
- `B-B1b-02`：仍属 B2 双 Orchestrator 的异常终态与 finally 设计，不能因 B1b-P 的错误类型已明确而关闭。
- 上述修订仅补充精度，不改变 V0.2 的架构分层或 B1b-P 纯策略负向职责。

```text
B1b V0.3 MINIMAL CONTRACT PRECISION AMENDMENT = SUBMITTED
R-B1b-06/07 = SPECIFIED / INDEPENDENT REVIEW PENDING
B1b-P IMPLEMENTATION READINESS = NOT_GRANTED
B1b-P IMPLEMENTATION AUTHORIZATION = NOT_GRANTED
B1b-E / B2 IMPLEMENTATION AUTHORIZATION = NOT_GRANTED
B3 POSITIVE GRANT PRODUCER = BLOCKED
D-M6-IU1-01 = OPEN
NEXT = B1b-P Bounded Implementation Readiness & Authorization Review
```
