"""Core Control Enums。

只包含 Canonical Registry 冻结的 Runtime 控制枚举。
禁止把 Domain Registered Values 写入本模块。
"""

from enum import Enum


class InputSource(str, Enum):
    """输入来源。"""

    USER = "USER"
    SYSTEM = "SYSTEM"
    SCHEDULER = "SCHEDULER"
    TOOL = "TOOL"
    WORKFLOW = "WORKFLOW"
    DEVICE = "DEVICE"
    EXTERNAL = "EXTERNAL"


class InputTriggerType(str, Enum):
    """输入触发类型。"""

    USER_VOICE = "USER_VOICE"
    USER_TEXT = "USER_TEXT"
    USER_OTHER = "USER_OTHER"
    SYSTEM_EVENT = "SYSTEM_EVENT"
    SCHEDULER_EVENT = "SCHEDULER_EVENT"
    TOOL_CALLBACK = "TOOL_CALLBACK"
    WORKFLOW_CALLBACK = "WORKFLOW_CALLBACK"
    TIMEOUT = "TIMEOUT"
    NETWORK_EVENT = "NETWORK_EVENT"
    DEVICE_EVENT = "DEVICE_EVENT"


class IdentityStatus(str, Enum):
    """主体绑定状态。"""

    BOUND = "BOUND"
    UNBOUND = "UNBOUND"
    UNKNOWN = "UNKNOWN"


class RuntimeControlState(str, Enum):
    """Core Runtime 控制状态，不含领域业务阶段。"""

    STARTING = "STARTING"
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    PROCESSING = "PROCESSING"
    RESPONDING = "RESPONDING"
    WAITING_USER = "WAITING_USER"
    WAITING_EXTERNAL = "WAITING_EXTERNAL"
    INTERRUPTED = "INTERRUPTED"
    ENDED = "ENDED"
    FAILED = "FAILED"


class SafetyPhase(str, Enum):
    """SafetyResult 阶段。EARLY 进入主链，DEEP 仅 M2 内部。"""

    EARLY = "EARLY"
    DEEP = "DEEP"


class SafetyRiskLevel(str, Enum):
    """安全风险等级。"""

    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ValidationMode(str, Enum):
    """策略要求的校验模式。"""

    FAST = "FAST"
    STANDARD = "STANDARD"
    STRICT = "STRICT"


class PlanningMode(str, Enum):
    """规划模式。"""

    FORCED = "FORCED"
    DETERMINISTIC = "DETERMINISTIC"
    AGENT_PLANNED = "AGENT_PLANNED"
    DEGRADED = "DEGRADED"


class RetrievalMode(str, Enum):
    """跨 Domain 的知识检索控制模式。"""

    VECTOR = "VECTOR"
    KEYWORD = "KEYWORD"
    HYBRID = "HYBRID"
    STRUCTURED_LOOKUP = "STRUCTURED_LOOKUP"
    EXTERNAL_API = "EXTERNAL_API"
    NONE = "NONE"


class PlanApprovalStatus(str, Enum):
    """计划批准状态。"""

    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ExecutionPlanStatus(str, Enum):
    """执行计划状态，不等于 BusinessStatus。"""

    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    PREEMPTED = "PREEMPTED"


class ValidationStatus(str, Enum):
    """结果验证状态。"""

    VALIDATED = "VALIDATED"
    PARTIALLY_VALIDATED = "PARTIALLY_VALIDATED"
    NOT_VALIDATED = "NOT_VALIDATED"
    CONFLICTED = "CONFLICTED"
    UNKNOWN = "UNKNOWN"


class BusinessStatus(str, Enum):
    """业务目标是否达成的通用判定。"""

    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"
    WAITING = "WAITING"
    UNKNOWN = "UNKNOWN"


class MemoryStatus(str, Enum):
    """记忆生命周期状态。"""

    STABLE = "STABLE"
    TEMPORARY = "TEMPORARY"
    EMERGING = "EMERGING"
    UNCERTAIN = "UNCERTAIN"
    DEPRECATED = "DEPRECATED"


class TransitionStatus(str, Enum):
    """状态迁移提交状态。"""

    NOT_REQUIRED = "NOT_REQUIRED"
    PROPOSED = "PROPOSED"
    COMMITTED = "COMMITTED"
    REJECTED = "REJECTED"
    DEFERRED = "DEFERRED"


class TaskStatus(str, Enum):
    """跨轮任务状态。"""

    ACTIVE = "ACTIVE"
    WAITING_USER = "WAITING_USER"
    WAITING_EXTERNAL = "WAITING_EXTERNAL"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class CoreControlIntent(str, Enum):
    """Runtime 控制意图。领域 Intent 不得加入本枚举。"""

    UNKNOWN = "UNKNOWN"
    STOP = "STOP"
    CANCEL = "CANCEL"
    HELP = "HELP"


class SpeechAct(str, Enum):
    """言语行为。"""

    REQUEST = "REQUEST"
    QUESTION = "QUESTION"
    STATEMENT = "STATEMENT"
    ANSWER = "ANSWER"
    CONFIRMATION = "CONFIRMATION"
    REJECTION = "REJECTION"
    CORRECTION = "CORRECTION"
    COMPLAINT = "COMPLAINT"
    EMOTIONAL_EXPRESSION = "EMOTIONAL_EXPRESSION"
    GREETING = "GREETING"
    FAREWELL = "FAREWELL"
    COMMAND = "COMMAND"
    UNCERTAIN = "UNCERTAIN"


class GenerationPath(str, Enum):
    """回复生成路径。"""

    TEMPLATE = "TEMPLATE"
    LLM = "LLM"
    HYBRID = "HYBRID"
    SILENT = "SILENT"


class ResponseType(str, Enum):
    """回复类型。"""

    NORMAL = "NORMAL"
    SHORT_ACK = "SHORT_ACK"
    RESULT_REPORT = "RESULT_REPORT"
    CLARIFICATION = "CLARIFICATION"
    TASK_PROMPT = "TASK_PROMPT"
    SAFETY_MESSAGE = "SAFETY_MESSAGE"
    CLOSING = "CLOSING"
    SILENCE = "SILENCE"
    SYSTEM_ERROR = "SYSTEM_ERROR"


class CoreControlAction(str, Enum):
    """跨领域控制动作。领域 Action 不得加入本枚举。"""

    ACKNOWLEDGE = "ACKNOWLEDGE"
    ANSWER = "ANSWER"
    CLARIFY = "CLARIFY"
    WAIT = "WAIT"
    END = "END"
    CONTINUE_TASK = "CONTINUE_TASK"
    ASK_REQUIRED_FIELD = "ASK_REQUIRED_FIELD"
    CONFIRM_ACTION = "CONFIRM_ACTION"
    COMPLETE_TASK = "COMPLETE_TASK"
    CANCEL_TASK = "CANCEL_TASK"
    DEFER_TASK = "DEFER_TASK"
    CALL_TOOL = "CALL_TOOL"
    USE_MEMORY = "USE_MEMORY"
    ENTER_SAFETY_WORKFLOW = "ENTER_SAFETY_WORKFLOW"
    STOP_CURRENT_ACTIVITY = "STOP_CURRENT_ACTIVITY"


class CoreControlStrategy(str, Enum):
    """跨领域控制策略。领域 Strategy 不得加入本枚举。"""

    DIRECT_FULFILLMENT = "DIRECT_FULFILLMENT"
    CLARIFY_THEN_ACT = "CLARIFY_THEN_ACT"
    TASK_CONTINUATION = "TASK_CONTINUATION"
    SAFETY_OVERRIDE = "SAFETY_OVERRIDE"
    DEGRADED_FALLBACK = "DEGRADED_FALLBACK"
    WAIT = "WAIT"
    END = "END"


class IntentEvidenceSource(str, Enum):
    """IntentResult.source。"""

    EXPLICIT = "EXPLICIT"
    INFERRED = "INFERRED"
    RULE = "RULE"


class ProcessingPath(str, Enum):
    """理解处理路径。"""

    FAST_PATH = "FAST_PATH"
    DEEP_PATH = "DEEP_PATH"
    HYBRID_PATH = "HYBRID_PATH"
    DEGRADED_PATH = "DEGRADED_PATH"


class ResponseValidationStatus(str, Enum):
    """RuntimeResponse 校验状态。字段名来自 Canonical，枚举来自 Schema Registry 其余对象。"""

    VALID = "VALID"
    FALLBACK_VALID = "FALLBACK_VALID"
    INVALID = "INVALID"


class CommitStatus(str, Enum):
    """UpdateResult.commit_result 状态。"""

    ATOMIC = "ATOMIC"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"


class EntityStatus(str, Enum):
    """实体解析状态。结构来自 Schema Registry 其余对象。"""

    EXPLICIT = "EXPLICIT"
    INFERRED = "INFERRED"
    RESOLVED = "RESOLVED"
    UNCERTAIN = "UNCERTAIN"
    NEGATED = "NEGATED"
    SUPERSEDED = "SUPERSEDED"
