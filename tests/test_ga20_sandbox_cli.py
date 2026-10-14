"""GA-20 interactive sandbox input boundaries; live inference is opt-in CI."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from agent_core.domain_application import bootstrap_domain_application
from examples.ga20_sandbox_cli import (
    DEFAULT_QUESTIONS,
    OPERATIONS,
    load_operator_source,
    validated_question,
)
from tests.test_ga08_execution_catalog import _snapshot
from tests.test_ga13_sqlite_business_intake import _database, _row


@pytest.mark.parametrize("domain", ["inventory", "learning"])
def test_valid_demo_scope(domain: str) -> None:
    assert (
        validated_question(domain, DEFAULT_QUESTIONS[domain])
        == DEFAULT_QUESTIONS[domain]
    )
    assert domain in OPERATIONS


@pytest.mark.parametrize(
    ("domain", "question"),
    [
        ("inventory", "帮我发送真实采购订单"),
        ("learning", "帮我给学生打分"),
        ("inventory", ""),
        ("inventory", "x" * 1001),
        ("unknown", "库存"),
    ],
)
def test_out_of_scope_fails_closed(domain: str, question: str) -> None:
    with pytest.raises(ValueError):
        validated_question(domain, question)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="FD loader Linux-only")
def test_operator_external_package_and_sqlite_source(tmp_path: Path) -> None:
    package = tmp_path / "package"
    snapshot = _snapshot(package, steps=1)
    catalog = bootstrap_domain_application(snapshot).execution_catalog(snapshot)
    database = tmp_path / "business.sqlite"
    _database(
        database, [_row(catalog, "sku", {"on_hand": 8, "reserved": 3, "target": 12})]
    )
    settings = {
        "domain": catalog.domain_id,
        "package_root": str(package),
        "generation_id": snapshot.generation_id,
        "domain_version": snapshot.descriptor.domain_version,
        "runtime_profile": snapshot.descriptor.runtime_compatibility,
        "manifest_digest": snapshot.expected_manifest_digest,
        "database_file": str(database),
        "step_keys": {"step-1": "sku"},
    }
    path = tmp_path / "source.json"
    path.write_text(json.dumps(settings), encoding="utf-8")
    verified, lookup = load_operator_source(path, "inventory")
    assert verified.descriptor.domain_id == catalog.domain_id
    assert lookup.records["sku"].value

    settings["manifest_digest"] = "0" * 64
    path.write_text(json.dumps(settings), encoding="utf-8")
    with pytest.raises(ValueError):
        load_operator_source(path, "inventory")
    with pytest.raises(ValueError):
        load_operator_source(path, "learning")
