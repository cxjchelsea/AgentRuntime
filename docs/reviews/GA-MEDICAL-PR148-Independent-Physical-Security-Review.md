# PR #148 — Independent Physical Security Integration Review

Reviewed initial implementation at `7d8afe770ec709eb944fd4f9b9f2c7235cb926d6`; updated after stable-operation identity claim remediation. Scope: `agent_core/medical_physical_host.py`, corresponding tests and existing `runtime/execution/invocation.py` contracts.

## Findings (do not infer production clearance from green CI)

- **R1 / operation issuer bypass — OPEN, P0**: `TrustedMedicalOperationIssuer.grant` remains publicly callable with its secret in the same process. `PermitBoundMedicalOperationIssuer` checks run permit and invokes a fail-closed injected approved-plan verifier; however, there is no independently isolated Host process or proof that all callers must use this facade. Unit tests use a synthetic validator, not attested M4 plan data.
- **R2 / raw physical delegate bypass — OPEN, P0**: `TrustedMedicalPhysicalHost.execute` calls `PhysicalToolAttemptExecutor` after claim; the raw delegate can still be passed to and called by arbitrary application code. No deployment-enforced exclusive Host ownership, RPC identity, credential isolation, or restricted tool registration is established. Existing `SandboxToolDispatcher` is explicitly inert and cannot prove real external-effect isolation.
- **R3 / durable claim semantics — PARTIAL, P0**: `SQLiteOperationClaimStore` persists nonce uniqueness and rejects concurrent duplicate claims. This is useful **local** replay evidence only. It does not bind a stable operation identity across separately issued nonces, provide fencing epochs/leases, or provide a distributed production DB CAS authority. Host now derives its local claim from stable signed operation scope rather than nonce, including the input digest and attempt. Reissuance of the same exact operation is denied locally; different operation identities, multi-host distributed fencing and external idempotency are not yet governed.
- **R4 / crash-unknown state — PARTIAL, P0**: claiming before invocation prevents replay of the same grant after a simulated exception/restart, but a durable state machine with `UNKNOWN_EXTERNAL_OUTCOME` and reconciliation/side-effect evidence is not yet implemented.
- **R5 / clinical authority — OPEN, P0**: upstream `MedicalSafetyDecisionSigner` uses synthetic rejected phrases. This is not a clinically validated safety decision or independently governed policy release.

## Evidence admitted

- Signed run permit checked for signature, identity, request, domain binding, policy and expiration before calling the operation issuer facade.
- Injected approved-plan verifier must return literal `True`; negative and unavailable results fail closed.
- Signed physical grant covers run/request/identity, domain fingerprint, approved plan, step, exact tool and payload digest, physical attempt, operation IDs and expiration.
- SQLite local claim tests exercise persistent replay, concurrent unique-nonce claims and storage unavailable failure; simulated physical failure cannot reuse the same grant.

## Conclusion and integration admission

**APP-LEVEL INTEGRATION: IMPLEMENTED, CI verification pending exact HEAD.**
**INDEPENDENT PHYSICAL SECURITY: NOT ACCEPTED.**
**PRODUCTION ADMISSION: DENIED / HOLD.**

Before physical acceptance: deploy a separately controlled Host with exclusive external adapter and signing key custody; bridge to independently attested M4 plan ownership, use a durable distributed operation-key CAS/fencing and state recovery; test unauthorized *direct host RPC* and all network/side-effect paths; use clinically governed safety decisions. Do not merge this PR as an assertion of production safety, and do not connect patient data or live external-action adapters on the basis of these synthetic tests.
