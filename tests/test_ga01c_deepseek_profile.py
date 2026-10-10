"""Selected GA-01C live provider profile; no billed requests."""

from __future__ import annotations

import asyncio
import json
from urllib.request import Request

from agent_core.chat_transport import (
    ChatCompletionsConfig,
    ChatCompletionsStrategyTransport,
)
from agent_core.model_adapter import StructuredStrategyTransportAdapter
from tests.test_ga01_slice2 import _run_soft_selection


def test_deepseek_flash_profile_is_compatible_with_frozen_m4_json_protocol() -> None:
    requests: list[dict[str, object]] = []

    def simulated_deepseek(request: Request, timeout: float) -> bytes:
        assert timeout == 12.0
        assert request.full_url == "https://api.deepseek.com/chat/completions"
        body_data = request.data
        assert isinstance(body_data, bytes)
        body = json.loads(body_data)
        requests.append(body)
        assert body["model"] == "deepseek-flash"
        assert body["response_format"] == {"type": "json_object"}
        assert "json" in body["messages"][0]["content"].lower()
        return json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "strategy_id": "DOMAIN_STRATEGY_A",
                                    "action_ids": ["DOMAIN_ACTION_A"],
                                    "reason_code": "PROVIDER_CONTRACT_ONLY",
                                }
                            )
                        }
                    }
                ]
            }
        ).encode("utf-8")

    config = ChatCompletionsConfig(
        endpoint="https://api.deepseek.com/chat/completions",
        model="deepseek-flash",
        api_key="fake-test-token",
    )
    result = asyncio.run(
        _run_soft_selection(
            StructuredStrategyTransportAdapter(
                ChatCompletionsStrategyTransport(config, send_once=simulated_deepseek)
            )
        )
    )
    assert result.selected_action_ids == ("DOMAIN_ACTION_A",)
    assert len(requests) == 1
