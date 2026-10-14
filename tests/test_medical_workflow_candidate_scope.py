"""Fail-closed workflow candidate scoping for the unified medical application."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from agent_core.domain_application import bootstrap_domain_application
from agent_core.domain_extension import DomainExtensionError
from agent_core.domain_unified_application import _WorkflowScopedModelTransport
from agent_core.knowledge_model_transport import KnowledgeBackedStrategyTransport
from tests.test_medical_domain_readonly_e2e import DOMAINS, _medical_package

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="secure package fixture is Linux-only"
)


@pytest.mark.parametrize(("domain_id", "topic", "values"), DOMAINS)
def test_medical_workflow_candidates_are_scoped_and_model_is_not_rewritten(
    tmp_path: Path, domain_id: str, topic: str, values: dict[str, int]
) -> None:
    del topic, values

    async def scenario() -> None:
        snapshot = _medical_package(tmp_path / "package", domain_id)
        app = bootstrap_domain_application(snapshot)
        catalog = app.execution_catalog(snapshot)
        actions = {
            action: strategy for strategy, action in app.extension.strategy_actions
        }
        calls: list[dict[str, Any]] = []

        class Model:
            async def __call__(self, payload: dict[str, Any]) -> dict[str, object]:
                calls.append(payload)
                return {
                    "strategy_id": payload["legal_strategy_ids"][0],
                    "action_ids": payload["candidate_action_ids"],
                    "reason_code": "SCOPED_CANDIDATE",
                }

        model = Model()
        scoped = _WorkflowScopedModelTransport(
            cast(KnowledgeBackedStrategyTransport, model), catalog, actions
        )
        all_actions = [step.action_id for step in catalog.workflow.steps]
        legal = [actions[action] for action in all_actions]
        payload: dict[str, Any] = {
            "candidate_action_ids": all_actions,
            "legal_strategy_ids": legal,
            "last_agent_action": None,
        }

        first = await scoped(payload)
        assert first["action_ids"] == [all_actions[0]]
        assert calls[-1]["required_workflow_step"] == catalog.workflow.steps[0].step_id
        assert payload["candidate_action_ids"] == all_actions

        second = dict(
            payload, last_agent_action=catalog.workflow.steps[0].completion_fact
        )
        result = await scoped(second)
        assert result["action_ids"] == [all_actions[1]]
        assert calls[-1]["required_workflow_step"] == catalog.workflow.steps[1].step_id

        with pytest.raises(
            DomainExtensionError, match="ambiguous workflow observation"
        ):
            await scoped(dict(payload, last_agent_action="FOREIGN_FACT"))
        with pytest.raises(DomainExtensionError, match="not legally available"):
            await scoped(dict(payload, candidate_action_ids=[all_actions[1]]))
        assert len(calls) == 2

        class InvalidModel:
            async def __call__(self, request: dict[str, Any]) -> dict[str, object]:
                del request
                return {
                    "strategy_id": legal[1],
                    "action_ids": [all_actions[1]],
                    "reason_code": "INVALID_EARLY_ACTION",
                }

        rejecting = _WorkflowScopedModelTransport(
            cast(KnowledgeBackedStrategyTransport, InvalidModel()), catalog, actions
        )
        with pytest.raises(DomainExtensionError, match="model selection violates"):
            await rejecting(payload)

    asyncio.run(scenario())
