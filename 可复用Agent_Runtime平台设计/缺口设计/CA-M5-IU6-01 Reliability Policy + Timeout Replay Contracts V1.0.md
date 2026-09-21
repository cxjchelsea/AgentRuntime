# CA-M5-IU6-01 Reliability Policy + Timeout / Replay Contracts V1.0

> Purpose：关闭 B-M5-IU6-001。
> Baseline：M5-IU6 Design Review = PASSED，Readiness = NOT_READY。
> 本 Amendment 只冻结 Reliability policy / timeout / retry decision / replay-safety contracts；不实现 logical/physical Tool attempt、IdempotencyRecord provenance、Step attempt sequence 或 Step finalization。

## 1. Blocker

~~~text
B-M5-IU6-001
RELIABILITY_POLICY_AND_TIMEOUT_RUNTIME_CONTRACT_MISSING
~~~

现有 Registry 仅保存 opaque string refs：timeout_policy / retry_policy / idempotency_* / side_effect_level。

Core 不能直接解释任意字符串，也不能把 mutable latest policy 在 execution time 绑定到已批准 capability。

## 2. 新增 M5 internal contracts

新增 runtime/execution/reliability.py，冻结：

~~~text
ReliabilityCapabilityKind
IdempotencyMode
SideEffectClass

ResolvedTimeoutPolicy
ResolvedRetryPolicy
ResolvedIdempotencyPolicy
ResolvedReliabilityPolicy
ReliabilityPolicyResolver

ReplaySafetyStatus
ReplaySafetyContext
ReplaySafetyDecision
ReplaySafetyEvaluator

RetryDecisionStatus
RetryDecision
RetryDecisionContext
RetryDecisionEvaluator

ExecutionClock
RetrySleeper
BackoffCalculator

TimeoutRunStatus
TimeoutRunResult
AsyncTimeoutRunner
~~~

## 3. Policy determinism

ResolvedReliabilityPolicy 必须绑定：

~~~text
capability_kind
capability_id
capability_version
policy_identity
~~~

policy_identity 必须是不可变 resolved identity（version/hash/token）。

冻结不变量：

~~~text
exact capability version
→ deterministic immutable reliability policy
~~~

禁止：

~~~text
policy_ref='standard'
→ execution time 自动绑定当前 latest policy
~~~

ReliabilityPolicyResolver 不拥有 Registry discovery、Capability substitution 或 Replan。

## 4. Retry policy semantics

ResolvedRetryPolicy.max_attempts = 总尝试次数，包含 attempt 1。

例如 max_attempts=3 只允许 attempt 1/2/3。

disabled retry policy 必须：

~~~text
enabled = false
max_attempts = 1
~~~

## 5. Timeout boundary

AsyncTimeoutRunner 只报告：

~~~text
COMPLETED
TIMED_OUT
UNKNOWN
~~~

它不拥有：

~~~text
Retry decision
Idempotency state transition
Lifecycle finalization
Capability substitution
~~~

TIMEOUT 不得自动改写成 FAILED。

ExecutionClock 为唯一 Reliability time-source contract，核心逻辑不得散落 datetime.now()/time.time()。

## 6. Replay safety

ReplaySafetyStatus：

~~~text
SAFE
UNSAFE
UNKNOWN
~~~

UNKNOWN 永远不等于 SAFE。

ReplaySafetyContext 只承载 CA-01 已知事实；跨 Step attempt operation correlation 仍属于 CA-02。

## 7. Retry decision

RetryDecisionStatus：

~~~text
RETRY
STOP
WAIT
UNKNOWN
~~~

RETRY 必须同时携带 next_attempt>=2 与 non-negative backoff_seconds。

非 RETRY decision 不得携带 retry fields。

## 8. Explicit non-goals

本 Amendment 不修改：

~~~text
CoreApprovedToolInvoker multi-attempt behavior
ToolInvocationJournalEntry attempt history
ToolInvocationRequest usage
IdempotencyRecord provenance
IdempotencyStore lifecycle
ToolOperationCorrelationKey
StepAttemptSequenceAuthority
StepReliabilityDecision
StepFinalizationDecision
ExecutionLifecycleService.finish_step
Canonical contracts
RuntimeOrchestrator
M6
~~~

以上全部继续留给 CA-M5-IU6-02 或后续 IU。

## 9. Blocker closure rule

B-M5-IU6-001 只有在以下全部满足后才可 CLOSED：

~~~text
1. contract code exists
2. targeted amendment review = PASSED
3. four local gates = GREEN
4. opaque policy refs are not interpreted directly in Core
5. policy_identity is immutable/deterministic
6. UNKNOWN replay safety != SAFE
7. TIMEOUT != FAILED
8. no retry loop / Tool invoke / lifecycle mutation added
~~~

## 10. Current status

~~~text
CA-M5-IU6-01 = CODE COMPLETE
CA-M5-IU6-01 TARGETED AMENDMENT REVIEW = PENDING
CA-M5-IU6-01 VERIFICATION = PENDING FOUR LOCAL GATES

B-M5-IU6-001 = FIX_IMPLEMENTED_PENDING_REVIEW_AND_GATES

M5-IU6 IMPLEMENTATION READINESS = NOT_READY
M5 = IN PROGRESS
~~~