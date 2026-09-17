"""M2-IU4 internal policy aggregation types.

These are implementation types, not new Canonical Contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.contracts import ValidationMode
from runtime.policy_management.errors import InvalidPolicyFragmentError


@dataclass(frozen=True, slots=True)
class PolicyFragment:
    """One rule's partial contribution to the final PolicyDecision."""

    source_id: str
    allowed: bool | None = None
    blocked: bool | None = None
    priority: int | None = None
    interrupt_current_task: bool | None = None
    validation_mode: ValidationMode | None = None
    reason_codes: tuple[str, ...] = ()
    forced_workflow: str | None = None
    forced_action: str | None = None
    allowed_actions: tuple[str, ...] | None = None
    forbidden_actions: tuple[str, ...] | None = None
    allowed_skills: tuple[str, ...] | None = None
    forbidden_skills: tuple[str, ...] | None = None
    allowed_tools: tuple[str, ...] | None = None
    forbidden_tools: tuple[str, ...] | None = None
    confirmation_required: bool | None = None
    response_constraints: dict[str, Any] | None = None
    policy_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise InvalidPolicyFragmentError("source_id must not be blank")
        if self.allowed is True and self.blocked is True:
            raise InvalidPolicyFragmentError(
                "allowed=True and blocked=True cannot coexist in one fragment"
            )
        for field_name in (
            "reason_codes",
            "policy_flags",
            "allowed_actions",
            "forbidden_actions",
            "allowed_skills",
            "forbidden_skills",
            "allowed_tools",
            "forbidden_tools",
        ):
            values = getattr(self, field_name)
            if values is not None and any(not value.strip() for value in values):
                raise InvalidPolicyFragmentError(
                    f"{field_name} must not contain blank values"
                )
