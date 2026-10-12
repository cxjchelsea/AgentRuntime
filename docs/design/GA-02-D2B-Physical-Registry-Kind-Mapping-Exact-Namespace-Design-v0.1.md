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
