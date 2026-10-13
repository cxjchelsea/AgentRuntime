"""GA-07 Slice C: package-owned Prompt/Rule/Knowledge inert content contracts.

Package bytes are verified against the D2-A asset refs. The resulting content
does not authorize tools, policy overrides, or publisher provenance.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from agent_core.domain_extension import DomainExtension, DomainExtensionError
from agent_core.domain_package_loader import VerifiedPackageSnapshotV1


@dataclass(frozen=True, slots=True)
class DomainContent:
    focus: str
    knowledge_key: str
    knowledge_fact: str
    required_knowledge: str
    completion_after: str


def _asset_object(raw: bytes, fields: frozenset[str]) -> dict[str, str]:
    if type(raw) is not bytes or len(raw) > 4096:
        raise DomainExtensionError("invalid domain content asset")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise DomainExtensionError("duplicate domain content key")
            result[key] = value
        return result

    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise DomainExtensionError("invalid domain content JSON") from exc
    if (
        type(data) is not dict
        or data.keys() != fields
        or any(
            type(value) is not str or not 1 <= len(value) <= 256
            for value in data.values()
        )
    ):
        raise DomainExtensionError("invalid domain content schema")
    return data


def assemble_domain_content(
    snapshot: VerifiedPackageSnapshotV1, extension: DomainExtension
) -> DomainContent:
    """Bind all three content assets to precisely one assembled package."""
    if (
        type(snapshot) is not VerifiedPackageSnapshotV1
        or type(extension) is not DomainExtension
    ):
        raise DomainExtensionError("invalid content assembly inputs")
    binding = extension.binding
    if (
        snapshot.generation_id != binding.generation_id
        or snapshot.descriptor.domain_id != binding.domain_id
        or snapshot.descriptor.domain_version != binding.domain_version
        or snapshot.descriptor.manifest_digest != binding.manifest_digest
    ):
        raise DomainExtensionError("content extension package mismatch")
    present: dict[str, dict[str, str]] = {}
    schemas = {
        "prompt": frozenset({"focus"}),
        "rule": frozenset({"required_knowledge", "completion_after"}),
        "knowledge": frozenset({"key", "fact"}),
    }
    for asset in snapshot.assets:
        kind = asset.ref.kind
        if kind not in schemas:
            continue
        if (
            kind in present
            or asset.ref.namespace != binding.domain_id
            or asset.ref.version != "1.0.0"
            or hashlib.sha256(asset.content_bytes).hexdigest() != asset.ref.sha256
        ):
            raise DomainExtensionError("duplicate or invalid domain content asset")
        present[kind] = _asset_object(asset.content_bytes, schemas[kind])
    if set(present) != set(schemas):
        raise DomainExtensionError("missing required domain content asset")
    prompt, rule, knowledge = present["prompt"], present["rule"], present["knowledge"]
    if rule["required_knowledge"] != knowledge["key"]:
        raise DomainExtensionError("rule requires different knowledge key")
    if rule["completion_after"] not in {"collect", "verify"}:
        raise DomainExtensionError("unsupported sandbox completion rule")
    return DomainContent(
        focus=prompt["focus"],
        knowledge_key=knowledge["key"],
        knowledge_fact=knowledge["fact"],
        required_knowledge=rule["required_knowledge"],
        completion_after=rule["completion_after"],
    )
