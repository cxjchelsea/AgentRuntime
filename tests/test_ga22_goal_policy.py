"""GA-22 domain-swappable update policy with fail-closed evidence rendering."""

from __future__ import annotations

import pytest

from examples.ga22_goal_policy import (
    DomainGoalPolicy,
    GoalUpdate,
    inventory_goal_policy,
)


def test_inventory_policy_parses_and_renders() -> None:
    policy = inventory_goal_policy()
    update = policy.parse("如果库存目标改成20件呢")
    assert update == GoalUpdate("inventory", "target", 20)
    assert "建议补货 15 件" in policy.render(update, {"available": 5})
    for text in ("目标改成20件而不是30件", "目标改成100001件", "随便调整"):
        with pytest.raises(ValueError):
            policy.parse(text)
    with pytest.raises(ValueError, match="fresh verified"):
        policy.render(update, {"available": "5"})


def test_second_domain_uses_same_policy_engine_without_inventory_logic() -> None:
    policy = DomainGoalPolicy(
        domain="learning",
        goal_key="completion_target",
        update_pattern=r"学习目标改成\s*(\d+)\s*项",
        metric_key="completed",
        metric_label="已完成任务",
        target_label="学习目标",
        delta_label="还需完成",
        unit="项",
        max_value=100,
    )
    change = policy.parse("学习目标改成 8 项")
    assert change == GoalUpdate("learning", "completion_target", 8)
    assert "还需完成 5 项" in policy.render(change, {"completed": 3})
    with pytest.raises(ValueError, match="foreign"):
        policy.render(GoalUpdate("inventory", "target", 8), {"completed": 3})


def test_goal_policy_rejects_malformed_config() -> None:
    with pytest.raises(ValueError):
        DomainGoalPolicy(
            domain="inventory",
            goal_key="target",
            update_pattern=r"(\d+)-(\d+)",
            metric_key="available",
            metric_label="stock",
            target_label="target",
            delta_label="buy",
            unit="pcs",
        )
