"""Loopback-only manual acceptance console for the existing GA-21 read-only agent.

Not a clinical application, production host, or general medical domain adapter.
Run under Linux with a pinned GA-20 operator config and an accessible model.
"""
from __future__ import annotations

import argparse
import asyncio
import hmac
import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from agent_core.chat_transport import ChatCompletionsConfig
from examples.ga20_sandbox_cli import ask_once
from examples.ga21_conversation import ReadOnlyConversation
from examples.ga22_goal_policy import learning_goal_policy
from examples.ga22_replanning import PreviousStepSources

ASSETS = Path(__file__).with_name("acceptance_console.html")
MAX_BODY = 4096
SUPPORTED = ("inventory", "learning")
MEDICAL_NOT_WIRED = ("medical.chronic-management", "medical.mental-wellbeing", "medical.risk_prediction")


class ConsoleState:
    def __init__(self, configs: dict[str, Path]) -> None:
        if not configs or any(domain not in SUPPORTED for domain in configs):
            raise ValueError("at least one supported, pinned demo domain is required")
        self.configs = configs
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.sessions: dict[str, ReadOnlyConversation] = {}

    def _new_session(self, domain: str) -> ReadOnlyConversation:
        config = ChatCompletionsConfig(
            endpoint=os.environ.get("GA01C_LLM_URL", "http://127.0.0.1:11434/v1/chat/completions"),
            model=os.environ.get("GA01C_LLM_MODEL", "qwen2.5:3b"),
            api_key=os.environ.get("GA01C_LLM_API_KEY", ""),
            timeout_seconds=45.0,
            max_tokens=200,
        )
        session_id = "accept-" + secrets.token_hex(12)
        subject_id = "synthetic-" + secrets.token_hex(12)

        async def execute(selected: str, question: str, target: int | None) -> dict[str, object]:
            return await ask_once(
                selected, question, config, self.configs[selected],
                goal_target=target, session_id=session_id, subject_id=subject_id,
            )

        async def continue_run(
            selected: str, question: str, target: int | None, previous: PreviousStepSources,
        ) -> dict[str, object]:
            return await ask_once(
                selected, question, config, self.configs[selected],
                goal_target=target, continuation=previous,
                session_id=session_id, subject_id=subject_id,
            )

        return ReadOnlyConversation(
            domain=domain, session_id=session_id, subject_id=subject_id,
            run_read_only=execute, run_continuation=continue_run,
            goal_policy=learning_goal_policy() if domain == "learning" else None,
        )

    def dispatch(self, payload: object) -> dict[str, object]:
        if type(payload) is not dict:
            raise ValueError("invalid request")
        if set(payload) - {"action", "domain", "message"}:
            raise ValueError("unsupported fields")
        action, domain = payload.get("action"), payload.get("domain")
        if type(domain) is not str or domain not in self.configs:
            raise ValueError("domain is not configured for this demo")
        if action == "reset":
            self.sessions[domain] = self._new_session(domain)
            return {"ok": True, "reset": True, "domain": domain}
        if action != "send" or type(payload.get("message")) is not str:
            raise ValueError("invalid action or message")
        message = payload["message"]
        if not 1 <= len(message.strip()) <= 1000:
            raise ValueError("message must contain 1..1000 characters")
        session = self.sessions.get(domain)
        if session is None:
            session = self._new_session(domain)
            self.sessions[domain] = session
        reply = asyncio.run(session.send(message))
        return {
            "ok": True, "domain": domain, "kind": reply.kind.value,
            "answer": reply.text, "turn": reply.turn_number,
            "cached": reply.reused_evidence, "tool_executions": reply.tool_executions,
            "revalidated_steps": list(reply.revalidated_steps),
        }


def make_handler(state: ConsoleState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _json(self, status: int, data: dict[str, Any]) -> None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path != "/":
                self._json(404, {"ok": False, "error": "not found"})
                return
            page = ASSETS.read_text(encoding="utf-8").replace(
                "__CONSOLE_TOKEN__", state.token
            ).replace("__AVAILABLE_DOMAINS__", json.dumps(list(state.configs)))
            body = page.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/api/turn":
                self._json(404, {"ok": False, "error": "not found"})
                return
            if self.headers.get("Origin") not in (None, "http://127.0.0.1:" + str(self.server.server_address[1])):
                self._json(403, {"ok": False, "error": "origin denied"})
                return
            if not hmac.compare_digest(self.headers.get("X-Console-Token", ""), state.token):
                self._json(403, {"ok": False, "error": "token denied"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= MAX_BODY or self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                    raise ValueError("invalid request size or content type")
                payload = json.loads(self.rfile.read(size))
                with state.lock:
                    result = state.dispatch(payload)
                self._json(200, result)
            except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
                self._json(400, {"ok": False, "error": "invalid or unsupported request"})
            except Exception:  # noqa: BLE001 - never leak tool/model internals via HTTP
                self._json(503, {"ok": False, "error": "agent unavailable or execution denied"})

        def log_message(self, format: str, *args: object) -> None:
            # Do not put medical/synthetic user messages in HTTP access logs.
            return

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Loopback-only GA-21 manual acceptance Web console")
    parser.add_argument("--inventory-config", type=Path)
    parser.add_argument("--learning-config", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    configs = {
        name: path.resolve() for name, path in
        (("inventory", args.inventory_config), ("learning", args.learning_config))
        if path is not None
    }
    state = ConsoleState(configs)
    for path in configs.values():
        if not path.is_file():
            parser.error("operator config file does not exist: " + str(path))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(state))
    print(f"Manual acceptance console: http://127.0.0.1:{args.port}/")
    print("Synthetic read-only demo only; medical domains are not wired.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
