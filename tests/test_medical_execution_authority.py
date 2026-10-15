"""Host medical permit negative verification; no clinical patient data."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from agent_core.domain_extension import DomainExtensionError
from agent_core.medical_execution_authority import (
    InMemoryMedicalPermitStore,
    MedicalExecutionAuthority,
    MedicalSafetyDecisionSigner,
    SQLiteMedicalPermitStore,
)
from tests.orchestration_stubs import build_runtime_input

SECRET = b"synthetic-host-fixture-key-32-bytes-long"
DOMAIN = "medical.chronic-management"
FINGERPRINT = "a" * 64
POLICY = "reviewed-fixture-v1"
DECISION_KEY = b"synthetic-safety-decision-key-32-bytes-long"


def _scope(authority, initial, run_id="test-run"):
    return authority.issue(
        initial=initial,
        run_id=run_id,
        domain_id=DOMAIN,
        binding_fingerprint=FINGERPRINT,
        policy_version=POLICY,
        clearance=MedicalSafetyDecisionSigner(DECISION_KEY, rejected_phrases=("urgent escalation",)).approve(
            initial=initial,
            run_id=run_id,
            domain_id=DOMAIN,
            binding_fingerprint=FINGERPRINT,
            policy_version=POLICY,
        ),
    )


def _consume(authority, permit, initial, **changes):
    args = {
        "initial": initial,
        "run_id": "test-run",
        "domain_id": DOMAIN,
        "binding_fingerprint": FINGERPRINT,
        "policy_version": POLICY,
    }
    args.update(changes)
    authority.consume(permit, **args)


def test_medical_permit_valid_once_and_replay_denied():
    authority = MedicalExecutionAuthority(
        SECRET, decision_verifier_key=DECISION_KEY, clock=lambda: 100.0
    )
    initial = build_runtime_input()
    permit = _scope(authority, initial)
    _consume(authority, permit, initial)
    with pytest.raises(DomainExtensionError, match="replay"):
        _consume(authority, permit, initial)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"run_id": "other-run"}, "scope mismatch"),
        ({"domain_id": "medical.mental-wellbeing"}, "scope mismatch"),
        ({"binding_fingerprint": "b" * 64}, "scope mismatch"),
        ({"policy_version": "obsolete-version"}, "scope mismatch"),
    ],
)
def test_medical_permit_rejects_foreign_scope(overrides, message):
    authority = MedicalExecutionAuthority(
        SECRET, decision_verifier_key=DECISION_KEY, clock=lambda: 100.0
    )
    initial = build_runtime_input()
    permit = _scope(authority, initial)
    with pytest.raises(DomainExtensionError, match=message):
        _consume(authority, permit, initial, **overrides)


def test_medical_permit_rejects_foreign_request_and_identity():
    authority = MedicalExecutionAuthority(
        SECRET, decision_verifier_key=DECISION_KEY, clock=lambda: 100.0
    )
    initial = build_runtime_input()
    permit = _scope(authority, initial)
    with pytest.raises(DomainExtensionError, match="scope mismatch"):
        _consume(authority, permit, build_runtime_input(request_id="foreign"))
    with pytest.raises(DomainExtensionError, match="scope mismatch"):
        _consume(authority, permit, build_runtime_input(session_id="foreign"))


def test_medical_permit_rejects_expiration_and_forgery():
    current = [100.0]
    authority = MedicalExecutionAuthority(
        SECRET,
        decision_verifier_key=DECISION_KEY,
        clock=lambda: current[0],
        ttl_seconds=2,
    )
    initial = build_runtime_input()
    original = _scope(authority, initial)
    with pytest.raises(DomainExtensionError, match="signature"):
        _consume(authority, replace(original, signature="0" * 64), initial)
    current[0] = 102.0
    with pytest.raises(DomainExtensionError, match="expired"):
        _consume(authority, original, initial)


def test_medical_permit_rejects_wrong_host_key():
    issuer = MedicalExecutionAuthority(
        SECRET, decision_verifier_key=DECISION_KEY, clock=lambda: 100.0
    )
    other = MedicalExecutionAuthority(
        b"different-synthetic-host-key-32-bytes",
        decision_verifier_key=DECISION_KEY,
        clock=lambda: 100.0,
    )
    initial = build_runtime_input()
    with pytest.raises(DomainExtensionError, match="signature"):
        _consume(other, _scope(issuer, initial), initial)


def test_medical_permit_shared_store_rejects_cross_instance_replay():
    store = InMemoryMedicalPermitStore()
    issuer = MedicalExecutionAuthority(
        SECRET, decision_verifier_key=DECISION_KEY, clock=lambda: 100.0, store=store
    )
    verifier = MedicalExecutionAuthority(
        SECRET, decision_verifier_key=DECISION_KEY, clock=lambda: 100.0, store=store
    )
    initial = build_runtime_input()
    permit = _scope(issuer, initial)
    _consume(verifier, permit, initial)
    with pytest.raises(DomainExtensionError, match="replay"):
        _consume(issuer, permit, initial)


class _RejectAllStore:
    def consume_once(self, nonce: str, expires_at: int) -> bool:
        del nonce, expires_at
        return False


def test_medical_permit_denies_when_atomic_store_cannot_admit():
    authority = MedicalExecutionAuthority(
        SECRET,
        decision_verifier_key=DECISION_KEY,
        clock=lambda: 100.0,
        store=_RejectAllStore(),
    )
    initial = build_runtime_input()
    with pytest.raises(DomainExtensionError, match="replay"):
        _consume(authority, _scope(authority, initial), initial)


def test_durable_sqlite_permit_prevents_replay_after_restart(tmp_path: Path):
    file = tmp_path / "medical-permits.sqlite"
    initial = build_runtime_input()
    first = MedicalExecutionAuthority(
        SECRET,
        decision_verifier_key=DECISION_KEY,
        clock=lambda: 100.0,
        store=SQLiteMedicalPermitStore(file),
    )
    permit = _scope(first, initial)
    _consume(first, permit, initial)
    reopened = MedicalExecutionAuthority(
        SECRET,
        decision_verifier_key=DECISION_KEY,
        clock=lambda: 100.0,
        store=SQLiteMedicalPermitStore(file),
    )
    with pytest.raises(DomainExtensionError, match="replay"):
        _consume(reopened, permit, initial)


def test_medical_permit_requires_trusted_allow_clearance():
    authority = MedicalExecutionAuthority(
        SECRET, decision_verifier_key=DECISION_KEY, clock=lambda: 100.0
    )
    initial = build_runtime_input(text="ordinary synthetic followup")
    with pytest.raises(DomainExtensionError, match="clearance required"):
        authority.issue(
            initial=initial,
            run_id="test-run",
            domain_id=DOMAIN,
            binding_fingerprint=FINGERPRINT,
            policy_version=POLICY,
        )


def test_medical_permit_rejects_mismatched_or_forged_safety_decision():
    authority = MedicalExecutionAuthority(
        SECRET, decision_verifier_key=DECISION_KEY, clock=lambda: 100.0
    )
    initial = build_runtime_input(text="ordinary synthetic followup")
    signer = MedicalSafetyDecisionSigner(DECISION_KEY, rejected_phrases=("urgent escalation",))
    clearance = signer.approve(
        initial=initial,
        run_id="test-run",
        domain_id=DOMAIN,
        binding_fingerprint=FINGERPRINT,
        policy_version=POLICY,
    )
    scope = dict(
        initial=initial,
        run_id="test-run",
        domain_id=DOMAIN,
        binding_fingerprint=FINGERPRINT,
        policy_version=POLICY,
    )
    with pytest.raises(DomainExtensionError, match="decision signature"):
        authority.issue(**scope, clearance=replace(clearance, signature="0" * 64))
    with pytest.raises(DomainExtensionError, match="decision scope mismatch"):
        authority.issue(
            **{**scope, "initial": build_runtime_input(text="changed medical request")},
            clearance=clearance,
        )


def test_sqlite_store_atomic_competing_consumers(tmp_path: Path):
    database = tmp_path / "competing.sqlite"
    one = SQLiteMedicalPermitStore(database)
    other = SQLiteMedicalPermitStore(database)

    def attempt(index: int) -> bool:
        store = one if index % 2 == 0 else other
        return store.consume_once("same-nonce", 1000)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(16)))
    assert results.count(True) == 1
    assert results.count(False) == 15


def test_sqlite_store_storage_unavailable_fails_closed(tmp_path: Path):
    database = tmp_path / "unavailable.sqlite"
    store = SQLiteMedicalPermitStore(database)
    database.unlink()
    database.mkdir()
    with pytest.raises(DomainExtensionError, match="storage unavailable"):
        store.consume_once("new-nonce", 1000)


def test_sqlite_store_non_unique_integrity_error_fails_closed(
    tmp_path: Path,
):
    database = tmp_path / "integrity.sqlite"
    store = SQLiteMedicalPermitStore(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TRIGGER deny_insert BEFORE INSERT "
            "ON medical_permit_consumption "
            "BEGIN SELECT RAISE(ABORT, 'other constraint'); END"
        )
    with pytest.raises(DomainExtensionError, match="storage integrity failure"):
        store.consume_once("new-nonce", 1000)


def test_host_safety_signer_does_not_sign_known_red_flag():
    signer = MedicalSafetyDecisionSigner(
        DECISION_KEY, rejected_phrases=("critical synthetic red flag",)
    )
    initial = build_runtime_input(text="critical synthetic red flag")
    with pytest.raises(DomainExtensionError, match="decision denied"):
        signer.approve(
            initial=initial,
            run_id="test-run",
            domain_id=DOMAIN,
            binding_fingerprint=FINGERPRINT,
            policy_version=POLICY,
        )
