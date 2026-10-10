"""GA-01C DIAG-02 test-only initial-evidence admission.

Provider assertions are based on a separately seeded synthetic evidence store,
not the user's sentence or the expected model action. No production M6 grant.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from agent_core.iteration import AgentRunBinding


class InitialEvidenceError(ValueError):
    """Invalid, stale or foreign evidence must not influence eligibility."""


@dataclass(frozen=True, slots=True)
class InitialEvidenceRecord:
    evidence_id: str
    run_id: str
    subject_id: str
    session_id: str
    identity_scope: str
    tenant_id: str | None
    domain_id: str
    domain_version: str
    domain_fingerprint: str
    record_revision: int
    observed_at: datetime
    expires_at: datetime
    status: str
    source_kind: str


@dataclass(frozen=True, slots=True)
class AcceptedInitialEvidence:
    evidence_id: str
    revision: int
    domain_fingerprint: str
    admitted_at: datetime
    status: str


class SyntheticInitialEvidenceProvider:
    """Only test composition can seed this provider; it cannot issue a grant."""

    def __init__(self, records: dict[str, InitialEvidenceRecord]) -> None:
        self._records = dict(records)

    def read(self, evidence_id: str) -> InitialEvidenceRecord | None:
        return self._records.get(evidence_id)


def admit_initial_evidence(
    binding: AgentRunBinding,
    provider: SyntheticInitialEvidenceProvider,
    evidence_id: str,
    *,
    now: datetime,
) -> AcceptedInitialEvidence | None:
    """Fail closed: absent/UNKNOWN evidence leaves both strategies eligible."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise InitialEvidenceError("admission clock must be timezone-aware")
    record = provider.read(evidence_id)
    if record is None:
        return None
    if (
        not record.evidence_id
        or record.evidence_id != evidence_id
        or record.run_id != binding.run_id
        or record.subject_id != binding.subject_id
        or record.session_id != binding.session_id
        or record.identity_scope != binding.identity_scope
        or record.tenant_id != binding.tenant_id
        or record.domain_id != binding.domain_id
        or record.domain_version != binding.domain_version
        or record.domain_fingerprint != binding.binding_fingerprint
        or record.record_revision < 1
        or record.source_kind != "ISOLATED_SYNTHETIC_STATE_STORE"
        or record.observed_at.tzinfo is None
        or record.expires_at.tzinfo is None
        or record.observed_at > now
        or now >= record.expires_at
        or record.expires_at <= record.observed_at
    ):
        raise InitialEvidenceError("initial evidence identity, revision or freshness invalid")
    if record.status in {"UNKNOWN", "MISSING", "CONTRADICTORY"}:
        return None
    if record.status != "AVAILABLE_UNVERIFIED":
        raise InitialEvidenceError("unknown evidence status")
    return AcceptedInitialEvidence(
        record.evidence_id,
        record.record_revision,
        record.domain_fingerprint,
        now,
        record.status,
    )
