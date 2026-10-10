"""GA-01C DIAG-02 independent test-only initial state admission tests."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, cast
from datetime import UTC, datetime, timedelta

import pytest

from agent_core.iteration import AgentRunBinding
from tests.ga01.initial_evidence import (
    InitialEvidenceError,
    InitialEvidenceRecord,
    SyntheticInitialEvidenceProvider,
    admit_initial_evidence,
)
from tests.orchestration_stubs import build_runtime_input

_NOW = datetime(2026, 10, 10, 1, tzinfo=UTC)


def _fixture() -> tuple[AgentRunBinding, InitialEvidenceRecord]:
    binding = AgentRunBinding.from_input(
        build_runtime_input(text="Check this synthetic evidence"),
        run_id="initial-evidence-fixture",
        domain_id="domain-evidence-fixture",
        domain_version="v1",
        binding_fingerprint="fingerprint-evidence",
    )
    record = InitialEvidenceRecord(
        evidence_id="evidence-in-store",
        run_id=binding.run_id,
        subject_id=binding.subject_id,
        session_id=binding.session_id,
        identity_scope=binding.identity_scope,
        tenant_id=binding.tenant_id,
        domain_id=binding.domain_id,
        domain_version=binding.domain_version,
        domain_fingerprint=binding.binding_fingerprint,
        record_revision=1,
        observed_at=_NOW - timedelta(hours=1),
        expires_at=_NOW + timedelta(hours=1),
        status="AVAILABLE_UNVERIFIED",
        source_kind="ISOLATED_SYNTHETIC_STATE_STORE",
    )
    return binding, record


def test_initial_evidence_admission_requires_store_and_valid_scope() -> None:
    binding, record = _fixture()
    assert (
        admit_initial_evidence(
            binding, SyntheticInitialEvidenceProvider({}), record.evidence_id, now=_NOW
        )
        is None
    )
    accepted = admit_initial_evidence(
        binding,
        SyntheticInitialEvidenceProvider({record.evidence_id: record}),
        record.evidence_id,
        now=_NOW,
    )
    assert accepted is not None
    assert accepted.status == "AVAILABLE_UNVERIFIED"
    assert accepted.revision == 1


@pytest.mark.parametrize(
    "change",
    [
        {"run_id": "another-run"},
        {"subject_id": "another-subject"},
        {"session_id": "another-session"},
        {"identity_scope": "another-scope"},
        {"tenant_id": "another-tenant"},
        {"domain_id": "another-domain"},
        {"domain_version": "v2"},
        {"domain_fingerprint": "another-fingerprint"},
        {"record_revision": 0},
        {"source_kind": "USER_TEXT"},
        {"observed_at": _NOW + timedelta(minutes=1)},
        {"expires_at": _NOW},
        {"observed_at": datetime(2026, 10, 10, 1)},
    ],
)
def test_initial_evidence_rejects_foreign_stale_untrusted_or_invalid(
    change: dict[str, object],
) -> None:
    binding, record = _fixture()
    updated = replace(record, **cast(Any, change))
    with pytest.raises(InitialEvidenceError):
        admit_initial_evidence(
            binding,
            SyntheticInitialEvidenceProvider({record.evidence_id: updated}),
            record.evidence_id,
            now=_NOW,
        )


@pytest.mark.parametrize("status", ["MISSING", "UNKNOWN", "CONTRADICTORY"])
def test_uncertain_initial_evidence_never_excludes_collection(status: str) -> None:
    binding, record = _fixture()
    updated = replace(record, status=status)
    assert (
        admit_initial_evidence(
            binding,
            SyntheticInitialEvidenceProvider({record.evidence_id: updated}),
            record.evidence_id,
            now=_NOW,
        )
        is None
    )
