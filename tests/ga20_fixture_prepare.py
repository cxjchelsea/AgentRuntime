"""CI-only GA-20 synthetic published package and SQLite fixture producer."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_core.domain_application import bootstrap_domain_application
from tests.test_ga08_execution_catalog import _snapshot
from tests.test_ga13_sqlite_business_intake import _database, _row


def prepare(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for domain, steps in (("inventory", 1), ("learning", 2)):
        package = output / (domain + "-package")
        snapshot = _snapshot(package, steps=steps)
        catalog = bootstrap_domain_application(snapshot).execution_catalog(snapshot)
        records = (
            ({"on_hand": 8, "reserved": 3, "target": 12},)
            if steps == 1
            else ({"completed": 2, "total": 5}, {"completed": 2, "total": 5})
        )
        keys = {
            step.step_id: f"business-{i}"
            for i, step in enumerate(catalog.workflow.steps, 1)
        }
        database = output / (domain + ".sqlite")
        _database(
            database,
            [
                _row(catalog, keys[step.step_id], data)
                for step, data in zip(catalog.workflow.steps, records, strict=True)
            ],
        )
        config = {
            "domain": catalog.domain_id,
            "package_root": str(package.resolve()),
            "generation_id": snapshot.generation_id,
            "domain_version": snapshot.descriptor.domain_version,
            "runtime_profile": snapshot.descriptor.runtime_compatibility,
            "manifest_digest": snapshot.expected_manifest_digest,
            "database_file": str(database.resolve()),
            "step_keys": keys,
        }
        (output / (domain + ".json")).write_text(
            json.dumps(config), encoding="utf-8"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.output_dir.resolve())


if __name__ == "__main__":
    main()
