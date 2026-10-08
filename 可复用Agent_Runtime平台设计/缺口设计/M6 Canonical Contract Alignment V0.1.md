# M6 Canonical Contract Alignment V0.1

- Status: PROPOSED / NOT FROZEN / NOT IMPLEMENTATION AUTHORIZED
- Source base: main @ `88d3831270c56331af899e74d0c595ba1793d69d`
- Owner: M6 Result Validation; scope: IU1 contracts and M5→M6 inbound boundary
- Normative source order: (1) Canonical Contract Registry V1.0 for primary-chain required/optional, naming and versions; (2) implemented Pydantic contracts and interfaces; (3) Schema Registry/M6 frozen design for candidate *internal* detailed models. Inconsistency requires controlled amendment, never implicit override.

## 1. Actual baseline and collisions

| Topic | Authoritative current state | Design proposal / mismatch | Decision |
|---|---|---|---|
| Main output | `ValidatedResult` canonical v1.0.0 required `schema_version, validation_id, execution_id, request_id, validation_status, business_status, claim_policy` | frozen M6 design additionally requires metadata/plan_id/scope/rule version | **retain canonical required list**; propose additive optional provenance only through separate controlled amendment |
| Optional output | `goal_validation, verified_facts, unverified_facts, conflicting_facts, followup, state_recommendation, validation_errors, quality` | Schema Registry says arrays and typed nested models; Python currently `dict[str, Any]` and `list[dict]` | design typed *internal* DTOs and explicit projection; do not silently change public field types |
| Business / validation status | `BusinessStatus`: SUCCESS, PARTIAL_SUCCESS, FAILED, WAITING, UNKNOWN. `ValidationStatus`: VALIDATED, PARTIALLY_VALIDATED, NOT_VALIDATED, CONFLICTED, UNKNOWN | Goal WAITING and detailed GoalStatus proposed, but not canonical top-level enum | keep distinct dimensions; no `ValidationStatus.WAITING` |
| Input | `ResultValidator.validate(execution_result, runtime_context, approved_action_plan)` | M6 proposal adds standalone `ValidationInput`, policy snapshot, rules/mode | design internal validated input builder; **retain existing abstract interface** until approved explicit migration |
| M5 identity | `ExecutionResult.execution_id/plan_id/request_id/identity_scope` | `ValidatedResult` lacks top-level identity_scope/plan_id | derive immutable identity binding internally, preserve in trace; additions to canonical need amendment |
| M4 goals | `PlanningGoal.goal_id, goal_type?, primary?, completion_condition?: str` | typed/registered condition semantics not implemented | never execute/free-interpret open strings; resolve against version-pinned Rule Registry; missing rule fail-closed |
| Execution output | `plan_status` is execution-only, plus step/tool/workflow/event/observation outputs | design sometimes treats M5 as business truth | no promotion to BusinessStatus/VerifiedFact without M6 evidence semantics |

## 2. Proposed IU1 internal DTOs (not new canonical main-chain schema)

### ValidationInputEnvelope (M6 internal)
- `execution_result: ExecutionResult` (required, immutable consumption)
- `approved_action_plan: ApprovedActionPlan` (required)
- `runtime_context: RuntimeContext` (required, snapshot)
- `identity_scope: str` (derived and equality-checked, nonempty)
- `session_id: str` (from context, nonempty)
- `policy_snapshot: Mapping` (from approved action plan, frozen)
- `validation_mode: ValidationMode` (resolved by **authorized** Policy/Rule binding, cannot downgrade)
- `validation_rule_bindings`: exact rule_id/version/content digest or explicit MISSING marker per goal
- `interpreter_bindings`: exact tool/version rule/digest or explicit MISSING marker
- `observation_cutoff: datetime` timezone-aware; explicit evidence time boundary
- `trace_ref` optional, no customer PII embedded
- Input derived from existing API parameters by `ValidationInputBuilder`; no second public `ResultValidator` interface without approved amendment.

### ValidationIdentityBinding
Required: `execution_id, plan_id, request_id, identity_scope, session_id`. Verify:
- execution plan_id == approved plan.plan_id; execution request_id == approved plan.request_id
- execution identity_scope == context.identity_context.identity_scope
- session_id is from runtime_context.session_context.session_id
- exact execution id across step/tool/workflow evidence when present; do not infer missing scopes
- equality must be checked before evidence construction and before any Result projection
- absent/mismatch or unauthorized rule policy -> structured fail-closed diagnostic; no verified fact and no success claim.

### EvidenceReference (internal)
- `evidence_id` deterministically bound to source_kind, source_id, execution_id, identity_scope, observed_at and stable source-version/hash; do not synthesize timestamps or status
- `source_kind` typed core category; source-specific interpretation through Domain registries
- `source_id`, `execution_id`, `identity_scope`, `observed_at` (if absent: freshness UNKNOWN), `raw_status`, `provenance_ref`, `authority_profile_ref` optional
- evidence snapshot only from existing M5 output; external callback/status read requires separately authorized injection contract, not implicit M6 Tool calls
- trust, freshness and promotion to fact are **not** IU1 responsibilities.

### ValidationProjection (temporary compatibility boundary)
- preserve exact `ValidatedResult` canonical required/optional field names, types, `schema_version=1.0.0` and `ClaimPolicy.allowed_claims/forbidden_claims`
- schema-invalid and identity-invalid cannot be packaged as `BusinessStatus.SUCCESS`; no success claims
- `ValidationStatus.UNKNOWN/NOT_VALIDATED` and `BusinessStatus.UNKNOWN` are safe unresolved defaults, not fabricated `FAILED`
- unknown external result != confirmed failure; waiting != unknown; verified failure may be `VALIDATED + FAILED`
- transport of provenance/rule IDs to M7/M8 deferred to authorized canonical additive schema amendment or trace linkage; must not silently hide loss.

## 3. Authority and invariants
1. M5 is sole execution-result authority; M6 cannot mutate/retry Tool/Skill/Workflow or synthesize durable journal.
2. M4 approved plan is sole goal provenance; M6 must not rewrite goals or parse arbitrary `completion_condition` using LLM.
3. M2 approved policy snapshot is minimum safety barrier. Domain constraints may strengthen, never weaken `STRICT`.
4. M6 raises only evidence-backed facts/claim permissions. Forbidden overrides allowed; UNKNOWN cannot be elevated to SUCCESS by default.
5. M7 receives claim semantics, not unvalidated raw Tool output. M8 receives proposed state recommendation, never direct state mutation from M6.
6. Idempotent deterministic validation identity per exact execution-result fingerprint + rule/profile version + policy snapshot; if result/rule changes, new identity/revalidation. Do not conflate with M5 execution retry identity.
7. Scope mismatch, invalid timestamps, missing interpretation rule, ambiguous correlation and evidence conflict fail closed without successful user claim.
8. No domain constants, e.g. notification or healthcare claim values, frozen into Core enums.

## 4. Controlled amendment candidates (not approved in v0.1)
- **CA-M6-001** Additive canonical `ValidatedResult` provenance (`plan_id`, `identity_scope`, `metadata` or dedicated link), versioning, M7/M8 propagation; select **one** shape and migration strategy after impact review.
- **CA-M6-002** Decide whether `goal_validation` should remain compatibility dictionary publicly or move to typed list with a versioned adapter.
- **CA-M6-003** RuleBinding/InterpreterBinding formal typed registries; scope of cross-module version pinning.
- **CA-M6-004** Policy snapshot/mode selection authority and fail-closed codes; make input builder ownership explicit.
- **CA-M6-005** Evidence reference identity and per-source key cardinality for Tool journal, Step, Workflow and business observations; verify exact M5 projector output.
None of the above is silently frozen or implemented.

## 5. Gate
```
M6 CANONICAL ALIGNMENT DRAFT = COMPLETE
M6-IU1 INPUT CONTRACT = PROPOSED
PUBLIC VALIDATEDRESULT SCHEMA CHANGE = NOT_AUTHORIZED
M6-IU1 FORMAL IMPLEMENTATION = NOT_AUTHORIZED
NEXT = M6-IU1 INDEPENDENT DESIGN REVIEW / CONTROLLED AMENDMENT
```
