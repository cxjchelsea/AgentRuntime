"""B0 negative authority boundary; tests exercise no positive grant producer."""

import asyncio
from dataclasses import FrozenInstanceError

import pytest

from runtime.validation.no_grant import (
    NoGrant,
    NoGrantReason,
    NoGrantTurnSlot,
    ReceiptAlreadyConsumedError,
    TurnClosedError,
)


def test_default_is_no_grant_and_not_positive_authority() -> None:
    slot = NoGrantTurnSlot()
    observed = slot.take_once()
    assert observed == NoGrant(NoGrantReason.NO_AUTHORIZED_POLICY_EVIDENCE)
    assert not hasattr(observed, "profile_id")
    assert not hasattr(observed, "authorized")
    assert not hasattr(slot, "issue_grant")
    assert not hasattr(slot, "install_receipt")
    assert not hasattr(slot, "set_authority")


def test_explicit_untrusted_evidence_stays_no_grant() -> None:
    slot = NoGrantTurnSlot(NoGrantReason.UNTRUSTED_RECEIPT)
    assert slot.take_once().reason is NoGrantReason.UNTRUSTED_RECEIPT


def test_type_rejection_prevents_freeform_grant() -> None:
    with pytest.raises(ValueError, match="typed NoGrantReason"):
        NoGrant("AUTHORIZED")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="typed NoGrantReason"):
        NoGrantTurnSlot("AUTHORIZED")  # type: ignore[arg-type]


def test_no_grant_value_is_immutable() -> None:
    result = NoGrant(NoGrantReason.AUTHORITY_UNAVAILABLE)
    with pytest.raises(FrozenInstanceError):
        result.reason = NoGrantReason.UNTRUSTED_RECEIPT  # type: ignore[misc]


def test_single_consumption_is_fail_closed() -> None:
    slot = NoGrantTurnSlot()
    assert isinstance(slot.take_once(), NoGrant)
    with pytest.raises(ReceiptAlreadyConsumedError):
        slot.take_once()


def test_close_blocks_first_take_and_close_is_idempotent() -> None:
    slot = NoGrantTurnSlot()
    slot.close()
    slot.close()
    with pytest.raises(TurnClosedError):
        slot.take_once()


def test_close_blocks_reuse_after_take() -> None:
    slot = NoGrantTurnSlot()
    slot.take_once()
    slot.close()
    with pytest.raises(TurnClosedError):
        slot.take_once()


def test_context_manager_closes_on_success_and_error() -> None:
    slot = NoGrantTurnSlot()
    with slot as active:
        assert isinstance(active.take_once(), NoGrant)
    with pytest.raises(TurnClosedError):
        slot.take_once()

    failure_slot = NoGrantTurnSlot()
    with pytest.raises(RuntimeError, match="stop"):
        with failure_slot:
            raise RuntimeError("stop")
    with pytest.raises(TurnClosedError):
        failure_slot.take_once()


def test_closed_context_manager_reentry_rejected() -> None:
    slot = NoGrantTurnSlot()
    with slot:
        pass
    with pytest.raises(TurnClosedError):
        with slot:
            pass


def test_separate_concurrent_turns_are_isolated() -> None:
    async def run_turn(reason: NoGrantReason) -> NoGrant:
        with NoGrantTurnSlot(reason) as slot:
            await asyncio.sleep(0)
            return slot.take_once()

    async def run_both() -> tuple[NoGrant, NoGrant]:
        first, second = await asyncio.gather(
            run_turn(NoGrantReason.UNTRUSTED_RECEIPT),
            run_turn(NoGrantReason.AUTHORITY_UNAVAILABLE),
        )
        return first, second

    a, b = asyncio.run(run_both())
    assert a.reason is NoGrantReason.UNTRUSTED_RECEIPT
    assert b.reason is NoGrantReason.AUTHORITY_UNAVAILABLE


def test_no_public_result_or_side_effect_methods() -> None:
    slot = NoGrantTurnSlot()
    for name in ("validate", "execute", "commit", "persist", "resolve_profile"):
        assert not hasattr(slot, name)
