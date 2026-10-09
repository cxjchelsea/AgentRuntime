"""M2-IU7 integrated Runtime Orchestrator.

This keeps the frozen 15 call points while evaluating the complete M2 constraint
inside the existing POLICY stage. No new Canonical Contract or top-level stage is
introduced.
"""

from __future__ import annotations

import asyncio
from typing import Any

from runtime.constraint_management import RuntimeConstraint, RuntimeConstraintEvaluator
from runtime.contracts import (
    ActionPlanDraft,
    ApprovedActionPlan,
    ExecutionResult,
    PolicyDecision,
    ResponsePlan,
    RuntimeContext,
    RuntimeInput,
    RuntimeResponse,
    SafetyPhase,
    SafetyResult,
    UnderstandingState,
    UpdateResult,
    ValidatedResult,
)
from runtime.orchestration.context import RuntimeTurnOutcome, TurnExecutionContext
from runtime.orchestration.errors import (
    OrchestrationInvariantError,
    RuntimeOrchestrationError,
    StageExecutionError,
)
from runtime.orchestration.m2_control import (
    AlternatePathRequiredError,
    PreemptionEffectRequiredError,
    PrioritySubjectResolver,
    RuntimeControlBlockedError,
)
from runtime.orchestration.m6_terminalization import finish_turn_once
from runtime.orchestration.runtime import (
    M6DownstreamBlocked,
    M6IntegrationMode,
    RuntimeOrchestrator,
    _assert_denied,
    _gated_validate,
)
from runtime.validation.m6_no_grant_facade import M6NoGrantTurnHandle, TurnOriginSnapshot
from runtime.validation.no_grant_downstream_policy import NoGrantDownstreamDecision
from runtime.orchestration.trace import TraceStatus
from runtime.priority_management import IncomingDisposition


class M2RuntimeOrchestrator(RuntimeOrchestrator):
    """RuntimeOrchestrator with explicit M2 post-understanding control integration.

    The base M0 orchestrator remains unchanged for regression compatibility. This
    integrated runtime path requires an explicit PrioritySubjectResolver and
    RuntimeConstraintEvaluator; it never invents Domain priority mappings.
    """

    def __init__(
        self,
        *,
        runtime_constraint_evaluator: RuntimeConstraintEvaluator,
        priority_subject_resolver: PrioritySubjectResolver,
        **runtime_dependencies: Any,
    ) -> None:
        super().__init__(**runtime_dependencies)
        self.runtime_constraint_evaluator = runtime_constraint_evaluator
        self.priority_subject_resolver = priority_subject_resolver

    async def run(self, runtime_input: RuntimeInput) -> RuntimeTurnOutcome:
        """Execute M2 POLICY with optional per-turn deny-only protection."""
        if self._m6_mode is M6IntegrationMode.LEGACY_TEST_COMPAT:
            return await self._run_m2_pipeline(runtime_input, None, None, None)

        origin = TurnOriginSnapshot.from_runtime_input(runtime_input)
        if self._m6_factory is None:
            raise RuntimeError("G2 facade factory is missing")
        handle = self._m6_factory.open_turn(origin)
        owned_turns: list[TurnExecutionContext] = []
        primary: BaseException | None = None
        try:
            await self._run_m2_pipeline(runtime_input, origin, handle, owned_turns)
            raise M6DownstreamBlocked()
        except BaseException as error:
            primary = error
            if owned_turns:
                turn = owned_turns[0]
                reason = (
                    "TURN_CANCELLED"
                    if isinstance(error, asyncio.CancelledError)
                    else error.error_code
                    if isinstance(error, RuntimeOrchestrationError)
                    else "G2_TURN_FAILURE"
                )
                try:
                    finish_turn_once(
                        turn.trace,
                        TraceStatus.ERROR,
                        reason,
                        primary_exception=error,
                        emit_turn_end=lambda trace: self._emit_log(
                            turn, event="TURN_END", status=trace.status.value
                        ),
                    )
                except Exception:  # noqa: BLE001,S110
                    pass
            raise
        finally:
            try:
                handle.close()
            except Exception as cleanup:
                if primary is None:
                    raise StageExecutionError("M6_CLEANUP", cleanup) from cleanup

    async def _run_m2_pipeline(
        self,
        runtime_input: RuntimeInput,
        origin: TurnOriginSnapshot | None,
        handle: M6NoGrantTurnHandle | None,
        owned_turns: list[TurnExecutionContext] | None,
    ) -> RuntimeTurnOutcome:
        """Preserve M2's 15 stages with two bounded G2 checkpoints."""
        turn_context = self._open_turn(runtime_input)
        if owned_turns is not None:
            owned_turns.append(turn_context)

        processed_input = await self._run_stage(
            turn_context,
            "INPUT",
            self.input_processor.process(runtime_input),
            RuntimeInput,
            input_contract_type="RuntimeInput",
        )

        if origin is not None:
            origin.assert_processed_identity(processed_input)

        early_safety = await self._run_stage(
            turn_context,
            "SAFETY_EARLY",
            self.safety_guard.evaluate_early(processed_input),
            SafetyResult,
            input_contract_type="RuntimeInput",
            invariant_check=lambda safety_result: self._assert_safety_phase(
                safety_result, SafetyPhase.EARLY, "SAFETY_EARLY"
            ),
        )

        runtime_context = await self._run_stage(
            turn_context,
            "CONTEXT",
            self.context_builder.build(processed_input, early_safety),
            RuntimeContext,
            input_contract_type="RuntimeInput",
        )

        understanding_state = await self._run_stage(
            turn_context,
            "UNDERSTANDING",
            self.understanding_engine.understand(processed_input, runtime_context),
            UnderstandingState,
            input_contract_type="RuntimeInput",
        )

        deep_safety = await self._run_stage(
            turn_context,
            "SAFETY_DEEP",
            self.safety_guard.evaluate_deep(
                processed_input,
                runtime_context,
                understanding_state,
                early_safety,
            ),
            SafetyResult,
            input_contract_type="UnderstandingState",
            invariant_check=lambda safety_result: self._assert_safety_phase(
                safety_result, SafetyPhase.DEEP, "SAFETY_DEEP"
            ),
        )

        constraint_box: list[RuntimeConstraint] = []
        policy_decision = await self._run_stage(
            turn_context,
            "POLICY",
            self._evaluate_integrated_policy(
                processed_input,
                runtime_context,
                understanding_state,
                deep_safety,
                constraint_box,
            ),
            PolicyDecision,
            input_contract_type="SafetyResult",
            invariant_check=lambda decision: (
                self._assert_runtime_constraint_allows_flow(
                    constraint_box,
                    processed_input.request_id,
                    decision,
                )
            ),
        )

        action_plan_draft = await self._run_stage(
            turn_context,
            "PLAN",
            self.planner.plan(runtime_context, understanding_state, policy_decision),
            ActionPlanDraft,
            input_contract_type="PolicyDecision",
            invariant_check=lambda draft: self._assert_plan_request_id(
                draft.request_id,
                processed_input.request_id,
                "PLAN",
            ),
        )

        validated_draft = await self._run_stage(
            turn_context,
            "PLAN_VALIDATE",
            self.plan_validator.validate(action_plan_draft),
            ActionPlanDraft,
            input_contract_type="ActionPlanDraft",
            invariant_check=lambda draft: self._assert_plan_request_id(
                draft.request_id,
                processed_input.request_id,
                "PLAN_VALIDATE",
            ),
        )

        approved_action_plan = await self._run_stage(
            turn_context,
            "POLICY_RECHECK",
            self.policy_rechecker.recheck(validated_draft, policy_decision),
            ApprovedActionPlan,
            input_contract_type="ActionPlanDraft",
            invariant_check=lambda plan: self._assert_approved_for_turn(
                plan,
                processed_input.request_id,
            ),
        )

        execution_result = await self._run_stage(
            turn_context,
            "EXECUTE",
            self.execution_engine.execute(approved_action_plan, runtime_context),
            ExecutionResult,
            input_contract_type="ApprovedActionPlan",
        )

        decisions: list[NoGrantDownstreamDecision] = []
        validation = (
            _gated_validate(
                handle, execution_result, runtime_context, approved_action_plan, decisions
            )
            if handle is not None
            else self.result_validator.validate(
                execution_result, runtime_context, approved_action_plan
            )
        )
        validated_result = await self._run_stage(
            turn_context,
            "RESULT_VALIDATE",
            validation,
            ValidatedResult,
            input_contract_type="ExecutionResult",
        )
        if origin is not None:
            _assert_denied(
                decisions, validated_result, execution_result, runtime_context, origin
            )
            raise M6DownstreamBlocked()

        response_plan = await self._run_stage(
            turn_context,
            "RESPONSE_PLAN",
            self.response_planner.plan(
                validated_result,
                runtime_context,
                understanding_state,
                approved_action_plan,
            ),
            ResponsePlan,
            input_contract_type="ValidatedResult",
        )

        generated_response = await self._run_stage(
            turn_context,
            "RESPONSE_GENERATE",
            self.response_generator.generate(response_plan),
            RuntimeResponse,
            input_contract_type="ResponsePlan",
        )

        runtime_response = await self._run_stage(
            turn_context,
            "RESPONSE_VALIDATE",
            self.response_validator.validate(generated_response, validated_result),
            RuntimeResponse,
            input_contract_type="RuntimeResponse",
        )

        update_result = await self._run_stage(
            turn_context,
            "UPDATE",
            self.state_memory_updater.update(
                processed_input,
                runtime_context,
                understanding_state,
                approved_action_plan,
                validated_result,
                runtime_response,
            ),
            UpdateResult,
            input_contract_type="RuntimeResponse",
        )

        self._close_turn(turn_context, TraceStatus.SUCCESS)
        return RuntimeTurnOutcome(
            runtime_response=runtime_response,
            update_result=update_result,
            turn_context=turn_context,
        )

    async def _evaluate_integrated_policy(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        safety_result: SafetyResult,
        constraint_box: list[RuntimeConstraint],
    ) -> PolicyDecision:
        subjects = await self.priority_subject_resolver.resolve(
            runtime_input,
            runtime_context,
            understanding_state,
            safety_result,
        )
        constraint = await self.runtime_constraint_evaluator.evaluate(
            runtime_context=runtime_context,
            understanding_state=understanding_state,
            safety_result=safety_result,
            current_priority_subject=subjects.current,
            incoming_priority_subject=subjects.incoming,
        )
        constraint_box.append(constraint)
        return constraint.policy_decision

    @staticmethod
    def _assert_runtime_constraint_allows_flow(
        constraint_box: list[RuntimeConstraint],
        request_id: str,
        policy_decision: PolicyDecision,
    ) -> None:
        if len(constraint_box) != 1:
            raise OrchestrationInvariantError(
                "POLICY",
                "integrated M2 policy evaluation must produce exactly one RuntimeConstraint",
            )
        constraint = constraint_box[0]
        if constraint.request_id != request_id:
            raise OrchestrationInvariantError(
                "POLICY",
                "RuntimeConstraint.request_id must match current RuntimeInput",
            )
        if constraint.policy_decision != policy_decision:
            raise OrchestrationInvariantError(
                "POLICY",
                "RuntimeConstraint policy decision must match POLICY output",
            )

        if policy_decision.blocked or not policy_decision.allowed:
            if policy_decision.forced_workflow is not None:
                raise AlternatePathRequiredError(policy_decision.forced_workflow)
            raise RuntimeControlBlockedError("POLICY_BLOCKED")

        if constraint.incoming_disposition is not IncomingDisposition.PROCESS_NOW:
            raise RuntimeControlBlockedError(
                f"INCOMING_{constraint.incoming_disposition.value}",
                disposition=constraint.incoming_disposition,
            )

        if (
            constraint.requires_interruption
            and constraint.preemption_decision.current_subject_id is not None
        ):
            raise PreemptionEffectRequiredError()

    @staticmethod
    def _assert_plan_request_id(
        actual_request_id: str,
        expected_request_id: str,
        stage_name: str,
    ) -> None:
        if actual_request_id != expected_request_id:
            raise OrchestrationInvariantError(
                stage_name,
                f"{stage_name} plan request_id must match current RuntimeInput",
            )

    def _assert_approved_for_turn(
        self,
        approved_action_plan: ApprovedActionPlan,
        expected_request_id: str,
    ) -> None:
        self._assert_approved_for_execution(approved_action_plan)
        self._assert_plan_request_id(
            approved_action_plan.request_id,
            expected_request_id,
            "POLICY_RECHECK",
        )
