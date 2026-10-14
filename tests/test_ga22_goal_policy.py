"""GA-22 domain-swappable update policy with fail-closed evidence rendering."""

from __future__ import annotations

import pytest

from examples.ga21_conversation import ReadOnlyConversation, TurnKind
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


def test_injected_learning_goal_policy_updates_same_session_controller() -> None:
    async def scenario() -> None:
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
        seen: list[int | None] = []

        async def run(
            domain: str, question: str, target: int | None
        ) -> dict[str, object]:
            assert domain == "learning"
            assert "学习" in question
            seen.append(target)
            return {
                "domain": domain,
                "answer": "已查询学习进度",
                "read_only": True,
                "evidence_digests": ["verified-study-record"],
                "executions": 1,
                "admitted_goal_target": target,
                "verified_metrics": {"completed": 3},
            }

        session = ReadOnlyConversation(
            domain="learning",
            session_id="learning-s",
            subject_id="learning-u",
            run_read_only=run,
            goal_policy=policy,
        )
        await session.send("查询学习进度")
        changed = await session.send("学习目标改成 8 项")
        assert changed.kind is TurnKind.GOAL_UPDATE
        assert "还需完成 5 项" in changed.text
        refreshed = await session.send("再查一次")
        assert "还需完成 5 项" in refreshed.text
        assert seen == [None, 8, 8]

    asyncio.run(scenario())
