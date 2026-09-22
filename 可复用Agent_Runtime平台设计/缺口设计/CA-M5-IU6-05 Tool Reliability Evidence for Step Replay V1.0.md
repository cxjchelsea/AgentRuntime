# CA-M5-IU6-05 Tool Reliability Evidence for Step Replay V1.0

> Purpose：关闭 Formal Implementation 阶段发现的 B-M5-IU6-009。
> Baseline：CA-M5-IU6-01/02/03/04 = PASSED。
> 本 Amendment 只补 whole-Skill replay 所需的 Tool reliability evidence；不实现 retry loop、Skill/Tool invoke、finish_step、Aggregation 或 M6。

## 1. Blocker

~~~text
B-M5-IU6-009
TOOL_RELIABILITY_EVIDENCE_MISSING_FOR_STEP_REPLAY
~~~

当前 Tool journal 有：

~~~text
idempotency_key?
operation_key?
operation_fingerprint?
~~~

但：

~~~text
idempotency_key = None
~~~

无法区分：

~~~text
NATURAL
NON_IDEMPOTENT
~~~

而 frozen IU6 design 已明确：

~~~text
NON_IDEMPOTENT + real invocation started
→ whole-Skill automatic replay = UNSAFE
~~~

因此 StepReplaySafetyEvaluator 当前缺失必要的 Tool policy provenance。

## 2. 新增合同

新增 Core-owned：

~~~text
ToolReliabilityEvidence
- policy_identity: str
- idempotency_mode: IdempotencyMode
- side_effect_class: SideEffectClass
- invocation_started: bool
~~~

并挂载：

~~~text
ToolInvocationJournalEntry.reliability_evidence?
~~~

## 3. Evidence semantics

`policy_identity` 来自 exact Tool version 已解析得到的 immutable `ResolvedReliabilityPolicy.policy_identity`。

`idempotency_mode` / `side_effect_class` 来自同一个 exact Tool resolved policy，不由 Step coordinator 重算。

`invocation_started` 表示本 logical Tool invocation 中至少一次真实 Tool implementation invocation 已经开始。

以下不等价：

~~~text
journal has physical-attempt evidence
!= real side effect invocation started
~~~

因为 Input Validation / Permission / deadline gate 也可能生成 fail-closed observation，所以 invocation_started 必须是显式 Core evidence。

## 4. Legacy compatibility

legacy IU4 journal 允许：

~~~text
reliability_evidence = None
~~~

以避免为历史单-attempt执行重开 IU4。

但进入 IU6 whole-Skill replay 判断时：

~~~text
reliability_evidence missing
→ replay safety = UNKNOWN
~~~

不得默认 SAFE。

## 5. Step replay aggregation rules

StepReplaySafetyEvaluator 至少必须满足：

~~~text
Tool evidence missing
→ UNKNOWN

Tool evidence NON_IDEMPOTENT + invocation_started
→ UNSAFE

Tool evidence NATURAL
→ 不因 absence of idempotency_key 被误判 UNKNOWN

Tool evidence KEY_BASED
→ 继续结合 idempotency_key + IdempotencyStore truth
~~~

Skill owner policy 不得覆盖子 Tool 的 UNSAFE evidence。

尤其禁止：

~~~text
Skill owner = NATURAL
+ Tool child = NON_IDEMPOTENT and invoked
→ SAFE
~~~

正确结果必须是：

~~~text
UNSAFE
~~~

## 6. Journal authority

`ToolReliabilityEvidence` 是 Core Tool journal truth 的一部分。

Domain Skill / Workflow 不能提供、覆盖或伪造该 evidence。

Tool adapter 也不拥有 policy_identity / idempotency_mode 的决定权。

## 7. Invocation-start invariant

若：

~~~text
reliability_evidence.invocation_started = true
~~~

则 journal 必须存在 physical attempt evidence。

但反向不成立：

~~~text
attempts != empty
不自动推出 invocation_started = true
~~~

因为 gate failure 可以生成 attempt observation。

## 8. Formal Implementation usage

Tool-level IU6 runtime：

~~~text
resolve exact Tool reliability policy
↓
build ToolReliabilityEvidence(policy_identity/mode/side-effect)
↓
before real invoke: invocation_started=false
↓
real Tool invoke begins
↓
invocation_started=true
↓
persist on logical Tool journal
~~~

Step-level IU6 runtime：

~~~text
StepAttemptObservation.tool_journal
↓
StepReplaySafetyEvaluator
↓
aggregate per-Tool reliability evidence
↓
SAFE / UNSAFE / UNKNOWN
~~~

## 9. Explicit non-goals

本 Amendment 不实现：

~~~text
Tool retry coordinator
Skill Step retry loop
ReliabilityPolicyResolver implementation
Idempotency state transition
StepAttemptSequence
finish_step
Checkpoint / Recovery
Aggregation
M6
~~~

## 10. Blocker closure rule

B-M5-IU6-009 只有以下全部满足才可 CLOSED：

~~~text
1. ToolReliabilityEvidence exists
2. evidence freezes immutable policy_identity
3. evidence freezes idempotency_mode + side_effect_class
4. evidence carries explicit invocation_started
5. ToolInvocationJournalEntry can carry evidence
6. legacy IU4 may omit evidence
7. whole-Skill replay must treat missing evidence as UNKNOWN
8. NON_IDEMPOTENT + invocation_started must be UNSAFE
9. Skill owner policy cannot override child Tool UNSAFE evidence
10. Targeted Amendment Review = PASSED
11. four local gates = GREEN
12. no retry/invoke/lifecycle/M6 authority leaks into CA-05
~~~

## 11. Current status

~~~text
CA-M5-IU6-05 = CODE COMPLETE
CA-M5-IU6-05 TARGETED AMENDMENT REVIEW = PASSED
CA-M5-IU6-05 VERIFICATION = PENDING FOUR LOCAL GATES

B-M5-IU6-009 = FIX_IMPLEMENTED_PENDING_GATES

M5-IU6 IMPLEMENTATION READINESS = NOT_READY
M5-IU6 FORMAL IMPLEMENTATION = PAUSED_AT_WHOLE_SKILL_REPLAY_EVIDENCE_BOUNDARY
M5 = IN PROGRESS
~~~