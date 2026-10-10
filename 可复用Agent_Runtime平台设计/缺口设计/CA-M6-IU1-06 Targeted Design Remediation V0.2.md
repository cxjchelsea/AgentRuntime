# CA-M6-IU1-06 Targeted Design Remediation V0.2

Status: DESIGN CANDIDATE / independent targeted re-review required. Supersedes V0.1 on authority transport, approval consistency and scope.
Baseline: main `88d3831270c56331af899e74d0c595ba1793d69d`; PR #82 previous HEAD `9af8c9a74d501bf29b8b7e44b6c781aedb2c1047`.

## 1. Verified existing implementation boundary

- `DefaultPolicyRechecker.recheck` produces `ApprovedActionPlan.policy_snapshot = PolicyDecision.model_dump(mode="json")`.
- `PlanApprovalCoordinator._validate_approved_integrity` enforces exact equality of these values and checks the approved plan corresponds to the draft.
- `PolicyDecision` currently has `policy_decision_id`, `validation_mode`, policy restrictions, but no validation-profile grant, request/scope, or signature authority.
- `ApprovedActionPlan` has plan_id/request_id, approved_at, and policy_snapshot, but **no standalone identity_scope**.
- `RuntimeContext.identity_context.identity_scope` and `ExecutionResult.identity_scope` exist; these are available for M6 inbound equality checks but cannot establish by themselves that M2 authorized a plan.
- `runtime/planning/runtime_integration.py` has `ValidationReceiptLedger`, which documents that it is not approval authority; **do not reuse it as a trusted grant issuer**.

### Frozen nonnegotiable invariants

```python
approved.policy_snapshot == policy_decision.model_dump(mode="json")
approved.plan_id == draft.plan_id
approved.request_id == draft.request_id
```

Never mutate `policy_snapshot` after `PolicyRechecker`, weaken equality checks, or add grant values by mutating the approved plan. M2/M4 keep their existing authority boundaries.

## 2. B-01 remediation — Single separately bound grant, outside policy_snapshot

**Decision:** withdraw V0.1's `approved.policy_snapshot["authorized_validation_profile_grant_v1"]` proposal. Also avoid changing `PolicyDecision` or `ApprovedActionPlan` canonical Pydantic fields in this IU1 amendment.

Use a **single read-only companion `ValidationGrantBindingV1`** returned by a narrowly scoped *approval-time binding port*, carried as an immutable envelope at the orchestration handoff. It is NOT embedded in policy_snapshot and NOT an alternative PolicyDecision.

```text
ApprovedValidationHandoffV1 (internal handoff; does not replace ApprovedActionPlan)
  approved_plan: ApprovedActionPlan
  decision_snapshot_digest: str
  grant_binding: ValidationGrantBindingV1 | None
  approval_proof: PlanApprovalBindingProofV1
```

The handoff is a **design proposal**, not an assertion that this internal port exists in main. Existing callers that only receive ApprovedActionPlan remain valid, but are treated as **NO_AUTHORIZED_GRANT** for rule-based success until a controlled integration provides authenticated proof. M5 must continue receiving the exact ApprovedActionPlan only; approval handoff envelope may be consumed by M6-side validation adapter through an injected authority port, not by changing the M5 executor. No grant is inferred from `ApprovedActionPlan.trace`, arbitrary dicts, or ambient Registry.

### Minimal binding data

```text
ValidationGrantBindingV1
  grant_schema_version: "1"
  policy_decision_id: str
  plan_id: str
  request_id: str
  identity_scope: str
  domain_id: str
  profile_ref: {profile_id, version, content_digest}
  applicability: {goal_ids[], tool_refs[]}
  validation_mode_floor: ValidationMode
  source_policy_digest: str
  approved_plan_digest: str
  issued_at: aware datetime
  binding_id: str
```

`PlanApprovalBindingProofV1` supplies `producer_identity`, `binding_id`, `policy_decision_id`, `approved_plan_digest`, `source_policy_digest`, `request_id`, `identity_scope`, and `authenticity_evidence` bound to the **trusted injected approval authority**. The proof must not be a raw hash that is accepted solely because it is structurally well formed.

The only plan binding authority is the approved M4 boundary delegating final authorization to the pre-existing M2 `PolicyRechecker` plus an explicit M2 validation-profile authorization input. M4 may narrow applicability; it cannot invent a profile grant.

## 3. B-02 remediation — Explicit trust-bound port, not imagined signing

Propose two small *injected* ports, **not a new signing service, database, registry or recovery engine**:

```text
ValidationProfileAuthorizationSource.authorize(
  policy_decision, request_scope, domain_scope
) -> ValidationAuthorizationIntent | NO_GRANT
PlanApprovalGrantBinder.bind_and_verify(
  authorization_intent, policy_decision,
  approved_plan, request_scope, trusted_approval_context
) -> VerifiedApprovalGrant | NO_GRANT
```

Both ports have a fail-closed default implementation `NO_GRANT` until an independently reviewed trusted producer exists. The binder must be *called only after* `PlanApprovalCoordinator`'s exact policy snapshot integrity checks pass; it must not impersonate the coordinator or independently approve the plan.

**Trust model:** Only a runtime-wired, locally authenticated binding producer within the same approval call chain can produce a verified grant. The consumer receives the grant through this trusted interface or a protected continuation handle, verifies exact identity and digest equality, and rejects user-supplied dictionaries/refs as authority. A digest detects content mismatch; it does not prove issuer identity. If the handoff crosses process/trust boundaries, a cryptographic MAC/signature or equivalent verified authenticated transport is required in a **separate** approved design. IU1 does not claim those facilities already exist.

Integrity atomicity is bounded to the *same trusted approval invocation*: approval valid and grant verified => emit pair; grant unavailable or binder fails => return approved plan without grant / no success-validation authority. No durable atomicity guarantee, replay persistence guarantee or standalone issuer database claimed.

## 4. B-03 remediation — Exact request/identity scope and temporal sequence

M2 decision lacks native identity_scope/request_id; therefore trusted input scope is an authenticated **approval invocation context** from existing RuntimeContext/RuntimeInput, validated against `draft.request_id`, `approved_plan.request_id`, and M6 `ExecutionResult.identity_scope`. This context **must be explicitly passed and verified by the new bounded approval binding port**, not inferred from PolicyDecision or untrusted Domain extension.

Proposed chronology:
1. Runtime supplies request_id + identity_scope + domain_id through a verified invocation context to M2 policy decision and to new authorization source. If trusted binding cannot be established, NO_GRANT.
2. M2 produces PolicyDecision plus optionally a request-scoped `ValidationAuthorizationIntent` identifying exact permitted profile and minimum mode; never contains future plan_id. It must be bound to exact `policy_decision_id` and decision digest.
3. M4 creates ActionPlanDraft with concrete plan_id/goals/steps and invokes its **unchanged** PolicyRechecker/Coordinator; approved plan keeps exact policy snapshot.
4. After normal approval integrity checks, grant binder intersects intent scope with approved goals and Tool refs; rejects widened or unknown applicability, seals approved_plan_digest and binding_id with trusted producer provenance; no mutation to ApprovedActionPlan.
5. Runtime orchestration passes verified immutable grant handoff to M6 validation admission **in addition to existing** public ResultValidator inputs via explicit injected trusted context/port. No new fourth positional argument to public `ResultValidator.validate` without separately approved API change.
6. M6 checks `ExecutionResult.plan_id/request_id/identity_scope` against approved plan, trusted approval context and grant. No exact trusted handoff -> NO_AUTHORIZED_GRANT; unbound Goal/Claim cannot become success.

### Time/replay/revocation
- `issued_at` is trusted approval-clock time (not an evidence observed_at); no implicit expiration time.
- Replayed validation must use the **same originally verified** policy/profile/grant snapshot, not current/latest registry. If protected snapshot unavailable, NO_GRANT.
- New validation obtains new approved authority, and always applies current M2 safety restrictions. No implied revocation lookup: when a policy requires live revocation, inability to check => NO_GRANT; otherwise documented bounded validity within same approved turn.
- Reject cross-identity, cross-plan, cross-session reuse; session may be derived from approved runtime invocation context, and must be equality-bound when available.

## 5. Compatibility, scope and tests

**Compatibility:** unchanged public Pydantic schemas and exact M4 snapshot equality; M5 remains an execution observer; IU1 does not create Goal/Claim completion facts. Legacy ApprovedActionPlan with no companion proof remains executable by M5, but M6 rule-based positive validation remains unresolved. In-process transport works only if the trusted authority handle survives to the M6 call; no claim of cross-process durability.

**Minimal controlled change inventory (proposal, not implementation):**
- New bounded approval context and two optional injected port interfaces in M2/M4 integration; fail-closed default.
- A trust-bound in-process handoff reference accessible by the M6 injected resolver; no public plan mutation and no second approval engine.
- M6 grant read/validate adapter; profile lookup is exact-version/digest and read-only.
- Test fixture for trusted grant producer and negative proof spoofing.
- If actual runtime orchestration cannot carry the reference safely, mark external integration dependency OPEN instead of smuggling grant into current generic fields.

**Verification oracles:**
1. Existing `approved.policy_snapshot == policy_decision.model_dump(mode="json")` holds with and without companion grant.
2. No producer => NO_GRANT without changing ApprovedPlan or M5 execution.
3. Fake `issuer_proof_ref` or arbitrary external dictionary => NO_GRANT.
4. Policy intent issued before plan_id; M4 final bind uses exact approved plan_id/goals/steps.
5. M4 grant binder cannot enlarge M2 intent scope or loosen mode.
6. Wrong request, identity_scope, plan_id or domain_id => NO_GRANT.
7. Profile version/digest differs => NO_GRANT, never Registry latest fallback.
8. No proof across runtime handoff => no success claim.
9. Same trusted approval invocation => one stable verified grant; no false promise of distributed replay.
10. Missing original replay snapshot => NO_GRANT.
11. Producer outage/throw => fail-closed, exact approval semantics unchanged.
12. No Tool call, State/Memory write, Agent Replan or new durable grant store from IU1.

## 6. Resolution disposition

| Prior finding | Candidate remedy | Current status |
|---|---|---|
| B-CA-M6-IU1-06-01 | remove snapshot injection, preserve exact equality, separate companion binding | DESIGN ADDRESSED / RE-REVIEW PENDING |
| B-CA-M6-IU1-06-02 | trusted in-process authority port, default NO_GRANT; external cryptography explicitly deferred | DESIGN ADDRESSED / RE-REVIEW PENDING |
| B-CA-M6-IU1-06-03 | exact authenticated runtime invocation context and two-phase intent→plan bind | DESIGN ADDRESSED / RE-REVIEW PENDING |
| R-CA-M6-IU1-06-04 | no new signing infrastructure, persistence runtime or Agent Loop implementation | DESIGN ADDRESSED / RE-REVIEW PENDING |

**Open integration question:** Can the present Runtime invocation/approval orchestration carry a trusted companion grant without an interface migration? If not, a bounded integration adapter must be separately designed and reviewed; a naked ref in generic `trace`/`policy_snapshot` is not allowed.

```text
CA-M6-IU1-06 TARGETED DESIGN REMEDIATION = SUBMITTED V0.2
FROZEN M4 POLICY SNAPSHOT INVARIANT = PRESERVED BY DESIGN
D-M6-IU1-01 = DESIGN PROPOSED / NOT IMPLEMENTED
CA-M6-IU1-06 TARGETED INDEPENDENT DESIGN RE-REVIEW = PENDING
M6-IU1 IMPLEMENTATION AUTHORIZATION = NOT_GRANTED
```
