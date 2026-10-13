# GA-02 D2-C C1 — Production Host Publisher / Issuer / Durable CAS 物理设计与实施就绪评估 v0.1

> **状态：DESIGN CANDIDATE / PHYSICAL IMPLEMENTATION NOT READY（HOLD）**  
> **精确代码基线：** `main@d2d59ec4c97ed6a85a13a5f36551752ad2c0f067`（仅合入 PR #117 的 `NON_PRODUCTION_SIMULATION` 测试参考模型）。  
> **相关上游：** PR #116 `feeb6218cb2e652fe3695b43f3ff320b7d92bd86` 仍是 **未合并 Draft**。其 §12–14 为本文件的**待审设计依据**，不得当作当前 main 已冻结生产规范；冲突须先修订上游、独立复审。  
> **变更纪律：** 本文件只提出候选物理架构、数据库映射、失败语义、实验计划与 Gate；不创建生产 issuer、持久库迁移、可信证据、调用方绑定或 Tool 权限。本文件自身不代表授权实施或合并。

## 1. 执行结论和范围

**C1 目标仅是由 Application/Host 控制的可信 Catalog 快照出版，以及一份经过真实签发者验证的、不可执行的来源与依赖证明。** 它不是智能体决策循环，不是 AgentRuntime 的新 Runtime，也不发布 `DomainBinding` / `BoundRunDomain`、不授予 Agent/Tool/Skill 执行权、不替换 C0 的 `UNTRUSTED_DIAGNOSTIC_ONLY` 角色、不允许通过字符串或 Hash 升级角色。D2-D/D3 保持独立 HARD HOLD。

**实施准备度：`NOT_READY / HARD_HOLD`。** 最多可以授权下一步**生产环境和事务能力调查、合同冻结与真实持久库的隔离验证**，不能直接进入 Host Issuer 正式接线。PR #117 的 1517 passed/7 skipped + 四门禁仅证明 Test-Only 工程通过，不证明生产事务和身份。

第一版生产源选择延续上游 §13.1 的 **C1-SRC-A Host-owned sealed canonical candidate only**。`BaseRegistry.get/list`、D2-B Mapping、C0 diagnostic、任意插件对象、`implementation_ref` 均不可成为可信出版输入。真实 Registry 迁移、D2-D/D3 激活另立审批。

## 2. 当前 main 的物理事实、与尚未获得的证据

| 当前源码/事实 | 已验证的含义 | 真实 C1 所缺 |
|---|---|---|
| `runtime/registries/base.py`：`RegistryRecord` 可变；`register/_store/get/list/unregister/enable/disable/clear` 与活对象引用 | 无跨实例、跨进程 Writer Fence；不允许通过本地锁读取“可信一致快照” | 隔离密封候选、拒绝 live Registry 来源、完整 writer/alias 审计 |
| `agent_core/domain_package_loader.py`：`HostPackageRootIssuer`、可注入 `publication_verifier`、FD-backed root lease | 包根可信验证不等于 Catalog issuer、Catalog epoch 或部署身份 | 独立部署认证、已核验包 manifest / policy Generation 精确关联 |
| `agent_core/domain_registry_mapping.py`：非权威单记录元数据观察 | 不构成 Host-owned immutable catalog | C1 物理验证不能调用它进行 trust promotion |
| `agent_core/domain_catalog_resolution.py`：C0 private diagnostic、canonical & graph algorithm | Hash/自洽是内容校验，不是签发者认证 | 可复用纯验证算法，但必须独立鉴权/签发，绝不能 replace(role) |
| `agent_core/runner.py`：sandbox coordinator，并非 Application Composition Root | 无生产可信入口 | 找到真实应用服务、运行主体、策略所有者和注入位置 |
| `pyproject.toml`：仅 Pydantic 为当前 production dependency | 仓库没有可据此认定的 PostgreSQL/MySQL driver 或 schema migration | 实际部署 DB、driver、迁移负责人、凭据/备份/HA/SLA 证据 |
| 合并的 `tests/reference_models/ga02_d2c_c1_srca_model.py` | `NON_PRODUCTION_SIMULATION` 内存状态机与 adversarial fixtures | 不可 import 为生产 issuer、持久化 adapter 或可信证据 |

源码核对不等于已完成部署调用链追踪；实际进程、外部应用、配置/证书/数据库及主机安全边界 **尚未见到**，不得推定为存在。

## 3. 建议物理结构（候选，不是已部署代码）

```text
Deployment Identity / Secrets / Host Policy (外部受信配置)
                    │  只允许部署端装配，不接受 Package/Agent 自建
Application Composition Root  [B01 owner: TBD]
      ├─ HostPackagePublicationVerifier [D2-A exact manifest + generation]
      ├─ HostSealedSourceAdmission      [B03/B04/B05; ONLY SRC-A]
      │     └─ immutable canonical bytes + definition / edge / adapter
      └─ CatalogIssuer / Publisher Port [不导出到 Domain、Agent、Tool]
                     │
             Durable Catalog Authority  [B02/B06/B07]
              ├─ ACID Lane/Writer/Transition/Tx
              ├─ ACID Lease/Issuance/Revocation
              └─ Immutable verified Blob + retention/GC
                     │
            C1 Read / Resolve / CompleteReadAndIssue
                     └─ CatalogResolutionEvidenceC1V1
                        TRUSTED_PINNED_NON_RUNNABLE (未来实现)
                        ───X──▶ D2-D/D3/Tool executable authority
```

安全边界：
1. Host 的 issuer 身份须从进程外独立部署证明及可信配置取得，测试用 `mint_principal`、类名、签名外观字符串、Python frozen dataclass、内容 Hash 均不算认证。
2. Domain package、LLM、Agent、插件、普通调用方不得获 issuer 构造器、writer token、DB write credential 或 raw policy/manifest verifier。
3. 单个 lane 精确包含 `environment_id, tenant_scope_id, domain_id, domain_version, host_policy_id, namespace`；这些标识来自 Host 权限与部署配置，不接受 caller 自选租户；不存在 namespace=None/最近版本降级。
4. Host Source Admission 对 staging/source 在独立来源权限下验证、深拷贝、规范化、完整验证、密封后交付 publisher；先出版后校验或从 mutable Registry 重建已提交 image 都不允许。
5. 任何未能证明来源归属/写者完整性/DB 原子性的环境，只能拒绝发布，不能回退到 C0 或测试原型。

## 4. 持久化基座选择与冻结条件（B02/B07）

**候选优先：支持唯一约束、行级锁、ACID 事务及多进程连接的关系数据库（例如 PostgreSQL 或 MySQL 的受支持事务引擎）。** 当前没有足够部署证据选择实际产品和版本，所以这里 **不冻结 PostgreSQL、MySQL、driver、SQL 方言和隔离级别**。一旦确认部署基础，必须通过真实 two-worker / restart / clock / backup-restore smoke，而不能直接复用内存 `RLock`。

**候选存储分层：** Lane、WriterTerm、Transition、PublishTx、Lease、Issuance 必须落在**同一可线性化事务权威**；不可将 Lane 写在 DB、Lease 放无事务保障的缓存。Image bytes 可使用同库 BLOB 或独立 immutable blob store，但必须先**耐久写入、可读回并校验 hash**，再提交当前指针；外部 blob + DB 并非天然一个原子事务，要求 PREPARED 不可见、失败/GC 安全以及 dangling pointer fail-closed。

| 逻辑表 / 约束（设计草案） | 主键/唯一索引 | 最小重要字段 |
|---|---|---|
| `catalog_lane` | `UNIQUE(lane_key)` | `revision, writer_term, epoch, generation_id, revocation_revision, status, image_digest, image_id, policy_generation, package_generation, manifest_sha` |
| `catalog_writer_term` | `UNIQUE(lane_key)` | `term, owner_instance, claim_transition`；接管持久 +1 |
| `catalog_image` | `UNIQUE(image_id)`，内容不可更新 | `PREPARED/COMMITTED/RETAINED, lane_key, source/policy/manifest pins, canonical_digest, byte_length, durable_location` |
| `catalog_transition` | `UNIQUE(lane_key,revision)`, `UNIQUE(lane_key,generation_id)` | `kind, old/new epoch, old/new generation, term, revocation_revision, fingerprint, pointer` |
| `catalog_tx` | `UNIQUE(lane_key,publication_tx_id)` | `publisher_principal_id, canonical_request_fp, expected_revision, writer_term, result_revision, result_epoch, disposition` |
| `catalog_lease` | `UNIQUE(lease_id)` | Host minted opaque ID, `principal_id, lane, revision, epoch, generation, revocation_revision, expiry, status, SINGLE_ISSUANCE` |
| `catalog_issuance` | `UNIQUE(lane_key,issuance_request_id)`, `UNIQUE(evidence_id)` | `original_principal, lease_id, request_fp, policy/package/source pins, evidence_bytes_or_digest, status, original_epoch` |

**生产冻结前需补齐：** 精确 SQL DDL、FK/index/check 约束、隔离级别、并发更新条件、锁顺序及死锁重试规则、DB 时间权威和 Lease TTL、最大计数器/溢出处理、迁移回滚策略、HA 主从/故障切换、事务与 blob 提交分界、审计脱敏、密钥轮换、GC/保留时间、备份恢复时的 fence 防回滚。当前上表仅是逻辑映射，不是可执行迁移脚本。

## 5. 事务边界、权限与历史回执（必须物理验收）

### 5.1 PUBLISH / SUPERSEDE

1. Host issuer 独立鉴权并取出固定 Lane/Policy/Package pins；D2-A 发布证明必须按 exact manifest/generation 检验。
2. 在 Host 拥有的隔离 staging source 中做规范化不可变复制，验证 Definition/edge/adapter/CORE、精确缺省与资源上限。拒绝 live `RegistryRecord`/Mapper/C0 作为已认证来源。
3. 将 image bytes 先存为独立不可变 PREPARED，持久化读回核对 digest；失败不可曝光为当前。
4. 由 DB 单事务持有/条件更新 `catalog_lane`：比较 `lane_key, revision, writer_term, revocation_revision, generation, current_image_digest, policy_generation, package_generation`；插入唯一 Transition、Publication Tx，并更新指针与 epoch/generation。在事务提交点统一生效；不能拆成“check then write”。
5. exact `tx_id+principal+request_fp` 重放读取 **历史回执**，不再增 epoch；相同 tx 不同 fingerprint、旧 writer term 或其他身份拒绝。历史回执不可被视为新签发。
6. Revoke 是独立持久事务：严格增加 revision 与 revocation_revision、标记旧 generation REVOKED；新出版必须创建全新 generation，永不复活旧 generation。

**崩溃语义：** PREPARED 后 CAS 前崩溃 ⇒ 不可见 orphan；CAS 后 ACK 丢失 ⇒ tx ledger 恢复单一已提交回执；COMMITTED Blob 缺失/损坏 ⇒ 不可用/摘要错误，禁止从 Registry 回退。

### 5.2 OPENREAD / COMPLETEREADANDISSUE

1. 每次都先 Host 鉴权，解析固定 tenant/lane/source；OpenRead 在同一 DB 权威登记短期、不透明、单次新签发 Lease，记录 epoch/generation/revision/revocation、到期和私有身份。Caller 看见标识不代表能伪造权威。
2. 仅读已持久提交和重新校验摘要的原始 sealed image，执行纯依赖图核验；匹配上游 C0 Definition/hash/occurrence/CORE 语义，但**不可**直接把 C0 role 改成 trusted。
3. `CompleteReadAndIssue` 在**一个** DB 原子事务里：先鉴权/隔离地查询现有 Issuance ID，若原身份、请求 fp、Source/Policy、Ledger integrity 完全匹配，仅返回明确标记的历史不可执行证据；否则检查 Lease ACTIVE/未过期、lane 当前未撤销、revision/epoch/generation/revocation/source/manifest/policy pins、image hash，然后原子消费 Lease 并插入唯一 `catalog_issuance`。提交点即 C1 evidence issuance 的线性化点。
4. 同一请求同时到达两个 Worker ⇒ 最多一个新 Evidence ID；另一个如精确匹配只返回已提交历史记录，不得二次消费 Lease 或绕过 issuer。不同 fp 冲突拒绝。签发完成后才发生 revoke ⇒ 已提交证据可作为历史返回，但绝不自动获得 D3 效力。
5. 用 DB 的事务时间或经过验证的时钟语义检查 Lease deadline；重启后找不到合法持久 Lease/Issuance 时拒绝，不用 caller token 重建；保留可重新检索的不可变历史直到明确 retention 结束。

**业务边界：** C1 发行的 `TRUSTED_PINNED_NON_RUNNABLE` 仅证明“在某个签发点检查过该快照”，不是“未来任何时候仍有效”。之后执行、状态变更和副作用均须 D2-D/D3 另行授予。

## 6. B01–B07 物理阻塞、责任人、准入证据

| Blocker | 当前独立结论 | 解除阻塞需要的物理证据 | 允许的下一小步 |
|---|---|---|---|
| **B01 Host 应用/Issuer** | BLOCKED：本仓库无可确认的真实 Application Root/部署主体 | 真实入口代码路径、进程服务账号/证书、策略/密钥所有者、独立 authentication negative case、Agent/Plugin 无构造权限 | Deployment/owner inventory |
| **B02 Durable CAS** | BLOCKED：只有内存模拟 | DB 产品/版本/配置，schema+原子 SQL，2 worker 同 revision 一胜一败、故障后不 ABA、DB 唯一约束 | 真实 DB 隔离 prototype |
| **B03 Source Writers** | BLOCKED：`BaseRegistry` 全部活写入口不可作为权威 | SRC-A 唯一 Host source + 真实 staging 文件/对象权限证明；live Registry 全路径 deny + 间接 alias 负例 | 全量 writer/alias audit |
| **B04 Coherent Image** | BLOCKED：无真实跨 source/adapters/edges 一致快照 | source admission 正确所有权、不可变内容、Definition/edge/adapter/policy 原子快照、同源 revision/pack pins | 纯候选校验设计 + fixture |
| **B05 D2-A Provenance** | BLOCKED：包根 verifier 与 C1 独立信任未连接 | 部署持有的确切 package publisher proof、manifest hash、generation/policy/tenant 绑定与不匹配拒绝 | Owner/attestation integration design |
| **B06 Lease / Ledger** | BLOCKED：仅 Python `RLock` | 不透明 Host-minted ID、TTL/close/revoke/consume、唯一 Issuance ID、lost-ACK 后读历史、跨 tenant 无存在性泄露 | 原子 Issuance SQL + 测试 |
| **B07 Recovery/GC** | BLOCKED：无 HA、备份、恢复/保留契约 | 故障时间表、事务型存储故障注入、blob GC 安全、DB 恢复防回滚、日志脱敏与人工 Repair 规范 | 生产 topology/ops decision |

**B08（D2-D/D3 active use）** 不在 C1 生产发行授权内，保持 OUT_OF_SCOPE_HOLD，不可借 C1 发布为 Agent/Tool 解锁任何执行。

## 7. 实施顺序：从真证据到生产代码（不重复扩展 fake Runtime）

| 阶段 | 可交付范围 | 准入/完成门禁 |
|---|---|---|
| **P0 现状与部署锁定** | 确定真实 Host 应用根、部署主体、tenant/policy/Package owner、实际数据库、单/多 Worker、备份恢复与版本 | B01/B02/B05/B07 owner+运行拓扑有可验证引用；不可“默认本地单进程” |
| **P1 源与身份合同冻结** | 严格 C1-SRC-A；签发者能力及不可伪造来源；D2-A 证明、完整 Definition/edge/adapter canonical vectors；否认 C0/Registry trust-upgrade | PR #116 合同独立复审与必要修订；权限与来源双故障负例 |
| **P2 独立真实 DB schema + CAS smoke** | 只实现封闭、不可外部签发的 Lane/Writer/Tx/Transition 和 Blob durability probe；不创建 trusted evidence | 真实 DB 两 Worker CAS、旧 term、PREPARED/crash/lost ACK、restart/ABA、迁移幂等；4 工程门禁 |
| **P3 Host Sealed Candidate Admission** | 可信配置装配、Host 唯一 source、policy/package/manifest 校验、规范化复制与原子 Publish | 物理 B01/B03/B04/B05 的调用链证据、未知源与 live Registry deny、跨 tenant 拒绝 |
| **P4 Lease/Issuance 原子化** | 生产有权限的私有 issuer + lease/ledger transaction + immutable non-runnable evidence；此阶段也须单独授权 | 原子签发 CAS、2 Worker 同 ID、跨 tenant、撤销并发、TTL、lost ACK、恢复/GC，T01–T22/F1/F2 相应物理证据 |
| **P5 生产限定接入审查** | 仅 Application Host 内部 Read-Only C1 服务；不对 Runner/Domain/Tool 暴露 | 独立安全复审、exact-main diff 与四门禁、deployment rollback+监控、人工授权 |
| **D2-D/D3** | 新单元；未来单独设计批准 | 不继承 P5 执行权限 |

**不得用 PR #117 中的 TestOnlyCatalog 替代 P2–P4 的真实实现。** 任何 P2/P3/P4 的生产代码必须有新分支、新范围、实际存储/主机证据及独立合并授权。数据迁移不能与 issuer 信任升级在同一未经拆分的 PR 完成。

## 8. 真实对抗/故障证据矩阵（优先）

每项证据记录 `commit SHA, environment, process IDs, DB server/version/transaction isolation, migration version, input fingerprint, schedule/barriers, exact first denial, lane old/new revision, transition count, issuance count, external side-effects=0, recovered state`。不准用“pytest 通过”代替 DB 事实。

| 检查集合 | 真实执行计划与预期 |
|---|---|
| **T01–T04** | 外部伪造 Host/lease/自签 digest；变 tenant/policy/source package；必须在发行前 fail-closed |
| **T05–T07** | Registry live aliases, `register/_store/unregister/enable/disable/clear`、嵌套 definition/`implementation_ref`、adapter/edge 变更；SRC-A 拒绝所有不受保护来源 |
| **T08/T09/T11** | 两独立 Worker 同 revision；CAS 一胜一败；较旧 term/failover、真实 restart 后旧 epoch/lease 不复活 |
| **T10/T21/T22** | 两 Reader+Writer、revoke CAS 于 Issue 前/后、始终验证 pin、历史可回但不能变当前执行权 |
| **T12/T13/T14** | PREPARED 宕机、CAS 后 ACK 丢失、已提交 Blob 损坏/删除；恢复不二次发布、不从 Registry 重建 |
| **T15–T19** | 真正 adapter/policy Generation 变更、完整依赖闭包、2MiB/10240B/256 Nodes/1024 edges、真实故障注入、跨 C0 Canonical 向量 |
| **F1-A..G** | Host-approved exact absence 或 exact edge；缺失/伪造/旧 policy/矛盾/required/foreign tenant 必须拒绝 |
| **F2-A..H** | 真实 DB 幂等 Issuance、同 request ID 冲突、跨租户不可读历史、revoke/expiry/2-worker/lost ACK/restart |
| **T20** | C1 证据直接传入 Agent/Tool/Run 的拒绝；在 D2-D/D3 单元中独立验证，非 C1 Gate 的“通过”项 |

两故障优先级应给出精确第一个拒绝码与零副作用证据；全 T01–T22 不应一律认定要由 C1 内部实现（例如 T20 是未来消费者验证）。

## 9. 未冻结的关键生产决策

- **Host 在哪里？** 应用根、运行用户、部署边界、服务身份、动态权限、秘密存储；要提供源码/实际部署证据。
- **DB 是哪个？** 产品和版本、事务隔离/锁、连接池、跨进程拓扑、镜像与测试环境、migration 及 DDL owner。
- **Blob 在哪里？** 同库 BLOB 或独立 immutable object store 的 durability、可读回与 GC/retention。
- **Source 如何入库？** Host staging 签发/审核流程、Package verifier 的独立政策及来源所有者。
- **Schema 还未最终冻结：** 与 PR #116 的 F1 occurrence/duplicate-error、F2 historical issuer、F3 canonical vectors、C0 严格兼容，及 B01–B07 gate 的修订审批。
- **Ops 谁负责？** leader election/term takeover、密钥轮换、数据库恢复与回滚后 UNAVAILABLE、审计、安全事件告警。

这些不是可由 AgentRuntime 仓库当前代码推断出来的事实；必须在真实项目环境中证明。确认前不应授权生产可信接口。

## 10. 独立审查与实施准入决定

| Gate | 当前 Decision | 理由 |
|---|---|---|
| 当前 main Exact HEAD 及 C1-SRC-A 测试模型 | **VERIFIED_TEST_ONLY** | #117 已合并、合并后 1517 passed，但无生产发行 |
| 第一版 Host sealed source 方案选择 | **DESIGN_SELECTED_FOR_REVIEW** | 继承 #116 §13.1，不接受 mutable Registry 直通 |
| 逻辑持久化 CAS/Issuer/Lease/GC 物理设计 | **DRAFT_READY_FOR_INDEPENDENT_REVIEW** | 本文形成候选映射；DB/Host/部署证据尚缺 |
| **P0 物理环境/owner 调查** | **READY_TO_START_NON_PRODUCTION** | 不授予 Trusted C1 |
| **P1 合同与来源冻结** | **HOLD_PENDING_UPSTREAM_PR116_REVIEW** | 上游未合并，需物理身份细节与 Schema 冻结 |
| **P2 实际 DB CAS 实施** | **HOLD_ENVIRONMENT_AND_AUTH** | 缺数据库/部署选择与独立 scope 授权 |
| **P3/P4 Host Issuer + 生产 Evidence** | **HARD_HOLD_B01_B07** | 七项物理证据未完成 |
| **D2-D/D3** | **HARD_HOLD_OUT_OF_SCOPE** | 不继承任何非运行证据的执行权 |
| PR #117 模拟测试原型 | **MERGED_TEST_ONLY** | 不能再升级其 role |
| PR #116 | **OPEN_DRAFT_UNMERGED** | 不默认为生产冻结设计 |

**下一建议 Gate：** `GA-02 D2-C C1 — P0 Host/DB Deployment Evidence Inventory + PR #116 Physical Contract Alignment Independent Design Review`。先拿到实际环境与身份/数据库证据，并独立复核 #116 与本物理设计的一致性；如果缺少应用/DB owner，只能继续 READINESS HOLD，不得创建生产 Trusted Issuer。

**最终授权声明：本设计文档仅用于独立审查，不构成生产实施、权限发行、合并 #116 或 D2-D/D3 准入授权。**


---

## 11. A1–A6 Targeted Physical Design Amendment v0.2（2026-10-13）

**Normative precedence / freeze boundary:** 此补遗只规范本 PR 的候选设计与 P0 取证格式；其安全语义不得覆盖未合并 PR #116 的有效条款或已合并 C0 的行为。冲突先形成显式上游修订，再独立复审。尤其不能将以下“拟定物理路径”理解为已选定 DB、已认证 Host、已实现发行能力。

### 11.1 A1 — Host / Issuer 的身份、作用域与实际运行装配

`HostPackageRootIssuer` 仅签发 D2-A 文件根租约，不构成 Catalog 发行者。真实 Catalog Issuer 的实例权威来自**独立部署配置和 Application Composition Root 认证**，而非类构造能力、Agent 提示词、用户 JSON、包内参数、Hash 或测试 `mint_principal`。

| 待冻结合同 | 正式要求 | P0 必要佐证（不得提供密钥明文） |
|---|---|---|
| Host 实例身份 | 稳定 `issuer_principal_id` 与实例 ID、运行主体、授权环境；应用根唯一装配 | 服务/应用仓库路径与确切修订、部署清单、主体类型和权限审查 |
| Lane / tenant | 六维 `environment,tenant,domain_id,domain_version,host_policy_id,namespace` 由 Host 上下文推导 | 不含真实客户 ID 的脱敏策略样例及授权负责人 |
| D2-A Package | `source_package_generation, manifest_sha256, verified_publisher` 与策略代际绑定；失败拒绝 | D2-A verifier 调用路径、已核验发布事件/证据结构（只存摘要） |
| Issuer 容器边界 | 私有发行 Port/写凭证不得导出至 Agent、Domain、Plugin、Tool、LLM | 实际 DI 装配、进程权限、模块导入与访问拒绝测试 |
| Writer 接管 | 真实租约/Owner 由持久化服务保有；旧 Writer 不能自行增长 term | owner takeover 的原子化记录与旧主体拒绝日志 |

**A1 决定：HOLD_FOR_REAL_HOST_OWNER.** 不知道真正部署的服务与鉴权提供方时，不准写入 `TRUSTED_PINNED_NON_RUNNABLE` 生产发行代码。

### 11.2 A2 — CAS / Isolation / SQL 合同必须先以真实 DB 锁定

**不选数据库产品的逻辑事务说明：**

- `WriterClaim(lane)`：由持久化权威以原子行锁/条件修改持有当前唯一 Writer Claim，递增 `writer_term`，同一事务写入 claim 轨迹。身份授权在 DB 事务边界复核；term 永不接受调用方提交的“更高值”。
- `Publish(lane, tx_id)`：首先在身份隔离下按 `(lane,tx_id)` 查询既有 **COMMITTED** 事务（相同 owner/fingerprint 可只返回 historical receipt）；新提交须以 `revision+term+revocation_revision+generation+source_policy_hash` 条件更新 Lane，写 Transition、Tx 与不可变 Image 指针。所有行受同一 DB 提交边界保护。
- `Revoke(lane)`：同一 DB 事务增加 `revision`、`revocation_revision`；以前的 image/lease 不能重新成为 ACTIVE。
- `OpenLease` / `CompleteReadAndIssue`：同一 DB Authority 发行不透明、单用途 Lease ID，使用服务端时钟；签发事务先鉴权读历史，再比较当前 Lane、Revocation、Lease 与已验证 Blob Fingerprint，原子消费 Lease 并插入唯一 Evidence。
- `UniqueConstraint` 冲突不能都被笼统重试：同 ID 不同 fingerprint → 冲突；完全一致 → 安全历史检索；DB 不确定提交 → 查询持久 Tx/Issuance Ledger，不自动重新执行物理签发。

**B02/B07 真实 DB 准入所需元数据：** DB engine/version、事务隔离、连接池与 Driver、锁顺序、migration id、唯一索引与 FK、候选 SQL、DB 时间接口、支持的故障恢复方式、独立的两个 Worker 进程。以上任一未证实，状态 `P2=HOLD`。不得拿内存 `RLock` 与模拟 Crash Hook 替代。

### 11.3 A3 — F1 HostOptionalAbsence 的 exact occurrence 归属

依 PR #116 §14.1 的正式候选字段，Host 侧证据必须至少绑定 `source_key=(kind,namespace,id,version)`、`relation`、`target_kind/id`、`host_policy_generation`、固定 `HOST_APPROVED_OMISSION`、规范化摘要及 **独立 issuer_provenance**。

**冲突处理不新增平行 C0 标识规则：** 若同一 Definition 的可选依赖出现多次相同 `relation,target`，必须按上游 C0 声明 occurrence 与重复边优先级证明如何唯一定位；若现有 C0 无法表示该身份，则该 shape `HOLD_FOR_UPSTREAM_ALIGNMENT`，不可让 C1 自行以输入顺序/索引去重，也不能将两个证据缩成一个。Exact edge 与 Host-approved absence 同一 occurrence 不能共存；可选 relation 没有二者之一必须拒绝。详细冲突协议在 PR #116 §15 候选修订中处理，**本 PR 不宣布其已冻结**。

### 11.4 A4 — 与 main C0 的准确资源限制及返回优先级

校对基线为 `main@d2d59ec4...` 的 `agent_core/domain_catalog_resolution.py`，**各限制不是统一的 C1 模拟结构限制**：

| 精确约束 | 真实 C0 校验位置 | 候选 C1 兼容要求 |
|---|---|---|
| 一般字符串最多 1024 Python code points | `_string` / `_copy_fields` | NFC/类别及形状优先级要映射，不能把 1025 直接一律叫 byte overflow |
| 嵌套值的复制深度上限 12 | `_copy_fields` 的 `depth > 12` | 这与 graph depth 完全不同 |
| Definition 的 canonical UTF-8 bytes ≤ 10240 | `_canonical_definition` | 前/等于/后一字节三点验证 |
| 在对应受限的 list/asset_ref 和 active 集合 ≤256 | `_copy_fields`、admission、`_resolve_owned_diagnostic_graph` | 不能把 256 泛化为所有“graph node”或列表 |
| Exact edges 数量 ≤1024 | `_resolve_owned_diagnostic_graph` | 重复定义的处理与数量规则一起复审 |
| 图最长依赖路径深度 ≤32 | `longest_depth` 计算和边界检查 | **main C0 已物理实现**；旧文档“只为提议”须以上游补遗纠正 |
| Combined envelope/closure UTF-8 budget ≤2,097,152 | `_preflight_evidence_budget` 及末端预算检查 | 统计口径须对齐实际组合输入/输出，不可只算原始文件大小 |

详细错误码双故障优先级需要 **调用顺序 + 相同物理快照** 的 Test Oracle 证明；缺少证据不得宣称 `C1_... = C0_...` 完全等价。Canonical F3 的 Golden Vector 只是内容算法校验，独立 issuer 的 provenance 另证。

### 11.5 A5 — P0 → P2 证据驱动与受控试验权限

P0 收集真实部署事实；P1 做来源与合同冻结；只有**明确指定一个隔离 DB 试验环境和实验权限**才能进入 P2。P2 也只允许先做 `Lane / Writer / Tx` 最小真实 ACID 实验，不得注册生产 Issuer、发布可信 C1 Evidence、连接生产 Runtime 或患者/客户真实数据。

P2 独立 Gate 应单独验证：同 Revision 两进程 CAS 一胜一败、旧 term Fencing、失 ACK 后精确 Tx 重放、重启后 revision/generation 不复用、事务时间源一致、PREPARED Blob 不可见。实际迁移/凭证/连接配置必须由 DB Owner 在可隔离权限的环境提供；本 PR 不提供密码、服务端连接或真实数据。

### 11.6 A6 — Ops / TTL / Recovery / Blob 保留的具体决策责任

| 决策项 | Owner（待实名确认） | 必须交付的可核验证据 |
|---|---|---|
| Lease TTL / 事务时钟 | Host + DB Owner | TTL 数值/单位、数据库时钟与隔离级别、边界竞争 |
| WAL/事务恢复与 leader takeover | DB/Platform Owner | 故障恢复 runbook、旧 term/epoch 不可回退的 trace |
| Blob durability / checksum / GC | Storage Owner | immutable lifecycle、指针/lease/历史 Ledger 引用保留规则 |
| 备份恢复、主从切换 | DB/SRE Owner | 恢复点、fencing fence、rollback → UNAVAILABLE 及审计 |
| Issuer 密钥/身份轮换 | Security + Host Owner | 最小权限和旧凭证撤销记录，不放明文密钥到仓库 |
| 监测告警/可追踪性 | Runtime Operations Owner | audit correlation、typed denial、零敏感明文日志 |

**以上 Owner 目前均未从 GitHub 仓库证实，不能用“推荐责任岗位”冒充已落实的人员。**

## 12. P0 Deployment Evidence Intake Contract v0.1

**规则：** 每条 P0 证据都需要 `evidence_id, owner_role, source_type, stable_ref, exact_revision_or_version, observed_at, environment_scope, what_it_proves, reviewer, decision`；敏感值只允许给出已经脱敏的元数据、文件路径和不可逆摘要。外部系统没有可访问证据时记录 `MISSING_EXTERNAL_EVIDENCE`，不得填占位假事实为 PASS。

| ID | 必须交付的信息 | 最小验证动作 | 当前 |
|---|---|---|---|
| P0-01 | 真实 Host 服务名、app repo/path/revision、生产 Composition Root | 源代码 exact SHA 追踪私有 Issuer 的装配与不可导出 | MISSING_EXTERNAL_EVIDENCE |
| P0-02 | 部署主体认证类型、Tenant/Environment/Policy Scope Owner | 验证服务账号及 allowlist 的非敏感配置快照、越权反例 | MISSING_EXTERNAL_EVIDENCE |
| P0-03 | DB engine + server version +事务隔离及 driver | 带版本的 schema/DSN 元数据 + DB 服务端只读验证 | MISSING_EXTERNAL_EVIDENCE |
| P0-04 | Worker 进程数、故障切换策略、抢占/接管方式 | 两独立进程/实例编号与部署拓扑追踪 | MISSING_EXTERNAL_EVIDENCE |
| P0-05 | D2-A Host Package exact manifest/verifier 与已发布 generation | 对实际 verifier 入口和归属作只读取证 | PARTIAL_CODE_ONLY |
| P0-06 | Blob durable location, checksum, retention, GC Owner | 存储服务类型、引用保留和 GC 策略元数据 | MISSING_EXTERNAL_EVIDENCE |
| P0-07 | Migration Owner、Rollback/Backup/Restore 安全策略 | 无秘密的版本清单、恢复/防 ABA 设计 | MISSING_EXTERNAL_EVIDENCE |
| P0-08 | Registry Writer 与 alias 全路径 | 枚举 BaseRegistry 所有写操作、嵌套 mutable Definition | PARTIAL_CODE_ONLY |
| P0-09 | C0 Exact Canonical/Resource/Error Priority | 原始 C0 源码位置 + Golden Vector / bound 三点测试证据 | PARTIAL_CODE_ONLY |
| P0-10 | 生产观察/审计与停机/撤销 Operator | runbook/ref、责任实体、后备人工流程 | MISSING_EXTERNAL_EVIDENCE |

**P0 退出准则：** P0-01～P0-07、P0-10 的现实证据已被可独立核查的 owner 确认；P0-08/09 的代码证据已补齐物理调用链；外部敏感信息已处理；没有 `UNVERIFIED` / `MISSING` 被视为已通过。仅确认 DB 品牌但不能提供事务与 Worker 证明不能退出 P0。

## 13. Amendment / Gate 决定（不得绕过）

| Gate | Decision | 原因 |
|---|---|---|
| A1–A6 设计补遗 | SUBMITTED_FOR_INDEPENDENT_REVIEW | 细化了证据和物理合同，未证实环境 |
| P0 Evidence Contract | DRAFT_COMPLETE / INTAKE_OPEN | 有字段、owner、校验动作，无真实外部证据 |
| PR #116 F1–F3 Cross-Alignment | UPSTREAM_AMENDMENT_REQUIRED | C0 graph depth 32、F1 occurrence 与发行原子性需要上游一致 |
| P1 Normative Freeze | HOLD_PENDING_PR116_INDEPENDENT_REVIEW | 两个 Draft 未合并 |
| P2 Real DB Feasibility Implementation | HOLD | 尚无 DB 产品/环境/Owner/实施授权 |
| P3/P4 C1 Trusted Issuer/Evidence | HARD_HOLD | B01–B07 未解除 |
| D2-D/D3 | HARD_HOLD | 非执行证据不授权运行 |
| PR #118 Merge | NOT_AUTHORIZED | 独立复审尚未完成 |


---

## 14. P0 Intake Cross-Alignment — F1-ORD-01 v0.3

**依据：** PR #116 §16 候选 `HostOptionalAbsenceOccV2`，`main@d2d59ec4c97ed6a85a13a5f36551752ad2c0f067` 的 `agent_core/domain_catalog_resolution.py:759–812`；本节补充 §11.3 与 §12 P0-08/09 的审查义务，不宣称 #116 已冻结或生产 Host 被认证。

### 14.1 物理来源与 Ordinal 准入

- **Exact C0 key**：`(source_key=(kind,namespace,id,version), relation_id, ordinal)`；ordinal 从**经 Host 认证的 Sealed Definition** 的相关字段 `enumerate(vals)` 取得，不能由任意 edge/absence JSON 自行编码身份。完整 relation_id 如 `skill.optional_tools`，不接受只写字段名 `optional_tools` 的弱匹配。
- **版本**：使用候选 `GA02-D2C-C1-OPTIONAL-ABSENCE-OCC-2`，将 `ordinal` 与 source/relation/target/policy/reason 一起进入 Canonical Bytes 和 Domain-Separated SHA256。旧 `V-ABS-01` 继续作为 hash-only 的历史向量，不接受它当作同名双声明的唯一有效 Host approval。
- **证明与存储**：DB 私有 `issuer_provenance` 必须指向独立的 Host source admission、签发者身份、policy generation、exact image/transition、单个 occurrence 的授权记录；不得将可自构造的 digest 或 `NON_PRODUCTION_SIMULATION` handle 当作部署凭证。
- **基数与故障**：每个已声明的 optional occurrence 恰好一个 exact edge 或一个已认证 V2 absence；一个审批不得覆盖两个 ordinal；同时存在 edge+absence、漏一个 ordinal、重复 ordinal、借用旧政策或外租户源都拒绝。先做 issuer/scope 审核，再执行图的 fail-closed 校验。
- **同源快照规则**：Image Builder 提交的 Definition、relation edge、V2 absence、adapter、CORE allowlist 与 policy/package 证明属于一个不可变来源版本；不能读 live `RegistryRecord` 的局部字段再推断全局 consistent snapshot。P2/P3 不得引入尚未批准的 C1 正向发行者。

### 14.2 P0 证据追加与演练

| P0 ID | 新增精确证明义务 | 当前状态 |
|---|---|---|
| P0-05 / Host source | 审计真实 Host 的 `issuer_provenance` owner、被认证 package manifest/policy/image/transition 的来源与访问控制 | MISSING_EXTERNAL_EVIDENCE |
| P0-08 / Writer alias | 证明源 Definition 顺序与 ordinal 在 Sealed Admission 后不可由 Registry writer/alias 重排，或出现变动就新的 generation 且旧批准无效 | PARTIAL_CODE_ONLY |
| P0-09 / C0 parity | 对 `skill.optional_tools=["tool-a","tool-a"]` 在 C0 逐个计算 0/1 的 `expected` 键，校验 duplicate ordinal/relation/declared_target 原因；在 C1 对齐 V2 schema | PARTIAL_CODE_ONLY |
| P0-09 / new golden | `V-ABS-OCC-00`: 234 UTF-8 bytes，摘要 `349e20e0dcf7af2d68c1a6dd5173188ba583346df92c9d37d2ad72094cf5000c`；`V-ABS-OCC-01`: 234 bytes，摘要 `ff2cf9ef7cea434720bf614d6d201d2be93d3b3d4eaefd343ad25b7a1cb2bf7b`；独立第二实现重算后才可 freeze | DESIGN_ONLY / SECOND_VERIFIER_PENDING |
| P0-09 / threat fixtures | 对 PR #116 §16.4 F1-A..G + ORD-01..05，记录 `ordinal_key, raw/canonical profile, admitted approval IDs, issuer-policy pins, first denial, side-effect count`；不得沿用过时 mock 实测声称生产通过 | DESIGN_ONLY / EXECUTION_PENDING |

**P0-09 退出条件新增：** 双 occurrence 与单缺省正负 fixture 明确采用 C0 的完整关系 ID 与真实 ordinal；新 Profile 的 0/1 摘要经第二独立实现核对；修订错误优先级与两个并发/篡改案例后再考虑 `P0-09 CODE_PARITY = VERIFIED`。这仍不替代 P0-01～07/10 的真实部署取证。

### 14.3 对当前 Gate 的影响

| Gate | Decision |
|---|---|
| F1-ORD-01 Physical Intake Alignment | DESIGN_SUBMITTED / REQUIRES_INDEPENDENT_REVIEW |
| P0 Evidence Intake Contract | EXPANDED / NOT COMPLETE |
| P0 Real Host / Database Facts | MISSING_EXTERNAL_EVIDENCE |
| F1-A..G / ORD Fixtures | SPECIFIED_NOT_EXECUTED |
| PR #116 F1 Versioned Contract | PROPOSED_NOT_FROZEN |
| P2 Real DB / P3 Host Issuer | HOLD / HARD_HOLD |
| PR #118 Merge Authorization | NOT ISSUED |

**下一 Gate：** `GA-02 D2-C C1 — PR #116 F1-ORD-01 Exact-HEAD Independent Versioned Schema/Golden Re-Review + PR #118 P0 Cross-Alignment Verification`。C1 Production B01–B07 与 D2-D/D3 均继续 HARD HOLD。
