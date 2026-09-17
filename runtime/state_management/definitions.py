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
    """一个 Core RuntimeControlState 的确定性约束。"""

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


def core_runtime_state_definitions() -> tuple[RuntimeStateDefinition, ...]:
    """返回 Core RuntimeControlState 的默认生命周期图。

    这里只描述通用 Runtime 生命周期，不包含任何 Domain 业务状态或优先级。
    Domain 若需要更窄的边界，应显式注入自己的 Core 状态配置，而不是扩展枚举。
    """

    return (
        RuntimeStateDefinition(
            RuntimeControlState.STARTING,
            interruptible=False,
            allowed_transitions=(
                RuntimeControlState.IDLE,
                RuntimeControlState.FAILED,
                RuntimeControlState.ENDED,
            ),
        ),
        RuntimeStateDefinition(
            RuntimeControlState.IDLE,
            interruptible=True,
            allowed_transitions=(
                RuntimeControlState.LISTENING,
                RuntimeControlState.PROCESSING,
                RuntimeControlState.ENDED,
                RuntimeControlState.FAILED,
            ),
        ),
        RuntimeStateDefinition(
            RuntimeControlState.LISTENING,
            interruptible=True,
            allowed_transitions=(
                RuntimeControlState.PROCESSING,
                RuntimeControlState.IDLE,
                RuntimeControlState.ENDED,
                RuntimeControlState.FAILED,
            ),
        ),
        RuntimeStateDefinition(
            RuntimeControlState.PROCESSING,
            interruptible=True,
            allowed_transitions=(
                RuntimeControlState.RESPONDING,
                RuntimeControlState.WAITING_USER,
                RuntimeControlState.WAITING_EXTERNAL,
                RuntimeControlState.INTERRUPTED,
                RuntimeControlState.IDLE,
                RuntimeControlState.ENDED,
                RuntimeControlState.FAILED,
            ),
        ),
        RuntimeStateDefinition(
            RuntimeControlState.RESPONDING,
            interruptible=True,
            allowed_transitions=(
                RuntimeControlState.LISTENING,
                RuntimeControlState.IDLE,
                RuntimeControlState.WAITING_USER,
                RuntimeControlState.INTERRUPTED,
                RuntimeControlState.ENDED,
                RuntimeControlState.FAILED,
            ),
        ),
        RuntimeStateDefinition(
            RuntimeControlState.WAITING_USER,
            interruptible=True,
            allowed_transitions=(
                RuntimeControlState.PROCESSING,
                RuntimeControlState.IDLE,
                RuntimeControlState.INTERRUPTED,
                RuntimeControlState.ENDED,
                RuntimeControlState.FAILED,
            ),
        ),
        RuntimeStateDefinition(
            RuntimeControlState.WAITING_EXTERNAL,
            interruptible=True,
            allowed_transitions=(
                RuntimeControlState.PROCESSING,
                RuntimeControlState.IDLE,
                RuntimeControlState.INTERRUPTED,
                RuntimeControlState.ENDED,
                RuntimeControlState.FAILED,
            ),
        ),
        RuntimeStateDefinition(
            RuntimeControlState.INTERRUPTED,
            interruptible=False,
            allowed_transitions=(
                RuntimeControlState.PROCESSING,
                RuntimeControlState.LISTENING,
                RuntimeControlState.IDLE,
                RuntimeControlState.ENDED,
                RuntimeControlState.FAILED,
            ),
        ),
        RuntimeStateDefinition(
            RuntimeControlState.ENDED,
            interruptible=False,
            allowed_transitions=(),
        ),
        RuntimeStateDefinition(
            RuntimeControlState.FAILED,
            interruptible=False,
            allowed_transitions=(
                RuntimeControlState.IDLE,
                RuntimeControlState.ENDED,
            ),
        ),
    )
