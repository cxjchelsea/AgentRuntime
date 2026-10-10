"""GA-02 D1: deterministic parser golden vectors and adversarial denials."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from agent_core.domain_descriptor import (
    PROFILE,
    PackageDescriptorError,
    descriptor_to_domain_manifest,
    parse_package_descriptor,
)

BASE = {
    "asset_refs": [],
    "domain_id": "inventory.reconcile",
    "domain_version": "1.0.0",
    "enabled": True,
    "name": "Inventory Reconciliation",
    "package_schema_version": "1",
    "runtime_compatibility": PROFILE,
}
GOLDEN = b'{"asset_refs":[],"domain_id":"inventory.reconcile","domain_version":"1.0.0","enabled":true,"name":"Inventory Reconciliation","package_schema_version":"1","runtime_compatibility":"GA02-D1-1"}'
DIGEST = "c757e6506fb0e8d7741c9abf5abc2880221655f506afd597dd7817edce195a3f"


def descriptor_bytes(value: dict[str, object], *, resign: bool = True) -> bytes:
    data = deepcopy(value)
    if resign:
        data.pop("manifest_digest", None)
        assets = data.get("asset_refs")
        if type(assets) is list:
            assets.sort(
                key=lambda r: (
                    r["kind"],
                    r["namespace"],
                    r["id"],
                    r["version"],
                    r["relative_path"],
                )
            )
        canonical = json.dumps(
            data, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        data["manifest_digest"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def ref(
    *, name: str = "stock.count", namespace: str = "inventory.reconcile"
) -> dict[str, str]:
    return {
        "kind": "action",
        "namespace": namespace,
        "id": name,
        "version": "1.0.0",
        "sha256": "a" * 64,
        "relative_path": "actions/count.json",
    }


def test_exact_golden_vector_and_manifest_adapter() -> None:
    assert hashlib.sha256(GOLDEN).hexdigest() == DIGEST
    result = parse_package_descriptor(descriptor_bytes(BASE))
    assert result.manifest_digest == DIGEST
    manifest = descriptor_to_domain_manifest(result)
    assert (manifest.domain_id, manifest.name, manifest.version, manifest.enabled) == (
        "inventory.reconcile",
        "Inventory Reconciliation",
        "1.0.0",
        True,
    )
    assert manifest.runtime_compatibility == PROFILE


def test_reordered_keys_and_nonascii_name() -> None:
    reversed_order = dict(reversed(list(BASE.items())))
    assert (
        parse_package_descriptor(descriptor_bytes(reversed_order)).manifest_digest
        == DIGEST
    )
    changed = parse_package_descriptor(descriptor_bytes({**BASE, "name": "库存核对"}))
    assert changed.name == "库存核对"
    assert changed.manifest_digest != DIGEST


def test_nonempty_asset_refs_are_sorted_in_hash_and_returned_value() -> None:
    one = ref()
    two = {**ref(name="reconcile"), "relative_path": "actions/reconcile.json"}
    left = parse_package_descriptor(
        descriptor_bytes({**BASE, "asset_refs": [one, two]})
    )
    right = parse_package_descriptor(
        descriptor_bytes({**BASE, "asset_refs": [two, one]})
    )
    assert left.manifest_digest == right.manifest_digest
    assert left.asset_refs == right.asset_refs


def test_disabled_metadata_remains_disabled() -> None:
    result = parse_package_descriptor(descriptor_bytes({**BASE, "enabled": False}))
    assert descriptor_to_domain_manifest(result).enabled is False


@pytest.mark.parametrize(
    "change",
    [
        {"domain_id": "Invalid_ID"},
        {"domain_version": "01.0.0"},
        {"name": " A"},
        {"name": "e\u0301"},
            {"name": ""},
        {"enabled": 1},
        {"runtime_compatibility": "latest"},
        {"package_schema_version": "2"},
        {"feature_flags": ["skip-safety"]},
        {"unexpected": True},
        {"asset_refs": [ref(namespace="foreign.domain")]},
        {"asset_refs": [ref(), ref()]},
        {"asset_refs": [{**ref(), "sha256": "BAD"}]},
        {"asset_refs": [{**ref(), "relative_path": "../escape"}]},
        {"asset_refs": [{**ref(), "relative_path": "x//y"}]},
        {"asset_refs": [{**ref(), "relative_path": "x\\y"}]},
        {"asset_refs": [{**ref(), "relative_path": "https://unsafe"}]},
        {"asset_refs": [{**ref(), "relative_path": "a%2fb"}]},
        {"asset_refs": [{**ref(), "kind": "executable"}]},
    ],
)
def test_invalid_descriptor_rejected(change: dict[str, object]) -> None:
    with pytest.raises(PackageDescriptorError):
        parse_package_descriptor(descriptor_bytes({**BASE, **change}))


@pytest.mark.parametrize(
    "data",
    [
        b'{"x":1,"x":2}',
        b'{"x":{"y":1,"y":2}}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":0.5}',
        b'{"x":1e2}',
        b"\xef\xbb\xbf{}",
        b"\xff",
        b'{"name":"\\ud800"}',
        b"[]",
        b"{}",
        b"",
    ],
)
def test_json_malformed_fails_closed(data: bytes) -> None:
    with pytest.raises(PackageDescriptorError):
        parse_package_descriptor(data)


def test_digest_tamper_missing_name_and_oversize() -> None:
    packet = json.loads(descriptor_bytes(BASE))
    packet["manifest_digest"] = "0" * 64
    with pytest.raises(PackageDescriptorError):
        parse_package_descriptor(descriptor_bytes(packet, resign=False))
    missing = dict(BASE)
    del missing["name"]
    with pytest.raises(PackageDescriptorError):
        parse_package_descriptor(descriptor_bytes(missing))
    with pytest.raises(PackageDescriptorError):
        parse_package_descriptor(b" " * 262145)
