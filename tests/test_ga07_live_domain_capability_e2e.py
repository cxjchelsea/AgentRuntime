"""GA-07 opt-in actual Qwen E2E through formal domain knowledge transport.

All indexed documents, strategies, actions, and observations are synthetic.
This proves interface consumption, not source authentication or real tools.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from agent_core.chat_transport import ChatCompletionsConfig
from agent_core.domain_knowledge import (
    DomainKnowledgeCapability,
    DomainScope,
    KnowledgeDocument,
)
from agent_core.knowledge_model_transport import KnowledgeBackedStrategyTransport
from agent_core.model_adapter import StructuredStrategyTransportAdapter
from agent_core.runner import AgentRunCoordinator, Decision, LoopBudget, ObservedFact, RunKind
from tests.ga05_fts_retrieval import IndexedDocument, SandboxFTSIndex
from tests.ga06_role_separated_turn import trusted_sandbox_instruction
from tests.orchestration_stubs import build_runtime_input
from tests.test_ga02_d4_two_domain_m4_e2e import _planner
from tests.test_ga03_domain_prompt_rule_knowledge_e2e import GA03Turn
from tests.test_ga05_retrieval_robustness_e2e import _CASES, _DOCUMENTS, _QUERIES, _domain

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="GA07 uses the Linux-only D2-A fixture package loader",
)


def _config() -> ChatCompletionsConfig:
    return ChatCompletionsConfig(
        endpoint=os.environ["GA01C_LLM_URL"],
        model=os.environ["GA01C_LLM_MODEL"],
        api_key=os.environ.get("GA01C_LLM_API_KEY", ""),
        timeout_seconds=45,
        max_tokens=192,
    )


class IntegratedDomainTurn(GA03Turn):
    def __init__(
        self,
        initial,
        domain,
        *,
        index: SandboxFTSIndex,
        query: str,
        config: ChatCompletionsConfig,
    ) -> None:
        super().__init__(initial, domain, available=frozenset())
        binding = domain.m4.binding
        scope = DomainScope(binding.domain_id, binding.binding_fingerprint)

        def provider(
            requested: DomainScope, lookup: str, limit: int
        ) -> tuple[KnowledgeDocument, ...]:
            if requested != scope:
                return ()
            hits = index.retrieve(binding, lookup, limit=limit)
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

        self.knowledge = DomainKnowledgeCapability(scope, provider)
        self.retrieval_transport = KnowledgeBackedStrategyTransport(
            config,
            self.knowledge,
            query=query,
            system_instruction=trusted_sandbox_instruction(domain),
        )
        self._planner, self._validator, self._rechecker = _planner(
            domain.m4,
            StructuredStrategyTransportAdapter(self.retrieval_transport),
        )

    async def decide(
        self,
        current_input,
        iteration,
        observations: tuple[ObservedFact, ...],
    ) -> Decision:
        admission = self.knowledge.retrieve_and_admit(self.retrieval_transport._query)
        if not admission.accepted:
            return Decision(iteration, "WAIT", reason=admission.reason)
        self.evidence = tuple(d.content for d in admission.documents)
        return await super().decide(current_input, iteration, observations)


@pytest.mark.skipif(
    os.environ.get("GA07_LIVE_OPT_IN") != "1"
    or not os.environ.get("GA01C_LLM_URL")
    or not os.environ.get("GA01C_LLM_MODEL"),
    reason="GA07 requires explicit live Qwen opt-in",
)
def test_ga07_real_qwen_formal_knowledge_port_two_domains(
    tmp_path: Path,
) -> None:
    async def evaluate() -> None:
        for repeat in range(3):
            root = tmp_path / f"trial-{repeat}"
            root.mkdir()
            domains = []
            index = SandboxFTSIndex()
            for number in (0, 1):
                folder = root / f"domain-{number}"
                folder.mkdir()
                domain = _domain(folder, number)
                domains.append(domain)
                index.add(domain.m4.binding, IndexedDocument(*_DOCUMENTS[number]))
            for number, domain in enumerate(domains):
                initial = build_runtime_input(text=_CASES[number][2])
                turn = IntegratedDomainTurn(
                    initial, domain, index=index, query=_QUERIES[number], config=_config()
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
                assert turn.selected_actions == [
                    domain.m4.collect_action,
                    *([domain.m4.verify_action] if expected == 2 else []),
                ]

    asyncio.run(evaluate())
