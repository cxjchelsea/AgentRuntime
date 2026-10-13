# GA-02 D2-C C1 — Trusted Host Catalog / Publisher–Epoch–Fencing Security Boundary Design v0.1

**Status:** PROPOSED — independent security/design review required. **C1 implementation authorization: HOLD.**  
**Exact base:** `main@01d6865d540c3dd0547ebcdd19508e71e38efddc` (PR #114 + #115 already merged; C0 post-main engineering gates pass).  
**Change discipline:** design-only; no C1 issuer, production wiring, Registry mutation, executable DomainBinding, Tool permission or D3 admission is authorized by this document.

## 1. Purpose and trust boundary

Produce a C1 **trusted-host-pinned, read-only catalog publication and provenance evidence** under a real Application-owned issuer. C0's `agent_core/domain_catalog_resolution.py` only produces `UNTRUSTED_DIAGNOSTIC_ONLY` / `NOT_ASSESSED`; caller-provided digests, frozen dataclasses, method names, private Python symbols and matching string generation tokens are **not authority**.

C1 may validate **exact immutable dependency evidence** for later D2-D assembly. It **must not** produce execution permission, activate a domain, issue `BoundRunDomain`, invoke `implementation_ref`, grant tenant access, call Tool/Skill/Workflow, mutate Registry/StateStore or cross the D3 side-effect boundary. Define any future C2/D3 activation as separately reviewed.

**Normative precedence:** physical source contracts + merged GA-02 D2 / D2-B / D2-C design > this proposal. Preserve upstream `GA02-D2-BINDING-1` fingerprint rather than creating an incompatible binding format. Any contradiction is a targeted amendment and re-review, not a silent override.

## 2. Physically verified as of exact main

| Source | Observed physical fact | Security consequence |
|---|---|---|
| `agent_core/domain_package_loader.py` | `HostPackageRootIssuer` holds independently injected `publication_verifier`; manages an FD-backed package-root lease; mutable internal generation dictionary | Package-root trust is **not** catalog issuer identity, Registry epoch or a cross-service permission grant. A caller-controlled verifier is not proof |
| `agent_core/domain_registry_mapping.py` | Non-authoritative Registry metadata observation; no trusted Host admission | Cannot import/map C0 observation as a trusted catalog |
| `runtime/registries/base.py` | Mutable `RegistryRecord`, mutable `_records`, public `register/_store/get/list/unregister/enable/disable/clear`; `get/list` return live records; definitions/implementation references may be shared | No shared epoch, immutable publication, cross-registry lock or write fence; all live mutable writers are a **C1 authority blocker** |
| `agent_core/domain_catalog_resolution.py` | C0 private `_resolve_untrusted_catalog_observation`, self-consistency/digest and graph checks only; no Registry or Host imports | Do not rename C0 result or trust-upgrade it |
| `agent_core/__init__.py`, `agent_core/runner.py` and domain loader/mapping entrances | No C0 resolver export, call, or production consumer added by #115 | Preserve the no-wiring invariant until D2-D/D3 authorization |
| C0 exact merged-main CI | Push run #38331579041: 1461 passed, 7 skipped; mypy/Ruff all passed | Confirms engineering baseline only; cannot validate an unimplemented issuer |

**Independent authority evidence still missing:** actual Application-owned publisher identity, deployment-pinned source/allowlist, cross-process durable epoch store, writer interception or immutable publication discipline covering every mutation, revocation authority, and a physically verified C1 Host integration root. Accordingly no C1 production implementation is ready today.

## 3. Actors, threat model, ownership

**Trust principals** (do not identify using a package-provided string):
1. **Application Composition Root:** creates, owns and injects issuer capabilities from independently deployed configuration/secret authority; issues no C2 permission at this gate.
2. **Host Catalog Publisher:** unique writer / CAS owner for one isolated `(environment, tenant-scope, domain-id, domain-version, policy-scope)` publication lane. Owns immutable snapshots and epoch history.
3. **Trusted package publisher verifier:** independently authenticates the D2-A package generation/manifest SHA; does not automatically own the Catalog lane.
4. **Catalog reader / resolver:** obtains an opaque read lease issued by publisher; cannot mint/renew/rebind its own epoch.
5. **Registry / adapter writers:** may propose mutations but cannot alter an issued publication image or bypass the authoritative publishing transition.
6. **Future D2-D/D3 consumers:** out of scope; revalidate active-use authorization and live revocation at effects.

**Adversary capabilities:** construct arbitrary dataclasses, mutate references shared with Registry, race register/unregister/disable/enable/clear, swap `implementation_ref`, swap adapter binding, present foreign tenant/domain keys, replay stale lease across restart, force token ABA/reuse, cause publisher crash mid-commit, poison definitions, raise exceptions or vary identity mid-read. Treat compromised Host/OS secrets or privileged mount namespace attacks as outside this model, but deployment assumptions must be documented and validated before C1 rollout.

## 4. Selected ownership model and explicit rejection of unsafe alternatives

**Selected design: single Host-owned immutable publication plus durable fencing state**, not live multi-Registry `get()` under an informal lock.

- All Registry and adapter inputs are converted to **owned canonical primitive copies**. No `RegistryRecord`, Pydantic instance, mutable dict/list, file handle, function or `implementation_ref` can be carried inside a published image.
- Publication immutable objects are not authoritative merely because `frozen=True`; authority derives from an **opaque issuer-held lease identity** verified against **current durable publication state**.
- The **only** promotion path is an Application/Host-owned checked publication transaction. The incoming package and C0 cannot supply expected catalog epoch or select their own attestation issuer.
- Any unguarded writer path or live object mutation that could change the authoritative catalog without an epoch/revocation change means **HOLD_C1**. Existing BaseRegistry APIs currently lack this protection. An alternative wholesale fork of Registry definitions and exclusive source-of-truth discipline must prove that old Registries are not authoritative writers. Never assume a per-instance Python RLock is a durable cross-process fencing mechanism.
- For multi-process deployment, use a durable CAS/fencing store (or genuinely equivalent transactional substrate); in-memory monotonically incremented integers or timestamps alone are insufficient across restart/replicas.

## 5. Proposed typed contract (design, not code)

### 5.1 Identities

`CatalogLaneIdV1` contains exact `environment_id`, `tenant_scope_id`, `domain_id`, `domain_version`, `host_policy_id` and exact scope namespace. Its canonical value is sourced from **trusted Host policy**, never from C0 input. Every request must bind to one exact lane.

`HostCatalogPublicationV1` contains `profile=GA02-D2C-C1-PUB-1`, `issuer_id`, `publisher_instance_id`, `lane_id`, `epoch` (durable monotonic non-reusable number/ordered ID), `generation_id` (globally unique random or store-backed identity, never reused), `publication_tx_id`, `source_package_generation`, `verified_manifest_sha256`, `policy_generation`, `registry_image_digest`, `edge_image_digest`, `adapter_image_digest`, `catalog_digest`, `revocation_generation` and `created_at` as audit metadata only. Generation and epoch must both be verified; a SHA is not a signature or bearer capability.

`CatalogReadLeaseV1` is an **issuer-issued opaque handle**, not a freely constructible dataclass proof. Its private publisher-side registry binds exact `(issuer identity, lane, publication epoch, generation, snapshot pointer, lease issuance id, revocation generation)`. Callers may inspect read-only metadata but cannot use metadata alone to authenticate a lease. Lease lifetime and revocation behavior must be explicit; never pin an FD or Python object identity as the only durable anti-replay mechanism.

`CatalogResolutionEvidenceC1V1` contains exact lane, issuer-side verified publication identity, source package and policy pins, stable canonical Registry/edge/adapter hashes, exact seed/closure keys, and a non-runnable role `TRUSTED_PINNED_NON_RUNNABLE`. Issuance is atomic after full validation; it is only evidence for future D2-D and is **not DomainBinding / active-use permission**.

### 5.2 Typed denial candidates

`C1_ISSUER_UNVERIFIED`, `C1_PUBLICATION_UNAVAILABLE`, `C1_LANE_SCOPE_MISMATCH`, `C1_SOURCE_PACKAGE_UNVERIFIED`, `C1_EPOCH_STALE`, `C1_PUBLICATION_REVOKED`, `C1_WRITER_FENCE_INVALID`, `C1_PUBLICATION_DIGEST_MISMATCH`, `C1_REGISTRY_MUTATION_UNGUARDED`, `C1_DEPENDENCY_INVALID`, `C1_ADAPTER_ATTESTATION_INVALID`, `C1_RESOURCE_LIMIT`, `C1_INTERNAL_UNSTABLE`. Names/error precedence are proposed and **not frozen** until independent design review.

**Denial precedence proposal:** malformed/forged lease or issuer → wrong lane/source policy/package → revoked/epoch/fence mismatch → resource bounds → canonical definitions/digests → exact D1 dependency closure → adapter attestation → final epoch and revocation recheck → atomic evidence. All exceptions are sanitized; no partial trusted result, no implicit retry against newer publication.

## 6. State machine and durable atomicity

```text
UNPUBLISHED
   │ verified Host identity + locked/pinned input capture
   ▼
PREPARED  ── durable compare-and-swap(epoch, generation, revocation, writer fence) ──▶ PUBLISHED
   │ failure / crash before commit                                         │
   ▼                                                                       ├──▶ SUPERSEDED
ABORTED                                                                  │
                                                                          └──▶ REVOKED
```

Required invariants:
1. **One atomic visible publication per lane**. PREPARED objects are invisible to trusted C1 reads. No partially published image.
2. **Monotonic, no ABA:** every successful publish/supersede/revoke advances an independent durable transition counter/fence; old identities never become current again, including restart and failover. A rolled-back durable store requires explicit repair/HOLD, not accepting an earlier generation.
3. **Fencing:** a writer must present the current writer epoch/term and expected publication revision to commit; stale writer commits are rejected even if an old process still owns a local lock.
4. **Revocation is durable and visible.** Revoke/disable must invalidate new C1 reads immediately under the authoritative store; already issued evidence is read-time history only, and future D3 consumers must check revocation at the point of effect.
5. **Immutable snapshots:** publish by exact owned value copy under guarded writer authority. No alias to the authoring Registry, no mutable `implementation_ref`, no hidden lazy external read.
6. **Cross-resource consistency:** source package pin, Host policy generation, Registry definitions, exact relation edges and Host adapter attestation must be captured as one logically coherent publication. If sources cannot be fenced or snapshot-copied coherently, C1 publication fails closed.
7. **No token-only security:** `issuer_id`, `epoch`, hashes, `generation_id` strings or a synthetic signature-looking field supplied by callers cannot mint trusted evidence.

## 7. Publication and C1 read protocol

### 7.1 Publisher transaction
1. At trusted composition root, authenticate publisher authority and immutable Host policy/tenant/lane; verify exact D2-A published package generation independently.
2. Obtain current durable writer fencing term and lane revision via the authoritative store. Acquire coherent read/copy access for all Registry/edge/adapter sources, or receive a sealed already-immutable canonical source image.
3. Validate exact namespaces, generation/policy identity, definition canonical `GA02-D2C-DEF-1` compatible with C0, full typed relation catalog, CORE schema allowlist, enabled state, exact adapter binding and size/graph limits. No fallback to `namespace=None` or closest version.
4. Copy into owned primitive immutable image, compute domain-separated digests and a publication image digest. Compare a second source revision or guarded lock/transaction fence after capture; reject any drift.
5. Write image to durable immutable blob store and CAS the authoritative lane pointer from expected revision to new `(epoch, generation, fence, digest)`. Atomic commit is the linearization point. Do not expose a pointer to an image that is not durably available.
6. On crash before CAS, orphan prepared blobs are inert; after CAS, recovery must locate exact committed immutable image, not regenerate from mutable Registries. Duplicate publication transaction IDs must be idempotent only when exact input digest/lane/fence matches; otherwise deny.
7. Audit publisher identity, lane, transition ID, old/new generation, digest, revocation, result code, without private patient data, secrets, raw manifest contents or unsafe paths.

### 7.2 Resolver read
1. Obtain issuer-supplied read lease for exact trusted lane/source/policy; never accept a caller-created `CatalogReadLeaseV1` as authentic.
2. Publisher validates private lease issuance record, durable current lane pointer, writer revision, revocation and immutable image digest. Pin snapshot identity for the **whole** graph resolution, not separately per Registry `get()`.
3. Consume **only the immutable publication**, applying C0-compatible canonical Definition and full exact dependency/edge checks. C0 can be reused as an explicitly pure **validation algorithm**, not as evidence authority: do not simply `replace(observation_role=...)`.
4. Revalidate epoch/generation/revocation and lease authority against the durable store **before** returning result. If any drift occurred, deny without partial evidence or automatic read of a newer image.
5. Issue C1 non-runnable evidence only through the trusted Host composition root. Do not export the issuer secret/capability to Agent/Tool/Domain plugin code.
6. At any subsequent D2-D/D3 consumption, repeat appropriately scoped active-use checks; an old C1 proof alone never grants runtime or side-effect authority.

## 8. Targeted adversarial acceptance matrix

| ID | Injected condition | Required observable outcome |
|---|---|---|
| T01 | Caller constructs identical-looking publication or lease dataclass | `C1_ISSUER_UNVERIFIED`; no trusted output |
| T02 | Caller supplies self-consistent C0 digest + forged `issuer_id` | Deny; no C0→C1 trust upgrade |
| T03 | Correct package digest but foreign tenant/lane or policy generation | `C1_LANE_SCOPE_MISMATCH` |
| T04 | Legit issuer, mismatched D2-A manifest or package generation | `C1_SOURCE_PACKAGE_UNVERIFIED` |
| T05 | Writer mutates Registry definition after snapshot capture | No published image mutation; stale writer fails or publication rotates |
| T06 | `register/unregister/enable/disable/clear` racing publisher | Coherent image or fail-closed; no mixed versions |
| T07 | In-place `RegistryRecord.definition` and `implementation_ref` swap | Cannot silently affect issued image; provenance invalidation required |
| T08 | Two concurrent publishers with same expected revision | Exactly one CAS winner; loser fenced |
| T09 | Old publisher resumes after process crash and newer term | Old fence rejected despite held local lock |
| T10 | Revoke before read and during read | Immediate denial or pre-return epoch/revocation mismatch; no partial evidence |
| T11 | Epoch/generation reuse after restart (ABA) | Deny older lease; durable monotonic identity |
| T12 | PREPARED blob crash before pointer CAS | No visible trusted publication |
| T13 | Crash after CAS before response | Deterministic recovery of one committed image; retry idempotent only for same tx |
| T14 | Blob deletion/corruption after pointer published | Fail closed, no mutable Registry fallback |
| T15 | Adapter generation/tenant allowlist rotates concurrently | Old snapshot read bounded; stale active binding prohibited |
| T16 | Optional/required edge tampering, CORE namespace crossing, cycle | Exact typed graph denial under coherent epoch |
| T17 | 2MiB evidence overflow / invalid canonical string / excessive depth | Resource/shape error in documented precedence; no trusted allocation bypass |
| T18 | Exception in issuer verifier, durable CAS store or digest computation | Sanitized unstable denial; no success side effects |
| T19 | Same invalid input permuted; C0 and C1 definitions evaluated | Deterministic canonical/hash/closure equivalence for **valid C0-compatible** data, distinct authority |
| T20 | C1 evidence passed to production Agent/Tool without D2-D/D3 grant | Refuse; no runnable/side-effect permission |
| T21 | Multiple workers/readers with publication turnover | Stable owned pinned image; read begin/end validation and no cross-epoch mixing |
| T22 | Revocation update racing C1 return | Defined linearization semantics; deny if observed before final validation; never promise D3-effect safety |

Tests must assert stable typed errors, no raw traceback/secret leaks, no partial evidence and no mutation on failure; use deterministic thread barriers and a real durable-store adapter verification stage, not merely mocks. A success fixture in a fake in-memory issuer is **test simulation only**, not production C1 attestation.

## 9. Physical Implementation Readiness — gaps and decision

| Gap | Observed blocker | Required remedy/evidence | Gate |
|---|---|---|---|
| C1-B01 | No Application-owned, independently authenticated Host Catalog issuer/composition root | Source-located production owner, deployment identity/allowlist, negative forged-issuer fixture | BLOCKED |
| C1-B02 | No durable per-lane monotonic epoch / generation / revocation store | Store schema, CAS + recovery protocol, concurrent two-worker smoke, no ABA | BLOCKED |
| C1-B03 | BaseRegistry exposes mutable records and mutation routes not fenced | Complete writer inventory and enforceable interception **or** sealed exclusive source-of-truth migration | BLOCKED |
| C1-B04 | No source-coherent Registry+adapter+edge snapshot and transaction | Owned-image builder with writer fence, immutable alias isolation, edge/adapter completeness tests | BLOCKED |
| C1-B05 | D2-A verifier may be caller-injected; no C1 authority coupling | Authenticated deployment publisher boundary, exact manifest/policy pin proof | BLOCKED |
| C1-B06 | No C1 opaque lease ownership/revocation contract or independent read authority | Exact typed issuer/lease/revocation/error schema + fault tests | BLOCKED |
| C1-B07 | No agreed operational persistence/restart/failover assumptions | Deployment topology, durable store technology, disaster recovery fencing evidence | BLOCKED |
| C1-B08 | D2-D/D3 active-use revalidation and no-permission rule not physically wired | Independent downstream design; **do not** prematurely wire while implementing C1 | OUT-OF-SCOPE HOLD |

**Implementation readiness verdict:** `C1 TRUSTED PRODUCTION IMPLEMENTATION = NOT READY / HOLD`. C0 merged CI does not lift any B01–B08 blocker. A bounded **design+test-only isolated prototype** may be separately authorized after exact normative schema review; it cannot issue a trust-positive public API or be wired to Runtime.

## 10. Proposed work packages and gates

- **C1-D1 — Physical Authority / Writer Inventory**: Map every Host issue, Registry writer, adapter writer, restart/failover actor, and package policy owner to code paths. Produce source-backed ownership + threat matrix, no implementation.
- **C1-D2 — Typed Publication / Durable Fencing Normative Contract**: Freeze lane identity, epoch/revocation CAS schema, typed issuer/lease API, resource accounting, fail-closed precedence and exact digest/provenance vectors.
- **C1-D3 — Independent Security Design Review**: Review T01–T22, transaction crash linearization, ABA, tenant cross-lane isolation, and C0 non-upgrade proof. Decide scoped prototype readiness.
- **C1-D4 — Isolated Fake-Store Test Prototype (optional)**: Tests only under explicit authorization; instrument 2-worker deterministic races and reference-copy safety, and label evidence NON_PRODUCTION.
- **C1-D5 — Real Store / Host Owner Implementation Readiness**: Source-verified application issuer, real durable CAS/lease store, all writer fences, D2-A provenance, controlled failover. Only after D1–D4 independent closure can a scoped physical implementation be separately authorized.
- **C1-D6 — Host-owned Non-runnable C1 Evidence**: Dedicated independent implementation and security reviews; *still* no D2-D executable binding, D3 privileges or general production tool integration.

Every gate requires exact immutable HEAD evidence, scoped diff review, four engineering tests, adversarial fault injection, no authority elevation, and separate merge decisions. No C1 stage inherits authorization from #114/#115.

## 11. Open decisions to freeze before implementation

1. Which actual Application service is sole Host Catalog publisher and what concrete attestation authenticates it independently of Domain packages?
2. Which durable store and CAS semantics are authoritative across concurrent processes, restarts and deployments? Is there an existing store contract to reuse?
3. Are Registries exclusively behind an owned writer service, or must the immutable publication be a separate source of truth? Enumerate direct mutation/alias paths.
4. How is D2-A package publisher verification actually deployed, and how are policy scopes/tenant identities independently pinned?
5. What precise linearization semantics apply to read-vs-revoke races, including future active-use rechecks?
6. What are the recovery/GC/retention guarantees for immutable blob images referenced by committed catalog pointers?
7. Which C1 evidence fields are required by already frozen D2-D binding, without modifying `GA02-D2-BINDING-1` compatibility?

**Final authorization ledger:** `C0=MERGED_AND_VERIFIED_C0_ONLY`; `C1_NORMATIVE_DESIGN=PROPOSED`; `C1_INDEPENDENT_REVIEW=PENDING`; `C1_PRODUCTION_IMPLEMENTATION_READINESS=HOLD_B01..B07`; `C1_IMPLEMENTATION_AUTHORIZATION=NOT_ISSUED`; `C2_D2D_D3_ACTIVE_USE=HARD_HOLD`.

---

## 12. R1–R5 Targeted Normative Security Contract Amendment v0.2

**Amendment status:** SUBMITTED FOR EXACT-HEAD INDEPENDENT RE-REVIEW; not production implementation authorization. This amendment narrows and supersedes conflicting language in §§5–11; none of the contracts below claim to be an existing deployed service. Every durable-store field and issuer/lease behavior is a **proposed normative schema** subject to physical implementation proof.

### 12.1 R1 — Read, issue, supersession and revocation linearization

**Separate meanings.** A catalog *read* grants a snapshot view only. A **C1 evidence issuance** asserts that the referenced publication was current/not-revoked at one authority-controlled linearization point, not continuously afterwards. A D2-D/D3 *active use* is a future, separate decision. There is no perpetual guarantee that previously returned C1 evidence is still current.

**Authoritative linearization points and ordering:**

1. \`Publish\` / \`Supersede\`: successful durable CAS of the lane pointer and monotonically increasing transition revision. New readers must pin the new value after the CAS. Old images remain immutable history, not current.
2. \`Revoke\`: committed durable CAS that **increments the transition revision and revocation revision** and sets the generation state \`REVOKED\` (or revokes current generation before an explicitly separate fresh publication). A revoked generation **never returns to PUBLISHED**; re-enable requires a distinct generation/epoch.
3. \`OpenRead\`: trusted issuer authenticates caller/lane and atomically obtains an issuer-owned lease identifier with exact observed lane revision, publication generation, epoch and revocation revision. A lease cannot be fabricated by re-constructing data fields, and may expire/revoke.
4. \`CompleteReadAndIssue\`: while holding the verified immutable image, perform graph verification; then a **single authoritative conditional issuance transaction** compares current \`lane_revision\`, \`epoch\`, \`generation_id\`, \`revocation_revision\`, policy/source pins and lease identity. **Successful conditional issuance is the C1 evidence linearization point**. If revoke/supersede commits before it, deny; if revoke commits afterwards, evidence is historical and no future active-use authorization is implied. A nontransactional “check then issue” gap is NOT acceptable.
5. \`Return\`: delivery may follow successful issuance. Failure/delivery cancellation leaves no partially issued object visible to the caller. A racing revoke committed **after** issuance but **before** network delivery cannot be made to retroactively undo issuance; returned evidence is tagged with the exact historical revision, and D2-D/D3 must recheck. No claim of “always deny if revocation happens before return” can be implemented without an atomic return/commit primitive.

**Deterministic schedule oracle:** with barriers \`read-start → snapshot-verified → revoke-CAS → final-issuance-CAS\`, issuance MUST deny \`C1_PUBLICATION_REVOKED\` (revoked same generation) or \`C1_EPOCH_STALE\` (superseded). With \`issuance-CAS → revoke-CAS → return\`, historical evidence MAY be delivered with original epoch and explicit non-runnable role; any active-use call MUST reject stale/revoked publication at its own later boundary. Resolve simultaneous commit contenders by durable transaction order, never by local wall-clock timestamp. Failed issuance emits no “trusted success” audit record.

**Lease cleanup:** closing/expiry affects live reader authorization and historical blob retention, not epoch reuse. Lost process leases expire/are fenced according to a bounded lease expiry policy (TBD at deployment); GC MUST conservatively preserve committed publication/evidence references until a specified safe retention condition is proved.

### 12.2 R2 — Durable CAS schema, image commit and recovery

The following is the **minimum logical store contract**, not a database migration script. Implementations must map to real transactional constraints in a later authorized unit.

| Record | Exact fields / invariant |
|---|---|
| \`catalog_lane\` | \`lane_key\` unique canonical Host-pinned tuple; \`lane_revision\` 64-bit monotonic non-reusable; \`writer_term\` monotonically fenced; \`epoch\` monotonically assigned; \`current_generation_id\`; \`current_image_digest\`; \`revocation_revision\`; \`status\` ACTIVE/REVOKED/UNAVAILABLE; \`policy_generation\`; \`source_package_generation\` |
| \`catalog_image\` | \`image_id\` unique content-addressed immutable blob pointer; bytes/profile; content digest; \`state\` PREPARED/COMMITTED/RETAINED; exact \`lane_key\`, \`generation_id\`, source/policy and adapter/edge digests; no mutable Registry instances |
| \`catalog_transition\` | Unique \`(lane_key,lane_revision)\`; unique generation ID within deployment; \`transition_kind\` PUBLISH/SUPERSEDE/REVOKE; old/new epoch/generation; writer term; exact CAS expected revision; committed image digest; audit outcome |
| \`catalog_tx\` | Unique \`(lane_key,publication_tx_id)\`; immutable request fingerprint and outcome; mismatch under same tx ID fails, identical retry reads previous committed result without repeating side effects |
| \`catalog_lease\` | Issuer-side, noncaller-mintable issuance ID; lane/epoch/generation/revision/revocation, authenticated requester/principal, expiry and current status; short-lived; never an authorization token for Tool execution |

**CAS predicate:** atomic commit only if \`lane_key\` matches, \`lane_revision == expected_revision\`, \`writer_term == current_term\`, \`revocation_revision == expected_revocation_revision\`, \`policy_generation\` and \`source_package_generation\` pins equal the Host authenticated expected pins, and PREPARED image content is durable/fully hash-checked. Commit atomically increments revision and assigns fresh epoch/generation and the COMMITTED pointer. Compare-and-set failure is a **typed denial**, never an implicit auto-retry on a newer catalog. Durable generation identifiers and epochs must survive restarts and failover without rollback; on rollback detection put lane into \`UNAVAILABLE\` until explicit operator repair.

**Publication crash table:**

| Crash point | Durable visibility | Recovery rule |
|---|---|---|
| Before durable image write | No image, no pointer | Fail; no issuance |
| After PREPARED image, before CAS | Orphan PREPARED not visible | GC only after safe retention/transaction checks; no issuer-issued read |
| CAS transaction commits but acknowledgment lost | Exactly one pointer/transition | Identify by \`publication_tx_id\` + canonical fingerprint, return existing result on identical replay; never double-increment epoch |
| After CAS, image corrupt or inaccessible | Pointer exists but image cannot authenticate | Fail closed \`C1_PUBLICATION_DIGEST_MISMATCH\` / \`C1_PUBLICATION_UNAVAILABLE\`; do not load mutable Registry fallback |
| Stale writer after failover | Higher durable writer term present | Deny \`C1_WRITER_FENCE_INVALID\`, even with old local lock |
| Restart with lease metadata lost | Lease cannot be authenticated | Deny; never reconstruct a valid lease from caller-supplied strings |

**GC/retention:** no deletion of a blob referred to by current committed lane pointer, still-valid issuer lease, or configured audit/evidence retention window. Mark/sweep or equivalent must operate against the durable pointer/lease state with the same fencing discipline. A dangling pointer cannot be “repaired” by recomputing from mutable Registry inputs. Require a real two-worker persistent CAS/failure-injection test and exact DB/storage choice before calling this production-ready.

### 12.3 R3 — Single authoritative writer model and physical mutation inventory

**Frozen conceptual choice: Catalog publisher owns a distinct sealed canonical source of truth.** Existing \`BaseRegistry\` is a mutable observation/input source, NOT the authoritative C1 catalog store. A publisher may import a Registry-derived image only from a **certified coherent, writer-fenced capture** or from a separate Host-administered immutable candidate; a mutable Registry instance, D2-B view or the C0 resolver may never issue or update current trusted C1 publication. The former “live Registry with one shared lock” alternative is **not approved** in this profile.

**Scope of physical write coverage:** enumerate direct and indirect modifications of all Registry instances: \`register\`, \`_store\`, \`unregister\`, \`enable\`, \`disable\`, \`clear\`, direct \`_records\` assignment/mutation, \`RegistryRecord.enabled/definition/implementation_ref/key\` edits, mutable nested Definition fields, reflection and shared aliases from \`get/list\`. Adapter and edge-catalog writers, Host policy generation changes and package source rotation require the same exclusive publication ownership rule. The existing Registry API is *not retroactively secure*: if any of these changes can affect a selected source image without the certified capture/generation transition, trusted C1 publication MUST refuse that source (\`C1_REGISTRY_MUTATION_UNGUARDED\`).

**Capture contract:** (a) verify actor owns Host-approved source snapshot, lane and writer fence; (b) take deeply owned bounded primitive copies, rejecting unknown/subclass/hostile values; (c) reject any \`implementation_ref\` as embedded evidence or callable authority; (d) verify source revision **from a source whose every writer is guarded** both before/after copying; (e) hash exact Definition, edge and adapter values and recheck package/policy pins; (f) atomically publish under lane CAS. A “before/after revision equal” check is **not a security proof** when untracked aliases can mutate the source. If guarded capture cannot be proven, only a separately admitted Host immutable candidate source is valid. No production C1 approval until actual code shows the latter ingestion path and authorization.

**Writer-path matrix (exact source from merged main \`01d6865d...\`):**

| Ref / code location | Physical mutation/read surface | Current writer protection | C1 action / owner |
|---|---|---|---|
| \`runtime/registries/base.py:29–36\` | Mutable \`RegistryRecord\` incl \`definition\`, \`implementation_ref\`, \`enabled\` | None observable in record type | Host Publisher: never persist record reference, reject alias as authority |
| \`runtime/registries/base.py:45–46,68–99\` | \`_records\`, \`register\`, \`_store\` | Instance dict, duplicate protection only | Host candidate capture requires independent fencing |
| \`runtime/registries/base.py:101–140\` | \`get/list\` return live records/aliases | No immutable copy/lease | Reject as trusted publication source without sealed capture |
| \`runtime/registries/base.py:142–179\` | \`unregister/enable/disable/clear\` | No cross-registry epoch | Same, plus revoke/new generation when authoritative source changes |
| \`runtime/registries/definitions.py:38–205\` | Pydantic \`Definition\` models with reference/list fields | Typed models do not establish shared Registry snapshot fencing | Deep primitive canonical copy, no retained object pointers |
| \`agent_core/domain_registry_mapping.py:230–266,269–313\` | Exact lookup of physical Registries and record reads | Local validation only, explicitly non-authoritative | No D2-B observation → C1 promotion |
| \`agent_core/domain_package_loader.py:204–249,279–335\` | \`HostPackageRootIssuer\` catalog/lease, verifier injection | Package root/publisher checks, not cross-Registry epoch | Independent package provenance must be pinned, not reused as C1 issuer |
| \`agent_core/runner.py:92–105\` | AgentRunCoordinator | Sandbox loop; explicitly not production composition root | Cannot issue C1 lease |
| \`agent_core/domain_catalog_resolution.py:995–1005\` | Private untrusted C0 read-only resolver | No Host/Registry publication authority | Algorithmic validator only; no role or authority upgrade |

The path inventory above covers inspected **physical roots and mutation primitives**; it does not yet prove all external Application/adapter/edge writers have been enumerated. **That absence remains B01/B03/B04 blocked**, not presumed closed by a Markdown table.

### 12.4 R4 — Issuer/lease contracts, typed role and hashing compatibility

**Host authenticated context (not caller-owned):** \`IssuerContextV1(issuer_capability_id, authenticated_principal_id, environment_id, tenant_scope_id, policy_generation, package_publication_proof_ref, writer_term)\`; minted by Application Composition Root from deployment-controlled policy/secret/identity evidence. The exact authentication mechanism remains a B01 physical blocker; \`issuer_capability_id\` text alone cannot authenticate. A test-only fake context must be labeled \`NON_PRODUCTION_SIMULATION\`.

**Lane canonicalization:** \`CatalogLaneIdV1(environment_id, tenant_scope_id, domain_id, domain_version, host_policy_id, namespace)\` with exact normalized NFC strings and explicit namespace (no implicit \`None\` fallback). Only the Host issuer may derive scope from authenticated policy. Cross-lane (including same domain/version but different tenant/policy) denies \`C1_LANE_SCOPE_MISMATCH\`; foreign CORE references permitted only for exact schema keys on independently authenticated allowlist, never as wildcard tenant/global Registry visibility.

**Proposed immutable image envelope (field names to freeze by exact literal vectors at next gate):**
\`{profile:"GA02-D2C-C1-IMAGE-1",lane:{...},epoch:int,generation_id:str,source_package_generation:str,verified_manifest_sha256:str,policy_generation:str,registry_definitions:[...],exact_edges:[...],adapter_attestations:[...],core_schema_allowlist:[...]}\`; canonical UTF-8/NFC JSON, sorted object keys, deterministic sorted typed arrays, zero floats, exact builtins and size ceilings inherited from approved C0 where applicable. \`catalog_digest = SHA256("GA02-D2C-C1-IMAGE-1\\0" || canonical_image_bytes)\` is content evidence only, **not a signature**. Distinct canonical profiles for lane, publication, transition and evidence must include literal domain-separated byte/hash goldens before implementation.

**Opaque lease verification:** issuer stores random/unpredictable handle issuance with exact principal, lane and source pins and validates via privileged issuer-side state. The caller may pass the opaque reference, but no dataclass reconstruction, reflection or mutable string signature substitutes for issuer-side lookup and current durable state. Lease must have specific lifetime/expiry/close/revoke and duplicate-use policy; process-local handle alone cannot survive issuer restart. Until those details are frozen, C1 trusted issuance HOLD.

**Non-runnable evidence contract:** immutable \`CatalogResolutionEvidenceC1V1(profile,lane_key,issuer_attestation_ref,publication_revision,epoch,generation_id,source_package_generation,verified_manifest_sha256,policy_generation,definition_hashes,edge_digest,adapter_digest,closure_digest,observation_role)\` with fixed \`observation_role="TRUSTED_PINNED_NON_RUNNABLE"\`. It contains no \`implementation_ref\`, callable, permission, tenant grant or \`BoundRunDomain\`. It must be produced only at \`CompleteReadAndIssue\` and must independently prove source/lease authority at verification time. D2-D may consume provenance as an **untrusted input to separately authenticated binding assembly**, not as automatic active-use. Do not modify upstream \`GA02-D2-BINDING-1\` or invent a second competing binding fingerprint in C1.

**Proposed deterministic denial precedence** (must be frozen with exact two-fault fixtures): type/shape/host issuer authentication → lane/package/policy identity → revocation/stale epoch/fence → total resource budgets → canonical Definition/digest → exact D1 closure/CORE → adapter → final atomic issuance revalidation. Caller-visible errors are code-only and sanitized; before cryptographic/issuer verification, even semantically valid metadata remains non-authoritative. There is no retry under a different epoch within one operation. Unreviewed public API => reject rather than expose a “trusted” bool flag.

### 12.5 R5 — Executable T01–T22 oracle/evidence plan

Every test must specify \`fixture\`, \`schedule\`, \`expected first code\`, \`durable state after\`, \`side-effect count\`, \`authority proof\`; an incomplete fixture is \`DESIGN_ONLY\`, not \`PASS\`. **No T01–T22 case has been executed for C1 at this design-only HEAD.**

| Tests | Fixture / scheduling obligation | Strict oracle | Evidence class |
|---|---|---|---|
| T01–T02 | Forged lease+issuer and forged C0 digest; valid data otherwise | \`C1_ISSUER_UNVERIFIED\`, zero C1 issuance | Deterministic security test, future |
| T03–T04 | Change one tenant/lane/policy field; swap one D2-A exact package SHA | \`C1_LANE_SCOPE_MISMATCH\` / \`C1_SOURCE_PACKAGE_UNVERIFIED\` | Unit + Host deployment proof |
| T05–T07 | Barrier: capture → direct alias/enable/disable/unregister/clear/\`implementation_ref\` mutation → commit | Unguarded source denied, or guarded capture image unchanged and new generation; no stale promotion | Source-writer inventory + race test |
| T08 | Two writers read revision N; release CAS concurrently | Exactly one transition N+1; losing writer \`C1_WRITER_FENCE_INVALID\` or stale CAS code, zero second publication | Two-worker real CAS |
| T09/T11 | Persist N; crash/restart; begin older writer with stale term; attempt epoch/generation reuse | Old term and old lease denied; no ABA/reuse | Real durable restart/failover |
| T10/T22 | Case A: revoke CAS before final issuance CAS; case B: issue CAS before revoke CAS and return after | Case A denied; case B historical non-runnable evidence may return, active-use still prohibited | Deterministic scheduler + real store |
| T12/T13 | Crash after PREPARED; separately crash after CAS before ACK; replay same and changed tx fingerprint | No pointer for PREPARED; one committed pointer for lost ACK; mismatched replay denied | Crash-recovery persistent store |
| T14 | Delete/corrupt referenced committed blob | \`C1_PUBLICATION_DIGEST_MISMATCH\` / unavailable, no Registry fallback | Blob-store fault injection |
| T15 | Rotate adapter generation/allowlist while read pinned | Epoch mismatch before issue if rotation commits first; historical evidence never executable | Two-writer barrier |
| T16 | Required missing D1 target, foreign CORE, optional absent, cyclic graph | Exact C0-compatible graph denial under single image; no C1 partial evidence | Canonical golden vectors |
| T17 | 2MiB+1 combined budget, 1025-scalar string, depth/edge/node overrun each isolated | Typed resource/shape denial according to approved precedence | Bounded limit tests |
| T18 | Failure at issuer validation, image write, CAS, final check, evidence issuance | Sanitized code-only denial, no uncommitted C1 evidence | Fault injection all stages |
| T19 | Permute valid Definition/edges; run C0-compatible canonical pure validation and Host issuer separately | Identical canonical digests for identical values; different roles/authority; never mutate C0 snapshot role | Literal cross-layer oracles |
| T20 | Present C1 non-runnable evidence directly to Agent/Tool/Runnable path | No active-use permission; **future D2-D/D3 verification**, not a C1 success claim | OUT-OF-SCOPE |
| T21 | Two readers pin epoch N; writer publishes N+1; stagger final issuance CAS | Issuance before turnover can return historical evidence; after turnover denies stale; never mix image versions | Two-reader/one-writer real store |

**Mandatory test fixtures:** named exact bad-pair precedence vectors (issuer+resource, lane+digest, revoke+cycle, stale epoch+adapter), in-memory reference model only as \`SIMULATED\`, real durable CAS two-worker/restart fixture before production, assertion of 0 external side effects, no raw secrets/tracebacks and exact issuance count. CI must not claim C1 PASSED from existing C0's 1461 tests.

### 12.6 B01–B07 physical owner/evidence trace and readiness ledger

| Blocker | Claimed owner boundary | Exact current code evidence | Missing physical contract before production implementation |
|---|---|---|---|
| B01 | Application Composition Root → Catalog issuer | \`agent_core/runner.py:92–105\` explicitly sandbox, not Host; \`agent_core/domain_package_loader.py:204–219\` requires externally supplied verifier | Identify actual app module, deploy-time principal/allowlist and unforgeable issuer construction |
| B02 | Durable lane store owner | \`runtime/registries/base.py:39–46\` in-memory mutable per-instance dict only | DB/store choice, schema unique constraints, writer-term fencing, epoch monotonic CAS/restart test |
| B03 | Host-owned sealed source and complete writers | \`runtime/registries/base.py:29–36,48–99,101–179\` mutable record and aliases | Complete direct/indirect writer inventory, sealed source enforcement / deny unsafe Registry capture |
| B04 | Publisher coherent capture | \`agent_core/domain_registry_mapping.py:230–313\` single-record lookups, not multi-source transaction | Verified single-image builder for Registry, edge, adapter and policy under same source revision |
| B05 | Package publisher/Host policy owner | \`agent_core/domain_package_loader.py:212–249,279–335\` lease scoped to package root | Independently authenticated package provenance + exact C1 lane/policy binding |
| B06 | Catalog issuer private lease store | \`agent_core/domain_catalog_resolution.py:995–1005\` accepts test-owned C0 input; issuer-side lease absent | Protected lease issuance/expiry/close/revoke/final CAS + impersonation tests |
| B07 | Deployment/store/recovery owner | \`BaseRegistry\` has no durable revision or image transaction; issuer only local \`RLock\` in loader | Persistence failure matrix, multi-process/failover choice, blob GC/retention and recovery evidence |

**Physical readiness assessment:** B01–B07 remain **BLOCKED / NOT IMPLEMENTED**, not closed by adding a trace row. R1/R2/R3 are now **NORMATIVE REMEDIATION SUBMITTED**; R4/R5 remain **SCHEMA/ORACLE PROFILE PROPOSED — exact vector + independent review required**. All apparent IDs and new contract names are *proposals*, not current runtime symbols.

### 12.7 Exact next gate and authorization

- \`PR116 R1–R5 TARGETED NORMATIVE AMENDMENT = SUBMITTED\`
- \`B01–B07 CODE-TRACE MATRIX = SUBMITTED, PHYSICAL GAPS OPEN\`
- \`C1 EXACT-HEAD INDEPENDENT SECURITY RE-REVIEW = PENDING\`
- \`C1 ISOLATED MODEL/TEST PROTOTYPE AUTHORIZATION = NOT ISSUED\`
- \`C1 PRODUCTION IMPLEMENTATION READINESS = HOLD\`
- \`C1 TRUST ISSUER / DOMAINBINDING / D3 = HARD HOLD\`
- \`PR116 MERGE AUTHORIZATION = NOT ISSUED\`

**Next:** GA-02 D2-C C1 — PR #116 R1–R5 Exact-HEAD Independent Normative Security Re-Review + Durable Store/Writer Boundary Readiness Gap Decision. Re-review real transaction semantics, exact precedence, and every B01–B07 unresolved physical dependency; do not silently convert a normative design into an authorized issuer.

---

## 13. R2 / R4 / R5 Final Narrow Normative Contract Amendment v0.3 — C1 Sealed-Source Ingestion Decision

**Gate:** TARGETED REMEDIATION SUBMITTED; requires a NEW exact-HEAD independent review. This §13 supersedes conflicting option-language in §§4, 7, 12.2–12.5. No physical Host issuer, durable store or trusted evidence is implemented. Test vectors below are **candidate design-oracle values**, not results of C1 execution.

### 13.1 First-slice exclusive source decision (R3 linkage; B03/B04 unchanged)

**SELECT C1-SRC-A:** only an Application/Host-owned **sealed immutable canonical candidate image** may enter the first C1 publisher. A Registry-derived candidate is NOT eligible unless later re-authorized by a separate exhaustive writer-fencing review; first slice MUST fail closed rather than attempting to capture any live \`BaseRegistry.get/list\`, \`RegistryRecord\`, mutable Pydantic alias, \`implementation_ref\`, mapper output, or C0 \`DiagnosticCatalogInputV1\` as issuer proof.

C1-SRC-A admission is an authenticated Host operation: exact principal/tenant/lane/policy and D2-A package generation pins → bounded primitive bytes captured once from an immutable deployment-controlled staging source → canonical Definition/edge/adapter validation → sealed digest and authoritative publisher transaction. Source data submitted by a domain/package/agent user, arbitrary lambda, in-memory frozen dataclass, test fixture, or unsigned path **never** constitutes an authenticated Host candidate. File immutability and object ownership are to be proved by an independently reviewed physical application boundary; absent proof, \`C1_ISSUER_UNVERIFIED\` or \`C1_REGISTRY_MUTATION_UNGUARDED\`, with no Catalog publication.

**Rotation rule:** any admitted change to exact Definition body, enabled state, namespace/tenant policy, referenced package version/digest, adapter version/identity, edge catalog, CORE schema allowlist, or revocation advances an authoritative lane transition; changes never rewrite a sealed previously published image. Revocation is not \`enabled=false\` inside an existing image. New publication has a **fresh** generation and ordered epoch. Previously admitted images are immutable history.

**Scope:** the matrix in §12.3 inventories source-level Registry write primitives, **not every deployment caller**. No evidence has been obtained yet that any actual Application sealed-source publisher exists. B01/B03/B04/B05 therefore remain BLOCKED for real C1.

### 13.2 R2 — Separate durable publication and issuance transaction contracts

**Required first-slice durability authority:** one linearizable transactional store for the per-lane current pointer, unique transitions, writer terms, revocation revisions, \`catalog_tx\` and \`catalog_issuance\`. A blob store may be separate **only if** the immutable blob is durably committed, checksum-verified and readable **before** the pointer CAS. No pointer-to-PREPARED / no out-of-band future commit assumption. The specific database, SQL isolation, locking scheme and deployment topology remain B02/B07 open until independently verified.

Add these logical records and uniqueness rules to §12.2:

| Record | Required unique key / invariant |
|---|---|
| \`catalog_writer_term\` | unique \`lane_key\`, \`term\` strictly increases on exclusive Host writer lease takeover/recovery; issued ONLY by the durable authority; no caller-supplied \`term\` upgrade |
| \`catalog_lane\` | unique \`lane_key\`; current \`lane_revision\`, \`epoch\`, \`generation_id\`, \`revocation_revision\`, \`writer_term\`, \`status\`, verified image digest and exact source/policy pins |
| \`catalog_transition\` | unique \`(lane_key,lane_revision)\`, unique \`(lane_key,generation_id)\`; monotonic committed transition log; no epoch/generation reuse |
| \`catalog_tx\` | unique \`(lane_key,publisher_tx_id)\`; immutable canonical request fingerprint; \`PENDING/COMMITTED/ABORTED\` disposition; same-key/different-fingerprint MUST deny |
| \`catalog_issuance\` | unique \`(lane_key,issuance_request_id)\`; unique \`evidence_id\`; exact issuance fingerprint, issuer-side lease ID/principal, pinned generation/epoch/revision/revocation, \`COMMITTED\` timestamp/audit outcome; **issued evidence is persisted or deterministically retrievable without replaying conditional issuance** |
| \`catalog_lease\` | unique issuer-created unguessable lease ID bound to authenticated principal, lane, fixed publication pin, expiry, usage mode and \`ACTIVE/CLOSED/REVOKED/EXPIRED\` status; process restart invalidates unpersisted leases |

**Publisher term acquisition:** the durable Host authority atomically increases \`writer_term\` for one lane as part of documented ownership takeover; that transition fences old writers immediately. The publisher CAS must compare \`writer_term\`, \`lane_revision\`, \`revocation_revision\`, current source/policy pins, expected current generation and image digest. If the store cannot guarantee atomic reads of these fields at the same serialization point, issuance/publishing are forbidden. Epoch arithmetic must not overflow or wrap: exhausted 64-bit counter / unsupported recovery point => \`UNAVAILABLE\` fail-closed, with explicit audited repair (never reset to 0). Caller timestamps are not authority.

**Publication transaction:** (P1) authenticate issuer/source, ensure durable immutable blob exists; (P2) validate canonical sealed image and expected transition; (P3) inside one durable atomic transaction check term + lane revision + revocation + source/policy + expected generation and uniqueness; mark image pointer COMMITTED, advance lane revision/epoch/generation, write unique transition and exact \`catalog_tx\` disposition; (P4) acknowledge. If ACK lost, read \`catalog_tx\` by exact ID and fingerprint and return the prior decision; no repeat CAS, no double epoch increment. If crash before commit, no new pointer is visible; prepared images may be GC'd only after fencing/retention proof.

**Conditional C1 issuance transaction:** (I1) read only a verified sealed image and issuer-minted lease; perform deterministic closure checks **outside** durable transaction; (I2) form request fingerprint over authenticated principal, lane, lease ID, exact image hash and closure, plus caller request id assigned/validated at a trusted boundary; (I3) in **one** durable serializable/linearizable transaction, first return an existing matching \`catalog_issuance\` decision for the same \`issuance_request_id\` without reassessing a newer generation; otherwise atomically validate lease \`ACTIVE\` and \`not expired\`, authenticated issuer/principal/lane, current exact lane revision/epoch/generation/revocation, policy/source pins, committed blob hash and non-revoked status, then insert a unique durable **non-runnable** evidence record. The insertion commit is \`CompleteReadAndIssue\` linearization. (I4) on lost ACK re-read by unique request key/fingerprint and return **that historical evidence** (if permitted by caller identity), marked non-runnable and original epoch. It MUST NOT be presented as fresh/current; later active-use rechecks independently. If same request ID has a different fingerprint, deny typed conflict. No two successful evidence IDs from the same request ID, including crash/restart.

**Lease lifetime:** first-slice \`SINGLE_ISSUANCE\` only; lease creation/close/expiration/revocation and successful issuance consumption are issuer-side durable state updates. No caller-created expiry or caller-provided boolean is trusted. A lease may be used once to commit a NEW issuance; duplicate **same request id+fingerprint** may retrieve the pre-existing evidence from durable issuance ledger but MUST NOT consume lease a second time. Expiry measured with authoritative transactional store clock or monotonic lease deadline checked inside transaction; for restarts, persisted lease and expiry are authoritative, otherwise fail closed. Specific TTL numeric policy remains a deployment-owned B06 decision and must be fixed prior to any production claim.

**Denial ordering within the conditional commit:** malformed/fake issuer/lease → tenant/lane/policy/package mismatch → already revoked → expired/consumed lease → stale epoch/revision/generation → immutable-image mismatch → issuance conflict/internal instability. A previously committed exact idempotent request may return its historical non-runnable record after revocation; this is **record retrieval**, not a new trusted assertion, and D2-D/D3 may never infer active authorization.

**Storage crash/GC invariant:** a committed publication pointer references durable, checksum-verified bytes; committed issuance records persist enough canonical evidence fields or their immutable evidence blob until an independently specified retention deadline. GC cannot remove images referenced by current pointer, unexpired lease, or retained issued evidence/audit record. No GC race may delete while a transaction pins an image. The concrete retention scheme and storage SQL are NOT implemented or claimed verified.

### 13.3 R4 — Exact authority/consumer schema and canonical examples

**Field-to-authority matrix (no caller-controlled upgrading):**

| Field family | Sole authoritative source | Consumer validation |
|---|---|---|
| \`principal, issuer capability, allowed environment/tenant, host policy\` | Application Composition Root / deployment-controlled identity | Privileged issuer lookup against independent deployment configuration; arbitrary strings fail |
| \`writer_term, lane_revision, epoch, revocation_revision, publication state\` | durable store CAS owner | One transactional atomic comparison; never from request body |
| \`source_package_generation, manifest digest, package publisher proof\` | independently authenticated D2-A Host publication | verify exact generation, domain/version and policy pin before C1 issuance |
| \`registry definitions, edges, adapters, CORE schema allowlist\` | Host-owned sealed immutable candidate image | copied canonical values + exact domain/namespace and deterministic limits; no live Registry alias |
| \`lease_id, expiry, principal, usage, issuance_request_id\` | issuer-controlled lease/issuance ledger | exact private lookup; no replayed fake metadata or cross-lane rebinding |
| \`closure/digests and C1 non-runnable evidence\` | pinned image algorithm + issuer transaction | content consistency **and separately** issuer-side evidence ID verification; hash alone is not a capability |
| \`DomainBinding, RunDomain, tool permissions\` | future D2-D/D3 separately approved authorities | **NOT ISSUED** from C1 |

**Candidate canonical JSON profile:** UTF-8; NFC normalization applied to strings before hash and strict reject of ambiguous/noncanonical externally serialized representations; object keys lexicographically sorted; no spaces; arrays sorted by typed fully qualified key where semantically sets; no floats/NaN, subclass, duplicate JSON keys, unpaired surrogate or invalid Unicode; use canonical lowercase SHA-256 hex. Prefix = UTF-8 \`PROFILE\`, then exactly one zero byte \`00\`, then canonical JSON bytes; SHA-256 of that sequence. Canonical value copies cannot retain mutable source references. C0's actual \`_json\` and \`_digest\` must be independently checked for identical compatible primitives; this **candidate** encoding does not silently change C0's existing implementation.

**Two independently computable literal candidate golden vectors** (ASCII, each JSON line contains zero trailing newline):
- **V-LANE-01:** prefix \`GA02-D2C-C1-LANE-1\`; bytes (143 UTF-8 bytes): \`{"domain_id":"demo","domain_version":"1.0.0","environment_id":"test","host_policy_id":"policy","namespace":"demo","tenant_scope_id":"tenant-a"}\`; \`sha256(prefix + 00 + bytes) = 1cebde41a4f3de83facb63b7550511fd36a9b635b7486214bf1bc032881709f1\`.
- **V-IMAGE-01:** prefix \`GA02-D2C-C1-IMAGE-1\`; bytes (479 UTF-8 bytes): \`{"adapter_attestations":[],"core_schema_allowlist":[],"epoch":1,"exact_edges":[],"generation_id":"gen-a","lane":{"domain_id":"demo","domain_version":"1.0.0","environment_id":"test","host_policy_id":"policy","namespace":"demo","tenant_scope_id":"tenant-a"},"policy_generation":"policy-gen-a","profile":"GA02-D2C-C1-IMAGE-1","registry_definitions":[],"source_package_generation":"pkg-a","verified_manifest_sha256":"0000000000000000000000000000000000000000000000000000000000000000"}\`; \`sha256(prefix + 00 + bytes) = b8e5af60b8bbe61fcb6fb4003657873cfbfa8688fae0861e9e4d5c1411b8fdbe\`.

**Vector limitations:** \`V-IMAGE-01\` is **hash-algorithm only**: zero referenced definitions, placeholder all-zero digest and no independently authenticated publisher render it INVALID as a real trusted Catalog publication. These are design candidates computed from the displayed byte strings, **not executed C1 tests**. Before normative freeze, re-compute with an independent implementation, add nonempty Definition/edge/adapter vectors, Unicode NFC, reordered-key, malformed and duplicate-key negative tests, source/authority-side attestation vector, and map exact D2-D \`GA02-D2-BINDING-1\` consumer fields. No public C1 trust API until those pass.

**Typed error preliminary freeze for isolated mock tests only:** \`C1_ISSUER_UNVERIFIED\` for fake issuance source/lease, \`C1_LANE_SCOPE_MISMATCH\` for tenant/policy/lane mismatch, \`C1_SOURCE_PACKAGE_UNVERIFIED\` for D2-A mismatch, \`C1_PUBLICATION_REVOKED\` for same generation revoked before issuance, \`C1_EPOCH_STALE\` for supersede, \`C1_WRITER_FENCE_INVALID\` for stale writer term, \`C1_ISSUANCE_CONFLICT\` for request ID fingerprint mismatch, \`C1_LEASE_INVALID\` for expired/consumed/unrecognized lease, \`C1_PUBLICATION_DIGEST_MISMATCH\` for committed blob corruption, \`C1_RESOURCE_LIMIT\` for resource budget breach; remaining mapping must receive independent two-fault review. If multiple faults, \`issuer→scope/source→revocation/lease/epoch→resource→definition/edge/adapter→final transactional check\` governs, except a previously committed exact issuance ID is a protected historical-ledger lookup, NOT a new issuance.

### 13.4 R5 — Exact deterministic adversarial oracle narrowing

The matrix below **removes alternative outcomes by fixing the fixture**, rather than claiming all environmental schedules always produce one code:

| ID | Fixed fixture/barrier schedule | Required first observable | Ledger / side effects |
|---|---|---|---|
| T05 | Admitted sealed image N, then mutate unrelated live Registry \`definition\` and attempt issue for N | Success only if image N unchanged and lease valid; historical non-runnable evidence; no source re-read | committed image digest unchanged; no Registry writes |
| T06 | Attempt to submit *live* Registry \`get/list\` result as sealed candidate; call register/disable at barrier | \`C1_REGISTRY_MUTATION_UNGUARDED\`, never trust-upgrade | zero publication, zero issuance |
| T07 | Swap \`implementation_ref\` on live record then attempt to admit as C1 source | \`C1_REGISTRY_MUTATION_UNGUARDED\` | zero publication, zero execution |
| T08 | Two different publisher \`tx_id\` read revision N and same term; A CAS first; B CAS on N | A: one N+1 commit; B: \`C1_EPOCH_STALE\` (same term, stale revision), NOT \`C1_WRITER_FENCE_INVALID\` | exactly one catalog_transition, one winning tx |
| T09 | Publisher term T replaced by T+1; old publisher attempts CAS with otherwise current revision | \`C1_WRITER_FENCE_INVALID\` | zero stale-writer transition |
| T10-A | Open lease N → revoke N transaction commits → new issuance N | \`C1_PUBLICATION_REVOKED\` | no new issuance |
| T10-B/T22 | Issuance N commits → revoke N commits → retry same request ID and fingerprint | exact historical non-runnable evidence ID retrieved; no fresh C1 issuance | one issuance, no runnable grant |
| T16-A | Required edge missing | \`C1_DEPENDENCY_INVALID\` | no issuance |
| T16-B | Optional edge absent **when policy explicitly permits omission** | Graph may remain valid with omission recorded, never invent target; issuer still must pass source and lease checks | zero fabricated dependency edges |
| T16-C | Optional edge points to an **explicitly present but invalid** declaration | \`C1_DEPENDENCY_INVALID\`; optional does not excuse corrupted declared target | no issuance |
| T17-A | C0-compatible diagnostic string is 1025 Unicode scalar values | \`C1_RESOURCE_LIMIT\` or separately frozen shape code; for first normative proposal choose \`C1_RESOURCE_LIMIT\` | no issuance |
| T17-B | Combined canonical input/envelope/closure exceeds 2,097,152 UTF-8 bytes | \`C1_RESOURCE_LIMIT\` | no issuance |
| T17-C | One canonical Registry Definition >10,240 UTF-8 bytes or collection >256 where C0 enforces it | \`C1_RESOURCE_LIMIT\` | no issuance |

**Boundary precision:** Python \`len(str)\` counts code points, not grapheme clusters. The proposed C1 ceiling for general strings is therefore **1024 Python code points** (not “UTF-8 bytes”, not grapheme clusters); additional exact \`_string\` validator and field-specific lengths from C0 must be preserved where applicable. 2 MiB and 10 KiB are UTF-8 **byte** counts. Exact graph \`edges\` maximum is **1024** per C0; 1025 must deny. A collection-size assertion applies only to named C0 lists with that actual bound; avoid inventing a universal “max depth 256.” Invalid \`V-IMAGE-01\` need not be admitted just to test its SHA.

**Remaining independent proof obligations:** T01–T22 have **not been executed** for C1; every first observable above is a normative expected oracle, not a reported test pass. Independently check C0 resource limits/normalization, error precedence on two-fault fixtures, optional-edge semantics against D2-C frozen design, exact store transactions, and authenticated Host issuer origin. If optional-edge policy in the frozen contract conflicts with T16-B, this amendment is **HOLD for that case** until explicit upstream compatibility amendment; do not override upstream silently.

### 13.5 Readiness and next gate

- \`C1-SRC-A HOST_SEALED_CANDIDATE_ONLY = SELECTED_FOR_REVIEW\`; all live Registry import paths for first C1 remain rejected.
- \`R2 DURABLE PUBLICATION+ISSUANCE CAS / LOST-ACK = NORMATIVE_AMENDMENT_SUBMITTED\`, physical database and cross-worker proof **MISSING**.
- \`R4 ISSUER/LEASE/ROLE + V-LANE-01 / V-IMAGE-01 CANDIDATE GOLDENS = SUBMITTED\`; deployment authenticator and nonempty vectors **MISSING**.
- \`R5 T05–T10 / T16 / T17 DETERMINISTIC_ORACLES = SUBMITTED\`; C1 runnable test implementation **MISSING**.
- \`B01..B07 C1_PRODUCTION_PHYSICAL_AUTHORITY = ALL_BLOCKED\`.
- \`PR116 EXACT_HEAD_INDEPENDENT_NORMATIVE_RE_REVIEW = PENDING\`.
- \`PR116 MERGE_AUTHORIZATION = NOT_ISSUED\`.
- \`C1 PRODUCTION_TRUST_EVIDENCE / DOMAINBINDING / D3_PERMISSIONS = HARD_HOLD\`.

**Next:** \`GA-02 D2-C C1 — PR #116 Final R2/R4/R5 Exact-HEAD Independent Security Re-Review + C1-SRC-A Sealed-Source/Issuer Test-Only Prototype Readiness\`. Do not convert draft test vectors or a mock CAS into proof of a deployed Host Catalog publisher.

---

## 14. F1–F3 Final Targeted Normative Amendment v0.4 + C1-SRC-A Isolated Test-Only Prototype Contract Freeze

**Authority level:** proposed **test-only normative contract**, subject to a NEW exact-HEAD independent security re-review. Sections here narrow conflicting details in §§12–13; they do not confer Host Catalog production authenticity, freeze the implementation of a real storage service or authorize code changes. Main source baseline remains \`01d6865d540c3dd0547ebcdd19508e71e38efddc\`. No production C1 issuer exists.

### 14.1 F1 — Host-approved explicit optional-edge absence (not silent omission)

Merged upstream D2-C §5(4) controls precedence: **every declared optional relation must resolve to either one exact versioned edge, or one Host-approved, catalog-pinned explicit absence decision**. An absent decision is an error regardless of the optional label. “Optional” means Host can explicitly authorize absence, never that an untrusted caller or resolver may silently omit an edge.

**Candidate typed \`HostOptionalAbsenceV1\`:**

| Field | Invariant and authority |
|---|---|
| \`source_key\` | Exact canonical \`kind, namespace, id, version\` of source Registry definition, pinned within Host-owned sealed candidate |
| \`relation\` | Exact declared optional relation field (e.g. \`optional_tools\`); any required relation is ineligible |
| \`target_kind, target_id\` | Exact declared target type/name from source Definition, no wildcard and no arbitrary text substitution |
| \`host_policy_generation\` | Exact independently issuer-authenticated policy generation, not package or user supplied |
| \`reason\` | Fixed \`HOST_APPROVED_OMISSION\`, evidence-only; a reason string does not authenticate permission |
| \`absence_digest\` | SHA-256 over \`GA02-D2C-C1-OPTIONAL-ABSENCE-1\` + \`00\` + canonical primitive JSON of the above five content fields |
| \`issuer_provenance\` | Private Host publisher's admitted candidate/transition reference and authenticated allowlist decision; **not** a forged string or signature-looking field |

This typed record is included in the immutable candidate image/edge-catalog closure digest, lane policy pin and eventual C1 evidence; it is never created by the graph resolver as a fallback. Exact source/target/relation + policy generation must match the captured Definition. An exact edge AND explicit absence for the same occurrence is contradictory and denies; duplicate or contradictory decisions deny. Multiple occurrences of an identical optional name must follow the same frozen occurrence identity and duplicate precedence as the upstream C0 edge policy—no implicit deduplication to evade validation. An independently Host-admitted absence permits **no target** and records the absence in closure; it does **not** approve Tool execution.

**Specific fail-closed fixture outcomes:**

| Case | Trusted sealed-source fixture | Expected resolution |
|---|---|---|
| F1-A | Declared optional \`tool-a\`; exact Host-authorized absence record current policy \`p1\` | Accept **absence as metadata only**, no fabricated edge |
| F1-B | Same declared optional name; neither edge nor absence record | \`C1_DEPENDENCY_INVALID\`; no issuance |
| F1-C | Caller-supplied fake approval text, missing Host-owned provenance | \`C1_ISSUER_UNVERIFIED\` / untrusted-source denial **before** graph success |
| F1-D | Absence record from previous policy generation | \`C1_LANE_SCOPE_MISMATCH\` / stale policy denial |
| F1-E | Both exact edge and explicit absence | \`C1_DEPENDENCY_INVALID\` |
| F1-F | Required edge replaced with optional absence record | \`C1_DEPENDENCY_INVALID\` |
| F1-G | Declared optional edge exists but target is invalid/foreign tenant | \`C1_DEPENDENCY_INVALID\`; may not silently prefer absence |

**Normative precedence correction:** §13.4 T16-B “policy explicitly permits omission” means *exact issuer-authenticated absence record admitted into current catalog* and nothing weaker. If earlier D2-C implementation has not specified a compatible occurrence identity/duplicate-error precedence for absences, that specific test case remains **HOLD_FOR_UPSTREAM_ALIGNMENT**, not an invented C0 compatibility claim.

### 14.2 F2 — Historical issuance retrieval never bypasses issuer authentication

**Distinguish NEW issuance from EXISTING historical evidence retrieval.** Both cross the issuer principal/authenticated tenant/lane boundary; only NEW issuance requires current non-revoked publication and live \`SINGLE_ISSUANCE\` lease. An existing committed request may be retrieved after revoke/expiry **solely** as a non-runnable history item, never as newly trusted/current authority.

**Single durable issuance transaction / retrieval gate:**

1. Authenticate the active request principal and issuer facility **before** any ledger lookup; derive \`environment, tenant, lane, policy\` from Host-owned verified context, not client claims.
2. Derive trusted-scoped \`issuance_request_id\`, \`request_fingerprint\`, \`caller_principal\` and \`original_lease_id\`. A caller-supplied identical request ID is not enough to own prior evidence; scope resolution precedes ledger visibility.
3. On existing \`(lane, issuance_request_id)\`, compare **constant-time where secret-bearing**, the original principal/tenant/lane/policy/package/source pins, exact canonical fingerprint and committed evidence ID/digest. Read from a tamper-protected, transactional ledger with authenticated issuer identity. Missing/corrupt/foreign-ledger record => typed denial and no evidence. Same ID with different fingerprint => \`C1_ISSUANCE_CONFLICT\`; foreign identity => \`C1_ISSUER_UNVERIFIED\` or \`C1_LANE_SCOPE_MISMATCH\`, never a record-leak existence oracle.
4. On matching COMMITTED record, return its immutable historical **\`NON_PRODUCTION_SIMULATION\`** representation in test-only prototypes; in a future real C1 service, always mark the original **\`TRUSTED_PINNED_NON_RUNNABLE\`** evidence as historical. No fresh issuance, no new success ledger row, no lease re-consumption, no version/epoch refresh and no D3 permission.
5. On absent ledger entry, validate a genuinely issuer-created **ACTIVE, single-use, not expired, not revoked** lease; transactionally check canonical pinned publication/current epoch/policy/source/revocation/Host issued principal and sealed blob, then consume lease + insert exactly one durable evidence row **within the same transaction**. If any predicate fails, deny with no evidence and no spent lease.
6. On concurrent duplicates, unique \`(lane, issuance_request_id)\` ensures at most one committed issuance. Winning request's immutable evidence ID is returned to exactly matching retriers; loser with different fingerprint denies. A crash after COMMIT before ACK never re-runs issuance.
7. Retain issued evidence bytes/hash, authenticated lineage and cross-process durable ledger until defined retention expiration; if expired/GCed, deny with a stable history-unavailable code, not fresh issuance.
8. If issuer identity provider/ledger is unavailable, fail closed; do not reconstruct a “trusted” record from an old C0 diagnostic, a signed-looking string or a cached runtime context.

**Required adversarial fixtures:** F2-A successful issuance → ACK loss → same principal identical replay ⇒ one ledger/evidence/lease-consumption, historical retrievable; F2-B same ID different fingerprint ⇒ conflict; F2-C foreign tenant/principal same ID ⇒ deny without leaking row existence; F2-D revoke between issuance and return ⇒ original historical item only; F2-E expired/consumed lease with new request ID ⇒ deny; F2-F restart and ledger corruption ⇒ deny without fallback; F2-G two workers racing same request ⇒ one commit, one identical retrieval/denial by fingerprint; F2-H lease expiration racing final CAS ⇒ serializable order, no stale fresh success.

**Physical dependency:** no such authenticated Host issuer, persisted lease store, private ledger, selected DB isolation or recovery proof currently exists. The above is only a frozen **reference-model target**, not B01/B02/B06/B07 closure.

### 14.3 F3 — Independently computed literal canonical vectors and error/limit compatibility

**Common encoding candidate:** NFC strings, canonical compact JSON with lexicographically sorted keys, \`ensure_ascii=False\`, \`allow_nan=False\`, exact UTF-8 without trailing newline; digest input = ASCII profile prefix + one literal NUL byte + canonical JSON bytes. For JSON from external bytes, reject duplicate object keys, invalid Unicode/surrogates and noncanonical input; do not silently normalize caller bytes into authenticated evidence. Values in an issuer-owned primitive image may be canonicalized only as part of the separately authenticated Host publication admission. Domain version and key profiles still follow exact upstream D1/C0 validators.

**Literal positive/hash-only reference vectors independently calculated from specified bytes (all profiles are C1 design candidates):**

| Vector | Profile + canonical JSON (no trailing LF) | UTF-8 bytes | SHA-256(prefix + \`00\` + bytes) |
|---|---|---:|---|
| V-ABS-01 | \`GA02-D2C-C1-OPTIONAL-ABSENCE-1\` + \`{"host_policy_generation":"p1","reason":"HOST_APPROVED_OMISSION","relation":"optional_tools","source_key":{"id":"helper","kind":"skill","namespace":"demo","version":"1.0.0"},"target_id":"tool-a","target_kind":"tool"}\` | 216 | \`44d1052aafdb430e715230e5eb6cc8ea626253b2a10a13d9625d573138ab5c6a\` |
| V-DEF-01 | \`GA02-D2C-C1-DEFINITION-1\` + \`{"enabled":true,"name":"café","tags":["alpha","beta"],"version":"1.0.0"}\` | 73 | \`a49961937c2704edcf37631248eed8525efec1e77d61a4923882ee3607b95e41\` |
| V-IMAGE-02 | \`GA02-D2C-C1-IMAGE-1\` + \`{"adapter_attestations":[{"adapter_generation":"a1","adapter_key":"lookup","registry_kind":"tool"}],"core_schema_allowlist":[],"epoch":2,"exact_edges":[{"relation":"required_tools","source":"skill-a","target":"tool-a"}],"generation_id":"gen-b","lane":{"domain_id":"demo","domain_version":"1.0.0","environment_id":"test","host_policy_id":"policy","namespace":"demo","tenant_scope_id":"tenant-a"},"policy_generation":"policy-gen-a","profile":"GA02-D2C-C1-IMAGE-1","registry_definitions":[{"id":"tool-a","kind":"tool","version":"1.0.0"}],"source_package_generation":"pkg-b","verified_manifest_sha256":"1111111111111111111111111111111111111111111111111111111111111111"}\` | 665 | \`0c65de29a2298b52010538ba8a2806783eb0f6e5065a41bb69db02466e9d3599\` |

These exercise nonempty relations and UTF-8 \`é\` (two UTF-8 bytes, one Python code point). **V-DEF-01 is a generic canonical JSON example, NOT a physically admitted Registry Definition type; V-IMAGE-02 is synthetic and deliberately lacks deployment/issuer evidence. Neither can be treated as a positive trusted Catalog admission or D2-D fingerprint proof.** V-LANE-01 and V-IMAGE-01 in §13.3 remain distinct previous candidate byte/hash examples. Independent cross-implementation recheck is a future review gate, not an already-executed C1 test.

**Mandatory negative vectors/oracles (targeted reference-model tests, NOT executed here):**

| ID | Mutation | Required observable |
|---|---|---|
| V-NEG-NFC | Replace NFC \`café\` with decomposed \`cafe\\u0301\` | reject externally supplied noncanonical bytes, not silently treat them as authenticated |
| V-NEG-ORDER | Reorder JSON object keys without changing semantic primitive content | canonical re-serialization yields identical digest only **after** independently verified admission, raw external noncanonical bytes rejected when canonical-wire required |
| V-NEG-DUP | \`{"a":1,"a":2}\` | duplicate field key rejected before digest |
| V-NEG-UNICODE | unpaired surrogate or invalid UTF-8 | strict decoding/canonical error, zero trusted evidence |
| V-NEG-TYPE | float, NaN, bool-as-int/subclass where strictly typed integer required | typed canonical denial |
| V-NEG-SCOPE | same image + foreign tenant/policy/lane | fail Host authority check before considering self-consistent hash |
| V-NEG-ABSENCE | valid absence digest but no authenticated Host policy approval / stale generation | deny; hash does not mint permission |
| V-NEG-2FAULT | forged issuer + 2 MiB overflow; foreign tenant + definition corruption; revoked publication + missing required edge | \`ISSUER_UNVERIFIED\` first; \`LANE_SCOPE_MISMATCH\` first; \`PUBLICATION_REVOKED\` first respectively (subject to exact immutable error taxonomy review) |

**C0 physical consistency boundaries:** \`agent_core/domain_catalog_resolution.py\` at merged main: \`_string\` uses Python \`len(str) <= 1024\`, NFC equality and rejects categories \`Cc/Cs\`; version <=32/id <=80 with regex where applicable. \`_json\` sorts keys, compact separators and emits UTF-8; \`_digest\` does profile + NUL + canonical JSON. Definition payload <=10,240 UTF-8 bytes, combined canonical evidence <=2,097,152 UTF-8 bytes, active node bound <=256, edges <=1024. A 1025-code-point string in C0 normally fails **admission/shape**; C1 reference model may choose \`C1_RESOURCE_LIMIT\` for a specific byte-budget gate, but MUST NOT describe that as an exact C0 error-code match. Under §5 upstream, depth 32 is only a **proposed** independent Host bound, not an already implemented C0 hard limit. All exact sizes/counts require isolated 1-under / boundary / 1-over tests.

**D2-D separation:** these C1 sample digests are neither the \`GA02-D2-BINDING-1\` fingerprint nor permission evidence. A dedicated future compatibility matrix must map exactly \`lane + generation + source/policy + closure hashes\` to the frozen D2-D binding contract, and validate every field under an independently authenticated composition root. C1 tests MUST assert no DomainBinding creation, run binding, Agent/Tool invocation, Registry write, or StateStore effects.

### 14.4 C1-SRC-A test-only prototype freeze (design scope, not implementation authorization)

| Dimension | Frozen **simulation-only** rule |
|---|---|
| Placement | New isolated test/reference-model module(s) and tests **only on a separately authorized branch**, without imports in production \`runtime/\`, \`agent_core/runner.py\`, package loader or Registry |
| Input | Synthetic Host candidate with owned immutable canonical primitive bytes; **never** a real Registry/Host publisher token, mutable live record, file-root lease or customer/tenant credential |
| Principal / issuer | Deliberately fake test-scoped issuer with clearly labeled \`SIMULATED\` context and explicit lane allowlist; impossible to feed into production trust checks |
| Storage | Deterministic in-memory transactional state machine implementing publication/issuance CAS, issuance ledger, lease consumption/revoke, writer fencing and lost-ACK replay **for simulation**, not proof of durable DB or cross-process restart |
| Output | \`NON_PRODUCTION_SIMULATION\` only; no \`TRUSTED_PINNED_NON_RUNNABLE\` production role, \`DomainBinding\`, active-use permission or trusted \`CatalogResolutionEvidenceC1V1\` instance |
| Fault tests | Barrier-scheduled T01–T22 + F1-A..G / F2-A..H / canonical vectors; explicitly distinguish simulated crash/restart from real durable-store failover |
| Boundaries | No new production exports, adapter binding, Tool/Skill/Workflow, network/real filesystem access, Registry writes, patient data, privilege elevation or Host secret |
| Validation | Exact-HEAD independent contract review first; after separate implementation authorization require pytest/mypy/Ruff lint/format, source import boundary review, deterministic race replay and explicit scope/merge reviews |
| Production promotion | **Forbidden** without a separate C1 physical implementation project resolving B01–B07 and real-store/issuer evidence, plus D2-D/D3 gates for any execution |

**Authorization ledger:** \`F1_EXPLICIT_ABSENCE_SCHEMA = SUBMITTED\`; \`F2_ISSUANCE_IDENTITY_AND_IDEMPOTENCY = SUBMITTED\`; \`F3_VECTOR_AND_ERROR_BOUNDARY = SUBMITTED\`; \`C1-SRC-A_TEST_ONLY_CONTRACT = PROPOSED_FOR_FREEZE\`; \`INDEPENDENT_EXACT_HEAD_RE_REVIEW = PENDING\`; \`TEST_ONLY_CODE_AUTHORIZATION = NOT_ISSUED\`; \`PR116_MERGE_AUTHORIZATION = NOT_ISSUED\`; \`C1_PRODUCTION_AUTHORITY = HOLD_B01..B07\`.

**Next gate:** \`GA-02 D2-C C1 — PR #116 F1–F3 Exact-HEAD Independent Final Design Re-Review + Test-Only Prototype Authorization Readiness\`. Independently recompute golden vectors, verify upstream optional absence and C0 limits, challenge issuer retrieval authentication and zero-authority simulation guardrails. No C1 code or PR merge without explicit separate authorization.
