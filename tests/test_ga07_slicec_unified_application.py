"""GA-07 Slice C unified app: same bootstrap, switched package, actual retrieval.

Test-only StepPort simulates effects. Package issuance and knowledge are local
synthetic fixtures; the real model path is explicitly opt-in.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from agent_core.chat_transport import ChatCompletionsConfig
from agent_core.domain_content import assemble_domain_content
from agent_core.domain_extension import DomainExtensionError
from agent_core.domain_knowledge import DomainScope, KnowledgeDocument
from agent_core.domain_package_loader import (
    HostPackageRootIssuer,
    HostPublishedGeneration,
    LocalPackageLoader,
)
from agent_core.domain_unified_application import (
    UnifiedDomainApplication,
    bootstrap_unified_domain_application,
)
from agent_core.runner import Decision, LoopBudget, ObservedFact, RunKind
from tests.ga05_fts_retrieval import IndexedDocument, SandboxFTSIndex
from tests.orchestration_stubs import build_runtime_input
from tests.test_ga03_domain_prompt_rule_knowledge_e2e import (
    _CASES,
    GA03Turn,
    _with_domain_assets,
)
from tests.test_ga05_retrieval_robustness_e2e import _DOCUMENTS, _QUERIES

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="D2-A sealed local package loader requires Linux",
)


def _snapshot(root: Path, case: tuple[str, ...]):
    root.mkdir()
    identity = _with_domain_assets(root, *case)
    record = HostPublishedGeneration(identity, str(root), True)
    issuer = HostPackageRootIssuer(
        (record,), publication_verifier=lambda published: published == record
    )
    with issuer.issue(identity.generation_id) as lease:
        return LocalPackageLoader().load(lease, identity)


def _config() -> ChatCompletionsConfig:
    return ChatCompletionsConfig(
        endpoint=os.environ.get(
            "GA01C_LLM_URL", "http://127.0.0.1:9/v1/chat/completions"
        ),
        model=os.environ.get("GA01C_LLM_MODEL", "offline-no-network"),
        api_key=os.environ.get("GA01C_LLM_API_KEY", ""),
        timeout_seconds=45,
        max_tokens=192,
    )


def _assembled(snapshot, index: SandboxFTSIndex, query: str):
    from agent_core.domain_application import bootstrap_domain_application

    binding = bootstrap_domain_application(snapshot).extension.binding
    scope = DomainScope(binding.domain_id, binding.binding_fingerprint)

    def provider(
        requested: DomainScope, text: str, limit: int
    ) -> tuple[KnowledgeDocument, ...]:
        if requested != scope:
            return ()
        # The SQLite demo index's binding protocol needs domain and fingerprint.
        from agent_core.sandbox_domain_assembly import assemble_sandbox_domain

        legacy = assemble_sandbox_domain(snapshot)
        hits = index.retrieve(legacy, text, limit=limit)
        return tuple(
            KnowledgeDocument(
                item.domain_id,
                item.binding_fingerprint,
                item.document_id,
                item.source_ref,
                item.sha256,
                item.snippet,
            )
            for item in hits
        )

    return bootstrap_unified_domain_application(
        snapshot, retriever=provider, query=query, model_config=_config()
    )


class _UnifiedSandboxTurn(GA03Turn):
    def __init__(self, initial, legacy, unified: UnifiedDomainApplication):
        super().__init__(initial, legacy, available=frozenset())
        self._unified = unified
        self._planner = unified.planner
        self._validator = unified.validator
        self._rechecker = unified.rechecker
        assert self.binding == unified.app.prepare(
            initial, run_id=f"sandbox-{legacy.m4.binding.domain_id}"
        )

    async def decide(
        self, current_input, iteration, observations: tuple[ObservedFact, ...]
    ) -> Decision:
        admitted = self._unified.knowledge.retrieve_and_admit(
            self._unified.model_transport._query
        )
        if not admitted.accepted:
            return Decision(iteration, "WAIT", reason=admitted.reason)
        self.evidence = tuple(d.content for d in admitted.documents)
        return await super().decide(current_input, iteration, observations)


def _legacy_content(snapshot):
    from agent_core.sandbox_domain_assembly import assemble_sandbox_domain
    from tests.ga03_domain_content_assembly import assemble_ga03_domain

    return assemble_ga03_domain(assemble_sandbox_domain(snapshot))


@pytest.mark.parametrize("number", [0, 1])
def test_unified_package_content_and_scope(tmp_path: Path, number: int) -> None:
    snapshot = _snapshot(tmp_path / f"domain-{number}", _CASES[number])
    index = SandboxFTSIndex()
    unified = _assembled(snapshot, index, _QUERIES[number])
    assert unified.content.focus == _CASES[number][2]
    assert unified.content.required_knowledge == _CASES[number][3]
    assert unified.content.knowledge_fact == _CASES[number][4]
    assert unified.content.completion_after == _CASES[number][5]
    assert unified.knowledge.scope.binding_fingerprint == (
        unified.app.extension.binding.binding_fingerprint
    )
    assert len(unified.app.extension.action_ids) == 2
    assert len(unified.app.extension.strategy_actions) == 2


def test_unified_no_retrieval_waits_without_model_or_tool(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path / "inventory", _CASES[0])
    unified = _assembled(snapshot, SandboxFTSIndex(), _QUERIES[0])
    initial = build_runtime_input(text="synthetic stock threshold")
    turn = _UnifiedSandboxTurn(initial, _legacy_content(snapshot), unified)
    result = asyncio.run(
        unified.run(
            initial,
            run_id="sandbox-inventory.reconcile",
            step=turn,
            budget=LoopBudget(),
        )
    )
    assert result.kind is RunKind.WAIT
    assert result.reason == "NO_EVIDENCE"
    assert result.executions == 0
    assert turn.mock_calls == 0


def test_unified_rejects_same_binding_with_foreign_m4_before_decision(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path / "inventory", _CASES[0])
    unified = _assembled(snapshot, SandboxFTSIndex(), _QUERIES[0])
    initial = build_runtime_input(text="synthetic stock threshold")
    turn = _UnifiedSandboxTurn(initial, _legacy_content(snapshot), unified)
    setattr(turn, "_planner", object())  # Same binding, wrong planner.
    with pytest.raises(DomainExtensionError, match="M4 binding mismatch"):
        asyncio.run(
            unified.run(
                initial,
                run_id="sandbox-inventory.reconcile",
                step=turn,
                budget=LoopBudget(),
            )
        )
    assert turn.mock_calls == 0


def test_unified_rule_knowledge_mismatch_rejected(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path / "inventory", _CASES[0])
    rule = next(a for a in snapshot.assets if a.ref.kind == "rule")
    altered = replace(
        rule,
        content_bytes=b'{"required_knowledge":"foreign","completion_after":"verify"}',
    )
    tampered = replace(
        snapshot,
        assets=tuple(altered if asset is rule else asset for asset in snapshot.assets),
    )
    from agent_core.domain_application import bootstrap_domain_application

    with pytest.raises(DomainExtensionError, match="digest"):
        app = bootstrap_domain_application(tampered)
        assemble_domain_content(tampered, app.extension)


@pytest.mark.skipif(
    os.environ.get("GA07C_LIVE_OPT_IN") != "1"
    or not os.environ.get("GA01C_LLM_URL")
    or not os.environ.get("GA01C_LLM_MODEL"),
    reason="explicit GA07C live inference opt-in required",
)
def test_unified_two_package_real_model_application_e2e(tmp_path: Path) -> None:
    async def evaluate() -> None:
        for repeat in range(3):
            for number in (0, 1):
                root = tmp_path / f"trial-{repeat}-{number}"
                snapshot = _snapshot(root, _CASES[number])
                legacy = _legacy_content(snapshot)
                index = SandboxFTSIndex()
                index.add(legacy.m4.binding, IndexedDocument(*_DOCUMENTS[number]))
                unified = _assembled(snapshot, index, _QUERIES[number])
                initial = build_runtime_input(text=_CASES[number][2])
                turn = _UnifiedSandboxTurn(initial, legacy, unified)
                outcome = await unified.run(
                    initial,
                    run_id=f"sandbox-{_CASES[number][0]}",
                    step=turn,
                    budget=LoopBudget(
                        max_iterations=4,
                        max_executions=3,
                        max_decision_seconds=65,
                        max_execution_seconds=5,
                    ),
                )
                expected = 2 if unified.content.completion_after == "verify" else 1
                assert outcome.kind is RunKind.FINISH
                assert outcome.executions == expected
                assert turn.selected_actions == [
                    legacy.m4.collect_action,
                    *([legacy.m4.verify_action] if expected == 2 else []),
                ]
                assert outcome.observations[-1].facts == ("GOAL_SATISFIED",)

    asyncio.run(evaluate())
