"""GA-05 isolated *real SQLite FTS5* domain-scoped knowledge retrieval.

No synthetic in-package knowledge fact is considered evidence. Callers query
actual indexed documents. Source and domain bindings are test-scoped; the
SQLite index and any source label are NOT a production trusted publisher.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass

from agent_core.sandbox_domain_assembly import (
    SandboxAssemblyError,
    SandboxDomainBinding,
)

_TOKEN = re.compile(r"[A-Za-z0-9_]+", re.ASCII)


@dataclass(frozen=True, slots=True)
class IndexedDocument:
    domain_id: str
    document_id: str
    source_ref: str
    text: str


@dataclass(frozen=True, slots=True)
class RetrievedEvidence:
    domain_id: str
    binding_fingerprint: str
    document_id: str
    source_ref: str
    sha256: str
    snippet: str


class SandboxFTSIndex:
    """Isolated in-memory real inverted index, with exact domain/binding filters."""

    def __init__(self) -> None:
        self._db = sqlite3.connect(":memory:")
        self._db.execute(
            "CREATE VIRTUAL TABLE docs USING fts5("
            "domain_id UNINDEXED, binding_id UNINDEXED, document_id UNINDEXED, "
            "source_ref UNINDEXED, sha256 UNINDEXED, body)"
        )
        self._seen: set[tuple[str, str, str]] = set()

    def add(self, binding: SandboxDomainBinding, doc: IndexedDocument) -> None:
        if (
            type(binding) is not SandboxDomainBinding
            or type(doc) is not IndexedDocument
            or doc.domain_id != binding.domain_id
            or not doc.document_id
            or not doc.source_ref
            or not doc.text.strip()
            or len(doc.text) > 2048
            or len(doc.source_ref) > 256
        ):
            raise SandboxAssemblyError("invalid scoped knowledge document")
        key = (binding.domain_id, binding.binding_fingerprint, doc.document_id)
        if key in self._seen:
            raise SandboxAssemblyError("duplicate knowledge document")
        self._db.execute(
            "INSERT INTO docs(domain_id,binding_id,document_id,source_ref,sha256,body)"
            " VALUES (?,?,?,?,?,?)",
            (
                binding.domain_id,
                binding.binding_fingerprint,
                doc.document_id,
                doc.source_ref,
                hashlib.sha256(doc.text.encode("utf-8")).hexdigest(),
                doc.text,
            ),
        )
        self._seen.add(key)

    def retrieve(
        self, binding: SandboxDomainBinding, query: str, *, limit: int = 2
    ) -> tuple[RetrievedEvidence, ...]:
        if (
            type(binding) is not SandboxDomainBinding
            or type(query) is not str
            or len(query) > 256
            or limit not in {1, 2, 3}
        ):
            raise SandboxAssemblyError("invalid retrieval request")
        terms = _TOKEN.findall(query.lower())
        if not terms or len(terms) > 10:
            return ()
        # Quoted FTS tokens from strict ASCII lexer: no caller MATCH operators.
        match = " OR ".join('"' + term + '"' for term in terms)
        rows = self._db.execute(
            "SELECT domain_id,binding_id,document_id,source_ref,sha256,body "
            "FROM docs WHERE docs MATCH ? AND domain_id=? AND binding_id=? "
            "ORDER BY rank LIMIT ?",
            (match, binding.domain_id, binding.binding_fingerprint, limit),
        ).fetchall()
        evidence: list[RetrievedEvidence] = []
        for domain, fingerprint, doc_id, source, digest, body in rows:
            if (
                domain != binding.domain_id
                or fingerprint != binding.binding_fingerprint
                or hashlib.sha256(body.encode("utf-8")).hexdigest() != digest
            ):
                raise SandboxAssemblyError("retrieval integrity or domain mismatch")
            evidence.append(
                RetrievedEvidence(domain, fingerprint, doc_id, source, digest, body)
            )
        return tuple(evidence)
