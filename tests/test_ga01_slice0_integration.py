"""Slice-0 compatibility probe with *real* M1 Context and enhanced M2.

This is a legacy orchestrator integration probe, NOT an implementation of
AgentRunCoordinator and NOT production authorization.
"""

from __future__ import annotations

import asyncio

from agent_core.iteration import AgentRunBinding, IterationRef
from tests.orchestration_stubs import CallRecorder, build_runtime_input
from tests.test_m2_runtime_integration_gate import (
    StaticPrioritySubjectResolver,
    _build_orchestrator,
    _incoming,
)


def test_system_event_is_accepted_by_real_context_m3_m2_and_m4() -> None:
    async def scenario() -> None:
        initial = build_runtime_input(
            request_id="slice0-original",
            trace_id="slice0-trace",
            text="original goal remains outside tool message",
        )
        binding = AgentRunBinding.from_input(
            initial,
            run_id="slice0-run",
            domain_id="fixture-domain",
            domain_version="1.0",
            binding_fingerprint="fixture-binding",
        )
        next_input = binding.iteration_input(initial, ordinal=1)
        ref = IterationRef.from_input(binding, next_input, ordinal=1)
        recorder = CallRecorder()
        runtime, _ = await _build_orchestrator(
            next_input,
            recorder=recorder,
            resolver=StaticPrioritySubjectResolver(current=None, incoming=_incoming()),
        )
        # This full legacy pipeline is *only* an existing-M1..M4
        # compatibility probe; the future Loop must NOT call run() repeatedly.
        outcome = await runtime.run(next_input)
        assert outcome.trace.request_id == ref.request_id
        assert outcome.trace.trace_id == ref.trace_id
        assert "UNDERSTANDING" in recorder.entries
        assert "PLAN" in recorder.entries
        assert "EXECUTE" in recorder.entries

    asyncio.run(scenario())
