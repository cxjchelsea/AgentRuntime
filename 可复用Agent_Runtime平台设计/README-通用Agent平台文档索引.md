# 可复用 Agent Runtime 平台设计文档包

本目录由原单一业务 Agent 设计包整体平台化转换而来。

## 目标

将原先针对单一产品的设计，调整为可用于多个 Agent 项目的通用框架：

```text
Agent Runtime Core
+
Domain Extension
+
Business Package
+
Application
```

## 文档层次

### A. 平台总体设计
- `0-可复用Agent Runtime平台总体设计.md`
- `1-可复用Agent Runtime平台八种通用智能能力规范 V1.0.md`
- `2-可复用Agent Runtime平台八种通用智能与M0-M9实现映射规范 V1.0.md`

### B. Runtime Core
- M0 Runtime Skeleton
- M1 Input & Context
- M2 Safety / State / Policy
- M3 Understanding
- M4 Planning & Orchestration
- M5 Execution Framework
- M6 Result Validation
- M7 Response Planning & Generation
- M8 State & Memory Update

### C. Domain Extension
- M9 Domain Package & Business Capability Integration

### D. Shared Infrastructure
- K0 Knowledge & RAG Infrastructure
- **Agent Runtime Core Contract Canonical Registry V1.0（首批 Core Contract 唯一正式来源）**
- Core Schema Registry（其余对象；与 Canonical Registry 冲突的旧定义失效）
- Runtime Invariants
- Non-functional Engineering Baseline
- E2E Evaluation
- Progressive Implementation Plan
- Traceability Matrix

## 最重要的转换原则

1. 所有具体业务 Intent / Entity / Workflow / Skill / Tool 均不再属于 Runtime Core。
2. Domain Package 通过 Registry / Plugin / Adapter / Config 接入。
3. Runtime State 与 Domain State 分离。
4. Core Schema 与 Domain Schema 分离。
5. Capability Contract 与具体技术 Implementation 分离。
6. Prompt、知识、业务规则都可版本化并随 Domain Package 交付。
7. 新技术优先作为现有 Capability 的新实现，而不是修改 Runtime 主链。
8. 平台至少需要两个明显不同 Domain 的接入实践，才能证明抽象真正可复用。

## 关于文档中的具体业务例子

部分原始文档保留了内容播放、天气、健康、高风险等具体例子用于解释机制。平台化版本中，这些例子统一视为 **Domain 示例**，不是 Core 必须支持的固定业务枚举。真正项目必须由自己的 Domain Package 注册对应对象。
