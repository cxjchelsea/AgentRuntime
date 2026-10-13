"""GA-07 Slice B application bootstrap for an injected, approved sandbox StepPort.

No authorization, model decision, physical action, or knowledge provider is
implicitly fabricated here. M4/M6 checks must be supplied by the application.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from agent_core.domain_execution_catalog import (
    DomainExecutionCatalog,
    WorkflowStepEvidence,
    assemble_execution_catalog,
)
from agent_core.domain_extension import (
    DomainExtension,
    DomainExtensionError,
    assemble_domain_extension,
)
from agent_core.domain_m4_assembly import assemble_domain_m4
from agent_core.domain_package_loader import VerifiedPackageSnapshotV1
from agent_core.iteration import AgentRunBinding
from agent_core.model_adapter import StructuredStrategyTransportAdapter
from agent_core.runner import (
    AgentRunCoordinator,
    Decision,
    LoopBudget,
    ObservedFact,
    RunOutcome,
    StepPort,
)
from runtime.contracts import RuntimeInput


@dataclass(frozen=True, slots=True)
class DomainApplication:
    extension: DomainExtension

    def execution_catalog(
        self, snapshot: VerifiedPackageSnapshotV1
    ) -> DomainExecutionCatalog:
        """Read inert workflow/tool/capability metadata, never grant execution."""
        return assemble_execution_catalog(snapshot, self.extension)

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
        execution_catalog: DomainExecutionCatalog | None = None,
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
        completion_check: Callable[[str, tuple[ObservedFact, ...]], bool] | None = None
        execution_guard: Callable[[Decision, ObservedFact | None, int], bool] | None = None
        if execution_catalog is not None:
            if (
                type(execution_catalog) is not DomainExecutionCatalog
                or execution_catalog.domain_id != binding.domain_id
                or execution_catalog.binding_fingerprint != binding.binding_fingerprint
            ):
                raise DomainExtensionError("execution catalog binding mismatch")

            def evaluate_domain_completion(
                run: str, observations: tuple[ObservedFact, ...]
            ) -> bool:
                # Explicit sandbox correlation; NOT a production attestation.
                steps = execution_catalog.workflow.steps
                if len(observations) != len(steps):
                    return False
                evidence = tuple(
                    WorkflowStepEvidence(observed.workflow_step_id, observed)
                    for observed in observations
                    if observed.workflow_step_id is not None
                )
                if len(evidence) != len(steps):
                    return False
                return execution_catalog.completion_from_observations(
                    run_id=run, observations=evidence
                )

            completion_check = evaluate_domain_completion

            def validate_workflow_execution(
                decision: Decision, observed: ObservedFact | None, index: int
            ) -> bool:
                steps = execution_catalog.workflow.steps
                if index < 0 or index >= len(steps) or decision.approved is None:
                    return False
                workflow_step = steps[index]
                approved_steps = decision.approved.steps
                if (
                    len(approved_steps) != 1
                    or approved_steps[0].action != workflow_step.action_id
                ):
                    return False
                if observed is None:
                    return True
                return (
                    observed.workflow_step_id == workflow_step.step_id
                    and observed.tool_id == workflow_step.tool_id
                    and workflow_step.completion_fact in observed.facts
                )

            execution_guard = validate_workflow_execution

        return await AgentRunCoordinator(
            step, budget, completion_check=completion_check,
            execution_guard=execution_guard
        ).run(initial, binding)


def bootstrap_domain_application(
    snapshot: VerifiedPackageSnapshotV1,
) -> DomainApplication:
    """Accept only GA-02 D2-A snapshot and create a fresh isolated extension."""
    return DomainApplication(assemble_domain_extension(snapshot))
