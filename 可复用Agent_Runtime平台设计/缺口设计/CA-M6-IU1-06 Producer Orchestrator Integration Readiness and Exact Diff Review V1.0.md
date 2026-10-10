# CA-M6-IU1-06 Producer / Orchestrator Integration Readiness + Exact Diff Authorization Review V1.0

Date: 2026-10-08. Review-only artifact. Main base: `88d3831270c56331af899e74d0c595ba1793d69d`. PR #82 reviewed HEAD: `08082e33935f5bc3a915c48ef446fe0ff94610c9`. Result: **NOT_READY / NO IMPLEMENTATION AUTHORIZATION**.

## 1. Inspected exact live surfaces

- `runtime/orchestration/runtime.py`: RuntimeOrchestrator constructor has fixed injected interfaces; run has POLICY→PLAN→PLAN_VALIDATE→POLICY_RECHECK→EXECUTE→RESULT_VALIDATE; `PolicyRechecker.recheck(draft, decision)` is required to produce `ApprovedActionPlan`; `ResultValidator.validate(execution_result, runtime_context, approved_action_plan)` is invoked with precisely 3 args. The Orchestrator holds `self.result_validator` shared across turns. Stage type gates must remain.
- `runtime/planning/runtime_integration.py`: `RuntimePolicyRecheckerAdapter.recheck` calls `PlanApprovalCoordinator.approve` and returns only `result.approved_plan`, not `PolicyApprovalResult` or grant.
- `runtime/planning/policy_approval.py`: `PlanApprovalCoordinator._validate_approved_integrity` insists `approved.policy_snapshot == policy_decision.model_dump(mode="json")`.
- `runtime/policy_enforcement/rechecker.py`: the original snapshot is made from `policy_decision.model_dump(mode="json")`.
- `runtime/interfaces/policy.py`, `runtime/interfaces/validation.py`: frozen public signatures. `runtime/contracts/input.py` includes `session_id` and `identity_scope`; `RuntimeContext` carries session/identity contexts; the PolicyDecision/ApprovedPlan models do not independently establish full scope/session grant authority.

## 2. Review of exact candidate integration

The V0.4 two-phase design is **coherent**: after POLICY stage M2-associated intent capture, then immutable intent narrowing after M4 approval; a turn-local grant verified immediately before the result validation call; a per-turn grant-aware facade retains the three-argument public `ResultValidator` signature. The design does **not** prove an existing trusted profile-grant-producing rule or composition-root registration. The actual code path lacks both producer and facade wiring; therefore code authorization needs a bounded interface proposal and producer proof.

### Strict file change inventory

| Path | Intended smallest diff | Decision |
|---|---|---|
| `runtime/orchestration/runtime.py` | Optional, explicitly vetted policy-intent source + turn-local state; POLICY-after/PLAN-before capture, post-approval narrower, before M6 single-turn adapter; finally invalidation; default NoGrant; preserve stage sequence | CANDIDATE ONLY |
| **New:** `runtime/interfaces/validation_grant.py` | Internal immutable Intent, NoGrant, VerifiedGrant, per-turn binder/authority/verifier Protocols; no Canonical output change | CANDIDATE ONLY |
| **New:** `runtime/validation/grant_facade.py` (or actual existing validation package if present) | PerTurnResultValidator adapter with immutable per-turn binding, close invalidation, legacy validator fail-closed and no optimistic claim | CANDIDATE ONLY |
| **New:** `runtime/policy_management/validation_profile_authority.py` | Policy-owned profile authorization source that demonstrates genuine M2 rule provenance and explicit exact profile authorization; default provider NoGrant | **BLOCKED until authority semantics accepted** |
| `runtime/planning/runtime_integration.py` | No mandatory signature change to RuntimePolicyRecheckerAdapter; if wiring needed, only nonsemantic composition support after separately approved diff | PRESERVE |
| `runtime/planning/policy_approval.py` | Preserve exact snapshot equality; add regression tests, do not weaken | NO SEMANTIC EDIT |
| `runtime/policy_enforcement/rechecker.py` | Preserve policy snapshot construction, no grant injection | NO EDIT |
| `runtime/interfaces/validation.py` | Preserve 3-argument public API; extension only through separately typed internal protocol | NO EDIT |
| `runtime/contracts/policy.py`, `planning.py`, `validation.py` | Preserve existing public Canonical types and versions | NO EDIT |
| M5 execution and journaling | No modifications | OUT OF SCOPE |
| `tests/test_m6_iu1_*grant*.py` (new) | Exact-source grant, no-grant, malformed/scope, concurrent turn, cancellation, replay missing, nonpositive claim, legacy validator, 3-argument ABI | REQUIRED WHEN AUTHORIZED |
| `tests/test_m4_policy_approval.py` and Orchestrator existing tests | Regression proving exact policy snapshot and original stage flow | REQUIRED WHEN AUTHORIZED |

## 3. Blocking implementation gaps

**IR-CA-M6-IU1-06-01 — M2 authority source/root proof (BLOCKER):** No concrete existing M2 profile authorization rule/port is shown in the inspected base. `capture_at_policy` timing plus injected Protocol is not proof that the profile was authorized. Require explicit policy-owned selection rule, trusted composition-root wiring, accepted domain applicability/profile constraints, and negative spoofing oracle. A fake producer in unit tests is insufficient for production readiness. Never infer authority from `validation_mode` or registry presence.

**IR-CA-M6-IU1-06-02 — Exact interface and failure routing diff (BLOCKER):** Proposed internal port, binder, facade, and NoGrant-safe core have not been expressed as executable exact method-level diff against Orchestrator. Determine which existing composition root builds the Orchestrator and registers only the vetted source. Confirm fail-closed `NoGrant` output is schema-valid without fabricating IDs; malformed inbound must use the existing exception path. Protect `_run_stage` type checks, close on cancellation and concurrent turns, and make any new binder invocation explicit and non-authorizing.

**IR-CA-M6-IU1-06-03 — Production authorization scope and evidence (BLOCKER):** No exact-head code changes, no test evidence, and no formal independent producer/integration impact authorization. Do not authorize full Slice B or public domain-success validation from a documentation-only PR. A separate Slice A-only design/authorization may proceed in parallel.

## 4. Allowed decision boundaries

**Design may be considered suitable for a bounded detailed implementation proposal**, not code authorization. A future controlled amendment can define and authorize only: trusted M2 profile authority producer, optional Orchestrator lifecycle seam, single-turn adapter, associated fixtures. No new Registry, key service, global store, cross-process proof runtime, M5 recovery, autonomous planner, or fourth public validator argument.

**Cross-module guard:** Maintain `approved.policy_snapshot == policy_decision.model_dump(mode="json")`; preserve M4 approval authority; keep M5 execution unmodified. A verified grant only permits authorized validation-rule evaluation; actual Fact/Goal/Claim promotion belongs to later M6 units with independent evidence.

**Minimum pre-authorization oracles:** same request/scope/session positive and negative joins; fake Domain authorization rejected; absent producer defaults NoGrant; M4 snapshot unchanged; same Plan to M5; legacy validator may not launder SUCCESS; concurrent turns, cancellation, exception, lost replay proof, current safety restrictions, exact-version pin; no Tool/state side effects. Postcode: pytest, mypy, ruff check, ruff format check; not run in this review.

## 5. Formal decision

```text
CA-M6-IU1-06 PRODUCER / ORCHESTRATOR INTEGRATION READINESS = NOT_READY
EXACT DIFF INVENTORY = DOCUMENTED (PROPOSED PATHS)
PRODUCER AUTHORITY = NOT VERIFIED
ORCHESTRATOR/FACADE CONTROLLED IMPLEMENTATION AUTHORIZATION = NOT_GRANTED
D-M6-IU1-01 = OPEN
M6-IU1 SLICE A = ELIGIBLE_FOR_SEPARATE BOUNDED AUTHORIZATION
M6-IU1 SLICE B = BLOCKED
FULL M6-IU1 IMPLEMENTATION AUTHORIZATION = NOT_GRANTED
NEXT = CA-M6-IU1-06 Bounded Physical Integration Design + Producer Authority Evidence
```
