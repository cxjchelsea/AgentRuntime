"""M2-IU7 internal orchestration control boundaries.

These types are internal-only. They do not add Canonical Contracts or change the
frozen M0-M2 module interfaces.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from runtime.contracts import (
    RuntimeContext,
    RuntimeInput,
    SafetyResult,
    UnderstandingState,
)
from runtime.orchestration.errors import RuntimeOrchestrationError
from runtime.priority_management import IncomingDisposition, PrioritySubject


@dataclass(frozen=True, slots=True)
class ResolvedPrioritySubjects:
    """Priority subjects explicitly resolved by an injected Domain/application adapter."""

    current: PrioritySubject | None
    incoming: PrioritySubject


class PrioritySubjectResolver(ABC):
    """Resolve runtime facts to generic priority subjects without Core hardcoding.

    Implementations may use Domain configuration, but Runtime Core never infers
    business priority kinds or numeric values from text, intents, or safety labels.
    """

    @abstractmethod
    async def resolve(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        safety_result: SafetyResult,
    ) -> ResolvedPrioritySubjects:
        """Return current/incoming subjects for the current turn."""
        ...


class RuntimeControlBlockedError(RuntimeOrchestrationError):
    """Ordinary Agent flow must not continue under an M2 hard control decision."""

    def __init__(
        self,
        reason_code: str,
        *,
        disposition: IncomingDisposition | None = None,
        stage_name: str = "POLICY",
    ) -> None:
        super().__init__(
            "M2 runtime control gate blocked ordinary Agent flow",
            error_code="RUNTIME_CONTROL_BLOCKED",
            stage_name=stage_name,
        )
        self.reason_code = reason_code
        self.disposition = disposition


class AlternatePathRequiredError(RuntimeOrchestrationError):
    """A forced workflow is required, but the ordinary Planner path is not allowed."""

    def __init__(self, forced_workflow: str, *, stage_name: str = "POLICY") -> None:
        super().__init__(
            "M2 requires a forced alternate workflow path",
            error_code="ALTERNATE_PATH_REQUIRED",
            stage_name=stage_name,
        )
        self.forced_workflow = forced_workflow


class PreemptionEffectRequiredError(RuntimeOrchestrationError):
    """A current activity must be interrupted before incoming work can proceed."""

    def __init__(self) -> None:
        super().__init__(
            "M2 requires preemption side effects before ordinary Agent flow can continue",
            error_code="PREEMPTION_EFFECT_REQUIRED",
            stage_name="POLICY",
        )
