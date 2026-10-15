"""Medical sandbox StepPort must not execute without an armed trusted gate."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from agent_core.domain_extension import DomainExtensionError
from agent_core.medical_tool_execution_gate import MedicalAuthorizedStep
from agent_core.runner import Decision


def test_medical_physical_step_rejects_bypass_before_tool() -> None:
    delegate = AsyncMock()
    untrusted = MedicalAuthorizedStep(delegate)

    async def scenario() -> None:
        with pytest.raises(DomainExtensionError, match="not authorized"):
            await untrusted.execute_and_observe(Decision.__new__(Decision))
        delegate.execute_and_observe.assert_not_awaited()

    asyncio.run(scenario())
