# M5-IU6 Implementation Readiness Review V1.0

> Review target：M5-IU6 Timeout / Retry / Idempotency。
> Baseline：M5-IU5 = PASSED。
> 本 Review 只判断是否已具备安全进入 IU6 Formal Implementation 的前置合同，不实现 Reliability 代码。

## 1. Readiness 结论

~~~text
M5-IU6 IMPLEMENTATION DESIGN = COMPLETE
M5-IU6 IMPLEMENTATION READINESS = NOT_READY

BLOCKERS = 5
PRODUCTION IMPLEMENTATION = NOT AUTHORIZED
~~~

原因不是 M5 缺少“重试循环”，而是当前 frozen runtime 仍无法无歧义表达安全 retry / timeout / idempotency。

## 2. B-M5-IU6-001 RELIABILITY_POLICY_AND_TIMEOUT_RUNTIME_CONTRACT_MISSING

现有 Registry metadata：

~~~text
timeout_policy
retry_policy
idempotency_policy / idempotency_mode
side_effect_level
~~~

仍是开放 string reference。

Core 当前没有已落地的 typed：

~~~text
ReliabilityPolicyResolver
ResolvedTimeoutPolicy
ResolvedRetryPolicy
ResolvedIdempotencyPolicy
ReplaySafetyEvaluator
RetryDecision
ExecutionClock
AsyncTimeoutRunner
RetrySleeper / BackoffCalculator
~~~

如果直接实现，只能由开发者临场解释业务字符串、直接调用 wall-clock / asyncio timeout，违反 Core/Domain 边界。

结论：

~~~text
B-M5-IU6-001 = OPEN
REQUIRES CA-M5-IU6-01
~~~

## 3. B-M5-IU6-002 IU4_TOOL_INVOCATION_IS_SINGLE_ATTEMPT_ONLY

当前 CoreApprovedToolInvoker 冻结：

~~~text
ToolInvocationRequest.attempt = 1
idempotency_key = None
~~~

当前 ToolInvocationJournalEntry 也只表达一次 logical invocation 的单份 raw/final result。

若直接在外层循环 Tool invoke，会破坏：

~~~text
logical call identity
Domain tool_results == logical final results
Core journal truth
idempotency key stability
permission-per-physical-attempt evidence
~~~

因此 IU4 frozen invocation boundary 必须 Controlled Amendment，正式区分 logical Tool call 与 physical attempts。

结论：

~~~text
B-M5-IU6-002 = OPEN
REQUIRES CA-M5-IU6-02
~~~

## 4. B-M5-IU6-003 IDEMPOTENCY_PROVENANCE_AND_RESULT_RECOVERY_INCOMPLETE

现有 IdempotencyStore 接口方向正确，但 IdempotencyRecord 当前只包含：

~~~text
key
execution_id
step_id
status
tool_call_id?
result_reference?
~~~

缺少：

~~~text
step_execution_id
tool_id
tool_version
operation_fingerprint
~~~

因此无法验证同一个 key 是否仍指向同一 exact Tool/version/input operation。

同时：

~~~text
COMPLETED + result_reference
~~~

没有对应 IdempotencyResultResolver / typed result recovery contract。

若发现已有 COMPLETED key，当前无法既“不重复 invoke”又“恢复可信结果”。

结论：

~~~text
B-M5-IU6-003 = OPEN
REQUIRES CA-M5-IU6-02
~~~

## 5. B-M5-IU6-004 STEP_ATTEMPT_SEQUENCE_AUTHORITY_MISSING

IU5 已冻结 attempt_number，但只负责单次 observation。

当前没有 component 拥有：

~~~text
同一 step_execution_id 当前 attempt 是多少
next attempt 是否唯一
跨 retry 是否单调递增
max_attempts 计数 authority
~~~

如果在 retry loop 内用局部变量临时计数，会把 attempt authority 隐含在某个实现中，也无法与后续 persistence/recovery 对齐。

因此 TD-M5-IU5-04 在 IU6 正式升级为 blocker。

结论：

~~~text
TD-M5-IU5-04 -> B-M5-IU6-004
B-M5-IU6-004 = OPEN
REQUIRES CA-M5-IU6-02
~~~

## 6. B-M5-IU6-005 STEP_FINALIZATION_AUTHORITY_NOT_FROZEN

IU5 故意没有把：

~~~text
PARTIAL_SUCCESS
BLOCKED
UNKNOWN
NO_EXTERNAL_EXECUTION
~~~

压成 StepExecutionStatus。

当前仍没有可信 authority 决定：

~~~text
这些 observation 是否 terminal
若 terminal 应映射成什么 StepExecutionStatus
何时才允许 finish_step
~~~

禁止临时规则：

~~~text
UNKNOWN -> FAILED
BLOCKED -> FAILED
NO_EXTERNAL_EXECUTION -> SUCCESS
PARTIAL_SUCCESS -> SUCCESS
~~~

因此 TD-M5-IU5-01 在 IU6 正式升级为 blocker。

结论：

~~~text
TD-M5-IU5-01 -> B-M5-IU6-005
B-M5-IU6-005 = OPEN
REQUIRES CA-M5-IU6-02
~~~

## 7. TD-M5-IU5-03 Replay Safety 状态

TD-M5-IU5-03 在 IU6 已经进入 blocking path，但其缺口被 B-M5-IU6-001 / 002 / 003 共同覆盖：

~~~text
typed replay-safety policy
logical/physical attempt evidence
idempotency provenance / recovery
~~~

因此不再额外创建重复 blocker 编号。

## 8. TD-M5-IU5-02 Workflow WAITING Durability

该项继续保持非阻塞：

~~~text
TD-M5-IU5-02 WORKFLOW_WAITING_DURABILITY_DEFERRED
~~~

因为 IU6 第一版明确不做：

~~~text
Workflow auto retry
WAITING duration timeout
Workflow resume
Checkpoint recovery
~~~

它将在 Persistence / Recovery 阶段升级处理。

## 9. 现有合同中可直接复用的部分

以下基础设施已足够，不是 blocker：

~~~text
ExecutionContext.deadline
ToolExecutionStatus.TIMEOUT / UNKNOWN
StepAttemptObservation
ToolInvocationRequest.idempotency_key 字段本身
IdempotencyStore get/reserve/mark_completed/mark_unknown 基础方向
ExecutionPermissionContextProvider / Evaluator
exact IU3 ResolvedStepCapabilities
Core Tool journal truth boundary
~~~

问题在于它们尚未被完整连接成可审计的 Reliability authority。

## 10. 第一版 Readiness 不要求解决的内容

以下明确不是 IU6 第一版 blocker：

~~~text
Workflow WAITING durable timeout
Workflow resume
Crash Recovery
durable attempt history
Resource Lock
Cancellation / Preemption handler
Plan stop/fallback interpretation
Plan Aggregation
M6
~~~

其中 Resource Lock 留到其独立实施范围；IU6 不因为 ToolDefinition.resource_locks 已存在就提前实现。

## 11. Controlled Amendment 要求

### CA-M5-IU6-01 Reliability Policy + Timeout / Replay Contracts

必须先冻结并独立审查：

~~~text
typed reliability policy objects
ReliabilityPolicyResolver
ExecutionClock
AsyncTimeoutRunner
RetrySleeper / BackoffCalculator
ReplaySafetyEvaluator
RetryDecision
~~~

要求：

~~~text
opaque policy string 不由 Core直接解释
UNKNOWN replay safety != SAFE
deadline expired 不启动新 side effect
TIMEOUT != FAILED
~~~

### CA-M5-IU6-02 Tool Attempt + Idempotency + Finalization Boundary

必须先冻结并独立审查：

~~~text
logical Tool call / physical attempt model
ToolAttemptObservation
Tool journal attempt history
stable idempotency key
IdempotencyRecord provenance
completed-result recovery
StepAttemptSequenceAuthority
StepReliabilityDecision
StepFinalizationDecision
~~~

要求：

~~~text
retry 不改变 Approved capability
Domain 不拥有 attempt/idempotency
COMPLETED / RESERVED / UNKNOWN 不盲目 invoke
PARTIAL_SUCCESS / BLOCKED / UNKNOWN / NO_EXTERNAL_EXECUTION 不被猜测终态
~~~

## 12. Canonical / Frozen Contract 影响

两项 amendment 均不得修改：

~~~text
Canonical ActionStep
ApprovedActionPlan top-level contract
PolicyDecision
ExecutionEngine frozen signature
RuntimeOrchestrator
M6 contracts
~~~

允许受控修改的 frozen internal artifacts：

~~~text
CoreApprovedToolInvoker
ToolInvocationJournalEntry
ToolInvocationRequest usage
IdempotencyRecord / IdempotencyStore support contracts
M5 internal reliability contracts
~~~

## 13. Readiness Re-Review Gate

只有以下条件全部满足后才能写 READY：

~~~text
1. CA-M5-IU6-01 Targeted Amendment Review = PASSED
2. CA-M5-IU6-01 four local gates = GREEN
3. CA-M5-IU6-02 Targeted Amendment Review = PASSED
4. CA-M5-IU6-02 four local gates = GREEN
5. 5 个 blocker 全部 CLOSED
6. max_attempts 明确表示“包含第一次”的总尝试次数
7. Tool physical attempt 与 Step attempt_number 两套计数不可混用
8. 不新增 Capability substitution / Replan
9. UNKNOWN side effect 不会进入 blind retry
10. Workflow owner 仍禁止 auto retry
11. IU6 不解释 on_failure/fallback
12. Canonical / M6 边界未被破坏
~~~

## 14. Current Formal Status

~~~text
M4 = CLOSED

M5-IU1 = PASSED
M5-IU2 = PASSED
M5-IU3 = PASSED
M5-IU4 = PASSED
M5-IU5 = PASSED

M5-IU6 IMPLEMENTATION DESIGN = COMPLETE
M5-IU6 IMPLEMENTATION READINESS = NOT_READY

B-M5-IU6-001 = OPEN
B-M5-IU6-002 = OPEN
B-M5-IU6-003 = OPEN
B-M5-IU6-004 = OPEN
B-M5-IU6-005 = OPEN

NEXT REQUIRED:
CA-M5-IU6-01
then CA-M5-IU6-02
then M5-IU6 Readiness Re-Review

M5 = IN PROGRESS
~~~