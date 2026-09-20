"""M4-IU8 concrete Planner + Runtime integration adapters.

This module wires IU2-IU7 into the frozen Runtime planning interfaces. It does not add
new top-level Runtime stages and does not execute M5 capabilities.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from runtime.contracts import (
    ActionPlanDraft,
    ApprovedActionPlan,
    PolicyDecision,
    RuntimeContext,
    UnderstandingState,
)
from runtime.interfaces.planning import (
    Planner,
    PlanValidator as PlanValidatorInterface,
    PolicyRechecker,
)
from runtime.planning.candidates import LegalActionCandidateBuilder
from runtime.planning.draft_validation import (
    ActionPlanDraftAssembler,
    PlanValidationContext,
    PlanValidationResult,
    PlanValidator,
    ResponseStrategyBuilder,
)
from runtime.planning.errors import (
    CapabilityContextError,
    PlanIdGenerationError,
    ValidationReceiptError,
)
from runtime.planning.execution_preplanning import ExecutionPreplanner
from runtime.planning.goals import GoalResolver
from runtime.planning.knowledge_planning import (
    KnowledgeCapabilityContext,
    KnowledgePlanner,
)
from runtime.planning.policy_approval import PlanApprovalCoordinator
from runtime.planning.routing import PlanningModeRouter
from runtime.planning.strategy_selection import HybridStrategySelector
from runtime.registries import CapabilityRegistry


class CapabilityIdResolver:
    """Project enabled CapabilityRegistry entries into an unambiguous ID set."""

    def __init__(self, capability_registry: CapabilityRegistry) -> None:
        self._capability_registry = capability_registry

    def resolve(self) -> frozenset[str]:
        seen: set[str] = set()
        for record in self._capability_registry.list():
            if not record.enabled:
                continue
            capability_id = record.definition.capability_id
            if capability_id in seen:
                raise CapabilityContextError(
                    "multiple enabled versions exist for one capability_id"
                )
            seen.add(capability_id)
        return frozenset(seen)


class DefaultM4Planner(Planner):
    """Concrete M4 planner composed from the already-verified IU2-IU6 units."""

    def __init__(
        self,
        *,
        mode_router: PlanningModeRouter,
        goal_resolver: GoalResolver,
        candidate_builder: LegalActionCandidateBuilder,
        strategy_selector: HybridStrategySelector,
        knowledge_planner: KnowledgePlanner,
        execution_preplanner: ExecutionPreplanner,
        response_strategy_builder: ResponseStrategyBuilder,
        draft_assembler: ActionPlanDraftAssembler,
        capability_id_resolver: CapabilityIdResolver,
        knowledge_capability_context: KnowledgeCapabilityContext,
        plan_id_factory: Callable[[str], str] | None = None,
    ) -> None:
        self._mode_router = mode_router
        self._goal_resolver = goal_resolver
        self._candidate_builder = candidate_builder
        self._strategy_selector = strategy_selector
        self._knowledge_planner = knowledge_planner
        self._execution_preplanner = execution_preplanner
        self._response_strategy_builder = response_strategy_builder
        self._draft_assembler = draft_assembler
        self._capability_id_resolver = capability_id_resolver
        self._knowledge_capability_context = knowledge_capability_context
        self._plan_id_factory = plan_id_factory or self._default_plan_id

    async def plan(
        self,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        policy_decision: PolicyDecision,
    ) -> ActionPlanDraft:
        route = self._mode_router.route(
            runtime_context,
            understanding_state,
            policy_decision,
        )
        goals = self._goal_resolver.resolve(
            runtime_context,
            understanding_state,
            policy_decision,
        )
        available_capability_ids = self._capability_id_resolver.resolve()

        candidates = self._candidate_builder.build(
            runtime_context,
            understanding_state,
            goals,
            policy_decision,
            planning_mode=route.mode,
            available_capability_ids=available_capability_ids,
        )
        strategy = await self._strategy_selector.select(
            planning_mode=route.mode,
            runtime_context=runtime_context,
            understanding_state=understanding_state,
            goals=goals,
            candidates=candidates,
            policy_decision=policy_decision,
            available_capability_ids=available_capability_ids,
        )

        knowledge = await self._knowledge_planner.plan(
            runtime_context=runtime_context,
            understanding_state=understanding_state,
            goals=goals,
            strategy=strategy,
            candidates=candidates,
            policy_decision=policy_decision,
            capability_context=self._knowledge_capability_context,
        )

        completion_conditions = tuple(
            goal.completion_condition
            for goal in (
                *((goals.primary_goal,) if goals.primary_goal is not None else ()),
                *goals.secondary_goals,
            )
            if goal.completion_condition is not None
            and goal.completion_condition.strip()
        )
        preplanning = self._execution_preplanner.plan(
            selected_action_ids=strategy.selected_action_ids,
            runtime_context=runtime_context,
            policy_decision=policy_decision,
            goal_completion_conditions=completion_conditions,
        )
        response_strategy = self._response_strategy_builder.build(
            strategy,
            preplanning,
            knowledge,
        )

        request_id = understanding_state.metadata.request_id
        plan_id = self._plan_id_factory(request_id)
        if not isinstance(plan_id, str) or not plan_id.strip():
            raise PlanIdGenerationError(
                "plan_id_factory must return a non-blank string"
            )

        return self._draft_assembler.build(
            plan_id=plan_id,
            request_id=request_id,
            planning_mode=route.mode,
            goals=goals,
            strategy=strategy,
            knowledge_planning=knowledge,
            execution_preplanning=preplanning,
            response_strategy=response_strategy,
        )

    @staticmethod
    def _default_plan_id(request_id: str) -> str:
        del request_id
        return f"plan-{uuid.uuid4().hex}"


@dataclass(frozen=True, slots=True)
class ValidationReceipt:
    """Internal one-shot proof that the exact Draft passed IU6 validation."""

    plan_id: str
    request_id: str
    fingerprint: str
    validation_codes: tuple[str, ...]


class ValidationReceiptLedger:
    """Turn-local integration ledger bridging the frozen validator/rechecker APIs.

    The frozen PlanValidator interface returns ActionPlanDraft rather than a validation
    receipt. This ledger carries only an integrity fingerprint + audit codes. It never
    stores Domain state, user memory, tool results, or approval authority.
    """

    def __init__(self) -> None:
        self._receipts: dict[tuple[str, str], ValidationReceipt] = {}

    def record(self, result: PlanValidationResult) -> None:
        draft = result.draft
        key = (draft.plan_id, draft.request_id)
        if key in self._receipts:
            raise ValidationReceiptError(
                "duplicate unconsumed validation receipt for plan/request"
            )
        self._receipts[key] = ValidationReceipt(
            plan_id=draft.plan_id,
            request_id=draft.request_id,
            fingerprint=self.fingerprint(draft),
            validation_codes=result.validation_codes,
        )

    def claim(self, draft: ActionPlanDraft) -> ValidationReceipt:
        key = (draft.plan_id, draft.request_id)
        receipt = self._receipts.pop(key, None)
        if receipt is None:
            raise ValidationReceiptError(
                "POLICY_RECHECK requires a prior PLAN_VALIDATE receipt"
            )
        if receipt.fingerprint != self.fingerprint(draft):
            raise ValidationReceiptError(
                "ActionPlanDraft changed after PLAN_VALIDATE"
            )
        return receipt

    def pending_count(self) -> int:
        return len(self._receipts)

    @staticmethod
    def fingerprint(draft: ActionPlanDraft) -> str:
        payload = draft.model_dump(mode="json")
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class RuntimePlanValidatorAdapter(PlanValidatorInterface):
    """Adapt IU6 PlanValidator to the frozen Runtime PlanValidator interface."""

    def __init__(
        self,
        *,
        validator: PlanValidator,
        validation_context: PlanValidationContext,
        receipt_ledger: ValidationReceiptLedger,
    ) -> None:
        self._validator = validator
        self._validation_context = validation_context
        self._receipt_ledger = receipt_ledger

    async def validate(
        self,
        action_plan_draft: ActionPlanDraft,
    ) -> ActionPlanDraft:
        result = self._validator.validate(
            action_plan_draft,
            self._validation_context,
        )
        self._receipt_ledger.record(result)
        return result.draft


class RuntimePolicyRecheckerAdapter(PolicyRechecker):
    """Bridge Runtime POLICY_RECHECK to IU7 coordinator + frozen M2 rechecker."""

    def __init__(
        self,
        *,
        approval_coordinator: PlanApprovalCoordinator,
        receipt_ledger: ValidationReceiptLedger,
    ) -> None:
        self._approval_coordinator = approval_coordinator
        self._receipt_ledger = receipt_ledger

    async def recheck(
        self,
        action_plan_draft: ActionPlanDraft,
        policy_decision: PolicyDecision,
    ) -> ApprovedActionPlan:
        receipt = self._receipt_ledger.claim(action_plan_draft)
        validated = PlanValidationResult(
            draft=action_plan_draft,
            validation_codes=receipt.validation_codes,
        )
        result = await self._approval_coordinator.approve(
            validated,
            policy_decision,
        )
        return result.approved_plan
