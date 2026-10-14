"""GA-13 application-boundary SQLite read-only intake for sandbox business Agents.

Read bounded rows from an already-existing application-approved SQLite file
BEFORE execution, then freeze GA-10 records for unchanged GA-12 business tools.
Never inject the database connection into GA-09 SandboxToolDispatcher.
This does not authenticate an external publisher or issue M6 permission.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path

from agent_core.domain_execution_catalog import DomainExecutionCatalog
from agent_core.readonly_domain_lookup import ReadOnlyDomainLookup, ReadOnlyRecord
from agent_core.runner import RunBoundaryError


def load_sqlite_business_snapshot(
    *,
    catalog: DomainExecutionCatalog,
    database_file: Path,
    step_keys: Mapping[str, str],
) -> ReadOnlyDomainLookup:
    """Read an explicitly named, pre-existing DB; no SQL comes from the model.

    The caller selects the database path and exact record keys. The schema is
    fixed: business_records(domain_id, binding_fingerprint, record_key,
    value, sha256). Missing, duplicate, foreign or invalid rows fail closed.
    SHA256 checks accidental/tampered content, not a publisher's authenticity.
    """
    if (
        type(catalog) is not DomainExecutionCatalog
        or not isinstance(database_file, Path)
        or type(step_keys) is not dict
        or set(step_keys) != {step.step_id for step in catalog.workflow.steps}
        or any(
            type(key) is not str or not 1 <= len(key) <= 96
            for key in step_keys.values()
        )
    ):
        raise RunBoundaryError("invalid SQLite intake binding")
    # Reject symlinks and absent paths. No URI supplied by caller, so no
    # URI query or alternate database target is model-controlled.
    if database_file.is_symlink() or not database_file.is_file():
        raise RunBoundaryError("SQLite source must be an existing regular file")
    records: dict[str, ReadOnlyRecord] = {}
    try:
        uri = database_file.resolve(strict=True).as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=2.0)) as connection:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            for key in dict.fromkeys(step_keys.values()):
                rows = connection.execute(
                    "SELECT domain_id, binding_fingerprint, record_key, value, sha256 "
                    "FROM business_records "
                    "WHERE domain_id=? AND binding_fingerprint=? AND record_key=? "
                    "LIMIT 2",
                    (catalog.domain_id, catalog.binding_fingerprint, key),
                ).fetchall()
                if len(rows) != 1:
                    raise RunBoundaryError("missing or ambiguous SQLite business row")
                domain_id, fingerprint, returned_key, value, digest = rows[0]
                if any(type(v) is not str for v in rows[0]):
                    raise RunBoundaryError("invalid SQLite business row types")
                record = ReadOnlyRecord(
                    domain_id=domain_id,
                    binding_fingerprint=fingerprint,
                    key=returned_key,
                    value=value,
                    sha256=digest,
                )
                if (
                    record.key != key
                    or record.domain_id != catalog.domain_id
                    or record.binding_fingerprint != catalog.binding_fingerprint
                    or hashlib.sha256(record.value.encode("utf-8")).hexdigest()
                    != record.sha256
                ):
                    raise RunBoundaryError("SQLite business source integrity mismatch")
                records[key] = record
            connection.rollback()
    except (sqlite3.Error, OSError, ValueError) as exc:
        raise RunBoundaryError("SQLite business intake failed") from exc

    # Immutable snapshot is the only object that crosses into Agent execution.
    return ReadOnlyDomainLookup(catalog, records, dict(step_keys))
