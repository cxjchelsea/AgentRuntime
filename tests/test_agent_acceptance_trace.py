"""Passive acceptance tracing must observe, never alter, Agent decisions."""
from __future__ import annotations

import asyncio
from typing import cast
from unittest.mock import AsyncMock

from agent_core.iteration import IterationRef
from agent_core.runner import Decision, ObservedFact, StepPort
from examples.agent_acceptance_trace import AcceptanceTraceStep
from runtime.contracts import RuntimeInput


def test_trace_records_decision_observation_and_finish_without_reexecution() -> None:
    iteration = cast(IterationRef, object())
    initial = cast(RuntimeInput, object())
    action = Decision(iteration, "ACT", reason="approved")
    finished = Decision(iteration, "FINISH", reason="evidence verified")
    observation = ObservedFact(
        "run-1", "request-1", "plan-1", "execution-1",
        "fingerprint-1", ("SYNTHETIC_TEST_FACT",),
        workflow_step_id="step-1", tool_id="tool-1",
    )

    class SyntheticStep:
        def __init__(self) -> None:
            self.decide = AsyncMock(side_effect=[action, finished])
            self.execute_and_observe = AsyncMock(return_value=observation)

    original = SyntheticStep()
    tracing = AcceptanceTraceStep(cast(StepPort, original))

    async def exercise() -> None:
        assert await tracing.decide(initial, iteration, ()) is action
        assert await tracing.execute_and_observe(action) is observation
        assert await tracing.decide(initial, iteration, (observation,)) is finished

    asyncio.run(exercise())
    assert [event["type"] for event in tracing.events] == [
        "decision", "observation", "decision",
    ]
    assert tracing.events[2]["seen_observations"] == 1
    assert tracing.events[1]["workflow_step_id"] == "step-1"
    assert "SYNTHETIC_TEST_FACT" not in repr(tracing.events)
    assert original.execute_and_observe.await_count == 1
