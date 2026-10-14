"""GA-20 interactive sandbox input boundaries; live inference is opt-in CI."""

from __future__ import annotations

import pytest

from examples.ga20_sandbox_cli import DEFAULT_QUESTIONS, OPERATIONS, validated_question


@pytest.mark.parametrize("domain", ["inventory", "learning"])
def test_valid_demo_scope(domain: str) -> None:
    assert (
        validated_question(domain, DEFAULT_QUESTIONS[domain])
        == DEFAULT_QUESTIONS[domain]
    )
    assert domain in OPERATIONS


@pytest.mark.parametrize(
    ("domain", "question"),
    [
        ("inventory", "帮我发送真实采购订单"),
        ("learning", "帮我给学生打分"),
        ("inventory", ""),
        ("inventory", "x" * 1001),
        ("unknown", "库存"),
    ],
)
def test_out_of_scope_fails_closed(domain: str, question: str) -> None:
    with pytest.raises(ValueError):
        validated_question(domain, question)
