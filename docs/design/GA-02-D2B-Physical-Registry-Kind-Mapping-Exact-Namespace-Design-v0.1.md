# GA-02 D2-B — Physical Registry Kind Mapping + Exact Namespace Adapter Design v0.1

**Status:** PROPOSED — INDEPENDENT DESIGN REVIEW REQUIRED; D2-B code implementation **NOT AUTHORIZED**.
**Exact source baseline:** `main@6ad660511a6ceb1f385ac1dced20337608fd3660` (PR #110 normative D2 design and PR #111 D2-A isolated Linux Loader already merged).
**Scope:** a deterministic, host-controlled, **read-only** classification and exact-namespace Registry projection for already verified D2-A `VerifiedPackageSnapshotV1`. D2-B neither resolves a dependency closure (D2-C), constructs `DomainBindingV1` (D2-D), creates run bindings (D2-E), registers a package, nor enables execution. Production publisher authenticity remains independently gated.

## 1. Verified source inventory and contract precedence

1. `agent_core/domain_descriptor.py`: D1 defines exactly 12 `_KINDS`: `action`, `strategy`, `skill`, `tool`, `workflow`, `capability`, `prompt`, `knowledge`, `rule`, `schema`, `state`, `eval`. Each `AssetReferenceV1` contains exact `kind, namespace, id, version, sha256, relative_path`. D1 constrains namespace to descriptor.domain_id or `CORE`; **CORE is permitted only for `schema`**. D1 never registers metadata or authorizes runnable admission.
2. `agent_core/domain_package_loader.py`: D2-A returns frozen owned descriptor/asset bytes, trust generation ID and independently host-pinned expected manifest digest. These are inert snapshots; D2-B must consume them without reopening files.
3. `runtime/registries/base.py`: `RegistryKey(item_id, version, namespace: str|None)`, `BaseRegistry.get(item_id, version, *, namespace=None)` is exact lookup, no version/namespace fallback. `RegistryRecord` is **mutable** and includes `implementation_ref` and `enabled`; `_build_key` strips ID/version but does not normalize namespace. D2-B must not retain a mutable record or implementation.
4. `runtime/registries/{action,strategy,skill,tool,workflow,capability,prompt,policy,schema,domain}.py`: concrete classes and `register/get` signatures physically checked. Most `register` methods default to `namespace=None`; `SchemaRegistry.register` instead stores `namespace or definition.namespace`. There is **no automatic domain namespace projection** during a `get`.
5. `runtime/registries/definitions.py`: `ActionDefinition, StrategyDefinition, SkillDefinition, ToolDefinition, WorkflowDefinition, PolicyDefinition, DomainManifest` have intrinsic `enabled`; `CapabilityDefinition` and `PromptDefinition` do **not**. `SchemaDefinition` has `scope` and optional `namespace`. `CapabilityDefinition.domain` and `PromptDefinition.domain` are optional domain-label metadata, not authority.
6. Normative priority: existing physical D1/Registry contracts remain authoritative; PR #110 `§11.1–11.2` governs D2-B semantics; `§13` governs current implementation/merge/deployment authority. No D2-B design can weaken D2-A `§12` trusted package boundary.

## 2. Total D1-kind classification (trusted host-owned fixed policy)

| D1 kind | Exact Registry | Expected definition | Intrinsic ID field | D2-B v1 outcome |
|---|---|---|---|---|
| action | `ActionRegistry` | `ActionDefinition` | `action_id` | `REGISTRY_EXACT` |
| strategy | `StrategyRegistry` | `StrategyDefinition` | `strategy_id` | `REGISTRY_EXACT` |
| skill | `SkillRegistry` | `SkillDefinition` | `skill_id` | `REGISTRY_EXACT` |
| tool | `ToolRegistry` | `ToolDefinition` | `tool_id` | `REGISTRY_EXACT` (**metadata-only**, no Tool execution) |
| workflow | `WorkflowRegistry` | `WorkflowDefinition` | `workflow_id` | `REGISTRY_EXACT` |
| capability | `CapabilityRegistry` | `CapabilityDefinition` | `capability_id` | `REGISTRY_EXACT` (no host adapter claim) |
| prompt | `PromptRegistry` | `PromptDefinition` | `prompt_id` | `REGISTRY_EXACT` **only if trusted host predeclares that policy**, otherwise `INERT_ONLY` |
| rule | `PolicyRegistry` | `PolicyDefinition` | `rule_id` | `REGISTRY_EXACT` **only if trusted host predeclares that policy**, otherwise `INERT_ONLY` (never Core policy override) |
| schema | `SchemaRegistry` | `SchemaDefinition` | `schema_id` | `REGISTRY_EXACT`; strict CORE/DOMAIN scope contract |
| knowledge | **none** | none | n/a | `INERT_ONLY` (no retrieval authority) |
| state | **none** | none | n/a | `INERT_ONLY` (no StateStore mutation) |
| eval | **none** | none | n/a | `INERT_ONLY` (no evaluation approval authority) |

These 12 entries are the **exhaustive** supported D1 kind set. Classification decisions come from a trusted Application **immutable, versioned** `KindMappingPolicyV1` (host-owned). The package cannot override a category, nominate an alternate Registry, select `INERT_ONLY` to evade required host registration, or convert a Registry-backed kind into a runnable object. An unknown kind, unknown policy version, malformed class selection or unsupported active kind is a typed fail-closed error. A policy is a *declaration*; it is not a new Registry implementation.

## 3. Exact-key namespace, version, and domain admission rules

**Required key for all Registry-backed assets:** `RegistryKey(ref.id, ref.version, ref.namespace)`, where `ref.namespace` must be **non-null, byte-exact**, and equal to either the trusted domain ID or the allowed `CORE` schema reservation. Do not trim/fold `ref.namespace`, infer from a model attribute, use an alias, select a latest version, enumerate candidates or fall back to `namespace=None`.

A `RegistryRecord` returned by `registry.get(ref.id, ref.version, namespace=ref.namespace)` is accepted for projection only if `type(record.key) is RegistryKey`, `record.key == expected_key`, `type(record.definition) is expected_definition_type` (strict class, not substitutable object), and intrinsic ID + version **exactly match** ref key. The D1 parser already canonicalizes IDs/versions; never use the `BaseRegistry._build_key` implicit `strip()` to launder noncanonical data into authority.

**DomainRegistry bootstrap is separate:** `domain_registry.get(descriptor.domain_id, descriptor.domain_version, namespace=descriptor.domain_id)`. Require exact matching `DomainManifest.domain_id/version`, compatible `runtime_compatibility`, `record.enabled is True`, `definition.enabled is True`; descriptive manifest `name` is not a permission claim. A legacy DomainRegistry record with `namespace=None` does **not** satisfy exact admission. Trusted host administrators must explicitly prepare correctly namespaced Registry entries **before** D2-C; no automatic registration/migration is allowed inside D2-B.

**Schema scope:** For `ref.namespace == "CORE"`, require `SchemaDefinition.scope == SchemaScope.CORE` and the host policy must explicitly permit the exact Core schema key; for `ref.namespace == descriptor.domain_id`, require `scope == SchemaScope.DOMAIN` and `definition.namespace == descriptor.domain_id` (tight v1 policy). Stored `record.key.namespace` MUST equal reference namespace regardless of the special `SchemaRegistry.register(namespace or definition.namespace)` behavior. A namespace supplied during registration that conflicts with the definition must be rejected at classification rather than silently adopted. Neither an unregistered CORE schema nor a domain schema can be treated as a Core-contract override.

**Optional domain labels:** For `CapabilityDefinition.domain` and `PromptDefinition.domain`, if present, require it exactly equal to descriptor.domain_id; `None` is not evidence of tenancy and must not be used to bypass trusted host namespace policy. The authoritative tenant/scope policy is Application-owned and is **not** derived from `definition.domain`.

**Enabled and authority:** Always require `record.enabled is True` for registry-backed assets. Check `definition.enabled is True` **only** on Action/Strategy/Skill/Tool/Workflow/Policy; on DomainManifest via independent bootstrap. Do not invent `enabled` for Prompt/Capability/Schema. Do not consume or copy `record.implementation_ref`: a malicious or mutable callable is not a trusted adapter grant.

## 4. Proposed bounded D2-B API and immutable results (NOT an implementation approval)

- Input: D2-A `VerifiedPackageSnapshotV1`, host-owned `KindMappingPolicyV1`, and a host-provided typed `RegistryCatalogViewV1` containing the exact concrete Registry instances (or a read-only snapshot thereof). A host-sourced domain-scope / CORE schema allowlist must accompany the policy.
- Pure classifier: `classify_verified_asset(ref, policy) -> AssetClassificationV1` where mode is `REGISTRY_EXACT | INERT_ONLY`. It cannot make new executable definitions, reload assets or accept package-selected class names.
- Registry-backed projection: `inspect_exact_registry_ref(ref, registry_view, policy) -> RegistryMatchEvidenceV1` returning *only* immutable scalar identity/status metadata and the expected definition **type name**. `RegistryRecord`, `definition`, `implementation_ref`, mutable dict/list, callable, and live Registry must **not** escape.
- Inert projection: `InertAssetEvidenceV1(kind, namespace, id, version, sha256, relative_path)` linked to D2-A verified bytes, but no prompt injection interpretation, retriever instance, StateStore schema registration, tool or runtime dispatch.
- Full output: `RegistryKindMappingSnapshotV1` in descriptor-sorted stable tuple order, with exact reference identity, classification and immutable evidence. It is **resolution-input evidence**, not the D2-C transitive closure, definition content hashes, trustworthy adapter generation or `DomainBindingV1`.
- Ownership: D2-B does not call `register/enable/disable/unregister/clear/list`, does not perform tool execution, does not write StateStore, and does not modify GA-01C/D2-A code. The trusted policy is immutable for one mapping operation; to avoid concurrent mutable-Registry TOCTOU, the mapping result is only a historical observation. D2-C must add trusted pinned snapshot/epoch coherence and definition-digest evidence; D3 must revalidate active use at execution admission.

**Implementation readiness question (required):** a live `RegistryRecord` is mutable. v1 cannot honestly assert multi-registry atomic consistency with independent `get` calls alone. The D2-B code slice is permitted to emit **non-authoritative per-record observations**, never an atomic enabled/permission proof. D2-C must separately introduce a host-owned epoch/catalog consistency mechanism or refuse active binding.

## 5. Typed failures and fail-closed semantics

The proposed adapter boundary must return a typed D2-specific denial category (names below are **proposed**, not existing code values):

| Proposed error | Trigger |
|---|---|
| `D2B_UNKNOWN_KIND_OR_POLICY` | D1-kind mapping table mismatch, unsupported policy revision, unapproved routing |
| `D2B_UNSUPPORTED_ACTIVE_KIND` | Active/Registry usage demanded for `INERT_ONLY` kind or unsupported prompt/rule profile |
| `D2B_EXACT_NAMESPACE_MISMATCH` | None/foreign namespace, mismatched CORE scope, colliding schema definition metadata |
| `D2B_EXACT_DEPENDENCY_NOT_FOUND` | No exact Registry triple, no explicit exact DomainRegistry record |
| `D2B_REGISTRY_DEFINITION_MISMATCH` | Returned key wrong, incorrect runtime class, intrinsic ID/version mismatch |
| `D2B_REGISTRY_DISABLED` | Record disabled or intrinsic enabled flag disabled where physically supported |
| `D2B_TRUSTED_CATALOG_INVALID` | Missing/contradictory host policy, untrusted CORE allowlist, inconsistent provided registry view |
| `D2B_REGISTRY_OBSERVATION_UNSTABLE` | Underlying registry error, unexpected mutable-state/race observation: deny, never treat as enabled |

Public failure surfaces must not include sensitive adapter representations, implementation objects, arbitrary file bytes, callables or tenant secrets. No retry using `list()`, no namespace None fallback, no best-match versions. One failure returns **no usable mapping snapshot**.

## 6. Physical negative/positive test matrix and verification gates

| ID | Test requirement |
|---|---|
| P01 | Exhaustive deterministic 12-kind policy table, exact physical Registry and intrinsic identity fields |
| P02 | Exact typed-key lookup in two domains with identical item ID/version, never cross-resolve |
| P03 | Allowed registered CORE schema with exact key and scope; independent trusted allowlist gate |
| P04 | Prompt/rule host predeclared Registry-backed vs inert-only cases; no interpretation of inert bytes |
| N01 | Only `namespace=None` legacy record exists: typed refusal, no implicit registration |
| N02 | `SchemaRegistry.register(namespace or definition.namespace)` causes inconsistent stored key/definition namespace: reject |
| N03 | CORE namespace on non-schema, CORE schema with DOMAIN scope, DOMAIN schema with CORE scope, unapproved CORE key |
| N04 | Missing exact version; newer version present; same ID/version foreign namespace; no fallback |
| N05 | Wrong definition class, ID/version disagreement, returned RegistryKey mismatch |
| N06 | `RegistryRecord.enabled=False`, intrinsic enabled=False where supported; Prompt/Capability/Schema no fictitious enabled field |
| N07 | Malicious/mutable `implementation_ref`, swapped implementation_ref, monkeypatched callable: no invocation/serialization/authority |
| N08 | Knowledge/state/eval or host policy inert prompt/rule requested as runnable: typed denial |
| N09 | Host policy changes during invocation, missing registry/corrupt mapping, unexpected Registry exception: fail closed |
| N10 | Snapshot serialization and immutability; records/definitions/callables/Registry references never escape |
| N11 | No register/enable/disable/unregister/clear/list, filesystem reopen, model/tool/StateStore side effects |
| N12 | D2-A regression suite and exact-main 4 engineering gates remain green; GA-01C compatibility regression stays green |

**Four engineering gates for any implementation PR:** `pytest`, `mypy`, `ruff check`, `ruff format --check` over existing configured paths; GA-01C compatibility is independent mandatory evidence. Freeze test names and concrete fixture setup in a distinct implementation-readiness review before coding. Any implementation requires exact-HEAD source design review and explicit separate authorization.

## 7. Unresolved questions / independent design-review checklist

**B-D2B-01 — Trusted policy shape:** confirm a fixed v1 policy schema that cannot be authored by package JSON, including prompt/rule modes and allowlisted CORE schema keys. Keep an explicit policy provenance/generation even if D2-B only emits inert metadata.

**B-D2B-02 — DomainRegistry read-time contract:** choose whether D2-B validates DomainRegistry exact preregistration immediately or only emits host exact-domain-key prerequisites consumed in D2-C. Current proposal prefers validation in read-only D2-B, without authorizing bootstrap writes.

**B-D2B-03 — SchemaDefinition namespace relation:** test `definition.namespace` when CORE, Domain and None, and `SchemaRegistry.register` with explicit namespace/implicit fallback. Decide strict `CORE` metadata equality vs allowing absent definition.namespace for CORE; v1 proposal defaults to exact CORE equality when present and host allowlist authoritative.

**B-D2B-04 — Record consistency:** explicitly decide if the D2-B physical unit should emit only non-authoritative exact-key metadata, or needs additional host supplied snapshot control to avoid a false security guarantee. Current recommendation: non-authoritative metadata only, defer atomicity and revocation to D2-C/D3.

**B-D2B-05 — Ownership and APIs:** constrain implementation to new `agent_core/domain_registry_mapping.py` plus tests if feasible. No modifications to BaseRegistry or Registry subclass normalization; no D2-C/D/E implementation under this slice.

**B-D2B-06 — Strict error stability:** settle finite typed error enum vs existing `PackageLoadError` codes without silently changing D2-A errors; test that all unexpected Registry exceptions fail closed with redacted outputs.

**B-D2B-07 — Schema scope and global namespace:** reserve `CORE` only for schema and forbid it on any other D1 asset. Domain namespace is exact; tenant policy external.

**B-D2B-08 — Evidence and authorization boundaries:** review that test fixtures do not equate mutable record snapshots with permanent grants. Production trusted publisher is still unproven; D2-B can be built and tested as an isolated metadata adapter but not used for production domain admission.

## 8. Decision / sequencing

**Design proposal submitted only.** The mapped concrete code above supports a source-compatible D2-B *design direction*. It does not yet settle every independent B-D2B-01..08 gate and **does not authorize D2-B physical implementation**.

Next: **GA-02 D2-B — Targeted Independent Design Review + Physical Contract Gap Assessment** on the exact new Draft PR HEAD, followed (if required) by bounded design remediation, then implementation-readiness authorization. D2-C/D/E, active DomainBinding, trusted publisher deployment and PR merge decisions remain independent.

---

## 9. R1–R5 Targeted Design Remediation v0.2 — Normative Amendment

**Status: SUBMITTED / EXACT-HEAD INDEPENDENT DESIGN RE-REVIEW PENDING.** This is a design-only revision, not D2-B implementation, PR merge, D2-C/D/E development or production domain admission authorization. Physical D1, D2-A and Registry source contracts remain authoritative; merged D2 normative design §11.1–11.2 and §13 apply. Within this file §9 supersedes conflicting §§2–8; previous proposals remain as historical design context.

### 9.1 R1 — Fixed host policy and distinct admission modes

Proposed immutable KindMappingPolicyV1 exact required fields:

| Field | Required type and semantics |
|---|---|
| profile | Literal GA02-D2B-KIND-1; no default |
| host_policy_id | Nonempty trusted-host-issued canonical ID |
| host_policy_generation | Nonempty immutable host-issued generation token |
| admitted_domain_id / admitted_domain_version | D1 canonical exact domain ID and version |
| runtime_profile | Literal GA02-D1-1 |
| expected_manifest_digest | Lowercase 64-hex SHA-256 from independently pinned host source |
| expected_publication_generation_id | Host-verified SEALED publication generation ID |
| prompt_mode / rule_mode | Each exactly REGISTRY_EXACT or INERT_ONLY |
| approved_core_schema_keys | Immutable set of exact (schema_id, schema_version) pairs |
| admission_mode | Exactly INERT_INSPECTION or REGISTRY_MAPPING |

All fields are mandatory, validated at the trusted Application composition boundary. Unknown fields, modes, versions, wildcard CORE keys, mutable policy mappings or package-specified class selectors are refused. The other ten kind policies are fixed by §2; only prompt/rule have host-declared per-kind classification choices. Do not accept arbitrary callable, import path or Registry class from package data. A frozen dataclass, a string saying SEALED or a correctly formatted policy generation is NOT evidence of trusted issuance. Host policy provenance/issuer verification is required at any untrusted call boundary, and remains a production integration dependency.

Require exact coherence of policy domain ID/version/profile/expected digest/publication generation with the D2-A verified snapshot and its trusted host load provenance. VerifiedPackageSnapshotV1 is frozen data, NOT an unforgeable capability; isinstance or equality of fields alone cannot establish that the host created it. A trusted Application-controlled issuer/loading boundary must attest provenance of the independent digest, generation and root lease. Test fixtures may use a deliberately isolated test-only issuer but cannot establish production authenticity. D2-B never reopens paths or reads unverified package-supplied data.

| Admission mode | Exact behavior |
|---|---|
| INERT_INSPECTION | No DomainRegistry or per-kind Registry lookup; return inert typed reference metadata only, all tagged INERT_INSPECTION_ONLY regardless of normal kind; zero assets allowed, no enabled or runnable claim. An explicitly untrusted diagnostic is never accepted as verified mapping evidence. |
| REGISTRY_MAPPING | Require exact DomainRegistry preregistration before inspecting any asset, record and DomainManifest enabled True, descriptor.enabled True, and exact host policy/snapshot identity. Registry-backed assets undergo exact-key non-authoritative observations. Inert-only assets stay inert. Failure denies whole mapping; zero assets never grants runtime readiness. |

DomainRegistry lookup: get(descriptor.domain_id, descriptor.domain_version, namespace=descriptor.domain_id). Legacy namespace=None does not qualify. D2-B does not register or repair missing records. DomainManifest domain ID/version/runtime compatibility must match exact trusted descriptor. Tenant/scope admission comes from trusted Application, not optional definition.domain labels.

### 9.2 R2 — Exact three-way Schema namespace and scope

§3 CORE 'when present' leniency is superseded. Both cases require precise equality of stored RegistryKey.namespace, D1 ref.namespace and SchemaDefinition.namespace, with no None exception.

| Ref namespace | Stored key namespace | Definition.namespace | Definition.scope | Extra gate |
|---|---|---|---|---|
| CORE | CORE | CORE, not None | SchemaScope.CORE | Exact (id,version) present in host approved_core_schema_keys |
| Trusted domain ID | Same exact domain ID | Same exact domain ID, not None | SchemaScope.DOMAIN | Domain equals trusted policy.admitted_domain_id |

Even if SchemaRegistry.register(namespace or definition.namespace) accepted a conflicting explicit namespace or a CORE record with definition.namespace=None, reject at observation time. Check intrinsic schema_id/version exactly. CORE reserved exclusively for schema and cannot override a Core Contract. No namespace normalization, alias, case fold, None fallback, wildcard/version fallback, legacy migration or unapproved CORE global visibility.

### 9.3 R3 — Typed error and atomic denial contract

D2-B owns D2BCode(str, Enum) and D2BMappingError(ValueError) with code and public str(error) exactly equal to the stable enum value. Preserve D2-A PackageLoadError untouched. Freeze the eight §5 D2B_* codes as exhaustive v1 public categories. Apply checks in this order:

1. Missing/untrusted host policy, origin, provenance, publication/digest mismatch, invalid registry view -> D2B_TRUSTED_CATALOG_INVALID; unknown mapping kind/profile -> D2B_UNKNOWN_KIND_OR_POLICY.
2. Invalid/foreign/None namespace, CORE reservation/allowlist/schema scope mismatch -> D2B_EXACT_NAMESPACE_MISMATCH.
3. Request to treat INERT_ONLY as active -> D2B_UNSUPPORTED_ACTIVE_KIND.
4. Exact RegistryItemNotFoundError from domain or asset Registry -> D2B_EXACT_DEPENDENCY_NOT_FOUND. Catch before generic RegistryError.
5. Wrong RegistryKey, strict definition class or intrinsic ID/version/metadata -> D2B_REGISTRY_DEFINITION_MISMATCH.
6. record.enabled is not True, or intrinsic definition.enabled is not True only where defined -> D2B_REGISTRY_DISABLED.
7. Other RegistryError, unexpected read exception, malformed observed record or detectable inconsistent mutation -> D2B_REGISTRY_OBSERVATION_UNSTABLE.

Do not expose raw exception messages, file paths, bytes, tenant secrets, RegistryRecord, implementation_ref or object repr in public errors or exception formatting. Never call attacker-controlled __str__, __repr__, __call__, or untrusted callbacks. Do not swallow process-fatal conditions or cancellation. Build and return only a complete frozen mapping result after every required check succeeds; on failure, no partial result, no retry/fallback, no register/enable/disable/unregister/clear/list and no filesystem reopen. An unstable-denial code reports detected uncertainty, NOT guaranteed detection of every race.

### 9.4 R4 — Immutable non-authoritative observation evidence

Proposed frozen/slotted result values with owned scalars and tuples only:

| Result | Required immutable fields and semantics |
|---|---|
| AssetClassificationV1 | (kind, namespace, id, version) and fixed classification REGISTRY_EXACT or INERT_ONLY |
| RegistryMatchEvidenceV1 | Exact ref tuple, Registry kind, observed exact (id,version,namespace), allowlisted expected definition type name, observed record.enabled boolean, observed intrinsic definition.enabled boolean or None, observation_role=NON_AUTHORITATIVE_AT_READ |
| InertAssetEvidenceV1 | Exact ref tuple, D1 digest and normalized relative path, observation_role=INERT_ONLY |
| RegistryKindMappingSnapshotV1 | Host policy ID/generation, exact domain/version, publication generation, admission mode, non-authoritative observation role, sorted tuple of immutable evidence |

In INERT_INSPECTION mode no RegistryMatchEvidenceV1 is present and the whole snapshot is INERT_INSPECTION_ONLY. In REGISTRY_MAPPING mode, Registry evidence is marked NON_AUTHORITATIVE_AT_READ. Intrinsic enabled None is permitted only for PromptDefinition, CapabilityDefinition and SchemaDefinition; no invented enabled field. Copy no mutable RegistryRecord, live definition, implementation_ref, Registry object, mutable list/dict, callable or handle. Do not pickle, deepcopy or log execution refs. The observation is historical, and successive Registry.get calls do NOT establish an atomic multi-Registry transaction. D2-C separately owns trusted catalog epoch, canonical definition hashing, transitive closure/host adapter evidence; D3 rechecks active-use permission/revocation. No D2-B result can be consumed as a grant or an ApprovedActionPlan.

### 9.5 R5 — Mandatory physical test and implementation-isolation matrix

| Test | Deterministic requirement |
|---|---|
| P01 | Exhaustive twelve-kind host-fixed table; only prompt/rule mode varies; reject injected policy map and unknown profile |
| P02 | INERT_INSPECTION for empty and mixed assets: zero Registry reads, all inert role, no runnable authority |
| P03 | REGISTRY_MAPPING: exact enabled DomainRegistry preregistration first; exact typed lookup and ID/version checks |
| P04 | Allowed CORE schema: stored key CORE, definition namespace CORE, SchemaScope.CORE, exact host allowlist |
| N01 | Forged frozen D2-A snapshot, invalid host origin/digest/generation/domain/profile: deny before Registry access |
| N02 | Missing, namespace=None legacy, wrong version or disabled DomainRegistry record: atomic denial |
| N03 | CORE definition.namespace=None, mismatched explicit SchemaRegistry.register namespace, wrong scope or CORE list: deny |
| N04 | Identical ID/version in two domains, only newer version, None-only legacy record: never fall back |
| N05 | Wrong definition class/key/intrinsic identity, malformed record, unexpected Registry exception: redacted error |
| N06 | Record disabled, intrinsic disabled where real; no fictitious enabled on Prompt/Capability/Schema |
| N07 | implementation_ref object traps for __repr__/__str__/__call__: never inspect, serialize or invoke |
| N08 | Prompt/rule inert vs backed; knowledge/state/eval always inert; active request on inert denied |
| N09 | Concurrent observable mutation, policy generation change: deny without partial snapshot; no claim invisible changes detected |
| N10 | Result frozen/slots with owned scalars/tuples only and explicit observation role; no record/definition/callable escapes |
| N11 | No Registry mutation or list(), no filesystem re-open, model/Tool/Skill/Workflow/StateStore side effects |
| N12 | Exact-HEAD full pytest/mypy/Ruff check/format and GA-01C integration with D2-A regression |

If later authorized, implementation is confined to new agent_core/domain_registry_mapping.py and tests/test_ga02_d2b_registry_mapping.py. Do not modify BaseRegistry, concrete Registries, D1, D2-A or Agent Loop. Before physical implementation readiness, reviewers must source-check actual fixtures and constructors, identify the host trusted policy issuer entry point, and confirm strict typed error identity. If trusted host provenance is unimplemented, code may only be tested through isolated synthetic fixtures; production admission remains denied.

### 9.6 Remediation evidence and review stop lines

| Target | Remediation status | Closure status |
|---|---|---|
| R1 / B-D2B-01 | Fixed host policy and disjoint modes specified §9.1 | PENDING INDEPENDENT RE-REVIEW |
| R2 / B-D2B-03 | Uniform explicit schema namespace/scope §9.2 | PENDING INDEPENDENT RE-REVIEW |
| R3 / B-D2B-06 | Error enum, mapping and no-partial-return §9.3 | PENDING INDEPENDENT RE-REVIEW |
| R4 / B-D2B-04/08 | Non-authoritative immutable read evidence §9.4 | PENDING INDEPENDENT RE-REVIEW |
| R5 / B-D2B-05/07 | Physical fixture and scope gates §9.5 | PENDING INDEPENDENT RE-REVIEW |

**Formal status:** R1–R5 DESIGN REMEDIATION SUBMITTED; EXACT-HEAD SOURCE-COMPATIBILITY RE-REVIEW PENDING; D2-B IMPLEMENTATION NOT AUTHORIZED; PR #112 MERGE NOT AUTHORIZED; PRODUCTION PACKAGE ADMISSION NOT AUTHORIZED. Next: GA-02 D2-B — R1–R5 Targeted Independent Design Re-Review + Implementation Readiness Gap Assessment.

---

## 10. IR-01..03 Physical Implementation Readiness Contract Amendment v0.3

**Status: READINESS AMENDMENT SUBMITTED / INDEPENDENT EXACT-HEAD RE-REVIEW REQUIRED.** This appendix freezes only an *isolated, inert* D2-B implementation target and its physical test obligations. D2-B source implementation, PR #112 merge, D2-C/D/E, D3/D4 runtime activation and production host publication remain NOT AUTHORIZED. Main baseline: `6ad660511a6ceb1f385ac1dced20337608fd3660`. Scope is the source-grounded D1/D2-A/Registry interfaces pinned below.

**Precedence:** actual D1/D2-A/Registry APIs and merged D2 §§11/13 > §10 physical-readiness details > §9 normative R1–R5 remediation > compatible earlier §§1–8. §10 does not change existing exported contracts or allow previously rejected legacy namespace behavior.

### 10.1 IR-01 — Trust-source ownership, API and implementation isolation

**Physical existing entry points (verified):** `agent_core.domain_package_loader.HostPackageRootIssuer(generations: tuple[HostPublishedGeneration,...], *, publication_verifier: Callable[[HostPublishedGeneration], bool])`; `HostPackageRootIssuer.issue(generation_id)` yields `TrustedPackageRootLease`, and `LocalPackageLoader().load(lease, expected: TrustedPackageIdentity)` returns `VerifiedPackageSnapshotV1(descriptor, descriptor_bytes, assets, generation_id, expected_manifest_digest)`. `TrustedPackageIdentity` contains `(generation_id, domain_id, domain_version, runtime_profile, expected_manifest_digest)`. The existing Host issuer accepts an injected verifier; **it does not prove an actual production publisher or authentic downstream origin when a frozen snapshot is passed independently**.

**Explicit separation of trust planes:**

| Plane | Physical owner / representation | Allowed this slice | Not proved |
|---|---|---|---|
| Publisher/deployment | Existing D2-A trusted-host `HostPackageRootIssuer`, `TrustedPackageIdentity`, immutable SEALED generation policy | Test-only issuer in isolated verification, existing Loader without changes | Independently managed production immutable publication or authenticity |
| D2-B host mapping policy | New `KindMappingPolicyV1`, fixed typed value issued/configured *inside the Application composition root* | Host-owned policy *data* with exact validation; isolated test-only construction | A new authenticated/persistent production policy issuer |
| D2-B source admission | New host-owned `D2BMappingRequestV1(snapshot, policy, registry_view, origin_evidence)` passed by composition root | Test-only verified-by-fixture caller profile for metadata mapping; never public untrusted API | Authenticity of an arbitrary Python instance or caller-supplied origin marker |
| Later durable coherence | D2-C verified host catalog/registry epoch and D3 runtime revalidation | None | Atomic Registry snapshot, registration authority, executable domain binding |

**Implementation API (proposed, exact method shape for readiness):**

```python
def map_verified_package(
    snapshot: VerifiedPackageSnapshotV1,
    *,
    policy: KindMappingPolicyV1,
    registries: RegistryCatalogViewV1,
    admission: D2BTrustedAdmissionV1,
) -> RegistryKindMappingSnapshotV1: ...
```

`KindMappingPolicyV1` has precisely the required fields/types in §9.1. `RegistryCatalogViewV1` is a fixed, typed, trusted-host composition of `DomainRegistry` and the nine existing concrete per-kind Registries (Action, Strategy, Skill, Tool, Workflow, Capability, Prompt, Policy, Schema), without dictionary-selected class names from package assets. Registry slots can be deliberately absent for inert-only kinds; any required backed kind missing its typed slot fails closed. Never perform `register`, `list`, `enable`, `disable` or `clear`.

`D2BTrustedAdmissionV1` is **not a user-constructible permission token** and cannot be authenticated by type, equality, hidden string, `sealed=True`, a caller-provided lambda or dataclass `frozen=True`. It represents an *already validated trusted host call-boundary decision*. First isolated implementation may provide a private, test-only issuer/factory strictly reachable in test composition; it MUST have no production constructor or public API that accepts arbitrary `snapshot`/`policy`/`admission` and upgrades them to trusted. No security decision may derive solely from the supplied admission object's fields. For non-test untrusted integrations the public entry denies `D2B_TRUSTED_CATALOG_INVALID` until a separate production Host publication/issuer design+implementation+verification has been approved. If this call boundary cannot be enforced without a non-test bypass, implementation readiness = HOLD. This is a gating design requirement, **not** a claim the real Application already implements this issuer.

**Trusted test flow (bounded):** tests create temporary fixture bytes + independent expected digest; invoke existing D2-A issuer/lease/Loader under its injected **test-only** verifier; the same dedicated isolated test harness carries the resulting `snapshot`, source identity and host policy into the D2-B mapper. Negative cases call the ordinary boundary with forged or mismatched objects and must be denied *before any Registry.get*. Synthetic production trust assertions are explicitly prohibited. Trusted source coherence compares exact `(descriptor.domain_id, descriptor.domain_version, descriptor.runtime_compatibility, manifest_digest, generation_id)` against the independently supplied test host identity/policy (including D2-A `expected_manifest_digest`); for Registry mapping require `descriptor.enabled is True`. D2-B does not reopen the source tree or retain a file descriptor.

**Data-only limitation:** `INERT_INSPECTION` returns `INERT_INSPECTION_ONLY` for all kinds with zero Registry calls, even if D1 asset kind normally maps to a Registry. The function may decline unsigned inspection as a trusted snapshot; externally supplied data may be described as *untrusted diagnostic* by a separately typed API only, never fed to D2-C. `REGISTRY_MAPPING` requires explicit exact `DomainRegistry.get(domain_id,version,namespace=domain_id)` and checks DomainManifest `runtime_compatibility == descriptor.runtime_compatibility`, domain ID/version and both enabled values. Zero assets are never runnable.

### 10.2 IR-02 — Concrete error boundary and no-partial-result verification

**Actual exception classes:** `runtime.registries.errors.RegistryError`, `RegistryItemNotFoundError(RegistryError)`, `InvalidRegistryItemError(RegistryError)`; D2-A has distinct `PackageLoadError(PackageLoadCode)` and the D1 parser has `PackageDescriptorError(ValueError)`. Do not leak their raw messages into D2-B errors, and do not retrofit D2-A error enums.

**New error shape:** `D2BCode(str, Enum)` with exactly the eight `D2B_*` values in §5/§9.3; `D2BMappingError(ValueError)` exposes immutable `code: D2BCode` and `str(error) == error.code.value`, with sanitized `raise ... from None` for captured unsafe Registry/host failures. No diagnostic path includes `__repr__`/`__str__` of a record, implementation reference or foreign exception.

| Specific Python failure | Required output / ordering |
|---|---|
| Invalid profile/policy shape or missing trusted admission, wrong snapshot generation/digest | `D2B_TRUSTED_CATALOG_INVALID` (before any Registry.get) |
| Unsupported kind/profile with otherwise valid host context | `D2B_UNKNOWN_KIND_OR_POLICY` |
| D1 ref wrong namespace / CORE not allowlisted / Schema scope-or-metadata mismatch | `D2B_EXACT_NAMESPACE_MISMATCH` |
| Attempt to request active use of inert-only classification | `D2B_UNSUPPORTED_ACTIVE_KIND` |
| Exact `RegistryItemNotFoundError` from required `get` | `D2B_EXACT_DEPENDENCY_NOT_FOUND`; catch more specific subclass first |
| Wrong exact `RegistryKey`, Python definition class, ID/version or domain metadata | `D2B_REGISTRY_DEFINITION_MISMATCH` |
| `record.enabled is not True` or actual intrinsic `.enabled is not True` | `D2B_REGISTRY_DISABLED`; no fictitious enabled field on Prompt/Capability/Schema |
| Other `RegistryError`, `InvalidRegistryItemError`, mutated/broken record access, unexpected ordinary `Exception` from trusted read | `D2B_REGISTRY_OBSERVATION_UNSTABLE`, redacted |

**Atomic return rule:** accumulate only private, primitive, bounded evidence; any denial discards the whole accumulated result; publish no generator/callback/partial tuple before completing all verifications. Error paths do not call Registry `list()`, mutate Registry, serialize exception cause/trace to public response, re-open filesystem assets or retry a different namespace/version. `KeyboardInterrupt`, `SystemExit`, `GeneratorExit` and genuine cancellation/base process termination must propagate; do not catch `BaseException` as a blanket data-denial. Ordinary `Exception` from a Registry read is sanitized and denied. An unstable observation is an alert on visible inconsistency, not proof every race was detected.

**Adversarial fixture:** inject `RegistryRecord.implementation_ref` object whose `__repr__`, `__str__`, `__call__` raise if invoked; assert none executes even on errors. Simulate a Registry `get()` returning a wrong-key record, throwing `RegistryItemNotFoundError`, generic `RegistryError`, and ordinary `RuntimeError` whose message includes a fake secret; each must map to stable public code with no leak. Inject a record.enabled flip detectable between reads; deny if actually observed, but never claim synchronized cross-Registry atomicity.

### 10.3 IR-03 — Source-accurate fixture constructors and test naming

**D1/D2-A fixture:** reuse the structure from `tests/test_ga02_d2a_package_loader.py`: `package_bytes(assets, enabled=True)` creates canonical JSON including exact `package_schema_version='1'`, `domain_id='inventory.reconcile'`, `domain_version='1.0.0'`, `runtime_compatibility='GA02-D1-1'`, `name`, and sorted D1 `asset_refs` with `kind, namespace, id, version, sha256, relative_path`. Digest is SHA-256 of canonical no-manifest-digest JSON (sort keys, compact separators, ensure_ascii=False). Existing D2-A helper `prepare(tmp_path, assets)` publishes `package.json` and assets, constructs `TrustedPackageIdentity('generation-1',domain,version,profile,digest)`, then `HostPackageRootIssuer((HostPublishedGeneration(identity,str(tmp_path),True),), publication_verifier=TEST_ONLY_LAMBDA)`; `with issuer.issue(...) as lease: snapshot=LocalPackageLoader().load(lease,identity)`.

**Fixture caution:** D2-A `ref()` currently creates `kind='action'` for all its helper asset names, including a prompt-like filename; D2-B tests MUST generate each desired D1 kind explicitly and recalculate digest, rather than mistaking a filename for a declared kind. `AssetReferenceV1`, `PackageDescriptorV1`, `VerifiedPackageSnapshotV1` are frozen dataclasses but are constructible by callers; negative tests must forge them and assert denial at the trusted boundary.

| Fixture type | Exact source-grounded constructor fields |
|---|---|
| DomainManifest | `DomainManifest(domain_id='inventory.reconcile',name='Inventory Reconciliation',version='1.0.0',enabled=True,runtime_compatibility='GA02-D1-1')` |
| DomainRegistry | `DomainRegistry().register(manifest, namespace='inventory.reconcile')`; legacy negative uses `namespace=None`; `get(domain_id,version,namespace=domain_id)` |
| ActionDefinition | `ActionDefinition(action_id='stock.count',version='1.0.0',category='inventory',description='count',intrusiveness_level=IntrusivenessLevel.LOW,requires_confirmation=False,required_capability=None,allowed_planning_modes=[PlanningMode.DETERMINISTIC])` — source-verified member in `runtime.contracts.enums.PlanningMode` |
| StrategyDefinition | `StrategyDefinition(strategy_id='stock.strategy',version='1.0.0',description='...',preferred_goals=[],preferred_needs=[],compatible_emotions=[],required_conditions=[],avoid_conditions=[],default_actions=[],intrusiveness_level=IntrusivenessLevel.LOW)` |
| SkillDefinition | `SkillDefinition(skill_id='stock.skill',version='1.0.0')` |
| ToolDefinition | `ToolDefinition(tool_id='stock.tool',version='1.0.0')` |
| WorkflowDefinition | `WorkflowDefinition(workflow_id='stock.workflow',version='1.0.0')` |
| CapabilityDefinition | `CapabilityDefinition(capability_id='stock.capability',version='1.0.0',domain='inventory.reconcile')`; **no intrinsic enabled** |
| PromptDefinition | `PromptDefinition(prompt_id='stock.prompt',version='1.0.0',layer=PromptLayer.DOMAIN,domain='inventory.reconcile')`; **no intrinsic enabled** |
| PolicyDefinition | `PolicyDefinition(rule_id='stock.rule',version='1.0.0',priority=1,scope='inventory.reconcile')` |
| SchemaDefinition CORE | `SchemaDefinition(schema_id='shared.schema',version='1.0.0',scope=SchemaScope.CORE,namespace='CORE')`; register with exact `namespace='CORE'` and exact host allowlist |
| SchemaDefinition DOMAIN | `SchemaDefinition(schema_id='stock.schema',version='1.0.0',scope=SchemaScope.DOMAIN,namespace='inventory.reconcile')` |

Actual concrete Registry `register` functions for Action/Strategy/Skill/Tool/Workflow/Capability/Prompt/Policy all accept `(definition, *, namespace: str|None=None, implementation_ref=None)`; `SchemaRegistry.register` uses `namespace or definition.namespace`. Build one typed `RegistryCatalogViewV1` from instances, not a dictionary of strings/classes controlled by package input. The tests should assert `get(id,version,namespace=domain)` and exact returned `RegistryRecord.key` and intrinsic definition identity, not infer namespace from optional definition.domain.

**Test modules/names after approval:** new `tests/test_ga02_d2b_registry_mapping.py` with `test_d2b_p01_*` through `test_d2b_p04_*` and `test_d2b_n01_*` through `test_d2b_n12_*`; `pytest` full and targeted, `python -m mypy agent_core runtime tests` (or repository-pinned full command), `python -m ruff check agent_core runtime tests`, `python -m ruff format --check agent_core runtime tests`, plus GA-01C compatibility workflows. `PlanningMode.DETERMINISTIC` is confirmed in `runtime.contracts.enums`; tests must still execute the actual constructor before authorization.

### 10.4 Readiness authorization limits and evidence ledger

| Item | Current contractual readiness | Still required before isolated implementation authorization |
|---|---|---|
| IR-01 | Host-owned test-only call boundary and provenance expectations specified | Exact test-only issuer integration and non-test fail-closed entry must be independently reviewed; real publisher remains separate |
| IR-02 | Finite Python exception/error/atomicity handling specified | Independent test fixture map and implementation boundaries checked |
| IR-03 | Physical constructors and fixture setup mapped against current modules | Actual PlanningMode enum choice, true run-tested fixture validity, exact HEAD readiness signoff |

**Formal state:** `IR-01..03 READINESS AMENDMENT = SUBMITTED`; `D2-B READINESS INDEPENDENT EXACT-HEAD REVIEW = PENDING`; `D2-B IMPLEMENTATION AUTHORIZATION = NOT ISSUED`; `PR #112 MERGE = NOT AUTHORIZED`; `PRODUCTION HOST ISSUER / IMMUTABLE SEALED PUBLICATION = NOT PROVEN`; `D2-C/D/E/D3 ACTIVATION = NOT AUTHORIZED`.

**Next:** GA-02 D2-B — IR-01..03 Targeted Independent Implementation Readiness Re-Review. On PASS, separately authorize **isolated, test-only metadata mapping** without production entry; on any host provenance bypass or physical constructor mismatch, HOLD.

---

## 11. IR-01A / IR-03A Final Test-Only Admission Boundary + Executable Fixture Amendment v0.4

**Status:** TARGETED DESIGN AMENDMENT SUBMITTED — exact-HEAD targeted independent review required. This is NOT code implementation, a GitHub PR merge authorization or real host publisher admission. The permitted first implementation is an **isolated metadata-only test harness**, with zero production-consumable trusted mapping entry points.

**Precedence:** real physical D1/D2-A/Registry contracts and merged D2 §11/§13 > this §11 final two-item gate > §10 readiness proposal > §9 normalized design > §§1–8 background. §11 deliberately narrows the apparent public `map_verified_package` signature in §10.1: the name and `admission` object from §10 are a conceptual future host boundary, **not an approved public production API for the first implementation**.

### 11.1 IR-01A — Enforceable test-only separation, not token-by-convention

**Selected option B: NO production-facing trusted mapper in the first implementation.** Since a Python frozen dataclass / secret-looking string / opaque object field / caller-injected lambda is forgeable or caller-controlled, it cannot certify provenance of `VerifiedPackageSnapshotV1`. This slice must not claim host source attestation, executable binding, registry authority or trusted durable evidence.

Concrete file and symbol boundary:

| Location | Allowed first-slice content | Prohibited content |
|---|---|---|
| `agent_core/domain_registry_mapping.py` | Fixed 12-kind policy table, typed errors, purely inert metadata projection / exact Registry read-and-compare primitive with **non-authoritative** results; prefix internal routine `_map_untrusted_observation` | No exported/public `map_verified_package` that upgrades caller data to trusted; no `HostIssuer`, real trusted Admission constructor, DomainBinding/RunBinding, Registry mutation or tool dispatch |
| `tests/test_ga02_d2b_registry_mapping.py` | Exact source-backed fixture builder, `_TestOnlyMappingHarness` and a test-only method that directly calls the private observation routine after an actual D2-A test fixture load; assertions for P01–P04/N01–N12 | No production-importable policy factory; no importable public Host admission token |
| Public `agent_core` imports / Application composition | Unchanged, no exports or call sites for mapping module; if a future integration requests trusted mapping, fail closed until separately authorized | No environment-variable or `PYTEST_CURRENT_TEST` production bypass, no `if __debug__`, no sentinel token, no fallback issuer constructed from arbitrary user-supplied values |

**Separation limitation stated explicitly:** Python naming (`_private`), test directory location and lack of `__all__` export are *packaging/test isolation*, not a cryptographic or language-enforced security boundary. Any Python code with direct interpreter access can call internal functions. Therefore the first slice MUST expose only `NON_AUTHORITATIVE_AT_READ` / `INERT_INSPECTION_ONLY` evidence, never a trusted host admission object. No downstream D2-C/D3 code may treat those values as authoritative. Production trusted use remains impossible by contract and absent call sites until the separately reviewed issuer/admission implementation exists. A future public `map_verified_package` must be a **new separately authorized integration** whose trust comes from a verified application-owned issuer, not from a caller-supplied dataclass.

**Positive test-only flow:** harness provisions a temporary local generation using `HostPackageRootIssuer` with a fixture-owned test verifier; creates `TrustedPackageIdentity`; loads with a live lease via `LocalPackageLoader.load`; pins its own expected host policy values; calls `_map_untrusted_observation` inside tests and checks metadata, exact namespace, error hygiene, non-authority. The fixture's `publication_verifier=lambda ...` is test-only and is not a production publisher. D2-B never itself calls `LocalPackageLoader`, reopens assets, mints a D2-A lease or registers any Registry entries; fixture setup may register predetermined records outside the mapper.

**Mandatory negative proofs:**

1. Search the entire candidate source for production imports/calls to `domain_registry_mapping`; none allowed. `agent_core/__init__.py` exports unchanged. There is no public factory that converts `(snapshot, policy, admission)` into a `trusted=True` result.
2. A forged `VerifiedPackageSnapshotV1` and forged `D2BTrustedAdmissionV1` / host policy from an arbitrary caller are **never** accepted as a trusted domain mapping. Under the selected option B there is no implemented trusted admission object at all; tests assert no such exported class/function exists. Calling the internal observation routine directly can return non-authoritative metadata, which is NOT a bypass of a production grant because no grant exists.
3. An untrusted input cannot select Registry class, reroute fixed kind or authorize active use. Unknown profile and mismatched descriptor/host fixture identity fail closed with D2-B typed error prior to any Registry `get`.
4. No `setattr`, proxy or malicious `implementation_ref` can cause `__call__`, `__str__`, `__repr__`, pickle/deepcopy or execution. A successful metadata observation has no Registry/Tool/Workflow/Model/StateStore side effects.
5. The test harness must be self-contained and **not imported in runtime files**. Its issuer does not survive tests and cannot be used to claim a real SEALED host publisher. An attempt to wire the module into a production application is outside approved scope and requires a separate authority review.

**Exact entry and output contract for the first implementation:**

```python
# agent_core/domain_registry_mapping.py — internal, untrusted metadata-only API
def _map_untrusted_observation(
    snapshot: VerifiedPackageSnapshotV1,
    *,
    policy: KindMappingPolicyV1,
    registries: RegistryCatalogViewV1,
) -> RegistryKindMappingSnapshotV1: ...
# Always returns only INERT_INSPECTION_ONLY / NON_AUTHORITATIVE_AT_READ.
# No admission parameter and no trusted=True/runnable result.
# No public map_verified_package() or D2BTrustedAdmissionV1 in this slice.
```

Host policy fields still undergo complete structural and equality validation for reproducibility; these checks establish *consistency only*, NOT issuer authenticity. Source provenance is NOT solved by this isolated unit and must remain a hard gate for production D2-C/D3.

### 11.2 IR-03A — Executable test-fixture builder, not D2-A `ref()` misclassification

Source-verified baseline: `tests/test_ga02_d2a_package_loader.py` defines `package_bytes(assets, enabled=True)`, `prepare(tmp_path, assets)` whose asset tuple elements are `(relative_path, content_bytes, item_id)`, and `ref(path, content, item=...)` that **always sets `kind='action'`**; `LocalPackageLoader().load(lease, TrustedPackageIdentity(...))` consumes `package.json` and exact referenced files. For D2-B multikind fixtures, **do not call `ref()`** for `prompt`, `schema` or `knowledge`. Build exact references explicitly.

Deterministic standalone test helper outline (pseudocode, imported only by `tests/`):

```python
from hashlib import sha256
import json
from pathlib import Path

DOMAIN = 'inventory.reconcile'
VERSION = '1.0.0'
PROFILE = 'GA02-D1-1'

def asset(kind: str, ident: str, path: str, payload: bytes, *, namespace: str = DOMAIN):
    return {
        'kind': kind, 'namespace': namespace, 'id': ident,
        'version': VERSION, 'sha256': sha256(payload).hexdigest(),
        'relative_path': path,
    }

def write_package(tmp_path: Path, assets: list[tuple[dict[str, str], bytes]]):
    # No absolute paths / collisions; create each exact referenced relative file.
    for ref, contents in assets:
        file = tmp_path / ref['relative_path']
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(contents)
    refs = sorted([ref for ref, _ in assets], key=lambda r: (
        r['kind'], r['namespace'], r['id'], r['version'], r['relative_path']))
    unsigned = {
        'package_schema_version': '1',
        'domain_id': DOMAIN, 'domain_version': VERSION,
        'name': 'Inventory Reconciliation', 'enabled': True,
        'runtime_compatibility': PROFILE, 'asset_refs': refs,
    }
    canonical = json.dumps(unsigned, sort_keys=True, separators=(',', ':'),
                           ensure_ascii=False).encode('utf-8')
    digest = sha256(canonical).hexdigest()
    descriptor = dict(unsigned, manifest_digest=digest)
    (tmp_path / 'package.json').write_bytes(json.dumps(descriptor).encode('utf-8'))
    return digest

def load_test_snapshot(tmp_path: Path, assets):
    digest = write_package(tmp_path, assets)
    identity = TrustedPackageIdentity('generation-1', DOMAIN, VERSION, PROFILE, digest)
    issuer = HostPackageRootIssuer(
        (HostPublishedGeneration(identity, str(tmp_path), True),),
        publication_verifier=lambda record: (
            record.sealed is True and record.absolute_root == str(tmp_path)),
    )  # STRICTLY TEST-ONLY verifier; not a real immutable publisher.
    with issuer.issue('generation-1') as lease:
        return LocalPackageLoader().load(lease, identity), identity
```

Above helper is fixed to Linux fixture execution because D2-A is Linux-only; skip where `sys.platform` does not start with `linux`. Actual importer names must be resolved to `agent_core.domain_package_loader` in the implementing test file. Asset tuples must use fresh distinct paths and no `..`, duplicate or symlink. The fixture is executable-style pseudocode: implementation review must actually run it; it is not falsely claimed tested merely because it appears here.

**Reference fixture dataset with exact expected mode/result:**

| Case | D1 asset ref + bytes | Host Registry fixture | Expected D2-B outcome |
|---|---|---|---|
| A01 domain action | `asset('action','stock.count','actions/count.txt',b'count')` | `DomainRegistry.register(DomainManifest(domain_id=DOMAIN,name='Inventory Reconciliation',version=VERSION,enabled=True,runtime_compatibility=PROFILE), namespace=DOMAIN)`; `ActionRegistry.register(ActionDefinition(action_id='stock.count',version=VERSION,category='inventory',description='count',intrusiveness_level=IntrusivenessLevel.LOW,requires_confirmation=False,required_capability=None,allowed_planning_modes=[PlanningMode.DETERMINISTIC]), namespace=DOMAIN)` | REGISTRY_MAPPING yields NON_AUTHORITATIVE_AT_READ action identity; no runnable grant |
| A02 CORE schema | `asset('schema','shared.schema','schemas/shared.json',b'{}',namespace='CORE')` | Register `SchemaDefinition(schema_id='shared.schema',version=VERSION,scope=SchemaScope.CORE,namespace='CORE')` in `SchemaRegistry` with namespace CORE; host policy exact allowlist contains `('shared.schema',VERSION)` | Exact CORE triple/scope accepted as read-time metadata only |
| A03 inert knowledge | `asset('knowledge','catalog.notes','knowledge/notes.txt',b'notes')` | Only enabled DomainRegistry needed for REGISTRY_MAPPING; no knowledge Registry exists | INERT_ONLY ref; no retriever instantiated |
| A04 missing domain | Same A01 but no DomainRegistry record (or only legacy namespace=None) | Action record may exist but host domain not registered | D2B_EXACT_DEPENDENCY_NOT_FOUND, no partial snapshot |
| A05 forged admission | Any A01 descriptor and arbitrary hand-built frozen snapshot or pretend policy token | No trusted admission class/entry exists | No trusted mapping possible; direct internal read may only produce non-authoritative metadata; no active use |
| A06 inert inspection | A01+A02+A03, with spy registries that throw if `get` is called | No domain pre-registration required | All INERT_INSPECTION_ONLY, zero Registry lookup, no runnable claim |

**Additional deterministic expected tests:** reject CORE schema with `definition.namespace=None`, wrong `SchemaScope.DOMAIN`, unapproved exact CORE key; reject Action/Domain mismatched ID/version, record disabled, and `RegistryItemNotFoundError` even where a newer version exists. For a hostile `implementation_ref`, use a trap object that raises in `__repr__`, `__str__` and `__call__`; assert counters remain zero and public error messages are only D2BCode values. Test failure after a successful earlier asset has no returned partial result. Verify full tuple/str/bool-only result recursively and that no live `RegistryRecord` or Pydantic Definition escapes. No per-asset `register` calls inside mapper; fixture registration belongs only to the test setup.

### 11.3 Final bounded readiness / independent review matrix

| Gate | Requirement for targeted independent review | Decision before review |
|---|---|---|
| IR-01A | Option B test-only isolation specified; no production export/trust admission; forged values cannot yield authorization; internal evidence always NON_AUTHORITATIVE_AT_READ | DESIGN SUBMITTED |
| IR-03A | Exact multikind D1 canonical fixture builder with action/CORE schema/knowledge, missing DomainRegistry and forged admission cases; explicit D2-A Linux loader path | DESIGN SUBMITTED |
| IR-02 | Existing §9.3/§10.2 stable typed errors, redaction and atomic denial unchanged | PREVIOUSLY DESIGN PASS |
| Source/test gates | Later implementation must actually execute targeted tests, full pytest, mypy, Ruff lint/format and GA-01C integration; test-only issuer cannot be production proof | NOT RUN IN THIS DOC CHANGE |

**Final status:** `IR-01A / IR-03A AMENDMENT = SUBMITTED`; `INDEPENDENT EXACT-HEAD RE-REVIEW = PENDING`; `D2-B ISOLATED TEST-ONLY METADATA IMPLEMENTATION = NOT YET AUTHORIZED`; `PR #112 MERGE = NOT AUTHORIZED`; `TRUSTED PRODUCTION HOST ISSUER = NOT PROVEN`; `D2-C/D/E/D3 ACTIVE ADMISSION = NOT AUTHORIZED`. Next: **GA-02 D2-B — IR-01A / IR-03A Targeted Independent Final Readiness Re-Review + Isolated Implementation Authorization Assessment**.
