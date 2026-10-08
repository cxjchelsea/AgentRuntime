# CA-M5-IU9-03 Durable Resource Lock Recovery + Fencing V1.0

> Base：CA-M5-IU9-02 PASSED @ ea809e29452c19e41ec162f4ffd48e3ee12c0423
> Target blocker：B-M5-IU9-005 RESOURCE_LOCK_CRASH_RECLAIM_AND_FENCING_MISSING

## 1. 目标

CA-03 只解决：

~~~text
durable ResourceLock authority
durable operation-resource binding
recovery epoch fencing
safe stale-lock reclaim
provider fencing capability boundary
UNKNOWN -> retain / fail closed
~~~

不进入 Workflow checkpoint/resume、RecoveryDisposition、whole-recovery orchestration、IU10 或 M6。

## 2. 核心安全不变量

~~~text
worker disappeared != external Tool stopped
heartbeat expired != resource safe to reclaim
TTL expired != resource safe to reclaim
recovery epoch advanced != prior provider operation cannot commit
binding says RELEASED != every durable lease is necessarily RELEASED
~~~

Tool resource lock 只有强证据成立时才可 reclaim。

## 3. Durable ResourceLock ledger

新增：

~~~text
DurableResourceLockState
DurableResourceLockRecord
DurableResourceLockReadStatus
DurableResourceLockReadDecision
DurableResourceLockStore
DurableResourceLockAuthority
InMemoryDurableResourceRecoveryStore
~~~

直接复用 IU8：ResourceLockOwner、ResourceLockAcquireRequest、ResourceLockLease、acquisition_id、ResourceLockAuthority。

规则：

~~~text
first exact acquisition -> ACQUIRED
same active acquisition replay -> ALREADY_ACQUIRED
same acquisition_id with different provenance -> UNKNOWN
another active acquisition on same lock_key -> BUSY
released acquisition cannot silently become active again
release only exact acquisition
release history retained as tombstone
~~~

所有 mutation 必须与 current recovery claim 在同一 durable transaction / CAS boundary 中完成。

## 4. Session execution lock recovery

恢复时同 session + 同 execution + 同 acquisition -> ALREADY_ACQUIRED / exact reattach；同 session + competing execution -> BUSY。

## 5. Durable operation-resource binding

新增 DurableOperationResourceBindingState / Record / ReadDecision / Store / DurableOperationResourceLeaseRegistry；继续复用 IU8 OperationResourceLeaseBinding 与 exact lease set。binding release 后保留 RELEASED tombstone。

## 6. External operation reconciliation

OperationRecoveryStatus：RUNNING_CONFIRMED / COMPLETED_CONFIRMED / STOPPED_CONFIRMED / NOT_FOUND_WITH_PROOF / UNKNOWN。

只有 COMPLETED_CONFIRMED、STOPPED_CONFIRMED、NOT_FOUND_WITH_PROOF 是强 reclaim 证据；普通 404、lookup failure、local task missing 必须映射 UNKNOWN。

## 7. Provider fencing boundary

新增 ProviderFenceStatus / ProviderFenceEvidence / ProviderFenceDecision / ProviderFencingAuthority / ProviderFencePersistenceDecision。

只有 ESTABLISHED 才能证明 prior exact provider operation 已不能继续提交副作用；evidence 必须绑定 exact operation_handle_id、recovery_epoch 和有效 Core-local established_at，并先 durable commit 再释放 lock。UNSUPPORTED / UNKNOWN 均 retain。

## 8. Safe reclaim matrix

~~~text
durable in-flight COMPLETED -> RECLAIM
durable in-flight CONFIRMED_STOPPED -> RECLAIM
probe COMPLETED_CONFIRMED -> RECLAIM
probe STOPPED_CONFIRMED -> RECLAIM
probe NOT_FOUND_WITH_PROOF -> RECLAIM
probe RUNNING_CONFIRMED -> RETAIN
probe UNKNOWN -> RETAIN
provider fence ESTABLISHED + durable commit -> RECLAIM
provider fence UNSUPPORTED / UNKNOWN -> RETAIN
no probe + no fence -> RETAIN
unbound active lease -> RETAIN / reconciliation required
stale recovery epoch -> UNKNOWN / no release
~~~

## 9. Partial reclaim

多资源 Tool reclaim 不假设跨多 lease 原子事务。若 lease A release unknown、lease B 已 released，则返回 UNKNOWN，分别暴露 released_leases 与 retained_leases，binding 保持 ACTIVE。后续 recovery 对 B 走 ALREADY_RELEASED exact replay，再释放 A；全部 RELEASED 后才写 binding tombstone。

## 10. Cross-store consistency rule

Targeted Review 补强：RELEASED binding 不能单独推出所有 durable lease 已 RELEASED。返回 ALREADY_RECLAIMED 前必须逐个核对 exact acquisition；ACTIVE / NONE / UNKNOWN / provenance mismatch 均返回 UNKNOWN，并保留已知 active lease。

## 11. Probe time rule

OperationRecoveryDecision.observed_at 是 Core-local observation time，强证据必须满足：

~~~text
handle.started_at <= observed_at <= recovered_at
~~~

未来时间 observation 不得授权资源释放。

## 12. In-flight evidence compatibility

CA-03 复用 CA-02 durable in-flight evidence。ORPHANED_UNCONFIRMED 本身不授权 reclaim，必须再经过 exact probe、provider fencing 或更强 durable terminal evidence。

## 13. Unbound lease handling

durable lock ledger 存在 active Tool lease、但找不到 operation-resource binding 时：UNBOUND_ACTIVE_RESOURCE_LEASES_REQUIRE_RECONCILIATION -> RETAINED。

## 14. Targeted Review findings

### F-M5-IU9-CA03-001 RELEASED_BINDING_NOT_CROSS_CHECKED_WITH_LEASE_LEDGER

初版遇到 RELEASED binding 会直接返回 ALREADY_RECLAIMED，跨 store / partial write 下可能隐藏 active lease。已修复为逐个读取 exact acquisition，全部 RELEASED 且 provenance 一致才允许 ALREADY_RECLAIMED。

~~~text
F-M5-IU9-CA03-001 = CLOSED
~~~

### F-M5-IU9-CA03-002 FUTURE_OPERATION_RECOVERY_OBSERVATION_COULD_AUTHORIZE_RECLAIM

初版只验证 observed_at >= operation started_at，未限制 observed_at <= recovered_at。已修复为 started_at <= observed_at <= recovered_at。

~~~text
F-M5-IU9-CA03-002 = CLOSED
~~~

## 15. Verification scenarios

已覆盖 session lock restart reattach / competing BUSY / stale epoch release rejection / IU8 durable adapter compatibility / orphan retain / RUNNING retain / STOPPED & COMPLETED & NOT_FOUND_WITH_PROOF reclaim / provider fence establish-persist-reuse / unsupported retain / unbound active retain / wrong identity retain / future probe time retain / RELEASED binding + ACTIVE lease contradiction UNKNOWN / partial reclaim + later recovery exact replay / inflight store exception retain。

## 16. Blocker mapping

~~~text
B-M5-IU9-005 RESOURCE_LOCK_CRASH_RECLAIM_AND_FENCING_MISSING = CLOSED

B-M5-IU9-006 WORKFLOW_CHECKPOINT_RESUME_AUTHORITY_INCOMPLETE = OPEN
B-M5-IU9-007 RECOVERY_DECISION_ORCHESTRATOR_MISSING = OPEN
~~~

## 17. Pre-document closure verification

~~~text
exact head = 22e3c5220e88ac3a5e71efed157b893344c1cdee
GitHub Actions run = 35822442848
pytest = PASSED (803 passed, 1 existing warning)
mypy = PASSED (201 source files)
ruff check = PASSED
ruff format --check = PASSED (201 files)
~~~

## 18. Current status

~~~text
CA-M5-IU9-03 = CODE COMPLETE
CA-M5-IU9-03 TARGETED AMENDMENT REVIEW = PASSED
CA-M5-IU9-03 VERIFICATION = PENDING FINAL DOCUMENTED HEAD

F-M5-IU9-CA03-001 = CLOSED
F-M5-IU9-CA03-002 = CLOSED

B-M5-IU9-001 = CLOSED
B-M5-IU9-002 = CLOSED
B-M5-IU9-003 = CLOSED
B-M5-IU9-004 = CLOSED
B-M5-IU9-005 = CLOSED
B-M5-IU9-006 = OPEN
B-M5-IU9-007 = OPEN

M5-IU9 IMPLEMENTATION READINESS = NOT_READY
NEW BLOCKER = NONE

NEXT REQUIRED = CA-M5-IU9-04 Workflow Checkpoint + Recovery Decision / Resume
M5 = IN PROGRESS
~~~
