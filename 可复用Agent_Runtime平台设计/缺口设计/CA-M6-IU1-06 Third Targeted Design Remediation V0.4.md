# CA-M6-IU1-06 Third Targeted Design Remediation V0.4

**状态：设计修复候选；必须独立复审。** 基线 main `88d3831270c56331af899e74d0c595ba1793d69d`；前次 PR #82 HEAD `ecd3b9aebb7216634f44435a946fdf8e6ee39d72`。本修订仅覆盖 RR2-01 和 RR2-02；V0.3 中 M4 快照完全一致、无新增存储/签名服务、无 Agent Loop 等约束继续生效。

## A. RR2-01：M2 授权意图必须先产生，M4 只能缩小范围

### A1. 精确时序与接口边界

现行主链调用为 `policy_engine.evaluate(runtime_context,understanding_state,deep_safety)` → `planner.plan(...,policy_decision)` → `policy_rechecker.recheck(validated_draft,policy_decision)`。不改三者现有签名和返回 Canonical 类型。

仅在受控 Orchestrator 集成补丁中引入一个**可选、只在该轮运行的** `ValidationProfileIntentSource`：
```python
class ValidationProfileIntentSource(Protocol):
    async def capture_at_policy(
        self, *, policy_decision: PolicyDecision,
        runtime_input: RuntimeInput, runtime_context: RuntimeContext,
        turn_nonce: str
    ) -> "ProfileIntent | NoGrant": ...
```
严格在 `POLICY` 阶段产出且经原主链合同检查成功**之后、PLAN 阶段开始之前**调用。它只能根据该次已完成的 M2 Decision、经过可信 Runtime 上下文绑定的 Domain 授权规则快照选择意图；不得重新执行 M2、改变 Decision、决定未来 plan_id、执行 Tool 或依据后续执行结果追补权限。

`ProfileIntent` 仅声明：`intent_version, policy_decision_id, policy_digest, request_id, identity_scope, session_id, domain_id, exact_profile_id/version/digest, permitted_goal_types/tool_refs, validation_mode_floor, turn_nonce, origin_proof`。不得包含未来 `plan_id` 或未经确认的具体 `goal_id`；`NoGrant` 是默认值。规范化不可变快照在采集阶段即固定；如果来源缺失、不可鉴别或发生超时则 `NoGrant`。

**授权来源要求：** `capture_at_policy` 只能消费由组合根预先装配、带 M2 Policy 决策来源证明的受信任 Profile 授权规则提供者；仅有 `PolicyDecision.validation_mode` 不能派生 Profile 权限。Domain Registry 存在内容不等于授权。原始 `PolicyDecision` 未携带 Profile 权限，因此真正的授权生产者是一个**待单独批准并实现的 M2 关联扩展**，不是已经存在的生产能力。未完成时，不得用测试假对象把正式环境默认为有授权。

`POLICY_RECHECK` 成功并保持 `approved.policy_snapshot == policy_decision.model_dump(mode="json")` 后，只调用已审定 `PlanGrantBinder.bind(intent, approved_plan, runtime_input, runtime_context, turn_nonce)`，把请求级意图与实际 `plan_id, request_id, approved_goal_ids, approved_step/tool_refs` 相交并校验，绝不能扩大原有 `permitted_goal_types/tool_refs`；规则授权不可更改已有 Tool 执行权限。意图为空时即 NoGrant，不允许此时新选择 Profile。此绑定端口也必须来自相同受信任的组合根，且不得修改 ApprovedActionPlan。

### A2. 身份和生命周期一致性

采用 `RuntimeInput.request_id/session_id`、`RuntimeContext.identity_context.identity_scope` 与 `RuntimeContext.session_context.session_id` 作为请求、Scope、会话上下文的原始输入。每阶段均校验这些值与对应 Plan/Execution 身份相等；`PolicyDecision` 自身不被假设具有 request/scope 字段。跨轮 `turn_nonce` 仅是本轮关联符，不充当认证或授权源；可信生产者实例和严格调用顺序才是内部信任根。所有输入是相同轮次的防御性不可变快照。

任何 M2 Intent 缺失、跨 scope、过时、更改 profile digest、绑定失败，必须 `NoGrant`；再次尝试不能在 M4 之后补发新 M2 Intent。重放时没有原有已验证 Intent/Grant 快照则 `NoGrant`，不允许重新查询“最新”。

## B. RR2-02：M6 per-turn adapter 完整消费协议

### B1. 显式内部接口

现有公开 `ResultValidator.validate(execution_result,runtime_context,approved_action_plan)->ValidatedResult` 保持不变。实现新增**内部非 Canonical**只读扩展：

```python
class GrantAwareValidationCore(Protocol):
    async def validate_bound(
        self, execution_result: ExecutionResult,
        runtime_context: RuntimeContext,
        approved_action_plan: ApprovedActionPlan,
        *, grant: "VerifiedGrant | NoGrant",
    ) -> ValidatedResult: ...

class PerTurnResultValidator(ResultValidator):
    def __init__(self, core: GrantAwareValidationCore,
                 grant: "VerifiedGrant | NoGrant",
                 immutable_turn_binding: "TurnBinding"): ...
    async def validate(self, execution_result, runtime_context,
                       approved_action_plan) -> ValidatedResult: ...
    def close(self) -> None: ...
```

一个 `PerTurnResultValidator` 是单次 `RESULT_VALIDATE` 调用使用的 facade；其 `core` 仅可持有无轮次可变状态的验证规则服务。传入的 `grant` / `TurnBinding` 为防御性不可变值，不能写入共享 `self.result_validator`。由明确命名的 `PerTurnValidatorFactory` 对**被审定的 `GrantAwareValidationCore` 实现**生成 facade；对普通旧版 `ResultValidator` 禁止悄然注入授权对象。

### B2. NO_GRANT 的安全语义（不得绕过）

- 缺少真实授权生产者 / `NoGrant`：调用**只允许生成无肯定性结论的受限 M6 实现**。它可对可靠的合同输入返回 `UNKNOWN/NOT_VALIDATED` 与 `BusinessStatus.UNKNOWN`、空 `allowed_claims`，但不得使用 Domain 验证规则判断 Goal SUCCESS、VerifiedFact 或通过普通旧版 Validator 偷渡肯定声明。是否能构造有效的 canonical `ValidatedResult` 仍受必填 ID、`ClaimPolicy` 和 Trace 约束；输入本身不合法必须按 IU1 Admission REJECTED 错误路径，不伪造结果。
- 有 `VerifiedGrant`：调用只读 `GrantAwareValidationCore.validate_bound(..., grant=...) `；这仍**只赋予规则解释权限**，不能凭 Grant 单独宣称业务成功，必须通过后续 IU2–IU7 的实证验证及 IU6 ClaimPolicy。
- 若系统装配的是 legacy `ResultValidator` 且未证实其输出会被可靠限制，**在需要授权 Profile 的路径不得委托它执行肯定性验证**；适配器应拒绝绑定或使用受限结果生成器。在旧版普通通道中只有独立审定不依赖 Profile 的安全验证才可运行，不能当成 M6 Domain 成功。
- 共享 Core 不得暴露 `set_grant`、全局 current-grant、ContextVar 或 mutable user session 字段。每轮 facade 私有值，异步并发与取消均不得读取其他轮次的权限。

### B3. Orchestrator 集成时序与异常边界

```text
POLICY result verified
  -> capture_at_policy (local immutable ProfileIntent / NoGrant)
  -> PLAN -> PLAN_VALIDATE -> POLICY_RECHECK (existing frozen semantics)
  -> bind(intention, exact approved plan) [local GrantCandidate / NoGrant]
  -> EXECUTE (same approved plan, untouched)
  -> validate grant correlation + execution identity
  -> PerTurnValidatorFactory.create(VerifiedGrant|NoGrant)
  -> RESULT_VALIDATE via existing 3-arg .validate()
  -> facade.close() in finally
```

`capture_at_policy`、`bind`、`verify`、`facade.close` 失败不可重新调用 M2/M4 或临时选择 Profile；返回 `NoGrant` 或走 Orchestrator 既有安全异常出口。不因未授权允许继续成功声明。以上新增内部调用仍需单独审定 Orchestrator 受控 diff 与异常语义；不额外引入新主链 stage 类型、不改变原 `_run_stage` 预期 `ValidatedResult` 类型检查。使用 `try/finally` 控制 facade 生命周期；取消后不可复用该 facade，`close()` 后任何 `validate` 调用必须拒绝。为避免“释放本地变量就安全”的错误假设，取消时显式令 facade 失效；即便第三方仍持有其引用，也不能再次消费。

### B4. 具体失败测试 Oracle

| ID | 场景 | 必须成立 |
|---|---|---|
| A01 | `POLICY` 完成后无 M2 profile authority | Intent=NoGrant；不从 `validation_mode` 自行授权 |
| A02 | M4 审批结束后尝试新建 Intent | 拒绝，Binder 不选择任何新 Profile |
| A03 | M2 Intent 与已批准 plan 的 goal/tool 不兼容 | NoGrant，不扩大 scope |
| A04 | M4 snapshot 与 PolicyDecision 不等 | 原审批失败，不触发 binder |
| A05 | 请求 / Scope / Session / Turn nonce 不一致 | NoGrant，无跨轮读取 |
| A06 | 旧版 `PolicyRechecker.recheck` / M6 `ResultValidator.validate` 签名 | 保持不变 |
| B01 | 无 Grant + Tool SUCCESS | M6 不给 Goal SUCCESS、VerifiedFact 或 positive claim |
| B02 | legacy Validator 会产肯定性输出 | 在需 Profile 路径上禁止未经审定的委托 |
| B03 | VerifiedGrant 但无业务证据 | 不能产生 Goal SUCCESS |
| B04 | 同 Orchestrator 并发两轮 | 两个 Facade 独立，权限不串扰 |
| B05 | Cancel/Exception | facade 显式失效，不能再次使用 |
| B06 | 原有 Grant Snapshot 丢失的 replay | NoGrant，不能用最新补授权 |
| B07 | `close()` 后重复调用 validate | 明确拒绝 |
| B08 | M6 返回不符合 Canonical 合同 | `_run_stage` 维持原有类型/安全异常边界 |

## C. 变更范围与实现授权边界

允许提出的后续代码范围仅限：可选 M2 关联 Intent Source 的明确接入点、现有 Orchestrator 的局部绑定顺序、M4 成功之后的 Scope-narrowing Binder、M6 单轮只读 Facade/Factory及其测试。不得修改 `PolicyDecision` / `ApprovedActionPlan` / `ValidatedResult` Canonical 结构，不得修改 M4 exact snapshot equality，不得增加新的 M5 执行控制、签名数据库、Grant Store、长期记忆或 Agent Loop Controller。

**仍然开放的真实依赖：** 受信任的 M2 Profile 授权 Intent 生产者不存在已证实的现成实现；这份文档定义何时何处必须生产及证明，而非把它宣称已上线。因此整个 IU1 Slice B 只有在独立复审、实施就绪评估和授权后才能开始编码。

```text
CA-M6-IU1-06 THIRD TARGETED DESIGN REMEDIATION = SUBMITTED_V0.4
RR2-01 TEMPORAL AUTHORIZATION = DESIGN ADDRESSED
RR2-02 PER-TURN VALIDATOR = DESIGN ADDRESSED
D-M6-IU1-01 = OPEN / PRODUCER INTEGRATION DEPENDENCY
CA-M6-IU1-06 THIRD TARGETED INDEPENDENT DESIGN RE-REVIEW = PENDING
M6-IU1 DESIGN FREEZE = NOT_APPROVED
M6-IU1 IMPLEMENTATION AUTHORIZATION = NOT_GRANTED
```
