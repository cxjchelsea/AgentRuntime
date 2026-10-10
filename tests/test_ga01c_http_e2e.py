"""Real local HTTP socket -> model protocol -> M4 approval -> sandbox Agent Loop.

This server is a deterministic provider simulator, NOT a genuine language model.
"""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agent_core.runner import AgentRunCoordinator, LoopBudget, RunKind
from tests.orchestration_stubs import build_runtime_input
from tests.test_ga01c_live import LiveSandboxTurn


def test_local_chat_http_endpoint_drives_approved_two_action_loop(
    monkeypatch,
) -> None:
    calls: list[dict[str, object]] = []

    class LocalChatEndpoint(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            assert self.path == "/v1/chat/completions"
            length = int(self.headers["Content-Length"])
            assert length < 8192
            request = json.loads(self.rfile.read(length))
            model_input = json.loads(request["messages"][1]["content"])
            calls.append(model_input)
            observed = model_input["last_agent_action"]
            second = observed == "MOCK_FOUND_NEEDS_VERIFICATION"
            strategy = "DOMAIN_STRATEGY_B" if second else "DOMAIN_STRATEGY_A"
            action = "DOMAIN_ACTION_B" if second else "DOMAIN_ACTION_A"
            selection = {
                "strategy_id": strategy,
                "action_ids": [action],
                "reason_code": "LOCAL_HTTP_TEST",
            }
            raw = json.dumps(
                {"choices": [{"message": {"content": json.dumps(selection)}}]}
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format: str, *args: object) -> None:
            del format, args  # No request body or credentials in CI logs.

    with ThreadingHTTPServer(("127.0.0.1", 0), LocalChatEndpoint) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        monkeypatch.setenv(
            "GA01C_LLM_URL",
            f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
        )
        monkeypatch.setenv("GA01C_LLM_MODEL", "local-mock-model")
        monkeypatch.setenv("GA01C_LLM_API_KEY", "")

        async def scenario() -> None:
            initial = build_runtime_input(text="local HTTP test safe query and verify")
            step = LiveSandboxTurn(initial)
            result = await AgentRunCoordinator(
                step,
                LoopBudget(max_iterations=4, max_executions=2),
            ).run(initial, step.binding)
            assert result.kind is RunKind.FINISH
            assert result.executions == 2
            assert step.selected_actions == ["DOMAIN_ACTION_A", "DOMAIN_ACTION_B"]

        try:
            asyncio.run(scenario())
        finally:
            server.shutdown()
            thread.join(timeout=3)

    assert len(calls) == 2
    assert calls[0]["last_agent_action"] is None
    assert calls[1]["last_agent_action"] == "MOCK_FOUND_NEEDS_VERIFICATION"
    assert all("tool_context" not in call for call in calls)
