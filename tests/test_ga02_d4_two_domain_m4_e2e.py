"""GA-02 D3/D4: two genuinely different package-owned M4 decisions, one Core.

Everything is sandbox-only: real D2-A loader, real M2/M4 gate and Loop;
no C1 issuer, production M6 positive grant, physical tool, or DB.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from agent_core.domain_package_loader import (
    HostPackageRootIssuer,
    HostPublishedGeneration,
    LocalPackageLoader,
    TrustedPackageIdentity,
)
from agent_core.model_adapter import StructuredStrategyTransportAdapter
from agent_core.runner import (
    AgentRunCoordinator,
    Decision,
    LoopBudget,
    ObservedFact,
    RunKind,
)
from agent_core.sandbox_domain_assembly import (
    SandboxAssemblyError,
    assemble_sandbox_domain,
)
from runtime.planning import (
    ActionPlanDraftAssembler,
    CapabilityIdResolver,
    CapabilityPlanner,
    ConfirmationPlanner,
    DefaultM4Planner,
    EvidenceRequirementPlanner,
    ExecutionPreplanner,
    FallbackPlanner,
    GoalResolver,
    HybridStrategySelector,
    KnowledgeCapabilityContext,
    KnowledgeDomainRouter,
    KnowledgeNeedResolver,
    KnowledgePlanner,
    LegalActionCandidateBuilder,
    MemoryUsagePlanner,
    PlanApprovalCoordinator,
    PlanningModeRouter,
    PlanValidationContext,
    PlanValidator,
    ResponseStrategyBuilder,
    RetrievalPlanner,
    RetrievalQueryBuilder,
    RuntimePlanValidatorAdapter,
    RuntimePolicyRecheckerAdapter,
    SelectedActionResolver,
    SequencePlanner,
    ToolPlanner,
    ValidationReceiptLedger,
)
from runtime.policy_enforcement import DefaultPolicyRechecker
from runtime.registries import CapabilityRegistry, ToolRegistry, WorkflowRegistry
from tests.ga02_d4_domain_m4_assembly import SandboxM4Domain, assemble_sandbox_m4
from tests.orchestration_stubs import build_runtime_input
from tests.test_ga01_slice1 import SandboxTurn
from tests.test_ga01_slice2_loop import ModelDrivenSandboxTurn

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="actual D2-A FD package loader is Linux-only",
)


def _package(tmp_path: Path, domain: str, noun: str) -> TrustedPackageIdentity:
    assets: list[dict[str, str]] = []
    names = {"collect": f"collect-{noun}", "verify": f"verify-{noun}"}
    for role, name in names.items():
        data = {"role": role, "description": f"{role} synthetic {noun}"}
        relative = f"actions/{name}.json"
        contents = json.dumps(data, sort_keys=True).encode()
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents)
        assets.append(
            {
                "kind": "action",
                "namespace": domain,
                "id": name,
                "version": "1.0.0",
                "sha256": hashlib.sha256(contents).hexdigest(),
                "relative_path": relative,
            }
        )
        sid = f"{role}-strategy-{noun}"
        relative = f"strategies/{sid}.json"
        contents = json.dumps(
            {"role": role, "action_id": name}, sort_keys=True
        ).encode()
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents)
        assets.append(
            {
                "kind": "strategy",
                "namespace": domain,
                "id": sid,
                "version": "1.0.0",
                "sha256": hashlib.sha256(contents).hexdigest(),
                "relative_path": relative,
            }
        )
    assets.sort(
        key=lambda a: (
            a["kind"],
            a["namespace"],
            a["id"],
            a["version"],
            a["relative_path"],
        )
    )
    manifest: dict[str, Any] = {
        "asset_refs": assets,
        "domain_id": domain,
        "domain_version": "1.0.0",
        "enabled": True,
        "name": f"Synthetic {noun}",
        "package_schema_version": "1",
        "runtime_compatibility": "GA02-D1-1",
    }
    digest = hashlib.sha256(
        json.dumps(
            manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    manifest["manifest_digest"] = digest
    (tmp_path / "package.json").write_bytes(json.dumps(manifest).encode())
    return TrustedPackageIdentity("sandbox-gen-1", domain, "1.0.0", "GA02-D1-1", digest)


def _load(tmp_path: Path, domain: str, noun: str) -> SandboxM4Domain:
    identity = _package(tmp_path, domain, noun)
    issuer = HostPackageRootIssuer(
        (HostPublishedGeneration(identity, str(tmp_path), True),),
        publication_verifier=lambda record: (
            record.identity == identity
            and record.absolute_root == str(tmp_path)
            and record.sealed
        ),
    )
    with issuer.issue(identity.generation_id) as lease:
        snapshot = LocalPackageLoader().load(lease, identity)
    return assemble_sandbox_m4(assemble_sandbox_domain(snapshot))


def _planner(domain: SandboxM4Domain, model: StructuredStrategyTransportAdapter):
    knowledge = KnowledgeCapabilityContext(
        available_domains=frozenset(), supported_retrieval_modes=frozenset()
    )
    caps = CapabilityRegistry()
    workflows = WorkflowRegistry()
    tools = ToolRegistry()
    ledger = ValidationReceiptLedger()
    planner = DefaultM4Planner(
        mode_router=PlanningModeRouter(),
        goal_resolver=GoalResolver(),
        candidate_builder=LegalActionCandidateBuilder(
            action_registry=domain.actions,
            strategy_registry=domain.strategies,
        ),
        strategy_selector=HybridStrategySelector(
            strategy_registry=domain.strategies,
            model=model,
        ),
        selected_action_resolver=SelectedActionResolver(domain.strategies),
        knowledge_planner=KnowledgePlanner(
            need_resolver=KnowledgeNeedResolver(),
            domain_router=KnowledgeDomainRouter(),
            query_builder=RetrievalQueryBuilder(),
            retrieval_planner=RetrievalPlanner(),
            evidence_planner=EvidenceRequirementPlanner(),
        ),
        execution_preplanner=ExecutionPreplanner(
            memory_planner=MemoryUsagePlanner(),
            capability_planner=CapabilityPlanner(
                skill_registry=domain.skills,
                workflow_registry=workflows,
            ),
            tool_planner=ToolPlanner(skill_registry=domain.skills, tool_registry=tools),
            confirmation_planner=ConfirmationPlanner(domain.actions),
            sequence_planner=SequencePlanner(),
            fallback_planner=FallbackPlanner(action_registry=domain.actions),
        ),
        response_strategy_builder=ResponseStrategyBuilder(),
        draft_assembler=ActionPlanDraftAssembler(),
        capability_id_resolver=CapabilityIdResolver(caps),
        knowledge_capability_context=knowledge,
        plan_id_factory=lambda request_id: f"domain-{request_id}",
    )
    validator = RuntimePlanValidatorAdapter(
        validator=PlanValidator(),
        validation_context=PlanValidationContext(
            action_registry=domain.actions,
            strategy_registry=domain.strategies,
            skill_registry=domain.skills,
            workflow_registry=workflows,
            tool_registry=tools,
            knowledge_capabilities=knowledge,
        ),
        receipt_ledger=ledger,
    )
    rechecker = RuntimePolicyRecheckerAdapter(
        approval_coordinator=PlanApprovalCoordinator(
            policy_rechecker=DefaultPolicyRechecker()
        ),
        receipt_ledger=ledger,
    )
    return planner, validator, rechecker


class DomainChoiceTransport:
    def __init__(self, domain: SandboxM4Domain):
        self.domain = domain
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, payload: dict[str, Any]) -> dict[str, object]:
        self.calls.append(payload)
        seen = payload["last_agent_action"] == "MOCK_FOUND_NEEDS_VERIFICATION"
        strategy = self.domain.verify_strategy if seen else self.domain.collect_strategy
        action = self.domain.verify_action if seen else self.domain.collect_action
        assert action in payload["candidate_action_ids"]
        assert strategy in payload["legal_strategy_ids"]
        return {
            "strategy_id": strategy,
            "action_ids": [action],
            "reason_code": "DOMAIN_SANDBOX_MODEL_CHOICE",
        }


class DomainDrivenTurn(ModelDrivenSandboxTurn):
    def __init__(self, initial, domain: SandboxM4Domain):
        self.domain = domain
        super().__init__(initial)
        self.binding = domain.binding.for_run(
            initial, run_id=f"sandbox-{domain.binding.domain_id}"
        )
        self.transport = DomainChoiceTransport(domain)
        self._planner, self._validator, self._rechecker = _planner(
            domain, StructuredStrategyTransportAdapter(self.transport)
        )

    async def execute_and_observe(self, decision: Decision) -> ObservedFact:
        if decision.approved is None or len(decision.approved.steps) != 1:
            raise SandboxAssemblyError("expected one approved action")
        action = decision.approved.steps[0].action
        if action == self.domain.collect_action:
            self.facts = ("MOCK_FOUND_NEEDS_VERIFICATION",)
        elif action == self.domain.verify_action:
            self.facts = ("GOAL_SATISFIED",)
        else:
            raise SandboxAssemblyError("action not in bound package")
        self.selected_actions.append(action)
        return await SandboxTurn.execute_and_observe(self, decision)


def test_two_domain_packages_same_core_and_real_m4(tmp_path: Path) -> None:
    async def scenario() -> None:
        traces = []
        for domain_id, noun in (
            ("inventory.reconcile", "stock"),
            ("learning.plan", "notes"),
        ):
            root = tmp_path / noun
            root.mkdir()
            domain = _load(root, domain_id, noun)
            initial = build_runtime_input(text=f"collect and verify fictional {noun}")
            turn = DomainDrivenTurn(initial, domain)
            outcome = await AgentRunCoordinator(
                turn, LoopBudget(max_iterations=4, max_executions=3)
            ).run(initial, turn.binding)
            assert outcome.kind is RunKind.FINISH
            assert outcome.executions == 2 and outcome.iterations == 3
            assert turn.selected_actions == [
                domain.collect_action,
                domain.verify_action,
            ]
            assert set(turn.transport.calls[0]["legal_strategy_ids"]) == {
                domain.collect_strategy,
                domain.verify_strategy,
            }
            assert all(
                obs.domain_fingerprint == domain.binding.binding_fingerprint
                for obs in outcome.observations
            )
            assert turn.mock_calls == 2
            traces.append((domain.binding.binding_fingerprint, turn.selected_actions))
        assert traces[0][0] != traces[1][0]
        assert traces[0][1] != traces[1][1]

    asyncio.run(scenario())


def test_rejects_cross_domain_strategy_reference(tmp_path: Path) -> None:
    domain = _load(tmp_path, "inventory.reconcile", "stock")
    # Inert asset content mutation is not accepted by the dynamic M4 assembler.
    original = next(a for a in domain.binding.assets if a.kind == "strategy")
    from dataclasses import replace

    tampered = replace(
        original, content_bytes=b'{"role":"collect","action_id":"foreign"}'
    )
    altered = replace(
        domain.binding,
        assets=tuple(tampered if a is original else a for a in domain.binding.assets),
    )
    with pytest.raises(SandboxAssemblyError, match="digest mismatch"):
        assemble_sandbox_m4(altered)

    # Even a synthetic caller that spoofs the asset checksum cannot introduce
    # a foreign action through the separately enforced strategy reference rule.
    # This is NOT a production-authenticated Host/issuer scenario.
    checksum_spoofed = replace(
        tampered, sha256=hashlib.sha256(tampered.content_bytes).hexdigest()
    )
    spoofed_binding = replace(
        domain.binding,
        assets=tuple(
            checksum_spoofed if a is original else a for a in domain.binding.assets
        ),
    )
    with pytest.raises(SandboxAssemblyError, match="foreign action"):
        assemble_sandbox_m4(spoofed_binding)
