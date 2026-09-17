"""M2-IU4 injectable PolicyRule boundary."""

from __future__ import annotations

from abc import ABC, abstractmethod

from runtime.contracts import RuntimeContext, SafetyResult, UnderstandingState
from runtime.policy_management.definitions import PolicyFragment


class PolicyRule(ABC):
    """Domain or runtime policy contributor.

    Concrete business policies live outside Core. Rules return partial constraints only;
    they do not execute actions, mutate state, or generate plans.
    """

    @property
    @abstractmethod
    def rule_id(self) -> str:
        """Stable rule identifier."""
        ...

    @abstractmethod
    async def evaluate(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        safety_result: SafetyResult,
    ) -> PolicyFragment | None:
        """Return a partial policy fragment when the rule applies."""
        ...
