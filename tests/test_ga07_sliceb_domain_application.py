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
from agent_core.model_adapter import StructuredStrategyTransportAdapter
from agent_core.runner import Decision, LoopBudget, ObservedFact, RunKind
from agent_core.sandbox_domain_assembly import assemble_sandbox_domain
from tests.ga02_d4_domain_m4_assembly import assemble_sandbox_m4
from tests.orchestration_stubs import build_runtime_input
from tests.test_ga02_d4_two_domain_m4_e2e import (
    DomainDrivenTurn,
    _package,
)

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
    assert (
        a.extension.binding.binding_fingerprint
        != b.extension.binding.binding_fingerprint
    )


def test_modified_package_strategy_rejected_before_m4_assembly(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path / "stock", "inventory.reconcile", "stock")
    original = next(asset for asset in snapshot.assets if asset.ref.kind == "strategy")
    forged = replace(original, content_bytes=b'{"action_id":"foreign","role":"collect"}')
    tampered = replace(
        snapshot,
        assets=tuple(forged if item is original else item for item in snapshot.assets),
    )
    with pytest.raises(DomainExtensionError, match="digest"):
        assemble_domain_extension(tampered)


def test_invalid_asset_reference_order_rejected(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path / "stock", "inventory.reconcile", "stock")
    tampered = replace(snapshot, assets=tuple(reversed(snapshot.assets)))
    with pytest.raises(DomainExtensionError, match="reference mismatch"):
        assemble_domain_extension(tampered)


@pytest.mark.parametrize(
    ("domain_id", "noun"),
    [("inventory.reconcile", "stock"), ("learning.plan", "notes")],
)
def test_package_driven_m4_runs_existing_agent_loop(
    tmp_path: Path, domain_id: str, noun: str
) -> None:
    snapshot = _snapshot(tmp_path / noun, domain_id, noun)
    app = bootstrap_domain_application(snapshot)
    domain_fixture = assemble_sandbox_m4(assemble_sandbox_domain(snapshot))
    initial = build_runtime_input(text=f"collect and verify fictional {noun}")
    turn = DomainDrivenTurn(initial, domain_fixture)
    turn._planner, turn._validator, turn._rechecker = app.m4(
        StructuredStrategyTransportAdapter(turn.transport)
    )
    outcome = asyncio.run(
        app.run(
            initial,
            run_id=f"sandbox-{domain_id}",
            step=turn,
            budget=LoopBudget(max_iterations=4, max_executions=3),
        )
    )
    assert outcome.kind is RunKind.FINISH
    assert outcome.executions == 2
    assert turn.selected_actions == [f"collect-{noun}", f"verify-{noun}"]
    assert turn.mock_calls == 2
