# M6-IU1 Slice B1b — Downstream NoGrant Claim / Side-Effect Barrier Controlled Design V0.1

**Date:** 2026-10-09. **Nature:** controlled design, no implementation authorization. **Code baseline:** main `1c0f68bdb4fd188e32b9fb22aa5424117e1fa881` (A/B0/B1a merged and exact-head post-merge gates accepted). **Design PR:** #82. **Source:** B1b/B2 readiness review in PR #82. D-M6-IU1-01 stays OPEN, B3 blocked.

## 1. Design objective and strict separation

The NoGrant canonical `ValidatedResult` currently contains `ValidationStatus.UNKNOWN` and `BusinessStatus.UNKNOWN`; `ClaimPolicy.allowed_claims=[]` and `forbidden_claims=[]` do not force M7 or M8 to refrain from success statements or mutations. B1b designs an authoritative **downstream boundary**, not a new business validator. It must never treat status UNKNOWN as affirmative, infer success from `ExecutionResult.plan_status`, or rely on prompt instructions to enforce no claims.

B1b is split into:
- **B1b-P policy kernel (candidate independently implementable):** purely classifies a *trusted, internally tagged* B1a NoGrant path, returns immutable `NoGrantDownstreamDecision` with permitted neutral output scope and forbidden mutations. No IO/Tool/M7/M8 calls.
- **B1b-E enforcement at actual call sites:** pre-M7 and pre-M8 barriers and post-generation assertion. These cannot protect production without **B2 concrete Orchestrator wiring**. B1b-E design may be frozen now; physical implementation remains blocked until B2 exact-method integration and permission gates.
- The tag is conveyed through a **private per-turn turn-local origin binding** created within the approved M6 facade, not derived solely by observing arbitrary `ValidatedResult.UNKNOWN/UNKNOWN` fields or an easily forged `validation_errors` dict. B1a itself provides no source attestation. An untagged UNKNOWN result is likewise never granted success by this policy, but cannot be labeled verified NoGrant provenance.

## 2. Existing exact contracts and physical call sites

Current `runtime/interfaces/response.py` has `ResponsePlanner.plan(validated_result,context,understanding,approved)`, `ResponseGenerator.generate(response_plan)` and `ResponseValidator.validate(runtime_response,validated_result)`; `runtime/interfaces/update.py` has `StateMemoryUpdater.update(runtime_input,context,understanding,approved,validated_result,runtime_response)`. Public signatures remain frozen.

Both `runtime/orchestration/runtime.py:run` and `runtime/orchestration/m2_runtime.py:run` call `result_validator.validate(execution,context,approved)` and immediately proceed to RESPONSE_PLAN/RESPONSE_GENERATE/RESPONSE_VALIDATE/UPDATE. Neither currently carries or checks an authoritative NoGrant-path token. B1b standalone code cannot claim it has already enforced these call sites.

## 3. B1b-B01 — Classification, allowed and forbidden action matrix

### 3.1 Default selected policy: STOP_BEFORE_DOWNSTREAM

For all B1a NoGrant-derived results, **the first safe production policy is to stop before any M7 or M8 call** and return an internal typed `NO_GRANT_DOWNSTREAM_BLOCKED` outcome to the enclosing Orchestrator/error boundary. Do **not** synthesize `RuntimeResponse` or `UpdateResult` with fabricated success/commit status; do not claim a full successful turn.

This is the default even when neutral messaging might be desirable, because existing injected M7/M8 implementations have no independently verified safety capability. A neutral user-facing clarification remains possible only in a separately authorized **SAFE_NEUTRAL_RESPONSE** path whose generator/template and output postvalidator are strictly controlled, immutable and side-effect-free and whose delivery semantics are reviewed. This path is **not** authorized or implemented in the initial B1b scope. Do not confuse error trace/logging with user-visible response delivery.

| Candidate route | NoGrant default | Why |
|---|---|---|
| M7 ResponsePlanner/Generator via injected interface | **DENY** | Can assert business success; interface promises insufficient for denial |
| M7 ResponseValidator as sole safety gate | **DENY as primary guard** | Invoked only after generation; too late to stop the generator's behavior |
| Side-effect-free neutral response under future approved safe factory | DEFERRED | Requires independent template, correlation and validation proof |
| M8 StateMemoryUpdater.update | **DENY** | May commit state/memory; post-call validation too late |
| External tool, notification, domain action, positive claim | **DENY** | No validation grant |
| Internal fail-closed error trace and no-grant telemetry | CONDITIONAL | Must be no business action and no positive response |
| Normal validated result from separately proven positive grant path | OUT_OF_SCOPE / must not be accidentally downgraded | B3/D-M6-IU1-01 blocked |

### 3.2 Internal decision contract

```text
NoGrantDownstreamDecision:
  disposition = BLOCK_BEFORE_M7_M8     # frozen for initial scope
  reason = NO_AUTHORIZED_VALIDATION_GRANT
  origin_classification = NO_GRANT_INTERNAL | UNATTESTED_UNKNOWN
  may_call_response_planner = false
  may_call_response_generator = false
  may_call_state_memory_updater = false
  may_emit_positive_claim = false
  may_commit_business_or_memory = false
  allowed_user_response = NONE
  source_validation_id, request_id, execution_id  # correlation-only
```

The classifier must use a **private internal handoff context** tied to the B1a invocation (request, execution, validation_id, same turn identity, B0 NoGrant) and exact canonical fields; no public `ValidatedResult` field is elevated to proof of a verified Grant. Forged positive `claim_policy`, fabricated error tags and copy-pasted UNKNOWN results cannot bypass a default block. A status or correlation mismatch => fail-closed typed internal error before M7/M8, never a fallback to `self.result_validator` that promotes authority.

## 4. B1b-B02 — Enforced placement, ownership, no bypass

**Proposed owner:** M6 private downstream gate/facade injected through approved production composition root; M7/M8 are consumers, not trusted to authorize themselves.

Both physical `run()` methods need identical logical guards:
1. After RESULT_VALIDATE, before RESPONSE_PLAN: check tagged NoGrant decision. If BLOCK, terminate safely through the existing *error* lifecycle with no M7/M8 invocation.
2. Before RESPONSE_GENERATE: defense-in-depth if any future constrained neutral ResponsePlan is admitted. Currently unreachable under default BLOCK.
3. After RESPONSE_GENERATE and before user delivery / RESPONSE_VALIDATE: independently check any output for unsupported positive claims; this is **not currently implementable as exhaustive free-form semantic verification without an explicit classifier**. Default BLOCK remains mandatory; no unreviewed LLM heuristic or keyword filter may be treated as proof.
4. Before UPDATE: deny all update call paths for NoGrant, even if an unexpected component returned a RuntimeResponse.
5. Trace/terminalization must not label the turn SUCCESS or claim state commit if a NoGrant guard blocks. The existing `_run_stage` error behavior and `_close_turn` require exact-diff review in B2 to prevent double terminalization and ensure cancellation safe cleanup.
6. No alternative legacy validator, test Stub or branch may bypass the gate; fail closed if the facade, trusted origin, or guard injection is absent in the gated production configuration.

**Important:** B1b-P may implement pure policy functions without touching `run()`. No claim of runtime enforcement until B2-E wires both concrete run paths and proves cancellation/error cleanup.

## 5. B1b-B03 — Unknown results, trace and fail-closed behavior

- `UNKNOWN/UNKNOWN` means **no established validation/business truth**, not FAIL, SUCCESS or UNSAFE fact. Do not create a verified negative medical outcome.
- A NoGrant result provides no permitted positive statement, even if underlying execution succeeded; zero verified facts/goals/state recommendation and zero authorized updates.
- If classification is missing, ambiguous, untagged, or conflicting, return a typed internal `DOWNSTREAM_AUTHORITY_UNKNOWN`/ `NO_GRANT_DOWNSTREAM_BLOCKED` decision; no default permission.
- Reasons are **internal typed enums** with no public Canonical schema changes. Trace correlation must not include protected user content; reason codes are permitted only as nonauthorizing diagnostics.
- If business constraints later require safe neutral text, a separate frozen controlled SAFE_NEUTRAL_RESPONSE contract must enumerate allowed exact templates, output encoding, no hidden TTS side effects, logging privacy, and safe delivery; no generic generator allowed before that gate.

## 6. B1b-B04 — Verification and oracle matrix

| ID | Scenario | Mandatory evidence |
|---|---|---|
| B1b-01 | B1a NoGrant UNKNOWN/UNKNOWN | BLOCK_BEFORE_M7_M8; no response planner/generator/updater calls |
| B1b-02 | malicious `allowed_claims=["completed"]` or forged `validation_errors` | cannot authorize success; fail closed |
| B1b-03 | execution Tool/plan SUCCESS while NoGrant | no business SUCCESS, no update or reply |
| B1b-04 | absent/mismatched private turn binding | typed BLOCK, no fallback |
| B1b-05 | neutral acknowledgement requested through ordinary M7 | DENY until safe-neutral contract explicitly authorized |
| B1b-06 | `StateMemoryUpdater` spy records side effects | zero calls, zero memory writes, zero state transitions |
| B1b-07 | ResponseValidator bypass / malicious response fixture | no bypass: block occurs **before** M7 |
| B1b-08 | normal positive-grant input | must be separately authorized; do not claim pass or invoke legacy permissive path in these tests |
| B1b-09 | exception/cancellation around gate | no extra M7/M8 calls; terminal trace and resources owned by B2 |
| B1b-10 | both concrete Orchestrator.run methods | no implementation claim until B2 exact-diff tests |
| B1b-11 | canonical `ValidatedResult` unchanged, public validator ABI unchanged | contract-diff inventory verifies zero changes |
| B1b-12 | exact implementation HEAD gates | pytest, mypy, ruff check, ruff format plus independent review |

## 7. Candidate implementation split and scope budget

**B1b-P pure design-to-code candidate** (requires separate readiness and authorization):
- NEW `runtime/validation/no_grant_downstream_policy.py` — immutable decision, typed reasons, pure classification, zero imports from physical M7/M8 and no I/O.
- NEW `tests/test_m6_iu1_slice_b1b_policy.py` — policy oracles including forged metadata/no grant and exact correlation checks.
- Prefer no changes to frozen `runtime/contracts/**`, `runtime/interfaces/**`, `runtime/orchestration/**`, existing A/B0/B1a.

**B1b-E + B2 physical integration** (NOT READY / NOT AUTHORIZED):
- Controlled exact method diffs in both Orchestrators and private facade injection; no new top-level stages or new public validator parameters.
- Resource lifecycle `try/finally` for B0 slot and per-turn controller; preserve existing trace terminalization and no cross-turn state.
- Must prove OriginBinding values from validated RuntimeInput, not copied from downstream payload.
- Existing M7/M8 calls only permitted after explicit authorized positive gate or separately reviewed safe-neutral path, both presently unavailable.
- No automatic legacy validation fallback; any proposal to preserve ungated legacy behavior requires separate explicit configuration boundary and approval, never implicit.

## 8. Dependency / gate status

```text
B1b-B01 CLAIM/ACTION CLASSIFICATION = DESIGN_SPECIFIED
B1b-B02 ENFORCEMENT PLACEMENT = DESIGN_SPECIFIED / PHYSICAL_B2_PENDING
B1b-B03 UNKNOWN/TRACE ERROR POLICY = DESIGN_SPECIFIED
B1b-B04 ORACLES = DESIGN_SPECIFIED / UNEXECUTED
B1b-P PURE POLICY IMPLEMENTATION READINESS = REVIEW_PENDING
B1b-E PRODUCTION ENFORCEMENT = NOT_READY / B2_DEPENDENCY
B1b FORMAL IMPLEMENTATION AUTHORIZATION = NOT_GRANTED
B2 FORMAL IMPLEMENTATION AUTHORIZATION = NOT_GRANTED
B3 POSITIVE GRANT PRODUCER = BLOCKED
D-M6-IU1-01 = OPEN
NEXT = M6-IU1 Slice B1b Independent Controlled Design Review
```

**This design deliberately chooses fail-closed stop before M7/M8 as an interim default.** It does not claim that user-visible fallback replies are delivered or that all side effects occurring *before* RESULT_VALIDATE can be rolled back. M5 execution already happened; B1b can only prevent **new downstream side effects**, not undo upstream execution.
