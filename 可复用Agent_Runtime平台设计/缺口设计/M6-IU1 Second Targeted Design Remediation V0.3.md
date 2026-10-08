# M6-IU1 Second Targeted Design Remediation V0.3

Status: SUBMITTED FOR INDEPENDENT RE-REVIEW. Not frozen, not implementation-authorized.
Base: main `88d3831270c56331af899e74d0c595ba1793d69d`.
Supersedes only the conflicting clauses of V0.2 relating to B-M6-IU1-RR-01/02/03. All previously accepted source-correlation, immutability, IU ownership and Agent Loop constraints remain unchanged.

## 1. RR-01 — Validation admission as one unambiguous contract

```text
ValidationAdmissionDecision (internal, non-canonical)
  status: ADMITTED | REJECTED
  reason_codes: tuple[AdmissionReasonCode, ...]  # zero or more; deterministic ordering
  binding: ValidationIdentityBinding | None
  envelope: ValidationInputEnvelope | None
  diagnostic_ref: str  # opaque, request-independent diagnostic identity
```

| State | binding | envelope | reason_codes | diagnostic_ref | downstream |
|---|---|---|---|---|---|
| ADMITTED normal | required | required | empty permitted | required | IU2 onward |
| ADMITTED with unresolved rules/time/source | required | required | nonempty unresolved diagnostic codes | required | IU2 onward, with claim promotion barred until independently verified |
| REJECTED | optional when and only when the full binding can be trusted | forbidden | at least one rejection reason | required | boundary failure only, **no ValidatedResult** |

`trace_ref` is **not required** at admission; replace previous mandatory `trace_ref` with `diagnostic_ref`. Generate a random, opaque diagnostic ID from the boundary event independently of user/session/plan fields; its uniqueness is scoped to the admission event and has **no authority to identify a business execution or grant claims**. Persisting diagnostic detail is optional and redacted; diagnostic ID must not be an evidence/validation ID.

API discipline: The internal builder's **single public method returns `ValidationAdmissionDecision`**, never both return and raise for ordinary validation failures. Low-level parser exceptions are normalized to `REJECTED + INPUT_SCHEMA_INVALID` by the boundary adapter; unexpected infrastructure exceptions propagate to the orchestrator's fail-closed error boundary and are never silently labeled ADMITTED. A rejected decision is a control outcome, not a canonical result. The orchestrator may issue an existing system-error response through a separately authorized M7 error path, with no success claim and no M8 business-state commit. Do not fabricate `execution_id` or `request_id` to fill canonical fields.

Reject reason codes use fixed namespace. Multiple reasons are deduplicated and ordered by fixed precedence: invalid schema → identity/scope → plan/request → Step/Tool correlation → other boundary violation. Do not reveal internal identifiers to end users.

Acceptance examples:
- Healthy input: `ADMITTED`, `reason_codes=()`.
- Unknown but authentic external receipt: `ADMITTED`, unresolved reason, never SUCCESS.
- Missing `identity_scope`: `REJECTED`, no envelope, opaque diagnostic_ref, no normal result.
- Unexpected service failure: orchestrator safe error path, no fabricated `REJECTED` or normal `ValidatedResult`.

## 2. RR-02 — Policy-authorized Rule Binding without retroactive M4 pinning

Authority separation:
- **M2 PolicySnapshot** decides whether validation is allowed, the minimum mode, and an explicit set of allowed validation-profile authorities (reference IDs and allowed version/digest constraints).
- **Domain ValidationRegistry** is only a lookup provider of immutable profiles; its mere registration, being latest, or enabled flag grants **no** authorization.
- **M6 RuleBindingResolver** reads policy-authorized profile refs; it cannot invent grants, downgrade strictness, or execute `PlanningGoal.completion_condition` strings.
- **M4 ApprovedActionPlan** may contain a trustworthy pinned profile. If present, exact match is mandatory and takes precedence; no fallback to any other version.

`AuthorizedValidationBindingSnapshot` (IU1 internal):
```text
  policy_snapshot_digest
  authorized_profile_id
  authorized_rule_set_ids: tuple[str, ...]
  authorized_version_constraints: tuple[...]  # exact version/digest or immutable allowlist
  registry_snapshot_id
  registry_snapshot_digest
  selection_effective_at: aware datetime   # the evaluation admission time, not fake source observed_at
  mode_floor: FAST | STANDARD | STRICT
  selected_rule_bindings: tuple[(rule_id, version, digest)]
  selection_authority: M4_PINNED | POLICY_AUTHORIZED_AT_ADMISSION
```

Exact selection algorithm:
1. Validate exact approved plan and policy snapshot. If snapshot lacks an **explicit** applicable validation-profile grant, return unresolved `VALIDATION_PROFILE_NOT_AUTHORIZED`; no ambient-registry fallback, no success claim.
2. If M4 carries a pinned grant, require its profile ID/version/digest to match the M2-authorized scope and immutable registry snapshot exactly. Disabled, changed, ambiguous or unavailable => `PINNED_VALIDATION_PROFILE_UNAVAILABLE` and no repinning.
3. Without M4 pin, select **only** one profile explicitly permitted by M2 snapshot for the exact domain/goal/tool applicability. Registry snapshot is fixed at admission; persist immutable profile content/digest in validation-bound proof. 0 matches => missing; >1 matches => ambiguous; neither case may elevate a Goal/Claim.
4. Resolve exact rule/interpreter versions and verify digest. No `latest`, cross-domain fallback, invisible policy rewrite, or automatic downgrade. M2 STRICT and currently applicable stronger safety restrictions prevail.
5. On replay of the **same evaluation**, use its stored immutable policy/profile/rule snapshot; if unavailable, fail closed. A fresh evaluation with new policy snapshot/rules gets a **new** validation fingerprint/identity and must recompute rather than retroactively rewriting the old result.
6. Registry disable/revocation is not ignored on future validation: new admissions must honor it. Already issued result consumption is constrained by the current mandatory safety barrier; a separate explicit revocation contract is needed for invalidating historical cached claims.

Migration rule: current `ApprovedActionPlan.policy_snapshot` is `dict[str, Any]` without a guaranteed validation-profile grant. Do **not** assert that historical M4 automatically contains authorization. Until a controlled M2/M4 producer amendment provides this grant, IU1 can exercise identity/source diagnostics, but cannot produce successful goal/claim promotion from unbound domain validation rules. This is an **explicit integration dependency**, not a hidden default configuration.

Test oracles: no grant; one exact grant; ambiguous grants; wrong domain; pinned/profile digest mismatch; registry disabled; replay when snapshot unavailable; stricter mode wins; rule changes yield new fingerprint; unauthorized historical result cannot be upgraded by current registry.

## 3. RR-03 — Minimal validation proof instead of mandatory full Trace fetch

Split **required consumption proof** from **optional audit trace**:
- `ValidationProof` is a small immutable, per-validation receipt maintained by the producing runtime adapter, bound by `validation_id`. It contains `validation_id, execution_id, request_id, plan_id, identity_scope, session_id, input_fingerprint, policy_snapshot_digest, rules_digest, evidence_digest, validated_result_digest, proof_schema_version` and the validation/consumer scope.
- The proof **does not assert external business truth on its own**. It only shows that the result and its validation inputs/bindings match; IU2–IU7 remain the authorities for validating facts.
- `AuditTrace` contains expanded event history and diagnostics. It is **not** required to be live or fetched on every M7/M8 consumption when the minimal proof is valid.

No change to public canonical `ValidatedResult` v1.0.0. An internal `ValidationOutcomeHandle` carries `ValidatedResult + ValidationProof` to M7/M8 via the orchestration adapter. Proof binding may be inline immutable data or fetched by exact `validation_id` from an **existing** approved runtime evidence/trace facility; no new M6 durable transaction store, global registry, cross-process consensus or recovery subsystem is authorized. If the proof cannot remain accessible for the intended lifecycle, the adapter must refuse safe success/state promotion until a properly approved persistence design exists.

Consumer checks before user success claim or M8 state mutation:
1. Validate proof integrity and `validated_result_digest`, exact request/execution, consumer's current `identity_scope/session_id` and intended purpose, rule/policy/evidence digests, and proof schema/version.
2. Reapply live/current authoritative safety restrictions; a historical proof never overrides a new safety lock.
3. Proof absence, mismatch, revoked safety permission, wrong session/scope or invalid digest => `PROOF_MISSING | PROOF_MISMATCH | PROOF_SCOPE_MISMATCH | POLICY_RESTRICTED`, and **NO_SUCCESS_CLAIM / NO_STATE_COMMIT**. Safe error/degraded response may describe inability to verify status only, using an authorized generic error path.
4. Audit trace unavailable but valid proof => may continue; emit a nonblocking audit availability diagnostic. This is **not** permission to ignore missing proof.
5. Proof must be emitted together with the result in the same authorized in-process handoff; no claim that separated distributed persistence is atomic without a separate design. Later durable/replay requirements become a bounded integration decision, not IU1 scaffolding.

**Key scope correction:** IU1 designs and contract-tests proof identities and adapter protocol; it does **not** implement final M7/M8 adapters, actual claim-policy checking, persistent proof store, or replay service. Those are downstream IU8/integration work.

Test oracles: valid inline proof, proof/result digest mismatch, proof identity mismatch, trace unavailable but valid proof, proof unavailable, stale policy with stronger live restriction, same validation replay, cross-session misuse, no durable store creation.

## 4. Agent Loop anti-overbuilding and explicit gate

Future `AgentObservationEnvelope` remains nonfrozen and owned by a downstream feedback adapter after Goal/Fact/Claim layers; M6-IU1 emits neither next-action decisions nor actual Agent Loop logic. The Agent Loop Controller receives only evidence-validated observations and must route all new actions through M2/M4/M5 approval; it controls turn/tool budgets. This remediation adds **no** Agent Runtime subsystem, Scheduler, ResourceBudgetRegistry, or Re-plan Store.

## 5. Disposition and remaining dependency

| Finding | V0.3 decision | Review state |
|---|---|---|
| B-M6-IU1-RR-01 | Admission invariant matrix + diagnostic IDs + single return outcome | REMEDIATED; independent re-review pending |
| B-M6-IU1-RR-02 | explicit M2 authorization and versioned immutable registry snapshot, no ambient fallback | REMEDIATED; independent re-review pending |
| B-M6-IU1-RR-03 | mandatory minimal proof + optional audit trace; no new M6 persistence framework | REMEDIATED; independent re-review pending |

**External readiness dependency `D-M6-IU1-01`:** Current M2/M4 policy producer does not yet prove an explicit validation-profile authorization grant. Implementer must either secure an approved cross-module amendment or keep unbound Goal/Claim validation fail-closed. This does **not** authorize inventing a permissive profile.

```text
M6-IU1 SECOND TARGETED DESIGN REMEDIATION = SUBMITTED
M6-IU1 DESIGN FREEZE = NOT_YET
M6-IU1 INDEPENDENT DESIGN RE-REVIEW = PENDING
M6-IU1 IMPLEMENTATION AUTHORIZATION = NOT_GRANTED
M6 AGENT LOOP ALIGNMENT = PRESERVED, NO NEW RUNTIME
```
