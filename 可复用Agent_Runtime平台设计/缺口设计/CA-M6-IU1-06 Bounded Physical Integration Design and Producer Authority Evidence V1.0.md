# CA-M6-IU1-06 Bounded Physical Integration Design + Producer Authority Evidence V1.0

Date: 2026-10-08. Design-only. Reviewed main baseline `88d3831270c56331af899e74d0c595ba1793d69d`, PR #82 prior HEAD `135018b6dff4c684705af2a16034d060b1f86c12`.
Status **PHYSICAL DESIGN PROPOSED / PRODUCER EVIDENCE GAP OPEN / IMPLEMENTATION NOT AUTHORIZED**.

## 1. Evidence ledger: inspected implemented source, NOT invented authorization

| Source file / method | Verified existing authority | Absent capability / implication |
|---|---|---|
| `runtime/policy_management/rules.py / PolicyRule.evaluate` | domain/runtime rule returns `PolicyFragment` (constraints) | NO versioned Validation Profile grant result |
| `runtime/policy_management/definitions.py / PolicyFragment` | validation_mode and allowed/forbidden Tool/Action, optional policy_flags | NO profile ID/version/digest, issuer proof or approved grant |
| `runtime/policy_management/engine.py / DefaultPolicyEngine.evaluate` | aggregates safety and PolicyRule fragments into `PolicyDecision` | NO authenticated profile selection artifact exposed to the Orchestrator |
| `runtime/orchestration/m2_runtime.py / M2RuntimeOrchestrator.run` | separate complete 10-stage loop, integrated runtime constraint via `_evaluate_integrated_policy` and `constraint_box`; returns `PolicyDecision` from `RuntimeConstraint` | Base Orchestrator patch alone DOES NOT reach this path |
| `runtime/orchestration/runtime.py / RuntimeOrchestrator.run` | direct POLICY, POLICY_RECHECK, EXECUTE, RESULT_VALIDATE call points | NO grant or turn-scoped facade |
| `runtime/planning/runtime_integration.py / RuntimePolicyRecheckerAdapter.recheck` | returns only `ApprovedActionPlan` | NO companion handoff |
| `runtime/planning/policy_approval.py / PlanApprovalCoordinator` | exact M2 policy snapshot equality | must preserve |
| `runtime/policy_enforcement/rechecker.py` | creates exact PolicyDecision snapshot | must preserve |
| `runtime/contracts/input.py` | request/session/identity scope original fields | must equality-bind to RuntimeContext, plan and execution |
| `runtime/interfaces/validation.py` | public three-argument Validator | cannot add fourth arg implicitly |

**Evidence finding:** An existing authenticated M2 Validation Profile authorization producer has **not** been identified. `PolicyRule` can provide policy-related inputs, but ordinary policy flags/validation_mode/Domain Registry are **insufficient** to authorize a particular Profile. No existing cryptographic provenance port is established in these files. Accordingly **D-M6-IU1-01 remains OPEN**; a reference to a `PolicyRule` is not proof of profile permission.

## 2. Minimal physical choice: one trusted producer, one turn-local handoff

### 2.1 M2-owned producer, rule authority
Add a small M2-owned `ValidationProfileIntentAuthority` Protocol, strictly injected by the trusted composition root and *registered only with pre-approved domain policy rules*. Proposed exact method:
```python
async def capture(
    *, policy_decision: PolicyDecision,
    runtime_input: RuntimeInput,
    runtime_context: RuntimeContext,
    immutable_policy_evidence: "PolicyEvaluationEvidence | None",
    turn_nonce: str,
) -> "ProfileIntent | NoGrant": ...
```
A `PolicyEvaluationEvidence` **cannot be assumed available** from `DefaultPolicyEngine.evaluate` or `M2RuntimeOrchestrator._evaluate_integrated_policy`. Therefore an independent, strictly controlled M2 producer/decision-evidence *exposure change* is REQUIRED before an affirmative intent can be issued. The first no-op implementation returns `NoGrant(NO_AUTHORIZED_POLICY_EVIDENCE)`. The evidence producer must bind registered policy source identity/version, exact policy_decision_id, policy digest, request/scope/session and profile allowlist, and prove it is from the policy evaluation that actually generated the decision—not a post-POLICY reinterpretation or unrelated side policy evaluation. No `latest` registry lookups.

Prefer an **immutable same-invocation typed evidence snapshot** from the M2 evaluation boundary (base Policy Engine or integrated RuntimeConstraint path) to a per-turn local variable. If changing frozen M2 evaluator return signatures would be required, introduce a reviewed internal production adapter with an explicit fixed result/receipt; do NOT write into `PolicyDecision.policy_flags`, `RuntimeContext.domain_extensions`, generic `trace`, or other ambiguous dictionaries. The receipt and `PolicyDecision` equality must be proven. Initial deployment may support `NO_GRANT` only.

### 2.2 M4 binding and trusted source
After `POLICY_RECHECK` returns exact `ApprovedActionPlan`, an `ApprovedPlanGrantBinder` checks immutable pre-policy intent, exact M2 decision and exact approved plan, and creates a restricted in-process candidate. It cannot reissue intent, widen profile scope, invoke Tool, or mutate plan/policy snapshot. Use a turn-local nonce solely to prevent accidental cross-turn interchange; nonce is not authenticating material.

Binding identity: `policy_decision_id`, decision digest, approved plan digest, plan_id, request_id, input/session/identity_scope, exact profile ID/version/digest, approved goal types and tool requirement refs, applicable ValidationMode floor. Each source must be present or NO_GRANT. Domain identity and profile applicable scope must be provided by the vetted authorization producer, not inferred from `goal_type` alone.

### 2.3 M6 single-turn consumption
Define internal `GrantAwareValidationCore.validate_bound(execution_result, runtime_context, approved_action_plan, *, grant)`; use per-turn `PerTurnResultValidator` wrapping an injected, reviewed `GrantAwareValidationCore`, implementing the existing public 3-arg `ResultValidator.validate` ABI. Scope: local `run()` variable, no mutation of shared `self.result_validator`, use `try/finally` to close/invalidate. If NoGrant, a verified restricted M6 path can only return canonical non-affirmative status for *valid* inbound identifiers; invalid core input is admission REJECTED/error, and no fabricated result. Legacy validator implementations not approved for no-grant constraints must not receive privileged delegation.

Do not implement an additional Profile Registry, grant store, signer, persistent replay authority or alternate M6 processing engine.

## 3. CRITICAL: both existing Orchestrator concrete paths must be covered

Two distinct concrete `run` bodies exist:
- `RuntimeOrchestrator.run`: standard PolicyEngine.evaluate → Planner → Rechecker → ResultValidator.
- `M2RuntimeOrchestrator.run`: integrated `_evaluate_integrated_policy` with `RuntimeConstraintEvaluator` and `PrioritySubjectResolver`, plus constraint and request checks, *duplicated full stage orchestration*.

A base `RuntimeOrchestrator.run` modification is **not inherited** by the subclass's overridden `run`. For actual functionality, either (A) apply the same **small, reviewed, per-turn insertions** in both bodies, with shared pure internal helper/factory for intent and facade, OR (B) deliberately refactor shared stage internals under a separately approved M0/M2 behavior-equivalence amendment. **For this CA, choose A** to avoid a broad runtime refactor. For M2 integrated path, positive authorization requires the M2 constraint producer to expose evidence from that exact integrated POLICY decision, not an unrelated `DefaultPolicyEngine` re-evaluation. If no such receipt, NO_GRANT. Keep existing priority/preemption/safety invariant order.

## 4. File-by-file exact change authorization candidate

| File | Narrow physical diff | Gate |
|---|---|---|
| **new** `runtime/interfaces/validation_grant.py` | immutable ProfileIntent / NoGrant / candidate / VerifiedGrant, approved producer/issuer interfaces; strict typed value contracts | Design candidate |
| **new** `runtime/policy_management/validation_profile_authority.py` | trusted M2 evidence consumer and no-op source; real rule-backed grant only after proof-of-authority amendment | **BLOCKED real producer** |
| `runtime/policy_management/engine.py` | if opted in, expose exact immutable policy-evaluation receipt via separately approved extension; existing evaluate return unchanged | **BLOCKED pending authority evidence** |
| `runtime/orchestration/m2_runtime.py` | opt-in capture after integrated POLICY, grant bind after approved Plan, single-turn M6 facade with current constraints intact | **REQUIRED; not omitted** |
| `runtime/orchestration/runtime.py` | same opt-in capture, bind, per-turn facade and cancellation closure | Design candidate |
| **new** `runtime/validation/grant_facade.py` | 3-arg turn-local grant-aware M6 facade; no-grant restricted path | Design candidate |
| `runtime/planning/runtime_integration.py` | existing adapter `recheck()` ABI untouched; only targeted regression fixtures if needed | No functional change |
| `runtime/planning/policy_approval.py` | exact policy_snapshot equality remains | No semantic change |
| `runtime/policy_enforcement/rechecker.py` | approved policy snapshot construction remains | No semantic change |
| `runtime/contracts/policy.py, planning.py, validation.py` | canonical public shape/version unchanged | No change |
| `runtime/execution/**` | no changes | Forbidden |
| new `tests/test_m6_iu1_grant_integration.py` | positive restricted producer/facade fixtures and negative oracles for both orchestrators | Required |
| existing M0/M2/M4 and M5 tests | regress complete stage/constraint/snapshot behavior | Required |

**Scope note:** A test fake that issues valid ProfileIntent demonstrates the *adapter* but does not establish a production M2 authority producer. A final authorization must distinguish structural port implementation from activating domain-positive grant issuance.

## 5. Exact method-level diff sketch (NOT IMPLEMENTED)

For each concrete Orchestrator.run:
```python
policy_decision = await existing_POLICY_stage(...)
intent = await optional_vetted_capture_or_no_grant(
    policy_decision=policy_decision,
    runtime_input=processed_input,
    runtime_context=runtime_context,
    turn_nonce=local_turn_nonce,
    # evidence MUST be from this exact POLICY stage; absent=>NoGrant
)
draft = await existing_PLAN_stage(...)
validated_draft = await existing_PLAN_VALIDATE_stage(...)
approved_plan = await existing_POLICY_RECHECK_stage(...)
grant_candidate = bind_existing_intent_to_approved_plan_or_no_grant(
    intent, approved_plan, policy_decision, processed_input, runtime_context
)
execution_result = await existing_EXECUTE_stage(approved_plan, runtime_context)
verified = verify_candidate_and_execution_or_no_grant(
    grant_candidate, execution_result, approved_plan, runtime_context
)
validator = per_turn_validator_factory.for_grant(
    verified, immutable_turn_identity=...,
) # do not mutate self.result_validator
try:
    validated = await existing_RESULT_VALIDATE_stage(
        validator.validate(execution_result, runtime_context, approved_plan)
    )
finally:
    validator.close()
# unchanged RESPONSE/UPDATE control under existing safety and Claim boundaries
```

All added optional callbacks fail closed; avoid introducing an extra main-chain stage/TraceStatus, and preserve original stage type checks and error exits. Turn-local scope lifetime on success/failure/cancellation; a leaked facade reference becomes invalid after closure. If the new producer cannot prove authority then `NoGrant`, and *any affirmative Goal/business/claim route is forbidden*. A NoGrant result is not itself verified business failure. For processes that restart/recover midturn, lost proof => NoGrant unless a separate approved replay design is provided.

## 6. Physical acceptance and evidence matrix

| ID | Tested path | Negative/positive oracle |
|---|---|---|
| P01 | base Orchestrator no producer | no implicit grant; approved plan unchanged; no unauthorized positive business claims |
| P02 | M2RuntimeOrchestrator no producer | same NoGrant, integrated constraint/priority invariant preserved |
| P03 | both orchestrators with approved same-call evidence fixture | captured only after *their own* POLICY success before PLAN |
| P04 | forged Domain provider/Registry profile | cannot issue authorized ProfileIntent |
| P05 | different policy_decision_id/policy digest | NoGrant |
| P06 | mismatch RuntimeInput request/session/scope vs Context/Plan/Execution | NoGrant or canonical Admission REJECTED |
| P07 | M4 exact policy_snapshot equality | unchanged |
| P08 | M2 intent cannot be minted after approval | NoGrant |
| P09 | profile lookup missing/reversion/digest changed | NoGrant; never latest |
| P10 | concurrent turns on same instance, different grants | isolated per-run facades |
| P11 | cancellation during validation and after approval | facade invalidated, no orphan grant |
| P12 | replay with lost original producer proof | NoGrant; no historical grant fabrication |
| P13 | valid grant but Tool success without verified business evidence | no Goal/Business SUCCESS or positive claim |
| P14 | legacy validator would allow unverified success | facade refuses unsafe delegation |
| P15 | shared M6 validator public three-arg ABI | unchanged |
| P16 | M2 integrated runtime constraint blocked/alternate/preemption | unchanged stage execution and denial behavior |
| P17 | tests in both runtimes, complete closure | pytest+mypy+ruff+format checked, no production Tool/State mutation from grant path |

## 7. Explicit readiness vs authorization

**Producer authority evidence classification:**
- ESTABLISHED: PolicyRule / PolicyFragment / DefaultPolicyEngine real M2 facilities and PolicyDecision outputs.
- ESTABLISHED: M2RuntimeOrchestrator integration path, canonical M4 approval and snapshot equality, public three-arg M6 contract.
- NOT ESTABLISHED: Profile ID/version/digest authorized by any specific M2 policy rule, trustworthy producer evidence/port, authenticated registered composition-root identity, exact immutable policy evaluation proof for integrated M2 path.
- NOT ESTABLISHED: test runner/gates for future implementation.

A minimal **NO_GRANT-only** structural port can be independently authorized as a closed-scope foundation, but cannot be advertised as a working RuleBinding capability. Positive Profile authorization requires the producer evidence and controlled producer-code authority to be independently accepted first. Do not conflate an adapter's test fake with authentic Policy authority.

```text
CA-M6-IU1-06 BOUNDED PHYSICAL INTEGRATION DESIGN = SUBMITTED
EXACT DIFF INVENTORY = PREPARED FOR REVIEW
M2 PRODUCER AUTHORITY EVIDENCE = INCOMPLETE / OPEN
M2 INTEGRATED ORCHESTRATOR PATH = IDENTIFIED / MUST BE COVERED
D-M6-IU1-01 = OPEN
CA-M6-IU1-06 INDEPENDENT PHYSICAL DESIGN REVIEW = PENDING
M6-IU1 SLICE B POSITIVE GRANT IMPLEMENTATION READINESS = NOT_READY
M6-IU1 IMPLEMENTATION AUTHORIZATION = NOT_GRANTED
NEXT = CA-M6-IU1-06 Independent Physical Design + Producer Authority Review
```
