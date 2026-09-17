# 可复用 Agent Runtime 平台
# 需求—能力—实现—测试追踪矩阵规范 V1.0


> **平台化转换说明**  
> 本文已从单一业务 Agent 设计转换为 **可复用 Agent Runtime 平台**设计。除明确标记为 `Core` 的对象、接口、不变量和生命周期外，任何具体业务 Intent、Entity、Workflow、Skill、Tool、知识域、状态字段、规则、提示词或示例均视为 **Domain Package 示例**，不得硬编码进 Runtime Core。新项目应通过 Registry / Adapter / Plugin / Config 注入领域差异。
> 
> 平台固定边界：`Runtime Core` 尽量稳定；`Domain Extension` 插件化；`Business Package` 配置化；`Application` 负责产品装配。

---

# 0. 文档定位

本文件定义整个项目的：

```text
Requirement Traceability Matrix
需求追踪矩阵
```

其核心目标是建立：

```text
需求
↓
业务能力
↓
Runtime实现
↓
Skill / Workflow / Tool
↓
数据 / API / Content依赖
↓
测试
↓
实现状态
↓
Release状态
```

的完整可追踪链。

本文件不负责重新定义需求，也不负责重新设计 Runtime。

它负责回答：

```text
一个需求到底在哪里被实现？

一个Runtime能力到底服务哪些需求？

一个Tool为什么存在？

一个功能到底有没有真正接入主链？

一个需求有没有测试证明已经完成？

Release中的每一项能力有没有遗漏？
```

---

# 1. 为什么必须建立 Traceability

当前项目已经存在：

```text
业务需求

F01～F10 Current Release Function

Domain Package 中的业务模块集合

三级业务能力目录

八种智能

M0～M9 Runtime设计

Skill

Workflow

Tool

E2E Evaluation
```

如果没有统一追踪体系，很容易出现：

```text
需求写了
但没有实现

代码写了
但不知道服务哪个需求

Skill存在
但没有接入Runtime

Tool存在
但没有被任何能力调用

测试存在
但不知道覆盖什么需求

功能声称“完成”
但只有代码，没有E2E
```

因此正式固定：

```text
CODE EXISTS
!=
IMPLEMENTED
!=
WIRED
!=
VERIFIED
!=
E2E PASSED
!=
RELEASE READY
```

---

# 2. 追踪主链

正式采用：

```text
Requirement
↓
Release Function
↓
Business Capability
↓
Runtime Intent / Goal
↓
M0～M9 Stage
↓
Skill / Workflow
↓
Tool / Content / API / Data
↓
Validation Rule
↓
Response Rule
↓
Update Rule
↓
Test Case
↓
Status
```

---

# 3. 追踪对象

正式定义以下追踪对象：

```text
REQ
Release Requirement

FUNC
Current Release Function

CAP
Business Capability

INTENT
Runtime Intent

GOAL
Runtime Goal

STAGE
M0～M9

SKILL

WORKFLOW

TOOL

DEP
Dependency

VAL
Validation Rule

RESP
Response Rule

UPDATE
Update Rule

TEST
Unit / Stage / Integration / E2E

REL
Release Item
```

---

# 4. ID规范

## Requirement

建议：

```text
REQ-001
REQ-002
```

---

## Release Function

沿用：

```text
F01
F02
...
F10
```

---

## Business Capability

建议：

```text
CAP-CONTENT-001
CAP-COMPANION-001
CAP-SAFETY-001
CAP-REMINDER-001
```

---

## Skill

```text
SKILL-CONTENT-001
```

---

## Workflow

```text
WF-HELP-001
WF-REMINDER-001
```

---

## Tool

```text
TOOL-PLAYBACK-001
TOOL-NOTIFY-001
```

---

## Validation Rule

```text
VAL-PLAYBACK-001
```

---

## Response Rule

```text
RESP-PLAYBACK-001
```

---

## Update Rule

```text
UPD-PLAYBACK-001
```

---

## Test

```text
UT-...
STAGE-...
INT-...
E2E-...
```

---

# 5. Traceability Matrix 主表

正式建议以下字段：

| 字段 | 说明 |
|---|---|
| Requirement ID | 原始需求ID |
| Requirement Name | 需求名称 |
| Release Function | F01～F10 |
| Business Module | Domain Package 中的业务模块集合 |
| Capability ID | M9 Capability |
| Capability Name | 业务能力 |
| Implementation Type | CONTENT / CONFIG / SKILL / WORKFLOW / TOOL / API / COMPOSITE |
| Runtime Intent | M3 Intent |
| Runtime Goal | M4 Goal |
| Runtime Stage | M0～M9涉及阶段 |
| Skill | 对应Skill |
| Workflow | 对应Workflow |
| Tool | 对应Tool |
| Content Dependency | 内容依赖 |
| API Dependency | API依赖 |
| Data Dependency | DB / Store依赖 |
| State Dependency | 依赖状态 |
| Policy Dependency | 依赖Policy |
| Validation Rule | M6规则 |
| Response Rule | M7规则 |
| Update Rule | M8规则 |
| Unit Test | 单元测试 |
| Stage Eval | 阶段评估 |
| Integration Test | 集成测试 |
| E2E Test | 端到端测试 |
| Dependency Status | 依赖状态 |
| Implementation Status | 实现状态 |
| Verification Status | 验证状态 |
| Release Status | 发布状态 |
| Owner | 负责人 |
| Notes | 备注 |

---

# 6. Implementation Type

正式采用：

```text
CONTENT

CONFIG

PROMPT_RESOURCE

SKILL

WORKFLOW

TOOL

EXTERNAL_API

COMPOSITE
```

---

# 7. Dependency Status

统一：

```text
AVAILABLE

STUB

PLANNED

NOT_FOUND

NOT_REQUIRED
```

---

# 8. Implementation Status

建议统一：

```text
DEFINED

DESIGNED

STUBBED

IMPLEMENTED

WIRED
```

---

# 9. Verification Status

统一：

```text
NOT_TESTED

UNIT_VERIFIED

STAGE_VERIFIED

INTEGRATION_VERIFIED

E2E_PASSED
```

---

# 10. Release Status

统一：

```text
NOT_READY

BLOCKED

CONDITIONALLY_READY

RELEASE_READY
```

---

# 11. Traceability 必须双向

不能只做：

```text
Requirement
→ Code
```

还必须支持反查：

```text
Tool
→ 被哪些Capability使用

Skill
→ 服务哪些Requirement

E2E Case
→ 覆盖哪些Requirement

Capability
→ 是否有真实依赖

Release Function
→ 是否全部有E2E证明
```

---

# 12. Requirement Coverage

每个 Requirement 至少必须追踪到：

```text
Capability
+
Implementation
+
Test
```

否则：

```text
TRACE_INCOMPLETE
```

---

# 13. Capability Coverage

每个 Capability 必须追踪到：

```text
Intent / Goal

Skill / Workflow

Dependency

Validation

Response

Update

E2E
```

缺任一关键项：

```text
Capability不能进入RELEASE_READY。
```

---

# 14. Tool Coverage

每个 Tool 必须能说明：

```text
谁调用它

为什么调用

是什么Side Effect

SUCCESS到底证明什么

哪个Validation Rule解释结果

有哪些Failure / Timeout测试
```

孤立 Tool 不应保留在生产 Registry 中。

---

# 15. Workflow Coverage

每个 Workflow 必须有：

```text
触发来源

允许State

状态流

Tool依赖

Timeout

Cancellation

Recovery

E2E
```

---

# 16. M6 Coverage

所有真实副作用能力必须具有：

```text
Validation Rule
```

禁止：

```text
Tool存在
但没有业务结果验证规则
```

---

# 17. M7 Coverage

所有用户可见业务结果必须有：

```text
Response / Claim Rule
```

至少明确：

```text
哪些可以说

哪些不能说

UNKNOWN怎么说
```

---

# 18. M8 Coverage

所有跨轮业务必须明确：

```text
State Update

Task Update

PendingQuestion

Context Update

Memory Rule
```

---

# 19. Test Coverage 分层

每项能力不要求所有类型测试数量一致，但至少判断是否适用：

```text
Unit

Stage Eval

Integration

E2E
```

---

# 20. 普通能力最低测试要求

至少：

```text
Happy Path

Failure Path

Timeout / UNKNOWN（如果有外部依赖）

Cross-turn（如果有状态）
```

---

# 21. Safety能力最低测试要求

必须额外：

```text
Preemption

Idempotency

Crash Recovery

Policy Blocking

Forbidden Claim
```

---

# 22. Memory能力最低要求

必须：

```text
Explicit Write

Correction

Temporary Override

Expiry

Wrong-user Isolation

Unavailable
```

---

# 23. 追踪矩阵示例：内容播放

```text
REQ:
用户可以请求播放内容

↓

FUNC:
F03 内容播放/控制

↓

CAP:
CAP-CONTENT-PLAYBACK

↓

INTENT:
PLAY_CONTENT

↓

GOAL:
START_PLAYBACK

↓

M4:
DIRECT_FULFILLMENT

↓

SKILL:
ContentSkill

↓

TOOL:
SearchContentTool
PlayTool
GetPlaybackStateTool

↓

M6:
VAL-PLAYBACK-STARTED

↓

M7:
RESP-PLAYBACK-RESULT

↓

M8:
UPD-PLAYBACK-STATE

↓

E2E:
E2E-CONTENT-001
E2E-CONTENT-002
E2E-CONTENT-003
```

---

# 24. 追踪矩阵示例：求助

```text
REQ
→ F04
→ CAP-HELP
→ HELP
→ HelpWorkflow
→ CreateHelpEventTool
→ NotificationTool
→ Notification Claim Ladder
→ Help Response Rule
→ Safety State Update
→ E2E-HELP-001～007
```

---

# 25. Requirement Coverage 指标

建议统计：

```text
Requirement Design Coverage

Requirement Implementation Coverage

Requirement Wiring Coverage

Requirement E2E Coverage

Requirement Release Coverage
```

---

# 26. Capability Coverage 指标

建议：

```text
Capability Dependency Completeness

Capability Validation Coverage

Capability E2E Coverage

Capability Release Readiness
```

---

# 27. Orphan Detection

必须能够发现：

```text
Orphan Requirement
没有实现路径

Orphan Capability
没有需求来源

Orphan Skill
没有Capability使用

Orphan Tool
没有Skill / Workflow使用

Orphan Test
没有覆盖对象

Untested Capability
没有E2E
```

---

# 28. Release Gate

一个 Release Function 只有满足：

```text
所有Required Capability已WIRED

所有Critical Dependency AVAILABLE

所有Critical E2E PASS

所有Safety Gate PASS

无Blocking Trace Gap
```

才能：

```text
RELEASE_READY
```

---

# 29. Traceability 更新规则

发生以下变更必须更新矩阵：

```text
Requirement修改

Capability新增/删除

Intent变更

Skill/Workflow变更

Tool替换

Dependency变化

Validation规则变化

E2E新增/失效

Release Scope变化
```

---

# 30. 不允许的做法

禁止：

```text
只在代码里记录关系

只靠开发人员记忆

需求完成靠口头确认

测试通过但不知道覆盖哪个Requirement

Capability标记完成但没有E2E
```

---

# 31. 与357三级能力的关系

当前三级目录尚未最终冻结，因此：

```text
本规范先冻结Traceability结构，
不冻结357具体映射。
```

等三级目录正式确定后，只需新增：

```text
Third-level Capability ID
```

作为一列接入现有矩阵。

无需重构体系。

---

# 32. 最终原则

```text
一、每个需求必须能追到实现。

二、每个实现必须能追到需求。

三、每个业务能力必须能追到真实依赖。

四、每个真实结果必须能追到验证规则。

五、每个用户可见结果必须能追到表达规则。

六、每个Release能力必须有E2E证据。

七、“完成”必须有状态和测试证明，而不是代码存在。

八、Traceability Matrix是项目真实完成度的唯一总视图。
```

至此：

```text
需求—能力—实现—测试追踪矩阵规范 V1.0
=
FROZEN
```