"""GA-07 Slice B application bootstrap for an injected, approved sandbox StepPort.

No authorization, model decision, physical action, or knowledge provider is
implicitly fabricated here. M4/M6 checks must be supplied by the application.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_core.domain_extension import (
    DomainExtension,
    DomainExtensionError,
    assemble_domain_extension,
)
from agent_core.domain_m4_assembly import assemble_domain_m4
from agent_core.domain_package_loader import VerifiedPackageSnapshotV1
from agent_core.iteration import AgentRunBinding
from agent_core.model_adapter import StructuredStrategyTransportAdapter
from agent_core.runner import AgentRunCoordinator, LoopBudget, RunOutcome, StepPort
from runtime.contracts import RuntimeInput


@dataclass(frozen=True, slots=True)
class DomainApplication:
    extension: DomainExtension

    def m4(self, model: StructuredStrategyTransportAdapter):
        """Create the existing M4 planner/validator/rechecker for this package."""
        return assemble_domain_m4(self.extension, model)

    def prepare(self, initial: RuntimeInput, *, run_id: str) -> AgentRunBinding:
        if type(initial) is not RuntimeInput or type(run_id) is not str or not run_id:
            raise DomainExtensionError("invalid application bootstrap request")
        return self.extension.binding.for_run(initial, run_id=run_id)

    async def run(
        self,
        initial: RuntimeInput,
        *,
        run_id: str,
        step: StepPort,
        budget: LoopBudget,
    ) -> RunOutcome:
        """Execute only an explicitly injected StepPort via the existing Loop.

        The caller is responsible for binding StepPort to this extension's
        registries and to M4 validation/policy enforcement. This bootstrap
        grants NO production execution permission.
        """
        if type(budget) is not LoopBudget:
            raise DomainExtensionError("invalid application loop budget")
        binding = self.prepare(initial, run_id=run_id)
        # An application must not reuse a StepPort assembled for a different
        # domain, run, subject or session, even for a WAIT-only decision.
        step_binding = getattr(step, "binding", None)
        if type(step_binding) is not AgentRunBinding:
            raise DomainExtensionError("unbound application step")
        if step_binding != binding:
            raise DomainExtensionError("application step binding mismatch")
        return await AgentRunCoordinator(step, budget).run(initial, binding)


def bootstrap_domain_application(
    snapshot: VerifiedPackageSnapshotV1,
) -> DomainApplication:
    """Accept only GA-02 D2-A snapshot and create a fresh isolated extension."""
    return DomainApplication(assemble_domain_extension(snapshot))
