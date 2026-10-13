"""GA-02 D3/D4 isolated domain-owned M4 registry assembly.

Converts pinned, hash-checked *sandbox* package assets into existing M4
Action/Strategy/Skill registries; never issues Host provenance, execution
permission, or a production DomainBinding.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from agent_core.sandbox_domain_assembly import SandboxAssemblyError, SandboxDomainBinding
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


@dataclass(frozen=True, slots=True)
class SandboxM4Domain:
    binding: SandboxDomainBinding
    actions: ActionRegistry
    strategies: StrategyRegistry
    skills: SkillRegistry
    collect_action: str
    verify_action: str
    collect_strategy: str
    verify_strategy: str


def _strict_json(data: bytes, expected: set[str]) -> dict[str, str]:
    if type(data) is not bytes or len(data) > 4096:
        raise SandboxAssemblyError("invalid sandbox asset bytes")

    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise SandboxAssemblyError("duplicate sandbox asset field")
            result[key] = value
        return result

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=no_duplicates)
    except (ValueError, UnicodeError) as exc:
        raise SandboxAssemblyError("invalid sandbox JSON asset") from exc
    if (
        type(value) is not dict
        or value.keys() != expected
        or any(type(v) is not str or not v or len(v) > 128 for v in value.values())
    ):
        raise SandboxAssemblyError("invalid sandbox asset schema")
    return value


def assemble_sandbox_m4(binding: SandboxDomainBinding) -> SandboxM4Domain:
    """Register strictly two ordered safe steps from a pinned sandbox package.

    This is a bounded demo schema, *not* a universal domain/plugin schema.
    The existing M4 Planner/Validator/Rechecker remain authoritative.
    """
    if type(binding) is not SandboxDomainBinding or binding.role != (
        "SANDBOX_NON_AUTHORITATIVE_DOMAIN_BINDING"
    ):
        raise SandboxAssemblyError("invalid sandbox domain binding")
    actions = ActionRegistry()
    strategies = StrategyRegistry()
    skills = SkillRegistry()
    by_role: dict[str, tuple[str, str]] = {}
    action_ids: set[str] = set()
    strategy_assets: list[tuple[str, str, str]] = []
    for asset in binding.assets:
        if asset.namespace != binding.domain_id or asset.version != "1.0.0":
            raise SandboxAssemblyError("sandbox namespace/version mismatch")
        if asset.kind == "action":
            value = _strict_json(asset.content_bytes, {"description", "role"})
            role = value["role"]
            if role not in {"collect", "verify"} or role in by_role:
                raise SandboxAssemblyError("duplicated or invalid action role")
            if asset.id in action_ids:
                raise SandboxAssemblyError("duplicate action id")
            by_role[role] = (asset.id, value["description"])
            action_ids.add(asset.id)
            actions.register(
                ActionDefinition(
                    action_id=asset.id,
                    version=asset.version,
                    category="SANDBOX",
                    description=value["description"],
                    intrusiveness_level=IntrusivenessLevel.LOW,
                    requires_confirmation=False,
                    required_capability=None,
                    allowed_planning_modes=[
                        PlanningMode.DETERMINISTIC,
                        PlanningMode.AGENT_PLANNED,
                    ],
                )
            )
        elif asset.kind == "strategy":
            value = _strict_json(asset.content_bytes, {"action_id", "role"})
            strategy_assets.append((asset.id, value["action_id"], value["role"]))
        else:
            raise SandboxAssemblyError("unsupported sandbox M4 asset kind")
    if set(by_role) != {"collect", "verify"} or len(strategy_assets) != 2:
        raise SandboxAssemblyError("missing sandbox action or strategy")
    if set(binding.action_ids) != action_ids:
        raise SandboxAssemblyError("binding action set mismatch")

    strategy_roles: dict[str, str] = {}
    for strategy_id, action_id, role in strategy_assets:
        if role not in by_role or role in strategy_roles:
            raise SandboxAssemblyError("duplicate or invalid strategy role")
        if by_role[role][0] != action_id:
            raise SandboxAssemblyError("strategy references foreign action")
        strategy_roles[role] = strategy_id
        strategies.register(
            StrategyDefinition(
                strategy_id=strategy_id,
                version="1.0.0",
                description=f"sandbox {role} strategy",
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
                skill_id=f"skill-{role}",
                version="1.0.0",
                supported_actions=[action_id],
            )
        )
    if set(strategy_roles) != {"collect", "verify"}:
        raise SandboxAssemblyError("incomplete sandbox strategies")
    return SandboxM4Domain(
        binding,
        actions,
        strategies,
        skills,
        by_role["collect"][0],
        by_role["verify"][0],
        strategy_roles["collect"],
        strategy_roles["verify"],
    )
