# M6-IU1 Slice B1a — Validation Identity + NoGrant Mapping Controlled Design V0.1

Date: 2026-10-08. Design only. Implemented reference `main@3ce861e59a322f5a5fc5906da5d6e6654b7e8087` (Slice A + B0 merged). Design predecessor PR #82 `3eb6114d4672925cedd4325bc1f0139bef63f294`. No code/implementation authorization.

## 1. Purpose, boundaries, authority

**B1a is a pure, internal, nonaffirmative projector.** Input: already-admitted exact Slice A envelope plus observed ExecutionResult and a consumed B0 NoGrant; output: canonical-**shaped, nonauthorizing** `ValidatedResult` suitable for contract testing, never a success certificate. B1a must not call M7/M8, register profile authority, replace runtime validator, or modify M2/M4/M5/Orchestrator/public contracts.

Separate roles:
- **Trusted invocation context owner (future B2 composition):** provides authentic current request_id/session_id/identity_scope and allocates one invocation-scoped validation identity.
- **Slice A:** checks exact plan/request/scope/session/Step/Tool structure, constructs immutable fingerprint. ADMITTED and corresponding envelope required.
- **B0:** emits only immutable NoGrant; no positive grant.
- **B1a:** binds IDs to admitted source and creates an UNKNOWN result with no verified facts/goals/claims; no profile interpretation.
- **B1b/B2:** must enforce downstream no-claim semantics and trusted orchestration handoff. Not authorized in B1a.

## 2. Exact contracts

### 2.1 ValidationInvocationIdentityV1 — internal frozen DTO

```text
validation_id: str           # opaque nonempty unique correlation ID allocated by trusted owner
request_id: str
execution_id: str
plan_id: str
session_id: str
identity_scope: str
admission_fingerprint: str   # exact Slice A envelope fingerprint
invocation_scope_id: str     # internal unique per-call identity; no issuer proof
```

All required and strict strings; reject empty, whitespace-only, wrong type. The public `ValidatedResult.validation_id` is an invocation correlation token, NOT authorization, proof of validation, or business truth. **Single allocation authority is the reviewed validation invocation factory**: local secure-random opaque ID per new validation attempt (such as UUID4), with the allocation event bound to request/session/scope/plan/execution and Slice A fingerprint. No caller-supplied user/Domain/Tool `validation_id`; if the factory cannot demonstrate controlled provenance, it returns an internal error and no public result. Repeated invocation against same ExecutionResult produces a new validation_id, not a retroactively attested result. Replay of a previously bound invocation requires its original frozen context/identity; lost identity => new invocation with a new ID and NoGrant only, never positive reuse. UUID uniqueness is probabilistic; implement tests for injected collision/conflicting registration if an ID allocator is reused, without claiming durable global collision prevention in B1a.

**Trusted boundary:** B1a can validate equality of provided fields but cannot authenticate them. B2 must supply expected request/session from validated RuntimeInput, not derive expectations from the very payload it checks. Internal factory must be injected or otherwise explicitly created by a trusted composition path; test fixture values do not prove production authority.

### 2.2 Exact input join / fail-closed

Proposed internal projector:
```python
def project_no_grant_result(
    *,
    admission: ValidationAdmissionDecision,
    execution: ExecutionResult,
    approved: ApprovedActionPlan,
    context: RuntimeContext,
    no_grant: NoGrant,
    identity: ValidationInvocationIdentityV1,
) -> ValidatedResult: ...
```

Only permit:
1. `admission.status == ADMITTED`, no reasons, non-null envelope. Never recover an envelope from rejected admission.
2. `no_grant` is an actual `NoGrant` instance, not string/dict/pseudo-VerifiedGrant.
3. `identity` matches execution.request_id/execution_id/plan_id, approved.request_id/plan_id, context.session_context.session_id and identity_context.identity_scope; also exact admission fingerprint. Empty source identifiers REJECTED.
4. To avoid a stale envelope being rebound to a changed ExecutionResult/Plan/Context, recompute **the exact Slice A serialization and digest through an approved public helper or repeat `admit_validation_input` with trusted expected values**; equality of fingerprint alone from an untrusted caller is insufficient. Pure B1a must not create a second inconsistent canonicalization scheme. Preserve RuleBinding `UNRESOLVED` only; no Registry lookup.
5. If any required join, source fingerprint, request/session, type or NoGrant invariant fails, raise a **typed internal projection error**. Never fabricate mandatory public result fields.

B1a should expose a narrow `NoGrantProjectionError` taxonomy (`ADMISSION_REJECTED`, `IDENTITY_MISMATCH`, `SOURCE_CHANGED`, `NO_GRANT_INVALID`, `VALIDATION_ID_INVALID`). Exceptions remain inside B1a pending B2 error routing.

### 2.3 Canonical mapping

Exact current public types: `ValidatedResult` has mandatory `validation_id, execution_id, request_id, validation_status, business_status, claim_policy`; `ClaimPolicy` requires `allowed_claims`, `forbidden_claims`.

```python
ValidatedResult(
    validation_id=identity.validation_id,
    execution_id=execution.execution_id,
    request_id=execution.request_id,
    validation_status=ValidationStatus.UNKNOWN,
    business_status=BusinessStatus.UNKNOWN,
    claim_policy=ClaimPolicy(
        allowed_claims=[],
        forbidden_claims=[],
        conditional_claims=[],
        required_qualifiers=["No authorized validation profile; no positive claims"],
        certainty_level=None,
    ),
    goal_validation=None,
    verified_facts=None,
    unverified_facts=None,
    conflicting_facts=None,
    followup=None,
    state_recommendation=None,
    validation_errors=[{"code": "GRANT_MISSING", "reason": no_grant.reason.value}],
    quality=None,
)
```

**Forbidden claims empty does not authorize claims.** It means no enumerated positive/negative claim vocabulary was resolved. A non-affirmative `ValidatedResult` alone is NOT a downstream security barrier. NoGrant guarantee stops at this pure projector until B1b/B2/M7/M8 independently prove the consumer gate. Never label this result `VALIDATED`, `SUCCESS`, `FAILED`, or present UNKNOWN as medically/business-confirmed failure. No GoalSuccess/VerifiedFact generation. No state recommendation or external Tool call.

## 3. Controlled implementation inventory (candidate only)

- NEW `runtime/validation/no_grant_projection.py`: strict internal invocation identity value, typed errors, pure source join/projector.
- NEW `tests/test_m6_iu1_slice_b1a_no_grant_projection.py`: exact-contract fixtures, failure cases and all mandatory oracles.
- OPTIONAL NEW `runtime/validation/validation_identity.py`: isolated validation ID allocation/binding factory if a single module would mix concerns. Must remain local and pure except an approved secure-random ID generation mechanism; no persistent records. Avoid test-supplied predictable IDs in production factories.
- Any exposure of shared Slice A normalization as a public helper requires an explicit scope check; do not modify `runtime/validation/slice_a.py` in the same implementation without targeted amendment.
- FORBIDDEN: edits to `runtime/contracts/**`, `runtime/interfaces/validation.py`, `runtime/orchestration/**`, M2/M4/M5, M7/M8, persistent state, external Registry, profile issuer or third-party Tool adapters.

## 4. Negative/positive contract oracles

| Gate | Fixture | Expected |
|---|---|---|
| B1a-01 | valid Slice A admission + typed NoGrant + trusted bound identity | Canonical ValidatedResult with UNKNOWN/UNKNOWN, none of goals/verified facts/claims |
| B1a-02 | rejected admission / absent envelope | typed error; no result |
| B1a-03 | wrong request, plan, session, identity_scope, execution_id | typed mismatch; no result |
| B1a-04 | reused/stale admission after mutation to ExecutionResult/ApprovedPlan/Context | source mismatch; no result |
| B1a-05 | forged NoGrant dict/string or pseudo positive grant | rejected |
| B1a-06 | empty/whitespace/non-string validation_id or caller-provided fake production authority | rejected |
| B1a-07 | different new invocation identity for same execution | distinct validation_id; both non-affirmative |
| B1a-08 | original replay context missing or conflicting | rejected / new NoGrant invocation only; no recovery success |
| B1a-09 | NoGrant enum reasons / missing Profile / tool status SUCCESS | UNKNOWN/UNKNOWN; no inferred business state |
| B1a-10 | zero calls to Tool, StateMemoryUpdater, ResponseGenerator, PolicyEngine or live Registry | verified absence / pure design |
| B1a-11 | current Canonical model exact schema + round-trip | pass |
| B1a-12 | full pytest + mypy + ruff check + ruff format on exact implementation HEAD | actual logs; no design-only PASS |

B1a does **not** test downstream claim enforcement beyond ensuring its own output has no allowed claims. That remains B1b/B2 entry gate.

## 5. Gate decisions and unresolved dependencies

```text
M6-IU1 B1a CONTROLLED DESIGN = SUBMITTED_FOR_INDEPENDENT_REVIEW
B1-RG-01 IDENTITY CONTRACT = DEFINED / TRUSTED_FACTORY_IMPLEMENTATION_PENDING
B1-RG-02 NOGRANT CANONICAL MAPPING = DEFINED / TESTS_PENDING
B1-RG-03 DOWNSTREAM CLAIM GUARD = DEFERRED_TO_B1b_B2 (NOT SATISFIED)
B1-RG-04 TRUSTED RUNTIME INPUT ORIGIN = DEFERRED_TO_B2
B1a FORMAL IMPLEMENTATION AUTHORIZATION = NOT_GRANTED
B1b/B2 = NOT_AUTHORIZED
D-M6-IU1-01 = OPEN / POSITIVE_GRANT_BLOCKED
NEXT = M6-IU1 Slice B1a Independent Controlled Design Review
```
