"""跨 Contract 的基础结构。

Quality 等对象在 Canonical 中被要求存在，但未冻结内部字段。
此处仅提供可序列化容器，不发明业务语义。
"""

from pydantic import BaseModel, ConfigDict

from runtime.contracts.enums import CommitStatus

SCHEMA_VERSION = "1.0.0"


class CanonicalModel(BaseModel):
    """所有 Core Contract 的共同约束：禁止未声明字段。"""

    model_config = ConfigDict(extra="forbid")


class VersionedContract(CanonicalModel):
    """带冻结 schema_version 的 Contract 基类。"""

    schema_version: str = SCHEMA_VERSION


class QualityAssessment(CanonicalModel):
    """质量对象占位。

    Canonical 要求 UnderstandingState / ActionPlan* 必须带 quality，
    但未冻结内部字段。允许附加非业务扩展键以外的说明性字段，
    因此此处 extra=allow，且无必填业务字段。
    """

    model_config = ConfigDict(extra="allow")


class DomainSchemaReference(CanonicalModel):
    """领域 Schema 引用，不把 Domain Schema 变成 Core 硬依赖。"""

    schema_id: str
    version: str
    domain_id: str | None = None


class CommitResult(CanonicalModel):
    """状态/记忆提交结果。"""

    status: CommitStatus
    detail: str | None = None
