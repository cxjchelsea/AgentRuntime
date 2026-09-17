"""M1 节点① Input Processor 的默认真实实现。

处理器只标准化已经适配为 ``RuntimeInput`` 的输入，不推断意图、情绪、
隐含需求、策略、Domain 值，也不执行 Tool。

语音 SDK、调度事件、HTTP 回调等原始来源适配器不属于本类职责，因为
冻结的 M0 接口已经明确为 ``RuntimeInput -> RuntimeInput``。
"""

from __future__ import annotations

import math
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

from runtime.contracts import InputTriggerType, RuntimeInput
from runtime.input_processing.errors import InputNormalizationError
from runtime.interfaces.input import InputProcessor

_WHITESPACE_RE = re.compile(r"\s+")
_ZERO_WIDTH_SPACE = "\u200b"
_BOM = "\ufeff"

_REQUIRED_IDENTIFIERS = (
    "request_id",
    "trace_id",
    "session_id",
    "subject_id",
    "identity_scope",
)

_USER_TRIGGERS = {
    InputTriggerType.USER_VOICE,
    InputTriggerType.USER_TEXT,
    InputTriggerType.USER_OTHER,
}


class DefaultInputProcessor(InputProcessor):
    """标准化一份 Canonical ``RuntimeInput``，不做语义推断。

    M1-IU1 当前职责：
    - 校验并清洗 Runtime 标识符；
    - 标准化可见文本，同时保留标准化前 ``raw_text``；
    - 将带时区时间统一为 UTC；
    - 校验 confidence 为 [0, 1] 内有限值；
    - 拒绝没有任何有效内容的用户输入；
    - 原样保留 payload / segments / metadata，不解释 Domain 语义。

    本单元明确不实现：
    - 各来源 RawInput Adapter；
    - 依赖模型的 ASR 标点恢复；
    - 依赖生命周期 / Store 的重复输入抑制；
    - Understanding、Routing、Policy、Tool 或 Domain 行为。
    """

    async def process(self, runtime_input: RuntimeInput) -> RuntimeInput:
        """返回经过重新校验的标准化副本，不原地修改输入对象。"""
        data = runtime_input.model_dump(mode="python")

        for field_name in _REQUIRED_IDENTIFIERS:
            data[field_name] = self._normalize_identifier(
                field_name,
                data[field_name],
                required=True,
            )

        for field_name in ("actor_id", "device_id", "tenant_id"):
            data[field_name] = self._normalize_identifier(
                field_name,
                data.get(field_name),
                required=False,
            )

        original_text = data.get("text")
        original_raw_text = data.get("raw_text")

        if original_raw_text is None and original_text is not None:
            # raw_text 始终保存标准化前文本；调用方只有 text 时先备份原值。
            data["raw_text"] = original_text

        normalized_text = self._normalize_text(original_text)
        normalized_raw_text = self._normalize_text(original_raw_text)
        # text 为空白或仅含不可见字符时，应继续尝试已有 raw_text，而不是
        # 因为原始 text 非 None 就阻断回退。
        data["text"] = normalized_text or normalized_raw_text

        data["input_type"] = self._normalize_optional_string(data.get("input_type"))
        data["timestamp"] = self._normalize_timestamp(data["timestamp"])
        data["confidence"] = self._normalize_confidence(data.get("confidence"))

        self._validate_meaningful_input(
            trigger_type=data["trigger_type"],
            normalized_text=data.get("text"),
            normalized_raw_text=self._normalize_text(data.get("raw_text")),
            input_payload=data.get("input_payload"),
            segments=data.get("segments"),
        )

        # 不使用默认不校验 update 的 model_copy；统一再次经过 Canonical Schema。
        return RuntimeInput.model_validate(data)

    @staticmethod
    def _normalize_identifier(
        field_name: str,
        value: str | None,
        *,
        required: bool,
    ) -> str | None:
        """统一必填和可选标识符规则：trim，且禁止内部空白。"""
        if value is None:
            if required:
                raise InputNormalizationError(field_name, "must not be missing")
            return None

        normalized = value.strip()
        if not normalized:
            if required:
                raise InputNormalizationError(field_name, "must not be blank")
            return None

        if any(character.isspace() for character in normalized):
            raise InputNormalizationError(
                field_name,
                "identifier must not contain whitespace",
            )
        return normalized

    @staticmethod
    def _normalize_optional_string(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _normalize_text(value: str | None) -> str | None:
        if value is None:
            return None

        # NFKC 仅统一兼容字符形态，不做任何业务或语义解释。
        normalized = unicodedata.normalize("NFKC", value)
        normalized = normalized.replace(_BOM, "").replace(_ZERO_WIDTH_SPACE, "")
        normalized = _WHITESPACE_RE.sub(" ", normalized).strip()
        return normalized or None

    @staticmethod
    def _normalize_timestamp(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise InputNormalizationError(
                "timestamp",
                "must be timezone-aware; timezone must not be guessed",
            )
        return value.astimezone(UTC)

    @staticmethod
    def _normalize_confidence(value: float | None) -> float | None:
        if value is None:
            return None
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise InputNormalizationError(
                "confidence",
                "must be a finite number between 0 and 1",
            )
        return value

    @staticmethod
    def _validate_meaningful_input(
        *,
        trigger_type: InputTriggerType,
        normalized_text: str | None,
        normalized_raw_text: str | None,
        input_payload: dict[str, Any] | None,
        segments: list[dict[str, Any]] | None,
    ) -> None:
        """用户触发输入至少要有有效文本、非空 payload 或非空 segments。

        空 ``{}`` / ``[]`` 明确定义为“无内容”；系统/调度类事件可仅凭 trigger
        本身表达有效事件，因此不套用该限制。
        """
        if trigger_type not in _USER_TRIGGERS:
            return

        has_text = bool(normalized_text) or bool(normalized_raw_text)
        has_payload = bool(input_payload)
        has_segments = bool(segments)
        if not (has_text or has_payload or has_segments):
            raise InputNormalizationError(
                "input",
                "user-originated input must contain text, payload, or segments",
            )
