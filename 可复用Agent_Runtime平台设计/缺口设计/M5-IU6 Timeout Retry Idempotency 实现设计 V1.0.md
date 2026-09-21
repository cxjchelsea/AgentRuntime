# M5-IU6 Timeout / Retry / Idempotency 实现设计 V1.0

> Baseline：M5-IU5 = PASSED。
> 对应 M5 主流程 Step 8：Timeout / Retry / Idempotency。
> 本设计先冻结 Reliability authority、attempt 模型、replay safety、timeout 与 idempotency 边界，不直接实现生产代码。

## 1. IU6 目标

~~~text
StepAttemptObservation
+ exact approved/resolved capability metadata
+ ExecutionContext / deadline
+ Reliability Policy
+ Idempotency / attempt history
        ↓
Reliability Decision
        ↓
受控 Tool / Step retry（仅在可证明安全时）
        ↓
新的 attempt evidence
        ↓
继续 RUNNING / WAITING / STOP / FINALIZE
~~~

核心不变量：

~~~text
Retry != generic loop
Timeout != Failed
Unknown side effect != safe to replay
Idempotency key != 每次 retry 新 key
Retry != Replan
Reliability != Capability substitution
~~~

## 2. 两层 Reliability

### 2.1 Tool Invocation Reliability

一次 logical Tool invocation 可以包含多个 physical Tool attempts。

~~~text
same approved tool_id + tool_version
same logical tool_call_id
same idempotency_key
physical attempt = 1,2,3...
~~~

Tool retry 必须发生在 CoreApprovedToolInvoker 内部，Skill / Workflow / Domain Tool adapter 不拥有 RetryPolicy 解释权。

### 2.2 Step Attempt Reliability

一次完整 Skill owner execution 是一个 Step attempt。

~~~text
StepAttemptObservation.attempt_number = 1,2,3...
~~~

Step retry 不得改变 ApprovedPlan、不重新 Planning、不替换 Capability。

第一版不允许自动重放 Workflow owner start，因为当前没有 durable workflow-start idempotency / recovery authority。

## 3. Typed Reliability Policy

现有 SkillDefinition / WorkflowDefinition / ToolDefinition 的 timeout_policy、retry_policy、idempotency_policy/idempotency_mode、side_effect_level 都仍是 str | None。

这些字段只能视为 policy reference / registered value，Core 不允许直接解释任意业务字符串。

因此新增注入式：

~~~text
ReliabilityPolicyResolver
~~~

建议冻结内部 typed policy：

~~~text
ResolvedTimeoutPolicy
- timeout_seconds

ResolvedRetryPolicy
- enabled
- max_attempts
- retry_on_statuses
- retry_on_error_codes
- backoff_seconds
- backoff_multiplier
- max_backoff_seconds

IdempotencyMode
- NATURAL
- KEY_BASED
- NON_IDEMPOTENT

SideEffectClass
- NONE
- LOW
- MEDIUM
- HIGH
~~~

Resolver 只能解释 exact resolved definition 上已经存在的 policy reference，不得 Registry discovery、Capability substitution 或 Domain hardcode。

作用域必须区分：

~~~text
ToolDefinition.retry_policy -> Tool physical-attempt policy
SkillDefinition.retry_policy -> Skill Step-attempt policy
Workflow owner -> 第一版不启用 auto-retry policy
~~~

同名 policy reference 在不同 capability kind 上也不得由 Core 假定同义；由 resolver 返回 typed policy。

## 4. Timeout Authority

IU6 必须区分：

~~~text
Tool Timeout
Step / owner Timeout
Execution / Plan Deadline
Workflow WAITING Timeout
~~~

Tool timeout 在 CoreApprovedToolInvoker 内执行，需要注入 AsyncTimeoutRunner。TIMEOUT != FAILED。

Execution / Plan deadline 直接来自 ExecutionContext.deadline。开始新的 physical Tool attempt 或 Step attempt 前必须检查 remaining budget；deadline 已过不得启动新的 side effect。

Step/owner timeout 来源于 exact Skill / Workflow definition 的 timeout policy。不能临时用 asyncio.wait_for 发明生产语义；必须有明确 timeout runner 和 side-effect uncertainty propagation。

Workflow WAITING duration timeout 不属于 IU6 第一版，继续留给 Workflow Persistence / Recovery，因此 TD-M5-IU5-02 暂不升级为 IU6 blocker。

## 5. Logical Tool Call / Physical Attempt

当前 IU4 固定：

~~~text
ToolInvocationRequest.attempt = 1
idempotency_key = None
~~~

这只适用于单次 invocation。

IU6 建议新增 ToolAttemptObservation：

~~~text
logical_tool_call_id
tool_id
tool_version
physical_attempt
idempotency_key
result
started_at
finished_at
~~~

同一个 logical Tool call 的 logical id 与 idempotency key 必须稳定，physical_attempt 单调递增。

计数语义正式区分：

~~~text
ToolInvocationRequest.attempt
= 当前 logical Tool call 内的 physical Tool attempt

StepAttemptObservation.attempt_number
= 当前 step_execution_id 的 Step attempt
~~~

二者不得混用。

## 6. Tool Journal Amendment

当前 ToolInvocationJournalEntry 只表达一份 raw/final result。若 retry 时简单追加多个旧 JournalEntry，会把一次 logical Tool call 错误表示成多次独立业务 Tool 调用。

因此建议 journal 改为：

~~~text
ToolInvocationJournalEntry
- logical_tool_call_id
- tool_id
- tool_version
- idempotency_key?
- attempts[]
- final_result
- permission / validation summary
~~~

Domain tool_results 仍只暴露 logical invocation 的 final result；physical attempts 只存在于 Core journal。

## 7. Retry Decision

新增：

~~~text
RetryDecisionStatus
- RETRY
- STOP
- WAIT
- UNKNOWN

RetryDecision
- status
- reason_codes
- next_attempt?
- backoff_seconds?
~~~

ResolvedRetryPolicy.max_attempts 冻结为：

~~~text
总尝试次数，包含第一次 attempt
~~~

例如 max_attempts = 3 表示最多 attempt 1 / 2 / 3，不表示“第一次 + 3 次 retry”。

只有同时满足以下条件才允许 RETRY：

~~~text
policy enabled
attempt < max_attempts
当前 status/error 命中 retry policy
deadline 仍允许
replay safety = SAFE
~~~

任一关键事实 UNKNOWN，不得默认 RETRY。

## 8. Replay Safety

新增 ReplaySafetyEvaluator，输出：

~~~text
SAFE
UNSAFE
UNKNOWN
~~~

NATURAL：可在 RetryPolicy 允许时重放。

KEY_BASED：首次 side effect 前必须 reserve idempotency key；所有 retry attempts 必须使用同一 key。IdempotencyStatus.UNKNOWN 时禁止盲目 replay。

NON_IDEMPOTENT：真实 invocation 已开始后默认 UNSAFE；第一版不发明“明确无 side effect occurred”的 adapter evidence。

## 9. Idempotency Key

新增 IdempotencyKeyFactory。Core 不硬编码哈希算法。

Key 至少要绑定可验证的 logical operation identity：

~~~text
execution_id
step_execution_id
tool_id
tool_version
logical_tool_call identity
normalized input fingerprint
~~~

同一次 logical call 的 retry 必须复用同一个 key。

## 10. Idempotency Store

现有 IdempotencyStore 的 get / reserve / mark_completed / mark_unknown 方向正确，但当前 IdempotencyRecord 缺少 tool_id、tool_version、operation_fingerprint，无法证明同一个 key 仍指向同一 Tool/version/input operation。

同时 COMPLETED 只有 result_reference，但没有 IdempotencyResultResolver 或等价 typed completed-result recovery contract。

冻结行为：

~~~text
RESERVED -> concurrent/in-flight；不得再次 invoke
COMPLETED -> 不再次 invoke；必须恢复可信 completed result
UNKNOWN -> 不再次 invoke；返回 UNKNOWN / recovery-required
~~~

## 11. Tool Retry Execution

流程：

~~~text
logical Tool call
↓
resolve typed reliability policy
↓
stable logical call / idempotency identity
↓
physical attempt N
↓
input validation
↓
permission re-check
↓
deadline admission
↓
idempotency preflight
  - first KEY_BASED attempt: reserve
  - later attempt: verify same existing reservation/provenance
  - COMPLETED: recover result, do not invoke
  - UNKNOWN: do not invoke
↓
timeout runner + exact Tool.invoke
↓
output validation
↓
update idempotency state when applicable
↓
append physical-attempt journal
↓
replay safety
↓
RetryDecision
↓
retry or return final logical Tool result
~~~

每个 physical retry 都必须重新检查当前 execution permission。

Idempotency reserve 绝不能早于 Input Validation / Permission / deadline admission。否则 INVALID_PARAMETER / PERMISSION_DENIED / 已过期 deadline 也会占住 key，而当前 Store 没有 release contract。

已有 COMPLETED record 的 result recovery 也必须在当前 Permission 仍允许的前提下返回，不能把 idempotency cache 变成绕过执行权限的旁路。

## 12. Step Attempt Retry

第一版只评估 Skill owner 的自动 Step replay。

Workflow owner 不自动重放。

Skill Step replay 只有在 StepReplaySafety = SAFE 时允许。只要存在 UNKNOWN Tool outcome、untrusted success、NON_IDEMPOTENT 已开始 side effect、idempotency UNKNOWN，就禁止自动 replay whole Skill。

## 13. Step Attempt Sequence

IU5 只记录 attempt_number，没有跨 attempt authority。

新增 StepAttemptSequenceAuthority：

~~~text
current_attempt(step_execution_id)
next_attempt(step_execution_id)
~~~

要求单调递增、不可重复、不得由 Domain 自报。

第一版允许 InMemory implementation 做机制测试；Crash recovery / durable history 仍属于后续 Persistence。

## 14. Step Reliability Decision

新增 StepReliabilityDisposition：

~~~text
RETRY
KEEP_RUNNING
WAIT_RECOVERY
FINALIZE
ABORT_UNKNOWN
~~~

基本规则：

~~~text
SUCCESS -> FINALIZE
FAILED / TIMEOUT -> safe+policy允许则 RETRY，否则 FINALIZE
WAITING / IN_PROGRESS -> KEEP_RUNNING
CANCELLED / PREEMPTED -> 不由 Retry 改写，交给 Step 9 Control/Finalization
~~~

PARTIAL_SUCCESS / BLOCKED / UNKNOWN / NO_EXTERNAL_EXECUTION 不能由 Core 临场压成现有 StepExecutionStatus。

## 15. Step Finalization

禁止：

~~~text
if unknown: finish_step(FAILED)
if no_external_execution: finish_step(SUCCESS)
~~~

新增 StepFinalizationEvaluator / StepFinalizationDecision。

只有 decision 明确给出 terminal StepExecutionStatus 时，execution coordinator 才能调用 ExecutionLifecycleService.finish_step。

Finalization evaluator 不解释 ActionStep.on_failure、fallback_plan、stop_conditions。

## 16. Timeout + Idempotency 不变量

~~~text
Tool timeout + NATURAL
→ 可继续按 RetryPolicy 评估

Tool timeout + KEY_BASED
→ 先进入 UNKNOWN/reconciliation；不得立即盲目 replay

Tool timeout + NON_IDEMPOTENT
→ UNSAFE；禁止自动 retry
~~~

## 17. Backoff / Time Source

Retry backoff 使用注入式 RetrySleeper / BackoffCalculator；如支持 jitter，必须注入 RetryJitterSource，Core 不直接使用全局 random。

所有 deadline / backoff timing 使用注入式 ExecutionClock，Reliability 核心不散落 datetime.now()/time.time()。

## 18. 第一版明确不做

~~~text
Workflow auto retry
Workflow WAITING timeout
Workflow resume
Crash Recovery
durable attempt history
Resource Lock
Cancellation / Preemption handler
Plan stop/fallback
Plan Aggregation
M6
~~~

## 19. Planned Tests

至少覆盖：opaque policy 不被直接解释、disabled retry、max_attempts 总次数语义、retryable/non-retryable、每 attempt permission re-check、INVALID/PERMISSION_DENIED 不 reserve key、deadline 过期不 reserve/不 invoke、NATURAL/KEY_BASED/NON_IDEMPOTENT replay safety、stable idempotency key、logical id stable、physical attempt 递增、journal attempt history、RESERVED/COMPLETED/UNKNOWN idempotency、COMPLETED recovery 仍受当前 Permission 约束、Tool timeout != FAILED、Skill replay safety、Workflow no auto-retry、Step attempt sequence、WAITING/IN_PROGRESS 不终态、UNKNOWN/PARTIAL_SUCCESS 不被猜测终态、IU6 不解释 on_failure/fallback、不进入 M6。

## 20. Controlled Amendment 预案

预计至少需要：

### CA-M5-IU6-01 Reliability Policy + Timeout / Replay Contracts

冻结 typed reliability policies、ReliabilityPolicyResolver、ExecutionClock、AsyncTimeoutRunner、RetrySleeper/Backoff、ReplaySafetyEvaluator、RetryDecision。

### CA-M5-IU6-02 Tool Attempt + Idempotency + Finalization Boundary

冻结 logical Tool call / physical attempt model、ToolAttemptObservation、Tool journal attempt history、IdempotencyKeyFactory、IdempotencyRecord provenance、completed-result recovery、StepAttemptSequenceAuthority、StepReliabilityDecision、StepFinalizationDecision。

两项 amendment 都不得修改 Canonical ApprovedActionPlan、PolicyDecision、ExecutionEngine frozen signature、RuntimeOrchestrator 或 M6。

## 21. 设计结论

~~~text
M5-IU6 IMPLEMENTATION DESIGN = COMPLETE
~~~

是否可实现以配套 Readiness Review 为准。