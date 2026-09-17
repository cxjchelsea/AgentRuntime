"""PolicyDecision：当前允许/禁止做什么。"""

from datetime import datetime
from typing import Any

from runtime.contracts.common import VersionedContract
from runtime.contracts.enums import ValidationMode


class PolicyDecision(VersionedContract):
    """主链策略输出。reason 与 interrupt_required 已失效。"""

    policy_decision_id: str
    allowed: bool
    blocked: bool
    priority: int
    interrupt_current_task: bool
    validation_mode: ValidationMode
    reason_codes: list[str]
    created_at: datetime
    forced_workflow: str | None = None
    forced_action: str | None = None
    allowed_actions: list[str] | None = None
    forbidden_actions: list[str] | None = None
    allowed_skills: list[str] | None = None
    forbidden_skills: list[str] | None = None
    allowed_tools: list[str] | None = None
    forbidden_tools: list[str] | None = None
    confirmation_required: bool | None = None
    response_constraints: dict[str, Any] | None = None
    policy_flags: list[str] | None = None
