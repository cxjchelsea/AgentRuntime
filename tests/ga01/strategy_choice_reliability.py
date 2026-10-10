"""Bounded pre-execution strategy-choice recovery for the GA-01C sandbox.

This is NOT a production retry policy, Tool replay mechanism or M4 authority.
Only rejected soft-model choices can be retried; M4 validates the final result.
Raw provider text and user goal are never logged.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from runtime.planning.errors import StrategyModelOutputError
from runtime.planning.strategy_selection import StrategyModelOutputValidator


class DiagnosticStrategyChoiceTransport:
    """One optional re-inference for invalid structured model choices.

    The same allow-listed model input is sent twice; no expected answer,
    error-specific hints, or action success assertions are inserted.
    """

    def __init__(
        self,
        infer_once: Callable[[dict[str, Any]], Awaitable[Mapping[str, object]]],
        *,
        max_invalid_retries: int = 1,
    ) -> None:
        if max_invalid_retries not in (0, 1):
            raise ValueError("sandbox supports zero or one pre-execution retry")
        self._infer_once = infer_once
        self._max_invalid_retries = max_invalid_retries
        self.invalid_output_categories: list[str] = []
        self.recovered_invalid_choices = 0
        self.unrecovered_invalid_choices = 0
        self.model_calls = 0

    async def __call__(self, payload: dict[str, Any]) -> Mapping[str, object]:
        strategies = payload.get("legal_strategy_ids")
        actions = payload.get("candidate_action_ids")
        if (
            not isinstance(strategies, list)
            or not strategies
            or not all(isinstance(x, str) and x for x in strategies)
            or not isinstance(actions, list)
            or not all(isinstance(x, str) and x for x in actions)
        ):
            raise ValueError("missing bounded strategy/action candidate set")
        validator = StrategyModelOutputValidator()
        for attempt in range(self._max_invalid_retries + 1):
            self.model_calls += 1
            # Transport failures are NOT retried by this choice-only wrapper.
            choice = await self._infer_once(payload)
            try:
                validator.validate(
                    choice,
                    legal_strategy_ids=frozenset(strategies),
                    legal_action_ids=frozenset(actions),
                )
            except StrategyModelOutputError as error:
                # The exception is produced by the local allow-list validator;
                # category contains no raw model text or user-private content.
                self.invalid_output_categories.append(str(error))
                if attempt == self._max_invalid_retries:
                    self.unrecovered_invalid_choices += 1
                    raise
                continue
            if attempt:
                self.recovered_invalid_choices += 1
            return choice
        raise AssertionError("unreachable bounded strategy choice retry")
