# M6-IU1 Slice B1a Targeted Controlled Design Remediation V0.2

**Status:** Controlled design amendment, submitted for targeted independent re-review; **NOT implementation authorization**. Date 2026-10-08. Predecessor B1a V0.1 at PR #82 `f81ca9c3f8cc84b949d6f70412085de381b06770`. Code baseline `main@3ce861e59a322f5a5fc5906da5d6e6654b7e8087`. Only B-B1a-01/02 and R-B1a-03..05 are amended. Other V0.1 provisions apply except where expressly superseded.

## 0. Decision: a pure projector cannot prove external caller trust

B1a may produce a **structurally canonical, nonaffirmative** `ValidatedResult`, but **no B1a-only test can attest production provenance of an inbound RuntimeInput** or enforce downstream no-positive-claim rules. Such assertions remain B2/B1b gates. There must be no fallback that simply treats caller-provided matching strings as trusted. Separate (1) structurally validated join and (2) production provenance. Every B1a output is a NoGrant/UNKNOWN candidate and is not authorized for runtime deployment.

## 1. B-B1a-01 — Origin-bound admission, no circular trust

### 1.1 Formal source-of-truth chain

```text
Future trusted B2 RuntimeInput owner
  -> trusted expected_request_id / expected_session_id / expected_identity_scope
  -> Slice A admit_validation_input(execution, context, approved, expected_request_id=..., expected_session_id=...)
  -> frozen ADMITTED envelope + exact fingerprint
  -> B1a pure projector (recheck exact original admission fingerprint)
```

B1a does **not** create those trusted expected IDs or claim to authenticate them. For component tests, a separately constructed `TrustedOriginBinding` *test fixture* is only structural simulation. Production B2 must supply a trusted caller-origin binding from independently validated RuntimeInput, not copy expected IDs from ExecutionResult or the proposed ValidationInvocationIdentity.

### 1.2 Contract update

```python
@dataclass(frozen=True, slots=True)
class ValidationOriginBinding:
    expected_request_id: str
    expected_session_id: str
    expected_identity_scope: str
    # absence of a provenance witness is explicit:
    trust_level: Literal["STRUCTURAL_ONLY"] = "STRUCTURAL_ONLY"
```

The type name is an **origin expectation**, not a credential. The fixed tag `STRUCTURAL_ONLY` intentionally prevents B1a from asserting `TRUSTED`. B1a validates that all nonempty strict fields match execution, plan, context and identity. B2 needs its own trusted injection/attestation mechanism and cannot promote this marker to validated production trust.

Original Slice A invocation must have been performed with the same expected request/session from the authoritative B2 owner. Since Slice A `ValidationAdmissionDecision` **does not retain the expected inputs or their origin**, B1a cannot cryptographically prove that relation: it recomputes admission and compares the exact frozen envelope; this establishes *snapshot equality*, not *authentic origin*. B2's composition/origin invariant remains mandatory.

**Fail closed:** missing/malformed origin binding, difference among origins, execution, plan, context, and current identities, or a rejected repeat admission => typed error, no result. In B1a tests, a self-consistent forged entire origin+payload may remain structurally admitted; document it as `NOT_APPLICABLE_IN_B1a`, never as a passing security proof.

## 2. B-B1a-02 — Validation ID owner, allocation/consumption

**Chosen design: single sealed internal operation, not a caller-constructed identity DTO accepted as authority.** Remove V0.1's public projector parameter `identity: ValidationInvocationIdentityV1`. A new invocation controller internally allocates a fresh `validation_id` and `invocation_scope_id` per attempt with secure-random UUID4 or injected allocator for deterministic isolated unit tests. The factory/controller immediately binds an immutable private identity to the origin fields, execution ID, plan ID and admission fingerprint **inside the same operation**, invokes the projector, and returns the resulting `ValidatedResult` (or typed failure).

```python
def project_no_grant_result(
    *,
    admission: ValidationAdmissionDecision,
    execution: ExecutionResult,
    approved: ApprovedActionPlan,
    context: RuntimeContext,
    origin: ValidationOriginBinding,   # structural checks only; future B2 trust root
    no_grant: NoGrant,                  # nonaffirmative marker, NOT consumption proof
    id_allocator: ValidationIdAllocator | None = None,  # trusted internal factory port
) -> ValidatedResult: ...
```

`id_allocator` is internal-only and must not be injectable through Domain/Tool/public ResultValidator; default production creation is a local private secure random allocator. Tests may pass a deterministic allocator, but such a value is never a production authority certificate. Two IDs distinguish **result correlation** vs **internal invocation tracking**; neither is an issuer proof. If the internal scope_id is not consumed by the actual projector state, omit it in implementation rather than adding a decorative field.

Order is frozen:
1. Verify argument types, admission ADMITTED and origin/identity snapshot join.
2. Re-run Slice A exact canonicalization and compare original fingerprint/source snapshots.
3. Verify `NoGrant` typing and static nonaffirmative mapping.
4. Allocate one validation ID only after prechecks; validate nonempty/strict ID and collision with IDs already minted **within this controller's declared lifetime**, if the controller retains such a local set. No global uniqueness/durable collision guarantee; do not misrepresent UUID4 probability as formal proof.
5. Construct `ValidatedResult` once and return; on failure do not return a partially formed result. There is no external retry/commit. A second independent call allocates a fresh ID and returns another NoGrant UNKNOWN candidate; **B1a does not implement idempotency or authorized replay**.
6. If allocation fails, typed error; no result. If no durable ID ledger exists, explicitly label collision detection **LOCAL_ONLY / NOT_CROSS_PROCESS** and defer distributed replay safety to B2/Runtime.

Invocation controller owns the transient lifecycle; there is no externally accepted identity DTO/token and thus no caller-forged approval capability. This is API-surface confinement, **not security against hostile Python code running in the same process**.

## 3. R-B1a-03 — B0 NoGrant provenance: precise, weak claim

Current B0 `NoGrant(reason)` is directly constructible and `NoGrantTurnSlot.take_once()` returns the exact same value class. **Do not assert that typing proves slot origin or once-only consumption.** The B1a projector checks only `isinstance(no_grant, NoGrant)` and valid typed reason; its output is permanently UNKNOWN/UNKNOWN regardless of whether the marker was freshly constructed or slot-produced.

The B0 once-only lifecycle is enforced by B0's slot **at the producing site**; its integration/close/finally behavior belongs to B2. A pseudo-positive receipt/dict is rejected; a freely constructed genuine NoGrant is permitted but cannot grant any positive state. Tests must check both. Never add fake certificate fields or mutate B0.

## 4. R-B1a-04 — One digest authority: Slice A

Choose the **existing public pure `admit_validation_input(...)` function**, not copied serializers or a new hashing implementation. On each B1a invocation:

```python
rechecked = admit_validation_input(
    execution, context, approved,
    expected_request_id=origin.expected_request_id,
    expected_session_id=origin.expected_session_id,
)
if rechecked.status != AdmissionStatus.ADMITTED or rechecked.envelope is None:
    raise NoGrantProjectionError(RECHECK_REJECTED)
if admission.status != AdmissionStatus.ADMITTED or admission.envelope is None:
    raise NoGrantProjectionError(ADMISSION_REJECTED)
if rechecked.envelope != admission.envelope:  # compares ALL frozen bytes + fingerprint + refs
    raise NoGrantProjectionError(SOURCE_CHANGED)
```

Also explicitly match `origin.expected_identity_scope` to both execution and context, because Slice A only compares scope *between* those two. Reject `rule_binding_status != "UNRESOLVED"` under this NoGrant-only design; never claim a resolved grant. Compare full `ValidationInputEnvelope`, not just digest; collision-resistant digest is not an authenticity oracle. B1a introduces no second digest/serializer.

Immutable `ValidationInputEnvelope` dataclass contains immutable strings and tuple of frozen refs. Mutable source models are reserialized at projection time by Slice A; later source mutation causes mismatch. A fresh admission computed from the same modified objects could be self-consistent, but **the input-original admission must originate from the earlier authorized step**; B2 attests call order and ownership.

## 5. R-B1a-05 — Canonical claim mapping and evidence oracles

The only constructed output follows V0.1 mapping:
- `validation_status=ValidationStatus.UNKNOWN` and `business_status=BusinessStatus.UNKNOWN` even if `execution.plan_status` or Tool output suggests SUCCESS.
- `ClaimPolicy.allowed_claims=[]`, `conditional_claims=[]`. `forbidden_claims=[]` is **not** deny-all; `required_qualifiers` is explanatory metadata, **not enforcement**.
- `goal_validation=None`, `verified_facts=None`, `unverified_facts=None`, `conflicting_facts=None`, `followup=None`, `state_recommendation=None`.
- `validation_errors=[{"code":"GRANT_MISSING","reason":no_grant.reason.value}]`; never overwrite with success.
- No response generation, State/Memory mutation, Tool invocation, registry lookup or policy reevaluation.
- On error, typed `NoGrantProjectionError` with stable reason and no `ValidatedResult`; never set UNKNOWN in lieu of a failed structural admission.

### Binding and negative oracle matrix

| ID | Input | Mandatory oracle |
|---|---|---|
| B1a-01 | original ADMITTED + origin matched + NoGrant | ValidatedResult UNKNOWN/UNKNOWN; zero positive claims |
| B1a-02 | initial REJECTED / missing envelope | typed ADMISSION_REJECTED |
| B1a-03 | wrong request, plan, session, scope, execution ID | typed IDENTITY_MISMATCH/RECHECK_REJECTED |
| B1a-04 | original admission + source fields modified afterwards | typed SOURCE_CHANGED |
| B1a-05 | fake positive/dict NoGrant | typed NO_GRANT_INVALID |
| B1a-06 | directly constructed valid NoGrant | still UNKNOWN/UNKNOWN; **not** a positive or a consumption proof |
| B1a-07 | id allocator returns blank/nonstring/repeated locally within declared controller lifetime | typed VALIDATION_ID_INVALID/COLLISION; no result |
| B1a-08 | 2 separate invocations, same execution | two nonaffirmative results with distinct IDs; no replay authorization |
| B1a-09 | source plan/Tool signals SUCCESS | must remain UNKNOWN/UNKNOWN; zero verified goals/facts |
| B1a-10 | missing/forged origin that disagrees with source | typed failure; fully self-consistent forgery is explicitly outside B1a structural proof |
| B1a-11 | envelope has fabricated RESOLVED binding | fail; no Profile grant resolution |
| B1a-12 | field-for-field canonical serialization round trip | `ValidatedResult.model_validate(...)` same UNKNOWN result |
| B1a-13 | component source import and monkeypatch fakes | never invokes Tool/M7/M8/Registry or state updates |
| B1a-14 | exact-HEAD four gates | pytest/mypy/ruff/format real execution before B1a closure |

**Implementation budget:** new `runtime/validation/no_grant_projection.py`, optional new internal `runtime/validation/validation_identity.py`, one new test module. No modifications to `runtime/validation/slice_a.py`, `runtime/validation/no_grant.py`, existing public interfaces, orchestration or domain modules without a new targeted amendment.

## 6. Re-review gate and explicit unsettled obligations

```text
B-B1a-01 = DESIGN_REMEDIATED (STRUCTURAL B1a ONLY; TRUSTED B2 ORIGIN OPEN)
B-B1a-02 = DESIGN_REMEDIATED (SEALED PER-CALL FACTORY; DISTRIBUTED REPLAY OUT_OF_SCOPE)
R-B1a-03 = DESIGN_REMEDIATED (NO GRANT ORIGIN PROOF CLAIM)
R-B1a-04 = DESIGN_REMEDIATED (SLICE A READMISSION + FULL ENVELOPE EQUALITY)
R-B1a-05 = DESIGN_REMEDIATED (UNKNOWN/UNKNOWN + DENY POSITIVE CLAIM ASSERTIONS)
B1a CONTROLLED DESIGN = SUBMITTED_FOR_TARGETED_INDEPENDENT_RE_REVIEW
B1a IMPLEMENTATION AUTHORIZATION = NOT_GRANTED
B1b/B2 = NOT_AUTHORIZED
D-M6-IU1-01 = OPEN
NEXT = M6-IU1 Slice B1a Targeted Independent Controlled Design Re-Review
```

The original B1a V0.1 proposal to accept an externally assembled `ValidationInvocationIdentityV1` is **superseded**. Neither this amendment nor B1a's test fixtures satisfy trusted production origin or downstream no-claim enforcement.
