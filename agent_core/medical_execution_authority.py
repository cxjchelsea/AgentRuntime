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
import time
from dataclasses import dataclass
from typing import Callable

from agent_core.domain_extension import DomainExtensionError
from runtime.contracts import RuntimeInput


@dataclass(frozen=True, slots=True)
class MedicalExecutionPermit:
    payload: str
    signature: str


class MedicalExecutionAuthority:
    """Mint and consume exactly once a run/request/domain/subject-bound permit."""

    def __init__(
        self,
        secret: bytes,
        *,
        clock: Callable[[], float] = time.time,
        ttl_seconds: int = 60,
    ) -> None:
        if type(secret) is not bytes or len(secret) < 32:
            raise DomainExtensionError("medical issuer requires a trusted key")
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 300:
            raise DomainExtensionError("invalid medical permit lifetime")
        self._secret = secret
        self._clock = clock
        self._ttl = ttl_seconds
        self._consumed: set[str] = set()

    def issue(
        self,
        *,
        initial: RuntimeInput,
        run_id: str,
        domain_id: str,
        binding_fingerprint: str,
        policy_version: str,
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
        }
        payload = json.dumps(data, separators=(",", ":"), sort_keys=True)
        sig = hmac.new(self._secret, payload.encode(), hashlib.sha256).hexdigest()
        return MedicalExecutionPermit(payload, sig)

    def consume(
        self,
        permit: MedicalExecutionPermit,
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
        if nonce in self._consumed:
            raise DomainExtensionError("medical authorization replay")
        self._consumed.add(nonce)
