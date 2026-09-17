"""UnderstandingState：嵌套理解结果，不恢复扁平旧字段。"""

from datetime import datetime
from typing import Any

from runtime.contracts.common import (
    CanonicalModel,
    QualityAssessment,
    VersionedContract,
)
from runtime.contracts.enums import (
    EntityStatus,
    IntentEvidenceSource,
    ProcessingPath,
    SpeechAct,
)

# 供测试与后续模块从 understanding 统一引用
__all__ = [
    "Entity",
    "IntentResult",
    "ProcessingPath",
    "QualityAssessment",
    "UncertaintyAssessment",
    "UnderstandingMetadata",
    "UnderstandingState",
]


class UnderstandingMetadata(CanonicalModel):
    """UnderstandingState.metadata。"""

    understanding_id: str
    request_id: str
    timestamp: datetime
    processing_path: ProcessingPath
    schema_version: str | None = None
    model_version: str | None = None
    prompt_version: str | None = None


class IntentResult(CanonicalModel):
    """单条意图结果。intent_id 来自 Registry，不是领域枚举。"""

    intent_id: str
    confidence: float
    source: IntentEvidenceSource
    evidence_ids: list[str] | None = None


class Entity(CanonicalModel):
    """通用实体结构，不冻结具体业务实体类型。"""

    entity_type: str
    value: str
    normalized_value: str | None = None
    status: EntityStatus | None = None
    confidence: float | None = None
    source: str | None = None


class UncertaintyAssessment(CanonicalModel):
    """理解不确定性。内部字段来自 Schema Registry 其余对象。"""

    uncertain_fields: list[str] | None = None
    candidate_interpretations: list[str] | None = None
    needs_clarification: bool | None = None
    safe_to_infer: bool | None = None


class SemanticUnderstanding(CanonicalModel):
    """语义层，全部可选。"""

    speech_act: SpeechAct | None = None
    normalized_meaning: str | None = None
    negation: bool | None = None
    confirmation: bool | None = None
    correction: bool | None = None
    entities: list[Entity] | None = None


class GoalUnderstanding(CanonicalModel):
    """目标理解，全部可选。"""

    explicit_goal: str | None = None
    implicit_need: str | None = None
    goal_parameters: dict[str, Any] | None = None
    confidence: float | None = None
    needs_clarification: bool | None = None


class Reference(CanonicalModel):
    """指代解析。"""

    reference_text: str
    reference_type: str | None = None
    resolved_target: str | None = None
    status: str | None = None
    source: str | None = None
    confidence: float | None = None


class UnderstandingState(VersionedContract):
    """主链理解输出。必须使用嵌套结构。"""

    metadata: UnderstandingMetadata
    intents: list[IntentResult]
    uncertainty: UncertaintyAssessment
    quality: QualityAssessment
    semantic: SemanticUnderstanding | None = None
    goal: GoalUnderstanding | None = None
    entities: list[Entity] | None = None
    references: list[Reference] | None = None
    topic: str | None = None
    emotion: dict[str, Any] | None = None
    needs: list[dict[str, Any]] | None = None
    interaction: dict[str, Any] | None = None
    risk: dict[str, Any] | None = None
    evidence: list[dict[str, Any]] | None = None
    memory_candidates: list[dict[str, Any]] | None = None
    candidate_actions: list[dict[str, Any]] | None = None
