"""GA-03: distinct Prompt/Rule/Knowledge packages, shared GA-01 M2/M4/Loop.

All knowledge, model decisions, and mock executions are deterministic test
fixtures. In particular the explicit prompt projection is NOT yet wired into
the production LLM prompt builder or a production RAG source.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from agent_core.domain_package_loader import (
    HostPackageRootIssuer,
    HostPublishedGeneration,
    LocalPackageLoader,
    TrustedPackageIdentity,
)
from agent_core.model_adapter import StructuredStrategyTransportAdapter
from agent_core.runner import (
    AgentRunCoordinator,
    Decision,
    LoopBudget,
    ObservedFact,
    RunKind,
)
from agent_core.sandbox_domain_assembly import (
    SandboxAssemblyError,
    assemble_sandbox_domain,
)
from tests.ga03_domain_content_assembly import (
    SandboxDomainKnowledge,
    assemble_ga03_domain,
)
from tests.orchestration_stubs import build_runtime_input
from tests.test_ga01_slice1 import SandboxTurn
from tests.test_ga02_d4_two_domain_m4_e2e import (
    DomainDrivenTurn,
    _package,
    _planner,
)

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="GA03 E2E reuses the Linux-only D2-A secure local FD loader",
)

_CASES = (
    (
        "inventory.reconcile",
        "stock",
        "Check fictional inventory balance against an exact count",
        "stock.threshold",
        "Mock stock threshold = 5 units",
        "verify",
    ),
    (
        "learning.plan",
        "notes",
        "Find one matching course note before drafting a study suggestion",
        "notes.index",
        "Mock note index contains linear algebra",
        "collect",
    ),
)


def _with_domain_assets(
    root: Path,
    domain_id: str,
    noun: str,
    focus: str,
    key: str,
    fact: str,
    completion: str,
) -> TrustedPackageIdentity:
    _package(root, domain_id, noun)
    descriptor_path = root / "package.json"
    descriptor: dict[str, Any] = json.loads(descriptor_path.read_bytes())
    content_by_kind = {
        "prompt": {"focus": focus},
        "rule": {"required_knowledge": key, "completion_after": completion},
        "knowledge": {"key": key, "fact": fact},
    }
    for kind, payload in content_by_kind.items():
        contents = json.dumps(payload, sort_keys=True).encode("utf-8")
        relative = f"{kind}/{kind}.json"
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents)
        descriptor["asset_refs"].append(
            {
                "kind": kind,
                "namespace": domain_id,
                "id": f"demo.{kind}",
                "version": "1.0.0",
                "sha256": hashlib.sha256(contents).hexdigest(),
                "relative_path": relative,
            }
        )
    descriptor["asset_refs"].sort(
        key=lambda ref: (
            ref["kind"],
            ref["namespace"],
            ref["id"],
            ref["version"],
            ref["relative_path"],
        )
    )
    del descriptor["manifest_digest"]
    digest = hashlib.sha256(
        json.dumps(
            descriptor, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    descriptor["manifest_digest"] = digest
    descriptor_path.write_bytes(json.dumps(descriptor).encode("utf-8"))
    return TrustedPackageIdentity(
        "sandbox-gen-1", domain_id, "1.0.0", "GA02-D1-1", digest
    )


def _load_case(root: Path, case: tuple[str, ...]) -> SandboxDomainKnowledge:
    identity = _with_domain_assets(root, *case)
    issuer = HostPackageRootIssuer(
        (HostPublishedGeneration(identity, str(root), True),),
        publication_verifier=lambda published: (
            published.identity == identity
            and published.absolute_root == str(root)
            and published.sealed
        ),
    )
    with issuer.issue(identity.generation_id) as lease:
        snapshot = LocalPackageLoader().load(lease, identity)
    return assemble_ga03_domain(assemble_sandbox_domain(snapshot))


class DomainKnowledgeTransport:
    """The sandbox model receives explicit bounded package context only."""

    def __init__(self, content: SandboxDomainKnowledge, evidence: tuple[str, ...]):
        self.content = content
        self.evidence = evidence
        self.calls: list[dict[str, Any]] = []
        self.projections: list[tuple[str, tuple[str, ...]]] = []

    async def __call__(self, payload: dict[str, Any]) -> dict[str, object]:
        self.calls.append(payload)
        self.projections.append((self.content.prompt_focus, self.evidence))
        if not self.evidence:
            raise AssertionError("knowledge gate must stop model calls")
        is_second = payload["last_agent_action"] == "MOCK_FOUND_NEEDS_VERIFICATION"
        role = "verify" if is_second else "collect"
        action = (
            self.content.m4.verify_action
            if role == "verify"
            else self.content.m4.collect_action
        )
        strategy = (
            self.content.m4.verify_strategy
            if role == "verify"
            else self.content.m4.collect_strategy
        )
        assert action in payload["candidate_action_ids"]
        assert strategy in payload["legal_strategy_ids"]
        return {
            "strategy_id": strategy,
            "action_ids": [action],
            "reason_code": "GA03_DOMAIN_EVIDENCE_MOCK_CHOICE",
        }


class GA03Turn(DomainDrivenTurn):
    def __init__(
        self,
        initial,
        content: SandboxDomainKnowledge,
        *,
        available: frozenset[str],
    ) -> None:
        self.content = content
        self.evidence = content.admitted_knowledge(available=available)
        super().__init__(initial, content.m4)
        self.ga03_transport = DomainKnowledgeTransport(content, self.evidence)
        self._planner, self._validator, self._rechecker = _planner(
            content.m4, StructuredStrategyTransportAdapter(self.ga03_transport)
        )

    async def decide(
        self, current_input, iteration, observations: tuple[ObservedFact, ...]
    ) -> Decision:
        if not self.evidence:
            return Decision(iteration, "WAIT", reason="GA03_REQUIRED_KNOWLEDGE_MISSING")
        return await super().decide(current_input, iteration, observations)

    async def execute_and_observe(self, decision: Decision) -> ObservedFact:
        if decision.approved is None or len(decision.approved.steps) != 1:
            raise SandboxAssemblyError("GA03 requires one approved sandbox step")
        action = decision.approved.steps[0].action
        if action not in {
            self.domain.collect_action,
            self.domain.verify_action,
        }:
            raise SandboxAssemblyError("GA03 foreign action")
        role = "collect" if action == self.domain.collect_action else "verify"
        self.facts = (
            ("GOAL_SATISFIED",)
            if role == self.content.completion_after
            else ("MOCK_FOUND_NEEDS_VERIFICATION",)
        )
        self.selected_actions.append(action)
        return await SandboxTurn.execute_and_observe(self, decision)


def test_ga03_two_domains_have_distinct_evidence_rules_and_task_paths(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        observations = []
        for case in _CASES:
            root = tmp_path / case[1]
            root.mkdir()
            domain = _load_case(root, case)
            initial = build_runtime_input(text=case[2])
            turn = GA03Turn(
                initial, domain, available=frozenset({domain.knowledge_key})
            )
            result = await AgentRunCoordinator(
                turn, LoopBudget(max_iterations=4, max_executions=3)
            ).run(initial, turn.binding)
            assert result.kind is RunKind.FINISH
            expected = 2 if domain.completion_after == "verify" else 1
            assert result.executions == expected
            assert result.iterations == expected + 1
            assert turn.selected_actions == [
                domain.m4.collect_action,
                *([domain.m4.verify_action] if expected == 2 else []),
            ]
            assert len(turn.ga03_transport.calls) == expected
            assert turn.ga03_transport.projections == [
                (domain.prompt_focus, (domain.knowledge_fact,))
            ] * expected
            assert domain.prompt_focus == case[2]
            assert turn.evidence == (case[4],)
            assert all(
                observed.domain_fingerprint == domain.m4.binding.binding_fingerprint
                for observed in result.observations
            )
            observations.append(
                (domain.m4.binding.binding_fingerprint, result.executions)
            )
        assert observations[0][0] != observations[1][0]
        assert observations[0][1] != observations[1][1]

    asyncio.run(scenario())


def test_ga03_missing_knowledge_waits_without_model_or_execution(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        domain = _load_case(tmp_path, _CASES[0])
        initial = build_runtime_input(text="stock check lacking knowledge")
        turn = GA03Turn(initial, domain, available=frozenset({"notes.index"}))
        result = await AgentRunCoordinator(turn, LoopBudget()).run(
            initial, turn.binding
        )
        assert result.kind is RunKind.WAIT
        assert result.reason == "GA03_REQUIRED_KNOWLEDGE_MISSING"
        assert result.executions == 0
        assert turn.transport.calls == []
        assert turn.mock_calls == 0

    asyncio.run(scenario())


def test_ga03_cross_domain_knowledge_is_not_accepted(tmp_path: Path) -> None:
    domain = _load_case(tmp_path, _CASES[0])
    assert domain.admitted_knowledge(available=frozenset({"notes.index"})) == ()
    assert domain.admitted_knowledge(available=frozenset({"stock.threshold"})) == (
        "Mock stock threshold = 5 units",
    )


def test_ga03_rejects_tampered_rule_asset_before_assembly(tmp_path: Path) -> None:
    domain = _load_case(tmp_path, _CASES[0])
    original = next(a for a in domain.m4.binding.assets if a.kind == "rule")
    forged = replace(
        original,
        content_bytes=b'{"required_knowledge":"notes.index","completion_after":"collect"}',
    )
    altered = replace(
        domain.m4.binding,
        assets=tuple(forged if a is original else a for a in domain.m4.binding.assets),
    )
    with pytest.raises(SandboxAssemblyError, match="digest"):
        assemble_ga03_domain(altered)


def test_ga03_rule_must_match_knowledge_even_with_spoofed_checksum(
    tmp_path: Path,
) -> None:
    domain = _load_case(tmp_path, _CASES[0])
    original = next(a for a in domain.m4.binding.assets if a.kind == "rule")
    data = b'{"required_knowledge":"notes.index","completion_after":"collect"}'
    forged = replace(
        original, content_bytes=data, sha256=hashlib.sha256(data).hexdigest()
    )
    altered = replace(
        domain.m4.binding,
        assets=tuple(forged if a is original else a for a in domain.m4.binding.assets),
    )
    with pytest.raises(SandboxAssemblyError, match="rule/knowledge mismatch"):
        assemble_ga03_domain(altered)
