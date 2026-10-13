"""C1-SRC-A isolated security reference model; NON_PRODUCTION_SIMULATION ONLY.

No production Host issuer, durable store, network, Registry, or runnable authority.
Thread locks and logical time are deliberate test simulation, NOT durable CAS.
"""

from __future__ import annotations

import hashlib
import json
import threading
import unicodedata
from dataclasses import dataclass
from typing import Any, NoReturn

ROLE = "NON_PRODUCTION_SIMULATION"


class SimulatedDenial(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _deny(code: str) -> NoReturn:
    raise SimulatedDenial(code)


def _validate(value: Any) -> None:
    if type(value) is str:
        if (
            not value
            or len(value) > 1024
            or unicodedata.normalize("NFC", value) != value
            or any(unicodedata.category(c) in {"Cc", "Cs"} for c in value)
        ):
            _deny("C1_INPUT_INVALID")
    elif type(value) is list:
        for item in value:
            _validate(item)
    elif type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                _deny("C1_INPUT_INVALID")
            _validate(key)
            _validate(item)
    elif value is None or type(value) in (bool, int):
        return
    else:
        _deny("C1_INPUT_INVALID")


def canonical(value: Any) -> bytes:
    _validate(value)
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8", "strict")
    except (UnicodeError, ValueError, TypeError):
        _deny("C1_INPUT_INVALID")
    if len(encoded) > 2097152:
        _deny("C1_RESOURCE_LIMIT")
    return encoded


def canonical_wire(raw: bytes) -> Any:
    if type(raw) is not bytes:
        _deny("C1_INPUT_INVALID")
    if len(raw) > 2097152:
        _deny("C1_RESOURCE_LIMIT")

    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in values:
            if key in output:
                _deny("C1_INPUT_INVALID")
            output[key] = value
        return output

    try:
        value = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=pairs)
    except (ValueError, UnicodeError):
        _deny("C1_INPUT_INVALID")
    if canonical(value) != raw:
        _deny("C1_INPUT_INVALID")
    return value


def digest(profile: str, value: Any) -> str:
    return hashlib.sha256(
        profile.encode("ascii") + b"\0" + canonical(value)
    ).hexdigest()


@dataclass(frozen=True, slots=True, eq=False)
class Principal:
    name: str
    lane: str
    role: str = ROLE


@dataclass(frozen=True, slots=True, eq=False)
class SealedCandidate:
    lane: str
    policy: str
    package: str
    image: bytes
    image_digest: str
    role: str = ROLE


@dataclass(frozen=True, slots=True, eq=False)
class ApprovedAbsence:
    source_kind: str
    source_namespace: str
    source_id: str
    source_version: str
    relation: str
    target_kind: str
    target_id: str
    occurrence: int
    policy: str
    digest: str
    role: str = ROLE


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
    owner: Principal
    lane: str
    revision: int
    epoch: int
    generation: str
    policy: str
    package: str
    expiry: int
    status: str = "ACTIVE"


@dataclass(frozen=True, slots=True)
class _Issuance:
    owner: Principal
    lease_id: str
    fingerprint: str
    policy: str
    package: str
    evidence: SimulatedEvidence
    evidence_digest: str
    record_digest: str


def _issuance_record_digest(
    owner: Principal,
    lease_id: str,
    fp: str,
    policy: str,
    package: str,
    evidence_digest: str,
) -> str:
    return digest(
        "GA02-D2C-C1-SIM-LEDGER-1",
        {
            "principal": owner.name,
            "lane": owner.lane,
            "lease": lease_id,
            "fingerprint": fp,
            "policy": policy,
            "package": package,
            "evidence_digest": evidence_digest,
        },
    )


def _evidence_digest(e: SimulatedEvidence) -> str:
    return digest(
        "GA02-D2C-C1-SIM-EVIDENCE-1",
        {
            "id": e.evidence_id,
            "lane": e.lane,
            "principal": e.principal,
            "epoch": e.epoch,
            "generation": e.generation,
            "image": e.image_digest,
            "role": e.role,
        },
    )


class PublicationResult(tuple[int, int]):
    """Tuple-compatible non-authorizing publication receipt."""

    historical: bool

    def __new__(
        cls, revision: int, epoch: int, *, historical: bool = False
    ) -> PublicationResult:
        receipt = tuple.__new__(cls, (revision, epoch))
        receipt.historical = historical
        return receipt


class TestOnlyCatalog:
    """Single-process reference with explicitly internal mock capability registry.

    Public enrollment methods are TEST FIXTURE SETUP only; they are NOT
    production authentication endpoints. Object identity is intentionally
    checked to reject independent same-value dataclass reconstruction.
    """

    __test__ = False

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._principals: dict[Principal, tuple[str, str, str]] = {}
        self._candidates: dict[
            SealedCandidate, tuple[Principal, str, str, str, bytes, str]
        ] = {}
        self._absences: dict[ApprovedAbsence, tuple[Principal, str, int, str, str]] = {}
        self._lanes: dict[str, _Lane] = {}
        self._images: dict[str, bytes] = {}
        self._leases: dict[str, _Lease] = {}
        self._issuance: dict[tuple[str, str], _Issuance] = {}
        self._transactions: dict[
            tuple[str, str], tuple[Principal, str, int, int, int, int]
        ] = {}
        self._counter = 0
        self._lease_counter = 0
        self._crash_stage: str | None = None
        self._clock = 0

    def mint_principal(self, name: str, lane: str) -> Principal:
        """TEST FIXTURE ONLY: simulate a trusted issuer's registration."""
        canonical({"name": name, "lane": lane})
        with self._lock:
            principal = Principal(name, lane)
            self._principals[principal] = (name, lane, ROLE)
            return principal

    def _auth(self, principal: Principal, lane: str) -> None:
        if type(principal) is not Principal or principal not in self._principals:
            _deny("C1_ISSUER_UNVERIFIED")
        if (principal.name, principal.lane, principal.role) != self._principals[
            principal
        ]:
            _deny("C1_ISSUER_UNVERIFIED")
        if principal.lane != lane:
            _deny("C1_LANE_SCOPE_MISMATCH")

    def admit_candidate(
        self,
        principal: Principal,
        *,
        policy: str,
        package: str,
        image: dict[str, Any],
    ) -> SealedCandidate:
        self._auth(principal, principal.lane)
        canonical({"policy": policy, "package": package})
        raw = canonical(image)
        with self._lock:
            candidate = SealedCandidate(
                principal.lane,
                policy,
                package,
                raw,
                hashlib.sha256(raw).hexdigest(),
            )
            self._candidates[candidate] = (
                principal,
                principal.lane,
                policy,
                package,
                raw,
                candidate.image_digest,
            )
            return candidate

    def approve_absence(
        self,
        principal: Principal,
        *,
        source_kind: str,
        source_namespace: str,
        source_id: str,
        source_version: str,
        relation: str,
        target_kind: str,
        target_id: str,
        occurrence: int,
        policy: str,
    ) -> ApprovedAbsence:
        self._auth(principal, principal.lane)
        if type(occurrence) is not int or occurrence < 0:
            _deny("C1_DEPENDENCY_INVALID")
        value = {
            "source_key": {
                "kind": source_kind,
                "namespace": source_namespace,
                "id": source_id,
                "version": source_version,
            },
            "relation": relation,
            "target_kind": target_kind,
            "target_id": target_id,
            "occurrence": occurrence,
            "host_policy_generation": policy,
            "reason": "HOST_APPROVED_OMISSION",
        }
        proof = digest("GA02-D2C-C1-SIM-OPTIONAL-ABSENCE-1", value)
        with self._lock:
            approved = ApprovedAbsence(
                source_kind,
                source_namespace,
                source_id,
                source_version,
                relation,
                target_kind,
                target_id,
                occurrence,
                policy,
                proof,
            )
            lane = self._lane(principal.lane)
            if not lane.generation or lane.revoked or policy != lane.policy:
                _deny("C1_LANE_SCOPE_MISMATCH")
            self._absences[approved] = (
                principal,
                proof,
                lane.epoch,
                lane.generation,
                policy,
            )
            return approved

    def check_absences(
        self,
        principal: Principal,
        *,
        source: tuple[str, str, str, str],
        declared: tuple[tuple[str, str, str, int, bool], ...],
        edges: tuple[tuple[str, str, str, int], ...],
        absences: tuple[ApprovedAbsence, ...],
        policy: str,
    ) -> tuple[tuple[str, str, str, int], ...]:
        self._auth(principal, principal.lane)
        with self._lock:
            lane_state = self._lane(principal.lane)
            if lane_state.revoked or not lane_state.generation:
                _deny("C1_PUBLICATION_REVOKED")
            approved: set[tuple[str, str, str, int]] = set()
            for a in absences:
                if type(a) is not ApprovedAbsence or a not in self._absences:
                    _deny("C1_ISSUER_UNVERIFIED")
                admitted_owner, original_digest, epoch, generation, original_policy = (
                    self._absences[a]
                )
                lane = self._lane(principal.lane)
                if (
                    admitted_owner is not principal
                    or epoch != lane.epoch
                    or generation != lane.generation
                ):
                    _deny("C1_EPOCH_STALE")
                canonical_value = {
                    "source_key": {
                        "kind": a.source_kind,
                        "namespace": a.source_namespace,
                        "id": a.source_id,
                        "version": a.source_version,
                    },
                    "relation": a.relation,
                    "target_kind": a.target_kind,
                    "target_id": a.target_id,
                    "occurrence": a.occurrence,
                    "host_policy_generation": a.policy,
                    "reason": "HOST_APPROVED_OMISSION",
                }
                if (
                    a.digest != original_digest
                    or a.digest
                    != digest("GA02-D2C-C1-SIM-OPTIONAL-ABSENCE-1", canonical_value)
                    or a.policy != original_policy
                ):
                    _deny("C1_PUBLICATION_DIGEST_MISMATCH")
                if a.policy != policy or a.policy != self._lane(principal.lane).policy:
                    _deny("C1_LANE_SCOPE_MISMATCH")
                if (
                    a.source_kind,
                    a.source_namespace,
                    a.source_id,
                    a.source_version,
                ) != source:
                    _deny("C1_DEPENDENCY_INVALID")
                key = (a.relation, a.target_kind, a.target_id, a.occurrence)
                if key in approved:
                    _deny("C1_DEPENDENCY_INVALID")
                approved.add(key)
            declared_keys = {
                (rel, kind, target, n) for rel, kind, target, n, _ in declared
            }
            edge_keys = set(edges)
            if len(declared_keys) != len(declared) or len(edge_keys) != len(edges):
                _deny("C1_DEPENDENCY_INVALID")
            if (approved | edge_keys) != declared_keys or approved & edge_keys:
                _deny("C1_DEPENDENCY_INVALID")
            if any(
                key in approved
                for *parts, required in declared
                if required
                for key in [tuple(parts)]
            ):
                _deny("C1_DEPENDENCY_INVALID")
            return tuple(sorted(edge_keys))

    def _lane(self, lane: str) -> _Lane:
        return self._lanes.setdefault(lane, _Lane())

    def take_writer_term(self, principal: Principal) -> tuple[int, int]:
        self._auth(principal, principal.lane)
        with self._lock:
            lane = self._lane(principal.lane)
            lane.term += 1
            return lane.term, lane.revision

    def publish(
        self,
        principal: Principal,
        candidate: SealedCandidate,
        *,
        term: int,
        expected_revision: int,
        tx_id: str,
    ) -> PublicationResult:
        self._auth(principal, principal.lane)
        if type(candidate) is not SealedCandidate or candidate not in self._candidates:
            _deny("C1_ISSUER_UNVERIFIED")
        (
            owner,
            admitted_lane,
            admitted_policy,
            admitted_package,
            admitted_bytes,
            admitted_digest,
        ) = self._candidates[candidate]
        if owner is not principal:
            _deny("C1_ISSUER_UNVERIFIED")
        if (
            candidate.lane,
            candidate.policy,
            candidate.package,
            candidate.image,
            candidate.image_digest,
        ) != (
            admitted_lane,
            admitted_policy,
            admitted_package,
            admitted_bytes,
            admitted_digest,
        ):
            _deny("C1_PUBLICATION_DIGEST_MISMATCH")
        if candidate.lane != principal.lane:
            _deny("C1_LANE_SCOPE_MISMATCH")
        if hashlib.sha256(candidate.image).hexdigest() != candidate.image_digest:
            _deny("C1_PUBLICATION_DIGEST_MISMATCH")
        canonical_wire(candidate.image)
        fp = digest(
            "GA02-D2C-C1-SIM-PUBLISH-1",
            {
                "image": candidate.image_digest,
                "lane": candidate.lane,
                "package": candidate.package,
                "policy": candidate.policy,
            },
        )
        with self._lock:
            lane = self._lane(principal.lane)
            previous = self._transactions.get((principal.lane, tx_id))
            if previous is not None:
                old_owner, old_fp, old_rev, old_epoch, old_term, old_expected = previous
                if old_owner is not principal:
                    _deny("C1_ISSUER_UNVERIFIED")
                if (
                    old_fp != fp
                    or old_term != term
                    or old_expected != expected_revision
                ):
                    _deny("C1_ISSUANCE_CONFLICT")
                return PublicationResult(old_rev, old_epoch, historical=True)
            self._crash("BEFORE_PUBLISH_CAS")
            if term != lane.term:
                _deny("C1_WRITER_FENCE_INVALID")
            if expected_revision != lane.revision:
                _deny("C1_EPOCH_STALE")
            lane.revision += 1
            lane.epoch += 1
            lane.generation = f"sim-gen-{lane.revision}"
            lane.revoked = False
            lane.policy, lane.package = candidate.policy, candidate.package
            lane.image_digest = candidate.image_digest
            self._images[candidate.image_digest] = candidate.image
            result = (lane.revision, lane.epoch)
            self._transactions[(principal.lane, tx_id)] = (
                principal,
                fp,
                result[0],
                result[1],
                term,
                expected_revision,
            )
            self._crash("AFTER_PUBLISH_CAS")
            return PublicationResult(*result, historical=False)

    def revoke(self, principal: Principal) -> int:
        self._auth(principal, principal.lane)
        with self._lock:
            lane = self._lane(principal.lane)
            lane.revision += 1
            lane.revoked = True
            return lane.revision

    def advance_clock(self, ticks: int) -> None:
        if type(ticks) is not int or ticks < 0:
            _deny("C1_INPUT_INVALID")
        with self._lock:
            self._clock += ticks

    def open_lease(self, principal: Principal, *, ttl: int = 10) -> str:
        self._auth(principal, principal.lane)
        if type(ttl) is not int or ttl <= 0:
            _deny("C1_LEASE_INVALID")
        with self._lock:
            lane = self._lane(principal.lane)
            if not lane.generation or lane.revoked:
                _deny("C1_PUBLICATION_REVOKED")
            self._lease_counter += 1
            lease_id = f"sim-lease-{self._lease_counter}"
            self._leases[lease_id] = _Lease(
                principal,
                principal.lane,
                lane.revision,
                lane.epoch,
                lane.generation,
                lane.policy,
                lane.package,
                self._clock + ttl,
            )
            return lease_id

    def close_lease(self, principal: Principal, lease_id: str) -> None:
        self._change_lease(principal, lease_id, "CLOSED")

    def revoke_lease(self, principal: Principal, lease_id: str) -> None:
        self._change_lease(principal, lease_id, "REVOKED")

    def _change_lease(self, principal: Principal, lease_id: str, status: str) -> None:
        self._auth(principal, principal.lane)
        with self._lock:
            lease = self._leases.get(lease_id)
            if lease is None or lease.owner is not principal:
                _deny("C1_LEASE_INVALID")
            if lease.status != "ACTIVE":
                _deny("C1_LEASE_INVALID")
            lease.status = status

    def issue(
        self,
        principal: Principal,
        *,
        lease_id: str,
        request_id: str,
        request_payload: dict[str, Any],
    ) -> SimulatedEvidence:
        self._auth(principal, principal.lane)
        fingerprint = digest(
            "GA02-D2C-C1-SIM-ISSUANCE-1",
            {
                "principal": principal.name,
                "lane": principal.lane,
                "lease": lease_id,
                "request": request_payload,
            },
        )
        with self._lock:
            key = (principal.lane, request_id)
            previous = self._issuance.get(key)
            if previous is not None:
                if previous.owner is not principal:
                    _deny("C1_ISSUER_UNVERIFIED")
                if previous.fingerprint != fingerprint or previous.lease_id != lease_id:
                    _deny("C1_ISSUANCE_CONFLICT")
                saved_lease = self._leases.get(previous.lease_id)
                if (
                    saved_lease is None
                    or saved_lease.owner is not principal
                    or saved_lease.policy != previous.policy
                    or saved_lease.package != previous.package
                ):
                    _deny("C1_PUBLICATION_DIGEST_MISMATCH")
                if previous.evidence_digest != _evidence_digest(
                    previous.evidence
                ) or previous.record_digest != _issuance_record_digest(
                    previous.owner,
                    previous.lease_id,
                    previous.fingerprint,
                    previous.policy,
                    previous.package,
                    previous.evidence_digest,
                ):
                    _deny("C1_PUBLICATION_DIGEST_MISMATCH")
                return previous.evidence  # immutable historical, not fresh authority
            lease = self._leases.get(lease_id)
            if lease is None or lease.owner is not principal:
                _deny("C1_LEASE_INVALID")
            if lease.lane != principal.lane:
                _deny("C1_LANE_SCOPE_MISMATCH")
            lane = self._lane(principal.lane)
            if lane.revoked:
                _deny("C1_PUBLICATION_REVOKED")
            if lease.status != "ACTIVE" or self._clock >= lease.expiry:
                _deny("C1_LEASE_INVALID")
            if (
                lease.revision,
                lease.epoch,
                lease.generation,
                lease.policy,
                lease.package,
            ) != (
                lane.revision,
                lane.epoch,
                lane.generation,
                lane.policy,
                lane.package,
            ):
                _deny("C1_EPOCH_STALE")
            if (
                hashlib.sha256(self._images.get(lane.image_digest, b"")).hexdigest()
                != lane.image_digest
            ):
                _deny("C1_PUBLICATION_DIGEST_MISMATCH")
            self._crash("BEFORE_ISSUE_CAS")
            self._counter += 1
            evidence = SimulatedEvidence(
                f"sim-evidence-{self._counter}",
                principal.lane,
                principal.name,
                lane.epoch,
                lane.generation,
                lane.image_digest,
            )
            lease.status = "CONSUMED"
            ed = _evidence_digest(evidence)
            self._issuance[key] = _Issuance(
                principal,
                lease_id,
                fingerprint,
                lane.policy,
                lane.package,
                evidence,
                ed,
                _issuance_record_digest(
                    principal, lease_id, fingerprint, lane.policy, lane.package, ed
                ),
            )
            self._crash("AFTER_ISSUE_CAS")
            return evidence

    def simulate_crash_at(self, stage: str | None) -> None:
        """Fault injection is single-process and never proves durable recovery."""
        if stage not in (
            None,
            "BEFORE_PUBLISH_CAS",
            "AFTER_PUBLISH_CAS",
            "BEFORE_ISSUE_CAS",
            "AFTER_ISSUE_CAS",
        ):
            _deny("C1_INPUT_INVALID")
        self._crash_stage = stage

    def _crash(self, stage: str) -> None:
        if self._crash_stage == stage:
            self._crash_stage = None
            _deny("C1_SIMULATED_CRASH")

    def counts(self) -> tuple[int, int]:
        with self._lock:
            return sum(lane.revision for lane in self._lanes.values()), len(
                self._issuance
            )
