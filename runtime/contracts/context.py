"""RuntimeContext 及其子上下文。"""

from datetime import datetime
from typing import Any

from runtime.contracts.common import CanonicalModel, VersionedContract
from runtime.contracts.enums import RuntimeControlState, TaskStatus
from runtime.contracts.identity import DomainIdentityExtension, IdentityContext


class SessionContext(CanonicalModel):
    """会话上下文。字段来自 Schema Registry 其余对象。"""

    session_id: str
    started_at: datetime | None = None
    last_active_at: datetime | None = None
    turn_index: int | None = None
    session_type: str | None = None
    current_topic: str | None = None
    session_summary: str | None = None
    ended: bool | None = None


class RuntimeStateContext(CanonicalModel):
    """Core Runtime 状态上下文，不含 Domain 业务阶段。"""

    current_state: RuntimeControlState
    previous_state: RuntimeControlState | None
    interruptible: bool
    entered_at: datetime
    active_task_id: str | None = None
    active_workflow_id: str | None = None
    interaction_mode: str | None = None
    pending_question_id: str | None = None
    runtime_flags: list[str] | None = None


class ConversationContext(CanonicalModel):
    """对话上下文。全部可选，供后续 M1 填充。"""

    recent_turns: list[dict[str, Any]] | None = None
    current_topic: str | None = None
    topic_history: list[str] | None = None
    pending_reference: str | None = None
    pending_question: str | None = None
    last_user_message: str | None = None
    last_agent_action: str | None = None
    conversation_stage: str | None = None


class TaskContext(CanonicalModel):
    """跨轮任务上下文。"""

    task_id: str | None = None
    task_type: str | None = None
    active_task: str | None = None
    task_stage: str | None = None
    required_fields: list[str] | None = None
    collected_fields: list[str] | None = None
    next_required_field: str | None = None
    timeout_at: datetime | None = None
    status: TaskStatus | None = None


class TimeContext(CanonicalModel):
    """时间上下文。quiet_period 仅为通用时间窗，不是陪护业务字段。"""

    current_datetime: datetime | None = None
    date: str | None = None
    weekday: str | None = None
    time_of_day: str | None = None
    quiet_period: bool | None = None
    special_date: str | None = None
    active_time_window: str | None = None


class MemoryContext(CanonicalModel):
    """已检索记忆上下文。"""

    retrieved_memories: list[dict[str, Any]] | None = None
    memory_query: str | None = None
    retrieval_reason: str | None = None
    memory_confidence: float | None = None
    memory_status: str | None = None
    service_status: str | None = None


class SafetyContext(CanonicalModel):
    """当前安全背景。"""

    current_risk_state: str | None = None
    active_safety_event: str | None = None
    recent_safety_event: str | None = None
    safety_lock: bool | None = None
    restricted_actions: list[str] | None = None


class ToolContext(CanonicalModel):
    """工具调用背景。不包含播放等业务必填字段。"""

    active_tool_calls: list[dict[str, Any]] | None = None
    recent_tool_results: list[dict[str, Any]] | None = None
    network_status: str | None = None


class InteractionContext(CanonicalModel):
    """交互策略背景。"""

    last_agent_action: str | None = None
    last_response_strategy: str | None = None
    recent_questions_count: int | None = None
    recent_questions: list[str] | None = None
    silence_mode: bool | None = None


class EnvironmentContext(CanonicalModel):
    """运行环境背景。"""

    network_status: str | None = None
    audio_status: str | None = None
    speaker_status: str | None = None
    microphone_status: str | None = None
    battery_status: str | None = None


class DomainExtensions(CanonicalModel):
    """DomainState / DomainIdentity 的唯一挂载点。"""

    domain_id: str
    identity: DomainIdentityExtension | None = None
    domain_state: dict[str, Any] | None = None
    extra: dict[str, Any] | None = None


class RuntimeContext(VersionedContract):
    """系统当前已知背景。"""

    identity_context: IdentityContext
    session_context: SessionContext
    runtime_state_context: RuntimeStateContext
    conversation_context: ConversationContext | None = None
    task_context: TaskContext | None = None
    time_context: TimeContext | None = None
    memory_context: MemoryContext | None = None
    safety_context: SafetyContext | None = None
    tool_context: ToolContext | None = None
    interaction_context: InteractionContext | None = None
    environment_context: EnvironmentContext | None = None
    domain_extensions: DomainExtensions | None = None
    missing_context: list[str] | None = None
