"""GA-01C DIAG-03 test-only verified typed planning context construction.

No request goal, unverified tool text, oracle action answer or permission grant
can be smuggled into the typed M4 projection.
"""

from __future__ import annotations

from agent_core.iteration import AgentRunBinding
from agent_core.runner import ObservedFact
from runtime.planning.strategy_selection import PlanningObservationContext
from tests.ga01.initial_evidence import AcceptedInitialEvidence
from tests.ga01.projector import SandboxObservationProjector

_VALID_AVAILABLE = frozenset({"SOURCE_AVAILABLE", "SOURCE_ALREADY_AVAILABLE"})


def from_initial_evidence(
    admitted: AcceptedInitialEvidence | None,
    binding: AgentRunBinding,
) -> PlanningObservationContext:
    if admitted is None:
        return PlanningObservationContext(1, "UNKNOWN", (), (), (), "NONE")
    if (
        admitted.domain_fingerprint != binding.binding_fingerprint
        or admitted.status != "AVAILABLE_UNVERIFIED"
        or admitted.revision < 1
    ):
        raise ValueError("foreign or invalid initial evidence for planning")
    return PlanningObservationContext(
        1,
        "AVAILABLE_UNVERIFIED",
        (f"{admitted.evidence_id}:revision:{admitted.revision}",),
        (),
        ("EVIDENCE_ACCURACY_NOT_YET_VALIDATED",),
        "INITIAL_STATE",
    )


def after_verified_execution(
    binding: AgentRunBinding,
    observations: tuple[ObservedFact, ...],
    projector: SandboxObservationProjector,
    executed_actions: tuple[str, ...],
    initial: PlanningObservationContext,
) -> PlanningObservationContext:
    # Must run the same strict scope/run/execution/fact verification as Slice-2.
    projection = projector.project(binding, observations)
    if (
        projection is None
        or not observations
        or len(executed_actions) < len(observations)
    ):
        raise ValueError("missing verified tool observation/action alignment")
    latest = observations[-1]
    fact = latest.facts[0]
    if fact in _VALID_AVAILABLE:
        state = "AVAILABLE_UNVERIFIED"
        pending: tuple[str, ...] = ("EVIDENCE_ACCURACY_NOT_YET_VALIDATED",)
    elif fact == "GOAL_SATISFIED":
        state = "VERIFIED"
        pending = ()
    elif fact == "VERIFICATION_UNSUPPORTED":
        state = "UNAVAILABLE"
        pending = ("SOURCE_EVIDENCE_REQUIRED",)
    else:
        raise ValueError("unknown execution fact for typed projection")
    source = (
        "INITIAL_AND_EXECUTION"
        if initial.source_scope == "INITIAL_STATE"
        else "EXECUTION"
    )
    return PlanningObservationContext(
        schema_version=1,
        evidence_state=state,
        evidence_refs=(*initial.evidence_refs, latest.execution_id),
        executed_action_ids=tuple(executed_actions[: len(observations)]),
        pending_conditions=pending,
        source_scope=source,
    )
