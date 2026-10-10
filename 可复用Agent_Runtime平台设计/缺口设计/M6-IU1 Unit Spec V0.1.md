# M6-IU1 Unit Spec v0.1 — Canonical Contract + Inbound/Identity/Provenance Boundary

Status: DRAFT / DESIGN REVIEW REQUIRED / NOT IMPLEMENTATION AUTHORIZED
Baseline: main@88d3831270c56331af899e74d0c595ba1793d69d
Dependencies: M4 ApprovedActionPlan, M5 canonical ExecutionResult, RuntimeContext, approved policy snapshot, Canonical/Schema Registry. Pair with M6 Canonical Contract Alignment V0.1.

## 1. Objective and non-goals
Convert an existing `ResultValidator.validate(ExecutionResult, RuntimeContext, ApprovedActionPlan)` call into an immutable, scope-safe, rule-bindable M6 input envelope; validate correlation and source provenance **before** downstream fact/claim interpretation. Remain compatible with current canonical `ValidatedResult`.

Out of scope: implementing EvidenceTrust, freshness decisions, ToolSuccess interpreter, GoalCompletion, conflict resolution, Claim Ladder, follow-up/state mutation, external status-query Tool calls, M7 response text and any M5 retry. IU2–IU8 remain separate.

## 2. Proposed components and ownership
| Component | Responsibility | Authority |
|---|---|---|
| `ValidationInputBuilder` | Snapshot arguments, resolve required source refs, bind policy/mode/rules | no interpretation or external Tool invocation |
| `ValidationCorrelationGuard` | Scope and plan/request/execution/step identity equalities | fail-closed, no corrective guessing |
| `ValidationRuleBindingPort` | read-only versioned rule selection; missing/ambiguous -> explicit unresolved | Domain values outside Core |
| `EvidenceReferenceProjector` | structured provenance refs to exact M5 entries, no claim promotions | no business success |
| `ValidatedResultCompatibilityProjector` | preserve canonical v1.0.0 output with safe fallback | no unverified successful claim |
| `ValidationTraceSink` | diagnostics with identity/rule/profile digests | no state/memory mutation |

## 3. Exact data flow
```
M5 ExecutionResult + M4 ApprovedActionPlan + M1 RuntimeContext
 → schema / identity / plan correlation guard
 → policy snapshot binding + mode check
 → registered goal/tool validation profile resolution
 → immutable ValidationInputEnvelope
 → deterministic EvidenceReference projection (no fact promotion)
 → IU2..IU7 [future]
 → Canonical ValidatedResult projector [future full pipeline, fail-closed in IU1]
```

## 4. Normative IU1 requirements
- **REQ-01** Accept only `ExecutionResult`, `ApprovedActionPlan`, `RuntimeContext` from the existing interface; no new mandatory positional argument.
- **REQ-02** Check `plan_id` / `request_id` equality across execution and approval. No substitution or reconciliation.
- **REQ-03** Check `identity_scope` equality with context, and derive `session_id` only from session context. Never fall back to `elder_id`, `user_scope` or domain ID.
- **REQ-04** Validate step IDs/call IDs have no ambiguous or contradictory ownership and map to approved steps/tool plan; optional output fields remain optional, but absence of required truth is not success.
- **REQ-05** Pin policy snapshot from the ApprovedActionPlan; Context cannot weaken it. `ValidationMode` has existing FAST/STANDARD/STRICT values, but exact authority must be resolved under CA-M6-004.
- **REQ-06** Tool/Goal bindings are immutable exact IDs/versions or explicit unknown/missing; never infer from status or open-string completion conditions.
- **REQ-07** Provenance refs preserve raw value classification and exact observed_at when present; no fake timestamps or external lookups.
- **REQ-08** Validation fails closed for invalid input or identity mismatch. Emit typed reason codes/trace; never fabricate a `VerifiedFact`.
- **REQ-09** Preserve `ValidatedResult` canonical public v1.0.0 required fields; any additive changes require controlled amendment.
- **REQ-10** Determinism: repeated identical inputs with same rule/policy pin produce same reference IDs, status/correlation decisions (trace event timestamp excluded); immutable inputs.
- **REQ-11** For malformed evidence, `UNKNOWN` is not automatically `FAILED`; keep `WAITING` as Business/Goal status, not ValidationStatus.
- **REQ-12** No Tool/Skill/Workflow call, M4 replan, persistent state/memory write, or M7 text generation within IU1.
- **REQ-13** Require explicit error provenance and trace for invalid schema, wrong request/plan/scope, missing binding, ambiguity, stale/unknown observation time.
- **REQ-14** Do not treat M5 `plan_status=SUCCESS` or Step `NOT_APPLICABLE` as direct Goal SUCCESS / failure.

## 5. Acceptance / negative gates
| Gate | Scenario | Expected |
|---|---|---|
| IU1-G01 | canonical healthy M5+M4+Context identities | envelope bound, no facts/claims inferred |
| IU1-G02 | request_id mismatch | fail-closed diagnostic |
| IU1-G03 | plan_id mismatch | fail-closed diagnostic |
| IU1-G04 | identity_scope mismatch | fail-closed diagnostic |
| IU1-G05 | wrong/duplicate Step and Tool correlation | fail-closed diagnostic |
| IU1-G06 | no Goal rule / no Tool interpreter | explicit missing binding, never success |
| IU1-G07 | unavailable timestamp | evidence freshness UNKNOWN, not invented NOW |
| IU1-G08 | Tool SUCCESS / timeout / cancellation | no business-fact promotion |
| IU1-G09 | strict policy cannot be downgraded by context | reject downgrade or preserve STRICT |
| IU1-G10 | same snapshots/profiles rerun | stable refs and deterministic outcome |
| IU1-G11 | canonical v1.0.0 serialization | contract preserved |
| IU1-G12 | no external calls or writes | side-effect-free boundary |
| IU1-G13 | wrong-domain identity and cross-session correlation | fail-closed |
| IU1-G14 | trace reason codes and digest provenance | verifiable without PII |

Four existing repository gates are mandatory on every implementation PR: pytest, mypy, ruff check, ruff format --check. Stage-level M6-F01..F18 are **future** aggregate gates, not claimed by IU1.

## 6. Design blockers and review questions
1. **IU1-B01** Canonical output metadata/provenance additive shape and version compatibility (CA-M6-001/002).
2. **IU1-B02** Owner and version-pinning of goal/tool RuleBinding profiles across M4 approval, M5 execution and M6 consumption (CA-M6-003).
3. **IU1-B03** PolicySnapshot and ValidationMode explicit authority and conflict rule (CA-M6-004).
4. **IU1-B04** Exact Step/Tool journal/Workflow/business output provenance cardinality (CA-M6-005).
5. **IU1-B05** Error handling contract: malformed input exception vs a safe `ValidatedResult`; which layer is authorized to decide.
6. **IU1-B06** Validation digest canonicalization, trace ownership and strict no-external-effects observability.

## 7. Readiness / authorization
```
M6-IU1 UNIT SPEC = V0.1 DRAFTED
M6-IU1 DESIGN FREEZE = NOT_YET
M6-IU1 INDEPENDENT DESIGN REVIEW = PENDING
M6-IU1 IMPLEMENTATION READINESS = NOT_READY
M6-IU1 IMPLEMENTATION AUTHORIZATION = NOT_GRANTED
```
Next: Independent M6-IU1 Design Review against canonical primary-chain contract and exact current M5 model, followed by targeted controlled amendments and re-review.
