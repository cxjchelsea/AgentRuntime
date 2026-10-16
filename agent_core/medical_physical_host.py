"""Medical Host-owned physical attempt gate (synthetic integration adapter).

Only the trusted composition root may hold the underlying physical executor and
grant issuer. This module intentionally supplies no production credential store.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from agent_core.domain_extension import DomainExtensionError
from agent_core.medical_execution_authority import MedicalExecutionPermit
from runtime.execution.invocation import (
    PhysicalToolAttemptExecutor,
    ToolAttemptObservation,
)


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


class SQLiteOperationClaimStore:
    """Durable single-use nonce claim; local SQLite integration only.

    A crash after admission consumes the claim permanently. This is not
    distributed fencing or proof of an external side effect's completion.
    """

    def __init__(self, path: Path) -> None:
        if not isinstance(path, Path):
            raise DomainExtensionError("invalid operation claim path")
        self._path = path
        try:
            with sqlite3.connect(self._path, timeout=5) as connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS medical_physical_claims "
                    "(nonce TEXT PRIMARY KEY NOT NULL, state TEXT NOT NULL)"
                )
        except sqlite3.Error as exc:
            raise DomainExtensionError("physical claim storage unavailable") from exc

    def claim_once(self, operation_nonce: str) -> bool:
        if type(operation_nonce) is not str or not operation_nonce:
            raise DomainExtensionError("invalid physical claim nonce")
        try:
            with sqlite3.connect(self._path, timeout=5) as connection:
                connection.execute(
                    "INSERT INTO medical_physical_claims(nonce, state) VALUES (?, ?)",
                    (operation_nonce, "UNKNOWN_EXTERNAL_OUTCOME"),
                )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint failed" in str(exc):
                return False
            raise DomainExtensionError("physical claim integrity failure") from exc
        except sqlite3.Error as exc:
            raise DomainExtensionError("physical claim storage unavailable") from exc
        return True


    def state(self, operation_key: str) -> str | None:
        """Return durable outcome. UNKNOWN must never trigger automatic retry."""
        try:
            with sqlite3.connect(self._path, timeout=5) as connection:
                row = connection.execute(
                    "SELECT state FROM medical_physical_claims WHERE nonce = ?",
                    (operation_key,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise DomainExtensionError("physical claim storage unavailable") from exc
        return str(row[0]) if row else None

    def confirm(self, operation_key: str) -> None:
        try:
            with sqlite3.connect(self._path, timeout=5) as connection:
                changed = connection.execute(
                    "UPDATE medical_physical_claims SET state = ? "
                    "WHERE nonce = ? AND state = ?",
                    ("CONFIRMED", operation_key, "UNKNOWN_EXTERNAL_OUTCOME"),
                ).rowcount
        except sqlite3.Error as exc:
            raise DomainExtensionError("physical claim storage unavailable") from exc
        if changed != 1:
            raise DomainExtensionError("physical claim cannot be confirmed")


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
            run_id,
            request_id,
            domain_fingerprint,
            identity_scope,
            approved_plan_id,
            step_execution_id,
            tool_id,
            logical_tool_call_id,
            operation_key,
            operation_fingerprint,
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


class PermitBoundMedicalOperationIssuer:
    """Issue physical grants only after verifying a signed medical run permit.

    Trust in the medical permit's policy and its clinical safety is governed by
    the upstream issuer. The approved plan ID remains caller-supplied here;
    this adapter is not an independently attested M4 plan authority.
    """

    def __init__(
        self,
        *,
        operation_issuer: TrustedMedicalOperationIssuer,
        medical_permit_verifier_key: bytes,
        approved_plan_verifier: Callable[[str, str, str, str], bool],
    ) -> None:
        if (
            type(medical_permit_verifier_key) is not bytes
            or len(medical_permit_verifier_key) < 32
        ):
            raise DomainExtensionError("medical permit verifier unavailable")
        self._issuer = operation_issuer
        if not callable(approved_plan_verifier):
            raise DomainExtensionError("approved plan verifier required")
        self._plan_verifier = approved_plan_verifier
        self._key = medical_permit_verifier_key

    def grant_from_permit(
        self,
        *,
        permit: MedicalExecutionPermit,
        domain_id: str,
        policy_version: str,
        subject_id: str,
        session_id: str,
        **operation: object,
    ) -> MedicalPhysicalGrant:
        if type(permit) is not MedicalExecutionPermit:
            raise DomainExtensionError("medical run permit required")
        signature = hmac.new(
            self._key, permit.payload.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, permit.signature):
            raise DomainExtensionError("invalid medical run permit signature")
        try:
            claim = json.loads(permit.payload)
        except (TypeError, ValueError) as exc:
            raise DomainExtensionError("invalid medical run permit") from exc
        if type(claim) is not dict or claim != {
            "domain_id": domain_id,
            "domain_binding": operation.get("domain_fingerprint"),
            "policy_version": policy_version,
            "request_id": operation.get("request_id"),
            "run_id": operation.get("run_id"),
            "subject_id": subject_id,
            "identity_scope": operation.get("identity_scope"),
            "session_id": session_id,
            "expires_at": claim.get("expires_at"),
            "nonce": claim.get("nonce"),
            "safety_decision_digest": claim.get("safety_decision_digest"),
        }:
            raise DomainExtensionError("medical run permit scope mismatch")
        if (
            type(claim["expires_at"]) is not int
            or int(self._issuer._clock()) >= claim["expires_at"]
            or type(claim["nonce"]) is not str
            or len(claim["nonce"]) != 32
            or type(claim["safety_decision_digest"]) is not str
            or len(claim["safety_decision_digest"]) != 64
        ):
            raise DomainExtensionError("expired or invalid medical run permit")
        plan = operation.get("approved_plan_id")
        step = operation.get("step_execution_id")
        tool = operation.get("tool_id")
        run = operation.get("run_id")
        if not all(type(x) is str and x for x in (plan, step, tool, run)):
            raise DomainExtensionError("medical approved plan scope missing")
        try:
            approved = self._plan_verifier(str(run), str(plan), str(step), str(tool))
        except Exception as exc:
            raise DomainExtensionError(
                "medical approved plan authority unavailable"
            ) from exc
        if approved is not True:
            raise DomainExtensionError("medical physical plan authorization denied")
        return self._issuer.grant(**operation)  # type: ignore[arg-type]


def _digest(payload: dict[str, object]) -> str:
    try:
        raw = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
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
        operation_identity = {
            key: value
            for key, value in claims.items()
            if key not in ("expires_at", "nonce")
        }
        operation_claim_key = _digest(operation_identity)
        if not self._claims.claim_once(operation_claim_key):
            raise DomainExtensionError("medical physical replay rejected")
        # Claim BEFORE first external effect. Exception/crash => UNKNOWN, no replay.
        observed = await self._physical.execute_physical_attempt(
            logical_tool_call_id=logical_tool_call_id,
            tool_id=tool_id,
            input_payload=input_payload,
            physical_attempt=physical_attempt,
            idempotency_key=idempotency_key,
            operation_key=operation_key,
            operation_fingerprint=operation_fingerprint,
        )
        if isinstance(self._claims, SQLiteOperationClaimStore):
            self._claims.confirm(operation_claim_key)
        return observed
