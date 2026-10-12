"""D2-A: Linux kernel-backed trusted local package loader tests."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

from agent_core.domain_package_loader import (
    HostPackageRootIssuer,
    HostPublishedGeneration,
    LocalPackageLoader,
    PackageLoadCode,
    PackageLoadError,
    TrustedPackageIdentity,
)

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux-only secure FD loading"
)

DOMAIN = "inventory.reconcile"


def package_bytes(
    assets: list[dict[str, str]], *, enabled: bool = True
) -> tuple[bytes, str]:
    payload = {
        "asset_refs": assets,
        "domain_id": DOMAIN,
        "domain_version": "1.0.0",
        "enabled": enabled,
        "name": "Inventory Reconciliation",
        "package_schema_version": "1",
        "runtime_compatibility": "GA02-D1-1",
    }
    ordered = sorted(
        assets,
        key=lambda v: (
            v["kind"],
            v["namespace"],
            v["id"],
            v["version"],
            v["relative_path"],
        ),
    )
    payload["asset_refs"] = ordered
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    digest = hashlib.sha256(canonical).hexdigest()
    payload["manifest_digest"] = digest
    return json.dumps(payload).encode(), digest


def ref(path: str, content: bytes, *, item: str = "stock.count") -> dict[str, str]:
    return {
        "kind": "action",
        "namespace": DOMAIN,
        "id": item,
        "version": "1.0.0",
        "sha256": hashlib.sha256(content).hexdigest(),
        "relative_path": path,
    }


def prepare(
    tmp_path: Path,
    assets: list[tuple[str, bytes, str]] | None = None,
    *,
    enabled: bool = True,
):
    items = (
        assets
        if assets is not None
        else [
            ("actions/a.txt", b"first", "stock.count"),
            ("prompts/b.txt", b"second", "stock.inspect"),
        ]
    )
    refs = []
    for name, data, ident in items:
        file = tmp_path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)
        refs.append(ref(name, data, item=ident))
    data, digest = package_bytes(refs, enabled=enabled)
    (tmp_path / "package.json").write_bytes(data)
    identity = TrustedPackageIdentity(
        "generation-1", DOMAIN, "1.0.0", "GA02-D1-1", digest
    )
    issuer = HostPackageRootIssuer(
        (HostPublishedGeneration(identity, str(tmp_path), True),)
    )
    return issuer, identity


def load(issuer: HostPackageRootIssuer, identity: TrustedPackageIdentity):
    with issuer.issue(identity.generation_id) as lease:
        return LocalPackageLoader().load(lease, identity)


def expect(code: PackageLoadCode, fn) -> None:
    with pytest.raises(PackageLoadError) as error:
        fn()
    assert error.value.code is code
    assert str(error.value) == code.value


def test_two_assets_are_owned_immutable_bytes_and_fd_lifetime(tmp_path: Path) -> None:
    issuer, identity = prepare(tmp_path)
    lease = issuer.issue(identity.generation_id)
    with lease:
        snapshot = LocalPackageLoader().load(lease, identity)
        assert len(snapshot.assets) == 2
        assert all(type(asset.content_bytes) is bytes for asset in snapshot.assets)
        assert {a.content_bytes for a in snapshot.assets} == {b"first", b"second"}
    (tmp_path / "actions/a.txt").write_bytes(b"changed")
    assert {a.content_bytes for a in snapshot.assets} == {b"first", b"second"}
    expect(
        PackageLoadCode.UNTRUSTED_PACKAGE_SOURCE,
        lambda: LocalPackageLoader().load(lease, identity),
    )


def test_empty_descriptor_is_inert_snapshot(tmp_path: Path) -> None:
    issuer, identity = prepare(tmp_path, [])
    assert load(issuer, identity).assets == ()


def test_host_digest_mismatch_is_denied(tmp_path: Path) -> None:
    issuer, _identity = prepare(tmp_path)
    changed = TrustedPackageIdentity(
        "generation-1", DOMAIN, "1.0.0", "GA02-D1-1", "a" * 64
    )
    expect(PackageLoadCode.UNTRUSTED_PACKAGE_SOURCE, lambda: load(issuer, changed))
    # A trusted publisher can be wrong: a mismatching allowlisted digest still denies.
    false_issuer = HostPackageRootIssuer(
        (HostPublishedGeneration(changed, str(tmp_path), True),)
    )
    expect(
        PackageLoadCode.PACKAGE_DESCRIPTOR_DIGEST_MISMATCH,
        lambda: load(false_issuer, changed),
    )


def test_disabled_descriptor(tmp_path: Path) -> None:
    issuer, identity = prepare(tmp_path, enabled=False)
    expect(PackageLoadCode.PACKAGE_DISABLED, lambda: load(issuer, identity))


def test_asset_sha_mismatch(tmp_path: Path) -> None:
    issuer, identity = prepare(tmp_path)
    (tmp_path / "actions/a.txt").write_bytes(b"tampered")
    expect(
        PackageLoadCode.PACKAGE_ASSET_INTEGRITY_FAILURE, lambda: load(issuer, identity)
    )


def test_symlink_asset_is_not_followed(tmp_path: Path) -> None:
    issuer, identity = prepare(tmp_path)
    file = tmp_path / "actions/a.txt"
    file.unlink()
    file.symlink_to(tmp_path / "prompts/b.txt")
    expect(PackageLoadCode.PACKAGE_ROOT_UNSAFE, lambda: load(issuer, identity))


def test_symlink_directory_is_not_followed(tmp_path: Path) -> None:
    issuer, identity = prepare(tmp_path)
    file = tmp_path / "actions/a.txt"
    file.unlink()
    (tmp_path / "actions").rmdir()
    (tmp_path / "actions").symlink_to(tmp_path / "prompts", target_is_directory=True)
    expect(PackageLoadCode.PACKAGE_ROOT_UNSAFE, lambda: load(issuer, identity))


def test_hardlink_is_denied(tmp_path: Path) -> None:
    issuer, identity = prepare(tmp_path)
    os.link(tmp_path / "actions/a.txt", tmp_path / "actions/alias")
    expect(PackageLoadCode.PACKAGE_ROOT_UNSAFE, lambda: load(issuer, identity))


def test_asset_over_limit(tmp_path: Path) -> None:
    issuer, identity = prepare(tmp_path)
    (tmp_path / "actions/a.txt").write_bytes(b"x" * (1_048_576 + 1))
    expect(PackageLoadCode.PACKAGE_RESOURCE_LIMIT, lambda: load(issuer, identity))


def test_untrusted_generation_is_denied(tmp_path: Path) -> None:
    issuer, identity = prepare(tmp_path)
    expect(PackageLoadCode.UNTRUSTED_PACKAGE_SOURCE, lambda: issuer.issue("unknown"))
    expect(
        PackageLoadCode.UNTRUSTED_PACKAGE_SOURCE,
        lambda: LocalPackageLoader().load(object(), identity),  # type: ignore[arg-type]
    )


def test_unsealed_generation_is_denied(tmp_path: Path) -> None:
    _issuer, identity = prepare(tmp_path)
    bad = HostPackageRootIssuer(
        (HostPublishedGeneration(identity, str(tmp_path), False),)
    )
    expect(PackageLoadCode.UNTRUSTED_PACKAGE_SOURCE, lambda: load(bad, identity))


def test_descriptor_is_not_a_tool_or_registry(tmp_path: Path) -> None:
    issuer, identity = prepare(tmp_path)
    snapshot = load(issuer, identity)
    assert not hasattr(snapshot, "execute")
    assert not hasattr(snapshot, "register")
    assert not hasattr(snapshot, "binding_fingerprint")

def test_missing_asset_is_integrity_failure(tmp_path: Path) -> None:
    issuer, identity = prepare(tmp_path)
    (tmp_path / "actions/a.txt").unlink()
    expect(PackageLoadCode.PACKAGE_ASSET_INTEGRITY_FAILURE, lambda: load(issuer, identity))


def test_symlink_descriptor_is_denied(tmp_path: Path) -> None:
    issuer, identity = prepare(tmp_path)
    source = tmp_path / "saved_package.json"
    (tmp_path / "package.json").rename(source)
    (tmp_path / "package.json").symlink_to(source)
    expect(PackageLoadCode.PACKAGE_ROOT_UNSAFE, lambda: load(issuer, identity))


def test_lease_cannot_be_reused_after_close(tmp_path: Path) -> None:
    issuer, identity = prepare(tmp_path)
    with issuer.issue(identity.generation_id) as lease:
        assert LocalPackageLoader().load(lease, identity).assets
    assert lease._fd not in issuer._live
    expect(
        PackageLoadCode.UNTRUSTED_PACKAGE_SOURCE,
        lambda: LocalPackageLoader().load(lease, identity),
    )
