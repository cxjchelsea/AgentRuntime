# 可复用 Agent Runtime 平台  
# M6 Result Validation 详细实现方案 V2.0

> **Phase 0 Fix**  
> `ValidatedResult` 与 `claim_policy` / `claim_plan` 语义以 Canonical Registry 为准。  
> 文中单独出现的 `ActionPlan` 指上游 `ApprovedActionPlan`。

> **平台化转换说明**  
> 本文已从单一业务 Agent 设计转换为 **可复用 Agent Runtime 平台**设计。除明确标记为 `Core` 的对象、接口、不变量和生命周期外，任何具体业务 Intent、Entity、Workflow、Skill、Tool、知识域、状态字段、规则、提示词或示例均视为 **Domain Package 示例**，不得硬编码进 Runtime Core。新项目应通过 Registry / Adapter / Plugin / Config 注入领域差异。
> 
> 平台固定边界：`Runtime Core` 尽量稳定；`Domain Extension` 插件化；`Business Package` 配置化；`Application` 负责产品装配。

> 本版本为 M6 V1.0 的结构化重整版。  
> 保留原方案中 Evidence、UNKNOWN、Goal Validation、Tool Result Interpretation、Tool Success Semantics、BusinessStatus、Claim Policy、Claim Ladder、Conflict Resolution、Follow-up Requirement、State Recommendation、Validation Mode、Metrics、Eval、PoC、Gate、交付物等全部内容，并统一纳入 M0～M9 的 22 项实现方案模板。
>
> 本版本重点补强：运行时验证主流程、数据生命周期、跨 M 接口、非功能约束、版本治理以及 Validation Rule 的正式边界。

---

# 01. 阶段定位

M6 位于：

```text
M5 Execution
        ↓
ExecutionResult
        ↓
M6 Result Validation
        ↓
ValidatedResult
        ↓
M7 Response Generation
```

M5 已经解决：

```text
Tool 有没有调用？

代码是否报错？

Step 有没有完成？

Execution 是否 Timeout / Failed / Cancelled？
```

M6 要解决：

```text
这些执行结果到底说明了什么？

业务目标到底有没有真正完成？

哪些事实已经被真实确认？

哪些事实仍然只是未知？

有没有不同证据相互冲突？

哪些信息可以告诉用户？

哪些信息绝对不能告诉用户？
```

因此 M6 是：

> 真实执行结果与最终用户表达之间的强制事实验证层。

---

# 02. 阶段目标与八种智能映射

## 2.1 M6 总体目标

M6 最终要完成：

```text
ExecutionResult
+
ActionPlan
+
RuntimeContext
+
Validation Rules
        ↓
Evidence
        ↓
Fact
        ↓
Goal Validation
        ↓
Business Status
        ↓
Claim Policy
        ↓
ValidatedResult
```

最核心的事实链：

```text
Execution Success
!=
Business Success
!=
Verified Fact
!=
User-claimable Fact
```

---

## 2.2 与八种智能的关系

M6 主要承担：

```text
8. 自我约束智能
```

同时支撑：

```text
6. 对话策略智能
```

映射如下：

| 智能能力 | M6职责 |
|---|---|
| 语义理解智能 | 不负责 |
| 上下文智能 | 使用必要 Context 验证当前真实状态 |
| 关系连续性智能 | 验证 Memory 读写事实 |
| 情绪理解智能 | 不负责 |
| 目标与隐含需求推断智能 | 不负责 |
| 对话策略智能 | 为后续策略和回复提供真实结果 |
| 主动性智能 | 验证主动行为是否真的执行 |
| 自我约束智能 | M6 核心，实现 Truth Boundary |

因此可以固定：

```text
M2
=
Behavior Guardrail

M6
=
Truth Guardrail
```

即：

```text
一个可靠 Agent
=
不乱做
+
不乱说
```

---

# 03. 职责边界

## 3.1 M6 负责

M6 负责：

```text
ExecutionResult Schema Validation

Evidence Collection

Evidence Trust Evaluation

Evidence Freshness Evaluation

Tool Result Interpretation

Tool Success Semantics解释

Goal Validation

Business Status判断

Cross-source Consistency Check

Fact Classification

UNKNOWN处理

Claim Policy生成

Claim Ladder限制

Follow-up Requirement判断

State Recommendation生成

Validation Trace
```

---

## 3.2 M6 不负责

M6 不负责：

```text
重新调用 Tool

重新执行 Skill

重新执行 Workflow

重新规划 ActionPlan

重新理解用户

生成最终用户话术

直接修改 Runtime State

直接写 Memory
```

如果结果无法确认：

```text
M6 不重新执行
```

而是：

```text
followup.required = true
```

后续 Runtime 决定是否进入新的 M4/M5。

---

## 3.3 M6 不生成自然语言

M6 可以输出：

```text
allowed_claim:
NOTIFICATION_STATUS_UNKNOWN
```

但不能直接生成：

> “我现在还不能确认工作人员是否收到了消息。”

具体语言属于 M7。

---

# 04. 前置依赖与外部依赖

## 4.1 M0 依赖

M6 依赖 M0 提供：

```text
ValidatedResult 基础 Schema

Validator Interface

Trace

Error Framework

Schema Version机制
```

---

## 4.2 M2 依赖

M6 需要继承：

```text
Policy Snapshot

Safety Boundary

Response Truth Policy

Validation Mode

Hard Claim Restrictions
```

尤其：

```text
安全场景不得提升未经验证的事实
```

---

## 4.3 M4 依赖

M6 必须读取：

```text
ActionPlan

Primary Goal

Secondary Goals

Expected Actions

Tool Plan

Required Success Conditions
```

因为：

```text
如果不知道原本想做什么
就无法判断到底做成没有
```

---

## 4.4 M5 依赖

M6 的主要事实来源：

```text
ExecutionResult

Step Results

Skill Results

Workflow Result

Tool Results

Business Result

State Observations

Errors
```

---

## 4.5 外部证据依赖

部分业务验证可能需要：

```text
Device State

Database Read

External Callback

External Status Query

Workflow Checkpoint

System State
```

但 M6 不能凭空创造这些能力。

如果系统本身没有某种回执能力：

```text
M6 永远不能验证超过该能力边界的事实
```

---

# 05. 输入

建议正式定义：

```text
ValidationInput
```

结构：

```text
ValidationInput

execution_result

action_plan

runtime_context

policy_snapshot

validation_rules

validation_mode
```

---

## 5.1 ExecutionResult 主要使用字段

```text
plan_status

step_results

skill_results

workflow_result

tool_results

business_result

state_observations

errors

cancellation
```

---

## 5.2 ActionPlan 的使用目的

ActionPlan 告诉 M6：

```text
原本的目标是什么？

哪些 Step 是 Required？

哪些是 Optional？

Primary Goal是什么？

什么结果才算完成？
```

例如：

```text
Goal:
START_CONTENT_PLAYBACK
```

如果：

```text
SearchContent = SUCCESS
PlayTool = FAILED
```

就不能因为执行过程中有一个成功 Step 而判断业务成功。

---

# 06. 输出

M6 唯一正式输出：

```text
ValidatedResult
```

它向 M7/M8 提供：

```text
业务到底成功没有

哪些事实已经确认

哪些仍未确认

哪些互相冲突

哪些可以对用户说

哪些绝对不能说

是否需要后续动作

推荐的状态变化依据
```

---

# 07. 核心数据结构

# 7.1 ValidatedResult

建议：

```text
ValidatedResult

schema_version

metadata

validation_status

goal_validation

verified_facts

unverified_facts

conflicting_facts

claim_policy

business_status

followup

state_recommendation

errors

quality
```

---

# 7.2 metadata

```text
validation_id

execution_id

plan_id

request_id

validator_version

rule_version

created_at
```

---

# 7.3 ValidationStatus

建议冻结：

```text
VALIDATED

PARTIALLY_VALIDATED

NOT_VALIDATED

CONFLICTED

UNKNOWN
```

---

## VALIDATED

表示：

```text
关键证据充分

且不存在重要冲突
```

---

## PARTIALLY_VALIDATED

表示：

```text
部分事实确认

部分事实未知
```

---

## NOT_VALIDATED

表示：

```text
现有证据不足以验证关键业务事实
```

---

## CONFLICTED

表示：

```text
关键证据来源互相矛盾
```

---

## UNKNOWN

表示：

```text
当前无法确定真实状态
```

---

# 7.4 GoalValidation

```text
GoalValidation

goal_id

goal_type

status

evidence_ids[]

missing_evidence[]

reason
```

---

# 7.5 GoalStatus

```text
COMPLETED

PARTIALLY_COMPLETED

NOT_COMPLETED

UNKNOWN
```

---

# 7.6 VerifiedFact

```text
VerifiedFact

fact_id

fact_type

value

confidence_level

evidence_ids[]

source_type

observed_at

valid_until
```

---

# 7.7 ConfidenceLevel

不建议使用看似精确但无校准依据的小数概率。

建议：

```text
CONFIRMED

STRONGLY_SUPPORTED

LIMITED

UNKNOWN
```

只有：

```text
CONFIRMED
或
STRONGLY_SUPPORTED
```

才适合高确定性用户声明。

---

# 7.8 SourceType

例如：

```text
TOOL_RESULT

EXTERNAL_CALLBACK

DEVICE_STATE

DATABASE_STATE

WORKFLOW_STATE

SYSTEM_STATE
```

---

# 7.9 UnverifiedFact

```text
UnverifiedFact

fact_type

candidate_value

reason

missing_evidence[]

risk_if_claimed
```

表示：

> 可能成立，但当前没有足够证据升级为事实。

---

# 7.10 FactConflict

```text
FactConflict

fact_type

source_a

value_a

source_b

value_b

resolution_status
```

---

# 7.11 ConflictResolutionStatus

```text
RESOLVED

UNRESOLVED
```

---

# 7.12 BusinessStatus

```text
BusinessStatus

status

code

summary

completed

partial
```

---

# 7.13 BusinessStatus.status

建议：

```text
SUCCESS

PARTIAL_SUCCESS

FAILED

UNKNOWN

WAITING
```

---

## WAITING

非常重要。

例如：

```text
通知请求已经提交

但还在等待工作人员回执
```

这时：

```text
WAITING
```

而不是：

```text
SUCCESS
```

---

# 7.14 ClaimPolicy

```text
ClaimPolicy

allowed_claims[]

forbidden_claims[]

conditional_claims[]

required_qualifiers[]

certainty_level
```

---

# 7.15 ClaimCertainty

```text
HIGH

MEDIUM

LOW

UNKNOWN
```

---

# 7.16 FollowupRequirement

```text
FollowupRequirement

required

type

reason

target

urgency
```

类型：

```text
RETRY_REQUIRED

STATUS_CHECK_REQUIRED

USER_CONFIRMATION_REQUIRED

SYSTEM_REPLAN_REQUIRED

WORKFLOW_CONTINUATION

NONE
```

---

# 7.17 StateRecommendation

```text
StateRecommendation

recommended_business_state

reason

evidence_ids[]
```

它只是推荐。

真正 State 修改仍属于 M8 + State Engine。

---

# 7.18 ValidationEvidence

```text
ValidationEvidence

evidence_id

source

source_id

field

value

timestamp

trust_level
```

---

# 7.19 TrustLevel

建议：

```text
AUTHORITATIVE

DIRECT

SECONDARY

INFERRED
```

通常：

```text
AUTHORITATIVE
DIRECT
```

才适合强事实声明。

---

# 7.20 ValidationRule

```text
ValidationRule

rule_id

target_goal

target_action

required_evidence[]

optional_evidence[]

success_conditions[]

failure_conditions[]

unknown_conditions[]

claim_rules[]
```

---

# 08. 数据来源、存储与生命周期

# 8.1 ValidationResult 生命周期

一般属于：

```text
Turn-Level
```

但关键结果可以进入：

```text
Event Store
Workflow State
State Update
Memory Update
```

由 M8 决定。

---

# 8.2 VerifiedFact 生命周期

不是所有事实都永久有效。

例如：

```text
playback_status = PLAYING
```

具有很强时效性。

所以建议：

```text
observed_at
valid_until
```

必须存在。

---

# 8.3 Evidence Freshness

例如：

```text
20分钟前
PlaybackStatus = PLAYING
```

不能证明：

```text
现在仍然 PLAYING
```

因此 M6 必须支持：

```text
STALE_EVIDENCE
```

---

# 8.4 UNKNOWN 生命周期

UNKNOWN 是：

```text
当前证据不足
```

不代表永久未知。

后续可能通过：

```text
Callback

Status Check

Workflow Continuation
```

变成可验证状态。

---

# 8.5 Conflict 生命周期

未解决 Conflict：

```text
UNRESOLVED
```

在当前 Turn 不得被静默抹掉。

---

# 8.6 ClaimPolicy 生命周期

ClaimPolicy 默认只针对：

```text
当前 ValidatedResult
```

不能永久套用到未来不同状态。

---

# 8.7 Follow-up 生命周期

FollowupRequirement 一旦进入新 Runtime Cycle：

```text
由新的 ActionPlan / Workflow 接管
```

当前 M6 不自行持续执行。

---

# 09. 内部组件

建议 M6 包含：

```text
ResultValidationOrchestrator

SchemaValidator

EvidenceCollector

EvidenceTrustEvaluator

EvidenceFreshnessChecker

ToolResultInterpreter

GoalValidator

ConsistencyChecker

FactClassifier

ClaimPolicyValidator

ClaimLadderResolver

FollowupResolver

StateRecommendationBuilder

ValidationAggregator

ValidationRuleRegistry

ToolInterpretationRegistry

ClaimPolicyRegistry
```

---

# 10. 运行时实现主流程

M6 正式运行时主流程：

```text
ExecutionResult
+
ActionPlan
+
RuntimeContext
+
Policy Snapshot
+
Validation Rules
        ↓
① Validation Input / Schema Check
        ↓
② Select Validation Mode
        ↓
③ Select Goal / Tool Validation Rules
        ↓
④ Collect Evidence
        ↓
⑤ Evaluate Evidence Trust / Freshness
        ↓
⑥ Interpret Tool Results
        ↓
⑦ Validate Primary / Secondary Goals
        ↓
⑧ Cross-source Consistency Check
        ↓
⑨ Classify Facts
        ↓
⑩ Build BusinessStatus
        ↓
⑪ Apply Claim Policy / Claim Ladder
        ↓
⑫ Resolve Follow-up Requirement
        ↓
⑬ Build State Recommendation
        ↓
⑭ Aggregate ValidatedResult
        ↓
M7 / M8
```

---

## 10.1 伪代码

```python
async def validate(
    execution_result,
    action_plan,
    runtime_context,
    policy_snapshot
):

    schema_validator.validate(
        execution_result,
        action_plan
    )

    mode = validation_mode_resolver.resolve(
        action_plan,
        policy_snapshot
    )

    rules = validation_rule_registry.select(
        action_plan,
        execution_result,
        mode
    )

    evidence = await evidence_collector.collect(
        execution_result,
        runtime_context,
        rules
    )

    usable_evidence = evidence_evaluator.evaluate(
        evidence
    )

    interpreted_results = tool_result_interpreter.interpret_all(
        execution_result.tool_results
    )

    goal_validation = goal_validator.validate(
        action_plan,
        interpreted_results,
        usable_evidence,
        rules
    )

    conflicts = consistency_checker.check(
        usable_evidence,
        interpreted_results
    )

    facts = fact_classifier.classify(
        usable_evidence,
        interpreted_results,
        conflicts
    )

    business_status = business_status_builder.build(
        goal_validation,
        facts,
        conflicts
    )

    claim_policy = claim_policy_validator.build(
        facts,
        business_status,
        policy_snapshot,
        rules
    )

    followup = followup_resolver.resolve(
        goal_validation,
        facts,
        business_status
    )

    state_recommendation = state_recommendation_builder.build(
        facts,
        business_status
    )

    return validation_aggregator.build(
        goal_validation,
        facts,
        conflicts,
        business_status,
        claim_policy,
        followup,
        state_recommendation
    )
```

---

# 11. 各步骤详细实现

# Step 1：Schema Validation

第一步验证：

```text
ExecutionResult 是否完整

ActionPlan 是否匹配

execution_id 是否存在

Step 是否属于该 Plan

ToolResult 是否属于该 Execution

Status 是否合法
```

---

## 11.1.1 Schema Invalid

如果结构损坏：

```text
validation_status =
NOT_VALIDATED
```

不能继续把残缺结果解释为真实事实。

---

# Step 2：Validation Mode

建议：

```text
FAST

STANDARD

STRICT
```

---

## FAST

适合：

```text
本地低风险、可直接读取真实结果的动作
```

例如：

```text
音量设置
```

---

## STANDARD

普通业务：

```text
播放

天气

新闻

普通提醒
```

---

## STRICT

用于：

```text
求助

高风险情绪

关键通知

健康相关关键状态
```

具体模式由：

```text
M2 Policy / 业务配置
```

决定。

M6 不自行重新判断安全级别。

---

# Step 3：Validation Rule Selection

根据：

```text
Goal

Action

Tool

Validation Mode
```

选择：

```text
ValidationRule
```

例如：

```text
START_CONTENT_PLAYBACK
```

规则可能要求：

```text
PlayTool Result

Playback State
```

---

# Step 4：Evidence Collection

按 Goal 收集证据。

来源包括：

```text
TOOL_RESULT

DEVICE_STATE

EXTERNAL_CALLBACK

DATABASE_READ

WORKFLOW_CHECKPOINT

SYSTEM_STATE
```

---

## 11.4.1 Evidence Requirement Registry

每个 Goal / Action 应定义：

```text
required_evidence

optional_evidence
```

而不是 M6 临时猜需要查什么。

---

# Step 5：Evidence Trust / Freshness

M6 判断：

```text
证据来源可信程度

证据是否当前有效
```

例如：

```text
DeviceState
当前查询结果
```

通常比：

```text
10分钟前的本地缓存
```

可信。

---

## 11.5.1 推荐证据优先级

```text
直接真实状态查询
>
外部系统明确回执
>
Tool业务响应
>
本地系统状态
>
推断状态
>
Planner预期
```

特别注意：

```text
Planner预期
```

不能当验证证据。

---

# Step 6：Tool Result Interpretation

不同 Tool 的：

```text
SUCCESS
```

语义不一样。

因此必须：

```text
ToolResult
↓
ToolResultInterpreter
↓
Evidence
```

而不能：

```text
status == SUCCESS
→ Business Success
```

---

## 11.6.1 Tool Success Semantics

每个 Tool Definition 应补充：

```text
success_semantics
```

说明：

```text
SUCCESS 到底证明什么
```

---

## 11.6.2 Weather Tool 示例

Tool：

```text
SUCCESS

temperature = 12
```

解释：

```text
Evidence:
weather.temperature = 12
```

---

## 11.6.3 Notification Tool 示例

若：

```text
SUCCESS = REQUEST_ACCEPTED
```

只能生成：

```text
notification.request_accepted = true
```

不能生成：

```text
notification.delivered = true
```

---

# Step 7：Goal Validation

逐个验证：

```text
Primary Goal

Secondary Goals
```

---

## 11.7.1 Primary Goal

Primary Goal 未完成时：

```text
BusinessStatus
```

通常不能为：

```text
SUCCESS
```

---

## 11.7.2 Secondary Goal

例如：

```text
ACKNOWLEDGE
+
PLAY_CONTENT
```

如果：

```text
ACKNOWLEDGE completed
PLAY_CONTENT failed
```

可以：

```text
Primary Goal = NOT_COMPLETED

Secondary Goal = COMPLETED

BusinessStatus =
PARTIAL_SUCCESS
```

---

# Step 8：Cross-source Consistency Check

多个来源互相核验。

例如：

```text
PlayTool = SUCCESS

DevicePlaybackState = STOPPED
```

产生：

```text
CONFLICTED
```

---

## 11.8.1 冲突处理原则

不能：

```text
为了方便选择成功结果
```

如果无法解决：

```text
Fact = UNKNOWN

validation_status = CONFLICTED
```

---

# Step 9：Fact Classification

所有候选事实最终分为：

```text
VERIFIED

UNVERIFIED

CONFLICTED
```

不允许：

```text
ASSUMED_TRUE
```

---

# Step 10：BusinessStatus Build

综合：

```text
Goal Validation

Fact Classification

Workflow Status

Conflict
```

生成：

```text
SUCCESS

PARTIAL_SUCCESS

FAILED

UNKNOWN

WAITING
```

---

# Step 11：Claim Policy / Claim Ladder

这是 M6 与 M7 的关键接口。

M6 不仅判断：

```text
事实是否为真
```

还判断：

```text
事实能不能以什么确定程度对用户表达
```

---

## 11.11.1 Technical Truth 与 User-facing Truth

例如：

```text
Technical Truth:
NotifyTool TIMEOUT
```

用户层允许表达的语义可能是：

```text
NOTIFICATION_STATUS_UNKNOWN
```

而不是暴露：

```text
HTTP timeout
```

---

## 11.11.2 Allowed Claims

M7 可以明确表达的事实。

---

## 11.11.3 Forbidden Claims

无证据时禁止表达：

```text
工作人员已收到

工作人员正在处理

家属正在赶来

药物一定安全

某个现实状态已经发生
```

---

## 11.11.4 Conditional Claims

例如只确认：

```text
notification.request_accepted
```

则可以表达：

```text
已经尝试提交通知请求
```

不能表达：

```text
对方已经收到
```

---

## 11.11.5 Required Qualifiers

允许要求 M7 使用类似语义：

```text
目前

暂时

系统显示

还不能确认
```

M6 只提供约束，不写最终句子。

---

# Step 12：Follow-up Requirement

当结果：

```text
FAILED

UNKNOWN

WAITING

PARTIAL_SUCCESS
```

可能需要后续动作。

---

## 11.12.1 Follow-up 类型

```text
RETRY_REQUIRED

STATUS_CHECK_REQUIRED

USER_CONFIRMATION_REQUIRED

SYSTEM_REPLAN_REQUIRED

WORKFLOW_CONTINUATION

NONE
```

---

## 11.12.2 M6 不执行 Follow-up

例如：

```text
STATUS_CHECK_REQUIRED
```

只是输出。

后续 Runtime 决定是否：

```text
进入新的 Plan
```

---

## 11.12.3 可查与不可查必须区分

如果外部系统没有：

```text
Status Query API
```

不能输出：

```text
STATUS_CHECK_REQUIRED
```

而应保留：

```text
UNKNOWN
```

---

# Step 13：State Recommendation

M6 根据已经确认的事实，可以给 M8：

```text
StateRecommendation
```

例如：

```text
playback_active
```

已确认：

```text
recommended_business_state =
PLAYBACK_ACTIVE
```

但：

```text
M6 不直接 set_state(S06)
```

---

# Step 14：Validation Aggregation

最后汇总：

```text
Goal Validation

Facts

Conflicts

BusinessStatus

ClaimPolicy

Followup

StateRecommendation
```

形成：

```text
ValidatedResult
```

---

# 12. 分支、路由与决策规则

# 12.1 No Evidence = No Verified Fact

核心硬原则：

```text
No Evidence
=
No Verified Fact
```

不能因为：

```text
Planner希望成功

Tool通常会成功

模型认为应该成功
```

就升级为事实。

---

# 12.2 UNKNOWN 是正式状态

必须允许：

```text
UNKNOWN
```

不能强迫系统：

```text
SUCCESS / FAILED
```

二值化。

例如：

```text
通知超时
```

如果接口无法证明成功或失败：

```text
UNKNOWN
```

才是正确结果。

---

# 12.3 保守验证原则

证据不足：

```text
只允许降低确定性
```

不能：

```text
提升确定性
```

即：

```text
可能成功
≠
已成功
```

---

# 12.4 Claim Ladder

建议为需要区分事实层级的业务建立：

```text
Claim Ladder
```

---

## 12.4.1 Notification Claim Ladder

```text
Level 1
通知请求已创建

Level 2
通知已发送

Level 3
通知已送达

Level 4
工作人员已确认

Level 5
工作人员正在处理
```

每一级必须有独立 Evidence。

---

## 12.4.2 Playback Claim Ladder

```text
Level 1
已找到内容

Level 2
已向播放器发送指令

Level 3
播放器状态 = PLAYING

Level 4
音频设备实际输出正常
```

系统能证明到哪一级，就只能声明到哪一级。

---

## 12.4.3 Weather Claim

Weather Tool 返回：

```text
temperature = 12
condition = rain
```

可验证的是：

```text
当前数据源返回：
12°C / rain
```

不能无依据延伸：

```text
今天肯定不会转晴
```

---

## 12.4.4 News Claim

News 必须至少检查：

```text
source

timestamp

publication_time
```

不能把：

```text
模型预训练记忆
```

作为当前 News Tool 的实时结果。

---

# 12.5 Playback Validation

例如：

```text
Goal:
START_CONTENT_PLAYBACK
```

如果：

```text
PlayTool = SUCCESS

PlaybackState = PLAYING
```

则：

```text
COMPLETED
```

如果：

```text
SearchContent = SUCCESS

PlayTool = FAILED
```

则：

```text
NOT_COMPLETED
```

---

# 12.6 Notification Validation

例如：

```text
create_help_event = SUCCESS

send_notification = REQUEST_ACCEPTED
```

M6：

```text
verified:
help_event_created
notification_request_accepted

unverified:
notification_delivered

forbidden:
staff_received
staff_responding
staff_on_the_way
```

---

# 12.7 Reminder Validation

如果：

```text
UpdateReminderTool = SUCCESS
```

并且接口本身只是：

```text
request accepted
```

则不能确认：

```text
reminder_updated
```

如果 Tool Result 是真实数据库事务确认，则可以确认。

---

# 12.8 Memory Validation

必须区分：

```text
write_requested

write_success

read_result

delete_success
```

---

## 12.8.1 Memory Candidate 不是 Memory Fact

M3：

```text
memory_candidate =
喜欢越剧
```

不代表：

```text
memory_saved = true
```

必须经过：

```text
M8
+
Memory Tool
+
M6 Validation
```

后才能成为真实存储事实。

---

# 12.9 Safety Event Validation

高风险场景必须严格区分：

```text
事件创建

通知请求

通知发送

通知送达

工作人员确认

处理完成
```

这些都是不同事实。

---

# 12.10 Medical Claim 限制

M6 必须继承 M2 的安全边界。

即使某 Tool 返回健康信息，也不能自动允许：

```text
诊断性结论

自行用药建议

无授权医学保证
```

除非产品范围、医学规则和证据链都明确支持。

---

# 12.11 Tool Success 不等于 Goal Success

固定：

```text
Tool SUCCESS
!=
Goal COMPLETED
```

因为 Goal 可能依赖多个 Step。

---

# 12.12 Execution Success 不等于 Business Success

即使：

```text
ExecutionResult.plan_status = SUCCESS
```

也只说明：

```text
执行器按照计划完成了调用
```

M6 仍需验证业务事实。

---

# 12.13 Verified Fact 不等于 Allowed Claim

例如：

```text
error_code = HTTP_502
```

是真实技术事实。

但：

```text
未必适合告诉用户
```

因此：

```text
Verified Fact
!=
User-facing Claim
```

---

# 13. 与前后 M 的接口

# 13.1 M0 → M6

提供：

```text
Validator Interface

ValidatedResult Schema

Trace

Error Framework
```

---

# 13.2 M2 → M6

提供：

```text
Policy Snapshot

Validation Mode

Safety Restrictions

Response Truth Rules
```

---

# 13.3 M4 → M6

提供：

```text
ActionPlan

Goal

Expected Business Outcome

Required Success
```

---

# 13.4 M5 → M6

正式输入：

```text
ExecutionResult
```

---

# 13.5 M6 → M7

M7 重点读取：

```text
BusinessStatus

VerifiedFacts

AllowedClaims

ForbiddenClaims

ConditionalClaims

RequiredQualifiers

Followup
```

正确链路：

```text
ExecutionResult
→ M6
→ ValidatedResult
→ M7
```

而不是：

```text
ExecutionResult
→ LLM自由解释
```

---

# 13.6 M6 → M8

M8 使用：

```text
ValidatedResult
```

决定：

```text
StateUpdate

TaskUpdate

EventUpdate

MemoryUpdate
```

不得直接以 M5 Tool Result 为事实依据。

---

# 13.7 M6 → 新 Runtime Cycle

若：

```text
followup =
SYSTEM_REPLAN_REQUIRED
```

则启动新的 Runtime Cycle。

正常情况下：

```text
M6 不直接调用 M4
```

---

# 14. 与业务模块的映射

# 14.1 领域交互

普通纯对话 Action 通常事实验证较轻。

主要检查：

```text
Action 是否真正完成

是否需要外部事实支撑
```

---

# 14.2 内容播放

重点验证：

```text
Search Result

PlayTool Result

Playback State

Playback Activity
```

---

# 14.3 情绪安抚

若只是：

```text
ACKNOWLEDGE
LISTEN
```

验证较轻。

如果调用：

```text
Content Tool
Human Help Tool
```

则按对应 Tool Rule 验证。

---

# 14.4 安全与领域事件

属于：

```text
STRICT Validation
```

重点：

```text
Event Creation

Notification

Callback

Workflow State

真实外部状态
```

---

# 14.5 领域提醒

重点：

```text
Reminder Status

Database Update

Escalation Event

Notification Result
```

---

# 14.6 领域任务交互

重点验证：

```text
Task Progress

Question / Answer State

Activity Completion
```

---

# 14.7 长期记忆

重点：

```text
Memory Read Result

Memory Write Result

Storage Existence

Delete Result
```

---

# 14.8 新闻天气

重点：

```text
Tool Data

Source

Timestamp

Publication Time

Freshness
```

---

# 15. 异常、超时与降级

# 15.1 Validator 自身异常

不能：

```text
默认成功
```

应：

```text
validation_status =
NOT_VALIDATED
```

---

# 15.2 Missing Tool Interpreter

新增 Tool 没有对应解释规则：

```text
MISSING_TOOL_INTERPRETER
```

其 Tool 结果只能：

```text
UNVERIFIED
```

---

# 15.3 Missing Validation Rule

对应 Goal 没有规则：

```text
MISSING_VALIDATION_RULE
```

不得自由推断成功。

---

# 15.4 Missing Evidence

记录：

```text
MISSING_EVIDENCE
```

并根据规则：

```text
UNKNOWN
或
PARTIALLY_VALIDATED
```

---

# 15.5 Stale Evidence

证据过期：

```text
STALE_EVIDENCE
```

不得作为当前强事实。

---

# 15.6 Conflicting Evidence

```text
CONFLICTING_EVIDENCE
```

无法解决：

```text
UNKNOWN / CONFLICTED
```

---

# 15.7 Validation Timeout

如果外部状态验证本身超时：

```text
VALIDATION_TIMEOUT
```

不默认失败，也不默认成功。

---

# 15.8 Claim Policy Violation

如果某候选 Claim 超过证据等级：

```text
CLAIM_POLICY_VIOLATION
```

必须进入：

```text
forbidden_claims
```

---

# 15.9 Validation Internal Error

兜底：

```text
VALIDATION_INTERNAL_ERROR
```

同时：

```text
NOT_VALIDATED
```

---

# 15.10 M6 Error Taxonomy

至少：

```text
INVALID_EXECUTION_RESULT

MISSING_EVIDENCE

STALE_EVIDENCE

CONFLICTING_EVIDENCE

MISSING_TOOL_INTERPRETER

MISSING_VALIDATION_RULE

CLAIM_POLICY_VIOLATION

UNSUPPORTED_CLAIM

VALIDATION_TIMEOUT

VALIDATION_INTERNAL_ERROR
```

---

# 16. 配置项与可变项

建议：

```text
validation_mode_mapping

goal_validation_rules

tool_success_semantics

evidence_trust_rules

evidence_freshness_rules

claim_ladders

claim_policy_rules

followup_rules

validation_timeout

rule_version
```

---

## 16.1 Tool Success Semantics 配置

例如：

```yaml
notification:
  success_means: REQUEST_ACCEPTED
```

而不是系统统一解释为：

```text
DELIVERED
```

---

## 16.2 Evidence Freshness 配置

不同事实可以不同：

```text
playback_state:
  ttl: very_short

weather_data:
  ttl: short

memory_write:
  ttl: persistent_confirmation
```

具体数值后续按业务评估确定。

---

# 17. 非功能约束

# 17.1 False Success 必须优先压低

M6 最大风险之一：

```text
实际未成功 / 未知

却被判成功
```

因此：

```text
False Success Rate
```

是最关键指标之一。

---

# 17.2 UNKNOWN 必须被允许

系统不能为了“体验流畅”而减少 UNKNOWN。

原则：

```text
应该 UNKNOWN 时保留 UNKNOWN
```

比假确定更重要。

---

# 17.3 Validation 应规则优先

第一版建议：

```text
规则

Evidence

Schema

State
```

为主。

不建议用 LLM 作为核心事实验证器。

---

# 17.4 验证延迟

低风险本地动作：

```text
FAST
```

尽快完成。

高风险外部状态：

```text
STRICT
```

允许增加必要验证，但仍应避免无边界等待。

---

# 17.5 可追踪性

任何：

```text
SUCCESS

FAILED

UNKNOWN

Allowed Claim

Forbidden Claim
```

都应该可以回答：

```text
为什么？
基于什么 Evidence？
用了哪个 Rule？
```

---

# 17.6 不制造不存在的观测能力

如果系统没有：

```text
配送回执
通知送达回执
音频物理输出检测
```

M6 不得假装可以验证。

---

# 18. Trace / Logging / Observability

每轮至少记录：

```text
execution_result_id

action_plan_id

validation_mode

selected_validation_rules

evidence_collected

evidence_rejected

evidence_trust

evidence_freshness

tool_interpretations

goal_validation

fact_classification

conflicts

business_status

allowed_claims

forbidden_claims

followup_decision

state_recommendation

final_validated_result
```

---

## 18.1 Rejected Evidence

必须记录：

```text
哪些 Evidence 被拒绝

为什么被拒绝
```

例如：

```text
PlaybackStatus=PLAYING

rejected because:
STALE_EVIDENCE
```

---

## 18.2 Rule Trace

至少记录：

```text
rule_id

rule_version
```

确保线上结论可以回溯到具体验证规则。

---

# 19. 版本、兼容与变更影响

# 19.1 ValidatedResult Schema Version

必须：

```text
ValidatedResult.schema_version
```

---

# 19.2 Validation Rule Version

每个 ValidationRule：

```text
rule_id

version
```

---

# 19.3 Tool Interpretation Version

Tool Success Semantics 改变属于重要行为变化。

建议：

```text
interpreter_version
```

---

# 19.4 Claim Policy Version

Claim Ladder / Forbidden Claims 也应版本化。

---

# 19.5 可配置变更

通常无需改 M6 Core：

```text
新增 Goal Validation Rule

新增 Tool Interpreter

调整 Evidence TTL

调整 Claim Ladder

新增普通 Claim Rule
```

---

# 19.6 新增 Tool

必须同时补：

```text
Tool Interpretation Rule

Success Semantics

Goal Validation Rule

Claim Policy
```

否则该 Tool 的结果不能升级为强事实。

---

# 19.7 Breaking Change

例如：

```text
修改 UNKNOWN 语义

改变 BusinessStatus 定义

改变 VerifiedFact 结构

改变 ClaimPolicy 契约

改变 GoalStatus 定义
```

会影响 M7/M8，必须升级版本。

---

# 20. 测试 / Eval

# 20.1 Schema Validation

测试：

```text
ExecutionResult完整

ExecutionResult残缺

ToolResult错绑定

非法Status
```

---

# 20.2 Goal Validation

测试：

```text
Goal完整成功

Goal部分成功

Goal失败

Goal未知
```

---

# 20.3 Tool Interpretation

确保不同 Tool 的：

```text
SUCCESS
```

按自身语义解释。

---

# 20.4 Evidence Priority

测试：

```text
ToolResult

DeviceState

Callback

DatabaseState
```

冲突时是否按规则处理。

---

# 20.5 Evidence Freshness

测试：

```text
当前证据

临界过期

明确过期
```

---

# 20.6 Conflict Detection

例如：

```text
Tool = SUCCESS

Device = STOPPED
```

必须产生 Conflict。

---

# 20.7 UNKNOWN Handling

重点测试：

> 应该 UNKNOWN 时，是否真的保留 UNKNOWN。

---

# 20.8 Claim Policy

同一个 ValidatedResult：

检查：

```text
哪些 allowed

哪些 forbidden

哪些 conditional
```

---

# 20.9 Follow-up Resolution

测试：

```text
可 Retry

可 Status Check

必须 Replan

Workflow Waiting

不可进一步确认
```

---

# 20.10 核心 Metrics

```text
Validation Success Rate

Business Goal Validation Accuracy

False Success Rate

False Failure Rate

Unknown Appropriateness

Claim Violation Rate

Conflict Detection Rate

Stale Evidence Rejection Rate

Unsupported Claim Rate

Validation Latency
```

---

# 20.11 False Success Rate

定义：

```text
真实 FAILED / UNKNOWN

却验证成 SUCCESS
```

目标必须极低。

---

# 20.12 False Failure Rate

真实成功：

```text
却因规则错误判失败
```

也需要控制。

---

# 20.13 Unknown Appropriateness

不能通过：

```text
强行判 SUCCESS / FAILED
```

来降低 UNKNOWN。

---

# 20.14 Claim Violation Rate

尤其：

```text
通知

求助

健康
```

场景目标：

```text
接近 0
```

---

# 20.15 ValidationEvalCase

建议：

```text
ValidationEvalCase

case_id

action_plan

execution_result

system_evidence

expected_goal_status

expected_verified_facts

expected_unverified_facts

expected_conflicts

expected_allowed_claims

expected_forbidden_claims

expected_followup
```

---

## 20.16 Eval 分类

至少：

```text
PLAYBACK

NOTIFICATION

HELP_EVENT

REMINDER

MEMORY

WEATHER

NEWS

TOOL_TIMEOUT

PARTIAL_SUCCESS

CONFLICTING_STATE

STALE_EVIDENCE

UNKNOWN_STATE

WORKFLOW_WAITING
```

---

# 21. Gate

## Gate M6-01

M6 正式输入至少包含：

```text
ExecutionResult

+

ActionPlan
```

---

## Gate M6-02

正式输出统一：

```text
ValidatedResult
```

---

## Gate M6-03

BusinessStatus 支持：

```text
SUCCESS

FAILED

PARTIAL_SUCCESS

WAITING

UNKNOWN
```

---

## Gate M6-04

UNKNOWN 是正式状态，不能被强制二值化。

---

## Gate M6-05

Tool SUCCESS 不自动等于 Business SUCCESS。

---

## Gate M6-06

每个重要 VerifiedFact 都必须具有 Evidence。

---

## Gate M6-07

没有 Evidence 的强事实不能进入 verified_facts。

---

## Gate M6-08

支持 Evidence Freshness。

---

## Gate M6-09

支持多个 Evidence 的 Conflict Detection。

---

## Gate M6-10

冲突无法解决时不得强行判成功。

---

## Gate M6-11

正式存在：

```text
allowed_claims

forbidden_claims
```

---

## Gate M6-12

通知场景可以区分：

```text
请求创建

请求提交

发送

送达

确认

处理
```

---

## Gate M6-13

M7 不需要重新解释原始 ToolResult 才能生成回复。

---

## Gate M6-14

M6 不生成最终自然语言回复。

---

## Gate M6-15

M6 不直接调用 Tool / Retry。

---

## Gate M6-16

M6 不直接修改 Runtime State。

---

## Gate M6-17

M6 可以产生 FollowupRequirement。

---

## Gate M6-18

M6 可以产生 StateRecommendation，但不能直接改 State。

---

## Gate M6-19

所有 ValidationRule 可追踪版本。

---

## Gate M6-20

False Success 存在专门自动化测试。

---

## Gate M6-21

Tool Success Semantics 已成为 Tool Contract 正式组成部分。

---

## Gate M6-22

Evidence Trust 与 Freshness 均进入验证流程。

---

## Gate M6-23

Planner 预期不能作为 Verified Evidence。

---

## Gate M6-24

Claim Ladder 能阻止系统跨事实层级表达。

---

# 22. 交付物

M6 最终至少形成：

```text
M6-01 Result Validation总体架构

M6-02 Runtime Validation主流程

M6-03 ValidatedResult Schema

M6-04 ValidationInput Schema

M6-05 Evidence Model

M6-06 Evidence Trust规范

M6-07 Evidence Freshness规范

M6-08 Tool Result Interpretation规范

M6-09 Tool Success Semantics规范

M6-10 Goal Validation规范

M6-11 BusinessStatus规范

M6-12 Fact Classification规范

M6-13 Conflict Resolution规范

M6-14 Claim Policy规范

M6-15 Claim Ladder规范

M6-16 UNKNOWN状态规范

M6-17 Followup Requirement规范

M6-18 State Recommendation规范

M6-19 Validation Mode规范

M6-20 GoalValidation Registry

M6-21 Tool Interpretation Registry

M6-22 ClaimPolicy Registry

M6-23 Validation Error Taxonomy

M6-24 Validation Trace规范

M6-25 M6 Eval Dataset

M6-26 M6 Metrics

M6-27 M6自动化测试

M6-28 M6 Gate验证报告
```

---

# 附录 A：推荐代码结构

```text
validation/

├── orchestrator.py
├── models.py
├── schemas.py
├── errors.py
├── mode.py
│
├── evidence/
│   ├── collector.py
│   ├── models.py
│   ├── trust.py
│   └── freshness.py
│
├── tools/
│   ├── interpreter.py
│   ├── registry.py
│   └── semantics.py
│
├── goals/
│   ├── validator.py
│   ├── registry.py
│   └── rules.py
│
├── consistency/
│   └── checker.py
│
├── facts/
│   ├── classifier.py
│   └── registry.py
│
├── claims/
│   ├── policy.py
│   ├── ladder.py
│   └── registry.py
│
├── followup/
│   └── resolver.py
│
├── state/
│   └── recommendation.py
│
└── config/
```

---

# 附录 B：Registry

建议至少建立：

```text
GoalValidationRegistry

ToolInterpretationRegistry

ClaimPolicyRegistry
```

这样未来新增：

```text
VideoCallSkill
```

只需要注册对应：

```text
Goal Validation Rule

Tool Semantics

Claim Policy
```

无需修改 M6 Core。

---

# 附录 C：GoalValidationRule 示例

```text
goal:
START_CONTENT_PLAYBACK

required_evidence:
PlayToolResult

optional_evidence:
DevicePlaybackState

success_condition:
PlayTool SUCCESS
AND
DevicePlaybackState PLAYING

failure_condition:
PlayTool FAILED

unknown_condition:
Tool TIMEOUT
or
critical evidence unavailable
```

如果当前系统没有：

```text
DevicePlaybackState
```

验证规则可以退化到：

```text
PlayTool Result
```

但 Claim Level 必须随证据能力下降。

---

# 附录 D：ClaimRule 示例

```text
fact:
notification_request_accepted

allowed:
NOTIFICATION_REQUEST_ACCEPTED

conditional:
NOTIFICATION_SENT

forbidden:
NOTIFICATION_DELIVERED
STAFF_RECEIVED
STAFF_RESPONDING
STAFF_ON_THE_WAY
```

---

# 附录 E：典型 PoC

## E.1 播放完全成功

M5：

```text
PlayTool = SUCCESS
```

设备：

```text
PlaybackState = PLAYING
```

M6：

```text
Goal =
COMPLETED

BusinessStatus =
SUCCESS

Verified:
playback_started

AllowedClaim:
PLAYBACK_STARTED
```

---

## E.2 Tool 成功但设备没播放

```text
PlayTool = SUCCESS

PlaybackState = STOPPED
```

M6：

```text
Validation =
CONFLICTED

Goal =
UNKNOWN / NOT_COMPLETED

Forbidden:
PLAYBACK_STARTED
```

---

## E.3 通知请求已接受

Notify：

```text
REQUEST_ACCEPTED
```

无送达回执。

M6：

```text
Verified:
notification_request_accepted

Unverified:
notification_delivered

Forbidden:
staff_received
staff_responding
```

---

## E.4 通知 Timeout

M5：

```text
TIMEOUT
```

M6：

```text
BusinessStatus =
UNKNOWN
```

Allowed：

```text
NOTIFICATION_STATUS_UNKNOWN
```

Forbidden：

```text
NOTIFICATION_SUCCESS

NOTIFICATION_FAILED
```

除非 Tool Contract 已明确 Timeout 的业务语义。

---

## E.5 天气查询成功

```text
WeatherTool = SUCCESS

temperature = 12

condition = rain
```

M6：

```text
Verified:
temperature = 12
condition = rain
```

前提：

```text
Tool Schema Valid
Source Valid
Freshness Valid
```

---

## E.6 天气缺字段

```text
WeatherTool = SUCCESS

temperature = null
```

M6：

```text
temperature =
UNVERIFIED
```

M7 不得自行补温度。

---

## E.7 Reminder Update

Tool：

```text
updated_status = COMPLETED
```

数据库：

```text
COMPLETED
```

M6：

```text
reminder_completed =
CONFIRMED
```

---

## E.8 Workflow Waiting

HelpWorkflow：

```text
event created

notification request sent

waiting callback
```

M6：

```text
BusinessStatus =
WAITING
```

而非 SUCCESS。

---

## E.9 Memory 写入

Tool：

```text
SUCCESS

memory_id = M001
```

Storage：

```text
record exists
```

M6：

```text
memory_saved =
CONFIRMED
```

---

## E.10 过期 Evidence

```text
PlaybackState = PLAYING

observed_at = 20 minutes ago
```

当前验证：

```text
STALE_EVIDENCE
```

不得用于证明当前播放状态。

---

# 附录 F：第一版实现范围

第一版建议优先实现：

```text
ValidatedResult Schema

ValidationInput

Validation Mode

GoalValidationRegistry

ToolResultInterpreter

Tool Success Semantics

EvidenceCollector

Evidence Trust / Freshness

FactClassifier

ConflictChecker

BusinessStatus

ClaimPolicy

Claim Ladder

UNKNOWN

FollowupResolver

StateRecommendation

Validation Trace
```

---

# 附录 G：第一版不要过度实现

暂不需要：

```text
复杂概率推理

贝叶斯证据融合

多模型事实投票

自动可信度学习

复杂因果推断
```

第一版规则化验证更可靠。

---

# 附录 H：第一版不能推迟的能力

必须第一版具备：

```text
UNKNOWN

Evidence Source

Tool Success Semantics

Allowed Claims

Forbidden Claims

Claim Ladder

Conflict Detection

Evidence Freshness

Goal Validation

Trace
```

这些构成 M6 的核心价值。

---

# 附录 I：M0～M6 当前完整链路

```text
M0
Runtime Skeleton

↓

M1
Input & Context

↓

M2
Safety / State / Policy

↓

M3
Understanding

↓

M4
Planning & Orchestration

↓

M5
Execution Framework

↓

M6
Result Validation
```

此时系统已经形成：

```text
上下文
→
约束
→
理解
→
决策
→
执行
→
事实验证
```

---

# 附录 J：M6 与 M7 的最终边界

M6 决定：

```text
什么是真的？

什么不知道？

什么有冲突？

什么可以说？

什么不能说？
```

M7 决定：

```text
这些真话怎么说得自然、
简短、
适老、
有陪伴感？
```

因此：

```text
M6
=
Truth Boundary

M7
=
Expression Layer
```

---

# 附录 K：M6 最终设计原则

M6 的核心不是：

```text
判断 Tool 有没有报错
```

而是建立：

```text
Evidence

↓

Fact

↓

Business Status

↓

Allowed Claim
```

四层转换链。

最终原则固定为：

```text
没有证据，不升级为事实。

存在冲突，不假装一致。

无法确认，明确 UNKNOWN。

事实已确认，也不代表必须原样告诉用户。

系统只能说它真正知道、
并且被允许表达的事情。
```

因此：

> 一个好的 M6，不是尽可能给出确定答案，而是在证据不足时，有能力明确保留“不知道”。