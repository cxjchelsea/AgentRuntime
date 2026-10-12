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