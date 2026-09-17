"""内部 Trace 模型。internal-only / non-canonical。

不升级为跨模块 Canonical Contract。默认不携带敏感 payload。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class TraceStatus(str, Enum):
    """一轮 Trace 的生命周期状态。"""

    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"


class StageEventStatus(str, Enum):
    """单个调用点结束状态。START 由 started_at + 日志表达。"""

    SUCCESS = "SUCCESS"
    ERROR = "ERROR"


@dataclass
class StageTraceEvent:
    """一个实现调用点的可观察记录。"""

    stage_name: str
    trace_id: str
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: float | None = None
    status: StageEventStatus | None = None
    input_contract_type: str | None = None
    output_contract_type: str | None = None
    error_type: str | None = None
    error_message: str | None = None


@dataclass
class TraceContext:
    """可观察性状态。与 TurnExecutionContext 分工：只记录 identity / timing / events / error。"""

    request_id: str
    trace_id: str
    session_id: str
    turn_id: str
    started_at: datetime
    finished_at: datetime | None = None
    status: TraceStatus = TraceStatus.RUNNING
    stage_events: list[StageTraceEvent] = field(default_factory=list)
    error: str | None = None
