"""StateUpdate / MemoryUpdate / UpdateResult。

UpdateResult 是 M8 主链终点。前两者只是内部结果。
"""

from typing import Any, ClassVar

from runtime.contracts.common import CommitResult, VersionedContract
from runtime.contracts.enums import RuntimeControlState, TransitionStatus


class StateUpdate(VersionedContract):
    """RuntimeControlState 迁移结果，禁止写入 Domain 业务状态。"""

    CHAIN_TERMINUS: ClassVar[bool] = False

    previous_state: RuntimeControlState | None
    proposed_state: RuntimeControlState
    transition_status: TransitionStatus
    committed_state: RuntimeControlState | None = None
    transition_event: str | None = None
    transition_reason_codes: list[str] | None = None
    evidence_ids: list[str] | None = None
    domain_state_update: dict[str, Any] | None = None


class MemoryUpdate(VersionedContract):
    """记忆候选与写入结果。LLM 不得单独决定 WRITE。"""

    CHAIN_TERMINUS: ClassVar[bool] = False

    identity_scope: str
    candidates: list[dict[str, Any]] | None = None
    writes: list[dict[str, Any]] | None = None
    updates: list[dict[str, Any]] | None = None
    deletes: list[dict[str, Any]] | None = None
    ignored: list[dict[str, Any]] | None = None
    reason_codes: list[str] | None = None


class UpdateResult(VersionedContract):
    """M8 主链终点。"""

    CHAIN_TERMINUS: ClassVar[bool] = True

    update_id: str
    request_id: str
    identity_scope: str
    state_update: StateUpdate
    commit_result: CommitResult
    task_update: dict[str, Any] | None = None
    conversation_update: dict[str, Any] | None = None
    interaction_update: dict[str, Any] | None = None
    session_update: dict[str, Any] | None = None
    event_update: dict[str, Any] | None = None
    memory_update: MemoryUpdate | None = None
    quality: dict[str, Any] | None = None
