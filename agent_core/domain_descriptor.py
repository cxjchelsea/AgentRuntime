"""GA-02 D1: strict inert package descriptor. No IO, registry mutation or tools."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from runtime.registries.definitions import DomainManifest

PROFILE = "GA02-D1-1"
MAX_BYTES = 262144
MAX_ASSETS = 256
_ID = re.compile(r"[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*\Z", re.ASCII)
_VERSION = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z", re.ASCII
)
_SHA = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_KINDS = frozenset(
    {
        "action",
        "strategy",
        "skill",
        "tool",
        "workflow",
        "capability",
        "prompt",
        "knowledge",
        "rule",
        "schema",
        "state",
        "eval",
    }
)
_TOP = frozenset(
    {
        "package_schema_version",
        "domain_id",
        "domain_version",
        "name",
        "enabled",
        "runtime_compatibility",
        "asset_refs",
        "manifest_digest",
        "feature_flags",
    }
)
_ASSET = frozenset({"kind", "namespace", "id", "version", "sha256", "relative_path"})


class PackageDescriptorError(ValueError):
    """Invalid package; never usable for registration or inference."""


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in items:
        if key in out:
            raise PackageDescriptorError("duplicate JSON key")
        out[key] = value
    return out


def _bad_number(_value: str) -> None:
    raise PackageDescriptorError("non-integer JSON number")


def _object(
    value: object, required: frozenset[str], allowed: frozenset[str]
) -> dict[str, Any]:
    if (
        type(value) is not dict
        or not required <= value.keys()
        or not value.keys() <= allowed
    ):
        raise PackageDescriptorError("missing or unknown descriptor fields")
    return value


def _string(value: object, field: str, limit: int) -> str:
    if type(value) is not str or not value or len(value) > limit:
        raise PackageDescriptorError(f"invalid {field}")
    if unicodedata.normalize("NFC", value) != value:
        raise PackageDescriptorError(f"non-NFC {field}")
    if any(unicodedata.category(ch) in {"Cc", "Cs"} for ch in value):
        raise PackageDescriptorError(f"invalid Unicode {field}")
    return value


def _identifier(value: object, field: str) -> str:
    s = _string(value, field, 80)
    if not _ID.fullmatch(s):
        raise PackageDescriptorError(f"invalid {field}")
    return s


def _version(value: object, field: str) -> str:
    s = _string(value, field, 32)
    if not _VERSION.fullmatch(s):
        raise PackageDescriptorError(f"invalid {field}")
    return s


def _path(value: object) -> str:
    s = _string(value, "relative_path", 512)
    if (
        s.startswith("/")
        or "\\" in s
        or "%" in s
        or ":" in s
        or any(p in {"", ".", ".."} for p in s.split("/"))
        or str(PurePosixPath(s)) != s
    ):
        raise PackageDescriptorError("unsafe asset path")
    return s


@dataclass(frozen=True, slots=True)
class AssetReferenceV1:
    kind: str
    namespace: str
    id: str
    version: str
    sha256: str
    relative_path: str


@dataclass(frozen=True, slots=True)
class PackageDescriptorV1:
    package_schema_version: str
    domain_id: str
    domain_version: str
    name: str
    enabled: bool
    runtime_compatibility: str
    asset_refs: tuple[AssetReferenceV1, ...]
    manifest_digest: str


def parse_package_descriptor(
    raw: bytes, *, supported_profile: str = PROFILE
) -> PackageDescriptorV1:
    """Parse exact versioned JSON bytes without touching packages or Registries."""
    if type(raw) is not bytes or not raw or len(raw) > MAX_BYTES:
        raise PackageDescriptorError("bad descriptor bytes or size")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise PackageDescriptorError("UTF-8 BOM is forbidden")
    try:
        data = json.loads(
            raw.decode("utf-8", "strict"),
            object_pairs_hook=_pairs,
            parse_constant=_bad_number,
            parse_float=_bad_number,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise PackageDescriptorError("invalid descriptor JSON") from exc
    top = _object(data, _TOP - {"feature_flags"}, _TOP)
    if (
        type(top["package_schema_version"]) is not str
        or top["package_schema_version"] != "1"
    ):
        raise PackageDescriptorError("unsupported package schema")
    domain = _identifier(top["domain_id"], "domain_id")
    version = _version(top["domain_version"], "domain_version")
    name = _string(top["name"], "name", 120)
    if name != name.strip():
        raise PackageDescriptorError("name whitespace")
    if type(top["enabled"]) is not bool:
        raise PackageDescriptorError("enabled must be boolean")
    profile = _string(top["runtime_compatibility"], "runtime_compatibility", 80)
    if type(supported_profile) is not str or profile != supported_profile:
        raise PackageDescriptorError("incompatible runtime")
    digest = top["manifest_digest"]
    if type(digest) is not str or not _SHA.fullmatch(digest):
        raise PackageDescriptorError("invalid manifest digest")
    if "feature_flags" in top and top["feature_flags"] != []:
        raise PackageDescriptorError("unsupported feature flags")
    if type(top["asset_refs"]) is not list or len(top["asset_refs"]) > MAX_ASSETS:
        raise PackageDescriptorError("invalid assets")
    refs: list[AssetReferenceV1] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in top["asset_refs"]:
        ref = _object(item, _ASSET, _ASSET)
        kind = _string(ref["kind"], "kind", 24)
        if kind not in _KINDS:
            raise PackageDescriptorError("unknown asset kind")
        namespace = (
            "CORE"
            if ref["namespace"] == "CORE" and kind == "schema"
            else _identifier(ref["namespace"], "namespace")
        )
        if namespace not in {domain, "CORE"}:
            raise PackageDescriptorError("foreign namespace")
        item_id = _identifier(ref["id"], "asset_id")
        item_version = _version(ref["version"], "asset_version")
        sha = ref["sha256"]
        if type(sha) is not str or not _SHA.fullmatch(sha):
            raise PackageDescriptorError("invalid asset digest")
        path = _path(ref["relative_path"])
        key = (kind, namespace, item_id, item_version)
        if key in seen:
            raise PackageDescriptorError("duplicate asset")
        seen.add(key)
        refs.append(AssetReferenceV1(kind, namespace, item_id, item_version, sha, path))
    refs.sort(key=lambda r: (r.kind, r.namespace, r.id, r.version, r.relative_path))
    canonical: dict[str, Any] = {
        "package_schema_version": "1",
        "domain_id": domain,
        "domain_version": version,
        "name": name,
        "enabled": top["enabled"],
        "runtime_compatibility": profile,
        "asset_refs": [
            {
                "kind": r.kind,
                "namespace": r.namespace,
                "id": r.id,
                "version": r.version,
                "sha256": r.sha256,
                "relative_path": r.relative_path,
            }
            for r in refs
        ],
    }
    if "feature_flags" in top:
        canonical["feature_flags"] = []
    byte_value = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8", "strict")
    if hashlib.sha256(byte_value).hexdigest() != digest:
        raise PackageDescriptorError("manifest digest mismatch")
    return PackageDescriptorV1(
        "1", domain, version, name, top["enabled"], profile, tuple(refs), digest
    )


def descriptor_to_domain_manifest(descriptor: PackageDescriptorV1) -> DomainManifest:
    """Pure metadata adapter: no Registry writes and no execution permission."""
    if type(descriptor) is not PackageDescriptorV1:
        raise PackageDescriptorError("not a validated descriptor")
    return DomainManifest(
        domain_id=descriptor.domain_id,
        name=descriptor.name,
        version=descriptor.domain_version,
        enabled=descriptor.enabled,
        runtime_compatibility=descriptor.runtime_compatibility,
    )
