# CA-M6-IU1-06 Final Producer Authority / Transport Controlled Amendment and Exact Method-Level Diff V1.2

Date: 2026-10-08. **DESIGN CANDIDATE ONLY.** PR #82 design starting HEAD `23978cfcd1f45a6416fe2937c49b004968d5147e`; exact implemented baseline `main@5a391f0a44eef410b5c4447e71c9b8bd1c11873f`. Slice A already merged. No Slice B implementation authorization is implied.

## 1. Controlled decision and precedence

**Choose one transport for this bounded design: per-turn, private, typed, immutable grant candidate/receipt passed by trusted in-process adapter.** It is **not** a field of `ApprovedActionPlan.policy_snapshot`, `RuntimeContext.domain_extensions`, mutable Orchestrator state, trace, or a Registry lookup. Explicitly supersede the earlier proposal to inject `policy_snapshot["authorized_validation_profile_grant_v1"]` for this controlled path. Current M4 invariant `approved.policy_snapshot == policy_decision.model_dump(mode="json")` remains unchanged. Neither approach is authorized for coding until independent review accepts this choice.

Separation: M2 same-decision receipt → M4 exact-plan *read-only* narrowing → M5 unchanged → M6 per-turn verification → (future IU2–IU8) validation. A valid grant authorizes selecting one pinned Validation Profile for evaluation only; never means Tool/Goal/Business success.

## 2. Authority proof, exact source and trust model

### 2.1 Internal structures (NOT public Canonical)

`NoGrant(reason_code)`, `PolicyEvaluationOutcome(policy_decision: PolicyDecision, source_receipt: PolicyValidationAuthorizationReceiptV1|NoGrant)`, `ProfileIntent`, `PlanBoundGrantCandidate`, `VerifiedGrant` are typed frozen internal values; IDs and digests must be domain-neutral, nonblank and context-scoped.

Receipt fields: `source_kind` (BASE_POLICY_EVALUATION / INTEGRATED_CONSTRAINT_EVALUATION), `source_decision_id`, `canonical_decision_digest`, `request_id`, `identity_scope`, `session_id`, `source_rule_id@version#registration_digest`, explicit `profile_id@version#digest`, `domain_id`, `goal_type_scope`, `tool_ref_scope`, `validation_mode_floor`, `evaluation_nonce`, immutable local `producer_instance_ref`. Producer is an operator-vetted M2 rule/constraint registered through a protected manifest; neither a self-declared receipt nor matching digest authenticates its source.

**Protected trust root must be proven at actual deployment/build entrypoint before any positive grant**: exact operator-vetted policy-rule manifest, registered rule implementation and version/digest, local protected invocation chain, explicit applicable Profile records, plus same-call receipt production. Unit fake ≠ production issuer. Unavailable root => `NoGrant(NO_TRUSTED_PRODUCER)`. If same-call evidence cannot be returned without changing frozen interfaces, require **separate controlled M2 extension authorization**; do not perform a second evaluation.

### 2.2 Base and integrated M2

Base `runtime/policy_management/engine.py:DefaultPolicyEngine.evaluate` currently loops `PolicyRule.evaluate`→`PolicyFragment`→`_aggregate`→`PolicyDecision`. No Profile Grant exists. Candidate internal opt-in `evaluate_with_receipt(...)->PolicyEvaluationOutcome`: same single rule iteration and same aggregate result, with immutable receipt from approved rule contribution only; existing `evaluate(...)->PolicyDecision` unchanged for legacy. Prove **one** evaluation, equivalent decision, fail-closed if registry/source proof absent; never synthesize a receipt from `PolicyFragment.validation_mode` or flags.

Integrated `runtime/orchestration/m2_runtime.py:_evaluate_integrated_policy` uses `RuntimeConstraintEvaluator` and `RuntimeConstraint.policy_decision`. A distinct integrated same-call receipt adapter is required; base DefaultPolicyEngine evidence is NOT interchangeable. If current RuntimeConstraintEvaluator cannot supply a trusted immutable source receipt, emit NoGrant; do not alter its return in-place without separate approval.

## 3. Exact method-level change sketch against implemented main

| Actual path/symbol | Reviewed physical insertion (candidate only) | Guard |
|---|---|---|
| `runtime/policy_management/engine.py:DefaultPolicyEngine.evaluate` | Keep public three-parameter PolicyDecision method; add separate internal opt-in same-evaluation outcome seam only if independently authorized | Legacy rule order, error handling, one evaluation, decision equivalence |
| `runtime/orchestration/runtime.py:RuntimeOrchestrator.run` | After POLICY `_run_stage` completes, read local same-call receipt or NoGrant; before PLAN bind decision/request/session/scope; after POLICY_RECHECK and M4 invariants narrow to exact plan; after EXECUTE verify M5 relation; invoke local facade at RESULT_VALIDATE instead of shared legacy validator **only** in explicit GRANT_GATED mode | Preserve 10-stage topology and `_run_stage` type check; no mutable per-turn data on `self` |
| `runtime/orchestration/m2_runtime.py:M2RuntimeOrchestrator.run` | Analogous insertions in independently overridden run, but read same-call receipt from `_evaluate_integrated_policy` and only **after** `_assert_runtime_constraint_allows_flow` passes | Preserve constraint, denied/alternate, priority, plan request invariants |
| `runtime/orchestration/m2_runtime.py:_evaluate_integrated_policy` | Candidate return-side *private* receipt holder attached to current evaluation invocation, not to shared `constraint_box` or `self`; NoGrant if source cannot prove origin | No unrelated policy re-evaluation, no forgery |
| `runtime/planning/policy_approval.py:PlanApprovalCoordinator._validate_approved_integrity` | **NO EDIT**; retain exact policy_snapshot equality | Never inject a grant after approval |
| `runtime/planning/runtime_integration.py:RuntimePolicyRecheckerAdapter.recheck` | **NO semantic edit**; original ApprovedActionPlan only | No fourth public return |
| `runtime/interfaces/validation.py:ResultValidator.validate` | **NO EDIT**, retain three args | No extra public grant parameter |
| New `runtime/interfaces/validation_grant.py` | Internal typed immutable receipt/NoGrant, binder/verifier protocols | Not Canonical |
| New `runtime/validation/grant_facade.py` | Per-turn `ResultValidator` implementation carrying verified-or-no-grant, with `close()` and invalid-after-close invariant | NoGrant cannot delegate to legacy affirmative validation |
| New `runtime/policy_management/validation_profile_authority.py` | Separate M2 authority-port proposal with protected manifest lookup (default NoGrant) | **Positive producer code BLOCKED pending trust root proof** |
| New integration factory | `build_grant_gated_runtime` requiring reviewed authority manifest, core and approved adapters; when absent fail construction or explicit NoGrant-only runtime | No arbitrary Domain-provided privileged provider |
| `runtime/contracts/*`, `runtime/execution/*` | **NO EDIT** | No public schema or M5 mutation |

### 3.1 Turn-local pseudo diff, both concrete run bodies

```python
# POLICY: must originate from this exact policy/constraint evaluation, not a second call
policy_decision = await existing_policy_stage()                 # unchanged stage and checks
policy_receipt = obtain_same_invocation_receipt_or_no_grant()    # local only
intent = verify_receipt_and_turn_identity_or_no_grant(
    policy_receipt, policy_decision, processed_input, runtime_context
)
# PLAN / PLAN_VALIDATE / POLICY_RECHECK unchanged
approved = await existing_policy_recheck()
assert approved.policy_snapshot == policy_decision.model_dump(mode="json")
candidate = narrow_to_approved_plan_or_no_grant(intent, approved)
# EXECUTE unchanged
execution = await existing_execute()
grant = verify_execution_and_candidate_or_no_grant(
    candidate, execution, processed_input, runtime_context, approved
)
validator = grant_facade_factory.create(grant)  # never self.result_validator mutation
try:
    validated = await existing_result_validate_stage(
        validator.validate(execution, runtime_context, approved)
    )
finally:
    validator.close()
```

The pseudo diff is an **insertion topology only**; implementation must correctly cover outer run exceptions/cancellation, including exceptions *before* facade creation. A `try/finally` surrounding only the awaited validate cannot close a facade when earlier helper creation fails. Factory and tests must explicitly prove teardown on normal/error/cancel and concurrent turns.

### 3.2 NoGrant / malformed / replay

Malformed core admission => typed rejection/error in the existing error routing, **not** fabricated `ValidatedResult`. For a valid inbound with NoGrant, use a reviewed schema-valid `ValidatedResult` with nonaffirmative status and no positive `claim_policy` (subject to actual public enum/required-fields check); no legacy affirmative delegation. Lost same-call proof after recovery => NoGrant, not dynamically resolve latest Profile. Authority invalidation, revoked/expired/disabled or ambiguous profile => NoGrant. A verified grant alone cannot produce positive Fact/Goal/Claim.

## 4. Exact tests / acceptance requirements

P01–P17 in existing V1.1 remain mandatory; additionally require:
- two physically distinct policy evaluation sources, single invocation each, no second evaluation; identical decision digest between source outcome and M4 snapshot;
- base/integrated legacy mode preserves existing decision, stage order, error routing and public ABI;
- enforce approved scope narrowing without mutating approved plan; independent concurrent turns cannot share a facade/receipt;
- manifest absent/mismatched/spoofed, Domain Registry-only, profile wrong version/digest, expiration/revocation, replay proof loss => NoGrant;
- original M2 integrated blocked/alternate/priority controls unchanged;
- explicit `ValidatedResult` no-grant fixture created using exact current Canonical required fields/enums, no success/claim promotion;
- no unreviewed signature change in PolicyEngine, RuntimeConstraintEvaluator, ResultValidator or planning interface;
- full pytest, mypy, ruff check, ruff format after code implementation; four passing gates do not replace issuer proof.

## 5. Controlled impact and remaining blocker disposition

**B-PD-01:** producer contract resolved conceptually; real M2 same-evaluation receipt source/manifest remains UNPROVEN. **B-PD-02:** dual path topology detailed; exceptional control flow and exact patch review still required. **B-PD-03:** trusted factory shape chosen, but actual deployment root remains UNVERIFIED. **R-PD-04/05:** test inventory mapped, executable tests not yet implemented.

Independent acceptance of V1.2 should explicitly choose the *single turn-local nonmutating transport*, close the preceding *design ambiguity*, and can separately authorize only a `NO_GRANT_ONLY` scaffold after an exact implementation authorization gate. It must NOT authorize Positive Grant while source proof is absent.

```text
CA-M6-IU1-06 FINAL PRODUCER AUTHORITY / TRANSPORT AMENDMENT = SUBMITTED_FOR_INDEPENDENT_REVIEW
TRANSPORT_CHOICE = SINGLE_TURN_LOCAL_IMMUTABLE_NO_SNAPSHOT_MUTATION (PROPOSED)
M2_SAME_EVALUATION_POSITIVE_PRODUCER_PROOF = NOT_ESTABLISHED
TRUSTED_PRODUCTION_COMPOSITION_ROOT = NOT_ESTABLISHED
D-M6-IU1-01 = OPEN
M6-IU1_SLICE_B_IMPLEMENTATION_READINESS = NOT_READY
SLICE_B_POSITIVE_GRANT_IMPLEMENTATION_AUTHORIZATION = NOT_GRANTED
NEXT = CA-M6-IU1-06 Final Controlled Amendment Independent Design Review
```
