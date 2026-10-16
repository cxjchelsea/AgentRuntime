"""GA-21 application-level bounded, stateful multi-turn goal continuation.

This is a per-process read-only conversation coordinator, not a durable runtime.
A continuation can recall a verified answer without replaying tools; refresh is
an explicit new GA-20 run with fresh read-only evidence. Fail closed on ambiguity.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum

from examples.ga20_sandbox_cli import validated_question
from examples.ga22_goal_policy import DomainGoalPolicy, GoalUpdate, inventory_goal_policy
from examples.ga22_replanning import (
    GoalState,
    PreviousStepSources,
    ReplanAction,
    decide_replanning,
)

RunReadOnly = Callable[[str, str, int | None], Awaitable[dict[str, object]]]
RunContinuation = Callable[
    [str, str, int | None, PreviousStepSources], Awaitable[dict[str, object]]
]


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
    binding_fingerprint: str | None = None
    step_sources: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ConversationReply:
    kind: TurnKind
    text: str
    turn_number: int
    reused_evidence: bool
    tool_executions: int
    revalidated_steps: tuple[str, ...] = ()
    goal: str | None = None
    decision_action: str | None = None
    observation_count: int | None = None
    loop_iterations: int | None = None
    finish_reason: str | None = None


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
        goal_policy: DomainGoalPolicy | None = None,
        run_continuation: RunContinuation | None = None,
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
        self._run_continuation = run_continuation
        self._goal_policy = goal_policy if goal_policy is not None else (
            inventory_goal_policy() if domain == "inventory" else None
        )
        if self._goal_policy is not None and self._goal_policy.domain != domain:
            raise ValueError("goal policy domain mismatch")
        self._last: VerifiedTurn | None = None
        self._goal_state: GoalState | None = None
        self._turns = 0
        self._closed = False
        self._turn_lock = asyncio.Lock()

    @property
    def last_verified(self) -> VerifiedTurn | None:
        return self._last

    @property
    def goal_state(self) -> GoalState | None:
        return self._goal_state

    def _classify(self, message: str) -> TurnKind:
        if not isinstance(message, str) or not 1 <= len(message.strip()) <= 1000:
            raise ValueError("message must be 1..1000 characters")
        value = message.strip().casefold()
        # A goal change needs re-understanding and fresh evidence. Never
        # classify it as RECALL, even if it mentions previous results.
        if any(phrase in value for phrase in _AMEND):
            if self._goal_policy is not None:
                self._goal_policy.parse(value)
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
        # Serialize state mutations across concurrent callers in one session.
        async with self._turn_lock:
            return await self._send_serial(message)

    async def _send_serial(self, message: str) -> ConversationReply:
        if self._closed:
            raise ValueError("conversation is closed")
        if self._turns >= self.max_turns:
            raise ValueError("conversation turn budget exhausted")
        kind = self._classify(message)
        if kind is TurnKind.CANCEL:
            self._closed = True
            self._last = None
            self._goal_state = None
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
            if self._last is None or self._last.domain != self.domain:
                raise ValueError("goal update requires a prior verified domain goal")
            policy = self._goal_policy
            if policy is None:
                raise ValueError("no admitted domain goal policy")
            target_update = policy.parse(message).value
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
        decision = decide_replanning(
            previous=self._goal_state,
            domain=self.domain,
            question=question,
            policy=self._goal_policy,
            update_text=message if kind is TurnKind.GOAL_UPDATE else None,
            refresh=kind is TurnKind.REFRESH,
        )
        if (
            decision.update is None and target_update is not None
            or decision.update is not None
            and decision.update.value != target_update
            or not decision.must_execute
        ):
            raise ValueError("replanning target mismatch")
        if kind is TurnKind.GOAL_UPDATE and decision.action not in (
            ReplanAction.REPLAN_WITH_FRESH_EVIDENCE,
            ReplanAction.REFRESH_WITH_FRESH_EVIDENCE,
        ):
            raise ValueError("goal update did not require new execution")
        prior = self._last
        goal_state = self._goal_state
        if (
            kind is TurnKind.GOAL_UPDATE
            and self._run_continuation is not None
            and prior is not None
            and prior.binding_fingerprint is not None
            and prior.step_sources
            and goal_state is not None
            and self._goal_policy is not None
        ):
            evidence = PreviousStepSources(
                domain=self.domain,
                binding_fingerprint=prior.binding_fingerprint,
                goal_version=goal_state.version,
                goal_key=self._goal_policy.goal_key,
                step_sources=prior.step_sources,
                session_id=self.session_id,
                subject_id=self.subject_id,
            )
            result = await self._run_continuation(
                self.domain, question, target_update, evidence
            )
        else:
            result = await self._runner(self.domain, question, target_update)
        if result.get("domain") != self.domain or result.get("read_only") is not True:
            raise ValueError("untrusted runner result")
        if result.get("admitted_goal_target") != target_update:
            raise ValueError("runner goal target admission mismatch")
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
        fingerprint = result.get("binding_fingerprint")
        source_pairs = result.get("step_source_digests")
        sources: tuple[tuple[str, str], ...] = ()
        if fingerprint is not None or source_pairs is not None:
            if (
                type(fingerprint) is not str
                or len(fingerprint) != 64
                or type(source_pairs) is not list
                or not source_pairs
                or any(
                    type(pair) is not list
                    or len(pair) != 2
                    or any(type(item) is not str or not item for item in pair)
                    or len(pair[1]) != 64
                    for pair in source_pairs
                )
            ):
                raise ValueError("incomplete or untrusted step source provenance")
            sources = tuple((pair[0], pair[1]) for pair in source_pairs)
            if len({step for step, _ in sources}) != len(sources):
                raise ValueError("duplicate verified step source")
        revalidated = result.get("revalidated_step_ids", [])
        actual_calls = result.get("tool_executions", executions)
        if (
            type(revalidated) is not list
            or any(type(step) is not str or not step for step in revalidated)
            or type(actual_calls) is not int
            or not 0 <= actual_calls <= executions
            or len(revalidated) + actual_calls != executions
        ):
            raise ValueError("invalid step execution accounting")
        available: int | None = None
        if target_update is not None:
            metrics = result.get("verified_metrics")
            policy = self._goal_policy
            if policy is None:
                raise ValueError("no admitted domain goal policy")
            answer = policy.render(
                GoalUpdate(self.domain, policy.goal_key, target_update),
                metrics,
            )
            if type(metrics) is dict:
                value = metrics.get(policy.metric_key)
                if type(value) is int:
                    available = value
        # Commit conversational state only after the entire read-only run
        # succeeds. Previous verified answer survives any denied request.
        self._last = VerifiedTurn(
            self.domain, question, answer, tuple(digests), executions,
            available=available, target=target_update,
            binding_fingerprint=fingerprint if type(fingerprint) is str else None,
            step_sources=sources,
        )
        self._goal_state = GoalState(
            self.domain, question, decision.next_version,
            decision.update, tuple(digests),
        )
        self._turns += 1
        observation_count = result.get("observation_count")
        loop_iterations = result.get("loop_iterations")
        finish_reason = result.get("finish_reason")
        return ConversationReply(
            kind,
            answer,
            self._turns,
            False,
            actual_calls,
            tuple(revalidated),
            goal=question,
            decision_action=decision.action.value,
            observation_count=observation_count if isinstance(observation_count, int) else None,
            loop_iterations=loop_iterations if isinstance(loop_iterations, int) else None,
            finish_reason=finish_reason if isinstance(finish_reason, str) else None,
        )
