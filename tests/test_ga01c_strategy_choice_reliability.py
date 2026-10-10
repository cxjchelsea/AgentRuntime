"""Adversarial checks for opt-in GA-01C strategy output recovery."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from runtime.planning.errors import StrategyModelOutputError
from tests.ga01.strategy_choice_reliability import DiagnosticStrategyChoiceTransport


def _request() -> dict[str, Any]:
    return {
        "legal_strategy_ids": ["DOMAIN_STRATEGY_A", "DOMAIN_STRATEGY_B"],
        "candidate_action_ids": ["DOMAIN_ACTION_A", "DOMAIN_ACTION_B"],
        "explicit_goal": "synthetic task",
    }


def _choice(strategy: str, action: str) -> dict[str, object]:
    return {"strategy_id": strategy, "action_ids": [action], "reason_code": "TEST"}


def test_invalid_strategy_recovers_once_without_changing_request() -> None:
    received: list[dict[str, Any]] = []
    replies = iter(
        [_choice("UNREGISTERED", "DOMAIN_ACTION_A"), _choice("DOMAIN_STRATEGY_A", "DOMAIN_ACTION_A")]
    )

    async def infer(payload: dict[str, Any]) -> dict[str, object]:
        received.append(dict(payload))
        return next(replies)

    t = DiagnosticStrategyChoiceTransport(infer)
    data = _request()
    choice = asyncio.run(t(data))
    assert choice["strategy_id"] == "DOMAIN_STRATEGY_A"
    assert received == [data, data]
    assert t.model_calls == 2
    assert t.recovered_invalid_choices == 1
    assert t.unrecovered_invalid_choices == 0
    assert len(t.invalid_output_categories) == 1
    assert "ineligible" in t.invalid_output_categories[0]


def test_persistent_invalid_action_fails_closed_after_one_retry() -> None:
    async def infer(_: dict[str, Any]) -> dict[str, object]:
        return _choice("DOMAIN_STRATEGY_A", "OUTSIDE_LEGAL_SPACE")

    t = DiagnosticStrategyChoiceTransport(infer)
    with pytest.raises(StrategyModelOutputError, match="legal candidate space"):
        asyncio.run(t(_request()))
    assert t.model_calls == 2
    assert t.recovered_invalid_choices == 0
    assert t.unrecovered_invalid_choices == 1


def test_zero_retry_mode_stays_fail_closed() -> None:
    async def infer(_: dict[str, Any]) -> dict[str, object]:
        return _choice("UNREGISTERED", "DOMAIN_ACTION_A")

    t = DiagnosticStrategyChoiceTransport(infer, max_invalid_retries=0)
    with pytest.raises(StrategyModelOutputError):
        asyncio.run(t(_request()))
    assert t.model_calls == 1
    assert t.unrecovered_invalid_choices == 1


def test_transport_failure_is_not_retried() -> None:
    calls = 0

    async def infer(_: dict[str, Any]) -> dict[str, object]:
        nonlocal calls
        calls += 1
        raise TimeoutError("simulated")

    t = DiagnosticStrategyChoiceTransport(infer)
    with pytest.raises(TimeoutError):
        asyncio.run(t(_request()))
    assert calls == 1
    assert t.model_calls == 1


def test_invalid_candidate_surface_never_invokes_model() -> None:
    calls = 0

    async def infer(_: dict[str, Any]) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return _choice("DOMAIN_STRATEGY_A", "DOMAIN_ACTION_A")

    t = DiagnosticStrategyChoiceTransport(infer)
    with pytest.raises(ValueError, match="candidate"):
        asyncio.run(t({"legal_strategy_ids": [], "candidate_action_ids": []}))
    assert calls == 0
