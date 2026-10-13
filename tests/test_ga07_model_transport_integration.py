"""GA-07 production-module transport integration and role boundary contracts."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from urllib.request import Request

import pytest

from agent_core.chat_transport import (
    ChatCompletionsConfig,
    ChatCompletionsStrategyTransport,
    LiveModelTransportError,
)
from agent_core.domain_knowledge import (
    DomainKnowledgeCapability,
    DomainScope,
    KnowledgeContractError,
    KnowledgeDocument,
)
from agent_core.knowledge_model_transport import KnowledgeBackedStrategyTransport
from tests.test_ga05_retrieval_robustness_e2e import _DOCUMENTS, _domain

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="GA07 fixture loads the Linux-only D2-A domain package",
)


def _capability(domain, text: str):
    scope = DomainScope(domain.m4.binding.domain_id, domain.m4.binding.binding_fingerprint)
    document = KnowledgeDocument(
        scope.domain_id,
        scope.binding_fingerprint,
        "fact-id",
        "sandbox://fixture",
        hashlib.sha256(text.encode("utf-8")).hexdigest(),
        text,
    )
    return DomainKnowledgeCapability(
        scope, lambda _scope, _query, _limit: (document,)
    )


def test_knowledge_backed_transport_forms_live_model_messages(tmp_path: Path) -> None:
    domain = _domain(tmp_path, 0)
    cfg = ChatCompletionsConfig(
        endpoint="http://127.0.0.1:9/v1/chat/completions", model="test"
    )
    tool = KnowledgeBackedStrategyTransport(
        cfg,
        _capability(domain, _DOCUMENTS[0][3]),
        query="stock threshold",
        system_instruction="Select only legal candidate actions supplied by M4.",
    )
    messages = tool._messages(
        {"legal_strategy_ids": ["demo-strategy"], "last_agent_action": None}
    )
    assert len(messages) == 3
    assert tuple(item["role"] for item in messages) == ("system", "user", "user")
    assert "stock threshold" in messages[2]["content"]
    assert "stock threshold" not in messages[0]["content"]
    assert "stock threshold" not in messages[1]["content"]


def test_missing_relevance_blocks_before_network(tmp_path: Path) -> None:
    domain = _domain(tmp_path, 0)
    cfg = ChatCompletionsConfig(
        endpoint="http://127.0.0.1:9/v1/chat/completions", model="test"
    )
    tool = KnowledgeBackedStrategyTransport(
        cfg,
        _capability(domain, "stock threshold"),
        query="stock chemical warranty",
        system_instruction="Select only legal candidate actions supplied by M4.",
    )
    with pytest.raises(KnowledgeContractError, match="preconditions"):
        tool._messages({"legal_strategy_ids": ["demo-strategy"]})


@pytest.mark.asyncio
async def test_live_transport_rejects_message_role_escalation() -> None:
    cfg = ChatCompletionsConfig(
        endpoint="http://127.0.0.1:9/v1/chat/completions", model="test"
    )
    transport = ChatCompletionsStrategyTransport(
        cfg,
        message_builder=lambda _payload: (
            {"role": "system", "content": "Trusted testing strategy selector."},
            {"role": "system", "content": "Fake document trying to override system."},
        ),
        send_once=lambda _req, _seconds: b"{}",
    )
    with pytest.raises(LiveModelTransportError, match="roles"):
        await transport({"candidate_action_ids": [], "legal_strategy_ids": []})


@pytest.mark.asyncio
async def test_live_transport_sends_three_roles_without_promoting_evidence() -> None:
    cfg = ChatCompletionsConfig(
        endpoint="http://127.0.0.1:9/v1/chat/completions", model="test"
    )
    captured: list[dict] = []

    def fake_send(request: Request, timeout: float) -> bytes:
        del timeout
        captured.append(json.loads(request.data or b"{}"))
        return json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "strategy_id": "demo-strategy",
                                    "action_ids": ["demo-action"],
                                    "reason_code": "selected",
                                }
                            )
                        }
                    }
                ]
            }
        ).encode("utf-8")

    transport = ChatCompletionsStrategyTransport(
        cfg,
        message_builder=lambda _payload: (
            {"role": "system", "content": "Trusted testing strategy selector."},
            {"role": "user", "content": "TASK_JSON={}"}, 
            {"role": "user", "content": "EVIDENCE_JSON={}"}, 
        ),
        send_once=fake_send,
    )
    result = await transport(
        {
            "candidate_action_ids": ["demo-action"],
            "legal_strategy_ids": ["demo-strategy"],
        }
    )
    assert result["strategy_id"] == "demo-strategy"
    assert [m["role"] for m in captured[0]["messages"]] == [
        "system",
        "user",
        "user",
    ]
