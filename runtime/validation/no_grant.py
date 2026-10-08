"""M6-IU1 Slice B0: non-affirmative, side-effect-free turn-local grant boundary.

B0 deliberately cannot issue, accept, or verify any positive Profile Grant.
It does not build a public ValidatedResult or invoke an Orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Self


class NoGrantReason(StrEnum):
    NO_AUTHORIZED_POLICY_EVIDENCE = "NO_AUTHORIZED_POLICY_EVIDENCE"
    UNTRUSTED_RECEIPT = "UNTRUSTED_RECEIPT"
    AUTHORITY_UNAVAILABLE = "AUTHORITY_UNAVAILABLE"
    RECEIPT_ALREADY_CONSUMED = "RECEIPT_ALREADY_CONSUMED"
    TURN_CLOSED = "TURN_CLOSED"


@dataclass(frozen=True, slots=True)
class NoGrant:
    """Terminal non-authority observation, never a profile authorization."""

    reason: NoGrantReason

    def __post_init__(self) -> None:
        if not isinstance(self.reason, NoGrantReason):
            raise ValueError("NoGrant requires a typed NoGrantReason")  # noqa: TRY004


class TurnClosedError(RuntimeError):
    """A turn-local container has been invalidated."""


class ReceiptAlreadyConsumedError(RuntimeError):
    """A once-only observation cannot be taken again."""


class NoGrantTurnSlot:
    """Local, once-only NoGrant observation; no positive receipt write surface.

    A slot must be allocated per turn and must never be shared as a singleton.
    Even a caller-supplied pseudo-receipt cannot become authorization here.
    """

    __slots__ = ("_closed", "_consumed", "_reason")

    def __init__(
        self,
        reason: NoGrantReason = NoGrantReason.NO_AUTHORIZED_POLICY_EVIDENCE,
    ) -> None:
        if not isinstance(reason, NoGrantReason):
            raise ValueError("slot requires a typed NoGrantReason")  # noqa: TRY004
        self._reason = reason
        self._consumed = False
        self._closed = False

    def take_once(self) -> NoGrant:
        if self._closed:
            raise TurnClosedError("grant slot is closed")
        if self._consumed:
            raise ReceiptAlreadyConsumedError("grant observation already consumed")
        self._consumed = True
        return NoGrant(self._reason)

    def close(self) -> None:
        """Invalidate the slot; closing twice is harmless."""
        self._closed = True

    def __enter__(self) -> Self:
        if self._closed:
            raise TurnClosedError("grant slot is closed")
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        self.close()
