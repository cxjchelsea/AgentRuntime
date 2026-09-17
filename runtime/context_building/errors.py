"""M1 Context Builder 内部错误。"""

from __future__ import annotations


class ContextBuildError(RuntimeError):
    """Context 构建失败基类。"""


class CriticalContextUnavailableError(ContextBuildError):
    """构造 RuntimeContext 所需的关键 Context 无法取得。"""

    def __init__(self, context_name: str, detail: str) -> None:
        self.context_name = context_name
        self.detail = detail
        super().__init__(f"critical context unavailable: {context_name}: {detail}")


class ContextBuildInvariantError(ContextBuildError):
    """M1 输入之间违反冻结不变量。"""


class InvalidContextProviderResultError(ContextBuildError):
    """Provider 返回了与声明 ContextKind 不匹配的类型。"""

    def __init__(self, context_name: str, expected: str, actual: str) -> None:
        self.context_name = context_name
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"invalid context provider result for {context_name}: "
            f"expected {expected}, got {actual}"
        )


class DuplicateContextProviderError(ContextBuildError):
    """同一 ContextKind 被重复注册，避免来源不明确。"""
