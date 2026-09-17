"""M2-IU2 Core Runtime 状态定义与迁移决策内部类型。

这些类型属于 State Engine 实现内部，不新增 Canonical Contract。
DomainState 不得进入本模块。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from runtime.contracts import RuntimeControlState


@dataclass(frozen=True, slots=True)
class RuntimeStateDefinition:
    """一个 Core RuntimeControlState 的确定性约束。

    ``allowed_transitions`` 必须由 Runtime 装配层显式提供。M2-IU2 不自行发明
    某个项目的完整状态迁移图。
    """

    state: RuntimeControlState
    interruptible: bool
    allowed_transitions: tuple[RuntimeControlState, ...]
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive when provided")
        if len(set(self.allowed_transitions)) != len(self.allowed_transitions):
            raise ValueError("allowed_transitions must not contain duplicates")


@dataclass(frozen=True, slots=True)
class RuntimeStateSnapshot:
    """State Store 中的 Core Runtime 状态快照。"""

    current_state: RuntimeControlState
    previous_state: RuntimeControlState | None
    entered_at: datetime
    interruptible: bool
    revision: int
    active_task_id: str | None = None
    active_workflow_id: str | None = None
    interaction_mode: str | None = None
    pending_question_id: str | None = None
    runtime_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.entered_at.tzinfo is None or self.entered_at.utcoffset() is None:
            raise ValueError("entered_at must be timezone-aware")
        if self.revision < 0:
            raise ValueError("revision must be non-negative")


@dataclass(frozen=True, slots=True)
class StateTransitionDecision:
    """一次迁移校验结果；不是 Canonical StateUpdate。"""

    from_state: RuntimeControlState
    to_state: RuntimeControlState
    allowed: bool
    no_op: bool
    reason_codes: tuple[str, ...]
    expected_revision: int
