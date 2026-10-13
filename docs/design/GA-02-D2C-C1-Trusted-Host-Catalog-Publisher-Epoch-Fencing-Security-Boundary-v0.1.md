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
