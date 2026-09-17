"""M2-IU1 可注入 Safety Rule 与内部 Finding。

具体“什么条件属于高风险”属于 Domain Rule Package；Core 只定义规则执行契约与
通用 SafetyResult 聚合所需的结构。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from runtime.contracts import (
    RuntimeContext,
    RuntimeInput,
    SafetyResult,
    SafetyRiskLevel,
    UnderstandingState,
)


@dataclass(frozen=True, slots=True)
class SafetyFinding:
    """单条 Safety Rule 的领域中立命中结果。"""

    rule_id: str
    risk_level: SafetyRiskLevel
    reason_codes: tuple[str, ...]
    risk_types: tuple[str, ...] = ()
    evidence: dict[str, Any] | None = None
    confidence: float | None = None
    interrupt_current_task: bool = False
    allowed_to_continue_normal_flow: bool = True
    safety_lock_required: bool = False
    force_workflow: str | None = None
    requires_immediate_action: bool = False
    restricted_actions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise ValueError("rule_id must not be blank")
        if not self.reason_codes:
            raise ValueError("reason_codes must not be empty")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")


class SafetyRule(ABC):
    """Domain Safety Rule 注入边界。

    一个规则可以只实现 Early、只实现 Deep，或同时实现两者。默认方法表示该阶段
    不参与判断，不等于“安全”。
    """

    @property
    @abstractmethod
    def rule_id(self) -> str:
        """稳定规则 ID；应由 Domain Rule Package 注册和版本管理。"""
        ...

    async def evaluate_early(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext | None,
    ) -> SafetyFinding | None:
        """M3 之前只使用 RuntimeInput 与有限 Context。"""
        return None

    async def evaluate_deep(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        early_safety: SafetyResult,
    ) -> SafetyFinding | None:
        """M3 之后可使用 UnderstandingState 做安全重评估。"""
        return None
