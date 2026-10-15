"""Medical Host-owned physical attempt gate (synthetic integration adapter).

Only the trusted composition root may hold the underlying physical executor and
grant issuer. This module intentionally supplies no production credential store.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from agent_core.domain_extension import DomainExtensionError
from runtime.execution.invocation import PhysicalToolAttemptExecutor, ToolAttemptObservation


@dataclass(frozen=True, slots=True)
class MedicalPhysicalGrant:
    payload: str
    signature: str


class OperationClaimStore(Protocol):
    def claim_once(self, operation_nonce: str) -> bool: ...


class InMemoryOperationClaimStore:
    """Test-only; not durable or safe for production multi-worker deployment."""

    def __init__(self) -> None:
        self._nonces: set[str] = set()

    def claim_once(self, operation_nonce: str) -> bool:
        if operation_nonce in self._nonces:
            return False
        self._nonces.add(operation_nonce)
        return True


class TrustedMedicalOperationIssuer:
    """Host-only operation grant issuer; never expose to Agent or domain package."""

    def __init__(
        self, secret: bytes, *, clock: Callable[[], float] = time.time
    ) -> None:
        if type(secret) is not bytes or len(secret) < 32:
            raise DomainExtensionError("invalid medical physical Host key")
        self._secret = secret
        self._clock = clock

    def grant(
        self,
        *,
        run_id: str,
        request_id: str,
        domain_fingerprint: str,
        identity_scope: str,
        approved_plan_id: str,
        step_execution_id: str,
        tool_id: str,
        logical_tool_call_id: str,
        input_payload: dict[str, object],
        physical_attempt: int,
        operation_key: str,
        operation_fingerprint: str,
        ttl_seconds: int = 30,
    ) -> MedicalPhysicalGrant:
        fields = (
            run_id, request_id, domain_fingerprint, identity_scope,
            approved_plan_id, step_execution_id, tool_id,
            logical_tool_call_id, operation_key, operation_fingerprint,
        )
        if (
            any(type(field) is not str or not field for field in fields)
            or type(physical_attempt) is not int
            or physical_attempt < 1
            or type(ttl_seconds) is not int
            or not 1 <= ttl_seconds <= 120
        ):
            raise DomainExtensionError("invalid medical physical grant scope")
        data = {
            "run_id": run_id,
            "request_id": request_id,
            "domain_fingerprint": domain_fingerprint,
            "identity_scope": identity_scope,
            "approved_plan_id": approved_plan_id,
            "step_execution_id": step_execution_id,
            "tool_id": tool_id,
            "logical_tool_call_id": logical_tool_call_id,
            "physical_attempt": physical_attempt,
            "operation_key": operation_key,
            "operation_fingerprint": operation_fingerprint,
            "input_digest": _digest(input_payload),
            "expires_at": int(self._clock()) + ttl_seconds,
            "nonce": secrets.token_hex(16),
        }
        payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return MedicalPhysicalGrant(
            payload,
            hmac.new(self._secret, payload.encode(), hashlib.sha256).hexdigest(),
        )


def _digest(payload: dict[str, object]) -> str:
    try:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise DomainExtensionError("unserializable medical physical input") from exc
    return hashlib.sha256(raw.encode()).hexdigest()


class TrustedMedicalPhysicalHost:
    """Validates and atomically claims a grant before the private executor."""

    def __init__(
        self,
        *,
        secret: bytes,
        physical: PhysicalToolAttemptExecutor,
        claims: OperationClaimStore,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if type(secret) is not bytes or len(secret) < 32:
            raise DomainExtensionError("invalid medical physical Host key")
        self._secret = secret
        self._physical = physical
        self._claims = claims
        self._clock = clock

    async def execute(
        self,
        *,
        grant: MedicalPhysicalGrant | None,
        run_id: str,
        request_id: str,
        domain_fingerprint: str,
        identity_scope: str,
        approved_plan_id: str,
        step_execution_id: str,
        logical_tool_call_id: str,
        tool_id: str,
        input_payload: dict[str, object],
        physical_attempt: int,
        idempotency_key: str | None,
        operation_key: str,
        operation_fingerprint: str,
    ) -> ToolAttemptObservation:
        if type(grant) is not MedicalPhysicalGrant:
            raise DomainExtensionError("medical physical authorization required")
        expected_sig = hmac.new(
            self._secret, grant.payload.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected_sig, grant.signature):
            raise DomainExtensionError("medical physical signature invalid")
        try:
            claims = json.loads(grant.payload)
        except (ValueError, TypeError) as exc:
            raise DomainExtensionError("medical physical grant invalid") from exc
        if type(claims) is not dict or claims != {
            "run_id": run_id,
            "request_id": request_id,
            "domain_fingerprint": domain_fingerprint,
            "identity_scope": identity_scope,
            "approved_plan_id": approved_plan_id,
            "step_execution_id": step_execution_id,
            "tool_id": tool_id,
            "logical_tool_call_id": logical_tool_call_id,
            "physical_attempt": physical_attempt,
            "operation_key": operation_key,
            "operation_fingerprint": operation_fingerprint,
            "input_digest": _digest(input_payload),
            "expires_at": claims.get("expires_at"),
            "nonce": claims.get("nonce"),
        }:
            raise DomainExtensionError("medical physical scope mismatch")
        expiry = claims["expires_at"]
        nonce = claims["nonce"]
        if (
            type(expiry) is not int
            or int(self._clock()) >= expiry
            or type(nonce) is not str
            or len(nonce) != 32
        ):
            raise DomainExtensionError("medical physical grant expired or invalid")
        if not self._claims.claim_once(nonce):
            raise DomainExtensionError("medical physical replay rejected")
        # Claim BEFORE first external effect. Exception/crash => UNKNOWN, no replay.
        return await self._physical.execute_physical_attempt(
            logical_tool_call_id=logical_tool_call_id,
            tool_id=tool_id,
            input_payload=input_payload,
            physical_attempt=physical_attempt,
            idempotency_key=idempotency_key,
            operation_key=operation_key,
            operation_fingerprint=operation_fingerprint,
        )
