"""GA-07 Slice B bounded, non-authoritative package-to-M4 extension assembly.

Consumes existing GA-02 D2-A verified package snapshots. These Python objects
are not Host issuance credentials: the application must independently supply
an authentic publisher/issuer. No positive external execution grants here.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from agent_core.domain_descriptor import parse_package_descriptor
from agent_core.domain_package_loader import VerifiedAssetV1, VerifiedPackageSnapshotV1
from agent_core.iteration import AgentRunBinding
from runtime.contracts import RuntimeInput
from runtime.contracts.enums import PlanningMode
from runtime.registries import (
    ActionDefinition,
    ActionRegistry,
    IntrusivenessLevel,
    SkillDefinition,
    SkillRegistry,
    StrategyDefinition,
    StrategyRegistry,
)


class DomainExtensionError(ValueError):
    """Invalid inert package, never a partial registry or execution grant."""


@dataclass(frozen=True, slots=True)
class DomainExtensionBinding:
    domain_id: str
    domain_version: str
    generation_id: str
    manifest_digest: str
    binding_fingerprint: str

    def for_run(self, initial: RuntimeInput, *, run_id: str) -> AgentRunBinding:
        return AgentRunBinding.from_input(
            initial,
            run_id=run_id,
            domain_id=self.domain_id,
            domain_version=self.domain_version,
            binding_fingerprint=self.binding_fingerprint,
        )


@dataclass(frozen=True, slots=True)
class DomainExtension:
    binding: DomainExtensionBinding
    actions: ActionRegistry
    strategies: StrategyRegistry
    skills: SkillRegistry
    action_ids: tuple[str, ...]
    strategy_ids: tuple[str, ...]
    strategy_actions: tuple[tuple[str, str], ...]


def _strict_object(raw: bytes, fields: frozenset[str]) -> dict[str, str]:
    if type(raw) is not bytes or len(raw) > 4096:
        raise DomainExtensionError("invalid domain asset bytes")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, value in pairs:
            if name in out:
                raise DomainExtensionError("duplicate domain asset property")
            out[name] = value
        return out

    try:
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise DomainExtensionError("unparseable domain asset") from exc
    if (
        type(parsed) is not dict
        or parsed.keys() != fields
        or any(type(v) is not str or not 1 <= len(v) <= 128 for v in parsed.values())
    ):
        raise DomainExtensionError("invalid domain asset fields")
    return parsed


def assemble_domain_extension(snapshot: VerifiedPackageSnapshotV1) -> DomainExtension:
    """Create fresh registries from verified bytes, without relying on test code."""
    if (
        type(snapshot) is not VerifiedPackageSnapshotV1
        or not snapshot.descriptor.enabled
        or not snapshot.generation_id
        or snapshot.expected_manifest_digest != snapshot.descriptor.manifest_digest
        or type(snapshot.assets) is not tuple
        or len(snapshot.assets) != len(snapshot.descriptor.asset_refs)
        or len(snapshot.assets) > 256
    ):
        raise DomainExtensionError("invalid D2-A package snapshot")
    try:
        if parse_package_descriptor(snapshot.descriptor_bytes) != snapshot.descriptor:
            raise DomainExtensionError("package descriptor changed")
    except (TypeError, ValueError) as exc:
        raise DomainExtensionError("invalid package descriptor") from exc
    if (
        any(type(asset) is not VerifiedAssetV1 for asset in snapshot.assets)
        or tuple(asset.ref for asset in snapshot.assets)
        != snapshot.descriptor.asset_refs
    ):
        raise DomainExtensionError("package asset reference mismatch")
    identity_assets: list[dict[str, str]] = []
    action_records: list[tuple[str, str, str]] = []
    strategy_records: list[tuple[str, str, str]] = []
    action_seen: set[str] = set()
    strategy_seen: set[str] = set()
    for asset in snapshot.assets:
        ref = asset.ref
        if (
            ref.namespace != snapshot.descriptor.domain_id
            or ref.version != "1.0.0"
            or type(asset.content_bytes) is not bytes
            or hashlib.sha256(asset.content_bytes).hexdigest() != ref.sha256
        ):
            raise DomainExtensionError("asset scope, version or digest invalid")
        identity_assets.append(
            {
                "kind": ref.kind,
                "namespace": ref.namespace,
                "id": ref.id,
                "version": ref.version,
                "sha256": ref.sha256,
            }
        )
        if ref.kind == "action":
            fields = _strict_object(
                asset.content_bytes, frozenset({"role", "description"})
            )
            if ref.id in action_seen:
                raise DomainExtensionError("duplicate action identifier")
            action_seen.add(ref.id)
            action_records.append((ref.id, fields["description"], fields["role"]))
        elif ref.kind == "strategy":
            fields = _strict_object(
                asset.content_bytes, frozenset({"role", "action_id"})
            )
            if ref.id in strategy_seen:
                raise DomainExtensionError("duplicate strategy identifier")
            strategy_seen.add(ref.id)
            strategy_records.append((ref.id, fields["action_id"], fields["role"]))
        elif ref.kind in {"prompt", "rule", "knowledge", "tool", "workflow", "capability"}:
            continue
        else:
            raise DomainExtensionError("unsupported executable asset kind")
    if (
        not action_records
        or not strategy_records
        or len(action_records) > 32
        or len(strategy_records) > 32
    ):
        raise DomainExtensionError("incomplete domain action/strategy mapping")
    by_action = {
        name: (description, role) for name, description, role in action_records
    }
    roles: set[str] = set()
    links: list[tuple[str, str]] = []
    for sid, action, role in strategy_records:
        if action not in by_action or by_action[action][1] != role:
            raise DomainExtensionError("foreign or mismatched strategy action")
        if role in roles:
            raise DomainExtensionError("ambiguous strategy role")
        roles.add(role)
        links.append((sid, action))
    if {action for _, action in links} != action_seen:
        raise DomainExtensionError("unreachable domain action")

    identity = {
        "domain_id": snapshot.descriptor.domain_id,
        "domain_version": snapshot.descriptor.domain_version,
        "generation_id": snapshot.generation_id,
        "manifest_digest": snapshot.descriptor.manifest_digest,
        "assets": identity_assets,
    }
    raw = json.dumps(
        identity, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    fingerprint = hashlib.sha256(b"GA02-D3-SANDBOX-BINDING-1\0" + raw).hexdigest()
    binding = DomainExtensionBinding(
        snapshot.descriptor.domain_id,
        snapshot.descriptor.domain_version,
        snapshot.generation_id,
        snapshot.descriptor.manifest_digest,
        fingerprint,
    )
    actions = ActionRegistry()
    strategies = StrategyRegistry()
    skills = SkillRegistry()
    for aid, description, _role in action_records:
        actions.register(
            ActionDefinition(
                action_id=aid,
                version="1.0.0",
                category="SANDBOX",
                description=description,
                intrusiveness_level=IntrusivenessLevel.LOW,
                requires_confirmation=False,
                required_capability=None,
                allowed_planning_modes=[
                    PlanningMode.DETERMINISTIC,
                    PlanningMode.AGENT_PLANNED,
                ],
            )
        )
    for sid, action in links:
        strategies.register(
            StrategyDefinition(
                strategy_id=sid,
                version="1.0.0",
                description="package-bound non-authoritative strategy",
                preferred_goals=[],
                preferred_needs=[],
                compatible_emotions=[],
                required_conditions=[],
                avoid_conditions=[],
                default_actions=[action],
                intrusiveness_level=IntrusivenessLevel.LOW,
            )
        )
        skills.register(
            SkillDefinition(
                skill_id="skill-" + sid,
                version="1.0.0",
                supported_actions=[action],
            )
        )
    return DomainExtension(
        binding,
        actions,
        strategies,
        skills,
        tuple(item[0] for item in action_records),
        tuple(item[0] for item in strategy_records),
        tuple(links),
    )
