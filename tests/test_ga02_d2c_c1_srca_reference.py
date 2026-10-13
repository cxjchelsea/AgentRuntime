"""C1-SRC-A S1/S2: isolation-only golden and publisher/issuer simulation tests."""

import concurrent.futures
import hashlib
import json
import threading
from dataclasses import replace

import pytest

from tests.reference_models.ga02_d2c_c1_srca_model import (
    ROLE,
    ApprovedAbsence,
    Principal,
    PublicationResult,
    SealedCandidate,
    SimulatedDenial,
    TestOnlyCatalog,
    canonical,
    canonical_wire,
    digest,
    validate_simulated_closure,
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
    ) == PublicationResult(1, 1, historical=False)
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
    ) == PublicationResult(1, 1, historical=True)
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
    ) == PublicationResult(2, 2, historical=False)


def test_simulation_only_never_run_capability() -> None:
    catalog, principal = fixture()
    lease = catalog.open_lease(principal)
    evidence = catalog.issue(
        principal, lease_id=lease, request_id="r", request_payload={}
    )
    assert evidence.role == "NON_PRODUCTION_SIMULATION"
    assert "TRUSTED_PINNED_NON_RUNNABLE" not in repr(evidence)


def test_g1_admitted_candidate_mutation_rejected_without_publication() -> None:
    catalog, principal = fixture()
    term, rev = catalog.take_writer_term(principal)
    admitted = catalog.admit_candidate(
        principal, policy="p1", package="pkg-a", image={"x": "owned"}
    )
    object.__setattr__(admitted, "policy", "evil")
    denied(
        "C1_PUBLICATION_DIGEST_MISMATCH",
        catalog.publish,
        principal,
        admitted,
        term=term,
        expected_revision=rev,
        tx_id="tamper",
    )
    assert catalog.counts() == (1, 0)


def test_g1_admitted_candidate_package_and_image_tampering_denied() -> None:
    for field, value in (("package", "evil"), ("image", b'{"x":"evil"}')):
        catalog, principal = fixture()
        term, rev = catalog.take_writer_term(principal)
        admitted = catalog.admit_candidate(
            principal, policy="p1", package="pkg-a", image={"x": "owned"}
        )
        object.__setattr__(admitted, field, value)
        denied(
            "C1_PUBLICATION_DIGEST_MISMATCH",
            catalog.publish,
            principal,
            admitted,
            term=term,
            expected_revision=rev,
            tx_id="tamper",
        )
        assert catalog.counts() == (1, 0)


def test_g2_approved_absence_digest_and_occurrence_tamper_denied() -> None:
    for field, value in (("digest", "0" * 64), ("occurrence", 8), ("target_id", "bad")):
        catalog, principal = fixture()
        approved = admit_absence(catalog, principal)
        object.__setattr__(approved, field, value)
        denied(
            "C1_PUBLICATION_DIGEST_MISMATCH",
            catalog.check_absences,
            principal,
            source=SOURCE,
            declared=DECLARED,
            edges=(),
            absences=(approved,),
            policy="p1",
        )


def test_g2_optional_approval_stale_after_generation_rotation() -> None:
    catalog, principal = fixture()
    approved = admit_absence(catalog, principal)
    term, rev = catalog.take_writer_term(principal)
    image = catalog.admit_candidate(
        principal, policy="p1", package="pkg-a", image={"v": 2}
    )
    assert catalog.publish(
        principal, image, term=term, expected_revision=rev, tx_id="new-generation"
    ) == PublicationResult(2, 2, historical=False)
    denied(
        "C1_EPOCH_STALE",
        catalog.check_absences,
        principal,
        source=SOURCE,
        declared=DECLARED,
        edges=(),
        absences=(approved,),
        policy="p1",
    )


def test_g3_lease_expiry_before_commit_versus_after_commit() -> None:
    catalog, principal = fixture()
    first_lease = catalog.open_lease(principal, ttl=1)
    catalog.advance_clock(1)
    denied(
        "C1_LEASE_INVALID",
        catalog.issue,
        principal,
        lease_id=first_lease,
        request_id="too-late",
        request_payload={},
    )
    assert catalog.counts() == (1, 0)
    later_lease = catalog.open_lease(principal, ttl=1)
    issued = catalog.issue(
        principal, lease_id=later_lease, request_id="issued", request_payload={}
    )
    catalog.advance_clock(1)
    assert (
        catalog.issue(
            principal, lease_id=later_lease, request_id="issued", request_payload={}
        )
        == issued
    )
    assert catalog.counts() == (1, 1)


def test_g3_lease_revocation_before_issue_and_after_issue() -> None:
    catalog, principal = fixture()
    lease = catalog.open_lease(principal)
    catalog.revoke_lease(principal, lease)
    denied(
        "C1_LEASE_INVALID",
        catalog.issue,
        principal,
        lease_id=lease,
        request_id="new",
        request_payload={},
    )
    fresh = catalog.open_lease(principal)
    issued = catalog.issue(
        principal, lease_id=fresh, request_id="existing", request_payload={}
    )
    denied("C1_LEASE_INVALID", catalog.revoke_lease, principal, fresh)
    assert (
        catalog.issue(
            principal, lease_id=fresh, request_id="existing", request_payload={}
        )
        == issued
    )


def test_g4_publication_tx_owner_and_term_bound() -> None:
    catalog, principal = fixture()
    other = catalog.mint_principal("other", "lane-a")
    same = catalog.admit_candidate(
        other, policy="p1", package="pkg-a", image={"k": ["v"]}
    )
    denied(
        "C1_ISSUER_UNVERIFIED",
        catalog.publish,
        other,
        same,
        term=1,
        expected_revision=0,
        tx_id="tx-a",
    )
    term, rev = catalog.take_writer_term(principal)
    own = catalog.admit_candidate(
        principal, policy="p1", package="pkg-a", image={"k": ["v"]}
    )
    denied(
        "C1_ISSUANCE_CONFLICT",
        catalog.publish,
        principal,
        own,
        term=term,
        expected_revision=0,
        tx_id="tx-a",
    )
    # The originally authorized publisher can retrieve its historical result.
    assert catalog.publish(
        principal, own, term=1, expected_revision=0, tx_id="tx-a"
    ) == PublicationResult(1, 1, historical=True)
    assert rev == 1


def test_g4_historical_pair_after_multiple_transitions() -> None:
    catalog, principal = fixture()
    catalog.revoke(principal)
    term, rev = catalog.take_writer_term(principal)
    admitted = catalog.admit_candidate(
        principal, policy="p1", package="pkg-a", image={"v": 2}
    )
    assert catalog.publish(
        principal, admitted, term=term, expected_revision=rev, tx_id="next"
    ) == PublicationResult(3, 2, historical=False)
    previous = catalog.admit_candidate(
        principal, policy="p1", package="pkg-a", image={"k": ["v"]}
    )
    assert catalog.publish(
        principal, previous, term=1, expected_revision=0, tx_id="tx-a"
    ) == PublicationResult(1, 1, historical=True)
    assert catalog.counts() == (3, 0)


def test_g5_issuance_ledger_policy_package_and_evidence_corruption_denied() -> None:
    for field, replacement in (("policy", "changed"), ("package", "changed")):
        catalog, principal = fixture()
        lease = catalog.open_lease(principal)
        catalog.issue(principal, lease_id=lease, request_id="id", request_payload={})
        row = catalog._issuance[("lane-a", "id")]  # test-owned fault injection
        catalog._issuance[("lane-a", "id")] = (
            replace(row, policy=replacement)
            if field == "policy"
            else replace(row, package=replacement)
        )
        denied(
            "C1_PUBLICATION_DIGEST_MISMATCH",
            catalog.issue,
            principal,
            lease_id=lease,
            request_id="id",
            request_payload={},
        )
        assert catalog.counts() == (1, 1)


def test_g5_issuance_evidence_digest_corruption_denied() -> None:
    catalog, principal = fixture()
    lease = catalog.open_lease(principal)
    catalog.issue(principal, lease_id=lease, request_id="id", request_payload={})
    row = catalog._issuance[("lane-a", "id")]  # test-owned fault injection
    catalog._issuance[("lane-a", "id")] = replace(row, evidence_digest="0" * 64)
    denied(
        "C1_PUBLICATION_DIGEST_MISMATCH",
        catalog.issue,
        principal,
        lease_id=lease,
        request_id="id",
        request_payload={},
    )


def test_g6_barrier_controlled_revoke_before_and_after_issue() -> None:
    # Events force commit order; ThreadPool alone does not establish it.
    catalog, principal = fixture()
    lease = catalog.open_lease(principal)
    import threading

    revoke_complete = threading.Event()

    def revoke_first() -> None:
        catalog.revoke(principal)
        revoke_complete.set()

    def issue_second() -> str:
        assert revoke_complete.wait(5)
        try:
            catalog.issue(
                principal, lease_id=lease, request_id="new", request_payload={}
            )
        except SimulatedDenial as exc:
            return exc.code
        return "UNEXPECTED_SUCCESS"

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        one = executor.submit(revoke_first)
        two = executor.submit(issue_second)
        one.result()
        assert two.result() == "C1_PUBLICATION_REVOKED"

    catalog2, principal2 = fixture()
    lease2 = catalog2.open_lease(principal2)
    issued_complete = threading.Event()

    def issue_first() -> object:
        item = catalog2.issue(
            principal2, lease_id=lease2, request_id="prior", request_payload={}
        )
        issued_complete.set()
        return item

    def revoke_second() -> None:
        assert issued_complete.wait(5)
        catalog2.revoke(principal2)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(issue_first)
        second = executor.submit(revoke_second)
        original = first.result()
        second.result()
    assert (
        catalog2.issue(
            principal2, lease_id=lease2, request_id="prior", request_payload={}
        )
        is original
    )


def test_g7_two_fault_precedence_and_upper_bounds() -> None:
    catalog, principal = fixture()
    forged = Principal(principal.name, principal.lane)
    denied(
        "C1_ISSUER_UNVERIFIED",
        catalog.admit_candidate,
        forged,
        policy="p1",
        package="pkg-a",
        image={"x": "z" * 1025},
    )
    denied("C1_INPUT_INVALID", canonical, {"x": "x" * 1025})
    denied("C1_INPUT_INVALID", canonical_wire, b'{"a":1,"a":2}')
    assert len(canonical({"x": "x" * 1024})) > 1024
    denied("C1_RESOURCE_LIMIT", canonical, {"x": "x" * 1024, "y": ["a" * 1024] * 2100})


def test_g7_simulated_role_and_exact_scope_not_executable() -> None:
    catalog, principal = fixture()
    lease = catalog.open_lease(principal)
    evidence = catalog.issue(
        principal, lease_id=lease, request_id="nonrun", request_payload={}
    )
    assert evidence.role == ROLE
    assert not hasattr(evidence, "implementation_ref")
    assert not hasattr(evidence, "run")


def test_r3_01_enrolled_principal_mutation_denied() -> None:
    for field, replacement in (
        ("name", "foreign"),
        ("lane", "lane-b"),
        ("role", "TRUSTED"),
    ):
        catalog, principal = fixture()
        object.__setattr__(principal, field, replacement)
        denied("C1_ISSUER_UNVERIFIED", catalog.take_writer_term, principal)
        denied("C1_ISSUER_UNVERIFIED", catalog.open_lease, principal)
        assert catalog.counts() == (1, 0)


def test_r3_03_absence_does_not_survive_revoke() -> None:
    catalog, principal = fixture()
    approved = admit_absence(catalog, principal)
    catalog.revoke(principal)
    denied(
        "C1_PUBLICATION_REVOKED",
        catalog.check_absences,
        principal,
        source=SOURCE,
        declared=DECLARED,
        edges=(),
        absences=(approved,),
        policy="p1",
    )


def test_r3_04_publication_receipt_is_historical_on_replay() -> None:
    catalog, principal = fixture()
    original = catalog._transactions[("lane-a", "tx-a")]
    candidate = catalog.admit_candidate(
        principal, policy="p1", package="pkg-a", image={"k": ["v"]}
    )
    term, revision = catalog.take_writer_term(principal)
    current = catalog.publish(
        principal,
        catalog.admit_candidate(
            principal, policy="p1", package="pkg-a", image={"later": True}
        ),
        term=term,
        expected_revision=revision,
        tx_id="next",
    )
    assert current == PublicationResult(2, 2, historical=False)
    assert current.historical is False
    old = catalog.publish(
        principal,
        candidate,
        term=original[4],
        expected_revision=original[5],
        tx_id="tx-a",
    )
    assert old == PublicationResult(1, 1, historical=True)
    assert old.historical is True
    assert catalog.counts() == (2, 0)


def test_r3_05_lease_terminal_transitions_are_monotonic() -> None:
    catalog, principal = fixture()
    for method in ("close_lease", "revoke_lease"):
        lease = catalog.open_lease(principal)
        getattr(catalog, method)(principal, lease)
        denied("C1_LEASE_INVALID", catalog.close_lease, principal, lease)
        denied("C1_LEASE_INVALID", catalog.revoke_lease, principal, lease)
    consumed = catalog.open_lease(principal)
    catalog.issue(principal, lease_id=consumed, request_id="spent", request_payload={})
    denied("C1_LEASE_INVALID", catalog.close_lease, principal, consumed)
    denied("C1_LEASE_INVALID", catalog.revoke_lease, principal, consumed)


def test_t12_t13_simulated_crash_before_and_after_publish_cas() -> None:
    catalog, principal = fixture()
    term, revision = catalog.take_writer_term(principal)
    candidate = catalog.admit_candidate(
        principal, policy="p1", package="pkg-a", image={"version": 2}
    )
    catalog.simulate_crash_at("BEFORE_PUBLISH_CAS")
    denied(
        "C1_SIMULATED_CRASH",
        catalog.publish,
        principal,
        candidate,
        term=term,
        expected_revision=revision,
        tx_id="replay",
    )
    assert catalog.counts() == (1, 0)
    catalog.simulate_crash_at("AFTER_PUBLISH_CAS")
    denied(
        "C1_SIMULATED_CRASH",
        catalog.publish,
        principal,
        candidate,
        term=term,
        expected_revision=revision,
        tx_id="replay",
    )
    assert catalog.counts() == (2, 0)
    replay = catalog.publish(
        principal,
        candidate,
        term=term,
        expected_revision=revision,
        tx_id="replay",
    )
    assert replay == PublicationResult(2, 2, historical=True) and replay.historical is True
    assert catalog.counts() == (2, 0)


def test_f2_a_simulated_crash_before_and_after_issue_commit() -> None:
    catalog, principal = fixture()
    lease = catalog.open_lease(principal)
    catalog.simulate_crash_at("BEFORE_ISSUE_CAS")
    denied(
        "C1_SIMULATED_CRASH",
        catalog.issue,
        principal,
        lease_id=lease,
        request_id="request",
        request_payload={},
    )
    assert catalog.counts() == (1, 0)
    catalog.simulate_crash_at("AFTER_ISSUE_CAS")
    denied(
        "C1_SIMULATED_CRASH",
        catalog.issue,
        principal,
        lease_id=lease,
        request_id="request",
        request_payload={},
    )
    assert catalog.counts() == (1, 1)
    historical = catalog.issue(
        principal,
        lease_id=lease,
        request_id="request",
        request_payload={},
    )
    assert historical.role == ROLE
    assert catalog.counts() == (1, 1)


def test_f2_g_racing_same_request_commits_once() -> None:
    catalog, principal = fixture()
    lease = catalog.open_lease(principal)
    barrier = threading.Barrier(2)

    def send() -> object:
        barrier.wait()
        return catalog.issue(
            principal,
            lease_id=lease,
            request_id="same",
            request_payload={"value": 1},
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(send) for _ in range(2)]
        assert futures[0].result() is futures[1].result()
    assert catalog.counts() == (1, 1)


def test_f1_g_mismatched_optional_target_not_accepted() -> None:
    catalog, principal = fixture()
    approved = admit_absence(catalog, principal)
    denied(
        "C1_DEPENDENCY_INVALID",
        catalog.check_absences,
        principal,
        source=SOURCE,
        declared=(("optional_tools", "tool", "foreign-tool", 0, False),),
        edges=(),
        absences=(approved,),
        policy="p1",
    )


def test_t14_committed_image_corruption_denied() -> None:
    catalog, principal = fixture()
    lease = catalog.open_lease(principal)
    lane = catalog._lanes["lane-a"]
    catalog._images[lane.image_digest] = b'{"tampered":true}'
    denied(
        "C1_PUBLICATION_DIGEST_MISMATCH",
        catalog.issue,
        principal,
        lease_id=lease,
        request_id="corrupt",
        request_payload={},
    )
    assert catalog.counts() == (1, 0)


def test_t19_semantic_json_order_same_digest_wire_canonical() -> None:
    left = {"z": 2, "a": {"second": 2, "first": 1}}
    right = {"a": {"first": 1, "second": 2}, "z": 2}
    assert canonical(left) == canonical(right)
    assert digest("GA02-D2C-C1-SIM-IMAGE-1", left) == digest(
        "GA02-D2C-C1-SIM-IMAGE-1", right
    )
    denied("C1_INPUT_INVALID", canonical_wire, b'{"z":2,"a":1}')


def test_t17_string_limit_shape_before_total_budget() -> None:
    assert canonical({"x": "a" * 1024}).startswith(b'{"x":')
    denied("C1_INPUT_INVALID", canonical, {"x": "a" * 1025})
    denied("C1_INPUT_INVALID", canonical_wire, b'{"a":1,"a":2}')

def test_rr01_identity_revalidated_inside_publish_lock() -> None:
    catalog, principal = fixture()
    term, rev = catalog.take_writer_term(principal)
    candidate = catalog.admit_candidate(
        principal, policy="p1", package="pkg-a", image={"counter": 2}
    )
    original_auth = catalog._auth
    fired = False

    def adversarial_auth(value: Principal, lane: str) -> None:
        nonlocal fired
        original_auth(value, lane)
        if not fired:
            fired = True
            object.__setattr__(value, "lane", "foreign-lane")

    catalog._auth = adversarial_auth  # isolated test-only after-auth injection
    denied(
        "C1_ISSUER_UNVERIFIED", catalog.publish, principal, candidate,
        term=term, expected_revision=rev, tx_id="auth-race",
    )
    assert catalog.counts() == (1, 0)


def test_rr02_historical_receipt_is_immutable_and_distinct() -> None:
    catalog, principal = fixture()
    record = catalog._transactions[("lane-a", "tx-a")]
    original = catalog.admit_candidate(
        principal, policy="p1", package="pkg-a", image={"k": ["v"]}
    )
    historical = catalog.publish(
        principal, original, term=record[4],
        expected_revision=record[5], tx_id="tx-a",
    )
    assert historical == PublicationResult(1, 1, historical=True)
    assert historical != PublicationResult(1, 1, historical=False)
    assert historical != (1, 1)
    with pytest.raises((AttributeError, TypeError)):
        historical.historical = False


def test_t02_self_consistent_digest_does_not_mint_issuer() -> None:
    catalog, principal = fixture()
    term, rev = catalog.take_writer_term(principal)
    raw = canonical({"forged_c0_digest": "d" * 64})
    claimed = SealedCandidate(
        lane=principal.lane, policy="p1", package="pkg-a",
        image=raw, image_digest=hashlib.sha256(raw).hexdigest(),
    )
    denied(
        "C1_ISSUER_UNVERIFIED", catalog.publish,
        principal, claimed, term=term, expected_revision=rev, tx_id="forged-c0",
    )
    assert catalog.counts() == (1, 0)


def test_t15_adapter_generation_rotation_invalidates_old_lease() -> None:
    catalog, principal = fixture()
    lease = catalog.open_lease(principal)
    term, rev = catalog.take_writer_term(principal)
    fresh_image = catalog.admit_candidate(
        principal, policy="p1", package="pkg-a",
        image={"adapter_generation": "adapter-v2", "tenant": "lane-a"},
    )
    new = catalog.publish(
        principal, fresh_image, term=term, expected_revision=rev, tx_id="adapter-v2",
    )
    assert new == PublicationResult(2, 2, historical=False)
    denied(
        "C1_EPOCH_STALE", catalog.issue, principal,
        lease_id=lease, request_id="stale-adapter", request_payload={},
    )


def test_t16_synthetic_core_cross_namespace_and_graph_cycles() -> None:
    assert validate_simulated_closure(
        [{"id": "skill-a"}, {"id": "tool-a"}],
        [("skill-a", "tool-a")],
    ) == ROLE
    denied(
        "C1_DEPENDENCY_INVALID", validate_simulated_closure,
        [{"id": "tenant:skill"}, {"id": "CORE:tool"}],
        [("tenant:skill", "CORE:tool")],
    )
    denied(
        "C1_DEPENDENCY_INVALID", validate_simulated_closure,
        [{"id": "a"}, {"id": "b"}], [("a", "b"), ("b", "a")],
    )
    denied(
        "C1_DEPENDENCY_INVALID", validate_simulated_closure,
        [{"id": "a"}], [("a", "missing")],
    )


def test_t17_synthetic_definition_node_edge_byte_limits() -> None:
    denied(
        "C1_RESOURCE_LIMIT", validate_simulated_closure,
        [{"id": "n", "payload": "x" * 1024, "items": ["a" * 1024] * 11}], [],
    )
    denied(
        "C1_RESOURCE_LIMIT", validate_simulated_closure,
        [{"id": f"node-{n}"} for n in range(257)], [],
    )
    denied(
        "C1_RESOURCE_LIMIT", validate_simulated_closure,
        [{"id": "n"}], [("n", "n")] * 1025,
    )
    assert validate_simulated_closure(
        [{"id": f"node-{n}"} for n in range(256)], []
    ) == ROLE


def test_t18_injected_verifier_and_finalization_fail_closed() -> None:
    catalog, principal = fixture()
    catalog.simulate_crash_at("BEFORE_ISSUER_ADMISSION")
    denied(
        "C1_SIMULATED_CRASH", catalog.admit_candidate,
        principal, policy="p1", package="pkg-a", image={"v": "valid"},
    )
    term, rev = catalog.take_writer_term(principal)
    candidate = catalog.admit_candidate(
        principal, policy="p1", package="pkg-a", image={"v": "valid"}
    )
    catalog.simulate_crash_at("BEFORE_DIGEST_VALIDATION")
    denied(
        "C1_SIMULATED_CRASH", catalog.publish,
        principal, candidate, term=term, expected_revision=rev,
        tx_id="digest-fault",
    )
    assert catalog.counts() == (1, 0)
    lease = catalog.open_lease(principal)
    catalog.simulate_crash_at("BEFORE_FINAL_ISSUE")
    denied(
        "C1_SIMULATED_CRASH", catalog.issue,
        principal, lease_id=lease, request_id="final-fault", request_payload={},
    )
    assert catalog.counts() == (1, 0)


def test_t21_two_readers_one_writer_generation_turnover() -> None:
    catalog, principal = fixture()
    leases = [catalog.open_lease(principal) for _ in range(2)]
    term, rev = catalog.take_writer_term(principal)
    barrier = threading.Barrier(3)
    published = threading.Event()

    def reader(lease: str) -> str:
        barrier.wait()
        assert published.wait(5)
        try:
            catalog.issue(
                principal, lease_id=lease, request_id=f"stale-{lease}",
                request_payload={},
            )
        except SimulatedDenial as exc:
            return exc.code
        return "UNEXPECTED_SUCCESS"

    def writer() -> None:
        barrier.wait()
        changed = catalog.admit_candidate(
            principal, policy="p1", package="pkg-a", image={"generation": 2},
        )
        catalog.publish(
            principal, changed, term=term, expected_revision=rev,
            tx_id="reader-turnover",
        )
        published.set()

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        a = executor.submit(reader, leases[0])
        b = executor.submit(reader, leases[1])
        w = executor.submit(writer)
        w.result()
        assert a.result() == "C1_EPOCH_STALE"
        assert b.result() == "C1_EPOCH_STALE"
    assert catalog.counts() == (2, 0)
