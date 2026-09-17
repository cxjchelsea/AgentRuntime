"""Runtime Orchestrator 内部错误边界。

对齐 M0 RuntimeError 字段意图（error_code / stage / message / cause），
但本对象是 internal-only，不是新的 Canonical Contract。
不得把原始异常直接当作用户回复。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from runtime.orchestration.trace import TraceContext


class RuntimeOrchestrationError(Exception):
    """编排层基础错误。供后续 Trace / Observability 使用。"""

    def __init__(
        self,
        message: str,
        *,
        error_code: str,
        stage_name: str | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.stage_name = stage_name
        self.cause = cause
        self.trace_context: TraceContext | None = None


class DependencyMissingError(RuntimeOrchestrationError):
    """构造 Orchestrator 时缺少必要 Module Interface。"""

    def __init__(self, missing_dependency_names: list[str]) -> None:
        joined_names = ", ".join(missing_dependency_names)
        super().__init__(
            f"缺失依赖: {joined_names}",
            error_code="DEPENDENCY_MISSING",
            stage_name=None,
        )
        self.missing_dependency_names = missing_dependency_names


class StageExecutionError(RuntimeOrchestrationError):
    """某一调用点抛出未处理异常。不伪造成功。"""

    def __init__(self, stage_name: str, cause: BaseException) -> None:
        super().__init__(
            f"阶段执行失败: {stage_name}",
            error_code="STAGE_EXECUTION_ERROR",
            stage_name=stage_name,
            cause=cause,
        )


class ContractValidationError(RuntimeOrchestrationError):
    """阶段返回值不是约定的 Canonical Contract。"""

    def __init__(self, stage_name: str, message: str) -> None:
        super().__init__(
            message,
            error_code="CONTRACT_VALIDATION_FAILURE",
            stage_name=stage_name,
        )


class OrchestrationInvariantError(RuntimeOrchestrationError):
    """违反冻结调用不变量，例如 Draft 进入 M5。"""

    def __init__(self, stage_name: str, message: str) -> None:
        super().__init__(
            message,
            error_code="ORCHESTRATION_INVARIANT_VIOLATION",
            stage_name=stage_name,
        )
