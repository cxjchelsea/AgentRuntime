"""Deferred cross-stage replan entry contract for M4 Gate M4-39.

M4 does not own Retrieval or Result Validation. This contract only defines the
information boundary that a future M5/M6 -> M4 Runtime loop must satisfy.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReplanEntryRequest:
    """Cross-stage request to start a new planning cycle after validation."""

    request_id: str
    prior_plan_id: str
    trigger_stage: str
    reason_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...] = ()
    preserve_goal: bool = True

    def __post_init__(self) -> None:
        if not self.request_id.strip() or not self.prior_plan_id.strip():
            raise ValueError("request_id and prior_plan_id must not be blank")
        if self.trigger_stage != "RESULT_VALIDATE":
            raise ValueError(
                "M4 cross-stage replan entry currently accepts RESULT_VALIDATE only"
            )
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        if any(not ref.strip() for ref in self.evidence_refs):
            raise ValueError("evidence_refs must not contain blank values")
