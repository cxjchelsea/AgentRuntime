"""Acceptance console boundary tests: no real model or business side effects."""
from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from examples.acceptance_console import ConsoleState, make_handler


def test_console_rejects_unconfigured_medical_domains(tmp_path: Path) -> None:
    state = ConsoleState({"inventory": tmp_path / "inventory.json"})
    try:
        state.dispatch(
            {"action": "send", "domain": "medical.chronic-management", "message": "hi"}
        )
    except ValueError as exc:
        assert "not configured" in str(exc)
    else:
        raise AssertionError("medical domain must not silently fall back")


def test_console_reset_is_domain_scoped(tmp_path: Path) -> None:
    state = ConsoleState(
        {"inventory": tmp_path / "i.json", "learning": tmp_path / "l.json"}
    )
    first = state.dispatch({"action": "reset", "domain": "inventory"})
    second = state.dispatch({"action": "reset", "domain": "learning"})
    assert first["domain"] == "inventory"
    assert second["domain"] == "learning"
    assert state.sessions["inventory"].session_id != state.sessions["learning"].session_id
    old = state.sessions["inventory"].session_id
    state.dispatch({"action": "reset", "domain": "learning"})
    assert state.sessions["inventory"].session_id == old


def test_http_denies_missing_token_and_foreign_origin(tmp_path: Path) -> None:
    state = ConsoleState({"inventory": tmp_path / "i.json"})
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        body = json.dumps({"action": "reset", "domain": "inventory"})
        conn.request("POST", "/api/turn", body, {"Content-Type": "application/json"})
        response = conn.getresponse()
        assert response.status == 403
        response.read()
        conn.request(
            "POST", "/api/turn", body,
            {
                "Content-Type": "application/json",
                "X-Console-Token": state.token,
                "Origin": "https://attacker.example",
            },
        )
        response = conn.getresponse()
        assert response.status == 403
        response.read()
        conn.request(
            "POST", "/api/turn", body,
            {
                "Content-Type": "application/json",
                "X-Console-Token": state.token,
                "Origin": f"http://127.0.0.1:{server.server_port}",
            },
        )
        response = conn.getresponse()
        assert response.status == 200
        assert json.loads(response.read())["reset"] is True
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_validated_turn_exposes_real_metadata(tmp_path: Path) -> None:
    state = ConsoleState({"inventory": tmp_path / "i.json"})
    from examples.ga21_conversation import ConversationReply, TurnKind

    class FakeConversation:
        async def send(self, message: str) -> ConversationReply:
            assert message == "请查询库存"
            return ConversationReply(TurnKind.NEW, "合成结果", 1, False, 2, ("step-1",))

    with patch.object(state, "_new_session", return_value=FakeConversation()):
        result = state.dispatch({"action": "send", "domain": "inventory", "message": "请查询库存"})
    assert result["answer"] == "合成结果"
    assert result["tool_executions"] == 2
    assert result["revalidated_steps"] == ["step-1"]
