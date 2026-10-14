"""GA-20 application-owned sandbox StepPort. Not a production M6 grant.

Uses the existing M1 normalization, M2 safety/policy/constraints, M3
understanding contract, and M4 planner/validator/rechecker. Only a pinned
read-only GA-09 dispatcher can execute steps. No tests imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent_core.domain_application import DomainApplication
from agent_core.domain_execution_catalog import WorkflowStepEvidence
from agent_core.iteration import AgentRunBinding, IterationRef
from agent_core.runner import Decision, ObservedFact, RunBoundaryError
from agent_core.sandbox_tool_dispatch import SandboxToolDispatcher
from runtime.constraint_management import RuntimeConstraintEvaluator
from runtime.contracts import (
    DomainExtensions,
    IdentityContext,
    IdentityStatus,
    RuntimeContext,
    RuntimeControlState,
    RuntimeInput,
    RuntimeStateContext,
    SessionContext,
)
from runtime.contracts.context import InteractionContext, ToolContext
from runtime.input_processing import DefaultInputProcessor
from runtime.interfaces.planning import Planner, PlanValidator, PolicyRechecker
from runtime.interfaces.understanding import UnderstandingEngine
from runtime.orchestration.m2_admission import assert_admission_allows_flow
from runtime.policy_management import DefaultPolicyEngine
from runtime.priority_management import PreemptionEngine, PrioritySubject
from runtime.safety import DefaultSafetyGuard


@dataclass
class ReadOnlyApplicationStep:
    initial: RuntimeInput
    run_id: str
    app: DomainApplication
    dispatcher: SandboxToolDispatcher
    planner: Planner
    validator: PlanValidator
    rechecker: PolicyRechecker
    understanding_engine: UnderstandingEngine
    executed: int = 0
    binding: AgentRunBinding = field(init=False)

    def __post_init__(self) -> None:
        self.binding = self.app.prepare(self.initial, run_id=self.run_id)
        if (
            self.dispatcher.catalog.binding_fingerprint
            != self.binding.binding_fingerprint
        ):
            raise RunBoundaryError("application dispatcher binding mismatch")
        # M2 is explicitly configured with no preemption of another task and
        # no silent priority bypass. This local sandbox supports one task only.
        self._safety = DefaultSafetyGuard(rules=[])
        self._constraints = RuntimeConstraintEvaluator(
            policy_engine=DefaultPolicyEngine(rules=[]),
            preemption_engine=PreemptionEngine(rules=[]),
        )

    async def decide(
        self,
        current_input: RuntimeInput,
        iteration: IterationRef,
        observations: tuple[ObservedFact, ...],
    ) -> Decision:
        self.binding.assert_identity(current_input)
        normalized = await DefaultInputProcessor().process(current_input)
        early = await self._safety.evaluate_early(normalized)
        context = RuntimeContext(
            identity_context=IdentityContext(
                subject_id=normalized.subject_id,
                identity_scope=normalized.identity_scope,
                identity_status=IdentityStatus.BOUND,
                tenant_id=normalized.tenant_id,
            ),
            session_context=SessionContext(session_id=normalized.session_id),
            runtime_state_context=RuntimeStateContext(
                current_state=RuntimeControlState.PROCESSING,
                previous_state=None,
                interruptible=True,
                entered_at=normalized.timestamp,
            ),
            domain_extensions=DomainExtensions(domain_id=self.binding.domain_id),
            tool_context=ToolContext(
                recent_tool_results=[
                    {"fact": fact}
                    for observation in observations
                    for fact in observation.facts
                ],
            ),
            interaction_context=InteractionContext(
                last_agent_action=observations[-1].facts[-1] if observations else None,
            ),
        )
        # Subsequent Agent iterations are SYSTEM events without user text.
        # M3 interprets the original user task without forging a new user event.
        interpretation_input = self.initial.model_copy(
            update={
                "request_id": normalized.request_id,
                "trace_id": normalized.trace_id,
            },
        )
        understanding = await self.understanding_engine.understand(
            interpretation_input, context
        )
        if (
            understanding.metadata.request_id != normalized.request_id
            or not understanding.intents
            or understanding.uncertainty.needs_clarification is True
        ):
            raise RunBoundaryError("application M3 understanding not admitted")
        deep = await self._safety.evaluate_deep(
            normalized, context, understanding, early
        )
        constraint = await self._constraints.evaluate(
            runtime_context=context,
            understanding_state=understanding,
            safety_result=deep,
            current_priority_subject=None,
            incoming_priority_subject=PrioritySubject(
                subject_id=normalized.subject_id,
                kind="GA20_READ_ONLY",
                priority=50,
                source="APPLICATION",
            ),
        )
        assert_admission_allows_flow(
            constraint=constraint,
            request_id=normalized.request_id,
            policy_decision=constraint.policy_decision,
        )
        if len(observations) == len(self.dispatcher.catalog.workflow.steps):
            if any(observed.workflow_step_id is None for observed in observations):
                raise RunBoundaryError("missing application step provenance")
            if not self.dispatcher.catalog.completion_from_observations(
                run_id=self.run_id,
                observations=tuple(
                    WorkflowStepEvidence(observed.workflow_step_id, observed)
                    for observed in observations
                    if observed.workflow_step_id is not None
                ),
            ):
                raise RunBoundaryError("unverified final business observation")
            return Decision(
                iteration,
                "FINISH",
                reason="VERIFIED_READ_ONLY_GOAL",
                completion_fact=observations[-1].facts[-1],
            )
        draft = await self.planner.plan(
            context, understanding, constraint.policy_decision
        )
        draft = draft.model_copy(update={"plan_id": "ga20-" + iteration.request_id})
        validated = await self.validator.validate(draft)
        approved = await self.rechecker.recheck(validated, constraint.policy_decision)
        return Decision(iteration, "ACT", context=context, approved=approved)

    async def execute_and_observe(self, decision: Decision) -> ObservedFact:
        # The existing dispatcher rejects mismatched action / step / tool.
        # Increment once, before await: no retry of an uncertain tool outcome.
        index = self.executed
        self.executed += 1
        return await self.dispatcher.observe(
            decision=decision,
            step_index=index,
            run_id=self.run_id,
            execution_id=f"ga20-execution-{index + 1}",
        )
