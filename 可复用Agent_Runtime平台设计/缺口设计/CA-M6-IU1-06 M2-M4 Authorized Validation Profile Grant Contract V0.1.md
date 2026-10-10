# CA-M6-IU1-06 M2/M4 Authorized Validation Profile Grant Contract V0.1

Status: CONTROLLED AMENDMENT DESIGN / PROPOSED / INDEPENDENT REVIEW REQUIRED
Base: AgentRuntime main `88d3831270c56331af899e74d0c595ba1793d69d`
PR: #82. Closes design gap D-M6-IU1-01 only after an independently accepted producer/consumer contract and implementation evidence. No code authorization in this artifact.

## 1. Background and exact current contract

Current `PolicyDecision` has `policy_decision_id`, `validation_mode: ValidationMode`, allowed/blocked, action/tool restrictions, created_at, and optional constraints; it **does not** contain a validation-profile grant. Current `ApprovedActionPlan` has `policy_snapshot: dict[str, Any]`, `approved_at` and generic goals/steps, but no specifically typed profile grant. `PlanningGoal.completion_condition: str` must not be used as executable rule authorization.

Therefore, **no historical approved plan should be deemed to carry a grant merely because its snapshot is a map or a Registry rule exists**.

## 2. One chosen transport, no parallel grant channels

Choose **one additive, versioned field within the existing ApprovedActionPlan.policy_snapshot map**:
`policy_snapshot["authorized_validation_profile_grant_v1"]`.

It is a **signed-off binding envelope created by the existing M2→M4 policy approval path**, not an arbitrary Domain field in a dictionary. Keep existing public Pydantic field shape and schema version as is for the *draft*; changing the canonical meaning of policy_snapshot still requires controlled cross-module approval and compatibility tests before deployment. Do **not** add a second optional top-level `ApprovedActionPlan` field or independent live PolicyRegistry lookup at M6.

### AuthorizedValidationProfileGrantV1 (typed internally; wire payload map)
```text
grant_schema_version: "1"
policy_decision_id: str
policy_snapshot_digest: str                # excludes this grant to avoid circular digest
grant_authority_ref: str                   # approved M2 rule authority, not registry existence
grant_id: str
plan_id: str
request_id: str
identity_scope: str
domain_id: str
validation_mode_floor: FAST | STANDARD | STRICT
profile_id: str
profile_version: str
profile_digest: str                        # exact immutable profile content hash
applicability:
  goal_ids: tuple[str, ...]                # subset of exact approved plan goals
  tool_refs: tuple[str, ...]               # explicit allowed Tool references; may be empty
issued_at: aware datetime
expires_at: aware datetime | None
issuer_proof_ref: str                      # verifiable binding to authenticated M2 approval producer
```
Mandatory: nonempty identity and ref strings, valid strict ISO-8601 aware times, ordered/canonical unique scope lists, exact version/digest, `expires_at>issued_at` when set. A grant is **authorization to interpret specific evidence/goal types under an approved validation rule**; it is **not** permission to execute Tools, make success claims, or skip evidence checks. Domain IDs and rule contents remain outside Core enums.

### Digest/proof chain
- `base_policy_digest = hash(canonical original PolicyDecision snapshot excluding grant)`.
- `grant_content_digest = hash(canonical grant fields except issuer_proof_ref)`.
- `issuer_proof_ref` resolves via existing trusted M2 approval binding to `policy_decision_id + base_policy_digest + grant_content_digest + plan/request/scope`.
- M4 approval seals an immutable full `policy_snapshot` including grant, with `approved_plan_digest` in existing approval evidence where available.
- M6 verifies both **authentic origin** and content digests, not merely a self-reported SHA. Opaque text claimed to be a signature is not trusted unless backed by existing authorized verifier.
- Avoid fabricating pre-existing cryptographic signing infrastructure; if issuer proof cannot be reliably verified in the current platform, status = `GRANT_AUTHORITY_UNVERIFIABLE` (fail closed) until approved authority-port implementation is supplied.

## 3. Exact producer / transport / consumer authority

| Layer | May do | Must not do |
|---|---|---|
| M2 policy authority | choose permitted profile+floor for exact current decision; emit immutable grant authorization evidence | choose by M6 Tool outcome; authorize M5 execution side effects |
| M4 approval boundary | bind M2 grant to exact plan/request/identity, ensure goal/tool applicability subset, seal snapshot | widen scope, reduce STRICT, select a different profile after approval |
| M5 | carry exact approved plan and provide observed ExecutionResult | reinterpret/reissue validation grants |
| M6 IU1 read-only resolver | verify grant provenance/version/digest/expiry/scope/profile snapshot; freeze exact binding | choose latest, infer ungranted profile, execute completion_condition string |
| Domain ValidationRegistry | immutable versioned profile lookup by exact ref, version, digest | grant authorization merely because profile exists |
| M7/M8 | consume later proof-bound ValidatedResult under safety barrier | treat grant as proof of business completion |

This does not require adding new M2 runtime state machine. Producer can be an injection extension of M2/M4 approval contract with independently tested evidence.

## 4. Preconditions, precedence and reject semantics

ValidationRuleBindingResolver:
1. First validate M5/M4 `plan_id`, `request_id` and RuntimeContext `identity_scope/session` equality.
2. Read only `authorized_validation_profile_grant_v1` from the **approved plan snapshot**; reject unknown grant versions or malformed fields. Never grant from current ambient registry or M6 configuration alone.
3. Verify M2 producer authority evidence, policy_decision_id and base-policy digest; verify approved plan binding; exact `identity_scope`, plan_id, request_id, domain_id and covered goal/tool refs. Mismatch => fail closed.
4. Check expiry/revocation at validation admission using trusted clock and separately authorized revocation view; no inferred evidence observation time. If revocation cannot be reliably queried, do not claim a revocation guarantee; required online policy check should block.
5. Resolve exact `profile_id@profile_version#profile_digest` from an immutable registry snapshot. Missing/changed/disabled/ambiguous => `GRANT_PROFILE_UNAVAILABLE`, not fallback.
6. Mode floor = max(M2 grant, any currently applicable stronger authorized safety restriction); current context cannot reduce strictness.
7. Freeze policy/profile/authority proof digests for validation ID and replay; same evaluation reuses same bound proof, fresh evaluation rechecks current applicability/expiry. Already validated results are still constrained by live M2 safety on consumption.

Error reason codes:
```text
GRANT_MISSING
GRANT_MALFORMED
GRANT_VERSION_UNSUPPORTED
GRANT_AUTHORITY_UNVERIFIABLE
GRANT_PLAN_REQUEST_SCOPE_MISMATCH
GRANT_APPLICABILITY_MISMATCH
GRANT_POLICY_DIGEST_MISMATCH
GRANT_EXPIRED_OR_REVOKED
GRANT_PROFILE_UNAVAILABLE
GRANT_MODE_DOWNGRADE_ATTEMPT
```
For a **valid canonical inbound** but absent/mismatched grant, return ADMITTED with rule binding UNRESOLVED and reason code; no positive goal/fact/claim promotion. For structurally corrupt/contradictory core identity, use IU1 REJECTED input path. A separate explicit mandatory-profile policy may elevate absent grant to REJECTED, but that constraint itself must be authenticated; don't improvise.

## 5. Circular-binding resolution / temporal authority

Potential chicken-and-egg: M2 selects authorization before M4 finalizes plan goal IDs and plan ID. **M2 must not issue a purported plan-bound grant on unknown future identifiers.**

Proposed controlled sequence:
1. M2 emits `ValidationProfileAuthorizationIntent` scoped to request/identity/policy decision/domain and permitted profile ref + mode floor, with authenticity proof.
2. M4 produces a candidate plan, checks goal/tool applicability, and during final approval **binds** M2 intent into `AuthorizedValidationProfileGrantV1` with concrete plan_id/goal_ids/tool_refs; M4 may narrow but not expand authority.
3. M4 approval evidence binds intent digest, final grant digest and approved plan digest; before any execution M5 consumes exactly that ApprovedPlan.
4. M6 checks producer chain. Unmatched intent/grant/approval evidence => unresolved/fail-closed.

This uses two **process stages** but **one persisted grant transport** in ApprovedPlan.policy_snapshot, avoiding unauthorized future-plan references in M2. The cryptographic/authenticity mechanism is an approved **port requirement**, not assumed already present.

## 6. Backward compatibility and migration

- Pre-amendment/historical plans without field: `GRANT_MISSING` → authorized-rule binding UNRESOLVED, no business-success claim. Existing M5 execution results remain valid execution observations.
- Existing M2 PolicyDecision schema unchanged initially; intent may be emitted as a companion authority-bound approval artifact only through a controlled producer extension. If canonical additions prove essential, submit a **separate** producer Schema amendment before implementation; this draft is not self-authorizing.
- Add field in policy_snapshot only; no new M5 retry, registry, durability engine, or Agent Loop Controller. Reject non-versioned old grants and unverifiable proof.
- Mixed mode: only newly approved plans carrying verifiable grants can support positive domain Goal validation. No migration script may fabricate historical grants.
- Separate user-visible claims remain guarded by downstream IU6 ClaimPolicy and IU8/M7/M8 proof handshake.

## 7. Negative and positive contract gates

| Gate | Fixture | Required result |
|---|---|---|
| G01 | M2 authorization intent → M4 exact plan binding | one verified grant for exact plan/scope |
| G02 | normal current ApprovedPlan lacks grant | UNRESOLVED, no success |
| G03 | arbitrary grant dictionary with no issuer proof | GRANT_AUTHORITY_UNVERIFIABLE |
| G04 | wrong plan/request/scope | fail-closed, no cross-user fact |
| G05 | goal/tool not covered by grant | GRANT_APPLICABILITY_MISMATCH |
| G06 | mismatched policy digest / modified grant | fail-closed |
| G07 | profile version/digest changed, disabled or missing | GRANT_PROFILE_UNAVAILABLE, no latest |
| G08 | stricter M2 floor/current safety vs weaker profile | strictest applies |
| G09 | expired or confirmed revoked grant | block, no positive claim |
| G10 | exact replay has immutable original profile snapshot | same binding/digest |
| G11 | replay snapshot lost or digest differs | unresolved, not reselect latest |
| G12 | formerly approved plan without grant | never retroactively synthesize |
| G13 | repeated exact candidate approval | stable grant binding/ID independent of volatile trace event timestamps |
| G14 | failed producer proof availability | unavailable/blocked, no implicit trust |
| G15 | M6 has rule resolver but no authenticated grant | no rule authority, no Tool calls |
| G16 | Agent Loop result consumed | grant never authorizes replan, new action passes M2/M4/M5 |

## 8. Controlled-change inventory and decisions still needed

| Artifact | Proposed diff | Owner | Gate |
|---|---|---|---|
| M2 policy producer extension | emit authenticated request-scoped ValidationProfileAuthorizationIntent | M2 | separate controlled amendment approval |
| M4 plan approval | intersect M2 intent with concrete plan scope; attach only field `authorized_validation_profile_grant_v1` to existing policy_snapshot; bind approval evidence | M4 | producer contract review |
| M6 rule consumer | exact grant parser, verifier, profile binder | M6-IU1 Slice B | after D-M6-IU1-01 is accepted |
| tests | G01–G16, regression M2/M4/M5 policy and serialization | shared | four gates and negative oracles |
| public Canonical `ValidatedResult` | no change | M6 | none in this amendment |

**Design review questions:** (a) locate an existing authenticated approval/authority-proof port or design minimum new bounded port; (b) verify plan approval can carry request-scoped intent into final plan without rewriting frozen M2/M4 contract; (c) exact `domain_id` source and approved intent scope; (d) revocation authority and offline behavior; (e) digest serialization standard consistent with existing approval evidence.

## 9. Gate status

```text
CA-M6-IU1-06 DESIGN = V0.1 SUBMITTED
D-M6-IU1-01 PRODUCER CONTRACT = SPECIFIED / NOT IMPLEMENTED
CA-M6-IU1-06 INDEPENDENT DESIGN REVIEW = PENDING
M6-IU1 SLICE B IMPLEMENTATION = BLOCKED
M6-IU1 WHOLE-UNIT IMPLEMENTATION AUTHORIZATION = NOT_GRANTED
M6 AGENT LOOP ANTI-OVERBUILDING = PRESERVED
```

Next: `CA-M6-IU1-06 Independent Design Review`, particularly authority-proof bootstrap and M2 intent→M4 concrete-plan binding, before changing any live public contract.
