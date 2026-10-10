"""Real local model inference smoke. No cloud API, no fake model output.

Requires Ollama qwen2.5:0.5b running on local HTTP endpoint.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from agent_core.chat_transport import ChatCompletionsConfig, ChatCompletionsStrategyTransport
from agent_core.model_adapter import StructuredStrategyTransportAdapter
from runtime.planning import HybridStrategySelector, StrategyModelOutputError
from tests.test_ga01_slice2 import _run_soft_selection


@pytest.mark.skipif(
    os.environ.get("GA01C_LLM_URL") is None,
    reason="actual local model server not configured",
)
def test_local_qwen_real_generation_not_a_mock() -> None:
    config = ChatCompletionsConfig(
        endpoint=os.environ["GA01C_LLM_URL"],
        model=os.environ.get("GA01C_LLM_MODEL", "qwen2.5:0.5b"),
        timeout_seconds=45,
        max_tokens=192,
    )
    transport = ChatCompletionsStrategyTransport(config)
    # Unlike existing tests, there is NO injected fake HTTP sender.
    # Qwen's weights must actually generate structured model content.
    model = StructuredStrategyTransportAdapter(transport)
    result = asyncio.run(_run_soft_selection(model))
    assert result.selection_path == "MODEL"
    assert result.selected_action_ids == ("DOMAIN_ACTION_A",)
