# M5-IU6 Formal Implementation 实现说明 V1.0

> Scope：M5 Execution Framework Step 8 — Timeout / Retry / Idempotency。
> Baseline：CA-M5-IU6-01/02/03/04 = PASSED；B-M5-IU6-001～008 = CLOSED；Implementation Readiness = READY。

## 1. 本轮实现

~~~text
Tool Reliability
- exact typed reliability policy resolution
- operation fingerprint / occurrence / cross-Step correlation
- validation / permission / deadline admission
- KEY_BASED idempotency preflight
- completed-result recovery
- physical Tool attempt
- timeout runner
- output validation
- replay safety
- retry decision / backoff
- physical retry
- atomic idempotency completion

Step Reliability
- owner timeout
- IU5 StepAttemptObservation collection
- Step replay safety
- Step retry decision
- StepAttemptSequenceAuthority
- exact Skill replay
- Tool sequence drift detection
- StepReliabilityDecision
- StepFinalizationDecision
~~~

## 2. 仍然不属于 IU6

~~~text
ExecutionLifecycleService.finish_step mutation
Workflow owner auto retry / resume
Checkpoint / Crash Recovery
durable attempt history
Resource Lock
Cancellation / Preemption execution
Plan stop/fallback interpretation
Plan Aggregation
M6
~~~

## 3. Tool-level 不变量

~~~text
Retry != Replan
Retry != Capability substitution
same logical Tool call -> stable logical id / operation identity / idempotency key
physical attempt strictly increments
each physical attempt re-checks current Permission
INVALID / DENIED / expired deadline -> no new side effect
TIMEOUT != FAILED
UNKNOWN side effect != blind retry
KEY_BASED completion uses IdempotencyCompletionAuthority
~~~

## 4. Step-level 不变量

~~~text
Workflow owner is never auto-replayed
Step replay only for exact SKILL owner
StepReplaySafetyDecision must be SAFE before retry
RetryDecision must be RETRY
StepAttemptSequenceAuthority must CLAIM exact +1
prior Tool operation identity must correlate across Step attempts
Tool sequence drift -> ABORT_UNKNOWN
Finalization only produces decision; it does not call finish_step
~~~

## 5. Independent Review finding fixed

Review 发现默认 Step replay safety 对 KEY_BASED Skill + 空 Tool journal 会返回 SAFE。

这违反 CA-M5-IU6-04：

~~~text
missing / ambiguous evidence -> UNKNOWN
~~~

已修改为：

~~~text
KEY_BASED + no Tool/idempotency evidence
-> ReplaySafetyStatus.UNKNOWN
-> STEP_KEY_BASED_EVIDENCE_MISSING
~~~

并增加 Formal Implementation behavioral test。

## 6. Formal behavior tests

新增：

~~~text
tests/test_m5_iu6_formal_implementation.py
~~~

覆盖：

~~~text
KEY_BASED missing evidence -> UNKNOWN
NATURAL Skill replay -> SAFE
NON_IDEMPOTENT Skill replay -> UNSAFE
Step attempt sequence monotonic/conflict-safe
Finalization only maps SUCCESS/FAILED/TIMEOUT
Retry requires SAFE + budget
InMemory atomic idempotency completion is recoverable
~~~

## 7. Current status

~~~text
M5-IU6 FORMAL IMPLEMENTATION = CODE COMPLETE CANDIDATE
M5-IU6 INDEPENDENT IMPLEMENTATION REVIEW = PENDING
M5-IU6 VERIFICATION = PENDING FOUR LOCAL GATES
M5-IU6 = NOT YET PASSED
M5 = IN PROGRESS
~~~