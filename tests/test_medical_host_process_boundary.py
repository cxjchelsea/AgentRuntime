"""Process-separated local Host smoke: no live patient data or external tools."""

from __future__ import annotations

import asyncio
import multiprocessing
from pathlib import Path
from typing import Any

import pytest

from agent_core.medical_host_unix_endpoint import (
    MedicalHostUnixEndpoint,
    request_medical_host,
)
from agent_core.medical_physical_host import (
    SQLiteOperationClaimStore,
    TrustedMedicalOperationIssuer,
    MedicalPhysicalGrant,
    TrustedMedicalPhysicalHost,
)

SCOPE: dict[str, Any] = {
    "run_id": "process-run",
    "request_id": "process-request",
    "domain_fingerprint": "c" * 64,
    "identity_scope": "synthetic-scope",
    "approved_plan_id": "approved-plan",
    "step_execution_id": "approved-step",
    "tool_id": "synthetic.readonly",
    "logical_tool_call_id": "physical-call",
    "input_payload": {"safe": True},
    "physical_attempt": 1,
    "operation_key": "one-operation",
    "operation_fingerprint": "operation-fingerprint",
}


class _HostOnlyPhysicalAdapter:
    def __init__(self, effect_marker: Path) -> None:
        self._marker = effect_marker

    async def execute_physical_attempt(self, **kwargs: Any) -> Any:
        del kwargs
        with self._marker.open("a", encoding="utf-8") as output:
            output.write("attempt\n")
        return None


def _host_process(socket: str, db: str, marker: str, stop: Any, grants: Any) -> None:
    host_secret = b"synthetic-spawn-host-isolated-32bytes-long"
    async def run() -> None:
        physical = _HostOnlyPhysicalAdapter(Path(marker))
        trusted = TrustedMedicalPhysicalHost(
            secret=host_secret,
            physical=physical,
            claims=SQLiteOperationClaimStore(Path(db)),
            clock=lambda: 100.0,
        )
        server = await MedicalHostUnixEndpoint(trusted).serve(Path(socket))
        token = TrustedMedicalOperationIssuer(host_secret, clock=lambda: 100.0).grant(**SCOPE)
        grants.put((token.payload, token.signature))
        try:
            while not stop.is_set():
                await asyncio.sleep(0.02)
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(run())


@pytest.mark.skipif(
    not hasattr(asyncio, "start_unix_server"), reason="Unix sockets unavailable"
)
def test_separate_host_process_rejects_bypass_and_preserves_claim(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        socket = tmp_path / "trusted-host.sock"
        database = tmp_path / "claims.db"
        effects = tmp_path / "private-executor-attempts.txt"
        ctx = multiprocessing.get_context("spawn")
        stop = ctx.Event()
        grants = ctx.Queue()
        worker = ctx.Process(
            target=_host_process,
            args=(str(socket), str(database), str(effects), stop, grants),
        )
        worker.start()
        try:
            for _ in range(200):
                if socket.exists():
                    break
                if not worker.is_alive():
                    pytest.fail("Host process exited before opening socket")
                await asyncio.sleep(0.025)
            assert socket.exists(), "Host socket unavailable"
            request = {**SCOPE, "idempotency_key": "one-operation"}
            # The application has no raw adapter or signing key from this RPC.
            denied = await request_medical_host(socket, grant=None, operation=request)
            assert denied["ok"] is False
            assert not effects.exists()
            payload, signature = grants.get(timeout=5)
            signed = MedicalPhysicalGrant(payload, signature)
            altered = {**request, "tool_id": "foreign-tool"}
            denied = await request_medical_host(socket, grant=signed, operation=altered)
            assert denied["ok"] is False
            assert not effects.exists()
            allowed = await request_medical_host(
                socket, grant=signed, operation=request
            )
            assert allowed["ok"] is True
            assert effects.read_text(encoding="utf-8").splitlines() == ["attempt"]
            replay = await request_medical_host(socket, grant=signed, operation=request)
            assert replay["ok"] is False
            assert effects.read_text(encoding="utf-8").splitlines() == ["attempt"]
        finally:
            stop.set()
            worker.join(timeout=5)
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)
            assert worker.exitcode == 0

    asyncio.run(scenario())
