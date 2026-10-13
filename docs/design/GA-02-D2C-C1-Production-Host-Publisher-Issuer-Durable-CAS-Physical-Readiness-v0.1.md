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
