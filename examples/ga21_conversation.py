"""GA-21 application-level bounded, stateful multi-turn goal continuation.

This is a per-process read-only conversation coordinator, not a durable runtime.
A continuation can recall a verified answer without replaying tools; refresh is
an explicit new GA-20 run with fresh read-only evidence. Fail closed on ambiguity.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from examples.ga20_sandbox_cli import validated_question

RunReadOnly = Callable[[str, str], Awaitable[dict[str, object]]]


class TurnKind(str, Enum):
    NEW = "NEW"
    RECALL = "RECALL"
    REFRESH = "REFRESH"
    CANCEL = "CANCEL"


@dataclass(frozen=True)
class VerifiedTurn:
    domain: str
    goal: str
    answer: str
    evidence_digests: tuple[str, ...]
    executions: int


@dataclass(frozen=True)
class ConversationReply:
    kind: TurnKind
    text: str
    turn_number: int
    reused_evidence: bool
    tool_executions: int


_RECALL = ("刚才", "上次", "之前", "结果", "还剩", "还有多少", "多少件", "再说", "复述", "继续", "what was", "previous", "recap")
_REFRESH = ("重新查询", "再查", "刷新", "更新数据", "最新", "查一次", "refresh", "query again", "recheck")
_CANCEL = ("取消", "结束任务", "停止任务", "cancel", "stop task")


class ReadOnlyConversation:
    """One explicitly selected domain, subject and session, in one process.

    A failed external execution never mutates conversation state. There are no
    hidden cross-domain transfers or implicit re-execution of a finished goal.
    """

    def __init__(
        self,
        *,
        domain: str,
        session_id: str,
        subject_id: str,
        run_read_only: RunReadOnly,
        max_turns: int = 20,
    ) -> None:
        if domain not in ("inventory", "learning"):
            raise ValueError("unsupported domain")
        if not session_id or not subject_id or max_turns < 1:
            raise ValueError("invalid conversation identity or budget")
        self.domain = domain
        self.session_id = session_id
        self.subject_id = subject_id
        self.max_turns = max_turns
        self._runner = run_read_only
        self._last: VerifiedTurn | None = None
        self._turns = 0
        self._closed = False

    @property
    def last_verified(self) -> VerifiedTurn | None:
        return self._last

    def _classify(self, message: str) -> TurnKind:
        if not isinstance(message, str) or not 1 <= len(message.strip()) <= 1000:
            raise ValueError("message must be 1..1000 characters")
        value = message.strip().casefold()
        if value in _CANCEL:
            return TurnKind.CANCEL
        if any(word in value for word in _REFRESH):
            return TurnKind.REFRESH
        if any(word in value for word in _RECALL):
            return TurnKind.RECALL
        return TurnKind.NEW

    async def send(self, message: str) -> ConversationReply:
        if self._closed:
            raise ValueError("conversation is closed")
        if self._turns >= self.max_turns:
            raise ValueError("conversation turn budget exhausted")
        kind = self._classify(message)
        if kind is TurnKind.CANCEL:
            self._closed = True
            self._last = None
            self._turns += 1
            return ConversationReply(kind, "当前会话任务已结束。", self._turns, False, 0)
        if kind is TurnKind.RECALL:
            if self._last is None:
                raise ValueError("no verified prior goal to continue")
            self._turns += 1
            return ConversationReply(
                kind,
                "以下是上次已验证查询结果（没有重新读取数据）："
                + self._last.answer,
                self._turns,
                True,
                0,
            )
        if kind is TurnKind.REFRESH:
            if self._last is None:
                raise ValueError("cannot refresh without a prior goal")
            question = self._last.goal
        else:
            # GA-20 scope validation remains authoritative. A new task must
            # explicitly specify supported domain terms and cannot silently
            # inherit permissions from the preceding turn.
            question = validated_question(self.domain, message)
        result = await self._runner(self.domain, question)
        if result.get("domain") != self.domain or result.get("read_only") is not True:
            raise ValueError("untrusted runner result")
        answer = result.get("answer")
        digests = result.get("evidence_digests")
        executions = result.get("executions")
        if (
            not isinstance(answer, str)
            or not answer.strip()
            or not isinstance(digests, list)
            or not digests
            or any(not isinstance(item, str) or not item for item in digests)
            or type(executions) is not int
            or executions < 1
        ):
            raise ValueError("unverified or incomplete business result")
        # Commit conversational state only after the entire read-only run
        # succeeds. Previous verified answer survives any denied request.
        self._last = VerifiedTurn(
            self.domain, question, answer, tuple(digests), executions
        )
        self._turns += 1
        return ConversationReply(kind, answer, self._turns, False, executions)
