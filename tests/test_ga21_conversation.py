"""GA-21 conversation goal continuation and read-only replay boundaries."""

from __future__ import annotations

import asyncio

import pytest

from examples.ga21_conversation import ReadOnlyConversation, TurnKind


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail = False

    async def __call__(self, domain: str, question: str) -> dict[str, object]:
        self.calls.append((domain, question))
        if self.fail:
            raise RuntimeError("provider unavailable")
        return {
            "domain": domain,
            "read_only": True,
            "answer": "库存尚有 5 件",
            "evidence_digests": ["sha256-evidence"],
            "executions": 1,
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
        assert runner.calls == [("inventory", "请查询库存")] * 2
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
        with pytest.raises(ValueError, match="goal amendment"):
            await session.send("刚才结果如果目标改成20件呢")
        assert len(runner.calls) == 1
        runner.fail = True
        with pytest.raises(RuntimeError, match="provider unavailable"):
            await session.send("再查一次")
        recall = await session.send("之前结果")
        assert recall.reused_evidence
        assert session.last_verified is not None
        assert session.last_verified.goal == "库存情况"

    asyncio.run(scenario())


def test_unverified_runner_result_rejected() -> None:
    async def invalid(_domain: str, _question: str) -> dict[str, object]:
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
