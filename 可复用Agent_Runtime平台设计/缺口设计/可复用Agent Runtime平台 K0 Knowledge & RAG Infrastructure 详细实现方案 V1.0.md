# 可复用 Agent Runtime 平台  
# K0 Knowledge & RAG Infrastructure 详细实现方案 V1.0


> **平台化转换说明**  
> 本文已从单一业务 Agent 设计转换为 **可复用 Agent Runtime 平台**设计。除明确标记为 `Core` 的对象、接口、不变量和生命周期外，任何具体业务 Intent、Entity、Workflow、Skill、Tool、知识域、状态字段、规则、提示词或示例均视为 **Domain Package 示例**，不得硬编码进 Runtime Core。新项目应通过 Registry / Adapter / Plugin / Config 注入领域差异。
> 
> 平台固定边界：`Runtime Core` 尽量稳定；`Domain Extension` 插件化；`Business Package` 配置化；`Application` 负责产品装配。

> K0 为 M0～M9 之外的横向知识基础设施设计。  
> 它不是某一个业务模块，也不是某一个 Runtime Step，而是向 M4、M5、M6 以及 M9 各业务能力提供统一知识服务。
>
> K0 解决：
>
> ```text
> 知识从哪里来？
> 如何进入系统？
> 如何组织？
> 如何切分？
> 如何建立 Metadata？
> 如何建立向量 / 关键词 / 结构化索引？
> 查询如何改写？
> 如何做 Hybrid Retrieval？
> 如何融合和去重？
> 如何 Rerank？
> 如何形成 Evidence？
> 如何管理来源、版本、有效期？
> 如何增量更新和下架？
> 如何评估 Retrieval 是否真正有效？
> ```
>
> K0 不负责：
>
> ```text
> 判断当前轮是否应该查知识 —— M4
> 决定用户下一步行为 —— M4
> 执行具体业务 Action —— M5
> 判断检索内容是否能成为用户可声明事实 —— M6
> 生成最终自然语言回答 —— M7
> 保存用户个人长期记忆 —— M8
> ```

---

# 01. 阶段定位

K0 是整个系统的：

```text
Shared Knowledge Infrastructure
```

整体关系：

```text
                     ┌────────────────────────────┐
                     │ K0 Knowledge / RAG Infra   │
                     │                            │
                     │ Repository                 │
                     │ Taxonomy                   │
                     │ Chunk                      │
                     │ Metadata                   │
                     │ Vector Index               │
                     │ Sparse Index               │
                     │ Structured Index           │
                     │ Retrieval                  │
                     │ Rerank                     │
                     │ Evidence Pack              │
                     └──────────────┬─────────────┘
                                    │
                                    │
M3 Understanding                   │
        ↓                           │
M4 Planning ── RetrievalPlan ──────┤
        ↓                           │
M5 Execution ───────────────→ Knowledge Service
        ↓                           │
M6 Validation ←──── Evidence Pack ─┘
        ↓
M7 Response
```

因此：

```text
M4
=
计划查什么

K0
=
系统实际上拥有什么知识、
以及这些知识如何被检索

M5
=
执行 RetrievalPlan

M6
=
把 Retrieval Result 解释成可验证 Evidence
```

---

# 02. 阶段目标与八种智能映射

## 2.1 K0 总体目标

K0 最终建立：

```text
Knowledge Source Management

+

Knowledge Repository

+

Knowledge Taxonomy

+

Document Processing

+

Chunking

+

Metadata Enrichment

+

Embedding

+

Vector Index

+

Sparse / BM25 Index

+

Structured Lookup Index

+

Knowledge Ingestion Pipeline

+

Query Processing

+

Hybrid Retrieval

+

Metadata Filtering

+

Candidate Fusion

+

Deduplication

+

Reranking

+

Evidence Pack Generation

+

Version / Validity Governance

+

Incremental Update

+

Deletion / Deprecation

+

Retrieval Evaluation
```

---

## 2.2 与八种智能的关系

K0 本身不是独立智能目标，而是为以下能力提供知识基础：

| 智能能力 | K0作用 |
|---|---|
| 语义理解智能 | 为知识型理解提供领域定义、实体等支持 |
| 上下文智能 | 根据当前 Context 做 Query / Filter |
| 关系连续性智能 | 不负责用户 Memory，但明确与 Memory 隔离 |
| 情绪理解智能 | 可提供审核后的支持型交互知识 |
| 目标与隐含需求 | 为知识型 Goal 提供信息 |
| 对话策略智能 | 为 M4 知识策略提供可检索能力 |
| 主动性智能 | 为主动话题提供知识基础 |
| 自我约束智能 | 来源、版本、可信度、有效期控制 |

---

# 03. 职责边界

## 3.1 K0 负责

K0 负责：

```text
Knowledge Source 接入

Knowledge Document 标准化

知识分类

Chunk

Metadata

Embedding

Index

Search

Filter

Fusion

Deduplication

Rerank

Evidence Pack

来源信息

版本信息

有效期

更新

下架

删除

检索 Trace

Retrieval Eval
```

---

## 3.2 K0 不负责

K0 不负责：

```text
判断用户真实 Intent

决定这轮是否需要 Retrieval

决定最终业务 Action

判断医疗风险

直接生成用户回复

直接把检索结果认定为最终业务真相

管理用户个体 Memory
```

---

## 3.3 Knowledge 与 Memory 分离

必须正式固定：

```text
Knowledge
=
关于世界、内容、业务、医学、文化的外部知识

Memory
=
关于具体用户的个人事实、偏好、关系、近期状态
```

例如：

```text
“越剧发源于哪里”
→ Knowledge

“这个用户喜欢越剧”
→ Memory
```

禁止：

```text
把用户个人 Memory
直接混入公共 Knowledge Index
```

也禁止：

```text
公共知识结果
自动写成用户 Memory
```

---

# 04. 前置依赖与外部依赖

## 4.1 M4 依赖

K0 接收 M4 产生的：

```text
RetrievalPlan

KnowledgeRequirement

EvidenceRequirement
```

---

## 4.2 M5 依赖

M5 通过：

```text
KnowledgeRetrievalSkill
```

调用 K0。

---

## 4.3 M6 依赖

K0 必须为 M6 提供：

```text
Source

Version

Timestamp

Validity

Trust Level

Retrieval Metadata

Evidence Content
```

否则 M6 无法验证。

---

## 4.4 M9 依赖

各业务模块向 K0 提供：

```text
Domain Knowledge

Business Content

Approved Rules

Content Repository
```

---

## 4.5 基础设施依赖

可包括：

```text
Object / Document Store

Relational Database

Vector Database

Search Engine / BM25

Embedding Model

Reranker Model

Parser

Scheduler

Monitoring
```

具体技术选型不在 V1.0 强制绑定。

---

# 05. 输入

K0 有两类正式输入。

---

## 5.1 Knowledge Ingestion Input

```text
KnowledgeIngestionInput

source

raw_document

domain_hint

metadata_hint

version_info

governance_info
```

---

## 5.2 Retrieval Input

正式接收：

```text
RetrievalPlan
```

至少包含：

```text
domain

query

query_variants

retrieval_mode

filters

source_policy

vector_top_k

sparse_top_k

rerank_enabled

rerank_top_n

freshness_requirement

minimum_evidence
```

---

# 06. 输出

K0 有两类正式输出。

---

## 6.1 IngestionResult

```text
IngestionResult

document_id

version

chunk_count

index_status

validation_result

errors[]
```

---

## 6.2 RetrievalResult

```text
RetrievalResult

query_id

domain

status

evidence_items[]

retrieval_metadata

errors[]
```

---

# 07. 核心数据结构

# 7.1 KnowledgeSource

```text
KnowledgeSource

source_id

name

source_type

owner

domain

trust_level

update_frequency

license_info

governance_status

enabled
```

---

## 7.1.1 SourceType

建议：

```text
INTERNAL_APPROVED

INTERNAL_REFERENCE

EXTERNAL_OFFICIAL

EXTERNAL_TRUSTED

EXTERNAL_GENERAL

GENERATED

UNKNOWN
```

---

# 7.2 KnowledgeDocument

```text
KnowledgeDocument

document_id

domain

category

scenario

title

content

source_id

source_type

author

published_at

updated_at

ingested_at

version

status

valid_from

valid_to

audience[]

population[]

safety_level

language

tags[]

checksum

metadata
```

---

# 7.3 DocumentStatus

建议：

```text
DRAFT

REVIEWING

ACTIVE

DEPRECATED

EXPIRED

DELETED
```

默认 Retrieval：

```text
ACTIVE only
```

除非 RetrievalPlan 明确允许其他状态。

---

# 7.4 KnowledgeChunk

```text
KnowledgeChunk

chunk_id

document_id

parent_chunk_id

domain

category

scenario

section_path[]

content

summary

entities[]

topics[]

keywords[]

population[]

audience[]

risk_level

source_id

source_trust

document_version

valid_from

valid_to

embedding_version

chunk_version

token_count

metadata
```

---

# 7.5 KnowledgeTaxonomyNode

```text
KnowledgeTaxonomyNode

taxonomy_id

level

parent_id

name

code

description

domain

enabled

version
```

---

# 7.6 Domain Package 中的业务能力目录项映射

当前业务目录适合映射为：

```text
一级目录
→ domain

二级目录
→ category

三级目录
→ scenario / subtopic
```

例如：

```text
领域交互
→ 家庭话题
→ 子女工作忙
```

映射：

```text
domain = COMPANION

category = FAMILY

scenario = CHILDREN_BUSY
```

它主要服务：

```text
Knowledge Classification

Metadata Filter

Scenario Routing

Retrieval Evaluation
```

而不是：

```text
Intent Taxonomy
```

---

# 7.7 EmbeddingRecord

```text
EmbeddingRecord

chunk_id

embedding_model

embedding_version

dimension

vector

created_at
```

---

# 7.8 SparseIndexRecord

```text
SparseIndexRecord

chunk_id

terms

tokenization_version

index_version
```

---

# 7.9 RetrievalCandidate

```text
RetrievalCandidate

chunk_id

document_id

dense_score

sparse_score

fusion_score

metadata_match

freshness_score

source_trust

rerank_score

final_score
```

---

# 7.10 EvidenceItem

K0 最重要输出对象之一：

```text
EvidenceItem

evidence_id

chunk_id

document_id

content

source_id

source_type

source_trust

document_version

published_at

updated_at

valid_from

valid_to

retrieval_score

rerank_score

domain

category

scenario

metadata
```

---

# 7.11 EvidencePack

建议：

```text
EvidencePack

query_id

items[]

coverage

retrieval_mode

source_summary

freshness_summary

conflict_hints[]

metadata
```

注意：

```text
EvidencePack
!=
Verified Fact
```

M6 才负责验证。

---

# 08. 数据来源、存储与生命周期

# 8.1 Knowledge 生命周期

建议：

```text
Source
↓
Raw
↓
Parsed
↓
Normalized
↓
Reviewed
↓
ACTIVE
↓
Updated / Superseded
↓
DEPRECATED / EXPIRED
↓
Archived / Deleted
```

---

# 8.2 原始内容与派生内容分离

至少区分：

```text
Raw Document

Normalized Document

Chunk

Embedding

Index
```

避免：

```text
原文一改
但旧 Embedding 仍在线
```

---

# 8.3 Version

每次实质性内容变化：

```text
document_version++
```

并保留：

```text
previous_version
```

用于：

```text
Trace

Rollback

Audit
```

---

# 8.4 Validity

知识应支持：

```text
valid_from

valid_to
```

尤其：

```text
医学内容

业务规则

政策信息

时效内容
```

---

# 8.5 Deprecated

新版本生效后旧版本：

```text
DEPRECATED
```

默认不再参与正常 Retrieval。

---

# 8.6 Physical Delete

仅在：

```text
数据删除要求

版权要求

错误内容必须彻底删除
```

等情况下物理删除。

一般历史版本优先：

```text
DEPRECATED
```

---

# 09. 内部组件

建议 K0 包含：

```text
KnowledgeIngestionOrchestrator

SourceRegistry

DocumentParser

DocumentNormalizer

KnowledgeClassifier

TaxonomyMapper

Chunker

MetadataEnricher

KnowledgeValidator

EmbeddingService

VectorIndexer

SparseIndexer

StructuredIndexer

KnowledgeRepository

RetrievalService

QueryPreprocessor

MetadataFilter

DenseRetriever

SparseRetriever

StructuredRetriever

CandidateFusionEngine

Deduplicator

Reranker

EvidenceSelector

EvidencePackBuilder

VersionManager

ValidityManager

IncrementalUpdateManager

DeleteManager

KnowledgeTracer

RetrievalMetricsCollector
```

---

# 10. 运行时实现主流程

K0 有两条核心主链。

---

# 10.1 Knowledge Ingestion Pipeline

```text
Raw Source
    ↓
① Source Validation
    ↓
② Parse
    ↓
③ Normalize
    ↓
④ Domain / Taxonomy Classification
    ↓
⑤ Document Validation
    ↓
⑥ Semantic Chunking
    ↓
⑦ Metadata Enrichment
    ↓
⑧ Chunk Validation
    ↓
⑨ Embedding
    ↓
⑩ Vector Index
    ↓
⑪ Sparse Index
    ↓
⑫ Structured Index
    ↓
⑬ Publish ACTIVE Version
    ↓
Knowledge Repository
```

---

# 10.2 Retrieval Pipeline

```text
RetrievalPlan
    ↓
① Retrieval Plan Validation
    ↓
② Query Preprocessing
    ↓
③ Metadata / Domain Filter
    ↓
④ Retrieval Routing
    ↓
 ┌────────────┬────────────┬─────────────┐
 │ Dense      │ Sparse     │ Structured  │
 │ Retrieval  │ Retrieval  │ Lookup      │
 └─────┬──────┴──────┬─────┴─────┬───────┘
       ↓             ↓           ↓
⑤ Candidate Fusion
       ↓
⑥ Deduplication
       ↓
⑦ Eligibility / Validity Filter
       ↓
⑧ Rerank
       ↓
⑨ Evidence Selection
       ↓
⑩ Evidence Pack Build
       ↓
RetrievalResult
```

---

# 10.3 伪代码

```python
async def retrieve(plan: RetrievalPlan):

    validate_retrieval_plan(plan)

    query = query_preprocessor.process(
        plan.query,
        plan.query_variants
    )

    filters = metadata_filter_builder.build(
        plan.filters,
        plan.source_policy,
        plan.freshness_requirement
    )

    candidates = []

    if plan.retrieval_mode in ["VECTOR", "HYBRID"]:
        candidates += dense_retriever.search(
            query=query,
            filters=filters,
            top_k=plan.vector_top_k
        )

    if plan.retrieval_mode in ["KEYWORD", "HYBRID"]:
        candidates += sparse_retriever.search(
            query=query,
            filters=filters,
            top_k=plan.sparse_top_k
        )

    if plan.retrieval_mode == "STRUCTURED_LOOKUP":
        candidates += structured_retriever.lookup(
            query=query,
            filters=filters
        )

    merged = fusion_engine.merge(candidates)

    deduped = deduplicator.run(merged)

    valid = validity_filter.apply(deduped)

    if plan.rerank_enabled:
        ranked = reranker.rank(
            query=query,
            candidates=valid,
            top_n=plan.rerank_top_n
        )
    else:
        ranked = valid

    selected = evidence_selector.select(
        ranked,
        minimum_evidence=plan.minimum_evidence
    )

    return evidence_pack_builder.build(
        query=query,
        items=selected,
        plan=plan
    )
```

---

# 11. 各步骤详细实现

# Step 1：Source Intake

不是所有来源都能直接进入正式知识库。

必须记录：

```text
来源是谁

来源属于什么类型

是否经过审核

允许服务什么业务

是否允许用于健康相关回答

是否存在有效期
```

---

## 11.1 Health 来源

医学/健康类建议优先：

```text
INTERNAL_APPROVED

EXTERNAL_OFFICIAL

经业务/医学审核的 External Trusted
```

第一版不建议：

```text
任意网页内容
→ 自动入健康正式库
```

---

# Step 2：Document Parsing

支持：

```text
Markdown

Plain Text

Structured JSON

CSV

Database Row

HTML

PDF extracted text
```

不同来源通过 Adapter 转为统一：

```text
KnowledgeDocument
```

---

# Step 3：Normalization

至少处理：

```text
编码

空白

标题结构

列表

表格语义

无效噪声

重复页眉页脚

特殊符号

字段标准化
```

---

# Step 4：Taxonomy Classification

依据：

```text
Domain

Category

Scenario
```

映射当前业务目录。

---

## 11.4.1 自动分类可以使用 LLM

LLM 可以产生：

```text
taxonomy candidates
```

但正式发布前：

```text
需要规则 / Schema Validation
```

高风险知识可要求人工审核。

---

# Step 5：Document Validation

检查：

```text
source存在

domain合法

version存在

status合法

必要Metadata存在

内容非空

有效期合法

敏感/风险标记合法
```

---

# Step 6：Chunking

Chunk 是 RAG 效果的核心之一。

正式原则：

```text
Semantic Boundary
>
Fixed Character Boundary
```

---

## 11.6.1 通用 Chunk 原则

优先：

```text
标题层级

自然段

完整语义单元

FAQ

规则

完整步骤
```

必要时受：

```text
max_tokens
```

限制。

---

## 11.6.2 FAQ

建议：

```text
一个 Question + 完整 Answer
=
一个 Chunk
```

---

## 11.6.3 医学 / 健康知识

例如：

```text
失眠
├── 定义
├── 常见表现
├── 日常改善
├── 风险提示
└── 何时寻求帮助
```

应分别形成语义 Chunk。

不要把：

```text
日常建议最后半段
+
风险提示前半段
```

硬拼成一个 Chunk。

---

## 11.6.4 人物 / 文化知识

例如人物：

```text
基本信息

生平

代表作

重要事件
```

分别切分。

---

## 11.6.5 规则知识

一条完整规则及必要条件：

```text
尽量保持一个独立 Chunk
```

避免上下文脱离。

---

## 11.6.6 Parent / Child Chunk

可支持：

```text
Parent Chunk
=
较完整语义上下文

Child Chunk
=
检索粒度
```

检索命中 Child 后，可返回 Parent 上下文。

第一版可预留接口，不要求全部场景立即使用。

---

# Step 7：Metadata Enrichment

Chunk 至少补：

```text
domain

category

scenario

section

entities

topics

population

source

source_trust

version

validity
```

---

## 11.7.1 Metadata 比 Embedding 同样重要

不能把所有检索问题都交给：

```text
cosine similarity
```

例如：

```text
population = elderly
status = ACTIVE
source_trust >= HIGH
```

应先通过 Metadata 约束候选。

---

# Step 8：Embedding

每个 Chunk 生成：

```text
embedding
```

必须记录：

```text
embedding_model

embedding_version
```

未来换模型时可以重建。

---

# Step 9：Vector Index

用于：

```text
Semantic Search
```

必须支持：

```text
Metadata Filter
```

---

# Step 10：Sparse / BM25 Index

用于：

```text
Exact Term

Name

Drug Name

Title

Rare Keyword

Abbreviation
```

等查询。

---

# Step 11：Structured Index

部分知识不应该向量化为主要查询方式。

例如：

```text
content_id

drug_id

reminder_id

固定字段表

FAQ ID

规则 ID
```

应提供：

```text
Structured Lookup
```

---

# Step 12：Query Preprocessing

K0 接收的 Query 已主要由 M4 规划。

K0 可以继续做技术级处理：

```text
Tokenize

Normalize

Synonym Expansion

Alias Resolution

Stop-word processing
```

但：

```text
不能改变业务 Goal
```

---

# Step 13：Metadata Filter

在 Retrieval 前优先约束：

```text
domain

status

population

source policy

validity

safety level

category

scenario
```

---

# Step 14：Dense Retrieval

输入：

```text
normalized query
```

返回：

```text
Top-K semantic candidates
```

---

# Step 15：Sparse Retrieval

返回：

```text
Top-K keyword candidates
```

---

# Step 16：Hybrid Retrieval

通用默认建议：

```text
Dense
+
Sparse
```

不是固定必须。

由 M4：

```text
RetrievalPlan.retrieval_mode
```

决定。

---

# Step 17：Candidate Fusion

建议支持：

```text
RRF

Weighted Score Fusion
```

第一版可优先使用：

```text
简单、稳定、可配置
```

的 Fusion。

具体参数通过 Eval 决定。

---

# Step 18：Deduplication

常见重复：

```text
同 Document 多个近似 Chunk

相同内容不同版本

多来源转载

Dense / Sparse重复命中
```

需要去重。

---

## 11.18.1 版本去重

默认：

```text
最新 ACTIVE Version
```

优先。

旧 DEPRECATED：

```text
不参与普通 Retrieval
```

---

# Step 19：Validity Filtering

检查：

```text
Document ACTIVE?

valid_from <= now?

valid_to 是否已过期?

Source enabled?

当前 Policy 是否允许使用?
```

---

# Step 20：Rerank

Initial Retrieval：

```text
高 Recall
```

Rerank：

```text
提高 Precision
```

可综合：

```text
Query Relevance

Semantic Relevance

Keyword Match

Metadata Match

Population Match

Scenario Match

Source Trust

Freshness
```

---

## 11.20.1 Reranker 不决定事实真伪

Rerank 只说明：

```text
更适合当前 Query
```

不说明：

```text
这个 Chunk 一定是真的
```

事实验证仍在 M6。

---

# Step 21：Evidence Selection

最终不是简单：

```text
取最高分 Top 5
```

还应考虑：

```text
minimum evidence

source diversity

coverage

duplicate information

conflict hints
```

---

# Step 22：Evidence Pack

最终返回：

```text
Evidence Pack
```

而不是裸字符串列表。

---

# 12. 分支、路由与决策规则

# 12.1 Retrieval Mode

支持：

```text
VECTOR

KEYWORD

HYBRID

STRUCTURED_LOOKUP

EXTERNAL_API
```

其中 EXTERNAL_API 可由统一 Knowledge Gateway 暴露接口，但真正实时 API 通常属于 Tool 系统。

---

# 12.2 推荐默认模式

普通非结构化静态知识：

```text
HYBRID
```

---

# 12.3 Keyword 优先场景

例如：

```text
人名

药名

戏曲名

作品标题

精确术语

编号
```

---

# 12.4 Vector 优势场景

例如：

```text
自然语言描述

模糊表达

概念解释

语义近似问题
```

---

# 12.5 Structured Lookup

适合：

```text
ID

固定字段

业务表

FAQ Key

规则编号
```

---

# 12.6 Weather / News

不应以静态 Knowledge Index 作为当前实时事实来源。

应：

```text
M4
→ EXTERNAL_API Plan

M5
→ Weather / News Tool
```

K0 只可用于：

```text
背景知识
解释知识
```

---

# 12.7 Knowledge 与实时数据

必须区分：

```text
Static / Semi-static Knowledge

Realtime Data
```

不能：

```text
“今天东京天气”
→ 静态向量库
```

---

# 12.8 Health Domain

默认：

```text
source_policy = APPROVED_ONLY

status = ACTIVE

validity_required = true

source_trust >= configured threshold
```

---

# 12.9 无结果

如果：

```text
RetrievalResult = NO_MATCH
```

K0 不自动生成答案。

返回：

```text
NO_MATCH
```

给 M5/M6。

---

# 12.10 低质量结果

如果：

```text
Evidence不足
```

返回：

```text
INSUFFICIENT_EVIDENCE
```

而不是强行补齐。

---

# 12.11 冲突提示

K0 可以识别：

```text
多个高质量结果内容可能冲突
```

输出：

```text
conflict_hints[]
```

但最终事实冲突判断仍由 M6。

---

# 13. 与 M4 的接口

M4 输出：

```text
RetrievalPlan
```

K0 必须严格执行其合法约束。

例如：

```text
domain = HEALTH

filters:
population = elderly
status = ACTIVE

source_policy = APPROVED_ONLY
```

K0 不应为了增加 Recall：

```text
擅自取消 approved filter
```

---

# 14. 与 M5 的接口

M5 使用：

```text
KnowledgeRetrievalSkill
```

建议接口：

```python
class KnowledgeRetrievalSkill:

    async def execute(
        self,
        retrieval_plan,
        execution_context
    ) -> RetrievalResult:
        ...
```

M5 负责：

```text
Timeout

Retry

Cancellation

Trace

ExecutionResult
```

K0 负责：

```text
检索内部逻辑
```

---

# 15. 与 M6 的接口

M6 不能只拿：

```text
chunk text
```

必须拿：

```text
EvidenceItem
```

至少包括：

```text
content

source

trust

version

published_at

updated_at

validity

scores
```

M6 再判断：

```text
能不能成为 VerifiedFact

是否过期

是否冲突

Claim 能说到什么程度
```

---

# 16. 配置项与可变项

建议：

```text
chunking_rules

max_chunk_tokens

chunk_overlap

embedding_model

embedding_version

vector_top_k

sparse_top_k

fusion_method

fusion_weights

rerank_enabled

rerank_model

rerank_top_n

source_trust_rules

domain_filter_rules

validity_rules

taxonomy_version

dedup_rules

minimum_score

evidence_selection_rules
```

---

## 16.1 不应写死的参数

例如：

```text
TopK = 20

TopN = 5
```

可以作为初始配置，但不能当永久业务规范。

必须通过 Eval 优化。

---

# 17. 非功能约束

# 17.1 Retrieval Precision / Recall 平衡

Initial Retrieval：

```text
偏 Recall
```

Rerank：

```text
偏 Precision
```

---

# 17.2 Traceability

每个最终 Evidence 必须能追到：

```text
Source
Document
Version
Chunk
Index Version
Query
Retrieval Score
Rerank Score
```

---

# 17.3 Freshness

时效内容必须：

```text
validity aware
```

不能让过期知识长期参与检索。

---

# 17.4 Availability

Knowledge Service 不可用时：

```text
不得让业务层误认为“没有知识”
```

必须区分：

```text
NO_MATCH

SERVICE_UNAVAILABLE
```

---

# 17.5 Security

不同知识域可支持：

```text
Access Policy
```

例如：

```text
内部内容

医学审核内容

公开内容
```

权限可以不同。

---

# 17.6 Privacy

公共 Knowledge Index：

```text
不得混入用户个人敏感 Memory
```

---

# 17.7 Performance

建议支持：

```text
Metadata Pre-filter

Parallel Dense / Sparse Search

Cache

Batch Embedding
```

但第一版先保证正确性。

---

# 18. Trace / Logging / Observability

# 18.1 Ingestion Trace

至少记录：

```text
source_id

document_id

document_version

parser_version

chunking_version

chunk_count

metadata_result

embedding_version

index_version

publish_status
```

---

# 18.2 Retrieval Trace

至少记录：

```text
query_id

original_query

normalized_query

domain

filters

retrieval_mode

dense_candidates

sparse_candidates

fusion_result

dedup_result

rerank_result

final_evidence_ids

latency
```

---

# 18.3 No Match Trace

需要记录：

```text
是 Filter 太严？

没有候选？

Rerank后无合格结果？

知识库确实没有？
```

以便后续补知识。

---

# 19. 版本、兼容与变更影响

必须版本化：

```text
KnowledgeDocument Schema

KnowledgeChunk Schema

Taxonomy

Chunking Rules

Embedding Model

Embedding Version

Sparse Index

Reranker

Retrieval Policy

EvidencePack Schema
```

---

## 19.1 Embedding Model 更换

不能直接：

```text
新旧 Vector 混用
```

应：

```text
embedding_version
```

隔离，并规划重建。

---

## 19.2 Chunking Rule 更改

Chunk ID / Chunk Version 需要升级。

---

## 19.3 Taxonomy 变更

需要：

```text
Migration / Remapping
```

不能旧 Metadata 静默失效。

---

## 19.4 Source 内容更新

建议：

```text
新 Version ACTIVE

旧 Version DEPRECATED
```

---

# 20. 测试 / Eval

K0 必须有独立 Retrieval Eval。

---

# 20.1 Ingestion Test

覆盖：

```text
正常 Document

空文档

格式错误

Metadata缺失

重复文档

Version升级

Deprecated内容
```

---

# 20.2 Chunk Quality Eval

检查：

```text
语义完整性

Chunk过长

Chunk过短

跨章节污染

关键规则被切断
```

---

# 20.3 Retrieval Eval Dataset

建议：

```text
RetrievalEvalCase

query

domain

filters

expected_relevant_documents[]

expected_relevant_chunks[]

forbidden_sources[]

freshness_requirement
```

---

# 20.4 Retrieval 指标

至少：

```text
Recall@K

Precision@K

MRR

NDCG

Hit Rate

No-match Accuracy

Wrong-domain Retrieval Rate

Stale Retrieval Rate

Unapproved-source Retrieval Rate
```

---

# 20.5 Rerank Eval

对比：

```text
Before Rerank

After Rerank
```

检查：

```text
Precision提升

Top1质量

TopN覆盖
```

---

# 20.6 Metadata Filter Accuracy

重点：

```text
Domain

Population

Scenario

Status

Source Policy

Validity
```

---

# 20.7 Health Retrieval Eval

单独统计：

```text
Approved Source Recall

Unapproved Source Leakage

Outdated Knowledge Retrieval

Population Mismatch

Safety-rule Retrieval
```

---

# 20.8 End-to-End RAG Eval

完整链：

```text
M4 RetrievalPlan
→ K0 Retrieval
→ M6 Validation
→ M7 Response
```

需要评：

```text
Retrieval Sufficiency

Evidence Grounding

Unsupported Claim Rate

Answer Coverage
```

---

# 20.9 Error Buckets

建议：

```text
WRONG_DOMAIN

BAD_QUERY_REWRITE

OVER_FILTERING

UNDER_FILTERING

VECTOR_MISS

KEYWORD_MISS

BAD_FUSION

DUPLICATE_RESULTS

BAD_RERANK

STALE_RESULT

WRONG_VERSION

UNAPPROVED_SOURCE

INSUFFICIENT_EVIDENCE
```

---

# 21. Gate

## Gate K0-01

Knowledge 与 User Memory 正式分离。

---

## Gate K0-02

正式存在：

```text
KnowledgeDocument
KnowledgeChunk
EvidenceItem
```

---

## Gate K0-03

Document 与 Chunk 均有：

```text
source

version

status

validity
```

---

## Gate K0-04

Domain Package 中的业务能力目录项可映射为 Knowledge Taxonomy / Metadata。

---

## Gate K0-05

Chunk 不只采用固定字数粗暴切分。

---

## Gate K0-06

Semantic Chunking 规则正式存在。

---

## Gate K0-07

Embedding Version 可追踪。

---

## Gate K0-08

Vector Search 支持 Metadata Filter。

---

## Gate K0-09

Sparse / Keyword Retrieval 正式存在。

---

## Gate K0-10

Structured Lookup 正式存在。

---

## Gate K0-11

Hybrid Retrieval 正式支持。

---

## Gate K0-12

Dense / Sparse Candidate 支持 Fusion。

---

## Gate K0-13

Candidate Deduplication 正式存在。

---

## Gate K0-14

Rerank 作为独立阶段存在。

---

## Gate K0-15

RetrievalResult 不只返回裸 Chunk 文本。

---

## Gate K0-16

EvidenceItem 包含 Source / Version / Validity。

---

## Gate K0-17

Deprecated / Expired Document 默认不进入正常 Retrieval。

---

## Gate K0-18

Health Domain 可以强制 Approved Source Policy。

---

## Gate K0-19

天气 / 新闻实时事实不依赖静态向量库。

---

## Gate K0-20

NO_MATCH 与 SERVICE_UNAVAILABLE 正式区分。

---

## Gate K0-21

Rerank Score 不被当作事实可信度。

---

## Gate K0-22

EvidencePack 不直接等于 VerifiedFact。

---

## Gate K0-23

K0 不直接生成最终用户回复。

---

## Gate K0-24

所有最终 Evidence 可追溯至原 Document。

---

## Gate K0-25

知识更新存在 Version / Deprecation 流程。

---

## Gate K0-26

Embedding 更换不会静默混用不同版本。

---

## Gate K0-27

Retrieval 有独立 Eval Dataset。

---

## Gate K0-28

Metadata Filter 有自动化测试。

---

## Gate K0-29

Health Retrieval 有独立高风险测试。

---

## Gate K0-30

M4 → K0 → M5 → M6 的 Contract 可以端到端跑通。

---

# 22. 交付物

K0 最终至少形成：

```text
K0-01 Knowledge & RAG总体架构

K0-02 Knowledge Ingestion Pipeline

K0-03 Retrieval Pipeline

K0-04 KnowledgeSource Schema

K0-05 KnowledgeDocument Schema

K0-06 KnowledgeChunk Schema

K0-07 Knowledge Taxonomy规范

K0-08 357目录映射规范

K0-09 Document Parsing规范

K0-10 Document Normalization规范

K0-11 Semantic Chunking规范

K0-12 Metadata规范

K0-13 Embedding规范

K0-14 Vector Index规范

K0-15 Sparse / BM25 Index规范

K0-16 Structured Lookup规范

K0-17 Metadata Filter规范

K0-18 Dense Retrieval规范

K0-19 Sparse Retrieval规范

K0-20 Hybrid Retrieval规范

K0-21 Candidate Fusion规范

K0-22 Deduplication规范

K0-23 Rerank规范

K0-24 Evidence Selection规范

K0-25 EvidenceItem Schema

K0-26 EvidencePack Schema

K0-27 Source Trust规范

K0-28 Version / Validity规范

K0-29 Incremental Update规范

K0-30 Deprecation / Deletion规范

K0-31 Knowledge Service接口规范

K0-32 KnowledgeRetrievalSkill接口规范

K0-33 Retrieval Error Taxonomy

K0-34 Retrieval Trace规范

K0-35 Retrieval Eval Dataset

K0-36 Retrieval Metrics

K0-37 Health Knowledge治理规范

K0-38 K0自动化测试

K0-39 K0 Gate验证报告
```

---

# 附录 A：推荐代码结构

```text
knowledge/

├── models/
│   ├── source.py
│   ├── document.py
│   ├── chunk.py
│   ├── evidence.py
│   └── taxonomy.py
│
├── ingestion/
│   ├── orchestrator.py
│   ├── parser.py
│   ├── normalizer.py
│   ├── classifier.py
│   ├── chunker.py
│   ├── metadata.py
│   └── validator.py
│
├── embedding/
│   ├── service.py
│   └── models.py
│
├── index/
│   ├── vector.py
│   ├── sparse.py
│   ├── structured.py
│   └── manager.py
│
├── retrieval/
│   ├── service.py
│   ├── query.py
│   ├── filters.py
│   ├── dense.py
│   ├── sparse.py
│   ├── structured.py
│   ├── fusion.py
│   ├── dedup.py
│   └── rerank.py
│
├── evidence/
│   ├── selector.py
│   └── builder.py
│
├── governance/
│   ├── source_policy.py
│   ├── version.py
│   ├── validity.py
│   ├── update.py
│   └── deletion.py
│
├── repository/
│   ├── document_store.py
│   └── chunk_store.py
│
├── evaluation/
│   ├── dataset.py
│   ├── metrics.py
│   └── runner.py
│
└── tracing/
    └── knowledge_trace.py
```

---

# 附录 B：第一版推荐实现范围

第一版优先完成：

```text
KnowledgeDocument

KnowledgeChunk

Taxonomy

Source Registry

Ingestion Pipeline

Semantic Chunking

Metadata

Embedding

Vector Index

BM25 / Sparse Index

Hybrid Retrieval

Metadata Filter

Fusion

Dedup

Basic Rerank

EvidenceItem

EvidencePack

Version / Status

Retrieval Trace

Retrieval Eval
```

---

# 附录 C：第一版暂时不建议做

暂时不优先：

```text
复杂 GraphRAG

知识图谱推理

多跳 Agentic Retrieval

自动网页爬虫无限采集

Self-RAG

复杂 Query Decomposition Agent

复杂 Multi-hop Planner

自动知识事实合并

LLM自动修改正式知识
```

这些都不是当前第一阶段的必要条件。

---

# 附录 D：第一版不能推迟的能力

必须第一版具备：

```text
Source

Version

Status

Validity

Taxonomy

Metadata

Semantic Chunking

Vector + Sparse 双索引

Hybrid Retrieval

Dedup

Evidence Source Trace

Deprecated内容隔离

NO_MATCH / UNAVAILABLE区分

Retrieval Eval
```

---

# 附录 E：三个典型 Retrieval 场景

## E.1 越剧起源

M4：

```text
domain = CONTENT

query =
越剧 起源 发展历史

retrieval_mode =
HYBRID
```

K0：

```text
Filter:
domain = CONTENT

Dense Search
+
BM25

→ Fusion
→ Rerank
→ Evidence Pack
```

M6 再验证来源和事实。

---

## E.2 目标用户失眠日常建议

M4：

```text
domain = HEALTH

population = elderly

source_policy =
APPROVED_ONLY

retrieval_mode =
HYBRID
```

K0：

```text
Metadata Filter:
HEALTH
elderly
ACTIVE
approved source

↓
Hybrid Search
↓
Rerank
↓
Evidence Pack
```

---

## E.3 “今天北京天气怎么样”

M4：

```text
domain = WEATHER

retrieval_mode =
EXTERNAL_API
```

不进入静态：

```text
Vector Index
```

由 M5：

```text
WeatherTool
```

完成。

---

# 附录 F：K0 与 Memory 的最终边界

```text
K0 Knowledge
=
世界是什么

M8 Memory
=
这个用户是什么样、
最近发生了什么
```

例如：

```text
越剧属于中国戏曲
→ K0

用户喜欢越剧
→ M8 Memory
```

两者在 M1 / M4 可以同时被使用：

```text
User Memory:
喜欢越剧

Knowledge:
越剧相关内容
```

但底层治理、生命周期、可信边界不同。

---

# 附录 G：K0 与 M4 的最终边界

```text
M4
负责：

这轮为什么查？
查什么？
查哪个 Domain？
用什么模式？
过滤什么？
需要什么 Evidence？

K0
负责：

这些知识实际存在哪里？
如何被索引？
如何检索？
如何融合？
如何重排？
如何形成 Evidence？
```

---

# 附录 H：K0 与 M6 的最终边界

K0 输出：

```text
Evidence Candidate
```

M6 输出：

```text
Verified Fact
```

必须固定：

```text
Retrieval Relevant
!=
Fact True

Rerank Top1
!=
Authoritative Truth

Evidence Pack
!=
Allowed Claim
```

---

# 附录 I：最终知识链路

完整知识型 Runtime：

```text
用户问题
↓
M3
理解问题
↓
M4
Knowledge Need
↓
Domain Routing
↓
Query Planning
↓
RetrievalPlan
↓
M5
KnowledgeRetrievalSkill
↓
K0
Filter
↓
Dense + Sparse
↓
Fusion
↓
Dedup
↓
Rerank
↓
Evidence Pack
↓
M6
Evidence Validation
↓
Verified Facts
↓
Claim Policy
↓
M7
Natural Language Response
```

---

# 附录 J：K0 最终设计原则

最终固定：

```text
一、
Knowledge 和 User Memory 必须分离。

二、
知识库不是一个“向量数据库”。

三、
RAG 不是“用户问题直接做 Vector Search”。

四、
Document、Chunk、Metadata、Index、Retrieval、Rerank、Evidence
必须是清晰分层的系统。

五、
Domain Package 中的业务能力目录项主要作为 Knowledge Taxonomy / Metadata，
而不是 Intent Space。

六、
Chunk 优先遵守语义完整性，
而不是机械固定字数。

七、
默认静态知识检索采用 Dense + Sparse 的 Hybrid Retrieval。

八、
实时信息应进入实时 Tool / API，
而不是依赖静态知识库。

九、
检索相关度不等于事实可信度。

十、
每一条最终 Evidence 必须可追溯至 Source / Document / Version。

十一、
旧知识必须可以 Deprecated / Expired，
不能永远参与检索。

十二、
高风险健康知识必须有更严格的 Source Policy。

十三、
K0 只负责提供 Evidence Candidate，
最终 Truth 仍由 M6 决定。

十四、
Knowledge Infrastructure 应作为全系统统一基础设施，
而不是每个业务 Skill 单独搭一套 RAG。
```

最终可以把整个 K0 压缩为：

```text
M4：
我需要什么知识？

K0：
系统如何真正找到这些知识？

M5：
把检索实际执行出来。

M6：
查到的东西到底能不能相信、能不能说？

M7：
把验证后的知识表达给用户。
```