# CA-M6-IU1-06 Targeted Amendment Remediation — B-FCA-01..03 + R-FCA-04 V1.3

Date: 2026-10-08. Exact design predecessor: PR #82 `b66116cb164d1b6498c3fcd9fa1a370685316182`. Implemented baseline: `main@5a391f0a44eef410b5c4447e71c9b8bd1c11873f`. **Design remediation only; no production Positive Grant or Slice B code implementation authorized.**

## 0. Frozen invariants and precedence

This amendment refines V1.2; **one transport only**: trusted same-invocation M2 evidence → immutable coroutine-local internal receipt/NoGrant → read-only plan-bound candidate → M6 turn-local facade. Do not append grants to `ApprovedActionPlan.policy_snapshot`; current M4 invariant `approved.policy_snapshot == policy_decision.model_dump(mode="json")` must remain exact. No new public `PolicyDecision`, `RuntimeConstraint`, `ResultValidator` or `ValidatedResult` fields and no M5 semantics modification.

If trusted producer authority is missing, the only safe operational grant status is `NoGrant`. A digest or self-described source identifier is *integrity correlation*, not proof that an M2 rule authorized a profile.

## 1. B-FCA-01 — exact same-invocation local evidence bridge

### Base Orchestrator

Current actual code: `runtime/orchestration/runtime.py:RuntimeOrchestrator.run` awaits `self._run_stage(...,"POLICY", self.policy_engine.evaluate(...), PolicyDecision,...)`; `DefaultPolicyEngine.evaluate` runs the configured rules once and aggregates `PolicyFragment` into one `PolicyDecision`.

Candidate implementation uses a **turn-local bridge object** allocated in `run` before POLICY, and an internal opt-in adapter `evaluate_decision_with_local_evidence(context, understanding, safety, bridge)` that:
1. Performs **exactly one** policy rule evaluation/aggregation; returns the original `PolicyDecision` (not `PolicyEvaluationOutcome`) to `_run_stage` so existing type/invariant checks remain intact.
2. Produces the immutable source receipt from that same invocation *only if* a separately approved protected M2 policy authority plugin actually emits a provenance-bound profile authorization. Before the public `PolicyDecision` is returned, atomically fills the previously empty, invocation-scoped bridge once; on failure, records `NoGrant` or leaves absent.
3. After a successful POLICY `_run_stage`, Orchestrator `take_once()` obtains receipt (or `NoGrant`); consumer checks `policy_decision_id`, canonical decision digest, request/session/scope, issuer reference and evaluation nonce. Reuse, second take, mismatched decision and missing fill ⇒ `NoGrant`.
4. Preserves existing `PolicyEngine.evaluate` 3-input signature for legacy mode. **Do not call original evaluate and a second evaluate-with-receipt**; opt-in adapter owns one evaluation. If the opt-in adapter would require duplicated policy aggregation logic, demand separate controlled M2 code/design review before implementation.

Bridge is not globally stored, not `self`, not a ContextVar, not a mutable shared engine attribute; it is not passed into Domain-provided functions as an ability to mint proof. The bridge transports a receipt but is never itself the trust root.

### Integrated M2 Orchestrator

Current actual code: `runtime/orchestration/m2_runtime.py:_evaluate_integrated_policy` calls `priority_subject_resolver.resolve(...)`, then **one** `runtime_constraint_evaluator.evaluate(...)`, appends `RuntimeConstraint` to `constraint_box`, and returns `constraint.policy_decision`; the POLICY stage checks `_assert_runtime_constraint_allows_flow`.

Candidate: a **separately authorized integrated constraint adapter** wraps this *same* `RuntimeConstraintEvaluator.evaluate` invocation and, only where an authenticated source receipt exists in that evaluation outcome, fills a separate run-local bridge. The helper **still returns a PolicyDecision** and appends one `RuntimeConstraint`; only after `_assert_runtime_constraint_allows_flow` passes may the local receipt be consumed. If evaluator exposes no receipt, use `NoGrant`. Never use DefaultPolicyEngine as a fallback producer on this path.

**Hard authorization limit:** Neither current `PolicyRule.evaluate -> PolicyFragment` nor current `RuntimeConstraintEvaluator.evaluate -> RuntimeConstraint` proves a real profile authority; changing their internals/wrapping their output for affirmative receipts is a *separate blocked producer implementation decision*. A fake bridge demonstration cannot close D-M6-IU1-01.

## 2. B-FCA-02 — protected authority root and deployability proof

Before `VerifiedGrant` can exist in production, an owner must supply a reviewable **TrustedAuthorityRegistrationEvidence** bundle:
- actual executable deployment bootstrap/entrypoint (path + invocation/config authority), owner of factory and immutable manifest, trust assumptions (local-only);
- allowlisted M2 registered rule `rule_id@version#registration_digest`, immutable Profile `profile_id@version#digest`, domain, goal-type and tool-reference applicability, mode floor;
- same evaluation call's rule contribution and resulting decision digest linked to the receipt; integrated path requires the exact constraint producer, not base PolicyEngine;
- disallow arbitrary Domain consumer, current Tool output, prompt fields, Registry existence, or mutable request payload from registering authorization providers;
- tested revocation/expiry decision source and clock; if unavailable when required => NoGrant; replay without original proof => NoGrant;
- recorded source provenance sufficient for review of version pinning, concurrent turns and execution ownership.

**Gate contract**: `build_grant_gated_runtime` refuses a request for positive-issuer mode if manifest/provenance/approved profile/authorized implementation is missing. A separate **NO_GRANT_ONLY** build may be accepted in a future independent bounded implementation decision; it must not silently delegate to an unreviewed legacy Validator. Unit mock issuer may exercise the wiring but never satisfy production authority evidence.

Disposition: `B-FCA-02 = DESIGN_SPECIFIED / EXTERNAL_TRUST_ROOT_EVIDENCE_OPEN`.

## 3. B-FCA-03 — exact public NoGrant output oracle

Current Canonical `ValidatedResult` requires `validation_id, execution_id, request_id, validation_status, business_status, claim_policy`. Existing enums permit `ValidationStatus.UNKNOWN` and `BusinessStatus.UNKNOWN`. `ClaimPolicy` requires `allowed_claims` and `forbidden_claims`.

For **valid input admission** with NoGrant, a reviewed restricted result factory can use:

```python
ValidatedResult(
    validation_id=trusted_per_turn_validation_id,
    execution_id=execution_result.execution_id,
    request_id=execution_result.request_id,
    validation_status=ValidationStatus.UNKNOWN,
    business_status=BusinessStatus.UNKNOWN,
    claim_policy=ClaimPolicy(
        allowed_claims=[],
        forbidden_claims=[],  # an empty list is NOT a grant; deny-all is enforced in consumers
        conditional_claims=[],
    ),
    goal_validation=None,
    verified_facts=None,
    state_recommendation=None,
    validation_errors=[{"code": "GRANT_MISSING", "source": "M6_IU1"}],
)
```

**Crucial:** `trusted_per_turn_validation_id` must be generated by the previously approved M6 validation invocation/identity owner, NOT from arbitrary Tool/Domain fields. This factory **must explicitly prohibit all positive claims in its own typed status and in downstream consumption**. Because `forbidden_claims=[]` is not a universal deny-list, a hard downstream consumer invariant `NoGrant ⇒ allowed_claims==[] AND no positive claim emission` is required; without demonstrated consumer guard, NO_GRANT_ONLY adapter cannot be called production-safe. Prefer a typed `NoGrantOutcome` distinct from public Canonical if no trusted validation ID or consumer guard exists. **No fabricated public result for malformed input**; reject via current orchestration error path, do not invent request/execution IDs.

Implementable fixture must assert all six required fields, unknown statuses, no Goal/Fact/Claim promotion, no legacy-validator delegation, and unknown ≠ business failure. Later optional `forbidden_claims` semantics and downstream M7 claim policy remain separate gate dependencies.

Disposition: `B-FCA-03 = CONTRACT_DEFINED / DOWNSTREAM_DENY-ALL_AND_ID_OWNER_VERIFICATION_REQUIRED`.

## 4. R-FCA-04 — lifecycle / cancellation / concurrent-turn method-level boundary

**No shared state**: each concrete `run` allocates a fresh immutable-intent carrier and unique facade; never replace `self.result_validator`, never write a grant to `turn_context` trace or shared builder state.

Recommended control flow for **both** `RuntimeOrchestrator.run` and overridden `M2RuntimeOrchestrator.run`:

```python
async def run(...):
    bridge = LocalOneShotReceiptBridge()  # default NoGrant; unique per call
    facade = None
    try:
        # original 10-stage flow, unchanged stage names/type checks
        # POLICY callable, optionally vetted adapter, returns *PolicyDecision*
        # verify bridge only after POLICY invariant success
        # PLAN, PLAN_VALIDATE, POLICY_RECHECK unchanged
        # bind to original approved plan and frozen M4 policy snapshot
        # EXECUTE unchanged; verify exact ExecutionResult/plan/request/identity
        facade = vetted_factory.new_turn_facade(verified_or_no_grant)
        # RESULT_VALIDATE uses facade.validate(execution, context, approved)
        # RESPONSE_PLAN, RESPONSE, UPDATE unchanged
        return original_runtime_turn_outcome
    finally:
        bridge.invalidate()
        if facade is not None:
            facade.close()
```

Placement requirement: the outer `try/finally` starts **before** first stage that may access a receipt, and encloses *all* paths until turn return. If `_open_turn` itself can fail, no bridge/facade exists yet; if any factory step fails before assignment, it must clean its own partially constructed resources. Preserve `CancelledError` propagation rather than converting it into a successful `ValidatedResult`; denied/alternate and exception stage transitions stay unmodified. After `close()`, calls to facade must fail, including delayed tasks and leaked coroutine references. Two concurrent runs of the same instance must never share a grant.

Gates: compare exact original 15 stage call points in both concrete runtimes; explicit fixtures for input/POLICY/approval/EXECUTE/RESULT_VALIDATE/response exceptions, CancelledError at all relevant checkpoints, concurrent interleavings, finalization on success and failure, receipt double-consumption, integrated M2 deny/interrupt/alternate/priority unchanged. Existing M4 exact policy-snapshot equality and M5 execution guarantees unaffected.

Disposition: `R-FCA-04 = DESIGN_ADDRESSED / PHYSICAL_DIFF_AND_RUNTIME_TESTS_PENDING`.

## 5. Final amendment closure matrix and next gate

| Item | Design-level disposition | Blocking implementation condition |
|---|---|---|
| B-FCA-01 | TARGETED_DESIGN_ADDRESSED | distinct real same-evaluation producers + single invocation evidence |
| B-FCA-02 | DESIGN_SPECIFIED / EVIDENCE_PENDING | vetted production root, manifest, authorizing rule/profile registration |
| B-FCA-03 | CONTRACT_DEFINED / GUARDS_PENDING | no-fabrication validation ID owner, no-claim downstream consumers |
| R-FCA-04 | TARGETED_DESIGN_ADDRESSED | exact method diff + cancellation/concurrency executable tests |

Controlled source candidate inventory: base and integrated Orchestrator (tiny local insertions only), explicit policy-owned same-call evidence adapter (independent M2 authorization), new internal typed grant contracts/facade and guarded factory, tests for P01–P17. **No public Canonical change, no M5/Memory/Tool edit, no new stages.**

```text
CA-M6-IU1-06 TARGETED AMENDMENT REMEDIATION = SUBMITTED_V1.3
B-FCA-01 = DESIGN_ADDRESSED / REAL_PRODUCER_PENDING
B-FCA-02 = AUTHORITY_EVIDENCE_OPEN
B-FCA-03 = CONTRACT_ADDRESSED / CONSUMER_GUARD_PENDING
R-FCA-04 = DESIGN_ADDRESSED / TESTS_PENDING
D-M6-IU1-01 = OPEN
SLICE_B_POSITIVE_GRANT_IMPLEMENTATION_READINESS = NOT_READY
SLICE_B_IMPLEMENTATION_AUTHORIZATION = NOT_GRANTED
NEXT = CA-M6-IU1-06 Targeted Independent Design Re-Review (V1.3)
```
