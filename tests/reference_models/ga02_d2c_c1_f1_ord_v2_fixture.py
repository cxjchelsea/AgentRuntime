"""Isolated V2 omission fixture. TEST ONLY; no issuer, I/O, or production trust."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

PROFILE = "GA02-D2C-C1-OPTIONAL-ABSENCE-OCC-2"
ROLE = "NON_PRODUCTION_SIMULATION"
SOURCE = ("skill", "demo", "helper", "1.0.0")
RELATION = "skill.optional_tools"


class FixtureDenial(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, eq=False)
class Approval:
    """Handle identity is object identity; record is kept privately in fixture."""

    raw: bytes
    digest: str
    ordinal: int
    role: str = ROLE


@dataclass(frozen=True, eq=False)
class FixturePrincipal:
    name: str
    lane: str
    role: str = ROLE


class V2Fixture:
    """Small fail-closed, isolated contract oracle; never a production issuer."""

    def __init__(self) -> None:
        self._principals: set[FixturePrincipal] = set()
        self._approvals: dict[
            Approval, tuple[FixturePrincipal, str, str, str, int]
        ] = {}
        self.publication_count = 0
        self.issuance_count = 0
        self.external_side_effect_count = 0

    def principal(self, name: str = "test", lane: str = "lane-a") -> FixturePrincipal:
        principal = FixturePrincipal(name, lane)
        self._principals.add(principal)
        return principal

    def _authenticate(self, principal: FixturePrincipal) -> None:
        if type(principal) is not FixturePrincipal or principal not in self._principals:
            raise FixtureDenial("C1_ISSUER_UNVERIFIED")

    def approve(
        self,
        principal: FixturePrincipal,
        *,
        ordinal: int,
        policy: str = "p1",
        image: str = "image-a",
        transition: str = "transition-a",
    ) -> Approval:
        self._authenticate(principal)
        if type(ordinal) is not int or ordinal < 0:
            raise FixtureDenial("C1_DEPENDENCY_INVALID")
        raw = canonical_bytes(ordinal, policy=policy)
        value = Approval(raw, hash_bytes(raw), ordinal)
        self._approvals[value] = (principal, policy, image, transition, ordinal)
        return value

    def check(
        self,
        principal: FixturePrincipal,
        *,
        targets: tuple[str, ...] = ("tool-a",),
        edges: tuple[int, ...] = (),
        approvals: tuple[Approval, ...] = (),
        policy: str = "p1",
        lane: str = "lane-a",
        image: str = "image-a",
        transition: str = "transition-a",
        required: tuple[int, ...] = (),
        edge_targets_valid: bool = True,
    ) -> tuple[tuple[int, str], ...]:
        self._authenticate(principal)  # first-denial tier 1
        if (
            principal.lane != lane
            or policy != "p1"
            or image != "image-a"
            or transition != "transition-a"
        ):
            raise FixtureDenial("C1_LANE_SCOPE_MISMATCH")  # tier 2
        expected = set(range(len(targets)))
        if (
            any(type(i) is not int or i < 0 or i not in expected for i in edges)
            or len(set(edges)) != len(edges)
            or any(type(i) is not int or i < 0 or i not in expected for i in required)
        ):
            raise FixtureDenial("C1_DEPENDENCY_INVALID")  # tier 3
        indexes: list[int] = []
        for approval in approvals:
            if type(approval) is not Approval or approval not in self._approvals:
                raise FixtureDenial("C1_ISSUER_UNVERIFIED")  # forged handle
            (owner, saved_policy, saved_image, saved_transition, saved_ordinal) = (
                self._approvals[approval]
            )
            if (
                owner is not principal
                or saved_policy != policy
                or saved_image != image
                or saved_transition != transition
            ):
                raise FixtureDenial("C1_LANE_SCOPE_MISMATCH")
            i = approval.ordinal
            if type(i) is not int or i < 0 or i not in expected or i != saved_ordinal:
                raise FixtureDenial("C1_DEPENDENCY_INVALID")
            indexes.append(i)
        accepted = set(indexes)
        if (
            len(accepted) != len(indexes)
            or accepted & set(edges)
            or accepted | set(edges) != expected
            or accepted & set(required)
            or not edge_targets_valid
        ):
            raise FixtureDenial("C1_DEPENDENCY_INVALID")  # tier 4
        for approval in approvals:
            if (
                approval.role != ROLE
                or approval.raw
                != canonical_bytes(
                    approval.ordinal,
                    policy=policy,
                    target_id=targets[approval.ordinal],
                )
                or approval.digest != hash_bytes(approval.raw)
            ):
                raise FixtureDenial("C1_DEPENDENCY_INVALID")  # tier 5
        return tuple((i, targets[i]) for i in sorted(accepted))


def canonical_bytes(
    ordinal: int,
    *,
    policy: str = "p1",
    target_id: str = "tool-a",
) -> bytes:
    if type(ordinal) is not int or ordinal < 0:
        raise FixtureDenial("C1_DEPENDENCY_INVALID")
    value: dict[str, Any] = {
        "host_policy_generation": policy,
        "ordinal": ordinal,
        "reason": "HOST_APPROVED_OMISSION",
        "relation": RELATION,
        "source_key": {
            "kind": SOURCE[0],
            "namespace": SOURCE[1],
            "id": SOURCE[2],
            "version": SOURCE[3],
        },
        "target_kind": "tool",
        "target_id": target_id,
    }
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def hash_bytes(raw: bytes) -> str:
    return hashlib.sha256(PROFILE.encode("ascii") + b"\0" + raw).hexdigest()
