"""GA-01C sandbox-only provenance projector. Not M6 production validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from agent_core.iteration import AgentRunBinding
from agent_core.runner import ObservedFact
from runtime.contracts.context import InteractionContext


class SandboxProjectionError(ValueError):
    """No best-effort projection of unknown or cross-run tool output."""


@dataclass(frozen=True, slots=True)
class SandboxObservationProjector:
    """Domain-configured bounded facts -> model context; ONLY test composition."""

    allowed_facts: Mapping[str, str]

    def project(
        self, binding: AgentRunBinding, observations: tuple[ObservedFact, ...]
    ) -> InteractionContext | None:
        if not observations:
            return None
        seen_executions: set[str] = set()
        for observation in observations:
            if (
                observation.run_id != binding.run_id
                or observation.domain_fingerprint != binding.binding_fingerprint
                or not observation.request_id
                or not observation.plan_id
                or not observation.execution_id
                or observation.execution_id in seen_executions
                or not observation.facts
            ):
                raise SandboxProjectionError("invalid sandbox observation provenance")
            seen_executions.add(observation.execution_id)
            if any(fact not in self.allowed_facts for fact in observation.facts):
                raise SandboxProjectionError("unknown sandbox observation fact")
        latest = observations[-1]
        if len(latest.facts) != 1:
            raise SandboxProjectionError("ambiguous final observation facts")
        return InteractionContext(last_agent_action=self.allowed_facts[latest.facts[0]])
