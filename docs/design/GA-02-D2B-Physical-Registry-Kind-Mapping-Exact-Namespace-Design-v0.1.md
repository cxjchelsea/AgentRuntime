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
