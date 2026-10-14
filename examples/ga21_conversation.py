"""GA-21 application-level bounded, stateful multi-turn goal continuation.

This is a per-process read-only conversation coordinator, not a durable runtime.
A continuation can recall a verified answer without replaying tools; refresh is
an explicit new GA-20 run with fresh read-only evidence. Fail closed on ambiguity.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
import re
from typing import Any

from examples.ga20_sandbox_cli import validated_question

RunReadOnly = Callable[[str, str], Awaitable[dict[str, object]]]


class TurnKind(str, Enum):
    NEW = "NEW"
    RECALL = "RECALL"
    REFRESH = "REFRESH"
    CANCEL = "CANCEL"
    GOAL_UPDATE = "GOAL_UPDATE"


@dataclass(frozen=True)
class VerifiedTurn:
    domain: str
    goal: str
    answer: str
    evidence_digests: tuple[str, ...]
    executions: int
    available: int | None = None
    target: int | None = None


@dataclass(frozen=True)
class ConversationReply:
    kind: TurnKind
    text: str
    turn_number: int
    reused_evidence: bool
    tool_executions: int


_TARGET_UPDATE = re.compile(r"(?:库存)?目标(?:改成|改为|调整为|设为|设成|设置为|是)\s*(\d{1,6})\s*件?")


_RECALL = ("刚才", "上次", "之前", "结果", "还剩", "还有多少", "多少件", "再说", "复述", "继续", "what was", "previous", "recap")
_REFRESH = ("重新查询", "再查", "刷新", "更新数据", "最新", "查一次", "refresh", "query again", "recheck")
_CANCEL = ("取消", "结束任务", "停止任务", "cancel", "stop task")
_AMEND = ("改成", "改为", "调整为", "目标设", "条件改", "假设", "如果", "instead", "change to", "what if")


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
        # A goal change needs re-understanding and fresh evidence. Never
        # classify it as RECALL, even if it mentions previous results.
        if any(phrase in value for phrase in _AMEND):
            if self.domain == "inventory" and _TARGET_UPDATE.search(value):
                return TurnKind.GOAL_UPDATE
            raise ValueError("unsupported or ambiguous goal amendment")
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
        target_update: int | None = None
        if kind is TurnKind.GOAL_UPDATE:
            if self._last is None or self._last.domain != "inventory":
                raise ValueError("goal update requires a prior verified inventory goal")
            found = _TARGET_UPDATE.findall(message)
            if len(found) != 1:
                raise ValueError("ambiguous inventory target update")
            target_update = int(found[0])
            if target_update > 100_000:
                raise ValueError("inventory target exceeds safe bounds")
            # New read-only workflow is required; cached measurements cannot
            # be treated as current evidence for the modified goal.
            question = self._last.goal
        elif kind is TurnKind.REFRESH:
            if self._last is None:
                raise ValueError("cannot refresh without a prior goal")
            question = self._last.goal
            target_update = self._last.target
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
        available: int | None = None
        if self.domain == "inventory":
            metrics = result.get("verified_metrics")
            if target_update is not None:
                if (
                    not isinstance(metrics, dict)
                    or set(metrics) != {"available"}
                    or type(metrics["available"]) is not int
                    or not 0 <= metrics["available"] <= 100_000
                ):
                    raise ValueError("goal update requires verified fresh stock evidence")
                available = metrics["available"]
                deficit = max(0, target_update - available)
                answer = (
                    f"重新查询验证可用库存为 {available} 件；按新目标 "
                    f"{target_update} 件，建议补货 {deficit} 件。"
                    "只进行了只读查询与重新计算，没有执行采购或库存变更。"
                )
        # Commit conversational state only after the entire read-only run
        # succeeds. Previous verified answer survives any denied request.
        self._last = VerifiedTurn(
            self.domain, question, answer, tuple(digests), executions,
            available=available, target=target_update,
        )
        self._turns += 1
        return ConversationReply(kind, answer, self._turns, False, executions)
