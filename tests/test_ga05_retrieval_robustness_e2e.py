"""GA-05 real SQLite FTS retrieval, evidence isolation and live-model E2E.

No cloud account, production DB or real user information is used.
The opt-in real model test executes six synthetic tasks with mock side effects.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
from pathlib import Path

import pytest

from agent_core.chat_transport import ChatCompletionsConfig
from agent_core.runner import AgentRunCoordinator, LoopBudget, RunKind
from agent_core.sandbox_domain_assembly import SandboxAssemblyError
from tests.ga05_fts_retrieval import IndexedDocument, SandboxFTSIndex
from tests.ga05_retrieval_model_turn import RetrievedDomainTurn, retrieval_instruction
from tests.orchestration_stubs import build_runtime_input
from tests.test_ga03_domain_prompt_rule_knowledge_e2e import _CASES, _load_case

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="GA05 reuses secure Linux-only D2-A local package loader",
)

_DOCUMENTS = (
    (
        "inventory.reconcile",
        "stock-ledger-01",
        "sandbox://stock/ledger/01",
        "stock threshold count 7 available units in fictional warehouse",
    ),
    (
        "learning.plan",
        "notes-index-01",
        "sandbox://notes/index/01",
        "linear algebra notes index contains vector space lesson",
    ),
)
_QUERIES = ("stock threshold", "linear algebra")


def _domain(tmp_path: Path, number: int):
    root = tmp_path / f"domain-{number}"
    root.mkdir()
    return _load_case(root, _CASES[number])


def _index(domains) -> SandboxFTSIndex:
    index = SandboxFTSIndex()
    for domain, item in zip(domains, _DOCUMENTS):
        index.add(domain.m4.binding, IndexedDocument(*item))
    return index


def _config() -> ChatCompletionsConfig:
    return ChatCompletionsConfig(
        endpoint=os.environ["GA01C_LLM_URL"],
        model=os.environ["GA01C_LLM_MODEL"],
        api_key=os.environ.get("GA01C_LLM_API_KEY", ""),
        timeout_seconds=45,
        max_tokens=192,
    )


@pytest.mark.parametrize("number", [0, 1])
def test_ga05_real_index_returns_scoped_citable_hits(
    tmp_path: Path, number: int
) -> None:
    domains = (_domain(tmp_path, 0), _domain(tmp_path, 1))
    index = _index(domains)
    evidence = index.retrieve(domains[number].m4.binding, _QUERIES[number])
    assert len(evidence) == 1
    assert evidence[0].domain_id == _DOCUMENTS[number][0]
    assert evidence[0].document_id == _DOCUMENTS[number][1]
    assert evidence[0].source_ref == _DOCUMENTS[number][2]
    assert evidence[0].sha256
    instruction = retrieval_instruction(domains[number], evidence)
    assert evidence[0].snippet in instruction
    assert evidence[0].source_ref in instruction
    assert domains[number].knowledge_fact not in instruction
    assert _DOCUMENTS[1 - number][3] not in instruction


def test_ga05_foreign_domain_query_is_not_a_hit(tmp_path: Path) -> None:
    domains = (_domain(tmp_path, 0), _domain(tmp_path, 1))
    index = _index(domains)
    assert index.retrieve(domains[0].m4.binding, "linear algebra") == ()
    assert index.retrieve(domains[1].m4.binding, "stock threshold") == ()


def test_ga05_no_evidence_waits_without_model_or_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GA01C_LLM_URL", "http://127.0.0.1:9/v1/chat/completions")
    monkeypatch.setenv("GA01C_LLM_MODEL", "unreachable-test-only")
    domain = _domain(tmp_path, 0)
    index = SandboxFTSIndex()
    initial = build_runtime_input(text="unknown stock threshold")
    turn = RetrievedDomainTurn(
        initial, domain, index=index, query="stock threshold", config=_config()
    )
    outcome = asyncio.run(
        AgentRunCoordinator(turn, LoopBudget()).run(initial, turn.binding)
    )
    assert outcome.kind is RunKind.WAIT
    assert outcome.reason == "GA05_NO_SCOPED_RETRIEVAL_EVIDENCE"
    assert outcome.executions == 0
    assert turn.retrieval_transport is None
    assert turn.mock_calls == 0


def test_ga05_cross_domain_fingerprint_cannot_borrow_document(
    tmp_path: Path,
) -> None:
    domains = (_domain(tmp_path, 0), _domain(tmp_path, 1))
    index = _index(domains)
    from dataclasses import replace

    impersonator = replace(
        domains[1].m4.binding,
        domain_id=domains[0].m4.binding.domain_id,
    )
    assert index.retrieve(impersonator, _QUERIES[0]) == ()
    assert index.retrieve(impersonator, _QUERIES[1]) == ()


def test_ga05_rejects_duplicate_doc_and_invalid_query(tmp_path: Path) -> None:
    domain = _domain(tmp_path, 0)
    index = SandboxFTSIndex()
    doc = IndexedDocument(*_DOCUMENTS[0])
    index.add(domain.m4.binding, doc)
    with pytest.raises(SandboxAssemblyError, match="duplicate"):
        index.add(domain.m4.binding, doc)
    assert tuple(
        item.document_id
        for item in index.retrieve(domain.m4.binding, 'stock" OR anything')
    ) == ("stock-ledger-01",)
    with pytest.raises(SandboxAssemblyError, match="invalid retrieval"):
        index.retrieve(domain.m4.binding, "stock", limit=999)


def test_ga05_detects_forged_index_row_digest(tmp_path: Path) -> None:
    domain = _domain(tmp_path, 0)
    index = SandboxFTSIndex()
    index.add(domain.m4.binding, IndexedDocument(*_DOCUMENTS[0]))
    # Adversarial test-only database mutation; never trusted production auth.
    index._db.execute(
        "UPDATE docs SET sha256=? WHERE document_id=?",
        ("0" * 64, _DOCUMENTS[0][1]),
    )
    with pytest.raises((SandboxAssemblyError, sqlite3.OperationalError)):
        index.retrieve(domain.m4.binding, "stock threshold")


@pytest.mark.skipif(
    os.environ.get("GA05_LIVE_OPT_IN") != "1"
    or not os.environ.get("GA01C_LLM_URL")
    or not os.environ.get("GA01C_LLM_MODEL"),
    reason="requires explicit GA05 real model endpoint opt-in",
)
def test_ga05_real_qwen_cross_domain_retrieval_e2e(tmp_path: Path) -> None:
    async def evaluate() -> None:
        for repeat in range(3):
            roots = tmp_path / f"trial-{repeat}"
            roots.mkdir()
            domains = (_domain(roots, 0), _domain(roots, 1))
            index = _index(domains)
            for number, domain in enumerate(domains):
                initial = build_runtime_input(text=_CASES[number][2])
                turn = RetrievedDomainTurn(
                    initial,
                    domain,
                    index=index,
                    query=_QUERIES[number],
                    config=_config(),
                )
                result = await AgentRunCoordinator(
                    turn,
                    LoopBudget(
                        max_iterations=4,
                        max_executions=3,
                        max_decision_seconds=65,
                        max_execution_seconds=5,
                    ),
                ).run(initial, turn.binding)
                expected = 2 if domain.completion_after == "verify" else 1
                assert result.kind is RunKind.FINISH
                assert result.executions == expected
                assert len(turn.retrieved) == 1
                assert turn.retrieval_transport is not None
                assert len(turn.retrieval_transport.calls) == expected
                assert turn.selected_actions == [
                    domain.m4.collect_action,
                    *([domain.m4.verify_action] if expected == 2 else []),
                ]

    asyncio.run(evaluate())
