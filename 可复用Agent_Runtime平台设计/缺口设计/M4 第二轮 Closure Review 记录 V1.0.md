# M4 第二轮 Closure Review 记录 V1.0

> 基线：PR #29 `m4-closure-fix-pack`。
> 本记录只判定 M4 Core Planning mechanism 的 Closure 条件，不代表 Domain Golden Set、业务规划质量、跨阶段 Retrieve→Validate→Replan E2E 或 Production Ready。

## 1. 第二轮 Review 结论

三项第一轮 Closure blocker 均已完成对应修复：

```text
B-M4-001 = CLOSED_BY_ARCHITECTURE_AMENDMENT
B-M4-002 = CLOSED_BY_GATE_RECLASSIFICATION
B-M4-003 = CLOSED_BY_CORE_EVAL_HARNESS
```

因此：

```text
M4 CLOSURE BLOCKER REVIEW = PASSED
M4 CLOSURE FIX PACK DESIGN REVIEW = PASSED
M4 IMPLEMENTATION CLOSURE = READY_TO_CLOSE_AFTER_GATES
```

当前仍不能直接标记 M4=CLOSED，唯一剩余前置为 Fix Pack 四项本地门禁。

## 2. B-M4-001 复核：Clarification / Active Interaction

最终责任模型已统一为：

```text
M3 uncertainty / needs_clarification
        ↓
registered Action / Strategy
+ Candidate / Eligibility / Strategy Rules
        ↓
统一 Strategy Selection
```

不再存在独立 Core ClarificationPlanner / ActiveInteractionPlanner。该决定与当前 IU3/IU8 实现一致，避免第二套“下一步行为决策器”。

V2.1 中残留的 Clarification Planning / Active Interaction Planning 能力清单已同步改为 Eligibility Projection，避免术语继续误导。

## 3. B-M4-002 复核：Gate M4-39

Gate M4-39 已正式重分类：

```text
CLASSIFICATION = CROSS_STAGE_DEFERRED
NOT_APPLICABLE_FOR_M4_IMPLEMENTATION_CLOSURE
DEFERRED_UNTIL_M5_M6
```

M4 侧已定义 `ReplanEntryRequest`，只允许 `RESULT_VALIDATE` 触发，并仅承载 request/plan/reason/evidence reference 等跨阶段入口信息。

因此当前没有把 M5/K0 Retrieval、M6 Result Validation 或递归 Replan 假实现进 M4。

## 4. B-M4-003 复核：M4 Eval Harness

Core 机制已落地：

```text
M4EvalGate
PlanningEvalCase
PlanningEvalResult
PlanningCaseEvaluator
M4GateThresholds
M4GateSummary
M4EvalReport
M4EvalRunner
```

四类冻结 Gate：

```text
POLICY
BEHAVIOR
MEMORY_TOOL
ACTIVE_SAFETY
```

缺少任一 Gate case 时该 Gate 不会自动通过。Core 不硬编码业务 taxonomy，也没有伪造 150～300 条业务 Golden Set。

正式区分：

```text
Core Eval Harness = IMPLEMENTED
Domain Golden Planning Set = DEFERRED_TO_DOMAIN_PACKAGE
Production Planning Quality Gate = NOT_EVALUATED
```

## 5. 剩余非阻塞债

```text
TD-M4-01 Goal source namespace reservation = NON_BLOCKING
TD-M4-02 Domain CandidateEligibility optional = NON_BLOCKING
TD-M4-04 Structured Planning Trace = NON_BLOCKING
XG-M4-39 Retrieve→Validate→Replan E2E = DEFERRED_UNTIL_M5_M6
```

上述项目不阻塞 M4 Core Implementation Closure，但必须保留到后续对应阶段。

## 6. Final Closure Gate

PR #29 / Fix Pack 合并前必须执行：

```text
python -m pytest tests -q
python -m mypy runtime tests
python -m ruff check runtime tests
python -m ruff format --check runtime tests
```

只有四项全部通过后，允许执行 Final Closure Authorization：

```text
M4_IMPLEMENTATION_CLOSURE = CLOSED
M4 = CLOSED
M5 = ALLOWED TO START
```

## 7. CLOSED 的限定含义

`M4 = CLOSED` 仅表示：

```text
Core Planning mechanism implementation closed
```

不表示：

```text
Domain Golden Set passed
Business planning quality verified
Retrieve→Validate→Replan E2E completed
M5/K0/M6 implemented
Production Ready
```