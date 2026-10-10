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

## 9. Open design decisions requiring independent review

- Which format and canonical serialization provide trustworthy package/asset digests without requiring a new Canonical contract?
- What precise `DomainExtensions` / `AgentRunBinding` fingerprint mapping should be treated as authoritative during context construction?
- How do existing Registries represent namespaces, available registered versions and implementation bindings, and which adapters are safe for tests?
- Are domain Prompt/Rule/Knowledge references all directly injectable via existing M3/M4 Ports, or is a narrow composition adapter required?
- Where is the exact trust boundary of Knowledge fixture provenance, including expiration and tenant filtering?
- Should explicit replan/finish tests include two-stage model choice as a mandatory minimum, or also check branching task strategies?

**Next:** GA-02 D0 Independent Unit Spec Review → targeted amendment → D1 only after design authorization.
