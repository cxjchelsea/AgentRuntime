"""GA-07 reusable, non-authoritative domain knowledge capability contracts.

Application-owned retrieval implementations provide records. This module
never issues Host provenance, M2 policy decisions, or M6 execution grants.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass

_TOKEN = re.compile(r"[a-z0-9_]+", re.ASCII)
_SUSPICIOUS = re.compile(
    r"ignore (all |any )?(previous|prior|system) instructions|"
    r"system prompt|developer message|you are now|"
    r"override (the )?(policy|instructions)|"
    r"reveal (the )?(secret|password|system)|"
    r"<\|im_start\|>|\[inst\]|execute (the )?(tool|command)",
    re.IGNORECASE,
)


class KnowledgeContractError(ValueError):
    """Invalid capability input; no evidence or model invocation is allowed."""


@dataclass(frozen=True, slots=True)
class DomainScope:
    domain_id: str
    binding_fingerprint: str


@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    domain_id: str
    binding_fingerprint: str
    document_id: str
    source_ref: str
    content_sha256: str
    content: str


@dataclass(frozen=True, slots=True)
class KnowledgeAdmission:
    documents: tuple[KnowledgeDocument, ...]
    reason: str

    @property
    def accepted(self) -> bool:
        return bool(self.documents)


# The caller supplies search; this is a capability port, NOT a source trust claim.
KnowledgeRetriever = Callable[
    [DomainScope, str, int], tuple[KnowledgeDocument, ...]
]


class DomainKnowledgeCapability:
    """Bind one exact domain/run scope to a replaceable retrieval provider."""

    def __init__(self, scope: DomainScope, retriever: KnowledgeRetriever) -> None:
        if (
            type(scope) is not DomainScope
            or not scope.domain_id
            or not re.fullmatch(r"[0-9a-f]{64}", scope.binding_fingerprint)
            or not callable(retriever)
        ):
            raise KnowledgeContractError("invalid domain knowledge scope")
        self.scope = scope
        self._retriever = retriever

    def retrieve_and_admit(
        self, query: str, *, limit: int = 2
    ) -> KnowledgeAdmission:
        if type(query) is not str or len(query) > 256 or limit not in {1, 2, 3}:
            raise KnowledgeContractError("invalid knowledge request")
        terms = tuple(dict.fromkeys(_TOKEN.findall(query.lower())))
        if not 2 <= len(terms) <= 8:
            return KnowledgeAdmission((), "UNSUPPORTED_QUERY")
        result = self._retriever(self.scope, query, limit)
        if type(result) is not tuple or len(result) > limit:
            raise KnowledgeContractError("invalid knowledge provider output")
        if not result:
            return KnowledgeAdmission((), "NO_EVIDENCE")
        accepted: list[KnowledgeDocument] = []
        for item in result:
            if (
                type(item) is not KnowledgeDocument
                or item.domain_id != self.scope.domain_id
                or item.binding_fingerprint != self.scope.binding_fingerprint
                or type(item.content) is not str
                or not 1 <= len(item.content) <= 2048
                or type(item.source_ref) is not str
                or not 1 <= len(item.source_ref) <= 256
                or type(item.document_id) is not str
                or not 1 <= len(item.document_id) <= 128
                or type(item.content_sha256) is not str
                or hashlib.sha256(item.content.encode("utf-8")).hexdigest()
                != item.content_sha256
            ):
                return KnowledgeAdmission((), "UNVERIFIED_EVIDENCE")
            if _SUSPICIOUS.search(item.content):
                return KnowledgeAdmission((), "SUSPECT_INSTRUCTION")
            if set(terms).issubset(set(_TOKEN.findall(item.content.lower()))):
                accepted.append(item)
        if not accepted:
            return KnowledgeAdmission((), "LOW_RELEVANCE")
        return KnowledgeAdmission(tuple(accepted), "ADMITTED")


def build_domain_model_messages(
    *,
    system_instruction: str,
    task_payload: dict[str, object],
    admission: KnowledgeAdmission,
) -> tuple[dict[str, str], ...]:
    """Construct role-separated model input from admitted, lower-trust facts.

    The instruction is supplied by the Application, not from retrieved data.
    Retrieved documents cannot modify roles, strategies, or permissions.
    """
    if (
        type(system_instruction) is not str
        or not 20 <= len(system_instruction) <= 2048
        or type(task_payload) is not dict
        or type(admission) is not KnowledgeAdmission
        or not admission.accepted
    ):
        raise KnowledgeContractError("model context preconditions failed")
    docs = [
        {
            "domain_id": d.domain_id,
            "document_id": d.document_id,
            "source_ref": d.source_ref,
            "sha256": d.content_sha256,
            "text": d.content,
        }
        for d in admission.documents
    ]
    try:
        task = json.dumps(task_payload, ensure_ascii=True, sort_keys=True)
        evidence = json.dumps(
            {"trust_level": "UNTRUSTED_RETRIEVAL_DATA", "documents": docs},
            ensure_ascii=True,
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise KnowledgeContractError("model payload not JSON serializable") from exc
    if len(task) > 4096 or len(evidence) > 4096:
        raise KnowledgeContractError("model payload exceeds limits")
    return (
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": "TASK_JSON=" + task},
        {"role": "user", "content": "EVIDENCE_JSON=" + evidence},
    )
