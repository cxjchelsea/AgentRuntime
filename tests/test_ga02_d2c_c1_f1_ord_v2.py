"""F1/ORD isolated V2 contract fixtures, no production publisher or DB."""

from dataclasses import replace
from typing import cast

import pytest

from tests.reference_models.ga02_d2c_c1_f1_ord_v2_fixture import (
    PROFILE,
    Approval,
    FixtureDenial,
    FixturePrincipal,
    V2Fixture,
    canonical_bytes,
    hash_bytes,
)

GOLDENS = (
    "349e20e0dcf7af2d68c1a6dd5173188ba583346df92c9d37d2ad72094cf5000c",
    "ff2cf9ef7cea434720bf614d6d201d2be93d3b3d4eaefd343ad25b7a1cb2bf7b",
)


def denied(code: str, callback: object, **kwargs: object) -> None:
    assert callable(callback)
    with pytest.raises(FixtureDenial) as failure:
        callback(**kwargs)
    assert failure.value.code == code


def setup() -> tuple[V2Fixture, FixturePrincipal]:
    fixture = V2Fixture()
    return fixture, fixture.principal()


def assert_no_effects(fixture: V2Fixture) -> None:
    assert (
        fixture.publication_count,
        fixture.issuance_count,
        fixture.external_side_effect_count,
    ) == (0, 0, 0)


@pytest.mark.parametrize("ordinal", [0, 1])
def test_v2_golden_byte_and_profile(ordinal: int) -> None:
    raw = canonical_bytes(ordinal)
    assert len(raw) == 234
    assert hash_bytes(raw) == GOLDENS[ordinal]
    assert b'"relation":"skill.optional_tools"' in raw
    assert PROFILE != "GA02-D2C-C1-OPTIONAL-ABSENCE-1"


def test_f1_a_approved_metadata_only() -> None:
    fixture, principal = setup()
    approved = fixture.approve(principal, ordinal=0)
    assert fixture.check(principal, approvals=(approved,)) == ((0, "tool-a"),)
    assert_no_effects(fixture)


def test_f1_b_missing_both() -> None:
    fixture, principal = setup()
    denied("C1_DEPENDENCY_INVALID", fixture.check, principal=principal)
    assert_no_effects(fixture)


def test_f1_c_forged_principal_precedes_missing_edge() -> None:
    fixture, principal = setup()
    forged = FixturePrincipal(principal.name, principal.lane)
    denied("C1_ISSUER_UNVERIFIED", fixture.check, principal=forged)
    assert_no_effects(fixture)


def test_f1_d_stale_policy_and_foreign_lane() -> None:
    fixture, principal = setup()
    approved = fixture.approve(principal, ordinal=0)
    denied(
        "C1_LANE_SCOPE_MISMATCH",
        fixture.check,
        principal=principal,
        approvals=(approved,),
        policy="p0",
    )
    denied(
        "C1_LANE_SCOPE_MISMATCH",
        fixture.check,
        principal=principal,
        approvals=(approved,),
        lane="foreign",
    )
    assert_no_effects(fixture)


def test_f1_e_edge_and_approval_or_duplicate_approval() -> None:
    fixture, principal = setup()
    approved = fixture.approve(principal, ordinal=0)
    denied(
        "C1_DEPENDENCY_INVALID",
        fixture.check,
        principal=principal,
        approvals=(approved,),
        edges=(0,),
    )
    denied(
        "C1_DEPENDENCY_INVALID",
        fixture.check,
        principal=principal,
        approvals=(approved, approved),
    )
    assert_no_effects(fixture)


def test_f1_f_required_cannot_be_absent() -> None:
    fixture, principal = setup()
    approved = fixture.approve(principal, ordinal=0)
    denied(
        "C1_DEPENDENCY_INVALID",
        fixture.check,
        principal=principal,
        approvals=(approved,),
        required=(0,),
    )
    assert_no_effects(fixture)


def test_f1_g_invalid_edge_target_with_unrelated_absence() -> None:
    fixture, principal = setup()
    approved = fixture.approve(principal, ordinal=1)
    denied(
        "C1_DEPENDENCY_INVALID",
        fixture.check,
        principal=principal,
        targets=("tool-a", "tool-a"),
        approvals=(approved,),
        edges=(0,),
        edge_targets_valid=False,
    )
    assert_no_effects(fixture)


def test_ord_01_missing_second_occurrence() -> None:
    fixture, principal = setup()
    approved = fixture.approve(principal, ordinal=0)
    denied(
        "C1_DEPENDENCY_INVALID",
        fixture.check,
        principal=principal,
        targets=("tool-a", "tool-a"),
        approvals=(approved,),
    )
    assert_no_effects(fixture)


def test_ord_02_two_approvals_are_distinct_and_ordered() -> None:
    fixture, principal = setup()
    a0 = fixture.approve(principal, ordinal=0)
    a1 = fixture.approve(principal, ordinal=1)
    assert a0 is not a1
    assert a0.digest != a1.digest
    result = fixture.check(principal, targets=("tool-a", "tool-a"), approvals=(a1, a0))
    assert result == ((0, "tool-a"), (1, "tool-a"))
    assert_no_effects(fixture)


def test_ord_03_digest_or_approval_transfer_rejected() -> None:
    fixture, principal = setup()
    approved = fixture.approve(principal, ordinal=0)
    forged = replace(approved, ordinal=1)
    denied(
        "C1_ISSUER_UNVERIFIED",
        fixture.check,
        principal=principal,
        targets=("tool-a", "tool-a"),
        approvals=(forged,),
    )
    assert_no_effects(fixture)


@pytest.mark.parametrize("ordinal", [2, -1, True, 1.0])
def test_ord_04_invalid_ordinal(ordinal: object) -> None:
    fixture, principal = setup()
    if type(ordinal) is int and ordinal >= 0:
        approval = fixture.approve(principal, ordinal=cast(int, ordinal))
        denied(
            "C1_DEPENDENCY_INVALID",
            fixture.check,
            principal=principal,
            targets=("tool-a", "tool-a"),
            approvals=(approval,),
        )
    else:
        denied(
            "C1_DEPENDENCY_INVALID",
            fixture.approve,
            principal=principal,
            ordinal=cast(int, ordinal),
        )
    assert_no_effects(fixture)


def test_ord_04_duplicate_edge_ordinal() -> None:
    fixture, principal = setup()
    denied("C1_DEPENDENCY_INVALID", fixture.check, principal=principal, edges=(0, 0))
    assert_no_effects(fixture)


def test_ord_05_legacy_v1_handle_cannot_promote() -> None:
    fixture, principal = setup()
    legacy = Approval(
        b"legacy",
        "44d1052aafdb430e715230e5eb6cc8ea626253b2a10a13d9625d573138ab5c6a",
        0,
    )
    denied(
        "C1_ISSUER_UNVERIFIED",
        fixture.check,
        principal=principal,
        approvals=(legacy,),
    )
    assert_no_effects(fixture)


def test_ir_03_forged_handle_distinct_from_valid_but_wrong_content() -> None:
    fixture, principal = setup()
    approved = fixture.approve(principal, ordinal=0)
    denied(
        "C1_ISSUER_UNVERIFIED",
        fixture.check,
        principal=principal,
        approvals=(replace(approved),),
    )
    assert fixture.check(principal, approvals=(approved,)) == ((0, "tool-a"),)
    assert_no_effects(fixture)


def test_neg_pair_foreign_scope_precedes_missing_dependency() -> None:
    fixture, principal = setup()
    denied("C1_LANE_SCOPE_MISMATCH", fixture.check, principal=principal, lane="other")
    assert_no_effects(fixture)


def test_neg_pair_valid_scope_conflict_is_dependency_denial() -> None:
    fixture, principal = setup()
    approved = fixture.approve(principal, ordinal=0)
    denied(
        "C1_DEPENDENCY_INVALID",
        fixture.check,
        principal=principal,
        approvals=(approved,),
        edges=(0,),
    )
    assert_no_effects(fixture)


def test_no_cross_fixture_handle_reuse() -> None:
    a, owner = setup()
    b, other = setup()
    approved = a.approve(owner, ordinal=0)
    denied("C1_ISSUER_UNVERIFIED", b.check, principal=other, approvals=(approved,))
    assert_no_effects(a)
    assert_no_effects(b)
