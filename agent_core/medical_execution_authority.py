"""Host-owned one-use medical execution authorization for the application boundary.

This is a local-process prototype: the issuer/key/nonce registry must live in
the trusted Host (durably shared across workers for production). A domain
package or model must never receive the signing key.
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
from runtime.contracts import RuntimeInput


@dataclass(frozen=True, slots=True)
class MedicalExecutionPermit:
    payload: str
    signature: str


class MedicalPermitConsumptionStore(Protocol):
    """Host-owned atomic, durable compare-and-set consumption boundary."""

    def consume_once(self, nonce: str, expires_at: int) -> bool: ...


class InMemoryMedicalPermitStore:
    """Single-process testing only; NOT production durable or cross-worker."""

    def __init__(self) -> None:
        self._consumed: set[str] = set()

    def consume_once(self, nonce: str, expires_at: int) -> bool:
        del expires_at
        if nonce in self._consumed:
            return False
        self._consumed.add(nonce)
        return True


class SQLiteMedicalPermitStore:
    """Durable SQLite uniqueness fence for local integration, not a production DB."""

    def __init__(self, path: Path) -> None:
        if not isinstance(path, Path):
            raise DomainExtensionError("invalid medical permit store path")
        self._path = path
        with sqlite3.connect(self._path, timeout=5.0) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS medical_permit_consumption "
                "(nonce TEXT PRIMARY KEY, expires_at INTEGER NOT NULL)"
            )

    def consume_once(self, nonce: str, expires_at: int) -> bool:
        try:
            with sqlite3.connect(self._path, timeout=5.0) as db:
                db.execute(
                    "INSERT INTO medical_permit_consumption(nonce, expires_at) "
                    "VALUES (?, ?)",
                    (nonce, expires_at),
                )
            return True
        except sqlite3.IntegrityError as exc:
            if (
                getattr(exc, "sqlite_errorcode", None)
                == sqlite3.SQLITE_CONSTRAINT_PRIMARYKEY
            ):
                return False
            raise DomainExtensionError(
                "medical permit storage integrity failure"
            ) from exc
        except sqlite3.Error as exc:
            raise DomainExtensionError("medical permit storage unavailable") from exc


@dataclass(frozen=True, slots=True)
class MedicalSafetyClearance:
    """Signed evidence of a trusted ALLOW decision, not a clinical judgment."""

    payload: str
    signature: str


class MedicalSafetyDecisionSigner:
    """Trusted Host component, separate from the execution permit issuer."""

    def __init__(self, secret: bytes, *, rejected_phrases: tuple[str, ...]) -> None:
        if not rejected_phrases or any(not phrase for phrase in rejected_phrases):
            raise DomainExtensionError("medical safety policy unavailable")
        self.rejected_phrases = rejected_phrases
        if type(secret) is not bytes or len(secret) < 32:
            raise DomainExtensionError("invalid medical safety decision key")
        self._secret = secret

    def approve(
        self,
        *,
        initial: RuntimeInput,
        run_id: str,
        domain_id: str,
        binding_fingerprint: str,
        policy_version: str,
    ) -> MedicalSafetyClearance:
        if type(initial) is not RuntimeInput or not initial.text:
            raise DomainExtensionError("medical safety input unavailable")
        normalized = " ".join(initial.text.casefold().split())
        if any(phrase in normalized for phrase in self.rejected_phrases):
            raise DomainExtensionError("medical safety decision denied")
        claims = {
            "decision": "ALLOW",
            "request_id": initial.request_id,
            "run_id": run_id,
            "domain_id": domain_id,
            "domain_binding": binding_fingerprint,
            "policy_version": policy_version,
            "subject_id": initial.subject_id,
            "identity_scope": initial.identity_scope,
            "session_id": initial.session_id,
            "input_sha256": hashlib.sha256(
                initial.text.encode("utf-8") if initial.text else b""
            ).hexdigest(),
        }
        payload = json.dumps(claims, sort_keys=True, separators=(",", ":"))
        return MedicalSafetyClearance(
            payload,
            hmac.new(self._secret, payload.encode(), hashlib.sha256).hexdigest(),
        )


class MedicalExecutionAuthority:
    """Mint and consume exactly once a run/request/domain/subject-bound permit."""

    def __init__(
        self,
        secret: bytes,
        *,
        clock: Callable[[], float] = time.time,
        ttl_seconds: int = 60,
        store: MedicalPermitConsumptionStore | None = None,
        decision_verifier_key: bytes | None = None,
    ) -> None:
        if type(secret) is not bytes or len(secret) < 32:
            raise DomainExtensionError("medical issuer requires a trusted key")
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 300:
            raise DomainExtensionError("invalid medical permit lifetime")
        if type(decision_verifier_key) is not bytes or len(decision_verifier_key) < 32:
            raise DomainExtensionError("medical safety decision verifier unavailable")
        self._decision_key = decision_verifier_key
        self._secret = secret
        self._clock = clock
        self._ttl = ttl_seconds
        self._store = store if store is not None else InMemoryMedicalPermitStore()

    def issue(
        self,
        *,
        initial: RuntimeInput,
        run_id: str,
        domain_id: str,
        binding_fingerprint: str,
        policy_version: str,
        clearance: MedicalSafetyClearance | None = None,
    ) -> MedicalExecutionPermit:
        if (
            type(initial) is not RuntimeInput
            or type(run_id) is not str
            or not run_id
            or not domain_id.startswith("medical.")
            or type(binding_fingerprint) is not str
            or len(binding_fingerprint) != 64
            or type(policy_version) is not str
            or not policy_version
        ):
            raise DomainExtensionError("invalid medical authorization scope")
        if type(clearance) is not MedicalSafetyClearance:
            raise DomainExtensionError("trusted medical safety clearance required")
        expected = hmac.new(
            self._decision_key, clearance.payload.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, clearance.signature):
            raise DomainExtensionError("invalid medical safety decision signature")
        try:
            decision = json.loads(clearance.payload)
        except (ValueError, TypeError) as exc:
            raise DomainExtensionError(
                "invalid medical safety decision claims"
            ) from exc
        if type(decision) is not dict or decision != {
            "decision": "ALLOW",
            "request_id": initial.request_id,
            "run_id": run_id,
            "domain_id": domain_id,
            "domain_binding": binding_fingerprint,
            "policy_version": policy_version,
            "subject_id": initial.subject_id,
            "identity_scope": initial.identity_scope,
            "session_id": initial.session_id,
            "input_sha256": hashlib.sha256(
                initial.text.encode("utf-8") if initial.text else b""
            ).hexdigest(),
        }:
            raise DomainExtensionError("medical safety decision scope mismatch")
        data = {
            "domain_id": domain_id,
            "domain_binding": binding_fingerprint,
            "policy_version": policy_version,
            "request_id": initial.request_id,
            "run_id": run_id,
            "subject_id": initial.subject_id,
            "identity_scope": initial.identity_scope,
            "session_id": initial.session_id,
            "expires_at": int(self._clock()) + self._ttl,
            "nonce": secrets.token_hex(16),
            "safety_decision_digest": hashlib.sha256(
                clearance.payload.encode()
            ).hexdigest(),
        }
        payload = json.dumps(data, separators=(",", ":"), sort_keys=True)
        sig = hmac.new(self._secret, payload.encode(), hashlib.sha256).hexdigest()
        return MedicalExecutionPermit(payload, sig)

    def consume(
        self,
        permit: MedicalExecutionPermit | None,
        *,
        initial: RuntimeInput,
        run_id: str,
        domain_id: str,
        binding_fingerprint: str,
        policy_version: str,
    ) -> None:
        if type(permit) is not MedicalExecutionPermit:
            raise DomainExtensionError("missing medical execution authorization")
        expected = hmac.new(
            self._secret, permit.payload.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, permit.signature):
            raise DomainExtensionError("invalid medical execution signature")
        try:
            claims = json.loads(permit.payload)
        except (ValueError, TypeError) as exc:
            raise DomainExtensionError("invalid medical authorization claims") from exc
        if type(claims) is not dict or claims != {
            "domain_id": domain_id,
            "domain_binding": binding_fingerprint,
            "policy_version": policy_version,
            "request_id": initial.request_id,
            "run_id": run_id,
            "subject_id": initial.subject_id,
            "identity_scope": initial.identity_scope,
            "session_id": initial.session_id,
            "expires_at": claims.get("expires_at"),
            "nonce": claims.get("nonce"),
            "safety_decision_digest": claims.get("safety_decision_digest"),
        }:
            raise DomainExtensionError("medical execution scope mismatch")
        nonce = claims["nonce"]
        expiry = claims["expires_at"]
        if (
            type(nonce) is not str
            or len(nonce) != 32
            or type(expiry) is not int
            or int(self._clock()) >= expiry
        ):
            raise DomainExtensionError("expired or invalid medical authorization")
        if not self._store.consume_once(nonce, expiry):
            raise DomainExtensionError("medical authorization replay")
