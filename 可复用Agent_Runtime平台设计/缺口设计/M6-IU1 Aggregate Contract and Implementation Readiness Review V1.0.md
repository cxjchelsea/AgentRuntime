# M6-IU1 Aggregate Contract / Implementation Readiness Review V1.0

Review date: 2026-10-08
Exact base: `main@88d3831270c56331af899e74d0c595ba1793d69d`
Reviewed design head: PR #82 `4e1c4b25408a98643d26c8cecdd79475d43ebb3a`
Result: **READY_WITH_BLOCKING_DEPENDENCY / IMPLEMENTATION NOT_AUTHORIZED**.

## 1. Scope, accepted authority and design precedence

The four PR documents are cumulative, *not* four independent canonical schemas:
1. `M6 Canonical Contract Alignment V0.1`: current public-schema precedence.
2. `M6-IU1 Unit Spec V0.1`: requirements and negative gates.
3. `M6-IU1 Targeted Design Remediation and Agent Loop Alignment V0.2`: detailed inbound/provenance and separation of Agent Loop.
4. `M6-IU1 Second Targeted Design Remediation V0.3`: overrides V0.2 for admission reason/diagnostic, authorized-rule fallback and proof/trace boundary.

Source of canonical truth remains the original Canonical Contract Registry plus implemented public schema; proposed internal DTO definitions are subject to re-review and do not implicitly authorize public schema changes.

Previously independently reviewed:
- First re-review R02/R04/R06/R07 design accepted.
- Second targeted re-review RR-01 CLOSED, RR-02 CLOSED_WITH_DEPENDENCY, RR-03 CLOSED.
- Agent observation alignment accepted as future requirement only, not part of IU1.

## 2. Aggregate interface contracts

### Existing, unchanged public contract
`ResultValidator.validate(ExecutionResult, RuntimeContext, ApprovedActionPlan) -> ValidatedResult` remains the existing abstract interface. `ValidatedResult` v1.0.0 required: `schema_version, validation_id, execution_id, request_id, validation_status, business_status, claim_policy`; optional extensions keep existing public compatibility. Neither `ValidationInputEnvelope` nor `ValidationProof` is added to public output in IU1.

### Internal contracts and owners
| Internal contract | Owner / producer | Required consumers | Deterministic condition |
|---|---|---|---|
| ValidationAdmissionDecision | M6 admission boundary | IU1 adapter; future IU8 | ADMITTED has identity binding+envelope, empty reason allowed; REJECTED has no envelope and nonempty reason |
| ValidationIdentityBinding | M6 correlation guard | evidence projector | execution/plan/request/scope/session consistency |
| ValidationInputEnvelope | M6 input builder | later IU2–IU7 | defensive frozen snapshot with policy and rule resolution state |
| ValidationRuleBindingSnapshot | M2-authorized resolver (M6 consumer) | later Goal/Tool validation | no unpinned rule auto-selection; exact immutable refs/digests |
| EvidenceReference | M6 provenance projector | later IU2–IU5 | reference only, no trust/fact claim promotion |
| ValidationProof / OutcomeHandle | later producing adapter / IU8 consumer boundary | M7/M8 | smallest integrity-bound proof, optional AuditTrace; no new IU1 durable store |
| AgentObservationEnvelope | future feedback adapter (nonfrozen) | future Agent Loop Controller | not built in IU1 |

### Status semantics
- Admission integrity failure -> REJECTED, no canonical `ValidatedResult` fabricated.
- Correct inbound data but missing Rule grant -> admitted/unresolved for diagnostic reference; **never** successful Goal/Claim.
- `ValidationStatus.UNKNOWN/NOT_VALIDATED` differs from `BusinessStatus.UNKNOWN/WAITING`; source data insufficiency cannot be presented as confirmed failure.
- IU1 does **not** compute business completion, success claims, evidence trust/freshness, or replan.

## 3. Gap and implementation assessment

| Item | Design disposition | Executable dependency | Readiness |
|---|---|---|---|
| Exact input correlation | reviewed accepted | current ExecutionResult/Plan/Context | DESIGN READY |
| Admission decision and typed errors | RR-01 closed | explicit admission adapter in IU1 | DESIGN READY |
| Immutable snapshots / reference IDs | R06 accepted | canonicalization implementation and oracle | DESIGN READY |
| M5 field provenance | R02 accepted | exact field-level tests, no invented journal | DESIGN READY |
| Rule profile authorization | RR-02 closed *with dependency* | **D-M6-IU1-01**: M2/M4 producer grant absent or not proven | **BLOCKED for rule-based success** |
| Proof/result consumer consistency | RR-03 closed | future IU8/M7/M8 wiring; authenticated producer binding | DESIGN READY FOR IU1 STUB / LATER INTEGRATION |
| Full M6 business validator | outside IU1 | IU2–IU8 | OUT OF SCOPE |
| Agent Loop | observation boundary requirement only | Vertical Slice Gate after minimal M6 | OUT OF SCOPE |

### D-M6-IU1-01 resolution contract (smallest cross-module controlled amendment)
Required producer/consumer handshake:
```
AuthorizedValidationProfileGrant
  authority_id (M2 Policy origin, domain neutral)
  policy_snapshot_digest
  profile_id + version/digest constraint
  exact applicability scope (domain, goal/tool refs, identity scope)
  minimum ValidationMode (FAST/STANDARD/STRICT)
  issued_at and applicable expiry/revocation semantics
```
Do not introduce a new global policy engine or unrestricted Registry lookup. A backward-compatible additive approved-plan policy snapshot field **or** a separate authority-bound snapshot reference can serve; choose *one* via impact review. On absence, ambiguity, mismatch, disabled version, revocation or replay without pinned snapshot => UNRESOLVED/NO_SUCCESS_CLAIM, never use latest version.

### Implementation slice split
- **Slice A, no cross-module production change required:** immutable ValidationAdmissionDecision + identity/correlation guards + read-only evidence refs + deterministic canonicalization + safe diagnostics and local unit negative oracles. Must preserve existing M6 abstract interface and existing canonical public models. Can start *after explicit bounded Slice A authorization*.
- **Slice B, must await D-M6-IU1-01 approval:** authorized RuleBinding, M2/M4 producer-side grant, replay profile pin. No domain Goal success before this. Requires own exact impact review and authorization.
- **Slice C, downstream integration:** ValidationProof consumer adapter and positive ClaimPolicy/GoalSuccess wiring are IU8/M7/M8 work. IU1 may publish interface spec/fixtures, not a store or production-claim path.

## 4. No-go conditions and test evidence

Mandatory negative tests before claiming IU1 implementation:
- wrong plan, request, identity scope, session, Step/Tool ownership; duplicate IDs; no fabricated identifiers
- admitted healthy input has empty reasons; rejected input has nonempty reason
- unsupported RuleBinding returns unresolved; unauthorized Registry entry **never** grants success
- immutable nested snapshots, canonical deterministic digests, exact source paths and absent timestamp handling
- M5 `Tool SUCCESS` does **not** yield VerifiedFact or Business SUCCESS
- injected proof absent/mismatch cannot authorize future M7 success or M8 mutation (contract oracle, not IU1's production integration)
- no I/O to Tools, no replan, state/memory commit, or generated natural language in IU1

Existing four project gates are required after code implementation: pytest, mypy, ruff check, ruff format --check. None has been run for M6 code in this design-only review.

## 5. Freeze and authorization assessment

A positive targeted design review does not equal aggregate implementation authorization. No new technical inconsistency found among accepted v0.1–v0.3 contract decisions **within the bounded Slice A**. However, whole-IU1 implementation readiness depends on resolving cross-module grant authority before implementing profile-based successful validation. Separate public output amendment `CA-M6-PUBLIC-01` remains UNAUTHORIZED.

```text
M6-IU1 AGGREGATE CONTRACT REVIEW = PASS_WITH_DEPENDENCY
M6-IU1 DESIGN BASELINE (ADMISSION/PROVENANCE) = READY_FOR_BOUNDED_FREEZE_DECISION
D-M6-IU1-01 (M2/M4 VALIDATION PROFILE GRANT) = OPEN/BLOCKING_FOR_RULE_BINDING
M6-IU1 FULL IMPLEMENTATION READINESS = NOT_READY
M6-IU1 FORMAL IMPLEMENTATION AUTHORIZATION = NOT_GRANTED
M6-IU1 SLICE A READINESS = ELIGIBLE_FOR_SEPARATE_BOUNDED_AUTHORIZATION
M6-IU1 SLICE B RULE-AUTHORIZED SUCCESS = BLOCKED
MAIN PUBLIC VALIDATEDRESULT SCHEMA CHANGE = NOT_AUTHORIZED
AGENT LOOP IMPLEMENTATION IN IU1 = PROHIBITED
```

Next recommended task: `CA-M6-IU1-06 M2/M4 Authorized Validation Profile Grant Contract` minimal controlled amendment; separately, explicitly authorize **Slice A only** if progress is needed while the producer amendment is under review. Follow with IU1 implementation readiness re-evaluation against the approved exact-head contract.
