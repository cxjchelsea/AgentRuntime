"""SafetyGuard：M2 双阶段安全评估，统一返回 SafetyResult。"""

from abc import ABC, abstractmethod

from runtime.contracts import (
    RuntimeContext,
    RuntimeInput,
    SafetyResult,
    UnderstandingState,
)


class SafetyGuard(ABC):
    """Early 与 Deep 共用同一 Contract，仅 phase 不同。"""

    @abstractmethod
    async def evaluate_early(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext | None = None,
    ) -> SafetyResult:
        """节点②早期安全评估，返回 phase=EARLY 的 SafetyResult。"""
        raise NotImplementedError

    @abstractmethod
    async def evaluate_deep(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        early_safety: SafetyResult,
    ) -> SafetyResult:
        """理解之后的深度安全评估，返回 phase=DEEP 的 SafetyResult。"""
        raise NotImplementedError
