# M4 Knowledge Contract Gap Review V1.0

> Review target: M4 V2.1 Knowledge Planning 与首批冻结 Canonical Contract 之间的接口缺口。  
> 本轮只做 Contract Review，不修改生产 Contract / Interface / Runtime 代码。

---

# 1. Review 结论

正式结论：

~~~text
DECISION = OPTION_A_APPROVED_FOR_CONTRACT_AMENDMENT
~~~

即：

> **KnowledgeRequirement / RetrievalPlan / EvidenceRequirement 应成为 M4-owned typed planning subcontracts，并作为 optional fields 正式加入 ActionPlanDraft 与 ApprovedActionPlan。**

不采用：

~~~text
OPTION_B
把三者只保留为 M4 内部对象，
再隐藏进 capability_plan / tool_plan / trace / ActionStep.parameters
~~~

原因是现有冻结链路已经要求：

~~~text
M4
→ ApprovedActionPlan
→ M5
→ KnowledgeRetrievalSkill / K0
→ M6
~~~

且 M5 的唯一合法规划输入仍是：

~~~text
ApprovedActionPlan
~~~

如果 Knowledge Planning 不进入 ApprovedActionPlan，则 M5 无法在不引入 side channel / hidden coupling 的前提下执行 M4 已批准的 RetrievalPlan。

因此，本 Review 判定：

~~~text
Knowledge Planning
是 Planning Semantics
不是 Tool implementation detail
也不是 Trace-only metadata
~~~

---

# 2. 发现的正式冲突

## 2.1 M4 V2.1 的明确要求

M4 V2.1 明确新增：

~~~text
Knowledge Need Decision
Knowledge Domain Routing
Retrieval Query Construction
Retrieval Planning
Evidence Requirement Planning
Knowledge-aware ActionPlan
Retrieve → Validate → Replan
~~~

并明确 M4 负责：

~~~text
要不要查知识
查什么
查哪个知识域
用什么检索方式
需要什么证据
~~~

M4 V2.1 还明确把以下内容放入规划输出：

~~~text
knowledge_requirement
retrieval_plan
evidence_requirement
~~~

其伪代码也在 ActionPlan Draft assembly 时显式传入三者。

## 2.2 K0 的明确要求

K0 V1.0 明确规定：

~~~text
K0 接收 M4 产生的：

RetrievalPlan
KnowledgeRequirement
EvidenceRequirement
~~~

且：

~~~text
M4 输出 RetrievalPlan
M5 通过 KnowledgeRetrievalSkill 调用 K0
~~~

因此 K0 设计已经把 RetrievalPlan 当作跨阶段正式输入，而不是 M4 私有实现细节。

## 2.3 Canonical V1.0 当前缺口

首批冻结 Canonical Registry 当前规定：

~~~text
ActionPlanDraft optional:
strategy
memory_usage
capability_plan
tool_plan
confirmation_plan
response_strategy
state_intent
stop_conditions
fallback_plan
trace
~~~

ApprovedActionPlan 的 optional 与 Draft 相同，另可含：

~~~text
approved_at
~~~

当前没有：

~~~text
knowledge_requirement
retrieval_plan
evidence_requirement
~~~

因此当前存在真实 Contract Gap：

~~~text
M4 V2.1 / K0
要求 Knowledge Planning 跨阶段传递

但

Canonical V1.0
没有正式承载位置
~~~

---

# 3. 为什么不能选择“只做 M4 内部对象”

如果只把三者保留在 M4 内部，会产生至少五个问题。

## 3.1 M5 无合法输入来源

冻结规则：

~~~text
M5 only consumes ApprovedActionPlan
~~~

如果 RetrievalPlan 不在 ApprovedActionPlan，M5 无法知道 M4 批准了什么 RetrievalPlan，除非额外引入 global cache、planner side channel、hidden runtime state、trace lookup 或 out-of-band object store。这会破坏当前主链 Contract。

## 3.2 PlanValidator 无法正式验证 Knowledge Planning

M4 V2.1 要求 Plan Validator 检查完整计划。如果 KnowledgeRequirement / RetrievalPlan / EvidenceRequirement 不属于 Draft，就会形成：

~~~text
Behavior Plan validated
Knowledge Plan unvalidated
~~~

不符合 “Knowledge-aware ActionPlan” 的设计。

## 3.3 M2 Policy Re-check 看不到完整 Intended Action

M2 Policy Re-check 的对象是 ActionPlanDraft。若 RetrievalPlan 被隐藏在 M4 内部，则 Policy Re-check 永久看不到知识访问意图，包括外部 API 路径和高约束 source policy。

## 3.4 Traceability 会变成隐式关联

RetrievalPlan 是计划内容，不应降级为日志内容。若只能通过 plan_id 再去 trace 中找 retrieval object，会形成隐式执行依赖。

## 3.5 K0 Gate K0-30 无法形成显式 Contract 链

K0 Gate K0-30 要求 M4 → K0 → M5 → M6 的 Contract 可以端到端跑通。若 RetrievalPlan 不是 M4 对外 Contract 的组成部分，这条 Gate 会依赖额外未冻结通道。

---

# 4. 为什么不能塞进 capability_plan / tool_plan

正式禁止以下兼容性捷径：

~~~text
capability_plan["retrieval_plan"] = ...
tool_plan["retrieval_plan"] = ...
trace["knowledge_requirement"] = ...
ActionStep.parameters["evidence_requirement"] = ...
~~~

原因：

- capability_plan 回答“选择什么能力”，KnowledgeRequirement 回答“为什么需要知识、需要什么知识”，语义不同。
- tool_plan 回答“要调用哪些 Tool”，RetrievalPlan 回答 Domain / Query / Mode / Filter / Source Policy / Evidence Minimum，抽象层不同。
- trace 不是业务 Contract，不能成为 M5 获取执行语义的唯一来源。
- ActionStep.parameters 会把 Planning Contract 绑定到某个 KnowledgeRetrievalSkill 的具体 step encoding。

---

# 5. 推荐 Contract 形态

## 5.1 新增 M4-owned typed planning subcontracts

建议正式新增四个类型，其中三个进入 ActionPlan*，一个作为 M4 typed intermediate：

~~~text
KnowledgeRequirement
RetrievalQuery
RetrievalPlan
EvidenceRequirement
~~~

Owner：

~~~text
M4 Planning
~~~

注意：

~~~text
EvidenceRequirement
!= EvidenceItem
!= EvidencePack
!= VerifiedFact
~~~

其中：

~~~text
EvidenceRequirement
= M4 对“需要什么级别证据”的计划要求

EvidenceItem / EvidencePack
= K0 检索结果

VerifiedFact
= M6 验证结果
~~~

## 5.2 ActionPlanDraft 新增 optional fields

建议：

~~~text
knowledge_requirement: KnowledgeRequirement | None
retrieval_plan: RetrievalPlan | None
evidence_requirement: EvidenceRequirement | None
~~~

## 5.3 ApprovedActionPlan 同步新增完全相同字段

必须同步。禁止 Draft 有 Knowledge Planning、Approved 丢掉 Knowledge Planning。

---

# 6. Schema-level optional 与 Runtime-level required 的区分

为保持向后兼容，三个新字段在 Schema 层建议为 optional。

但 IU4 实现后应增加 Runtime invariant。

Case A：不需要知识：

~~~text
knowledge_requirement.required = false
retrieval_plan = None
evidence_requirement = None
~~~

Case B：需要知识：

~~~text
knowledge_requirement.required = true
retrieval_plan != None
evidence_requirement != None
~~~

即：

~~~text
optional field
!= 可以任意缺失
~~~

而是：

~~~text
Schema 为兼容旧 Consumer 而 optional
Runtime Validator 对新 Planner 输出实施条件必填
~~~

---

# 7. 对四个结构的字段裁决

本 Review 不改变 M4 V2.1 已定义的字段语义。

## 7.1 KnowledgeRequirement

保留 V2.1：

~~~text
required
reason
domain
knowledge_type
query_target
source_constraints[]
freshness_requirement
evidence_level
population
scenario
safety_level
~~~

domain / knowledge_type / population / scenario / safety_level 不得在 Runtime Core 硬编码业务取值，继续来自 Domain Registry / Domain Package / Config。

## 7.2 RetrievalQuery

保留 V2.1：

~~~text
original_query
normalized_query
query_variants[]
entities[]
topics[]
temporal_constraints
population
domain
scenario
~~~

本 Review 建议 RetrievalQuery 先作为 M4 typed intermediate，而不是增加第四个 ActionPlan 顶层字段。

原因是当前 M4 V2.1 / K0 的跨阶段正式输入明确是：

~~~text
KnowledgeRequirement
RetrievalPlan
EvidenceRequirement
~~~

## 7.3 RetrievalPlan

保留 V2.1 / K0 对 M5/K0 真正需要的执行计划字段：

~~~text
required
domain
query
query_variants[]
retrieval_mode
filters
source_policy
vector_top_k
sparse_top_k
merge_policy
rerank_enabled
rerank_top_n
freshness_requirement
minimum_evidence
fallback_policy
~~~

明确采用：

~~~text
RetrievalQuery
= M4 query construction intermediate

RetrievalPlan.query / query_variants
= 跨阶段 execution-facing projection
~~~

这样不改变 K0 当前“正式接收 RetrievalPlan”的接口口径。

## 7.4 EvidenceRequirement

保留 V2.1：

~~~text
required
minimum_count
minimum_trust
freshness_required
source_diversity_required
conflict_check_required
citation_required
~~~

---

# 8. RetrievalMode 的裁决

M4 V2.1 / K0 当前共同使用：

~~~text
VECTOR
KEYWORD
HYBRID
STRUCTURED_LOOKUP
EXTERNAL_API
NONE
~~~

本 Review 判定：

~~~text
RetrievalMode
属于跨 Domain 的 Knowledge Infrastructure control vocabulary
可以冻结为 Core/K0 structural enum
~~~

但 KnowledgeDomain / KnowledgeType / SourcePolicy / Population / Scenario / SafetyLevel 不应因此一起硬编码为 Core enum。

---

# 9. Owner / Producer / Consumer 冻结建议

| Object | Owner | Producer | Direct Consumer | Lifecycle |
|---|---|---|---|---|
| KnowledgeRequirement | M4 | KnowledgeNeedResolver | M4 Retrieval Planning / PlanValidator / M5 | Turn / Current Plan |
| RetrievalQuery | M4 | RetrievalQueryBuilder | RetrievalPlanner | Internal / Current Plan |
| RetrievalPlan | M4 | RetrievalPlanner | PlanValidator / M5 KnowledgeRetrievalSkill / K0 | Turn / Current Plan |
| EvidenceRequirement | M4 | EvidenceRequirementPlanner | PlanValidator / M5 / K0；后续供 M6 验证链参考 | Turn / Current Plan |

K0 不拥有 RetrievalPlan 的决策语义。K0 只负责严格执行合法 RetrievalPlan 并返回 Evidence Candidate。

---

# 10. Compatibility Review

Core Schema Registry V1.0 §161 明确允许：

~~~text
新增 optional field
新增 Registry 条目
新增非破坏性 enum value
~~~

前提：

~~~text
旧 Consumer 不崩溃
~~~

而 §162 将删除核心字段、修改字段原始语义、修改 enum 既有值语义、修改 Truth Level、修改 Producer / Consumer Owner、optional → required、改变 ID 关联逻辑定义为 Breaking Change，并要求 Schema Major Version Upgrade。

本次建议只新增 optional typed fields，不删除旧字段、不改变旧字段语义、不改变 Owner、不把 optional 改 required。

因此判定：

~~~text
COMPATIBILITY_CLASS
= BACKWARD_COMPATIBLE_SCHEMA_EXTENSION
~~~

不是 Schema Major Change。

---

# 11. Schema Version Review

虽然不是 Major Breaking Change，但 Contract surface 已增加。

Core Schema Registry 建议 schema version 使用 MAJOR.MINOR，因此建议：

~~~text
ActionPlanDraft      1.0.0 → 1.1.0
ApprovedActionPlan   1.0.0 → 1.1.0
~~~

不建议修改 runtime.contracts.common.SCEMA_VERSION 使所有 VersionedContract 一起变成 1.1.0，因为此次变更只属于 M4 Planning Contracts。

正确方向应是仅对 ActionPlanDraft / ApprovedActionPlan 做 per-contract schema version bump，并增加 1.0 → 1.1 compatibility tests。

如果项目最终决定“新增 optional field 不 bump minor”，也必须形成显式 Schema Version 决议，不能默默扩大 frozen 1.0.0 surface。

本 Review 推荐：

~~~text
MINOR BUMP = YES
~~~

---

# 12. 不应在本次 Contract Amendment 中顺手解决的内容

此次 amendment 只解决 Knowledge Planning 的正式承载问题。

不得趁机修改：

~~~text
PlanningGoal
ActionStep
StrategySelection
memory_usage
capability_plan
tool_plan
response_strategy
M2 PolicyDecision
M5 ExecutionResult
M6 ValidatedResult
~~~

也不得同时实现真实 Knowledge Retrieval、Vector Search、BM25、Reranker、External API、Evidence Validation 或 Final Response。

---

# 13. 对 M4-IU4 的 Gate

在开始正式 IU4 Knowledge Planning production implementation 前，必须先完成一次独立 Contract Amendment。

建议新增中间步骤：

~~~text
M4-CA1
Knowledge Planning Contract Amendment
~~~

M4-CA1 只允许：

1. 新增 typed planning subcontracts；
2. 将三个 optional fields 加入 ActionPlanDraft / ApprovedActionPlan；
3. 增加 RetrievalMode structural enum；
4. 做 per-contract minor version 决议与兼容测试；
5. 更新 Canonical Registry / Schema Registry；
6. 不实现 Knowledge Planner 业务逻辑。

通过后：

~~~text
M4-IU4 Knowledge Planning
= ALLOWED
~~~

在 M4-CA1 通过前：

~~~text
M4-IU4
= BLOCKED_BY_CONTRACT_GAP
~~~

---

# 14. M4-CA1 必须验证的 Contract Invariants

至少：

~~~text
KCG-01 ActionPlan 名称仍禁止单独使用
KCG-02 M5 仍只消费 ApprovedActionPlan
KCG-03 Draft / Approved 的 Knowledge 三字段形状一致
KCG-04 required=false 不会要求 RetrievalPlan
KCG-05 required=true 在新 Planner / PlanValidator 中必须配套 RetrievalPlan + EvidenceRequirement
KCG-06 RetrievalPlan != ExecutionResult
KCG-07 EvidenceRequirement != EvidenceItem / EvidencePack / VerifiedFact
KCG-08 RetrievalMode 是基础设施控制值，KnowledgeDomain 等业务值仍 Domain-injected
KCG-09 旧 ActionPlanDraft / ApprovedActionPlan payload 仍可被新 Schema 解析
KCG-10 M0–M3 regression 保持绿色
KCG-11 IU1–IU3 regression 保持绿色
KCG-12 不通过 capability_plan / tool_plan / trace 隐藏 Knowledge Semantics
~~~

---

# 15. 最终架构链

Contract Amendment 后，知识型计划的正式链应为：

~~~text
M3 UnderstandingState
        ↓
M4 Goal / Candidate / Strategy
        ↓
KnowledgeNeedResolver
        ↓
KnowledgeRequirement
        ↓
RetrievalQueryBuilder
        ↓
RetrievalQuery
        ↓
RetrievalPlanner
        ↓
RetrievalPlan
        ↓
EvidenceRequirementPlanner
        ↓
EvidenceRequirement
        ↓
ActionPlanDraft 1.1
        ↓
PlanValidator
        ↓
M2 Policy Re-check
        ↓
ApprovedActionPlan 1.1
        ↓
M5 KnowledgeRetrievalSkill
        ↓
K0
        ↓
EvidencePack
        ↓
M6
        ↓
VerifiedFact / Claim Policy
~~~

始终保持：

~~~text
RetrievalPlan != Retrieval execution
EvidenceRequirement != Evidence
EvidencePack != VerifiedFact
Model knowledge != RAG Evidence
~~~

---

# 16. Review 决议

最终冻结本 Review 的建议：

~~~text
OPTION_A = APPROVED

KnowledgeRequirement
RetrievalPlan
EvidenceRequirement
→ typed M4 planning subcontracts
→ optional fields on ActionPlanDraft
→ same optional fields on ApprovedActionPlan

RetrievalQuery
→ typed M4 internal query object
→ projected into RetrievalPlan

Compatibility
= backward-compatible optional extension

Recommended schema version
= ActionPlanDraft / ApprovedActionPlan 1.1.0

M4-IU4
= BLOCKED until M4-CA1 Contract Amendment passes
~~~

因此下一步不是直接实现 Knowledge Planner，而是：

~~~text
NEXT_ALLOWED
= M4-CA1 Knowledge Planning Contract Amendment
~~~
