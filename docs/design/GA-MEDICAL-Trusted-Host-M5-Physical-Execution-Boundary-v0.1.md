# GA Medical Production — Trusted Host / M5 Physical Tool Boundary

Baseline: `main` at `26621bd5934d6304249b3f764be9e5cbb276b98f`, PR #147 post-merge push gates successful.

## Independent physical-readiness finding

**Decision: NOT PRODUCTION READY.** This is a targeted physical design and admission plan, not a production grant.

Existing executable paths:
- `MedicalSafetyApplication.run` → synthetic `MedicalPreflightPolicy` → signed `MedicalSafetyClearance` → signed `MedicalExecutionPermit`.
- `UnifiedDomainApplication._run_checked` consumes the permit **once per Agent run**, and passes `MedicalAuthorizedStep(authorized=True)` to `DomainApplication.run`.
- `MedicalAuthorizedStep.execute_and_observe` checks a constructor boolean but does not independently verify a per-operation Host grant or the identity of the physical tool.
- A caller with direct access to the original `StepPort`, `SandboxToolDispatcher.observe`, or `PhysicalToolAttemptExecutor` can bypass the wrapper. The sandbox dispatcher is expressly not a production external-effect adapter.
- `runtime.execution.permission` has M5 `ExecutionPermissionContextProvider` and `ExecutionPermissionEvaluator` contracts, and `runtime.execution.invocation` has `PhysicalToolAttemptExecutor` and `ApprovedToolInvoker` contracts, but there is no trusted medical physical operation authority wired into these implementations.
- A positive signed clearance is still based on a synthetic phrase policy, not clinically approved triage; missing phrase matching does not imply low risk.

## Single integrated implementation target

A **trusted Tool Host** must own all real external adapters and accept no direct calls from untrusted application code. The Host, not `MedicalAuthorizedStep`, is the enforcement point. Keep the generic Core contracts domain-neutral; a medical domain governance adapter supplies scoped policy and identity evidence.

1. **Admission/decision:** a separately controlled medical-safety service produces an immutable `ALLOW / DENY / UNKNOWN` decision; only `ALLOW` may enter execution authorization. Bind decision ID/hash, reviewed policy release ID, patient/identity scope, request text digest, request ID, run ID and domain package fingerprint. `DENY` or `UNKNOWN` must never mint a grant.
2. **Per-operation grant:** trusted Host issues a bounded grant for exact `tool_id`, `tool_version`, `approved_plan_id`, `step_execution_id`, `operation_key`, `operation_fingerprint`, caller scope and expiry; do not reuse the once-per-run permit as a physical attempt grant.
3. **Physical fence:** `PhysicalToolAttemptExecutor` adapter calls Host `authorize_and_claim` using the actual input digest and operation identity **immediately before** each physical attempt; Host atomically reserves the operation (CAS/idempotency and fencing epoch) before invoking the private external adapter. No grant or failed claim means zero external invocation. Stale, cross-domain, replay, unapproved tool, different payload, changed session, cancelled run and expired claims fail closed.
4. **Recovery semantics:** distinguish `NOT_STARTED`, `CLAIMED`, `UNKNOWN_EXTERNAL_OUTCOME`, `CONFIRMED`. Crash after dispatch is `UNKNOWN`; do not automatically retry external effects. Multi-worker and scheduler restart must honor durable fencing.
5. **Privacy and evidence:** persist immutable, redacted decision/grant/claim/attempt references; never log clinical request bodies, medical facts, or signing secrets; enforce patient/tenant isolation.
6. **Composition ownership:** physical adapter is registered only in trusted Host. Application receives a restricted proxy and cannot instantiate a raw adapter or access signing keys. Tests must invoke the physical Host entry directly to prove it refuses absent authorization.

## Acceptance matrix (all required, not equivalent to existing CI)

| Gate | Evidence | Status |
|---|---|---|
| PR #147 main engineering push | 1753 passed; Mypy/Ruff/format green | PASS |
| Domain swap in real model sandbox | GA-01C/GA-07 at PR exact HEAD | PASS (prior PR checks) |
| Independently governed medical ALLOW | Reviewed policy bundle + decision authority | BLOCKED |
| Host-owned per-tool, per-attempt grant | Actual physical adapter integration | BLOCKED |
| Direct raw-adapter bypass | Isolation test: zero effects even if application invokes raw interface | BLOCKED |
| Persistent cross-worker CAS/fencing | Real DB concurrent/crash/restart evidence | BLOCKED |
| Recovery/external effects | UNKNOWN handling and idempotency evidence | BLOCKED |
| Identity/privacy | Real Host auth, multi-tenant scope and audit tests | BLOCKED |

## Implementation boundary and non-goals

Keep this as **one coherent next implementation work package**. Do not split into micro-PRs for individual fields or revise the universal Agent's M4 planning logic. A medical-specific Host adapter should consume existing `runtime.execution.permission` and `runtime.execution.invocation` protocols; Core permission evaluation remains domain-neutral. Do not silently connect a real patient database, external notification system, or medical action until a verified Host can enforce operation grants.

No source file in this design-only PR claims to create a physical external execution fence. Final merge of this document, if separately authorized, indicates **design intake only**, never medical-production admission.
