"""Provider-neutral structured strategy transport; never grants planning/tool rights.

Slice 2 only. Real transport credentials and external API are not bundled.
HybridStrategySelector performs legal strategy/action validation downstream.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from runtime.planning.strategy_selection import StrategyModelRequest


class StrategyTransportError(RuntimeError):
    """A structured model request failed without implying any action success."""


class StructuredStrategyTransportAdapter:
    """Translate frozen M4 request to an injectable async JSON transport.

    The transport is only invoked by the existing HybridStrategySelector after
    rule precedence and candidate filtering. This is not a tool adapter.
    """

    def __init__(
        self,
        transport: Callable[[dict[str, Any]], Awaitable[Mapping[str, object]]],
        *,
        include_legacy_agent_action: bool = True,
    ) -> None:
        self._transport = transport
        self._include_legacy_agent_action = include_legacy_agent_action

    async def infer(self, request: StrategyModelRequest) -> Mapping[str, object]:
        # Allow-listed fields only; never forward RuntimeContext or ToolResult.
        payload: dict[str, Any] = {
            "request_id": request.request_id,
            "planning_mode": request.planning_mode.value,
            "intent_ids": list(request.understanding.intent_ids),
            "explicit_goal": request.understanding.explicit_goal,
            "legal_strategy_ids": list(request.legal_strategy_ids),
            "candidate_action_ids": list(request.candidate_action_ids),
            "available_capability_ids": list(request.available_capability_ids),
        }
        if self._include_legacy_agent_action:
            payload["last_agent_action"] = request.context.recent_agent_action
        observation = request.planning_observation
        if observation is not None:
            payload["planning_observation"] = {
                "schema_version": observation.schema_version,
                "evidence_state": observation.evidence_state,
                "evidence_refs": list(observation.evidence_refs),
                "executed_action_ids": list(observation.executed_action_ids),
                "pending_conditions": list(observation.pending_conditions),
                "source_scope": observation.source_scope,
            }
        try:
            response = await self._transport(payload)
        except Exception as exc:
            raise StrategyTransportError(
                "structured strategy transport failed"
            ) from exc
        if not isinstance(response, Mapping):
            raise StrategyTransportError("strategy transport returned a non-object")
        return response
