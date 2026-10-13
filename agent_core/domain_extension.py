"""GA-07 Slice B: package-driven, non-authoritative Domain Extension assembly.

This consumes an inert GA-02 pinned binding, never a trusted issuer claim.
Only bounded LOW-impact actions/strategies are supported. No tools, workflow
execution, C1 publisher authority, M6 grant or new M4 planner is created.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from agent_core.sandbox_domain_assembly import (
    ROLE,
    SandboxAssemblyError,
    SandboxDomainBinding,
)
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
    """Invalid inert domain package configuration; no partial assembly returned."""


@dataclass(frozen=True, slots=True)
class DomainExtension:
    """Fresh, run-scoped M4 registries, generated from one pinned package."""

    binding: SandboxDomainBinding
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


def assemble_domain_extension(binding: SandboxDomainBinding) -> DomainExtension:
    """Use package-defined IDs and strategy links, never fixed domain values.

    The GA-02 binding is still explicitly SANDBOX_NON_AUTHORITATIVE, so
    registries generated here are not grants and cannot enable external tools.
    """
    if (
        type(binding) is not SandboxDomainBinding
        or binding.role != ROLE
        or not binding.domain_id
        or not binding.binding_fingerprint
        or not binding.assets
        or len(binding.assets) > 256
    ):
        raise DomainExtensionError("invalid inert domain binding")
    actions = ActionRegistry()
    strategies = StrategyRegistry()
    skills = SkillRegistry()
    action_ids: list[str] = []
    strategy_ids: list[str] = []
    links: list[tuple[str, str]] = []
    action_seen: set[str] = set()
    strategy_seen: set[str] = set()
    action_records: list[tuple[str, str, str]] = []
    strategy_records: list[tuple[str, str, str]] = []
    for asset in binding.assets:
        if (
            asset.namespace != binding.domain_id
            or hashlib.sha256(asset.content_bytes).hexdigest() != asset.sha256
            or asset.version != "1.0.0"
        ):
            raise DomainExtensionError("asset scope, version or digest invalid")
        if asset.kind == "action":
            value = _strict_object(asset.content_bytes, frozenset({"role", "description"}))
            if asset.id in action_seen:
                raise DomainExtensionError("duplicate action identifier")
            action_seen.add(asset.id)
            action_records.append((asset.id, value["description"], value["role"]))
        elif asset.kind == "strategy":
            value = _strict_object(asset.content_bytes, frozenset({"role", "action_id"}))
            if asset.id in strategy_seen:
                raise DomainExtensionError("duplicate strategy identifier")
            strategy_seen.add(asset.id)
            strategy_records.append((asset.id, value["action_id"], value["role"]))
        elif asset.kind in {"prompt", "rule", "knowledge"}:
            # Domain content has a separate retrieval/prompt interface (Slice A).
            # Do not accidentally interpret its bytes as executable actions.
            continue
        else:
            raise DomainExtensionError("unsupported executable asset kind")
    if (
        not action_records
        or not strategy_records
        or len(action_records) > 32
        or len(strategy_records) > 32
        or set(binding.action_ids) != action_seen
    ):
        raise DomainExtensionError("incomplete domain action/strategy mapping")
    by_action = {item: (description, role) for item, description, role in action_records}
    roles: set[str] = set()
    for strategy_id, action_id, role in strategy_records:
        if action_id not in by_action or by_action[action_id][1] != role:
            raise DomainExtensionError("foreign or mismatched strategy action")
        if role in roles:
            raise DomainExtensionError("ambiguous strategy role")
        roles.add(role)
        strategy_ids.append(strategy_id)
        links.append((strategy_id, action_id))
    if set(item for _, item in links) != action_seen:
        raise DomainExtensionError("unreachable domain action")
    for action_id, description, _role in action_records:
        actions.register(
            ActionDefinition(
                action_id=action_id,
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
        action_ids.append(action_id)
    for strategy_id, action_id in links:
        strategies.register(
            StrategyDefinition(
                strategy_id=strategy_id,
                version="1.0.0",
                description="package-bound sandbox strategy",
                preferred_goals=[],
                preferred_needs=[],
                compatible_emotions=[],
                required_conditions=[],
                avoid_conditions=[],
                default_actions=[action_id],
                intrusiveness_level=IntrusivenessLevel.LOW,
            )
        )
        skills.register(
            SkillDefinition(
                skill_id="skill-" + strategy_id,
                version="1.0.0",
                supported_actions=[action_id],
            )
        )
    return DomainExtension(
        binding,
        actions,
        strategies,
        skills,
        tuple(action_ids),
        tuple(strategy_ids),
        tuple(links),
    )
