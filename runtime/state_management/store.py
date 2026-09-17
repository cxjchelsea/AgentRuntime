"""M2-IU2 Runtime State Store 抽象与可执行内存实现。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Hashable
from threading import Lock

from runtime.state_management.definitions import RuntimeStateSnapshot
from runtime.state_management.errors import StateRevisionConflictError


class RuntimeStateStore(ABC):
    """Core Runtime 状态持久层边界。

    Store 只负责按 scope 读写快照；不判断迁移是否合法。
    """

    @abstractmethod
    async def load(self, scope_key: Hashable) -> RuntimeStateSnapshot | None:
        """读取当前状态；不存在时返回 None。"""
        ...

    @abstractmethod
    async def compare_and_set(
        self,
        scope_key: Hashable,
        *,
        expected_revision: int | None,
        snapshot: RuntimeStateSnapshot,
    ) -> None:
        """按 revision 原子提交；冲突时必须失败，不能静默覆盖。"""
        ...


class InMemoryRuntimeStateStore(RuntimeStateStore):
    """用于测试、PoC 和单进程运行时的真实内存 Store。

    这是明确的非生产 Adapter；生产环境可替换为数据库或分布式存储实现。
    """

    def __init__(self) -> None:
        self._items: dict[Hashable, RuntimeStateSnapshot] = {}
        self._lock = Lock()

    async def load(self, scope_key: Hashable) -> RuntimeStateSnapshot | None:
        with self._lock:
            return self._items.get(scope_key)

    async def compare_and_set(
        self,
        scope_key: Hashable,
        *,
        expected_revision: int | None,
        snapshot: RuntimeStateSnapshot,
    ) -> None:
        with self._lock:
            current = self._items.get(scope_key)
            current_revision = None if current is None else current.revision
            if current_revision != expected_revision:
                raise StateRevisionConflictError(
                    "runtime state revision changed before commit"
                )
            self._items[scope_key] = snapshot
