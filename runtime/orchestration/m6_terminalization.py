"""B2 Foundation F: isolated in-memory turn terminalization, not production wired."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum

from runtime.orchestration.trace import TraceContext, TraceStatus


class TerminalizationErrorCode(StrEnum):
    INVALID_TRACE = "INVALID_TRACE"
    INVALID_STATUS = "INVALID_STATUS"
    INCONSISTENT_TERMINAL_STATE = "INCONSISTENT_TERMINAL_STATE"
    TERMINAL_LOG_FAILURE = "TERMINAL_LOG_FAILURE"


class TerminalizationError(RuntimeError):
    def __init__(self, code: TerminalizationErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


def finish_turn_once(
    trace: TraceContext,
    status: TraceStatus,
    reason_code: str | None = None,
    *,
    emit_turn_end: Callable[[TraceContext], None] | None = None,
    primary_exception: BaseException | None = None,
) -> bool:
    """Commit Trace before a *single* optional log attempt.

    When a primary failure already exists, a logging failure must not mask it.
    Callers remain responsible for re-raising that original failure.
    """
    if type(trace) is not TraceContext:
        raise TerminalizationError(TerminalizationErrorCode.INVALID_TRACE)
    if type(status) is not TraceStatus or status is TraceStatus.RUNNING:
        raise TerminalizationError(TerminalizationErrorCode.INVALID_STATUS)
    running = trace.status is TraceStatus.RUNNING
    unfinished = trace.finished_at is None
    if running != unfinished:
        raise TerminalizationError(
            TerminalizationErrorCode.INCONSISTENT_TERMINAL_STATE
        )
    if not running:
        return False
    if reason_code is not None and (type(reason_code) is not str or not reason_code):
        raise TerminalizationError(TerminalizationErrorCode.INVALID_STATUS)
    trace.finished_at = datetime.now(UTC)
    trace.status = status
    if reason_code is not None:
        trace.error = reason_code
    if emit_turn_end is not None:
        try:
            emit_turn_end(trace)
        except Exception as exc:
            if primary_exception is None:
                raise TerminalizationError(
                    TerminalizationErrorCode.TERMINAL_LOG_FAILURE
                ) from exc
            # Original exception is re-raised by caller; Trace stays terminal.
    return True
