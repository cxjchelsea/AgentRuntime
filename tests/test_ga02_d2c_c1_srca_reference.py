"""C1-SRC-A S1/S2: isolation-only golden and publisher/issuer simulation tests."""

import concurrent.futures
import hashlib
import json

import pytest

from tests.reference_models.ga02_d2c_c1_srca_model import (
    ROLE,
    Principal,
    SimulatedDenial,
    TestOnlyCatalog,
    canonical,
    canonical_wire,
    check_optional_absences,
    digest,
    synthetic_candidate,
)

LANE = Principal("test-issuer", "lane-a")
FOREIGN = Principal("other", "lane-b")


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


def test_f1_explicit_absence_not_silent() -> None:
    declared = (("optional_tools", "tool-a", False),)
    assert (
        check_optional_absences(
            declared,
            (),
            (("optional_tools", "tool-a", "p1"),),
            policy="p1",
        )
        == ()
    )
    denied(
        "C1_DEPENDENCY_INVALID", check_optional_absences, declared, (), (), policy="p1"
    )
    denied(
        "C1_LANE_SCOPE_MISMATCH",
        check_optional_absences,
        declared,
        (),
        (("optional_tools", "tool-a", "old"),),
        policy="p1",
    )
    denied(
        "C1_DEPENDENCY_INVALID",
        check_optional_absences,
        declared,
        (("optional_tools", "tool-a"),),
        (("optional_tools", "tool-a", "p1"),),
        policy="p1",
    )
    denied(
        "C1_DEPENDENCY_INVALID",
        check_optional_absences,
        (("required_tools", "tool-a", True),),
        (),
        (("required_tools", "tool-a", "p1"),),
        policy="p1",
    )


def published() -> TestOnlyCatalog:
    catalog = TestOnlyCatalog()
    term, rev = catalog.take_writer_term(LANE)
    assert catalog.publish(
        LANE,
        synthetic_candidate(
            lane="lane-a", policy="p1", package="pkg-a", image={"k": ["v"]}
        ),
        term=term,
        expected_revision=rev,
        tx_id="tx-a",
    ) == (1, 1)
    return catalog


def test_f2_single_use_historical_replay_and_revoke() -> None:
    catalog = published()
    catalog.open_lease(LANE, "lease-a")
    first = catalog.issue(
        LANE, lease_id="lease-a", request_id="req", request_payload={"x": 1}
    )
    assert first.role == ROLE
    assert first.evidence_id == "sim-evidence-1"
    catalog.revoke(LANE)
    second = catalog.issue(
        LANE, lease_id="lease-a", request_id="req", request_payload={"x": 1}
    )
    assert first == second
    assert catalog.counts() == (2, 1)
    denied(
        "C1_ISSUANCE_CONFLICT",
        catalog.issue,
        LANE,
        lease_id="lease-a",
        request_id="req",
        request_payload={"x": 2},
    )
    denied(
        "C1_PUBLICATION_REVOKED",
        catalog.issue,
        LANE,
        lease_id="lease-a",
        request_id="fresh",
        request_payload={"x": 1},
    )


def test_f2_cross_lane_does_not_disclose_evidence() -> None:
    catalog = published()
    catalog.open_lease(LANE, "lease")
    catalog.issue(LANE, lease_id="lease", request_id="r", request_payload={"k": True})
    denied(
        "C1_LEASE_INVALID",
        catalog.issue,
        FOREIGN,
        lease_id="lease",
        request_id="r",
        request_payload={"k": True},
    )
    impostor = Principal("foreign", "lane-a")
    denied(
        "C1_ISSUER_UNVERIFIED",
        catalog.issue,
        impostor,
        lease_id="lease",
        request_id="r",
        request_payload={"k": True},
    )


def test_cas_stale_revision_and_writer_term() -> None:
    catalog = published()
    image = synthetic_candidate(
        lane="lane-a", policy="p1", package="pkg-a", image={"n": 2}
    )
    denied(
        "C1_EPOCH_STALE",
        catalog.publish,
        LANE,
        image,
        term=1,
        expected_revision=0,
        tx_id="stale",
    )
    term, _ = catalog.take_writer_term(LANE)
    denied(
        "C1_WRITER_FENCE_INVALID",
        catalog.publish,
        LANE,
        image,
        term=1,
        expected_revision=1,
        tx_id="old",
    )
    assert catalog.publish(
        LANE, image, term=term, expected_revision=1, tx_id="new"
    ) == (2, 2)


def test_f2_two_thread_duplicate_issue() -> None:
    catalog = published()
    catalog.open_lease(LANE, "lease")

    def call() -> object:
        return catalog.issue(
            LANE, lease_id="lease", request_id="request", request_payload={"a": 1}
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(call) for _ in range(2)]
    assert futures[0].result() == futures[1].result()
    assert catalog.counts() == (1, 1)


def test_no_trusted_role_or_production_import() -> None:
    catalog = published()
    catalog.open_lease(LANE, "lease")
    result = catalog.issue(LANE, lease_id="lease", request_id="r", request_payload={})
    assert result.role == "NON_PRODUCTION_SIMULATION"
    assert "TRUSTED_PINNED_NON_RUNNABLE" not in repr(result)
