# GA-02 D2-C — Trusted Catalog Epoch + Canonical Definition Digest + Exact Dependency Closure Design v0.1

**Status:** PROPOSED / INDEPENDENT DESIGN REVIEW REQUIRED / IMPLEMENTATION NOT AUTHORIZED.
**Exact design baseline:** `main@bb26be9b1442b28180d434fee8d7d6241ae72f4d` (D2-B PR #113 merged).
**Scope:** host-controlled catalog provenance, immutable read evidence, canonical definition hashing, exact transitive versioned dependency closure and a **non-runnable resolution proposal**. This design does not mint production trust, `DomainBindingV1`, `BoundRunDomainV1`, tool execution or D3 active-use permissions.

## 1. Source-of-truth and precedence

1. Existing `agent_core/domain_descriptor.py`: twelve fixed asset kinds; exact `kind, namespace, id, version, sha256, relative_path`, host domain ID or schema-only `CORE`.
2. Existing `agent_core/domain_package_loader.py`: `VerifiedPackageSnapshotV1` owns descriptor and asset bytes, but is **caller-constructible frozen data**. Its type and its self-contained digest are not trusted publisher proof. Production sealed publication remains an independent hard gate.
3. Existing `agent_core/domain_registry_mapping.py`: `_map_untrusted_observation` emits only historical `NON_AUTHORITATIVE_AT_READ` or `INERT_INSPECTION_ONLY` evidence; no trusted mapper/binding exists.
4. Existing `runtime/registries/base.py`: `BaseRegistry.get(item_id, version, namespace=...)` is exact lookup; `RegistryKey` frozen but `RegistryRecord` and `_records` mutable. The registries have no shared epoch, generation, write fence, transactional snapshot or content hash. A sequence of `get` operations **cannot certify a coherent catalog**.
5. Existing `runtime/registries/definitions.py`: definition classes are Pydantic/CanonicalModel, including versionless references in `StrategyDefinition.default_actions`, `SkillDefinition.required_tools/optional_tools`, `WorkflowDefinition.required_tools/optional_tools`, and `CapabilityDefinition.skills/workflows/tools`. `PolicyDefinition.priority` is integer. `PromptDefinition`, `CapabilityDefinition`, `SchemaDefinition` lack intrinsic `enabled`; the others listed in the D2-B kind table have it.
6. Normative priority: actual physical source > merged `docs/design/GA-02-D2-Package-Loader-Resolver-Immutable-Binding-Design-v0.1.md` §11.2, §11.4, §11.7, §11.8 and §13 > merged D2-B design §9–11 > this **proposed** D2-C physical refinement. Conflicts require explicit amendment and independent review, not silent inference.

## 2. Trust boundary and deliverable classes

D2-C must distinguish **three states**:

| Level | Evidence | Permitted result | Prohibited claim |
|---|---|---|---|
| C0: untrusted inspection | Existing D2-B observation and caller-supplied catalogs | `NON_AUTHORITATIVE_AT_READ` only | Catalog is host-issued or usable for binding |
| C1: trusted-host pinned read-only catalog | Host controls generation, source registration, scope and mutation exclusion; all provenance independently verified at a trusted composition root | Immutable `CatalogResolutionEvidenceV1` tied to exact epoch, definitions and closure, as *input to later D2-D* | Runnable permission, adapter invocation or live D3 admission |
| C2: runnable binding / active use | **Later** D2-D/D2-E and D3 gates | Outside D2-C | No D2-C object alone activates a domain |

**Important hard gap:** the current repository implements C0 only. A frozen `CatalogSnapshotV1` with `generation="host-v1"`, a supplied lambda, `__class__` check, signed-looking string, digest or private Python function is **not** proof of C1. If the host cannot provide an Application-owned pinned catalog publication and verifiable issuer/ownership boundary, the first D2-C implementation **MUST be isolated and diagnostic-only**, as in D2-B; C1 issuance and every active binding stay `HOLD`. This is a design gate, not an assumption that production HostPublisher is present.

D2-C has no Registry write permission, cannot bootstrap `DomainRegistry`, cannot fill in missing declarations, and cannot re-open package files. Never use `RegistryRecord.implementation_ref` as adapter authority.

## 3. Proposed contract shapes

### 3.1 Trusted Catalog envelope — not self-authenticating

`CatalogSnapshotV1(profile="GA02-D2C-CATALOG-1", host_catalog_generation, publisher_generation, domain_id, domain_version, runtime_profile, manifest_sha256, host_policy_id, host_policy_generation, allowed_core_schema_keys, registry_entries, adapter_entries, edge_entries, host_catalog_digest)`.

- Entries are immutable, sorted tuples, with owned primitive values only. Each `registry_entry` contains `(registry_kind, namespace, id, exact_version, definition_type, definition_sha256, record_enabled, intrinsic_enabled_or_none)`; the exact `DomainManifest` is pinned independently.
- `adapter_entry`: `(registry_kind, exact_key, adapter_key, adapter_generation, tenant_scope_allowlist_id, domain_scope, host_registration_digest)`, as specified in upstream §11.2. Adapter values may be absent **only** where the host operational profile does not require an implementation; absence means no executable capability.
- `edge_entry`: `(source_kind, source_namespace, source_id, source_exact_version, relation, target_kind, target_namespace, target_id, target_exact_version)`; optional-edge declared absence uses an explicit host-controlled outcome rather than an ambiguous null target.
- `host_catalog_generation` is a Host-issued immutable token for the **entire** adapter + exact-edge + Registry-definition snapshot. Every relevant change, disable, deletion, reassignment or revocation must rotate the generation. The `host_catalog_digest` verifies byte-level envelope consistency, **not issuer authenticity**.
- `CatalogSnapshotV1` is data. Provenance must come from an Application-owned catalog issuer maintaining publication ownership and an authoritative generation/epoch check. No API may create trusted evidence merely by accepting caller-supplied snapshots.

### 3.2 Registry key and canonical hashes

`ExactRegistryDependencyV1(registry_kind, namespace, id, version, definition_sha256, enabled_at_resolution, host_adapter_key?, host_adapter_generation?)`.

- Exact key = `(registry_kind, namespace, id, version)`; never infer version, use wildcard/alias, accept `None` namespace, list for a latest version or cross a tenant/domain.
- Definition hash input: **explicit versioned per-class allowlist** obtained from `model_dump(mode="json")` only as the starting source, then strictly validated by schema. All declared fields included, including explicit `null` values. No pickle, `repr`, `str` of arbitrary values, `implementation_ref`, dynamic callable, custom serializer, timestamp or wall-clock.
- Canonical JSON: recursive lexicographic object keys; compact separators `,` and `:`; `ensure_ascii=false`; NFC strings with invalid/surrogate/control characters rejected; enums use defined string values; strict true/false, strict integer for `priority` (`bool` is not an int), optional null only where defined; reject floats and unknown fields. Fixed list semantics: preserve order for ordered definition fields, normalize no list by guessing it is a set.
- SHA-256 over UTF-8 canonical JSON definition bytes. The hash does not attest who provided the definition; compare it against independently host-pinned registration content at C1.
- `enabled_at_resolution` means metadata observed under a trusted epoch, **not live authorization**. The D2-D binding fingerprint schema remains upstream §11.7 `GA02-D2-BINDING-1`; do not independently invent a second incompatible binding fingerprint in D2-C.

### 3.3 Dependency edges and resolved closure

`VersionedEdgeCatalogV1(profile="GA02-D2C-EDGES-1", host_catalog_generation, edges, edge_digest)` is a typed view of the **same pinned** generation, not a separately independent authority token. Edges must be exact, sorted, unique and host-authored. Source must match an actual definition field; target IDs in versionless fields are never promoted into exact versions without a matching host edge.

`CatalogResolutionEvidenceV1(profile, host_catalog_generation, manifest_sha256, host_policy_generation, source_generation, exact_seed_keys, exact_dependency_keys, exact_edges, definition_hashes, adapter_attestations, closure_digest, observation_role)` is immutable and only emitted after complete closure verification. `observation_role` is fixed `RESOLVED_NON_RUNNABLE` unless and until C1 producer authentication is separately authorized; even at C1 the evidence is **not executable**.

No public `resolve_verified_domain(...)` may accept a frozen dataclass supplied by an arbitrary caller and upgrade it to C1. In the isolated first slice, use a clearly internal function returning untrusted diagnostic-only closure or reject a production trust request.

## 4. Coherent catalog publication and epoch control (blocking design gate)

**Selected direction for independent review: immutable publication by a single Host Catalog owner**. It is preferable to pretending that several mutable Registries share an epoch when they do not. Publication protocol:

1. Host administrator pre-registers exact DomainManifest, approved definitions and adapters outside D2-C, under a trusted maintenance window / serialized owner control.
2. Host Catalog owner captures the Registry definitions and host adapter/edge declarations into **owned immutable canonical value copies**, validates strict identity/status and computes content hashes, then publishes a new `generation` atomically by swapping an immutable catalog reference.
3. Host issuer binds that publication to separately verified D2-A package generation/digest and host policy scope, and records a trusted generation identity independently of package JSON. All D2-C reads are against the single published immutable image, **never against mutable live `RegistryRecord`**.
4. Writers/disable/unregister/re-register operations must be unable to mutate the published image. Any post-publication in-place definition/list mutation or Registry `implementation_ref` swap is not controlled by current Registry APIs; therefore the publication implementation needs a guarded ownership discipline, a copy-on-publish translation that never exposes live mutable references, and reliable generation rotation on authoritative changes. Without a validated write interception/authority boundary, **fail closed for trusted C1**.
5. Reader pins one immutable generation lease/handle through full resolution and checks its epoch at begin/end. Same token equality alone is insufficient unless only Host owns token publication, preserves immutability and tracks revocations. No retry against a newer generation within one resolution operation. Fail atomically with no partial result on epoch drift.
6. A catalog generation is historical evidence: D3 must recheck active-use generation, authorization, revocation, exact definitions and permission at the point of effect. D2-C cannot close a side-effect TOCTOU window by itself.

**Alternative for independent review:** a Host-owned guarded read/write transaction with true shared locking and snapshot ownership across all Registries, adapter and edge catalogs. This requires an explicit physical mutation intercept for every Registry writer and dynamic definition mutation. Any unguarded `BaseRegistry.register/unregister/disable` path => C1 blocked. Do **not** bolt a token onto D2-B results and claim atomicity.

## 5. Exact transitive closure algorithm — deterministic, bounded, no fallback

Inputs: pinned verified D2-A byte snapshot with authenticated host source provenance (for C1), D2-B fixed kind mapping semantics, immutable catalog generation, host-owned edge catalog and operational requirements. The algorithm first checks policy/source/catalog binding and exact domain record under the same catalog epoch.

1. Seed keys: sorted exact Registry-backed D1 asset refs. Keep `knowledge/state/eval` as inert, and host-configured `prompt/rule INERT_ONLY` non-resolving. Zero seeds may generate an inspection result but never operational readiness.
2. Verify each referenced definition has the correct physical definition class, key, namespace/CORE schema scope, enabled behavior, host catalog entry and canonical `definition_sha256`.
3. Extract **only** physically declared versionless relation fields: `Strategy.default_actions → action`; `Skill.required_tools/optional_tools → tool`; `Workflow.required_tools/optional_tools → tool`; `Capability.skills → skill`, `workflows → workflow`, `tools → tool`. No inventing relations from arbitrary descriptive text, Prompt content, Schema bytes or DomainManifest display name. New relation types require versioned amendment.
4. Resolve each required declared name by exact `VersionedEdgeCatalogV1` entry with matching source key, relation and target ID. Require one unambiguous exact versioned edge, no duplicate conflicting mapping. An optional relation present in its definition is still an explicit declared edge or host-approved explicit absence; a missing optional-edge decision is **not** silently ignored.
5. For every target, require an exact approved D1 seed/asset or explicit Host-pinned Core dependency allowance with immutable reference and digest. Never use latest-version selection, a different domain's Registry, global `namespace=None` or best-effort fallback. CORE only where D1/host policy permits. Physical source does not prove a general transitive non-schema Core sharing feature; do not invent one in D2-C.
6. Compute closure with sorted worklist and `visited`/active recursion stack, bounded by host-owned maximum nodes/edges/depth (proposed defaults: nodes ≤256, edges ≤1024, depth ≤32; **not frozen** until independently reviewed against actual limits and legitimate workloads). v1 conservatively denies cycles even if harmless.
7. Reject missing definitions, disabled entries, hashes that disagree with catalog, mismatched generation/scope, dangling or duplicated edges, missing host adapter when required, circular dependencies, resource-limit overruns or any Registry read instability. Never register a missing target. Return immutable sorted nodes/edges only on full success.

Atomic failure applies to entire resolution, with no returned partial closure or leaked internal implementation references. Logging contains only public typed code and safe correlation; no package bytes or raw Registry exceptions.

## 6. Adapter evidence and separation from run authority

The fixed Host Adapter Catalog must attest `registry_kind + exact RegistryKey → adapter_key/generation`, `tenant_scope_allowlist_id`, `domain_scope` and `host_registration_digest`. Compare this with independently Host-registered values; **never** map, compare by `repr`, hash, call, serialize or execute `RegistryRecord.implementation_ref`.

A Registry record can be enabled without an eligible adapter, and a recognized adapter can exist without an operationally authorized action. Any executable claim requires a separate Host-operational profile and later D2-D/D3 admission. Missing adapter for a profile requiring one is a typed denial. A non-runnable metadata-only resolution may preserve explicit `adapter_absent` without treating it as a permission.

## 7. Proposed D2-C typed denial categories

New D2-C codes are **proposed** and must be frozen in independent review. Expose code values only, not raw exception text.

| Code | Condition |
|---|---|
| `D2C_UNTRUSTED_CATALOG_SOURCE` | Host publisher/issuer/independent policy source not proven for C1 |
| `D2C_CATALOG_GENERATION_MISMATCH` | Epoch drift or independently pinned generation differs |
| `D2C_CATALOG_SNAPSHOT_UNSTABLE` | In-place mutable observation, unguarded writer, snapshot violation |
| `D2C_CANONICAL_DEFINITION_INVALID` | Unsupported class/field, invalid unicode/number/serialization |
| `D2C_DEFINITION_HASH_MISMATCH` | Host pinned digest differs from recomputed definition |
| `D2C_EDGE_CATALOG_INVALID` | Missing, contradictory, duplicate or ambiguous versioned edge |
| `D2C_EXACT_DEPENDENCY_MISSING` | Missing exact key, wrong namespace/version or unauthorized foreign target |
| `D2C_DEPENDENCY_CYCLE` | Cycle detected in exact closure graph |
| `D2C_DEPENDENCY_DISABLED` | Required node/definition disabled |
| `D2C_HOST_ADAPTER_MISMATCH` | Adapter attestation absent/changed where required |
| `D2C_RESOURCE_LIMIT` | Approved graph or canonical-size bounds exceeded |
| `D2C_RESOLUTION_UNSTABLE` | Unexpected read/host failure; sanitized refusal |

C1 provenance/epoch failures have priority before graph traversal; invalid types/keys and canonical definitions before resolving edges; unresolved exact edges before closure completion; instability always fail-closed. Do not collapse a D2-A PackageLoadError or D2-B MappingError into a fictitious success; mapping between gate error types must be explicit and reviewed.

## 8. Concrete positive and adversarial verification matrix

| ID | Required evidence |
|---|---|
| P01 | Frozen catalog snapshot pinned to independently controlled Host issuer and exact D2-A/Policy identity (test-only simulation must be explicitly labeled) |
| P02 | One action seed with exact schema/domain metadata and deterministic definition hash |
| P03 | Strategy→Action; Skill/Workflow→Tool; Capability→Skill/Workflow/Tool via exact versioned edges |
| P04 | Two domains with colliding ID/version, no cross-domain resolution; CORE schema exact allowlist and scope |
| P05 | Stable sorted closure independent of insertion order; same Host generation and definition bytes give identical digest |
| P06 | Optional versionless relation explicitly absent by Host policy (not silently skipped); prompt/rule inert classification |
| N01 | Missing, fake, mismatched, user-supplied Host issuer token / snapshot rejected as C1; no privilege elevation from frozen dataclass |
| N02 | Epoch rotates during snapshot capture or resolution: deny, no partial evidence |
| N03 | `RegistryRecord.enabled` or definition mutable field changes without valid Host generation: deny trusted resolution |
| N04 | Definition list reorder/content change changes digest; invalid Unicode, floats, callable, extra field, bool-as-int denied |
| N05 | One source ID maps to two exact versions, no edge, wrong relation or wrong source ID: fail closed |
| N06 | Missing exact version; present latest or `namespace=None` only: refuse without fallback |
| N07 | Transitive cycle, duplicated edge, dangling target and graph limits: typed atomic denial |
| N08 | CORE/scope mismatch, tenant/cross-domain leakage, unapproved Core exception: deny |
| N09 | Host adapter rotation, missing required adapter, fake adapter reference, malicious `implementation_ref`: no authority or invocation |
| N10 | No mutation/list/execute/model/StateStore/filesystem-open from resolver; no reference to mutable RegistryRecord escapes |
| N11 | D2-A/D2-B tests and all pytest/mypy/Ruff gates PASS; GA-01C integration and real sandbox E2E independently checked |
| N12 | Simultaneous read/write/disable/unregister mutation attempts verify publication/epoch guarantee; if Host cannot enforce, trusted C1 = HOLD |
| N13 | No public runtime caller for catalog resolution or DomainBinding before separately approved D2-D/D3 gates |
| N14 | Reference fixtures for upstream D2-D §11.7 five hashes preserved; D2-C cannot silently change fingerprint encoding |

## 9. Physical implementation slices and authorization gates

**Design-only first. No implementation is authorized by creating this file.**

- **Stage A — Physical authority proof:** identify actual trusted Host Catalog owner, durable generation publication/epoch store, protected write paths, and independent D2-A publisher provenance. If missing, explicitly authorize only isolated non-authoritative test harness; **C1 production stays HOLD**.
- **Stage B — Normative contracts:** freeze exact `CatalogSnapshotV1`/edge/adapters/definition hash schema, source class allowlists, canonical byte vectors, digest and error precedence. Independent design review before code.
- **Stage C — Isolated pure resolver:** implement canonical definition bytes and graph closure from owned immutable copies only; no Registry mutation, execution, public trustworthy issuer or DomainBinding.
- **Stage D — Host-pinned integration (separately authorized):** wire real Application-controlled issuer + atomic published generation, demonstrate adversarial writer/disable/revoke race coverage. No live-run use until D2-D/D3.
- **Stage E — Evidence and closure:** exact main-target diff review, deterministic full gates, independent security/evidence review, separate PR merge authorization. Source and operational authorities remain separate.

Proposed isolation: a new `agent_core/domain_catalog_resolution.py` for pure data/closure contracts and `tests/test_ga02_d2c_catalog_resolution.py` for isolated contract tests; any Host publication adapter or changes to `runtime/registries/base.py` require separate scope/authorization. No application wiring, auto-bootstrap, model or Tool calls in the first implementation.

## 10. Unresolved design blockers for independent review

- **D2C-B01 (critical):** Which *existing physical* Application component owns Host Catalog generation and ensures immutable publication? Current `BaseRegistry` cannot attest it. Do not invent an implemented owner.
- **D2C-B02 (critical):** How are concurrent Registry/register/disable/unregister and mutable Pydantic fields intercepted or excluded without new unsafe global locks?
- **D2C-B03 (critical):** Does the first D2-C PR intentionally remain **C0 diagnostic-only**, like D2-B, until a real publisher exists? Recommendation: **yes**.
- **D2C-B04:** Freeze per-definition canonical allowlisted schemas and independent SHA-256 golden vectors, including exact JSON `null` and list-order behavior.
- **D2C-B05:** Freeze the optional relation absence contract and duplicate-ref/edge precedence (source string may be duplicated in a list).
- **D2C-B06:** Reconcile upstream allowance of Host-pinned external Core dependencies with D1's schema-only `CORE` constraint; do not silently permit a CORE Tool/Skill.
- **D2C-B07:** Pick and source-verify limits for graph size/depth, bytes and CPU budget, plus exhaustive cycle/ambiguity cases.
- **D2C-B08:** Freeze adapter attestation absence semantics and host operational profile separation, without inspecting `implementation_ref`.
- **D2C-B09:** Pin use of the upstream D2-D fingerprint §11.7 and exact host catalog generation rotation to avoid incompatible hashes.
- **D2C-B10:** Decide exact error-to-gate mapping and behavior for simultaneous host revocation; D3 active-use remains independent.

## 11. Decision

**D2-C initial normative design = SUBMITTED FOR INDEPENDENT REVIEW.**

Source-grounded architecture is feasible as a staged isolated resolver, but **production trustworthy C1 evidence is currently NOT READY** because the repository has no demonstrated Host-owned immutable Registry/Adapter/Edge catalog publisher or comprehensive mutation fence. This must not be downgraded to a cosmetic epoch token. Do not create a production trusted mapper, DomainBinding, side-effect authorization or runnable status based on this design. Next gate: **GA-02 D2-C — Targeted Independent Design Review + Host Catalog Authority/Physical Gap Assessment** at exact draft PR head, followed by bounded normative remediation.
