"""D2-A: Linux kernel-backed trusted local package loader tests."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
from pathlib import Path

import pytest

import agent_core.domain_package_loader as loader_mod
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
        (HostPublishedGeneration(identity, str(tmp_path), True),),
        publication_verifier=lambda record: (
            record.sealed and record.absolute_root == str(tmp_path)
        ),
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
        (HostPublishedGeneration(changed, str(tmp_path), True),),
        publication_verifier=lambda record: (
            record.sealed and record.absolute_root == str(tmp_path)
        ),
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
        (HostPublishedGeneration(identity, str(tmp_path), False),),
        publication_verifier=lambda record: (
            record.sealed and record.absolute_root == str(tmp_path)
        ),
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
    expect(
        PackageLoadCode.PACKAGE_ASSET_INTEGRITY_FAILURE, lambda: load(issuer, identity)
    )


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
    assert lease._issuance not in issuer._live
    expect(
        PackageLoadCode.UNTRUSTED_PACKAGE_SOURCE,
        lambda: LocalPackageLoader().load(lease, identity),
    )


def test_host_verifier_rejects_untrusted_publisher(tmp_path: Path) -> None:
    _issuer, identity = prepare(tmp_path)
    rejected = HostPackageRootIssuer(
        (HostPublishedGeneration(identity, str(tmp_path), True),),
        publication_verifier=lambda _entry: False,
    )
    expect(PackageLoadCode.UNTRUSTED_PACKAGE_SOURCE, lambda: load(rejected, identity))


def test_absolute_root_intermediate_symlink_denied(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    _issuer, identity = prepare(real)
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    unsafe = HostPackageRootIssuer(
        (HostPublishedGeneration(identity, str(alias), True),),
        publication_verifier=lambda entry: entry.absolute_root == str(alias),
    )
    expect(PackageLoadCode.PACKAGE_ROOT_UNSAFE, lambda: load(unsafe, identity))


def test_descriptor_max_bytes_denied(tmp_path: Path) -> None:
    issuer, identity = prepare(tmp_path)
    (tmp_path / "package.json").write_bytes(b"x" * 262145)
    expect(PackageLoadCode.PACKAGE_RESOURCE_LIMIT, lambda: load(issuer, identity))


def test_duplicate_asset_relative_path_denied(tmp_path: Path) -> None:
    _issuer, identity = prepare(tmp_path)
    refs = [
        ref("actions/a.txt", b"first", item="stock.count"),
        ref("actions/a.txt", b"first", item="stock.inspect"),
    ]
    data, digest = package_bytes(refs)
    (tmp_path / "package.json").write_bytes(data)
    updated = TrustedPackageIdentity(
        identity.generation_id, DOMAIN, "1.0.0", "GA02-D1-1", digest
    )
    issuer = HostPackageRootIssuer(
        (HostPublishedGeneration(updated, str(tmp_path), True),),
        publication_verifier=lambda entry: entry.absolute_root == str(tmp_path),
    )
    expect(
        PackageLoadCode.PACKAGE_ASSET_INTEGRITY_FAILURE,
        lambda: load(issuer, updated),
    )


def test_fifo_asset_denied_without_block(tmp_path: Path) -> None:
    issuer, identity = prepare(tmp_path)
    asset = tmp_path / "actions/a.txt"
    asset.unlink()
    os.mkfifo(asset)
    expect(PackageLoadCode.PACKAGE_ROOT_UNSAFE, lambda: load(issuer, identity))


def test_stale_lease_issuance_not_reused(tmp_path: Path) -> None:
    issuer, identity = prepare(tmp_path)
    first = issuer.issue(identity.generation_id)
    first.close()
    second = issuer.issue(identity.generation_id)
    try:
        assert first._issuance is not second._issuance
        expect(
            PackageLoadCode.UNTRUSTED_PACKAGE_SOURCE,
            lambda: LocalPackageLoader().load(first, identity),
        )
        with second:
            assert LocalPackageLoader().load(second, identity).assets
    finally:
        second.close()


def test_nested_load_same_lease_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issuer, identity = prepare(tmp_path)
    actual = loader_mod._read_open_fd
    counter = 0

    def guarded_read(fd: int, limit: int) -> bytes:
        nonlocal counter
        counter += 1
        if counter == 1:
            expect(
                PackageLoadCode.UNTRUSTED_PACKAGE_SOURCE,
                lambda: LocalPackageLoader().load(lease, identity),
            )
        return actual(fd, limit)

    with issuer.issue(identity.generation_id) as lease:
        monkeypatch.setattr(loader_mod, "_read_open_fd", guarded_read)
        assert LocalPackageLoader().load(lease, identity).assets


def test_concurrent_close_waits_for_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issuer, identity = prepare(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    close_started = threading.Event()
    close_finished = threading.Event()
    errors: list[BaseException] = []
    original = loader_mod._read_open_fd

    def blocked(fd: int, limit: int) -> bytes:
        entered.set()
        if not release.wait(5):
            raise AssertionError("loader timeout")
        return original(fd, limit)

    lease = issuer.issue(identity.generation_id)
    lease.__enter__()
    monkeypatch.setattr(loader_mod, "_read_open_fd", blocked)

    def reader() -> None:
        try:
            LocalPackageLoader().load(lease, identity)
        except BaseException as exc:  # noqa: BLE001  # Capture worker failures.
            errors.append(exc)

    def closer() -> None:
        close_started.set()
        try:
            lease.close()
        except BaseException as exc:  # noqa: BLE001  # Capture worker failures.
            errors.append(exc)
        finally:
            close_finished.set()

    worker = threading.Thread(target=reader)
    stopper = threading.Thread(target=closer)
    try:
        worker.start()
        assert entered.wait(5)
        stopper.start()
        assert close_started.wait(5)
        assert not close_finished.wait(0.05)
    finally:
        release.set()
        worker.join(timeout=5)
        stopper.join(timeout=5)
        lease.close()
    assert not worker.is_alive() and not stopper.is_alive()
    assert not errors


def test_injected_asset_io_error_releases_fds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issuer, identity = prepare(tmp_path)
    initial = len(os.listdir("/proc/self/fd"))
    actual = loader_mod._read_open_fd
    count = 0

    def broken(fd: int, limit: int) -> bytes:
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("injected read failure")
        return actual(fd, limit)

    monkeypatch.setattr(loader_mod, "_read_open_fd", broken)
    expect(PackageLoadCode.PACKAGE_IO_FAILURE, lambda: load(issuer, identity))
    assert issuer._live == {}
    assert len(os.listdir("/proc/self/fd")) == initial


def test_injected_base_exception_releases_fds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issuer, identity = prepare(tmp_path)
    initial = len(os.listdir("/proc/self/fd"))
    actual = loader_mod._read_open_fd
    count = 0

    def interrupted(fd: int, limit: int) -> bytes:
        nonlocal count
        count += 1
        if count == 2:
            raise KeyboardInterrupt()
        return actual(fd, limit)

    monkeypatch.setattr(loader_mod, "_read_open_fd", interrupted)
    with pytest.raises(KeyboardInterrupt):
        load(issuer, identity)
    assert issuer._live == {}
    assert len(os.listdir("/proc/self/fd")) == initial


def test_unsupported_profile_is_typed(tmp_path: Path) -> None:
    _issuer, identity = prepare(tmp_path)
    unsupported = TrustedPackageIdentity(
        identity.generation_id,
        identity.domain_id,
        identity.domain_version,
        "WRONG-PROFILE",
        identity.expected_manifest_digest,
    )
    issuer = HostPackageRootIssuer(
        (HostPublishedGeneration(unsupported, str(tmp_path), True),),
        publication_verifier=lambda entry: entry.absolute_root == str(tmp_path),
    )
    expect(
        PackageLoadCode.PACKAGE_PROFILE_MISMATCH,
        lambda: load(issuer, unsupported),
    )

def test_issuer_checks_lease_object_identity(tmp_path: Path) -> None:
    issuer, identity = prepare(tmp_path)
    with issuer.issue(identity.generation_id) as lease:
        original = lease._issuance
        lease._issuance = object()
        expect(
            PackageLoadCode.PACKAGE_ROOT_UNSAFE,
            lambda: LocalPackageLoader().load(lease, identity),
        )
        lease._issuance = original
        assert LocalPackageLoader().load(lease, identity).assets


def test_publisher_verification_revoked_during_lease(tmp_path: Path) -> None:
    _issuer, identity = prepare(tmp_path)
    allowed = [True]
    issuer = HostPackageRootIssuer(
        (HostPublishedGeneration(identity, str(tmp_path), True),),
        publication_verifier=lambda _entry: allowed[0],
    )
    with issuer.issue(identity.generation_id) as lease:
        allowed[0] = False
        expect(
            PackageLoadCode.UNTRUSTED_PACKAGE_SOURCE,
            lambda: LocalPackageLoader().load(lease, identity),
        )


def test_file_stat_change_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issuer, identity = prepare(tmp_path)
    real_fstat = loader_mod.os.fstat
    calls = 0

    def altered(fd: int) -> os.stat_result:
        nonlocal calls
        info = real_fstat(fd)
        if info.st_size == 5:
            calls += 1
            if calls == 3:
                values = list(info)
                values[6] += 1
                return os.stat_result(values)
        return info

    monkeypatch.setattr(loader_mod.os, "fstat", altered)
    expect(
        PackageLoadCode.PACKAGE_READ_UNSTABLE,
        lambda: load(issuer, identity),
    )


def test_close_os_failure_revokes_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issuer, identity = prepare(tmp_path)
    lease = issuer.issue(identity.generation_id)
    real_close = loader_mod.os.close

    def close_then_fail(fd: int) -> None:
        real_close(fd)
        if fd == lease._fd:
            raise OSError("simulated uncertain close outcome")

    monkeypatch.setattr(loader_mod.os, "close", close_then_fail)
    expect(PackageLoadCode.PACKAGE_IO_FAILURE, lease.close)
    assert lease._closed
    assert lease._issuance not in issuer._live
    expect(
        PackageLoadCode.UNTRUSTED_PACKAGE_SOURCE,
        lambda: LocalPackageLoader().load(lease, identity),
    )


def test_root_generation_rename_does_not_change_pinned_fd(tmp_path: Path) -> None:
    generation = tmp_path / "generation"
    generation.mkdir()
    issuer, identity = prepare(generation)
    with issuer.issue(identity.generation_id) as lease:
        generation.rename(tmp_path / "renamed")
        assert LocalPackageLoader().load(lease, identity).assets
