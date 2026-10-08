# CA-M6-IU1-06 Targeted Physical Design Remediation V1.1

Date: 2026-10-08. PR #82 exact previous HEAD `71eade1ffa473b6a863929ff1669d76e0741ccac`; baseline `main@88d3831270c56331af899e74d0c595ba1793d69d`.
Status: DESIGN REMEDIATION SUBMITTED; targeted independent physical re-review pending. Supersedes V1.0 only for B-PD-01..03 and R-PD-04..05. No implementation or approval implied.

## 0. Source check and rejected assumption

In `runtime/policy_management/{definitions,rules,engine}.py`, PolicyFragment contains `validation_mode` but no Profile authorization grant, and `PolicyRule.evaluate` returns only PolicyFragment. `DefaultPolicyEngine.evaluate` returns only PolicyDecision. `M2RuntimeOrchestrator._evaluate_integrated_policy` produces PolicyDecision through a RuntimeConstraintEvaluator; it is NOT an independent DefaultPolicyEngine decision. Both base and M2 integrated concrete `run` bodies own the stage sequence. `tests/test_m2_runtime_integration_gate.py` assembles the integrated Orchestrator as a **test composition site**, not proof of production composition authority. No obvious production bootstrap/composition root was identified in the searched repository tree: this is an explicit integration gap rather than evidence that arbitrary injected Profile providers are safe.

## 1. B-PD-01 — Same-evaluation M2 authorization evidence

### Exact internal output contract, distinct from public PolicyDecision
```text
PolicyValidationAuthorizationReceiptV1
  receipt_version = 1
  source_kind = BASE_POLICY_EVALUATION | INTEGRATED_CONSTRAINT_EVALUATION
  source_decision_id: str
  canonical_decision_digest: str
  evaluated_request_id: str
  evaluated_identity_scope: str
  evaluated_session_id: str
  originating_rule_refs: tuple[(rule_id, rule_version, registration_digest)]
  authorized_profiles: tuple[
    (profile_id, profile_version, profile_digest, domain_id,
     allowed_goal_types, allowed_tool_refs, validation_mode_floor)
  ]
  producer_instance_ref: opaque internal identifier
  evaluation_nonce: opaque per-evaluation correlation
```

**Producer rule:** an affirmative receipt MUST be emitted by the very same trusted M2 evaluation invocation that emits the `PolicyDecision`. For base M2 this means a controlled internal `PolicyEvaluationOutcome(decision, authorization_receipt|NoGrant)` adapter inside the DefaultPolicyEngine evaluation boundary, with the public `PolicyEngine.evaluate -> PolicyDecision` left unchanged. For integrated M2, the equivalent receipt must originate inside the **same** `RuntimeConstraintEvaluator.evaluate` invocation that returns the `RuntimeConstraint`, and bind to `constraint.policy_decision`; it is forbidden to call an unrelated DefaultPolicyEngine to mint it.

The existing M2 rule interface currently cannot emit a grant. Introduce an opt-in, explicitly approved M2-owned **ProfileAuthorizationPolicyRule** (separate from current generic PolicyFragment) registered by the trusted composition entry. It must evaluate in the same M2 decision transaction and give exact permitted profile refs/scope. Until a controlled implementation proves such association, receipt is `NoGrant(NO_M2_AUTHORIZED_PROFILE_EVIDENCE)`. Do not transform free-text flags, `validation_mode`, or Registry contents into a receipt. Authorized profile references are assertions of policy authority only, never verification of a Goal outcome.

**Single-invocation evidence transport:** a typed return-side internal evaluation receipt / orchestrator-local holder filled exactly once during the same evaluation, checked against its returned decision before any PLAN work. The holder must be private to the coroutine, immutable after emission and not stored on a shared engine, singleton, ContextVar, stage_results or user-controlled dictionary. If an internal evaluation boundary cannot expose evidence safely without a signature modification, keep `NoGrant` and request a separate bounded M2 extension authorization. A fabricated second evaluation does not qualify.

**Conflict/failure:** multiple competing authorized profiles for the same applicability without a deterministic pre-approved precedence => `NoGrant(AMBIGUOUS_PROFILE_AUTHORITY)`. Missing rule registration/version, digest mismatches, or scope gaps => NoGrant. A receipt can only contain profiles contributed by vetted registered ProfileAuthorizationPolicyRule instances and consistent with the final PolicyDecision safety restrictions; none when blocked. No implicit “latest”.

## 2. B-PD-02 — Dual-orchestrator compatibility, NoGrant explicit rollout mode

Choose an **opt-in, fail-closed grant-enforced integration mode**, not silent replacement of the old ResultValidator:
- `LEGACY_UNCHANGED`: when new feature not installed, both existing Orchestrator classes preserve current run path and all existing 15 call points; this mode does **not** claim RuleGrant safety or M6 authorized domain-success functionality. Its behavior is explicitly an existing legacy compatibility baseline, not a production validation security certification.
- `GRANT_GATED`: opt-in only with validated `GrantAwareValidationCore + PerTurnValidatorFactory` and a vetted M2 Evidence Provider. In this mode, missing receipt/intent/approval binding => NoGrant, and the *restricted M6 consumer* returns only schema-valid no-affirmative validation or safe error (never delegates to unvetted legacy Validator). The mode must fail at construction if the gated consumer is missing or unvetted. There is no automatic fallback to legacy success generation.

**Concrete turn checkpoints in BOTH** `runtime/orchestration/runtime.py:RuntimeOrchestrator.run` and `runtime/orchestration/m2_runtime.py:M2RuntimeOrchestrator.run`:
1. Execute existing POLICY with existing error + invariant gates; locally attach only authentic same-evaluation M2 receipt from actual path; do not add a new named stage.
2. Before PLAN, check exact decision digest + request/session/scope; capture immutable ProfileIntent or NoGrant.
3. Execute existing PLAN/PLAN_VALIDATE/POLICY_RECHECK and all request, priority, preemption checks in original order.
4. AFTER successful approval, narrow authorized Goal types/Tool refs to exact approved plan; verify original `approved.policy_snapshot == policy_decision.model_dump(mode="json")`; do not mutate ApprovedPlan.
5. Execute M5 with exact original Plan; no Tool, Retry, Lock, Checkpoint, Recovery changes.
6. Verify ExecutionResult identity; obtain locally scoped `VerifiedGrant|NoGrant`; create one PerTurnResultValidator. Invoke existing `RESULT_VALIDATE` with its original three args and expected `ValidatedResult` type.
7. `try/finally` invalidates facade on normal completion, timeout, cancellation and exception, and no mutable grant references survive on `self`. Track cancellation midvalidation; zero positive claims if binding verification fails. Recovery without original receipt => NoGrant.
8. Preserve existing RESPONSE/UPDATE stage ordering and safety barriers. The `NoGrant` restricted result must conform to the public canonical schema; when input contract invalid, use typed rejection/error, not fabricated mandatory IDs.

M2 integrated **POLICY constraint** invariant and deny/interrupt/forced path order remain unchanged; capture only after successful constraint invariants. Two explicit separate code insertions with one shared internal read-only helper is preferred to refactoring the 10-stage skeleton.

## 3. B-PD-03 — Trust-root registration and real builder integration

There is no verified production wiring root among the inspected sources. Establish a **bounded, explicit composition factory** `build_grant_gated_runtime(..., vetted_policy_authority, validation_core, ...)` in a new integration-only module; do not expose ProfileAuthorizationPolicyRule registration through an unaudited arbitrary RuntimeOrchestrator constructor argument as a security authority.

Factory rules:
- The factory accepts a frozen, operator-vetted **authority manifest** mapping `rule_id → version/registration_digest → allowed domain/profile IDs`. It must verify exact registrations and callable provenance from an approved M2 policy evaluation adapter. The manifest is a deployment artifact and an independent authorization dependency, **not** a self-declared authority field supplied by Domain tools or requests.
- Both base and integrated M2 runtime configurations must use the same profile-authority admissibility rules but distinct exact-decision receipt adapters; never forge a receipt when an integrated constraint path cannot expose it.
- Source authenticating assumption is a trusted in-process deployment configuration plus protected invocation chain, NOT cryptographic signing. For distributed/asynchronous boundaries the first version is unsupported and returns NoGrant.
- Initial production-safe factory returns a gated `NO_GRANT_ONLY` build until the M2 receipt implementation and reviewed manifest exist. Test fakes may prove the wiring in isolation, but may not be shipped as production authority.
- Preserve `DefaultPolicyEngine` standard usage and preexisting constructors for legacy callers. If allowing explicit trusted factory to pass an optional grant mode requires an internal constructor parameter, the exact signature diff must undergo independent authorization.

Required composition evidence before productive positive ProfileGrant: the **actual deployed runtime entrypoint and factory invocation** (repo path or separately supplied integrator config), approved M2 rule manifest, authorized Profile content digests, and connection from source policy evaluation to approval and M6; absent any => NoGrant. If no runtime entrypoint is in this repo, do not invent one in a comment; record external integration dependency.

## 4. R-PD-04 / R-PD-05 — Regression and test inventory

| Test module / test oracles | Base RuntimeOrchestrator | M2RuntimeOrchestrator |
|---|---|---|
| new `tests/test_m6_iu1_grant_policy_evidence.py` | P03 P04 P05 P08 P09: same-decision source receipt, no fake registry grant, immutable rule refs/digests | Same, with exact RuntimeConstraint.policy_decision and NoGrant on missing receipt |
| new `tests/test_m6_iu1_grant_runtime.py` | P01 P06 P07 P10 P11 P12 P14 P15: legacy vs gated, session/scope, snapshot, concurrent-turn, cancel, replay and restricted output | P02 and same negative oracles on overridden full run |
| new `tests/test_m6_iu1_grant_outcome.py` | P13: no automatic Goal/Business success from Tool success or mere Grant; valid canonical UNKNOWN/NOT_VALIDATED | Same |
| existing `tests/test_m0_closure.py` / orchestration tests | preserved original stage list, `ResultValidator.validate` ABI | Not substituted for M2 regression |
| existing `tests/test_m2_runtime_integration_gate.py` | N/A | P16 deny, interrupt, alternate, priority and RuntimeConstraint consistency |
| existing `tests/test_m4_policy_approval.py` | P07 exact policy snapshot unchanged | Same approval checker used |

**P17 four gates:** `pytest tests -q`; `mypy runtime tests`; `ruff check runtime tests`; `ruff format --check runtime tests`. No assertion that they ran in this documentation-only task.

New negative cases: same exact policy decision with forged second evaluation; integrated M2 constraint and unrelated DefaultPolicyEngine decision; policy source manifest mismatch; untrusted Domain provider; builder refuses GRANT_GATED without audited Core; NO_GRANT must not delegate to legacy affirmative Validator; concurrent turns; cancelled facade use after close; expired or missing proof; identity scope/session disagreement.

## 5. Finding dispositions, true gates

| Finding | Proposed fix | Gate |
|---|---|---|
| B-CA-M6-IU1-06-PD-01 | same-evaluation M2 decision receipt, explicit policy rule authority, integrated constraint-specific proof | DESIGN ADDRESSED / RE-REVIEW PENDING |
| B-CA-M6-IU1-06-PD-02 | two-path opt-in rollout, enforced NoGrant gated fallback and complete stage invariants | DESIGN ADDRESSED / RE-REVIEW PENDING |
| B-CA-M6-IU1-06-PD-03 | explicit vetted factory/manifest, no unverified root assumptions | DESIGN ADDRESSED / RE-REVIEW PENDING |
| R-CA-M6-IU1-06-PD-04 | separate base/integrated compatibility rollout | DESIGN ADDRESSED / RE-REVIEW PENDING |
| R-CA-M6-IU1-06-PD-05 | P01–P17 to exact test modules/oracles | DESIGN ADDRESSED / RE-REVIEW PENDING |

```text
CA-M6-IU1-06 TARGETED PHYSICAL DESIGN REMEDIATION = SUBMITTED_V1.1
M2 SAME-DECISION RECEIPT CONTRACT = PROPOSED / NOT IMPLEMENTED
TRUSTED PRODUCTION COMPOSITION AUTHORITY = PROPOSED / NOT VERIFIED
B-PD-01..03 = DESIGN ADDRESSED / INDEPENDENT RE-REVIEW PENDING
R-PD-04..05 = DESIGN ADDRESSED / INDEPENDENT RE-REVIEW PENDING
D-M6-IU1-01 = OPEN
M6-IU1 SLICE B POSITIVE-GRANT IMPLEMENTATION = NOT_AUTHORIZED
NEXT = CA-M6-IU1-06 Targeted Independent Physical Design Re-Review
```
