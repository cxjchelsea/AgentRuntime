"""M2-IU2 Runtime State / Transition Engine 错误。"""


class RuntimeStateError(RuntimeError):
    """State Engine 基础错误。"""


class DuplicateStateDefinitionError(RuntimeStateError):
    """同一 RuntimeControlState 被重复定义。"""


class MissingStateDefinitionError(RuntimeStateError):
    """迁移涉及未注册的 Core 状态定义。"""


class InvalidStateTransitionError(RuntimeStateError):
    """请求的 Core 状态迁移不合法。"""


class StateNotInitializedError(RuntimeStateError):
    """当前 scope 尚未建立 RuntimeStateSnapshot。"""


class StateStoreUnavailableError(RuntimeStateError):
    """状态存储明确不可用。"""


class StateRevisionConflictError(RuntimeStateError):
    """CAS 提交时 revision 已变化，拒绝覆盖较新的状态。"""
