"""GA-02 D2-A: inert, Linux-only, host-pinned domain package byte loader.

No registry, tool, model, filesystem writes or domain execution authority.
The trusted host must publish immutable SEALED generations; stat checks alone
cannot detect every concurrent in-place write.
"""

from __future__ import annotations

import hashlib
import os
import stat
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Final, Self

from agent_core.domain_descriptor import (
    MAX_ASSETS,
    MAX_BYTES,
    PROFILE,
    AssetReferenceV1,
    PackageDescriptorError,
    PackageDescriptorV1,
    parse_package_descriptor,
)

_MAX_ASSET: Final = 1_048_576
_MAX_TOTAL: Final = 16_777_216
_MAX_DEPTH: Final = 12
_CHUNK: Final = 65_536
_REQUIRED_FLAGS: Final = ("O_NOFOLLOW", "O_DIRECTORY", "O_CLOEXEC", "O_NONBLOCK")
_LEASE_TOKEN = object()


class PackageLoadCode(str, Enum):
    UNTRUSTED_PACKAGE_SOURCE = "UNTRUSTED_PACKAGE_SOURCE"
    PACKAGE_ROOT_UNSAFE = "PACKAGE_ROOT_UNSAFE"
    PACKAGE_DESCRIPTOR_INVALID = "PACKAGE_DESCRIPTOR_INVALID"
    PACKAGE_DESCRIPTOR_DIGEST_MISMATCH = "PACKAGE_DESCRIPTOR_DIGEST_MISMATCH"
    PACKAGE_DISABLED = "PACKAGE_DISABLED"
    PACKAGE_PROFILE_MISMATCH = "PACKAGE_PROFILE_MISMATCH"
    PACKAGE_READ_UNSTABLE = "PACKAGE_READ_UNSTABLE"
    PACKAGE_ASSET_INTEGRITY_FAILURE = "PACKAGE_ASSET_INTEGRITY_FAILURE"
    PACKAGE_RESOURCE_LIMIT = "PACKAGE_RESOURCE_LIMIT"
    PACKAGE_IO_FAILURE = "PACKAGE_IO_FAILURE"


class PackageLoadError(ValueError):
    """Stable error code only; never include file paths or package bytes."""

    def __init__(self, code: PackageLoadCode) -> None:
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
class TrustedPackageIdentity:
    generation_id: str
    domain_id: str
    domain_version: str
    runtime_profile: str
    expected_manifest_digest: str


@dataclass(frozen=True, slots=True)
class HostPublishedGeneration:
    """Issued by the trusted host, never constructed from package JSON."""

    identity: TrustedPackageIdentity
    absolute_root: str
    sealed: bool


@dataclass(frozen=True, slots=True)
class VerifiedAssetV1:
    ref: AssetReferenceV1
    content_bytes: bytes


@dataclass(frozen=True, slots=True)
class VerifiedPackageSnapshotV1:
    descriptor: PackageDescriptorV1
    descriptor_bytes: bytes
    assets: tuple[VerifiedAssetV1, ...]
    generation_id: str
    expected_manifest_digest: str


def _linux() -> None:
    if (
        not sys.platform.startswith("linux")
        or not hasattr(os, "supports_dir_fd")
        or os.open not in os.supports_dir_fd
        or any(not hasattr(os, flag) for flag in _REQUIRED_FLAGS)
    ):
        raise PackageLoadError(PackageLoadCode.PACKAGE_ROOT_UNSAFE)


def _identity_of(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _directory(info: os.stat_result, root_device: int) -> None:
    if not stat.S_ISDIR(info.st_mode) or info.st_dev != root_device:
        raise PackageLoadError(PackageLoadCode.PACKAGE_ROOT_UNSAFE)


class TrustedPackageRootLease:
    """Opaque FD lifetime; only HostPackageRootIssuer can mint a live lease."""

    __slots__ = ("_active", "_closed", "_fd", "_identity", "_owner")

    def __init__(
        self,
        token: object,
        fd: int,
        identity: TrustedPackageIdentity,
        owner: object,
    ) -> None:
        if token is not _LEASE_TOKEN:
            raise PackageLoadError(PackageLoadCode.UNTRUSTED_PACKAGE_SOURCE)
        self._fd = fd
        self._identity = identity
        self._owner = owner
        self._closed = False
        self._active = False

    def __enter__(self) -> Self:
        if self._closed or self._active:
            raise PackageLoadError(PackageLoadCode.UNTRUSTED_PACKAGE_SOURCE)
        self._active = True
        return self

    def __exit__(self, _type: object, _value: object, _trace: object) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._active = False
            os.close(self._fd)


class HostPackageRootIssuer:
    """Trusted application bootstrap interface; no package-controlled input.

    'sealed' is an assertion by the host publisher and must be independently
    enforced by deployment. This class does not implement a publisher.
    """

    def __init__(self, generations: tuple[HostPublishedGeneration, ...]) -> None:
        self._catalog: dict[str, HostPublishedGeneration] = {}
        for generation in generations:
            ident = generation.identity
            if (
                type(generation.absolute_root) is not str
                or not os.path.isabs(generation.absolute_root)
                or type(ident.generation_id) is not str
                or not ident.generation_id
                or ident.generation_id in self._catalog
                or type(ident.expected_manifest_digest) is not str
                or len(ident.expected_manifest_digest) != 64
                or any(
                    ch not in "0123456789abcdef"
                    for ch in ident.expected_manifest_digest
                )
            ):
                raise PackageLoadError(PackageLoadCode.UNTRUSTED_PACKAGE_SOURCE)
            self._catalog[ident.generation_id] = generation
        self._live: dict[int, tuple[int, int]] = {}

    def issue(self, generation_id: str) -> TrustedPackageRootLease:
        _linux()
        record = self._catalog.get(generation_id)
        if record is None or record.sealed is not True:
            raise PackageLoadError(PackageLoadCode.UNTRUSTED_PACKAGE_SOURCE)
        fd = -1
        try:
            fd = os.open(
                record.absolute_root,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
            info = os.fstat(fd)
            _directory(info, info.st_dev)
            self._live[fd] = (info.st_dev, info.st_ino)
            return TrustedPackageRootLease(_LEASE_TOKEN, fd, record.identity, self)
        except OSError as exc:
            if fd >= 0:
                os.close(fd)
            raise PackageLoadError(PackageLoadCode.PACKAGE_ROOT_UNSAFE) from exc

    def _check(
        self, lease: TrustedPackageRootLease, expected: TrustedPackageIdentity
    ) -> tuple[int, int]:
        if (
            type(lease) is not TrustedPackageRootLease
            or lease._owner is not self
            or lease._closed
            or not lease._active
            or lease._identity != expected
        ):
            raise PackageLoadError(PackageLoadCode.UNTRUSTED_PACKAGE_SOURCE)
        actual = self._catalog.get(expected.generation_id)
        if actual is None or actual.sealed is not True or actual.identity != expected:
            raise PackageLoadError(PackageLoadCode.UNTRUSTED_PACKAGE_SOURCE)
        try:
            info = os.fstat(lease._fd)
        except OSError as exc:
            raise PackageLoadError(PackageLoadCode.PACKAGE_ROOT_UNSAFE) from exc
        pinned = self._live.get(lease._fd)
        if pinned is None or pinned != (info.st_dev, info.st_ino):
            raise PackageLoadError(PackageLoadCode.PACKAGE_ROOT_UNSAFE)
        return pinned


def _read_open_fd(fd: int, max_bytes: int) -> bytes:
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise PackageLoadError(PackageLoadCode.PACKAGE_ROOT_UNSAFE)
    if before.st_size > max_bytes:
        raise PackageLoadError(PackageLoadCode.PACKAGE_RESOURCE_LIMIT)
    result = bytearray()
    while len(result) <= max_bytes:
        chunk = os.read(fd, min(_CHUNK, max_bytes + 1 - len(result)))
        if not chunk:
            break
        result.extend(chunk)
    if len(result) > max_bytes:
        raise PackageLoadError(PackageLoadCode.PACKAGE_RESOURCE_LIMIT)
    after = os.fstat(fd)
    if _identity_of(before) != _identity_of(after) or len(result) != before.st_size:
        raise PackageLoadError(PackageLoadCode.PACKAGE_READ_UNSTABLE)
    return bytes(result)


def _open_asset(
    root_fd: int, relative_path: str, root_device: int
) -> tuple[int, list[int]]:
    components = relative_path.split("/")
    if (
        len(components) > _MAX_DEPTH
        or any(x in {"", ".", ".."} for x in components)
        or relative_path.startswith("/")
    ):
        raise PackageLoadError(PackageLoadCode.PACKAGE_RESOURCE_LIMIT)
    opened: list[int] = []
    parent = root_fd
    try:
        for component in components[:-1]:
            fd = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent,
            )
            opened.append(fd)
            _directory(os.fstat(fd), root_device)
            parent = fd
        fd = os.open(
            components[-1],
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
            dir_fd=parent,
        )
        opened.append(fd)
        leaf = os.fstat(fd)
        if leaf.st_dev != root_device:
            raise PackageLoadError(PackageLoadCode.PACKAGE_ROOT_UNSAFE)
        return fd, opened
    except BaseException:
        for fd in reversed(opened):
            os.close(fd)
        raise


class LocalPackageLoader:
    """Never interprets assets or issues a DomainBinding."""

    def load(
        self,
        lease: TrustedPackageRootLease,
        expected: TrustedPackageIdentity,
    ) -> VerifiedPackageSnapshotV1:
        _linux()
        # The private issuer is the only authority to validate this lease.
        if type(lease) is not TrustedPackageRootLease:
            raise PackageLoadError(PackageLoadCode.UNTRUSTED_PACKAGE_SOURCE)
        owner = lease._owner
        if not isinstance(owner, HostPackageRootIssuer):
            raise PackageLoadError(PackageLoadCode.UNTRUSTED_PACKAGE_SOURCE)
        root_dev, _ = owner._check(lease, expected)
        descriptor_fd = -1
        try:
            descriptor_fd = os.open(
                "package.json",
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                dir_fd=lease._fd,
            )
            if os.fstat(descriptor_fd).st_dev != root_dev:
                raise PackageLoadError(PackageLoadCode.PACKAGE_ROOT_UNSAFE)
            raw = _read_open_fd(descriptor_fd, MAX_BYTES)
        except OSError as exc:
            raise PackageLoadError(PackageLoadCode.PACKAGE_IO_FAILURE) from exc
        finally:
            if descriptor_fd >= 0:
                os.close(descriptor_fd)
        try:
            descriptor = parse_package_descriptor(
                raw, supported_profile=expected.runtime_profile
            )
        except PackageDescriptorError as exc:
            raise PackageLoadError(PackageLoadCode.PACKAGE_DESCRIPTOR_INVALID) from exc
        if (
            descriptor.domain_id != expected.domain_id
            or descriptor.domain_version != expected.domain_version
        ):
            raise PackageLoadError(PackageLoadCode.PACKAGE_DESCRIPTOR_INVALID)
        if descriptor.runtime_compatibility != PROFILE:
            raise PackageLoadError(PackageLoadCode.PACKAGE_PROFILE_MISMATCH)
        if not descriptor.enabled:
            raise PackageLoadError(PackageLoadCode.PACKAGE_DISABLED)
        if descriptor.manifest_digest != expected.expected_manifest_digest:
            raise PackageLoadError(PackageLoadCode.PACKAGE_DESCRIPTOR_DIGEST_MISMATCH)
        if len(descriptor.asset_refs) > MAX_ASSETS:
            raise PackageLoadError(PackageLoadCode.PACKAGE_RESOURCE_LIMIT)
        assets: list[VerifiedAssetV1] = []
        paths: set[str] = set()
        inodes: set[tuple[int, int]] = set()
        total = 0
        for ref in descriptor.asset_refs:
            if ref.relative_path in paths:
                raise PackageLoadError(PackageLoadCode.PACKAGE_ASSET_INTEGRITY_FAILURE)
            paths.add(ref.relative_path)
            opened: list[int] = []
            try:
                asset_fd, opened = _open_asset(lease._fd, ref.relative_path, root_dev)
                info = os.fstat(asset_fd)
                identity = (info.st_dev, info.st_ino)
                if identity in inodes:
                    raise PackageLoadError(
                        PackageLoadCode.PACKAGE_ASSET_INTEGRITY_FAILURE
                    )
                inodes.add(identity)
                content = _read_open_fd(asset_fd, min(_MAX_ASSET, _MAX_TOTAL - total))
                if hashlib.sha256(content).hexdigest() != ref.sha256:
                    raise PackageLoadError(
                        PackageLoadCode.PACKAGE_ASSET_INTEGRITY_FAILURE
                    )
                total += len(content)
                assets.append(VerifiedAssetV1(ref, content))
            except OSError as exc:
                raise PackageLoadError(PackageLoadCode.PACKAGE_IO_FAILURE) from exc
            finally:
                for fd in reversed(opened):
                    os.close(fd)
        return VerifiedPackageSnapshotV1(
            descriptor, raw, tuple(assets),
            expected.generation_id, expected.expected_manifest_digest,
        )
