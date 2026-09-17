"""M2-IU3 internal priority / preemption types.

These are Runtime implementation types, not new Canonical Contracts.
Domain-specific priority names are injected values and must not be added here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from runtime.priority_management.errors import InvalidPrioritySubjectError


class PriorityRelation(str, Enum):
    """Incoming priority relative to the current activity."""

    HIGHER = "HIGHER"
    EQUAL = "EQUAL"
    LOWER = "LOWER"
    ANY = "ANY"


class IncomingDisposition(str, Enum):
    """What should happen to the incoming event after evaluation."""

    PROCESS_NOW = "PROCESS_NOW"
    DEFER = "DEFER"
    QUEUE = "QUEUE"
    DROP = "DROP"


class CleanupPolicy(str, Enum):
    """Cleanup behavior for the interrupted activity."""

    NONE = "NONE"
    PRESERVE = "PRESERVE"
    CANCEL = "CANCEL"
    CHECKPOINT = "CHECKPOINT"


class ResumePolicy(str, Enum):
    """What happens to the interrupted activity after incoming work completes."""

    NO_RESUME = "NO_RESUME"
    OPTIONAL_RESUME = "OPTIONAL_RESUME"
    AUTO_RESUME = "AUTO_RESUME"
    REPLAN = "REPLAN"


@dataclass(frozen=True, slots=True)
class PrioritySubject:
    """A current activity or incoming event after external priority resolution."""

    subject_id: str
    kind: str
    priority: int
    source: str | None = None

    def __post_init__(self) -> None:
        if not self.subject_id.strip():
            raise InvalidPrioritySubjectError("subject_id must not be blank")
        if not self.kind.strip():
            raise InvalidPrioritySubjectError("kind must not be blank")


@dataclass(frozen=True, slots=True)
class PriorityDecision:
    """Deterministic comparison only; it does not itself perform preemption."""

    current_priority: int | None
    incoming_priority: int
    relation: PriorityRelation
    higher_than_current: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreemptionRule:
    """Explicit preemption policy for a current-kind / incoming-kind pair."""

    current_kind: str
    incoming_kind: str
    relation: PriorityRelation
    interrupt: bool
    disposition: IncomingDisposition
    when_not_interruptible: IncomingDisposition | None = None
    on_interrupt: str | None = None
    cleanup_policy: CleanupPolicy = CleanupPolicy.NONE
    resume_policy: ResumePolicy = ResumePolicy.NO_RESUME

    def __post_init__(self) -> None:
        if not self.current_kind.strip():
            raise ValueError("current_kind must not be blank")
        if not self.incoming_kind.strip():
            raise ValueError("incoming_kind must not be blank")
        if self.interrupt and self.disposition is not IncomingDisposition.PROCESS_NOW:
            raise ValueError("interrupt=True requires PROCESS_NOW disposition")
        if self.interrupt and self.when_not_interruptible is None:
            raise ValueError(
                "interrupt=True requires explicit when_not_interruptible disposition"
            )
        if not self.interrupt and self.when_not_interruptible is not None:
            raise ValueError(
                "when_not_interruptible is only valid when interrupt=True"
            )
        if not self.interrupt and self.on_interrupt is not None:
            raise ValueError("on_interrupt is only valid when interrupt=True")


@dataclass(frozen=True, slots=True)
class PreemptionDecision:
    """Pure decision result; no cancellation, queueing, or state mutation occurs here."""

    current_subject_id: str | None
    incoming_subject_id: str
    interrupt: bool
    can_interrupt: bool
    disposition: IncomingDisposition
    on_interrupt: str | None
    cleanup_policy: CleanupPolicy
    resume_policy: ResumePolicy
    priority_decision: PriorityDecision
    reason_codes: tuple[str, ...]
