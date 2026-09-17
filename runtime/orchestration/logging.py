"""最小 Structured Logging Hook。不依赖外部监控平台。"""

from __future__ import annotations

import json
import logging
from typing import Protocol


class RuntimeLogHook(Protocol):
    """可替换的结构化日志出口。"""

    def emit(self, record: dict[str, object]) -> None:
        """写入一条已脱敏记录。"""


class NullLogHook:
    """禁用日志。Trace 事件仍可独立存在。"""

    def emit(self, record: dict[str, object]) -> None:
        """丢弃记录。"""
        return


class RecordingLogHook:
    """测试用可替换 Hook。"""

    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def emit(self, record: dict[str, object]) -> None:
        """保存副本，避免后续修改污染断言。"""
        self.records.append(dict(record))


class StdlibStructuredLogHook:
    """默认 Hook：标准 logging，输出 JSON 行。"""

    def __init__(self, logger_name: str = "runtime.orchestration") -> None:
        self._logger = logging.getLogger(logger_name)

    def emit(self, record: dict[str, object]) -> None:
        """只记录结构化字段，不展开 payload。"""
        self._logger.info(json.dumps(record, default=str, ensure_ascii=False))
