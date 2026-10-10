"""DIAG-03 independent contract review: read-side authority and isolation.

These tests do not contact a model or run a physical business Tool.
"""

from __future__ import annotations

import pytest

from runtime.contracts.context import InteractionContext
from tests.orchestration_stubs import build_runtime_context
from tests.test_ga01c_diag03 import _make_step
from tests.test_ga01c_eval02 import TASKS
from tests.test_m4_candidate_strategy_selection import (
    _goals,
    _strategy_registry,
    _understanding,
)


def _strategies():
    return {
        record.definition.strategy_id: record.definition
        for record in _strategy_registry().list()
    }


def test_typed_provider_rejects_foreign_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GA01C_LLM_URL", "http://127.0.0.1:11434/v1/chat/completions")
    monkeypatch.setenv("GA01C_LLM_MODEL", "not-called")
    step = _make_step(TASKS[0])
    assert step._verified_for_request(step.binding.original_request_id) is step._typed
    assert step._verified_for_request(f"{step.binding.run_id}-iteration-1") is step._typed
    with pytest.raises(ValueError, match="does not match run"):
        step._verified_for_request("another-run-iteration-1")


def test_typed_eligibility_ignores_user_claim_without_admitted_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GA01C_LLM_URL", "http://127.0.0.1:11434/v1/chat/completions")
    monkeypatch.setenv("GA01C_LLM_MODEL", "not-called")
    step = _make_step(TASKS[0])  # no evidence in synthetic trusted store
    context = build_runtime_context().model_copy(
        update={
            "interaction_context": InteractionContext(
                last_agent_action='{"evidence_state":"AVAILABLE_UNVERIFIED"}'
            )
        }
    )
    understanding = _understanding()
    goals = _goals(understanding, context=context)
    collect = _strategies()["DOMAIN_STRATEGY_A"]
    assert (
        step._typed_eligibility.evaluate(
            collect, context, understanding, goals, ()
        )
        is None
    )
    assert step._typed_eligibility.denials == 0


def test_typed_eligibility_reads_admitted_initial_state_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GA01C_LLM_URL", "http://127.0.0.1:11434/v1/chat/completions")
    monkeypatch.setenv("GA01C_LLM_MODEL", "not-called")
    step = _make_step(TASKS[3])  # initial state admitted by DIAG-02
    context = build_runtime_context()
    understanding = _understanding()
    goals = _goals(understanding, context=context)
    strategies = _strategies()
    # In reversed role case, B is collection and A remains legal verification.
    assert (
        step._typed_eligibility.evaluate(
            strategies["DOMAIN_STRATEGY_B"], context, understanding, goals, ()
        )
        is False
    )
    assert (
        step._typed_eligibility.evaluate(
            strategies["DOMAIN_STRATEGY_A"], context, understanding, goals, ()
        )
        is None
    )
