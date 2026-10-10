# CA-M6-IU1-06 Second Targeted Design Remediation V0.3

Status: TARGETED DESIGN CANDIDATE / independent re-review required. Base main `88d3831270c56331af899e74d0c595ba1793d69d`. Supersedes V0.2 only for actual Orchestrator handoff and trusted authority protocol.

## 1. Exact existing boundary and rejected shortcut

Verified in main:
- `RuntimePolicyRecheckerAdapter.recheck(ActionPlanDraft, PolicyDecision) -> ApprovedActionPlan`; `PlanApprovalCoordinator.approve(...)` returns `PolicyApprovalResult`, adapter returns only `result.approved_plan`.
- `RuntimeOrchestrator.run()` calls the abstract `PolicyRechecker.recheck(...)`, checks for `ApprovedActionPlan`, executes M5, then calls `ResultValidator.validate(execution_result, runtime_context, approved_action_plan)`. There is **no companion grant transport** today.
- `approved.policy_snapshot == policy_decision.model_dump(mode="json")` is frozen and remains exact.
- Neither PolicyDecision nor ApprovedActionPlan is authoritative for identity_scope/session_id; the per-turn RuntimeInput/RuntimeContext and ExecutionResult carry relevant identities.

**Rejected:** invisible ContextVar, process-global dict, late assignment to arbitrary `trace` or `policy_snapshot`, overloaded `ApprovedActionPlan`, a fourth positional ResultValidator argument, a new credential database, replacing PlanApprovalCoordinator, or treating a SHA digest as proof of issuer authentication.

## 2. B-02/B-03/RR-01 resolution: one explicit, opt-in orchestration authority port

Use a narrowly scoped **opt-in orchestrator extension**, not a hidden side-channel: `ValidationGrantAuthorityPort`. Only the RuntimeOrchestrator instance constructed by a trusted composition root receives this port. By default it is absent, and every M6 rule grant decision is `NO_GRANT`.

```python
class ValidationGrantAuthorityPort(Protocol):
    async def bind_after_approval(
        self, *, approved_plan: ApprovedActionPlan,
        policy_decision: PolicyDecision,
        runtime_context: RuntimeContext,
        runtime_input: RuntimeInput,
        turn_nonce: str,
    ) -> "GrantBindingOutcome": ...

    def verify_for_validation(
        self, *, candidate: "GrantBindingOutcome",
        approved_plan: ApprovedActionPlan,
        policy_decision: PolicyDecision,
        runtime_context: RuntimeContext,
        runtime_input: RuntimeInput,
        turn_nonce: str,
    ) -> "VerifiedGrant | NoGrant": ...
```

These signatures are **new bounded internal integration interfaces requiring independent authorization**, not claims about existing methods. The production bridge initially implements only `NO_GRANT` unless explicitly wired with an approved M2-profile-authorization source and M4 approval-proof verifier. An arbitrary injectable external plugin or Domain service must not be registered as grant authority. The trusted composition root is accountable for wiring **one vetted instance** to both bind and verify methods.

**Exact seam in RuntimeOrchestrator.run():**
1. Run existing `POLICY_RECHECK` unchanged and receive only the exact `ApprovedActionPlan`. Independently reassert snapshot equality and request/plan consistency before invoking the new port.
2. Create a local `turn_nonce` in the running turn; after successful approval call `bind_after_approval` with the approved plan, original policy decision, trusted runtime input/context and nonce. This does **not** mutate the approved plan, the policy decision or M5.
3. Save the returned immutable `GrantBindingOutcome` in an **ordinary local variable of this one `run()` coroutine**, not on `self`, ContextVar, RuntimeContext mutable dict or shared registry. `NO_GRANT` is a valid value and means no rule-authorized success.
4. Call M5 with original `approved_action_plan, runtime_context` exactly as today.
5. Immediately before `RESULT_VALIDATE`, use `verify_for_validation` on the same trusted port, checking `ExecutionResult.plan_id/request_id/identity_scope` consistency as part of M6's existing admission guards. Deliver `VerifiedGrant | NoGrant` through an **explicit optional trusted validator adapter factory** scoped to the same call: `validator = validation_grant_binding.bind(self.result_validator, verified_grant)`; call `validator.validate(execution_result,runtime_context,approved_action_plan)` with the three original parameters. The binding facade's single use and closed lifetime must be enforced; it must not mutate the singleton shared `self.result_validator`.
6. On cancellation, exception, or return, local variables go out of scope and the per-turn adapter is closed in a `finally` block. No grant is retained on a reusable singleton or shared mutable state.

This is a **controlled limited internal Orchestrator/adapter change**, not an unmodified-code claim. If adding the opt-in port or per-turn validator facade is refused by the M0/M4 frozen integration contract, the only allowed implementation is `NO_GRANT`; start IU1 Slice A separately and keep Slice B blocked. No alternative hidden transport.

## 3. Trusted provenance and exact binding

`GrantBindingOutcome` is one of:
- `NoGrant(reason_code)`
- `GrantCandidate(immutable data, trusted_internal_provenance)`; *not yet valid for success*.

`VerifiedGrant` is produced only by `ValidationGrantAuthorityPort.verify_for_validation`, which checks:
- `policy_decision_id`, `PolicyDecision` canonical digest, `ApprovedActionPlan` canonical digest, `plan_id`, `request_id`, `runtime_input.request_id`, `runtime_context.identity_context.identity_scope`, session ID and current turn nonce from the trusted invocation;
- frozen `approved.policy_snapshot == policy_decision.model_dump(mode="json")`;
- M2-origin exact profile authorization intent bound to the same decision/request/scope, and M4 post-approval narrowing of scope to exact goal IDs and tool refs; no M4-created or widened M2 authorization;
- exact Domain profile ID/version/content digest and validation mode floor; stricter applicable safety rules may only restrict;
- issuer identity through *port invocation provenance supplied by the trusted composition root and a protected same-call grant candidate*, not a string `issuer_proof_ref` or merely a digest. External/process-crossing handoff **is not supported** without separate authenticated transport authorization.

An internal immutable handoff is trusted only to the extent the application composition root and process boundary are trusted. This is a scoped **in-process trust assumption**, not cryptographic evidence of an external signer, and must be stated in production deployment limitations. Candidate objects arriving from user data/Domain tools/LLM outputs always become `NO_GRANT`.

M2 authorization source is **new and separately implemented**; until it emits a verified intent from approved policy rules, the binding port returns `NoGrant(GRANT_SOURCE_UNAVAILABLE)`. A PolicyDecision alone does not imply a profile grant; `validation_mode` is a floor, not profile permission.

## 4. Per-turn lifecycle and failure table

| Case | Required behavior |
|---|---|
| no port / no M2 intent | NO_GRANT; M5 allowed on its previously approved plan; no rule-based success |
| grant producer raises / times out | NO_GRANT and diagnostic; *never* rerun M4, never choose latest |
| invalid scope/request/plan/session | NO_GRANT or existing M6 REJECTED if canonical identity itself contradictory |
| parallel turns sharing one Orchestrator | two distinct local nonce/candidate/facades; no reuse or overwritten shared state |
| cancelled between approval and M6 | candidate invalid at end of turn, no grant left accessible |
| same turn retries validation | reverify same frozen grant candidate and unchanged approved plan; no new M2 permission minted |
| process crash / turn recovery | no in-memory grant proof => NO_GRANT until separately approved replay binding; do not invent grant from checkpoint |
| changed policy, revocation or new safety restriction | current safety barrier prevails; no grant-based bypass; when mandatory check unavailable => NO_GRANT |
| non-trusted injected port / external candidate | reject composition at bootstrap or NO_GRANT; no generic injection authority |
| approved plan snapshot deviates from M2 decision | frozen approval integrity failure; never build candidate |

The port owns **no durable state**. Any logging contains only redacted reason codes and bounded references; not secrets or full policy payloads. Grant-protected proof never grants Tool execution permission or business success by itself.

## 5. Minimal approved change inventory

| Code unit | Bounded proposed change | Freeze constraints |
|---|---|---|
| Orchestrator constructor/turn `runtime/orchestration/runtime.py` | optional vetted authority port; turn-local candidate and per-turn validator facade | preserve existing stage names and stage type checks |
| Approval integration | M2 authorization source/in-process provenance available to vetted port | do not change `PolicyRechecker.recheck` or exact M4 approval invariant |
| M6 validator adapter | optional three-arg per-turn facade consuming `VerifiedGrant` | no generic RuntimeContext/trace field mutation; no additional public Validator positional param |
| Canonical schemas `PolicyDecision`, `ApprovedActionPlan`, `ValidatedResult` | **none** | existing schema/version unaffected |
| M5 | **none** | no retry/recovery/locking changes |
| Agent Loop | **none** | no Replan Controller in M6-IU1 |

The use of `validation_grant_binding.bind(...)` is pseudocode describing an adapter factory; before implementation, name the actual type/protocol and independently authorize this single narrow integration diff. If exact old three-argument `ResultValidator` implementation cannot consume a bound facade, the only valid behavior is NO_GRANT and Slice B remains blocked.

## 6. Integration test oracles, exact signatures

1. Existing `RuntimePolicyRecheckerAdapter.recheck(draft,policy_decision)` still returns only ApprovedActionPlan.
2. Existing `PlanApprovalCoordinator.approve` still compares exact snapshot, unchanged with/without grants.
3. `RuntimeOrchestrator.run` without optional authority port yields identical previous orchestration signatures and no grant success.
4. A vetted fake authority binds only after M4 approval and can be verified by the same-call M6 facade with original 3 arguments.
5. Two simultaneous `run()` on one Orchestrator yield distinct nonces, independent grants and no state leakage.
6. Cross-request/identity_scope/session/plan grant reuse fails.
7. Forged grant candidate and untrusted injected provider fail closed.
8. Current M2 `PolicyDecision` without extra intent cannot be interpreted as grant.
9. Invalid/missing exact profile snapshot => NO_GRANT, never latest Registry fallback.
10. M5 receives unchanged ApprovedPlan and no grant.
11. Cancellation/producer fault/timeout removes access; no durable grant store or recovery.
12. Crash/restart loses grant and cannot retroactively permit goal SUCCESS.
13. Valid grant alone cannot mark Tool or business SUCCESS without verified outcome evidence.
14. M6 adapter always maintains three-argument `ResultValidator.validate`.
15. No new Agent Loop, State write, Claim Policy bypass or natural-language response action inside IU1.

## 7. Disposition and gate

| Review finding | V0.3 resolution | Pending acceptance |
|---|---|---|
| B-CA-M6-IU1-06-02 | composition-root trust and single-call verification; default NO_GRANT | independent review |
| B-CA-M6-IU1-06-03 | exact runtime request/plan/scope/session binding and temporal order | independent review |
| B-CA-M6-IU1-06-RR-01 | explicit opt-in Orchestrator seam + per-turn facade; no secret handoff | independent review |
| B-CA-M6-IU1-06-01 / R-04 | preserve previous closure: frozen M4 snapshot and no overbuilding | regression check |

```text
CA-M6-IU1-06 SECOND TARGETED DESIGN REMEDIATION = SUBMITTED V0.3
D-M6-IU1-01 = BOUNDED INTEGRATION DESIGN PROPOSED / NOT IMPLEMENTED
CA-M6-IU1-06 SECOND TARGETED INDEPENDENT DESIGN RE-REVIEW = PENDING
M6-IU1 SLICE B = BLOCKED UNTIL PORT/PRODUCER AUTHORIZED
M6-IU1 IMPLEMENTATION AUTHORIZATION = NOT_GRANTED
```
