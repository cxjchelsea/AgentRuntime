"""单次 Turn 的内部执行上下文。

internal-only / non-canonical
TurnExecutionContext = 编排生命周期
TraceContext = 可观察性状态
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from runtime.contracts import RuntimeResponse, UpdateResult
from runtime.orchestration.trace import TraceContext


@dataclass
class TurnExecutionContext:
    """编排生命周期状态。不把完整业务结果写入日志。"""

    trace: TraceContext
    stage_results: dict[str, object] = field(default_factory=dict)

    @property
    def request_id(self) -> str:
        """复用 Trace 中的 request_id。"""
        return self.trace.request_id

    @property
    def trace_id(self) -> str:
        """复用 Trace 中的 trace_id。"""
        return self.trace.trace_id

    @property
    def session_id(self) -> str:
        """复用 Trace 中的 session_id。"""
        return self.trace.session_id

    @property
    def call_log(self) -> list[str]:
        """由 stage events 派生，避免第二套顺序账本。"""
        return [stage_event.stage_name for stage_event in self.trace.stage_events]


@dataclass(frozen=True)
class RuntimeTurnOutcome:
    """Orchestrator 内部返回值。不是 Canonical Contract。"""

    runtime_response: RuntimeResponse
    update_result: UpdateResult
    turn_context: TurnExecutionContext

    @property
    def trace(self) -> TraceContext:
        """附带 trace reference，不升级为业务 Contract。"""
        return self.turn_context.trace

    def __iter__(self) -> Iterator[RuntimeResponse | UpdateResult]:
        """允许解包为 (RuntimeResponse, UpdateResult)。"""
        yield self.runtime_response
        yield self.update_result
