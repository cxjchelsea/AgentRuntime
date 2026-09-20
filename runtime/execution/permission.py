"""M5 execution-permission contracts.

Planning authorization and execution permission are intentionally distinct:
- M2/M4 decide whether a Tool may appear in an approved plan.
- M5 checks whether the current execution subject/environment still satisfies
  ToolDefinition.required_permissions before invocation.

This module defines the contract only. It does not resolve roles, devices, bindings,
or Domain-specific permission facts by itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from runtime.contracts.execution import ExecutionContext
from runtime.registries.definitions import ToolDefinition


class PermissionDecisionStatus(str, Enum):
    ALLOWED = "ALLOWED"
    DENIED = "DENIED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ExecutionPermissionContext:
    execution_id: str
    identity_scope: str
    granted_permissions: frozenset[str] = frozenset()
    denied_permissions: frozenset[str] = frozenset()
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.execution_id.strip() or not self.identity_scope.strip():
            raise ValueError("execution_id and identity_scope must not be blank")
        if self.granted_permissions & self.denied_permissions:
            raise ValueError(
                "one permission cannot be both granted and denied"
            )
        if any(not value.strip() for value in self.granted_permissions):
            raise ValueError("granted_permissions must not contain blank values")
        if any(not value.strip() for value in self.denied_permissions):
            raise ValueError("denied_permissions must not contain blank values")
        if any(not ref.strip() for ref in self.evidence_refs):
            raise ValueError("evidence_refs must not contain blank values")


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    status: PermissionDecisionStatus
    reason_codes: tuple[str, ...]
    missing_permissions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.reason_codes or any(
            not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain non-blank values")
        if any(not value.strip() for value in self.missing_permissions):
            raise ValueError(
                "missing_permissions must not contain blank values"
            )
        if (
            self.status is PermissionDecisionStatus.ALLOWED
            and self.missing_permissions
        ):
            raise ValueError(
                "ALLOWED permission decision cannot carry missing_permissions"
            )


class ExecutionPermissionContextProvider(Protocol):
    async def build(
        self,
        execution_context: ExecutionContext,
    ) -> ExecutionPermissionContext:
        """Project current binding/device/environment/role facts for execution."""


class ExecutionPermissionEvaluator(Protocol):
    def evaluate(
        self,
        tool_definition: ToolDefinition,
        permission_context: ExecutionPermissionContext,
    ) -> PermissionDecision:
        """Evaluate current execution permission without changing the approved plan."""
