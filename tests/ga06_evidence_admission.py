"""GA-06 sandbox-only retrieval relevance admission and untrusted evidence envelope.

Intentional conservative lexical contract for two pinned demo domains; no
semantic relevance claims, no production source authentication or M6 rights.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from agent_core.sandbox_domain_assembly import SandboxAssemblyError, SandboxDomainBinding
from tests.ga05_fts_retrieval import RetrievedEvidence

_TERMS = re.compile(r"[a-z0-9_]+", re.ASCII)
# Conservative known attack indicators, not a general prompt-injection detector.
_UNSAFE = re.compile(
    r"ignore (all |any )?(previous|prior|system) instructions|"
    r"system prompt|developer message|"
    r"you are now|override (the )?(policy|instructions)|"
    r"reveal (the )?(secret|password|system)|"
    r"<\|im_start\|>|\[inst\]|"
    r"execute (the )?(tool|command)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class EvidenceAdmission:
    admitted: tuple[RetrievedEvidence, ...]
    reason: str
    requested_terms: tuple[str, ...]

    @property
    def accepted(self) -> bool:
        return bool(self.admitted)


def admit_evidence(
    binding: SandboxDomainBinding,
    query: str,
    hits: tuple[RetrievedEvidence, ...],
) -> EvidenceAdmission:
    """Fail closed for empty/partial/ambiguous matches or known injection markers.

    One must not infer authoritativeness from index-managed SHA. This only
    checks byte consistency and relevance under a narrow lexical demo policy.
    """
    if type(binding) is not SandboxDomainBinding or type(query) is not str:
        raise SandboxAssemblyError("invalid evidence admission request")
    terms = tuple(dict.fromkeys(_TERMS.findall(query.lower())))
    if not 2 <= len(terms) <= 8 or len(query) > 256:
        return EvidenceAdmission((), "GA06_QUERY_UNSUPPORTED", terms)
    if not hits or len(hits) > 3:
        return EvidenceAdmission((), "GA06_NO_RELEVANT_EVIDENCE", terms)

    good: list[RetrievedEvidence] = []
    for hit in hits:
        if (
            type(hit) is not RetrievedEvidence
            or hit.domain_id != binding.domain_id
            or hit.binding_fingerprint != binding.binding_fingerprint
            or not hit.source_ref.startswith("sandbox://")
            or not hit.document_id
            or type(hit.snippet) is not str
            or len(hit.snippet) > 2048
            or hashlib.sha256(hit.snippet.encode("utf-8")).hexdigest()
            != hit.sha256
        ):
            return EvidenceAdmission((), "GA06_UNVERIFIED_EVIDENCE", terms)
        if _UNSAFE.search(hit.snippet):
            return EvidenceAdmission((), "GA06_SUSPECT_INSTRUCTION", terms)
        document_terms = set(_TERMS.findall(hit.snippet.lower()))
        if not set(terms).issubset(document_terms):
            continue
        good.append(hit)
    if not good:
        return EvidenceAdmission((), "GA06_LOW_RELEVANCE", terms)
    return EvidenceAdmission(tuple(good), "GA06_EVIDENCE_ADMITTED", terms)


def lower_trust_user_context(admission: EvidenceAdmission) -> str:
    if type(admission) is not EvidenceAdmission or not admission.accepted:
        raise SandboxAssemblyError("no admitted evidence")
    items = [
        {
            "domain_id": e.domain_id,
            "source_ref": e.source_ref,
            "document_id": e.document_id,
            "sha256": e.sha256,
            "text": e.snippet,
        }
        for e in admission.admitted
    ]
    result = json.dumps(
        {"trust_level": "UNTRUSTED_RETRIEVAL_DATA", "documents": items},
        ensure_ascii=True,
        sort_keys=True,
    )
    if len(result) > 4096:
        raise SandboxAssemblyError("lower trust envelope oversized")
    return result
