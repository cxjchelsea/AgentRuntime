"""Synthetic medical-domain read-only SQLite/tool E2E, not clinical validation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from agent_core.domain_application import bootstrap_domain_application
from agent_core.domain_package_loader import (
    HostPackageRootIssuer,
    HostPublishedGeneration,
    LocalPackageLoader,
    TrustedPackageIdentity,
)
from agent_core.model_adapter import StructuredStrategyTransportAdapter
from agent_core.readonly_domain_lookup import ReadOnlyDomainLookup
from agent_core.runner import (
    Decision,
    LoopBudget,
    ObservedFact,
    RunBoundaryError,
    RunKind,
)
from agent_core.sandbox_tool_dispatch import SandboxToolDispatcher
from agent_core.sqlite_business_intake import load_sqlite_business_snapshot
from tests.orchestration_stubs import build_runtime_input
from tests.test_ga01_slice2_loop import ModelDrivenSandboxTurn
from tests.test_ga08_execution_catalog import _snapshot
from tests.test_ga13_sqlite_business_intake import _database, _row

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="verified package loader requires Linux",
)

DOMAINS = (
    (
        "medical.chronic-management",
        "blood_pressure",
        {"systolic": 128, "diastolic": 82},
    ),
    (
        "medical.mental-wellbeing",
        "mood_checkin",
        {"mood_score": 3, "sleep_hours": 7},
    ),
)


def _medical_package(root: Path, domain: str, *, differentiated: bool = False):
    """Reissue fixture as a distinct verified medical package, including knowledge."""
    # Distinct package-owned workflows, without altering the generic Agent Core.
    step_count = 2 if not differentiated or domain == DOMAINS[0][0] else 1
    _snapshot(root, steps=step_count, with_content=True)
    manifest_path = root / "package.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["domain_id"] = domain
    is_chronic = domain == "medical.chronic-management"
    domain_content = {
        "knowledge": {
            "key": "bp-metric-guide" if is_chronic else "wellbeing-checkin-guide",
            "fact": (
                "Synthetic blood pressure trend evidence; no clinical classification"
                if is_chronic
                else "Synthetic mood and sleep checkin evidence; no mental health diagnosis"
            ),
        },
        "rule": {
            "required_knowledge": (
                "bp-metric-guide" if is_chronic else "wellbeing-checkin-guide"
            ),
            "completion_after": "verify" if is_chronic else "collect",
        },
        "prompt": {
            "focus": (
                "Review synthetic longitudinal metrics without clinical advice"
                if is_chronic
                else "Summarize synthetic wellbeing checkin without diagnosis"
            ),
        },
    }
    for ref in manifest["asset_refs"]:
        ref["namespace"] = domain
        if ref["kind"] in domain_content:
            asset_path = root / ref["relative_path"]
            raw = json.dumps(domain_content[ref["kind"]], sort_keys=True).encode()
            asset_path.write_bytes(raw)
            ref["sha256"] = hashlib.sha256(raw).hexdigest()
    manifest.pop("manifest_digest")
    digest = hashlib.sha256(
        json.dumps(
            manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    manifest["manifest_digest"] = digest
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    identity = TrustedPackageIdentity(
        "medical-synthetic-gen", domain, "1.0.0", "GA02-D1-1", digest
    )
    publication = HostPublishedGeneration(identity, str(root), True)
    issuer = HostPackageRootIssuer(
        (publication,), publication_verifier=lambda record: record == publication
    )
    with issuer.issue(identity.generation_id) as lease:
        return LocalPackageLoader().load(lease, identity)


@pytest.mark.parametrize(("domain_id", "topic", "medical_data"), DOMAINS)
def test_medical_subdomain_real_sqlite_m4_tool_chain(
    tmp_path: Path, domain_id: str, topic: str, medical_data: dict[str, int]
) -> None:
    async def scenario() -> None:
        snapshot = _medical_package(tmp_path / "package", domain_id)
        app = bootstrap_domain_application(snapshot)
        catalog = app.execution_catalog(snapshot)
        assert catalog.domain_id == domain_id
        knowledge = [
            asset for asset in snapshot.assets if asset.ref.kind == "knowledge"
        ]
        assert len(knowledge) == 1
        keys = {
            step.step_id: f"{topic}-{i}"
            for i, step in enumerate(catalog.workflow.steps)
        }
        db = tmp_path / "medical-synthetic.sqlite"
        _database(
            db,
            [
                _row(catalog, keys[step.step_id], medical_data)
                for step in catalog.workflow.steps
            ],
        )
        before = db.read_bytes()
        lookup = load_sqlite_business_snapshot(
            catalog=catalog, database_file=db, step_keys=keys
        )
        dispatcher = SandboxToolDispatcher(catalog, lookup.handlers())

        async def choose(payload: dict[str, Any]) -> dict[str, object]:
            role = "verify" if payload["last_agent_action"] == "FACT_1" else "collect"
            return {
                "strategy_id": f"{role}-strategy-notes",
                "action_ids": [f"{role}-notes"],
                "reason_code": "MEDICAL_SYNTHETIC_READ_ONLY",
            }

        class MedicalTurn(ModelDrivenSandboxTurn):
            def __post_init__(self) -> None:
                super().__post_init__()
                self.binding = app.prepare(self.initial, run_id="medical-readonly-run")
                self._planner, self._validator, self._rechecker = app.m4(
                    StructuredStrategyTransportAdapter(choose)
                )

            async def execute_and_observe(self, decision: Decision) -> ObservedFact:
                observed = await dispatcher.observe(
                    decision=decision,
                    step_index=self.actions,
                    run_id=self.binding.run_id,
                    execution_id=f"medical-execution-{self.actions + 1}",
                )
                self.actions += 1
                return observed

        initial = build_runtime_input(
            text=f"Read synthetic {topic} and verify its source"
        )
        result = await app.run(
            initial,
            run_id="medical-readonly-run",
            step=MedicalTurn(initial),
            budget=LoopBudget(max_iterations=4, max_executions=3),
            execution_catalog=catalog,
        )
        assert result.kind is RunKind.FINISH
        assert result.executions == 2
        assert [obs.workflow_step_id for obs in result.observations] == [
            "step-1",
            "step-2",
        ]
        assert all(
            "RECORD_SHA256_" in " ".join(obs.facts) for obs in result.observations
        )
        assert db.read_bytes() == before

    asyncio.run(scenario())


def test_medical_sqlite_cross_domain_evidence_rejected(tmp_path: Path) -> None:
    chronic = _medical_package(tmp_path / "chronic", DOMAINS[0][0])
    mental = _medical_package(tmp_path / "mental", DOMAINS[1][0])
    a = bootstrap_domain_application(chronic).execution_catalog(chronic)
    b = bootstrap_domain_application(mental).execution_catalog(mental)
    assert a.binding_fingerprint != b.binding_fingerprint
    db = tmp_path / "cross-domain.sqlite"
    _database(db, [_row(a, f"record-{i}", DOMAINS[0][2]) for i in range(1, 3)])
    with pytest.raises(RunBoundaryError, match="SQLite|record snapshot"):
        load_sqlite_business_snapshot(
            catalog=b,
            database_file=db,
            step_keys={"step-1": "record-1", "step-2": "record-2"},
        )

    valid = load_sqlite_business_snapshot(
        catalog=a,
        database_file=db,
        step_keys={"step-1": "record-1", "step-2": "record-2"},
    )
    with pytest.raises(RunBoundaryError, match="scope mismatch"):
        ReadOnlyDomainLookup(b, dict(valid.records), dict(valid.step_keys))
