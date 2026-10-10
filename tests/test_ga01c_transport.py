"""GA-01C transport: no network or provider key needed."""

from __future__ import annotations

import asyncio
import json
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from agent_core.chat_transport import (
    ChatCompletionsConfig,
    ChatCompletionsStrategyTransport,
    LiveModelTransportError,
)
from agent_core.model_adapter import StructuredStrategyTransportAdapter
from runtime.planning import StrategyModelOutputError
from tests.test_ga01_slice2 import _run_soft_selection


def _payload(strategy: str, action: str) -> bytes:
    return json.dumps({
        "choices": [{
            "message": {
                "content": json.dumps({
                    "strategy_id": strategy,
                    "action_ids": [action],
                    "reason_code": "LIVE_TEST_PROVIDER",
                })
            }
        }]
    }).encode("utf-8")


def test_http_json_contract_via_injected_transport_without_network() -> None:
    captured: list[dict[str, object]] = []

    def send(request: Request, timeout: float) -> bytes:
        assert timeout == 3.0
        assert request.full_url == "https://api.example.org/v1/chat/completions"
        assert request.get_header("Authorization") == "Bearer test-placeholder"
        body = json.loads(request.data or b"{}")
        captured.append(body)
        assert body["temperature"] == 0
        assert body["response_format"] == {"type": "json_object"}
        assert "DOMAIN_ACTION_A" in body["messages"][1]["content"]
        return _payload("DOMAIN_STRATEGY_A", "DOMAIN_ACTION_A")

    config = ChatCompletionsConfig(
        endpoint="https://api.example.org/v1/chat/completions",
        model="model-placeholder",
        api_key="test-placeholder",
        timeout_seconds=3.0,
    )
    model = StructuredStrategyTransportAdapter(
        ChatCompletionsStrategyTransport(config, send_once=send)
    )
    result = asyncio.run(_run_soft_selection(model))
    assert result.selected_action_ids == ("DOMAIN_ACTION_A",)
    assert len(captured) == 1
    assert "test-placeholder" not in repr(config)


@pytest.mark.parametrize(
    "url",
    [
        "http://remote.example.com/v1/chat/completions",
        "https://example.com/v1/chat/completions?token=unsafe",
        "https://username:pass@example.com/v1/chat/completions",
        "https://example.com/v1/other",
    ],
)
def test_untrusted_model_endpoint_blocked(url: str) -> None:
    with pytest.raises(ValueError):
        ChatCompletionsConfig(url, "model", "secret")


def test_model_response_invalid_json_fails_closed() -> None:
    transport = ChatCompletionsStrategyTransport(
        ChatCompletionsConfig("http://127.0.0.1:8888/v1/chat/completions", "local"),
        send_once=lambda _request, _timeout: b'{"choices": []}',
    )
    with pytest.raises(LiveModelTransportError, match="invalid structured"):
        asyncio.run(transport({"legal_strategy_ids": [], "candidate_action_ids": []}))


def test_model_response_illegal_action_rejected_by_real_m4() -> None:
    transport = ChatCompletionsStrategyTransport(
        ChatCompletionsConfig("http://localhost:9999/v1/chat/completions", "local"),
        send_once=lambda _request, _timeout: _payload(
            "DOMAIN_STRATEGY_A", "UNREGISTERED_ACTION"
        ),
    )
    with pytest.raises(StrategyModelOutputError):
        asyncio.run(
            _run_soft_selection(StructuredStrategyTransportAdapter(transport))
        )


def test_provider_failure_does_not_retry_or_disclose_secret() -> None:
    calls = 0

    def unavailable(request: Request, timeout: float) -> bytes:
        nonlocal calls
        calls += 1
        raise HTTPError(request.full_url, 503, "unavailable", None, None)

    transport = ChatCompletionsStrategyTransport(
        ChatCompletionsConfig(
            "https://api.example.org/v1/chat/completions",
            "model",
            "never-log-secret",
        ),
        send_once=unavailable,
    )
    with pytest.raises(LiveModelTransportError) as exc:
        asyncio.run(transport({"legal_strategy_ids": [], "candidate_action_ids": []}))
    assert calls == 1
    assert "never-log-secret" not in str(exc.value)
