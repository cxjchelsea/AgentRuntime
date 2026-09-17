"""M2-IU1 Safety Guard 内部错误类型。"""

from __future__ import annotations

from runtime.contracts import SafetyPhase


class SafetyGuardError(RuntimeError):
    """Safety Guard 基础错误。"""


class DuplicateSafetyRuleError(SafetyGuardError):
    """同一 Guard 内不允许重复 rule_id。"""


class InvalidSafetyFindingError(SafetyGuardError):
    """SafetyRule 返回了与规则契约不一致的 finding。"""


class SafetyRuleConflictError(SafetyGuardError):
    """多个 Hard Safety Rule 给出不可兼容的强制约束。"""


class SafetyRuleExecutionError(SafetyGuardError):
    """规则执行失败；不得把规则异常伪装成安全。"""

    def __init__(self, rule_id: str, phase: SafetyPhase, cause: BaseException) -> None:
        self.rule_id = rule_id
        self.phase = phase
        self.cause = cause
        super().__init__(f"safety rule execution failed: {rule_id} [{phase.value}]")


class SafetyGuardInvariantError(SafetyGuardError):
    """Early / Deep 调用链输入违反冻结不变量。"""
