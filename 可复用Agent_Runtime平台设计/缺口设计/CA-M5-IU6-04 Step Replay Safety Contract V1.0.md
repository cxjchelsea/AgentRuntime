# CA-M5-IU6-04 Step Replay Safety Contract V1.0

> Purpose：关闭 Formal Implementation 阶段发现的 B-M5-IU6-008。
> Baseline：CA-M5-IU6-01/02/03 = PASSED。
> 本 Amendment 只补 whole-Skill Step replay 的 safety authority；不实现 Step retry loop、Skill invoke、Tool invoke、finish_step、Aggregation 或 M6。

## 1. Blocker

~~~text
B-M5-IU6-008
STEP_REPLAY_SAFETY_RUNTIME_CONTRACT_MISSING
~~~

现有 Tool-level：

~~~text
ReplaySafetyContext.current_status: ToolExecutionStatus
ReplaySafetyEvaluator
~~~

只能表达 Tool invocation replay safety。

现有 Step-level：

~~~text
StepReliabilityEvaluator(
  observation,
  replay_safety,
  retry_decision
)
~~~

却没有 authority 负责产出 whole-Skill replay_safety。

## 2. 新增合同

新增：

~~~text
StepReplaySafetyRequest
- observation: StepAttemptObservation
- owner_policy: ResolvedReliabilityPolicy

StepReplaySafetyEvaluator
- async evaluate(request)
  -> ReplaySafetyDecision
~~~

## 3. Owner policy identity

StepReplaySafetyRequest 只接受：

~~~text
owner_policy.capability_kind = SKILL
~~~

Tool / Workflow reliability policy 不得作为 whole-Skill replay authority。

StepReplaySafetyRequest 自身必须验证：

~~~text
observation.execution_owner = SKILL
owner_policy.capability_id/version
== observation.owner_capability_id/version
~~~

因此 caller 不能把另一个 Skill、Tool 或 Workflow 的 policy 拼进当前 Step replay safety envelope。

## 4. Evidence scope

Evaluator 必须基于完整：

~~~text
StepAttemptObservation
- owner result
- Tool final results
- Core Tool journal
- unknown/untrusted-success flags

+ exact Skill reliability policy
~~~

必要时 evaluator 可以通过自身注入依赖读取 IdempotencyStore / durable evidence。

Coordinator 不得自己发明：

~~~text
FAILED -> SAFE
TIMEOUT -> SAFE
PARTIAL_SUCCESS -> SAFE
~~~

## 5. Fail-closed

任何以下情况：

~~~text
evidence 缺失
idempotency state UNKNOWN
Tool side effect 无法确认
untrusted success
correlation evidence 不完整
evaluator exception/invalid result
~~~

都不能由 coordinator 默认成 SAFE。

正式不变量：

~~~text
UNKNOWN != SAFE
UNSAFE != RETRY
~~~

## 6. Authority boundary

StepReplaySafetyEvaluator 不得：

~~~text
修改 ApprovedPlan
重新 Planning
Capability substitution
Registry discovery
调用 Skill / Workflow / Tool
分配 Step attempt_number
修改 lifecycle
调用 finish_step
进入 M6
~~~

它只返回 ReplaySafetyDecision。

## 7. 与 Tool-level ReplaySafetyEvaluator 的关系

~~~text
ReplaySafetyEvaluator
= one Tool logical invocation replay safety

StepReplaySafetyEvaluator
= whole Skill Step attempt replay safety
~~~

二者不得互相替代。

Step evaluator 可以综合当前 attempt 中多个 Tool 的 journal/idempotency evidence，但不能把 StepAttemptStatus 强行转成 ToolExecutionStatus 后复用 Tool evaluator。

## 8. Formal Implementation usage

Step retry 正式链：

~~~text
StepAttemptObservation
+ exact Skill ResolvedReliabilityPolicy
↓
StepReplaySafetyEvaluator
↓
ReplaySafetyDecision
+ RetryDecisionEvaluator
↓
StepReliabilityEvaluator
↓
RETRY / FINALIZE / WAIT_RECOVERY / ...
~~~

只有：

~~~text
ReplaySafetyDecision = SAFE
+ RetryDecision = RETRY
+ StepAttemptSequenceAuthority.claim_next = CLAIMED
~~~

才允许重新执行同一个 exact Skill owner。

## 9. Explicit non-goals

本 Amendment 不实现：

~~~text
Skill Step retry loop
Skill owner timeout execution
Tool retry coordinator
Workflow auto-retry
finish_step
Checkpoint / Recovery
Aggregation
M6
~~~

## 10. Blocker closure rule

B-M5-IU6-008 只有以下全部满足才可 CLOSED：

~~~text
1. StepReplaySafetyRequest exists
2. request only accepts SKILL reliability policy
3. request enforces SKILL execution owner + exact observed Skill id/version
4. StepReplaySafetyEvaluator exists
5. evaluator result remains ReplaySafetyDecision SAFE/UNSAFE/UNKNOWN
6. UNKNOWN cannot become SAFE by coordinator default
7. Tool-level ReplaySafetyEvaluator is not reused as Step evaluator
8. Targeted Amendment Review = PASSED
9. four local gates = GREEN
10. no execution/lifecycle/M6 authority leaked into CA-04
~~~

## 11. Current status

~~~text
CA-M5-IU6-04 = PASSED
CA-M5-IU6-04 TARGETED AMENDMENT REVIEW = PASSED
CA-M5-IU6-04 VERIFICATION = PASSED

B-M5-IU6-008 = CLOSED
NEW BLOCKER = NONE

M5-IU6 IMPLEMENTATION READINESS = PENDING RE-REVIEW
M5-IU6 FORMAL IMPLEMENTATION = PAUSED
M5 = IN PROGRESS
~~~