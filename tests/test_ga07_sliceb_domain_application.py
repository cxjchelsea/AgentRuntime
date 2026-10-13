"""GA-07 Slice B independent package-driven M4 assembly and bootstrap tests."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from agent_core.domain_application import bootstrap_domain_application
from agent_core.domain_extension import DomainExtensionError, assemble_domain_extension
from agent_core.domain_package_loader import (
    HostPackageRootIssuer,
    HostPublishedGeneration,
    LocalPackageLoader,
)
from agent_core.runner import Decision, LoopBudget, ObservedFact, RunKind
from agent_core.sandbox_domain_assembly import SandboxBoundAsset, assemble_sandbox_domain
from tests.orchestration_stubs import build_runtime_input
from tests.test_ga02_d4_two_domain_m4_e2e import _package

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="the D2-A sealed local package loader requires Linux",
)


def _snapshot(root: Path, domain: str, noun: str):
    root.mkdir()
    identity = _package(root, domain, noun)
    record = HostPublishedGeneration(identity, str(root), True)
    issuer = HostPackageRootIssuer(
        (record,),
        publication_verifier=lambda generation: generation == record,
    )
    with issuer.issue(identity.generation_id) as lease:
        return LocalPackageLoader().load(lease, identity)


class _WaitOnlyStep:
    def __init__(self):
        self.calls = 0

    async def decide(self, _input, iteration, _observations):
        self.calls += 1
        return Decision(iteration, "WAIT", reason="APP_REQUIRES_EXPLICIT_APPROVAL")

    async def execute_and_observe(self, _decision) -> ObservedFact:
        raise AssertionError("application bootstrap MUST NOT auto-execute tools")


@pytest.mark.parametrize(
    ("domain_id", "noun"),
    [("inventory.reconcile", "stock"), ("learning.plan", "notes")],
)
def test_reusable_bootstrap_loads_two_domain_packages(
    tmp_path: Path, domain_id: str, noun: str
) -> None:
    snapshot = _snapshot(tmp_path / noun, domain_id, noun)
    app = bootstrap_domain_application(snapshot)
    extension = app.extension
    assert extension.binding.domain_id == domain_id
    assert set(extension.action_ids) == {f"collect-{noun}", f"verify-{noun}"}
    assert set(extension.strategy_ids) == {
        f"collect-strategy-{noun}",
        f"verify-strategy-{noun}",
    }
    assert dict(extension.strategy_actions) == {
        f"collect-strategy-{noun}": f"collect-{noun}",
        f"verify-strategy-{noun}": f"verify-{noun}",
    }
    assert extension.actions is not None
    assert extension.strategies is not None
    assert extension.skills is not None
    initial = build_runtime_input(text=f"synthetic {noun} task")
    step = _WaitOnlyStep()
    outcome = asyncio.run(
        app.run(initial, run_id=f"ga07-{noun}", step=step, budget=LoopBudget())
    )
    assert outcome.kind is RunKind.WAIT
    assert outcome.reason == "APP_REQUIRES_EXPLICIT_APPROVAL"
    assert outcome.executions == 0
    assert step.calls == 1


def test_cross_domain_assemblies_do_not_share_registries(tmp_path: Path) -> None:
    a = bootstrap_domain_application(
        _snapshot(tmp_path / "stock", "inventory.reconcile", "stock")
    )
    b = bootstrap_domain_application(
        _snapshot(tmp_path / "notes", "learning.plan", "notes")
    )
    assert a.extension.actions is not b.extension.actions
    assert a.extension.strategies is not b.extension.strategies
    assert a.extension.skills is not b.extension.skills
    assert not set(a.extension.action_ids) & set(b.extension.action_ids)
    assert a.extension.binding.binding_fingerprint != b.extension.binding.binding_fingerprint


def test_cross_package_action_reference_is_rejected(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path / "stock", "inventory.reconcile", "stock")
    binding = assemble_sandbox_domain(snapshot)
    original = next(asset for asset in binding.assets if asset.kind == "strategy")
    import hashlib

    forged = b'{"action_id":"foreign-action","role":"collect"}'
    modified = replace(
        original, content_bytes=forged, sha256=hashlib.sha256(forged).hexdigest()
    )
    mutated = replace(
        binding,
        assets=tuple(modified if item == original else item for item in binding.assets),
    )
    with pytest.raises(DomainExtensionError, match="foreign or mismatched"):
        assemble_domain_extension(mutated)


def test_tampered_asset_digest_rejected(tmp_path: Path) -> None:
    binding = assemble_sandbox_domain(
        _snapshot(tmp_path / "stock", "inventory.reconcile", "stock")
    )
    item = binding.assets[0]
    bad = SandboxBoundAsset(
        item.kind,
        item.namespace,
        item.id,
        item.version,
        "0" * 64,
        item.content_bytes,
    )
    mutated = replace(binding, assets=(bad, *binding.assets[1:]))
    with pytest.raises(DomainExtensionError, match="digest"):
        assemble_domain_extension(mutated)
