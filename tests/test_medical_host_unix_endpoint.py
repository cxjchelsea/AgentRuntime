"""Exercise the actual Unix socket admission boundary without live tools."""

from __future__ import annotations

import asyncio
import stat
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

from agent_core.medical_host_unix_endpoint import (
    MedicalHostUnixEndpoint,
    request_medical_host,
)
from agent_core.medical_physical_host import (
    InMemoryOperationClaimStore,
    TrustedMedicalOperationIssuer,
    TrustedMedicalPhysicalHost,
)

KEY = b"synthetic-host-rpc-key-at-least-32-bytes"
OPERATION: dict[str, Any] = {
    "run_id": "sandbox-run",
    "request_id": "sandbox-request",
    "domain_fingerprint": "a" * 64,
    "identity_scope": "sandbox-patient",
    "approved_plan_id": "plan-one",
    "step_execution_id": "step-one",
    "logical_tool_call_id": "toolcall-one",
    "tool_id": "sandbox.readonly",
    "input_payload": {"synthetic": True},
    "physical_attempt": 1,
    "idempotency_key": "idempotency-one",
    "operation_key": "operation-one",
    "operation_fingerprint": "fingerprint-one",
}


def test_unix_endpoint_rejects_unauthorized_tool_before_raw_executor(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        raw = AsyncMock()
        host = TrustedMedicalPhysicalHost(
            secret=KEY,
            physical=raw,
            claims=InMemoryOperationClaimStore(),
            clock=lambda: 100.0,
        )
        endpoint = MedicalHostUnixEndpoint(host)
        path = tmp_path / "medical-host.sock"
        server = await endpoint.serve(path)
        try:
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
            denied = await request_medical_host(
                path, grant=None, operation=OPERATION
            )
            assert denied["ok"] is False
            raw.execute_physical_attempt.assert_not_awaited()
            signed = TrustedMedicalOperationIssuer(
                KEY, clock=lambda: 100.0
            ).grant(
                **{
                    key: value
                    for key, value in OPERATION.items()
                    if key != "idempotency_key"
                }
            )
            altered = {**OPERATION, "tool_id": "other-tool"}
            denied = await request_medical_host(
                path, grant=signed, operation=altered
            )
            assert denied["ok"] is False
            raw.execute_physical_attempt.assert_not_awaited()
            allowed = await request_medical_host(
                path, grant=signed, operation=OPERATION
            )
            assert allowed == {"ok": True}
            assert raw.execute_physical_attempt.await_count == 1
            replay = await request_medical_host(
                path, grant=signed, operation=OPERATION
            )
            assert replay["ok"] is False
            assert raw.execute_physical_attempt.await_count == 1
        finally:
            server.close()
            await server.wait_closed()
            path.unlink(missing_ok=True)

    asyncio.run(scenario())
