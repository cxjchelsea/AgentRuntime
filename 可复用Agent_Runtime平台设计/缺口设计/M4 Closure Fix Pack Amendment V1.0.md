# M4 Closure Fix Pack Amendment V1.0

> 适用范围：M4 Planning & Orchestration V2.1 Closure Review 后的三项阻塞修复。
> 本文件不重开 M0-M3，不改变 Canonical Contract，不扩大 M4 到 M5/K0/M6/M7。
> 与 M4 V2.1、M4 四项关键子设计冻结版发生 Closure 冲突时，以本文件为准。

## 1. 修复结论

本次 Fix Pack 处理三项阻塞：CF-1 Clarification / Active Interaction 责任模型收口；CF-2 Gate M4-39 重分类为 Cross-stage Deferred 并定义 Replan Entry Contract；CF-3 补齐 M4 Eval Harness 机制骨架。

本次修复不代表 Domain Golden Set 已完成，不代表业务规划质量达到上线阈值，不代表 Retrieve → Validate → Replan 已完成跨阶段 E2E，也不代表 M5 / K0 / M6 已实现或 Production Ready。

## 2. CF-1：Clarification / Active Interaction 最终责任模型

### 2.1 最终冻结决定

M4 Core 不再保留独立 ClarificationPlanner / ActiveInteractionPlanner 作为与 Strategy / Action 并列的第二套下一步行为决策器。

原因：M3 已输出 uncertainty / needs_clarification；M4 IU3 已完成 Legal Action Candidate 与 Strategy Selection；Domain 可注册 CLARIFY、WAIT、SILENCE、ACTIVE_* 等合法 Action / Strategy。若再增加独立 ClarificationPlanner / ActiveInteractionPlanner，会形成重复决策权并破坏单一合法 Action Space + Strategy Selection 主决策面的冻结边界。

### 2.2 Step 12 新定义

原 Step 12“Clarification / Active Decision”修订为“Clarification / Active Eligibility Projection”。其含义是：M3 uncertainty / needs_clarification + RuntimeContext + PolicyDecision + Domain injected eligibility / strategy rules → 进入 IU3 已存在的合法 Action / Strategy 空间，而不是新增第二个 Planner。

### 2.3 Clarification 正式表达方式

信息不足时：M3 needs_clarification=true → M4 中注册的 CLARIFY Action 进入合法 Candidate Space → Strategy Selection 选择 CLARIFY → M5 执行对应能力 → M7 生成实际确认问句。M4 不重新读取原始文本，不重新做 M3 Understanding。

### 2.4 Active Interaction 正式表达方式

主动互动通过 ActionCandidateProvider、CandidateEligibilityRule、StrategyEligibilityRule、StrategySelectionRule、RuntimeContext 与 PolicyDecision 表达，输出仍必须是 registered Action / Strategy，不引入隐藏行为通道。

因此：B-M4-001 = CLOSED_BY_ARCHITECTURE_AMENDMENT。

## 3. CF-2：Gate M4-39 Cross-stage Deferred

### 3.1 Gate 重分类

原 Gate M4-39“Retrieve → Validate → Replan”无法由 M4 单阶段独立证明，因为 Retrieve 属于 M5/K0，Validate 属于 M6，Replan 才重新进入 M4。

正式修订：Gate M4-39 CLASSIFICATION = CROSS_STAGE_DEFERRED；在 M4 Implementation Closure 中标记 NOT_APPLICABLE_FOR_M4_IMPLEMENTATION_CLOSURE。真正 E2E 在 M5 + M6 完成后验证。

### 3.2 Replan Entry Contract

新增内部合同 ReplanEntryRequest，字段为 request_id、prior_plan_id、trigger_stage、reason_codes、evidence_refs、preserve_goal。

约束：只接受 RESULT_VALIDATE 触发；必须引用上一份 plan_id；必须有明确 reason_codes；evidence_refs 只保存引用，不保存 Evidence / ValidatedResult 真值本体；不改变冻结 Planner 接口；不在 M4 内伪造 M5/M6。

未来跨阶段接线应为：M5 Execution → M6 Result Validation → ReplanEntryRequest → Runtime 开启新的 Planning Cycle → M4 基于新的 RuntimeContext / PolicyDecision 重新规划。禁止 M4 内部递归自调用，也禁止 M4 直接执行 Retrieve / Validate。

因此：B-M4-002 = CLOSED_BY_GATE_RECLASSIFICATION；登记 XG-M4-39 = DEFERRED_UNTIL_M5_M6。

## 4. CF-3：M4 Eval Harness

### 4.1 Core 与 Domain 职责

Core 负责 Eval Case Schema、Eval Result Schema、四类 Gate 分类、Gate Threshold Mechanism、Eval Runner 与聚合报告。Domain 负责真实 Golden Planning Set、业务标签、医疗/陪护/天气等 Domain 规则和真实上线阈值。

Core 不硬编码 HEALTH / WEATHER / CONTENT / 医疗诊断类别 / 陪护业务类别。

### 4.2 四类冻结 Gate

代码化为 POLICY、BEHAVIOR、MEMORY_TOOL、ACTIVE_SAFETY，对应原冻结的 Policy Gate、Behavior Gate、Memory/Tool Gate、Active/Safety Gate。

### 4.3 新增 Core Eval 对象

PlanningEvalCase、PlanningEvalResult、M4EvalGate、M4GateThresholds、M4GateSummary、M4EvalReport、PlanningCaseEvaluator、M4EvalRunner。

### 4.4 Runner 边界

M4EvalRunner 不调用真实医疗规则，不判断某业务 Action 是否医学正确，不发明 Golden Label，不自动生成真实 Golden Set，也不决定生产阈值。这些均由 Domain / Eval Package 注入。

每个冻结 Gate 至少需要一个 case，否则该 Gate 不能通过。默认机制阈值为 1.0，但 Domain 可以显式注入 M4GateThresholds；真实生产阈值不在 Core 冻结。

原设计建议 150～300 条 M4 Golden Planning Set。本次 Closure 不伪造这些业务样例。正式状态：Core Eval Harness = IMPLEMENTED；Domain Golden Planning Set = DEFERRED_TO_DOMAIN_PACKAGE；Production Planning Quality Gate = NOT_EVALUATED。

因此 M4 Core Implementation Closure 可以在机制层关闭，但不能宣称 M4 Business Eval Closure / Production Ready。

## 5. M4 Trace

Structured M4 Planning Trace 本次不作为 Closure blocker。登记 TD-M4-04 = NON_BLOCKING。Runtime 已具备 PLAN、PLAN_VALIDATE、POLICY_RECHECK 阶段 Trace。后续可扩展 planning_mode、goal resolution path、candidate count、strategy selection path、knowledge_required、retrieval_mode、selected action ids、validation codes、policy audit codes，但不得记录完整敏感 payload。

## 6. 修复后状态

B-M4-001 = CLOSED_BY_ARCHITECTURE_AMENDMENT
B-M4-002 = CLOSED_BY_GATE_RECLASSIFICATION
B-M4-003 = CLOSED_BY_CORE_EVAL_HARNESS

仍保留非阻塞债：TD-M4-01 Goal source namespace reservation；TD-M4-02 Domain CandidateEligibility optional；TD-M4-04 Structured Planning Trace。

跨阶段 Deferred Gate：XG-M4-39 Retrieve → Validate → Replan E2E = DEFERRED_UNTIL_M5_M6。

## 7. Fix Pack 关闭条件

合并前必须运行 pytest、mypy、ruff check、ruff format --check，并确认：Clarification / Active 不再被定义为独立 Core Planner；ReplanEntryRequest 不执行 Retrieve / Validate / Replan；M4-39 已明确 Cross-stage Deferred；四类 Eval Gate 均有机制层对象；Core Eval Harness 不含业务 taxonomy；Domain Golden Set 未被伪造为已完成。

满足后重新进行 M4 Closure Review，而不是自动宣称 M4 = CLOSED。