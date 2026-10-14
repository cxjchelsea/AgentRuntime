"""GA-20 application-owned sandbox StepPort. Not a production M6 grant.

Uses the existing M1 normalization, M2 safety/policy/constraints, M3
understanding contract, and M4 planner/validator/rechecker. Only a pinned
read-only GA-09 dispatcher can execute steps. No tests imports.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from agent_core.domain_application import DomainApplication
from agent_core.domain_execution_catalog import WorkflowStepEvidence
from agent_core.iteration import AgentRunBinding, IterationRef
from agent_core.runner import Decision, ObservedFact, RunBoundaryError
from agent_core.sandbox_tool_dispatch import SandboxToolDispatcher
from runtime.constraint_management import RuntimeConstraintEvaluator
from runtime.contracts import (
    CoreControlIntent,
    DomainExtensions,
    IdentityContext,
    IdentityStatus,
    IntentEvidenceSource,
    IntentResult,
    QualityAssessment,
    RuntimeContext,
    RuntimeControlState,
    RuntimeInput,
    RuntimeStateContext,
    SessionContext,
    UnderstandingMetadata,
    UnderstandingState,
)
from runtime.contracts.context import InteractionContext, ToolContext
from runtime.contracts.enums import ProcessingPath
from runtime.contracts.understanding import GoalUnderstanding, UncertaintyAssessment
from runtime.input_processing import DefaultInputProcessor
from runtime.interfaces.planning import Planner, PlanValidator, PolicyRechecker
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
    executed: int = 0
    binding: AgentRunBinding = field(init=False)

    def __post_init__(self) -> None:
        self.binding = self.app.prepare(self.initial, run_id=self.run_id)
        if self.dispatcher.catalog.binding_fingerprint != self.binding.binding_fingerprint:
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
        understanding = UnderstandingState(
            metadata=UnderstandingMetadata(
                understanding_id="ga20-understanding-" + iteration.request_id,
                request_id=normalized.request_id,
                timestamp=datetime.now(UTC),
                processing_path=ProcessingPath.FAST_PATH,
            ),
            intents=[
                IntentResult(
                    intent_id=CoreControlIntent.UNKNOWN.value,
                    confidence=0.0,
                    source=IntentEvidenceSource.RULE,
                )
            ],
            uncertainty=UncertaintyAssessment(),
            quality=QualityAssessment(),
            goal=GoalUnderstanding(explicit_goal="DOMAIN_GOAL", confidence=1.0),
        )
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
            if not self.dispatcher.catalog.completion_from_observations(
                run_id=self.run_id,
                observations=tuple(
                    WorkflowStepEvidence(
                        observed.workflow_step_id, observed
                    )
                    for observed in observations
                ),
            ):
                raise RunBoundaryError("unverified final business observation")
            return Decision(
                iteration, "FINISH", reason="VERIFIED_READ_ONLY_GOAL",
                completion_fact=observations[-1].facts[-1],
            )
        draft = await self.planner.plan(
            context, understanding, constraint.policy_decision
        )
        draft = draft.model_copy(update={"plan_id": "ga20-" + iteration.request_id})
        validated = await self.validator.validate(draft)
        approved = await self.rechecker.recheck(
            validated, constraint.policy_decision
        )
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
