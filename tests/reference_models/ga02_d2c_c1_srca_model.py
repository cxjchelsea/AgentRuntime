"""NON_PRODUCTION_SIMULATION: GA-02 D2-C C1-SRC-A isolated reference model.

Test support only. No runtime imports, Host issuer, Registry, IO or permissions.
It models one process's atomic transitions under a Python RLock; this is NOT
durable CAS, cross-worker fencing, or a trusted Catalog implementation.
"""
from __future__ import annotations

import hashlib
import json
import threading
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal

ROLE = "NON_PRODUCTION_SIMULATION"
_SOURCE = "SIMULATED_HOST_SEALED_CANDIDATE"


class SimulatedDenial(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _deny(code: str) -> None:
    raise SimulatedDenial(code)


def _validate(v: Any) -> None:
    if type(v) is str:
        if not v or len(v) > 1024 or unicodedata.normalize("NFC", v) != v:
            _deny("C1_INPUT_INVALID")
        if any(unicodedata.category(c) in {"Cc", "Cs"} for c in v):
            _deny("C1_INPUT_INVALID")
    elif type(v) is list:
        for x in v:
            _validate(x)
    elif type(v) is dict:
        for k, x in v.items():
            if type(k) is not str:
                _deny("C1_INPUT_INVALID")
            _validate(k)
            _validate(x)
    elif v is None or type(v) in (bool, int):
        return
    else:
        _deny("C1_INPUT_INVALID")


def canonical(v: Any) -> bytes:
    _validate(v)
    try:
        data = json.dumps(
            v, sort_keys=True, ensure_ascii=False,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8", "strict")
    except (UnicodeError, ValueError, TypeError):
        _deny("C1_INPUT_INVALID")
    if len(data) > 2097152:
        _deny("C1_RESOURCE_LIMIT")
    return data


def canonical_wire(raw: bytes) -> Any:
    if type(raw) is not bytes or len(raw) > 2097152:
        _deny("C1_RESOURCE_LIMIT")
    def pairs(v: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, x in v:
            if k in out:
                _deny("C1_INPUT_INVALID")
            out[k] = x
        return out
    try:
        obj = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=pairs)
    except (ValueError, UnicodeError):
        _deny("C1_INPUT_INVALID")
    if canonical(obj) != raw:
        _deny("C1_INPUT_INVALID")
    return obj


def digest(profile: str, value: Any) -> str:
    return hashlib.sha256(profile.encode("ascii") + b"\0" + canonical(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class Principal:
    name: str
    lane: str
    simulation_role: Literal["NON_PRODUCTION_SIMULATION"] = ROLE  # type: ignore[assignment]


@dataclass(frozen=True, slots=True)
class SealedCandidate:
    lane: str
    policy: str
    package: str
    image: bytes
    image_digest: str
    source: Literal["SIMULATED_HOST_SEALED_CANDIDATE"] = _SOURCE  # type: ignore[assignment]


@dataclass(frozen=True, slots=True)
class SimulatedEvidence:
    evidence_id: str
    lane: str
    principal: str
    epoch: int
    generation: str
    image_digest: str
    role: str = ROLE


@dataclass(slots=True)
class _Lane:
    revision: int = 0
    term: int = 0
    epoch: int = 0
    generation: str = ""
    image_digest: str = ""
    policy: str = ""
    package: str = ""
    revoked: bool = False


@dataclass(slots=True)
class _Lease:
    principal: str
    lane: str
    revision: int
    epoch: int
    generation: str
    policy: str
    package: str
    active: bool = True


def synthetic_candidate(
    *, lane: str, policy: str, package: str, image: dict[str, Any]
) -> SealedCandidate:
    """Admit a test-owned image as data, never a real Host credential."""
    for s in (lane, policy, package):
        _validate(s)
    raw = canonical(image)
    return SealedCandidate(
        lane, policy, package, raw,
        hashlib.sha256(raw).hexdigest(),
    )


def check_optional_absences(
    declared: tuple[tuple[str, str, bool], ...],
    edges: tuple[tuple[str, str], ...],
    absences: tuple[tuple[str, str, str], ...],
    *,
    policy: str,
) -> tuple[tuple[str, str], ...]:
    """Explicit Host-like policy approval is simulation input, not authentication."""
    seen: set[tuple[str, str]] = set()
    resolved: list[tuple[str, str]] = []
    edge_set = set(edges)
    absence_set = {(rel, target) for rel, target, _ in absences}
    if len(edge_set) != len(edges) or len(absence_set) != len(absences):
        _deny("C1_DEPENDENCY_INVALID")
    if any(p != policy for _, _, p in absences):
        _deny("C1_LANE_SCOPE_MISMATCH")
    for relation, target, required in declared:
        key = (relation, target)
        if key in seen:
            _deny("C1_DEPENDENCY_INVALID")
        seen.add(key)
        has_edge, has_absence = key in edge_set, key in absence_set
        if (has_edge and has_absence) or (not has_edge and not has_absence):
            _deny("C1_DEPENDENCY_INVALID")
        if required and has_absence:
            _deny("C1_DEPENDENCY_INVALID")
        if has_edge:
            resolved.append(key)
    if edge_set - seen or absence_set - seen:
        _deny("C1_DEPENDENCY_INVALID")
    return tuple(sorted(resolved))


class TestOnlyCatalog:
    """Deterministic in-memory reference. RLock != durable DB transaction."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._lanes: dict[str, _Lane] = {}
        self._images: dict[str, bytes] = {}
        self._leases: dict[str, _Lease] = {}
        self._issuance: dict[tuple[str, str], tuple[str, SimulatedEvidence]] = {}
        self._transactions: dict[tuple[str, str], tuple[str, int]] = {}
        self._counter = 0

    def _lane(self, lane: str) -> _Lane:
        return self._lanes.setdefault(lane, _Lane())

    def _auth(self, principal: Principal, lane: str) -> None:
        if type(principal) is not Principal or principal.simulation_role != ROLE:
            _deny("C1_ISSUER_UNVERIFIED")
        if principal.lane != lane:
            _deny("C1_LANE_SCOPE_MISMATCH")

    def take_writer_term(self, principal: Principal) -> tuple[int, int]:
        self._auth(principal, principal.lane)
        with self._lock:
            state = self._lane(principal.lane)
            state.term += 1
            return state.term, state.revision

    def publish(
        self, principal: Principal, candidate: SealedCandidate, *,
        term: int, expected_revision: int, tx_id: str,
    ) -> tuple[int, int]:
        self._auth(principal, candidate.lane)
        if type(candidate) is not SealedCandidate or candidate.source != _SOURCE:
            _deny("C1_ISSUER_UNVERIFIED")
        if hashlib.sha256(candidate.image).hexdigest() != candidate.image_digest:
            _deny("C1_PUBLICATION_DIGEST_MISMATCH")
        canonical_wire(candidate.image)
        fingerprint = digest("GA02-D2C-C1-SIM-PUBLISH-1", {
            "candidate": candidate.image_digest, "lane": candidate.lane,
            "package": candidate.package, "policy": candidate.policy,
        })
        with self._lock:
            state = self._lane(candidate.lane)
            prior = self._transactions.get((candidate.lane, tx_id))
            if prior is not None:
                if prior[0] != fingerprint:
                    _deny("C1_ISSUANCE_CONFLICT")
                return prior[1], prior[1]
            if term != state.term:
                _deny("C1_WRITER_FENCE_INVALID")
            if expected_revision != state.revision:
                _deny("C1_EPOCH_STALE")
            state.revision += 1
            state.epoch += 1
            state.generation = f"sim-generation-{state.revision}"
            state.revoked = False
            state.policy = candidate.policy
            state.package = candidate.package
            state.image_digest = candidate.image_digest
            self._images[candidate.image_digest] = candidate.image
            self._transactions[(candidate.lane, tx_id)] = (fingerprint, state.revision)
            return state.revision, state.epoch

    def revoke(self, principal: Principal) -> int:
        self._auth(principal, principal.lane)
        with self._lock:
            lane = self._lane(principal.lane)
            lane.revision += 1
            lane.revoked = True
            return lane.revision

    def open_lease(self, principal: Principal, lease_id: str) -> None:
        self._auth(principal, principal.lane)
        with self._lock:
            if lease_id in self._leases:
                _deny("C1_LEASE_INVALID")
            lane = self._lane(principal.lane)
            if not lane.generation or lane.revoked:
                _deny("C1_PUBLICATION_REVOKED")
            self._leases[lease_id] = _Lease(
                principal.name, principal.lane, lane.revision, lane.epoch,
                lane.generation, lane.policy, lane.package,
            )

    def issue(
        self, principal: Principal, *, lease_id: str, request_id: str,
        request_payload: dict[str, Any],
    ) -> SimulatedEvidence:
        self._auth(principal, principal.lane)
        fp = digest("GA02-D2C-C1-SIM-ISSUANCE-1", {
            "principal": principal.name, "lane": principal.lane,
            "lease": lease_id, "request": request_payload,
        })
        with self._lock:
            key = (principal.lane, request_id)
            prior = self._issuance.get(key)
            if prior is not None:
                if prior[1].principal != principal.name:
                    _deny("C1_ISSUER_UNVERIFIED")
                if prior[0] != fp:
                    _deny("C1_ISSUANCE_CONFLICT")
                return prior[1]  # Historical non-runnable lookup; no reissuance
            lease = self._leases.get(lease_id)
            if lease is None or lease.principal != principal.name:
                _deny("C1_LEASE_INVALID")
            if lease.lane != principal.lane:
                _deny("C1_LANE_SCOPE_MISMATCH")
            lane = self._lane(principal.lane)
            if lane.revoked:
                _deny("C1_PUBLICATION_REVOKED")
            if not lease.active:
                _deny("C1_LEASE_INVALID")
            if (lease.revision, lease.epoch, lease.generation, lease.policy, lease.package) != (
                lane.revision, lane.epoch, lane.generation, lane.policy, lane.package,
            ):
                _deny("C1_EPOCH_STALE")
            if hashlib.sha256(self._images.get(lane.image_digest, b"")).hexdigest() != lane.image_digest:
                _deny("C1_PUBLICATION_DIGEST_MISMATCH")
            self._counter += 1
            evidence = SimulatedEvidence(
                f"sim-evidence-{self._counter}", principal.lane, principal.name,
                lane.epoch, lane.generation, lane.image_digest,
            )
            lease.active = False
            self._issuance[key] = (fp, evidence)
            return evidence

    def counts(self) -> tuple[int, int]:
        with self._lock:
            return sum(x.revision for x in self._lanes.values()), len(self._issuance)
