# GA-02 D2 — Package Loader + Dependency Resolver + Immutable DomainBinding Design v0.1

Status: **PROPOSED — INDEPENDENT DESIGN REVIEW REQUIRED**. This document is not D2 implementation or merge authorization.

Baseline: main at 0fa2f7bbb745100171cbbea621b23708649c539c; GA-02 D0 normative design §§9.1–9.7 and merged D1 descriptor parser. Goal: turn a structurally validated inert domain descriptor into a trusted, byte-verified, exact-registry-resolved and deterministic immutable domain binding, without granting execution authority.

## 1. Physical source alignment

| Existing file | Verified behavior | D2 boundary |
|---|---|---|
| agent_core/domain_descriptor.py | Strict UTF-8 JSON, frozen PackageDescriptorV1, typed AssetReferenceV1, manifest self-SHA, sorted assets | Reuse unchanged; independently verify trusted expected manifest hash and actual asset contents |
| runtime/registries/base.py | RegistryKey(item_id, version, namespace), exact BaseRegistry.get, mutable RegistryRecord(definition, implementation_ref, enabled); disable/unregister/clear mutate active state | Exact lookups; immutable owned copies; never embed mutable records or implementation_ref objects |
| runtime/registries/domain.py | DomainRegistry stores DomainManifest with enabled=definition.enabled, namespace default None | Trusted namespace policy and enabled check; no registration/enable side effect |
| runtime/registries/definitions.py | DomainManifest has required domain_id/name/version and optional runtime_compatibility/enabled/plain-string lists | Keep Canonical untouched; preserve versions in GA-02 refs, not plain-string lists |
| D0 §9.1 | Trusted Composition Root issues run-scoped BoundRunDomain; AgentRunBinding carries run correlation; context domain ID is projection | D2 defines typed sidecar/proof; physical AgentRunBinding signature must be independently source-checked before coding |

No evidence from D1 proves package publisher authenticity, file content integrity, Registry enablement, adapter legitimacy or user permission.

## 2. Architecture / single path

Trusted Application configuration supplies allowlisted absolute root, exact domain ID/version, independently pinned expected manifest SHA256, supported runtime profile and trusted adapter-catalog generation.

TrustedRootLocator → LocalPackageLoader → VerifiedPackageSnapshot → ExactDependencyResolver → ResolvedDependencySnapshot → DomainBindingAssembler → immutable DomainBindingV1 → trusted Application Composition Root (later D3 connection).

The package never supplies its own trusted root, expected hash, tenant authority or executable callback. D2 has no model execution, knowledge retrieval, arbitrary imports, tool calls, StateStore writes or new M2/M4/M5 grants. D1 may parse disabled manifests for audit; D2 refuses to bind them for active use. D2 errors are typed and fail closed before any binding is returned.

## 3. D2-A — Trusted local package loader

Proposed API: load_local_package(TrustedRootHandle, TrustedPackageIdentity, LoaderLimits) → VerifiedPackageSnapshot or typed failure.

TrustedPackageIdentity contains expected domain_id, exact domain_version, expected_manifest_sha256, runtime_profile_id from an independent host allowlist. First read package.json into owned bytes within D1 262144-byte limit, parse using existing D1 code; require identity/profile/expected SHA equality and enabled=true. A package manifest hash alone is internal consistency, not authenticity.

For every sorted declared AssetReferenceV1, resolve relative POSIX path under the preconfigured root using secure directory descriptor operations; open one time, copy owned bytes, check regular file and bound size, compute SHA256 over those exact captured bytes, compare declaration and close. Only assemble snapshot once all references pass, and never reopen unchecked paths. Proposed bounds: per asset 1 MiB, whole package 16 MiB, at most 256 references, path depth ≤12; values require review before freeze.

First implementation targets Linux/POSIX and requires openat-style traversal, O_NOFOLLOW for every path component, directory/file type validation and enforcement against symlinks, directory traversal, FIFOs/devices and unwanted mounts. Plain Path.resolve followed by opening is not TOCTOU safe. Document root-handle pinning, hardlink and file replacement policy. Fail closed on platforms without required primitives rather than falling back to an unsafe path. Detect in-place changed or growing files during read when possible and require trusted package publication to prevent concurrent edits; content hash always applies to captured bytes.

Snapshot stores frozen descriptor and tuple of owned VerifiedAsset(kind, namespace, id, version, relative_path, declared_sha256, content_bytes), never mutable file handles or path instances. No remote URL, eval, pickle, imports, prompt execution or tool capability registration.

Negative tests: altered trusted expected manifest digest; bad actual asset hash; missing file; forbidden/absolute/encoded traversal; nested symlink; root swap; FIFO/device; over-limit or race; duplicate logical identity; transient file change. Assert no partial snapshot or external side effect.

## 4. D2-B — Asset kinds and mapping

D1 accepts action, strategy, skill, tool, workflow, capability, prompt, knowledge, rule, schema, state, eval. D2 explicitly classifies each into a physically compatible existing Registry definition type or a verified inert-only asset; there is no filename-based inference or implicit lookup.

| Kind | Candidate metadata type / disposition |
|---|---|
| action | ActionDefinition, exact registry key |
| strategy | StrategyDefinition, exact key and declared action edges |
| skill | SkillDefinition, exact key |
| tool | ToolDefinition, exact metadata only; no execution grant |
| workflow | WorkflowDefinition, exact key |
| capability | CapabilityDefinition, exact key; host adapter resolved separately |
| prompt | PromptDefinition when backed by compatible Registry; otherwise inert bytes |
| rule | PolicyDefinition metadata or inert data, never Core policy override |
| schema | SchemaDefinition; reserved CORE namespace only for explicitly shared Core schema |
| knowledge | inert verified source/reference; not a retriever |
| state | inert verified schema/reference; not StateStore |
| eval | inert verified evaluation data; not approval authority |

This table is **provisional** until actual registry class constructors / key conventions are checked. BaseRegistry allows namespace=None, whereas D1 refs use an explicit namespace. D2 must freeze exact trusted per-registry namespace normalization and refuse hidden None fallback or cross-domain ambiguity. If a physical registry adapter is not implemented for a kind, return UNSUPPORTED_DEPENDENCY_KIND for active binding; do not silently resolve nearest matching record.

## 5. D2-C — Deterministic exact dependency resolver

Proposed API: resolve(VerifiedPackageSnapshot, TrustedRegistryCatalogView, TrustedHostAdapterCatalogView) → ResolvedDependencySnapshot or typed refusal.

Algorithm:
1. Check the exact domain_id and domain_version in DomainRegistry and trusted namespace policy; record.enabled and definition.enabled must be true. Require descriptor → DomainManifest field mapping including name, version, enabled and exact runtime profile.
2. For every verified asset declared as Registry-backed, call get(item_id, exact_version, namespace=trusted_exact_namespace); never list/best-match/latest. Compare returned RegistryKey to expected identity, definition type, built-in ID/version fields and domain scope.
3. Copy the record's definition through typed serialization to a strict canonical inert JSON value, SHA256 it, and retain only the resulting immutable byte hash/normalized value, not Pydantic model, list/dict, RegistryRecord or arbitrary implementation_ref.
4. Validate definition's own enabled flag where present and all declared compatible edges. Missing explicit versions on downstream references are a blocking compatibility gap, not permission for approximate selection.
5. If host adapter metadata is needed, look up trusted application allowlist key and immutable generation under tenant/domain scope. Package-declared adapter IDs and mutable implementation_ref objects cannot nominate an implementation. A future physical tool invocation still requires existing M2/M4/M5 authority.
6. Emit sorted frozen ResolvedDependencyEvidence tuples (kind, namespace, ID, exact version, definition SHA, enabled-at-resolution, trusted adapter key and generation if applicable). Duplicate/foreign-domain/missing/unresolved/disabled entries abort atomically.

Snapshot is **resolution-time evidence only**. D3 must add independently reviewed active-use checks that re-read exact Registry records and adapter generations before inference/physical action and fail closed if a dependency was disabled, unregistered or changed. D2 binding never stores a mutable RegistryRecord and must not treat snapshot enabled=true as permanent permission.

Resolver tests: missing exact version, namespace None vs explicit, same ID in distinct namespaces, disabled record or definition, changed mutable definition after snapshot, unregistered entry, swapped implementation_ref, rotated adapter generation, cyclic/incomplete graph, invalid cross-references, tenant mismatch.


## 6. D2-D — DomainBinding and binding fingerprint

Proposed immutable values (GA-02-only dataclasses, not new Canonical contracts):

- VerifiedAsset: typed key, normalized relative_path, lowercase sha256 and captured owned bytes.
- ResolvedDependencyEvidence: registry_kind, namespace, item_id, exact_version, definition_sha256, enabled_at_resolution, trusted_adapter_key/generation (nullable).
- DomainBindingV1: domain_id, exact domain_version, runtime_profile, trusted manifest_sha256, immutable VerifiedAsset tuple, immutable ResolvedDependencyEvidence tuple, host_catalog_generation and binding_fingerprint.

Prohibited fields: tenant/session/run/user identifiers, credentials, arbitrary Python callables, mutable implementation_ref, live RegistryRecord, state value, tool grant, filesystem handle, current time. Asset bytes are bounded, never written to logs.

Proposed fingerprint v1: SHA256 over bytes consisting of UTF-8 prefix GA02-D2-BINDING-1 followed by zero byte followed by canonical JSON of binding_profile, domain ID/version, runtime profile, host-verified manifest SHA, sorted typed asset digest refs, sorted typed registry definition hashes, enabled_at_resolution=true, verified adapter keys/generations, and host catalog generation. Use D0 canonical JSON sort, NFC, no floating point, compact separators, UTF-8, and reject noncanonical values. The fingerprint contains **no personal data** and is not a signature or capability grant.

This profile remains **unfrozen** until independent literal golden canonical byte vectors and SHA digests are computed and tested for: one empty reference, one nonempty action and Registry definition, reordered assets, changed asset content digest, definition update, adapter generation rotation, and cross-process restart stability. These literal values are a D2 design readiness gate, not numbers to fabricate.

## 7. D2-E — Run-scoped binding and correlation

D2 DomainBindingV1 represents package/dependency identity **without user identity**. Only trusted Composition Root may issue BoundRunDomain(run_id, request_id, trace_id, session_id, subject_id, identity_scope, tenant_id, domain_id, domain_version, binding_fingerprint, immutable binding reference).

At run creation and each later integration boundary, compare sidecar to existing AgentRunBinding's correlation fields and authorized input. RuntimeContext.domain_extensions.domain_id is only a domain projection; its extra values must never be treated as authoritative version/fingerprint. Mismatched tenant, user, session, request, domain version, digest/fingerprint, stale observation, missing sidecar or midrun rebind -> typed fail-closed before inference, retrieval, Tool/Skill/Workflow dispatch, state write and FINISH.

D2-E is an architectural port **subject to physical source signature verification**: locate and inspect existing AgentRunBinding.from_input, RuntimeInput, RuntimeContext, DomainExtensions and M6 correlation method. Do not implement against imagined field locations or add another competing run authority. D3 attaches this sidecar to actual agent loop; D2 does not change M2/M4/M5 execution authority.

## 8. Typed errors and atomicity

| Code | Fail-closed meaning |
|---|---|
| UNTRUSTED_PACKAGE_SOURCE | Host expected SHA/root not independently provided |
| PACKAGE_ROOT_UNSAFE | Root or path security violation |
| PACKAGE_READ_UNSTABLE | File identity/length changed or unsupported security primitive |
| PACKAGE_DESCRIPTOR_DIGEST_MISMATCH | Trusted expected manifest hash mismatch |
| PACKAGE_ASSET_INTEGRITY_FAILURE | Missing/oversize/nonregular file or actual SHA mismatch |
| PACKAGE_DISABLED | Descriptor or required Domain Registry entry disabled |
| PACKAGE_PROFILE_MISMATCH | Wrong runtime compatibility profile |
| DEPENDENCY_KIND_UNSUPPORTED | No approved physical mapping |
| DEPENDENCY_NOT_FOUND_OR_DISABLED | Exact registry key unavailable |
| DEPENDENCY_IDENTITY_MISMATCH | Key vs definition vs namespace mismatch |
| TRUSTED_HOST_ADAPTER_MISMATCH | Trusted catalog key or generation invalid |
| BINDING_FINGERPRINT_MISMATCH | Noncanonical or inconsistent snapshot hash |
| RUN_DOMAIN_CORRELATION_DENIED | Wrong tenant/run/session/domain or missing sidecar |

Errors should include stable stage/code and safe identifiers, not package raw bytes, secrets, personal identifiers or untrusted filesystem paths. Error exceptions vs returned typed result remains a design review decision. Every failure yields no partially trusted binding, no Registry mutations and no automatic attempt to select another version.

## 9. Required test and gate matrix

| Slice | Evidence | Release condition |
|---|---|---|
| D2-A | Secure POSIX root operations, symlink/hardlink/race/missing/size/hash negative fixtures | Complete verified owned bytes; no unchecked reopen |
| D2-B | Explicit mapping of all 12 D1 kinds, CORE reserved handling, unsupported-kind refusal | No fuzzy namespace, class or Registry fallback |
| D2-C | Exact get, deep immutable snapshots, revocation/rotation/foreign namespace negatives | Snapshot correctness without granting execution |
| D2-D | Canonical literal bytes + independent golden digest vectors, process restart | Deterministic fingerprint without personal/run info |
| D2-E | Actual source-aligned AgentRunBinding/RuntimeInput/Context correlation | One trusted sidecar, no new StateStore or grant |
| Aggregate | Full Pytest, Mypy, Ruff lint, Ruff format and GA-01C regression at exact PR HEAD | All green; no D4 two-domain E2E claimed |

Design must resolve these blockers **before D2 implementation authorization**:
- B-D2-01: complete physical Registry kind→definition mapping and explicit namespace None policy.
- B-D2-02: trusted adapter catalog provenance, generation and immutable binding agreement.
- B-D2-03: supported OS, secure path-open primitives, root-swap/hardlink/mount and write-race policy.
- B-D2-04: freeze canonical fingerprint schema and literal SHA golden fixtures.
- B-D2-05: inspect physical AgentRunBinding/RuntimeInput/RuntimeContext types and align sidecar fields.
- B-D2-06: versionless referenced definition edges and transitive dependency closure/revocation semantics.
- B-D2-07: distinction between syntactically valid empty descriptor and operationally admissible domain package.

## 10. Decision and next step

**D2 DESIGN v0.1 = PROPOSED / IMPLEMENTATION NOT AUTHORIZED.** Review against D0/D1 and the exact existing source signatures. Next: GA-02 D2 Independent Design Review + Source-Compatible Contract Gap Assessment; remedy B-D2-01…07 into v0.2 and authorize individual slices only after independent review. Do not merge this design PR or start D3/D4 merely on the strength of this draft.

---

## 11. v0.2 Targeted Design Remediation — Normative Amendment

**Status: v0.2 design remediation proposed for targeted independent re-review.** This section supersedes v0.1 sections 3–9 if any conflict. It is a source-compatible proposal, NOT a passed independent re-review, D2-A implementation authorization, production domain activation, or permission grant. Source baseline remains main at 0fa2f7bbb745100171cbbea621b23708649c539c.

### 11.1 B-D2-01 — Exact physical Registry map and namespace policy

Current source: runtime/registries/base.py RegistryKey(item_id,version,namespace) and get(item_id,version,namespace=...); runtime/registries/__init__.py exports concrete Registry types; registry registration methods generally accept namespace=None, but SchemaRegistry.register uses namespace or definition.namespace. There is no implicit domain namespace projection.

| D1 kind | Physical class | Intrinsic definition identity | D2 treatment |
|---|---|---|---|
| action | ActionRegistry / ActionDefinition | action_id, version | exact metadata lookup |
| strategy | StrategyRegistry / StrategyDefinition | strategy_id, version | exact metadata lookup |
| skill | SkillRegistry / SkillDefinition | skill_id, version | exact metadata lookup |
| tool | ToolRegistry / ToolDefinition | tool_id, version | exact metadata lookup; no execution |
| workflow | WorkflowRegistry / WorkflowDefinition | workflow_id, version | exact metadata lookup |
| capability | CapabilityRegistry / CapabilityDefinition | capability_id, version | exact metadata lookup; host adapter independent |
| prompt | PromptRegistry / PromptDefinition | prompt_id, version | exact metadata lookup when declared Registry-backed; otherwise inert bytes only under explicit trusted host policy |
| rule | PolicyRegistry / PolicyDefinition | rule_id, version | exact metadata lookup when declared Registry-backed; otherwise inert rules only under explicit trusted host policy |
| schema | SchemaRegistry / SchemaDefinition | schema_id, version, scope, namespace | CORE restricted to shared Core schema; domain schema must match domain ID |
| knowledge | no approved generic Registry in audited exported set | not applicable | inert verified bytes/reference; must not imply retrieval |
| state | no approved generic Registry in audited exported set | not applicable | inert verified state-schema data; no StateStore |
| eval | no approved generic Registry in audited exported set | not applicable | inert verified evaluation data; no authority |

The classifier is a **trusted host-supplied, immutable table**; a package may not choose its registry class or switch a kind dynamically. First active-binding profile is conservative: prompt and rule are Registry-backed only when predeclared in host policy; otherwise classify them as inert-only and prohibit any corresponding execution/composition claim. Every D1 kind must appear in the table, but the existence of a table entry is not a promise the kind is operationally supported.

Namespace policy for D2: require the exact non-null namespace from D1 for every Registry-backed reference, including DomainRegistry registration and lookup. No automatic None→domain adaptation, no 'first matching' or wildcard lookup. Legacy None-scoped records must be *explicitly re-registered by the host* with the proper exact namespace before D2 active resolution, outside D2's read-only behavior. SchemaRegistry: require stored key namespace exactly equals reference namespace; schema definition scope must be CORE for namespace CORE and DOMAIN for domain namespace, and domain definition namespace must match when present. CORE is reserved for D1 schema kind only. DomainRegistry's exact namespace is the active domain_id for D2-enabled packages; pre-existing None-scoped DomainRegistry records are not accepted as equivalent. This is a **migration/preparation prerequisite**, not a hidden code fallback.

Per-entry checks: record key equals requested triple; runtime definition type is exact expected type; intrinsic identity/version fields equal key; optional domain/scope metadata agrees with requested namespace. Negative tests must include same ID in two domain namespaces, None-only legacy record, conflicting intrinsic ID, missing exact version, Schema CORE/D09 collision, mismatched namespace and wrong Registry type.

### 11.2 B-D2-02 — Trusted adapter catalog and enabled semantics

Define host-only injected immutable CatalogSnapshotV1(profile_id, generation, allowed_adapter_entries). An adapter entry is a frozen tuple of (registry_kind, exact RegistryKey, adapter_key, adapter_generation, tenant_scope_allowlist_id, domain_scope, host_registration_digest). This is a **trusted host declaration** and cannot be created, modified or inferred from package.json. D2 may inspect values but never call a Python object or instantiate an adapter.

At load/resolve time, if a future D3 port requires an implementation, the RegistryRecord.implementation_ref **must not become authority**. Its type, repr, object identity and callable cannot be hashed, persisted or invoked in D2. A trusted catalog must independently attest the registry key→host adapter key/generation binding; if not attested, return TRUSTED_HOST_ADAPTER_MISMATCH. A mutable implementation_ref swap is grounds for denial whenever a trusted mapping would be affected. Until a host-owned stable registration attestation exists, D2 treats that dependency as metadata-only and denies 'executable binding' admission. Host adapter generation changes force a different binding fingerprint and future run binding; D3 active-use revocation checks revalidate generation.

Enablement: every record requires record.enabled is exactly True. For ActionDefinition/StrategyDefinition/SkillDefinition/ToolDefinition/WorkflowDefinition and DomainManifest require definition.enabled is exactly True. CapabilityDefinition and PromptDefinition do not expose enabled in audited source, so **record.enabled only** is checked; do not invent optional model fields. PolicyDefinition enabled is checked. No Registry mutation, enable(), register() or side-effect fallback from D2. Tenant/domain scope comes from trusted host configuration, not from package-authored fields.

### 11.3 B-D2-03 and B-D2-10 — Linux secure-root snapshot profile

Supported first implementation: Linux only, local read-only *published package generation* under a trusted Application-administered root. Other OSs yield PACKAGE_ROOT_UNSAFE until separately reviewed. Trusted root FD is opened by the host from its allowlisted deployment location and held for the entire admission. The API receives this trusted FD/opaque handle, not an arbitrary path from the package or the user.

Path handling: start only from that already-pinned root FD; use component-by-component openat (Python dir_fd or equivalent) with O_NOFOLLOW, O_CLOEXEC, O_DIRECTORY for directories and regular-file-only fstat for leaf nodes; reject all symlinks, '.', '..', empty components, NUL, encoded traversal, file descriptors not derived from the trusted root, FIFOs/devices/sockets, and absolute paths. Do not use realpath-then-open. First implementation additionally rejects device changes (st_dev) across directory/leaf traversal and file hardlink count != 1, as a conservative policy to avoid aliases and mount/hardlink provenance ambiguities. This does not prove an untrusted filesystem has no bind mounts; deployment MUST use a trusted, immutable read-only published volume, and a mount namespace/privileged attacker can invalidate the trust assumption. Reject duplicate normalized relative paths even if separate logical asset keys claim them; reject repeated physical inode aliases inside a snapshot.

File reads: open descriptor and assets once, verify fstat pre/post (identity, size, mtime_ns, ctime_ns) plus bounded streaming and captured byte sha256. A mismatch or changing file fails closed with PACKAGE_READ_UNSTABLE; stable metadata **alone is not sufficient** to prove concurrent-write absence. The immutable publication policy (atomic generation directory published by trusted host, no writers after publication, trusted expected manifest digest) is the required defense; descriptors/assets are copied from each FD exactly once to owned bytes, and never reopened during assembly. File hash is over the captured bytes. All per-asset/aggregate bounds apply during streaming. Any unimplemented secure read primitive => fail closed; no silent Path/open fallback.

### 11.4 B-D2-06 — Versionless transitive refs and exact closure

Physical source fields: StrategyDefinition.default_actions: list[str]; SkillDefinition.required_tools / optional_tools: list[str] | None; WorkflowDefinition.required_tools / optional_tools: list[str] | None; CapabilityDefinition.skills/workflows/tools: list[str] | None. They lack exact versions and namespaces. D2 MUST NOT derive versions or pick latest from these strings.

Introduce trusted host-owned VersionedEdgeCatalogV1 for active packages: each declaration is frozen (source_kind, source_namespace, source_id, source_exact_version, relation, target_kind, target_namespace, target_id, target_exact_version), plus a host catalog generation and digest. For every versionless referenced string, enumerate the exact expected edge keys and require **exactly one** catalog mapping for each required edge, matching the source definition's actual string value. Map only references for which physical definitions declare an interpretable relation; ambiguous identifiers/duplicates/mismatched source target IDs/missing catalog entries deny active resolution. Optional target edges may be explicitly declared absent by host policy, never silently reinterpreted as required or ignored if declared.

Build transitive closure over typed keys from exact seed D1 refs, validate all referenced Registry records and their immutable digests, reject cycles for the D2 v1 conservative profile (even if potentially harmless), and require that every active dependency is pinned and provenance-consistent. Edges or required registry entries not in the package's declared verified snapshot are denied unless an **explicit host-core dependency allowance** pins immutable Core registry evidence and hash. No implicit global registry visibility, no wildcard tenant scope. All host edge-catalog generations/digests participate in fingerprint via host_catalog_generation, and changing them invalidates future bindings.

### 11.5 B-D2-07 — Bootstrap and runnable admission

There are two distinct outcomes:
- **VerifiedPackageSnapshot / InertBindingMetadata:** descriptor with zero assets can be accepted as *data-only* for inspection, never as an active runnable domain.
- **Active DomainBindingV1:** requires host-approved domain registration, exact enabled namespace/domain/version/profile, trusted manifest pin and verified assets, versioned closure, host catalog generation, and an **Application-supplied operational profile** naming the minimum eligible action/strategy/prompt/evidence capabilities. A missing minimum is PACKAGE_NOT_OPERATIONALLY_READY. D2 cannot decide that a domain with no actions is executable.

Bootstrap order is explicit: trusted host administrator verifies package provenance, registers approved DomainManifest and exact dependency metadata into the existing registries **outside D2**, then freezes trusted host catalog snapshots; D2 only reads and compares these pre-registered records. A clean host with no DomainRegistry record returns DEPENDENCY_NOT_FOUND_OR_DISABLED and a typed registration prerequisite, not automatic registration or a circular 'loader must register' transition. Host registration is never triggered by package JSON or D2. A deployed package update requires a fresh trusted publication/registration and a fresh binding for **new** runs only.

### 11.6 B-D2-05 — Actual run/iteration correlation, now physically anchored

**Verified physical source**: agent_core/iteration.py defines frozen AgentRunBinding with run_id, original_request_id, original_trace_id, session_id, subject_id, identity_scope, tenant_id: str | None, domain_id, domain_version, binding_fingerprint. Its from_input(runtime_input, *, run_id, domain_id, domain_version, binding_fingerprint) copies RuntimeInput identity. RuntimeInput in runtime/contracts/input.py provides request_id, trace_id, session_id, subject_id, identity_scope, tenant_id: str | None. RuntimeContext in runtime/contracts/context.py provides identity_context, session_context and optional domain_extensions with domain_id, but no authoritative domain version/fingerprint.

BoundRunDomainV1 is minted only by trusted Application Composition Root: (run_id, original_request_id, original_trace_id, session_id, subject_id, identity_scope, tenant_id: str | None, domain_id, domain_version, binding_fingerprint, immutable DomainBinding reference). It is NOT a Canonical Contract/DomainState. Original fields must exactly match AgentRunBinding/from_input; missing sidecar or identity mismatch fails before first inference. A nullable tenant_id is compared by **exact equality**, never converted to wildcard: None vs non-None mismatch; a trusted Application may reject None entirely if its admission policy requires tenant segregation.

IterationRef.from_input in agent_core/iteration.py expects original request/trace for ordinal 0, and for ordinal >0 request_id = run_id + '-iteration-' + ordinal and trace_id = run_id + '-trace-' + ordinal. Therefore sidecar holds *original* request/trace and the current IterationRef supplies per-turn expected values; do not accidentally require current request_id == original_request_id on later turns. Existing assert_execution_correlation checks iteration fingerprint, input/context domain/identity plus plan/execution correlation, but does **not** validate authoritative package version vs sidecar; D3 must explicitly verify sidecar.binding_fingerprint/domain_version and current tenant/session/request/trace at each decide, observe, replan, dispatch and finish boundary. M6 structural admission remains deny-only and cannot be treated as approval.

### 11.7 B-D2-04 and B-D2-09 — Canonical binding and definition hashing profile

Freeze D2 fingerprint v1 as the following exact schema. Hash input = UTF-8 bytes of GA02-D2-BINDING-1, one NUL byte, then canonical JSON UTF-8 with lexicographically sorted recursive keys, compact separators (comma+colon), ensure_ascii=false, no trailing newline. Reject non-NFC/invalid Unicode; reject floats and nonfinite numbers; null only at the two optional host adapter fields. Booleans lower case. Asset entries sorted by (kind,namespace,id,version,relative_path). Dependency entries sorted by (registry_kind,namespace,id,version); duplicates forbidden. All runtime arrays must use immutable tuples after normalization.

Root keys EXACTLY: assets, binding_profile, dependencies, domain_id, domain_version, host_catalog_generation, manifest_sha256, runtime_profile. Asset entry keys EXACTLY: id,kind,namespace,relative_path,sha256,version. Dependency entry keys EXACTLY: definition_sha256,enabled_at_resolution,host_adapter_generation,host_adapter_key,id,namespace,registry_kind,version. enabled_at_resolution MUST be true. Host_catalog_generation is SHA-256 over the normalized trusted adapter + versioned edge catalog generation envelope, or a host-authored immutable generation token checked by exact agreement against those catalog snapshots; D2 v1 chooses **one host-authored token which identifies the complete immutable trusted catalog snapshot**, and any change to adapter/edge entries must rotate the token. Arbitrary self-selected package token is forbidden.

Definition hash: typed Canonical/Pydantic definition converted to model_dump(mode='json') **only as a starting value**; recursively validate allowlisted keys and types, strings NFC, enums normalized to declared string values, all None explicitly represented per type's exact schema (no implicit omit), reject floats (unless a future separately versioned profile enumerates safe fields), no wallclock or callables. Recursively sort JSON keys, no whitespace, SHA-256 the canonical UTF-8 bytes. These definitions in current tested registry set are string/bool/list/nullable (PolicyDefinition.priority is int and is allowed as a strict JSON integer; reject bool-as-int). Reject tuples converted unexpectedly, mixed-type lists and invalid Unicode; require explicit type-specific canonical fields rather than arbitrary object repr. Pin definition hash golden fixtures in independent review before D2-C code authorization.

**Literal reference fixture A — empty deps/assets (fingerprint *serialization* only; not operationally admissible):**

~~~json
{"assets":[],"binding_profile":"GA02-D2-BINDING-1","dependencies":[],"domain_id":"inventory.reconcile","domain_version":"1.0.0","host_catalog_generation":"host-v1","manifest_sha256":"c757e6506fb0e8d7741c9abf5abc2880221655f506afd597dd7817edce195a3f","runtime_profile":"GA02-D1-1"}
~~~

Fingerprint SHA-256 including prefix and NUL:
~~~text
8342fd5a5d645e8ab907cd3cbdab4e78cf5a7375a4da554f903184b8809be859
~~~

**Literal reference fixture B — one action asset and one exact action Registry dependency (synthetic digest values; serialization-only):**

~~~json
{"assets":[{"id":"stock.count","kind":"action","namespace":"inventory.reconcile","relative_path":"actions/count.json","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","version":"1.0.0"}],"binding_profile":"GA02-D2-BINDING-1","dependencies":[{"definition_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","enabled_at_resolution":true,"host_adapter_generation":null,"host_adapter_key":null,"id":"stock.count","namespace":"inventory.reconcile","registry_kind":"action","version":"1.0.0"}],"domain_id":"inventory.reconcile","domain_version":"1.0.0","host_catalog_generation":"host-v1","manifest_sha256":"c757e6506fb0e8d7741c9abf5abc2880221655f506afd597dd7817edce195a3f","runtime_profile":"GA02-D1-1"}
~~~

Fingerprint SHA-256 including prefix and NUL:
~~~text
649c58d4aa6fb132e807a5b96c2969e354fc942568371e7a8087a2d984855bfd
~~~

Synthetic change vectors derived from fixture B (each changes only named input): definition_sha256 changed to 64 'c' digits → 2121d12f19c3e7cdf0e67f6d1d2942b03760cb4d11393046d68ded40e81e10b8; host_catalog_generation changed to host-v2 → 3a5aecc673eb889b351f39c92282c7a6f211e4cb020d08a0137c5c6535f89692; asset sha256 changed to 64 'd' digits → 3e19d5c7c5b8a71fd1dad2d991d42e240264cdf911bc97aa7b02fffbb259d125. Reordered input asset_refs must canonicalize to the same binding fingerprint. **These fixture hashes are independently computed reference calculations, NOT a claim that a D2 implementation currently passes them.** A second independent implementation/test must recompute and confirm literal byte-for-byte vectors prior to frozen readiness.

### 11.8 B-D2-08 — Revocation and active-use check port

D2 snapshot is a historical verified value; D3 must implement an injected trusted active-use checker. Proposed API: assert_bound_dependencies_active(binding, RegistryCatalogView, HostAdapterCatalogView, VersionedEdgeCatalogView) → PASS or typed denial. At each D3 decision/admission, before side-effect dispatch and before accepting observations/finalization, re-fetch exact Registry keys, compare current record.enabled, optional definition.enabled, canonical definition_sha256, exact host adapter key/generation, host edge catalog generation and binding_fingerprint. Fail closed on disable/unregister/clear, mutable definition changes, adapter rotation or unknown Registry errors. Never replay a timed-out side-effect or treat stale snapshot as approval.

The revocation checker itself is NOT a D2 implementation deliverable unless separately authorized; D2 has to preserve the evidence needed to implement it later. No time-of-check-to-use guarantee exists for arbitrary in-place mutations without host snapshot/epoch control; protected read/dispatch critical section or host atomic generation admission is a D3 mandatory design gate.

### 11.9 Revised sequencing and review gates

1. D2-A first: Linux trusted-root loader capturing a verified, inert snapshot; host expected SHA and immutable publication are prerequisites. No Registry access, no binding.
2. D2-B: only source-grounded kind registry mapping plus namespace adapters and negative tests; explicit host policy, no registration.
3. D2-C: exact dependency closure, typed definition hash and trusted host adapters; no callable or mutable RegistryRecord escapes.
4. D2-D: deterministic fingerprint with literal fixtures A/B plus mutations, distinct process test, and manifest authenticity evidence.
5. D2-E: run-sidecar constructor and pure correlation checks mapped to physical AgentRunBinding; no StepPort wiring.
6. D2-F: independent aggregate implementation verification, no D3/D4 implied approval.

**v0.2 gates:** B-D2-01..07 and additional B-D2-08..10 have proposed remedies recorded. Separate independent design re-review MUST evaluate unresolved implementation choices (notably host publication/cross-device safety, exact definition serializer, catalog atomics and revocation time-of-use) before authorizing D2-A. D2-A readiness does not authorize D2-B–E or merge this design PR.

**Decision remains:** D2 DESIGN v0.2 = TARGETED REMEDIATION PROPOSED; D2 IMPLEMENTATION = NOT AUTHORIZED; PR #110 stays Draft. Next: GA-02 D2 v0.2 Targeted Independent Design Re-Review and then narrow D2-A readiness, with explicit stop on any remaining blocker.
