"""Core Identity 与 Domain Identity Extension。"""

from runtime.contracts.common import CanonicalModel, VersionedContract
from runtime.contracts.enums import IdentityStatus, InputSource


class CoreIdentity(VersionedContract):
    """领域中立的 Core 身份。禁止 elder_id / patient_id 等角色字段。"""

    subject_id: str
    identity_scope: str
    source: InputSource
    actor_id: str | None = None
    device_id: str | None = None
    tenant_id: str | None = None


class DomainIdentityExtension(VersionedContract):
    """领域身份扩展，只能挂到 RuntimeContext.domain_extensions.identity。"""

    domain_id: str
    subject_type: str
    domain_subject_ref: str | None = None
    claims: dict[str, object] | None = None


class IdentityContext(CanonicalModel):
    """RuntimeContext.identity_context。"""

    subject_id: str
    identity_scope: str
    identity_status: IdentityStatus
    actor_id: str | None = None
    device_id: str | None = None
    tenant_id: str | None = None
    language_preference: str | None = None
