# M6-IU1 Slice B1a — Minimal Contract Precision Amendment V0.3

**Scope:** Only R-B1a-06, R-B1a-07, R-B1a-08. **Status:** design amendment submitted, NOT implementation authorization. **Design parent:** PR #82 at `2fbb3eb952801fd1efdc92d1b5f46873a4917d46`. **Code base:** `main@3ce861e59a322f5a5fc5906da5d6e6654b7e8087`. V0.1 and V0.2 remain applicable except where superseded here.

## 1. R-B1a-06 — identity allocation lifetime and collision authority (CLOSED IN DESIGN)

### Chosen option: bounded **controller-instance-local** uniqueness

A single `NoGrantProjectionController` owns a private `seen_validation_ids: set[str]` for its **explicit instance lifetime**. This is an internal unit-of-work object; it is never a global registry, credential signer, distributed idempotency ledger or shared production singleton. Its only projection method allocates an opaque validation correlation ID using a private UUID4 generator by default, with an injected `ValidationIdAllocator` permitted **only to internal test/composition code**. A plain stateless global function cannot promise cross-call collision checks and is not the canonical B1a entrypoint.

```python
class NoGrantProjectionController:
    def __init__(self, *, id_allocator: ValidationIdAllocator | None = None) -> None: ...
    def project(
        self, *, admission: ValidationAdmissionDecision,
        execution: ExecutionResult, approved: ApprovedActionPlan,
        context: RuntimeContext, origin: ValidationOriginBinding,
        no_grant: NoGrant,
    ) -> ValidatedResult: ...
```

- Controller lifecycle is created and owned by a reviewed trusted orchestration/composition caller (B2). B1a tests instantiate and retain one controller for two or more sequential projections to assert duplicate detection.
- Identity issuance is **last** after all argument/admission/snapshot checks, immediately before canonical construction. An ID must be a strict nonempty string with no leading/trailing whitespace (reject, do not coerce/strip), not a pre-supplied caller value.
- If allocation throws, returns non-string/blank, or returns an ID already used by **the same controller**, fail via typed `VALIDATION_ID_INVALID` / `VALIDATION_ID_COLLISION`; never return partial result.
- Insert the newly allocated ID into the controller-local used set **before** constructing the result. If construction raises, the ID remains spent; never reuse on retry.
- Two successfully projected calls through the same retained controller must carry distinct IDs. Separate controller instances, processes or recovered runtimes have no shared dedup authority; UUID4 only provides probabilistic uniqueness. Never assert global/cross-process/exact-once uniqueness.
- This object has no mutation beyond its private ID bookkeeping and does not retain source input, profile grant, response or business state. B2 must avoid using one controller across unrelated turns to imply shared trusted context; sharing across threads is **not** guaranteed safe. Tests should scope sequential same-instance collision, not multithread atomic uniqueness.
- Validation ID is a correlation identifier, never validation success or authorized Profile proof. The optional test allocator cannot enter public `ResultValidator` ABI, Domain/Tool interfaces or application inputs.

## 2. R-B1a-07 — deterministic validation and failure precedence (CLOSED IN DESIGN)

Formal single-call order:

| Rank | Guard | Fail-closed result |
|---|---|---|
| 1 | Exact runtime argument types for admission, execution, approved, context, origin, no_grant; required origin strings and literal `STRUCTURAL_ONLY` | `INVALID_INPUT` / `ORIGIN_INVALID` / `NO_GRANT_INVALID` |
| 2 | Original admission has `status=ADMITTED`, `reasons=()`, nonnull frozen envelope and binding `UNRESOLVED` | `ADMISSION_REJECTED` / `ADMISSION_INVALID` |
| 3 | Structural equality: expected request/session/scope vs execution/approved/context; nonempty source identifiers | `IDENTITY_MISMATCH` |
| 4 | Repeat existing Slice A `admit_validation_input` using origin expected request/session; require ADMITTED and envelope, no errors | `RECHECK_REJECTED` |
| 5 | Compare *entire* repeated `ValidationInputEnvelope` to original and require `rule_binding_status=UNRESOLVED` | `SOURCE_CHANGED` / `ADMISSION_INVALID` |
| 6 | Recheck NoGrant enum validity; invariant only, never assert slot provenance | `NO_GRANT_INVALID` |
| 7 | Allocate + reserve validation ID using the controller-private allocator/seen set | `VALIDATION_ID_INVALID` / `VALIDATION_ID_COLLISION` |
| 8 | Construct only UNKNOWN/UNKNOWN canonical result, zero positive claims, facts, goals or state recommendations | internal typed `PROJECTION_FAILED` on canonical construction failure |

No allocation or exposed result on failure in ranks 1–6. If ranks 7–8 fail, no result returned; any allocated ID stays spent. All errors are typed `NoGrantProjectionError` with stable enum-like reason codes; avoid leaking raw exceptions or producing a made-up success/UNKNOWN result to mask structural rejection. When original admission is REJECTED, **ADMISSION_REJECTED takes precedence over readmission**; never evaluate potentially malformed source payload before rejecting original admission. A null/non-instance admission produces `INVALID_INPUT`, not an AttributeError. The first failing rank wins and must be tested.

B1a error handling remains internal; B2 determines the future runtime failure route. No M7/M8 handoff, Tool call, policy reevaluation or update occurs in B1a.

## 3. R-B1a-08 — terminology and trust semantics (CLOSED IN DESIGN)

**Canonical name only:** `ValidationOriginBinding`. Required fields `expected_request_id`, `expected_session_id`, `expected_identity_scope`, and literal `trust_level="STRUCTURAL_ONLY"`. It is a structural expectation container and **not** a verified caller identity, authentication token, source proof or positive validation grant.

- The older V0.2 narrative phrase `TrustedOriginBinding` is **deprecated**, even as a test fixture alias. Tests and future implementation must use only `ValidationOriginBinding`.
- An instance assembled from user-provided matching fields may pass B1a *structural* checks; B1a must never report it as originating from a trusted runtime caller.
- Genuine expected values, original Slice A admission call order and downstream fail-closed claim handling remain separately owned by **B2 / B1b**, not B1a.
- Do not add a `TRUSTED` trust level or promote `STRUCTURAL_ONLY`. Structural equality and digest equality are not authenticity certificates.

## 4. Amendment verification oracles

| ID | Oracle |
|---|---|
| R06-01 | Two calls to the **same** retained controller with injected duplicate IDs: second fails `VALIDATION_ID_COLLISION`; first output unchanged |
| R06-02 | Distinct valid IDs in one controller: both are UNKNOWN/UNKNOWN |
| R06-03 | Separate controllers do **not** claim shared collision state; never present a cross-process guarantee |
| R06-04 | allocator blank/nonstring/raised exception: typed error and no result; reserved ID not reused after projection-construction failure |
| R07-01 | original REJECTED admission => ADMISSION_REJECTED before re-admission or ID allocation |
| R07-02 | null/wrong-type admission/origin/no_grant => stable typed error, not unhandled attribute error |
| R07-03 | mismatched request/session/scope or stale snapshot => typed error with **zero ID allocations** |
| R07-04 | source-admitted but malformed NoGrant marker => no positive result |
| R08-01 | `ValidationOriginBinding` is the only origin type; `STRUCTURAL_ONLY` preserved |
| R08-02 | fully self-consistent malicious origin/source remains **outside** B1a authenticity coverage, not a passing trust oracle |
| BASE | Canonical `ValidatedResult` UNKNOWN/UNKNOWN, `allowed_claims=[]`, no verified facts, goals, positive state or downstream consumption |
| GATES | New implementation must separately pass exact-HEAD pytest, mypy, ruff check and ruff format plus independent review |

## 5. Frozen delta and decision

- Supersedes V0.2's ambiguous stateless project function and optional collision state: **controller instance is the owner and collision scope**.
- Supersedes `TrustedOriginBinding` string everywhere: use `ValidationOriginBinding` only.
- Fixes strict evaluation precedence and allocator-spend lifecycle.
- Unchanged: Slice A repeat admission + full envelope equality; B0 NoGrant is not a consumption attestation; UNKNOWN/UNKNOWN no-positive-claim mapping; no public ABI changes; B1a **cannot prove production trusted origin or downstream claim denial**.

```text
R-B1a-06 = DESIGN_REMEDIATED (CONTROLLER-INSTANCE LOCAL COLLISION ONLY)
R-B1a-07 = DESIGN_REMEDIATED (EXPLICIT ERROR PRECEDENCE / NO EARLY ID)
R-B1a-08 = DESIGN_REMEDIATED (ValidationOriginBinding / STRUCTURAL_ONLY)
B1a MINIMAL CONTRACT PRECISION AMENDMENT = SUBMITTED_FOR_REVIEW
B1a IMPLEMENTATION AUTHORIZATION = NOT_GRANTED
B1b / B2 = NOT_AUTHORIZED
D-M6-IU1-01 = OPEN
NEXT = M6-IU1 Slice B1a Bounded Implementation Authorization Review
```
