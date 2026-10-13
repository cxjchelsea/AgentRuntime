"""GA-02 D3: actual D2-A loader -> sandbox binding -> real M4 -> mock task E2E.

This test-only adapter translates generic M4 fixture actions into *package*
action ids. It never claims the model planner was dynamically assembled from
Domain assets or that M6 has issued positive production grants.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from agent_core.domain_package_loader import (
    HostPackageRootIssuer,
    HostPublishedGeneration,
    LocalPackageLoader,
    TrustedPackageIdentity,
    VerifiedAssetV1,
)
from agent_core.runner import AgentRunCoordinator, Decision, LoopBudget, ObservedFact, RunKind
from agent_core.sandbox_domain_assembly import (
    ROLE,
    SandboxAssemblyError,
    SandboxDomainBinding,
    assemble_sandbox_domain,
)
from tests.orchestration_stubs import build_runtime_input
from tests.test_ga01_slice2_loop import ModelDrivenSandboxTurn

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="D2-A requires Linux FD loader"
)

ACTION_MAP = {"DOMAIN_ACTION_A": "collect", "DOMAIN_ACTION_B": "verify"}


def _write_package(tmp_path: Path, *, domain_id: str = "inventory.reconcile") -> TrustedPackageIdentity:
    assets: list[dict[str, str]] = []
    for action_id in ("collect", "verify"):
        content = json.dumps({"description": action_id}, sort_keys=True).encode()
        relative = f"actions/{action_id}.json"
        location = tmp_path / relative
        location.parent.mkdir(parents=True, exist_ok=True)
        location.write_bytes(content)
        assets.append(
            {
                "kind": "action",
                "namespace": domain_id,
                "id": action_id,
                "version": "1.0.0",
                "sha256": hashlib.sha256(content).hexdigest(),
                "relative_path": relative,
            }
        )
    payload: dict[str, object] = {
        "asset_refs": assets,
        "domain_id": domain_id,
        "domain_version": "1.0.0",
        "enabled": True,
        "name": "Safe Sandbox Task",
        "package_schema_version": "1",
        "runtime_compatibility": "GA02-D1-1",
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(canonical).hexdigest()
    payload["manifest_digest"] = digest
    (tmp_path / "package.json").write_bytes(json.dumps(payload).encode())
    return TrustedPackageIdentity(
        "sandbox-gen-1", domain_id, "1.0.0", "GA02-D1-1", digest
    )


def _load(tmp_path: Path, *, domain_id: str = "inventory.reconcile"):
    identity = _write_package(tmp_path, domain_id=domain_id)
    # Narrow test-only source verifier. Not an independently authenticated Host.
    issuer = HostPackageRootIssuer(
        (HostPublishedGeneration(identity, str(tmp_path), True),),
        publication_verifier=lambda generation: (
            generation.identity == identity
            and generation.absolute_root == str(tmp_path)
            and generation.sealed
        ),
    )
    with issuer.issue(identity.generation_id) as lease:
        return LocalPackageLoader().load(lease, identity)


class PackageBoundSandboxStep:
    """Guard approved M4 mock actions with the pinned package's allowlist."""

    def __init__(self, inner: ModelDrivenSandboxTurn, binding: SandboxDomainBinding):
        self.inner = inner
        self.domain_binding = binding
        self.binding = inner.binding = binding.for_run(inner.initial, run_id="d3-sandbox-run")
        if set(ACTION_MAP.values()) != set(binding.action_ids):
            raise SandboxAssemblyError("sandbox action mapping does not match package")

    async def decide(self, current_input, iteration, observations):
        return await self.inner.decide(current_input, iteration, observations)

    async def execute_and_observe(self, decision: Decision) -> ObservedFact:
        approved = decision.approved
        if approved is None or len(approved.steps) != 1:
            raise SandboxAssemblyError("sandbox requires exactly one approved action")
        if ACTION_MAP.get(approved.steps[0].action) not in self.binding_action_ids:
            raise SandboxAssemblyError("approved M4 action not present in package")
        return await self.inner.execute_and_observe(decision)

    @property
    def binding_action_ids(self) -> tuple[str, ...]:
        return self.domain_binding.action_ids


def _bound_step(initial, binding: SandboxDomainBinding):
    inner = ModelDrivenSandboxTurn(initial)
    step = PackageBoundSandboxStep(inner, binding)
    return step


def test_d3_first_package_bound_task_e2e(tmp_path: Path) -> None:
    async def scenario() -> None:
        snapshot = _load(tmp_path)
        binding = assemble_sandbox_domain(snapshot)
        assert binding.role == ROLE
        assert binding.action_ids == ("collect", "verify")
        assert binding.domain_id == "inventory.reconcile"

        initial = build_runtime_input(text="collect then check fictional stock levels")
        step = _bound_step(initial, binding)
        result = await AgentRunCoordinator(
            step, LoopBudget(max_iterations=4, max_executions=3)
        ).run(initial, step.binding)
        assert result.kind is RunKind.FINISH
        assert result.executions == 2
        assert result.iterations == 3
        assert step.inner.selected_actions == ["DOMAIN_ACTION_A", "DOMAIN_ACTION_B"]
        assert [obs.domain_fingerprint for obs in result.observations] == [
            binding.binding_fingerprint, binding.binding_fingerprint
        ]
        assert step.inner.fake_model.calls[1]["last_agent_action"] == (
            "MOCK_FOUND_NEEDS_VERIFICATION"
        )
    asyncio.run(scenario())


def test_d3_repeated_bytes_pin_same_identity(tmp_path: Path) -> None:
    snap = _load(tmp_path)
    a = assemble_sandbox_domain(snap)
    b = assemble_sandbox_domain(snap)
    assert a == b
    assert a.binding_fingerprint == b.binding_fingerprint
    assert a.assets[0].content_bytes == b.assets[0].content_bytes


def test_d3_rejects_changed_asset_after_loader(tmp_path: Path) -> None:
    snap = _load(tmp_path)
    changed = replace(snap.assets[0], content_bytes=b"tampered")
    with pytest.raises(SandboxAssemblyError, match="digest"):
        assemble_sandbox_domain(replace(snap, assets=(changed, *snap.assets[1:])))


def test_d3_rejects_incomplete_snapshot(tmp_path: Path) -> None:
    snap = _load(tmp_path)
    with pytest.raises(SandboxAssemblyError, match="incomplete"):
        assemble_sandbox_domain(replace(snap, assets=snap.assets[:-1]))


def test_d3_source_change_changes_fingerprint(tmp_path: Path) -> None:
    one = assemble_sandbox_domain(_load(tmp_path))
    other = tmp_path / "other"
    other.mkdir()
    two = assemble_sandbox_domain(_load(other, domain_id="learning.plan"))
    assert one.binding_fingerprint != two.binding_fingerprint
    assert one.domain_id != two.domain_id


def test_d3_mismatched_action_mapping_does_not_run(tmp_path: Path) -> None:
    snap = _load(tmp_path)
    binding = assemble_sandbox_domain(snap)
    initial = build_runtime_input(text="safe mock task")
    step = _bound_step(initial, binding)
    assert step.inner.actions == 0
    assert "UNREGISTERED" not in ACTION_MAP
