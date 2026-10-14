"""GA-22 real source-revalidated selective continuation with M4 approval."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest

from agent_core.chat_transport import ChatCompletionsConfig
from agent_core.runner import RunBoundaryError
from examples import ga20_sandbox_cli
from examples.ga21_conversation import ReadOnlyConversation, TurnKind
from examples.ga22_goal_policy import learning_goal_policy
from examples.ga22_replanning import PreviousStepSources
from tests.ga20_fixture_prepare import prepare

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux-only fixture loader"
)


class DeterministicTransport:
    def __init__(self, config: object, *, system_instruction: str) -> None:
        assert config is not None and system_instruction

    async def __call__(self, payload: dict[str, Any]) -> dict[str, object]:
        return {
            "strategy_id": payload["legal_strategy_ids"][0],
            "action_ids": [payload["candidate_action_ids"][0]],
            "reason_code": "BUSINESS_READ_ONLY_QUERY",
        }


async def deterministic_answer(**_kwargs: object) -> object:
    raise RunBoundaryError("use verified deterministic fallback")


def test_m4_approved_two_step_continuation_and_digest_invalidation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        ga20_sandbox_cli, "ChatCompletionsStrategyTransport", DeterministicTransport
    )
    monkeypatch.setattr(
        ga20_sandbox_cli, "generate_live_business_answer", deterministic_answer
    )
    prepare(tmp_path)
    operator_config = tmp_path / "learning.json"
    config = ChatCompletionsConfig(
        endpoint="http://127.0.0.1:11434/v1/chat/completions",
        model="deterministic-selector",
        api_key="",
        timeout_seconds=10.0,
        max_tokens=200,
    )

    async def read(domain: str, question: str, target: int | None) -> dict[str, object]:
        return await ga20_sandbox_cli.ask_once(
            domain, question, config, operator_config, goal_target=target,
            session_id="learning-s", subject_id="learning-u",
        )

    async def continue_run(
        domain: str,
        question: str,
        target: int | None,
        previous: PreviousStepSources,
    ) -> dict[str, object]:
        return await ga20_sandbox_cli.ask_once(
            domain,
            question,
            config,
            operator_config,
            goal_target=target,
            continuation=previous,
            session_id="learning-s",
            subject_id="learning-u",
        )

    async def scenario() -> None:
        session = ReadOnlyConversation(
            domain="learning",
            session_id="learning-s",
            subject_id="learning-u",
            run_read_only=read,
            run_continuation=continue_run,
            goal_policy=learning_goal_policy(),
        )
        initial = await session.send("请查询学习进度")
        assert initial.kind is TurnKind.NEW
        assert initial.tool_executions == 2

        changed = await session.send("学习目标改成8项")
        assert changed.kind is TurnKind.GOAL_UPDATE
        assert changed.tool_executions == 1
        assert changed.revalidated_steps == ("step-1",)
        assert "还需完成 6 项" in changed.text

        settings = json.loads(operator_config.read_text(encoding="utf-8"))
        database = Path(settings["database_file"])
        updated = '{"completed":3,"total":5}'
        digest = hashlib.sha256(updated.encode()).hexdigest()
        with sqlite3.connect(database) as conn:
            conn.execute(
                "UPDATE business_records SET value=?, sha256=? WHERE record_key=?",
                (updated, digest, settings["step_keys"]["step-1"]),
            )
        next_change = await session.send("学习目标改成9项")
        assert next_change.kind is TurnKind.GOAL_UPDATE
        assert next_change.tool_executions == 2
        assert next_change.revalidated_steps == ()

    asyncio.run(scenario())
