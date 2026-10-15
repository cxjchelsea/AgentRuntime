"""Trusted-application physical StepPort fence for medical sandbox calls.

The wrapper is armed only by the checked application after consuming a signed
Host permit. The raw delegate must remain private to the trusted composition
root. This does not substitute for independent M6/tool-host enforcement.
"""

from __future__ import annotations

from agent_core.domain_extension import DomainExtensionError
from agent_core.runner import Decision, ObservedFact, StepPort
from agent_core.iteration import IterationRef
from runtime.contracts import RuntimeInput


class MedicalAuthorizedStep:
    def __init__(self, delegate: StepPort, *, authorized: bool = False) -> None:
        self._delegate = delegate
        self._authorized = authorized
        self.binding = getattr(delegate, "binding", None)

    async def decide(
        self,
        current_input: RuntimeInput,
        iteration: IterationRef,
        observations: tuple[ObservedFact, ...],
    ) -> Decision:
        if not self._authorized:
            raise DomainExtensionError("medical tool operation is not authorized")
        return await self._delegate.decide(current_input, iteration, observations)

    async def execute_and_observe(self, decision: Decision) -> ObservedFact:
        if not self._authorized:
            raise DomainExtensionError("medical tool operation is not authorized")
        if decision.approved is None or not decision.approved.steps:
            raise DomainExtensionError("medical tool operation lacks approved action")
        return await self._delegate.execute_and_observe(decision)
