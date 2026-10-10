# GA-02 — Domain Package Integration / Unit Spec v0.1

**Status:** PROPOSED — design baseline, not a frozen implementation authorization  
**Base:** main `eee2cde44fa7e696c5e30edb32f5e99fc07b9b92` (GA-01C PR #106)  
**Goal:** prove **the same Agent Core** runs different business domains solely by selecting a versioned Domain Package and injecting its bounded assets. No change to Core source between domain runs.

## 1. Motivation / current-state gap

The repository's authoritative [general architecture](../01-总体架构.md) and [implementation plan](../05-总体实施方案.md) identify GA-02 as PackageLoader/Assembly + DomainBinding, followed by two-domain E2E. Observed code facts at this base:

- `runtime.registries.DomainRegistry` registers `DomainManifest(domain_id, version, ...)`, but does **not** load/assemble a package. `PromptRegistry` registers metadata; it does not compile actual prompt assets.
- `AgentRunBinding` (`agent_core/iteration.py`) already pins `domain_id`, `domain_version`, `binding_fingerprint`, session/identity/tenant and checks iteration identity. It does not itself resolve package dependencies.
- `AgentRunCoordinator` consumes injected `StepPort`; the current GA-01C loop is **sandbox-only**; it does not grant production tool rights or a trusted business StateStore.
- M4 `HybridStrategySelector` validates model choices against legal strategy/action candidates. The Domain cannot replace Policy/Recheck/Approval with a prompt or force execution.
- Current synthetic GA-01C tasks include multiple business *labels*, but their fixture-based configuration is **not** proof that two independently loadable, version-pinned Domain Packages exist.

Do not rewrite M3/M4/M5/M6 or introduce a second planner, state store, executor or runtime. GA-02 is an assembly/product-boundary unit.

## 2. Deliverable boundaries

| Unit | Deliverable | Exit proof |
|---|---|---|
| GA-02-D0 | this contract + independent design review | ownership, authority, API and acceptance aligned |
| GA-02-D1 | minimal `PackageManifest` / asset reference adapter over current `DomainManifest` | deterministic parsing, exact versions, schema validation and rejection cases |
| GA-02-D2 | isolated `PackageLoader` + dependency resolution + immutable `DomainBinding` | same bytes → same fingerprint; missing/ambiguous/disabled/incompatible dependencies → fail closed |
| GA-02-D3 | composition adapter to existing M3/M4/StepPort and typed Observation | real legal Registry candidates and prompt/knowledge references; no parallel Core implementation |
| GA-02-D4 | two unrelated domain fixtures + shared Core E2E and negative isolation tests | identical Core source/revision, differing domain assets/behavior, verified replan & finish |
| GA-02-D5 | exact-head independent review, evaluator, integration evidence | gates green, scope bounded, explicit authorization before merge |

**Out of scope:** real patient data, production external side effects, M6 Positive Grant, trusted production StateStore, cross-tenant memory, arbitrary Python plug-in execution, K0 index/retriever/reranker implementation, production deployment or broad runtime refactor. Knowledge bindings may point to verified sandbox facts only; *a reference to an index is not a retrieval implementation*.

## 3. Package structure and asset ownership (candidate layout, not yet frozen)

```text
domains/
  <domain_id>/
    package.yaml             # manifest, exact versioned references, compatibility
    prompts/                 # Domain + Task + Constraint content
    rules/                   # Domain-specific eligibility and safety constraints
    capabilities/            # action/skill/tool/workflow metadata + adapter IDs
    knowledge/               # source/version/validity declaration (no implied retrieval)
    state/                   # domain state schema and allowed update boundaries
    eval/                    # business truth, denial and end-to-end cases
```

A package distinguishes **Domain Extension** (reusable Schema/Rules/Capability definitions and allowed adapter references) from **Business Assets** (product prompts, knowledge binding, configuration, evaluation). They may be shipped together, but not granted the same authority.

Minimal required identifiers: `domain_id`, `version`, `package_schema_version`, `runtime_compatibility`, `manifest_digest`, `asset_refs`, and optional `feature_flags`. Asset refs are typed `(kind, id, exact_version, digest, path_or_registered_id)` — no floating latest/implicit fallback, no unverified remote URI execution. IDs are domain-scoped; intentionally shared global Core schemas must explicitly declare Core scope. Unknown required fields, missing assets and duplicate IDs fail before any inference.

Do **not** modify the existing Canonical `DomainManifest` simply to fit a YAML sketch until compatibility analysis and migration review identify exactly which additional fields are necessary. Prefer a GA-02 wrapper/adapter and explicit mapping into the current Registry first.

## 4. Interfaces and data flow (proposed, precise responsibilities)

```text
Application supplies (subject/session/tenant, domain_id, exact_version)
  -> PackageLocator resolves local trusted package source
  -> PackageLoader validates manifest, asset integrity and schema versions
  -> DependencyResolver pins Core/runtime/schema/Action/Strategy/Skill/Tool refs
  -> PackageAssembler builds immutable DomainBinding + binding_fingerprint
  -> Application Composition Root checks identity/session/tenant + authorization
  -> existing M3/M4 model prompts, Registry and StepPort adapters receive bound assets
  -> existing AgentRunCoordinator -> legal decide/approve -> sandbox action
  -> verified typed Observation -> existing model replan -> evidence-backed FINISH
```

**`PackageLoader.load(reference)`** returns inert parsed data, never imports/executed code and never creates a Tool authority. Validate package input size, canonical paths (no `../`, symlinks escaping root), object shape, id/version, hash and duplicate fields. Sandbox fixture assets must be immutable after load.

**`DependencyResolver.resolve(parsed_package, available_registries, runtime_version)`** returns exact immutable dependency keys + evidence that required versions exist, enabled, domain scope matches and required capabilities are actually mapped to allowed adapters. Do not treat declared `required_tools` as permission to call them.

**`PackageAssembler.assemble(resolved)`** creates a frozen read-only `DomainBinding` containing `(domain_id, domain_version, package_schema_version, package_digest, dependency_fingerprint, binding_fingerprint, prompt_refs, knowledge_refs, action/strategy/skill/tool/workflow refs, rule_refs, state_schema_ref, eval_refs)`. Digest must cover normalized versioned refs **and bytes/digests of loaded assets**; deterministic across process restarts, distinct when semantically relevant assets change. Bindings never embed raw credentials or mutable business state.

**`DomainRunFactory.bind(binding, runtime_input)`** verifies tenant/identity/session/subject scope and uses existing `AgentRunBinding.from_input(...domain_id,domain_version,binding_fingerprint)`. Fail closed on a mid-run domain/version/fingerprint change; never reinterpret observations from a previous domain. Cache is optional and keyed by exact fingerprint and scope, never by domain name alone.

**Model/prompt surface:** construct Domain/Task/Constraint prompt layers from bounded assets. Core safety/Policy/System boundaries remain authoritative; retrieved content is untrusted data, not system instructions. Strategy IDs and Action IDs visible to M4 remain legal Registry-derived IDs, not user or prompt-supplied permissions. The provider-neutral adapter remains intact.

**Knowledge surface:** `KnowledgeBinding` describes source IDs, version, retrieval interface, validity metadata, tenant/domain filters and provenance. Actual retrieval execution and evidence verification are separately authorized/tested; `KnowledgePlan` from M4 is not proof that retrieved facts exist.

**State surface:** Domain schema and memory policy configure an existing state boundary only; packages cannot instantiate a second authoritative State Store or write other domains' memory. Before trusted store integration, use isolated sandbox scoped state.

## 5. Unbreakable authority and isolation invariants

1. **No Core source edits for a domain switch:** same Git SHA, same AgentRunCoordinator, same M3/M4/M5 protocols; only `DomainBinding` and injected provider/adapter assets vary.
2. **Binding immutability:** exact package and dependency digests pinned at run start; change/reload yields a *new* binding, never silent hot-swap within an active run.
3. **Authorization never delegated to package:** Domain rule can reduce legal candidates or supply typed eligibility; it cannot bypass Safety, Policy, M4 validation, approval or M5 execution rights. Package-supplied prompts cannot manufacture `ApprovedActionPlan` or `ValidatedResult`.
4. **Identity/tenant separation:** every state, observation, retrieval and capability adapter request checks session, subject, tenant, domain and fingerprint before use. Foreign observations are refused rather than summarized.
5. **Side effects fail closed:** sandbox actions are explicitly mock and evidence-bearing; unknown, timed-out and unverified physical outcomes are not replayed or called success.
6. **Typed sources:** text returned by tools/knowledge remains untrusted and cannot elevate policy/strategy legal space.
7. **Version conflicts fail closed:** ambiguous package versions, missing adapter refs, disabled dependencies and stale/untrusted schemas never cause fallback to arbitrary latest.
8. **Avoid fake multi-domain evidence:** changing task wording or `domain_id` alone is insufficient; each package must independently declare real domain-specific actions, prompts, evidence rules and fixtures.

## 6. Two-domain E2E acceptance design

Use **synthetic inventory reconciliation** and **synthetic invoice audit** to avoid medical or real personal data and to make the domains genuinely different. The project may choose different harmless domains in review, provided the tests prove the same separation.

| Condition | Inventory package | Invoice package |
|---|---|---|
| Independent input semantics | uncounted vs counted stock | missing vs present invoice line items |
| Own goal/action meanings | collect count → reconcile stock | acquire line evidence → reconcile invoice |
| Own assets | manifest, prompts, rule, capability & knowledge refs | independent manifest, prompts, rule, capability & knowledge refs |
| Verified sandbox observation | checked stock-count evidence | checked invoice-line evidence |
| E2E | initial model choice → approved mock action → typed observation → model replan → evidence-based FINISH | same Core loop and authority chain with different DomainBinding |
| No Core edit | same commit SHA | same commit SHA |

**Minimum evaluation matrix:**

- 2 domains × missing/present evidence × at least 2 repeated runs (8 E2E runs minimum); model-driven steps must record nonzero actual model requests where multiple legal choices exist. Do not count deterministic `SINGLE_LEGAL` routing as model reasoning.
- Each run records actual package digest, frozen domain binding, legal candidate set, model selection, approved plan, sandbox action, verified Observation, replanning decision and `FINISH/BLOCK/WAIT` cause. Assert completion only from admitted verified evidence.
- Negative cases: unknown/disabled/incompatible package; missing tool/skill/strategy; conflicting exact versions; broken asset digest; path traversal; duplicate namespace; mutated package after bind; session/tenant/domain/fingerprint mismatch; cross-domain observation or memory contamination; malicious prompt asking to ignore policy; missing/expired knowledge evidence; tool timeout/cancellation; model illegal strategy/action. Each must fail closed.
- Swap packages via Application composition only; test that code-level `agent_core/` and `runtime/` imports/source digests are **identical** across the two runs.
- CI: full pytest, mypy, Ruff check/format; separate opt-in live-model DIAG/E2E (with model/container digests) when model service available. Report deterministic and live-model gates separately; do not conceal nondeterministic failures.

**Passing the matrix does not imply production readiness.** Report model reliability distribution and real Tool/StateStore limitations separately.

## 7. Compatibility and integration checkpoints

- **C01 Manifest:** map minimal GA-02 descriptor to existing `DomainManifest` without silently expanding Canonical contracts.
- **C02 Registry:** preserve domain/version namespace and M4 candidate filtering. `StrategyModelOutputValidator` remains authoritative.
- **C03 Binding:** reconcile fingerprint with `AgentRunBinding` and current `DomainExtensions` of `RuntimeContext`; no second source of identity.
- **C04 Policy/Rule:** compare actual M2 policy/constraint/priority engines before freezing Domain rule priorities; never assume an old diagram is the implemented order.
- **C05 Execution:** confirm M5 owner, Tool/Skill/Workflow Registry and invocation boundaries; no model-triggered direct Tool.
- **C06 Prompt/Knowledge:** content assembly does not become a permission grant or unverified truth.
- **C07 Evaluation:** real model + typed observations + dual-domain isolation, fixed thresholds and exact-head evidence.

## 8. Implementation gates and authorization

1. **Independent design review** of this Unit Spec against real source for D0; record precise blockers as amendments, without marking GA-02 DONE.
2. **D1** minimal descriptor/schema and parser with invalid-case tests, isolated branch.
3. **D2** loader/resolver/frozen binding and identity checks with deterministic positive and negative tests.
4. **D3** wire existing `StepPort`/M3/M4/typed observation through composition; no production Tool or Store grants.
5. **D4** second real package; pass both packages on the **same** Core and independent sandbox store; evidence-driven replan and finish.
6. **D5** end-to-end evaluation, exact-head independent review, merge authorization, and final main post-merge gates.

**D0 completion criterion:** decision on descriptor authority, digest scheme, source/adapter scope and experimental security boundary. **GA-02 completion criterion:** package swap independently proven by two domains, not merely a working loader or a manifest registration.

## 9. D0 Targeted Remediation — Normative Contract Profile v0.1.1

**Status:** D0 remediation proposal; not an implementation approval. This section resolves B01–B06 of PR #107 review. For D1, sections below are normative over earlier illustrative API names/layouts wherever they conflict. Do not widen GA-02 into a second Core or a new trusted Runtime.

### 9.1 B01 — DomainBinding authority, identity and lifecycle

There are three distinct sources, never interchangeable:

1. **Trusted Composition Root** is the sole issuer of a resolved `DomainBinding` at run creation. It stores an **immutable run-scoped sidecar** `BoundRunDomain` containing `run_id, request_id, trace_id, session_id, subject_id, identity_scope, tenant_id, domain_id, domain_version, binding_fingerprint` plus references to immutable asset snapshots. It is scoped to the Application's session/tenant authority. There is exactly one active binding per run.
2. Existing `AgentRunBinding.from_input` is the **Agent Loop correlation carrier**: its `domain_id, domain_version, binding_fingerprint` MUST match `BoundRunDomain` on construction and before any adapter invocation, observation admission, replan and finalization. All original identity/session/tenant fields must also match.
3. `RuntimeContext.domain_extensions.domain_id` is an existing domain **projection**, NOT authority for package version/fingerprint. It MUST equal the run binding's domain ID. Existing `DomainExtensions` has no authoritative version/fingerprint fields: do not write them to `extra` and later pretend they are verified. Existing M6 `assert_execution_correlation` only checks domain ID; this is not proof of full package binding.

**Run boundary function (proposed D2/D3):** `assert_bound_domain(sidecar, run_binding, input, runtime_context, observation?)` first verifies sidecar exact run identity/version/fingerprint and original input identity; checks RuntimeContext domain projection, plus observation domain fingerprint and correlation where available. On mismatch, return typed refusal **before** model inference, sandbox action, state read/write, tool capability lookup, or finish. A context without domain extensions fails closed when required. Sidecar is not a second State Store, does not own business state, and must not grant permission. A package update creates a fresh binding for **new** runs; no mid-run rebind, auto-upgrade, or state migration. Any missing sidecar prohibits domain-specific adapter invocation.

**Separation of digest vs run identity:** `binding_fingerprint` is an immutable package/dependency snapshot identifier; it MUST NOT include personal identity, run ID, timestamps, secrets or session-specific state. The sidecar binds that fingerprint *to* the run's identity via explicit equality checks, not by polluting a content hash with user data.

### 9.2 B02 — Canonical descriptor and digest profile

**D1 format:** UTF-8 **JSON** descriptor `package.json`, not YAML. The earlier `package.yaml` directory name is illustrative and superseded for D1; this deliberately eliminates YAML aliases/custom tags and enforces standard JSON parsing. Reject duplicate object keys at **every depth** (parser `object_pairs_hook` or equivalent), nonfinite numbers (`NaN`/`Infinity`), unpaired surrogates, non-normalized/invalid identifiers and any schema-unknown field. Never silently discard fields or coerce numeric versions.

**Versioned envelope (minimal D1):**
- `package_schema_version: "1"`;
- `domain_id` and `domain_version`: bounded nonblank ASCII identifiers (e.g. `inventory.reconcile`, `1.0.0`), with D1 grammar: `domain_id` = `[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*`, 1–80 bytes; `domain_version` = `[0-9]+\.[0-9]+\.[0-9]+` with no leading zero except `0`, 1–32 bytes; no case folding/implicit alias;
- `name`: required nonblank NFC display string (1–120 Unicode scalar values), rejecting leading/trailing whitespace, control characters and unpaired surrogates; display metadata only, never authority;
- `enabled`: required JSON boolean; D1 mapping preserves true or false exactly, D2 refuses disabled manifests and D1 must never silently coerce false to true;
- `runtime_compatibility`: **exact supported runtime contract/profile ID**, not a floating range or `latest`;
- `asset_refs`: array of objects each with `kind, namespace, id, version, sha256, relative_path`; namespace is a required, explicit domain-scoped identifier (or reserved `CORE` solely for declared shared Core assets), and only enumerated kinds, explicit exact version and namespace, no duplicate normalized `(kind,id,version,namespace)`;
- `manifest_digest`: lowercase hexadecimal SHA-256 digest of canonical descriptor **excluding `manifest_digest` itself**;
- optional `feature_flags` only if enumerated by the D1 schema. Optional non-D1 fields are forbidden rather than silently accepted.

Use canonical UTF-8 JSON bytes with keys sorted lexicographically, no insignificant whitespace, explicit NFC validation for any permitted human text, deterministic escaping and **no JSON floating-point inputs in the D1 descriptor**. The D1 implementation shall freeze and test **golden canonical byte vectors and SHA-256 outputs**, including process-restart stability. `asset_refs` are sorted by tuple `(kind,namespace,id,version,relative_path)` for digest purposes; duplicates rejected, not silently de-duplicated. The digest binds asset refs and their declared per-asset SHA-256 values. Each referenced local asset's SHA-256 is checked against actual bytes before D2 assembly. Define a deterministic `binding_fingerprint` as SHA-256 over a domain-separated envelope containing verified descriptor digest + normalized resolved dependency keys/immutable config digests + runtime contract profile ID; freeze separate golden vectors in D2. Python object IDs, memory addresses, mutable `implementation_ref` reprs and wall-clock timestamps are prohibited hash inputs.

**D0 final closure profile (B02, normative):** Serialize the **validated normalized descriptor value**, not its raw input order. Before canonicalization, reject invalid UTF-8 (including BOM and unpaired-surrogate escapes), duplicate keys at any depth, NaN/Infinity, fractional/exponent JSON numbers, integers, control/invalid Unicode characters, and text not already in NFC (reject rather than silently convert). D1 accepts JSON strings, booleans, arrays, objects, and integers only where the declared schema admits them; the minimal V1 fields below do not need numeric data. Object keys sort by Unicode code point, recursively; use JSON separators `,` and `:` with no padding; `ensure_ascii=false`, UTF-8 without BOM, JSON standard escaping for `"`, `\\`, and control characters (no unnecessary escaping of printable non-ASCII text); lowercase boolean tokens `true`/`false`. Reject duplicate decoded/normalized keys even if spelled with different escape sequences. An **explicit `asset_refs` stable sort** by `(kind,namespace,id,version,relative_path)` is performed *once during validated-value construction*, before both the returned descriptor value and digest computation; both have precisely that same normalized order. An asset with the same `(kind,namespace,id,version)` appearing twice is rejected even if its paths/digests differ. Remove only root-level `manifest_digest` from the canonical hash input; all other validated fields, including `name`, `enabled` and sorted refs, are covered. The D1 parser rejects a missing/incorrect 64-lowercase-hex manifest digest; a separate trusted expected digest remains necessary to establish authenticity.

**Literal D1 golden vector (no asset refs, tests parser/canonical bytes only; D2 still rejects unsatisfied business dependencies):**

```json
{"asset_refs":[],"domain_id":"inventory.reconcile","domain_version":"1.0.0","enabled":true,"name":"Inventory Reconciliation","package_schema_version":"1","runtime_compatibility":"GA02-D1-1"}
```

The single line above, with **no trailing newline**, is the exact canonical UTF-8 byte sequence used for SHA-256 (it excludes the top-level `manifest_digest`). Expected `sha256`:

```text
c757e6506fb0e8d7741c9abf5abc2880221655f506afd597dd7817edce195a3f
```

The complete accepted `package.json` adds `"manifest_digest":"c757e6506fb0e8d7741c9abf5abc2880221655f506afd597dd7817edce195a3f"` as another root field. Reordered root keys MUST hash identically; changed `name`/`enabled` MUST produce different hash; missing digest, one-bit mismatch, duplicate escaped key, non-NFC string, nonfinite number and invalid UTF-8 MUST fail. A non-ASCII golden vector with printable NFC text and a reordered nonempty `asset_refs` vector must be frozen and tested as part of D1 before merge; this ASCII vector alone does not establish their behavior.

**Source boundary:** only a trusted, preconfigured read-only package root is permitted. Resolve each path relative to this root; reject absolute paths, `..`, empty/dot path components, NUL, encoded traversal, symlink escapes and disallowed file types. For D1, no remote URL/import/exec and no permission inference from the package's self-declared hash. A self-digest detects accidental/tampered bytes **relative to a trusted expected digest**; authenticity comes from trusted distribution/allowlist outside the package itself. For D2 TOCTOU safety, read descriptor and assets to owned immutable bytes, validate all digests, then assemble **only from those captured bytes**; never reopen an unchecked mutable path during or after binding. Any mismatch aborts atomically before an AgentRunBinding exists.

### 9.3 B03 — Registry snapshot, enablement and revocation

`BaseRegistry.get` returns a mutable `RegistryRecord` that exposes `enabled`, `implementation_ref` and a mutable definition. `enable/disable/unregister/clear` can alter active records. Therefore:

- D2 `DependencyResolver` makes an **owned immutable value snapshot** of required registry keys `(registry_kind, namespace, item_id, exact_version)`, a canonical serialized definition digest, enabled-at-resolution status, and *only a trusted implementation-adapter key* for relevant sandbox ports. **Never retain mutable RegistryRecord, CanonicalModel instance, dict/list, or arbitrary implementation_ref in DomainBinding.**
- At resolution time, require exact key, `record.enabled is True`, definition itself enabled if its type exposes that property, cross-reference integrity and trusted adapter key. Distinguish `implementation_ref` (opaque trusted host binding) from the package-declared adapter ID; a package cannot manufacture or register its own callable.
- D3 active-use check re-reads current Registry state and independently verifies required key is still enabled, present, matches expected definition digest and allowed adapter identity/scope; disabled, unregistered or changed since bind **fails closed** before decision/physical execution. Resolver cannot use `list()` to pick an arbitrary best version.
- Snapshots freeze **semantic metadata**; active-use checks detect **revocation**. If the host supplies mutable implementation objects, guard them behind an Application-owned immutable adapter mapping and forbid uncontrolled in-place replacement; a versioned host adapter generation token is included in the dependency fingerprint.
- Duplicate registry identities, same ID with different namespaces, missing exact version, disabled-record after assembly and mismatched implementation refs have explicit deterministic negative tests. No global registry mutation during another tenant's run.

### 9.4 B04 — Existing DomainManifest mapping and compatibility

`runtime.registries.DomainManifest` remains unchanged in D1. GA-02 `PackageDescriptorV1` is an **untrusted input value**, not a replacement Canonical model or an authority to execute. `DescriptorToDomainManifestAdapter` maps required `domain_id → domain_id`, `name → name`, `domain_version → version`, `enabled → enabled`, and checked `runtime_compatibility → runtime_compatibility` with values copied from the validated descriptor; no fabricated display name or implicit enablement is permitted. D1 may construct an `enabled=false` metadata projection for audit, but does not register it or allow execution; D2 must reject disabled manifest activation. The `DomainRegistry.register` implementation stores `enabled=definition.enabled` and may not be used to override the descriptor. The descriptor's `package_schema_version`, `manifest_digest` and exact-versioned `asset_refs` remain GA-02-only metadata, not invented `DomainManifest` fields; projected asset IDs populate existing optional `registered_* / prompt_packages / knowledge_domains` lists only where mappings are explicit and test-covered. Do not invent a versioned-asset semantic for the plain string fields in DomainManifest. The D1 descriptor retains exact versions; D2 resolver consumes descriptor refs, never tries to derive versions back from projected `DomainManifest`.

**Compatibility rule:** the descriptor's `runtime_compatibility` equals the exact Application-provided supported GA-02 profile ID; mismatches reject. Domain identity namespace and `domain_version` must match the `DomainRegistry` key at D2; no `None` namespace wildcard or unknown-language aliases. Asset kind-to-Registry mapping is enumerated with validation rather than inferred from filenames. Reject unsupported schema version, unknown required or optional fields, bad identifier grammar, duplicates, implicit version ranges and disabled manifest. `feature_flags` cannot switch off Safety/M4 gates or create authorization.

### 9.5 B05 — Minimal composition Port and authority path

`BoundDomainAssets` is a typed **read-only value projection** from D2 assembly, not a new Engine or production side-effect adapter. Candidate members:
`binding_fingerprint, domain_id, domain_version, prompt_layers (renderable bounded bytes), action_refs, strategy_refs, capability_adapter_keys, eligibility_rule_keys, knowledge_source_refs, state_schema_ref, observation_projector_key`. These are *keys/content* copied from verified assets, never unchecked Python callables. Application Composition Root resolves trusted host adapters via an allowlist and creates existing M3/M4 Engine/Planner and `StepPort` once per run using these assets.

**Prompt meaning is an explicit port:** GA-01C's `StructuredStrategyTransportAdapter` sends legal IDs/observation; domain-specific semantic instructions are currently supplied independently to the model transport (e.g. `_semantic_instruction` in the sandbox tests). D3 must define `DomainPromptAssembler` to supply bounded domain/task instructions to the **existing** transport without changing its authority, and prove two package prompts produce distinct domain decisions; Registry metadata alone does not do this. Core safety/system constraints precede domain text, and retrieved text is marked untrusted. No package-provided instructions can override M4 action legality or bypass M2 safety.

**Rule meaning is also an explicit port:** allowlisted host-owned typed `StrategyEligibilityRule`/configuration may *remove* candidates via existing M4 mechanisms; no prompt rule may positively approve a denied action. Knowledge refs are declarations only until a separately verified retrieval/provenance adapter exists. M5 Tool/Workflow invocation remains protected by existing legal/approved/runtime ownership and no new Positive Grant; in GA-02 sandbox, the only executable adapters are bounded no-side-effect fixtures with verified `ObservedFact`. D3 must prove model-selected strategy/action passes existing M4 validation and the AgentRunCoordinator boundary, never direct model→Tool.

**Composition data ownership:** `PackageLoader` cannot mutate Application state or Registry; `DomainBinding` is constructed in an isolated composition scope, immutable by value, and never stored in domain-authored memory. `BoundRunDomain` correlates its fingerprint with `AgentRunBinding` and `RuntimeContext.domain_extensions.domain_id` on every step.

### 9.6 B06 — Two-domain E2E evidence assertions

An E2E is not counted as model-driven if all task decisions take `SINGLE_LEGAL`, a deterministic rule path, or a mock strategy output with an expected answer embedded in a prompt.

**For each independently loaded domain**, the acceptance run must include:
1. A pre-action decision with **at least two legal strategies** and a physical model request; the selected action is independently checked against existing M4 legal space.
2. An approved **sandbox** action with correlated run/domain/session/plan identifiers; a verified typed observation comes from that domain's trusted fixture evidence, not the raw model text or arbitrary JSON state.
3. A post-observation **actual model-driven** selection among multiple legal strategies (or a model-driven plan update where existing M4 integration explicitly supports it); record separate real provider invocation and observation content. Finish requires evidence in `AgentRunCoordinator`, not merely model assertion.
4. Two distinct real asset packages with different prompts/action/strategy meaning, evidence schemas and dependency snapshots; domain switching changes only composition inputs/DomainBinding, never `agent_core/` or `runtime/` source. Record exact identical Core git SHA, loaded asset and binding hashes, model calls, selection paths and finish causes.
5. At least 2 domains × 2 evidence conditions × 2 runs; track each true model call separately from deterministic bypass. The missing-evidence branch may justifiably `BLOCK/WAIT` if facts are insufficient, but may not fabricate success.
6. Targeted negatives: **same asset ID in distinct namespaces**, disabled dependency *after binding*, mutable asset change after digest check, foreign-domain observation, stale run fingerprint, cross-tenant/session state, prompt injection requesting safety bypass, expired/unverified knowledge, timeout/cancellation, illegal model action. Every prohibited path fails closed with typed diagnostic evidence.

Require deterministic fixture gate separately from **opt-in real-model E2E** at an exact head and model/container digest. All failed model trials remain evidence. A small passing matrix is compatibility proof, not statistical reliability or production safety authorization.

### 9.7 D1 implementation readiness / scope freeze

**D1 MAY implement only:** local trusted-root `package.json` parser; `PackageDescriptorV1` typed values and exact schema/profile validation; canonical JSON bytes and digest golden vectors; strict typed asset refs; path/duplicate/nonfinite/unknown-field negative tests; a pure `DescriptorToDomainManifestAdapter` mapping with no runtime mutation. All malformed inputs rejected before registration or model use.

**D1 MUST NOT implement:** D2 Registry resolution, binding fingerprint / revocation implementation, live Adapter instantiation, M3/M4/StepPort composition, knowledge retrieval, production side effects, new Canonical `DomainManifest` fields, altered M2/M4/M5 authority or new StateStore. Those are subsequent units after separate reviews.

**D0 closure conditions:** independent targeted review verifies B01–B06 have concrete source-compatible mechanisms, D1 profile is consistent and small, no accidental Canonical/Runtime changes; only then `D1 IMPLEMENTATION AUTHORIZATION` can be issued. Unit Spec still remains PROPOSED until that review.

## 10. Remaining follow-up topics (not D1 blockers once sections 9.1–9.7 pass)

- D2 exact dependency fingerprint and enabled/revocation semantics must have golden test vectors and separately reviewed implementation.
- D3 composition Port must integrate with real M3/M4 signatures and document authentic action semantics vs prompt injection.
- D4 live model evidence must include branching, legitimate BLOCK/WAIT and model variability, not only all-green cases.
- D5 production boundary remains unapproved even if synthetic dual-domain E2E passes.

**Next:** GA-02 D0 Targeted Independent Re-Review at the new exact PR HEAD. Do not start D1 implementation or merge #107 merely from this amendment.
