"""GA-09 in-process sandbox tool dispatch for a package-owned workflow.

An explicit application-injected handler executes one inert/synthetic tool.
This is NOT an M6 grant, production tool adapter, or external side effect
execution path. Do not register network, filesystem, or mutable host adapters.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from agent_core.domain_execution_catalog import DomainExecutionCatalog
from agent_core.runner import Decision, ObservedFact, RunBoundaryError

SandboxToolHandler = Callable[[str, str], Awaitable[tuple[str, ...]]]


@dataclass(frozen=True, slots=True)
class SandboxToolDispatcher:
    catalog: DomainExecutionCatalog
    handlers: Mapping[str, SandboxToolHandler]

    def __post_init__(self) -> None:
        if type(self.catalog) is not DomainExecutionCatalog:
            raise RunBoundaryError("invalid sandbox execution catalog")
        if (
            type(self.handlers) is not dict
            or set(self.handlers) != set(self.catalog.tool_ids)
            or not all(callable(handler) for handler in self.handlers.values())
        ):
            raise RunBoundaryError("sandbox tool handler registry mismatch")
        # Prevent caller mutations after registration from redirecting dispatch.
        object.__setattr__(self, "handlers", MappingProxyType(dict(self.handlers)))

    async def observe(
        self,
        *,
        decision: Decision,
        step_index: int,
        run_id: str,
        execution_id: str,
    ) -> ObservedFact:
        """Run exactly the declared tool after an already-approved M4 action.

        The AgentRunCoordinator still validates request/run/plan identities,
        enforces timeouts and budgets, and checks this observation's completion.
        """
        if (
            type(step_index) is not int
            or not 0 <= step_index < len(self.catalog.workflow.steps)
            or decision.approved is None
            or len(decision.approved.steps) != 1
            or decision.approved.steps[0].action
            != self.catalog.workflow.steps[step_index].action_id
            or type(run_id) is not str
            or not run_id
            or type(execution_id) is not str
            or not execution_id
        ):
            raise RunBoundaryError("sandbox tool action not in approved workflow")
        workflow_step = self.catalog.workflow.steps[step_index]
        handler = self.handlers[workflow_step.tool_id]
        try:
            facts = await handler(workflow_step.step_id, workflow_step.tool_id)
        except Exception as exc:
            # Preserve cancellation (BaseException) and never leak handler details.
            raise RunBoundaryError("sandbox tool handler failed") from exc
        if (
            type(facts) is not tuple
            or not 1 <= len(facts) <= 8
            or any(type(fact) is not str or not 1 <= len(fact) <= 96 for fact in facts)
            or workflow_step.completion_fact not in facts
        ):
            raise RunBoundaryError("sandbox tool observation incomplete or invalid")
        return ObservedFact(
            run_id=run_id,
            request_id=decision.approved.request_id,
            plan_id=decision.approved.plan_id,
            execution_id=execution_id,
            domain_fingerprint=self.catalog.binding_fingerprint,
            facts=facts,
            workflow_step_id=workflow_step.step_id,
            tool_id=workflow_step.tool_id,
        )
