# M6-IU1 Targeted Design Remediation + Agent Loop Readiness Alignment V0.2

Status: DESIGN REMEDIATION CANDIDATE; Independent Re-Review required; no implementation authorization.
Baseline main: `88d3831270c56331af899e74d0c595ba1793d69d`; original PR #82 head: `4860b94eaa6d1c7a9f4620a51cee691755d479a0`.
Scope: M6-IU1 inbound/correlation/provenance contracts only. This document amends the v0.1 alignment and IU1 Unit Spec where specified. If conflicting, v0.2 is the candidate for independent review, not an approved public schema change.

## 0. Decisions, precedence, and ownership

- Existing Canonical Registry defines the public `ValidatedResult` v1.0.0 fields. IU1 **does not** change its fields, `ClaimPolicy`, `ResultValidator.validate` signature, `ExecutionResult` or `ApprovedActionPlan`.
- `ValidationInputBuilder` and `ValidationCorrelationGuard` are pure M6 boundaries. M4 remains owner of ApprovedActionPlan, M5 of ExecutionResult, M2 of Policy constraints.
- `EvidenceReference` is **internal and observational**, not `VerifiedFact`. IU1 does not resolve trust, freshness, goals, business state or claims.
- A later Agent Loop Controller consumes **M6 interpreted feedback**, not raw M5 Tool results; **no loop or replan in IU1/M6**.

## 1. CA-M6-IU1-01 — Fail-Closed Failure Outcome Contract (B-R01)

Two noninterchangeable paths:

**REJECTED_INPUT (boundary integrity failure):** invalid/missing typed canonical input, missing/blank execution_id/request_id/plan_id/identity_scope/session_id, identity mismatch, plan/request mismatch, contradictory duplicate IDs, invalid ownership mapping, malformed mandatory evidence identity. `ValidationInputBuilder.build` returns `ValidationAdmissionDecision(status=REJECTED, reason_codes, correlation_context?)` or raises `ValidationBoundaryError` *internally*, mapped by the M6 adapter into the same typed rejected decision. It **must not** construct canonical `ValidatedResult` with fabricated required IDs. The upstream orchestrator controls a safe error path, which permits **zero verified facts, zero affirmative claims, zero automatic state commit**. Under no circumstances may it emit a normal successful `ValidatedResult`.

**ADMITTED_UNRESOLVED (truth incompleteness):** correct identities, valid input, but absent goal/tool rule, incomplete observation, unknown time or missing external receipt. The admission outcome is `ADMITTED`; downstream IU2–IU7 can eventually produce canonical `ValidatedResult(validation_status=UNKNOWN|NOT_VALIDATED, business_status=UNKNOWN|WAITING, claim_policy.allowed_claims=[], claim_policy.forbidden_claims=[...])` based on resolved evidence, with mandatory reason codes in a separately bound trace. IU1 itself **does not fabricate a final ValidationResult**. `WAITING` requires explicit pending-event evidence, not simply a timeout.

Proposed typed contracts (internal; not a new public main-chain type):
```text
ValidationAdmissionDecision
  status: ADMITTED | REJECTED
  reason_codes: nonempty typed tuple
  binding: ValidationIdentityBinding | None
  envelope: ValidationInputEnvelope | None  # only ADMITTED
  trace_ref: str
```
Invariants: `ADMITTED => binding+envelope`; `REJECTED => envelope=None`; reason codes include `INPUT_SCHEMA_INVALID, EXECUTION_PLAN_MISMATCH, EXECUTION_REQUEST_MISMATCH, IDENTITY_SCOPE_MISMATCH, MISSING_SESSION_ID, STEP_IDENTITY_CONFLICT, EVIDENCE_SOURCE_ID_CONFLICT`. For missing rules use `GOAL_RULE_MISSING, TOOL_INTERPRETER_MISSING` as **unresolved observations**, not admission rejection, unless policy specifies validation requires an authoritative binding before any processing.

## 2. CA-M6-IU1-02 — Exact M5 Source Correlation (B-R02)

The **only source of observed results** is an immutable copy of canonical M5 `ExecutionResult`; plan provenance from exact approved M4 plan. IU1 maps evidence references without promoting truth:

| M5 source | authoritative join key | cardinality | admission behavior |
|---|---|---|---|
| `step_results[]` | `step_id` in approved `steps[]`; `step_execution_id` if present | approved step IDs unique; nonnull step_execution_id unique per execution | unknown/foreign `step_id`, duplicate present IDs => REJECTED; absent optional IDs => no synthesized identity, diagnose `STEP_PROVENANCE_INCOMPLETE` |
| `tool_results[]` | explicit `tool_call_id`, where present joined to step `tool_call_ids[]` | same tool_call_id one canonical occurrence, unless underlying journal explicitly versions attempts | duplicate or conflicting known correlation => REJECTED; orphan with no verifiable step join => quarantine/unresolved and cannot promote |
| `skill_results[]` | explicit `step_execution_id` or registered mapping, if present | many evidence records can attach to one step | no positional joins; unmatched => unresolved |
| `workflow_result` / `workflow_results[]` | explicit workflow/step identity where available | one-to-many, cross-step only with authorized mapping | no assumption that singular and plural fields represent different events; identical identified observations dedup; inconsistent duplicates => conflict diagnostic |
| `business_outputs[]` | producer/source reference and explicit step/execution binding | zero-to-many | never equate output presence to business SUCCESS; uncorrelatable => unresolved |
| `state_observations[]` | explicit source scope, time and execution binding | zero-to-many | no scope/time inference, no high-certainty fact |
| `execution_events[]`, `errors[]`, `cancellation`, `timing` | execution_id from parent; nested identifiers if present | zero-to-many | lifecycle context only, not business evidence by status |
| durable M5 journal | **not** independently queried by IU1 | not included unless serialized/bound into canonical M5 observation | never query durable storage through an invented M6 backdoor |

Stable `EvidenceReference`: `source_kind, source_path/index, source_local_id?, execution_id, step_id?, step_execution_id?, tool_call_id?, identity_scope, observed_at?, evidence_fingerprint, reference_id`. Use source path/index solely to distinguish multiple unkeyed records **within one frozen canonical list**, not as source-independent identity or authoritative correlation. `observed_at=None` means temporal status UNKNOWN, not now. Preserve original timezone offset; reject naive times where mandatory, otherwise mark unknown and defer IU2. Reject cross-scope nested IDs if present. Cross-source disagreement is **not** silently deduplicated or a confirmed fact; IU5 later resolves it. IU1 can quarantine unjoined observational entries without losing them.

## 3. CA-M6-IU1-03 — Rule/Policy Authority (B-R03)

`PlanningGoal.completion_condition: str` is descriptive, never executable code or authority. No LLM interpretation or dynamic reinterpretation. Versioned `ValidationRuleBinding` and `ToolInterpreterBinding` must be read through an injected read-only resolver:
```text
rule_ref: {domain_id, rule_id, version, digest}
applicability: {goal_id|tool_id, capability_version?, policy_profile_id}
selection_status: PINNED_MATCH | RESOLVED_EXACT | MISSING | AMBIGUOUS | VERSION_MISMATCH | DISABLED
```
Binding priority:
1. If approved plan carries a trustworthy pinned validation profile, resolve **only** exact matching version/digest; mismatch => unresolved/fail-closed (never silently select latest).
2. If no approved profile exists (current M4 generally lacks a dedicated validation binding), M6 uses the Policy-authorized domain registry snapshot at validation admission, then **freezes** exact refs for that validation evaluation. This is a provisional bridge, **not** retrospective assertion that M4 pinned it. Cross-turn/replay must retain the resolved immutable snapshot.
3. Missing/ambiguous/disabled/version mismatch => `GOAL_RULE_UNAVAILABLE` / `INTERPRETER_UNAVAILABLE`, no goal completion or success claim. Explicit policy prohibition can reject admission.

`policy_snapshot` is from ApprovedActionPlan and immutable; `RuntimeContext` can add restrictive current safety constraints but cannot weaken it. `STRICT` policy cannot downgrade to FAST. Mode authority remains Policy (M2) or signed domain validation profile, not IU1 heuristic or arbitrary field. If authoritative mode cannot be resolved, admission may proceed in a `MODE_UNRESOLVED` restricted state **only for diagnostics**; no Rule/Claim success promotion; reject when policy mandates strictly bound mode.

## 4. CA-M6-IU1-04 — Provenance and Canonical Output Compatibility (B-R04/R05)

`ValidatedResult` v1.0.0 public field list stays unchanged. `validation_id` is a correlation handle to a durable or verifiable validation trace; trace records exact `execution_id, plan_id, request_id, session_id, identity_scope, policy_snapshot_digest, rule_bindings/digests, source evidence references, input_fingerprint`, output digest, status and reason codes.

**Mandatory handshake**: before M7/M8 consume a result, the orchestration adapter must verify `validation_id` resolves to a matching immutable trace binding, same execution/request/scope, and rule/evidence digests; missing/mismatch => downstream **NO_SUCCESS_CLAIM / NO_STATE_COMMIT**. A single-process in-memory trace may suffice in an initial demo **only if** it is guaranteed available for the entire consumer lifecycle; production durable lifecycle and replay require an approved storage adapter. M6 may **emit** trace events but does not commit user state or memory.

Proposed future additive canonical amendment `CA-M6-PUBLIC-01` (requires separate authorization): decide top-level `plan_id, identity_scope, trace_ref` vs nested metadata, and typed `goal_validation` shape, together with schema version migration/mixed-version read compatibility. Not authorized by this remediation.

Validation identity scope: `validation_id` per evaluation fingerprint and rule/policy version; `trace_ref` explicitly binds tenant/session/scope and is not a globally guessable user identifier. Ref IDs are scoped inside execution, not cross-user identifiers. `identity_scope` is the canonical isolation key; `subject_id` is not substituted silently.

## 5. CA-M6-IU1-05 — Immutable snapshot and deterministic digest (R-R06)

1. On admission, take defensive snapshots of Pydantic inputs with `model_dump(mode="json")` under frozen schema versions, then normalize to value-only immutable structures. Do not assume frozen dataclass alone makes nested dict/list immutable.
2. Use canonical UTF-8 JSON serialization with fixed key sorting, explicit null vs missing, stable encoding of enum/datetime, and stable list ordering **where order is semantically significant**; sort only collections defined as sets. Record canonicalization version `m6-input-canon-v1`.
3. `input_fingerprint = SHA-256(canonical bytes of identity+approved plan+execution result+context safety projection+resolved policy/rule snapshots+schema/canonicalization versions)`. Do not hash volatile trace creation timestamps, random event IDs, or secrets into public IDs.
4. `reference_id = SHA-256(namespace + input_fingerprint + exact canonical source path + source-local ID when present + canonical source payload digest)`, scoped by execution/identity. Same exact snapshot returns same references. Legitimately repeated identical observations in different list positions stay distinguishable; reordering ordered lists changes fingerprint rather than silently reassigning source IDs.
5. No mutable reference alias after snapshot. Digest collision handling is defensive (canonical payload equality check), never silently merge distinct evidence.
6. Rule configuration change, context/policy change, and source observation change => new validation fingerprint. Idempotent calculation **does not** imply cached truth remains fresh later: IU2 evaluates freshness against a separately bound evaluation cutoff and revalidates when cutoff changes.

## 6. R-R07 — IU1 exact scope and Agent Loop alignment

**IU1 IN:** schema/admission, identity and source cardinality guard, read-only rule/policy binding, immutable inbound snapshot, deterministic evidence *references*, trace binding, canonical compatibility plan and negative contract fixtures.
**IU1 OUT:** source trust/freshness verdict (IU2), tool semantics (IU3), goal/business status (IU4), conflicts/facts (IU5), claim policy (IU6), follow-up recommendation (IU7), final validator orchestration (IU8), Agent's next action decision (separate Agent Loop Controller).

Proposed future **AgentObservationEnvelope** (not built or public-frozen by IU1):
```text
  goal_ref, validation_ref, execution_ref,
  goal_statuses, business_status, validation_status,
  verified_fact_refs, unresolved_fact_refs, conflict_refs,
  permitted_followup_signals, unresolved_reason_codes,
  policy_boundary_ref, state_snapshot_ref,
  resource_budget_ref, observation_version
```
Owner: downstream feedback adapter after IU4–IU7, not M6-IU1. Only validated, evidence-linked statuses are populated; absent signals remain UNKNOWN. Agent Loop Controller decides `FINISH, CONTINUE, REPLAN, WAIT_USER, WAIT_EXTERNAL, STOP` from that observation; all new actions pass M2/M4 approval and M5 execution; M6 never chooses or executes an action.

**Vertical Slice Gate after minimal M6 completion** (do not wait for full M7/M8 feature breadth): identical goal with different trustworthy observations must produce distinct bounded Agent decisions; the test must prove no replan-on-UNKNOWN without authority, no forbidden Tool action, no fabricated business success, and max-turn/tool budgets. Small test-only response/state adapters are acceptable; do not claim Production Agent from a demo.

## 7. Test oracle matrix, revised
| ID | Scenario | Expected admission / trace | Forbidden outcome |
|---|---|---|---|
| T01 | exact matching plan/request/scope/session | ADMITTED, stable snapshot | invented scope |
| T02 | plan mismatch | REJECTED + EXECUTION_PLAN_MISMATCH | ValidatedResult SUCCESS |
| T03 | request mismatch | REJECTED + EXECUTION_REQUEST_MISMATCH | silent mapping |
| T04 | scope mismatch | REJECTED + IDENTITY_SCOPE_MISMATCH | cross-user fact |
| T05 | missing session | REJECTED + MISSING_SESSION_ID | synthetic session |
| T06 | duplicate Step or ambiguous Tool owner | REJECTED + correlation code | positional reassignment |
| T07 | unmatched optional Tool observation | ADMITTED unresolved, quarantine | fabricated Step |
| T08 | absent rule/disabled binding | ADMITTED unresolved (or policy-mandated REJECTED) | Goal SUCCESS |
| T09 | pinned digest mismatch | unresolved/blocked with VERSION_MISMATCH | latest rule fallback |
| T10 | strict policy + context weaker mode | preserve STRICT / deny downgrade | FAST relaxation |
| T11 | missing observed_at | temporal UNKNOWN | `now()` as event time |
| T12 | two identical recorded items in distinct positions | distinct source refs, reproducible | hidden dedup |
| T13 | same immutable snapshots rerun | identical canonical digests and references | unstable identity |
| T14 | rule snapshot changed | new input fingerprint | reuse stale decision |
| T15 | trace reference missing at M7/M8 | NO_SUCCESS_CLAIM / NO_STATE_COMMIT | unverified output |
| T16 | Tool SUCCESS but no business receipt | no VerifiedFact/business success in IU1 | false success |
| T17 | business waiting evidence vs timeout ambiguity | evidence preserved, deferred to IU4 | WAITING asserted from timeout |
| T18 | no Tool/Skill/Workflow invocation, State write, Memory write, natural-language output | side-effect free | execution |
| T19 | freeze nested input, then mutate caller dict | frozen snapshot unchanged | mutable alias |
| T20 | Agent Loop planned observation schema only | no next-action generation by M6 | M6 replan |

## 8. Finding disposition and gate
| Finding | Remediation | State |
|---|---|---|
| B-M6-IU1-R01 | §1 typed admission and safe outcome | DESIGN ADDRESSED; re-review pending |
| B-M6-IU1-R02 | §2 source cardinality/correlation | DESIGN ADDRESSED; re-review pending |
| B-M6-IU1-R03 | §3 exact binding precedence and fallback | DESIGN ADDRESSED; re-review pending |
| B-M6-IU1-R04 | §2/§4 identity/provenance lifecycle | DESIGN ADDRESSED; re-review pending |
| B-M6-IU1-R05 | §4 mandatory trace handshake/public amendment | DESIGN ADDRESSED; re-review pending |
| R-M6-IU1-R06 | §5 deterministic immutable fingerprints | DESIGN ADDRESSED; re-review pending |
| R-M6-IU1-R07 | §6 IU ownership and future Agent Loop | DESIGN ADDRESSED; re-review pending |

```text
M6-IU1 TARGETED DESIGN REMEDIATION = SUBMITTED
AGENT LOOP READINESS ALIGNMENT = DOCUMENTED (future contract only)
M6 CANONICAL PUBLIC CONTRACT AMENDMENT = NOT AUTHORIZED
M6-IU1 INDEPENDENT DESIGN RE-REVIEW = PENDING
M6-IU1 IMPLEMENTATION READINESS = NOT_READY
M6-IU1 IMPLEMENTATION AUTHORIZATION = NOT_GRANTED
```
