"""M4 Planning internal errors."""


class PlanningError(RuntimeError):
    """Base error for M4 planning implementation."""


class PlanningBlockedByPolicyError(PlanningError):
    """Raised when M4 is invoked despite a blocking M2 PolicyDecision."""


class PlanningRouteConflictError(PlanningError):
    """Raised when generic planning-route signals conflict."""


class InvalidPlanningRouteRuleError(PlanningError):
    """Raised when an injected PlanningMode rule is malformed."""


class GoalResolutionError(PlanningError):
    """Base error for M4 goal resolution."""


class InvalidGoalCandidateError(GoalResolutionError):
    """Raised when an injected/internal goal candidate is malformed."""


class GoalProviderExecutionError(GoalResolutionError):
    """Raised when an injected goal provider fails."""


class CandidateGenerationError(PlanningError):
    """Base error for legal M4 action candidate generation."""


class InvalidActionCandidateError(CandidateGenerationError):
    """Raised when a candidate is malformed or references an illegal action."""


class ActionRegistryAmbiguityError(CandidateGenerationError):
    """Raised when one action_id has multiple enabled registry versions."""


class CandidateEligibilityError(CandidateGenerationError):
    """Raised when an injected eligibility rule fails."""


class StrategySelectionError(PlanningError):
    """Base error for M4 strategy selection."""


class StrategyRegistryAmbiguityError(StrategySelectionError):
    """Raised when one strategy_id has multiple enabled registry versions."""


class InvalidStrategySelectionError(StrategySelectionError):
    """Raised when a rule/model chooses outside the legal strategy/action space."""


class StrategyRuleExecutionError(StrategySelectionError):
    """Raised when an injected deterministic strategy rule fails."""


class StrategyModelBoundaryError(StrategySelectionError):
    """Base error for the optional soft-selection model boundary."""


class StrategyModelUnavailableError(StrategyModelBoundaryError):
    """Raised when model selection is requested without a configured model."""


class StrategyModelExecutionError(StrategyModelBoundaryError):
    """Raised when the strategy model fails during inference."""


class StrategyModelOutputError(StrategyModelBoundaryError):
    """Raised when model output violates the frozen legal-choice boundary."""


class KnowledgePlanningError(PlanningError):
    """Base error for M4 Knowledge Planning."""


class KnowledgeNeedResolutionError(KnowledgePlanningError):
    """Raised when knowledge need cannot be resolved safely."""


class KnowledgeNeedRuleExecutionError(KnowledgeNeedResolutionError):
    """Raised when an injected knowledge-need rule fails."""


class KnowledgeDomainRoutingError(KnowledgePlanningError):
    """Raised when a required knowledge domain cannot be resolved."""


class KnowledgeDomainRuleExecutionError(KnowledgeDomainRoutingError):
    """Raised when an injected knowledge-domain rule fails."""


class RetrievalQueryBuildError(KnowledgePlanningError):
    """Raised when a valid RetrievalQuery cannot be constructed."""


class QueryRewriteError(RetrievalQueryBuildError):
    """Raised when query rewrite violates the bounded rewrite contract."""


class RetrievalPlanningError(KnowledgePlanningError):
    """Raised when RetrievalPlan cannot be produced from supported capabilities."""


class RetrievalModeRuleExecutionError(RetrievalPlanningError):
    """Raised when an injected retrieval-mode rule fails."""


class EvidenceRequirementPlanningError(KnowledgePlanningError):
    """Raised when EvidenceRequirement cannot be resolved."""


class EvidenceRequirementRuleExecutionError(EvidenceRequirementPlanningError):
    """Raised when an injected evidence-requirement rule fails."""


class ExecutionPreplanningError(PlanningError):
    """Base error for M4-IU5 execution-preplanning decisions."""


class MemoryUsagePlanningError(ExecutionPreplanningError):
    """Raised when memory-usage planning cannot be resolved safely."""


class CapabilityPlanningError(ExecutionPreplanningError):
    """Raised when selected actions cannot be mapped to legal capabilities."""


class ToolPlanningError(ExecutionPreplanningError):
    """Raised when required tools cannot be planned legally."""


class SequencePlanningError(ExecutionPreplanningError):
    """Raised when a valid action sequence cannot be constructed."""


class ConfirmationPlanningError(ExecutionPreplanningError):
    """Raised when confirmation requirements are inconsistent."""


class FallbackPlanningError(ExecutionPreplanningError):
    """Raised when fallback planning is invalid or unsafe."""


class DraftAssemblyError(PlanningError):
    """Raised when M4-IU6 cannot assemble a valid ActionPlanDraft shape."""


class ResponseStrategyPlanningError(DraftAssemblyError):
    """Raised when response-strategy planning is conflicting or malformed."""


class PlanValidationError(PlanningError):
    """Raised when ActionPlanDraft fails structural/registry/capability validation."""
