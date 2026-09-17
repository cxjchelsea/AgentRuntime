"""ResponsePlan 与 RuntimeResponse。"""

from typing import Any

from runtime.contracts.common import CanonicalModel, VersionedContract
from runtime.contracts.enums import (
    GenerationPath,
    ResponseType,
    ResponseValidationStatus,
)


class ResponseRequirement(CanonicalModel):
    """是否必须回复及回复类型。"""

    required: bool
    response_type: ResponseType
    reason_codes: list[str] | None = None


class ClaimPlan(CanonicalModel):
    """可执行表达计划中的声明约束。"""

    must_include_claims: list[str]
    forbidden_claims: list[str]
    optional_claims: list[str] | None = None
    required_qualifiers: list[str] | None = None


class ResponsePlan(VersionedContract):
    """M7 内部表达计划。主链对外输出是 RuntimeResponse。"""

    response_plan_id: str
    request_id: str
    response_requirement: ResponseRequirement
    claim_plan: ClaimPlan
    communicative_goals: list[str] | None = None
    content_plan: dict[str, Any] | None = None
    tone_profile: dict[str, Any] | None = None
    length_policy: dict[str, Any] | None = None
    question_plan: dict[str, Any] | None = None
    memory_expression: dict[str, Any] | None = None
    safety_constraints: dict[str, Any] | None = None
    tts_constraints: dict[str, Any] | None = None
    generation_path: GenerationPath | None = None


class RuntimeResponse(VersionedContract):
    """主链用户可见输出。"""

    response_id: str
    request_id: str
    response_type: ResponseType
    payload: dict[str, Any]
    response_validation_status: ResponseValidationStatus
    tts_payload: dict[str, Any] | None = None
    question: dict[str, Any] | None = None
    trace: dict[str, Any] | None = None
