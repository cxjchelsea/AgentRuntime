"""Host medical permit negative verification; no clinical patient data."""

from __future__ import annotations

from dataclasses import replace

import pytest

from agent_core.domain_extension import DomainExtensionError
from agent_core.medical_execution_authority import (
    MedicalExecutionAuthority,
    InMemoryMedicalPermitStore,
)
from tests.orchestration_stubs import build_runtime_input

SECRET = b"synthetic-host-fixture-key-32-bytes-long"
DOMAIN = "medical.chronic-management"
FINGERPRINT = "a" * 64
POLICY = "reviewed-fixture-v1"


def _scope(authority, initial, run_id="test-run"):
    return authority.issue(
        initial=initial,
        run_id=run_id,
        domain_id=DOMAIN,
        binding_fingerprint=FINGERPRINT,
        policy_version=POLICY,
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
    authority = MedicalExecutionAuthority(SECRET, clock=lambda: 100.0)
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
    authority = MedicalExecutionAuthority(SECRET, clock=lambda: 100.0)
    initial = build_runtime_input()
    permit = _scope(authority, initial)
    with pytest.raises(DomainExtensionError, match=message):
        _consume(authority, permit, initial, **overrides)


def test_medical_permit_rejects_foreign_request_and_identity():
    authority = MedicalExecutionAuthority(SECRET, clock=lambda: 100.0)
    initial = build_runtime_input()
    permit = _scope(authority, initial)
    with pytest.raises(DomainExtensionError, match="scope mismatch"):
        _consume(authority, permit, build_runtime_input(request_id="foreign"))
    with pytest.raises(DomainExtensionError, match="scope mismatch"):
        _consume(authority, permit, build_runtime_input(session_id="foreign"))


def test_medical_permit_rejects_expiration_and_forgery():
    current = [100.0]
    authority = MedicalExecutionAuthority(
        SECRET, clock=lambda: current[0], ttl_seconds=2
    )
    initial = build_runtime_input()
    original = _scope(authority, initial)
    with pytest.raises(DomainExtensionError, match="signature"):
        _consume(authority, replace(original, signature="0" * 64), initial)
    current[0] = 102.0
    with pytest.raises(DomainExtensionError, match="expired"):
        _consume(authority, original, initial)


def test_medical_permit_rejects_wrong_host_key():
    issuer = MedicalExecutionAuthority(SECRET, clock=lambda: 100.0)
    other = MedicalExecutionAuthority(
        b"different-synthetic-host-key-32-bytes", clock=lambda: 100.0
    )
    initial = build_runtime_input()
    with pytest.raises(DomainExtensionError, match="signature"):
        _consume(other, _scope(issuer, initial), initial)


def test_medical_permit_shared_store_rejects_cross_instance_replay():
    store = InMemoryMedicalPermitStore()
    issuer = MedicalExecutionAuthority(SECRET, clock=lambda: 100.0, store=store)
    verifier = MedicalExecutionAuthority(SECRET, clock=lambda: 100.0, store=store)
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
        SECRET, clock=lambda: 100.0, store=_RejectAllStore()
    )
    initial = build_runtime_input()
    with pytest.raises(DomainExtensionError, match="replay"):
        _consume(authority, _scope(authority, initial), initial)
