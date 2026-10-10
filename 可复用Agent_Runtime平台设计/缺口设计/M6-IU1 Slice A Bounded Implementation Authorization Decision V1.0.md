# M6-IU1 Slice A Bounded Implementation Authorization Decision V1.0

Date: 2026-10-08. Repository: cxjchelsea/AgentRuntime. Reviewed PR #82 exact HEAD `05a2f7f86931845a46ed6d496c37d412fe57c796`; base main `88d3831270c56331af899e74d0c595ba1793d69d`.

**Decision: AUTHORIZE_SLICE_A_ONLY (bounded).** This authorizes development of deterministic non-affirmative Admission / Identity / Provenance internals and targeted tests **only**. It is not implementation completion, gate passage, Slice B authorization or a merge decision.

## 1. Authority and precedence

Authoritative public schemas remain actual `runtime/contracts/` and `runtime/interfaces/validation.py`. IU1 design basis: `M6-IU1 Unit Spec V0.1`, `M6-IU1 Targeted Design Remediation and Agent Loop Alignment V0.2`, `M6-IU1 Second Targeted Design Remediation V0.3`, `M6-IU1 Aggregate Contract and Implementation Readiness Review V1.0`; CA-M6-IU1-06 Producer/Orchestrator reviews clarify that profile grant is a **separate blocked dependency**. New design-only DTO names do not change Canonical. Preserve source contracts and current M4/M5 behavior.

The present public `ResultValidator.validate(execution_result, runtime_context, approved_action_plan) -> ValidatedResult` (3 args) remains unchanged. `ValidatedResult` v1.0.0 fields including `validation_id, execution_id, request_id, validation_status, business_status, claim_policy` remain unchanged. Slice A must not fabricate a canonical result for REJECTED inbound. If a restricted NoGrant compatibility projector is implemented, only if it is independently within Slice A existing validated-contract limitations; no domain-positive claims, and do not bypass required fields.

## 2. Exact authorized scope

**A1 — Typed admission and immutable input snapshot.**
- Internal `ValidationAdmissionDecision` ADMITTED / REJECTED; accepted envelope and empty reasons on ADMITTED, no accepted envelope and explicit nonempty typed reason(s) on REJECTED.
- `ValidationInputEnvelope` as a defensive immutable internal snapshot of M5 ExecutionResult, approved M4 plan, RuntimeContext and frozen public policy snapshot; no late dynamic Registry selection, no mutation of source objects.
- Contract-error diagnostics must never silently coerce identities, normalize away ambiguity, or create missing IDs.

**A2 — Identity/correlation guard.**
- Exact equality of `request_id`, `plan_id` between M5/M4 and trusted Runtime context; `identity_scope` consistency with `RuntimeContext.identity_context.identity_scope`; `session_id` must come from `RuntimeContext.session_context.session_id` / authenticated current request, not domain `elder_id` or guessed user_scope.
- Step, Tool invocation, call/attempt IDs and allowed owner correlation only when present in actual frozen input structures; double ownership, duplicate IDs or unknown references REJECTED/typed unresolved per the IU1 contracts. No fabricated timestamps/identifiers.
- Verify approved `policy_snapshot` source identity and structural consistency without reassessing policy or M4 approvals.

**A3 — Read-only provenance references and deterministic canonicalization.**
- Project exact source paths and exact M5 evidence identifiers as `EvidenceReference`, preserving observed_at only when present; absent observed_at stays absent or explicitly unknown. Do not assert evidence trust, business completion or fresh observation.
- Deterministic canonical digest/ref identity from unchanged input; same input yields same refs/reasons/digest (trace event wall clocks exempt), including nested immutable data. Explicit missing/ambiguous policy/rule/profile reason codes may be included as **UNRESOLVED**, but not as authorized RuleBinding.

**A4 — Tests.** Include unit negative cases and pure adapter tests against current production contracts; maintain M0/M2/M4/M5 regression expectations; additional tests must not mock evidence to imply actual success.

### Authorized file inventory (new private names conditional on repository shape)
- New internal M6 admission / guard / snapshot / evidence-reference modules under `runtime/validation/` or a narrowly named `runtime/validation_i u1/` package with Python-legal name chosen at implementation; avoid introducing a parallel Runtime layer.
- New `tests/test_m6_iu1_admission.py`, `tests/test_m6_iu1_identity.py`, `tests/test_m6_iu1_provenance.py`, or equivalent exact-scope tests.
- Minimal imports/package exports only if needed. No semantic edits to public canonical models or frozen M4/M5 owners.

## 3. Explicitly NOT authorized

- **Slice B**: M2 ProfileIntent producer, same-evaluation authorization receipt, trusted composer/factory, positive Profile Grant, runtime/orchestrator grant handoff and per-turn grant-aware success processing. `D-M6-IU1-01 = OPEN`.
- **Slice C / IU2–IU8**: ToolSuccess→GoalSuccess, evidence trust/freshness decisions, VerifiedFact promotion, BusinessStatus.SUCCESS, positive ClaimPolicy authorization, M7/M8 response or state mutation, durable proof store, replay authority, Agent Loop feedback/replan.
- No changes to `runtime/contracts/policy.py`, `planning.py`, `validation.py`, `runtime/interfaces/validation.py`, `runtime/planning/policy_approval.py`, `runtime/policy_enforcement/rechecker.py`, M5 execution engine, or the `RuntimeOrchestrator.run / M2RuntimeOrchestrator.run` stage topology.
- No dependency on a working grant provider; RuleBinding absent/ambiguous = UNRESOLVED with no success claim.

## 4. Verification checklist and pass conditions

| Gate | Required evidence |
|---|---|
| SA-01 | valid M5/M4/Context yields ADMITTED, immutable envelope, no facts/claims |
| SA-02 | wrong plan/request/identity_scope/session => REJECTED with nonempty reasons, no envelope |
| SA-03 | duplicate Step, Tool/Call ownership, mismatched source refs => REJECTED or typed unresolved per contract |
| SA-04 | missing pinned Rule/Profile returns UNRESOLVED, never Registry latest/success |
| SA-05 | original nested inputs and snapshot unchanged; deterministic digest/reference IDs |
| SA-06 | missing observed_at remains unknown; no fabricated timestamps |
| SA-07 | M5 Tool SUCCESS or plan SUCCESS is NOT automatically VerifiedFact, Goal SUCCESS, or Business SUCCESS |
| SA-08 | no external Tool/Skill invocation, M2/M4 recheck, state/memory mutation or Agent Loop |
| SA-09 | Canonical `ValidatedResult` unchanged and malformed Admission cannot create a canonical success |
| SA-10 | tests cover M0/M2/M4/M5 frozen behavior; 4 project gates green on implementation HEAD |

Run: `python -m pytest tests -q`; `python -m mypy runtime tests`; `python -m ruff check runtime tests`; `python -m ruff format --check runtime tests`. No tests were executed by this authorization decision; no PASS claimed.

## 5. Development execution and next gate

1. Implement A1 admission DTO/error taxonomy and identity checks in a **new work branch or tightly scoped PR** originating from a known main baseline; do not mix this bounded implementation with design-only PR #82 and unresolved grant proposals.
2. Add A2 and A3 read-only envelope/ref projector, then targeted tests and full gates. Review exact committed HEAD independently; any scope expansion requires explicit controlled amendment.
3. Perform `M6-IU1 Slice A Independent Implementation Review` and then `Slice A Verification Closure` only after actual code+four gates. This decision expires for a changed canonical/public interface until reevaluated.
4. Continue D-M6-IU1-01 separately; it does not block Slice A but continues to block Slice B.

```text
M6-IU1 SLICE A BOUNDED IMPLEMENTATION AUTHORIZATION = AUTHORIZE_SLICE_A_ONLY
M6-IU1 SLICE A IMPLEMENTATION STATUS = NOT_STARTED / NOT VERIFIED
M6-IU1 SLICE B AUTHORIZATION = NOT_GRANTED
D-M6-IU1-01 = OPEN
M6-IU1 WHOLE-UNIT IMPLEMENTATION AUTHORIZATION = NOT_GRANTED
M6-IU1 PR #82 MERGE AUTHORIZATION = NOT_GRANTED
NEXT = M6-IU1 Slice A Formal Implementation (Admission / Identity / Provenance)
```
