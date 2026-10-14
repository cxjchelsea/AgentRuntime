"""GA-21 conversation goal continuation and read-only replay boundaries."""

from __future__ import annotations

import asyncio

import pytest

from examples.ga21_conversation import ReadOnlyConversation, TurnKind


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int | None]] = []
        self.fail = False

    async def __call__(
        self, domain: str, question: str, target: int | None
    ) -> dict[str, object]:
        self.calls.append((domain, question, target))
        if self.fail:
            raise RuntimeError("provider unavailable")
        return {
            "domain": domain,
            "read_only": True,
            "answer": "库存尚有 5 件",
            "evidence_digests": ["sha256-evidence"],
            "executions": 1,
            "admitted_goal_target": target,
            "verified_metrics": {"available": 5},
        }


def test_goal_recall_refresh_and_cancel() -> None:
    async def scenario() -> None:
        runner = FakeRunner()
        conversation = ReadOnlyConversation(
            domain="inventory",
            session_id="s1",
            subject_id="u1",
            run_read_only=runner,
        )
        first = await conversation.send("请查询库存")
        assert first.kind is TurnKind.NEW
        assert first.tool_executions == 1
        recall = await conversation.send("刚才结果是什么")
        assert recall.reused_evidence and recall.tool_executions == 0
        assert "没有重新读取数据" in recall.text
        assert len(runner.calls) == 1
        refreshed = await conversation.send("再查一次")
        assert refreshed.kind is TurnKind.REFRESH
        assert refreshed.tool_executions == 1
        assert runner.calls == [("inventory", "请查询库存", None)] * 2
        cancelled = await conversation.send("取消")
        assert cancelled.kind is TurnKind.CANCEL
        with pytest.raises(ValueError, match="closed"):
            await conversation.send("刚才结果")

    asyncio.run(scenario())


def test_failure_preserves_verified_goal_and_scoping() -> None:
    async def scenario() -> None:
        runner = FakeRunner()
        session = ReadOnlyConversation(
            domain="inventory",
            session_id="s1",
            subject_id="u1",
            run_read_only=runner,
        )
        with pytest.raises(ValueError, match="no verified"):
            await session.send("刚才结果")
        await session.send("库存情况")
        with pytest.raises(ValueError, match="outside"):
            await session.send("学习进度")
        updated = await session.send("刚才结果如果目标改成20件呢")
        assert updated.kind is TurnKind.GOAL_UPDATE
        assert "建议补货 15 件" in updated.text
        assert len(runner.calls) == 2
        assert session.last_verified is not None
        assert session.last_verified.target == 20
        with pytest.raises(ValueError, match="ambiguous or unsupported"):
            await session.send("如果库存目标随便变呢")
        with pytest.raises(ValueError, match="safe bounds"):
            await session.send("目标改成100001件")
        with pytest.raises(ValueError, match="ambiguous"):
            await session.send("目标改成20件而不是30件")
        assert len(runner.calls) == 2
        runner.fail = True
        with pytest.raises(RuntimeError, match="provider unavailable"):
            await session.send("再查一次")
        recall = await session.send("之前结果")
        assert recall.reused_evidence
        assert session.last_verified is not None
        assert session.last_verified.goal == "库存情况"
        assert session.last_verified.target == 20

    asyncio.run(scenario())


def test_unverified_runner_result_rejected() -> None:
    async def invalid(
        _domain: str, _question: str, _target: int | None
    ) -> dict[str, object]:
        return {
            "domain": "inventory",
            "read_only": True,
            "answer": "ok",
            "executions": 1,
            "evidence_digests": [],
        }

    async def scenario() -> None:
        session = ReadOnlyConversation(
            domain="inventory",
            session_id="s",
            subject_id="u",
            run_read_only=invalid,
        )
        with pytest.raises(ValueError, match="unverified"):
            await session.send("库存")
        assert session.last_verified is None

    asyncio.run(scenario())


def test_turn_budget_and_cross_domain_denial() -> None:
    async def scenario() -> None:
        session = ReadOnlyConversation(
            domain="learning",
            session_id="s",
            subject_id="u",
            run_read_only=FakeRunner(),
            max_turns=1,
        )
        with pytest.raises(ValueError, match="outside"):
            await session.send("库存")
        await session.send("学习进度")
        with pytest.raises(ValueError, match="budget"):
            await session.send("刚才结果")

    asyncio.run(scenario())


def test_updated_goal_refresh_uses_new_evidence_and_preserves_target() -> None:
    async def scenario() -> None:
        runner = FakeRunner()
        session = ReadOnlyConversation(
            domain="inventory",
            session_id="s",
            subject_id="u",
            run_read_only=runner,
        )
        await session.send("查询库存")
        await session.send("目标改成20件")
        refreshed = await session.send("再查一次")
        assert refreshed.kind is TurnKind.REFRESH
        assert "建议补货 15 件" in refreshed.text
        assert len(runner.calls) == 3
        assert session.last_verified is not None
        assert session.last_verified.target == 20

    asyncio.run(scenario())


def test_concurrent_turns_are_serialized() -> None:
    async def scenario() -> None:
        runner = FakeRunner()
        session = ReadOnlyConversation(
            domain="inventory",
            session_id="s",
            subject_id="u",
            run_read_only=runner,
        )
        await asyncio.gather(
            session.send("查询库存"),
            session.send("查询库存"),
        )
        assert len(runner.calls) == 2
        assert session.last_verified is not None

    asyncio.run(scenario())
