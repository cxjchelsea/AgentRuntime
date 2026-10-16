"""Host physical gate rejects bypass before touching the executor."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from agent_core.domain_extension import DomainExtensionError
from agent_core.medical_execution_authority import (
    MedicalExecutionAuthority,
    MedicalSafetyDecisionSigner,
)
from agent_core.medical_physical_host import (
    InMemoryOperationClaimStore,
    PermitBoundMedicalOperationIssuer,
    SQLiteOperationClaimStore,
    TrustedMedicalOperationIssuer,
    TrustedMedicalPhysicalHost,
)
from tests.orchestration_stubs import build_runtime_input

SECRET = b"synthetic-physical-host-signing-key-at-least-32"
INPUT = {"synthetic": "data"}
SCOPE: Any = {
    "run_id": "r1",
    "request_id": "q1",
    "domain_fingerprint": "a" * 64,
    "identity_scope": "tenant1/patient1",
    "approved_plan_id": "p1",
    "step_execution_id": "s1",
    "tool_id": "synthetic.readonly",
    "logical_tool_call_id": "tc1",
    "input_payload": INPUT,
    "physical_attempt": 1,
    "operation_key": "op1",
    "operation_fingerprint": "f1",
}


def _kwargs(args: Any, **changes: Any) -> Any:
    return {**args, **changes}


def test_host_gate_denies_unscoped_forged_and_replayed_attempt() -> None:
    async def scenario() -> None:
        executor = AsyncMock()
        clock = lambda: 100.0
        issuer = TrustedMedicalOperationIssuer(SECRET, clock=clock)
        host = TrustedMedicalPhysicalHost(
            secret=SECRET,
            physical=executor,
            claims=InMemoryOperationClaimStore(),
            clock=clock,
        )
        args: Any = {**SCOPE, "idempotency_key": "idem1"}
        with pytest.raises(DomainExtensionError, match="required"):
            await host.execute(grant=None, **args)
        assert executor.execute_physical_attempt.await_count == 0
        grant = issuer.grant(**SCOPE)
        with pytest.raises(DomainExtensionError, match="signature"):
            await host.execute(grant=replace(grant, signature="0" * 64), **args)
        with pytest.raises(DomainExtensionError, match="scope mismatch"):
            await host.execute(grant=grant, **_kwargs(args, tool_id="foreign"))
        with pytest.raises(DomainExtensionError, match="scope mismatch"):
            await host.execute(
                grant=grant, **_kwargs(args, input_payload={"synthetic": "tampered"})
            )
        assert executor.execute_physical_attempt.await_count == 0
        await host.execute(grant=grant, **args)
        assert executor.execute_physical_attempt.await_count == 1
        with pytest.raises(DomainExtensionError, match="replay"):
            await host.execute(grant=grant, **args)
        assert executor.execute_physical_attempt.await_count == 1

    asyncio.run(scenario())


def test_host_gate_rejects_expired_and_foreign_identity() -> None:
    async def scenario() -> None:
        now = [100.0]
        executor = AsyncMock()
        issuer = TrustedMedicalOperationIssuer(SECRET, clock=lambda: now[0])
        host = TrustedMedicalPhysicalHost(
            secret=SECRET,
            physical=executor,
            claims=InMemoryOperationClaimStore(),
            clock=lambda: now[0],
        )
        args: Any = {**SCOPE, "idempotency_key": None}
        grant = issuer.grant(**SCOPE, ttl_seconds=1)
        with pytest.raises(DomainExtensionError, match="scope mismatch"):
            await host.execute(
                grant=grant, **_kwargs(args, identity_scope="tenant2/patient2")
            )
        now[0] = 101.0
        with pytest.raises(DomainExtensionError, match="expired"):
            await host.execute(grant=grant, **args)
        executor.execute_physical_attempt.assert_not_awaited()

    asyncio.run(scenario())


def test_sqlite_host_claim_persists_across_restart(tmp_path: Path) -> None:
    database = tmp_path / "physical-claims.sqlite"
    first = SQLiteOperationClaimStore(database)
    assert first.claim_once("nonce-one")
    reopened = SQLiteOperationClaimStore(database)
    assert not reopened.claim_once("nonce-one")


def test_sqlite_host_claim_competing_workers(tmp_path: Path) -> None:
    database = tmp_path / "physical-claims.sqlite"
    stores = [SQLiteOperationClaimStore(database) for _ in range(2)]

    def claim(index: int) -> bool:
        return stores[index % 2].claim_once("same-operation")

    with ThreadPoolExecutor(max_workers=8) as pool:
        result = list(pool.map(claim, range(16)))
    assert result.count(True) == 1
    assert result.count(False) == 15


def test_sqlite_host_claim_storage_failure_closed(tmp_path: Path) -> None:
    database = tmp_path / "physical-claims.sqlite"
    store = SQLiteOperationClaimStore(database)
    database.unlink()
    database.mkdir()
    with pytest.raises(DomainExtensionError, match="storage unavailable"):
        store.claim_once("new-operation")


def test_physical_operation_issuer_requires_signed_scoped_medical_run_permit() -> None:
    from dataclasses import replace as replace_signed

    medical_key = b"synthetic-medical-run-permit-issuer-key-32"
    decision_key = b"synthetic-medical-safety-decision-key-32"
    initial = build_runtime_input(text="ordinary synthetic followup")
    operation = {
        **SCOPE,
        "run_id": "scoped-run",
        "request_id": initial.request_id,
        "identity_scope": initial.identity_scope,
    }
    domain_id = "medical.chronic-management"
    version = "synthetic-reviewed-policy"
    clearance = MedicalSafetyDecisionSigner(
        decision_key, rejected_phrases=("urgent escalation",)
    ).approve(
        initial=initial,
        run_id="scoped-run",
        domain_id=domain_id,
        binding_fingerprint=operation["domain_fingerprint"],
        policy_version=version,
    )
    medical = MedicalExecutionAuthority(
        medical_key, decision_verifier_key=decision_key, clock=lambda: 100.0
    )
    permit = medical.issue(
        initial=initial, run_id="scoped-run", domain_id=domain_id,
        binding_fingerprint=operation["domain_fingerprint"],
        policy_version=version,
        clearance=clearance,
    )
    bound = PermitBoundMedicalOperationIssuer(
        operation_issuer=TrustedMedicalOperationIssuer(SECRET, clock=lambda: 100.0),
        medical_permit_verifier_key=medical_key,
        approved_plan_verifier=lambda run, plan, step, tool: (
            run == "scoped-run" and plan == "p1"
            and step == "s1" and tool == "synthetic.readonly"
        ),
    )

    def request(signed: Any, **changes: Any) -> Any:
        return {
            "permit": signed,
            "domain_id": domain_id,
            "policy_version": version,
            "subject_id": initial.subject_id,
            "session_id": initial.session_id,
            **operation,
            **changes,
        }

    assert bound.grant_from_permit(**request(permit)).signature
    with pytest.raises(DomainExtensionError, match="signature"):
        bound.grant_from_permit(
            **request(replace_signed(permit, signature="0" * 64))
        )
    with pytest.raises(DomainExtensionError, match="scope mismatch"):
        bound.grant_from_permit(**request(permit, identity_scope="another-tenant"))
    with pytest.raises(DomainExtensionError, match="scope mismatch"):
        bound.grant_from_permit(**request(permit, domain_id="medical.foreign"))
    with pytest.raises(DomainExtensionError, match="plan authorization denied"):
        bound.grant_from_permit(**request(permit, approved_plan_id="foreign-plan"))


def test_host_crash_unknown_outcome_never_replays_external_attempt(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        db = tmp_path / "crash-claims.sqlite"
        executor = AsyncMock()
        executor.execute_physical_attempt.side_effect = RuntimeError("unknown")
        issuer = TrustedMedicalOperationIssuer(SECRET, clock=lambda: 100.0)
        token = issuer.grant(**SCOPE)
        arguments: Any = {**SCOPE, "idempotency_key": "idem-crash"}
        host = TrustedMedicalPhysicalHost(
            secret=SECRET,
            physical=executor,
            claims=SQLiteOperationClaimStore(db),
            clock=lambda: 100.0,
        )
        with pytest.raises(RuntimeError, match="unknown"):
            await host.execute(grant=token, **arguments)
        restarted_host = TrustedMedicalPhysicalHost(
            secret=SECRET,
            physical=executor,
            claims=SQLiteOperationClaimStore(db),
            clock=lambda: 100.0,
        )
        with pytest.raises(DomainExtensionError, match="replay"):
            await restarted_host.execute(grant=token, **arguments)
        assert executor.execute_physical_attempt.await_count == 1

    asyncio.run(scenario())
