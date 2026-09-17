"""BaseRegistry：确定性行为的通用注册表。

不执行业务，不静默覆盖，不自动创建缺失项。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from runtime.registries.errors import (
    DuplicateRegistrationError,
    InvalidRegistryItemError,
    RegistryItemNotFoundError,
)

DefinitionType = TypeVar("DefinitionType")


@dataclass(frozen=True)
class RegistryKey:
    """最小稳定标识：id + version + 可选 namespace。"""

    item_id: str
    version: str
    namespace: str | None = None


@dataclass
class RegistryRecord(Generic[DefinitionType]):
    """定义与实现引用的绑定，不含执行逻辑。"""

    key: RegistryKey
    definition: DefinitionType
    implementation_ref: object | None = None
    enabled: bool = True


class BaseRegistry(Generic[DefinitionType]):
    """通用 Registry 机制。子类只负责抽取 key，不添加业务语义。"""

    # 子类可声明期望的定义类型；None 表示不做运行时类型约束
    _expected_definition_type: type[object] | None = None

    def __init__(self) -> None:
        self._records: dict[RegistryKey, RegistryRecord[DefinitionType]] = {}

    def register(
        self,
        item_id: str,
        version: str,
        definition: DefinitionType,
        *,
        namespace: str | None = None,
        implementation_ref: object | None = None,
        enabled: bool = True,
    ) -> None:
        """按最小稳定标识注册。重复 key 必须失败，不静默覆盖。"""
        self._store(
            item_id,
            version,
            definition,
            namespace=namespace,
            implementation_ref=implementation_ref,
            enabled=enabled,
        )

    def _store(
        self,
        item_id: str,
        version: str,
        definition: DefinitionType,
        *,
        namespace: str | None = None,
        implementation_ref: object | None = None,
        enabled: bool = True,
    ) -> None:
        """内部写入。统一处理非法定义、类型不匹配与重复注册。"""
        if definition is None:
            raise InvalidRegistryItemError("definition 不得为空")
        expected_definition_type = type(self)._expected_definition_type
        if expected_definition_type is not None and not isinstance(
            definition, expected_definition_type
        ):
            raise InvalidRegistryItemError(
                f"类型不匹配: 期望 {expected_definition_type.__name__}，"
                f"实际 {type(definition).__name__}"
            )
        registry_key = self._build_key(item_id, version, namespace)
        if registry_key in self._records:
            raise DuplicateRegistrationError(
                f"已存在注册项: {registry_key.item_id}@{registry_key.version}"
            )
        self._records[registry_key] = RegistryRecord(
            key=registry_key,
            definition=definition,
            implementation_ref=implementation_ref,
            enabled=enabled,
        )

    def get(
        self,
        item_id: str,
        version: str,
        *,
        namespace: str | None = None,
    ) -> RegistryRecord[DefinitionType]:
        """精确获取某版本。不猜测、不回退。"""
        registry_key = self._build_key(item_id, version, namespace)
        stored_record = self._records.get(registry_key)
        if stored_record is None:
            raise RegistryItemNotFoundError(
                f"未注册: {registry_key.item_id}@{registry_key.version}"
            )
        return stored_record

    def exists(
        self,
        item_id: str,
        version: str,
        *,
        namespace: str | None = None,
    ) -> bool:
        """判断精确 key 是否存在。"""
        registry_key = self._build_key(item_id, version, namespace, validate=False)
        if registry_key.item_id == "" or registry_key.version == "":
            return False
        return registry_key in self._records

    def list(
        self, *, namespace: str | None = None
    ) -> list[RegistryRecord[DefinitionType]]:
        """列出已注册项。namespace 为 None 时列出全部。"""
        if namespace is None:
            return list(self._records.values())
        return [
            stored_record
            for stored_record in self._records.values()
            if stored_record.key.namespace == namespace
        ]

    def unregister(
        self,
        item_id: str,
        version: str,
        *,
        namespace: str | None = None,
    ) -> None:
        """显式移除。不存在则报错。"""
        registry_key = self._build_key(item_id, version, namespace)
        if registry_key not in self._records:
            raise RegistryItemNotFoundError(
                f"无法移除未注册项: {registry_key.item_id}@{registry_key.version}"
            )
        del self._records[registry_key]

    def enable(
        self,
        item_id: str,
        version: str,
        *,
        namespace: str | None = None,
    ) -> None:
        """标记可用。不执行业务。"""
        self.get(item_id, version, namespace=namespace).enabled = True

    def disable(
        self,
        item_id: str,
        version: str,
        *,
        namespace: str | None = None,
    ) -> None:
        """标记停用。不执行业务。"""
        self.get(item_id, version, namespace=namespace).enabled = False

    def clear(self) -> None:
        """清空当前实例。仅用于测试或明确生命周期结束。"""
        self._records.clear()

    def _build_key(
        self,
        item_id: str,
        version: str,
        namespace: str | None,
        *,
        validate: bool = True,
    ) -> RegistryKey:
        """构造 key。空 id / version 视为非法。"""
        normalized_item_id = item_id.strip() if item_id is not None else ""
        normalized_version = version.strip() if version is not None else ""
        if validate and (normalized_item_id == "" or normalized_version == ""):
            raise InvalidRegistryItemError("item_id 与 version 不得为空")
        return RegistryKey(
            item_id=normalized_item_id,
            version=normalized_version,
            namespace=namespace,
        )
