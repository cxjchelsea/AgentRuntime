"""Application-owned synthetic medical safety preflight; no clinical triage claim.

Host supplies an explicit scoped policy. Matching marks a *requested* human
handoff; it does not send messages or attest a successful handoff.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from agent_core.domain_extension import DomainExtensionError
from agent_core.domain_unified_application import UnifiedDomainApplication
from agent_core.medical_execution_authority import (
    MedicalExecutionAuthority,
    MedicalSafetyDecisionSigner,
)
from agent_core.runner import LoopBudget, RunKind, RunOutcome, StepPort
from runtime.contracts import RuntimeInput


@dataclass(frozen=True, slots=True)
class MedicalPreflightPolicy:
    domain_id: str
    binding_fingerprint: str
    escalation_phrases: tuple[str, ...]
    policy_version: str = "synthetic-v1"

    def __post_init__(self) -> None:
        if (
            not self.domain_id.startswith("medical.")
            or not self.policy_version
            or not re.fullmatch(r"[0-9a-f]{64}", self.binding_fingerprint)
            or not self.escalation_phrases
            or len(self.escalation_phrases) > 16
            or any(
                type(term) is not str
                or not 3 <= len(term) <= 100
                or term != term.strip()
                or term != term.casefold()
                for term in self.escalation_phrases
            )
            or len(set(self.escalation_phrases)) != len(self.escalation_phrases)
        ):
            raise DomainExtensionError("invalid medical preflight policy")

    def requires_human(self, text: str) -> bool:
        normalized = " ".join(text.casefold().split())
        return any(term in normalized for term in self.escalation_phrases)


@dataclass(frozen=True, slots=True)
class MedicalSafetyApplication:
    unified: UnifiedDomainApplication
    preflight: MedicalPreflightPolicy
    authority: MedicalExecutionAuthority | None = None
    decision_signer: MedicalSafetyDecisionSigner | None = None

    def __post_init__(self) -> None:
        binding = self.unified.app.extension.binding
        if (
            binding.domain_id != self.preflight.domain_id
            or binding.binding_fingerprint != self.preflight.binding_fingerprint
            or (
                self.decision_signer is not None
                and self.decision_signer.rejected_phrases
                != self.preflight.escalation_phrases
            )
        ):
            raise DomainExtensionError("medical safety policy binding mismatch")

    async def run(
        self,
        initial: RuntimeInput,
        *,
        run_id: str,
        step: StepPort,
        budget: LoopBudget,
    ) -> RunOutcome:
        # No provider, M4, knowledge retrieval, or tools before this branch.
        # Missing/unsupported input is not treated as safe.
        if type(initial) is not RuntimeInput or not initial.text:
            return RunOutcome(
                run_id, RunKind.BLOCK, "MEDICAL_SAFETY_INPUT_UNAVAILABLE", 0, 0, ()
            )
        if self.preflight.requires_human(initial.text):
            return RunOutcome(
                run_id, RunKind.BLOCK, "MEDICAL_HUMAN_REVIEW_REQUIRED", 0, 0, ()
            )
        if self.authority is None or self.decision_signer is None:
            raise DomainExtensionError("medical execution authority unavailable")
        clearance = self.decision_signer.approve(
            initial=initial,
            run_id=run_id,
            domain_id=self.preflight.domain_id,
            binding_fingerprint=self.preflight.binding_fingerprint,
            policy_version=self.preflight.policy_version,
        )
        permit = self.authority.issue(
            initial=initial,
            run_id=run_id,
            domain_id=self.preflight.domain_id,
            binding_fingerprint=self.preflight.binding_fingerprint,
            policy_version=self.preflight.policy_version,
            clearance=clearance,
        )
        return await self.unified._run_checked(
            initial,
            run_id=run_id,
            step=step,
            budget=budget,
            medical_authority=self.authority,
            medical_permit=permit,
            medical_policy_version=self.preflight.policy_version,
        )
