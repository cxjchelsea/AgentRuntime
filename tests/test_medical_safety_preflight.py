"""Medical safety must interrupt *before* knowledge, model, M4 and tools."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch
from typing import cast

import pytest

from agent_core.chat_transport import ChatCompletionsConfig
from agent_core.domain_extension import DomainExtensionError
from agent_core.domain_unified_application import (
    UnifiedDomainApplication,
    bootstrap_unified_domain_application,
)
from agent_core.medical_safety_application import (
    MedicalPreflightPolicy,
    MedicalSafetyApplication,
)
from agent_core.runner import LoopBudget, RunKind, RunOutcome, StepPort
from tests.orchestration_stubs import build_runtime_input
from tests.test_medical_domain_readonly_e2e import DOMAINS, _medical_package

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="secure package fixture is Linux-only"
)

RISK_PHRASES = {
    DOMAINS[0][0]: ("crushing chest pain right now", "现在胸痛呼吸困难"),
    DOMAINS[1][0]: ("i intend to kill myself tonight", "我现在要自杀"),
}


@pytest.mark.parametrize(("domain", "topic", "values"), DOMAINS)
def test_medical_high_risk_preflight_never_calls_knowledge_model_or_tools(
    tmp_path: Path, domain: str, topic: str, values: dict[str, int]
) -> None:
    del topic, values
    calls = []

    def retriever(scope, query, limit):
        del scope, query, limit
        calls.append("knowledge")
        raise AssertionError("knowledge must not run on high-risk task")

    snapshot = _medical_package(tmp_path / "package", domain, differentiated=True)
    config = ChatCompletionsConfig(
        endpoint="http://127.0.0.1:11434/v1/chat/completions",
        model="qwen2.5:3b",
    )
    unified = bootstrap_unified_domain_application(
        snapshot, retriever=retriever, query="blood pressure", model_config=config
    )
    policy = MedicalPreflightPolicy(
        domain_id=domain,
        binding_fingerprint=unified.app.extension.binding.binding_fingerprint,
        escalation_phrases=RISK_PHRASES[domain],
    )
    safety = MedicalSafetyApplication(unified, policy)

    class ForbiddenStep:
        async def decide(self, *args):
            del args
            calls.append("planning")
            raise AssertionError("planning must not run")

        async def execute_and_observe(self, *args):
            del args
            calls.append("tools")
            raise AssertionError("tool must not run")

    async def scenario():
        for phrase in RISK_PHRASES[domain]:
            outcome = await safety.run(
                build_runtime_input(text=phrase),
                run_id="medical-safety",
                step=ForbiddenStep(),
                budget=LoopBudget(),
            )
            assert outcome.kind is RunKind.BLOCK
            assert outcome.reason == "MEDICAL_HUMAN_REVIEW_REQUIRED"
            assert outcome.executions == 0
            assert outcome.iterations == 0
            assert outcome.observations == ()
        assert calls == []

    asyncio.run(scenario())


def test_medical_preflight_rejects_foreign_domain_policy(tmp_path: Path) -> None:
    domain = DOMAINS[0][0]
    snapshot = _medical_package(tmp_path / "package", domain)
    unified = bootstrap_unified_domain_application(
        snapshot,
        retriever=lambda scope, query, limit: (),
        query="blood pressure",
        model_config=ChatCompletionsConfig(
            endpoint="http://127.0.0.1:11434/v1/chat/completions",
            model="qwen2.5:3b",
        ),
    )
    foreign = MedicalPreflightPolicy(
        domain_id=DOMAINS[1][0],
        binding_fingerprint=unified.app.extension.binding.binding_fingerprint,
        escalation_phrases=RISK_PHRASES[DOMAINS[1][0]],
    )
    with pytest.raises(DomainExtensionError, match="binding mismatch"):
        MedicalSafetyApplication(unified, foreign)


@pytest.mark.parametrize(("domain", "topic", "values"), DOMAINS)
def test_direct_unified_medical_run_rejected_before_step(
    tmp_path: Path, domain: str, topic: str, values: dict[str, int]
) -> None:
    del topic, values
    snapshot = _medical_package(tmp_path / "direct", domain, differentiated=True)
    unified = bootstrap_unified_domain_application(
        snapshot,
        retriever=lambda scope, query, limit: (),
        query="blood pressure",
        model_config=ChatCompletionsConfig(
            endpoint="http://127.0.0.1:11434/v1/chat/completions",
            model="qwen2.5:3b",
        ),
    )

    async def scenario() -> None:
        with pytest.raises(DomainExtensionError, match="requires safety preflight"):
            await unified.run(
                build_runtime_input(text="routine synthetic request"),
                run_id="unguarded-medical",
                step=cast(StepPort, object()),
                budget=LoopBudget(),
            )

    asyncio.run(scenario())


@pytest.mark.parametrize(("domain", "topic", "values"), DOMAINS)
def test_medical_safety_entry_routes_routine_only_after_preflight(
    tmp_path: Path, domain: str, topic: str, values: dict[str, int]
) -> None:
    del topic, values
    snapshot = _medical_package(tmp_path / "joint", domain, differentiated=True)
    unified = bootstrap_unified_domain_application(
        snapshot,
        retriever=lambda scope, query, limit: (),
        query="blood pressure",
        model_config=ChatCompletionsConfig(
            endpoint="http://127.0.0.1:11434/v1/chat/completions",
            model="qwen2.5:3b",
        ),
    )
    safety = MedicalSafetyApplication(
        unified,
        MedicalPreflightPolicy(
            domain,
            unified.app.extension.binding.binding_fingerprint,
            RISK_PHRASES[domain],
        ),
    )
    calls: list[str] = []

    async def checked_execution(self, initial, *, run_id, step, budget):
        del self, step, budget
        calls.append(initial.text)
        return RunOutcome(run_id, RunKind.WAIT, "ROUTED_TO_CHECKED_AGENT", 1, 0, ())

    async def scenario() -> None:
        with patch.object(UnifiedDomainApplication, "_run_checked", checked_execution):
            routine = await safety.run(
                build_runtime_input(text="routine synthetic checkin"),
                run_id="safe",
                step=cast(StepPort, object()),
                budget=LoopBudget(),
            )
            assert routine.reason == "ROUTED_TO_CHECKED_AGENT"
            for phrase in RISK_PHRASES[domain]:
                blocked = await safety.run(
                    build_runtime_input(text=phrase),
                    run_id="high-risk",
                    step=cast(StepPort, object()),
                    budget=LoopBudget(),
                )
                assert blocked.kind is RunKind.BLOCK
                assert blocked.reason == "MEDICAL_HUMAN_REVIEW_REQUIRED"
                assert blocked.executions == 0
            missing = await safety.run(
                build_runtime_input(text=None),
                run_id="missing",
                step=cast(StepPort, object()),
                budget=LoopBudget(),
            )
            assert missing.reason == "MEDICAL_SAFETY_INPUT_UNAVAILABLE"
        assert calls == ["routine synthetic checkin"]

    asyncio.run(scenario())
