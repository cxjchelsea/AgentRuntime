"""Registry 内部错误。不得直接作为用户自然语言回复。"""


class RegistryError(Exception):
    """Registry 基础错误。"""


class DuplicateRegistrationError(RegistryError):
    """同一 identifier + version 重复注册。"""


class RegistryItemNotFoundError(RegistryError):
    """查询的注册项不存在。"""


class InvalidRegistryItemError(RegistryError):
    """标识符、版本或定义不合法。"""
