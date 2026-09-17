"""SafetyResult：唯一安全结果 Schema，用 phase 区分 EARLY / DEEP。"""

from datetime import datetime
from typing import Any

from runtime.contracts.common import VersionedContract
from runtime.contracts.enums import SafetyPhase, SafetyRiskLevel


class SafetyResult(VersionedContract):
    """不得再实现 EarlySafetyResult / DeepSafetyResult 独立类型。"""

    safety_result_id: str
    request_id: str
    phase: SafetyPhase
    risk_detected: bool
    risk_level: SafetyRiskLevel
    interrupt_current_task: bool
    allowed_to_continue_normal_flow: bool
    safety_lock_required: bool
    reason_codes: list[str]
    created_at: datetime
    risk_types: list[str] | None = None
    matched_rules: list[str] | None = None
    evidence: dict[str, Any] | None = None
    confidence: float | None = None
    force_workflow: str | None = None
    requires_immediate_action: bool | None = None
    restricted_actions: list[str] | None = None
