"""C1-SRC-A S1/S2: isolation-only golden and publisher/issuer simulation tests."""

import concurrent.futures
import hashlib
import json
import threading

import pytest

from tests.reference_models.ga02_d2c_c1_srca_model import (
    ROLE,
    Principal,
    SimulatedDenial,
    TestOnlyCatalog,
    ApprovedAbsence,
    SealedCandidate,
    canonical,
    canonical_wire,
    digest,
)


def denied(code: str, fn: object, *args: object, **kw: object) -> None:
    assert callable(fn)
    with pytest.raises(SimulatedDenial) as exc:
        fn(*args, **kw)
    assert exc.value.code == code


@pytest.mark.parametrize(
    ("profile", "raw", "size", "expected"),
    [
        (
            "GA02-D2C-C1-OPTIONAL-ABSENCE-1",
            '{"host_policy_generation":"p1","reason":"HOST_APPROVED_OMISSION","relation":"optional_tools","source_key":{"id":"helper","kind":"skill","namespace":"demo","version":"1.0.0"},"target_id":"tool-a","target_kind":"tool"}',
            216,
            "44d1052aafdb430e715230e5eb6cc8ea626253b2a10a13d9625d573138ab5c6a",
        ),
        (
            "GA02-D2C-C1-DEFINITION-1",
            '{"enabled":true,"name":"café","tags":["alpha","beta"],"version":"1.0.0"}',
            73,
            "a49961937c2704edcf37631248eed8525efec1e77d61a4923882ee3607b95e41",
        ),
        (
            "GA02-D2C-C1-IMAGE-1",
            '{"adapter_attestations":[{"adapter_generation":"a1","adapter_key":"lookup","registry_kind":"tool"}],"core_schema_allowlist":[],"epoch":2,"exact_edges":[{"relation":"required_tools","source":"skill-a","target":"tool-a"}],"generation_id":"gen-b","lane":{"domain_id":"demo","domain_version":"1.0.0","environment_id":"test","host_policy_id":"policy","namespace":"demo","tenant_scope_id":"tenant-a"},"policy_generation":"policy-gen-a","profile":"GA02-D2C-C1-IMAGE-1","registry_definitions":[{"id":"tool-a","kind":"tool","version":"1.0.0"}],"source_package_generation":"pkg-b","verified_manifest_sha256":"1111111111111111111111111111111111111111111111111111111111111111"}',
            665,
            "0c65de29a2298b52010538ba8a2806783eb0f6e5065a41bb69db02466e9d3599",
        ),
    ],
)
def test_f3_literal_vectors(profile: str, raw: str, size: int, expected: str) -> None:
    encoded = raw.encode("utf-8")
    assert len(encoded) == size
    assert hashlib.sha256(profile.encode() + b"\0" + encoded).hexdigest() == expected
    assert canonical_wire(encoded) == json.loads(raw)
    assert digest(profile, json.loads(raw)) == expected


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a":1,"a":2}',
        b'{"b":2,"a":1}',
        b'{"x":1.25}',
        b'{"x":NaN}',
        b'{"x":"\\ud800"}',
        b'{"x":"cafe\\u0301"}',
    ],
)
def test_f3_noncanonical_and_duplicate_wire_rejected(raw: bytes) -> None:
    denied("C1_INPUT_INVALID", canonical_wire, raw)


def test_f3_invalid_values_and_boundaries() -> None:
    denied("C1_INPUT_INVALID", canonical, {"x": "x" * 1025})
    denied("C1_INPUT_INVALID", canonical, {"x": float("nan")})
    denied("C1_INPUT_INVALID", canonical, {"x": "cafe\u0301"})
    assert canonical({"x": "café"}) == '{"x":"café"}'.encode()


SOURCE = ("skill", "demo", "helper", "1.0.0")
DECLARED = (("optional_tools", "tool", "tool-a", 0, False),)


def fixture() -> tuple[TestOnlyCatalog, Principal]:
    catalog = TestOnlyCatalog()
    principal = catalog.mint_principal("test-issuer", "lane-a")
    term, rev = catalog.take_writer_term(principal)
    candidate = catalog.admit_candidate(
        principal, policy="p1", package="pkg-a", image={"k": ["v"]}
    )
    assert catalog.publish(
        principal, candidate, term=term, expected_revision=rev, tx_id="tx-a"
    ) == (1, 1)
    return catalog, principal


def admit_absence(catalog: TestOnlyCatalog, principal: Principal) -> ApprovedAbsence:
    return catalog.approve_absence(
        principal,
        source_kind="skill",
        source_namespace="demo",
        source_id="helper",
        source_version="1.0.0",
        relation="optional_tools",
        target_kind="tool",
        target_id="tool-a",
        occurrence=0,
        policy="p1",
    )


def test_b01_forged_principal_denied_on_writer_and_issuance() -> None:
    catalog, principal = fixture()
    forged = Principal(principal.name, principal.lane)
    denied("C1_ISSUER_UNVERIFIED", catalog.take_writer_term, forged)
    denied("C1_ISSUER_UNVERIFIED", catalog.open_lease, forged)
    lease = catalog.open_lease(principal)
    denied(
        "C1_ISSUER_UNVERIFIED",
        catalog.issue,
        forged,
        lease_id=lease,
        request_id="r",
        request_payload={},
    )


def test_b02_forged_sealed_candidate_denied() -> None:
    catalog, principal = fixture()
    term, revision = catalog.take_writer_term(principal)
    candidate = catalog.admit_candidate(
        principal, policy="p1", package="pkg-a", image={"k": "v"}
    )
    forged = SealedCandidate(
        candidate.lane,
        candidate.policy,
        candidate.package,
        candidate.image,
        candidate.image_digest,
    )
    denied(
        "C1_ISSUER_UNVERIFIED",
        catalog.publish,
        principal,
        forged,
        term=term,
        expected_revision=revision,
        tx_id="forged",
    )
    assert catalog.counts() == (1, 0)


def test_b03_optional_absence_exact_origin_and_occurrence() -> None:
    catalog, principal = fixture()
    approved = admit_absence(catalog, principal)
    assert (
        catalog.check_absences(
            principal,
            source=SOURCE,
            declared=DECLARED,
            edges=(),
            absences=(approved,),
            policy="p1",
        )
        == ()
    )
    denied(
        "C1_DEPENDENCY_INVALID",
        catalog.check_absences,
        principal,
        source=SOURCE,
        declared=DECLARED,
        edges=(),
        absences=(),
        policy="p1",
    )
    fake = ApprovedAbsence(
        approved.source_kind,
        approved.source_namespace,
        approved.source_id,
        approved.source_version,
        approved.relation,
        approved.target_kind,
        approved.target_id,
        approved.occurrence,
        approved.policy,
        approved.digest,
    )
    denied(
        "C1_ISSUER_UNVERIFIED",
        catalog.check_absences,
        principal,
        source=SOURCE,
        declared=DECLARED,
        edges=(),
        absences=(fake,),
        policy="p1",
    )
    denied(
        "C1_DEPENDENCY_INVALID",
        catalog.check_absences,
        principal,
        source=SOURCE,
        declared=(("optional_tools", "tool", "tool-a", 1, False),),
        edges=(),
        absences=(approved,),
        policy="p1",
    )
    denied(
        "C1_DEPENDENCY_INVALID",
        catalog.check_absences,
        principal,
        source=SOURCE,
        declared=(("required_tools", "tool", "tool-a", 0, True),),
        edges=(),
        absences=(approved,),
        policy="p1",
    )
    denied(
        "C1_DEPENDENCY_INVALID",
        catalog.check_absences,
        principal,
        source=SOURCE,
        declared=DECLARED,
        edges=(("optional_tools", "tool", "tool-a", 0),),
        absences=(approved,),
        policy="p1",
    )


def test_b04_lease_issue_close_revoke_expire() -> None:
    catalog, principal = fixture()
    lease = catalog.open_lease(principal, ttl=3)
    catalog.advance_clock(3)
    denied(
        "C1_LEASE_INVALID",
        catalog.issue,
        principal,
        lease_id=lease,
        request_id="expired",
        request_payload={},
    )
    closed = catalog.open_lease(principal)
    catalog.close_lease(principal, closed)
    denied(
        "C1_LEASE_INVALID",
        catalog.issue,
        principal,
        lease_id=closed,
        request_id="closed",
        request_payload={},
    )
    revoked = catalog.open_lease(principal)
    catalog.revoke_lease(principal, revoked)
    denied(
        "C1_LEASE_INVALID",
        catalog.issue,
        principal,
        lease_id=revoked,
        request_id="revoked",
        request_payload={},
    )
    good = catalog.open_lease(principal)
    first = catalog.issue(principal, lease_id=good, request_id="ok", request_payload={})
    assert first.role == ROLE
    denied(
        "C1_LEASE_INVALID",
        catalog.issue,
        principal,
        lease_id=good,
        request_id="new",
        request_payload={},
    )


def test_b05_publication_exact_idempotent_result_after_revoke() -> None:
    catalog, principal = fixture()
    term, expected = 1, 0
    candidate = catalog.admit_candidate(
        principal, policy="p1", package="pkg-a", image={"k": ["v"]}
    )
    catalog.revoke(principal)
    assert catalog.publish(
        principal, candidate, term=term, expected_revision=expected, tx_id="tx-a"
    ) == (1, 1)
    assert catalog.counts() == (2, 0)
    denied(
        "C1_ISSUANCE_CONFLICT",
        catalog.publish,
        principal,
        catalog.admit_candidate(
            principal, policy="p1", package="pkg-a", image={"k": ["new"]}
        ),
        term=term,
        expected_revision=expected,
        tx_id="tx-a",
    )


def test_b06_historical_issuance_foreign_identity_and_corruption() -> None:
    catalog, principal = fixture()
    lease = catalog.open_lease(principal)
    first = catalog.issue(
        principal, lease_id=lease, request_id="req", request_payload={"a": 1}
    )
    catalog.revoke(principal)
    assert (
        catalog.issue(
            principal, lease_id=lease, request_id="req", request_payload={"a": 1}
        )
        is first
    )
    other = catalog.mint_principal("impostor", "lane-a")
    denied(
        "C1_ISSUER_UNVERIFIED",
        catalog.issue,
        other,
        lease_id=lease,
        request_id="req",
        request_payload={"a": 1},
    )
    denied(
        "C1_ISSUANCE_CONFLICT",
        catalog.issue,
        principal,
        lease_id=lease,
        request_id="req",
        request_payload={"a": 2},
    )
    assert catalog.counts() == (2, 1)


def test_b07_two_writer_same_revision_only_one_wins() -> None:
    catalog, principal = fixture()
    term, rev = catalog.take_writer_term(principal)
    candidate = catalog.admit_candidate(
        principal, policy="p1", package="pkg-a", image={"k": 2}
    )
    barrier = threading.Barrier(2)

    def attempt(tx: str) -> tuple[str, object]:
        barrier.wait()
        try:
            result = catalog.publish(
                principal,
                candidate,
                term=term,
                expected_revision=rev,
                tx_id=tx,
            )
            return ("success", result)
        except SimulatedDenial as exc:
            return ("denied", exc.code)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt, s) for s in ("a", "b")]
        outcomes = [x.result() for x in futures]
    assert [x[0] for x in outcomes].count("success") == 1
    assert ("denied", "C1_EPOCH_STALE") in outcomes
    assert catalog.counts() == (2, 0)


def test_b07_revoke_before_issue_versus_historical_replay() -> None:
    catalog, principal = fixture()
    lease = catalog.open_lease(principal)
    catalog.revoke(principal)
    denied(
        "C1_PUBLICATION_REVOKED",
        catalog.issue,
        principal,
        lease_id=lease,
        request_id="never",
        request_payload={},
    )
    assert catalog.counts() == (2, 0)

    catalog2, principal2 = fixture()
    lease2 = catalog2.open_lease(principal2)
    prior = catalog2.issue(
        principal2, lease_id=lease2, request_id="issued", request_payload={}
    )
    catalog2.revoke(principal2)
    assert (
        catalog2.issue(
            principal2, lease_id=lease2, request_id="issued", request_payload={}
        )
        is prior
    )


def test_b07_cross_tenant_and_stale_writer_term() -> None:
    catalog, principal = fixture()
    other = catalog.mint_principal("other", "lane-b")
    lease = catalog.open_lease(principal)
    denied(
        "C1_LEASE_INVALID",
        catalog.issue,
        other,
        lease_id=lease,
        request_id="x",
        request_payload={},
    )
    term, rev = catalog.take_writer_term(principal)
    candidate = catalog.admit_candidate(
        principal, policy="p1", package="pkg-a", image={"k": 2}
    )
    denied(
        "C1_WRITER_FENCE_INVALID",
        catalog.publish,
        principal,
        candidate,
        term=term - 1,
        expected_revision=rev,
        tx_id="old",
    )
    assert catalog.publish(
        principal, candidate, term=term, expected_revision=rev, tx_id="ok"
    ) == (2, 2)


def test_simulation_only_never_run_capability() -> None:
    catalog, principal = fixture()
    lease = catalog.open_lease(principal)
    evidence = catalog.issue(
        principal, lease_id=lease, request_id="r", request_payload={}
    )
    assert evidence.role == "NON_PRODUCTION_SIMULATION"
    assert "TRUSTED_PINNED_NON_RUNNABLE" not in repr(evidence)
