"""Medical completion rules must agree with the bound workflow before model use."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agent_core.chat_transport import ChatCompletionsConfig
from agent_core.domain_extension import DomainExtensionError
from agent_core.domain_unified_application import bootstrap_unified_domain_application
from tests.test_medical_domain_readonly_e2e import DOMAINS, _medical_package

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="secure package fixture is Linux-only"
)


@pytest.mark.parametrize(("domain_id", "topic", "values"), DOMAINS)
@pytest.mark.parametrize("differentiated", [False, True])
def test_medical_completion_rule_matches_signed_workflow(
    tmp_path: Path,
    domain_id: str,
    topic: str,
    values: dict[str, int],
    differentiated: bool,
) -> None:
    del topic, values
    snapshot = _medical_package(
        tmp_path / "valid", domain_id, differentiated=differentiated
    )
    config = ChatCompletionsConfig(
        endpoint="http://127.0.0.1:11434/v1/chat/completions",
        model="qwen2.5:3b",
    )

    def retrieve(scope, query, limit):
        del scope, query, limit
        return ()

    query = "blood pressure" if domain_id == DOMAINS[0][0] else "mood sleep"
    app = bootstrap_unified_domain_application(
        snapshot, retriever=retrieve, query=query, model_config=config
    )
    assert app.execution_catalog is not None
    expected = "collect" if len(app.execution_catalog.workflow.steps) == 1 else "verify"
    assert app.content.completion_after == expected

    invalid = _medical_package(
        tmp_path / "invalid",
        domain_id,
        differentiated=differentiated,
        completion_override="verify" if expected == "collect" else "collect",
    )
    with pytest.raises(DomainExtensionError, match="completion rule/workflow mismatch"):
        bootstrap_unified_domain_application(
            invalid, retriever=retrieve, query=query, model_config=config
        )
