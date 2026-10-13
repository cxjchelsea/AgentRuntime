"""GA-07 reusable retrieval-backed strategy model transport.

Connects the DomainKnowledgeCapability port with the existing real model
transport and M4 structured strategy adapter, without granting any tools.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agent_core.chat_transport import (
    ChatCompletionsConfig,
    ChatCompletionsStrategyTransport,
)
from agent_core.domain_knowledge import (
    DomainKnowledgeCapability,
    KnowledgeContractError,
    build_domain_model_messages,
)


class KnowledgeBackedStrategyTransport:
    """Inject a replaceable, domain-pinned retrieval capability into model input.

    Fail-closed admission is evaluated per invocation; no query result is
    silently reused across runs. Real external actions still require M4/M6.
    """

    def __init__(
        self,
        config: ChatCompletionsConfig,
        capability: DomainKnowledgeCapability,
        *,
        query: str,
        system_instruction: str,
    ) -> None:
        if type(capability) is not DomainKnowledgeCapability:
            raise KnowledgeContractError("missing knowledge capability")
        if type(query) is not str or not query:
            raise KnowledgeContractError("missing retrieval query")
        self.capability = capability
        self._query = query
        self._instruction = system_instruction
        self._transport = ChatCompletionsStrategyTransport(
            config, message_builder=self._messages
        )

    def _messages(
        self, payload: dict[str, Any]
    ) -> tuple[dict[str, str], ...]:
        admission = self.capability.retrieve_and_admit(self._query)
        return build_domain_model_messages(
            system_instruction=self._instruction,
            task_payload=payload,
            admission=admission,
        )

    async def __call__(self, payload: dict[str, Any]) -> Mapping[str, object]:
        return await self._transport(payload)
