"""ExecutionResult：真实执行观察，不是业务真相。"""

from datetime import datetime
from typing import Any

from pydantic import ConfigDict

from runtime.contracts.common import CanonicalModel, VersionedContract
from runtime.contracts.enums import ExecutionPlanStatus, RuntimeControlState


class ExecutionTiming(CanonicalModel):
    """执行时间窗。Canonical 仅要求存在 timing 对象。"""

    model_config = ConfigDict(extra="allow")

    started_at: datetime | None = None
    finished_at: datetime | None = None


class StepExecutionResult(CanonicalModel):
    """单步执行结果。"""

    step_execution_id: str | None = None
    step_id: str | None = None
    action: str | None = None
    status: str | None = None
    skill_id: str | None = None
    workflow_id: str | None = None
    tool_call_ids: list[str] | None = None
    output: dict[str, Any] | None = None
    error: str | None = None
    retry_count: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ExecutionResult(VersionedContract):
    """主链执行输出。使用 plan_status 与分层 results。"""

    execution_id: str
    plan_id: str
    request_id: str
    identity_scope: str
    plan_status: ExecutionPlanStatus
    step_results: list[StepExecutionResult]
    timing: ExecutionTiming
    skill_results: list[dict[str, Any]] | None = None
    workflow_result: dict[str, Any] | None = None
    tool_results: list[dict[str, Any]] | None = None
    business_outputs: list[dict[str, Any]] | None = None
    execution_events: list[dict[str, Any]] | None = None
    state_observations: list[dict[str, Any]] | None = None
    errors: list[dict[str, Any]] | None = None
    cancellation: dict[str, Any] | None = None
    quality: dict[str, Any] | None = None


class ExecutionContext(VersionedContract):
    """M5 内部执行上下文。本轮仅作为依赖类型落地，不实现执行逻辑。"""

    execution_id: str
    plan_id: str
    request_id: str
    session_id: str
    identity_scope: str
    policy_snapshot: dict[str, Any]
    device_id: str | None = None
    current_state: RuntimeControlState | None = None
    step_state: dict[str, Any] | None = None
    tool_context: dict[str, Any] | None = None
    deadline: datetime | None = None
    cancellation_token: str | None = None
    trace_context: dict[str, Any] | None = None
