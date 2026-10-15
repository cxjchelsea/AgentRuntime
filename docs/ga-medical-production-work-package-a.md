# GA Medical Production — Work Package A: Execution Authority Boundary

Baseline: main merge commit `c6762e23e66968eb6f2087c52644461dc9865f96`.

## Implemented, scoped acceptance prototype

- `MedicalSafetyApplication.run` evaluates an explicit Host-injected deterministic preflight before invoking retrieval, planning, or tool access.
- A clearly escalated synthetic request returns `MEDICAL_HUMAN_REVIEW_REQUIRED` and executes **zero** Agent steps. Missing input fails closed.
- A trusted medical safety decision signer produces a separately signed ALLOW clearance, bound to request text digest, request/run, subject/session, domain fingerprint and policy version. Permit issuance fails closed if the clearance is missing, forged, or scoped to different input. The current signer is a Host-injected integration component, NOT independently validated clinical adjudication.
- A permitted routine request obtains an HMAC-SHA256 `MedicalExecutionPermit` from `MedicalExecutionAuthority`, binding request, run, subject, identity scope, session, exact domain fingerprint and policy version.
- `UnifiedDomainApplication._run_checked` checks and consumes that authorization **at its own entry**, prior to invoking the existing `DomainApplication.run`.
- Invalid signatures, expired permits, repeated permits, cross-domain or cross-policy reuse, mismatched request/run/session, and missing authorization are rejected.
- Existing synthetic chronic-management and mental-wellbeing live model E2E use the explicit Host authority; no clinical patient data is involved.

## P0 production blockers: NOT production-ready

This in-process HMAC issuer is an **integration prototype**, not a production trust boundary.

1. The issuer currently lives in the same Python process as the application. Untrusted code in that process must not be able to create another issuer or call lower-level runtime components. Production requires a separate trusted Host, explicit dependency ownership, and inaccessible signing keys.
2. Replay prevention now uses an injectable atomic `consume_once` interface. An in-memory implementation supports unit testing, and a SQLite unique-index implementation demonstrates persistence/reopen behavior. Neither establishes production-grade cross-host deployment: require a reviewed database ownership/transaction contract, failure semantics, backup/restore handling and multi-worker race verification.
3. Direct `DomainApplication.run` access and direct execution Tool/M6 ports are not sealed by this adapter. Host service exposure must allow execution only via a verified operation-bound permission, and physical tool invocation must recheck that permission.
4. `MedicalPreflightPolicy` uses synthetic phrase matching and a descriptive policy version; it is not a reviewed, immutable clinical risk rule bundle. The separately signed ALLOW token binds this synthetic decision but does not make the underlying clinical decision safe. A production Host must isolate the independent safety signer from untrusted application/model code. Production requires medical governance, negative/uncertain/multilingual/multi-turn assessment and independently approved decision logic.
5. No actual human-handoff delivery, persistence, receiving acknowledgement, retries, or operator confirmation is included. A `BLOCK` reason cannot be represented as successful human reception.
6. The current prototype consumes a permit before an Agent run. A production design needs cancellation/revalidation and reauthorization semantics for long-running and resumed runs, not one initial check for all future tool steps.

## Admission decision

Code may be accepted as **GA-A scoped application integration/evidence**, conditional on passing full CI and independent review. Never interpret it as authorization to launch a real medical production workload. The release gate remains **BLOCKED** until all P0 items are addressed and independently tested.

## R2 targeted remediation evidence

- Linux `PosixPath` is accepted by the SQLite store using `isinstance(Path)`.
- SQLite uniqueness violations are identified by the explicit primary-key SQLite error code; unrelated integrity failures fail closed.
- Adversarial tests cover 16 concurrent attempts against two independent SQLite connections (one admission), storage unavailability, trigger-induced non-unique integrity error, and reopening the persistent database to reject replay.
- These integration checks do not attest PostgreSQL/MySQL production CAS, transaction ownership, multi-host isolation, or crash-recovery of a clinical external side effect.

## R1 and R3 acceptance limitations

A signed ALLOW clearance is currently created by an injected Host-designated signer after the synthetic preflight. The signer method does **not** independently implement a clinically approved policy decision; trusted process/key ownership is mandatory and not verified by this PR. The medical tool execution boundary / M6 permission is not wrapped by this permit, so external effects remain unavailable for production admission. Treat these as P0 blockers, not silently passed controls.

## R1/R3 application-level targeted remediation

- The Host-designated safety signer now checks its own configured synthetic rejection policy before minting ALLOW. The medical application rejects a signer whose rejection phrases differ from its bound preflight configuration. This is defense in depth, not an authoritative clinical safety service.
- The checked medical composition wraps the physical sandbox StepPort in `MedicalAuthorizedStep` after the signed permit is successfully consumed. Its tool call entry rejects an unarmed wrapper and a missing approved action. The underlying delegate must remain private to the trusted application composition root; direct access to that delegate or M6 tools is not ruled out by this application-level adapter.
- Acceptance requires tests and real Qwen CI on the exact PR HEAD. Independent Host/M6 authorization, approved clinical policy governance, and deployable distributed durable authority remain P0 production release blockers.
