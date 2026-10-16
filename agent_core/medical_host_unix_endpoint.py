"""Unix socket entry for Host-owned medical physical attempts.

The socket listener MUST run in a separately controlled Host process with sole
custody of physical adapters and issuer keys. Local in-process tests prove RPC
admission only; they do not prove deployment/OS isolation.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from agent_core.domain_extension import DomainExtensionError
from agent_core.medical_physical_host import (
    MedicalPhysicalGrant,
    TrustedMedicalPhysicalHost,
)

MAX_REQUEST_BYTES = 16384


class MedicalHostUnixEndpoint:
    """Expose guarded physical attempts only; never register a raw executor."""

    def __init__(self, host: TrustedMedicalPhysicalHost) -> None:
        self._host = host

    async def handle(self, raw: bytes) -> dict[str, object]:
        if not raw or len(raw) > MAX_REQUEST_BYTES:
            return {"ok": False, "error": "invalid request"}
        try:
            request = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return {"ok": False, "error": "invalid request"}
        if type(request) is not dict or set(request) != {"grant", "operation"}:
            return {"ok": False, "error": "invalid request"}
        token = request["grant"]
        operation = request["operation"]
        if type(operation) is not dict:
            return {"ok": False, "error": "invalid request"}
        if token is not None and (
            type(token) is not dict or set(token) != {"payload", "signature"}
            or not all(type(item) is str for item in token.values())
        ):
            return {"ok": False, "error": "invalid request"}
        grant = None if token is None else MedicalPhysicalGrant(**token)
        try:
            await self._host.execute(grant=grant, **operation)
        except (DomainExtensionError, TypeError, ValueError):
            # Never expose keys, patient data, or internal rejection details.
            return {"ok": False, "error": "authorization or execution denied"}
        except Exception:
            # Side effect may already have happened: UNKNOWN, never auto-retry.
            return {"ok": False, "error": "unknown external outcome"}
        return {"ok": True}

    async def serve(self, socket_path: Path) -> asyncio.AbstractServer:
        if not isinstance(socket_path, Path) or socket_path.exists():
            raise DomainExtensionError("invalid or occupied medical Host socket")
        server = await asyncio.start_unix_server(self._accept, path=str(socket_path))
        socket_path.chmod(0o600)
        return server

    async def _accept(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            raw = await reader.readline()
            if len(raw) > MAX_REQUEST_BYTES:
                response: dict[str, object] = {"ok": False, "error": "invalid request"}
            else:
                response = await self.handle(raw)
            writer.write((json.dumps(response) + "\n").encode())
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()


async def request_medical_host(
    socket_path: Path,
    *,
    grant: MedicalPhysicalGrant | None,
    operation: dict[str, object],
) -> dict[str, object]:
    """Unprivileged RPC client: no direct executor, key, or issuer parameter."""
    reader, writer = await asyncio.open_unix_connection(str(socket_path))
    try:
        raw = json.dumps(
            {
                "grant": None if grant is None else {
                    "payload": grant.payload,
                    "signature": grant.signature,
                },
                "operation": operation,
            },
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        if len(raw) >= MAX_REQUEST_BYTES:
            raise DomainExtensionError("medical Host request too large")
        writer.write(raw + b"\n")
        await writer.drain()
        line = await reader.readline()
        if not line or len(line) > MAX_REQUEST_BYTES:
            raise DomainExtensionError("invalid medical Host response")
        result: Any = json.loads(line)
        if type(result) is not dict or type(result.get("ok")) is not bool:
            raise DomainExtensionError("invalid medical Host response")
        return result
    finally:
        writer.close()
        await writer.wait_closed()
