"""RuntimeInput：本轮进入系统的标准输入。"""

from datetime import datetime
from typing import Any

from runtime.contracts.common import VersionedContract
from runtime.contracts.enums import InputSource, InputTriggerType


class RuntimeInput(VersionedContract):
    """主链起点。text / raw_text 都不是用户意图。"""

    request_id: str
    trace_id: str
    session_id: str
    subject_id: str
    identity_scope: str
    source: InputSource
    trigger_type: InputTriggerType
    timestamp: datetime
    actor_id: str | None = None
    device_id: str | None = None
    tenant_id: str | None = None
    input_type: str | None = None
    text: str | None = None
    raw_text: str | None = None
    input_payload: dict[str, Any] | None = None
    confidence: float | None = None
    segments: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None
