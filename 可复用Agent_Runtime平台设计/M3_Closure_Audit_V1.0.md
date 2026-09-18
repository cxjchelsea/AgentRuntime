# M3 Closure Audit V1.0

## 1. 审计结论口径

本文件审计的是 **M3 Understanding 机制是否完成实现闭环，并且仍严格停留在 Understanding 权限边界内**。

M3 CLOSED 的定义固定为：

```text
Deterministic Understanding
+ FAST / HYBRID / DEEP Routing
+ Structured Model Boundary
+ Evidence / Uncertainty / Risk / Candidate Postprocessing
+ Rule > Model Final Merge
+ Canonical UnderstandingState Assembly
+ M2 Deep Safety / Policy Reintegration
+ fail-closed boundaries
```

M3 CLOSED **不等于**：

```text
真实模型 Provider 已提供
Domain Intent / Need / Action Taxonomy 已提供
真实业务 Prompt 已提供
真实医疗 / 陪护 / 教育规则已提供
M3 可以自行做 SafetyDecision
M3 可以自行做 PolicyDecision
M3 可以规划 ActionPlan
M3 可以调用 Tool / Workflow
M3 可以生成最终回复
M3 可以写入长期 Memory
业务闭环已完成
Production Ready
```

这些内容属于 Provider / Domain Package / M2 / M4 / M5 / M7 / M8 / M9，不得因为 M3 闭环而越权宣称。

---

## 2. M3 单元状态

| 单元 | 内容 | Closure 输入状态 |
|---|---|---|
| M3-IU1 | Understanding Contract Alignment & Internal Types | PASSED |
| M3-IU2 | Rules-first Deterministic Understanding | PASSED |
| M3-IU3 | Fast / Deep Routing & Model Boundary | PASSED |
| M3-IU4 | Evidence / Uncertainty / Candidate Extraction | PASSED |
| M3-IU5 | Understanding Orchestrator / Final Merge | PASSED |
| M3-IU6 | M2 Deep Safety / Policy Integration | PASSED |
| M3-IU7 | Integration + E2E + Closure Gate | 当前执行 Closure 总门禁 |

---

## 3. Closure Invariants

### M3-G01 UnderstandingState remains the only Canonical M3 output

最终主链输出必须仍是冻结的：

```text
UnderstandingState
```

内部类型如：

```text
RuleParseResult
ModelUnderstandingResult
UnderstandingPostprocessResult
CandidateAction
MemoryCandidate
RiskSignalSet
UnderstandingEvidence
```

不得升级成新的 Canonical 主链 Contract。

判定：**PASS by implementation + closure test**。

### M3-G02 UnderstandingState != ActionPlan

M3 只负责理解，不得产生：

```text
ActionPlanDraft
ApprovedActionPlan
ToolCall
WorkflowCall
PolicyDecision
RuntimeResponse
StateUpdate
MemoryUpdate
```

判定：**PASS**。

### M3-G03 Rule facts > model inference

当 deterministic rule 已确定：

```text
negation
confirmation
correction
single speech_act
same intent_id
```

模型不得覆盖确定性事实或伪造 RULE provenance。

判定：**PASS by IU5 tests**。

### M3-G04 FAST path must not call model

当 deterministic result 已满足 FAST 条件时：

```text
FAST_PATH
→ no DeepUnderstandingRequest
→ no model.infer()
```

判定：**PASS by IU5 E2E**。

### M3-G05 DEEP / HYBRID model boundary is Understanding-only

模型输入只允许经过显式 allow-list Context projection；模型输出不得跨越到：

```text
Plan
Policy
Tool
Workflow
Response
State Update
Memory Write
Execution Result
```

判定：**PASS by IU3 + closure test**。

### M3-G06 Deep/Hybrid cannot silently complete without required model result

需要模型的路由没有配置模型时必须 fail closed；模型执行失败不得伪装成成功 Understanding。

判定：**PASS**。

### M3-G07 Evidence provenance cannot be spoofed

模型 Evidence 必须被归一为：

```text
MODEL_INFERENCE
```

不得声称自身是：

```text
RULE_MATCH
SYSTEM_STATE
MEMORY
```

模型引用的 evidence_id 必须真实存在。

判定：**PASS by IU4/IU5 tests**。

### M3-G08 Risk signal != SafetyDecision

M3 可以输出：

```text
RiskSignalSet
UnderstandingState.risk
```

但不得输出或执行：

```text
SafetyResult
forced workflow
runtime block
preemption effect
```

真正的风险升级仍由 M2 Deep Safety Rule 完成。

判定：**PASS by IU6 integration tests**。

### M3-G09 Intent != Policy authorization

M3 Intent 只是理解结果。

```text
UnderstandingState
→ M2 SAFETY_DEEP
→ M2 POLICY
→ only then M4
```

M3 不得绕过 M2 直接授权 Planner。

判定：**PASS by IU6 integration tests**。

### M3-G10 CandidateAction != ApprovedActionPlan

CandidateAction 只允许表达 semantic affordance，不得携带：

```text
steps
approval_status
policy_snapshot
tool_requirement
```

判定：**PASS by closure test**。

### M3-G11 MemoryCandidate != persisted Memory

M3 只能发现候选记忆，不得：

```text
write
commit
persist
store
```

判定：**PASS by implementation + AST closure test**。

### M3-G12 Domain taxonomy remains injected

Core 不得硬编码 companion / medical / reminder / patient 等业务 vocabulary，也不得把 357 个三级目录变成 Core Intent。

判定：**PASS，Closure test 持续扫描**。

### M3-G13 M2 remains the sole Safety / Policy authority

IU6 不新增第二套：

```text
M3SafetyBridge
M3PolicyBridge
M3ConstraintCoordinator
```

而是复用已经 CLOSED 的：

```text
M2RuntimeOrchestrator
UNDERSTANDING
→ SAFETY_DEEP
→ POLICY
→ PLAN
```

判定：**PASS**。

### M3-G14 No downstream side effects inside runtime/understanding

M3 production package 不得直接执行：

```text
execute
commit
persist
write
cancel
resume
transition
enqueue
```

判定：**PASS by AST closure gate**。

### M3-G15 Frozen UnderstandingEngine interface remains unchanged

接口继续固定为：

```python
understand(
    RuntimeInput,
    RuntimeContext,
) -> UnderstandingState
```

判定：**PASS**。

### M3-G16 M0-M2 regression must remain green

M3 Closure 不能通过修改冻结的 M0-M2 Contract / Interface / Runtime authority 来获得“通过”。

判定：**待最终全量门禁确认**。

---

## 4. 非阻塞架构债务

### TD-M3-01 Opaque dict substructures

当前：

```text
emotion
needs
interaction
recent_turns
relevant_memories
```

部分结构仍包含开放 dict。

裁决：**NON_BLOCKING_TECH_DEBT**。

要求：后续如需增加字段级治理，应通过冻结子 Schema 或专用 projection 收紧，不应在 M3 Closure 临时扩张 Canonical Contract。

### TD-M3-02 pending_question_resolution 无 Canonical 落点

IU2 可产生：

```text
pending_question_resolution
```

但冻结 UnderstandingState 当前没有直接对应字段。

IU5 没有把它偷偷塞入 interaction / metadata / quality。

裁决：**DEFERRED_BY_SCHEMA**。

后续若确认该信息必须跨阶段消费，应先完成 Contract 变更评审。

### TD-M3-03 RiskSignalSet 为集合级 confidence

当前 RiskSignalSet 只有一个集合级 confidence；多个来源混合时可能损失 per-signal confidence 信息。

裁决：**NON_BLOCKING_SCHEMA_DEBT**。

不得把集合 confidence 解释成每个 signal 的独立置信度。

### TD-M3-04 Model Context 中 recent_turns / memories 内部仍是 opaque dict

Context Selector 已限制顶层 allow-list，但 selected item 内部字段未二次 schema-filter。

裁决：**NON_BLOCKING_DATA_BOUNDARY_DEBT**。

后续需要字段级 model exposure policy 时再收紧。

### TD-M3-05 No concrete model provider

当前只有：

```text
StructuredUnderstandingModel Protocol
```

没有 OpenAI / Anthropic / local model provider。

裁决：**NOT_A_CORE_BLOCKER**。

Provider 属于可替换实现 / Application / Domain deployment，不应写死在 Runtime Core。

---

## 5. 明确 Deferred，而非 M3 Blocker

| Deferred Capability | 原因 | 后续归属 |
|---|---|---|
| concrete LLM provider | Provider-neutral Core | Adapter / Application |
| concrete Domain intents / needs / actions | Domain-owned vocabulary | Domain Extension / M9 |
| business prompts | 业务配置 | Business Package |
| clinical / companion semantic rules | Domain truth，不得由 Core 发明 | Domain Rule Package |
| Action planning | 不属于 Understanding | M4 |
| Tool / Workflow execution | 不属于 Understanding | M5 |
| final response generation | 不属于 Understanding | M7 |
| memory persistence | M3 只有 candidate | M8 |
| actual forced SafetyWorkflow execution | M2 仅做 authority decision | M4/M5 |
| pending_question_resolution Canonical mapping | 当前冻结 Schema 无落点 | Contract review |

---

## 6. Closure Gate

只有同时满足以下条件才能正式宣布：

```text
M3_IMPLEMENTATION_CLOSURE = CLOSED
NEXT_ALLOWED = M4 Planning & Orchestration Implementation
```

条件：

1. `tests/test_m3_closure.py` 全部通过；
2. M3-IU1～IU6 既有测试全部通过；
3. 全量 pytest 通过；
4. mypy 通过；
5. ruff check 通过；
6. ruff format --check 通过；
7. M0 / M1 / M2 Closure 回归保持绿色；
8. Closure 审查未发现新的 Canonical expansion、Domain hardcode、Safety/Policy authority duplication、Planner/Tool/Memory side effect 或 fabricated capability。

在上述门禁完成前：

```text
M3 = READY_FOR_CLOSURE_REVIEW
```

而不是 CLOSED。
