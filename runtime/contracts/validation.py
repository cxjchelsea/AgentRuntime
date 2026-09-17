"""ValidatedResult：已确认的业务真相层。"""

from typing import Any

from runtime.contracts.common import CanonicalModel, VersionedContract
from runtime.contracts.enums import BusinessStatus, ValidationStatus


class ClaimPolicy(CanonicalModel):
    """可表达声明策略。至少包含 allowed_claims 与 forbidden_claims。"""

    allowed_claims: list[str]
    forbidden_claims: list[str]
    conditional_claims: list[str] | None = None
    required_qualifiers: list[str] | None = None
    certainty_level: str | None = None


class ValidatedResult(VersionedContract):
    """主链验证输出。"""

    validation_id: str
    execution_id: str
    request_id: str
    validation_status: ValidationStatus
    business_status: BusinessStatus
    claim_policy: ClaimPolicy
    goal_validation: dict[str, Any] | None = None
    verified_facts: list[dict[str, Any]] | None = None
    unverified_facts: list[dict[str, Any]] | None = None
    conflicting_facts: list[dict[str, Any]] | None = None
    followup: dict[str, Any] | None = None
    state_recommendation: dict[str, Any] | None = None
    validation_errors: list[dict[str, Any]] | None = None
    quality: dict[str, Any] | None = None
