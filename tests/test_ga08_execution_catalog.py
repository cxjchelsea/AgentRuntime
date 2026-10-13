"""GA-08: two distinct package-owned execution catalogs, no live grants."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from agent_core.domain_application import bootstrap_domain_application
from agent_core.domain_execution_catalog import (
    WorkflowStepEvidence,
    assemble_execution_catalog,
)
from agent_core.domain_extension import DomainExtensionError
from agent_core.domain_package_loader import (
    HostPackageRootIssuer,
    HostPublishedGeneration,
    LocalPackageLoader,
    TrustedPackageIdentity,
)
from agent_core.model_adapter import StructuredStrategyTransportAdapter
from agent_core.runner import Decision, LoopBudget, ObservedFact, RunKind
from tests.orchestration_stubs import build_runtime_input
from tests.test_ga01_slice1 import SandboxTurn
from tests.test_ga01_slice2_loop import ModelDrivenSandboxTurn
from tests.test_ga02_d4_two_domain_m4_e2e import _package

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="GA08 uses Linux-only D2-A verified package loader",
)


def _snapshot(root: Path, *, steps: int = 1):
    root.mkdir()
    domain = "inventory.reconcile" if steps == 1 else "learning.plan"
    noun = "stock" if steps == 1 else "notes"
    _package(root, domain, noun)
    manifest = json.loads((root / "package.json").read_text())
    tool_names = ["lookup-stock"] if steps == 1 else ["read-notes", "check-outline"]
    additions: list[dict[str, str]] = []
    payloads: list[tuple[str, str, dict[str, Any]]] = [
        ("tool", tool_id, {"description": "synthetic metadata for " + tool_id})
        for tool_id in tool_names
    ]
    entries = [
        {
            "step_id": f"step-{number}",
            "tool_id": tool_id,
            "action_id": ("collect-" if number == 1 else "verify-") + noun,
            "completion_fact": "FACT_" + str(number),
        }
        for number, tool_id in enumerate(tool_names, 1)
    ]
    payloads.extend(
        [
            ("workflow", "work-" + noun, {"steps": entries}),
            (
                "capability",
                "cap-" + noun,
                {"workflow_id": "work-" + noun, "tool_ids": tool_names},
            ),
        ]
    )
    for kind, asset_id, payload in payloads:
        raw = json.dumps(payload, sort_keys=True).encode()
        relpath = kind + "/" + asset_id + ".json"
        target = root / relpath
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(raw)
        additions.append(
            {
                "kind": kind,
                "namespace": domain,
                "id": asset_id,
                "version": "1.0.0",
                "sha256": hashlib.sha256(raw).hexdigest(),
                "relative_path": relpath,
            }
        )
    manifest["asset_refs"].extend(additions)
    manifest["asset_refs"].sort(
        key=lambda row: (
            row["kind"],
            row["namespace"],
            row["id"],
            row["version"],
            row["relative_path"],
        )
    )
    manifest.pop("manifest_digest")
    digest = hashlib.sha256(
        json.dumps(
            manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    manifest["manifest_digest"] = digest
    (root / "package.json").write_text(json.dumps(manifest))
    identity = TrustedPackageIdentity(
        "sandbox-gen-1", domain, "1.0.0", "GA02-D1-1", digest
    )
    record = HostPublishedGeneration(identity, str(root), True)
    issuer = HostPackageRootIssuer(
        (record,), publication_verifier=lambda generation: generation == record
    )
    with issuer.issue(identity.generation_id) as lease:
        return LocalPackageLoader().load(lease, identity)


@pytest.mark.parametrize("steps", [1, 2])
def test_distinct_domain_execution_catalogs_and_ordered_completion(
    tmp_path: Path, steps: int
) -> None:
    snapshot = _snapshot(tmp_path / "package", steps=steps)
    app = bootstrap_domain_application(snapshot)
    catalog = app.execution_catalog(snapshot)
    assert catalog.domain_id == snapshot.descriptor.domain_id
    assert len(catalog.workflow.steps) == steps
    assert len(catalog.tool_ids) == steps
    assert catalog.capability_id.startswith("cap-")
    assert all(
        catalog.tools.get(tool_id, "1.0.0", namespace=catalog.domain_id)
        for tool_id in catalog.tool_ids
    )
    evidence = tuple(
        WorkflowStepEvidence(
            step.step_id,
            ObservedFact(
                "run-1",
                "request-1",
                f"plan-{number}",
                f"execution-{number}",
                catalog.binding_fingerprint,
                (step.completion_fact,),
                workflow_step_id=step.step_id,
                tool_id=step.tool_id,
            ),
        )
        for number, step in enumerate(catalog.workflow.steps, 1)
    )
    assert catalog.completion_from_observations(run_id="run-1", observations=evidence)
    assert not catalog.completion_from_observations(
        run_id="other-run", observations=evidence
    )
    assert not catalog.completion_from_observations(
        run_id="run-1", observations=evidence[:-1]
    )
    if steps > 1:
        assert not catalog.completion_from_observations(
            run_id="run-1", observations=tuple(reversed(evidence))
        )
    assert not catalog.completion_from_observations(
        run_id="run-1",
        observations=(
            *evidence[:-1],
            replace(
                evidence[-1],
                observation=replace(
                    evidence[-1].observation, domain_fingerprint="0" * 64
                ),
            ),
        ),
    )
    assert not catalog.completion_from_observations(
        run_id="run-1",
        observations=(
            *evidence[:-1],
            replace(evidence[-1], step_id="wrong-step"),
        ),
    )
    invalid_observations = (
        replace(evidence[-1].observation, workflow_step_id="wrong-step"),
        replace(evidence[-1].observation, tool_id="wrong-tool"),
        replace(evidence[-1].observation, tool_id=None),
        replace(evidence[-1].observation, workflow_step_id=None),
    )
    for invalid_observation in invalid_observations:
        altered = replace(evidence[-1], observation=invalid_observation)
        assert not catalog.completion_from_observations(
            run_id="run-1", observations=(*evidence[:-1], altered)
        )


def test_cross_package_catalog_cannot_consume_foreign_snapshot(tmp_path: Path) -> None:
    first = _snapshot(tmp_path / "stock", steps=1)
    second = _snapshot(tmp_path / "notes", steps=2)
    first_app = bootstrap_domain_application(first)
    with pytest.raises(DomainExtensionError, match="binding mismatch"):
        assemble_execution_catalog(second, first_app.extension)


def test_tool_asset_tamper_and_foreign_capability_reference_rejected(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path / "stock", steps=1)
    extension = bootstrap_domain_application(snapshot).extension
    asset = next(a for a in snapshot.assets if a.ref.kind == "tool")
    forged = replace(asset, content_bytes=b'{"description":"tampered"}')
    with pytest.raises(DomainExtensionError, match="integrity"):
        assemble_execution_catalog(
            replace(
                snapshot,
                assets=tuple(forged if a is asset else a for a in snapshot.assets),
            ),
            extension,
        )
    cap = next(a for a in snapshot.assets if a.ref.kind == "capability")
    tampered = b'{"workflow_id":"foreign","tool_ids":["lookup-stock"]}'
    new_ref = replace(cap.ref, sha256=hashlib.sha256(tampered).hexdigest())
    # An attacker cannot rewrite a ref without violating the pinned manifest.
    forged_cap = replace(cap, ref=new_ref, content_bytes=tampered)
    with pytest.raises(DomainExtensionError, match="binding mismatch|integrity"):
        assemble_execution_catalog(
            replace(
                snapshot,
                assets=tuple(forged_cap if a is cap else a for a in snapshot.assets),
            ),
            extension,
        )


@pytest.mark.parametrize("steps", [1, 2])
def test_ga08_domain_workflow_real_m4_sandbox_loop(tmp_path: Path, steps: int) -> None:
    async def scenario() -> None:
        snapshot = _snapshot(tmp_path / "workflow", steps=steps)
        app = bootstrap_domain_application(snapshot)
        catalog = app.execution_catalog(snapshot)
        initial = build_runtime_input(text="complete the domain sandbox task")
        noun = "stock" if steps == 1 else "notes"

        class DomainTransport:
            def __init__(self) -> None:
                self.calls: list[dict[str, Any]] = []

            async def __call__(self, payload: dict[str, Any]) -> dict[str, object]:
                self.calls.append(payload)
                next_role = (
                    "verify" if payload["last_agent_action"] == "FACT_1" else "collect"
                )
                return {
                    "strategy_id": next_role + "-strategy-" + noun,
                    "action_ids": [next_role + "-" + noun],
                    "reason_code": "PACKAGE_WORKFLOW_CHOICE",
                }

        transport = DomainTransport()

        class WorkflowTurn(ModelDrivenSandboxTurn):
            def __post_init__(self) -> None:
                super().__post_init__()
                self.binding = app.prepare(self.initial, run_id="ga08-run")
                self._planner, self._validator, self._rechecker = app.m4(
                    StructuredStrategyTransportAdapter(transport)
                )

            async def execute_and_observe(self, decision: Decision) -> ObservedFact:
                assert decision.approved is not None
                assert len(decision.approved.steps) == 1
                index = self.actions
                step = catalog.workflow.steps[index]
                self.selected_actions.append(decision.approved.steps[0].action)
                self.facts = (step.completion_fact,)
                if index == steps - 1:
                    self.facts += ("GOAL_SATISFIED",)
                result = await SandboxTurn.execute_and_observe(self, decision)
                return replace(
                    result, workflow_step_id=step.step_id, tool_id=step.tool_id
                )

        turn = WorkflowTurn(initial)
        outcome = await app.run(
            initial,
            run_id="ga08-run",
            step=turn,
            budget=LoopBudget(max_iterations=steps + 2, max_executions=steps + 1),
            execution_catalog=catalog,
        )
        assert outcome.kind is RunKind.FINISH
        assert outcome.executions == steps
        assert outcome.iterations == steps + 1
        assert turn.selected_actions == [
            step.action_id for step in catalog.workflow.steps
        ]
        assert turn.mock_calls == steps
        assert len(transport.calls) == steps
        assert len(outcome.observations) == steps

    asyncio.run(scenario())
