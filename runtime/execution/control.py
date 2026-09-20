"""M5 cancellation / preemption control-signal contracts.

Priority and safety decisions remain owned by M2/Runtime. M5 only observes an already
resolved execution-control signal and applies the corresponding stop/preempt behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class ExecutionControlSignalType(str, Enum):
    NONE = "NONE"
    CANCEL = "CANCEL"
    PREEMPT = "PREEMPT"


@dataclass(frozen=True, slots=True)
class ExecutionControlSignal:
    signal_type: ExecutionControlSignalType
    reason_code: str | None = None
    source: str | None = None

    def __post_init__(self) -> None:
        if self.signal_type is ExecutionControlSignalType.NONE:
            if self.reason_code is not None:
                raise ValueError("NONE signal cannot carry reason_code")
            return
        if self.reason_code is None or not self.reason_code.strip():
            raise ValueError("CANCEL/PREEMPT signal requires reason_code")
        if self.source is not None and not self.source.strip():
            raise ValueError("source must not be blank")


class ExecutionControlSignalSource(Protocol):
    async def get_signal(self, execution_id: str) -> ExecutionControlSignal:
        """Return Runtime/M2-resolved execution control for one execution."""
