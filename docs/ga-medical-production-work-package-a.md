# GA Medical Production — Work Package A: Execution Authority Boundary

Baseline: main merge commit `c6762e23e66968eb6f2087c52644461dc9865f96`.

## Implemented, scoped acceptance prototype

- `MedicalSafetyApplication.run` evaluates an explicit Host-injected deterministic preflight before invoking retrieval, planning, or tool access.
- A clearly escalated synthetic request returns `MEDICAL_HUMAN_REVIEW_REQUIRED` and executes **zero** Agent steps. Missing input fails closed.
- A permitted routine request obtains an HMAC-SHA256 `MedicalExecutionPermit` from `MedicalExecutionAuthority`, binding request, run, subject, identity scope, session, exact domain fingerprint and policy version.
- `UnifiedDomainApplication._run_checked` checks and consumes that authorization **at its own entry**, prior to invoking the existing `DomainApplication.run`.
- Invalid signatures, expired permits, repeated permits, cross-domain or cross-policy reuse, mismatched request/run/session, and missing authorization are rejected.
- Existing synthetic chronic-management and mental-wellbeing live model E2E use the explicit Host authority; no clinical patient data is involved.

## P0 production blockers: NOT production-ready

This in-process HMAC issuer is an **integration prototype**, not a production trust boundary.

1. The issuer currently lives in the same Python process as the application. Untrusted code in that process must not be able to create another issuer or call lower-level runtime components. Production requires a separate trusted Host, explicit dependency ownership, and inaccessible signing keys.
2. Replay prevention uses a local `set`, not durable or atomic cross-worker storage. Production requires a unique claim identifier and durable compare-and-set consumption in a database shared across workers; crashes/retries must have defined semantics.
3. Direct `DomainApplication.run` access and direct execution Tool/M6 ports are not sealed by this adapter. Host service exposure must allow execution only via a verified operation-bound permission, and physical tool invocation must recheck that permission.
4. `MedicalPreflightPolicy` uses synthetic phrase matching and a descriptive policy version; it is not a reviewed, immutable clinical risk rule bundle. Production requires medical governance, negative/uncertain/multilingual/multi-turn assessment and independently approved decision logic.
5. No actual human-handoff delivery, persistence, receiving acknowledgement, retries, or operator confirmation is included. A `BLOCK` reason cannot be represented as successful human reception.
6. The current prototype consumes a permit before an Agent run. A production design needs cancellation/revalidation and reauthorization semantics for long-running and resumed runs, not one initial check for all future tool steps.

## Admission decision

Code may be accepted as **GA-A scoped application integration/evidence**, conditional on passing full CI and independent review. Never interpret it as authorization to launch a real medical production workload. The release gate remains **BLOCKED** until all P0 items are addressed and independently tested.
