"""GA-21 in-process multi-turn read-only business Agent CLI (Linux sandbox)."""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from agent_core.chat_transport import ChatCompletionsConfig
from examples.ga20_sandbox_cli import ask_once
from examples.ga21_conversation import ReadOnlyConversation
from examples.ga22_goal_policy import learning_goal_policy
from examples.ga22_replanning import PreviousStepSources


async def converse(domain: str, operator_config: Path) -> None:
    config = ChatCompletionsConfig(
        endpoint=os.environ.get("GA01C_LLM_URL", "http://127.0.0.1:11434/v1/chat/completions"),
        model=os.environ.get("GA01C_LLM_MODEL", "qwen2.5:3b"),
        api_key=os.environ.get("GA01C_LLM_API_KEY", ""),
        timeout_seconds=45.0,
        max_tokens=200,
    )

    async def run(selected: str, question: str, target: int | None) -> dict[str, object]:
        return await ask_once(
            selected, question, config, operator_config,
            goal_target=target,
            session_id="ga21-local-session",
            subject_id="ga21-local-subject",
        )

    async def continue_run(
        selected: str, question: str, target: int | None,
        previous: PreviousStepSources,
    ) -> dict[str, object]:
        return await ask_once(
            selected, question, config, operator_config,
            goal_target=target, continuation=previous,
            session_id="ga21-local-session",
            subject_id="ga21-local-subject",
        )

    conversation = ReadOnlyConversation(
        domain=domain,
        session_id="ga21-local-session",
        subject_id="ga21-local-subject",
        run_read_only=run,
        goal_policy=learning_goal_policy() if domain == "learning" else None,
        run_continuation=continue_run,
    )
    print("GA-21 本地只读会话。输入任务、‘刚才结果’、‘再查一次’或‘取消’。")
    while True:
        try:
            message = input("用户: ")
        except EOFError:
            return
        try:
            answer = await conversation.send(message)
        except (ValueError, RuntimeError, OSError) as exc:
            print(f"拒绝本轮请求: {exc}")
            continue
        print(f"Agent: {answer.text}")
        if answer.revalidated_steps:
            print(
                "GA22_STEP_CONTINUATION "
                f"revalidated={','.join(answer.revalidated_steps)} "
                f"tool_calls={answer.tool_executions}"
            )
        if answer.kind.value == "CANCEL":
            return


def main() -> int:
    parser = argparse.ArgumentParser(description="GA-21 bounded multi-turn read-only Agent")
    parser.add_argument("--domain", choices=("inventory", "learning"), required=True)
    parser.add_argument("--operator-config", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(converse(args.domain, args.operator_config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
