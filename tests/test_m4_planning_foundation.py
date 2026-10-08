"""M4-IU1 Planning foundation: Action/Strategy registries and frozen contract alignment."""

from __future__ import annotations

import inspect

import pytest

import runtime.contracts as contracts_module
from runtime.contracts import ActionPlanDraft, ApprovedActionPlan
from runtime.contracts.enums import PlanningMode
from runtime.interfaces import Planner
from runtime.registries import (
    ActionDefinition,
    ActionRegistry,
    DuplicateRegistrationError,
    IntrusivenessLevel,
    StrategyDefinition,
    StrategyRegistry,
)


def _action_definition(
    *,
    action_id: str = "DOMAIN_ACTION",
    version: str = "1.0.0",
    enabled: bool = True,
) -> ActionDefinition:
    return ActionDefinition(
        action_id=action_id,
        version=version,
        category="DOMAIN_CATEGORY",
        description="domain-provided action metadata",
        intrusiveness_level=IntrusivenessLevel.LOW,
        requires_confirmation=False,
        required_capability="DOMAIN_CAPABILITY",
        allowed_planning_modes=[
            PlanningMode.DETERMINISTIC,
            PlanningMode.AGENT_PLANNED,
        ],
        enabled=enabled,
    )


def _strategy_definition(
    *,
    strategy_id: str = "DOMAIN_STRATEGY",
    version: str = "1.0.0",
    enabled: bool = True,
) -> StrategyDefinition:
    return StrategyDefinition(
        strategy_id=strategy_id,
        version=version,
        description="domain-provided strategy metadata",
        preferred_goals=["DOMAIN_GOAL"],
        preferred_needs=["DOMAIN_NEED"],
        compatible_emotions=["DOMAIN_EMOTION"],
        required_conditions=["DOMAIN_CONDITION"],
        avoid_conditions=["DOMAIN_AVOID_CONDITION"],
        default_actions=["DOMAIN_ACTION"],
        intrusiveness_level=IntrusivenessLevel.LOW,
        enabled=enabled,
    )


def test_frozen_planning_contract_names_remain_unambiguous() -> None:
    assert "ActionPlan" not in contracts_module.__all__
    assert "ActionPlanDraft" in contracts_module.__all__
    assert "ApprovedActionPlan" in contracts_module.__all__
    assert ActionPlanDraft is not ApprovedActionPlan


def test_planner_interface_still_outputs_action_plan_draft() -> None:
    signature = inspect.signature(Planner.plan)
    assert tuple(signature.parameters) == (
        "self",
        "runtime_context",
        "understanding_state",
        "policy_decision",
    )
    assert signature.return_annotation in {"ActionPlanDraft", ActionPlanDraft}


def test_action_definition_matches_frozen_m4_registry_surface() -> None:
    definition = _action_definition()

    assert definition.action_id == "DOMAIN_ACTION"
    assert definition.category == "DOMAIN_CATEGORY"
    assert definition.intrusiveness_level is IntrusivenessLevel.LOW
    assert definition.required_capability == "DOMAIN_CAPABILITY"
    assert definition.allowed_planning_modes == [
        PlanningMode.DETERMINISTIC,
        PlanningMode.AGENT_PLANNED,
    ]


def test_strategy_definition_matches_frozen_m4_registry_surface() -> None:
    definition = _strategy_definition()

    assert definition.strategy_id == "DOMAIN_STRATEGY"
    assert definition.preferred_goals == ["DOMAIN_GOAL"]
    assert definition.preferred_needs == ["DOMAIN_NEED"]
    assert definition.compatible_emotions == ["DOMAIN_EMOTION"]
    assert definition.default_actions == ["DOMAIN_ACTION"]


def test_action_registry_is_deterministic_and_does_not_execute_action() -> None:
    registry = ActionRegistry()
    definition = _action_definition()

    registry.register(definition, namespace="domain.test")

    record = registry.get("DOMAIN_ACTION", "1.0.0", namespace="domain.test")
    assert record.definition == definition
    assert record.implementation_ref is None
    assert record.enabled is True


def test_strategy_registry_is_deterministic_and_does_not_select_strategy() -> None:
    registry = StrategyRegistry()
    definition = _strategy_definition()

    registry.register(definition, namespace="domain.test")

    record = registry.get("DOMAIN_STRATEGY", "1.0.0", namespace="domain.test")
    assert record.definition == definition
    assert record.implementation_ref is None
    assert record.enabled is True


def test_action_registry_rejects_duplicate_key_instead_of_overwriting() -> None:
    registry = ActionRegistry()
    definition = _action_definition()
    registry.register(definition, namespace="domain.test")

    with pytest.raises(DuplicateRegistrationError):
        registry.register(definition, namespace="domain.test")


def test_strategy_registry_rejects_duplicate_key_instead_of_overwriting() -> None:
    registry = StrategyRegistry()
    definition = _strategy_definition()
    registry.register(definition, namespace="domain.test")

    with pytest.raises(DuplicateRegistrationError):
        registry.register(definition, namespace="domain.test")


def test_disabled_definition_stays_disabled_in_registry() -> None:
    action_registry = ActionRegistry()
    strategy_registry = StrategyRegistry()

    action_registry.register(
        _action_definition(action_id="DISABLED_ACTION", enabled=False)
    )
    strategy_registry.register(
        _strategy_definition(strategy_id="DISABLED_STRATEGY", enabled=False)
    )

    assert action_registry.get("DISABLED_ACTION", "1.0.0").enabled is False
    assert strategy_registry.get("DISABLED_STRATEGY", "1.0.0").enabled is False


def test_core_registries_do_not_ship_domain_action_or_strategy_catalogs() -> None:
    action_registry = ActionRegistry()
    strategy_registry = StrategyRegistry()

    assert action_registry.list() == []
    assert strategy_registry.list() == []
