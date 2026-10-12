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


---

## 12. B01–B10 + R11–R13 Targeted Normative Remediation v0.2 — C0 Isolated Contract Freeze

**Status:** TARGETED DESIGN REMEDIATION SUBMITTED / INDEPENDENT EXACT-HEAD RE-REVIEW PENDING.
**Design-only authority:** This amendment overrides §§2–10 wherever they conflict, but cannot override physical source or merged upstream D2 §11. It authorizes **neither** a Python implementation nor a merge nor C1 production trust. An exact-head independent re-review and separate C0 implementation-readiness authorization are mandatory.

### 12.1 B01/B02 — Honest owner boundary and enforceable publication protocol

**Current physical availability:** No existing source-backed \`HostCatalogPublisher\`, shared Registry epoch, writer interception, generation lease or trusted issuer was found in the reviewed \`BaseRegistry\`/D2-A/D2-B interfaces. The name **\`ProposedHostCatalogOwnerV1\`** below is a *future design role*, not an implemented symbol.

**C0 permitted:** Read a test-owned, already copied immutable primitive catalog image supplied from an isolated fixture. Verify structural consistency and calculate hashes/closure. Return \`UNTRUSTED_DIAGNOSTIC_ONLY\` resolution evidence; do not attest a production publisher or consume any live Registry / D2-B observation as trustworthy evidence. A forged \`CatalogSnapshotV1\` may produce this diagnostic result, never C1 authority. C0 is not allowed to call Host Root Issuer, Registrar or D3 active-use.

**C1 required before separate authorization:** A real Application-owned HostCatalogOwner must exclusively control (a) registration intake, (b) immutable snapshot creation, (c) adapter/edge publication, (d) monotonic epoch/generation state and (e) revocation. All writes affecting authoritative eligibility must be serialized through that owner: \`register\`, \`_store\`, \`unregister\`, \`enable\`, \`disable\`, \`clear\`, direct \`RegistryRecord.enabled/definition/key/implementation_ref\` assignment, nested Pydantic field/list mutation and Host adapter/edge rotation. Existing public mutable aliases make this **not satisfied today**; a deployment merely promising “maintenance window” is insufficient. If a bypassing mutable alias or writer exists, C1 fails closed. No hand-waved direct instrumentation of \`BaseRegistry\` is approved here.

A proposed future owner would capture exact primitive/typed definition fields under enforced exclusive ownership; validate those copies against the authoritative host registration source, make a deep **value copy** with no live Python objects, hash the immutable image, then atomically publish a generation carrying its own recorded issuer provenance. A reader pins a generation and checks the authoritative epoch/revocation state before and after resolution. ABA and untracked mutation are denied by monotonic non-reuse of generation IDs and invalidation, not by two arbitrary equal strings. Historical C1 evidence still never grants D3 run permission. Source issuer and write-fencing designs, verification harness and operational deployment proof are **separate blocked work**, not made real by this paragraph.

### 12.2 B03 — First implementation is C0 only: fixed public/private surface

The first allowable **candidate implementation** (pending separate authorization) is \`agent_core/domain_catalog_resolution.py\` with an internal \`_resolve_untrusted_catalog_observation(input: DiagnosticCatalogInputV1) -> DiagnosticResolutionSnapshotV1\`. Inputs comprise only **owned primitive immutable values** created in tests; it MUST not accept a “trusted=True” flag, \`HostIssuer\`, arbitrary Registry object, callable, mutable \`RegistryRecord\`, path or file descriptor. \`DiagnosticResolutionSnapshotV1.observation_role\` must be exactly \`UNTRUSTED_DIAGNOSTIC_ONLY\`; this supersedes generic \`RESOLVED_NON_RUNNABLE\` as the C0 marker to prevent accidental treatment as C1. No exported \`resolve_verified_domain\`, \`TrustedCatalogAdmission\`, \`DomainBindingV1\`, \`BoundRunDomainV1\`, runtime consumer or privilege-upgrading conversion. All C1 contracts from §3 remain **design-only shapes**, not constructors for trusted decisions. Code/test paths must be explicitly authorized and frozen before source implementation.

### 12.3 B04/R12 — Canonical definition content profile: D2C-DEF-1

**Source definitions covered:** \`DomainManifest\`, \`ActionDefinition\`, \`StrategyDefinition\`, \`SkillDefinition\`, \`ToolDefinition\`, \`WorkflowDefinition\`, \`CapabilityDefinition\`, \`PromptDefinition\`, \`PolicyDefinition\`, \`SchemaDefinition\` (exact classes, no subclasses). The exact canonical field lists are the declared Pydantic \`model_fields\` of those ten **source-pinned** classes, compared against an explicitly committed expected field-name/type manifest in implementation tests. A changed source field is schema drift and fails closed until a versioned amendment; do not silently auto-approve a new field from dynamic reflection.

Canonical definition input to C0 is an already-owned primitive representation \`(definition_type_id, fields)\`; no call on an attacker-supplied Pydantic object. A future Host capture adapter, only with exclusive write ownership and separate security review, may convert concrete Pydantic definitions to owned primitive values after exact-class and field checks. The C0 core does **not** call arbitrary \`model_dump()\`, \`__str__()\`, \`__repr__()\`, JSON encoder hooks, pickle or \`implementation_ref\`. The manifest MUST explicitly freeze scalar/list/optional types for every declared physical field before implementation; relying only on a Pydantic field declaration is not the frozen runtime validator.

**Exact v1 canonical bytes:** Given a prevalidated mapping with every expected field present (including explicit \`null\` for optional \`None\`), recursively require \`type(value)\` to be exactly \`dict/list/str/bool/int/NoneType\` as allowed by each field, and forbid float, bytes, callable, unexpected dict/list nesting, unknown keys, NaN, Infinity or bool-as-int. String values must be NFC and contain no surrogate, forbidden control, or noncanonical identifier where an ID field is required. Enum fields use their declared enum **string value** and the allowlisted members only, not arbitrary strings. Lists are arrays of exact validated primitive types with **declared order preserved**; no sorting/deduplication during definition hashing. Serialize only fields to UTF-8 \`json.dumps(..., sort_keys=True, separators=(",",":"), ensure_ascii=False, allow_nan=False)\`, with no BOM/newline. \`definition_sha256=SHA256(b"GA02-D2C-DEF-1\\x00" + canonical_json_bytes)\`; this is a **proposed new definition-digest profile**, distinct from upstream D2-D binding-fingerprint algorithm. Independently review/check compatibility before declaring it frozen and computing authoritative reference vectors. No identity or source authentication follows merely from the hash.

C0 deterministic bounds, proposed for re-review: at most 10 KiB per canonical definition, at most 1024 Unicode characters per string and at most 256 items in each list; oversize denied before hashing. These are policy decisions, **not claims that existing Registry models already enforce them**. Before C0 implementation authorization, include a complete per-class field/type manifest and at least 10 literal independent reference hash vectors (one per class), plus Unicode and \`null\` negative fixtures. Until reference vectors and exact primitive field contracts receive independent approval, **B04 remains implementation-readiness HOLD**.

### 12.4 B05/R11 — Explicit relation inventory and edge identity

The following is the **only proposed traversable relation set** for C0:

| Source class.field | Target kind | Relation ID | Status |
|---|---|---|---|
| \`StrategyDefinition.default_actions\` | action | \`strategy.default_actions\` | required for each listed ID |
| \`SkillDefinition.required_tools\` | tool | \`skill.required_tools\` | required for each listed ID |
| \`SkillDefinition.optional_tools\` | tool | \`skill.optional_tools\` | host optional-selection policy required |
| \`WorkflowDefinition.required_tools\` | tool | \`workflow.required_tools\` | required for each listed ID |
| \`WorkflowDefinition.optional_tools\` | tool | \`workflow.optional_tools\` | host optional-selection policy required |
| \`CapabilityDefinition.skills\` | skill | \`capability.skills\` | required for each listed ID |
| \`CapabilityDefinition.workflows\` | workflow | \`capability.workflows\` | required for each listed ID |
| \`CapabilityDefinition.tools\` | tool | \`capability.tools\` | required for each listed ID |
| \`ActionDefinition.required_capability\` | capability | \`action.required_capability\` | **required if non-null** |
| \`SkillDefinition.supported_actions\` | action | \`skill.supported_actions\` | **required for each listed ID** |

**Other physically reference-like fields:** \`DomainManifest.required_core_schemas\`, \`registered_schemas\`, \`registered_intents\`, \`registered_workflows\`, \`registered_capabilities\`, \`registered_skills\`, \`registered_tools\`, \`knowledge_domains\`, \`prompt_packages\`, \`state_schema\`, \`eval_packages\`, \`feature_flags\`; \`CapabilityDefinition.intents/entities/needs/knowledge_dependencies/state_dependencies/policy_dependencies/validation_dependencies/eval_cases\`; \`ActionDefinition.allowed_planning_modes\`; Schema/Prompt strings. These are **not automatically traversed** by C0 v1: their representation does not pin target namespace/version/type, and some are taxonomy or descriptive labels rather than a Registry dependency. They MUST be marked \`UNRESOLVED_NON_GRAPH_METADATA\`, never used to assert complete operational readiness; any Host-operational profile requiring them cannot be admitted as complete without a separate exact-contract extension. \`DomainManifest.required_core_schemas\` must instead be verified by a distinct exact Host-pinned CORE Schema prerequisite check before any future C1 claim; C0 only reports \`NOT_VERIFIED\`.

**Exact edge identity:** \`(source_registry_kind,source_namespace,source_id,source_version,relation_id,ordinal,declared_target_id,target_registry_kind,target_namespace,target_id,target_version,outcome)\`. Ordinal is the zero-based **position in the declared list** (scalar \`required_capability\` uses 0). Repeated declared IDs at different ordinals are distinct edge occurrences; each requires its own Host-pinned exact edge declaration, with no conflicting target version. An extra catalog edge not corresponding to a source occurrence is invalid. \`outcome\` is exactly \`PINNED\` or \`OPTIONAL_ABSENT\`; \`OPTIONAL_ABSENT\` permitted **only** for a declared \`optional_tools\` occurrence, with \`target_kind/namespace/id/version = null\` in an explicitly versioned outcome union. \`OPTIONAL_ABSENT\` signifies a conscious Host exclusion of a genuinely optional dependency, not “the optional reference was silently dropped”; nonempty \`required_tools\` / \`supported_actions\` etc. cannot be absent. \`None\` source list means zero listed occurrences, not permission to omit another field. List \`[]\` means zero occurrences. No wildcard/“latest”/global namespace mapping.

Before C0 implementation, an independent review MUST resolve potential cycles introduced by \`Action.required_capability ↔ Capability.skills ↔ Skill.supported_actions\`, keeping v1 conservative reject-cycles behavior explicit; a legitimate cyclic graph is not proof of execution readiness. Neither coverage breadth nor cycle rejection silently grants operational completeness.

### 12.5 B06 — Exact CORE v1 constraint

Under the current D1 parser, **only \`schema\` may have \`namespace="CORE"\`**. This rule applies to seeds, edge targets, Host exception declarations and required Core Schema prerequisites. An apparent Host allowance for a CORE Tool/Skill/Action/Workflow/Capability/Prompt/Policy is denied, even if a trusted Catalog claims it. The \`CORE\` Schema must have exact key, \`SchemaDefinition.namespace="CORE"\`, \`SchemaScope.CORE\`, Host-approved (id,version) and pinned definition digest. All non-CORE dependency targets must be in the admitted domain's exact namespace; no global lookup, null namespace or implicit cross-domain edge. General shared non-schema Core registries require a separately reviewed versioned D1/provenance amendment, outside C0/C1 v1.

### 12.6 B07 — Deterministic graph rules and resource limits

**Proposed C0 test bounds (approval pending):** at most 256 D1 asset refs (aligns with D1), 256 distinct closure nodes, 1024 edge occurrences, 32 traversal depth, 256 list elements per definition field, 10 KiB serialized definition and 2 MiB total canonical input/evidence payload. Count limits *before* allocating full worklists or returning evidence; reject large/ambiguous input atomically with \`D2C_RESOURCE_LIMIT\`. Independent design re-review must verify these are adequate and consistent with 10 KiB×256 values (total 2 MiB deliberately tighter than the maximum product). Do not invent a wallclock timer or a cross-process CPU guarantee in a pure Python diagnostic implementation.

Graph ordering: sort typed seed keys lexicographically by \`(kind,namespace,id,version)\`; sort each edge by the exact source key + relation ID + ordinal + target key; use deterministic depth-first cycle detection with states \`UNSEEN/ACTIVE/DONE\`. A back-edge to ACTIVE is a cycle, **including** one introduced through a newly added Action/Capability link. Shared reachable subgraphs are allowed; duplicate occurrences are not deduplicated before edge validation. Reject missing exact edge or target; no recursive re-query of mutable Registries. Output nodes/edges sorted and immutable; no partial results. Graph limits must be tested at boundary and boundary+1, independent of Python dict insertion order.

### 12.7 B08 — Host adapter attestation remains non-authoritative in C0

Catalog key: \`(registry_kind,namespace,id,version)\`; attestation value exactly \`(adapter_key,adapter_generation,tenant_scope_allowlist_id,domain_scope,host_registration_digest)\` as upstream D2 §11.2. For C0, values are caller-supplied **diagnostic declarations**; allow explicitly \`NOT_REQUIRED_BY_DIAGNOSTIC_PROFILE\` vs \`ABSENT_UNVERIFIED\` vs \`DECLARED_NON_AUTHORITATIVE\`. None is a grant. Do not infer an Adapter from \`RegistryRecord.implementation_ref\` or call/serialize that object. Operational requirement determination, including when an adapter is mandatory, belongs to a separately authenticated Host operational profile; the C0 resolver must not mint or accept one as trusted. A future C1 requires separately verified registration digest, scope and generation under one authoritative Host epoch; any mismatch denies.

### 12.8 B09 — Domain-separated digest inventory and upstream D2-D compatibility

**Never change upstream D2 §11.7 \`GA02-D2-BINDING-1\\x00\` fingerprint bytes/root key schema or its five existing vectors.** D2-C defines *separate proposed* evidence digests; they are **not** binding fingerprints:

- \`definition_sha256\`: \`SHA256(b"GA02-D2C-DEF-1\\x00" + canonical_definition_json)\` (§12.3).
- \`edge_digest\`: \`SHA256(b"GA02-D2C-EDGES-1\\x00" + canonical_json_of_sorted_exact_edge_records)\`.
- \`host_catalog_digest\`: \`SHA256(b"GA02-D2C-CATALOG-1\\x00" + canonical_json_of_host_envelope_excluding_its_own_digest)\`.
- \`closure_digest\`: \`SHA256(b"GA02-D2C-CLOSURE-1\\x00" + canonical_json_of_sorted_seed_node_edge_and_definition_digest_evidence)\`.

Here \`\\x00\` denotes one NUL byte, **not** the four printable characters backslash/x/zero/zero; all canonical JSON uses the same strict encoding, NFC, enum, null and scalar rules in §12.3. V1 catalog envelope identity must bind D2-A package generation/digest, domain ID/version, runtime profile, host mapping policy ID/generation, whole adapter+edge+registry-definition generation and approved CORE keys; hashes computed over the envelope are consistency proofs only, with issuer authenticity separately required for C1. Exactly freeze every root and nested key and compute multiple independent golden vectors **before code authorization**. A hash can change without an epoch when the untrusted fixture changes; only a real Host owner can rotate authoritative epoch. Tests must reproduce the five upstream D2-D reference vectors without silently rewriting them.

### 12.9 B10 — Deterministic C0 typed errors, atomic denial and C1 revocation

For the diagnostic resolver, ordered precedence is:

1. \`D2C_UNTRUSTED_CATALOG_SOURCE\` for **requested C1** without verified issuer, regardless of supplied snapshots; C0 diagnostic requests are never considered C1.
2. \`D2C_CATALOG_GENERATION_MISMATCH\` / \`D2C_CATALOG_SNAPSHOT_UNSTABLE\` for explicit internally contradictory generation/epoch or unstable copied input.
3. \`D2C_RESOURCE_LIMIT\` for bounded-size/type envelope violations that can be checked before traversal.
4. \`D2C_CANONICAL_DEFINITION_INVALID\`, then \`D2C_DEFINITION_HASH_MISMATCH\` for malformed class/field/bytes or mismatched recomputed digest.
5. \`D2C_EDGE_CATALOG_INVALID\` for bad/duplicate/ambiguous edge/outcome; \`D2C_EXACT_DEPENDENCY_MISSING\` for absent approved exact target; \`D2C_DEPENDENCY_DISABLED\` for disabled required node; \`D2C_HOST_ADAPTER_MISMATCH\` for contradictions in declared adapter metadata.
6. \`D2C_DEPENDENCY_CYCLE\` for deterministic detected cycle; \`D2C_RESOLUTION_UNSTABLE\` for any unexpected normal exception (public message: code only), never a success.

All checks fail the **entire** resolution; no partial \`DiagnosticResolutionSnapshotV1\`, no “best effort”, no automatic retry against a later generation, no Registry writes/filesystem reads/Tool/LLM/StateStore calls. Preserve D2-A/D2-B prior gate exceptions at their own boundaries; an explicit composition caller may map them by reviewed fixed mapping, never interpret them as D2-C success. Do not catch \`BaseException\` cancellation/process exit. Avoid invoking attacker-controlled \`repr\`, \`str\` or callable in error creation.

Any trusted C1 check for publisher revocation or epoch drift denies before producing an authoritative result. Even C1 would still be a historical catalog view, not a lasting execution approval. D3 must do independent active-use revalidation at the point of effect; no mutation of the already issued historical evidence retroactively grants use.

### 12.10 R13 — Three independent digests and required linkage

**Never conflate:**

1. **Package file SHA-256**: D1 \`AssetReferenceV1.sha256\` and D2-A verified \`VerifiedAssetV1.content_bytes\` prove only the captured package file content under the loader's publication assumption.
2. **Registry definition SHA-256**: §12.3 canonical typed definition content obtained from an owned Host-pinned or C0 fixture-owned representation; independent of package file bytes.
3. **Host registration and adapter attestation digest**: Host-only metadata about exact Registry key, publisher generation, scopes and adapter key/generation; not recoverable from package JSON, \`implementation_ref\` or the two former hashes.

A relation between these values is made **only** by the exact asset \`(kind,namespace,id,version)\` and an independently approved Host registration edge tied to its publication and policy generation. No equality requirement between unrelated digest types, and no claim that metadata hash authenticates the file publisher. C0 labels these as diagnostic associations; C1 cannot be asserted without a trustworthy Host issuer and mutation fence.

### 12.11 Closure ledger and next review gate

| Finding | Targeted design remedy | Current authorization |
|---|---|---|
| B01/B02 | §12.1 defines future owner/protocol; accurately exposes absent physical host authority | **C1 HARD HOLD** |
| B03 | §12.2 freezes isolated C0-only API and forbids grants | C0 design candidate; code still NOT AUTHORIZED |
| B04/R12 | §12.3 gives strict canonical profile, owner and bounds; per-field manifest/golden fixtures remain a follow-on design deliverable | **C0 READINESS HOLD** |
| B05/R11 | §12.4 exhaustively classifies traversed and intentionally excluded physical relation fields; pins occurrence semantics | TARGETED DESIGN REMEDIED; independent review pending |
| B06 | §12.5 enforces schema-only CORE | TARGETED DESIGN REMEDIED; independent review pending |
| B07 | §12.6 gives deterministic graph and proposed explicit limits | Limit adequacy/review pending |
| B08 | §12.7 separates non-authoritative C0 adapter declarations from C1 grants | TARGETED DESIGN REMEDIED; independent review pending |
| B09 | §12.8 separates canonical digests and preserves D2-D reference profile | Golden vectors/nested schemas pending |
| B10 | §12.9 defines error precedence, cancellation and revocation authority | TARGETED DESIGN REMEDIED; independent review pending |
| R13 | §12.10 prevents file/definition/registration digest conflation | TARGETED DESIGN REMEDIED; independent review pending |

**Formal current status:** \`GA-02 D2-C B01–B10/R11–R13 TARGETED NORMATIVE REMEDIATION = SUBMITTED\`; \`INDEPENDENT DESIGN RE-REVIEW = PENDING\`; \`C0 IMPLEMENTATION READINESS = HOLD\` pending exact field manifests/vectors and physical test contracts; \`C1 PRODUCTION TRUST = HOLD\`; \`PR #114 MERGE = NOT AUTHORIZED\`.

**Next task:** \`GA-02 D2-C — PR #114 Exact-HEAD Targeted Independent Normative Design Re-Review + C0 Readiness Gap Assessment\`. If any blocked items remain, address them as bounded design-only amendments **before** a separate isolated implementation authorization.